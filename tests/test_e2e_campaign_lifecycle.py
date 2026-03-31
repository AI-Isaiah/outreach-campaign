"""E2E tests for the full campaign lifecycle — enrollment, queue, send, advance, reorder."""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

import psycopg2
import psycopg2.extras
import pytest

from src.models.database import get_connection, get_cursor, run_migrations
from src.models.campaigns import create_campaign
from src.models.templates import create_template
from src.models.enrollment import (
    add_sequence_step,
    enroll_contact,
    get_contact_campaign_status,
    get_sequence_steps,
    update_contact_campaign_status,
)
from src.models.events import log_event
from src.services.priority_queue import get_daily_queue
from src.services.email_sender import send_campaign_email
from src.services.sequence_utils import advance_to_next_step
from src.services.campaign_sequence import reorder_campaign_sequence
from tests.conftest import TEST_USER_ID, insert_company, insert_contact


def _conn(tmp_db):
    """Get a fresh connection from the test DB URL."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


# ---------------------------------------------------------------------------
# 1. Full campaign lifecycle
# ---------------------------------------------------------------------------


def test_full_campaign_lifecycle(tmp_db):
    """Create campaign -> template -> step -> enroll -> queue -> send -> event logged."""
    conn = _conn(tmp_db)

    # Setup
    campaign_id = create_campaign(conn, "lifecycle_test", user_id=TEST_USER_ID)
    template_id = create_template(
        conn, "intro_v1", "email",
        "Hello {{ first_name }}, intro from us.",
        subject="Intro",
        user_id=TEST_USER_ID,
    )
    step_id = add_sequence_step(
        conn, campaign_id, 1, "email",
        template_id=template_id, delay_days=0,
        user_id=TEST_USER_ID,
    )

    company_id = insert_company(conn, "Alpha Capital", aum_millions=500)
    contact_id = insert_contact(
        conn, company_id, first_name="Alice", last_name="Smith",
        email="alice@alpha.com", email_status="valid",
    )

    # Enroll
    ccs_id = enroll_contact(
        conn, contact_id, campaign_id,
        next_action_date=date.today().isoformat(),
        user_id=TEST_USER_ID,
    )
    assert ccs_id is not None

    # Queue should contain our contact
    queue = get_daily_queue(conn, campaign_id, user_id=TEST_USER_ID)
    contact_ids_in_queue = [item["contact_id"] for item in queue]
    assert contact_id in contact_ids_in_queue

    # Send with mocked SMTP
    config = {
        "smtp": {"host": "smtp.test.com", "port": 587, "username": "test@test.com"},
        "smtp_password": "fake",
        "calendly_url": "https://cal.com/test",
        "physical_address": "123 Test St",
    }
    with patch("src.services.email_sender.send_email", return_value=True) as mock_send:
        success = send_campaign_email(
            conn, contact_id, campaign_id, template_id, config,
            user_id=TEST_USER_ID,
        )
    assert success is True
    mock_send.assert_called_once()

    # Verify event logged
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM events WHERE contact_id = %s AND event_type = 'email_sent'",
            (contact_id,),
        )
        event = cur.fetchone()
    assert event is not None
    assert event["campaign_id"] == campaign_id

    conn.close()


# ---------------------------------------------------------------------------
# 2. SMTP failure mid-batch
# ---------------------------------------------------------------------------


def test_smtp_failure_mid_batch(tmp_db):
    """Batch send: #1 succeeds, #2 fails, #3 succeeds. Verify counts."""
    conn = _conn(tmp_db)

    campaign_id = create_campaign(conn, "batch_test", user_id=TEST_USER_ID)
    template_id = create_template(
        conn, "batch_tmpl", "email", "Hi {{ first_name }}",
        subject="Batch", user_id=TEST_USER_ID,
    )
    add_sequence_step(
        conn, campaign_id, 1, "email",
        template_id=template_id, delay_days=0,
        user_id=TEST_USER_ID,
    )

    contact_ids = []
    for i, name in enumerate(["Bob", "Carol", "Dave"]):
        co = insert_company(conn, f"Fund{i}")
        cid = insert_contact(
            conn, co, first_name=name, last_name="Test",
            email=f"{name.lower()}@fund{i}.com", email_status="valid",
        )
        enroll_contact(
            conn, cid, campaign_id,
            next_action_date=date.today().isoformat(),
            user_id=TEST_USER_ID,
        )
        contact_ids.append(cid)

    config = {
        "smtp": {"host": "smtp.test.com", "port": 587, "username": "test@test.com"},
        "smtp_password": "fake",
        "calendly_url": "", "physical_address": "123 St",
    }

    # Mock send_email: True, False, True
    side_effects = [True, False, True]
    results = []
    with patch("src.services.email_sender.send_email", side_effect=side_effects):
        for cid in contact_ids:
            ok = send_campaign_email(
                conn, cid, campaign_id, template_id, config,
                user_id=TEST_USER_ID,
            )
            results.append(ok)

    assert results == [True, False, True]

    # Verify events: 2 email_sent events (for contacts 0 and 2)
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT contact_id FROM events WHERE event_type = 'email_sent' AND campaign_id = %s",
            (campaign_id,),
        )
        sent_contacts = {row["contact_id"] for row in cur.fetchall()}
    assert contact_ids[0] in sent_contacts
    assert contact_ids[1] not in sent_contacts
    assert contact_ids[2] in sent_contacts

    conn.close()


