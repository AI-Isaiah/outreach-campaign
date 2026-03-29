"""Insights API routes — LLM-powered campaign analysis."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.services.llm_advisor import get_analysis_history, run_analysis
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["insights"])


class AnalyzeRequest(BaseModel):
    campaign_id: int


@router.post("/insights/analyze")
@_limiter.limit("5/minute")
def analyze_campaign(request: Request, body: AnalyzeRequest, conn=Depends(get_db), user=Depends(get_current_user)):
    """Run an AI-powered analysis of campaign performance."""
    # Verify campaign exists and belongs to this user
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id FROM campaigns WHERE id = %s AND user_id = %s",
            (body.campaign_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Campaign {body.campaign_id} not found")

    result = run_analysis(conn, body.campaign_id, user_id=user["id"])
    return result


@router.get("/insights/history")
def insight_history(
    campaign_id: Optional[int] = Query(None),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Return past advisor runs, optionally filtered by campaign."""
    if campaign_id:
        with get_cursor(conn) as cur:
            # Verify campaign belongs to this user
            cur.execute(
                "SELECT id FROM campaigns WHERE id = %s AND user_id = %s",
                (campaign_id, user["id"]),
            )
            if not cur.fetchone():
                raise HTTPException(404, f"Campaign {campaign_id} not found")
        return get_analysis_history(conn, campaign_id, user_id=user["id"])

    # Return all runs scoped via campaigns
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT ar.id, ar.campaign_id, ar.run_type, ar.prompt_summary,
                      ar.response_text, ar.insights_json, ar.template_suggestions_json,
                      ar.events_analyzed, ar.created_at
               FROM advisor_runs ar
               JOIN campaigns cam ON cam.id = ar.campaign_id
               WHERE cam.user_id = %s
               ORDER BY ar.created_at DESC
               LIMIT 50""",
            (user["id"],),
        )
        return [dict(r) for r in cur.fetchall()]
