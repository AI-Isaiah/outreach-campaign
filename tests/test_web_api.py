"""Tests for the FastAPI web API routes (Phase 1)."""

from __future__ import annotations

import json
from unittest.mock import patch

import psycopg2
import psycopg2.extras
import pytest
from fastapi.testclient import TestClient

from src.models.database import get_connection, run_migrations
from src.web.app import app
from src.web.dependencies import get_db
from tests.conftest import TEST_USER_ID


@pytest.fixture
def db_conn(tmp_db):
    """Provide a database connection for test setup."""
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


def _seed_company(conn, name="Test Fund", aum=500.0, firm_type="Hedge Fund"):
    """Insert a test company and return its id."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country, user_id)
           VALUES (%s, %s, %s, %s, 'US', %s) RETURNING id""",
        (name, name.lower(), aum, firm_type, TEST_USER_ID),
    )
    conn.commit()
    return cur.fetchone()["id"]


def _seed_contact(conn, company_id, first="John", last="Doe", email="john@test.com"):
    """Insert a test contact and return its id."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name, email,
                                 email_normalized, email_status, user_id)
           VALUES (%s, %s, %s, %s, %s, %s, 'valid', %s) RETURNING id""",
        (company_id, first, last, f"{first} {last}", email, email.lower(), TEST_USER_ID),
    )
    conn.commit()
    return cur.fetchone()["id"]


def _seed_campaign(conn, name="test_campaign"):
    """Insert a test campaign and return its id."""
    from src.models.campaigns import create_campaign
    return create_campaign(conn, name, user_id=TEST_USER_ID)


# ---------- Health ----------

def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------- Templates CRUD ----------

