"""Tests for campaign metrics, variant comparison, weekly summary, firm type
breakdown, and weekly plan generation."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.models.database import get_connection, run_migrations
from src.models.campaigns import (
    create_campaign,
    enroll_contact,
    log_event,
    update_contact_campaign_status,
)
from src.services.metrics import (
    get_campaign_metrics,
    get_variant_comparison,
    get_weekly_summary,
    get_company_type_breakdown,
)
from src.commands.weekly_plan import generate_weekly_plan
from tests.conftest import TEST_USER_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db(db_path):
    """Return a connection with migrations applied."""
    conn = get_connection(db_path)
    run_migrations(conn)
    return conn


def _create_company(conn, name="Acme Fund", firm_type="Hedge Fund"):
    """Insert a company and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO companies (name, name_normalized, firm_type, user_id) VALUES (%s, %s, %s, %s) RETURNING id",
        (name, name.lower(), firm_type, TEST_USER_ID),
    )
    company_id = cursor.fetchone()["id"]
    conn.commit()
    return company_id


def _create_contact(conn, company_id, priority_rank=1, email=None):
    """Insert a contact and return its id."""
    email = email or f"contact{priority_rank}@example.com"
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO contacts (company_id, priority_rank, email, email_normalized, "
        "first_name, last_name, full_name, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (company_id, priority_rank, email, email.lower(),
         f"First{priority_rank}", f"Last{priority_rank}",
         f"First{priority_rank} Last{priority_rank}", TEST_USER_ID),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    return contact_id


def _create_campaign(conn, name="Q1 Outreach"):
    """Insert a campaign and return its id."""
    return create_campaign(conn, name, user_id=TEST_USER_ID)


def _enroll(conn, contact_id, campaign_id, variant=None):
    """Enroll a contact in a campaign with optional variant."""
    return enroll_contact(
        conn, contact_id, campaign_id,
        variant=variant,
        next_action_date=date.today().isoformat(),
        user_id=TEST_USER_ID,
    )


def _set_status(conn, contact_id, campaign_id, status):
    """Directly set a contact's campaign status."""
    update_contact_campaign_status(conn, contact_id, campaign_id, status=status, user_id=TEST_USER_ID)


def _log_event(conn, contact_id, event_type, campaign_id, created_at=None):
    """Log an event, optionally with a specific created_at timestamp."""
    event_id = log_event(conn, contact_id, event_type, campaign_id=campaign_id, user_id=TEST_USER_ID)
    if created_at is not None:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE events SET created_at = %s WHERE id = %s",
            (created_at, event_id),
        )
        conn.commit()
    return event_id


# ---------------------------------------------------------------------------
# Tests: get_campaign_metrics
# ---------------------------------------------------------------------------

