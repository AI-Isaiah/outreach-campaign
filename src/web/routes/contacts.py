"""Contact API routes — list, detail, timeline, status transitions."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.application.contact_service import transition_contact_status
from src.models.campaigns import (
    get_campaign_by_name,
    get_contact_campaign_status,
    log_event,
)
from src.config import DEFAULT_CAMPAIGN
from src.enums import LifecycleStage
from src.services.normalization_utils import normalize_email as _normalize_email, normalize_linkedin_url as _normalize_linkedin
from src.services.phone_utils import normalize_phone
from src.services.state_machine import InvalidTransition
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

router = APIRouter(tags=["contacts"])


LIFECYCLE_STAGES = set(LifecycleStage)


class CreateContactRequest(BaseModel):
    first_name: str = Field(max_length=200)
    last_name: str = Field(max_length=200)
    email: Optional[str] = Field(default=None, max_length=254)
    phone_number: Optional[str] = Field(default=None, max_length=50)
    linkedin_url: Optional[str] = Field(default=None, max_length=2048)
    title: Optional[str] = Field(default=None, max_length=200)
    company_id: Optional[int] = None
    lifecycle_stage: str = Field(default="cold", max_length=50)
    newsletter_opt_in: bool = False
    notes: Optional[str] = Field(default=None, max_length=5000)


class LifecycleUpdateRequest(BaseModel):
    lifecycle_stage: str = Field(max_length=50)


class StatusTransitionRequest(BaseModel):
    campaign: str = Field(default=DEFAULT_CAMPAIGN, max_length=200)
    new_status: str = Field(max_length=50)
    note: Optional[str] = Field(default=None, max_length=5000)


class ResponseNoteRequest(BaseModel):
    campaign: Optional[str] = Field(default=None, max_length=200)
    note_type: str = Field(default="general", max_length=50)
    content: str = Field(max_length=5000)


class PhoneUpdateRequest(BaseModel):
    phone_number: str = Field(max_length=50)


class LinkedInUrlUpdateRequest(BaseModel):
    linkedin_url: str = Field(max_length=2048)


class NameUpdateRequest(BaseModel):
    first_name: str = Field(max_length=200)
    last_name: str = Field(max_length=200)


class BulkLifecycleRequest(BaseModel):
    contact_ids: list[int]
    lifecycle_stage: str = Field(max_length=50)


@router.post("/contacts")
def create_contact(
    body: CreateContactRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a new contact manually."""
    if body.lifecycle_stage not in LIFECYCLE_STAGES:
        raise HTTPException(400, f"Invalid lifecycle stage. Must be one of: {', '.join(sorted(LIFECYCLE_STAGES))}")

    with get_cursor(conn) as cur:
        # Validate company if provided
        if body.company_id is not None:
            cur.execute("SELECT id FROM companies WHERE id = %s AND user_id = %s", (body.company_id, user["id"]))
            if not cur.fetchone():
                raise HTTPException(404, f"Company {body.company_id} not found")

        full_name = f"{body.first_name} {body.last_name}"
        email_norm = _normalize_email(body.email) if body.email else None
        linkedin_norm = _normalize_linkedin(body.linkedin_url) if body.linkedin_url else None
        phone_norm = None
        if body.phone_number:
            phone_norm = normalize_phone(body.phone_number)

        # Check for duplicate email
        if email_norm:
            cur.execute("SELECT id FROM contacts WHERE email_normalized = %s AND user_id = %s", (email_norm, user["id"]))
            existing = cur.fetchone()
            if existing:
                raise HTTPException(409, f"Contact with email '{body.email}' already exists")

        newsletter_status = "subscribed" if body.newsletter_opt_in else "none"

        cur.execute(
            """INSERT INTO contacts (
                   first_name, last_name, full_name, email, email_normalized,
                   linkedin_url, linkedin_url_normalized, phone_number, phone_normalized,
                   title, company_id, source, lifecycle_stage, newsletter_status,
                   priority_rank, email_status, user_id
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'manual', %s, %s, 999, 'unverified', %s)
               RETURNING id""",
            (
                body.first_name, body.last_name, full_name,
                body.email, email_norm,
                body.linkedin_url, linkedin_norm,
                body.phone_number, phone_norm,
                body.title, body.company_id,
                body.lifecycle_stage, newsletter_status,
                user["id"],
            ),
        )
        contact_id = cur.fetchone()["id"]

        log_event(conn, contact_id, "contact_created", metadata='{"source": "manual"}', user_id=user["id"])

        # Add initial note if provided
        if body.notes:
            cur.execute(
                "INSERT INTO response_notes (contact_id, note_type, content) VALUES (%s, 'general', %s)",
                (contact_id, body.notes),
            )

        conn.commit()
        return {"id": contact_id, "success": True}


