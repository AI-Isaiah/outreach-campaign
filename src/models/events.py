"""Event logging CRUD operations (extracted from campaigns.py)."""

from __future__ import annotations

from typing import Optional

from psycopg2.extensions import connection as PgConnection

from src.models.database import get_cursor


def log_event(
    conn: PgConnection,
    contact_id: int,
    event_type: str,
    campaign_id: Optional[int] = None,
    template_id: Optional[int] = None,
    metadata: Optional[str] = None,
    *,
    user_id: int,
) -> int:
    """Log an event and return its id.

    The metadata argument should be a JSON string (or None).
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            """INSERT INTO events
               (contact_id, event_type, campaign_id, template_id, metadata, user_id)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (contact_id, event_type, campaign_id, template_id, metadata, user_id),
        )
        row = cursor.fetchone()
        conn.commit()
        return row["id"]
