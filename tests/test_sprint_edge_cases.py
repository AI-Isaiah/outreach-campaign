"""Sprint 1-4 friction sweep edge case tests.

Covers: health score computation, batch send idempotency, contacts API
sort/filter, cron auth, schedule presets, fund signal extraction, and
send_email_batch shared helper.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import psycopg2
import psycopg2.extras
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.models.campaigns import (
    create_campaign,
    enroll_contact,
    update_contact_campaign_status,
)
from src.models.database import get_connection, get_cursor, run_migrations
from src.models.templates import create_template
from src.services.deep_research_service import (
    _detect_signal_type,
    _extract_fund_signals,
    _recency_score,
)
from src.services.metrics import compute_health_score
from src.web.app import app
from src.web.dependencies import get_db, verify_cron_secret
from src.web.routes.queue import _resolve_schedule_times
from tests.conftest import TEST_USER_ID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_db):
    """Return a database connection with migrations applied."""
    connection = get_connection(tmp_db)
    run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def db_conn(tmp_db):
    """Alias — some test helpers expect db_conn."""
    connection = get_connection(tmp_db)
    run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def client(tmp_db):
    """Create a FastAPI test client with DB dependency override."""
    def _override_get_db():
        c = get_connection(tmp_db)
        run_migrations(c)
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _seed_company(conn, name="Test Fund", aum=500.0, firm_type="Hedge Fund", country="US"):
    """Insert a test company and return its id."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country, user_id)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, name.lower(), aum, firm_type, country, TEST_USER_ID),
    )
    conn.commit()
    return cur.fetchone()["id"]


