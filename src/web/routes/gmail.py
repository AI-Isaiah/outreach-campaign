"""Gmail OAuth and email draft API routes.

Creates actual email drafts in the user's Gmail account via OAuth.
Separate from drafts.py which handles campaign wizard form persistence.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

_limiter = Limiter(key_func=get_remote_address)

from googleapiclient.errors import HttpError

from src.config import DEFAULT_CAMPAIGN, load_config_safe
from src.enums import EventType
from src.models.enrollment import get_sequence_steps, record_template_usage
from src.services.sequence_utils import advance_to_next_step
from src.models.events import log_event
from src.services.email_sender import render_campaign_email
from cryptography.fernet import InvalidToken

from src.services.gmail_drafter import GmailDrafter
from src.services.token_encryption import decrypt_token
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail", tags=["gmail"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")


def _get_user_drafter(conn, user_id: int) -> GmailDrafter | None:
    """Load Gmail OAuth tokens from DB and return a GmailDrafter, or None."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT gmail_access_token, gmail_refresh_token, gmail_connected
               FROM users WHERE id = %s""",
            (user_id,),
        )
        row = cur.fetchone()

    if not row or not row["gmail_connected"] or not row["gmail_access_token"]:
        return None

    try:
        access_token = decrypt_token(row["gmail_access_token"])
        refresh_token = decrypt_token(row["gmail_refresh_token"]) if row["gmail_refresh_token"] else ""
    except (InvalidToken, ValueError):
        logger.exception("Failed to decrypt Gmail tokens for user %s", user_id)
        return None

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        logger.warning("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set")
        return None

    return GmailDrafter.from_db_tokens(
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )


class DraftRequest(BaseModel):
    contact_id: int
    campaign: str = Field(default=DEFAULT_CAMPAIGN, max_length=200)
    template_id: int | None = None  # Optional for AI template steps with no reference
    step_order: int | None = None
    subject: Optional[str] = Field(default=None, max_length=200)
    body_text: Optional[str] = Field(default=None, max_length=5000)


class BatchDraftRequest(BaseModel):
    campaign: str = Field(default=DEFAULT_CAMPAIGN, max_length=200)
    date: Optional[str] = Field(default=None, max_length=50)
    limit: int = 20


@router.get("/status")
def gmail_status(
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Check if Gmail is authorized for the current user."""
    drafter = _get_user_drafter(conn, user["id"])
    return {"authorized": drafter is not None and drafter.is_authorized()}