@router.patch("/contacts/{contact_id}/lifecycle")
def update_lifecycle_stage(
    contact_id: int,
    body: LifecycleUpdateRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update a contact's lifecycle stage."""
    if body.lifecycle_stage not in LIFECYCLE_STAGES:
        raise HTTPException(400, f"Invalid lifecycle stage. Must be one of: {', '.join(sorted(LIFECYCLE_STAGES))}")

    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.id, c.lifecycle_stage FROM contacts c
               WHERE c.id = %s AND c.user_id = %s""",
            (contact_id, user["id"]),
        )
        contact = cur.fetchone()
        if not contact:
            raise HTTPException(404, f"Contact {contact_id} not found")

        old_stage = contact["lifecycle_stage"]
        if old_stage == body.lifecycle_stage:
            return {"success": True, "lifecycle_stage": old_stage}

        cur.execute(
            "UPDATE contacts SET lifecycle_stage = %s WHERE id = %s",
            (body.lifecycle_stage, contact_id),
        )
        log_event(
            conn, contact_id, "lifecycle_changed",
            metadata=json.dumps({"from": old_stage, "to": body.lifecycle_stage}),
            user_id=user["id"],
        )
        conn.commit()
        return {"success": True, "lifecycle_stage": body.lifecycle_stage}


@router.get("/contacts")
def list_contacts(
    search: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """List contacts with optional search."""
    offset = (page - 1) * per_page
    with get_cursor(conn) as cur:
        if search:
            query = """
            SELECT c.*, co.name AS company_name, co.aum_millions
            FROM contacts c
            LEFT JOIN companies co ON co.id = c.company_id
            WHERE c.user_id = %s
              AND (c.full_name LIKE %s OR c.email LIKE %s
               OR co.name LIKE %s OR c.first_name LIKE %s OR c.last_name LIKE %s)
            ORDER BY co.aum_millions DESC NULLS LAST
            LIMIT %s OFFSET %s
            """
            like = f"%{search}%"
            cur.execute(query, (user["id"], like, like, like, like, like, per_page, offset))
            rows = cur.fetchall()

            count_query = """
            SELECT COUNT(*) AS cnt FROM contacts c
            LEFT JOIN companies co ON co.id = c.company_id
            WHERE c.user_id = %s
              AND (c.full_name LIKE %s OR c.email LIKE %s
               OR co.name LIKE %s OR c.first_name LIKE %s OR c.last_name LIKE %s)
            """
            cur.execute(count_query, (user["id"], like, like, like, like, like))
            total = cur.fetchone()["cnt"]
        else:
            query = """
            SELECT c.*, co.name AS company_name, co.aum_millions
            FROM contacts c
            LEFT JOIN companies co ON co.id = c.company_id
            WHERE c.user_id = %s
            ORDER BY co.aum_millions DESC NULLS LAST
            LIMIT %s OFFSET %s
            """
            cur.execute(query, (user["id"], per_page, offset))
            rows = cur.fetchall()
            cur.execute(
                """SELECT COUNT(*) AS cnt FROM contacts c
                   WHERE c.user_id = %s""",
                (user["id"],),
            )
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
    user=Depends(get_current_user),
):
    """Get contact detail with company info and campaign enrollments."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.*, co.name AS company_name, co.aum_millions,
                      co.firm_type, co.country, co.website, co.is_gdpr AS company_is_gdpr
               FROM contacts c
               LEFT JOIN companies co ON co.id = c.company_id
               WHERE c.id = %s AND c.user_id = %s""",
            (contact_id, user["id"]),
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

        # Get response notes (bounded)
        cur.execute(
            "SELECT * FROM response_notes WHERE contact_id = %s ORDER BY created_at DESC LIMIT 100",
            (contact_id,),
        )
        notes = cur.fetchall()

        # Get tags
        cur.execute(
            """SELECT t.* FROM tags t
               JOIN entity_tags et ON et.tag_id = t.id
               WHERE et.entity_type = 'contact' AND et.entity_id = %s
               ORDER BY t.name""",
            (contact_id,),
        )
        tags = cur.fetchall()

        return {
            "contact": dict(contact),
            "enrollments": [dict(e) for e in enrollments],
            "notes": [dict(n) for n in notes],
            "tags": [dict(t) for t in tags],
        }


@router.get("/contacts/{contact_id}/events")
def get_contact_events(
    contact_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get the event timeline for a contact."""
    with get_cursor(conn) as cur:
        # Verify contact belongs to user
        cur.execute(
            """SELECT c.id FROM contacts c
               WHERE c.id = %s AND c.user_id = %s""",
            (contact_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Contact {contact_id} not found")

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
    user=Depends(get_current_user),
):
    """Log a response outcome and transition contact status."""
    # Verify contact belongs to user
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.id FROM contacts c
               WHERE c.id = %s AND c.user_id = %s""",
            (contact_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Contact {contact_id} not found")

    # Verify campaign belongs to user
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id FROM campaigns WHERE name = %s AND user_id = %s",
            (body.campaign, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Campaign '{body.campaign}' not found")

    try:
        return transition_contact_status(
            conn, contact_id, body.campaign, body.new_status, note=body.note,
            user_id=user["id"],
        )
    except ValueError as e:
        status_code = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code, str(e))
    except InvalidTransition as e:
        raise HTTPException(400, str(e))


@router.post("/contacts/{contact_id}/notes")
def add_response_note(
    contact_id: int,
    body: ResponseNoteRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Add a response note to a contact."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.id FROM contacts c
               WHERE c.id = %s AND c.user_id = %s""",
            (contact_id, user["id"]),
        )
        contact = cur.fetchone()
        if not contact:
            raise HTTPException(404, f"Contact {contact_id} not found")

        campaign_id = None
        if body.campaign:
            camp = get_campaign_by_name(conn, body.campaign, user_id=user["id"])
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
    user=Depends(get_current_user),
):
    """Add or update a contact's phone number with E.164 normalization."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.id FROM contacts c
               WHERE c.id = %s AND c.user_id = %s""",
            (contact_id, user["id"]),
        )
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


