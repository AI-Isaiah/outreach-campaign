"""Comprehensive tests for the priority queue algorithm."""

from datetime import date, timedelta

import pytest

from src.models.database import get_connection, run_migrations
from src.models.campaigns import (
    create_campaign,
    add_sequence_step,
    create_template,
    enroll_contact,
    update_contact_campaign_status,
    get_sequence_steps,
)
from src.services.priority_queue import (
    get_daily_queue,
    get_next_step_for_contact,
    count_steps_for_contact,
    defer_contact,
    get_defer_stats,
)
from tests.conftest import TEST_USER_ID, insert_company, insert_contact


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return date.today().isoformat()


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def _tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


def _setup_campaign_with_steps(conn):
    """Create a campaign with standard 5-step sequence.

    Steps:
      1: linkedin_connect (delay 0)
      2: linkedin_message (delay 3)
      3: email (delay 5)
      4: email (delay 7, non_gdpr_only)
      5: email (delay 14, non_gdpr_only)
    """
    campaign_id = create_campaign(conn, "test_campaign", user_id=TEST_USER_ID)

    t1 = create_template(conn, "li_connect", "linkedin_connect", "Hi {{first_name}}", user_id=TEST_USER_ID)
    t2 = create_template(conn, "li_msg", "linkedin_message", "Following up...", user_id=TEST_USER_ID)
    t3 = create_template(
        conn, "email_cold", "email", "Hello {{first_name}}", subject="Quick intro", user_id=TEST_USER_ID,
    )
    t4 = create_template(
        conn, "email_followup", "email", "Following up...", subject="Following up", user_id=TEST_USER_ID,
    )
    t5 = create_template(
        conn, "email_breakup", "email", "Last note...", subject="Last note", user_id=TEST_USER_ID,
    )

    add_sequence_step(conn, campaign_id, 1, "linkedin_connect", t1, delay_days=0)
    add_sequence_step(conn, campaign_id, 2, "linkedin_message", t2, delay_days=3)
    add_sequence_step(conn, campaign_id, 3, "email", t3, delay_days=5)
    add_sequence_step(
        conn, campaign_id, 4, "email", t4, delay_days=7, non_gdpr_only=True
    )
    add_sequence_step(
        conn, campaign_id, 5, "email", t5, delay_days=14, non_gdpr_only=True
    )

    return campaign_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_db):
    """Return a fresh database connection with migrations applied."""
    connection = get_connection(tmp_db)
    run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def campaign(conn):
    """Return campaign_id for a standard 5-step campaign."""
    return _setup_campaign_with_steps(conn)


# ---------------------------------------------------------------------------
# Tests: get_daily_queue
# ---------------------------------------------------------------------------