@router.post("/authorize")
def gmail_authorize(
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Start OAuth flow — redirects to the DB-backed /auth/gmail/connect flow."""
    # Delegate to the DB-backed OAuth flow in gmail_oauth.py
    from src.web.routes.gmail_oauth import GOOGLE_REDIRECT_URI, SCOPES as OAUTH_SCOPES
    import secrets as _secrets
    import hashlib
    from datetime import datetime, timedelta, timezone

    if not GOOGLE_CLIENT_ID:
        raise HTTPException(500, "Google OAuth not configured (GOOGLE_CLIENT_ID missing)")

    state = _secrets.token_urlsafe(32)
    code_verifier = _secrets.token_urlsafe(43)
    code_challenge = hashlib.sha256(code_verifier.encode()).hexdigest()

    with get_cursor(conn) as cur:
        cur.execute("DELETE FROM oauth_states WHERE expires_at < NOW()")
        cur.execute("DELETE FROM oauth_states WHERE user_id = %s", (user["id"],))
        cur.execute(
            "INSERT INTO oauth_states (state, user_id, expires_at, code_challenge) VALUES (%s, %s, %s, %s)",
            (state, user["id"], datetime.now(timezone.utc) + timedelta(minutes=10), code_challenge),
        )
        conn.commit()

    from urllib.parse import urlencode
    params = urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": OAUTH_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    authorization_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    return {"authorization_url": authorization_url}


@router.post("/drafts")
@_limiter.limit("10/minute")
def create_draft(
    request: Request,
    body: DraftRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Push a single email to Gmail as a draft."""
    drafter = _get_user_drafter(conn, user["id"])
    if not drafter or not drafter.is_authorized():
        raise HTTPException(401, "Gmail not authorized. Connect Gmail first.")

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM campaigns WHERE name = %s AND user_id = %s",
            (body.campaign, user["id"]),
        )
        camp = cur.fetchone()
    if not camp:
        raise HTTPException(404, f"Campaign '{body.campaign}' not found")

    campaign_id = camp["id"]

    config = load_config_safe()

    # Use overrides or render from template
    if body.body_text and body.subject:
        subject = body.subject
        body_text = body.body_text
        body_html = None
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT c.email FROM contacts c
                   JOIN companies co ON co.id = c.company_id
                   WHERE c.id = %s AND co.user_id = %s""",
                (body.contact_id, user["id"]),
            )
            contact = cur.fetchone()
            if not contact:
                raise HTTPException(404, f"Contact {body.contact_id} not found")
            to_email = contact["email"]
    else:
        rendered = render_campaign_email(
            conn, body.contact_id, campaign_id, body.template_id, config,
            user_id=user["id"],
        )
        if not rendered:
            raise HTTPException(400, "Could not render email (check contact eligibility)")
        subject = body.subject or rendered["subject"]
        body_text = body.body_text or rendered["body_text"]
        body_html = rendered["body_html"] if not body.body_text else None
        to_email = rendered["contact_email"]

    # Create the Gmail draft
    try:
        draft_id = drafter.create_draft(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
    except (HttpError, RuntimeError, OSError) as e:
        logger.error("Failed to create Gmail draft: %s", e)
        raise HTTPException(500, f"Failed to create Gmail draft: {e}")

    # Store in DB
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO gmail_drafts (contact_id, campaign_id, gmail_draft_id, subject, to_email, template_id, user_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (body.contact_id, campaign_id, draft_id, subject, to_email, body.template_id, user["id"]),
        )
        conn.commit()

        return {
            "success": True,
            "draft_id": draft_id,
            "to_email": to_email,
            "subject": subject,
        }


@router.post("/drafts/batch")
@_limiter.limit("3/minute")
def create_batch_drafts(
    request: Request,
    body: BatchDraftRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Push all today's email queue items to Gmail as drafts."""
    drafter = _get_user_drafter(conn, user["id"])
    if not drafter or not drafter.is_authorized():
        raise HTTPException(401, "Gmail not authorized. Connect Gmail first.")

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM campaigns WHERE name = %s AND user_id = %s",
            (body.campaign, user["id"]),
        )
        camp = cur.fetchone()
    if not camp:
        raise HTTPException(404, f"Campaign '{body.campaign}' not found")

    campaign_id = camp["id"]

    config = load_config_safe()

    from src.services.priority_queue import get_daily_queue
    items = get_daily_queue(conn, campaign_id, target_date=body.date, limit=body.limit, user_id=user["id"])
    email_items = [i for i in items if i["channel"] == "email"]

    results = []
    for item in email_items:
        # Skip if draft already exists
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT id FROM gmail_drafts
                   WHERE contact_id = %s AND campaign_id = %s AND status = 'drafted' AND user_id = %s""",
                (item["contact_id"], campaign_id, user["id"]),
            )
            existing = cur.fetchone()
        if existing:
            results.append({
                "contact_id": item["contact_id"],
                "skipped": True,
                "reason": "draft already exists",
            })
            continue

        rendered = render_campaign_email(
            conn, item["contact_id"], campaign_id, item["template_id"], config,
            user_id=user["id"],
        )
        if not rendered:
            results.append({
                "contact_id": item["contact_id"],
                "success": False,
                "error": "Could not render email",
            })
            continue

        try:
            draft_id = drafter.create_draft(
                to_email=rendered["contact_email"],
                subject=rendered["subject"],
                body_text=rendered["body_text"],
                body_html=rendered["body_html"],
            )
            with get_cursor(conn) as cur:
                cur.execute(
                    """INSERT INTO gmail_drafts
                       (contact_id, campaign_id, gmail_draft_id, subject, to_email, template_id, user_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (item["contact_id"], campaign_id, draft_id, rendered["subject"], rendered["contact_email"], item.get("template_id"), user["id"]),
                )
                conn.commit()
            results.append({
                "contact_id": item["contact_id"],
                "success": True,
                "draft_id": draft_id,
            })
        except (HttpError, RuntimeError, OSError) as e:
            logger.error("Batch draft creation failed for contact %d: %s", item["contact_id"], e)
            results.append({
                "contact_id": item["contact_id"],
                "success": False,
                "error": str(e),
            })

    return {
        "total": len(email_items),
        "results": results,
    }


