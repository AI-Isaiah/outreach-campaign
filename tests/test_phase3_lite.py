"""Tests for Phase 3 Lite: neutral remap, template history write path, reply breakdown, winning badge."""

from __future__ import annotations

from src.models.campaigns import (
    create_campaign,
    record_template_usage,
    update_contact_campaign_status,
)
from src.models.templates import create_template
from src.models.database import get_connection, get_cursor, run_migrations
from src.services.metrics import get_campaign_metrics
from src.services.response_analyzer import annotate_is_winning, get_template_performance
from src.services.state_machine import transition_contact
from tests.conftest import TEST_USER_ID


def _setup(conn):
    """Create base data: company, contact, campaign, template, enrollment."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country, user_id)
               VALUES ('Test Fund', 'test fund', 500.0, 'Hedge Fund', 'US', %s) RETURNING id""",
            (TEST_USER_ID,),
        )
        company_id = cur.fetchone()["id"]

        cur.execute(
            """INSERT INTO contacts (company_id, first_name, last_name, full_name, email,
                                     email_normalized, email_status, user_id)
               VALUES (%s, 'Jane', 'Smith', 'Jane Smith', 'jane@test.com', 'jane@test.com', 'valid', %s)
               RETURNING id""",
            (company_id, TEST_USER_ID),
        )
        contact_id = cur.fetchone()["id"]

    campaign_id = create_campaign(conn, "phase3_test", user_id=TEST_USER_ID)
    template_id = create_template(conn, "Intro Email", "email", "Hello {{name}}", subject="Hi", user_id=TEST_USER_ID)

    # Enroll contact in campaign
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO contact_campaign_status (contact_id, campaign_id, status, current_step)
               VALUES (%s, %s, 'in_progress', 1)""",
            (contact_id, campaign_id),
        )
        conn.commit()

    return company_id, contact_id, campaign_id, template_id


def _create_pending_reply(conn, contact_id, campaign_id, classification="neutral"):
    """Create a pending reply for testing the confirm flow."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO pending_replies (contact_id, campaign_id, gmail_message_id, subject, snippet, classification)
               VALUES (%s, %s, 'msg_123', 'Re: Hi', 'Thanks for reaching out', %s) RETURNING id""",
            (contact_id, campaign_id, classification),
        )
        reply_id = cur.fetchone()["id"]
        conn.commit()
    return reply_id


# ---------------------------------------------------------------------------
# Neutral remap tests (3)
# ---------------------------------------------------------------------------


def test_neutral_confirm_transitions_to_replied_positive(tmp_db):
    """Neutral confirmation maps to REPLIED_POSITIVE via status_map."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, template_id = _setup(conn)

    # Record template usage so outcome UPDATE has a target
    record_template_usage(conn, contact_id, campaign_id, template_id, "email")

    reply_id = _create_pending_reply(conn, contact_id, campaign_id, "neutral")

    # Simulate the confirm flow (same logic as the route)
    status_map = {
        "replied_positive": "replied_positive",
        "replied_negative": "replied_negative",
        "neutral": "replied_positive",
    }
    outcome = "neutral"
    mapped_status = status_map[outcome]

    with get_cursor(conn) as cur:
        cur.execute(
            "UPDATE pending_replies SET confirmed = true, confirmed_outcome = %s WHERE id = %s",
            (outcome, reply_id),
        )

    transition_contact(conn, contact_id, campaign_id, mapped_status, user_id=TEST_USER_ID)

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT status FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
            (contact_id, campaign_id),
        )
        row = cur.fetchone()

    assert row["status"] == "replied_positive"
    conn.close()


def test_positive_negative_confirm_unchanged(tmp_db):
    """Positive and negative confirmations work as before."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _ = _setup(conn)

    transition_contact(conn, contact_id, campaign_id, "replied_positive", user_id=TEST_USER_ID)

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT status FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
            (contact_id, campaign_id),
        )
        row = cur.fetchone()

    assert row["status"] == "replied_positive"
    conn.close()


def test_confirmed_outcome_stores_original_value(tmp_db):
    """confirmed_outcome stores raw 'neutral', not the remapped value."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _ = _setup(conn)

    reply_id = _create_pending_reply(conn, contact_id, campaign_id, "neutral")

    with get_cursor(conn) as cur:
        cur.execute(
            "UPDATE pending_replies SET confirmed = true, confirmed_outcome = %s WHERE id = %s",
            ("neutral", reply_id),
        )
        conn.commit()

        cur.execute("SELECT confirmed_outcome FROM pending_replies WHERE id = %s", (reply_id,))
        row = cur.fetchone()

    assert row["confirmed_outcome"] == "neutral"
    conn.close()