@router.post("/contacts/{contact_id}/linkedin-url")
def update_linkedin_url(
    contact_id: int,
    body: LinkedInUrlUpdateRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update a contact's LinkedIn URL with normalization."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.id FROM contacts c
               WHERE c.id = %s AND c.user_id = %s""",
            (contact_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Contact {contact_id} not found")

        normalized = _normalize_linkedin(body.linkedin_url)

        cur.execute(
            "UPDATE contacts SET linkedin_url = %s, linkedin_url_normalized = %s WHERE id = %s",
            (body.linkedin_url, normalized, contact_id),
        )
        conn.commit()

        return {
            "success": True,
            "contact_id": contact_id,
            "linkedin_url": body.linkedin_url,
            "linkedin_url_normalized": normalized,
        }


@router.post("/contacts/{contact_id}/name")
def update_contact_name(
    contact_id: int,
    body: NameUpdateRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update a contact's first name, last name, and full name."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.id FROM contacts c
               WHERE c.id = %s AND c.user_id = %s""",
            (contact_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Contact {contact_id} not found")

        full_name = f"{body.first_name} {body.last_name}"

        cur.execute(
            "UPDATE contacts SET first_name = %s, last_name = %s, full_name = %s WHERE id = %s",
            (body.first_name, body.last_name, full_name, contact_id),
        )
        conn.commit()

        return {
            "success": True,
            "contact_id": contact_id,
            "full_name": full_name,
        }


@router.post("/contacts/bulk/lifecycle")
def bulk_update_lifecycle(
    body: BulkLifecycleRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update lifecycle stage for multiple contacts at once."""
    if body.lifecycle_stage not in LIFECYCLE_STAGES:
        raise HTTPException(400, f"Invalid lifecycle stage. Must be one of: {', '.join(sorted(LIFECYCLE_STAGES))}")

    if not body.contact_ids:
        raise HTTPException(400, "contact_ids must not be empty")

    if len(body.contact_ids) > 500:
        raise HTTPException(400, "Cannot update more than 500 contacts at once")

    with get_cursor(conn) as cur:
        # Verify all contacts exist and belong to user
        placeholders = ", ".join(["%s"] * len(body.contact_ids))
        cur.execute(
            f"""SELECT c.id, c.lifecycle_stage FROM contacts c
                WHERE c.id IN ({placeholders}) AND c.user_id = %s""",
            body.contact_ids + [user["id"]],
        )
        found = cur.fetchall()
        found_ids = {r["id"] for r in found}
        missing = [cid for cid in body.contact_ids if cid not in found_ids]
        if missing:
            raise HTTPException(404, f"Contacts not found: {missing}")

        # Update all
        cur.execute(
            f"UPDATE contacts SET lifecycle_stage = %s WHERE id IN ({placeholders}) AND user_id = %s",
            [body.lifecycle_stage] + body.contact_ids + [user["id"]],
        )

        # Log events
        for contact in found:
            old_stage = contact["lifecycle_stage"]
            if old_stage != body.lifecycle_stage:
                log_event(
                    conn, contact["id"], "lifecycle_changed",
                    metadata=json.dumps({"from": old_stage, "to": body.lifecycle_stage, "bulk": True}),
                    user_id=user["id"],
                )

        conn.commit()
        return {
            "success": True,
            "updated": len(body.contact_ids),
            "lifecycle_stage": body.lifecycle_stage,
        }