class TestGetDailyQueue:
    """Tests for the get_daily_queue function."""

    def test_basic_queue_returns_correct_contacts(self, conn, campaign):
        """Contacts enrolled and ready today appear in the queue."""
        comp_id = insert_company(conn, "Acme Corp", aum_millions=500)
        contact_id = insert_contact(conn, comp_id, first_name="Alice", last_name="Smith")
        enroll_contact(conn, contact_id, campaign, next_action_date=_today())
        # Set current_step to 1 (linkedin_connect) and status to in_progress
        update_contact_campaign_status(
            conn, contact_id, campaign, status="in_progress", current_step=1
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())

        assert len(queue) == 1
        item = queue[0]
        assert item["contact_id"] == contact_id
        assert item["company_name"] == "Acme Corp"
        assert item["contact_name"] == "Alice Smith"
        assert item["channel"] == "linkedin_connect"
        assert item["step_order"] == 1
        assert item["aum_millions"] == 500.0
        assert item["is_gdpr"] is False

    def test_one_per_company_lowest_rank_returned(self, conn, campaign):
        """Only the lowest priority_rank contact per company is returned."""
        comp_id = insert_company(conn, "Big Fund", aum_millions=1000)

        c1 = insert_contact(
            conn, comp_id, first_name="Primary", last_name="Contact", priority_rank=1
        )
        c2 = insert_contact(
            conn,
            comp_id,
            first_name="Secondary",
            last_name="Contact",
            priority_rank=2,
            email="secondary@example.com",
        )

        for cid in [c1, c2]:
            enroll_contact(conn, cid, campaign, next_action_date=_today())
            update_contact_campaign_status(
                conn, cid, campaign, status="in_progress", current_step=1
            )

        queue = get_daily_queue(conn, campaign, target_date=_today())

        assert len(queue) == 1
        assert queue[0]["contact_id"] == c1
        assert queue[0]["contact_name"] == "Primary Contact"

    def test_aum_ordering_highest_first(self, conn, campaign):
        """Companies are ordered by AUM descending."""
        comp_small = insert_company(conn, "Small Fund", aum_millions=100)
        comp_big = insert_company(conn, "Big Fund", aum_millions=5000)
        comp_mid = insert_company(conn, "Mid Fund", aum_millions=1000)

        contacts = []
        for comp_id, name in [
            (comp_small, "Small"),
            (comp_big, "Big"),
            (comp_mid, "Mid"),
        ]:
            cid = insert_contact(conn, comp_id, first_name=name, last_name="Person")
            enroll_contact(conn, cid, campaign, next_action_date=_today())
            update_contact_campaign_status(
                conn, cid, campaign, status="in_progress", current_step=1
            )
            contacts.append(cid)

        queue = get_daily_queue(conn, campaign, target_date=_today(), limit=10)

        assert len(queue) == 3
        assert queue[0]["aum_millions"] == 5000
        assert queue[0]["company_name"] == "Big Fund"
        assert queue[1]["aum_millions"] == 1000
        assert queue[2]["aum_millions"] == 100

    def test_aum_nulls_last(self, conn, campaign):
        """Companies with NULL AUM sort after those with values."""
        comp_with_aum = insert_company(conn, "Known Fund", aum_millions=500)
        comp_no_aum = insert_company(conn, "Unknown Fund", aum_millions=None)

        c1 = insert_contact(conn, comp_with_aum, first_name="Known", last_name="Contact")
        c2 = insert_contact(
            conn, comp_no_aum, first_name="Unknown", last_name="Contact",
            email="unknown@example.com",
        )

        for cid in [c1, c2]:
            enroll_contact(conn, cid, campaign, next_action_date=_today())
            update_contact_campaign_status(
                conn, cid, campaign, status="in_progress", current_step=1
            )

        queue = get_daily_queue(conn, campaign, target_date=_today())

        assert len(queue) == 2
        assert queue[0]["aum_millions"] == 500
        assert queue[1]["aum_millions"] is None

    def test_date_filtering_only_today_or_earlier(self, conn, campaign):
        """Only contacts with next_action_date <= target_date appear."""
        comp = insert_company(conn, "Test Corp", aum_millions=500)

        c_past = insert_contact(
            conn, comp, first_name="Past", last_name="Contact", priority_rank=1
        )
        enroll_contact(conn, c_past, campaign, next_action_date=_yesterday())
        update_contact_campaign_status(
            conn, c_past, campaign, status="in_progress", current_step=1
        )

        comp2 = insert_company(conn, "Future Corp", aum_millions=600)
        c_future = insert_contact(
            conn, comp2, first_name="Future", last_name="Contact",
            email="future@example.com",
        )
        enroll_contact(conn, c_future, campaign, next_action_date=_tomorrow())
        update_contact_campaign_status(
            conn, c_future, campaign, status="in_progress", current_step=1
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())

        assert len(queue) == 1
        assert queue[0]["contact_name"] == "Past Contact"

    def test_email_step_skips_unverified_email(self, conn, campaign):
        """Contacts on email steps with email_status != 'valid' are skipped."""
        comp = insert_company(conn, "Email Corp", aum_millions=500)

        # Contact with unverified email on an email step
        c_unverified = insert_contact(
            conn, comp, first_name="Unverified", last_name="Email",
            email="bad@example.com", email_status="unverified",
        )
        enroll_contact(conn, c_unverified, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, c_unverified, campaign, status="in_progress", current_step=3  # email step
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 0

    def test_email_step_includes_valid_email(self, conn, campaign):
        """Contacts on email steps with email_status = 'valid' are included."""
        comp = insert_company(conn, "Valid Corp", aum_millions=500)

        c_valid = insert_contact(
            conn, comp, first_name="Valid", last_name="Email",
            email="good@example.com", email_status="valid",
        )
        enroll_contact(conn, c_valid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, c_valid, campaign, status="in_progress", current_step=3
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 1
        assert queue[0]["channel"] == "email"

    def test_linkedin_step_skips_no_linkedin(self, conn, campaign):
        """Contacts on LinkedIn steps without a LinkedIn URL are skipped."""
        comp = insert_company(conn, "NoLI Corp", aum_millions=500)

        c_no_li = insert_contact(
            conn, comp, first_name="NoLI", last_name="Contact",
            linkedin_url=None,
        )
        enroll_contact(conn, c_no_li, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, c_no_li, campaign, status="in_progress", current_step=1  # linkedin_connect
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 0

    def test_linkedin_step_skips_empty_linkedin(self, conn, campaign):
        """Contacts on LinkedIn steps with empty string LinkedIn URL are skipped."""
        comp = insert_company(conn, "EmptyLI Corp", aum_millions=500)

        c_empty_li = insert_contact(
            conn, comp, first_name="EmptyLI", last_name="Contact",
            linkedin_url="",
        )
        enroll_contact(conn, c_empty_li, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, c_empty_li, campaign, status="in_progress", current_step=2  # linkedin_message
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 0

    def test_unsubscribed_contacts_skipped(self, conn, campaign):
        """Unsubscribed contacts are excluded from the queue."""
        comp = insert_company(conn, "Unsub Corp", aum_millions=500)

        c_unsub = insert_contact(
            conn, comp, first_name="Unsub", last_name="Contact",
            unsubscribed=True,
        )
        enroll_contact(conn, c_unsub, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, c_unsub, campaign, status="in_progress", current_step=1
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 0

    def test_limit_parameter(self, conn, campaign):
        """Limit parameter caps the number of results."""
        for i in range(5):
            comp_id = insert_company(conn, f"Fund {i}", aum_millions=1000 - i * 100)
            cid = insert_contact(
                conn, comp_id, first_name=f"Contact{i}", last_name="Test",
                email=f"c{i}@example.com",
                linkedin_url=f"https://linkedin.com/in/c{i}",
            )
            enroll_contact(conn, cid, campaign, next_action_date=_today())
            update_contact_campaign_status(
                conn, cid, campaign, status="in_progress", current_step=1
            )

        queue = get_daily_queue(conn, campaign, target_date=_today(), limit=3)
        assert len(queue) == 3
        # Top 3 by AUM
        assert queue[0]["aum_millions"] == 1000
        assert queue[1]["aum_millions"] == 900
        assert queue[2]["aum_millions"] == 800

    def test_empty_queue_no_contacts_ready(self, conn, campaign):
        """Returns empty list when no contacts are ready."""
        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert queue == []

    def test_terminal_status_excluded(self, conn, campaign):
        """Contacts with a terminal status ('no_response') are not in the queue."""
        comp = insert_company(conn, "Done Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Done", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="no_response", current_step=5
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 0

    def test_queued_status_included(self, conn, campaign):
        """Contacts with status 'queued' are included in the queue."""
        comp = insert_company(conn, "Queued Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Queued", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="queued", current_step=1
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 1

    def test_default_target_date_is_today(self, conn, campaign):
        """When target_date is None, defaults to today."""
        comp = insert_company(conn, "Today Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Today", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1
        )

        queue = get_daily_queue(conn, campaign)  # no target_date
        assert len(queue) == 1

    def test_queue_returns_total_steps(self, conn, campaign):
        """Each queue item includes the total steps for that contact."""
        comp = insert_company(conn, "Steps Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Steps", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 1
        # Non-GDPR contact: all 5 steps are applicable
        assert queue[0]["total_steps"] == 5

    def test_queue_total_steps_gdpr_contact(self, conn, campaign):
        """GDPR contacts get fewer total_steps (non_gdpr_only excluded)."""
        comp = insert_company(conn, "EU Fund", aum_millions=500, is_gdpr=True)
        cid = insert_contact(
            conn, comp, first_name="GDPR", last_name="Contact", is_gdpr=True,
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 1
        # GDPR contact: steps 4 and 5 (non_gdpr_only) are excluded => 3 steps
        assert queue[0]["total_steps"] == 3
        assert queue[0]["is_gdpr"] is True

    def test_multiple_companies_one_contact_each(self, conn, campaign):
        """Multiple companies each contribute exactly one contact."""
        comp_a = insert_company(conn, "Company A", aum_millions=2000)
        comp_b = insert_company(conn, "Company B", aum_millions=1500)

        # Company A: 2 contacts, rank 1 and 2
        ca1 = insert_contact(
            conn, comp_a, first_name="A1", last_name="First", priority_rank=1,
        )
        ca2 = insert_contact(
            conn, comp_a, first_name="A2", last_name="Second", priority_rank=2,
            email="a2@example.com",
        )

        # Company B: 1 contact
        cb1 = insert_contact(
            conn, comp_b, first_name="B1", last_name="Only",
            email="b1@example.com", linkedin_url="https://linkedin.com/in/b1",
        )

        for cid in [ca1, ca2, cb1]:
            enroll_contact(conn, cid, campaign, next_action_date=_today())
            update_contact_campaign_status(
                conn, cid, campaign, status="in_progress", current_step=1
            )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 2
        contact_ids = [q["contact_id"] for q in queue]
        assert ca1 in contact_ids  # lowest rank for Company A
        assert cb1 in contact_ids  # only contact for Company B
        assert ca2 not in contact_ids  # rank 2, skipped

    def test_queue_returns_firm_type(self, conn, campaign):
        """Queue items include the company's firm_type field."""
        comp = insert_company(conn, "HF Corp", aum_millions=500, firm_type="Hedge Fund")
        cid = insert_contact(conn, comp, first_name="HF", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 1
        assert queue[0]["firm_type"] == "Hedge Fund"

    def test_queue_returns_null_firm_type(self, conn, campaign):
        """Queue items with no firm_type return None."""
        comp = insert_company(conn, "Unknown Corp", aum_millions=200)
        cid = insert_contact(conn, comp, first_name="Unk", last_name="Contact",
                              email="unk@example.com")
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1
        )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        assert len(queue) == 1
        assert queue[0]["firm_type"] is None

    def test_gdpr_step_filtering_in_queue(self, conn, campaign):
        """Non-GDPR contacts on non_gdpr_only steps are included;
        GDPR contacts on non_gdpr_only steps are excluded."""
        comp_us = insert_company(conn, "US Fund", aum_millions=800)
        comp_eu = insert_company(conn, "EU Fund", aum_millions=900)

        c_us = insert_contact(
            conn, comp_us, first_name="US", last_name="Person",
            email_status="valid", is_gdpr=False,
        )
        c_eu = insert_contact(
            conn, comp_eu, first_name="EU", last_name="Person",
            email="eu@example.com", email_status="valid", is_gdpr=True,
        )

        for cid in [c_us, c_eu]:
            enroll_contact(conn, cid, campaign, next_action_date=_today())
            # Step 4 is non_gdpr_only email step
            update_contact_campaign_status(
                conn, cid, campaign, status="in_progress", current_step=4
            )

        queue = get_daily_queue(conn, campaign, target_date=_today())
        contact_ids = [q["contact_id"] for q in queue]
        assert c_us in contact_ids  # non-GDPR on non_gdpr_only step => OK
        assert c_eu not in contact_ids  # GDPR on non_gdpr_only step => skip


# ---------------------------------------------------------------------------
# Tests: get_next_step_for_contact
# ---------------------------------------------------------------------------

class TestGetNextStepForContact:
    """Tests for the get_next_step_for_contact function."""

    def test_returns_current_step(self, conn, campaign):
        """Returns the step matching the contact's current_step."""
        comp = insert_company(conn, "Test Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Test", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=2
        )

        step = get_next_step_for_contact(conn, cid, campaign)
        assert step is not None
        assert step["step_order"] == 2
        assert step["channel"] == "linkedin_message"

    def test_returns_none_past_last_step(self, conn, campaign):
        """Returns None when current_step is beyond all sequence steps."""
        comp = insert_company(conn, "Test Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Test", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=99
        )

        step = get_next_step_for_contact(conn, cid, campaign)
        assert step is None

    def test_gdpr_contact_skips_non_gdpr_only_steps(self, conn, campaign):
        """GDPR contacts skip steps marked non_gdpr_only and find the next eligible step."""
        comp = insert_company(conn, "EU Corp", aum_millions=500, is_gdpr=True)
        cid = insert_contact(conn, comp, first_name="EU", last_name="Contact", is_gdpr=True)
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        # Step 4 is non_gdpr_only, so a GDPR contact at step 4 should not get it
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=4
        )

        step = get_next_step_for_contact(conn, cid, campaign)
        # Steps 4 and 5 are both non_gdpr_only, so no eligible step remains
        assert step is None

    def test_non_gdpr_contact_gets_non_gdpr_only_step(self, conn, campaign):
        """Non-GDPR contacts can access non_gdpr_only steps normally."""
        comp = insert_company(conn, "US Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="US", last_name="Contact", is_gdpr=False)
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=4
        )

        step = get_next_step_for_contact(conn, cid, campaign)
        assert step is not None
        assert step["step_order"] == 4

    def test_returns_none_for_unenrolled_contact(self, conn, campaign):
        """Returns None if the contact is not enrolled in the campaign."""
        comp = insert_company(conn, "Test Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Not", last_name="Enrolled")

        step = get_next_step_for_contact(conn, cid, campaign)
        assert step is None

    def test_first_step(self, conn, campaign):
        """Returns step 1 when contact is at current_step=1."""
        comp = insert_company(conn, "Test Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="New", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="queued", current_step=1
        )

        step = get_next_step_for_contact(conn, cid, campaign)
        assert step is not None
        assert step["step_order"] == 1
        assert step["channel"] == "linkedin_connect"

    def test_gdpr_skips_forward(self, conn, campaign):
        """GDPR contact at step 3 gets step 3 (which is not GDPR-restricted)."""
        comp = insert_company(conn, "EU Corp", aum_millions=500, is_gdpr=True)
        cid = insert_contact(conn, comp, first_name="EU", last_name="Contact", is_gdpr=True)
        enroll_contact(conn, cid, campaign, next_action_date=_today())
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=3
        )

        step = get_next_step_for_contact(conn, cid, campaign)
        assert step is not None
        assert step["step_order"] == 3
        assert step["channel"] == "email"


# ---------------------------------------------------------------------------
# Tests: count_steps_for_contact
# ---------------------------------------------------------------------------

class TestCountStepsForContact:
    """Tests for the count_steps_for_contact function."""

    def test_non_gdpr_gets_all_steps(self, conn, campaign):
        """Non-GDPR contacts see all 5 steps."""
        comp = insert_company(conn, "US Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="US", last_name="Contact", is_gdpr=False)

        count = count_steps_for_contact(conn, cid, campaign)
        assert count == 5

    def test_gdpr_excludes_non_gdpr_only_steps(self, conn, campaign):
        """GDPR contacts see 3 steps (steps 4 and 5 are non_gdpr_only)."""
        comp = insert_company(conn, "EU Corp", aum_millions=500, is_gdpr=True)
        cid = insert_contact(conn, comp, first_name="EU", last_name="Contact", is_gdpr=True)

        count = count_steps_for_contact(conn, cid, campaign)
        assert count == 3

    def test_nonexistent_contact_returns_zero(self, conn, campaign):
        """Returns 0 for a contact ID that doesn't exist."""
        count = count_steps_for_contact(conn, 9999, campaign)
        assert count == 0

    def test_with_gdpr_only_steps(self, conn):
        """A campaign with gdpr_only steps: non-GDPR contacts skip them."""
        campaign_id = create_campaign(conn, "gdpr_test_campaign", user_id=TEST_USER_ID)
        t1 = create_template(conn, "t1", "email", "body1", subject="s1", user_id=TEST_USER_ID)
        t2 = create_template(conn, "t2", "email", "body2", subject="s2", user_id=TEST_USER_ID)
        t3 = create_template(conn, "t3", "email", "body3", subject="s3", user_id=TEST_USER_ID)

        add_sequence_step(conn, campaign_id, 1, "email", t1, delay_days=0)
        add_sequence_step(
            conn, campaign_id, 2, "email", t2, delay_days=3, gdpr_only=True
        )
        add_sequence_step(conn, campaign_id, 3, "email", t3, delay_days=5)

        comp = insert_company(conn, "US Corp", aum_millions=500)
        c_us = insert_contact(conn, comp, first_name="US", last_name="Contact", is_gdpr=False)
        comp_eu = insert_company(conn, "EU Corp", aum_millions=500, is_gdpr=True)
        c_eu = insert_contact(
            conn, comp_eu, first_name="EU", last_name="Contact",
            email="eu@example.com", is_gdpr=True,
        )

        # Non-GDPR contact: step 2 (gdpr_only) is skipped => 2 steps
        assert count_steps_for_contact(conn, c_us, campaign_id) == 2
        # GDPR contact: all 3 steps are available
        assert count_steps_for_contact(conn, c_eu, campaign_id) == 3


# ---------------------------------------------------------------------------
# Defer Tests
# ---------------------------------------------------------------------------


class TestDeferContact:
    """Tests for defer_contact() and get_defer_stats()."""

    def test_defer_moves_to_tomorrow(self, tmp_db):
        conn = get_connection(tmp_db)
        run_migrations(conn)

        comp = insert_company(conn, "Defer Corp", aum_millions=100)
        contact = insert_contact(conn, comp, first_name="Deferred", email="defer@test.com")
        campaign_id = create_campaign(conn, "defer_campaign", user_id=TEST_USER_ID)
        t1 = create_template(conn, "t1", "email", "body", user_id=TEST_USER_ID)
        add_sequence_step(conn, campaign_id, 1, "email", t1)
        enroll_contact(conn, contact, campaign_id, next_action_date=_today())

        result = defer_contact(conn, contact, campaign_id, reason="Bad timing")
        assert result["success"] is True
        assert result["next_action_date"] == _tomorrow()
        assert result["reason"] == "Bad timing"

        # Verify next_action_date was updated
        cursor = conn.cursor()
        cursor.execute(
            "SELECT next_action_date FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
            (contact, campaign_id),
        )
        row = cursor.fetchone()
        cursor.close()
        assert str(row["next_action_date"]) == _tomorrow()
        conn.close()

    def test_defer_not_enrolled(self, tmp_db):
        conn = get_connection(tmp_db)
        run_migrations(conn)

        comp = insert_company(conn, "NE Corp")
        contact = insert_contact(conn, comp, email="ne@test.com")
        campaign_id = create_campaign(conn, "ne_campaign", user_id=TEST_USER_ID)

        result = defer_contact(conn, contact, campaign_id)
        assert result["success"] is False
        conn.close()

    def test_defer_logs_event(self, tmp_db):
        conn = get_connection(tmp_db)
        run_migrations(conn)

        comp = insert_company(conn, "Event Corp")
        contact = insert_contact(conn, comp, email="event@test.com")
        campaign_id = create_campaign(conn, "event_campaign", user_id=TEST_USER_ID)
        t1 = create_template(conn, "t1", "email", "body", user_id=TEST_USER_ID)
        add_sequence_step(conn, campaign_id, 1, "email", t1)
        enroll_contact(conn, contact, campaign_id, next_action_date=_today())

        defer_contact(conn, contact, campaign_id, reason="Need more research")

        cursor = conn.cursor()
        cursor.execute(
            "SELECT event_type, notes FROM events WHERE contact_id = %s AND event_type = 'deferred'",
            (contact,),
        )
        event = cursor.fetchone()
        cursor.close()
        assert event is not None
        assert event["notes"] == "Need more research"
        conn.close()

    def test_defer_stats(self, tmp_db):
        conn = get_connection(tmp_db)
        run_migrations(conn)

        comp = insert_company(conn, "Stats Corp")
        c1 = insert_contact(conn, comp, first_name="C1", email="c1@test.com")
        c2 = insert_contact(conn, comp, first_name="C2", email="c2@test.com", priority_rank=2)
        campaign_id = create_campaign(conn, "stats_campaign", user_id=TEST_USER_ID)
        t1 = create_template(conn, "t1", "email", "body", user_id=TEST_USER_ID)
        add_sequence_step(conn, campaign_id, 1, "email", t1)
        enroll_contact(conn, c1, campaign_id, next_action_date=_today())
        enroll_contact(conn, c2, campaign_id, next_action_date=_today())

        defer_contact(conn, c1, campaign_id, reason="Bad timing")
        defer_contact(conn, c2, campaign_id, reason="Bad timing")
        defer_contact(conn, c1, campaign_id, reason="Not relevant now")

        stats = get_defer_stats(conn, campaign_id=campaign_id)
        assert stats["today_count"] >= 2  # at least 2 today
        assert stats["total_count"] == 3
        assert len(stats["by_reason"]) >= 1
        # c1 deferred twice, should show in repeat_deferrals
        assert any(r["contact_id"] == c1 for r in stats["repeat_deferrals"])
        conn.close()