def _seed_contact(
    conn, company_id, first="John", last="Doe", email="john@test.com",
    linkedin_url=None, unsubscribed=False,
):
    """Insert a test contact and return its id."""
    email_norm = email.lower() if email else None
    linkedin_norm = linkedin_url.lower().rstrip("/") if linkedin_url else None
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name, email,
                                 email_normalized, email_status, linkedin_url,
                                 linkedin_url_normalized, unsubscribed, user_id)
           VALUES (%s, %s, %s, %s, %s, %s, 'valid', %s, %s, %s, %s) RETURNING id""",
        (company_id, first, last, f"{first} {last}", email, email_norm,
         linkedin_url, linkedin_norm, unsubscribed, TEST_USER_ID),
    )
    conn.commit()
    return cur.fetchone()["id"]


def _seed_campaign(conn, name="test_campaign"):
    """Insert a test campaign and return its id."""
    return create_campaign(conn, name, user_id=TEST_USER_ID)


def _enroll(conn, contact_id, campaign_id, status="in_progress", variant=None):
    """Enroll a contact in a campaign and return enrollment id."""
    eid = enroll_contact(
        conn, contact_id, campaign_id,
        variant=variant,
        next_action_date=date.today().isoformat(),
        user_id=TEST_USER_ID,
    )
    if status != "queued":
        update_contact_campaign_status(
            conn, contact_id, campaign_id,
            status=status,
            user_id=TEST_USER_ID,
        )
    return eid


def _seed_template(conn, name="test_tmpl", body="Hi {{ first_name }}", subject="Hello"):
    """Create a template and return its id."""
    return create_template(
        conn, name, "email", body,
        subject=subject, user_id=TEST_USER_ID,
    )


# ===========================================================================
# 1. Health score computation
# ===========================================================================


class TestComputeHealthScore:
    """Edge cases for compute_health_score in services/metrics.py."""

    def test_zero_enrolled_returns_none(self):
        """0 enrolled contacts should return None (no data to score)."""
        metrics = {"total_enrolled": 0, "by_status": {}, "emails_sent": 0}
        assert compute_health_score(metrics) is None

    def test_all_positive_replies(self):
        """All contacts with positive replies: score = (1.0 * 50) + (velocity * 30) - (0 * 20).
        With emails_sent == total_enrolled, velocity = 1.0, so score = 50 + 30 = 80.
        """
        metrics = {
            "total_enrolled": 10,
            "by_status": {
                "replied_positive": 10,
                "bounced": 0,
            },
            "emails_sent": 10,
        }
        score = compute_health_score(metrics)
        assert score == 80

    def test_all_bounced_clamped_to_zero(self):
        """All bounced: positive_reply_rate=0, velocity=1.0 (sent all), bounce_rate=1.0.
        score = 0 + 30 - 20 = 10. Not negative, so not clamped.
        """
        metrics = {
            "total_enrolled": 10,
            "by_status": {
                "replied_positive": 0,
                "bounced": 10,
            },
            "emails_sent": 10,
        }
        score = compute_health_score(metrics)
        assert score == 10

    def test_extreme_bounce_clamped_to_zero(self):
        """Scenario where the score formula goes negative (high bounce, zero positive,
        low velocity). score should be clamped to 0.
        """
        # positive_reply_rate = 0/5 = 0
        # send_velocity = 1/5 = 0.2
        # bounce_rate = 1/1 = 1.0
        # score = 0 + 0.2*30 - 1.0*20 = 6 - 20 = -14 -> clamped to 0
        metrics = {
            "total_enrolled": 5,
            "by_status": {"replied_positive": 0, "bounced": 1},
            "emails_sent": 1,
        }
        score = compute_health_score(metrics)
        assert score == 0

    def test_typical_mixed_case(self):
        """Mixed scenario: 20 enrolled, 3 positive, 2 bounced, 15 emails sent.
        positive_reply_rate = 3/20 = 0.15
        send_velocity = 15/20 = 0.75
        bounce_rate = 2/15 ~ 0.1333
        score = 0.15*50 + 0.75*30 - 0.1333*20 = 7.5 + 22.5 - 2.667 = 27.333 -> 27
        """
        metrics = {
            "total_enrolled": 20,
            "by_status": {"replied_positive": 3, "bounced": 2},
            "emails_sent": 15,
        }
        score = compute_health_score(metrics)
        assert score == 27

    def test_zero_emails_sent_velocity_zero(self):
        """No emails sent yet: velocity = 0, bounce_rate = 0 (guarded by emails_sent > 0).
        score = 0 + 0 - 0 = 0.
        """
        metrics = {
            "total_enrolled": 10,
            "by_status": {"replied_positive": 0, "bounced": 0},
            "emails_sent": 0,
        }
        score = compute_health_score(metrics)
        assert score == 0

    def test_score_capped_at_100(self):
        """Score should never exceed 100 even with very high velocity."""
        metrics = {
            "total_enrolled": 2,
            "by_status": {"replied_positive": 2, "bounced": 0},
            # Simulate more emails sent than enrolled (follow-ups)
            "emails_sent": 10,
        }
        score = compute_health_score(metrics)
        assert score <= 100

    def test_missing_by_status_keys(self):
        """If by_status has no replied_positive/bounced keys, defaults to 0."""
        metrics = {
            "total_enrolled": 5,
            "by_status": {},
            "emails_sent": 3,
        }
        score = compute_health_score(metrics)
        # positive_reply_rate=0, velocity=0.6, bounce_rate=0
        # 0 + 18 - 0 = 18
        assert score == 18


# ===========================================================================
# 2. Batch send with idempotency guard
# ===========================================================================


class TestSendCampaignEmailIdempotency:
    """The atomic UPDATE SET sent_at=NOW() WHERE sent_at IS NULL guard."""

    def _setup_sendable(self, conn):
        """Create a company, contact, campaign, template, and enrollment ready to send."""
        company_id = _seed_company(conn, name="Idem Fund")
        contact_id = _seed_contact(conn, company_id, email="idem@test.com")
        campaign_id = _seed_campaign(conn, "idem_campaign")
        template_id = _seed_template(conn, name="idem_tmpl")
        _enroll(conn, contact_id, campaign_id, status="in_progress")

        # Add a sequence step so step advancement works
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO sequence_steps (campaign_id, step_order, channel, template_id, delay_days)
               VALUES (%s, 1, 'email', %s, 0)""",
            (campaign_id, template_id),
        )
        conn.commit()

        config = {
            "calendly_url": "https://calendly.com/test",
            "physical_address": "123 Main St, NY",
            "smtp": {
                "host": "smtp.test.com",
                "port": 587,
                "username": "test@test.com",
                "password": "pass",
            },
            "smtp_password": "pass",
        }
        return contact_id, campaign_id, template_id, config

    @patch("src.services.email_sender.send_email", return_value=True)
    def test_first_send_succeeds(self, mock_send, conn):
        """First call to send_campaign_email should succeed (sent_at IS NULL)."""
        from src.services.email_sender import send_campaign_email

        contact_id, campaign_id, template_id, config = self._setup_sendable(conn)
        result = send_campaign_email(
            conn, contact_id, campaign_id, template_id, config,
            user_id=TEST_USER_ID,
        )
        assert result is True
        assert mock_send.called

    @patch("src.services.email_sender.send_email", return_value=True)
    def test_second_send_same_step_returns_false(self, mock_send, conn):
        """Two sends at the same step: second should fail because sent_at is set and step hasn't advanced."""
        from src.services.email_sender import send_campaign_email
        from src.models.database import get_cursor

        contact_id, campaign_id, template_id, config = self._setup_sendable(conn)

        # First send sets sent_at via the idempotency guard
        result1 = send_campaign_email(
            conn, contact_id, campaign_id, template_id, config,
            user_id=TEST_USER_ID,
        )
        assert result1 is True

        # Reset sent_at clearing (step advance clears it). Set it back manually to simulate
        # the guard catching a concurrent send BEFORE step advance completes.
        with get_cursor(conn) as cur:
            cur.execute(
                "UPDATE contact_campaign_status SET sent_at = NOW() WHERE contact_id = %s AND campaign_id = %s",
                (contact_id, campaign_id),
            )
        conn.commit()

        # Second send — idempotency guard should block it
        mock_send.reset_mock()
        result2 = send_campaign_email(
            conn, contact_id, campaign_id, template_id, config,
            user_id=TEST_USER_ID,
        )
        assert result2 is False

    @patch("src.services.email_sender.send_email", return_value=True)
    def test_not_enrolled_returns_false(self, mock_send, conn):
        """Contact not enrolled in campaign should return False."""
        from src.services.email_sender import send_campaign_email

        company_id = _seed_company(conn, name="No Enroll Fund")
        contact_id = _seed_contact(conn, company_id, email="noenroll@test.com")
        campaign_id = _seed_campaign(conn, "no_enroll_campaign")
        template_id = _seed_template(conn, name="noenroll_tmpl")
        config = {
            "calendly_url": "",
            "physical_address": "123 St",
            "smtp": {"host": "smtp.test.com", "port": 587, "username": "a@b.com"},
            "smtp_password": "x",
        }

        result = send_campaign_email(
            conn, contact_id, campaign_id, template_id, config,
            user_id=TEST_USER_ID,
        )
        assert result is False
        assert not mock_send.called

    @patch("src.services.email_sender.send_email", return_value=True)
    def test_unsubscribed_contact_returns_false(self, mock_send, conn):
        """Unsubscribed contacts should be blocked before the idempotency guard."""
        from src.services.email_sender import send_campaign_email

        company_id = _seed_company(conn, name="Unsub Fund")
        contact_id = _seed_contact(
            conn, company_id, email="unsub@test.com", unsubscribed=True,
        )
        campaign_id = _seed_campaign(conn, "unsub_campaign")
        template_id = _seed_template(conn)
        _enroll(conn, contact_id, campaign_id, status="in_progress")
        config = {
            "calendly_url": "",
            "physical_address": "123 St",
            "smtp": {"host": "smtp.test.com", "port": 587, "username": "a@b.com"},
            "smtp_password": "x",
        }

        result = send_campaign_email(
            conn, contact_id, campaign_id, template_id, config,
            user_id=TEST_USER_ID,
        )
        assert result is False


