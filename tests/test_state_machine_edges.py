"""Edge case tests for src/services/state_machine.py.

Complements the existing test_state_machine.py with additional boundary cases:
- queued-to-completed is invalid (completed is not in VALID_TRANSITIONS from queued)
- terminal states cannot transition at all
- replied_positive and replied_negative are terminal (no auto-activation)
- bounced from a contact with no company_id
"""

import pytest

from src.models.database import get_connection, run_migrations
from src.models.campaigns import (
    enroll_contact,
    get_contact_campaign_status,
    update_contact_campaign_status,
)
from src.services.state_machine import (
    VALID_TRANSITIONS,
    InvalidTransition,
    transition_contact,
    _activate_next_contact,
    get_active_contact_for_company,
)
from src.enums import ContactStatus
from tests.conftest import TEST_USER_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db(db_path):
    conn = get_connection(db_path)
    run_migrations(conn)
    return conn


def _create_company(conn, name="Edge Fund"):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO companies (name, name_normalized, user_id) VALUES (%s, %s, %s) RETURNING id",
        (name, name.lower(), TEST_USER_ID),
    )
    company_id = cursor.fetchone()["id"]
    conn.commit()
    return company_id


def _create_contact(conn, company_id, priority_rank=1, email=None):
    email = email or f"edge{priority_rank}@example.com"
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO contacts (company_id, priority_rank, email, first_name, last_name, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (company_id, priority_rank, email, f"First{priority_rank}", f"Last{priority_rank}", TEST_USER_ID),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    return contact_id


def _create_campaign(conn, name="Edge Campaign"):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO campaigns (name, user_id) VALUES (%s, %s) RETURNING id",
        (name, TEST_USER_ID),
    )
    campaign_id = cursor.fetchone()["id"]
    conn.commit()
    return campaign_id


# ---------------------------------------------------------------------------
# Tests: queued -> completed is invalid
# ---------------------------------------------------------------------------

