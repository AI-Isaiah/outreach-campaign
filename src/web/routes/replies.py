"""Pending replies API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.services.state_machine import InvalidTransition, transition_contact
from src.web.dependencies import get_db

router = APIRouter(tags=["replies"])


class ConfirmReplyRequest(BaseModel):
    outcome: str  # replied_positive | replied_negative | neutral
    note: Optional[str] = None


@router.get("/replies/pending")
def list_pending_replies(
    conn=Depends(get_db),
):
    """List unconfirmed pending replies with contact/company info."""
    cur = conn.cursor()
    cur.execute(
        """SELECT pr.*,
                  c.full_name AS contact_name, c.email AS contact_email,
                  co.name AS company_name, co.aum_millions
           FROM pending_replies pr
           JOIN contacts c ON c.id = pr.contact_id
           LEFT JOIN companies co ON co.id = c.company_id
           WHERE pr.confirmed = 0
           ORDER BY pr.detected_at DESC"""
    )
    return [dict(r) for r in cur.fetchall()]


@router.post("/replies/{reply_id}/confirm")
def confirm_reply(
    reply_id: int,
    body: ConfirmReplyRequest,
    conn=Depends(get_db),
):
    """Confirm or correct a pending reply classification."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM pending_replies WHERE id = %s", (reply_id,))
    reply = cur.fetchone()
    if not reply:
        raise HTTPException(404, f"Reply {reply_id} not found")

    if reply["confirmed"]:
        raise HTTPException(400, "Reply already confirmed")

    # Update the reply record
    cur.execute(
        """UPDATE pending_replies
           SET confirmed = 1, confirmed_outcome = %s, confirmed_at = NOW()
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
):
    """Placeholder for Gmail reply scanning (implemented in Phase 4)."""
    return {
        "status": "not_implemented",
        "message": "Reply scanning will be available after Phase 4 implementation.",
    }
