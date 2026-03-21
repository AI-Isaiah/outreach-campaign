"""Contact campaign state machine.

Manages status transitions for contacts within a campaign and auto-activates
the next priority contact at a company when the current one is exhausted.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from src.enums import ContactStatus, EventType
from src.models.campaigns import (
    enroll_contact,
    get_contact_campaign_status,
    log_event,
    update_contact_campaign_status,
)
from src.models.database import get_cursor


class InvalidTransition(Exception):
    """Raised when a status transition is not allowed."""


# Maps current status -> set of valid next statuses
VALID_TRANSITIONS: dict[str, set[str]] = {
    ContactStatus.QUEUED: {ContactStatus.IN_PROGRESS},
    ContactStatus.IN_PROGRESS: {
        ContactStatus.NO_RESPONSE,
        ContactStatus.REPLIED_POSITIVE,
        ContactStatus.REPLIED_NEGATIVE,
        ContactStatus.BOUNCED,
    },
}

# Terminal statuses that trigger auto-activation of the next contact
_TERMINAL_STATUSES = {ContactStatus.NO_RESPONSE, ContactStatus.BOUNCED}


def transition_contact(
    conn,
    contact_id: int,
    campaign_id: int,
    new_status: str,
) -> str:
    """Transition a contact to a new campaign status.

    Validates the transition, updates the status, logs an event, and
    auto-activates the next priority contact when the new status is terminal.

    Args:
        conn: database connection
        contact_id: the contact being transitioned
        campaign_id: the campaign context
        new_status: the desired new status

    Returns:
        The new status string.

    Raises:
        InvalidTransition: if the transition is not allowed or the contact
            is not enrolled in the campaign.
    """
    row = get_contact_campaign_status(conn, contact_id, campaign_id)
    if row is None:
        raise InvalidTransition(
            f"Contact {contact_id} is not enrolled in campaign {campaign_id}"
        )

    current_status = row["status"]
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise InvalidTransition(
            f"Cannot transition from '{current_status}' to '{new_status}'"
        )

    # Persist the status change
    update_contact_campaign_status(conn, contact_id, campaign_id, status=new_status)

    # Log an event for the transition
    log_event(conn, contact_id, f"status_{new_status}", campaign_id=campaign_id)

    # Auto-activate next contact at the same company for terminal statuses
    if new_status in _TERMINAL_STATUSES:
        _activate_next_contact(conn, contact_id, campaign_id)

    return new_status


def _activate_next_contact(
    conn,
    contact_id: int,
    campaign_id: int,
) -> Optional[int]:
    """Activate the next-ranked contact at the same company.

    Finds the company and priority_rank of the given contact, then looks for
    the next-ranked contact at that company who is not already enrolled in
    the campaign. If found, enrolls them with status ``queued`` and today's
    date as next_action_date, and logs an ``auto_activated`` event.

    Returns:
        The newly activated contact_id, or None if no more contacts remain.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT company_id, priority_rank FROM contacts WHERE id = %s",
            (contact_id,),
        )
        contact_row = cursor.fetchone()

        if contact_row is None:
            return None

        company_id = contact_row["company_id"]
        current_rank = contact_row["priority_rank"]

        # Use FOR UPDATE to prevent race conditions where two concurrent
        # transitions could both try to activate the same next contact.
        cursor.execute(
            """SELECT c.id FROM contacts c
               WHERE c.company_id = %s AND c.priority_rank > %s
               AND c.id NOT IN (
                   SELECT contact_id FROM contact_campaign_status WHERE campaign_id = %s
               )
               ORDER BY c.priority_rank ASC
               LIMIT 1
               FOR UPDATE OF c""",
            (company_id, current_rank, campaign_id),
        )
        next_contact = cursor.fetchone()

        if next_contact is None:
            return None

        next_contact_id = next_contact["id"]

        # Enroll while FOR UPDATE lock is still held to prevent race conditions
        enroll_contact(
            conn,
            next_contact_id,
            campaign_id,
            next_action_date=date.today().isoformat(),
        )

        log_event(conn, next_contact_id, EventType.AUTO_ACTIVATED, campaign_id=campaign_id)

        return next_contact_id


def get_active_contact_for_company(
    conn,
    company_id: int,
    campaign_id: int,
):
    """Return the contact that is actively being worked for a company.

    A contact is considered active if its campaign status is ``queued`` or
    ``in_progress``.

    Returns:
        The contact row, or None if no active contact exists for the company
        in this campaign.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            """SELECT c.* FROM contacts c
               JOIN contact_campaign_status ccs
                 ON ccs.contact_id = c.id AND ccs.campaign_id = %s
               WHERE c.company_id = %s
                 AND ccs.status IN ('queued', 'in_progress')
               ORDER BY c.priority_rank ASC
               LIMIT 1""",
            (campaign_id, company_id),
        )
        return cursor.fetchone()
