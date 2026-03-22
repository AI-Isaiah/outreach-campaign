"""Tests for the contact campaign state machine."""

import pytest

from src.models.database import get_connection, run_migrations
from src.models.campaigns import (
    enroll_contact,
    get_contact_campaign_status,
    log_event,
)
from src.services.state_machine import (
    VALID_TRANSITIONS,
    InvalidTransition,
    transition_contact,
    _activate_next_contact,
    get_active_contact_for_company,
)
from tests.conftest import TEST_USER_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db(db_path):
    """Return a connection with migrations applied."""
    conn = get_connection(db_path)
    run_migrations(conn)
    return conn


def _create_company(conn, name="Acme Fund"):
    """Insert a company and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO companies (name, name_normalized, user_id) VALUES (%s, %s, %s) RETURNING id",
        (name, name.lower(), TEST_USER_ID),
    )
    company_id = cursor.fetchone()["id"]
    conn.commit()
    return company_id


def _create_contact(conn, company_id, priority_rank=1, email=None):
    """Insert a contact and return its id."""
    email = email or f"contact{priority_rank}@example.com"
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO contacts (company_id, priority_rank, email, first_name, last_name, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (company_id, priority_rank, email, f"First{priority_rank}", f"Last{priority_rank}", TEST_USER_ID),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    return contact_id


def _create_campaign(conn, name="Q1 Outreach"):
    """Insert a campaign and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO campaigns (name, user_id) VALUES (%s, %s) RETURNING id",
        (name, TEST_USER_ID),
    )
    campaign_id = cursor.fetchone()["id"]
    conn.commit()
    return campaign_id


def _event_types_for_contact(conn, contact_id, campaign_id=None):
    """Return a list of event_type strings for a contact."""
    cursor = conn.cursor()
    if campaign_id is not None:
        cursor.execute(
            "SELECT event_type FROM events WHERE contact_id = %s AND campaign_id = %s ORDER BY id",
            (contact_id, campaign_id),
        )
    else:
        cursor.execute(
            "SELECT event_type FROM events WHERE contact_id = %s ORDER BY id",
            (contact_id,),
        )
    rows = cursor.fetchall()
    return [r["event_type"] for r in rows]


# ---------------------------------------------------------------------------
# Tests: VALID_TRANSITIONS definition
# ---------------------------------------------------------------------------

class TestValidTransitions:
    def test_queued_can_become_in_progress(self):
        assert "in_progress" in VALID_TRANSITIONS["queued"]

    def test_in_progress_terminal_states(self):
        expected = {"no_response", "replied_positive", "replied_negative", "bounced"}
        assert VALID_TRANSITIONS["in_progress"] == expected

    def test_queued_only_allows_in_progress(self):
        assert VALID_TRANSITIONS["queued"] == {"in_progress"}


# ---------------------------------------------------------------------------
# Tests: valid transitions
# ---------------------------------------------------------------------------

class TestTransitionContact:
    def test_queued_to_in_progress(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)

        result = transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)

        assert result == "in_progress"
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=1)
        assert row["status"] == "in_progress"
        conn.close()

    def test_in_progress_to_replied_positive(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)

        result = transition_contact(conn, contact_id, campaign_id, "replied_positive", user_id=1)

        assert result == "replied_positive"
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=1)
        assert row["status"] == "replied_positive"
        conn.close()

    def test_in_progress_to_replied_negative(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)

        result = transition_contact(conn, contact_id, campaign_id, "replied_negative", user_id=1)

        assert result == "replied_negative"
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=1)
        assert row["status"] == "replied_negative"
        conn.close()

    def test_in_progress_to_no_response(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)

        result = transition_contact(conn, contact_id, campaign_id, "no_response", user_id=1)

        assert result == "no_response"
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=1)
        assert row["status"] == "no_response"
        conn.close()

    def test_in_progress_to_bounced(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)

        result = transition_contact(conn, contact_id, campaign_id, "bounced", user_id=1)

        assert result == "bounced"
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=1)
        assert row["status"] == "bounced"
        conn.close()


# ---------------------------------------------------------------------------
# Tests: invalid transitions
# ---------------------------------------------------------------------------

