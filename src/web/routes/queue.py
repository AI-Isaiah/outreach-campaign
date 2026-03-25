"""Queue API routes — daily action queue with rendered messages."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.application.queue_service import apply_cross_campaign_email_dedup, get_enriched_queue
from src.config import DEFAULT_CAMPAIGN
from src.models.campaigns import get_campaign_by_name
from src.models.templates import get_template
from src.services.linkedin_actions import complete_linkedin_action
from src.services.priority_queue import defer_contact, get_defer_stats
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

router = APIRouter(tags=["queue"])


class LinkedInDoneRequest(BaseModel):
    action_type: str = Field(default="connect", max_length=50)


class QueueOverrideRequest(BaseModel):
    contact_id: int
    template_id: int


class DeferRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)
    campaign: str = Field(default=DEFAULT_CAMPAIGN, max_length=200)


# Static routes MUST come before parameterized /queue/{campaign} to avoid capture
@router.get("/queue/defer/stats")
def defer_statistics(
    campaign: Optional[str] = None,
    date: Optional[str] = None,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get defer/skip analytics."""
    campaign_id = None
    if campaign:
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT id FROM campaigns WHERE name = %s AND user_id = %s",
                (campaign, user["id"]),
            )
            camp = cur.fetchone()
        if camp:
            campaign_id = camp["id"]

    return get_defer_stats(conn, campaign_id=campaign_id, target_date=date)


@router.get("/queue/all")
def get_all_queues(
    date: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get today's action queue across ALL active campaigns for the user."""
    # Find all active campaigns for this user
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id, name FROM campaigns WHERE user_id = %s AND status = 'active'",
            (user["id"],),
        )
        active_campaigns = cur.fetchall()

    if not active_campaigns:
        return {"items": [], "total": 0}

    # Collect queue items from each active campaign
    merged: list[dict] = []
    for camp in active_campaigns:
        try:
            result = get_enriched_queue(
                conn, camp["name"], date=date, limit=limit, user_id=user["id"],
            )
        except ValueError:
            continue

        for item in result.get("items", []):
            item["campaign_name"] = camp["name"]
            item["campaign_id"] = camp["id"]
            merged.append(item)

    # Sort by step_order ASC, then by contact_name as tiebreaker
    merged.sort(key=lambda x: (
        x.get("step_order") or 0,
        x.get("contact_name") or "",
    ))

    # Cross-campaign email dedup + limit in one pass
    merged = apply_cross_campaign_email_dedup(merged, limit=limit)

    return {"items": merged, "total": len(merged)}


@router.get("/queue/{campaign}")
def get_queue(
    campaign: str,
    date: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    mode: str = Query(default="adaptive"),
    firm_type: Optional[str] = Query(default=None),
    aum_min: Optional[float] = Query(default=None),
    aum_max: Optional[float] = Query(default=None),
    diverse: bool = Query(default=True),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get today's action queue with rendered messages."""
    try:
        return get_enriched_queue(
            conn, campaign,
            date=date, limit=limit, mode=mode,
            firm_type=firm_type, aum_min=aum_min, aum_max=aum_max,
            diverse=diverse,
            user_id=user["id"],
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/queue/{contact_id}/linkedin-done")
def mark_linkedin_done(
    contact_id: int,
    body: LinkedInDoneRequest,
    campaign: str = DEFAULT_CAMPAIGN,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Mark a LinkedIn action as manually completed."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id FROM campaigns WHERE name = %s AND user_id = %s",
            (campaign, user["id"]),
        )
        camp = cur.fetchone()
    if not camp:
        raise HTTPException(404, f"Campaign '{campaign}' not found")

    try:
        result = complete_linkedin_action(
            conn, contact_id, camp["id"], body.action_type,
            user_id=user["id"],
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/queue/{campaign}/override")
def override_template(
    campaign: str,
    body: QueueOverrideRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Override the recommended template for a contact in the queue."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id, name FROM campaigns WHERE name = %s AND user_id = %s",
            (campaign, user["id"]),
        )
        camp = cur.fetchone()
    if not camp:
        raise HTTPException(404, f"Campaign '{campaign}' not found")

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM templates WHERE id = %s AND user_id = %s",
            (body.template_id, user["id"]),
        )
        template = cur.fetchone()
    if not template:
        raise HTTPException(404, f"Template {body.template_id} not found")

    with get_cursor(conn) as cur:
        try:
            key = f"override_{body.contact_id}_{camp['id']}"
            cur.execute(
                """INSERT INTO engine_config (key, value, user_id, updated_at)
                   VALUES (%s, %s, %s, NOW())
                   ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
                (key, str(body.template_id), user["id"]),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "success": True,
        "contact_id": body.contact_id,
        "template_id": body.template_id,
        "template_name": template["name"],
    }


@router.post("/queue/{contact_id}/defer")
def defer_queue_contact(
    contact_id: int,
    body: DeferRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Defer/skip a contact in the queue. Pushes them to tomorrow."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id FROM campaigns WHERE name = %s AND user_id = %s",
            (body.campaign, user["id"]),
        )
        camp = cur.fetchone()
    if not camp:
        raise HTTPException(404, f"Campaign '{body.campaign}' not found")

    result = defer_contact(conn, contact_id, camp["id"], reason=body.reason)
    if not result["success"]:
        raise HTTPException(404, result.get("error", "Defer failed"))

    return result
