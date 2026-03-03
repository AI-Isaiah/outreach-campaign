"""Tests for the contact scorer service."""

from __future__ import annotations

from src.models.campaigns import create_campaign, enroll_contact
from src.models.database import get_connection, run_migrations
from src.services.contact_scorer import score_contacts


def _setup(conn):
    """Create base data for scorer tests."""
    cur = conn.cursor()

    # Create two companies with different AUMs
    cur.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country)
           VALUES ('Big Fund', 'big fund', 2000.0, 'Hedge Fund', 'US') RETURNING id"""
    )
    big_id = cur.fetchone()["id"]

    cur.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country)
           VALUES ('Small Fund', 'small fund', 50.0, 'Family Office', 'US') RETURNING id"""
    )
    small_id = cur.fetchone()["id"]

    # Create contacts
    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name, email,
                                 email_normalized, email_status, linkedin_url)
           VALUES (%s, 'Alice', 'A', 'Alice A', 'alice@big.com', 'alice@big.com', 'valid',
                   'https://linkedin.com/in/alice')
           RETURNING id""",
        (big_id,),
    )
    alice_id = cur.fetchone()["id"]

    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name, email,
                                 email_normalized, email_status)
           VALUES (%s, 'Bob', 'B', 'Bob B', 'bob@small.com', 'bob@small.com', 'valid')
           RETURNING id""",
        (small_id,),
    )
    bob_id = cur.fetchone()["id"]

    campaign_id = create_campaign(conn, "scorer_test")

    # Enroll both
    enroll_contact(conn, alice_id, campaign_id, next_action_date="2026-01-01")
    enroll_contact(conn, bob_id, campaign_id, next_action_date="2026-01-01")

    conn.commit()
    return campaign_id, alice_id, bob_id


def test_score_contacts_basic(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    campaign_id, alice_id, bob_id = _setup(conn)

    scores = score_contacts(conn, campaign_id, [alice_id, bob_id])
    assert len(scores) == 2

    # Alice (high AUM, has LinkedIn) should score higher than Bob (low AUM, no LinkedIn)
    alice_score = next(s for s in scores if s["contact_id"] == alice_id)
    bob_score = next(s for s in scores if s["contact_id"] == bob_id)

    assert alice_score["priority_score"] > bob_score["priority_score"]
    assert "breakdown" in alice_score
    assert alice_score["breakdown"]["channel_score"] > bob_score["breakdown"]["channel_score"]
    conn.close()


def test_score_contacts_empty(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    campaign_id = create_campaign(conn, "empty_scorer")

    scores = score_contacts(conn, campaign_id, [])
    assert scores == []
    conn.close()


def test_scores_sorted_descending(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    campaign_id, alice_id, bob_id = _setup(conn)

    scores = score_contacts(conn, campaign_id, [bob_id, alice_id])
    # Should be sorted by score descending
    assert scores[0]["priority_score"] >= scores[1]["priority_score"]
    conn.close()


def test_score_has_all_breakdown_fields(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    campaign_id, alice_id, _ = _setup(conn)

    scores = score_contacts(conn, campaign_id, [alice_id])
    assert len(scores) == 1
    breakdown = scores[0]["breakdown"]
    assert "aum_score" in breakdown
    assert "segment_score" in breakdown
    assert "channel_score" in breakdown
    assert "recency_score" in breakdown
    conn.close()
