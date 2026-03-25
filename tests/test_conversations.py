"""Tests for conversation tracking API."""

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
        "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Conv Corp', 'conv corp', %s) RETURNING id",
        (TEST_USER_ID,),
    )
    return cur.fetchone()["id"]


@pytest.fixture
def contact_id(client, company_id):
    resp = client.post("/api/contacts", json={
        "first_name": "Conv",
        "last_name": "Test",
        "company_id": company_id,
    })
    return resp.json()["id"]


class TestConversations:
    def test_create_conversation(self, client, contact_id):
        resp = client.post(f"/api/contacts/{contact_id}/conversations", json={
            "channel": "conference",
            "title": "Token2049 sidebar",
            "notes": "Discussed Multimarket fund",
            "outcome": "successful",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "id" in resp.json()

    def test_list_conversations(self, client, contact_id):
        # Create two conversations
        client.post(f"/api/contacts/{contact_id}/conversations", json={
            "channel": "phone",
            "title": "Intro call",
        })
        client.post(f"/api/contacts/{contact_id}/conversations", json={
            "channel": "video_call",
            "title": "Follow-up",
        })

        resp = client.get(f"/api/contacts/{contact_id}/conversations")
        assert resp.status_code == 200
        convs = resp.json()
        assert len(convs) == 2

    def test_update_conversation(self, client, contact_id):
        create = client.post(f"/api/contacts/{contact_id}/conversations", json={
            "channel": "phone",
            "title": "Initial call",
        })
        conv_id = create.json()["id"]

        resp = client.put(f"/api/conversations/{conv_id}", json={
            "title": "Updated call",
            "outcome": "successful",
        })
        assert resp.status_code == 200

    def test_delete_conversation(self, client, contact_id):
        create = client.post(f"/api/contacts/{contact_id}/conversations", json={
            "channel": "email",
            "title": "Quick exchange",
        })
        conv_id = create.json()["id"]

        resp = client.delete(f"/api/conversations/{conv_id}")
        assert resp.status_code == 200

        # Verify deleted
        convs = client.get(f"/api/contacts/{contact_id}/conversations").json()
        assert len(convs) == 0

    def test_invalid_channel(self, client, contact_id):
        resp = client.post(f"/api/contacts/{contact_id}/conversations", json={
            "channel": "pigeon_mail",
            "title": "Bad channel",
        })
        assert resp.status_code == 400

    def test_invalid_outcome(self, client, contact_id):
        resp = client.post(f"/api/contacts/{contact_id}/conversations", json={
            "channel": "phone",
            "title": "Bad outcome",
            "outcome": "maybe",
        })
        assert resp.status_code == 400

    def test_contact_not_found(self, client):
        resp = client.post("/api/contacts/99999/conversations", json={
            "channel": "phone",
            "title": "Ghost",
        })
        assert resp.status_code == 404

    def test_lifecycle_auto_advance(self, client, contact_id):
        """Successful conversation should advance lifecycle."""
        # Contact starts as 'cold'
        client.post(f"/api/contacts/{contact_id}/conversations", json={
            "channel": "conference",
            "title": "First meeting",
            "outcome": "successful",
        })

        detail = client.get(f"/api/contacts/{contact_id}").json()
        assert detail["contact"]["lifecycle_stage"] == "contacted"

        # Second successful conversation: contacted -> nurturing
        client.post(f"/api/contacts/{contact_id}/conversations", json={
            "channel": "phone",
            "title": "Follow-up call",
            "outcome": "successful",
        })

        detail = client.get(f"/api/contacts/{contact_id}").json()
        assert detail["contact"]["lifecycle_stage"] == "nurturing"
