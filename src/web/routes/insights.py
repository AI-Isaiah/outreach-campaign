"""Insights API routes — LLM-powered campaign analysis."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.services.llm_advisor import get_analysis_history, run_analysis
from src.web.dependencies import get_db

router = APIRouter(tags=["insights"])


class AnalyzeRequest(BaseModel):
    campaign_id: int


@router.post("/insights/analyze")
def analyze_campaign(body: AnalyzeRequest, conn=Depends(get_db)):
    """Run an AI-powered analysis of campaign performance."""
    # Verify campaign exists
    cur = conn.cursor()
    cur.execute("SELECT id FROM campaigns WHERE id = %s", (body.campaign_id,))
    if not cur.fetchone():
        raise HTTPException(404, f"Campaign {body.campaign_id} not found")

    result = run_analysis(conn, body.campaign_id)
    return result


@router.get("/insights/history")
def insight_history(
    campaign_id: Optional[int] = Query(None),
    conn=Depends(get_db),
):
    """Return past advisor runs, optionally filtered by campaign."""
    if campaign_id:
        return get_analysis_history(conn, campaign_id)

    # If no campaign_id, return all runs
    cur = conn.cursor()
    cur.execute(
        """SELECT id, campaign_id, run_type, prompt_summary,
                  response_text, insights_json, created_at
           FROM advisor_runs
           ORDER BY created_at DESC
           LIMIT 50"""
    )
    return [dict(r) for r in cur.fetchall()]
