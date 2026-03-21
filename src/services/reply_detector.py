"""Gmail reply detection service.

Scans Gmail inbox for replies from enrolled contacts, classifies sentiment
via Claude API, and stores pending replies for operator review.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import httpx

from src.services.gmail_drafter import GmailDrafter
from src.models.database import get_cursor

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLASSIFY_MODEL = "claude-haiku-4-5-20251001"


def scan_gmail_for_replies(conn, drafter: GmailDrafter | None = None) -> dict:
    """Scan Gmail for replies from enrolled contacts.

    Args:
        conn: PostgreSQL connection
        drafter: optional GmailDrafter instance (created if not provided)

    Returns:
        dict with keys: scanned, new_replies, errors
    """
    # Get enrolled contacts with email addresses first
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT DISTINCT c.id, c.email, ccs.campaign_id, ccs.created_at AS enrolled_at
               FROM contact_campaign_status ccs
               JOIN contacts c ON c.id = ccs.contact_id
               WHERE c.email IS NOT NULL
                 AND ccs.status IN ('in_progress', 'queued')"""
        )
        contacts = cur.fetchall()

    stats = {"scanned": 0, "new_replies": 0, "errors": 0}

    if not contacts:
        return stats

    if drafter is None:
        drafter = GmailDrafter()

    service = drafter._get_service()

    for contact in contacts:
        try:
            _scan_contact_replies(
                conn, service, contact, stats
            )
        except Exception:
            logger.exception(
                "Error scanning replies for contact %s", contact["id"]
            )
            stats["errors"] += 1

    conn.commit()
    return stats


def _scan_contact_replies(conn, service, contact: dict, stats: dict) -> None:
    """Scan Gmail for replies from a single contact."""
    stats["scanned"] += 1

    # Search for messages from this contact's email
    query = f"from:{contact['email']}"
    try:
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=10)
            .execute()
        )
    except Exception:
        logger.exception("Gmail API error for %s", contact["email"])
        stats["errors"] += 1
        return

    messages = results.get("messages", [])
    if not messages:
        return

    with get_cursor(conn) as cur:
        for msg_stub in messages:
            msg_id = msg_stub["id"]

            # Check if we already have this message
            cur.execute(
                "SELECT id FROM pending_replies WHERE gmail_message_id = %s",
                (msg_id,),
            )
            if cur.fetchone():
                continue

            # Fetch the full message
            try:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="metadata")
                    .execute()
                )
            except Exception:
                continue

            # Check if message is after enrollment
            internal_ts = int(msg.get("internalDate", "0")) / 1000
            msg_date = datetime.fromtimestamp(internal_ts, tz=timezone.utc)
            enrolled_at = contact["enrolled_at"]
            if enrolled_at:
                try:
                    if isinstance(enrolled_at, str):
                        enrolled_dt = datetime.fromisoformat(
                            enrolled_at.replace("Z", "+00:00")
                        )
                    else:
                        enrolled_dt = enrolled_at
                    if enrolled_dt.tzinfo is None:
                        enrolled_dt = enrolled_dt.replace(tzinfo=timezone.utc)
                    if msg_date < enrolled_dt:
                        continue
                except (ValueError, TypeError):
                    pass

            # Extract subject and snippet
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            subject = headers.get("subject", "")
            snippet = msg.get("snippet", "")
            thread_id = msg.get("threadId", "")

            # Classify the reply
            classification, confidence = _classify_reply(snippet)

            # Store as pending reply
            _store_pending_reply(
                conn,
                contact_id=contact["id"],
                campaign_id=contact["campaign_id"],
                gmail_thread_id=thread_id,
                gmail_message_id=msg_id,
                subject=subject,
                snippet=snippet,
                classification=classification,
                confidence=confidence,
            )
            stats["new_replies"] += 1


def _classify_reply(reply_text: str) -> tuple[str, float]:
    """Classify a reply as positive/negative/neutral using Claude API.

    Returns:
        (classification, confidence) tuple
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — defaulting to neutral")
        return "neutral", 0.5

    if not reply_text or not reply_text.strip():
        return "neutral", 0.5

    prompt = (
        "Classify this email reply from a potential investor/allocator. "
        "Is the sender interested in taking a meeting or learning more (positive), "
        "declining or unsubscribing (negative), or neutral/ambiguous (neutral)?\n\n"
        f"Reply text: {reply_text}\n\n"
        "Respond with JSON only: "
        '{"classification": "positive"|"negative"|"neutral", '
        '"confidence": 0.0-1.0, "summary": "one sentence"}'
    )

    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLASSIFY_MODEL,
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"]
        parsed = json.loads(text)
        return parsed.get("classification", "neutral"), parsed.get("confidence", 0.5)
    except Exception:
        logger.exception("LLM classification failed")
        return "neutral", 0.5


def _store_pending_reply(
    conn,
    *,
    contact_id: int,
    campaign_id: int,
    gmail_thread_id: str,
    gmail_message_id: str,
    subject: str,
    snippet: str,
    classification: str,
    confidence: float,
) -> int:
    """Insert a pending reply into the database.

    Returns:
        The new pending_reply id.
    """
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO pending_replies
                   (contact_id, campaign_id, gmail_thread_id, gmail_message_id,
                    subject, snippet, reply_snippet,
                    llm_classification, llm_confidence,
                    classification, confidence)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (gmail_message_id) DO NOTHING
               RETURNING id""",
            (
                contact_id,
                campaign_id,
                gmail_thread_id,
                gmail_message_id,
                subject,
                snippet,
                snippet,
                classification,
                confidence,
                classification,
                confidence,
            ),
        )
        row = cur.fetchone()
        return row["id"] if row else None
