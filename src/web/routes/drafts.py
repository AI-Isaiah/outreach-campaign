"""Campaign draft API routes — CRUD for wizard draft persistence."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.models.database import get_cursor
from src.web.dependencies import get_current_user, get_db

router = APIRouter(tags=["drafts"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class CreateDraftRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)


class UpdateDraftRequest(BaseModel):
    form_data: dict
    current_step: Optional[int] = None


class BulkContactIdsRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


# ---------------------------------------------------------------------------
# Draft CRUD
# ---------------------------------------------------------------------------

@router.post("/campaigns/draft")
def create_draft(
    body: CreateDraftRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a new campaign wizard draft."""
    user_id = user["id"]
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO campaign_drafts (user_id, name)
               VALUES (%s, %s)
               RETURNING id, version""",
            (user_id, body.name),
        )
        row = cur.fetchone()
    conn.commit()
    return {"id": row["id"], "version": row["version"]}


@router.get("/campaigns/draft/{draft_id}")
def get_draft(
    draft_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Retrieve a campaign wizard draft. Ownership-checked."""
    user_id = user["id"]
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT id, form_data, current_step, version, updated_at
               FROM campaign_drafts
               WHERE id = %s AND user_id = %s""",
            (draft_id, user_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Draft not found")
    return dict(row)


@router.patch("/campaigns/draft/{draft_id}")
def update_draft(
    draft_id: int,
    body: UpdateDraftRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update a campaign wizard draft. Full replace of form_data, bumps version."""
    user_id = user["id"]
    with get_cursor(conn) as cur:
        cur.execute(
            """UPDATE campaign_drafts
               SET form_data = %s,
                   current_step = COALESCE(%s, current_step),
                   version = version + 1,
                   updated_at = NOW(),
                   expires_at = NOW() + INTERVAL '30 days'
               WHERE id = %s AND user_id = %s
               RETURNING id, version""",
            (
                json.dumps(body.form_data),
                body.current_step,
                draft_id,
                user_id,
            ),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Draft not found")
    conn.commit()
    return {"id": row["id"], "version": row["version"]}


@router.delete("/campaigns/draft/{draft_id}")
def delete_draft(
    draft_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a campaign wizard draft. Ownership-checked."""
    user_id = user["id"]
    with get_cursor(conn) as cur:
        cur.execute(
            """DELETE FROM campaign_drafts
               WHERE id = %s AND user_id = %s
               RETURNING id""",
            (draft_id, user_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Draft not found")
    conn.commit()
    return {"success": True}


# ---------------------------------------------------------------------------
# Bulk contact fetch (used by wizard audience step to hydrate selected IDs)
# ---------------------------------------------------------------------------

@router.post("/contacts/by-ids")
def get_contacts_by_ids(
    body: BulkContactIdsRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Fetch contacts by a list of IDs. Returns only contacts owned by the user."""
    user_id = user["id"]
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT id, first_name, last_name, full_name,
                      email_normalized AS email,
                      linkedin_url_normalized AS linkedin_url,
                      title, company_id
               FROM contacts
               WHERE id = ANY(%s::int[]) AND user_id = %s""",
            (body.ids, user_id),
        )
        rows = [dict(r) for r in cur.fetchall()]
    return rows


# ---------------------------------------------------------------------------
# Draft cleanup
# ---------------------------------------------------------------------------
# TODO: Add expired-draft cleanup.  Two options:
#   1. A periodic cron job:
#        DELETE FROM campaign_drafts WHERE expires_at < NOW()
#      Wire it into the existing cron_router pattern (see routes/replies.py).
#   2. Inline on login — add to get_current_user() in dependencies.py:
#        After resolving the user, fire-and-forget:
#          DELETE FROM campaign_drafts
#          WHERE user_id = %s AND expires_at < NOW()
#      This keeps it simple but adds a write to every authed request.
#   Option 1 (cron) is recommended for production.
