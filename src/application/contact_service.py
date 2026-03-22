"""Contact application service — orchestrates status transitions and related ops.

Extracted from routes/contacts.py to keep the route layer thin.
"""

from __future__ import annotations

import json
from typing import Optional

from src.models.campaigns import (
    get_campaign_by_name,
    get_contact_campaign_status,
    log_event,
)
from src.services.state_machine import InvalidTransition, transition_contact
from src.models.database import get_cursor


def transition_contact_status(
    conn,
    contact_id: int,
    campaign_name: str,
    new_status: str,
    note: Optional[str] = None,
    *,
    user_id: int,
) -> dict:
    """Transition a contact's campaign status with validation.

    Handles:
    - Campaign lookup
    - Contact existence check
    - Auto-advance from queued to in_progress
    - Status transition
    - Call-booked event logging
    - Response note storage

    Raises:
        ValueError: if campaign not found, contact not found, or not enrolled.
        InvalidTransition: if the status transition is not allowed.
    """
    camp = get_campaign_by_name(conn, campaign_name, user_id=user_id)
    if not camp:
        raise ValueError(f"Campaign '{campaign_name}' not found")

    campaign_id = camp["id"]

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id, full_name, email FROM contacts WHERE id = %s",
            (contact_id,),
        )
        contact = cur.fetchone()
        if not contact:
            raise ValueError(f"Contact {contact_id} not found")

        ccs = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=user_id)
        if ccs is None:
            raise ValueError(f"Contact {contact_id} not enrolled in campaign")

        # Auto-advance from queued to in_progress if needed
        if ccs["status"] == "queued":
            transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=user_id)

        # Apply the transition
        result_status = transition_contact(conn, contact_id, campaign_id, new_status, user_id=user_id)

        # Log call_booked event if applicable
        if new_status == "replied_positive" and note and "call" in note.lower():
            log_event(
                conn, contact_id, "call_booked",
                campaign_id=campaign_id,
                metadata=json.dumps({"note": note}),
                user_id=user_id,
            )

        # Save response note if provided
        if note:
            cur.execute(
                """INSERT INTO response_notes (contact_id, campaign_id, note_type, content)
                   VALUES (%s, %s, %s, %s)""",
                (contact_id, campaign_id, new_status, note),
            )

        conn.commit()

        return {
            "success": True,
            "contact_id": contact_id,
            "new_status": result_status,
        }