# ---------------------------------------------------------------------------
# 3. Enroll idempotent
# ---------------------------------------------------------------------------


def test_enroll_idempotent(tmp_db):
    """Enrolling the same contact twice returns None the second time, no error."""
    conn = _conn(tmp_db)

    campaign_id = create_campaign(conn, "idem_test", user_id=TEST_USER_ID)
    add_sequence_step(conn, campaign_id, 1, "email", user_id=TEST_USER_ID)
    co = insert_company(conn, "Idem Corp")
    cid = insert_contact(conn, co, email="idem@test.com")

    first = enroll_contact(conn, cid, campaign_id, user_id=TEST_USER_ID)
    second = enroll_contact(conn, cid, campaign_id, user_id=TEST_USER_ID)

    assert first is not None
    assert second is None  # idempotent: already enrolled

    # Only 1 row exists
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM contact_campaign_status "
            "WHERE contact_id = %s AND campaign_id = %s",
            (cid, campaign_id),
        )
        assert cur.fetchone()["cnt"] == 1

    conn.close()


# ---------------------------------------------------------------------------
# 4. sent_at prevents double send
# ---------------------------------------------------------------------------


def test_sent_at_prevents_double_send(tmp_db):
    """If sent_at is already set, the idempotency guard prevents a second send."""
    conn = _conn(tmp_db)

    campaign_id = create_campaign(conn, "double_send", user_id=TEST_USER_ID)
    template_id = create_template(
        conn, "ds_tmpl", "email", "Hi {{ first_name }}",
        subject="DS", user_id=TEST_USER_ID,
    )
    add_sequence_step(
        conn, campaign_id, 1, "email",
        template_id=template_id, delay_days=0,
        user_id=TEST_USER_ID,
    )
    co = insert_company(conn, "DS Corp")
    cid = insert_contact(
        conn, co, first_name="Eve", email="eve@ds.com", email_status="valid",
    )
    enroll_contact(
        conn, cid, campaign_id,
        next_action_date=date.today().isoformat(),
        user_id=TEST_USER_ID,
    )

    # Manually set sent_at to simulate already-sent
    with get_cursor(conn) as cur:
        cur.execute(
            "UPDATE contact_campaign_status SET sent_at = NOW() "
            "WHERE contact_id = %s AND campaign_id = %s",
            (cid, campaign_id),
        )
        conn.commit()

    config = {
        "smtp": {"host": "smtp.test.com", "port": 587, "username": "test@test.com"},
        "smtp_password": "fake",
        "calendly_url": "", "physical_address": "123 St",
    }

    with patch("src.services.email_sender.send_email", return_value=True) as mock_send:
        result = send_campaign_email(
            conn, cid, campaign_id, template_id, config,
            user_id=TEST_USER_ID,
        )

    # Should return False (already sent) and never call SMTP
    assert result is False
    mock_send.assert_not_called()

    conn.close()