# ===========================================================================
# 3. Contacts API sort/filter
# ===========================================================================


class TestContactsApiSortFilter:
    """Edge cases for GET /api/contacts — sort, filter, search, dedup."""

    def _seed_varied_contacts(self, conn):
        """Seed contacts with different names, AUMs, emails, and LinkedIn URLs."""
        co_big = _seed_company(conn, "Big Capital", aum=2000.0, firm_type="Pension")
        co_small = _seed_company(conn, "Small Ventures", aum=50.0, firm_type="VC")
        co_mid = _seed_company(conn, "Mid Fund", aum=500.0, firm_type="Hedge Fund")

        c1 = _seed_contact(conn, co_big, first="Alice", last="Zulu", email="alice@big.com",
                           linkedin_url="https://linkedin.com/in/alice")
        c2 = _seed_contact(conn, co_small, first="Bob", last="Alpha", email=None,
                           linkedin_url="https://linkedin.com/in/bob")
        c3 = _seed_contact(conn, co_mid, first="Charlie", last="Mid", email="charlie@mid.com",
                           linkedin_url=None)
        # Second contact at Big Capital (same company as c1)
        c4 = _seed_contact(conn, co_big, first="Diana", last="Big", email="diana@big.com",
                           linkedin_url="https://linkedin.com/in/diana")
        return co_big, co_small, co_mid, c1, c2, c3, c4

    def test_sort_by_name_asc(self, client, db_conn):
        """Sorting by name ASC should order alphabetically by full_name."""
        self._seed_varied_contacts(db_conn)
        resp = client.get("/api/contacts?sort_by=name&sort_dir=asc")
        assert resp.status_code == 200
        data = resp.json()
        names = [c["full_name"] for c in data["contacts"]]
        assert names == sorted(names)

    def test_sort_by_aum_desc(self, client, db_conn):
        """Sorting by aum DESC should put highest AUM companies first."""
        self._seed_varied_contacts(db_conn)
        resp = client.get("/api/contacts?sort_by=aum&sort_dir=desc")
        assert resp.status_code == 200
        data = resp.json()
        aums = [c.get("aum_millions") for c in data["contacts"]]
        # Filter out None for sorting check — NULLS LAST in desc
        non_null = [a for a in aums if a is not None]
        assert non_null == sorted(non_null, reverse=True)

    def test_has_linkedin_filter(self, client, db_conn):
        """has_linkedin=true should only return contacts with linkedin_url."""
        self._seed_varied_contacts(db_conn)
        resp = client.get("/api/contacts?has_linkedin=true")
        assert resp.status_code == 200
        data = resp.json()
        for c in data["contacts"]:
            assert c.get("linkedin_url") is not None and c["linkedin_url"] != ""

    def test_has_email_filter(self, client, db_conn):
        """has_email=true should only return contacts with non-null email."""
        self._seed_varied_contacts(db_conn)
        resp = client.get("/api/contacts?has_email=true")
        assert resp.status_code == 200
        data = resp.json()
        for c in data["contacts"]:
            assert c.get("email") is not None and c["email"] != ""

    def test_one_per_company(self, client, db_conn):
        """one_per_company=true should return at most one contact per company."""
        self._seed_varied_contacts(db_conn)
        resp = client.get("/api/contacts?one_per_company=true")
        assert resp.status_code == 200
        data = resp.json()
        company_ids = [c["company_id"] for c in data["contacts"]]
        assert len(company_ids) == len(set(company_ids)), "Duplicate companies found"

    def test_search_ilike_case_insensitive(self, client, db_conn):
        """Search should match case-insensitively (ILIKE)."""
        self._seed_varied_contacts(db_conn)
        # Search for "ALICE" (uppercase) — should find "Alice"
        resp = client.get("/api/contacts?search=ALICE")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any("Alice" in c["full_name"] for c in data["contacts"])

    def test_invalid_sort_by_rejected(self, client, db_conn):
        """Invalid sort_by value should be rejected with 422."""
        resp = client.get("/api/contacts?sort_by=invalid_column")
        assert resp.status_code == 422  # FastAPI Query regex validation

    def test_search_by_company_name(self, client, db_conn):
        """Search should also match company names."""
        self._seed_varied_contacts(db_conn)
        resp = client.get("/api/contacts?search=Big Capital")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_empty_result(self, client):
        """Search for nonexistent name returns empty list."""
        resp = client.get("/api/contacts?search=zzz_nonexistent_999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["contacts"] == []

    def test_pagination(self, client, db_conn):
        """Page/per_page should correctly paginate results."""
        self._seed_varied_contacts(db_conn)
        resp = client.get("/api/contacts?per_page=2&page=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["contacts"]) <= 2
        assert data["per_page"] == 2
        assert data["page"] == 1
        assert data["pages"] >= 1


# ===========================================================================
# 4. Cron auth (verify_cron_secret)
# ===========================================================================


class TestCronAuth:
    """Edge cases for verify_cron_secret dependency."""

    def _make_request(self, authorization: str | None = None) -> Request:
        """Build a minimal Starlette Request with optional Authorization header."""
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/cron/scan-replies",
            "headers": [],
        }
        if authorization is not None:
            scope["headers"] = [(b"authorization", authorization.encode())]
        return Request(scope)

    def test_missing_cron_secret_env_returns_503(self):
        """When CRON_SECRET env var is not set, should raise 503."""
        from fastapi import HTTPException

        req = self._make_request(authorization="Bearer something")
        with patch.dict(os.environ, {}, clear=False):
            # Ensure CRON_SECRET is not set
            env_copy = os.environ.copy()
            env_copy.pop("CRON_SECRET", None)
            with patch.dict(os.environ, env_copy, clear=True):
                with pytest.raises(HTTPException) as exc_info:
                    verify_cron_secret(req)
                assert exc_info.value.status_code == 503
                assert "not configured" in exc_info.value.detail.lower()

    def test_wrong_secret_returns_401(self):
        """When Authorization header doesn't match CRON_SECRET, should raise 401."""
        from fastapi import HTTPException

        req = self._make_request(authorization="Bearer wrong_secret")
        with patch.dict(os.environ, {"CRON_SECRET": "correct_secret"}):
            with pytest.raises(HTTPException) as exc_info:
                verify_cron_secret(req)
            assert exc_info.value.status_code == 401

    def test_correct_secret_passes(self):
        """When Authorization header matches, verify_cron_secret should not raise."""
        req = self._make_request(authorization="Bearer my_cron_secret_123")
        with patch.dict(os.environ, {"CRON_SECRET": "my_cron_secret_123"}):
            # Should not raise any exception
            verify_cron_secret(req)

    def test_missing_auth_header_returns_401(self):
        """No Authorization header at all should raise 401."""
        from fastapi import HTTPException

        req = self._make_request(authorization=None)
        with patch.dict(os.environ, {"CRON_SECRET": "some_secret"}):
            with pytest.raises(HTTPException) as exc_info:
                verify_cron_secret(req)
            assert exc_info.value.status_code == 401

    def test_bearer_prefix_required(self):
        """Authorization without 'Bearer ' prefix should fail."""
        from fastapi import HTTPException

        req = self._make_request(authorization="my_cron_secret")
        with patch.dict(os.environ, {"CRON_SECRET": "my_cron_secret"}):
            with pytest.raises(HTTPException) as exc_info:
                verify_cron_secret(req)
            assert exc_info.value.status_code == 401


# ===========================================================================
# 5. Schedule presets
# ===========================================================================


class TestSchedulePresets:
    """Edge cases for _resolve_schedule_times in routes/queue.py."""

    def test_now_returns_current_time(self):
        """'now' preset should return current UTC time for all items."""
        before = datetime.now(timezone.utc)
        times = _resolve_schedule_times("now", 3)
        after = datetime.now(timezone.utc)

        assert len(times) == 3
        for t in times:
            assert before <= t <= after

    def test_tomorrow_9am(self):
        """'tomorrow_9am' should return next day at 09:00 UTC."""
        times = _resolve_schedule_times("tomorrow_9am", 2)
        now = datetime.now(timezone.utc)
        expected_date = (now + timedelta(days=1)).date()

        assert len(times) == 2
        for t in times:
            assert t.date() == expected_date
            assert t.hour == 9
            assert t.minute == 0
            assert t.second == 0

    def test_spread_3_days_distributes_items(self):
        """'spread_3_days' should spread items across multiple days, 5 per day."""
        times = _resolve_schedule_times("spread_3_days", 12)

        assert len(times) == 12

        # Group by date
        dates = [t.date() for t in times]
        unique_dates = sorted(set(dates))

        # With 12 items at 5/day: day1=5, day2=5, day3=2 -> 3 unique days
        assert len(unique_dates) == 3

        # Each time should be 9am
        for t in times:
            assert t.hour == 9

    def test_spread_3_days_single_item(self):
        """Single item in spread_3_days should land on day+1."""
        times = _resolve_schedule_times("spread_3_days", 1)
        now = datetime.now(timezone.utc)
        expected_date = (now + timedelta(days=1)).date()

        assert len(times) == 1
        assert times[0].date() == expected_date

    def test_spread_3_days_exactly_5_items(self):
        """Exactly 5 items should all land on day+1 (5 per day)."""
        times = _resolve_schedule_times("spread_3_days", 5)
        now = datetime.now(timezone.utc)
        expected_date = (now + timedelta(days=1)).date()

        assert len(times) == 5
        for t in times:
            assert t.date() == expected_date

    def test_iso_datetime_passthrough(self):
        """An ISO datetime string should be parsed and returned for all items."""
        times = _resolve_schedule_times("2026-04-01T14:30:00", 3)
        assert len(times) == 3
        for t in times:
            assert t.year == 2026
            assert t.month == 4
            assert t.day == 1
            assert t.hour == 14
            assert t.minute == 30

    def test_invalid_preset_raises_value_error(self):
        """Unrecognized schedule string should raise ValueError."""
        with pytest.raises(ValueError, match="Unrecognized schedule"):
            _resolve_schedule_times("next_full_moon", 5)

    def test_empty_count_returns_empty(self):
        """Zero items should return an empty list."""
        times = _resolve_schedule_times("now", 0)
        assert times == []

    def test_schedule_endpoint_rejects_invalid(self, client, db_conn):
        """POST /api/queue/schedule with invalid preset returns 400."""
        company_id = _seed_company(db_conn)
        contact_id = _seed_contact(db_conn, company_id, email="sched@test.com")
        campaign_id = _seed_campaign(db_conn, "sched_test")

        resp = client.post("/api/queue/schedule", json={
            "items": [{"contact_id": contact_id, "campaign_id": campaign_id}],
            "schedule": "not_a_real_preset",
        })
        assert resp.status_code == 400


# ===========================================================================
# 6. Fund signal extraction
# ===========================================================================


class TestFundSignalExtraction:
    """Edge cases for _extract_fund_signals in deep_research_service.py."""

    def test_crypto_signals_with_high_recency(self):
        """Crypto signals mentioning 'just announced' should get high recency score."""
        research = {
            "crypto_signals": [
                {"quote": "Just announced a $500M crypto allocation to Bitcoin", "relevance": "high"},
            ],
            "talking_points": [],
        }
        signals = _extract_fund_signals(research)
        assert len(signals) >= 1
        assert signals[0]["recency_score"] == 0.9
        assert signals[0]["type"] == "crypto_allocation"

    def test_no_signals_returns_empty(self):
        """Empty or missing crypto_signals and talking_points returns []."""
        assert _extract_fund_signals({}) == []
        assert _extract_fund_signals({"crypto_signals": [], "talking_points": []}) == []
        assert _extract_fund_signals({"crypto_signals": None, "talking_points": None}) == []

    def test_talking_points_with_event_hooks(self):
        """Talking points with hook_type 'event_hook' should be extracted."""
        research = {
            "crypto_signals": [],
            "talking_points": [
                {
                    "hook_type": "event_hook",
                    "text": "Spoke at the 2026 Blockchain Summit conference",
                    "source_reference": "Event listing",
                },
            ],
        }
        signals = _extract_fund_signals(research)
        assert len(signals) == 1
        assert signals[0]["type"] == "conference"

    def test_recency_scoring_order(self):
        """Signals should be sorted by recency_score descending."""
        research = {
            "crypto_signals": [
                {"quote": "Historically invested in traditional assets for years", "relevance": "medium"},
                {"quote": "Just launched a new fund this week", "relevance": "high"},
                {"quote": "This year they increased crypto allocation", "relevance": "medium"},
            ],
            "talking_points": [],
        }
        signals = _extract_fund_signals(research)
        assert len(signals) >= 2
        scores = [s["recency_score"] for s in signals]
        assert scores == sorted(scores, reverse=True)

    def test_low_relevance_general_signals_filtered(self):
        """Low-relevance signals with type 'general' should be filtered out."""
        research = {
            "crypto_signals": [
                {"quote": "They are a financial services company", "relevance": "low"},
            ],
            "talking_points": [],
        }
        signals = _extract_fund_signals(research)
        assert len(signals) == 0

    def test_deduplication_by_text(self):
        """Duplicate texts (case-insensitive) should be deduplicated."""
        research = {
            "crypto_signals": [
                {"quote": "Allocated $100M to Bitcoin", "relevance": "high"},
                {"quote": "allocated $100m to bitcoin", "relevance": "high"},
            ],
            "talking_points": [],
        }
        signals = _extract_fund_signals(research)
        assert len(signals) == 1

    def test_non_dict_entries_skipped(self):
        """Non-dict entries in crypto_signals should be silently skipped."""
        research = {
            "crypto_signals": [
                "not a dict",
                42,
                {"quote": "Real signal about new fund raise", "relevance": "high"},
            ],
            "talking_points": [],
        }
        signals = _extract_fund_signals(research)
        assert len(signals) == 1

    def test_talking_points_only_event_portfolio_team(self):
        """Only event_hook, portfolio_move, and team_signal hook_types are extracted."""
        research = {
            "crypto_signals": [],
            "talking_points": [
                {"hook_type": "thesis_alignment", "text": "They love crypto thesis", "source_reference": "x"},
                {"hook_type": "portfolio_move", "text": "They acquired a blockchain company", "source_reference": "x"},
                {"hook_type": "team_signal", "text": "Newly appointed CIO from Coinbase", "source_reference": "x"},
            ],
        }
        signals = _extract_fund_signals(research)
        # thesis_alignment should be excluded
        assert len(signals) == 2
        types = {s["type"] for s in signals}
        assert "portfolio_move" in types
        assert "key_hire" in types

    def test_signal_type_detection(self):
        """Verify the _detect_signal_type helper correctly categorizes signals."""
        assert _detect_signal_type("They raised a $200M fund") == "fund_raise"
        assert _detect_signal_type("Appointed a new CIO") == "key_hire"
        assert _detect_signal_type("Allocated to Bitcoin") == "crypto_allocation"
        assert _detect_signal_type("They took a new position in DeFi") == "portfolio_move"
        assert _detect_signal_type("Speaking at a conference") == "conference"
        assert _detect_signal_type("They exist as a company") == "general"

    def test_recency_score_helper(self):
        """Verify the _recency_score helper for various keyword patterns."""
        assert _recency_score("just announced") == 0.9
        assert _recency_score("this week they launched") == 0.9
        assert _recency_score("this year crypto allocation") == 0.6
        assert _recency_score("in Q2 they diversified") == 0.6
        assert _recency_score("historically conservative") == 0.2
        assert _recency_score("no temporal keywords here") == 0.4


# ===========================================================================
# 7. send_email_batch shared helper
# ===========================================================================


class TestSendEmailBatch:
    """Edge cases for send_email_batch in application/queue_service.py."""

    def test_empty_rows_returns_zero(self, conn):
        """Empty rows list should return sent=0, failed=0."""
        from src.application.queue_service import send_email_batch

        config = {"smtp": {}, "smtp_password": "", "physical_address": "", "calendly_url": ""}
        result = send_email_batch(conn, [], config, user_id=TEST_USER_ID)
        assert result == {"sent": 0, "failed": 0, "errors": []}

    @patch("src.application.queue_service.send_campaign_email", return_value=False)
    def test_rows_with_failed_send(self, mock_send, conn):
        """When send_campaign_email returns False, failed count increments."""
        from src.application.queue_service import send_email_batch

        rows = [
            {"contact_id": 1, "campaign_id": 1, "template_id": 1},
            {"contact_id": 2, "campaign_id": 1, "template_id": 1},
        ]
        config = {"smtp": {}, "smtp_password": "", "physical_address": "", "calendly_url": ""}
        result = send_email_batch(conn, rows, config, user_id=TEST_USER_ID)
        assert result["sent"] == 0
        assert result["failed"] == 2
        assert len(result["errors"]) == 2

    @patch("src.application.queue_service.send_campaign_email", side_effect=Exception("SMTP down"))
    def test_exception_in_send_increments_failed(self, mock_send, conn):
        """Exceptions during send should increment failed, not crash the batch."""
        from src.application.queue_service import send_email_batch

        rows = [{"contact_id": 99, "campaign_id": 99, "template_id": 99}]
        config = {"smtp": {}, "smtp_password": "", "physical_address": "", "calendly_url": ""}
        result = send_email_batch(conn, rows, config, user_id=TEST_USER_ID)
        assert result["sent"] == 0
        assert result["failed"] == 1
        assert "SMTP down" in result["errors"][0]

    @patch("src.application.queue_service.send_campaign_email", return_value=True)
    def test_user_id_passthrough(self, mock_send, conn):
        """user_id should be passed through to send_campaign_email."""
        from src.application.queue_service import send_email_batch

        rows = [{"contact_id": 1, "campaign_id": 1, "template_id": 1}]
        config = {"smtp": {}}
        result = send_email_batch(conn, rows, config, user_id=42)
        assert result["sent"] == 1

        # Verify user_id was passed correctly
        call_kwargs = mock_send.call_args
        assert call_kwargs.kwargs["user_id"] == 42

    @patch("src.application.queue_service.send_campaign_email")
    def test_mixed_success_and_failure(self, mock_send, conn):
        """Batch with mixed results: some succeed, some fail."""
        from src.application.queue_service import send_email_batch

        mock_send.side_effect = [True, False, True, Exception("timeout")]
        rows = [
            {"contact_id": i, "campaign_id": 1, "template_id": 1}
            for i in range(4)
        ]
        config = {"smtp": {}}
        result = send_email_batch(conn, rows, config, user_id=TEST_USER_ID)
        assert result["sent"] == 2
        assert result["failed"] == 2
        assert len(result["errors"]) == 2

    @patch("src.application.queue_service.send_campaign_email", return_value=True)
    def test_user_id_from_row_when_kwarg_not_set(self, mock_send, conn):
        """When user_id kwarg is None, should use row's user_id field."""
        from src.application.queue_service import send_email_batch

        rows = [{"contact_id": 1, "campaign_id": 1, "template_id": 1, "user_id": 77}]
        config = {"smtp": {}}
        result = send_email_batch(conn, rows, config)
        assert result["sent"] == 1
        assert mock_send.call_args.kwargs["user_id"] == 77
