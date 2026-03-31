"""CLI command handler: log a reply or status update for a contact."""

from __future__ import annotations

import json

from src.models.database import get_cursor
from src.models.campaigns import (
    get_campaign_by_name,
    get_contact_campaign_status,
)
from src.models.events import log_event
from src.services.state_machine import transition_contact, InvalidTransition


OUTCOME_MAP = {
    "positive": "replied_positive",
    "negative": "replied_negative",
    "call-booked": "replied_positive",
    "no-response": "no_response",
}


def log_reply(
    conn,
    action: str,
    identifier: str,
    outcome: str,
    *,
    user_id: int,
    campaign_name: str | None = None,
) -> dict:
    """Log a reply or status update for a contact.

    Returns dict with 'contact_name', 'new_status', 'outcome'.
    Raises ValueError on validation errors or if contact/campaign not found.
    Raises InvalidTransition on state machine errors.
    """
    if action != "reply":
        raise ValueError(f"Unknown action '{action}'. Supported: reply")

    if outcome not in OUTCOME_MAP:
        raise ValueError(f"Unknown outcome '{outcome}'. Supported: {', '.join(OUTCOME_MAP.keys())}")

    with get_cursor(conn) as cur:
        if identifier.isdigit():
            cur.execute(
                "SELECT id, email, full_name FROM contacts WHERE id = %s AND user_id = %s",
                (int(identifier), user_id),
            )
            contact_row = cur.fetchone()
        else:
            cur.execute(
                "SELECT id, email, full_name FROM contacts WHERE (email = %s OR email_normalized = %s) AND user_id = %s",
                (identifier, identifier.lower().strip(), user_id),
            )
            contact_row = cur.fetchone()

        if contact_row is None:
            raise ValueError(f"Contact '{identifier}' not found")

        contact_id = contact_row["id"]

        # Find the campaign
        if campaign_name:
            camp = get_campaign_by_name(conn, campaign_name, user_id=user_id)
            if not camp:
                raise ValueError(f"Campaign '{campaign_name}' not found")
            campaign_id = camp["id"]
        else:
            # Use first active campaign this contact is enrolled in
            cur.execute(
                """SELECT ccs.campaign_id FROM contact_campaign_status ccs
                   JOIN campaigns c ON c.id = ccs.campaign_id
                   WHERE ccs.contact_id = %s AND c.status = 'active'
                   ORDER BY ccs.id DESC LIMIT 1""",
                (contact_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("Contact is not enrolled in any active campaign")
            campaign_id = row["campaign_id"]

    # Ensure contact is in_progress before transitioning
    ccs = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=user_id)
    if ccs is None:
        raise ValueError(f"Contact is not enrolled in campaign {campaign_id}")

    # If currently queued, auto-advance to in_progress first
    if ccs["status"] == "queued":
        transition_contact(conn, contact_id, campaign_id, "in_progress", user_id=user_id)

    # Apply the transition
    new_status = OUTCOME_MAP[outcome]
    transition_contact(conn, contact_id, campaign_id, new_status, user_id=user_id)

    # Log extra metadata for call-booked
    if outcome == "call-booked":
        log_event(
            conn,
            contact_id,
            "call_booked",
            campaign_id=campaign_id,
            metadata=json.dumps({"call_booked": True}),
            user_id=user_id,
        )

    conn.commit()
    contact_name = contact_row["full_name"] or contact_row["email"] or str(contact_id)

    return {
        "contact_name": contact_name,
        "new_status": new_status,
        "outcome": outcome,
    }
