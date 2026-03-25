"""Tests for unified inbox API route."""

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
        "email_normalized, email_status, user_id) VALUES (%s, 'John', 'Doe', 'John Doe', %s, %s, 'valid', %s) RETURNING id",
        (company_id, email, email.lower(), TEST_USER_ID),
    )
    conn.commit()
    return cur.fetchone()["id"]


def _seed_campaign(conn, name="test_campaign"):
    from src.models.campaigns import create_campaign
    return create_campaign(conn, name, user_id=TEST_USER_ID)


def test_inbox_empty(client):
    resp = client.get("/api/inbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_inbox_with_pending_reply(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)
    campaign_id = _seed_campaign(db_conn)

    cur = db_conn.cursor()
    cur.execute(
        """INSERT INTO pending_replies (contact_id, campaign_id, subject, snippet,
                                        classification, confidence, confirmed)
           VALUES (%s, %s, 'Re: Intro', 'Sounds great!', 'positive', 0.95, false)""",
        (contact_id, campaign_id),
    )
    db_conn.commit()

    resp = client.get("/api/inbox")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["channel"] == "email"
    assert data["items"][0]["contact_name"] == "John Doe"


def test_inbox_with_whatsapp(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)

    cur = db_conn.cursor()
    cur.execute(
        """INSERT INTO whatsapp_messages (contact_id, phone_number, direction, message_text, captured_at)
           VALUES (%s, '+15551234567', 'received', 'Hello from WhatsApp', NOW())""",
        (contact_id,),
    )
    db_conn.commit()

    resp = client.get("/api/inbox")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["channel"] == "whatsapp"


def test_inbox_channel_filter(client, db_conn):
    company_id = _seed_company(db_conn)
    contact_id = _seed_contact(db_conn, company_id)
    campaign_id = _seed_campaign(db_conn)

    cur = db_conn.cursor()
    # Add email reply
    cur.execute(
        """INSERT INTO pending_replies (contact_id, campaign_id, subject, snippet,
                                        classification, confidence, confirmed)
           VALUES (%s, %s, 'Re: Intro', 'Sounds great!', 'positive', 0.95, false)""",
        (contact_id, campaign_id),
    )
    # Add whatsapp message
    cur.execute(
        """INSERT INTO whatsapp_messages (contact_id, phone_number, direction, message_text, captured_at)
           VALUES (%s, '+15551234567', 'received', 'WhatsApp msg', NOW())""",
        (contact_id,),
    )
    # Add note
    cur.execute(
        "INSERT INTO response_notes (contact_id, note_type, content) VALUES (%s, 'general', 'A note')",
        (contact_id,),
    )
    db_conn.commit()

    # All channels
    resp = client.get("/api/inbox")
    assert resp.json()["total"] == 3

    # Email only
    resp2 = client.get("/api/inbox?channel=email")
    assert resp2.json()["total"] == 1
    assert resp2.json()["items"][0]["channel"] == "email"

    # WhatsApp only
    resp3 = client.get("/api/inbox?channel=whatsapp")
    assert resp3.json()["total"] == 1
    assert resp3.json()["items"][0]["channel"] == "whatsapp"

    # Notes only
    resp4 = client.get("/api/inbox?channel=notes")
    assert resp4.json()["total"] == 1
    assert resp4.json()["items"][0]["channel"] == "note"
