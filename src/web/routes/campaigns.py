"""Campaign API routes."""

from __future__ import annotations

from typing import Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.application.campaign_service import launch_campaign as _launch_campaign
from src.models.campaigns import delete_campaign, get_campaign_by_name, update_campaign_status
from src.services.metrics import (
    compute_health_score,
    get_campaign_metrics,
    get_company_type_breakdown,
    get_variant_comparison,
    get_weekly_summary,
)
from src.services.response_analyzer import annotate_is_winning, get_template_performance
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

router = APIRouter(tags=["campaigns"])


# ---------------------------------------------------------------------------
# Pydantic models for campaign launch
# ---------------------------------------------------------------------------

class SequenceStepInput(BaseModel):
    step_order: int
    channel: str = Field(max_length=50)
    delay_days: int = Field(ge=0)
    template_id: int | None = None
    draft_mode: str = "template"  # "template" or "ai"


class LaunchCampaignRequest(BaseModel):
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=1000)
    steps: list[SequenceStepInput]
    contact_ids: list[int]
    status: str = Field(default="active")


class UpdateCampaignStatusRequest(BaseModel):
    status: str = Field(pattern="^(active|paused|archived)$")


def _row_to_dict(row) -> dict:
    """Convert a database row to a plain dict."""
    return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Atomic campaign launch (must be registered BEFORE /{name} to avoid capture)
# ---------------------------------------------------------------------------