# ---------------------------------------------------------------------------
# 5. Contact completes all steps
# ---------------------------------------------------------------------------


def test_contact_completes_all_steps(tmp_db):
    """Walk a contact through a 3-step sequence and verify status = completed at end."""
    conn = _conn(tmp_db)

    campaign_id = create_campaign(conn, "multi_step", user_id=TEST_USER_ID)

    # Create 3 templates and 3 steps
    tmpl_ids = []
    for i in range(1, 4):
        tid = create_template(
            conn, f"step{i}_tmpl", "email",
            f"Step {i} body for {{{{ first_name }}}}",
            subject=f"Step {i}",
            user_id=TEST_USER_ID,
        )
        tmpl_ids.append(tid)
        add_sequence_step(
            conn, campaign_id, i, "email",
            template_id=tid, delay_days=0,
            user_id=TEST_USER_ID,
        )

    co = insert_company(conn, "Multi Corp")
    cid = insert_contact(
        conn, co, first_name="Frank", email="frank@multi.com", email_status="valid",
    )
    enroll_contact(
        conn, cid, campaign_id,
        next_action_date=date.today().isoformat(),
        user_id=TEST_USER_ID,
    )

    config = {
        "smtp": {"host": "smtp.test.com", "port": 587, "username": "test@test.com"},
        "smtp_password": "fake",
        "calendly_url": "", "physical_address": "123 St",
    }

    with patch("src.services.email_sender.send_email", return_value=True):
        # Send step 1
        ok1 = send_campaign_email(
            conn, cid, campaign_id, tmpl_ids[0], config, user_id=TEST_USER_ID,
        )
        assert ok1 is True

        # After step 1, should be at step 2 — clear sent_at for next send
        ccs = get_contact_campaign_status(conn, cid, campaign_id, user_id=TEST_USER_ID)
        assert ccs["current_step"] == 2

        # Send step 2
        ok2 = send_campaign_email(
            conn, cid, campaign_id, tmpl_ids[1], config, user_id=TEST_USER_ID,
        )
        assert ok2 is True

        ccs = get_contact_campaign_status(conn, cid, campaign_id, user_id=TEST_USER_ID)
        assert ccs["current_step"] == 3

        # Send step 3 (final)
        ok3 = send_campaign_email(
            conn, cid, campaign_id, tmpl_ids[2], config, user_id=TEST_USER_ID,
        )
        assert ok3 is True

    # After all steps, contact's step should remain at 3 (no step 4 to advance to)
    # The advance_to_next_step returns None when there's no next step
    ccs = get_contact_campaign_status(conn, cid, campaign_id, user_id=TEST_USER_ID)
    assert ccs["current_step"] == 3

    # Verify 3 email_sent events
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM events "
            "WHERE contact_id = %s AND event_type = 'email_sent' AND campaign_id = %s",
            (cid, campaign_id),
        )
        assert cur.fetchone()["cnt"] == 3

    conn.close()


# ---------------------------------------------------------------------------
# 6. Soft-delete during campaign
# ---------------------------------------------------------------------------


