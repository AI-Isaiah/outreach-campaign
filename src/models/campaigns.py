"""CRUD operations for campaigns, templates, sequence steps, enrollment, and events.

Templates, events, and enrollment/sequence-step operations have been split into
``models/templates.py``, ``models/events.py``, and ``models/enrollment.py``
respectively. They are re-exported here so existing
``from src.models.campaigns import ...`` statements continue to work.
"""

from __future__ import annotations

from typing import Optional

from psycopg2.extensions import connection as PgConnection

from src.models.database import get_cursor

# Re-export from split modules for backward compatibility
from src.models.templates import create_template, get_template, list_templates  # noqa: F401
from src.models.events import log_event  # noqa: F401
from src.models.enrollment import (  # noqa: F401
    add_sequence_step,
    get_sequence_steps,
    enroll_contact,
    bulk_enroll_contacts,
    get_contact_campaign_status,
    update_contact_campaign_status,
    get_message_draft,
    record_template_usage,
)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

def create_campaign(
    conn: PgConnection,
    name: str,
    description: Optional[str] = None,
    *,
    user_id: int,
) -> int:
    """Create a new campaign and return its id."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            "INSERT INTO campaigns (name, description, user_id) VALUES (%s, %s, %s) RETURNING id",
            (name, description, user_id),
        )
        row = cursor.fetchone()
        conn.commit()
        return row["id"]


def get_campaign(conn: PgConnection, campaign_id: int, *, user_id: int):
    """Return a single campaign by id, or None."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT * FROM campaigns WHERE id = %s AND user_id = %s",
            (campaign_id, user_id),
        )
        return cursor.fetchone()


def get_campaign_by_name(conn: PgConnection, name: str, *, user_id: int):
    """Return a single campaign by name, or None."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT * FROM campaigns WHERE name = %s AND user_id = %s",
            (name, user_id),
        )
        return cursor.fetchone()


def list_campaigns(
    conn: PgConnection,
    status: Optional[str] = None,
    *,
    user_id: int,
) -> list:
    """Return all campaigns, optionally filtered by status."""
    with get_cursor(conn) as cursor:
        if status is not None:
            cursor.execute(
                "SELECT * FROM campaigns WHERE user_id = %s AND status = %s ORDER BY id",
                (user_id, status),
            )
        else:
            cursor.execute(
                "SELECT * FROM campaigns WHERE user_id = %s ORDER BY id",
                (user_id,),
            )
        return cursor.fetchall()


def update_campaign_status(
    conn: PgConnection,
    campaign_id: int,
    status: str,
    *,
    user_id: int,
) -> None:
    """Update the status of a campaign."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            "UPDATE campaigns SET status = %s WHERE id = %s AND user_id = %s",
            (status, campaign_id, user_id),
        )
        conn.commit()
