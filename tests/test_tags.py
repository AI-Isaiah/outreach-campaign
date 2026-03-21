"""Tests for tag API routes."""

from __future__ import annotations

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
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


@pytest.fixture
def client(tmp_db):
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


def _seed_company(conn, name="Test Fund"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country, user_id) "
        "VALUES (%s, %s, 500.0, 'Hedge Fund', 'US', %s) RETURNING id",
        (name, name.lower(), TEST_USER_ID),
    )
    conn.commit()
    return cur.fetchone()["id"]


def _seed_contact(conn, company_id, email="john@test.com"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO contacts (company_id, first_name, last_name, full_name, email, "
        "email_normalized, email_status) VALUES (%s, 'John', 'Doe', 'John Doe', %s, %s, 'valid') RETURNING id",
        (company_id, email, email.lower()),
    )
    conn.commit()
    return cur.fetchone()["id"]


# ---------- CRUD ----------

def test_create_tag(client):
    resp = client.post("/api/tags", json={"name": "VIP", "color": "#EF4444"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["id"] > 0


def test_create_duplicate_tag(client):
    client.post("/api/tags", json={"name": "VIP"})
    resp = client.post("/api/tags", json={"name": "VIP"})
    assert resp.status_code == 409


def test_list_tags(client):
    client.post("/api/tags", json={"name": "Alpha"})
    client.post("/api/tags", json={"name": "Beta"})

    resp = client.get("/api/tags")
    assert resp.status_code == 200
    tags = resp.json()
    assert len(tags) == 2
    assert tags[0]["name"] == "Alpha"  # sorted by name


def test_delete_tag(client):
    resp = client.post("/api/tags", json={"name": "Temp"})
    tag_id = resp.json()["id"]

    resp2 = client.delete(f"/api/tags/{tag_id}")
    assert resp2.status_code == 200

    resp3 = client.get("/api/tags")
    assert len(resp3.json()) == 0


def test_delete_tag_not_found(client):
    resp = client.delete("/api/tags/9999")
    assert resp.status_code == 404


# ---------- Attach / Detach ----------

def test_attach_tag_to_contact(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)

    resp = client.post("/api/tags", json={"name": "Hot Lead"})
    tag_id = resp.json()["id"]

    resp2 = client.post(f"/api/tags/{tag_id}/attach", json={
        "entity_type": "contact",
        "entity_id": contact_id,
    })
    assert resp2.status_code == 200
    assert resp2.json()["already_attached"] is False

    # Attach again should be idempotent
    resp3 = client.post(f"/api/tags/{tag_id}/attach", json={
        "entity_type": "contact",
        "entity_id": contact_id,
    })
    assert resp3.json()["already_attached"] is True


def test_attach_tag_to_company(client, db_conn):
    company_id = _seed_company(db_conn)

    resp = client.post("/api/tags", json={"name": "Tier 1"})
    tag_id = resp.json()["id"]

    resp2 = client.post(f"/api/tags/{tag_id}/attach", json={
        "entity_type": "company",
        "entity_id": company_id,
    })
    assert resp2.status_code == 200


def test_attach_tag_invalid_entity_type(client):
    resp = client.post("/api/tags", json={"name": "Test"})
    tag_id = resp.json()["id"]

    resp2 = client.post(f"/api/tags/{tag_id}/attach", json={
        "entity_type": "deal",
        "entity_id": 1,
    })
    assert resp2.status_code == 400


def test_detach_tag(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)

    resp = client.post("/api/tags", json={"name": "Remove Me"})
    tag_id = resp.json()["id"]

    client.post(f"/api/tags/{tag_id}/attach", json={
        "entity_type": "contact",
        "entity_id": contact_id,
    })

    resp2 = client.post(f"/api/tags/{tag_id}/detach", json={
        "entity_type": "contact",
        "entity_id": contact_id,
    })
    assert resp2.status_code == 200

    # Verify removed
    resp3 = client.get(f"/api/tags/entity/contact/{contact_id}")
    assert len(resp3.json()) == 0


# ---------- Entity Tags ----------

def test_get_entity_tags(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)

    for name in ("Alpha", "Beta"):
        resp = client.post("/api/tags", json={"name": name})
        tag_id = resp.json()["id"]
        client.post(f"/api/tags/{tag_id}/attach", json={
            "entity_type": "contact",
            "entity_id": contact_id,
        })

    resp2 = client.get(f"/api/tags/entity/contact/{contact_id}")
    assert resp2.status_code == 200
    tags = resp2.json()
    assert len(tags) == 2
    assert tags[0]["name"] == "Alpha"


def test_get_entity_tags_invalid_type(client):
    resp = client.get("/api/tags/entity/deal/1")
    assert resp.status_code == 400


# ---------- Tag Filter on CRM ----------

def test_crm_contacts_filter_by_tag(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)

    resp = client.post("/api/tags", json={"name": "VIP"})
    tag_id = resp.json()["id"]
    client.post(f"/api/tags/{tag_id}/attach", json={
        "entity_type": "contact",
        "entity_id": contact_id,
    })

    resp2 = client.get("/api/crm/contacts?tag=VIP")
    assert resp2.status_code == 200
    assert resp2.json()["total"] >= 1

    resp3 = client.get("/api/crm/contacts?tag=nonexistent")
    assert resp3.json()["total"] == 0


def test_crm_companies_filter_by_tag(client, db_conn):
    company_id = _seed_company(db_conn)

    resp = client.post("/api/tags", json={"name": "Tier 1"})
    tag_id = resp.json()["id"]
    client.post(f"/api/tags/{tag_id}/attach", json={
        "entity_type": "company",
        "entity_id": company_id,
    })

    resp2 = client.get("/api/crm/companies?tag=Tier 1")
    assert resp2.status_code == 200
    assert resp2.json()["total"] >= 1