class TestInvalidTransitions:
    def test_queued_to_no_response_is_invalid(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "no_response", user_id=1)
        conn.close()

    def test_queued_to_bounced_is_invalid(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "bounced", user_id=1)
        conn.close()

    def test_queued_to_replied_positive_is_invalid(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "replied_positive", user_id=1)
        conn.close()

    def test_terminal_state_cannot_transition(self, tmp_db):
        """A contact in no_response cannot transition further."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)
        transition_contact(conn, contact_id, campaign_id, "no_response", user_id=1)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)
        conn.close()

    def test_in_progress_to_queued_is_invalid(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "queued", user_id=1)
        conn.close()

    def test_in_progress_to_in_progress_is_invalid(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)
        conn.close()

    def test_not_enrolled_raises(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        # Do NOT enroll

        with pytest.raises(InvalidTransition, match="not enrolled"):
            transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)
        conn.close()

    def test_bogus_status_raises(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "nonexistent_status", user_id=1)
        conn.close()


# ---------------------------------------------------------------------------
# Tests: event logging
# ---------------------------------------------------------------------------

class TestEventLogging:
    def test_transition_logs_event(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)

        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)

        events = _event_types_for_contact(conn, contact_id, campaign_id)
        assert "status_in_progress" in events
        conn.close()

    def test_multiple_transitions_log_multiple_events(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)

        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)
        transition_contact(conn, contact_id, campaign_id, "replied_positive", user_id=1)

        events = _event_types_for_contact(conn, contact_id, campaign_id)
        assert events == ["status_in_progress", "status_replied_positive"]
        conn.close()

    def test_no_response_logs_both_transition_and_activation_events(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        c2 = _create_contact(conn, company_id, priority_rank=2)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=1)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)

        transition_contact(conn, c1, campaign_id, "no_response", user_id=1)

        # c1 should have the transition event
        c1_events = _event_types_for_contact(conn, c1, campaign_id)
        assert "status_no_response" in c1_events

        # c2 should have the auto_activated event
        c2_events = _event_types_for_contact(conn, c2, campaign_id)
        assert "auto_activated" in c2_events
        conn.close()


# ---------------------------------------------------------------------------
# Tests: auto-activation on no_response
# ---------------------------------------------------------------------------

class TestAutoActivationNoResponse:
    def test_next_contact_enrolled_on_no_response(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        c2 = _create_contact(conn, company_id, priority_rank=2)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=1)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)

        transition_contact(conn, c1, campaign_id, "no_response", user_id=1)

        c2_status = get_contact_campaign_status(conn, c2, campaign_id, user_id=1)
        assert c2_status is not None
        assert c2_status["status"] == "queued"
        assert c2_status["next_action_date"] is not None
        conn.close()

    def test_activation_skips_already_enrolled_contacts(self, tmp_db):
        """If rank 2 is already enrolled, rank 3 should be activated."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        c2 = _create_contact(conn, company_id, priority_rank=2)
        c3 = _create_contact(conn, company_id, priority_rank=3)
        campaign_id = _create_campaign(conn)

        enroll_contact(conn, c1, campaign_id, user_id=1)
        enroll_contact(conn, c2, campaign_id, user_id=1)  # pre-enroll c2

        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)
        transition_contact(conn, c1, campaign_id, "no_response", user_id=1)

        # c2 was already enrolled so c3 should have been activated
        c3_status = get_contact_campaign_status(conn, c3, campaign_id, user_id=1)
        assert c3_status is not None
        assert c3_status["status"] == "queued"
        conn.close()

    def test_cascading_activation(self, tmp_db):
        """When c2 also exhausts, c3 should be activated."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        c2 = _create_contact(conn, company_id, priority_rank=2)
        c3 = _create_contact(conn, company_id, priority_rank=3)
        campaign_id = _create_campaign(conn)

        enroll_contact(conn, c1, campaign_id, user_id=1)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)
        transition_contact(conn, c1, campaign_id, "no_response", user_id=1)
        # c2 is now auto-enrolled

        transition_contact(conn, c2, campaign_id, "in_progress", user_id=1)
        transition_contact(conn, c2, campaign_id, "no_response", user_id=1)
        # c3 should now be auto-enrolled

        c3_status = get_contact_campaign_status(conn, c3, campaign_id, user_id=1)
        assert c3_status is not None
        assert c3_status["status"] == "queued"
        conn.close()


# ---------------------------------------------------------------------------
# Tests: auto-activation on bounced
# ---------------------------------------------------------------------------

class TestAutoActivationBounced:
    def test_next_contact_enrolled_on_bounced(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        c2 = _create_contact(conn, company_id, priority_rank=2)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=1)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)

        transition_contact(conn, c1, campaign_id, "bounced", user_id=1)

        c2_status = get_contact_campaign_status(conn, c2, campaign_id, user_id=1)
        assert c2_status is not None
        assert c2_status["status"] == "queued"
        conn.close()

    def test_bounced_logs_auto_activated_event(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        c2 = _create_contact(conn, company_id, priority_rank=2)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=1)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)

        transition_contact(conn, c1, campaign_id, "bounced", user_id=1)

        c2_events = _event_types_for_contact(conn, c2, campaign_id)
        assert "auto_activated" in c2_events
        conn.close()


# ---------------------------------------------------------------------------
# Tests: no auto-activation when all contacts exhausted
# ---------------------------------------------------------------------------

class TestNoAutoActivation:
    def test_no_activation_when_all_contacts_exhausted(self, tmp_db):
        """Only one contact at company, no_response should not fail."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=1)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)

        # Should not raise even though there is no next contact
        result = transition_contact(conn, c1, campaign_id, "no_response", user_id=1)
        assert result == "no_response"
        conn.close()

    def test_no_activation_when_remaining_contacts_already_enrolled(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        c2 = _create_contact(conn, company_id, priority_rank=2)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=1)
        enroll_contact(conn, c2, campaign_id, user_id=1)

        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)
        transition_contact(conn, c1, campaign_id, "no_response", user_id=1)

        # c2 was already enrolled, and there is no c3 - transition should succeed
        # Check that no extra enrollment was created (only original two)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM contact_campaign_status WHERE campaign_id = %s",
            (campaign_id,),
        )
        count = cursor.fetchone()["cnt"]
        assert count == 2
        conn.close()


