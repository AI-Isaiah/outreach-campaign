"""Tests for deal pipeline API routes."""

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


def _seed_company(conn, name="Test Fund", aum=500.0):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country, user_id) "
        "VALUES (%s, %s, %s, 'Hedge Fund', 'US', %s) RETURNING id",
        (name, name.lower(), aum, TEST_USER_ID),
    )
    conn.commit()
    return cur.fetchone()["id"]


def _seed_contact(conn, company_id, first="John", last="Doe", email="john@test.com"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO contacts (company_id, first_name, last_name, full_name, email, "
        "email_normalized, email_status, user_id) VALUES (%s, %s, %s, %s, %s, %s, 'valid', %s) RETURNING id",
        (company_id, first, last, f"{first} {last}", email, email.lower(), TEST_USER_ID),
    )
    conn.commit()
    return cur.fetchone()["id"]


# ---------- Create ----------

def test_create_deal(client, db_conn):
    company_id = _seed_company(db_conn)
    resp = client.post("/api/deals", json={
        "company_id": company_id,
        "title": "Series A Investment",
        "amount_millions": 25.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["id"] > 0


def test_create_deal_with_contact(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)
    resp = client.post("/api/deals", json={
        "company_id": company_id,
        "contact_id": contact_id,
        "title": "Fund Allocation",
        "stage": "contacted",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_create_deal_invalid_stage(client, db_conn):
    company_id = _seed_company(db_conn)
    resp = client.post("/api/deals", json={
        "company_id": company_id,
        "title": "Bad Deal",
        "stage": "invalid_stage",
    })
    assert resp.status_code in (400, 422)


def test_create_deal_company_not_found(client):
    resp = client.post("/api/deals", json={
        "company_id": 9999,
        "title": "No Company",
    })
    assert resp.status_code == 404


# ---------- Detail ----------

def test_get_deal_detail(client, db_conn):
    company_id = _seed_company(db_conn)
    resp = client.post("/api/deals", json={
        "company_id": company_id,
        "title": "Detail Test",
    })
    deal_id = resp.json()["id"]

    resp2 = client.get(f"/api/deals/{deal_id}")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["deal"]["title"] == "Detail Test"
    assert len(data["stage_history"]) == 1  # initial stage log


def test_get_deal_not_found(client):
    resp = client.get("/api/deals/9999")
    assert resp.status_code == 404


# ---------- Update ----------

def test_update_deal(client, db_conn):
    company_id = _seed_company(db_conn)
    resp = client.post("/api/deals", json={
        "company_id": company_id,
        "title": "Old Title",
    })
    deal_id = resp.json()["id"]

    resp2 = client.put(f"/api/deals/{deal_id}", json={"title": "New Title"})
    assert resp2.status_code == 200

    resp3 = client.get(f"/api/deals/{deal_id}")
    assert resp3.json()["deal"]["title"] == "New Title"


# ---------- Stage Transitions ----------

def test_stage_transition(client, db_conn):
    company_id = _seed_company(db_conn)
    resp = client.post("/api/deals", json={
        "company_id": company_id,
        "title": "Stage Test",
        "stage": "cold",
    })
    deal_id = resp.json()["id"]

    resp2 = client.patch(f"/api/deals/{deal_id}/stage", json={"stage": "contacted"})
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["changed"] is True
    assert data["from_stage"] == "cold"
    assert data["stage"] == "contacted"

    # Verify stage history
    resp3 = client.get(f"/api/deals/{deal_id}")
    assert len(resp3.json()["stage_history"]) == 2


def test_stage_transition_same_stage(client, db_conn):
    company_id = _seed_company(db_conn)
    resp = client.post("/api/deals", json={
        "company_id": company_id,
        "title": "Same Stage",
        "stage": "cold",
    })
    deal_id = resp.json()["id"]

    resp2 = client.patch(f"/api/deals/{deal_id}/stage", json={"stage": "cold"})
    assert resp2.status_code == 200
    assert resp2.json()["changed"] is False


# ---------- Pipeline ----------

def test_pipeline_grouping(client, db_conn):
    company_id = _seed_company(db_conn)

    client.post("/api/deals", json={"company_id": company_id, "title": "D1", "stage": "cold"})
    client.post("/api/deals", json={"company_id": company_id, "title": "D2", "stage": "engaged"})
    client.post("/api/deals", json={"company_id": company_id, "title": "D3", "stage": "won"})

    resp = client.get("/api/deals/pipeline")
    assert resp.status_code == 200
    pipeline = resp.json()["pipeline"]
    assert len(pipeline["cold"]) == 1
    assert len(pipeline["engaged"]) == 1
    assert len(pipeline["won"]) == 1
    assert len(pipeline["contacted"]) == 0


# ---------- List ----------

def test_list_deals(client, db_conn):
    company_id = _seed_company(db_conn)
    client.post("/api/deals", json={"company_id": company_id, "title": "D1"})
    client.post("/api/deals", json={"company_id": company_id, "title": "D2"})

    resp = client.get("/api/deals")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_list_deals_filter_stage(client, db_conn):
    company_id = _seed_company(db_conn)
    client.post("/api/deals", json={"company_id": company_id, "title": "D1", "stage": "cold"})
    client.post("/api/deals", json={"company_id": company_id, "title": "D2", "stage": "won"})

    resp = client.get("/api/deals?stage=cold")
    assert resp.json()["total"] == 1


# ---------- Delete ----------

def test_delete_deal(client, db_conn):
    company_id = _seed_company(db_conn)
    resp = client.post("/api/deals", json={"company_id": company_id, "title": "To Delete"})
    deal_id = resp.json()["id"]

    resp2 = client.delete(f"/api/deals/{deal_id}")
    assert resp2.status_code == 200
    assert resp2.json()["success"] is True

    resp3 = client.get(f"/api/deals/{deal_id}")
    assert resp3.status_code == 404


def test_delete_deal_not_found(client):
    resp = client.delete("/api/deals/9999")
    assert resp.status_code == 404
