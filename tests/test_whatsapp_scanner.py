"""Tests for the WhatsApp scanner service."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.models.database import get_connection, run_migrations
from src.services.whatsapp_scanner import (
    WhatsAppScanner,
    _store_message,
    _update_scan_state,
    normalize_phone,
)


def _setup_contact_with_phone(conn):
    """Create a company and contact with a phone number."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO companies (name, name_normalized, firm_type, country)
           VALUES ('Phone Fund', 'phone fund', 'Hedge Fund', 'US') RETURNING id"""
    )
    company_id = cur.fetchone()["id"]

    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name,
                                 email, email_normalized, email_status,
                                 phone_number, phone_normalized)
           VALUES (%s, 'Bob', 'Smith', 'Bob Smith',
                   'bob@phonefund.com', 'bob@phonefund.com', 'valid',
                   '+1 555-123-4567', '+15551234567')
           RETURNING id""",
        (company_id,),
    )
    contact_id = cur.fetchone()["id"]
    conn.commit()
    return company_id, contact_id


def test_store_message(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id = _setup_contact_with_phone(conn)

    msg_id = _store_message(
        conn,
        contact_id=contact_id,
        phone_number="+15551234567",
        message_text="Hello, interested in your fund",
        direction="inbound",
        whatsapp_timestamp="2025-02-19T10:00:00+00:00",
    )
    conn.commit()

    assert msg_id is not None
    assert msg_id > 0

    # Verify stored
    cur = conn.cursor()
    cur.execute("SELECT * FROM whatsapp_messages WHERE id = %s", (msg_id,))
    row = cur.fetchone()
    assert row["contact_id"] == contact_id
    assert row["direction"] == "inbound"
    conn.close()


def test_store_message_dedup(tmp_db):
    """Same message with same timestamp+direction should be ignored."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id = _setup_contact_with_phone(conn)

    ts = "2025-02-19T10:00:00+00:00"
    msg1 = _store_message(
        conn,
        contact_id=contact_id,
        phone_number="+15551234567",
        message_text="Hello",
        direction="inbound",
        whatsapp_timestamp=ts,
    )
    conn.commit()

    msg2 = _store_message(
        conn,
        contact_id=contact_id,
        phone_number="+15551234567",
        message_text="Hello",
        direction="inbound",
        whatsapp_timestamp=ts,
    )
    conn.commit()

    assert msg1 is not None
    assert msg2 is None  # duplicate — ON CONFLICT DO NOTHING
    conn.close()


def test_update_scan_state(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id = _setup_contact_with_phone(conn)

    _update_scan_state(conn, contact_id)
    conn.commit()

    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM whatsapp_scan_state WHERE contact_id = %s", (contact_id,)
    )
    row = cur.fetchone()
    assert row is not None
    assert row["last_scanned_at"] is not None

    # Update again — should upsert
    _update_scan_state(conn, contact_id)
    conn.commit()

    cur.execute("SELECT COUNT(*) AS cnt FROM whatsapp_scan_state WHERE contact_id = %s", (contact_id,))
    assert cur.fetchone()["cnt"] == 1
    conn.close()


def test_scan_contacts_no_phones(tmp_db):
    """Scanning with no contacts having phone numbers should return zero."""
    conn = get_connection(tmp_db)
    run_migrations(conn)

    scanner = WhatsAppScanner.__new__(WhatsAppScanner)
    scanner._page = MagicMock()

    result = scanner.scan_contacts(conn)
    assert result["scanned"] == 0
    assert result["new_messages"] == 0
    conn.close()


@patch.object(WhatsAppScanner, "_extract_messages")
def test_scan_contacts_with_messages(mock_extract, tmp_db):
    """Should store extracted messages."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id = _setup_contact_with_phone(conn)

    mock_extract.return_value = [
        {
            "text": "Let's discuss further",
            "direction": "inbound",
            "timestamp": "2025-02-19T10:00:00+00:00",
        },
        {
            "text": "Sure, I'll send details",
            "direction": "outbound",
            "timestamp": "2025-02-19T10:05:00+00:00",
        },
    ]

    scanner = WhatsAppScanner.__new__(WhatsAppScanner)
    scanner._page = MagicMock()

    result = scanner.scan_contacts(conn)
    assert result["scanned"] == 1
    assert result["new_messages"] == 2
    assert result["errors"] == 0

    # Verify messages in DB
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM whatsapp_messages WHERE contact_id = %s ORDER BY whatsapp_timestamp",
        (contact_id,),
    )
    messages = cur.fetchall()
    assert len(messages) == 2
    assert messages[0]["direction"] == "inbound"
    assert messages[1]["direction"] == "outbound"
    conn.close()


def test_scanner_extract_requires_setup():
    """_extract_messages should raise if not initialized."""
    scanner = WhatsAppScanner()
    try:
        scanner._extract_messages({"phone_normalized": "+1234", "full_name": "Test"})
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "not initialized" in str(e)
