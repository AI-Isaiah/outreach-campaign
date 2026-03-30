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
from googleapiclient.errors import HttpError as GoogleHttpError

from src.constants import LLM_MODELS
from src.enums import ContactStatus
from src.services.gmail_drafter import GmailDrafter
from src.models.database import get_cursor

logger = logging.getLogger(__name__)

CLASSIFY_MODEL = LLM_MODELS["classification"]


def scan_gmail_for_replies(
    conn,
    drafter: GmailDrafter | None = None,
    *,
    user_id: int,
    gmail_service=None,
) -> dict:
    """Scan Gmail for replies from enrolled contacts.

    Args:
        conn: PostgreSQL connection
        drafter: optional GmailDrafter instance (created if not provided)
        user_id: owner user id — only scan contacts belonging to this user
        gmail_service: optional pre-built Gmail API service object.
            When provided (e.g. from DB-stored tokens in a cron/web context),
            used directly instead of building one from drafter.

    Returns:
        dict with keys: scanned, new_replies, errors
    """
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT DISTINCT c.id, c.email, c.user_id, ccs.campaign_id, ccs.created_at AS enrolled_at
               FROM contact_campaign_status ccs
               JOIN contacts c ON c.id = ccs.contact_id
               WHERE c.email IS NOT NULL
                 AND ccs.status IN (%s, %s)
                 AND c.user_id = %s""",
            (ContactStatus.IN_PROGRESS, ContactStatus.QUEUED, user_id),
        )
        contacts = cur.fetchall()

    stats = {"scanned": 0, "new_replies": 0, "errors": 0}

    if not contacts:
        return stats

    if gmail_service is not None:
        service = gmail_service
    else:
        if drafter is None:
            drafter = GmailDrafter()
        service = drafter._get_service()

    for contact in contacts:
        try:
            _scan_contact_replies(
                conn, service, contact, stats
            )
        except (GoogleHttpError, httpx.HTTPError, KeyError, ValueError) as exc:
            logger.exception(
                "Error scanning replies for contact %s: %s", contact["id"], exc
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
    except (GoogleHttpError, OSError, KeyError) as exc:
        logger.exception("Gmail API error for %s: %s", contact["email"], exc)
        stats["errors"] += 1
        return

    messages = results.get("messages", [])
    if not messages:
        return

    with get_cursor(conn) as cur:
        for msg_stub in messages:
            msg_id = msg_stub["id"]

            # Check if we already have this message (scoped via contact FK + user_id)
            cur.execute(
                "SELECT id FROM pending_replies WHERE gmail_message_id = %s AND user_id = %s",
                (msg_id, contact["user_id"]),
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
            except (GoogleHttpError, OSError):
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

            # Resolve API key: per-user DB key first, then env fallback
            _api_key = _resolve_api_key(conn, contact["user_id"])

            # Classify the reply
            classification, confidence = _classify_reply(snippet, api_key=_api_key)

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
                user_id=contact["user_id"],
            )
            stats["new_replies"] += 1


def _resolve_api_key(conn, user_id: int) -> str:
    """Resolve Anthropic API key: check user's DB key first, fall back to env."""
    try:
        from src.web.routes.settings import get_user_api_keys
        keys = get_user_api_keys(conn, user_id)
        if keys.get("anthropic"):
            return keys["anthropic"]
    except (ImportError, Exception):
        pass
    return os.getenv("ANTHROPIC_API_KEY", "")


def _classify_reply(reply_text: str, *, api_key: str = "") -> tuple[str, float]:
    """Classify a reply as positive/negative/neutral using Claude API.

    Args:
        reply_text: the reply snippet to classify
        api_key: Anthropic API key to use for classification

    Returns:
        (classification, confidence) tuple
    """
    if not api_key:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
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
                "x-api-key": api_key,
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
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError):
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
    user_id: int,
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
                    classification, confidence, user_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                user_id,
            ),
        )
        row = cur.fetchone()
        return row["id"] if row else None
