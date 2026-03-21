"""Campaign API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from src.services.metrics import (
    get_campaign_metrics,
    get_company_type_breakdown,
    get_variant_comparison,
    get_weekly_summary,
)
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

router = APIRouter(tags=["campaigns"])


def _row_to_dict(row) -> dict:
    """Convert a database row to a plain dict."""
    return dict(row) if row else {}


@router.get("/campaigns")
def list_all_campaigns(
    status: Optional[str] = None,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """List all campaigns."""
    with get_cursor(conn) as cur:
        if status:
            cur.execute(
                "SELECT * FROM campaigns WHERE user_id = %s AND status = %s ORDER BY created_at DESC",
                (user["id"], status),
            )
        else:
            cur.execute(
                "SELECT * FROM campaigns WHERE user_id = %s ORDER BY created_at DESC",
                (user["id"],),
            )
        return [_row_to_dict(r) for r in cur.fetchall()]


def _get_campaign_by_name_scoped(conn, name: str, user_id):
    """Fetch a campaign by name scoped to user_id."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM campaigns WHERE name = %s AND user_id = %s",
            (name, user_id),
        )
        return cur.fetchone()


@router.get("/campaigns/{name}")
def get_campaign(
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get campaign details by name."""
    camp = _get_campaign_by_name_scoped(conn, name, user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")
    return _row_to_dict(camp)


@router.get("/campaigns/{name}/metrics")
def get_metrics(
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get campaign metrics."""
    camp = _get_campaign_by_name_scoped(conn, name, user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")

    campaign_id = camp["id"]
    metrics = get_campaign_metrics(conn, campaign_id)
    variants = get_variant_comparison(conn, campaign_id)
    weekly = get_weekly_summary(conn, campaign_id, weeks_back=1)
    firm_breakdown = get_company_type_breakdown(conn, campaign_id)

    return {
        "campaign": _row_to_dict(camp),
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
    camp = _get_campaign_by_name_scoped(conn, name, user["id"])
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
    camp = _get_campaign_by_name_scoped(conn, name, user["id"])
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
