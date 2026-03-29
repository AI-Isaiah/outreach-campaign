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
from src.application.queue_service import apply_cross_campaign_email_dedup
from src.services.priority_queue import (
    get_daily_queue,
    get_next_step_for_contact,
    count_steps_for_contact,
)
from tests.conftest import insert_company, insert_contact, TEST_USER_ID


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
        conn, "email_cold", "email", "Hello {{first_name}}", subject="Quick intro", user_id=TEST_USER_ID
    )
    t4 = create_template(
        conn, "email_followup", "email", "Following up...", subject="Following up", user_id=TEST_USER_ID
    )
    t5 = create_template(
        conn, "email_breakup", "email", "Last note...", subject="Last note", user_id=TEST_USER_ID
    )

    add_sequence_step(conn, campaign_id, 1, "linkedin_connect", t1, delay_days=0, user_id=TEST_USER_ID)
    add_sequence_step(conn, campaign_id, 2, "linkedin_message", t2, delay_days=3, user_id=TEST_USER_ID)
    add_sequence_step(conn, campaign_id, 3, "email", t3, delay_days=5, user_id=TEST_USER_ID)
    add_sequence_step(
        conn, campaign_id, 4, "email", t4, delay_days=7, non_gdpr_only=True, user_id=TEST_USER_ID
    )
    add_sequence_step(
        conn, campaign_id, 5, "email", t5, delay_days=14, non_gdpr_only=True, user_id=TEST_USER_ID
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
        enroll_contact(conn, contact_id, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        # Set current_step to 1 (linkedin_connect) and status to in_progress
        update_contact_campaign_status(
            conn, contact_id, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)

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
            enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
            update_contact_campaign_status(
                conn, cid, campaign, status="in_progress", current_step=1,
                user_id=TEST_USER_ID,
            )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)

        assert len(queue) == 1
        assert queue[0]["contact_id"] == c1
        assert queue[0]["contact_name"] == "Primary Contact"

    def test_step_ordering_lowest_first(self, conn, campaign):
        """Contacts are ordered by current_step ascending."""
        comp_step3 = insert_company(conn, "Step3 Fund", aum_millions=100)
        comp_step1 = insert_company(conn, "Step1 Fund", aum_millions=5000)
        comp_step2 = insert_company(conn, "Step2 Fund", aum_millions=1000)

        c3 = insert_contact(
            conn, comp_step3, first_name="Step3", last_name="Person",
            email="s3@example.com", email_status="valid",
        )
        enroll_contact(conn, c3, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c3, campaign, status="in_progress", current_step=3,
            user_id=TEST_USER_ID,
        )

        c1 = insert_contact(
            conn, comp_step1, first_name="Step1", last_name="Person",
            email="s1@example.com",
        )
        enroll_contact(conn, c1, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c1, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        c2 = insert_contact(
            conn, comp_step2, first_name="Step2", last_name="Person",
            email="s2@example.com",
        )
        enroll_contact(conn, c2, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c2, campaign, status="in_progress", current_step=2,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), limit=10, user_id=TEST_USER_ID)

        assert len(queue) == 3
        assert queue[0]["step_order"] == 1
        assert queue[0]["company_name"] == "Step1 Fund"
        assert queue[1]["step_order"] == 2
        assert queue[2]["step_order"] == 3

    def test_same_step_ordered_by_action_date(self, conn, campaign):
        """Contacts at the same step are ordered by next_action_date ascending."""
        comp_recent = insert_company(conn, "Recent Fund", aum_millions=500)
        comp_older = insert_company(conn, "Older Fund", aum_millions=None)

        c_recent = insert_contact(
            conn, comp_recent, first_name="Recent", last_name="Contact",
        )
        c_older = insert_contact(
            conn, comp_older, first_name="Older", last_name="Contact",
            email="older@example.com",
        )

        # Enroll with different next_action_dates (both in the past so they're eligible)
        enroll_contact(conn, c_recent, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_recent, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )
        enroll_contact(conn, c_older, campaign, next_action_date=_yesterday(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_older, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)

        assert len(queue) == 2
        # Older action date should come first
        assert queue[0]["contact_name"] == "Older Contact"
        assert queue[1]["contact_name"] == "Recent Contact"

    def test_date_filtering_only_today_or_earlier(self, conn, campaign):
        """Only contacts with next_action_date <= target_date appear."""
        comp = insert_company(conn, "Test Corp", aum_millions=500)

        c_past = insert_contact(
            conn, comp, first_name="Past", last_name="Contact", priority_rank=1
        )
        enroll_contact(conn, c_past, campaign, next_action_date=_yesterday(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_past, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        comp2 = insert_company(conn, "Future Corp", aum_millions=600)
        c_future = insert_contact(
            conn, comp2, first_name="Future", last_name="Contact",
            email="future@example.com",
        )
        enroll_contact(conn, c_future, campaign, next_action_date=_tomorrow(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_future, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)

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
        enroll_contact(conn, c_unverified, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_unverified, campaign, status="in_progress", current_step=3,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
        assert len(queue) == 0

    def test_email_step_includes_valid_email(self, conn, campaign):
        """Contacts on email steps with email_status = 'valid' are included."""
        comp = insert_company(conn, "Valid Corp", aum_millions=500)

        c_valid = insert_contact(
            conn, comp, first_name="Valid", last_name="Email",
            email="good@example.com", email_status="valid",
        )
        enroll_contact(conn, c_valid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_valid, campaign, status="in_progress", current_step=3,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
        assert len(queue) == 1
        assert queue[0]["channel"] == "email"

    def test_linkedin_step_skips_no_linkedin(self, conn, campaign):
        """Contacts on LinkedIn steps without a LinkedIn URL are skipped."""
        comp = insert_company(conn, "NoLI Corp", aum_millions=500)

        c_no_li = insert_contact(
            conn, comp, first_name="NoLI", last_name="Contact",
            linkedin_url=None,
        )
        enroll_contact(conn, c_no_li, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_no_li, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
        assert len(queue) == 0

    def test_linkedin_step_skips_empty_linkedin(self, conn, campaign):
        """Contacts on LinkedIn steps with empty string LinkedIn URL are skipped."""
        comp = insert_company(conn, "EmptyLI Corp", aum_millions=500)

        c_empty_li = insert_contact(
            conn, comp, first_name="EmptyLI", last_name="Contact",
            linkedin_url="",
        )
        enroll_contact(conn, c_empty_li, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_empty_li, campaign, status="in_progress", current_step=2,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
        assert len(queue) == 0

    def test_unsubscribed_contacts_skipped(self, conn, campaign):
        """Unsubscribed contacts are excluded from the queue."""
        comp = insert_company(conn, "Unsub Corp", aum_millions=500)

        c_unsub = insert_contact(
            conn, comp, first_name="Unsub", last_name="Contact",
            unsubscribed=True,
        )
        enroll_contact(conn, c_unsub, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_unsub, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
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
            enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
            update_contact_campaign_status(
                conn, cid, campaign, status="in_progress", current_step=1,
                user_id=TEST_USER_ID,
            )

        queue = get_daily_queue(conn, campaign, target_date=_today(), limit=3, user_id=TEST_USER_ID)
        assert len(queue) == 3

    def test_empty_queue_no_contacts_ready(self, conn, campaign):
        """Returns empty list when no contacts are ready."""
        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
        assert queue == []

    def test_completed_status_excluded(self, conn, campaign):
        """Contacts with status 'completed' are not in the queue."""
        comp = insert_company(conn, "Done Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Done", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="completed", current_step=5,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
        assert len(queue) == 0

    def test_queued_status_included(self, conn, campaign):
        """Contacts with status 'queued' are included in the queue."""
        comp = insert_company(conn, "Queued Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Queued", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="queued", current_step=1,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
        assert len(queue) == 1

    def test_default_target_date_is_today(self, conn, campaign):
        """When target_date is None, defaults to today."""
        comp = insert_company(conn, "Today Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Today", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, user_id=TEST_USER_ID)  # no target_date
        assert len(queue) == 1

    def test_queue_returns_total_steps(self, conn, campaign):
        """Each queue item includes the total steps for that contact."""
        comp = insert_company(conn, "Steps Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Steps", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
        assert len(queue) == 1
        # Non-GDPR contact: all 5 steps are applicable
        assert queue[0]["total_steps"] == 5

    def test_queue_total_steps_gdpr_contact(self, conn, campaign):
        """GDPR contacts get fewer total_steps (non_gdpr_only excluded)."""
        comp = insert_company(conn, "EU Fund", aum_millions=500, is_gdpr=True)
        cid = insert_contact(
            conn, comp, first_name="GDPR", last_name="Contact", is_gdpr=True,
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
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
            enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
            update_contact_campaign_status(
                conn, cid, campaign, status="in_progress", current_step=1,
                user_id=TEST_USER_ID,
            )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
        assert len(queue) == 2
        contact_ids = [q["contact_id"] for q in queue]
        assert ca1 in contact_ids  # lowest rank for Company A
        assert cb1 in contact_ids  # only contact for Company B
        assert ca2 not in contact_ids  # rank 2, skipped

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
            enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
            # Step 4 is non_gdpr_only email step
            update_contact_campaign_status(
                conn, cid, campaign, status="in_progress", current_step=4,
                user_id=TEST_USER_ID,
            )

        queue = get_daily_queue(conn, campaign, target_date=_today(), user_id=TEST_USER_ID)
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
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=2,
            user_id=TEST_USER_ID,
        )

        step = get_next_step_for_contact(conn, cid, campaign)
        assert step is not None
        assert step["step_order"] == 2
        assert step["channel"] == "linkedin_message"

    def test_returns_none_past_last_step(self, conn, campaign):
        """Returns None when current_step is beyond all sequence steps."""
        comp = insert_company(conn, "Test Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Test", last_name="Contact")
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=99,
            user_id=TEST_USER_ID,
        )

        step = get_next_step_for_contact(conn, cid, campaign)
        assert step is None

    def test_gdpr_contact_skips_non_gdpr_only_steps(self, conn, campaign):
        """GDPR contacts skip steps marked non_gdpr_only and find the next eligible step."""
        comp = insert_company(conn, "EU Corp", aum_millions=500, is_gdpr=True)
        cid = insert_contact(conn, comp, first_name="EU", last_name="Contact", is_gdpr=True)
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        # Step 4 is non_gdpr_only, so a GDPR contact at step 4 should not get it
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=4,
            user_id=TEST_USER_ID,
        )

        step = get_next_step_for_contact(conn, cid, campaign)
        # Steps 4 and 5 are both non_gdpr_only, so no eligible step remains
        assert step is None

    def test_non_gdpr_contact_gets_non_gdpr_only_step(self, conn, campaign):
        """Non-GDPR contacts can access non_gdpr_only steps normally."""
        comp = insert_company(conn, "US Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="US", last_name="Contact", is_gdpr=False)
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=4,
            user_id=TEST_USER_ID,
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
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="queued", current_step=1,
            user_id=TEST_USER_ID,
        )

        step = get_next_step_for_contact(conn, cid, campaign)
        assert step is not None
        assert step["step_order"] == 1
        assert step["channel"] == "linkedin_connect"

    def test_gdpr_skips_forward(self, conn, campaign):
        """GDPR contact at step 3 gets step 3 (which is not GDPR-restricted)."""
        comp = insert_company(conn, "EU Corp", aum_millions=500, is_gdpr=True)
        cid = insert_contact(conn, comp, first_name="EU", last_name="Contact", is_gdpr=True)
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=3,
            user_id=TEST_USER_ID,
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

        add_sequence_step(conn, campaign_id, 1, "email", t1, delay_days=0, user_id=TEST_USER_ID)
        add_sequence_step(
            conn, campaign_id, 2, "email", t2, delay_days=3, gdpr_only=True, user_id=TEST_USER_ID
        )
        add_sequence_step(conn, campaign_id, 3, "email", t3, delay_days=5, user_id=TEST_USER_ID)

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
# Tests: email dedup (same-email override)
# ---------------------------------------------------------------------------

class TestCrossCampaignEmailDedup:
    """Tests for cross-campaign email dedup.

    When the same contact is enrolled in multiple campaigns and both have
    email steps due today, only the first (earliest step) keeps the email
    channel. The cross-campaign dedup happens in the /queue/all route, not
    in get_daily_queue() (which is per-campaign).

    Note: within a single user, the UNIQUE(user_id, email_normalized) constraint
    on contacts prevents two different contacts from sharing an email. So the
    dedup scenario is: the SAME contact enrolled in multiple campaigns.
    """

    def _setup_simple_email_campaign(self, conn, name):
        """Create a simple campaign with one email step."""
        campaign_id = create_campaign(conn, name, user_id=TEST_USER_ID)
        tmpl = create_template(
            conn, f"{name}_email", "email", "Hello {{first_name}}",
            subject=f"{name} subject", user_id=TEST_USER_ID,
        )
        add_sequence_step(conn, campaign_id, 1, "email", tmpl, delay_days=0, user_id=TEST_USER_ID)
        return campaign_id

    def test_same_contact_two_campaigns_deduped(self, conn):
        """Same contact in two campaigns: only first email item kept, second overridden."""
        camp_a = self._setup_simple_email_campaign(conn, "campaign_a")
        camp_b = self._setup_simple_email_campaign(conn, "campaign_b")

        comp = insert_company(conn, "Test Fund", aum_millions=1000)
        contact_id = insert_contact(
            conn, comp, first_name="Alice", last_name="Smith",
            email="alice@testfund.com", email_status="valid",
        )

        for camp_id in [camp_a, camp_b]:
            enroll_contact(conn, contact_id, camp_id, next_action_date=_today(), user_id=TEST_USER_ID)
            update_contact_campaign_status(
                conn, contact_id, camp_id, status="in_progress", current_step=1,
                user_id=TEST_USER_ID,
            )

        items_a = get_daily_queue(conn, camp_a, target_date=_today(), user_id=TEST_USER_ID)
        items_b = get_daily_queue(conn, camp_b, target_date=_today(), user_id=TEST_USER_ID)
        assert items_a[0]["channel"] == "email"
        assert items_b[0]["channel"] == "email"

        merged = sorted(items_a + items_b, key=lambda x: x.get("step_order", 0))
        result = apply_cross_campaign_email_dedup(merged)

        assert result[0]["channel"] == "email"
        assert result[1]["channel"] == "linkedin_only"
        assert result[1].get("email_dedup_override") is True

    def test_different_contacts_no_dedup(self, conn):
        """Different contacts in two campaigns: no dedup needed."""
        camp_a = self._setup_simple_email_campaign(conn, "camp_no_dedup_a")
        camp_b = self._setup_simple_email_campaign(conn, "camp_no_dedup_b")

        comp_a = insert_company(conn, "Fund A Dedup", aum_millions=1000)
        comp_b = insert_company(conn, "Fund B Dedup", aum_millions=900)

        c_a = insert_contact(conn, comp_a, first_name="Alice", last_name="A",
                             email="alice@fund-a-dedup.com", email_status="valid")
        c_b = insert_contact(conn, comp_b, first_name="Bob", last_name="B",
                             email="bob@fund-b-dedup.com", email_status="valid")

        enroll_contact(conn, c_a, camp_a, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(conn, c_a, camp_a, status="in_progress", current_step=1, user_id=TEST_USER_ID)
        enroll_contact(conn, c_b, camp_b, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(conn, c_b, camp_b, status="in_progress", current_step=1, user_id=TEST_USER_ID)

        items_a = get_daily_queue(conn, camp_a, target_date=_today(), user_id=TEST_USER_ID)
        items_b = get_daily_queue(conn, camp_b, target_date=_today(), user_id=TEST_USER_ID)
        result = apply_cross_campaign_email_dedup(items_a + items_b)

        assert all(item["channel"] == "email" for item in result)

    def test_linkedin_steps_not_deduped(self, conn):
        """LinkedIn steps are not affected by email dedup."""
        camp_a = create_campaign(conn, "li_camp_a", user_id=TEST_USER_ID)
        camp_b = create_campaign(conn, "li_camp_b", user_id=TEST_USER_ID)
        tmpl = create_template(conn, "li_tmpl_dedup", "linkedin_connect", "Hi", user_id=TEST_USER_ID)
        add_sequence_step(conn, camp_a, 1, "linkedin_connect", tmpl, delay_days=0, user_id=TEST_USER_ID)
        add_sequence_step(conn, camp_b, 1, "linkedin_connect", tmpl, delay_days=0, user_id=TEST_USER_ID)

        comp = insert_company(conn, "LI Fund Dedup", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="LI", last_name="Person")

        for camp_id in [camp_a, camp_b]:
            enroll_contact(conn, cid, camp_id, next_action_date=_today(), user_id=TEST_USER_ID)
            update_contact_campaign_status(conn, cid, camp_id, status="in_progress", current_step=1, user_id=TEST_USER_ID)

        items_a = get_daily_queue(conn, camp_a, target_date=_today(), user_id=TEST_USER_ID)
        items_b = get_daily_queue(conn, camp_b, target_date=_today(), user_id=TEST_USER_ID)
        result = apply_cross_campaign_email_dedup(items_a + items_b)

        assert all(item["channel"] == "linkedin_connect" for item in result)

    def test_single_campaign_contact_no_dedup(self, conn):
        """Contact in only one campaign: no dedup applied."""
        camp = self._setup_simple_email_campaign(conn, "single_camp_dedup")
        comp = insert_company(conn, "Solo Fund Dedup", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Solo", last_name="Contact",
                             email="solo@unique-dedup.com", email_status="valid")
        enroll_contact(conn, cid, camp, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(conn, cid, camp, status="in_progress", current_step=1, user_id=TEST_USER_ID)

        items = get_daily_queue(conn, camp, target_date=_today(), user_id=TEST_USER_ID)
        result = apply_cross_campaign_email_dedup(items)

        assert len(result) == 1
        assert result[0]["channel"] == "email"
        assert result[0].get("email_dedup_override") is None