class TestQueuedToCompletedInvalid:
    def test_queued_to_completed_raises(self, tmp_db):
        """The 'completed' status is not reachable from 'queued'."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "completed", user_id=TEST_USER_ID)
        conn.close()

    def test_queued_to_unsubscribed_raises(self, tmp_db):
        """The 'unsubscribed' status is not reachable from 'queued'."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "unsubscribed", user_id=TEST_USER_ID)
        conn.close()

    def test_in_progress_to_completed_raises(self, tmp_db):
        """The 'completed' status is not reachable from 'in_progress'."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=TEST_USER_ID)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "completed", user_id=TEST_USER_ID)
        conn.close()


# ---------------------------------------------------------------------------
# Tests: all terminal states cannot transition further
# ---------------------------------------------------------------------------

class TestTerminalStatesBlocked:
    def test_replied_positive_cannot_transition(self, tmp_db):
        """replied_positive is terminal -- no transitions allowed."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=TEST_USER_ID)
        transition_contact(conn, contact_id, campaign_id, "replied_positive", user_id=TEST_USER_ID)

        # Try every possible target status
        for target in ["queued", "in_progress", "no_response", "bounced", "replied_negative", "completed"]:
            with pytest.raises(InvalidTransition, match="Cannot transition"):
                transition_contact(conn, contact_id, campaign_id, target, user_id=TEST_USER_ID)
        conn.close()

    def test_replied_negative_cannot_transition(self, tmp_db):
        """replied_negative is terminal -- no transitions allowed."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=TEST_USER_ID)
        transition_contact(conn, contact_id, campaign_id, "replied_negative", user_id=TEST_USER_ID)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=TEST_USER_ID)
        conn.close()

    def test_no_response_cannot_transition(self, tmp_db):
        """no_response is terminal -- no transitions allowed."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=TEST_USER_ID)
        transition_contact(conn, contact_id, campaign_id, "no_response", user_id=TEST_USER_ID)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "queued", user_id=TEST_USER_ID)
        conn.close()

    def test_bounced_cannot_transition(self, tmp_db):
        """bounced is terminal -- no transitions allowed."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=TEST_USER_ID)
        transition_contact(conn, contact_id, campaign_id, "bounced", user_id=TEST_USER_ID)

        with pytest.raises(InvalidTransition, match="Cannot transition"):
            transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=TEST_USER_ID)
        conn.close()


# ---------------------------------------------------------------------------
# Tests: replied_positive does NOT auto-activate (it is NOT in _TERMINAL_STATUSES)
# ---------------------------------------------------------------------------

class TestRepliedPositiveIsNotAutoActivating:
    def test_replied_positive_no_auto_activate(self, tmp_db):
        """replied_positive should NOT trigger auto-activation of next contact."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1, email="rp1@ex.com")
        c2 = _create_contact(conn, company_id, priority_rank=2, email="rp2@ex.com")
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=TEST_USER_ID)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=TEST_USER_ID)

        transition_contact(conn, c1, campaign_id, "replied_positive", user_id=TEST_USER_ID)

        # c2 should NOT have been auto-enrolled
        c2_status = get_contact_campaign_status(conn, c2, campaign_id, user_id=TEST_USER_ID)
        assert c2_status is None
        conn.close()

    def test_replied_negative_no_auto_activate(self, tmp_db):
        """replied_negative should NOT trigger auto-activation of next contact."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1, email="rn1@ex.com")
        c2 = _create_contact(conn, company_id, priority_rank=2, email="rn2@ex.com")
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=TEST_USER_ID)
        transition_contact(conn, c1, campaign_id, "in_progress", user_id=TEST_USER_ID)

        transition_contact(conn, c1, campaign_id, "replied_negative", user_id=TEST_USER_ID)

        c2_status = get_contact_campaign_status(conn, c2, campaign_id, user_id=TEST_USER_ID)
        assert c2_status is None
        conn.close()


# ---------------------------------------------------------------------------
# Tests: _activate_next_contact directly
# ---------------------------------------------------------------------------

class TestActivateNextContactDirect:
    def test_returns_none_for_nonexistent_contact(self, tmp_db):
        conn = _setup_db(tmp_db)
        campaign_id = _create_campaign(conn)
        result = _activate_next_contact(conn, 99999, campaign_id, user_id=TEST_USER_ID)
        assert result is None
        conn.close()

    def test_returns_none_when_no_next_contact(self, tmp_db):
        """Single contact at company, no next to activate."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1)
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=TEST_USER_ID)

        result = _activate_next_contact(conn, c1, campaign_id, user_id=TEST_USER_ID)
        assert result is None
        conn.close()

    def test_activates_next_by_rank(self, tmp_db):
        """Should activate rank 2 when rank 1 triggers activation."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1, email="act1@ex.com")
        c2 = _create_contact(conn, company_id, priority_rank=2, email="act2@ex.com")
        c3 = _create_contact(conn, company_id, priority_rank=3, email="act3@ex.com")
        campaign_id = _create_campaign(conn)
        enroll_contact(conn, c1, campaign_id, user_id=TEST_USER_ID)

        result = _activate_next_contact(conn, c1, campaign_id, user_id=TEST_USER_ID)
        assert result == c2

        # c2 should now be enrolled
        c2_status = get_contact_campaign_status(conn, c2, campaign_id, user_id=TEST_USER_ID)
        assert c2_status is not None
        assert c2_status["status"] == "queued"
        conn.close()


# ---------------------------------------------------------------------------
# Tests: VALID_TRANSITIONS exhaustiveness
# ---------------------------------------------------------------------------

class TestValidTransitionsExhaustive:
    def test_all_valid_transitions_succeed(self, tmp_db):
        """Verify each entry in VALID_TRANSITIONS actually works end-to-end."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        campaign_idx = [0]

        for source, targets in VALID_TRANSITIONS.items():
            for target in targets:
                campaign_idx[0] += 1
                cname = f"Campaign_{campaign_idx[0]}"
                contact_id = _create_contact(
                    conn, company_id,
                    priority_rank=campaign_idx[0],
                    email=f"exhaust{campaign_idx[0]}@ex.com",
                )
                campaign_id = _create_campaign(conn, name=cname)
                enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)

                # Move to source state first if not queued
                if source != "queued":
                    update_contact_campaign_status(
                        conn, contact_id, campaign_id, status=source, user_id=TEST_USER_ID,
                    )

                result = transition_contact(
                    conn, contact_id, campaign_id, target, user_id=TEST_USER_ID,
                )
                assert result == target

                row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
                assert row["status"] == target

        conn.close()
