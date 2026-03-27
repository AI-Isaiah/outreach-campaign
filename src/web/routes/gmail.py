"""Gmail OAuth and draft API routes."""

from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

_FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

_limiter = Limiter(key_func=get_remote_address)

from src.config import DEFAULT_CAMPAIGN, load_config_safe
from src.enums import EventType
from src.models.campaigns import get_campaign_by_name
from src.models.enrollment import get_sequence_steps, record_template_usage
from src.services.sequence_utils import advance_to_next_step
from src.models.events import log_event
from src.services.email_sender import render_campaign_email
from src.services.gmail_drafter import GmailDrafter
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

router = APIRouter(prefix="/gmail", tags=["gmail"])

_drafter = GmailDrafter()


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
def gmail_status():
    """Check if Gmail is authorized."""
    return {"authorized": _drafter.is_authorized()}


@router.post("/authorize")
def gmail_authorize():
    """Start OAuth flow — returns the URL the user should visit."""
    try:
        url = _drafter.get_authorization_url()
        return {"authorization_url": url}
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))


@router.get("/callback")
def gmail_callback(code: str = Query(...)):
    """Handle OAuth callback from Google."""
    try:
        _drafter.handle_callback(code)
        return RedirectResponse(url=f"{_FRONTEND_URL}/settings?gmail=connected")
    except Exception as e:
        raise HTTPException(400, f"OAuth failed: {e}")


@router.post("/drafts")
@_limiter.limit("10/minute")
def create_draft(
    request: Request,
    body: DraftRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Push a single email to Gmail as a draft."""
    if not _drafter.is_authorized():
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
        draft_id = _drafter.create_draft(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
    except Exception as e:
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
    if not _drafter.is_authorized():
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
    items = get_daily_queue(conn, campaign_id, target_date=body.date, limit=body.limit)
    email_items = [i for i in items if i["channel"] == "email"]

    results = []
    for item in email_items:
        # Skip if draft already exists
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT id FROM gmail_drafts
                   WHERE contact_id = %s AND campaign_id = %s AND status = 'drafted'""",
                (item["contact_id"], campaign_id),
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
            draft_id = _drafter.create_draft(
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
        except Exception as e:
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

    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT * FROM gmail_drafts
               WHERE contact_id = %s AND campaign_id = %s
               ORDER BY id DESC LIMIT 1""",
            (contact_id, camp["id"]),
        )
        draft_row = cur.fetchone()

        if not draft_row:
            return {"status": "no_draft"}

        # If status is 'drafted', check with Gmail API
        if draft_row["status"] == "drafted" and _drafter.is_authorized():
            try:
                gmail_status = _drafter.check_draft_status(draft_row["gmail_draft_id"])
                if gmail_status == "sent":
                    # Draft was sent — update our records
                    cur.execute(
                        "UPDATE gmail_drafts SET status = 'sent', updated_at = NOW() WHERE id = %s",
                        (draft_row["id"],),
                    )
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
            except Exception:
                pass  # Can't reach Gmail API — return DB status

        return {
            "status": draft_row["status"],
            "draft_id": draft_row["gmail_draft_id"],
            "subject": draft_row["subject"],
            "created_at": draft_row["created_at"],
        }
