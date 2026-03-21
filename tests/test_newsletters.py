"""Tests for newsletter management API."""

import psycopg2
import psycopg2.extras
import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_USER_ID


@pytest.fixture
def client(tmp_db):
    import os
    os.environ["SUPABASE_DB_URL"] = tmp_db
    os.environ.pop("API_SECRET_KEY", None)
    from src.web.app import app
    from src.models.database import init_pool, close_pool

    init_pool(tmp_db)
    try:
        yield TestClient(app)
    finally:
        close_pool()


@pytest.fixture
def db_conn(tmp_db):
    conn = psycopg2.connect(tmp_db, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def company_id(db_conn):
    """Create a company owned by the test user."""
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Newsletter Corp', 'newsletter corp', %s) RETURNING id",
        (TEST_USER_ID,),
    )
    return cur.fetchone()["id"]


class TestNewsletterCRUD:
    def test_create_newsletter(self, client):
        resp = client.post("/api/newsletters", json={
            "subject": "Test Newsletter",
            "body_html": "<h1>Hello</h1><p>World</p>",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "id" in data

    def test_list_newsletters(self, client):
        client.post("/api/newsletters", json={
            "subject": "NL 1",
            "body_html": "<p>1</p>",
        })
        client.post("/api/newsletters", json={
            "subject": "NL 2",
            "body_html": "<p>2</p>",
        })

        resp = client.get("/api/newsletters")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["newsletters"]) == 2

    def test_get_newsletter_detail(self, client):
        create = client.post("/api/newsletters", json={
            "subject": "Detail Test",
            "body_html": "<p>Detail</p>",
        })
        nl_id = create.json()["id"]

        resp = client.get(f"/api/newsletters/{nl_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["newsletter"]["subject"] == "Detail Test"
        assert data["attachments"] == []
        assert data["send_stats"] == {}

    def test_update_newsletter(self, client):
        create = client.post("/api/newsletters", json={
            "subject": "Old Subject",
            "body_html": "<p>Old</p>",
        })
        nl_id = create.json()["id"]

        resp = client.put(f"/api/newsletters/{nl_id}", json={
            "subject": "New Subject",
        })
        assert resp.status_code == 200

        detail = client.get(f"/api/newsletters/{nl_id}").json()
        assert detail["newsletter"]["subject"] == "New Subject"

    def test_delete_draft_newsletter(self, client):
        create = client.post("/api/newsletters", json={
            "subject": "To Delete",
            "body_html": "<p>Bye</p>",
        })
        nl_id = create.json()["id"]

        resp = client.delete(f"/api/newsletters/{nl_id}")
        assert resp.status_code == 200

        resp = client.get(f"/api/newsletters/{nl_id}")
        assert resp.status_code == 404

    def test_cannot_edit_sent_newsletter(self, client, db_conn):
        create = client.post("/api/newsletters", json={
            "subject": "Already Sent",
            "body_html": "<p>Sent</p>",
        })
        nl_id = create.json()["id"]

        # Mark as sent directly in DB
        cur = db_conn.cursor()
        cur.execute("UPDATE newsletters SET status = 'sent' WHERE id = %s", (nl_id,))

        resp = client.put(f"/api/newsletters/{nl_id}", json={"subject": "Changed"})
        assert resp.status_code == 400

    def test_cannot_delete_sent_newsletter(self, client, db_conn):
        create = client.post("/api/newsletters", json={
            "subject": "Sent NL",
            "body_html": "<p>Done</p>",
        })
        nl_id = create.json()["id"]

        cur = db_conn.cursor()
        cur.execute("UPDATE newsletters SET status = 'sent' WHERE id = %s", (nl_id,))

        resp = client.delete(f"/api/newsletters/{nl_id}")
        assert resp.status_code == 400


class TestRecipientPreview:
    def test_preview_recipients(self, client, db_conn, company_id):
        """Preview recipients with newsletter opt-in filter."""
        # Create two contacts — one subscribed, one not
        client.post("/api/contacts", json={
            "first_name": "Sub",
            "last_name": "Scribed",
            "email": "sub@test.com",
            "newsletter_opt_in": True,
            "company_id": company_id,
        })
        client.post("/api/contacts", json={
            "first_name": "Not",
            "last_name": "Subbed",
            "email": "not@test.com",
            "newsletter_opt_in": False,
            "company_id": company_id,
        })

        create = client.post("/api/newsletters", json={
            "subject": "Preview Test",
            "body_html": "<p>Test</p>",
        })
        nl_id = create.json()["id"]

        # With newsletter_only=true (default)
        resp = client.get(f"/api/newsletters/{nl_id}/recipients")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["recipients"][0]["email"] == "sub@test.com"

    def test_preview_by_lifecycle(self, client, db_conn, company_id):
        """Filter recipients by lifecycle stage."""
        client.post("/api/contacts", json={
            "first_name": "Client",
            "last_name": "Person",
            "email": "client@test.com",
            "lifecycle_stage": "client",
            "newsletter_opt_in": True,
            "company_id": company_id,
        })
        client.post("/api/contacts", json={
            "first_name": "Cold",
            "last_name": "Person",
            "email": "cold@test.com",
            "lifecycle_stage": "cold",
            "newsletter_opt_in": True,
            "company_id": company_id,
        })

        create = client.post("/api/newsletters", json={
            "subject": "Lifecycle Filter",
            "body_html": "<p>Test</p>",
        })
        nl_id = create.json()["id"]

        resp = client.get(f"/api/newsletters/{nl_id}/recipients?lifecycle_stages=client")
        data = resp.json()
        assert data["count"] == 1
        assert data["recipients"][0]["lifecycle_stage"] == "client"