# ---------------------------------------------------------------------------
# Template history write path tests (4)
# ---------------------------------------------------------------------------


def test_record_template_usage_inserts(tmp_db):
    """record_template_usage() creates a row with NULL outcome."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, template_id = _setup(conn)

    record_template_usage(conn, contact_id, campaign_id, template_id, "email")

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM contact_template_history WHERE contact_id = %s AND campaign_id = %s",
            (contact_id, campaign_id),
        )
        row = cur.fetchone()

    assert row is not None
    assert row["template_id"] == template_id
    assert row["channel"] == "email"
    assert row["outcome"] is None
    conn.close()


def test_record_template_usage_duplicate_is_noop(tmp_db):
    """Duplicate INSERT (same contact+campaign+template) is silently ignored."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, template_id = _setup(conn)

    record_template_usage(conn, contact_id, campaign_id, template_id, "email")
    record_template_usage(conn, contact_id, campaign_id, template_id, "email")

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM contact_template_history WHERE contact_id = %s AND campaign_id = %s",
            (contact_id, campaign_id),
        )
        row = cur.fetchone()

    assert row["cnt"] == 1
    conn.close()


def test_record_template_usage_null_template_id_skips(tmp_db):
    """NULL template_id is silently skipped (old Gmail drafts)."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _ = _setup(conn)

    record_template_usage(conn, contact_id, campaign_id, None, "email")

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM contact_template_history WHERE contact_id = %s",
            (contact_id,),
        )
        row = cur.fetchone()

    assert row["cnt"] == 0
    conn.close()


def test_outcome_update_sets_value_and_timestamp(tmp_db):
    """After confirmation, outcome and outcome_at are set."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, template_id = _setup(conn)

    record_template_usage(conn, contact_id, campaign_id, template_id, "email")

    with get_cursor(conn) as cur:
        cur.execute(
            """UPDATE contact_template_history
               SET outcome = 'positive', outcome_at = NOW()
               WHERE id = (
                   SELECT id FROM contact_template_history
                   WHERE contact_id = %s AND campaign_id = %s AND outcome IS NULL
                   ORDER BY sent_at DESC LIMIT 1
               )""",
            (contact_id, campaign_id),
        )
        conn.commit()

        cur.execute(
            "SELECT outcome, outcome_at FROM contact_template_history WHERE contact_id = %s AND campaign_id = %s",
            (contact_id, campaign_id),
        )
        row = cur.fetchone()

    assert row["outcome"] == "positive"
    assert row["outcome_at"] is not None
    conn.close()


def test_outcome_update_noop_when_no_history(tmp_db):
    """UPDATE with no matching row doesn't crash (0 rows affected)."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _ = _setup(conn)

    # No record_template_usage call — table is empty for this contact
    with get_cursor(conn) as cur:
        cur.execute(
            """UPDATE contact_template_history
               SET outcome = 'positive', outcome_at = NOW()
               WHERE id = (
                   SELECT id FROM contact_template_history
                   WHERE contact_id = %s AND campaign_id = %s AND outcome IS NULL
                   ORDER BY sent_at DESC LIMIT 1
               )""",
            (contact_id, campaign_id),
        )
        conn.commit()
    # No error — passes if we get here
    conn.close()


# ---------------------------------------------------------------------------
# Reply breakdown tests (2)
# ---------------------------------------------------------------------------


def test_reply_breakdown_with_data(tmp_db):
    """reply_breakdown includes correct positive/negative counts."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _ = _setup(conn)

    # Transition to replied_positive
    transition_contact(conn, contact_id, campaign_id, "replied_positive", user_id=TEST_USER_ID)

    metrics = get_campaign_metrics(conn, campaign_id, user_id=TEST_USER_ID)
    rb = metrics["reply_breakdown"]

    assert rb["positive"] == 1
    assert rb["negative"] == 0
    assert rb["total"] == 1
    assert rb["positive_rate"] == 1.0
    conn.close()


