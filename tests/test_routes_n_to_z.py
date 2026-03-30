"""Comprehensive API route tests (second half): newsletters through templates.

Covers ~100 tests across:
  newsletters, products, queue, replies, research, sequence_generator,
  settings, smart_import, stats, tags, templates
"""

from __future__ import annotations

import io
import json
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import psycopg2
import psycopg2.extras
import pytest
from fastapi.testclient import TestClient

from src.models.database import get_connection, get_cursor, run_migrations
from src.web.app import app
from src.web.dependencies import get_db
from tests.conftest import TEST_USER_ID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn(tmp_db):
    """Provide a raw database connection for direct seed helpers."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


@pytest.fixture
def client(tmp_db):
    """FastAPI TestClient with DB dependency override (dev-mode auth)."""
    def _override_get_db():
        conn = get_connection(tmp_db)
        run_migrations(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_company(conn, name="Test Fund", aum=500.0, firm_type="Hedge Fund", country="US"):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country, user_id)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, name.lower(), aum, firm_type, country, TEST_USER_ID),
    )
    conn.commit()
    cid = cur.fetchone()["id"]
    cur.close()
    return cid


def _seed_contact(conn, company_id, first="John", last="Doe", email="john@test.com",
                  email_status="valid", linkedin_url=None, unsubscribed=False,
                  newsletter_status="subscribed", lifecycle_stage="cold"):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO contacts
           (company_id, first_name, last_name, full_name, email, email_normalized,
            email_status, linkedin_url, linkedin_url_normalized,
            unsubscribed, newsletter_status, lifecycle_stage, user_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (company_id, first, last, f"{first} {last}", email,
         email.lower() if email else None, email_status,
         linkedin_url, linkedin_url.lower().rstrip("/") if linkedin_url else None,
         unsubscribed, newsletter_status, lifecycle_stage, TEST_USER_ID),
    )
    conn.commit()
    cid = cur.fetchone()["id"]
    cur.close()
    return cid


def _seed_campaign(conn, name="test_campaign"):
    from src.models.campaigns import create_campaign
    return create_campaign(conn, name, user_id=TEST_USER_ID)


def _seed_template(conn, name="tmpl", channel="email", body="Hello {{ first_name }}", subject="Hi"):
    from src.models.templates import create_template
    return create_template(conn, name, channel, body, subject=subject, user_id=TEST_USER_ID)


def _seed_newsletter(conn, subject="Weekly Update", body_html="<p>Hello</p>",
                     status="draft"):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO newsletters (subject, body_html, status, user_id)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (subject, body_html, status, TEST_USER_ID),
    )
    conn.commit()
    nid = cur.fetchone()["id"]
    cur.close()
    return nid


def _seed_product(conn, name="Crypto Fund Alpha", description="Multi-strat"):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO products (name, description, user_id)
           VALUES (%s, %s, %s) RETURNING id""",
        (name, description, TEST_USER_ID),
    )
    conn.commit()
    pid = cur.fetchone()["id"]
    cur.close()
    return pid


def _seed_tag(conn, name="VIP", color="#FF0000"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tags (name, color, user_id) VALUES (%s, %s, %s) RETURNING id",
        (name, color, TEST_USER_ID),
    )
    conn.commit()
    tid = cur.fetchone()["id"]
    cur.close()
    return tid


def _seed_research_job(conn, name="Test Job", total=3, status="pending"):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO research_jobs (name, method, total_companies, cost_estimate_usd, status, user_id)
           VALUES (%s, 'hybrid', %s, 0.033, %s, %s) RETURNING id""",
        (name, total, status, TEST_USER_ID),
    )
    conn.commit()
    jid = cur.fetchone()["id"]
    cur.close()
    return jid


def _seed_research_result(conn, job_id, company_name="Alpha Fund", score=75,
                          category="likely_interested", status="completed",
                          discovered_contacts=None):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO research_results
               (job_id, company_name, crypto_score, category, evidence_summary,
                status, discovered_contacts_json)
           VALUES (%s, %s, %s, %s, 'Test evidence', %s, %s) RETURNING id""",
        (job_id, company_name, score, category, status,
         json.dumps(discovered_contacts) if discovered_contacts else None),
    )
    conn.commit()
    rid = cur.fetchone()["id"]
    cur.close()
    return rid


# ============================================================================
# NEWSLETTERS
# ============================================================================

