"""Tests for the response analyzer service."""

from __future__ import annotations

from src.models.campaigns import create_campaign
from src.models.templates import create_template
from src.models.database import get_connection, run_migrations
from src.services.response_analyzer import (
    get_channel_performance,
    get_segment_performance,
    get_template_performance,
    get_timing_performance,
)
from tests.conftest import TEST_USER_ID


def _setup(conn):
    """Create base data for response analyzer tests."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country, user_id)
           VALUES ('Big Fund', 'big fund', 2000.0, 'Hedge Fund', 'US', %s) RETURNING id""",
        (TEST_USER_ID,),
    )
    company_id = cur.fetchone()["id"]

    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name, email,
                                 email_normalized, email_status, user_id)
           VALUES (%s, 'John', 'Doe', 'John Doe', 'john@test.com', 'john@test.com', 'valid', %s)
           RETURNING id""",
        (company_id, TEST_USER_ID),
    )
    contact_id = cur.fetchone()["id"]

    campaign_id = create_campaign(conn, "test_camp", user_id=TEST_USER_ID)
    template_id = create_template(conn, "tmpl1", "email", "body1", subject="subj1", user_id=TEST_USER_ID)

    return company_id, contact_id, campaign_id, template_id


def test_template_performance_empty(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    campaign_id = create_campaign(conn, "empty_camp", user_id=TEST_USER_ID)
    result = get_template_performance(conn, campaign_id)
    assert result == []
    conn.close()


def test_template_performance_with_data(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, template_id = _setup(conn)

    cur = conn.cursor()
    # Add template history entries
    for outcome in ["positive", "positive", "negative", None, None]:
        cur.execute(
            """INSERT INTO contact_template_history (contact_id, campaign_id, template_id, channel, outcome, user_id)
               VALUES (%s, %s, %s, 'email', %s, %s)
               ON CONFLICT (contact_id, campaign_id, template_id) DO UPDATE SET outcome = EXCLUDED.outcome""",
            (contact_id, campaign_id, template_id, outcome, TEST_USER_ID),
        )
    conn.commit()

    result = get_template_performance(conn, campaign_id)
    assert len(result) >= 1
    assert result[0]["template_id"] == template_id
    assert result[0]["confidence"] == "low"  # <20 sends
    conn.close()


def test_channel_performance_empty(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    campaign_id = create_campaign(conn, "empty_camp", user_id=TEST_USER_ID)
    result = get_channel_performance(conn, campaign_id)
    assert result == []
    conn.close()


def test_segment_performance(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _ = _setup(conn)

    from src.models.campaigns import enroll_contact
    enroll_contact(conn, contact_id, campaign_id, user_id=1)

    result = get_segment_performance(conn, campaign_id)
    assert len(result) >= 1
    # Big Fund has 2000M AUM -> "$1B+" tier
    tiers = [r["aum_tier"] for r in result]
    assert "$1B+" in tiers
    conn.close()


def test_timing_performance_empty(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    campaign_id = create_campaign(conn, "empty_camp", user_id=TEST_USER_ID)
    result = get_timing_performance(conn, campaign_id)
    assert result == []
    conn.close()
