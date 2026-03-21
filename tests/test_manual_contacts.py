"""Tests for manual contact creation and lifecycle stage management."""

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
    """Create a company owned by the test user for contact association."""
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Default Corp', 'default corp', %s) RETURNING id",
        (TEST_USER_ID,),
    )
    return cur.fetchone()["id"]


class TestCreateContact:
    def test_create_minimal_contact(self, client, company_id):
        """Create a contact with only required fields."""
        resp = client.post("/api/contacts", json={
            "first_name": "Alice",
            "last_name": "Smith",
            "company_id": company_id,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "id" in data

        # Verify contact was created
        detail = client.get(f"/api/contacts/{data['id']}").json()
        assert detail["contact"]["full_name"] == "Alice Smith"
        assert detail["contact"]["source"] == "manual"
        assert detail["contact"]["lifecycle_stage"] == "cold"

    def test_create_full_contact(self, client, db_conn):
        """Create a contact with all optional fields."""
        # Create a company first
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Test Corp', 'test corp', %s) RETURNING id",
            (TEST_USER_ID,),
        )
        company_id = cur.fetchone()["id"]

        resp = client.post("/api/contacts", json={
            "first_name": "Bob",
            "last_name": "Jones",
            "email": "bob@test.com",
            "phone_number": "+15551234567",
            "linkedin_url": "https://linkedin.com/in/bobjones",
            "title": "CIO",
            "company_id": company_id,
            "lifecycle_stage": "nurturing",
            "newsletter_opt_in": True,
            "notes": "Met at conference",
        })
        assert resp.status_code == 200
        data = resp.json()
        contact_id = data["id"]

        detail = client.get(f"/api/contacts/{contact_id}").json()
        c = detail["contact"]
        assert c["email"] == "bob@test.com"
        assert c["lifecycle_stage"] == "nurturing"
        assert c["newsletter_status"] == "subscribed"
        assert c["company_id"] == company_id

        # Check initial note was saved
        assert any(n["content"] == "Met at conference" for n in detail["notes"])

    def test_create_contact_no_company(self, client, db_conn):
        """Create a contact without a company — creation succeeds, company_id is NULL."""
        resp = client.post("/api/contacts", json={
            "first_name": "Solo",
            "last_name": "Person",
        })
        assert resp.status_code == 200
        contact_id = resp.json()["id"]

        # Verify directly in DB since the API detail route requires a company join
        cur = db_conn.cursor()
        cur.execute("SELECT company_id FROM contacts WHERE id = %s", (contact_id,))
        row = cur.fetchone()
        assert row["company_id"] is None

    def test_create_contact_invalid_company(self, client):
        """Reject contact creation with nonexistent company."""
        resp = client.post("/api/contacts", json={
            "first_name": "Bad",
            "last_name": "Ref",
            "company_id": 99999,
        })
        assert resp.status_code == 404

    def test_create_contact_invalid_lifecycle(self, client):
        """Reject invalid lifecycle stage."""
        resp = client.post("/api/contacts", json={
            "first_name": "Bad",
            "last_name": "Stage",
            "lifecycle_stage": "invalid",
        })
        assert resp.status_code == 400


class TestLifecycleStage:
    def test_update_lifecycle(self, client, company_id):
        """Update lifecycle stage of an existing contact."""
        create = client.post("/api/contacts", json={
            "first_name": "Lifecycle",
            "last_name": "Test",
            "company_id": company_id,
        })
        cid = create.json()["id"]

        resp = client.patch(f"/api/contacts/{cid}/lifecycle", json={
            "lifecycle_stage": "contacted",
        })
        assert resp.status_code == 200
        assert resp.json()["lifecycle_stage"] == "contacted"

        # Verify it stuck
        detail = client.get(f"/api/contacts/{cid}").json()
        assert detail["contact"]["lifecycle_stage"] == "contacted"

    def test_update_lifecycle_invalid(self, client, company_id):
        """Reject invalid lifecycle stage."""
        create = client.post("/api/contacts", json={
            "first_name": "Bad",
            "last_name": "Update",
            "company_id": company_id,
        })
        cid = create.json()["id"]

        resp = client.patch(f"/api/contacts/{cid}/lifecycle", json={
            "lifecycle_stage": "nonexistent",
        })
        assert resp.status_code == 400

    def test_update_lifecycle_not_found(self, client):
        """404 for nonexistent contact."""
        resp = client.patch("/api/contacts/99999/lifecycle", json={
            "lifecycle_stage": "client",
        })
        assert resp.status_code == 404

    def test_same_lifecycle_noop(self, client, company_id):
        """No-op when setting same stage."""
        create = client.post("/api/contacts", json={
            "first_name": "Same",
            "last_name": "Stage",
            "company_id": company_id,
        })
        cid = create.json()["id"]

        resp = client.patch(f"/api/contacts/{cid}/lifecycle", json={
            "lifecycle_stage": "cold",
        })
        assert resp.status_code == 200
        assert resp.json()["lifecycle_stage"] == "cold"