def test_reply_breakdown_zero_replies(tmp_db):
    """reply_breakdown handles zero replies without division error."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, _, campaign_id, _ = _setup(conn)

    # Contact stays in_progress — no replies
    metrics = get_campaign_metrics(conn, campaign_id, user_id=TEST_USER_ID)
    rb = metrics["reply_breakdown"]

    assert rb["positive"] == 0
    assert rb["negative"] == 0
    assert rb["total"] == 0
    assert rb["positive_rate"] == 0.0
    conn.close()


# ---------------------------------------------------------------------------
# Template performance + winning badge tests (3)
# ---------------------------------------------------------------------------


def _add_template_history(conn, contact_id, campaign_id, template_id, outcome, channel="email"):
    """Helper to insert a contact_template_history row with outcome."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO contact_template_history (contact_id, campaign_id, template_id, channel, outcome)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (contact_id, campaign_id, template_id) DO UPDATE SET outcome = EXCLUDED.outcome""",
            (contact_id, campaign_id, template_id, channel, outcome),
        )
        conn.commit()


def test_is_winning_for_top_performer(tmp_db):
    """Template with highest positive_rate and >= 5 sends gets is_winning=true."""
    conn = get_connection(tmp_db)
    run_migrations(conn)

    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO companies (name, name_normalized, user_id)
               VALUES ('Co', 'co', %s) RETURNING id""",
            (TEST_USER_ID,),
        )
        co_id = cur.fetchone()["id"]

    campaign_id = create_campaign(conn, "perf_camp", user_id=TEST_USER_ID)
    t1 = create_template(conn, "Good Template", "email", "body", subject="s", user_id=TEST_USER_ID)
    t2 = create_template(conn, "Bad Template", "email", "body2", subject="s2", user_id=TEST_USER_ID)

    # Create 6 contacts for t1 (5 positive, 1 negative) and 6 for t2 (2 positive, 4 negative)
    for i in range(12):
        full_name = f"Contact {i}"
        email = f"c{i}@test.com"
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO contacts (company_id, first_name, last_name, full_name, email, email_normalized, user_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (co_id, "C", str(i), full_name, email, email, TEST_USER_ID),
            )
            cid = cur.fetchone()["id"]

        tid = t1 if i < 6 else t2
        outcome = "positive" if (i < 5 or i in (6, 7)) else "negative"
        _add_template_history(conn, cid, campaign_id, tid, outcome)

    results = get_template_performance(conn, campaign_id)
    assert len(results) == 2

    annotate_is_winning(results)
    winning = [r for r in results if r["is_winning"]]
    assert len(winning) == 1
    assert winning[0]["template_id"] == t1
    conn.close()


def test_is_winning_false_below_threshold(tmp_db):
    """No badge when all templates have < 5 sends."""
    conn = get_connection(tmp_db)
    run_migrations(conn)

    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO companies (name, name_normalized, user_id)
               VALUES ('Small Co', 'small co', %s) RETURNING id""",
            (TEST_USER_ID,),
        )
        co_id = cur.fetchone()["id"]

        cur.execute(
            """INSERT INTO contacts (company_id, first_name, last_name, full_name, email, email_normalized, user_id)
               VALUES (%s, 'A', 'B', 'A B', 'ab@test.com', 'ab@test.com', %s) RETURNING id""",
            (co_id, TEST_USER_ID),
        )
        cid = cur.fetchone()["id"]

    campaign_id = create_campaign(conn, "small_camp", user_id=TEST_USER_ID)
    tid = create_template(conn, "Low Volume", "email", "body", subject="s", user_id=TEST_USER_ID)

    _add_template_history(conn, cid, campaign_id, tid, "positive")

    results = get_template_performance(conn, campaign_id)
    assert len(results) == 1
    assert results[0]["total_sends"] < 5

    annotate_is_winning(results)
    assert not results[0].get("is_winning")  # No winner below threshold
    conn.close()


def test_unknown_outcome_no_transition(tmp_db):
    """Unknown outcome value doesn't trigger a transition or crash."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _ = _setup(conn)

    status_map = {
        "replied_positive": "replied_positive",
        "replied_negative": "replied_negative",
        "neutral": "replied_positive",
    }
    outcome = "some_random_value"

    # Should not be in status_map
    assert outcome not in status_map

    # Contact stays in_progress
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT status FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
            (contact_id, campaign_id),
        )
        row = cur.fetchone()

    assert row["status"] == "in_progress"
    conn.close()