@router.post("/campaigns/launch")
def launch_campaign(
    body: LaunchCampaignRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a campaign with sequence steps and enroll contacts in one transaction."""
    try:
        return _launch_campaign(
            conn,
            name=body.name,
            description=body.description,
            steps=[s.model_dump() for s in body.steps],
            contact_ids=body.contact_ids,
            status=body.status,
            user_id=user["id"],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except psycopg2.IntegrityError as exc:
        conn.rollback()
        msg = str(exc)
        if "campaigns_user_name_unique" in msg or "campaigns_name_key" in msg:
            raise HTTPException(409, f"Campaign '{body.name}' already exists")
        raise HTTPException(400, f"Integrity error: {msg}")
    except psycopg2.Error:
        conn.rollback()
        raise HTTPException(500, "Failed to launch campaign")


@router.patch("/campaigns/{name}/status")
def patch_campaign_status(
    name: str,
    body: UpdateCampaignStatusRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update campaign status (active, paused, archived)."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")
    update_campaign_status(conn, camp["id"], body.status, user_id=user["id"])
    return {"name": name, "status": body.status}


@router.delete("/campaigns/{name}")
def remove_campaign(
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a campaign and all its enrollments and sequence steps."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")
    deleted = delete_campaign(conn, camp["id"], user_id=user["id"])
    if not deleted:
        raise HTTPException(500, "Failed to delete campaign")
    return {"name": name, "deleted": True}


@router.get("/campaigns")
def list_all_campaigns(
    status: Optional[str] = None,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """List all campaigns with embedded metrics (CTE for O(1) table scans)."""
    user_id = user["id"]
    status_filter = "AND c.status = %s" if status else ""

    query = f"""
    WITH campaign_stats AS (
        SELECT ccs.campaign_id,
               COUNT(*) AS contacts_count,
               COUNT(*) FILTER (WHERE ccs.status IN
                   ('replied_positive','replied_negative','no_response','bounced')
               ) AS contacted_count,
               COUNT(*) FILTER (WHERE ccs.status IN
                   ('replied_positive','replied_negative')
               ) AS replied_count,
               COUNT(*) FILTER (WHERE ccs.status = 'replied_positive'
               ) AS positive_count,
               COUNT(*) FILTER (WHERE ccs.status = 'bounced'
               ) AS bounced_count,
               COUNT(*) FILTER (WHERE ccs.status IN
                   ('replied_positive','replied_negative','no_response',
                    'bounced','completed')
               ) AS completed_count
        FROM contact_campaign_status ccs
        JOIN campaigns ca ON ca.id = ccs.campaign_id AND ca.user_id = %s
        GROUP BY ccs.campaign_id
    ),
    campaign_calls AS (
        SELECT e.campaign_id, COUNT(*) AS calls_booked
        FROM events e
        WHERE e.event_type = 'call_booked' AND e.user_id = %s
        GROUP BY e.campaign_id
    ),
    campaign_sends AS (
        SELECT e.campaign_id, COUNT(*) AS emails_sent
        FROM events e
        WHERE e.event_type = 'email_sent' AND e.user_id = %s
        GROUP BY e.campaign_id
    )
    SELECT c.*,
           COALESCE(cs.contacts_count, 0) AS contacts_count,
           COALESCE(cs.replied_count, 0) AS replied_count,
           CASE WHEN COALESCE(cs.contacted_count, 0) > 0
                THEN ROUND(cs.replied_count::numeric / cs.contacted_count * 100, 1)
                ELSE 0 END AS reply_rate,
           COALESCE(cc.calls_booked, 0) AS calls_booked,
           CASE WHEN COALESCE(cs.contacts_count, 0) > 0
                THEN ROUND(cs.completed_count::numeric / cs.contacts_count * 100, 1)
                ELSE 0 END AS progress_pct,
           COALESCE(cs.positive_count, 0) AS positive_count,
           COALESCE(cs.bounced_count, 0) AS bounced_count,
           COALESCE(csn.emails_sent, 0) AS emails_sent
    FROM campaigns c
    LEFT JOIN campaign_stats cs ON cs.campaign_id = c.id
    LEFT JOIN campaign_calls cc ON cc.campaign_id = c.id
    LEFT JOIN campaign_sends csn ON csn.campaign_id = c.id
    WHERE c.user_id = %s {status_filter}
    ORDER BY c.created_at DESC
    """

    # Build final params: [user_id (stats CTE), user_id (calls CTE), user_id (sends CTE), user_id (WHERE)]
    final_params = [user_id, user_id, user_id, user_id]
    if status:
        final_params.append(status)

    with get_cursor(conn) as cur:
        cur.execute(query, final_params)
        rows = [_row_to_dict(r) for r in cur.fetchall()]

    for row in rows:
        metrics_compat = {
            "total_enrolled": row.get("contacts_count", 0),
            "by_status": {
                "replied_positive": row.get("positive_count", 0),
                "bounced": row.get("bounced_count", 0),
            },
            "emails_sent": row.get("emails_sent", 0),
        }
        row["health_score"] = compute_health_score(metrics_compat)

    return rows


@router.get("/campaigns/{campaign_id}/contacts")
def get_campaign_contacts(
    campaign_id: int,
    status: Optional[str] = None,
    sort: str = "step",
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get contacts enrolled in a specific campaign with their step and status."""
    user_id = user["id"]

    # Verify campaign belongs to user
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id FROM campaigns WHERE id = %s AND user_id = %s",
            (campaign_id, user_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Campaign not found")

    sort_map = {
        "step": "ccs.current_step ASC, ccs.next_action_date ASC",
        "name": "COALESCE(c.full_name, c.first_name) ASC",
        "status": "ccs.status ASC",
    }
    order_by = sort_map.get(sort, sort_map["step"])

    query = f"""
    SELECT c.id, c.first_name, c.last_name, c.full_name,
           c.email_normalized AS email, c.linkedin_url_normalized AS linkedin_url,
           c.title,
           comp.name AS company_name, comp.id AS company_id,
           ccs.current_step, ccs.status, ccs.next_action_date,
           ccs.assigned_variant,
           (SELECT COUNT(*) FROM sequence_steps ss
            WHERE ss.campaign_id = %s) AS total_steps
    FROM contact_campaign_status ccs
    JOIN contacts c ON c.id = ccs.contact_id
    LEFT JOIN companies comp ON comp.id = c.company_id
    WHERE ccs.campaign_id = %s AND c.user_id = %s
    {"AND ccs.status = %s" if status else ""}
    ORDER BY {order_by}
    """

    params: list = [campaign_id, campaign_id, user_id]
    if status:
        params.append(status)

    with get_cursor(conn) as cur:
        cur.execute(query, params)
        return [_row_to_dict(r) for r in cur.fetchall()]


@router.get("/campaigns/{name}")
def get_campaign(
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get campaign details by name."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")
    result = _row_to_dict(camp)
    metrics = get_campaign_metrics(conn, camp["id"])
    result["health_score"] = compute_health_score(metrics)
    return result


@router.get("/campaigns/{name}/metrics")
def get_metrics(
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get campaign metrics."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")

    campaign_id = camp["id"]
    metrics = get_campaign_metrics(conn, campaign_id)
    variants = get_variant_comparison(conn, campaign_id)
    weekly = get_weekly_summary(conn, campaign_id, weeks_back=1)
    firm_breakdown = get_company_type_breakdown(conn, campaign_id)

    campaign_dict = _row_to_dict(camp)
    campaign_dict["health_score"] = compute_health_score(metrics)

    return {
        "campaign": campaign_dict,
        "metrics": metrics,
        "variants": variants,
        "weekly": weekly,
        "firm_breakdown": firm_breakdown,
    }


@router.get("/campaigns/{name}/weekly")
def get_campaign_weekly(
    name: str,
    weeks_back: int = 1,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get weekly summary for a campaign."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")

    weekly = get_weekly_summary(conn, camp["id"], weeks_back=weeks_back)
    return {"campaign": name, "weekly": weekly}


@router.get("/campaigns/{name}/report")
def get_campaign_report(
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get full campaign report with metrics, variants, and breakdown."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")

    campaign_id = camp["id"]
    return {
        "campaign": _row_to_dict(camp),
        "metrics": get_campaign_metrics(conn, campaign_id),
        "variants": get_variant_comparison(conn, campaign_id),
        "weekly": get_weekly_summary(conn, campaign_id, weeks_back=1),
        "firm_breakdown": get_company_type_breakdown(conn, campaign_id),
    }


@router.get("/campaigns/{name}/template-performance")
def get_campaign_template_performance(
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get template performance metrics with winning badge for a campaign."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")

    results = get_template_performance(conn, camp["id"], user_id=user["id"])
    return annotate_is_winning(results)