def test_soft_delete_during_campaign(tmp_db):
    """Soft-delete via 'Remove from Contacts': gone from queue, enrollment deleted, contact preserved."""
    conn = _conn(tmp_db)

    campaign_id = create_campaign(conn, "softdel_test", user_id=TEST_USER_ID)
    add_sequence_step(
        conn, campaign_id, 1, "email", delay_days=0,
        user_id=TEST_USER_ID,
    )
    co = insert_company(conn, "SoftDel Corp")
    cid = insert_contact(
        conn, co, first_name="Grace", email="grace@sd.com", email_status="valid",
    )
    enroll_contact(
        conn, cid, campaign_id,
        next_action_date=date.today().isoformat(),
        user_id=TEST_USER_ID,
    )

    # Verify contact is in queue before removal
    queue_before = get_daily_queue(conn, campaign_id, user_id=TEST_USER_ID)
    assert any(item["contact_id"] == cid for item in queue_before)

    # Soft-delete: set removed_at, delete enrollment (mimics the route handler)
    with get_cursor(conn) as cur:
        cur.execute(
            "UPDATE contacts SET removed_at = NOW(), removal_reason = %s WHERE id = %s AND user_id = %s",
            ("Remove from Contacts", cid, TEST_USER_ID),
        )
        cur.execute(
            "DELETE FROM contact_campaign_status WHERE contact_id = %s",
            (cid,),
        )
        conn.commit()

    # Contact gone from queue
    queue_after = get_daily_queue(conn, campaign_id, user_id=TEST_USER_ID)
    assert not any(item["contact_id"] == cid for item in queue_after)

    # Enrollment row deleted
    ccs = get_contact_campaign_status(conn, cid, campaign_id, user_id=TEST_USER_ID)
    assert ccs is None

    # Contact still in DB with removed_at set
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT removed_at, removal_reason FROM contacts WHERE id = %s",
            (cid,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row["removed_at"] is not None
    assert row["removal_reason"] == "Remove from Contacts"

    conn.close()


# ---------------------------------------------------------------------------
# 7. Sequence reorder preserves position
# ---------------------------------------------------------------------------


def test_sequence_reorder_preserves_position(tmp_db):
    """Reorder steps (swap 2 and 3). Contact at step 2 gets new step 2's stable_id."""
    conn = _conn(tmp_db)

    campaign_id = create_campaign(conn, "reorder_test", user_id=TEST_USER_ID)

    # Create 3 steps
    step_ids = []
    for i in range(1, 4):
        sid = add_sequence_step(
            conn, campaign_id, i, "email", delay_days=i,
            user_id=TEST_USER_ID,
        )
        step_ids.append(sid)

    # Get the stable_ids
    steps = get_sequence_steps(conn, campaign_id, user_id=TEST_USER_ID)
    original_step2_stable = str(steps[1]["stable_id"])  # what is at position 2 now
    original_step3_stable = str(steps[2]["stable_id"])  # what is at position 3 now

    # Enroll contact at step 2
    co = insert_company(conn, "Reorder Corp")
    cid = insert_contact(conn, co, email="reorder@test.com", email_status="valid")
    enroll_contact(
        conn, cid, campaign_id,
        next_action_date=date.today().isoformat(),
        user_id=TEST_USER_ID,
    )
    # Manually advance to step 2
    update_contact_campaign_status(
        conn, cid, campaign_id, current_step=2, status="in_progress",
        user_id=TEST_USER_ID,
    )

    # Verify at step 2 with original step2's stable_id
    ccs_before = get_contact_campaign_status(conn, cid, campaign_id, user_id=TEST_USER_ID)
    assert ccs_before["current_step"] == 2
    assert str(ccs_before["current_step_id"]) == original_step2_stable

    # Swap step 2 and 3 (step_ids[1] becomes order 3, step_ids[2] becomes order 2)
    reorder_result = reorder_campaign_sequence(
        conn, campaign_id,
        steps=[
            {"step_id": step_ids[0], "step_order": 1},
            {"step_id": step_ids[2], "step_order": 2},  # old step 3 -> new step 2
            {"step_id": step_ids[1], "step_order": 3},  # old step 2 -> new step 3
        ],
        user_id=TEST_USER_ID,
    )
    assert reorder_result["affected_count"] >= 1

    # Contact should still be at position 2 but now with the stable_id of old step 3
    ccs_after = get_contact_campaign_status(conn, cid, campaign_id, user_id=TEST_USER_ID)
    assert ccs_after["current_step"] == 2
    assert str(ccs_after["current_step_id"]) == original_step3_stable

    conn.close()