@router.get("/drafts/{contact_id}")
def check_draft_status(
    contact_id: int,
    campaign: str = DEFAULT_CAMPAIGN,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Check the status of a contact's Gmail draft."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM campaigns WHERE name = %s AND user_id = %s",
            (campaign, user["id"]),
        )
        camp = cur.fetchone()
    if not camp:
        raise HTTPException(404, f"Campaign '{campaign}' not found")

    drafter = _get_user_drafter(conn, user["id"])

    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT * FROM gmail_drafts
               WHERE contact_id = %s AND campaign_id = %s AND user_id = %s
               ORDER BY id DESC LIMIT 1""",
            (contact_id, camp["id"], user["id"]),
        )
        draft_row = cur.fetchone()

        if not draft_row:
            return {"status": "no_draft"}

        # If status is 'drafted', check with Gmail API
        if draft_row["status"] == "drafted" and drafter and drafter.is_authorized():
            try:
                gmail_status = drafter.check_draft_status(draft_row["gmail_draft_id"])
                if gmail_status == "sent":
                    # Draft was sent — atomically update only if still 'drafted'
                    cur.execute(
                        "UPDATE gmail_drafts SET status = 'sent', updated_at = NOW() WHERE id = %s AND status = 'drafted'",
                        (draft_row["id"],),
                    )
                    if cur.rowcount == 0:
                        # Already processed by a concurrent request
                        conn.rollback()
                        return dict(draft_row) | {"status": "sent"}
                    conn.commit()

                    log_event(
                        conn, contact_id, EventType.EMAIL_SENT,
                        campaign_id=camp["id"],
                        template_id=draft_row.get("template_id"),
                        metadata=json.dumps({"source": "gmail", "subject": draft_row["subject"]}),
                        user_id=user["id"],
                    )

                    if draft_row.get("template_id"):
                        record_template_usage(
                            conn, contact_id, camp["id"],
                            draft_row["template_id"], channel="email",
                            user_id=user["id"],
                        )

                    # Advance to next step (sets next_action_date, clears approval state)
                    steps = get_sequence_steps(conn, camp["id"], user_id=user["id"])
                    cur.execute(
                        "SELECT current_step FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
                        (contact_id, camp["id"]),
                    )
                    status_row = cur.fetchone()
                    if status_row:
                        advance_to_next_step(
                            conn, contact_id, camp["id"],
                            status_row["current_step"], steps,
                            user_id=user["id"],
                        )

                    conn.commit()
                    return {"status": "sent", "draft_id": draft_row["gmail_draft_id"]}
            except (HttpError, RuntimeError, OSError) as exc:
                logger.error("Gmail API check failed for draft %s: %s", draft_row["gmail_draft_id"], exc)

        return {
            "status": draft_row["status"],
            "draft_id": draft_row["gmail_draft_id"],
            "subject": draft_row["subject"],
            "created_at": draft_row["created_at"],
        }
