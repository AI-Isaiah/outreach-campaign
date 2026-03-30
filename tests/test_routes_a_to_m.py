"""Comprehensive tests for API route endpoints A-M (alphabetically).

Covers: auth, campaigns, contacts, conversations, crm, deals,
deep_research, gmail, gmail_oauth, import_routes, inbox, insights.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import psycopg2
import psycopg2.extras
import pytest
from fastapi.testclient import TestClient

from src.models.database import get_connection, run_migrations
from src.web.app import app
from src.web.dependencies import get_db
from tests.conftest import TEST_USER_ID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn(tmp_db):
    """Provide a database connection for direct test setup."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


@pytest.fixture
def client(tmp_db):
    """Create a test client with DB dependency override."""
    def _override_get_db():
        conn = get_connection(tmp_db)
        run_migrations(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

_seed_counter = 0


def _next_id():
    global _seed_counter
    _seed_counter += 1
    return _seed_counter


def _seed_company(conn, name=None, aum=500.0, firm_type="Hedge Fund", country="US", user_id=TEST_USER_ID):
    n = _next_id()
    name = name or f"Fund_{n}"
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country, user_id)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, name.lower(), aum, firm_type, country, user_id),
    )
    conn.commit()
    cid = cur.fetchone()["id"]
    cur.close()
    return cid


def _seed_contact(conn, company_id, first=None, last="Doe", email=None, user_id=TEST_USER_ID):
    n = _next_id()
    first = first or f"User{n}"
    email = email or f"user{n}@test.com"
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name,
                                 email, email_normalized, email_status, user_id,
                                 priority_rank, lifecycle_stage)
           VALUES (%s, %s, %s, %s, %s, %s, 'valid', %s, 1, 'cold') RETURNING id""",
        (company_id, first, last, f"{first} {last}", email, email.lower(), user_id),
    )
    conn.commit()
    cid = cur.fetchone()["id"]
    cur.close()
    return cid


def _seed_campaign(conn, name=None, user_id=TEST_USER_ID):
    from src.models.campaigns import create_campaign
    n = _next_id()
    name = name or f"campaign_{n}"
    return create_campaign(conn, name, user_id=user_id)


def _seed_deal(conn, company_id, title=None, stage="cold", user_id=TEST_USER_ID):
    n = _next_id()
    title = title or f"Deal_{n}"
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO deals (company_id, title, stage, user_id)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (company_id, title, stage, user_id),
    )
    conn.commit()
    did = cur.fetchone()["id"]
    # Log initial stage
    cur.execute(
        "INSERT INTO deal_stage_log (deal_id, from_stage, to_stage, user_id) VALUES (%s, NULL, %s, %s)",
        (did, stage, user_id),
    )
    conn.commit()
    cur.close()
    return did


def _seed_user_2(conn):
    """Insert a second user for multi-tenancy tests. Returns user_id."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (email, name) VALUES ('user2@test.com', 'User Two') "
        "ON CONFLICT (email) DO UPDATE SET name = 'User Two' RETURNING id"
    )
    conn.commit()
    uid = cur.fetchone()["id"]
    cur.close()
    return uid


def _seed_user_with_password(conn, email="login@test.com", name="Login User", password="securepass1"):
    """Insert a user with a hashed password for auth tests."""
    import bcrypt
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s) "
        "ON CONFLICT (email) DO UPDATE SET password_hash = %s, name = %s RETURNING id",
        (email, name, hashed, hashed, name),
    )
    conn.commit()
    uid = cur.fetchone()["id"]
    cur.close()
    return uid


def _seed_allowed_email(conn, email):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO allowed_emails (email) VALUES (%s) ON CONFLICT DO NOTHING",
        (email,),
    )
    conn.commit()
    cur.close()


# ============================================================================
# AUTH ROUTES (/api/auth/*)
# ============================================================================

class TestAuthLogin:
    def test_login_success(self, client, db_conn):
        _seed_user_with_password(db_conn, email="loginok@test.com", password="goodpass123")
        resp = client.post("/api/auth/login", json={"email": "loginok@test.com", "password": "goodpass123"})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["email"] == "loginok@test.com"

    def test_login_wrong_password(self, client, db_conn):
        _seed_user_with_password(db_conn, email="wrongpw@test.com", password="correctpass1")
        resp = client.post("/api/auth/login", json={"email": "wrongpw@test.com", "password": "wrongpassword"})
        assert resp.status_code == 401

    def test_login_unknown_email(self, client):
        resp = client.post("/api/auth/login", json={"email": "nobody@test.com", "password": "anything1"})
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        resp = client.post("/api/auth/login", json={"email": "x@test.com"})
        assert resp.status_code == 422

    def test_login_empty_body(self, client):
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code == 422

    def test_login_deactivated_user(self, client, db_conn):
        uid = _seed_user_with_password(db_conn, email="deact@test.com", password="pass12345")
        cur = db_conn.cursor()
        cur.execute("UPDATE users SET is_active = false WHERE id = %s", (uid,))
        db_conn.commit()
        cur.close()
        resp = client.post("/api/auth/login", json={"email": "deact@test.com", "password": "pass12345"})
        assert resp.status_code == 403


class TestAuthRegister:
    def test_register_success(self, client, db_conn):
        email = "newuser@test.com"
        _seed_allowed_email(db_conn, email)
        resp = client.post("/api/auth/register", json={
            "email": email, "name": "New User", "password": "password123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["email"] == email

    def test_register_not_on_invite_list(self, client):
        resp = client.post("/api/auth/register", json={
            "email": "noinvite@test.com", "name": "No Invite", "password": "password123",
        })
        assert resp.status_code == 403

    def test_register_duplicate(self, client, db_conn):
        email = "dup@test.com"
        _seed_allowed_email(db_conn, email)
        _seed_user_with_password(db_conn, email=email, password="existing1")
        resp = client.post("/api/auth/register", json={
            "email": email, "name": "Dup", "password": "password123",
        })
        assert resp.status_code == 409

    def test_register_password_too_short(self, client, db_conn):
        email = "short@test.com"
        _seed_allowed_email(db_conn, email)
        resp = client.post("/api/auth/register", json={
            "email": email, "name": "Short", "password": "abc",
        })
        assert resp.status_code == 422


class TestAuthForgotPassword:
    @patch("src.web.routes.auth._send_reset_email")
    def test_forgot_password_known_email(self, mock_send, client, db_conn):
        _seed_user_with_password(db_conn, email="forgot@test.com")
        resp = client.post("/api/auth/forgot-password", json={"email": "forgot@test.com"})
        assert resp.status_code == 200
        assert "message" in resp.json()
        mock_send.assert_called_once()

    def test_forgot_password_unknown_email(self, client):
        resp = client.post("/api/auth/forgot-password", json={"email": "unknown@test.com"})
        # Should always return 200 to prevent email enumeration
        assert resp.status_code == 200


class TestAuthResetPassword:
    def test_reset_password_success(self, client, db_conn):
        uid = _seed_user_with_password(db_conn, email="reset@test.com", password="oldpass12")
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, NOW() + INTERVAL '1 hour')",
            (uid, "valid_token_123"),
        )
        db_conn.commit()
        cur.close()
        resp = client.post("/api/auth/reset-password", json={
            "token": "valid_token_123", "password": "newpass123",
        })
        assert resp.status_code == 200

    def test_reset_password_invalid_token(self, client):
        resp = client.post("/api/auth/reset-password", json={
            "token": "bad_token", "password": "newpass123",
        })
        assert resp.status_code == 400

    def test_reset_password_expired_token(self, client, db_conn):
        uid = _seed_user_with_password(db_conn, email="expired@test.com")
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, NOW() - INTERVAL '1 hour')",
            (uid, "expired_token_456"),
        )
        db_conn.commit()
        cur.close()
        resp = client.post("/api/auth/reset-password", json={
            "token": "expired_token_456", "password": "newpass123",
        })
        assert resp.status_code == 400

    def test_reset_password_used_token(self, client, db_conn):
        uid = _seed_user_with_password(db_conn, email="used@test.com")
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at, used) VALUES (%s, %s, NOW() + INTERVAL '1 hour', true)",
            (uid, "used_token_789"),
        )
        db_conn.commit()
        cur.close()
        resp = client.post("/api/auth/reset-password", json={
            "token": "used_token_789", "password": "newpass123",
        })
        assert resp.status_code == 400


