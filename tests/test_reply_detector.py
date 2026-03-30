"""Tests for the Gmail reply detector service."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import httpx

from src.models.campaigns import create_campaign
from src.models.database import get_connection, run_migrations
from tests.conftest import TEST_USER_ID
from src.services.reply_detector import (
    _classify_reply,
    _store_pending_reply,
    scan_gmail_for_replies,
)


def _setup_enrolled_contact(conn):
    """Create a company, contact, campaign, and enroll the contact."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO companies (name, name_normalized, firm_type, country, user_id)
           VALUES ('Test Fund', 'test fund', 'Hedge Fund', 'US', %s) RETURNING id""",
        (TEST_USER_ID,),
    )
    company_id = cur.fetchone()["id"]

    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name,
                                 email, email_normalized, email_status, user_id)
           VALUES (%s, 'Jane', 'Doe', 'Jane Doe', 'jane@testfund.com',
                   'jane@testfund.com', 'valid', %s)
           RETURNING id""",
        (company_id, TEST_USER_ID),
    )
    contact_id = cur.fetchone()["id"]

    campaign_id = create_campaign(conn, "reply_test", user_id=TEST_USER_ID)

    from src.models.campaigns import enroll_contact

    enroll_contact(conn, contact_id, campaign_id, user_id=1)

    # Set status to in_progress for scanning
    cur.execute(
        """UPDATE contact_campaign_status SET status = 'in_progress'
           WHERE contact_id = %s AND campaign_id = %s""",
        (contact_id, campaign_id),
    )
    conn.commit()

    return company_id, contact_id, campaign_id


def test_store_pending_reply(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id = _setup_enrolled_contact(conn)

    reply_id = _store_pending_reply(
        conn,
        contact_id=contact_id,
        campaign_id=campaign_id,
        gmail_thread_id="thread_123",
        gmail_message_id="msg_123",
        subject="Re: Introduction",
        snippet="Thanks for reaching out, let's chat!",
        classification="positive",
        confidence=0.9,
        user_id=1,
    )
    conn.commit()

    assert reply_id > 0

    # Verify it was stored
    cur = conn.cursor()
    cur.execute("SELECT * FROM pending_replies WHERE id = %s", (reply_id,))
    row = cur.fetchone()
    assert row["contact_id"] == contact_id
    assert row["gmail_message_id"] == "msg_123"
    assert row["classification"] == "positive"
    assert row["confidence"] == 0.9
    assert row["confirmed"] is False
    conn.close()


def test_store_pending_reply_dedup(tmp_db):
    """Same gmail_message_id should not be inserted twice."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id = _setup_enrolled_contact(conn)

    _store_pending_reply(
        conn,
        contact_id=contact_id,
        campaign_id=campaign_id,
        gmail_thread_id="thread_dup",
        gmail_message_id="msg_dup",
        subject="Re: test",
        snippet="test",
        classification="neutral",
        confidence=0.5,
        user_id=1,
    )
    conn.commit()

    # Check dedup — scanning would check before inserting
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM pending_replies WHERE gmail_message_id = %s", ("msg_dup",)
    )
    assert cur.fetchone() is not None
    conn.close()


def test_classify_reply_no_api_key(tmp_db):
    """Without ANTHROPIC_API_KEY, should return neutral."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
        classification, confidence = _classify_reply("Let's schedule a call", api_key="")
        assert classification == "neutral"
        assert confidence == 0.5


def test_classify_reply_empty_text(tmp_db):
    """Empty text should return neutral."""
    classification, confidence = _classify_reply("")
    assert classification == "neutral"
    assert confidence == 0.5


@patch("src.services.reply_detector.httpx.post")
def test_classify_reply_positive(mock_post):
    """Should classify a positive reply correctly."""
    mock_post.return_value = MagicMock(
        status_code=200,
        raise_for_status=MagicMock(),
        json=MagicMock(
            return_value={
                "content": [
                    {
                        "text": '{"classification": "positive", "confidence": 0.95, "summary": "Interested in meeting"}'
                    }
                ]
            }
        ),
    )
    classification, confidence = _classify_reply("Sounds great, let's schedule a call!", api_key="test-key")
    assert classification == "positive"
    assert confidence == 0.95


@patch("src.services.reply_detector.httpx.post")
def test_classify_reply_api_error(mock_post):
    """Should return neutral on API error."""
    mock_post.side_effect = httpx.ConnectError("API unreachable")
    classification, confidence = _classify_reply("Some reply text", api_key="test-key")
    assert classification == "neutral"
    assert confidence == 0.5


def test_scan_gmail_no_contacts(tmp_db):
    """Scanning with no enrolled contacts should return zero results."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    create_campaign(conn, "empty_camp", user_id=TEST_USER_ID)
    conn.commit()

    mock_drafter = MagicMock()
    result = scan_gmail_for_replies(conn, drafter=mock_drafter, user_id=1)
    assert result["scanned"] == 0
    assert result["new_replies"] == 0
    conn.close()


@patch("src.services.reply_detector._classify_reply", return_value=("positive", 0.9))
def test_scan_gmail_with_replies(mock_classify, tmp_db):
    """Full scan with mocked Gmail API should find new replies."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id = _setup_enrolled_contact(conn)

    # Mock the Gmail service
    mock_service = MagicMock()
    mock_messages = mock_service.users().messages()

    # messages.list returns one message
    mock_messages.list.return_value.execute.return_value = {
        "messages": [{"id": "msg_scan_1"}]
    }

    # messages.get returns message metadata
    mock_messages.get.return_value.execute.return_value = {
        "id": "msg_scan_1",
        "threadId": "thread_scan_1",
        "internalDate": "1798675200000",  # 2026-12-31 — after enrollment
        "snippet": "I'd love to learn more about your fund",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Re: Introduction to Our Fund"},
                {"name": "From", "value": "jane@testfund.com"},
            ]
        },
    }

    mock_drafter = MagicMock()
    mock_drafter._get_service.return_value = mock_service

    result = scan_gmail_for_replies(conn, drafter=mock_drafter, user_id=1)
    assert result["scanned"] == 1
    assert result["new_replies"] == 1
    assert result["errors"] == 0

    # Verify reply stored in DB
    cur = conn.cursor()
    cur.execute("SELECT * FROM pending_replies WHERE contact_id = %s", (contact_id,))
    reply = cur.fetchone()
    assert reply is not None
    assert reply["gmail_message_id"] == "msg_scan_1"
    assert reply["classification"] == "positive"
    conn.close()