# ---------------------------------------------------------------------------
# Tests: replied_positive does NOT trigger auto-activation
# ---------------------------------------------------------------------------

class TestRepliedPositiveNoActivation:
    def test_replied_positive_does_not_activate_next(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        c2 = _create_contact(conn, company_id, priority_rank=2)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=1)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)

        transition_contact(conn, c1, campaign_id, "replied_positive", user_id=1)

        c2_status = get_contact_campaign_status(conn, c2, campaign_id, user_id=1)
        assert c2_status is None  # c2 should NOT have been enrolled
        conn.close()

    def test_replied_negative_does_not_activate_next(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        c2 = _create_contact(conn, company_id, priority_rank=2)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=1)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)

        transition_contact(conn, c1, campaign_id, "replied_negative", user_id=1)

        c2_status = get_contact_campaign_status(conn, c2, campaign_id, user_id=1)
        assert c2_status is None
        conn.close()


# ---------------------------------------------------------------------------
# Tests: get_active_contact_for_company
# ---------------------------------------------------------------------------

class TestGetActiveContactForCompany:
    def test_returns_queued_contact(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)

        active = get_active_contact_for_company(conn, company_id, campaign_id, user_id=1)
        assert active is not None
        assert active["id"] == contact_id
        conn.close()

    def test_returns_in_progress_contact(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=1)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=1)

        active = get_active_contact_for_company(conn, company_id, campaign_id, user_id=1)
        assert active is not None
        assert active["id"] == contact_id
        conn.close()

    def test_returns_none_when_contact_is_terminal(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=1)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)
        transition_contact(conn, c1, campaign_id, "replied_positive", user_id=1)

        active = get_active_contact_for_company(conn, company_id, campaign_id, user_id=1)
        assert active is None
        conn.close()

    def test_returns_none_when_no_enrollment(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)

        active = get_active_contact_for_company(conn, company_id, campaign_id, user_id=1)
        assert active is None
        conn.close()

    def test_returns_lowest_rank_active_contact(self, tmp_db):
        """If multiple contacts are active, return the one with lowest rank."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        c2 = _create_contact(conn, company_id, priority_rank=2)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=1)
        enroll_contact(conn, c2, campaign_id, user_id=1)

        active = get_active_contact_for_company(conn, company_id, campaign_id, user_id=1)
        assert active["id"] == c1
        conn.close()

    def test_returns_next_active_after_first_exhausted(self, tmp_db):
        """After c1 hits no_response and c2 is auto-activated, c2 is the active one."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        c2 = _create_contact(conn, company_id, priority_rank=2)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=1)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=1)
        transition_contact(conn, c1, campaign_id, "no_response", user_id=1)
        # c2 auto-activated

        active = get_active_contact_for_company(conn, company_id, campaign_id, user_id=1)
        assert active is not None
        assert active["id"] == c2
        conn.close()

    def test_different_campaigns_are_independent(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_a = _create_campaign(conn, name="Campaign A")
        campaign_b = _create_campaign(conn, name="Campaign B")
        enroll_contact(conn, contact_id, campaign_a, user_id=1)

        active_a = get_active_contact_for_company(conn, company_id, campaign_a, user_id=1)
        active_b = get_active_contact_for_company(conn, company_id, campaign_b, user_id=1)

        assert active_a is not None
        assert active_a["id"] == contact_id
        assert active_b is None
        conn.close()