class TestGetCampaignMetrics:
    def test_basic_counts(self, tmp_db):
        """Metrics return correct status counts and totals."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1, email="a@ex.com")
        c2 = _create_contact(conn, company_id, priority_rank=2, email="b@ex.com")
        c3 = _create_contact(conn, company_id, priority_rank=3, email="c@ex.com")
        campaign_id = _create_campaign(conn)

        _enroll(conn, c1, campaign_id)
        _enroll(conn, c2, campaign_id)
        _enroll(conn, c3, campaign_id)

        _set_status(conn, c1, campaign_id, "in_progress")
        _set_status(conn, c2, campaign_id, "replied_positive")
        # c3 stays queued

        metrics = get_campaign_metrics(conn, campaign_id, user_id=TEST_USER_ID)

        assert metrics["total_enrolled"] == 3
        assert metrics["by_status"]["queued"] == 1
        assert metrics["by_status"]["in_progress"] == 1
        assert metrics["by_status"]["replied_positive"] == 1
        assert metrics["by_status"]["replied_negative"] == 0
        assert metrics["by_status"]["no_response"] == 0
        assert metrics["by_status"]["bounced"] == 0
        conn.close()

    def test_event_counts(self, tmp_db):
        """Metrics count events correctly."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="x@ex.com")
        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id)

        log_event(conn, c1, "email_sent", campaign_id=campaign_id, user_id=TEST_USER_ID)
        log_event(conn, c1, "email_sent", campaign_id=campaign_id, user_id=TEST_USER_ID)
        log_event(conn, c1, "expandi_connected", campaign_id=campaign_id, user_id=TEST_USER_ID)
        log_event(conn, c1, "expandi_message_sent", campaign_id=campaign_id, user_id=TEST_USER_ID)
        log_event(conn, c1, "call_booked", campaign_id=campaign_id, user_id=TEST_USER_ID)

        metrics = get_campaign_metrics(conn, campaign_id, user_id=TEST_USER_ID)

        assert metrics["emails_sent"] == 2
        assert metrics["linkedin_connects"] == 1
        assert metrics["linkedin_messages"] == 1
        assert metrics["calls_booked"] == 1
        conn.close()

    def test_reply_rate_calculation(self, tmp_db):
        """Reply rate = (positive + negative) / non-queued."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)

        contacts = []
        for i in range(5):
            c = _create_contact(conn, company_id, priority_rank=i + 1,
                                email=f"user{i}@ex.com")
            contacts.append(c)

        campaign_id = _create_campaign(conn)

        for c in contacts:
            _enroll(conn, c, campaign_id)

        # c0: replied_positive, c1: replied_negative, c2: no_response,
        # c3: in_progress, c4: queued
        _set_status(conn, contacts[0], campaign_id, "replied_positive")
        _set_status(conn, contacts[1], campaign_id, "replied_negative")
        _set_status(conn, contacts[2], campaign_id, "no_response")
        _set_status(conn, contacts[3], campaign_id, "in_progress")
        # contacts[4] stays queued

        metrics = get_campaign_metrics(conn, campaign_id, user_id=TEST_USER_ID)

        # non-queued = 5 - 1 = 4
        # replies = 1 + 1 = 2
        # reply_rate = 2/4 = 0.5
        assert metrics["reply_rate"] == 0.5
        # positive_rate = 1/4 = 0.25
        assert metrics["positive_rate"] == 0.25
        conn.close()

    def test_reply_rate_all_queued(self, tmp_db):
        """Reply rate is 0.0 when all contacts are queued (avoids division by zero)."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="q@ex.com")
        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id)

        metrics = get_campaign_metrics(conn, campaign_id, user_id=TEST_USER_ID)

        assert metrics["reply_rate"] == 0.0
        assert metrics["positive_rate"] == 0.0
        conn.close()

    def test_empty_campaign(self, tmp_db):
        """Empty campaign returns all zeros."""
        conn = _setup_db(tmp_db)
        campaign_id = _create_campaign(conn)

        metrics = get_campaign_metrics(conn, campaign_id, user_id=TEST_USER_ID)

        assert metrics["total_enrolled"] == 0
        assert metrics["emails_sent"] == 0
        assert metrics["linkedin_connects"] == 0
        assert metrics["linkedin_messages"] == 0
        assert metrics["calls_booked"] == 0
        assert metrics["reply_rate"] == 0.0
        assert metrics["positive_rate"] == 0.0
        assert all(v == 0 for v in metrics["by_status"].values())
        conn.close()

    def test_events_from_other_campaigns_not_counted(self, tmp_db):
        """Events for a different campaign are not counted."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="z@ex.com")
        camp_a = _create_campaign(conn, "Campaign A")
        camp_b = _create_campaign(conn, "Campaign B")

        _enroll(conn, c1, camp_a)
        log_event(conn, c1, "email_sent", campaign_id=camp_b, user_id=TEST_USER_ID)

        metrics = get_campaign_metrics(conn, camp_a, user_id=TEST_USER_ID)
        assert metrics["emails_sent"] == 0
        conn.close()


# ---------------------------------------------------------------------------
# Tests: get_variant_comparison
# ---------------------------------------------------------------------------

class TestGetVariantComparison:
    def test_basic_variant_breakdown(self, tmp_db):
        """Variant comparison returns correct per-variant stats."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)

        contacts_a = []
        contacts_b = []
        for i in range(3):
            c = _create_contact(conn, company_id, priority_rank=i + 1,
                                email=f"a{i}@ex.com")
            contacts_a.append(c)
        for i in range(3):
            c = _create_contact(conn, company_id, priority_rank=i + 4,
                                email=f"b{i}@ex.com")
            contacts_b.append(c)

        campaign_id = _create_campaign(conn)

        for c in contacts_a:
            _enroll(conn, c, campaign_id, variant="A")
        for c in contacts_b:
            _enroll(conn, c, campaign_id, variant="B")

        # Variant A: 1 positive, 1 negative, 1 no_response
        _set_status(conn, contacts_a[0], campaign_id, "replied_positive")
        _set_status(conn, contacts_a[1], campaign_id, "replied_negative")
        _set_status(conn, contacts_a[2], campaign_id, "no_response")

        # Variant B: 2 positive, 0 negative, 1 no_response
        _set_status(conn, contacts_b[0], campaign_id, "replied_positive")
        _set_status(conn, contacts_b[1], campaign_id, "replied_positive")
        _set_status(conn, contacts_b[2], campaign_id, "no_response")

        variants = get_variant_comparison(conn, campaign_id, user_id=TEST_USER_ID)

        assert len(variants) == 2

        var_a = next(v for v in variants if v["variant"] == "A")
        var_b = next(v for v in variants if v["variant"] == "B")

        assert var_a["total"] == 3
        assert var_a["replied_positive"] == 1
        assert var_a["replied_negative"] == 1
        assert var_a["no_response"] == 1
        # reply_rate = 2/3 (all non-queued)
        assert abs(var_a["reply_rate"] - 2 / 3) < 0.01
        assert abs(var_a["positive_rate"] - 1 / 3) < 0.01

        assert var_b["total"] == 3
        assert var_b["replied_positive"] == 2
        assert var_b["replied_negative"] == 0
        assert var_b["no_response"] == 1
        # reply_rate = 2/3
        assert abs(var_b["reply_rate"] - 2 / 3) < 0.01
        # positive_rate = 2/3
        assert abs(var_b["positive_rate"] - 2 / 3) < 0.01
        conn.close()

    def test_empty_variants(self, tmp_db):
        """Campaign with no variant assignments returns empty list."""
        conn = _setup_db(tmp_db)
        campaign_id = _create_campaign(conn)

        variants = get_variant_comparison(conn, campaign_id, user_id=TEST_USER_ID)
        assert variants == []
        conn.close()

    def test_null_variants_excluded(self, tmp_db):
        """Contacts with NULL variant are excluded from comparison."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="null@ex.com")
        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id, variant=None)

        variants = get_variant_comparison(conn, campaign_id, user_id=TEST_USER_ID)
        assert variants == []
        conn.close()

    def test_variant_with_queued_contacts(self, tmp_db):
        """Queued contacts are excluded from reply rate denominator."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1, email="v1@ex.com")
        c2 = _create_contact(conn, company_id, priority_rank=2, email="v2@ex.com")
        campaign_id = _create_campaign(conn)

        _enroll(conn, c1, campaign_id, variant="A")
        _enroll(conn, c2, campaign_id, variant="A")

        # c1: replied_positive, c2: queued
        _set_status(conn, c1, campaign_id, "replied_positive")

        variants = get_variant_comparison(conn, campaign_id, user_id=TEST_USER_ID)
        assert len(variants) == 1

        var_a = variants[0]
        assert var_a["total"] == 2
        # non-queued = 1 (only c1)
        # reply_rate = 1/1 = 1.0
        assert var_a["reply_rate"] == 1.0
        assert var_a["positive_rate"] == 1.0
        conn.close()


