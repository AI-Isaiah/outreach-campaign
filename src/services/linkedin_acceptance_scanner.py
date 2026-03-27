"""LinkedIn connection acceptance scanner via Gmail.

Scans Gmail for LinkedIn notification emails that indicate a contact
has accepted a connection request. Matches the name/profile URL from
the email to enrolled contacts, logs the event, and advances the
campaign sequence automatically.

LinkedIn sends emails with subjects like:
- "<Name> accepted your invitation"
- "<Name> accepted your invitation to connect"
- "You and <Name> are now connected"
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from src.enums import ContactStatus
from src.services.gmail_drafter import GmailDrafter
from src.services.normalization_utils import normalize_linkedin_url
from src.models.database import get_cursor

logger = logging.getLogger(__name__)

# LinkedIn notification sender
LINKEDIN_SENDERS = [
    "invitations@linkedin.com",
    "notifications-noreply@linkedin.com",
    "messages-noreply@linkedin.com",
]

# Patterns matching LinkedIn acceptance notification subjects
ACCEPTANCE_SUBJECT_PATTERNS = [
    re.compile(r"(.+?)\s+accepted your invitation", re.IGNORECASE),
    re.compile(r"you and\s+(.+?)\s+are now connected", re.IGNORECASE),
    re.compile(r"(.+?)\s+accepted your connection request", re.IGNORECASE),
]

# Pattern to extract LinkedIn profile URLs from email body
PROFILE_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/([a-zA-Z0-9\-]+)",
    re.IGNORECASE,
)


def _normalize_name(name: str) -> str:
    """Normalize a name for fuzzy matching."""
    return re.sub(r"[^a-z\s]", "", name.lower()).strip()


def _extract_profile_url(body: str) -> Optional[str]:
    """Extract a LinkedIn profile URL from email body text."""
    match = PROFILE_URL_PATTERN.search(body)
    if match:
        slug = match.group(1)
        return f"https://www.linkedin.com/in/{slug.lower()}"
    return None


def _extract_accepted_name(subject: str) -> Optional[str]:
    """Extract the name of the person who accepted from the subject line."""
    for pattern in ACCEPTANCE_SUBJECT_PATTERNS:
        match = pattern.search(subject)
        if match:
            name = match.group(1).strip()
            # Clean up common artifacts
            name = re.sub(r"\s+", " ", name)
            return name
    return None


def _get_email_body_text(payload: dict) -> str:
    """Extract plain text body from Gmail message payload."""
    import base64

    body_text = ""

    # Direct body
    if payload.get("body", {}).get("data"):
        body_text = base64.urlsafe_b64decode(
            payload["body"]["data"]
        ).decode("utf-8", errors="replace")
        return body_text

    # Multipart — find text/plain or text/html
    for part in payload.get("parts", []):
        mime = part.get("mimeType", "")
        if mime == "text/plain" and part.get("body", {}).get("data"):
            body_text = base64.urlsafe_b64decode(
                part["body"]["data"]
            ).decode("utf-8", errors="replace")
            return body_text
        if mime == "text/html" and part.get("body", {}).get("data"):
            body_text = base64.urlsafe_b64decode(
                part["body"]["data"]
            ).decode("utf-8", errors="replace")
            # Strip HTML tags for URL extraction
            body_text = re.sub(r"<[^>]+>", " ", body_text)

        # Recurse into nested multipart
        if part.get("parts"):
            nested = _get_email_body_text(part)
            if nested:
                return nested

    return body_text


def _find_contact_by_profile_url(conn, profile_url: str, *, user_id: int) -> Optional[dict]:
    """Find a contact by normalized LinkedIn URL."""
    normalized = normalize_linkedin_url(profile_url)
    if not normalized:
        return None

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id, first_name, last_name FROM contacts WHERE linkedin_url_normalized = %s AND user_id = %s",
            (normalized, user_id),
        )
        return cur.fetchone()


def _find_contact_by_name(conn, full_name: str, *, user_id: int) -> Optional[dict]:
    """Find a contact by name match.

    Uses name_normalized for matching. Falls back to first_name + last_name
    comparison if normalized field isn't populated.
    """
    normalized = _normalize_name(full_name)
    if not normalized:
        return None

    with get_cursor(conn) as cur:
        # Try exact normalized match first
        cur.execute(
            "SELECT id, first_name, last_name FROM contacts WHERE name_normalized = %s AND user_id = %s",
            (normalized, user_id),
        )
        row = cur.fetchone()
        if row:
            return row

        # Split into first/last and try matching
        parts = normalized.split()
        if len(parts) >= 2:
            first = parts[0]
            last = parts[-1]
            cur.execute(
                """SELECT id, first_name, last_name FROM contacts
                   WHERE LOWER(first_name) = %s AND LOWER(last_name) = %s AND user_id = %s""",
                (first, last, user_id),
            )
            row = cur.fetchone()
            if row:
                return row

        return None


def scan_linkedin_acceptances(
    conn,
    drafter: GmailDrafter | None = None,
    days_back: int = 7,
    *,
    user_id: int,
) -> dict:
    """Scan Gmail for LinkedIn connection acceptance notifications.

    Searches for emails from LinkedIn that indicate someone accepted
    a connection request. Matches the accepted person to contacts in
    the database and advances their campaign sequence.

    Args:
        conn: PostgreSQL connection
        drafter: optional GmailDrafter instance (created if not provided)
        days_back: how many days back to search (default: 7)

    Returns:
        dict with keys: scanned, matched, advanced, already_processed, errors, details
    """
    from src.models.enrollment import (
        get_contact_campaign_status,
        get_sequence_steps,
        update_contact_campaign_status,
    )
    from src.models.events import log_event

    stats = {
        "scanned": 0,
        "matched": 0,
        "advanced": 0,
        "already_processed": 0,
        "errors": 0,
        "details": [],
    }

    if drafter is None:
        drafter = GmailDrafter()

    try:
        service = drafter._get_service()
    except Exception as e:
        logger.error("Failed to get Gmail service: %s", e)
        stats["errors"] += 1
        return stats

    # Build the Gmail search query
    after_date = (date.today() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    query = f'from:(invitations@linkedin.com OR notifications-noreply@linkedin.com) subject:("accepted your invitation" OR "are now connected") after:{after_date}'

    try:
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=50)
            .execute()
        )
    except Exception as e:
        logger.exception("Gmail API search failed")
        stats["errors"] += 1
        return stats

    messages = results.get("messages", [])
    if not messages:
        return stats

    with get_cursor(conn) as cur:
        for msg_stub in messages:
            msg_id = msg_stub["id"]
            stats["scanned"] += 1

            # Check if we already processed this Gmail message
            cur.execute(
                """SELECT id FROM events
                   WHERE event_type = 'linkedin_acceptance_detected'
                     AND metadata LIKE %s""",
                (f"%{msg_id}%",),
            )
            if cur.fetchone():
                stats["already_processed"] += 1
                continue

            try:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="full")
                    .execute()
                )
            except Exception:
                logger.exception("Failed to fetch message %s", msg_id)
                stats["errors"] += 1
                continue

            # Extract headers
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            subject = headers.get("subject", "")
            from_addr = headers.get("from", "")

            # Verify sender is LinkedIn
            if not any(sender in from_addr.lower() for sender in LINKEDIN_SENDERS):
                continue

            # Extract the name from the subject
            accepted_name = _extract_accepted_name(subject)
            if not accepted_name:
                continue

            # Try to extract a profile URL from the body for more reliable matching
            body_text = _get_email_body_text(msg.get("payload", {}))
            profile_url = _extract_profile_url(body_text)

            # Match to a contact — prefer URL match, fall back to name
            contact = None
            match_method = None

            if profile_url:
                contact = _find_contact_by_profile_url(conn, profile_url, user_id=user_id)
                if contact:
                    match_method = "linkedin_url"

            if contact is None:
                contact = _find_contact_by_name(conn, accepted_name, user_id=user_id)
                if contact:
                    match_method = "name"

            if contact is None:
                logger.info(
                    "No contact match for LinkedIn acceptance: %s (url=%s)",
                    accepted_name,
                    profile_url,
                )
                continue

            contact_id = contact["id"]
            contact_display = f"{contact['first_name']} {contact['last_name']}"
            stats["matched"] += 1

            # Find all active campaign enrollments for this contact
            cur.execute(
                """SELECT ccs.campaign_id, ccs.current_step, ccs.status
                   FROM contact_campaign_status ccs
                   WHERE ccs.contact_id = %s AND ccs.status IN (%s, %s)""",
                (contact_id, ContactStatus.QUEUED, ContactStatus.IN_PROGRESS),
            )
            enrollments = cur.fetchall()

            if not enrollments:
                # Contact exists but not enrolled in any active campaign
                stats["details"].append({
                    "contact_id": contact_id,
                    "contact_name": contact_display,
                    "accepted_name": accepted_name,
                    "match_method": match_method,
                    "advanced": False,
                    "note": "not enrolled in active campaign",
                })
                continue

            advanced_any = False
            for enrollment in enrollments:
                campaign_id = enrollment["campaign_id"]
                current_step_order = enrollment["current_step"]

                steps = get_sequence_steps(conn, campaign_id, user_id=user_id)
                step_by_order = {s["step_order"]: s for s in steps}
                current_step = step_by_order.get(current_step_order)

                if (
                    current_step
                    and current_step["channel"] == "linkedin_connect"
                ):
                    # Advance to next step
                    next_step = None
                    for s in steps:
                        if s["step_order"] > current_step_order:
                            next_step = s
                            break

                    if next_step:
                        next_date = (
                            date.today() + timedelta(days=next_step["delay_days"])
                        ).isoformat()
                        update_contact_campaign_status(
                            conn,
                            contact_id,
                            campaign_id,
                            status="in_progress",
                            current_step=next_step["step_order"],
                            current_step_id=str(next_step["stable_id"]),
                            next_action_date=next_date,
                            user_id=user_id,
                        )
                    else:
                        update_contact_campaign_status(
                            conn,
                            contact_id,
                            campaign_id,
                            status="no_response",
                            user_id=user_id,
                        )

                    advanced_any = True

            # Log the event (once per contact, not per enrollment)
            campaign_for_log = enrollments[0]["campaign_id"] if enrollments else None
            log_event(
                conn,
                contact_id,
                "linkedin_acceptance_detected",
                campaign_id=campaign_for_log,
                user_id=user_id,
            )

            # Store gmail_message_id in the event metadata for dedup
            cur.execute(
                """UPDATE events SET metadata = %s
                   WHERE id = (
                       SELECT id FROM events
                       WHERE contact_id = %s AND event_type = 'linkedin_acceptance_detected'
                         AND metadata IS NULL
                       ORDER BY created_at DESC LIMIT 1
                   )""",
                (
                    json.dumps({
                        "gmail_message_id": msg_id,
                        "accepted_name": accepted_name,
                        "profile_url": profile_url,
                        "match_method": match_method,
                    }),
                    contact_id,
                ),
            )

            if advanced_any:
                stats["advanced"] += 1

            stats["details"].append({
                "contact_id": contact_id,
                "contact_name": contact_display,
                "accepted_name": accepted_name,
                "match_method": match_method,
                "advanced": advanced_any,
            })

        conn.commit()
    return stats
