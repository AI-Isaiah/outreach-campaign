"""Gmail OAuth and draft API routes."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from src.config import load_config
from src.models.campaigns import get_campaign_by_name, log_event, update_contact_campaign_status
from src.services.email_sender import render_campaign_email
from src.services.gmail_drafter import GmailDrafter
from src.web.dependencies import get_db

router = APIRouter(prefix="/gmail", tags=["gmail"])

_drafter = GmailDrafter()


class DraftRequest(BaseModel):
    contact_id: int
    campaign: str = "Q1_2026_initial"
    template_id: int
    subject: Optional[str] = None  # override rendered subject
    body_text: Optional[str] = None  # override rendered body


class BatchDraftRequest(BaseModel):
    campaign: str = "Q1_2026_initial"
    date: Optional[str] = None
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
        return RedirectResponse(url="http://localhost:5173/settings?gmail=connected")
    except Exception as e:
        raise HTTPException(400, f"OAuth failed: {e}")


@router.post("/drafts")
def create_draft(
    body: DraftRequest,
    conn=Depends(get_db),
):
    """Push a single email to Gmail as a draft."""
    if not _drafter.is_authorized():
        raise HTTPException(401, "Gmail not authorized. Connect Gmail first.")

    camp = get_campaign_by_name(conn, body.campaign)
    if not camp:
        raise HTTPException(404, f"Campaign '{body.campaign}' not found")

    campaign_id = camp["id"]

    try:
        config = load_config()
    except FileNotFoundError:
        config = {}

    # Use overrides or render from template
    if body.body_text and body.subject:
        subject = body.subject
        body_text = body.body_text
        body_html = None
        cur = conn.cursor()
        cur.execute(
            "SELECT email FROM contacts WHERE id = %s", (body.contact_id,),
        )
        contact = cur.fetchone()
        if not contact:
            raise HTTPException(404, f"Contact {body.contact_id} not found")
        to_email = contact["email"]
    else:
        rendered = render_campaign_email(
            conn, body.contact_id, campaign_id, body.template_id, config
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
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO gmail_drafts (contact_id, campaign_id, gmail_draft_id, subject, to_email)
           VALUES (%s, %s, %s, %s, %s)""",
        (body.contact_id, campaign_id, draft_id, subject, to_email),
    )
    conn.commit()

    return {
        "success": True,
        "draft_id": draft_id,
        "to_email": to_email,
        "subject": subject,
    }


@router.post("/drafts/batch")
def create_batch_drafts(
    body: BatchDraftRequest,
    conn=Depends(get_db),
):
    """Push all today's email queue items to Gmail as drafts."""
    if not _drafter.is_authorized():
        raise HTTPException(401, "Gmail not authorized. Connect Gmail first.")

    camp = get_campaign_by_name(conn, body.campaign)
    if not camp:
        raise HTTPException(404, f"Campaign '{body.campaign}' not found")

    campaign_id = camp["id"]

    try:
        config = load_config()
    except FileNotFoundError:
        config = {}

    from src.services.priority_queue import get_daily_queue
    items = get_daily_queue(conn, campaign_id, target_date=body.date, limit=body.limit)
    email_items = [i for i in items if i["channel"] == "email"]

    results = []
    for item in email_items:
        # Skip if draft already exists
        cur = conn.cursor()
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
            conn, item["contact_id"], campaign_id, item["template_id"], config
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
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO gmail_drafts
                   (contact_id, campaign_id, gmail_draft_id, subject, to_email)
                   VALUES (%s, %s, %s, %s, %s)""",
                (item["contact_id"], campaign_id, draft_id, rendered["subject"], rendered["contact_email"]),
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
    campaign: str = "Q1_2026_initial",
    conn=Depends(get_db),
):
    """Check the status of a contact's Gmail draft."""
    camp = get_campaign_by_name(conn, campaign)
    if not camp:
        raise HTTPException(404, f"Campaign '{campaign}' not found")

    cur = conn.cursor()
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

                # Log the email_sent event and advance step
                log_event(
                    conn, contact_id, "email_sent",
                    campaign_id=camp["id"],
                    metadata=json.dumps({"source": "gmail", "subject": draft_row["subject"]}),
                )

                # Advance step
                cur.execute(
                    """SELECT current_step FROM contact_campaign_status
                       WHERE contact_id = %s AND campaign_id = %s""",
                    (contact_id, camp["id"]),
                )
                status_row = cur.fetchone()
                if status_row:
                    update_contact_campaign_status(
                        conn, contact_id, camp["id"],
                        current_step=status_row["current_step"] + 1,
                    )

                return {"status": "sent", "draft_id": draft_row["gmail_draft_id"]}
        except Exception:
            pass  # Can't reach Gmail API — return DB status

    return {
        "status": draft_row["status"],
        "draft_id": draft_row["gmail_draft_id"],
        "subject": draft_row["subject"],
        "created_at": draft_row["created_at"],
    }
