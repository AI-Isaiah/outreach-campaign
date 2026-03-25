"""Tests for product interest tracking API."""

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
        "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Product Corp', 'product corp', %s) RETURNING id",
        (TEST_USER_ID,),
    )
    return cur.fetchone()["id"]


@pytest.fixture
def contact_id(client, company_id):
    resp = client.post("/api/contacts", json={
        "first_name": "Product",
        "last_name": "Test",
        "company_id": company_id,
    })
    return resp.json()["id"]


@pytest.fixture
def seed_products(db_conn):
    """Re-seed products since TRUNCATE clears them."""
    cur = db_conn.cursor()
    cur.execute("""
        INSERT INTO products (name, description, user_id) VALUES
            ('Multimarket', 'Multimarket Fund', %s),
            ('Delta', 'Delta Fund', %s),
            ('Metaworld Fund', 'Metaworld Fund', %s)
        ON CONFLICT (user_id, name) DO NOTHING
    """, (TEST_USER_ID, TEST_USER_ID, TEST_USER_ID))
    cur.execute("SELECT * FROM products ORDER BY id")
    return cur.fetchall()


class TestProducts:
    def test_list_seeded_products(self, client, seed_products):
        """Products should be listed after seeding."""
        resp = client.get("/api/products")
        assert resp.status_code == 200
        products = resp.json()
        names = {p["name"] for p in products}
        assert "Multimarket" in names
        assert "Delta" in names
        assert "Metaworld Fund" in names

    def test_create_product(self, client):
        resp = client.post("/api/products", json={
            "name": "New Fund",
            "description": "A new fund product",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update_product(self, client):
        create = client.post("/api/products", json={"name": "Update Me"})
        pid = create.json()["id"]

        resp = client.put(f"/api/products/{pid}", json={"description": "Updated"})
        assert resp.status_code == 200

    def test_delete_product_soft(self, client):
        """Delete should soft-delete (set is_active=false)."""
        create = client.post("/api/products", json={"name": "To Delete"})
        pid = create.json()["id"]

        resp = client.delete(f"/api/products/{pid}")
        assert resp.status_code == 200

        # Should not appear in active list
        products = client.get("/api/products").json()
        assert not any(p["id"] == pid for p in products)


class TestContactProducts:
    def test_link_product(self, client, contact_id, seed_products):
        """Link a product interest to a contact."""
        products = client.get("/api/products").json()
        pid = products[0]["id"]

        resp = client.post(f"/api/contacts/{contact_id}/products", json={
            "product_id": pid,
            "stage": "interested",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_list_contact_products(self, client, contact_id, seed_products):
        products = client.get("/api/products").json()
        pid = products[0]["id"]

        client.post(f"/api/contacts/{contact_id}/products", json={
            "product_id": pid,
        })

        resp = client.get(f"/api/contacts/{contact_id}/products")
        assert resp.status_code == 200
        cps = resp.json()
        assert len(cps) == 1
        assert cps[0]["product_name"] == products[0]["name"]
        assert cps[0]["stage"] == "discussed"

    def test_update_product_stage(self, client, contact_id, seed_products):
        products = client.get("/api/products").json()
        pid = products[0]["id"]

        client.post(f"/api/contacts/{contact_id}/products", json={
            "product_id": pid,
        })

        resp = client.patch(
            f"/api/contacts/{contact_id}/products/{pid}/stage",
            json={"stage": "due_diligence"},
        )
        assert resp.status_code == 200

        cps = client.get(f"/api/contacts/{contact_id}/products").json()
        assert cps[0]["stage"] == "due_diligence"

    def test_invalid_stage(self, client, contact_id, seed_products):
        products = client.get("/api/products").json()
        pid = products[0]["id"]

        resp = client.post(f"/api/contacts/{contact_id}/products", json={
            "product_id": pid,
            "stage": "bogus",
        })
        assert resp.status_code == 400

    def test_remove_product(self, client, contact_id, seed_products):
        products = client.get("/api/products").json()
        pid = products[0]["id"]

        client.post(f"/api/contacts/{contact_id}/products", json={
            "product_id": pid,
        })

        resp = client.delete(f"/api/contacts/{contact_id}/products/{pid}")
        assert resp.status_code == 200

        cps = client.get(f"/api/contacts/{contact_id}/products").json()
        assert len(cps) == 0

    def test_upsert_on_conflict(self, client, contact_id, seed_products):
        """Linking same product twice should update, not error."""
        products = client.get("/api/products").json()
        pid = products[0]["id"]

        client.post(f"/api/contacts/{contact_id}/products", json={
            "product_id": pid,
            "stage": "discussed",
        })

        resp = client.post(f"/api/contacts/{contact_id}/products", json={
            "product_id": pid,
            "stage": "invested",
        })
        assert resp.status_code == 200

        cps = client.get(f"/api/contacts/{contact_id}/products").json()
        assert len(cps) == 1
        assert cps[0]["stage"] == "invested"