def test_create_template(client):
    resp = client.post("/api/templates", json={
        "name": "intro_email_v1",
        "channel": "email",
        "body_template": "Hello {{ first_name }}",
        "subject": "Intro",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["id"] > 0


def test_list_templates(client, db_conn):
    from src.models.templates import create_template
    create_template(db_conn, "t1", "email", "body1", subject="subj1", user_id=TEST_USER_ID)
    create_template(db_conn, "t2", "linkedin_connect", "body2", user_id=TEST_USER_ID)

    resp = client.get("/api/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


def test_list_templates_by_channel(client, db_conn):
    from src.models.templates import create_template
    create_template(db_conn, "t1", "email", "body1", user_id=TEST_USER_ID)
    create_template(db_conn, "t2", "linkedin_connect", "body2", user_id=TEST_USER_ID)

    resp = client.get("/api/templates?channel=email")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["channel"] == "email"


def test_get_template(client, db_conn):
    from src.models.templates import create_template
    tid = create_template(db_conn, "test_tmpl", "email", "body", subject="subj", user_id=TEST_USER_ID)

    resp = client.get(f"/api/templates/{tid}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "test_tmpl"


def test_get_template_not_found(client):
    resp = client.get("/api/templates/9999")
    assert resp.status_code == 404


def test_update_template(client, db_conn):
    from src.models.templates import create_template
    tid = create_template(db_conn, "old_name", "email", "old body", user_id=TEST_USER_ID)

    resp = client.put(f"/api/templates/{tid}", json={"name": "new_name"})
    assert resp.status_code == 200

    resp2 = client.get(f"/api/templates/{tid}")
    assert resp2.json()["name"] == "new_name"


def test_deactivate_template(client, db_conn):
    from src.models.templates import create_template
    tid = create_template(db_conn, "to_deactivate", "email", "body", user_id=TEST_USER_ID)

    resp = client.patch(f"/api/templates/{tid}/deactivate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


# ---------- Pending Replies ----------

def test_list_pending_replies_empty(client):
    resp = client.get("/api/replies/pending")
    assert resp.status_code == 200
    data = resp.json()
    assert data["replies"] == []
    assert "last_auto_scan_at" in data


def test_confirm_reply(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)
    campaign_id = _seed_campaign(db_conn)

    cur = db_conn.cursor()
    cur.execute(
        """INSERT INTO pending_replies (contact_id, campaign_id, subject, snippet,
                                        classification, confidence, confirmed)
           VALUES (%s, %s, 'Re: Intro', 'Sounds great!', 'positive', 0.95, false)
           RETURNING id""",
        (contact_id, campaign_id),
    )
    reply_id = cur.fetchone()["id"]
    db_conn.commit()

    resp = client.post(f"/api/replies/{reply_id}/confirm", json={
        "outcome": "replied_positive",
        "note": "Very interested in meeting",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_confirm_reply_not_found(client):
    resp = client.post("/api/replies/9999/confirm", json={"outcome": "replied_positive"})
    assert resp.status_code == 404


def test_reply_scan(client):
    """Scan with no enrolled contacts should return ok with zero scanned."""
    resp = client.post("/api/replies/scan")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["scanned"] == 0


# ---------- CRM Contacts ----------

def test_crm_contacts_list(client, db_conn):
    company_id = _seed_company(db_conn)
    _seed_contact(db_conn, company_id)

    resp = client.get("/api/crm/contacts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["contacts"]) >= 1


def test_crm_contacts_search(client, db_conn):
    company_id = _seed_company(db_conn, name="Alpha Capital")
    _seed_contact(db_conn, company_id, first="Alice", last="Smith", email="alice@alpha.com")

    resp = client.get("/api/crm/contacts?search=Alice")
    data = resp.json()
    assert data["total"] >= 1


def test_crm_contacts_filter_aum(client, db_conn):
    co1 = _seed_company(db_conn, name="Small Fund", aum=50.0)
    co2 = _seed_company(db_conn, name="Big Fund", aum=2000.0)
    _seed_contact(db_conn, co1, email="a@small.com")
    _seed_contact(db_conn, co2, email="b@big.com")

    resp = client.get("/api/crm/contacts?min_aum=1000")
    data = resp.json()
    assert data["total"] >= 1
    for c in data["contacts"]:
        assert c["aum_millions"] >= 1000


# ---------- CRM Timeline ----------

def test_crm_timeline_empty(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)

    resp = client.get(f"/api/crm/contacts/{contact_id}/timeline")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entries"] == []


def test_crm_timeline_with_events(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)
    campaign_id = _seed_campaign(db_conn)

    from src.models.events import log_event
    log_event(db_conn, contact_id, "email_sent", campaign_id=campaign_id, user_id=1)
    db_conn.commit()

    resp = client.get(f"/api/crm/contacts/{contact_id}/timeline")
    data = resp.json()
    assert data["total"] >= 1


def test_crm_timeline_not_found(client):
    resp = client.get("/api/crm/contacts/9999/timeline")
    assert resp.status_code == 404


# ---------- CRM Companies ----------

def test_crm_companies_list(client, db_conn):
    _seed_company(db_conn)

    resp = client.get("/api/crm/companies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


def test_crm_company_detail(client, db_conn):
    company_id = _seed_company(db_conn, name="Detail Fund")
    _seed_contact(db_conn, company_id, email="detail@fund.com")

    resp = client.get(f"/api/crm/companies/{company_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["company"]["name"] == "Detail Fund"
    assert len(data["contacts"]) == 1


def test_crm_company_not_found(client):
    resp = client.get("/api/crm/companies/9999")
    assert resp.status_code == 404


# ---------- CRM Search ----------

def test_global_search(client, db_conn):
    company_id = _seed_company(db_conn, name="Searchable Corp")
    _seed_contact(db_conn, company_id, first="SearchMe", email="sm@test.com")

    resp = client.get("/api/crm/search?q=SearchMe")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


def test_global_search_empty(client):
    resp = client.get("/api/crm/search?q=nonexistent_xyz_123")
    data = resp.json()
    assert data["total"] == 0


# ---------- Campaign Weekly / Report ----------

def test_campaign_weekly(client, db_conn):
    _seed_campaign(db_conn, "weekly_test")

    resp = client.get("/api/campaigns/weekly_test/weekly")
    assert resp.status_code == 200
    data = resp.json()
    assert data["campaign"] == "weekly_test"
    assert "weekly" in data


def test_campaign_report(client, db_conn):
    _seed_campaign(db_conn, "report_test")

    resp = client.get("/api/campaigns/report_test/report")
    assert resp.status_code == 200
    data = resp.json()
    assert "metrics" in data
    assert "variants" in data


def test_campaign_weekly_not_found(client):
    resp = client.get("/api/campaigns/nonexistent/weekly")
    assert resp.status_code == 404


# ---------- Queue Override ----------

def test_queue_override(client, db_conn):
    campaign_id = _seed_campaign(db_conn, "override_test")
    from src.models.templates import create_template
    tid = create_template(db_conn, "override_tmpl", "email", "body", user_id=TEST_USER_ID)

    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)

    resp = client.post("/api/queue/override_test/override", json={
        "contact_id": contact_id,
        "template_id": tid,
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------- Phone Update ----------

def test_update_phone(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)

    resp = client.post(f"/api/contacts/{contact_id}/phone", json={
        "phone_number": "+1 (555) 123-4567",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["phone_normalized"] == "+15551234567"


def test_update_phone_invalid(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)

    resp = client.post(f"/api/contacts/{contact_id}/phone", json={
        "phone_number": "abc",
    })
    assert resp.status_code == 400


def test_update_phone_not_found(client):
    resp = client.post("/api/contacts/9999/phone", json={
        "phone_number": "+15551234567",
    })
    assert resp.status_code == 404


# ---------- Settings ----------

def test_get_settings(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "engine_config" in data
    assert "gmail_authorized" in data


def test_update_settings(client):
    resp = client.put("/api/settings", json={
        "settings": {"explore_rate": "0.15", "max_daily_emails": "10"},
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Verify the settings persisted
    resp2 = client.get("/api/settings")
    config = resp2.json()["engine_config"]
    assert config["explore_rate"] == "0.15"
    assert config["max_daily_emails"] == "10"


# ---------- Import (placeholder test) ----------

def test_import_dedupe(client):
    """Test the dedupe endpoint runs without error on empty DB."""
    resp = client.post("/api/import/dedupe")
    assert resp.status_code == 200


# ---------- Queue Defer ----------

def test_defer_contact(client, db_conn):
    """Test deferring a contact moves them to tomorrow."""
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)
    campaign_id = _seed_campaign(db_conn, "defer_test")

    from src.models.campaigns import enroll_contact
    from datetime import date
    enroll_contact(db_conn, contact_id, campaign_id, next_action_date=date.today().isoformat(), user_id=1)

    resp = client.post(f"/api/queue/{contact_id}/defer", json={
        "campaign": "defer_test",
        "reason": "Bad timing",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["reason"] == "Bad timing"
    assert data["next_action_date"] is not None


def test_defer_contact_not_enrolled(client, db_conn):
    """Deferring a contact not enrolled returns 404."""
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)
    _seed_campaign(db_conn, "defer_not_enrolled")

    resp = client.post(f"/api/queue/{contact_id}/defer", json={
        "campaign": "defer_not_enrolled",
    })
    assert resp.status_code == 404


def test_defer_stats_empty(client):
    """Defer stats on empty DB returns zeroes."""
    resp = client.get("/api/queue/defer/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["today_count"] == 0
    assert data["total_count"] == 0


def test_defer_stats_after_defer(client, db_conn):
    """Defer stats reflect deferred contacts."""
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)
    campaign_id = _seed_campaign(db_conn, "defer_stats_test")

    from src.models.campaigns import enroll_contact
    from datetime import date
    enroll_contact(db_conn, contact_id, campaign_id, next_action_date=date.today().isoformat(), user_id=1)

    # Defer the contact
    client.post(f"/api/queue/{contact_id}/defer", json={
        "campaign": "defer_stats_test",
        "reason": "Need more research",
    })

    resp = client.get("/api/queue/defer/stats?campaign=defer_stats_test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["today_count"] >= 1
    assert data["total_count"] >= 1
    assert any(r["reason"] == "Need more research" for r in data["by_reason"])
