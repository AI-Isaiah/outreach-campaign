"""Unified inbox API route — aggregates replies and notes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get("")
def get_inbox(
    channel: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Unified inbox: unconfirmed replies + recent notes, sorted desc."""
    offset = (page - 1) * per_page
    parts = []
    params: list = []

    # Pending replies (unconfirmed)
    if channel is None or channel == "email":
        parts.append("""
            SELECT pr.id AS item_id, 'email' AS channel,
                   c.full_name AS contact_name, co.name AS company_name,
                   c.id AS contact_id, co.id AS company_id,
                   pr.subject, pr.snippet AS body,
                   pr.classification, pr.detected_at AS occurred_at
            FROM pending_replies pr
            JOIN contacts c ON c.id = pr.contact_id
            JOIN companies co ON co.id = c.company_id
            WHERE pr.confirmed = false AND co.user_id = %s
        """)
        params.append(user["id"])

    # Recent response notes
    if channel is None or channel == "notes":
        parts.append("""
            SELECT rn.id AS item_id, 'note' AS channel,
                   c.full_name AS contact_name, co.name AS company_name,
                   c.id AS contact_id, co.id AS company_id,
                   rn.note_type AS subject, rn.content AS body,
                   NULL AS classification, rn.created_at AS occurred_at
            FROM response_notes rn
            JOIN contacts c ON c.id = rn.contact_id
            JOIN companies co ON co.id = c.company_id
            WHERE co.user_id = %s
        """)
        params.append(user["id"])

    if not parts:
        return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

    union = " UNION ALL ".join(parts)
    count_params = list(params)  # params before adding LIMIT/OFFSET
    query = f"SELECT * FROM ({union}) AS inbox ORDER BY occurred_at DESC LIMIT %s OFFSET %s"
    params.extend([per_page, offset])

    with get_cursor(conn) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

        # Count
        count_query = f"SELECT COUNT(*) AS cnt FROM ({union}) AS inbox"
        cur.execute(count_query, count_params)
        total = cur.fetchone()["cnt"]

        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if total else 0,
        }
