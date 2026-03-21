"""Pending replies API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.services.linkedin_acceptance_scanner import scan_linkedin_acceptances
from src.services.reply_detector import scan_gmail_for_replies
from src.services.state_machine import InvalidTransition, transition_contact
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

router = APIRouter(tags=["replies"])


class ConfirmReplyRequest(BaseModel):
    outcome: str = Field(max_length=50)
    note: Optional[str] = Field(default=None, max_length=5000)


@router.get("/replies/pending")
def list_pending_replies(
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """List unconfirmed pending replies with contact/company info."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT pr.*,
                      c.full_name AS contact_name, c.email AS contact_email,
                      co.name AS company_name, co.aum_millions
               FROM pending_replies pr
               JOIN contacts c ON c.id = pr.contact_id
               JOIN companies co ON co.id = c.company_id
               WHERE pr.confirmed = false AND co.user_id = %s
               ORDER BY pr.detected_at DESC""",
            (user["id"],),
        )
        return [dict(r) for r in cur.fetchall()]


@router.post("/replies/{reply_id}/confirm")
def confirm_reply(
    reply_id: int,
    body: ConfirmReplyRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Confirm or correct a pending reply classification."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT pr.* FROM pending_replies pr
               JOIN contacts c ON c.id = pr.contact_id
               JOIN companies co ON co.id = c.company_id
               WHERE pr.id = %s AND co.user_id = %s""",
            (reply_id, user["id"]),
        )
        reply = cur.fetchone()
        if not reply:
            raise HTTPException(404, f"Reply {reply_id} not found")

        if reply["confirmed"]:
            raise HTTPException(400, "Reply already confirmed")

        # Update the reply record
        cur.execute(
            """UPDATE pending_replies
               SET confirmed = true, confirmed_outcome = %s, confirmed_at = NOW()
               WHERE id = %s""",
            (body.outcome, reply_id),
        )

        # Trigger state machine transition if positive or negative
        status_map = {
            "replied_positive": "replied_positive",
            "replied_negative": "replied_negative",
        }
        if body.outcome in status_map and reply["campaign_id"]:
            try:
                transition_contact(
                    conn, reply["contact_id"], reply["campaign_id"],
                    status_map[body.outcome],
                )
            except InvalidTransition:
                pass  # Contact may already be in this state

        # Save note if provided
        if body.note and reply["campaign_id"]:
            cur.execute(
                """INSERT INTO response_notes (contact_id, campaign_id, note_type, content)
                   VALUES (%s, %s, %s, %s)""",
                (reply["contact_id"], reply["campaign_id"], body.outcome, body.note),
            )

        conn.commit()

        return {"success": True, "reply_id": reply_id, "outcome": body.outcome}


@router.post("/replies/scan")
def trigger_reply_scan(
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Scan Gmail inbox for replies from enrolled contacts."""
    try:
        result = scan_gmail_for_replies(conn)
        return {"status": "ok", **result}
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/replies/scan-linkedin")
def trigger_linkedin_scan(
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Scan Gmail for LinkedIn connection acceptance notifications.

    Searches for emails from LinkedIn indicating someone accepted
    a connection request. Matches to contacts and auto-advances
    their campaign sequence from linkedin_connect to the next step.
    """
    try:
        result = scan_linkedin_acceptances(conn)
        return {"status": "ok", **result}
    except RuntimeError as e:
        raise HTTPException(400, str(e))
