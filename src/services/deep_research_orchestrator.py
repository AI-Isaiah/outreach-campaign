"""Deep research — background orchestration, status management, thread spawning."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import psycopg2

from src.models.database import get_cursor
from src.services.deep_research_queries import (
    COST_PERPLEXITY_QUERY,
    COST_SONNET_SYNTHESIS,
    _build_research_queries,
    _extract_fund_signals,
    _perplexity_query,
)
from src.services.deep_research_enrichment import (
    _enrich_contacts,
    _get_previous_crypto_score,
    _synthesize_with_sonnet,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_cancelled(conn, deep_research_id: int, *, user_id: int) -> bool:
    """Check if deep research has been cancelled."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT status FROM deep_research WHERE id = %s AND user_id = %s",
            (deep_research_id, user_id),
        )
        row = cur.fetchone()
        return row is not None and row["status"] == "cancelled"


def _update_status(conn, deep_research_id: int, status: str, *, user_id: int, **kwargs) -> None:
    """Update deep_research row status and optional fields."""
    sets = ["status = %s", "updated_at = NOW()"]
    vals: list = [status]

    for key in (
        "raw_queries", "company_overview", "crypto_signals", "key_people",
        "talking_points", "risk_factors", "updated_crypto_score", "confidence",
        "actual_cost_usd", "query_count", "previous_crypto_score",
        "error_message", "fund_signals",
    ):
        if key in kwargs:
            val = kwargs[key]
            if key in ("raw_queries", "crypto_signals", "key_people", "talking_points", "fund_signals"):
                val = json.dumps(val) if val is not None else None
            sets.append(f"{key} = %s")
            vals.append(val)

    if status == "researching":
        sets.append("started_at = COALESCE(started_at, NOW())")
    if status in ("completed", "failed", "cancelled"):
        sets.append("completed_at = NOW()")

    vals.extend([deep_research_id, user_id])
    with get_cursor(conn) as cur:
        cur.execute(
            f"UPDATE deep_research SET {', '.join(sets)} WHERE id = %s AND user_id = %s",
            vals,
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Background Thread Entry Point
# ---------------------------------------------------------------------------


def run_deep_research(
    deep_research_id: int,
    db_url: str,
    api_keys: dict | None = None,
) -> None:
    """Background thread entry point. Gets fresh connection and runs pipeline."""
    from src.models.database import get_connection, run_migrations

    conn = get_connection(db_url)
    user_id = None
    try:
        run_migrations(conn)

        # Fetch user_id from the deep_research row for scoped updates
        with get_cursor(conn) as cur:
            cur.execute("SELECT user_id FROM deep_research WHERE id = %s", (deep_research_id,))
            row = cur.fetchone()
            if not row:
                logger.warning(
                    "Deep research %d not found — row may have been deleted before background thread started",
                    deep_research_id,
                )
                return
            user_id = row["user_id"]

        keys = api_keys or {}
        if not keys.get("perplexity"):
            keys["perplexity"] = os.getenv("PERPLEXITY_API_KEY", "")
        if not keys.get("anthropic"):
            keys["anthropic"] = os.getenv("ANTHROPIC_API_KEY", "")

        _execute_deep_research(conn, deep_research_id, keys)
    except (httpx.HTTPError, psycopg2.Error, json.JSONDecodeError, KeyError, RuntimeError) as e:
        logger.exception("Deep research %d failed", deep_research_id)
        if user_id is not None:
            try:
                _update_status(conn, deep_research_id, "failed", user_id=user_id, error_message=str(e))
            except psycopg2.Error:
                logger.exception("Failed to update deep research %d status", deep_research_id)
        else:
            logger.error(
                "Deep research %d failed and user_id is None — cannot update status: %s",
                deep_research_id, e,
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _execute_deep_research(conn, deep_research_id: int, api_keys: dict) -> None:
    """Main orchestrator: queries -> synthesis -> contact enrichment."""
    # Fetch deep_research row + company data
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT dr.*, c.name AS company_name, c.country
               FROM deep_research dr
               JOIN companies c ON c.id = dr.company_id
               WHERE dr.id = %s""",
            (deep_research_id,),
        )
        dr = cur.fetchone()

    if not dr or dr["status"] == "cancelled":
        return

    company_name = dr["company_name"]
    company_id = dr["company_id"]
    user_id = dr["user_id"]
    is_us_based = (dr.get("country") or "").strip().upper() in ("US", "USA", "UNITED STATES")
    perplexity_key = api_keys.get("perplexity", "")
    anthropic_key = api_keys.get("anthropic", "")

    if not perplexity_key:
        _update_status(conn, deep_research_id, "failed", user_id=user_id, error_message="PERPLEXITY_API_KEY not configured")
        return
    if not anthropic_key:
        _update_status(conn, deep_research_id, "failed", user_id=user_id, error_message="ANTHROPIC_API_KEY not configured")
        return

    # --- Phase 1: Parallel Perplexity queries ---
    _update_status(conn, deep_research_id, "researching", user_id=user_id)

    queries = _build_research_queries(company_name, is_us_based)
    query_results: list[dict] = []
    total_cost = 0.0

    def _run_query(query: str) -> dict:
        """Execute a single query with rate-limit backoff."""
        backoff_waits = [2, 5, 10, 30]
        for attempt, wait in enumerate([0] + backoff_waits):
            if wait:
                time.sleep(wait)
            try:
                result = _perplexity_query(query, perplexity_key)
                result["query"] = query
                return result
            except httpx.HTTPStatusError:
                if attempt >= len(backoff_waits):
                    return {"query": query, "error": "Rate limited after retries", "cost_usd": 0, "duration_ms": 0}
                continue
        return {"query": query, "error": "Rate limited after retries", "cost_usd": 0, "duration_ms": 0}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_run_query, q): q for q in queries}
        for future in as_completed(futures):
            result = future.result()
            query_results.append(result)
            total_cost += result.get("cost_usd", 0)

    # Check cancellation between phases
    if _is_cancelled(conn, deep_research_id, user_id=user_id):
        _update_status(
            conn, deep_research_id, "cancelled",
            user_id=user_id,
            raw_queries=query_results,
            actual_cost_usd=round(total_cost, 4),
            query_count=len(queries),
        )
        return

    # Require minimum 2 successful queries to proceed
    successful = [r for r in query_results if "response" in r]
    if len(successful) < 2:
        _update_status(
            conn, deep_research_id, "failed",
            user_id=user_id,
            raw_queries=query_results,
            actual_cost_usd=round(total_cost, 4),
            query_count=len(queries),
            error_message=f"Only {len(successful)} of {len(queries)} queries succeeded (minimum 2 required)",
        )
        return

    # --- Phase 2: Sonnet synthesis ---
    _update_status(
        conn, deep_research_id, "synthesizing",
        user_id=user_id,
        raw_queries=query_results,
        actual_cost_usd=round(total_cost, 4),
        query_count=len(queries),
    )

    # Fetch any prior bulk research data for this company (scoped via research_jobs.user_id)
    bulk_research = None
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT rr.web_search_raw, rr.website_crawl_raw
               FROM research_results rr
               JOIN research_jobs rj ON rj.id = rr.job_id
               WHERE rr.company_id = %s AND rr.status = 'completed' AND rj.user_id = %s
               ORDER BY rr.created_at DESC LIMIT 1""",
            (company_id, user_id),
        )
        bulk_research = cur.fetchone()

    synthesis = _synthesize_with_sonnet(query_results, company_name, bulk_research, anthropic_key)
    total_cost += COST_SONNET_SYNTHESIS

    # Check cancellation after synthesis
    if _is_cancelled(conn, deep_research_id, user_id=user_id):
        _update_status(
            conn, deep_research_id, "cancelled",
            user_id=user_id,
            actual_cost_usd=round(total_cost, 4),
        )
        return

    # --- Phase 3: Enrich contacts + snapshot previous score ---
    previous_score = _get_previous_crypto_score(conn, company_id, user_id=user_id)

    key_people = synthesis.get("key_people") or []
    if not isinstance(key_people, list):
        key_people = []
    _enrich_contacts(conn, company_id, key_people, user_id)

    # Validate LLM-supplied crypto score before DB write
    raw_score = synthesis.get("updated_crypto_score")
    try:
        validated_score = max(0, min(100, int(raw_score))) if raw_score is not None else None
    except (TypeError, ValueError):
        validated_score = None

    fund_signals = _extract_fund_signals(synthesis)

    # --- Final update ---
    _update_status(
        conn, deep_research_id, "completed",
        user_id=user_id,
        raw_queries=query_results,
        company_overview=synthesis.get("company_overview"),
        crypto_signals=synthesis.get("crypto_signals"),
        key_people=key_people,
        talking_points=synthesis.get("talking_points"),
        risk_factors=synthesis.get("risk_factors"),
        updated_crypto_score=validated_score,
        confidence=synthesis.get("confidence") if synthesis.get("confidence") in ("high", "medium", "low") else None,
        actual_cost_usd=round(total_cost, 4),
        query_count=len(queries),
        previous_crypto_score=previous_score,
        fund_signals=fund_signals,
    )

    logger.info(
        "Deep research %d completed for %s: score=%s, cost=$%.4f",
        deep_research_id, company_name,
        synthesis.get("updated_crypto_score"), total_cost,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_deep_research_background(
    deep_research_id: int,
    db_url: str,
    api_keys: dict | None = None,
) -> None:
    """Spawn a daemon thread to run deep research."""
    thread = threading.Thread(
        target=run_deep_research,
        args=(deep_research_id, db_url, api_keys),
        daemon=True,
        name=f"deep-research-{deep_research_id}",
    )
    thread.start()
