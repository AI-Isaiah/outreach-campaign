"""Template CRUD operations (extracted from campaigns.py)."""

from __future__ import annotations

from typing import Optional

from psycopg2.extensions import connection as PgConnection

from src.models.database import get_cursor


def create_template(
    conn: PgConnection,
    name: str,
    channel: str,
    body_template: str,
    subject: Optional[str] = None,
    variant_group: Optional[str] = None,
    variant_label: Optional[str] = None,
    *,
    user_id: int,
) -> int:
    """Create a new template and return its id."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            """INSERT INTO templates
               (name, channel, body_template, subject, variant_group, variant_label, user_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (name, channel, body_template, subject, variant_group, variant_label, user_id),
        )
        row = cursor.fetchone()
        conn.commit()
        return row["id"]


def get_template(conn: PgConnection, template_id: int, *, user_id: int) -> dict | None:
    """Return a single template by id, or None."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT * FROM templates WHERE id = %s AND user_id = %s",
            (template_id, user_id),
        )
        return cursor.fetchone()


def list_templates(
    conn: PgConnection,
    channel: Optional[str] = None,
    is_active: bool = True,
    *,
    user_id: int,
) -> list[dict]:
    """Return templates, optionally filtered by channel and active status."""
    query = "SELECT * FROM templates WHERE user_id = %s"
    params: list = [user_id]

    if channel is not None:
        query += " AND channel = %s"
        params.append(channel)

    query += " AND is_active = %s"
    params.append(is_active)

    query += " ORDER BY id"
    with get_cursor(conn) as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()