class TestAuthMe:
    def test_get_me(self, client):
        # In dev mode (no JWT_SECRET), returns default user
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "email" in data


# ============================================================================
# CAMPAIGN ROUTES (/api/campaigns/*)
# ============================================================================

class TestCampaignList:
    def test_list_empty(self, client):
        resp = client.get("/api/campaigns")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_data(self, client, db_conn):
        _seed_campaign(db_conn, "camp_a")
        _seed_campaign(db_conn, "camp_b")
        resp = client.get("/api/campaigns")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Should have health_score computed
        assert "health_score" in data[0]

    def test_list_filter_by_status(self, client, db_conn):
        _seed_campaign(db_conn, "active_camp")
        resp = client.get("/api/campaigns?status=active")
        assert resp.status_code == 200
        data = resp.json()
        for row in data:
            assert row["status"] == "active"

    def test_list_filter_nonexistent_status(self, client, db_conn):
        _seed_campaign(db_conn, "status_test")
        resp = client.get("/api/campaigns?status=nonexistent")
        assert resp.status_code == 200
        assert resp.json() == []


class TestCampaignLaunch:
    def test_launch_success(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.post("/api/campaigns/launch", json={
            "name": "launch_test",
            "description": "Test launch",
            "steps": [{"step_order": 1, "channel": "email", "delay_days": 0}],
            "contact_ids": [ctid],
            "status": "active",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "launch_test"
        assert data["contacts_enrolled"] == 1
        assert data["steps_created"] == 1

    def test_launch_draft_no_enrollment(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.post("/api/campaigns/launch", json={
            "name": "draft_camp",
            "steps": [{"step_order": 1, "channel": "email", "delay_days": 0}],
            "contact_ids": [ctid],
            "status": "draft",
        })
        assert resp.status_code == 200
        assert resp.json()["contacts_enrolled"] == 0

    def test_launch_missing_steps(self, client):
        resp = client.post("/api/campaigns/launch", json={
            "name": "no_steps",
            "steps": [],
            "contact_ids": [],
        })
        assert resp.status_code == 400

    def test_launch_invalid_status(self, client):
        resp = client.post("/api/campaigns/launch", json={
            "name": "bad_status",
            "steps": [{"step_order": 1, "channel": "email", "delay_days": 0}],
            "contact_ids": [],
            "status": "invalid",
        })
        assert resp.status_code == 400

    def test_launch_duplicate_name(self, client, db_conn):
        _seed_campaign(db_conn, "dup_name")
        resp = client.post("/api/campaigns/launch", json={
            "name": "dup_name",
            "steps": [{"step_order": 1, "channel": "email", "delay_days": 0}],
            "contact_ids": [],
            "status": "draft",  # draft bypasses 0-contacts check — testing name uniqueness
        })
        assert resp.status_code == 409

    def test_launch_missing_name(self, client):
        resp = client.post("/api/campaigns/launch", json={
            "steps": [{"step_order": 1, "channel": "email", "delay_days": 0}],
            "contact_ids": [],
        })
        assert resp.status_code == 422

    def test_launch_with_nonexistent_contacts(self, client):
        resp = client.post("/api/campaigns/launch", json={
            "name": "ghost_contacts",
            "steps": [{"step_order": 1, "channel": "email", "delay_days": 0}],
            "contact_ids": [99999],
        })
        assert resp.status_code == 400


class TestCampaignGet:
    def test_get_by_name(self, client, db_conn):
        _seed_campaign(db_conn, "get_test")
        resp = client.get("/api/campaigns/get_test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "get_test"
        assert "health_score" in data

    def test_get_not_found(self, client):
        resp = client.get("/api/campaigns/nonexistent")
        assert resp.status_code == 404


class TestCampaignMetrics:
    def test_metrics_success(self, client, db_conn):
        _seed_campaign(db_conn, "metrics_test")
        resp = client.get("/api/campaigns/metrics_test/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data
        assert "variants" in data
        assert "weekly" in data
        assert "firm_breakdown" in data

    def test_metrics_not_found(self, client):
        resp = client.get("/api/campaigns/nonexistent/metrics")
        assert resp.status_code == 404


class TestCampaignWeekly:
    def test_weekly_success(self, client, db_conn):
        _seed_campaign(db_conn, "weekly_ok")
        resp = client.get("/api/campaigns/weekly_ok/weekly")
        assert resp.status_code == 200
        data = resp.json()
        assert data["campaign"] == "weekly_ok"
        assert "weekly" in data

    def test_weekly_not_found(self, client):
        resp = client.get("/api/campaigns/nope/weekly")
        assert resp.status_code == 404


class TestCampaignReport:
    def test_report_success(self, client, db_conn):
        _seed_campaign(db_conn, "report_ok")
        resp = client.get("/api/campaigns/report_ok/report")
        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data
        assert "variants" in data

    def test_report_not_found(self, client):
        resp = client.get("/api/campaigns/nonexistent/report")
        assert resp.status_code == 404


class TestCampaignTemplatePerformance:
    def test_template_performance_success(self, client, db_conn):
        _seed_campaign(db_conn, "tpl_perf")
        resp = client.get("/api/campaigns/tpl_perf/template-performance")
        assert resp.status_code == 200

    def test_template_performance_not_found(self, client):
        resp = client.get("/api/campaigns/nonexistent/template-performance")
        assert resp.status_code == 404


class TestCampaignContacts:
    def test_campaign_contacts(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.post("/api/campaigns/launch", json={
            "name": "camp_contacts",
            "steps": [{"step_order": 1, "channel": "email", "delay_days": 0}],
            "contact_ids": [ctid],
            "status": "active",
        })
        campaign_id = resp.json()["campaign_id"]
        resp2 = client.get(f"/api/campaigns/{campaign_id}/contacts")
        assert resp2.status_code == 200
        assert len(resp2.json()) == 1

    def test_campaign_contacts_not_found(self, client):
        resp = client.get("/api/campaigns/99999/contacts")
        assert resp.status_code == 404


# ============================================================================
# CONTACT ROUTES (/api/contacts/*)
# ============================================================================

class TestContactList:
    def test_list_empty(self, client):
        resp = client.get("/api/contacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["contacts"] == []
        assert data["total"] == 0

    def test_list_with_data(self, client, db_conn):
        coid = _seed_company(db_conn)
        _seed_contact(db_conn, coid)
        _seed_contact(db_conn, coid)
        resp = client.get("/api/contacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["contacts"]) == 2

    def test_list_search(self, client, db_conn):
        coid = _seed_company(db_conn, name="Searchable Inc")
        _seed_contact(db_conn, coid, first="FindMe", email="findme@test.com")
        _seed_contact(db_conn, coid, first="Other", email="other@test.com")
        resp = client.get("/api/contacts?search=FindMe")
        data = resp.json()
        assert data["total"] >= 1
        assert any("FindMe" in c["full_name"] for c in data["contacts"])

    def test_list_sort_by_name(self, client, db_conn):
        coid = _seed_company(db_conn)
        _seed_contact(db_conn, coid, first="Zara", email="zara@test.com")
        _seed_contact(db_conn, coid, first="Alice", email="alice@test.com")
        resp = client.get("/api/contacts?sort_by=name&sort_dir=asc")
        assert resp.status_code == 200

    def test_list_filter_has_linkedin(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid, email="lionly@test.com")
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE contacts SET linkedin_url = 'https://linkedin.com/in/test', linkedin_url_normalized = 'https://linkedin.com/in/test' WHERE id = %s",
            (ctid,),
        )
        db_conn.commit()
        cur.close()
        resp = client.get("/api/contacts?has_linkedin=true")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    def test_list_pagination_page_1(self, client, db_conn):
        coid = _seed_company(db_conn)
        for _ in range(5):
            _seed_contact(db_conn, coid)
        resp = client.get("/api/contacts?per_page=2&page=1")
        data = resp.json()
        assert len(data["contacts"]) == 2
        assert data["pages"] == 3

    def test_list_pagination_high_page(self, client, db_conn):
        coid = _seed_company(db_conn)
        _seed_contact(db_conn, coid)
        resp = client.get("/api/contacts?page=999")
        data = resp.json()
        assert data["contacts"] == []

    def test_list_one_per_company(self, client, db_conn):
        co1 = _seed_company(db_conn, name="CompA")
        co2 = _seed_company(db_conn, name="CompB")
        _seed_contact(db_conn, co1, email="a1@test.com")
        _seed_contact(db_conn, co1, email="a2@test.com")
        _seed_contact(db_conn, co2, email="b1@test.com")
        resp = client.get("/api/contacts?one_per_company=true")
        data = resp.json()
        assert data["total"] == 2  # one from each company


class TestContactExclusionFilters:
    """Tests for exclude_campaigns and never_contacted query params on GET /contacts."""

    def _enroll(self, conn, contact_id, campaign_id):
        from src.models.enrollment import enroll_contact
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)

    def test_exclude_campaigns_filters_enrolled_contacts(self, client, db_conn):
        co = _seed_company(db_conn)
        ct_a = _seed_contact(db_conn, co, first="Alice", email="alice_excl@test.com")
        ct_b = _seed_contact(db_conn, co, first="Bob", email="bob_excl@test.com")
        camp = _seed_campaign(db_conn, name="camp_excl_1")
        self._enroll(db_conn, ct_a, camp)

        resp = client.get(f"/api/contacts?exclude_campaigns={camp}")
        assert resp.status_code == 200
        data = resp.json()
        returned_ids = [c["id"] for c in data["contacts"]]
        assert ct_a not in returned_ids
        assert ct_b in returned_ids

    def test_never_contacted_filters_enrolled_contacts(self, client, db_conn):
        co = _seed_company(db_conn)
        ct_a = _seed_contact(db_conn, co, first="Carol", email="carol_nc@test.com")
        ct_b = _seed_contact(db_conn, co, first="Dave", email="dave_nc@test.com")
        camp = _seed_campaign(db_conn, name="camp_nc")
        self._enroll(db_conn, ct_a, camp)

        resp = client.get("/api/contacts?never_contacted=true")
        assert resp.status_code == 200
        data = resp.json()
        returned_ids = [c["id"] for c in data["contacts"]]
        assert ct_a not in returned_ids
        assert ct_b in returned_ids

    def test_exclude_campaigns_comma_separated(self, client, db_conn):
        co = _seed_company(db_conn)
        ct_a = _seed_contact(db_conn, co, first="Eve", email="eve_cs@test.com")
        ct_b = _seed_contact(db_conn, co, first="Frank", email="frank_cs@test.com")
        ct_c = _seed_contact(db_conn, co, first="Grace", email="grace_cs@test.com")
        camp1 = _seed_campaign(db_conn, name="camp_cs_1")
        camp2 = _seed_campaign(db_conn, name="camp_cs_2")
        self._enroll(db_conn, ct_a, camp1)
        self._enroll(db_conn, ct_b, camp2)

        resp = client.get(f"/api/contacts?exclude_campaigns={camp1},{camp2}")
        assert resp.status_code == 200
        data = resp.json()
        returned_ids = [c["id"] for c in data["contacts"]]
        assert ct_a not in returned_ids
        assert ct_b not in returned_ids
        assert ct_c in returned_ids

    def test_exclude_campaigns_empty_string_ignored(self, client, db_conn):
        co = _seed_company(db_conn)
        ct_a = _seed_contact(db_conn, co, first="Hank", email="hank_es@test.com")
        ct_b = _seed_contact(db_conn, co, first="Ivy", email="ivy_es@test.com")

        resp = client.get("/api/contacts?exclude_campaigns=")
        assert resp.status_code == 200
        data = resp.json()
        returned_ids = [c["id"] for c in data["contacts"]]
        assert ct_a in returned_ids
        assert ct_b in returned_ids


class TestContactCreate:
    def test_create_success(self, client, db_conn):
        coid = _seed_company(db_conn)
        resp = client.post("/api/contacts", json={
            "first_name": "New", "last_name": "Contact",
            "email": "new@test.com", "company_id": coid,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["id"] > 0

    def test_create_missing_first_name(self, client):
        resp = client.post("/api/contacts", json={
            "last_name": "Only",
        })
        assert resp.status_code == 422

    def test_create_missing_last_name(self, client):
        resp = client.post("/api/contacts", json={
            "first_name": "Only",
        })
        assert resp.status_code == 422

    def test_create_duplicate_email(self, client, db_conn):
        coid = _seed_company(db_conn)
        _seed_contact(db_conn, coid, email="dup@dup.com")
        resp = client.post("/api/contacts", json={
            "first_name": "Dup", "last_name": "Check",
            "email": "dup@dup.com", "company_id": coid,
        })
        assert resp.status_code == 409

    def test_create_invalid_company(self, client):
        resp = client.post("/api/contacts", json={
            "first_name": "Bad", "last_name": "Co",
            "company_id": 99999,
        })
        assert resp.status_code == 404

    def test_create_invalid_lifecycle_stage(self, client, db_conn):
        coid = _seed_company(db_conn)
        resp = client.post("/api/contacts", json={
            "first_name": "Bad", "last_name": "Stage",
            "lifecycle_stage": "invalid_stage", "company_id": coid,
        })
        assert resp.status_code == 400

    def test_create_with_notes(self, client, db_conn):
        coid = _seed_company(db_conn)
        resp = client.post("/api/contacts", json={
            "first_name": "Noted", "last_name": "Person",
            "notes": "Important prospect", "company_id": coid,
        })
        assert resp.status_code == 200

    def test_create_minimal(self, client):
        resp = client.post("/api/contacts", json={
            "first_name": "Min", "last_name": "Contact",
        })
        assert resp.status_code == 200


class TestContactGet:
    def test_get_exists(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.get(f"/api/contacts/{ctid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "contact" in data
        assert "enrollments" in data
        assert "notes" in data
        assert "tags" in data

    def test_get_not_found(self, client):
        resp = client.get("/api/contacts/99999")
        assert resp.status_code == 404

    def test_get_wrong_user(self, client, db_conn):
        """Multi-tenancy: user 1 cannot see user 2's contact."""
        uid2 = _seed_user_2(db_conn)
        coid = _seed_company(db_conn, name="U2_Company", user_id=uid2)
        ctid = _seed_contact(db_conn, coid, email="u2@other.com", user_id=uid2)
        resp = client.get(f"/api/contacts/{ctid}")
        assert resp.status_code == 404


class TestContactLifecycle:
    def test_update_lifecycle(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.patch(f"/api/contacts/{ctid}/lifecycle", json={
            "lifecycle_stage": "contacted",
        })
        assert resp.status_code == 200
        assert resp.json()["lifecycle_stage"] == "contacted"

    def test_update_lifecycle_same_stage(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.patch(f"/api/contacts/{ctid}/lifecycle", json={
            "lifecycle_stage": "cold",  # same as default
        })
        assert resp.status_code == 200

    def test_update_lifecycle_invalid_stage(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.patch(f"/api/contacts/{ctid}/lifecycle", json={
            "lifecycle_stage": "garbage",
        })
        assert resp.status_code == 400

    def test_update_lifecycle_not_found(self, client):
        resp = client.patch("/api/contacts/99999/lifecycle", json={
            "lifecycle_stage": "contacted",
        })
        assert resp.status_code == 404


class TestContactBulkLifecycle:
    def test_bulk_lifecycle_success(self, client, db_conn):
        coid = _seed_company(db_conn)
        ct1 = _seed_contact(db_conn, coid, email="bulk1@test.com")
        ct2 = _seed_contact(db_conn, coid, email="bulk2@test.com")
        resp = client.post("/api/contacts/bulk/lifecycle", json={
            "contact_ids": [ct1, ct2], "lifecycle_stage": "nurturing",
        })
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2

    def test_bulk_lifecycle_empty_ids(self, client):
        resp = client.post("/api/contacts/bulk/lifecycle", json={
            "contact_ids": [], "lifecycle_stage": "contacted",
        })
        assert resp.status_code == 400

    def test_bulk_lifecycle_invalid_stage(self, client, db_conn):
        coid = _seed_company(db_conn)
        ct = _seed_contact(db_conn, coid)
        resp = client.post("/api/contacts/bulk/lifecycle", json={
            "contact_ids": [ct], "lifecycle_stage": "invalid",
        })
        assert resp.status_code == 400

    def test_bulk_lifecycle_missing_contacts(self, client):
        resp = client.post("/api/contacts/bulk/lifecycle", json={
            "contact_ids": [99999], "lifecycle_stage": "contacted",
        })
        assert resp.status_code == 404


class TestContactEvents:
    def test_events_empty(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.get(f"/api/contacts/{ctid}/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_events_not_found(self, client):
        resp = client.get("/api/contacts/99999/events")
        assert resp.status_code == 404

    def test_events_with_data(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        from src.models.events import log_event
        log_event(db_conn, ctid, "contact_created", user_id=TEST_USER_ID)
        db_conn.commit()
        resp = client.get(f"/api/contacts/{ctid}/events")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestContactPatch:
    """Tests for PATCH /contacts/{id} — partial contact update."""

    def test_patch_email(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid, email="old@example.com")
        resp = client.patch(f"/api/contacts/{ctid}", json={"email": "new@example.com"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Verify email_status reset
        from src.models.database import get_cursor
        with get_cursor(db_conn) as cur:
            cur.execute("SELECT email, email_normalized, email_status FROM contacts WHERE id = %s", (ctid,))
            row = cur.fetchone()
        assert row["email"] == "new@example.com"
        assert row["email_normalized"] == "new@example.com"
        assert row["email_status"] == "unverified"

    def test_patch_invalid_email(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.patch(f"/api/contacts/{ctid}", json={"email": "not-an-email"})
        assert resp.status_code == 400

    def test_patch_duplicate_email(self, client, db_conn):
        coid = _seed_company(db_conn)
        ct1 = _seed_contact(db_conn, coid, email="taken@example.com")
        ct2 = _seed_contact(db_conn, coid, email="other@example.com")
        resp = client.patch(f"/api/contacts/{ct2}", json={"email": "taken@example.com"})
        assert resp.status_code == 409

    def test_patch_title_strips_html(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.patch(f"/api/contacts/{ctid}", json={"title": "<script>alert('xss')</script>Portfolio Manager"})
        assert resp.status_code == 200
        from src.models.database import get_cursor
        with get_cursor(db_conn) as cur:
            cur.execute("SELECT title FROM contacts WHERE id = %s", (ctid,))
            row = cur.fetchone()
        assert "<script>" not in row["title"]
        assert "Portfolio Manager" in row["title"]

    def test_patch_name_updates_full_name(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.patch(f"/api/contacts/{ctid}", json={"first_name": "Alice", "last_name": "Smith"})
        assert resp.status_code == 200
        from src.models.database import get_cursor
        with get_cursor(db_conn) as cur:
            cur.execute("SELECT first_name, last_name, full_name FROM contacts WHERE id = %s", (ctid,))
            row = cur.fetchone()
        assert row["full_name"] == "Alice Smith"
        assert row["first_name"] == "Alice"
        assert row["last_name"] == "Smith"

    def test_patch_empty_first_name_rejected(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.patch(f"/api/contacts/{ctid}", json={"first_name": "", "last_name": "Smith"})
        assert resp.status_code == 400

    def test_patch_no_fields_rejected(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.patch(f"/api/contacts/{ctid}", json={})
        assert resp.status_code == 400

    def test_patch_not_found(self, client):
        resp = client.patch("/api/contacts/99999", json={"title": "CEO"})
        assert resp.status_code == 404

    def test_patch_multiple_fields(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid, email="old@test.com")
        resp = client.patch(f"/api/contacts/{ctid}", json={
            "email": "new@test.com",
            "title": "Managing Director",
            "first_name": "Jane",
            "last_name": "Doe",
        })
        assert resp.status_code == 200
        contact = resp.json()["contact"]
        assert contact["email"] == "new@test.com"
        assert contact["title"] == "Managing Director"
        assert contact["full_name"] == "Jane Doe"

    def test_patch_email_clears_channel_override(self, client, db_conn):
        """Email change should clear channel_override for queue dedup re-evaluation."""
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid, email="old@test.com")
        from src.models.campaigns import create_campaign
        camp = create_campaign(db_conn, "TestCamp", user_id=TEST_USER_ID)
        from src.models.enrollment import enroll_contact
        enroll_contact(db_conn, ctid, camp, user_id=TEST_USER_ID)
        from src.models.database import get_cursor
        with get_cursor(db_conn) as cur:
            cur.execute(
                "UPDATE contact_campaign_status SET channel_override = 'linkedin_only' WHERE contact_id = %s",
                (ctid,),
            )
        db_conn.commit()
        resp = client.patch(f"/api/contacts/{ctid}", json={"email": "new@test.com"})
        assert resp.status_code == 200
        with get_cursor(db_conn) as cur:
            cur.execute(
                "SELECT channel_override FROM contact_campaign_status WHERE contact_id = %s",
                (ctid,),
            )
            row = cur.fetchone()
        assert row["channel_override"] is None

    def test_patch_phone(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.patch(f"/api/contacts/{ctid}", json={"phone_number": "+1 (555) 123-4567"})
        assert resp.status_code == 200
        contact = resp.json()["contact"]
        assert contact["phone_number"] == "+1 (555) 123-4567"
        assert contact["phone_normalized"] == "+15551234567"

    def test_patch_phone_invalid(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.patch(f"/api/contacts/{ctid}", json={"phone_number": "abc"})
        assert resp.status_code == 400

    def test_patch_only_first_name_preserves_last(self, client, db_conn):
        """Patching only first_name should keep the existing last_name."""
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        # Set initial name
        client.patch(f"/api/contacts/{ctid}", json={"first_name": "Alice", "last_name": "Johnson"})
        # Patch only first_name
        resp = client.patch(f"/api/contacts/{ctid}", json={"first_name": "Bob"})
        assert resp.status_code == 200
        contact = resp.json()["contact"]
        assert contact["first_name"] == "Bob"
        assert contact["last_name"] == "Johnson"
        assert contact["full_name"] == "Bob Johnson"


class TestContactNotes:
    def test_add_note(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.post(f"/api/contacts/{ctid}/notes", json={
            "content": "Met at conference",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_add_note_not_found(self, client):
        resp = client.post("/api/contacts/99999/notes", json={
            "content": "Should fail",
        })
        assert resp.status_code == 404


# ============================================================================
# CONVERSATION ROUTES (/api/contacts/{id}/conversations, /api/conversations/*)
# ============================================================================

class TestConversations:
    def test_list_conversations_empty(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.get(f"/api/contacts/{ctid}/conversations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_conversation(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.post(f"/api/contacts/{ctid}/conversations", json={
            "channel": "phone", "title": "Intro call",
            "notes": "Discussed fund strategy",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        conv_id = resp.json()["id"]
        assert conv_id > 0

    def test_create_conversation_invalid_channel(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.post(f"/api/contacts/{ctid}/conversations", json={
            "channel": "pigeon", "title": "Bad channel",
        })
        assert resp.status_code in (400, 422)

    def test_create_conversation_invalid_outcome(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.post(f"/api/contacts/{ctid}/conversations", json={
            "channel": "phone", "title": "Test", "outcome": "maybe",
        })
        assert resp.status_code in (400, 422)

    def test_create_conversation_not_found(self, client):
        resp = client.post("/api/contacts/99999/conversations", json={
            "channel": "phone", "title": "Ghost",
        })
        assert resp.status_code == 404

    def test_create_conversation_successful_advances_lifecycle(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.post(f"/api/contacts/{ctid}/conversations", json={
            "channel": "phone", "title": "Good call",
            "outcome": "successful",
        })
        assert resp.status_code == 200

    def test_update_conversation(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.post(f"/api/contacts/{ctid}/conversations", json={
            "channel": "phone", "title": "Original title",
        })
        conv_id = resp.json()["id"]
        resp2 = client.put(f"/api/conversations/{conv_id}", json={
            "title": "Updated title",
        })
        assert resp2.status_code == 200
        assert resp2.json()["success"] is True

    def test_update_conversation_not_found(self, client):
        resp = client.put("/api/conversations/99999", json={"title": "Nope"})
        assert resp.status_code == 404

    def test_update_conversation_invalid_channel(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.post(f"/api/contacts/{ctid}/conversations", json={
            "channel": "phone", "title": "Test",
        })
        conv_id = resp.json()["id"]
        resp2 = client.put(f"/api/conversations/{conv_id}", json={
            "channel": "pigeon",
        })
        assert resp2.status_code in (400, 422)

    def test_delete_conversation(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.post(f"/api/contacts/{ctid}/conversations", json={
            "channel": "phone", "title": "To delete",
        })
        conv_id = resp.json()["id"]
        resp2 = client.delete(f"/api/conversations/{conv_id}")
        assert resp2.status_code == 200
        assert resp2.json()["success"] is True

    def test_delete_conversation_not_found(self, client):
        resp = client.delete("/api/conversations/99999")
        assert resp.status_code == 404


# ============================================================================
# CRM ROUTES (/api/crm/*)
# ============================================================================

class TestCrmCompanies:
    def test_list_companies_empty(self, client):
        resp = client.get("/api/crm/companies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["companies"] == []
        assert data["total"] == 0

    def test_list_companies_with_data(self, client, db_conn):
        _seed_company(db_conn, "CRM Corp")
        resp = client.get("/api/crm/companies")
        data = resp.json()
        assert data["total"] >= 1

    def test_list_companies_search(self, client, db_conn):
        _seed_company(db_conn, "Unique Quantum Fund")
        resp = client.get("/api/crm/companies?search=Quantum")
        data = resp.json()
        assert data["total"] >= 1

    def test_list_companies_filter_firm_type(self, client, db_conn):
        _seed_company(db_conn, "Family Office Fund", firm_type="Family Office")
        resp = client.get("/api/crm/companies?firm_type=Family Office")
        data = resp.json()
        assert data["total"] >= 1

    def test_company_detail(self, client, db_conn):
        coid = _seed_company(db_conn, "Detail Corp")
        _seed_contact(db_conn, coid, email="detail@corp.com")
        resp = client.get(f"/api/crm/companies/{coid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["company"]["name"] == "Detail Corp"
        assert len(data["contacts"]) == 1
        assert "event_count" in data

    def test_company_detail_not_found(self, client):
        resp = client.get("/api/crm/companies/99999")
        assert resp.status_code == 404


class TestCrmContacts:
    def test_list_crm_contacts(self, client, db_conn):
        coid = _seed_company(db_conn)
        _seed_contact(db_conn, coid)
        resp = client.get("/api/crm/contacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_crm_contacts_search(self, client, db_conn):
        coid = _seed_company(db_conn, "CRM Search Co")
        _seed_contact(db_conn, coid, first="CrmSearchTarget", email="crmsearch@test.com")
        resp = client.get("/api/crm/contacts?search=CrmSearchTarget")
        data = resp.json()
        assert data["total"] >= 1

    def test_crm_contacts_filter_aum(self, client, db_conn):
        coid = _seed_company(db_conn, aum=5000.0)
        _seed_contact(db_conn, coid, email="bigaum@test.com")
        resp = client.get("/api/crm/contacts?min_aum=4000")
        data = resp.json()
        assert data["total"] >= 1

    def test_crm_contacts_sort(self, client, db_conn):
        coid = _seed_company(db_conn)
        _seed_contact(db_conn, coid)
        resp = client.get("/api/crm/contacts?sort_by=full_name&sort_dir=asc")
        assert resp.status_code == 200


class TestCrmTimeline:
    def test_timeline_empty(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        resp = client.get(f"/api/crm/contacts/{ctid}/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []

    def test_timeline_not_found(self, client):
        resp = client.get("/api/crm/contacts/99999/timeline")
        assert resp.status_code == 404


class TestCrmGlobalSearch:
    def test_search_contacts(self, client, db_conn):
        coid = _seed_company(db_conn, "Global Search Corp")
        _seed_contact(db_conn, coid, first="Searchable", email="gsearch@test.com")
        resp = client.get("/api/crm/search?q=Searchable")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_search_companies(self, client, db_conn):
        _seed_company(db_conn, "Acme Global Partners")
        resp = client.get("/api/crm/search?q=Acme Global")
        data = resp.json()
        assert any(c["name"] == "Acme Global Partners" for c in data["companies"])

    def test_search_empty_results(self, client):
        resp = client.get("/api/crm/search?q=zzz_nonexistent_zzz")
        data = resp.json()
        assert data["total"] == 0

    def test_search_missing_query(self, client):
        resp = client.get("/api/crm/search")
        assert resp.status_code == 422


# ============================================================================
# DEAL ROUTES (/api/deals/*)
# ============================================================================

class TestDealPipeline:
    def test_pipeline_empty(self, client):
        resp = client.get("/api/deals/pipeline")
        assert resp.status_code == 200
        data = resp.json()
        assert "pipeline" in data
        # Should have all stages as keys
        assert "cold" in data["pipeline"]
        assert "won" in data["pipeline"]

    def test_pipeline_with_deals(self, client, db_conn):
        coid = _seed_company(db_conn)
        _seed_deal(db_conn, coid, stage="cold")
        _seed_deal(db_conn, coid, stage="engaged")
        resp = client.get("/api/deals/pipeline")
        data = resp.json()
        assert len(data["pipeline"]["cold"]) >= 1
        assert len(data["pipeline"]["engaged"]) >= 1


class TestDealList:
    def test_list_empty(self, client):
        resp = client.get("/api/deals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deals"] == []
        assert data["total"] == 0

    def test_list_with_data(self, client, db_conn):
        coid = _seed_company(db_conn)
        _seed_deal(db_conn, coid)
        resp = client.get("/api/deals")
        data = resp.json()
        assert data["total"] >= 1

    def test_list_filter_stage(self, client, db_conn):
        coid = _seed_company(db_conn)
        _seed_deal(db_conn, coid, stage="won")
        resp = client.get("/api/deals?stage=won")
        data = resp.json()
        for d in data["deals"]:
            assert d["stage"] == "won"

    def test_list_filter_min_amount(self, client, db_conn):
        coid = _seed_company(db_conn)
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO deals (company_id, title, stage, amount_millions, user_id) VALUES (%s, 'Big Deal', 'cold', 50.0, %s) RETURNING id",
            (coid, TEST_USER_ID),
        )
        db_conn.commit()
        cur.close()
        resp = client.get("/api/deals?min_amount=40")
        data = resp.json()
        assert data["total"] >= 1


class TestDealCreate:
    def test_create_success(self, client, db_conn):
        coid = _seed_company(db_conn)
        resp = client.post("/api/deals", json={
            "company_id": coid, "title": "New Deal",
            "stage": "cold", "amount_millions": 10.0,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["id"] > 0

    def test_create_invalid_stage(self, client, db_conn):
        coid = _seed_company(db_conn)
        resp = client.post("/api/deals", json={
            "company_id": coid, "title": "Bad Stage",
            "stage": "invalid_stage",
        })
        assert resp.status_code in (400, 422)

    def test_create_company_not_found(self, client):
        resp = client.post("/api/deals", json={
            "company_id": 99999, "title": "Ghost Company",
        })
        assert resp.status_code == 404

    def test_create_contact_not_found(self, client, db_conn):
        coid = _seed_company(db_conn)
        resp = client.post("/api/deals", json={
            "company_id": coid, "title": "Bad Contact",
            "contact_id": 99999,
        })
        assert resp.status_code == 404

    def test_create_missing_title(self, client, db_conn):
        coid = _seed_company(db_conn)
        resp = client.post("/api/deals", json={"company_id": coid})
        assert resp.status_code == 422


class TestDealGet:
    def test_get_success(self, client, db_conn):
        coid = _seed_company(db_conn)
        did = _seed_deal(db_conn, coid)
        resp = client.get(f"/api/deals/{did}")
        assert resp.status_code == 200
        data = resp.json()
        assert "deal" in data
        assert "stage_history" in data
        assert len(data["stage_history"]) >= 1

    def test_get_not_found(self, client):
        resp = client.get("/api/deals/99999")
        assert resp.status_code == 404


class TestDealUpdate:
    def test_update_success(self, client, db_conn):
        coid = _seed_company(db_conn)
        did = _seed_deal(db_conn, coid)
        resp = client.put(f"/api/deals/{did}", json={
            "title": "Updated Title", "amount_millions": 25.0,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update_not_found(self, client):
        resp = client.put("/api/deals/99999", json={"title": "Nope"})
        assert resp.status_code == 404

    def test_update_no_fields(self, client, db_conn):
        coid = _seed_company(db_conn)
        did = _seed_deal(db_conn, coid)
        resp = client.put(f"/api/deals/{did}", json={})
        assert resp.status_code == 400


class TestDealStageChange:
    def test_stage_change(self, client, db_conn):
        coid = _seed_company(db_conn)
        did = _seed_deal(db_conn, coid, stage="cold")
        resp = client.patch(f"/api/deals/{did}/stage", json={"stage": "engaged"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] == "engaged"
        assert data["from_stage"] == "cold"
        assert data["changed"] is True

    def test_stage_change_same_stage(self, client, db_conn):
        coid = _seed_company(db_conn)
        did = _seed_deal(db_conn, coid, stage="cold")
        resp = client.patch(f"/api/deals/{did}/stage", json={"stage": "cold"})
        assert resp.status_code == 200
        assert resp.json()["changed"] is False

    def test_stage_change_invalid(self, client, db_conn):
        coid = _seed_company(db_conn)
        did = _seed_deal(db_conn, coid)
        resp = client.patch(f"/api/deals/{did}/stage", json={"stage": "invalid"})
        assert resp.status_code in (400, 422)

    def test_stage_change_not_found(self, client):
        resp = client.patch("/api/deals/99999/stage", json={"stage": "won"})
        assert resp.status_code == 404


class TestDealDelete:
    def test_delete_success(self, client, db_conn):
        coid = _seed_company(db_conn)
        did = _seed_deal(db_conn, coid)
        resp = client.delete(f"/api/deals/{did}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Verify deleted
        resp2 = client.get(f"/api/deals/{did}")
        assert resp2.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete("/api/deals/99999")
        assert resp.status_code == 404


# ============================================================================
# DEEP RESEARCH ROUTES (/api/research/deep/*)
# ============================================================================

class TestDeepResearchTrigger:
    @patch("src.web.routes.deep_research._trigger_deep_research")
    @patch("src.web.routes.deep_research.get_user_api_keys", return_value={"perplexity": "pplx-key", "anthropic": "ant-key"})
    def test_trigger_success(self, mock_keys, mock_trigger, client, db_conn):
        coid = _seed_company(db_conn, country="US")
        resp = client.post(f"/api/research/deep/{coid}")
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pending"
        assert "id" in data
        assert "cost_estimate_usd" in data

    def test_trigger_company_not_found(self, client):
        resp = client.post("/api/research/deep/99999")
        assert resp.status_code == 404

    @patch("src.web.routes.deep_research.get_user_api_keys", return_value={"perplexity": "", "anthropic": ""})
    def test_trigger_no_api_key(self, mock_keys, client, db_conn):
        coid = _seed_company(db_conn)
        resp = client.post(f"/api/research/deep/{coid}")
        assert resp.status_code == 400

    @patch("src.web.routes.deep_research._trigger_deep_research")
    @patch("src.web.routes.deep_research.get_user_api_keys", return_value={"perplexity": "pplx-key", "anthropic": "ant-key"})
    def test_trigger_duplicate(self, mock_keys, mock_trigger, client, db_conn):
        coid = _seed_company(db_conn)
        # First trigger
        client.post(f"/api/research/deep/{coid}")
        # Second trigger should conflict
        resp = client.post(f"/api/research/deep/{coid}")
        assert resp.status_code == 409


class TestDeepResearchGet:
    def test_get_no_research(self, client, db_conn):
        coid = _seed_company(db_conn)
        resp = client.get(f"/api/research/deep/{coid}")
        assert resp.status_code == 404

    @patch("src.web.routes.deep_research._trigger_deep_research")
    @patch("src.web.routes.deep_research.get_user_api_keys", return_value={"perplexity": "pplx-key", "anthropic": "ant-key"})
    def test_get_existing_research(self, mock_keys, mock_trigger, client, db_conn):
        coid = _seed_company(db_conn)
        client.post(f"/api/research/deep/{coid}")
        resp = client.get(f"/api/research/deep/{coid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["company_id"] == coid


class TestDeepResearchCancel:
    @patch("src.web.routes.deep_research._trigger_deep_research")
    @patch("src.web.routes.deep_research.get_user_api_keys", return_value={"perplexity": "pplx-key", "anthropic": "ant-key"})
    def test_cancel_success(self, mock_keys, mock_trigger, client, db_conn):
        coid = _seed_company(db_conn)
        resp = client.post(f"/api/research/deep/{coid}")
        dr_id = resp.json()["id"]
        resp2 = client.post(f"/api/research/deep/{dr_id}/cancel")
        assert resp2.status_code == 200
        assert resp2.json()["success"] is True

    def test_cancel_not_found(self, client):
        resp = client.post("/api/research/deep/99999/cancel")
        assert resp.status_code == 404

    @patch("src.web.routes.deep_research._trigger_deep_research")
    @patch("src.web.routes.deep_research.get_user_api_keys", return_value={"perplexity": "pplx-key", "anthropic": "ant-key"})
    def test_cancel_already_cancelled(self, mock_keys, mock_trigger, client, db_conn):
        coid = _seed_company(db_conn)
        resp = client.post(f"/api/research/deep/{coid}")
        dr_id = resp.json()["id"]
        client.post(f"/api/research/deep/{dr_id}/cancel")
        resp2 = client.post(f"/api/research/deep/{dr_id}/cancel")
        assert resp2.status_code == 400


# ============================================================================
# GMAIL ROUTES (/api/gmail/*)
# ============================================================================

class TestGmailStatus:
    def test_gmail_status(self, client):
        resp = client.get("/api/gmail/status")
        assert resp.status_code == 200
        assert "authorized" in resp.json()


class TestGmailDrafts:
    @patch("src.web.routes.gmail._get_user_drafter")
    def test_create_draft_unauthorized(self, mock_get_drafter, client):
        mock_drafter = MagicMock()
        mock_drafter.is_authorized.return_value = False
        mock_get_drafter.return_value = mock_drafter
        resp = client.post("/api/gmail/drafts", json={
            "contact_id": 1, "subject": "Hi", "body_text": "Hello",
        })
        assert resp.status_code == 401

    @patch("src.web.routes.gmail._get_user_drafter")
    def test_create_draft_campaign_not_found(self, mock_get_drafter, client):
        mock_drafter = MagicMock()
        mock_drafter.is_authorized.return_value = True
        mock_get_drafter.return_value = mock_drafter
        resp = client.post("/api/gmail/drafts", json={
            "contact_id": 1, "campaign": "nonexistent",
            "subject": "Hi", "body_text": "Hello",
        })
        assert resp.status_code == 404


class TestGmailBatchDrafts:
    @patch("src.web.routes.gmail._get_user_drafter")
    def test_batch_drafts_unauthorized(self, mock_get_drafter, client):
        mock_drafter = MagicMock()
        mock_drafter.is_authorized.return_value = False
        mock_get_drafter.return_value = mock_drafter
        resp = client.post("/api/gmail/drafts/batch", json={
            "campaign": "test",
        })
        assert resp.status_code == 401

    @patch("src.web.routes.gmail._get_user_drafter")
    def test_batch_drafts_campaign_not_found(self, mock_get_drafter, client):
        mock_drafter = MagicMock()
        mock_drafter.is_authorized.return_value = True
        mock_get_drafter.return_value = mock_drafter
        resp = client.post("/api/gmail/drafts/batch", json={
            "campaign": "nonexistent",
        })
        assert resp.status_code == 404


# ============================================================================
# GMAIL OAUTH ROUTES (/api/auth/gmail/*)
# ============================================================================

class TestGmailOAuth:
    @patch("src.web.routes.gmail_oauth.GOOGLE_CLIENT_ID", "")
    def test_connect_no_client_id(self, client):
        resp = client.get("/api/auth/gmail/connect", follow_redirects=False)
        assert resp.status_code == 500

    @patch("src.web.routes.gmail_oauth.GOOGLE_CLIENT_ID", "fake-client-id")
    def test_connect_redirects(self, client):
        resp = client.get("/api/auth/gmail/connect", follow_redirects=False)
        # Should redirect to Google OAuth
        assert resp.status_code == 307
        assert "accounts.google.com" in resp.headers.get("location", "")

    def test_callback_missing_params(self, client):
        resp = client.get("/api/auth/gmail/callback", follow_redirects=False)
        assert resp.status_code == 307
        assert "missing_params" in resp.headers.get("location", "")

    def test_callback_error_param(self, client):
        resp = client.get("/api/auth/gmail/callback?error=access_denied", follow_redirects=False)
        assert resp.status_code == 307
        assert "access_denied" in resp.headers.get("location", "")

    def test_callback_invalid_state(self, client):
        resp = client.get("/api/auth/gmail/callback?code=abc&state=bad", follow_redirects=False)
        assert resp.status_code == 307
        assert "invalid_state" in resp.headers.get("location", "")

    def test_disconnect(self, client):
        resp = client.post("/api/auth/gmail/disconnect")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ============================================================================
# IMPORT ROUTES (/api/import/*)
# ============================================================================

class TestImport:
    def test_dedupe_empty(self, client):
        resp = client.post("/api/import/dedupe")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_csv_import_no_file(self, client):
        resp = client.post("/api/import/csv")
        assert resp.status_code == 422

    def test_csv_import_wrong_extension(self, client):
        import io
        resp = client.post("/api/import/csv", files={
            "file": ("data.txt", io.BytesIO(b"hello"), "text/plain"),
        })
        assert resp.status_code == 400


# ============================================================================
# INBOX ROUTES (/api/inbox)
# ============================================================================

class TestInbox:
    def test_inbox_empty(self, client):
        resp = client.get("/api/inbox")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_inbox_filter_channel_email(self, client):
        resp = client.get("/api/inbox?channel=email")
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_inbox_filter_channel_notes(self, client):
        resp = client.get("/api/inbox?channel=notes")
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_inbox_pagination(self, client):
        resp = client.get("/api/inbox?page=1&per_page=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["per_page"] == 10

    def test_inbox_with_note_data(self, client, db_conn):
        coid = _seed_company(db_conn)
        ctid = _seed_contact(db_conn, coid)
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO response_notes (contact_id, note_type, content, user_id) VALUES (%s, 'general', 'Test note', %s)",
            (ctid, TEST_USER_ID),
        )
        db_conn.commit()
        cur.close()
        resp = client.get("/api/inbox?channel=notes")
        data = resp.json()
        assert data["total"] >= 1


# ============================================================================
# INSIGHTS ROUTES (/api/insights/*)
# ============================================================================

class TestInsights:
    @patch("src.web.routes.insights.run_analysis")
    def test_analyze_success(self, mock_run, client, db_conn):
        camp_id = _seed_campaign(db_conn)
        mock_run.return_value = {"insights": "test", "campaign_id": camp_id}
        resp = client.post("/api/insights/analyze", json={"campaign_id": camp_id})
        assert resp.status_code == 200

    def test_analyze_campaign_not_found(self, client):
        resp = client.post("/api/insights/analyze", json={"campaign_id": 99999})
        assert resp.status_code == 404

    def test_history_empty(self, client):
        resp = client.get("/api/insights/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_campaign_filter_not_found(self, client):
        resp = client.get("/api/insights/history?campaign_id=99999")
        assert resp.status_code == 404


# ============================================================================
# MULTI-TENANCY TESTS (cross-cutting)
# ============================================================================

class TestMultiTenancy:
    def test_contacts_isolated(self, client, db_conn):
        """User 1 cannot see user 2's contacts via GET /api/contacts/{id}."""
        uid2 = _seed_user_2(db_conn)
        coid = _seed_company(db_conn, name="U2 Corp", user_id=uid2)
        ctid = _seed_contact(db_conn, coid, email="hidden@u2.com", user_id=uid2)
        resp = client.get(f"/api/contacts/{ctid}")
        assert resp.status_code == 404

    def test_companies_isolated(self, client, db_conn):
        """User 1 cannot see user 2's companies via GET /api/crm/companies/{id}."""
        uid2 = _seed_user_2(db_conn)
        coid = _seed_company(db_conn, name="U2 Stealth Co", user_id=uid2)
        resp = client.get(f"/api/crm/companies/{coid}")
        assert resp.status_code == 404

    def test_deals_isolated(self, client, db_conn):
        """User 1 cannot see user 2's deals via GET /api/deals/{id}."""
        uid2 = _seed_user_2(db_conn)
        coid = _seed_company(db_conn, name="U2 Deal Corp", user_id=uid2)
        did = _seed_deal(db_conn, coid, user_id=uid2)
        resp = client.get(f"/api/deals/{did}")
        assert resp.status_code == 404

    def test_campaigns_isolated(self, client, db_conn):
        """User 1 cannot see user 2's campaigns via GET /api/campaigns/{name}."""
        uid2 = _seed_user_2(db_conn)
        from src.models.campaigns import create_campaign
        create_campaign(db_conn, "u2_secret_campaign", user_id=uid2)
        resp = client.get("/api/campaigns/u2_secret_campaign")
        assert resp.status_code == 404

    def test_contact_list_isolated(self, client, db_conn):
        """User 1's contact list excludes user 2's contacts."""
        uid2 = _seed_user_2(db_conn)
        coid = _seed_company(db_conn, name="U2 List Corp", user_id=uid2)
        _seed_contact(db_conn, coid, first="Invisible", email="invisible@u2.com", user_id=uid2)
        resp = client.get("/api/contacts?search=Invisible")
        data = resp.json()
        assert data["total"] == 0

    def test_deal_delete_isolated(self, client, db_conn):
        """User 1 cannot delete user 2's deal."""
        uid2 = _seed_user_2(db_conn)
        coid = _seed_company(db_conn, name="U2 Del Corp", user_id=uid2)
        did = _seed_deal(db_conn, coid, user_id=uid2)
        resp = client.delete(f"/api/deals/{did}")
        assert resp.status_code == 404