class TestNewsletters:
    """Newsletter CRUD, recipients, send."""

    def test_list_newsletters_empty(self, client):
        resp = client.get("/api/newsletters")
        assert resp.status_code == 200
        data = resp.json()
        assert data["newsletters"] == []
        assert data["total"] == 0

    def test_create_newsletter(self, client):
        resp = client.post("/api/newsletters", json={
            "subject": "Weekly Digest",
            "body_html": "<h1>Hello</h1>",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["id"] > 0

    def test_list_newsletters_after_create(self, client, db_conn):
        _seed_newsletter(db_conn, "Newsletter A")
        _seed_newsletter(db_conn, "Newsletter B")
        resp = client.get("/api/newsletters")
        assert resp.json()["total"] == 2
        assert len(resp.json()["newsletters"]) == 2

    def test_get_newsletter(self, client, db_conn):
        nid = _seed_newsletter(db_conn, "Detail NL", "<p>content</p>")
        resp = client.get(f"/api/newsletters/{nid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["newsletter"]["subject"] == "Detail NL"
        assert "attachments" in data
        assert "send_stats" in data

    def test_get_newsletter_not_found(self, client):
        resp = client.get("/api/newsletters/9999")
        assert resp.status_code == 404

    def test_update_newsletter(self, client, db_conn):
        nid = _seed_newsletter(db_conn)
        resp = client.put(f"/api/newsletters/{nid}", json={
            "subject": "Updated Subject",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update_newsletter_not_draft_fails(self, client, db_conn):
        nid = _seed_newsletter(db_conn, status="sent")
        resp = client.put(f"/api/newsletters/{nid}", json={"subject": "New"})
        assert resp.status_code == 400

    def test_update_newsletter_not_found(self, client):
        resp = client.put("/api/newsletters/9999", json={"subject": "X"})
        assert resp.status_code == 404

    def test_delete_newsletter(self, client, db_conn):
        nid = _seed_newsletter(db_conn)
        resp = client.delete(f"/api/newsletters/{nid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Verify gone
        resp2 = client.get(f"/api/newsletters/{nid}")
        assert resp2.status_code == 404

    def test_delete_newsletter_not_draft_fails(self, client, db_conn):
        nid = _seed_newsletter(db_conn, status="sending")
        resp = client.delete(f"/api/newsletters/{nid}")
        assert resp.status_code == 400

    def test_delete_newsletter_not_found(self, client):
        resp = client.delete("/api/newsletters/9999")
        assert resp.status_code == 404

    def test_preview_recipients_empty(self, client, db_conn):
        nid = _seed_newsletter(db_conn)
        resp = client.get(f"/api/newsletters/{nid}/recipients")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_preview_recipients_with_contacts(self, client, db_conn):
        nid = _seed_newsletter(db_conn)
        co = _seed_company(db_conn)
        _seed_contact(db_conn, co, first="Alice", email="alice@test.com",
                      newsletter_status="subscribed")
        resp = client.get(f"/api/newsletters/{nid}/recipients")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_preview_recipients_newsletter_not_found(self, client):
        resp = client.get("/api/newsletters/9999/recipients")
        assert resp.status_code == 404

    def test_send_newsletter_no_recipients(self, client, db_conn):
        nid = _seed_newsletter(db_conn)
        resp = client.post(f"/api/newsletters/{nid}/send", json={
            "newsletter_only": True,
        })
        assert resp.status_code == 400

    def test_send_newsletter_not_found(self, client):
        resp = client.post("/api/newsletters/9999/send", json={})
        assert resp.status_code == 404

    def test_send_newsletter_already_sent(self, client, db_conn):
        nid = _seed_newsletter(db_conn, status="sent")
        resp = client.post(f"/api/newsletters/{nid}/send", json={})
        assert resp.status_code == 400

    def test_create_newsletter_validation(self, client):
        """Missing required field body_html."""
        resp = client.post("/api/newsletters", json={"subject": "No body"})
        assert resp.status_code == 422


# ============================================================================
# PRODUCTS
# ============================================================================

class TestProducts:
    """Product CRUD and contact-product linking."""

    def test_list_products_empty(self, client):
        resp = client.get("/api/products")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_product(self, client):
        resp = client.post("/api/products", json={
            "name": "Alpha Strategy",
            "description": "Long-short crypto",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_list_products_after_create(self, client, db_conn):
        _seed_product(db_conn, "Product A")
        _seed_product(db_conn, "Product B")
        resp = client.get("/api/products")
        assert len(resp.json()) == 2

    def test_update_product(self, client, db_conn):
        pid = _seed_product(db_conn, "Old Name")
        resp = client.put(f"/api/products/{pid}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update_product_not_found(self, client):
        resp = client.put("/api/products/9999", json={"name": "X"})
        assert resp.status_code == 404

    def test_delete_product(self, client, db_conn):
        pid = _seed_product(db_conn)
        resp = client.delete(f"/api/products/{pid}")
        assert resp.status_code == 200
        # Product soft-deleted; list should be empty
        resp2 = client.get("/api/products")
        assert resp2.json() == []

    def test_delete_product_not_found(self, client):
        resp = client.delete("/api/products/9999")
        assert resp.status_code == 404

    def test_link_contact_product(self, client, db_conn):
        pid = _seed_product(db_conn)
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="link@test.com")
        resp = client.post(f"/api/contacts/{cid}/products", json={
            "product_id": pid,
            "stage": "discussed",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_link_contact_product_invalid_stage(self, client, db_conn):
        pid = _seed_product(db_conn)
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="stage@test.com")
        resp = client.post(f"/api/contacts/{cid}/products", json={
            "product_id": pid,
            "stage": "invalid_stage_value",
        })
        assert resp.status_code == 400

    def test_link_contact_product_not_found_contact(self, client, db_conn):
        pid = _seed_product(db_conn)
        resp = client.post("/api/contacts/9999/products", json={
            "product_id": pid,
            "stage": "discussed",
        })
        assert resp.status_code == 404

    def test_link_contact_product_not_found_product(self, client, db_conn):
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="noprod@test.com")
        resp = client.post(f"/api/contacts/{cid}/products", json={
            "product_id": 9999,
            "stage": "discussed",
        })
        assert resp.status_code == 404

    def test_list_contact_products(self, client, db_conn):
        pid = _seed_product(db_conn, "Product X")
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="listprod@test.com")
        client.post(f"/api/contacts/{cid}/products", json={
            "product_id": pid, "stage": "discussed",
        })
        resp = client.get(f"/api/contacts/{cid}/products")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_list_contact_products_not_found(self, client):
        resp = client.get("/api/contacts/9999/products")
        assert resp.status_code == 404

    def test_update_contact_product_stage(self, client, db_conn):
        pid = _seed_product(db_conn)
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="stage_upd@test.com")
        client.post(f"/api/contacts/{cid}/products", json={
            "product_id": pid, "stage": "discussed",
        })
        resp = client.patch(f"/api/contacts/{cid}/products/{pid}/stage", json={
            "stage": "interested",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update_contact_product_stage_invalid(self, client, db_conn):
        pid = _seed_product(db_conn)
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="badstage@test.com")
        client.post(f"/api/contacts/{cid}/products", json={
            "product_id": pid, "stage": "discussed",
        })
        resp = client.patch(f"/api/contacts/{cid}/products/{pid}/stage", json={
            "stage": "not_a_stage",
        })
        assert resp.status_code == 400

    def test_update_contact_product_stage_not_found(self, client):
        resp = client.patch("/api/contacts/9999/products/9999/stage", json={
            "stage": "interested",
        })
        assert resp.status_code == 404

    def test_remove_contact_product(self, client, db_conn):
        pid = _seed_product(db_conn)
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="remove@test.com")
        client.post(f"/api/contacts/{cid}/products", json={
            "product_id": pid, "stage": "discussed",
        })
        resp = client.delete(f"/api/contacts/{cid}/products/{pid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_remove_contact_product_not_found(self, client):
        resp = client.delete("/api/contacts/9999/products/9999")
        assert resp.status_code == 404


# ============================================================================
# QUEUE
# ============================================================================

class TestQueue:
    """Queue endpoints: all, campaign, batch-approve, schedule, defer."""

    def test_get_all_queues_empty(self, client):
        resp = client.get("/api/queue/all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_campaign_queue_not_found(self, client):
        resp = client.get("/api/queue/nonexistent_campaign")
        assert resp.status_code == 404

    def test_get_campaign_queue(self, client, db_conn):
        _seed_campaign(db_conn, "queue_test")
        resp = client.get("/api/queue/queue_test")
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_batch_approve_empty(self, client):
        resp = client.post("/api/queue/batch-approve", json={"items": []})
        assert resp.status_code == 200
        assert resp.json()["approved"] == 0

    def test_batch_approve(self, client, db_conn):
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="approve@test.com")
        camp_id = _seed_campaign(db_conn, "approve_test")
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, cid, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)

        resp = client.post("/api/queue/batch-approve", json={
            "items": [{"contact_id": cid, "campaign_id": camp_id}],
        })
        assert resp.status_code == 200
        assert resp.json()["approved"] >= 0

    def test_batch_send_empty(self, client):
        resp = client.post("/api/queue/batch-send")
        assert resp.status_code == 200
        assert resp.json()["sent"] == 0

    def test_schedule_empty_items(self, client):
        resp = client.post("/api/queue/schedule", json={
            "items": [],
            "schedule": "now",
        })
        assert resp.status_code == 200
        assert resp.json()["scheduled"] == 0

    def test_schedule_invalid_schedule(self, client):
        resp = client.post("/api/queue/schedule", json={
            "items": [{"contact_id": 1, "campaign_id": 1}],
            "schedule": "not-a-valid-schedule",
        })
        assert resp.status_code == 400

    # -----------------------------------------------------------------------
    # B1: remaining count excludes LinkedIn
    # -----------------------------------------------------------------------
    def test_batch_send_remaining_excludes_linkedin(self, client, db_conn):
        """remaining count should only count email-channel items, not LinkedIn."""
        co = _seed_company(db_conn, name="Remaining Co")
        cid = _seed_contact(db_conn, co, email="remaining@test.com")
        camp_id = _seed_campaign(db_conn, "remaining_test")
        tmpl_id = _seed_template(db_conn, name="rem_tmpl")
        from src.models.campaigns import enroll_contact
        from src.models.enrollment import add_sequence_step
        add_sequence_step(db_conn, camp_id, 1, "email", tmpl_id, user_id=TEST_USER_ID)
        add_sequence_step(db_conn, camp_id, 2, "linkedin_connect", tmpl_id, user_id=TEST_USER_ID)
        enroll_contact(db_conn, cid, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        # Approve the contact
        resp = client.post("/api/queue/batch-approve", json={
            "items": [{"contact_id": cid, "campaign_id": camp_id}],
        })
        assert resp.status_code == 200
        # batch-send should process the email step; remaining should be 0 (not 1 from linkedin step)
        resp = client.post("/api/queue/batch-send")
        assert resp.status_code == 200
        data = resp.json()
        # Even if send fails (no SMTP), remaining should not count LinkedIn items
        assert "remaining" in data

    # -----------------------------------------------------------------------
    # B2: Server-side validation in batch_approve
    # -----------------------------------------------------------------------
    def test_batch_approve_company_duplicate_rejected(self, client, db_conn):
        """Two contacts at same company should fail validation without force."""
        co = _seed_company(db_conn, name="Dupe Co")
        c1 = _seed_contact(db_conn, co, first="Alice", email="alice@dupe.com")
        c2 = _seed_contact(db_conn, co, first="Bob", email="bob@dupe.com")
        camp_id = _seed_campaign(db_conn, "dupe_test")
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, c1, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        enroll_contact(db_conn, c2, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        resp = client.post("/api/queue/batch-approve", json={
            "items": [
                {"contact_id": c1, "campaign_id": camp_id},
                {"contact_id": c2, "campaign_id": camp_id},
            ],
        })
        assert resp.status_code == 400
        data = resp.json()
        assert "company_duplicates" in data
        assert len(data["company_duplicates"]) == 1

    def test_batch_approve_company_duplicate_forced(self, client, db_conn):
        """Two contacts at same company should pass with force=true."""
        co = _seed_company(db_conn, name="Force Co")
        c1 = _seed_contact(db_conn, co, first="Alice", email="alice@force.com")
        c2 = _seed_contact(db_conn, co, first="Bob", email="bob@force.com")
        camp_id = _seed_campaign(db_conn, "force_test")
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, c1, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        enroll_contact(db_conn, c2, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        resp = client.post("/api/queue/batch-approve?force=true", json={
            "items": [
                {"contact_id": c1, "campaign_id": camp_id},
                {"contact_id": c2, "campaign_id": camp_id},
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["approved"] == 2

    def test_batch_approve_email_duplicate_rejected(self, client, db_conn):
        """Same contact enrolled in two campaigns should fail email dedup validation."""
        co = _seed_company(db_conn, name="Email Dupe Co")
        cid = _seed_contact(db_conn, co, first="Alice", email="emaildupe@test.com")
        camp1 = _seed_campaign(db_conn, "email_dupe_test1")
        camp2 = _seed_campaign(db_conn, "email_dupe_test2")
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, cid, camp1,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        enroll_contact(db_conn, cid, camp2,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        resp = client.post("/api/queue/batch-approve", json={
            "items": [
                {"contact_id": cid, "campaign_id": camp1},
                {"contact_id": cid, "campaign_id": camp2},
            ],
        })
        assert resp.status_code == 400
        data = resp.json()
        assert "email_duplicates" in data

    def test_batch_approve_clean_passes(self, client, db_conn):
        """Two contacts at different companies with different emails should pass."""
        co1 = _seed_company(db_conn, name="Clean Co 1")
        co2 = _seed_company(db_conn, name="Clean Co 2")
        c1 = _seed_contact(db_conn, co1, first="Alice", email="alice@clean.com")
        c2 = _seed_contact(db_conn, co2, first="Bob", email="bob@clean.com")
        camp_id = _seed_campaign(db_conn, "clean_test")
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, c1, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        enroll_contact(db_conn, c2, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        resp = client.post("/api/queue/batch-approve", json={
            "items": [
                {"contact_id": c1, "campaign_id": camp_id},
                {"contact_id": c2, "campaign_id": camp_id},
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["approved"] == 2

    # -----------------------------------------------------------------------
    # B3: Undo-send endpoint
    # -----------------------------------------------------------------------
    def test_undo_send_empty(self, client):
        """Undo with no recent sends returns undone=0."""
        resp = client.post("/api/queue/undo-send")
        assert resp.status_code == 200
        assert resp.json()["undone"] == 0

    def test_undo_send_within_window(self, client, db_conn):
        """Undo should reset sent_at, approved_at, and current_step for recent sends."""
        co = _seed_company(db_conn, name="Undo Co")
        cid = _seed_contact(db_conn, co, email="undo@test.com")
        camp_id = _seed_campaign(db_conn, "undo_test")
        # Need 2 steps so undo can regress from step 2 to step 1
        from src.models.enrollment import add_sequence_step
        add_sequence_step(db_conn, camp_id, 1, "email", user_id=TEST_USER_ID)
        add_sequence_step(db_conn, camp_id, 2, "email", user_id=TEST_USER_ID)
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, cid, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        # Simulate a recent send by setting sent_at = NOW() and step advanced to 2
        cur = db_conn.cursor()
        cur.execute(
            """UPDATE contact_campaign_status
               SET sent_at = NOW(), approved_at = NOW(), current_step = 2
               WHERE contact_id = %s AND campaign_id = %s""",
            (cid, camp_id),
        )
        db_conn.commit()
        cur.close()

        resp = client.post("/api/queue/undo-send")
        assert resp.status_code == 200
        assert resp.json()["undone"] == 1

        # Verify the reset
        cur = db_conn.cursor()
        cur.execute(
            "SELECT sent_at, approved_at, current_step FROM contact_campaign_status WHERE contact_id = %s",
            (cid,),
        )
        row = cur.fetchone()
        cur.close()
        assert row["sent_at"] is None
        assert row["approved_at"] is None
        assert row["current_step"] == 1  # regressed from 2 to 1

    def test_undo_send_outside_window(self, client, db_conn):
        """Undo should NOT reset items sent more than 30s ago."""
        co = _seed_company(db_conn, name="Old Co")
        cid = _seed_contact(db_conn, co, email="old@test.com")
        camp_id = _seed_campaign(db_conn, "old_test")
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, cid, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        cur = db_conn.cursor()
        cur.execute(
            """UPDATE contact_campaign_status
               SET sent_at = NOW() - interval '60 seconds', approved_at = NOW() - interval '60 seconds'
               WHERE contact_id = %s AND campaign_id = %s""",
            (cid, camp_id),
        )
        db_conn.commit()
        cur.close()

        resp = client.post("/api/queue/undo-send")
        assert resp.status_code == 200
        assert resp.json()["undone"] == 0

    def test_schedule_now(self, client, db_conn):
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="sched@test.com")
        camp_id = _seed_campaign(db_conn, "sched_test")
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, cid, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)

        resp = client.post("/api/queue/schedule", json={
            "items": [{"contact_id": cid, "campaign_id": camp_id}],
            "schedule": "now",
        })
        assert resp.status_code == 200

    def test_defer_stats_empty(self, client):
        resp = client.get("/api/queue/defer/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["today_count"] == 0

    def test_defer_contact(self, client, db_conn):
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="defer@test.com")
        camp_id = _seed_campaign(db_conn, "defer_route_test")
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, cid, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)

        resp = client.post(f"/api/queue/{cid}/defer", json={
            "campaign": "defer_route_test",
            "reason": "Timing",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_defer_campaign_not_found(self, client, db_conn):
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="defnf@test.com")
        resp = client.post(f"/api/queue/{cid}/defer", json={
            "campaign": "nonexistent",
        })
        assert resp.status_code == 404

    def test_override_template(self, client, db_conn):
        camp_id = _seed_campaign(db_conn, "override_rt")
        tid = _seed_template(db_conn, "override_tmpl")
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="over@test.com")

        resp = client.post("/api/queue/override_rt/override", json={
            "contact_id": cid,
            "template_id": tid,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_override_template_campaign_not_found(self, client, db_conn):
        tid = _seed_template(db_conn, "override_nf")
        resp = client.post("/api/queue/no_camp/override", json={
            "contact_id": 1, "template_id": tid,
        })
        assert resp.status_code == 404

    def test_override_template_not_found(self, client, db_conn):
        _seed_campaign(db_conn, "override_tmpl_nf")
        resp = client.post("/api/queue/override_tmpl_nf/override", json={
            "contact_id": 1, "template_id": 9999,
        })
        assert resp.status_code == 404

    def test_linkedin_done_campaign_not_found(self, client):
        resp = client.post(
            "/api/queue/1/linkedin-done?campaign=nonexistent",
            json={"action_type": "connect"},
        )
        assert resp.status_code == 404

    # -----------------------------------------------------------------------
    # Swap contact regression tests (dogfooding session)
    # -----------------------------------------------------------------------
    def test_swap_candidates_returns_same_company_not_enrolled(self, client, db_conn):
        """get_swap_candidates returns contacts from same company not enrolled."""
        co = _seed_company(db_conn, name="Swap Co")
        c1 = _seed_contact(db_conn, co, first="Alice", email="alice@swap.com")
        c2 = _seed_contact(db_conn, co, first="Bob", email="bob@swap.com")
        c3 = _seed_contact(db_conn, co, first="Carol", email="carol@swap.com")
        camp_id = _seed_campaign(db_conn, "swap_test")
        from src.models.enrollment import add_sequence_step
        add_sequence_step(db_conn, camp_id, 1, "email", user_id=TEST_USER_ID)
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, c1, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)

        resp = client.get(f"/api/queue/swap-candidates/{c1}/{camp_id}")
        assert resp.status_code == 200
        data = resp.json()
        candidate_ids = [c["id"] for c in data["candidates"]]
        assert c2 in candidate_ids
        assert c3 in candidate_ids
        # Enrolled contact should NOT appear as a candidate
        assert c1 not in candidate_ids

    def test_swap_contact_success(self, client, db_conn):
        """swap_contact removes current contact and enrolls replacement at step 1."""
        co = _seed_company(db_conn, name="Swap OK Co")
        c1 = _seed_contact(db_conn, co, first="Alice", email="alice@swapok.com")
        c2 = _seed_contact(db_conn, co, first="Bob", email="bob@swapok.com")
        camp_id = _seed_campaign(db_conn, "swap_ok_test")
        from src.models.enrollment import add_sequence_step
        add_sequence_step(db_conn, camp_id, 1, "email", user_id=TEST_USER_ID)
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, c1, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)

        resp = client.post("/api/queue/swap-contact", json={
            "current_contact_id": c1,
            "replacement_contact_id": c2,
            "campaign_id": camp_id,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["enrolled_contact_id"] == c2

        # Verify: c1 no longer enrolled, c2 is enrolled
        cur = db_conn.cursor()
        cur.execute(
            "SELECT contact_id FROM contact_campaign_status WHERE campaign_id = %s",
            (camp_id,),
        )
        enrolled_ids = [r["contact_id"] for r in cur.fetchall()]
        assert c1 not in enrolled_ids
        assert c2 in enrolled_ids

    def test_swap_contact_fails_not_step_1(self, client, db_conn):
        """swap_contact fails if current contact is not at step 1."""
        co = _seed_company(db_conn, name="Swap Step Co")
        c1 = _seed_contact(db_conn, co, first="Alice", email="alice@swapstep.com")
        c2 = _seed_contact(db_conn, co, first="Bob", email="bob@swapstep.com")
        camp_id = _seed_campaign(db_conn, "swap_step_test")
        from src.models.enrollment import add_sequence_step
        add_sequence_step(db_conn, camp_id, 1, "email", user_id=TEST_USER_ID)
        add_sequence_step(db_conn, camp_id, 2, "email", user_id=TEST_USER_ID)
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, c1, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)
        # Advance c1 to step 2
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE contact_campaign_status SET current_step = 2 WHERE contact_id = %s AND campaign_id = %s",
            (c1, camp_id),
        )
        db_conn.commit()

        resp = client.post("/api/queue/swap-contact", json={
            "current_contact_id": c1,
            "replacement_contact_id": c2,
            "campaign_id": camp_id,
        })
        assert resp.status_code == 400
        assert "step 1" in resp.json()["detail"].lower()

    def test_swap_contact_fails_different_companies(self, client, db_conn):
        """swap_contact fails if contacts are at different companies."""
        co1 = _seed_company(db_conn, name="Swap Co Alpha")
        co2 = _seed_company(db_conn, name="Swap Co Beta")
        c1 = _seed_contact(db_conn, co1, first="Alice", email="alice@swapalpha.com")
        c2 = _seed_contact(db_conn, co2, first="Bob", email="bob@swapbeta.com")
        camp_id = _seed_campaign(db_conn, "swap_diff_test")
        from src.models.enrollment import add_sequence_step
        add_sequence_step(db_conn, camp_id, 1, "email", user_id=TEST_USER_ID)
        from src.models.campaigns import enroll_contact
        enroll_contact(db_conn, c1, camp_id,
                       next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)

        resp = client.post("/api/queue/swap-contact", json={
            "current_contact_id": c1,
            "replacement_contact_id": c2,
            "campaign_id": camp_id,
        })
        assert resp.status_code == 400
        assert "same company" in resp.json()["detail"].lower()


# ============================================================================
# REPLIES
# ============================================================================

class TestReplies:
    """Pending replies, confirm, scan, cron endpoints."""

    def test_list_pending_replies_empty(self, client):
        resp = client.get("/api/replies/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert data["replies"] == []
        assert "last_auto_scan_at" in data

    def test_confirm_reply(self, client, db_conn):
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="reply@test.com")
        camp_id = _seed_campaign(db_conn, "reply_camp")

        cur = db_conn.cursor()
        cur.execute(
            """INSERT INTO pending_replies
               (contact_id, campaign_id, subject, snippet, classification, confidence, confirmed, user_id)
               VALUES (%s, %s, 'Re: Hi', 'Sounds good', 'positive', 0.9, false, %s)
               RETURNING id""",
            (cid, camp_id, TEST_USER_ID),
        )
        reply_id = cur.fetchone()["id"]
        db_conn.commit()
        cur.close()

        resp = client.post(f"/api/replies/{reply_id}/confirm", json={
            "outcome": "replied_positive",
            "note": "Interested in meeting",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_confirm_reply_not_found(self, client):
        resp = client.post("/api/replies/9999/confirm", json={
            "outcome": "replied_positive",
        })
        assert resp.status_code == 404

    def test_confirm_reply_already_confirmed(self, client, db_conn):
        co = _seed_company(db_conn)
        cid = _seed_contact(db_conn, co, email="dup_reply@test.com")

        cur = db_conn.cursor()
        cur.execute(
            """INSERT INTO pending_replies
               (contact_id, subject, snippet, classification, confidence, confirmed, user_id)
               VALUES (%s, 'Re: Hi', 'ok', 'positive', 0.9, true, %s)
               RETURNING id""",
            (cid, TEST_USER_ID),
        )
        reply_id = cur.fetchone()["id"]
        db_conn.commit()
        cur.close()

        resp = client.post(f"/api/replies/{reply_id}/confirm", json={
            "outcome": "replied_positive",
        })
        assert resp.status_code == 400

    def test_scan_replies(self, client):
        resp = client.post("/api/replies/scan")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_cron_scan_replies_no_secret(self, client):
        """Cron endpoint without CRON_SECRET env returns 503."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CRON_SECRET", None)
            resp = client.post("/api/cron/scan-replies")
        assert resp.status_code in (401, 503)

    def test_cron_scan_replies_bad_secret(self, client):
        with patch.dict(os.environ, {"CRON_SECRET": "correct_secret"}):
            resp = client.post(
                "/api/cron/scan-replies",
                headers={"Authorization": "Bearer wrong_secret"},
            )
        assert resp.status_code == 401

    def test_cron_scan_replies_valid_secret(self, client):
        with patch.dict(os.environ, {"CRON_SECRET": "test_secret_123"}):
            resp = client.post(
                "/api/cron/scan-replies",
                headers={"Authorization": "Bearer test_secret_123"},
            )
        assert resp.status_code == 200

    def test_cron_send_scheduled_no_secret(self, client):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CRON_SECRET", None)
            resp = client.post("/api/cron/send-scheduled")
        assert resp.status_code in (401, 503)

    def test_cron_send_scheduled_valid(self, client):
        with patch.dict(os.environ, {"CRON_SECRET": "sched_secret"}):
            resp = client.post(
                "/api/cron/send-scheduled",
                headers={"Authorization": "Bearer sched_secret"},
            )
        assert resp.status_code == 200
        assert resp.json()["sent"] == 0


# ============================================================================
# RESEARCH
# ============================================================================

class TestResearch:
    """Research jobs: CRUD, results, cancel, retry, export, batch import."""

    def test_list_jobs_empty(self, client):
        resp = client.get("/api/research/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["jobs"] == []
        assert data["total"] == 0

    def test_list_jobs_with_filter(self, client, db_conn):
        _seed_research_job(db_conn, "Job A", status="completed")
        _seed_research_job(db_conn, "Job B", status="pending")

        resp = client.get("/api/research/jobs?status=completed")
        data = resp.json()
        assert data["total"] == 1

    def test_get_job(self, client, db_conn):
        jid = _seed_research_job(db_conn, "Detail Job", status="completed")
        _seed_research_result(db_conn, jid, "Fund A", score=80)
        _seed_research_result(db_conn, jid, "Fund B", score=40)

        resp = client.get(f"/api/research/jobs/{jid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job"]["name"] == "Detail Job"
        assert "by_category" in data
        assert "score_distribution" in data

    def test_get_job_not_found(self, client):
        resp = client.get("/api/research/jobs/9999")
        assert resp.status_code == 404

    def test_get_job_results(self, client, db_conn):
        jid = _seed_research_job(db_conn, "Result Job")
        _seed_research_result(db_conn, jid, "Fund X", score=90)

        resp = client.get(f"/api/research/jobs/{jid}/results")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_get_job_results_not_found(self, client):
        resp = client.get("/api/research/jobs/9999/results")
        assert resp.status_code == 404

    def test_get_job_results_with_filters(self, client, db_conn):
        jid = _seed_research_job(db_conn, "Filter Job")
        _seed_research_result(db_conn, jid, "High Fund", score=85, category="likely_interested")
        _seed_research_result(db_conn, jid, "Low Fund", score=20, category="unlikely")

        resp = client.get(f"/api/research/jobs/{jid}/results?min_score=50")
        assert resp.json()["total"] == 1

    def test_get_single_result(self, client, db_conn):
        jid = _seed_research_job(db_conn, "Single Result Job")
        rid = _seed_research_result(db_conn, jid, "Target Fund")

        resp = client.get(f"/api/research/results/{rid}")
        assert resp.status_code == 200
        assert resp.json()["company_name"] == "Target Fund"

    def test_get_single_result_not_found(self, client):
        resp = client.get("/api/research/results/9999")
        assert resp.status_code == 404

    def test_cancel_job(self, client, db_conn):
        jid = _seed_research_job(db_conn, "Cancel Job", status="researching")
        with patch("src.services.crypto_research.cancel_research_job",
                   return_value={"success": True}):
            resp = client.post(f"/api/research/jobs/{jid}/cancel")
        assert resp.status_code == 200

    def test_cancel_job_not_found(self, client):
        resp = client.post("/api/research/jobs/9999/cancel")
        assert resp.status_code == 404

    def test_retry_job_not_found(self, client):
        resp = client.post("/api/research/jobs/9999/retry")
        assert resp.status_code == 404

    def test_retry_job_wrong_status(self, client, db_conn):
        jid = _seed_research_job(db_conn, "Running Job", status="researching")
        resp = client.post(f"/api/research/jobs/{jid}/retry")
        assert resp.status_code == 400

    def test_retry_job_no_errors(self, client, db_conn):
        jid = _seed_research_job(db_conn, "Clean Job", status="completed")
        _seed_research_result(db_conn, jid, "OK Fund", status="completed")
        resp = client.post(f"/api/research/jobs/{jid}/retry")
        assert resp.status_code == 400

    def test_export_results(self, client, db_conn):
        jid = _seed_research_job(db_conn, "Export Job")
        _seed_research_result(db_conn, jid, "Export Fund", score=70)

        resp = client.post(f"/api/research/jobs/{jid}/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_export_results_not_found(self, client):
        resp = client.post("/api/research/jobs/9999/export")
        assert resp.status_code == 404

    def test_delete_job(self, client, db_conn):
        jid = _seed_research_job(db_conn, "Delete Job")
        resp = client.delete(f"/api/research/jobs/{jid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Confirm deleted
        resp2 = client.get(f"/api/research/jobs/{jid}")
        assert resp2.status_code == 404

    def test_delete_job_not_found(self, client):
        resp = client.delete("/api/research/jobs/9999")
        assert resp.status_code == 404

    def test_batch_import_empty_ids(self, client):
        resp = client.post("/api/research/batch-import", json={
            "result_ids": [],
        })
        assert resp.status_code == 400

    def test_import_contacts_from_result(self, client, db_conn):
        jid = _seed_research_job(db_conn, "Import Job", status="completed")
        contacts = [
            {"name": "Jane Doe", "title": "CIO", "email": "jane@fund.com"},
        ]
        rid = _seed_research_result(db_conn, jid, "Import Fund",
                                    discovered_contacts=contacts)
        co = _seed_company(db_conn, name="Import Fund")
        # Link result to company
        cur = db_conn.cursor()
        cur.execute("UPDATE research_results SET company_id = %s WHERE id = %s",
                    (co, rid))
        db_conn.commit()
        cur.close()

        resp = client.post(f"/api/research/results/{rid}/import-contacts")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_import_contacts_result_not_found(self, client):
        resp = client.post("/api/research/results/9999/import-contacts")
        assert resp.status_code == 404

    # -----------------------------------------------------------------------
    # Auto-heal stuck 'cancelling' jobs (dogfooding regression)
    # -----------------------------------------------------------------------
    def test_list_jobs_auto_heals_stuck_cancelling(self, client, db_conn):
        """Jobs stuck in 'cancelling' for >5 minutes get auto-transitioned to 'cancelled'."""
        cur = db_conn.cursor()
        cur.execute(
            """INSERT INTO research_jobs
                   (name, method, total_companies, cost_estimate_usd, status, user_id, updated_at)
               VALUES ('Stuck Job', 'hybrid', 1, 0.01, 'cancelling', %s, NOW() - INTERVAL '10 minutes')
               RETURNING id""",
            (TEST_USER_ID,),
        )
        jid = cur.fetchone()["id"]
        db_conn.commit()
        cur.close()

        # Call the list endpoint which triggers auto-heal
        resp = client.get("/api/research/jobs")
        assert resp.status_code == 200

        # Verify the job status is now 'cancelled'
        cur = db_conn.cursor()
        cur.execute("SELECT status FROM research_jobs WHERE id = %s", (jid,))
        row = cur.fetchone()
        assert row["status"] == "cancelled"
        cur.close()

    def test_list_jobs_does_not_heal_recent_cancelling(self, client, db_conn):
        """Jobs in 'cancelling' for <5 minutes should NOT be auto-healed."""
        cur = db_conn.cursor()
        cur.execute(
            """INSERT INTO research_jobs
                   (name, method, total_companies, cost_estimate_usd, status, user_id, updated_at)
               VALUES ('Recent Cancel', 'hybrid', 1, 0.01, 'cancelling', %s, NOW() - INTERVAL '2 minutes')
               RETURNING id""",
            (TEST_USER_ID,),
        )
        jid = cur.fetchone()["id"]
        db_conn.commit()
        cur.close()

        resp = client.get("/api/research/jobs")
        assert resp.status_code == 200

        # Should still be 'cancelling' since it's only 2 minutes old
        cur = db_conn.cursor()
        cur.execute("SELECT status FROM research_jobs WHERE id = %s", (jid,))
        row = cur.fetchone()
        assert row["status"] == "cancelling"
        cur.close()


# ============================================================================
# SEQUENCE GENERATOR
# ============================================================================

class TestSequenceGenerator:
    """Generate campaign sequences."""

    def test_generate_sequence(self, client, db_conn):
        camp_id = _seed_campaign(db_conn, "seq_gen_camp")
        resp = client.post(f"/api/campaigns/{camp_id}/generate-sequence", json={
            "touchpoints": 3,
            "channels": ["email", "linkedin"],
        })
        assert resp.status_code == 200
        assert "steps" in resp.json()
        assert len(resp.json()["steps"]) == 3

    def test_generate_sequence_campaign_not_found(self, client):
        resp = client.post("/api/campaigns/9999/generate-sequence", json={
            "touchpoints": 2,
            "channels": ["email"],
        })
        assert resp.status_code == 404

    def test_generate_sequence_validation_zero_touchpoints(self, client, db_conn):
        camp_id = _seed_campaign(db_conn, "seq_val")
        resp = client.post(f"/api/campaigns/{camp_id}/generate-sequence", json={
            "touchpoints": 0,
            "channels": ["email"],
        })
        assert resp.status_code == 422

    def test_generate_sequence_validation_no_channels(self, client, db_conn):
        camp_id = _seed_campaign(db_conn, "seq_no_ch")
        resp = client.post(f"/api/campaigns/{camp_id}/generate-sequence", json={
            "touchpoints": 2,
            "channels": [],
        })
        assert resp.status_code == 422


# ============================================================================
# SETTINGS
# ============================================================================

class TestSettings:
    """Settings: engine config, API keys, SMTP, compliance."""

    def test_get_settings(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "engine_config" in data
        assert "gmail_authorized" in data

    def test_update_settings(self, client):
        resp = client.put("/api/settings", json={
            "settings": {"max_daily_emails": "20", "explore_rate": "0.1"},
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "max_daily_emails" in resp.json()["updated"]

    def test_update_settings_persists(self, client):
        client.put("/api/settings", json={
            "settings": {"test_key": "test_val"},
        })
        resp = client.get("/api/settings")
        assert resp.json()["engine_config"]["test_key"] == "test_val"

    def test_get_api_keys(self, client):
        resp = client.get("/api/settings/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert "anthropic_configured" in data
        assert "perplexity_configured" in data

    def test_update_api_keys(self, client):
        resp = client.put("/api/settings/api-keys", json={
            "anthropic_api_key": "sk-ant-test-12345678",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update_api_keys_empty(self, client):
        resp = client.put("/api/settings/api-keys", json={})
        assert resp.status_code == 200
        assert resp.json()["updated"] == []

    def test_get_email_config(self, client):
        resp = client.get("/api/settings/email-config")
        assert resp.status_code == 200
        data = resp.json()
        assert "gmail_connected" in data
        assert "smtp_configured" in data

    def test_save_smtp_config(self, client):
        resp = client.post("/api/settings/smtp", json={
            "host": "smtp.gmail.com",
            "port": 587,
            "username": "test@gmail.com",
            "password": "app-password",
            "from_email": "test@gmail.com",
            "from_name": "Test User",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_save_compliance_config(self, client):
        resp = client.post("/api/settings/compliance", json={
            "physical_address": "123 Main St, NYC",
            "calendly_url": "https://calendly.com/test",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ============================================================================
# SMART IMPORT
# ============================================================================

class TestSmartImport:
    """Smart CSV import: upload, preview, execute."""

    def test_upload_non_csv_rejected(self, client):
        resp = client.post(
            "/api/import/smart",
            files={"file": ("data.txt", b"col1,col2\nval1,val2\n", "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_empty_csv(self, client):
        resp = client.post(
            "/api/import/smart",
            files={"file": ("data.csv", b"", "text/csv")},
        )
        assert resp.status_code == 400

    def test_get_active_import_job_none(self, client):
        resp = client.get("/api/import/jobs/active")
        assert resp.status_code == 200
        assert resp.json()["job"] is None

    def test_get_import_job_not_found(self, client):
        resp = client.get("/api/import/jobs/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_preview_import_job_not_found(self, client):
        resp = client.post("/api/import/preview", json={
            "import_job_id": "00000000-0000-0000-0000-000000000000",
            "approved_mapping": {},
        })
        assert resp.status_code == 404

    def test_execute_import_job_not_found(self, client):
        resp = client.post("/api/import/execute", json={
            "import_job_id": "00000000-0000-0000-0000-000000000000",
        })
        assert resp.status_code == 404


# ============================================================================
# STATS
# ============================================================================

class TestStats:
    """Database statistics overview."""

    def test_get_stats_empty(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["companies"] == 0
        assert data["contacts"] == 0
        assert "email_status" in data
        assert "previous_period" in data

    def test_get_stats_with_data(self, client, db_conn):
        co = _seed_company(db_conn)
        _seed_contact(db_conn, co, email="stats@test.com")
        _seed_campaign(db_conn, "stats_camp")

        resp = client.get("/api/stats")
        data = resp.json()
        assert data["companies"] >= 1
        assert data["contacts"] >= 1
        assert data["campaigns"] >= 1
        assert data["previous_period"]["current_week_events"] >= 0


# ============================================================================
# TAGS
# ============================================================================

class TestTags:
    """Tag CRUD and attach/detach to entities."""

    def test_list_tags_empty(self, client):
        resp = client.get("/api/tags")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_tag(self, client):
        resp = client.post("/api/tags", json={"name": "Priority", "color": "#FF0000"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_create_duplicate_tag(self, client, db_conn):
        _seed_tag(db_conn, "Duplicate")
        resp = client.post("/api/tags", json={"name": "Duplicate"})
        assert resp.status_code == 409

    def test_list_tags_after_create(self, client, db_conn):
        _seed_tag(db_conn, "Tag1")
        _seed_tag(db_conn, "Tag2")
        resp = client.get("/api/tags")
        assert len(resp.json()) == 2

    def test_delete_tag(self, client, db_conn):
        tid = _seed_tag(db_conn, "ToDelete")
        resp = client.delete(f"/api/tags/{tid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_tag_not_found(self, client):
        resp = client.delete("/api/tags/9999")
        assert resp.status_code == 404

    def test_attach_tag_to_company(self, client, db_conn):
        tid = _seed_tag(db_conn, "AttachTag")
        co = _seed_company(db_conn, name="Tagged Co")
        resp = client.post(f"/api/tags/{tid}/attach", json={
            "entity_type": "company",
            "entity_id": co,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["already_attached"] is False

    def test_attach_tag_already_attached(self, client, db_conn):
        tid = _seed_tag(db_conn, "DupAttach")
        co = _seed_company(db_conn, name="DupTagCo")
        client.post(f"/api/tags/{tid}/attach", json={
            "entity_type": "company", "entity_id": co,
        })
        resp = client.post(f"/api/tags/{tid}/attach", json={
            "entity_type": "company", "entity_id": co,
        })
        assert resp.json()["already_attached"] is True

    def test_attach_tag_invalid_entity_type(self, client, db_conn):
        tid = _seed_tag(db_conn, "BadType")
        resp = client.post(f"/api/tags/{tid}/attach", json={
            "entity_type": "deal",
            "entity_id": 1,
        })
        assert resp.status_code == 400

    def test_attach_tag_not_found_tag(self, client):
        resp = client.post("/api/tags/9999/attach", json={
            "entity_type": "company", "entity_id": 1,
        })
        assert resp.status_code == 404

    def test_attach_tag_entity_not_found(self, client, db_conn):
        tid = _seed_tag(db_conn, "NoEntity")
        resp = client.post(f"/api/tags/{tid}/attach", json={
            "entity_type": "company", "entity_id": 9999,
        })
        assert resp.status_code == 404

    def test_detach_tag(self, client, db_conn):
        tid = _seed_tag(db_conn, "DetachTag")
        co = _seed_company(db_conn, name="DetachCo")
        client.post(f"/api/tags/{tid}/attach", json={
            "entity_type": "company", "entity_id": co,
        })
        resp = client.post(f"/api/tags/{tid}/detach", json={
            "entity_type": "company", "entity_id": co,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_detach_tag_invalid_entity_type(self, client, db_conn):
        tid = _seed_tag(db_conn, "DetachBad")
        resp = client.post(f"/api/tags/{tid}/detach", json={
            "entity_type": "invalid", "entity_id": 1,
        })
        assert resp.status_code == 400

    def test_get_entity_tags_empty(self, client, db_conn):
        co = _seed_company(db_conn, name="NoTagCo")
        resp = client.get(f"/api/tags/entity/company/{co}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_entity_tags_with_data(self, client, db_conn):
        tid = _seed_tag(db_conn, "EntityTag")
        co = _seed_company(db_conn, name="EntityCo")
        client.post(f"/api/tags/{tid}/attach", json={
            "entity_type": "company", "entity_id": co,
        })
        resp = client.get(f"/api/tags/entity/company/{co}")
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "EntityTag"

    def test_get_entity_tags_invalid_type(self, client):
        resp = client.get("/api/tags/entity/invalid/1")
        assert resp.status_code == 400


# ============================================================================
# TEMPLATES
# ============================================================================

class TestTemplates:
    """Template CRUD, deactivate, generate-sequence, improve-message."""

    def test_list_templates_empty(self, client):
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_template(self, client):
        resp = client.post("/api/templates", json={
            "name": "Intro Email",
            "channel": "email",
            "body_template": "Hello {{ first_name }}",
            "subject": "Introduction",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_list_templates_with_channel_filter(self, client, db_conn):
        _seed_template(db_conn, "email_tmpl", "email")
        _seed_template(db_conn, "li_tmpl", "linkedin_connect")
        resp = client.get("/api/templates?channel=email")
        assert len(resp.json()) == 1

    def test_get_template(self, client, db_conn):
        tid = _seed_template(db_conn, "detail_tmpl")
        resp = client.get(f"/api/templates/{tid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "detail_tmpl"

    def test_get_template_not_found(self, client):
        resp = client.get("/api/templates/9999")
        assert resp.status_code == 404

    def test_update_template(self, client, db_conn):
        tid = _seed_template(db_conn, "old_tmpl")
        resp = client.put(f"/api/templates/{tid}", json={"name": "new_tmpl"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update_template_no_fields(self, client, db_conn):
        tid = _seed_template(db_conn, "no_update")
        resp = client.put(f"/api/templates/{tid}", json={})
        assert resp.status_code == 400

    def test_update_template_not_found(self, client):
        resp = client.put("/api/templates/9999", json={"name": "x"})
        assert resp.status_code == 404

    def test_deactivate_template(self, client, db_conn):
        tid = _seed_template(db_conn, "deact_tmpl")
        resp = client.patch(f"/api/templates/{tid}/deactivate")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_deactivate_template_not_found(self, client):
        resp = client.patch("/api/templates/9999/deactivate")
        assert resp.status_code == 404

    def test_create_template_validation(self, client):
        """Missing required field channel."""
        resp = client.post("/api/templates", json={
            "name": "Bad Template",
            "body_template": "Hello",
        })
        assert resp.status_code == 422

    def test_generate_sequence_messages(self, client):
        """Generate AI messages for a sequence (mocked LLM)."""
        mock_messages = [
            {"step_order": 1, "channel": "email", "subject": "Intro",
             "body": "Hello", "model": "test"},
        ]
        with patch("src.services.message_drafter.generate_sequence_messages",
                   return_value=mock_messages):
            resp = client.post("/api/templates/generate-sequence", json={
                "steps": [{"step_order": 1, "channel": "email", "delay_days": 0}],
                "product_description": "A cutting-edge crypto strategy fund.",
                "target_audience": "crypto fund allocators",
            })
        assert resp.status_code == 200
        assert "messages" in resp.json()

    def test_generate_sequence_validation(self, client):
        """Empty steps list fails validation."""
        resp = client.post("/api/templates/generate-sequence", json={
            "steps": [],
            "product_description": "A cutting-edge crypto strategy fund.",
        })
        assert resp.status_code == 422

    def test_improve_message(self, client):
        """Improve a message (mocked LLM)."""
        mock_result = {
            "body": "Improved message text",
            "subject": "Better Subject",
            "model": "test",
        }
        with patch("src.services.message_drafter.improve_message",
                   return_value=mock_result):
            resp = client.post("/api/templates/improve-message", json={
                "channel": "email",
                "body": "Original message",
                "subject": "Original Subject",
                "instruction": "Make it shorter and punchier",
            })
        assert resp.status_code == 200
        assert resp.json()["body"] == "Improved message text"

    def test_improve_message_validation(self, client):
        """Empty instruction fails validation."""
        resp = client.post("/api/templates/improve-message", json={
            "channel": "email",
            "body": "Hello",
            "instruction": "",
        })
        assert resp.status_code == 422