# ---------------------------------------------------------------------------
# Tests: get_weekly_summary
# ---------------------------------------------------------------------------

class TestGetWeeklySummary:
    def test_filters_by_date_range(self, tmp_db):
        """Only events within the time window are counted."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="wk@ex.com")
        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id)

        today = date.today()
        yesterday = (today - timedelta(days=1)).isoformat() + " 12:00:00"
        two_weeks_ago = (today - timedelta(days=14)).isoformat() + " 12:00:00"

        # Events within last week
        _log_event(conn, c1, "email_sent", campaign_id, created_at=yesterday)
        _log_event(conn, c1, "status_replied_positive", campaign_id,
                   created_at=yesterday)
        _log_event(conn, c1, "call_booked", campaign_id, created_at=yesterday)

        # Events outside the window (two weeks ago)
        _log_event(conn, c1, "email_sent", campaign_id,
                   created_at=two_weeks_ago)
        _log_event(conn, c1, "expandi_connected", campaign_id,
                   created_at=two_weeks_ago)

        summary = get_weekly_summary(conn, campaign_id, weeks_back=1, user_id=TEST_USER_ID)

        assert summary["emails_sent"] == 1
        assert summary["replies_positive"] == 1
        assert summary["calls_booked"] == 1
        # The old events should not be counted
        assert summary["linkedin_actions"] == 0
        conn.close()

    def test_wider_window(self, tmp_db):
        """weeks_back=2 captures events from the past 14 days."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="wide@ex.com")
        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id)

        today = date.today()
        ten_days_ago = (today - timedelta(days=10)).isoformat() + " 12:00:00"

        _log_event(conn, c1, "email_sent", campaign_id, created_at=ten_days_ago)

        # weeks_back=1 should NOT capture this
        summary_1 = get_weekly_summary(conn, campaign_id, weeks_back=1, user_id=TEST_USER_ID)
        assert summary_1["emails_sent"] == 0

        # weeks_back=2 should capture it
        summary_2 = get_weekly_summary(conn, campaign_id, weeks_back=2, user_id=TEST_USER_ID)
        assert summary_2["emails_sent"] == 1
        conn.close()

    def test_linkedin_actions_combined(self, tmp_db):
        """linkedin_actions sums expandi_connected and expandi_message_sent."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="li@ex.com")
        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id)

        today = date.today()
        recent = (today - timedelta(days=1)).isoformat() + " 12:00:00"

        _log_event(conn, c1, "expandi_connected", campaign_id, created_at=recent)
        _log_event(conn, c1, "expandi_message_sent", campaign_id, created_at=recent)
        _log_event(conn, c1, "expandi_message_sent", campaign_id, created_at=recent)

        summary = get_weekly_summary(conn, campaign_id, weeks_back=1, user_id=TEST_USER_ID)
        assert summary["linkedin_actions"] == 3
        conn.close()

    def test_empty_period(self, tmp_db):
        """No events in the period returns zeros."""
        conn = _setup_db(tmp_db)
        campaign_id = _create_campaign(conn)

        summary = get_weekly_summary(conn, campaign_id, weeks_back=1, user_id=TEST_USER_ID)

        assert summary["emails_sent"] == 0
        assert summary["linkedin_actions"] == 0
        assert summary["replies_positive"] == 0
        assert summary["replies_negative"] == 0
        assert summary["calls_booked"] == 0
        assert summary["new_no_response"] == 0
        conn.close()

    def test_period_string_format(self, tmp_db):
        """Period string is formatted as 'YYYY-MM-DD to YYYY-MM-DD'."""
        conn = _setup_db(tmp_db)
        campaign_id = _create_campaign(conn)

        summary = get_weekly_summary(conn, campaign_id, weeks_back=1, user_id=TEST_USER_ID)

        today = date.today()
        start = today - timedelta(days=7)
        expected_period = f"{start.isoformat()} to {today.isoformat()}"
        assert summary["period"] == expected_period
        conn.close()


# ---------------------------------------------------------------------------
# Tests: get_company_type_breakdown
# ---------------------------------------------------------------------------

class TestGetCompanyTypeBreakdown:
    def test_groups_by_firm_type(self, tmp_db):
        """Breakdown groups contacts by their company's firm_type."""
        conn = _setup_db(tmp_db)
        hf_company = _create_company(conn, "Alpha Fund", firm_type="Hedge Fund")
        vc_company = _create_company(conn, "Beta Capital", firm_type="Venture Capital")

        c1 = _create_contact(conn, hf_company, priority_rank=1, email="hf1@ex.com")
        c2 = _create_contact(conn, hf_company, priority_rank=2, email="hf2@ex.com")
        c3 = _create_contact(conn, vc_company, priority_rank=1, email="vc1@ex.com")

        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id)
        _enroll(conn, c2, campaign_id)
        _enroll(conn, c3, campaign_id)

        _set_status(conn, c1, campaign_id, "replied_positive")
        _set_status(conn, c2, campaign_id, "no_response")
        _set_status(conn, c3, campaign_id, "replied_positive")

        breakdown = get_company_type_breakdown(conn, campaign_id, user_id=TEST_USER_ID)

        assert len(breakdown) == 2

        vc = next(b for b in breakdown if b["firm_type"] == "Venture Capital")
        hf = next(b for b in breakdown if b["firm_type"] == "Hedge Fund")

        assert vc["total"] == 1
        assert vc["replied_positive"] == 1
        assert vc["reply_rate"] == 1.0
        assert vc["positive_rate"] == 1.0

        assert hf["total"] == 2
        assert hf["replied_positive"] == 1
        assert hf["no_response"] == 1
        assert hf["reply_rate"] == 0.5
        assert hf["positive_rate"] == 0.5
        conn.close()

    def test_sorted_by_reply_rate_descending(self, tmp_db):
        """Results are sorted by reply_rate descending."""
        conn = _setup_db(tmp_db)
        co_a = _create_company(conn, "Fund A", firm_type="Type A")
        co_b = _create_company(conn, "Fund B", firm_type="Type B")

        c_a = _create_contact(conn, co_a, priority_rank=1, email="ta@ex.com")
        c_b = _create_contact(conn, co_b, priority_rank=1, email="tb@ex.com")

        campaign_id = _create_campaign(conn)
        _enroll(conn, c_a, campaign_id)
        _enroll(conn, c_b, campaign_id)

        _set_status(conn, c_a, campaign_id, "no_response")  # reply_rate = 0
        _set_status(conn, c_b, campaign_id, "replied_positive")  # reply_rate = 1

        breakdown = get_company_type_breakdown(conn, campaign_id, user_id=TEST_USER_ID)

        assert breakdown[0]["firm_type"] == "Type B"
        assert breakdown[1]["firm_type"] == "Type A"
        conn.close()

    def test_null_firm_type_becomes_unknown(self, tmp_db):
        """Companies with NULL firm_type are grouped under 'Unknown'."""
        conn = _setup_db(tmp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO companies (name, name_normalized, user_id) VALUES (%s, %s, %s) RETURNING id",
            ("No Type Inc", "no type inc", TEST_USER_ID),
        )
        company_id = cursor.fetchone()["id"]
        conn.commit()

        c1 = _create_contact(conn, company_id, email="nt@ex.com")
        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id)
        _set_status(conn, c1, campaign_id, "replied_positive")

        breakdown = get_company_type_breakdown(conn, campaign_id, user_id=TEST_USER_ID)

        assert len(breakdown) == 1
        assert breakdown[0]["firm_type"] == "Unknown"
        conn.close()

    def test_empty_campaign_returns_empty(self, tmp_db):
        """Empty campaign returns empty breakdown."""
        conn = _setup_db(tmp_db)
        campaign_id = _create_campaign(conn)

        breakdown = get_company_type_breakdown(conn, campaign_id, user_id=TEST_USER_ID)
        assert breakdown == []
        conn.close()

    def test_queued_excluded_from_reply_rate_denominator(self, tmp_db):
        """Queued contacts don't inflate the denominator."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn, "Queue Fund", firm_type="Family Office")
        c1 = _create_contact(conn, company_id, priority_rank=1, email="q1@ex.com")
        c2 = _create_contact(conn, company_id, priority_rank=2, email="q2@ex.com")

        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id)
        _enroll(conn, c2, campaign_id)

        _set_status(conn, c1, campaign_id, "replied_positive")
        # c2 stays queued

        breakdown = get_company_type_breakdown(conn, campaign_id, user_id=TEST_USER_ID)
        assert len(breakdown) == 1

        fo = breakdown[0]
        assert fo["total"] == 2
        # non-queued = 1, positive = 1 -> positive_rate = 1.0
        assert fo["positive_rate"] == 1.0
        assert fo["reply_rate"] == 1.0
        conn.close()


# ---------------------------------------------------------------------------
# Tests: generate_weekly_plan
# ---------------------------------------------------------------------------

class TestGenerateWeeklyPlan:
    def test_returns_all_sections(self, tmp_db):
        """Weekly plan returns all expected top-level keys."""
        conn = _setup_db(tmp_db)
        _create_campaign(conn, "Test Campaign")

        plan = generate_weekly_plan(conn, "Test Campaign")

        assert "campaign" in plan
        assert "last_week" in plan
        assert "overall" in plan
        assert "variant_comparison" in plan
        assert "company_type_breakdown" in plan
        assert "proposed_next_week" in plan
        assert "newsletter_recommendation" in plan
        assert "next_actions" in plan
        conn.close()

    def test_campaign_not_found_raises(self, tmp_db):
        """Requesting a nonexistent campaign raises ValueError."""
        conn = _setup_db(tmp_db)

        with pytest.raises(ValueError, match="not found"):
            generate_weekly_plan(conn, "Nonexistent")
        conn.close()

    def test_campaign_info(self, tmp_db):
        """Campaign section contains id, name, and status."""
        conn = _setup_db(tmp_db)
        campaign_id = _create_campaign(conn, "My Campaign")

        plan = generate_weekly_plan(conn, "My Campaign")

        assert plan["campaign"]["id"] == campaign_id
        assert plan["campaign"]["name"] == "My Campaign"
        assert plan["campaign"]["status"] == "active"
        conn.close()

    def test_empty_campaign_plan(self, tmp_db):
        """Plan for empty campaign returns zero metrics and default actions."""
        conn = _setup_db(tmp_db)
        _create_campaign(conn, "Empty")

        plan = generate_weekly_plan(conn, "Empty")

        assert plan["overall"]["total_enrolled"] == 0
        assert plan["last_week"]["emails_sent"] == 0
        assert plan["variant_comparison"] == []
        assert plan["company_type_breakdown"] == []
        assert plan["proposed_next_week"]["contacts_ready"] == 0
        assert plan["proposed_next_week"]["channel_mix"] == {}
        conn.close()

    def test_newsletter_recommendation_positive_replies(self, tmp_db):
        """Newsletter recommended when positive replies exist."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="nr@ex.com")
        campaign_id = _create_campaign(conn, "NL Test")

        _enroll(conn, c1, campaign_id)
        _set_status(conn, c1, campaign_id, "replied_positive")

        plan = generate_weekly_plan(conn, "NL Test")

        assert plan["newsletter_recommendation"]["recommend"] is True
        assert "positive" in plan["newsletter_recommendation"]["reason"].lower() or \
               "nurture" in plan["newsletter_recommendation"]["reason"].lower()
        conn.close()

    def test_newsletter_recommendation_no_replies(self, tmp_db):
        """Newsletter not recommended when no positive replies and low no-response rate."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="nopl@ex.com")
        campaign_id = _create_campaign(conn, "NL No")

        _enroll(conn, c1, campaign_id)
        _set_status(conn, c1, campaign_id, "in_progress")

        plan = generate_weekly_plan(conn, "NL No")

        assert plan["newsletter_recommendation"]["recommend"] is False
        conn.close()

    def test_newsletter_recommendation_high_no_response(self, tmp_db):
        """Newsletter recommended when no-response rate >= 30%."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)

        contacts = []
        for i in range(10):
            c = _create_contact(conn, company_id, priority_rank=i + 1,
                                email=f"nr{i}@ex.com")
            contacts.append(c)

        campaign_id = _create_campaign(conn, "NL NR")

        for c in contacts:
            _enroll(conn, c, campaign_id)

        # 4 no_response, 6 in_progress -> 40% no_response rate
        for c in contacts[:4]:
            _set_status(conn, c, campaign_id, "no_response")
        for c in contacts[4:]:
            _set_status(conn, c, campaign_id, "in_progress")

        plan = generate_weekly_plan(conn, "NL NR")

        assert plan["newsletter_recommendation"]["recommend"] is True
        assert "no response" in plan["newsletter_recommendation"]["reason"].lower() or \
               "re-engage" in plan["newsletter_recommendation"]["reason"].lower()
        conn.close()

    def test_proposed_next_week_counts_ready_contacts(self, tmp_db):
        """Proposed next week correctly counts contacts ready for action."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1, email="rdy1@ex.com")
        c2 = _create_contact(conn, company_id, priority_rank=2, email="rdy2@ex.com")
        campaign_id = _create_campaign(conn, "Ready Test")

        _enroll(conn, c1, campaign_id)
        _enroll(conn, c2, campaign_id)

        plan = generate_weekly_plan(conn, "Ready Test")

        assert plan["proposed_next_week"]["contacts_ready"] == 2
        conn.close()

    def test_next_actions_not_empty(self, tmp_db):
        """Next actions list is never empty."""
        conn = _setup_db(tmp_db)
        _create_campaign(conn, "Actions Test")

        plan = generate_weekly_plan(conn, "Actions Test")

        assert len(plan["next_actions"]) >= 1
        conn.close()

    def test_next_actions_with_ready_contacts(self, tmp_db):
        """Next actions include processing ready contacts when available."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="act@ex.com")
        campaign_id = _create_campaign(conn, "Action Ready")

        # Add a sequence step so channel_mix can be computed
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sequence_steps (campaign_id, step_order, channel, delay_days) "
            "VALUES (%s, 1, 'email', 0)",
            (campaign_id,),
        )
        conn.commit()

        _enroll(conn, c1, campaign_id)

        plan = generate_weekly_plan(conn, "Action Ready")

        action_text = " ".join(plan["next_actions"])
        assert "1 contact" in action_text.lower() or "process" in action_text.lower()
        conn.close()


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_metrics_with_bounced_status(self, tmp_db):
        """Bounced contacts are counted correctly."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="bounce@ex.com")
        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id)
        _set_status(conn, c1, campaign_id, "bounced")

        metrics = get_campaign_metrics(conn, campaign_id, user_id=TEST_USER_ID)

        assert metrics["by_status"]["bounced"] == 1
        assert metrics["total_enrolled"] == 1
        # non-queued = 1, replies = 0
        assert metrics["reply_rate"] == 0.0
        conn.close()

    def test_multiple_campaigns_isolated(self, tmp_db):
        """Metrics for one campaign do not leak into another."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1, email="iso1@ex.com")
        c2 = _create_contact(conn, company_id, priority_rank=2, email="iso2@ex.com")

        camp_a = _create_campaign(conn, "Camp A")
        camp_b = _create_campaign(conn, "Camp B")

        _enroll(conn, c1, camp_a)
        _enroll(conn, c2, camp_b)

        _set_status(conn, c1, camp_a, "replied_positive")
        _set_status(conn, c2, camp_b, "no_response")

        metrics_a = get_campaign_metrics(conn, camp_a, user_id=TEST_USER_ID)
        metrics_b = get_campaign_metrics(conn, camp_b, user_id=TEST_USER_ID)

        assert metrics_a["total_enrolled"] == 1
        assert metrics_a["by_status"]["replied_positive"] == 1
        assert metrics_a["by_status"]["no_response"] == 0

        assert metrics_b["total_enrolled"] == 1
        assert metrics_b["by_status"]["replied_positive"] == 0
        assert metrics_b["by_status"]["no_response"] == 1
        conn.close()

    def test_variant_comparison_with_mixed_variants(self, tmp_db):
        """Contacts with NULL and non-NULL variants are handled correctly."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, priority_rank=1, email="mix1@ex.com")
        c2 = _create_contact(conn, company_id, priority_rank=2, email="mix2@ex.com")
        c3 = _create_contact(conn, company_id, priority_rank=3, email="mix3@ex.com")

        campaign_id = _create_campaign(conn)

        _enroll(conn, c1, campaign_id, variant="A")
        _enroll(conn, c2, campaign_id, variant=None)
        _enroll(conn, c3, campaign_id, variant="B")

        _set_status(conn, c1, campaign_id, "replied_positive")
        _set_status(conn, c2, campaign_id, "no_response")
        _set_status(conn, c3, campaign_id, "no_response")

        variants = get_variant_comparison(conn, campaign_id, user_id=TEST_USER_ID)

        # Only A and B, not NULL
        assert len(variants) == 2
        variant_labels = {v["variant"] for v in variants}
        assert variant_labels == {"A", "B"}
        conn.close()

    def test_weekly_summary_no_response_events(self, tmp_db):
        """Weekly summary counts status_no_response events."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="norev@ex.com")
        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id)

        today = date.today()
        recent = (today - timedelta(days=1)).isoformat() + " 12:00:00"

        _log_event(conn, c1, "status_no_response", campaign_id, created_at=recent)
        _log_event(conn, c1, "status_no_response", campaign_id, created_at=recent)

        summary = get_weekly_summary(conn, campaign_id, weeks_back=1, user_id=TEST_USER_ID)
        assert summary["new_no_response"] == 2
        conn.close()

    def test_weekly_summary_negative_replies(self, tmp_db):
        """Weekly summary counts status_replied_negative events."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="neg@ex.com")
        campaign_id = _create_campaign(conn)
        _enroll(conn, c1, campaign_id)

        today = date.today()
        recent = (today - timedelta(days=1)).isoformat() + " 12:00:00"

        _log_event(conn, c1, "status_replied_negative", campaign_id, created_at=recent)

        summary = get_weekly_summary(conn, campaign_id, weeks_back=1, user_id=TEST_USER_ID)
        assert summary["replies_negative"] == 1
        conn.close()
