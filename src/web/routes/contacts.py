"""Contact API routes — list, detail, timeline, status transitions."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.models.campaigns import (
    get_campaign_by_name,
    get_contact_campaign_status,
    log_event,
)
from src.services.phone_utils import normalize_phone
from src.services.state_machine import InvalidTransition, transition_contact
from src.web.dependencies import get_db

router = APIRouter(tags=["contacts"])


class StatusTransitionRequest(BaseModel):
    campaign: str = "Q1_2026_initial"
    new_status: str  # replied_positive | replied_negative | no_response | bounced
    note: Optional[str] = None


class ResponseNoteRequest(BaseModel):
    campaign: Optional[str] = None
    note_type: str = "general"
    content: str


class PhoneUpdateRequest(BaseModel):
    phone_number: str


@router.get("/contacts")
def list_contacts(
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
    conn=Depends(get_db),
):
    """List contacts with optional search."""
    offset = (page - 1) * per_page
    cur = conn.cursor()

    if search:
        query = """
        SELECT c.*, co.name AS company_name, co.aum_millions
        FROM contacts c
        LEFT JOIN companies co ON co.id = c.company_id
        WHERE c.full_name LIKE %s OR c.email LIKE %s
           OR co.name LIKE %s OR c.first_name LIKE %s OR c.last_name LIKE %s
        ORDER BY co.aum_millions DESC NULLS LAST
        LIMIT %s OFFSET %s
        """
        like = f"%{search}%"
        cur.execute(query, (like, like, like, like, like, per_page, offset))
        rows = cur.fetchall()

        count_query = """
        SELECT COUNT(*) AS cnt FROM contacts c
        LEFT JOIN companies co ON co.id = c.company_id
        WHERE c.full_name LIKE %s OR c.email LIKE %s
           OR co.name LIKE %s OR c.first_name LIKE %s OR c.last_name LIKE %s
        """
        cur.execute(count_query, (like, like, like, like, like))
        total = cur.fetchone()["cnt"]
    else:
        query = """
        SELECT c.*, co.name AS company_name, co.aum_millions
        FROM contacts c
        LEFT JOIN companies co ON co.id = c.company_id
        ORDER BY co.aum_millions DESC NULLS LAST
        LIMIT %s OFFSET %s
        """
        cur.execute(query, (per_page, offset))
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) AS cnt FROM contacts")
        total = cur.fetchone()["cnt"]

    return {
        "contacts": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/contacts/{contact_id}")
def get_contact(
    contact_id: int,
    conn=Depends(get_db),
):
    """Get contact detail with company info and campaign enrollments."""
    cur = conn.cursor()
    cur.execute(
        """SELECT c.*, co.name AS company_name, co.aum_millions,
                  co.firm_type, co.country, co.website, co.is_gdpr AS company_is_gdpr
           FROM contacts c
           LEFT JOIN companies co ON co.id = c.company_id
           WHERE c.id = %s""",
        (contact_id,),
    )
    contact = cur.fetchone()

    if not contact:
        raise HTTPException(404, f"Contact {contact_id} not found")

    # Get campaign enrollments
    cur.execute(
        """SELECT ccs.*, cam.name AS campaign_name
           FROM contact_campaign_status ccs
           JOIN campaigns cam ON cam.id = ccs.campaign_id
           WHERE ccs.contact_id = %s
           ORDER BY ccs.id DESC""",
        (contact_id,),
    )
    enrollments = cur.fetchall()

    # Get response notes
    cur.execute(
        "SELECT * FROM response_notes WHERE contact_id = %s ORDER BY created_at DESC",
        (contact_id,),
    )
    notes = cur.fetchall()

    return {
        "contact": dict(contact),
        "enrollments": [dict(e) for e in enrollments],
        "notes": [dict(n) for n in notes],
    }


@router.get("/contacts/{contact_id}/events")
def get_contact_events(
    contact_id: int,
    conn=Depends(get_db),
):
    """Get the event timeline for a contact."""
    cur = conn.cursor()
    cur.execute(
        """SELECT e.*, t.name AS template_name
           FROM events e
           LEFT JOIN templates t ON t.id = e.template_id
           WHERE e.contact_id = %s
           ORDER BY e.created_at DESC""",
        (contact_id,),
    )
    events = cur.fetchall()

    return [dict(e) for e in events]


@router.post("/contacts/{contact_id}/status")
def update_contact_status(
    contact_id: int,
    body: StatusTransitionRequest,
    conn=Depends(get_db),
):
    """Log a response outcome and transition contact status."""
    camp = get_campaign_by_name(conn, body.campaign)
    if not camp:
        raise HTTPException(404, f"Campaign '{body.campaign}' not found")

    campaign_id = camp["id"]

    # Verify contact exists
    cur = conn.cursor()
    cur.execute(
        "SELECT id, full_name, email FROM contacts WHERE id = %s",
        (contact_id,),
    )
    contact = cur.fetchone()
    if not contact:
        raise HTTPException(404, f"Contact {contact_id} not found")

    # Check enrollment
    ccs = get_contact_campaign_status(conn, contact_id, campaign_id)
    if ccs is None:
        raise HTTPException(400, f"Contact {contact_id} not enrolled in campaign")

    # Auto-advance from queued to in_progress if needed
    if ccs["status"] == "queued":
        try:
            transition_contact(conn, contact_id, campaign_id, "in_progress")
        except InvalidTransition as e:
            raise HTTPException(400, str(e))

    # Apply the transition
    try:
        new_status = transition_contact(conn, contact_id, campaign_id, body.new_status)
    except InvalidTransition as e:
        raise HTTPException(400, str(e))

    # Log call_booked event if applicable
    if body.new_status == "replied_positive" and body.note and "call" in body.note.lower():
        log_event(
            conn, contact_id, "call_booked",
            campaign_id=campaign_id,
            metadata=json.dumps({"note": body.note}),
        )

    # Save response note if provided
    if body.note:
        cur.execute(
            """INSERT INTO response_notes (contact_id, campaign_id, note_type, content)
               VALUES (%s, %s, %s, %s)""",
            (contact_id, campaign_id, body.new_status, body.note),
        )
        conn.commit()

    return {
        "success": True,
        "contact_id": contact_id,
        "new_status": new_status,
    }


@router.post("/contacts/{contact_id}/notes")
def add_response_note(
    contact_id: int,
    body: ResponseNoteRequest,
    conn=Depends(get_db),
):
    """Add a response note to a contact."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM contacts WHERE id = %s", (contact_id,),
    )
    contact = cur.fetchone()
    if not contact:
        raise HTTPException(404, f"Contact {contact_id} not found")

    campaign_id = None
    if body.campaign:
        camp = get_campaign_by_name(conn, body.campaign)
        if camp:
            campaign_id = camp["id"]

    cur.execute(
        """INSERT INTO response_notes (contact_id, campaign_id, note_type, content)
           VALUES (%s, %s, %s, %s)""",
        (contact_id, campaign_id, body.note_type, body.content),
    )
    conn.commit()

    return {"success": True}


@router.post("/contacts/{contact_id}/phone")
def update_phone(
    contact_id: int,
    body: PhoneUpdateRequest,
    conn=Depends(get_db),
):
    """Add or update a contact's phone number with E.164 normalization."""
    cur = conn.cursor()
    cur.execute("SELECT id FROM contacts WHERE id = %s", (contact_id,))
    if not cur.fetchone():
        raise HTTPException(404, f"Contact {contact_id} not found")

    normalized = normalize_phone(body.phone_number)
    if not normalized:
        raise HTTPException(400, "Invalid phone number format")

    cur.execute(
        "UPDATE contacts SET phone_number = %s, phone_normalized = %s WHERE id = %s",
        (body.phone_number, normalized, contact_id),
    )
    conn.commit()

    return {
        "success": True,
        "contact_id": contact_id,
        "phone_number": body.phone_number,
        "phone_normalized": normalized,
    }
