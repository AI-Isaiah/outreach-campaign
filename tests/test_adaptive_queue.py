"""Tests for the adaptive queue orchestrator."""

from __future__ import annotations

from datetime import date

from src.models.campaigns import (
    add_sequence_step,
    create_campaign,
    create_template,
    enroll_contact,
)
from src.models.database import get_connection, run_migrations
from src.services.adaptive_queue import get_adaptive_queue, _apply_channel_rules
from tests.conftest import TEST_USER_ID


def _full_setup(conn):
    """Create complete setup for adaptive queue tests."""
    cur = conn.cursor()

    # Company
    cur.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country, user_id)
           VALUES ('Alpha Capital', 'alpha capital', 1500.0, 'Hedge Fund', 'US', %s) RETURNING id""",
        (TEST_USER_ID,),
    )
    company_id = cur.fetchone()["id"]

    # Contact with email + linkedin
    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name, email,
                                 email_normalized, email_status, linkedin_url, linkedin_url_normalized)
           VALUES (%s, 'Jane', 'Smith', 'Jane Smith', 'jane@alpha.com', 'jane@alpha.com',
                   'valid', 'https://linkedin.com/in/jsmith', 'https://linkedin.com/in/jsmith')
           RETURNING id""",
        (company_id,),
    )
    contact_id = cur.fetchone()["id"]
    conn.commit()

    # Campaign + template + sequence + enrollment
    campaign_id = create_campaign(conn, "adaptive_test", user_id=TEST_USER_ID)
    template_id = create_template(conn, "intro_v1", "email", "Hello {{ first_name }}", subject="Intro", user_id=TEST_USER_ID)
    add_sequence_step(conn, campaign_id, 1, "email", template_id=template_id, delay_days=0)

    today = date.today().isoformat()
    enroll_contact(conn, contact_id, campaign_id, next_action_date=today)

    return company_id, contact_id, campaign_id, template_id


def test_adaptive_queue_basic(tmp_db):
    """Adaptive queue should return enriched items with scores."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _ = _full_setup(conn)

    items = get_adaptive_queue(conn, campaign_id)
    assert len(items) >= 1

    item = items[0]
    assert item["contact_id"] == contact_id
    assert "priority_score" in item
    assert "selection_mode" in item
    assert "reasoning" in item
    assert item["priority_score"] >= 0
    conn.close()


def test_adaptive_queue_empty(tmp_db):
    """Adaptive queue with no eligible contacts returns empty."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    campaign_id = create_campaign(conn, "empty_adaptive", user_id=TEST_USER_ID)

    items = get_adaptive_queue(conn, campaign_id)
    assert items == []
    conn.close()


def test_adaptive_queue_has_alternatives(tmp_db):
    """Result should include alternatives list."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, _, campaign_id, _ = _full_setup(conn)

    items = get_adaptive_queue(conn, campaign_id)
    assert len(items) >= 1
    assert "alternatives" in items[0]
    conn.close()


def test_adaptive_queue_respects_limit(tmp_db):
    """Should respect the limit parameter."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, _, campaign_id, template_id = _full_setup(conn)

    # Add more contacts
    cur = conn.cursor()
    today = date.today().isoformat()
    for i in range(5):
        cur.execute(
            """INSERT INTO companies (name, name_normalized, aum_millions, country, user_id)
               VALUES (%s, %s, %s, 'US', %s) RETURNING id""",
            (f"Fund_{i}", f"fund_{i}", 100.0 * (i + 1), TEST_USER_ID),
        )
        co_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO contacts (company_id, first_name, full_name, email,
                                     email_normalized, email_status)
               VALUES (%s, %s, %s, %s, %s, 'valid') RETURNING id""",
            (co_id, f"Person{i}", f"Person {i}", f"p{i}@test.com", f"p{i}@test.com"),
        )
        c_id = cur.fetchone()["id"]
        conn.commit()
        enroll_contact(conn, c_id, campaign_id, next_action_date=today)

    items = get_adaptive_queue(conn, campaign_id, limit=3)
    assert len(items) <= 3
    conn.close()


def test_adaptive_queue_sorted_by_score(tmp_db):
    """Items should be sorted by priority_score descending."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, _, campaign_id, template_id = _full_setup(conn)

    # Add a contact with lower AUM
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, country, user_id)
           VALUES ('Tiny Fund', 'tiny fund', 10.0, 'US', %s) RETURNING id""",
        (TEST_USER_ID,),
    )
    co_id = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO contacts (company_id, first_name, full_name, email,
                                 email_normalized, email_status)
           VALUES (%s, 'Tiny', 'Tiny Person', 'tiny@test.com', 'tiny@test.com', 'valid')
           RETURNING id""",
        (co_id,),
    )
    tiny_id = cur.fetchone()["id"]
    conn.commit()
    today = date.today().isoformat()
    enroll_contact(conn, tiny_id, campaign_id, next_action_date=today)

    items = get_adaptive_queue(conn, campaign_id)
    if len(items) >= 2:
        for i in range(len(items) - 1):
            assert items[i]["priority_score"] >= items[i + 1]["priority_score"]
    conn.close()


# --- Channel rules unit tests ---

def test_channel_rules_linkedin_first():
    """New contacts (no history) with LinkedIn should get LinkedIn first."""
    item = {"linkedin_url": "https://linkedin.com/in/test", "email": "test@test.com"}
    result = _apply_channel_rules("email", [], item)
    assert result == "linkedin_connect"


def test_channel_rules_no_linkedin_keeps_email():
    """New contacts without LinkedIn keep email channel."""
    item = {"linkedin_url": None, "email": "test@test.com"}
    result = _apply_channel_rules("email", [], item)
    assert result == "email"


def test_channel_rules_three_same_switches():
    """After 2 same-type channels, should switch."""
    item = {"linkedin_url": "https://linkedin.com/in/test", "email": "test@test.com"}
    result = _apply_channel_rules("email", ["email", "email"], item)
    assert result.startswith("linkedin")


def test_channel_rules_two_different_keeps():
    """Mixed history should not trigger switch."""
    item = {"linkedin_url": "https://linkedin.com/in/test", "email": "test@test.com"}
    result = _apply_channel_rules("email", ["linkedin_connect", "email"], item)
    assert result == "email"


def test_channel_rules_short_history_no_switch():
    """With only 1 previous touch, no switch needed."""
    item = {"linkedin_url": "https://linkedin.com/in/test", "email": "test@test.com"}
    result = _apply_channel_rules("email", ["email"], item)
    assert result == "email"
