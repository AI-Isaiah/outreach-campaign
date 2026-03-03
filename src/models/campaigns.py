"""CRUD operations for campaigns, templates, sequence steps, enrollment, and events."""

from __future__ import annotations

import json
import psycopg2
from datetime import datetime
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

def create_campaign(
    conn,
    name: str,
    description: Optional[str] = None,
) -> int:
    """Create a new campaign and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO campaigns (name, description) VALUES (%s, %s) RETURNING id",
        (name, description),
    )
    row = cursor.fetchone()
    conn.commit()
    return row["id"]


def get_campaign(conn, campaign_id: int):
    """Return a single campaign by id, or None."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM campaigns WHERE id = %s",
        (campaign_id,),
    )
    return cursor.fetchone()


def get_campaign_by_name(conn, name: str):
    """Return a single campaign by name, or None."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM campaigns WHERE name = %s",
        (name,),
    )
    return cursor.fetchone()


def list_campaigns(
    conn,
    status: Optional[str] = None,
) -> list:
    """Return all campaigns, optionally filtered by status."""
    cursor = conn.cursor()
    if status is not None:
        cursor.execute(
            "SELECT * FROM campaigns WHERE status = %s ORDER BY id",
            (status,),
        )
    else:
        cursor.execute("SELECT * FROM campaigns ORDER BY id")
    return cursor.fetchall()


def update_campaign_status(
    conn,
    campaign_id: int,
    status: str,
) -> None:
    """Update the status of a campaign."""
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE campaigns SET status = %s WHERE id = %s",
        (status, campaign_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def create_template(
    conn,
    name: str,
    channel: str,
    body_template: str,
    subject: Optional[str] = None,
    variant_group: Optional[str] = None,
    variant_label: Optional[str] = None,
) -> int:
    """Create a new template and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO templates
           (name, channel, body_template, subject, variant_group, variant_label)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, channel, body_template, subject, variant_group, variant_label),
    )
    row = cursor.fetchone()
    conn.commit()
    return row["id"]


def get_template(conn, template_id: int):
    """Return a single template by id, or None."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM templates WHERE id = %s",
        (template_id,),
    )
    return cursor.fetchone()


def list_templates(
    conn,
    channel: Optional[str] = None,
    is_active: bool = True,
) -> list:
    """Return templates, optionally filtered by channel and active status."""
    query = "SELECT * FROM templates WHERE 1=1"
    params: list = []

    if channel is not None:
        query += " AND channel = %s"
        params.append(channel)

    query += " AND is_active = %s"
    params.append(is_active)

    query += " ORDER BY id"
    cursor = conn.cursor()
    cursor.execute(query, params)
    return cursor.fetchall()


# ---------------------------------------------------------------------------
# Sequence Steps
# ---------------------------------------------------------------------------

def add_sequence_step(
    conn,
    campaign_id: int,
    step_order: int,
    channel: str,
    template_id: Optional[int] = None,
    delay_days: int = 0,
    gdpr_only: bool = False,
    non_gdpr_only: bool = False,
) -> int:
    """Add a sequence step to a campaign and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO sequence_steps
           (campaign_id, step_order, channel, template_id, delay_days, gdpr_only, non_gdpr_only)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (
            campaign_id,
            step_order,
            channel,
            template_id,
            delay_days,
            gdpr_only,
            non_gdpr_only,
        ),
    )
    row = cursor.fetchone()
    conn.commit()
    return row["id"]


# ---------------------------------------------------------------------------
# Sequence Steps (query)
# ---------------------------------------------------------------------------

def get_sequence_steps(conn, campaign_id: int) -> list:
    """Return all steps for a campaign, ordered by step_order."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM sequence_steps WHERE campaign_id = %s ORDER BY step_order",
        (campaign_id,),
    )
    return cursor.fetchall()


# ---------------------------------------------------------------------------
# Contact Campaign Enrollment / Status
# ---------------------------------------------------------------------------

def enroll_contact(
    conn,
    contact_id: int,
    campaign_id: int,
    variant: Optional[str] = None,
    next_action_date: Optional[str] = None,
) -> Optional[int]:
    """Enroll a contact in a campaign. Returns enrollment id, or None if already enrolled."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO contact_campaign_status
               (contact_id, campaign_id, current_step, assigned_variant, next_action_date)
               VALUES (%s, %s, 1, %s, %s) RETURNING id""",
            (contact_id, campaign_id, variant, next_action_date),
        )
        row = cursor.fetchone()
        conn.commit()
        return row["id"]
    except psycopg2.IntegrityError:
        conn.rollback()
        return None


def bulk_enroll_contacts(
    conn,
    campaign_id: int,
    contact_ids: list,
    variant_assigner: Optional[Callable] = None,
) -> int:
    """Enroll multiple contacts in a campaign.

    Args:
        conn: database connection
        campaign_id: campaign to enroll contacts in
        contact_ids: list of contact ids to enroll
        variant_assigner: optional callable(contact_id) -> str for variant assignment

    Returns:
        count of newly enrolled contacts (skips already enrolled)
    """
    if not contact_ids:
        return 0
    placeholders = ",".join("%s" for _ in contact_ids)
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT contact_id FROM contact_campaign_status "
        f"WHERE campaign_id = %s AND contact_id IN ({placeholders})",
        [campaign_id] + list(contact_ids),
    )
    already_enrolled = {row["contact_id"] for row in cursor.fetchall()}

    enrolled_count = 0
    for contact_id in contact_ids:
        if contact_id in already_enrolled:
            continue
        variant = variant_assigner(contact_id) if variant_assigner else None
        cursor.execute(
            """INSERT INTO contact_campaign_status
               (contact_id, campaign_id, current_step, assigned_variant)
               VALUES (%s, %s, 1, %s)""",
            (contact_id, campaign_id, variant),
        )
        enrolled_count += 1

    conn.commit()
    return enrolled_count


def get_contact_campaign_status(
    conn,
    contact_id: int,
    campaign_id: int,
):
    """Return the enrollment/status row for a contact in a campaign, or None."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
        (contact_id, campaign_id),
    )
    return cursor.fetchone()


def update_contact_campaign_status(
    conn,
    contact_id: int,
    campaign_id: int,
    status: Optional[str] = None,
    current_step: Optional[int] = None,
    next_action_date: Optional[str] = None,
) -> None:
    """Update fields on a contact's campaign status row.

    Only supplied (non-None) fields are updated. updated_at is always refreshed.
    """
    fields = []
    params: list = []

    if status is not None:
        fields.append("status = %s")
        params.append(status)
    if current_step is not None:
        fields.append("current_step = %s")
        params.append(current_step)
    if next_action_date is not None:
        fields.append("next_action_date = %s")
        params.append(next_action_date)

    if not fields:
        return

    fields.append("updated_at = NOW()")

    query = (
        f"UPDATE contact_campaign_status SET {', '.join(fields)} "
        f"WHERE contact_id = %s AND campaign_id = %s"
    )
    params.extend([contact_id, campaign_id])
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def log_event(
    conn,
    contact_id: int,
    event_type: str,
    campaign_id: Optional[int] = None,
    template_id: Optional[int] = None,
    metadata: Optional[str] = None,
) -> int:
    """Log an event and return its id.

    The metadata argument should be a JSON string (or None).
    """
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO events
           (contact_id, event_type, campaign_id, template_id, metadata)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (contact_id, event_type, campaign_id, template_id, metadata),
    )
    row = cursor.fetchone()
    conn.commit()
    return row["id"]
