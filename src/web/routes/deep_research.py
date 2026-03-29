"""Deep research API routes — per-company structured research pipeline.

Endpoints:
  POST /research/deep/{company_id}              — Trigger deep research
  GET  /research/deep/{company_id}              — Get latest result
  POST /research/deep/{deep_research_id}/cancel — Cancel in-progress research
"""

from __future__ import annotations

import logging
import os

import httpx as _httpx
import psycopg2
import psycopg2.errors

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.config import SUPABASE_DB_URL
from src.models.database import get_cursor
from src.web.dependencies import get_current_user, get_db

_limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false",
)
_MAX_DEEP_RESEARCH_PER_DAY = 20
from src.web.routes.settings import get_user_api_keys

_logger = logging.getLogger(__name__)
_SUPABASE_URL = os.getenv("SUPABASE_URL", "")
_SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

_US_COUNTRY_VARIANTS = {"US", "USA", "United States"}

router = APIRouter(prefix="/research/deep", tags=["deep-research"])


# ---------------------------------------------------------------------------
# Background trigger
# ---------------------------------------------------------------------------

def _trigger_deep_research(deep_research_id: int, api_keys: dict) -> None:
    """Start deep research via Supabase Edge Function or local background thread.

    Uses Edge Function when SUPABASE_URL is configured (production).
    Falls back to in-process background thread for local development.
    """
    if _SUPABASE_URL and _SUPABASE_SERVICE_ROLE_KEY:
        try:
            _httpx.post(
                f"{_SUPABASE_URL}/functions/v1/deep-research",
                headers={
                    "Authorization": f"Bearer {_SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "deep_research_id": deep_research_id,
                    "api_keys": api_keys,
                },
                timeout=5,
            )
        except (_httpx.HTTPError, OSError) as exc:
            _logger.exception("Failed to trigger deep-research Edge Function: %s", exc)
    else:
        from src.services.deep_research_service import start_deep_research_background

        start_deep_research_background(deep_research_id, SUPABASE_DB_URL, api_keys)


# ---------------------------------------------------------------------------
# POST /research/deep/{company_id} — Trigger deep research
# ---------------------------------------------------------------------------

@router.post("/{company_id}", status_code=202)
@_limiter.limit("5/hour")
def trigger_deep_research(
    request: Request,
    company_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Trigger a deep research job for a specific company."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id, name, country FROM companies WHERE id = %s AND user_id = %s",
            (company_id, user["id"]),
        )
        company = cur.fetchone()
        if not company:
            raise HTTPException(404, "Company not found")

        # Per-user daily cost cap
        cur.execute(
            """SELECT COUNT(*) AS cnt FROM deep_research
               WHERE user_id = %s AND created_at > NOW() - INTERVAL '24 hours'""",
            (user["id"],),
        )
        if cur.fetchone()["cnt"] >= _MAX_DEEP_RESEARCH_PER_DAY:
            _logger.warning("User %s hit deep research daily cap", user["id"])
            raise HTTPException(429, f"Daily limit of {_MAX_DEEP_RESEARCH_PER_DAY} deep research jobs reached")

        cur.execute(
            """SELECT id FROM deep_research
               WHERE company_id = %s AND user_id = %s
               AND status IN ('pending', 'researching', 'synthesizing')""",
            (company_id, user["id"]),
        )
        if cur.fetchone():
            raise HTTPException(
                409, "Deep research already in progress for this company"
            )

    # Resolve API keys
    api_keys = get_user_api_keys(conn, user["id"])
    if not api_keys.get("perplexity"):
        raise HTTPException(
            400,
            "Perplexity API key required for deep research. "
            "Configure it in Settings > API Keys.",
        )

    # Determine if US-based for cost estimation
    is_us = (company["country"] or "") in _US_COUNTRY_VARIANTS

    from src.services.deep_research_service import estimate_cost

    cost_estimate = estimate_cost(is_us)

    # Create deep research record
    with get_cursor(conn) as cur:
        try:
            cur.execute(
                """INSERT INTO deep_research
                       (company_id, user_id, status, cost_estimate_usd, query_count)
                   VALUES (%s, %s, 'pending', %s, %s)
                   RETURNING id""",
                (
                    company_id,
                    user["id"],
                    cost_estimate["cost_estimate_usd"],
                    cost_estimate["query_count"],
                ),
            )
            deep_research_id = cur.fetchone()["id"]
            conn.commit()
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(409, "Deep research already in progress for this company")
        except psycopg2.Error:
            conn.rollback()
            raise

    # Trigger background processing
    _trigger_deep_research(deep_research_id, api_keys)

    return {
        "id": deep_research_id,
        "status": "pending",
        "cost_estimate_usd": cost_estimate["cost_estimate_usd"],
        "query_count": cost_estimate["query_count"],
        "message": f"Deep research started for {company['name']}",
    }


# ---------------------------------------------------------------------------
# GET /research/deep/{company_id} — Get latest result
# ---------------------------------------------------------------------------

@router.get("/{company_id}")
def get_deep_research(
    company_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get the latest deep research result for a company."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT * FROM deep_research
               WHERE company_id = %s AND user_id = %s
               ORDER BY created_at DESC LIMIT 1""",
            (company_id, user["id"]),
        )
        result = cur.fetchone()

    if not result:
        raise HTTPException(404, "No deep research found for this company")

    result = dict(result)

    # Auto-heal stale pending jobs that never started
    if result["status"] == "pending" and result.get("created_at"):
        with get_cursor(conn) as cur:
            cur.execute(
                """UPDATE deep_research
                   SET status = 'failed',
                       error_message = 'Background processing failed to start',
                       updated_at = NOW()
                   WHERE id = %s
                   AND status = 'pending'
                   AND created_at < NOW() - INTERVAL '5 minutes'
                   RETURNING id""",
                (result["id"],),
            )
            healed = cur.fetchone()
            if healed:
                conn.commit()
                result["status"] = "failed"
                result["error_message"] = "Background processing failed to start"

    return result


# ---------------------------------------------------------------------------
# POST /research/deep/{deep_research_id}/cancel — Cancel in-progress
# ---------------------------------------------------------------------------

@router.post("/{deep_research_id}/cancel")
def cancel_deep_research(
    deep_research_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Cancel an in-progress deep research job."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id, user_id, status FROM deep_research WHERE id = %s",
            (deep_research_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(404, "Deep research not found")

    if row["user_id"] != user["id"]:
        raise HTTPException(403, "Not authorized to cancel this research")

    cancelable = ("pending", "researching", "synthesizing")
    if row["status"] not in cancelable:
        raise HTTPException(
            400, f"Cannot cancel: research is already {row['status']}"
        )

    with get_cursor(conn) as cur:
        try:
            cur.execute(
                """UPDATE deep_research
                   SET status = 'cancelled', updated_at = NOW()
                   WHERE id = %s AND user_id = %s
                     AND status IN ('pending', 'researching', 'synthesizing')""",
                (deep_research_id, user["id"]),
            )
            if cur.rowcount == 0:
                conn.rollback()
                raise HTTPException(409, "Research already finished before cancel took effect")
            conn.commit()
        except HTTPException:
            raise
        except psycopg2.Error:
            conn.rollback()
            raise

    return {"success": True, "message": "Deep research cancelled"}
