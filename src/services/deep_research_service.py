"""Per-company deep research pipeline.

Runs targeted Perplexity Sonar queries in parallel, synthesizes results
with Claude Sonnet into structured JSON (talking points, key people,
crypto signals), and enriches CRM contacts from the output.

Architecture:
  - _perplexity_query: shared helper for individual Perplexity API calls
  - _build_research_queries: constructs 5-6 targeted query strings
  - _synthesize_with_sonnet: structured synthesis via Claude Sonnet
  - _enrich_contacts: matches key_people output to existing CRM contacts
  - _execute_deep_research: orchestrator with parallel queries and cancellation
  - run_deep_research: background thread entry point
  - start_deep_research_background: spawns daemon thread
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from src.models.database import get_cursor
from src.services.normalization_utils import (
    normalize_company_name,
    normalize_email,
    normalize_linkedin_url,
    split_name,
)

logger = logging.getLogger(__name__)

DEEP_RESEARCH_MODEL = "claude-sonnet-4-20250514"

# Cost estimates per operation
COST_PERPLEXITY_QUERY = 0.005
COST_SONNET_SYNTHESIS = 0.03

SYNTHESIS_PROMPT = """\
You are an investment research analyst preparing a pre-meeting brief for
outreach to {company_name}. Below are research results from multiple queries
and any prior bulk research data.

RESEARCH DATA:
{raw_query_results_concatenated}

PRIOR BULK RESEARCH (if available):
{web_search_raw}
{website_crawl_raw}

Produce a JSON object with EXACTLY this schema:
{{
  "company_overview": "2-3 paragraph summary of investment philosophy, AUM, fund structure",
  "crypto_signals": [
    {{"source": "source name", "quote": "exact quote or finding", "relevance": "high|medium|low"}}
  ],
  "key_people": [
    {{"name": "Full Name", "title": "Title", "linkedin_url": "URL or null", "context": "1 sentence on relevance"}}
  ],
  "talking_points": [
    {{"hook_type": "thesis_alignment|team_signal|event_hook|portfolio_move",
     "text": "Draft talking point written as if sender is reaching out to this company",
     "source_reference": "What source this references"}}
  ],
  "risk_factors": "Any concerns about approaching this company (or null)",
  "updated_crypto_score": 0-100,
  "confidence": "high|medium|low"
}}

Rules:
- Each talking point MUST reference a specific, verifiable source
- Talking points should demonstrate genuine familiarity, not generic flattery
- crypto_score: 80-100=confirmed investor, 60-79=likely interested, 40-59=possible, 20-39=no signal, 0-19=unlikely
- Return ONLY valid JSON, no markdown fences, no explanation"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_cancelled(conn, deep_research_id: int) -> bool:
    """Check if deep research has been cancelled."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT status FROM deep_research WHERE id = %s",
            (deep_research_id,),
        )
        row = cur.fetchone()
        return row is not None and row["status"] == "cancelled"


def _update_status(conn, deep_research_id: int, status: str, **kwargs) -> None:
    """Update deep_research row status and optional fields."""
    sets = ["status = %s", "updated_at = NOW()"]
    vals: list = [status]

    for key in (
        "raw_queries", "company_overview", "crypto_signals", "key_people",
        "talking_points", "risk_factors", "updated_crypto_score", "confidence",
        "actual_cost_usd", "query_count", "previous_crypto_score",
        "error_message",
    ):
        if key in kwargs:
            val = kwargs[key]
            if key in ("raw_queries", "crypto_signals", "key_people", "talking_points"):
                val = json.dumps(val) if val is not None else None
            sets.append(f"{key} = %s")
            vals.append(val)

    if status == "researching":
        sets.append("started_at = COALESCE(started_at, NOW())")
    if status in ("completed", "failed", "cancelled"):
        sets.append("completed_at = NOW()")

    vals.append(deep_research_id)
    with get_cursor(conn) as cur:
        cur.execute(
            f"UPDATE deep_research SET {', '.join(sets)} WHERE id = %s",
            vals,
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Perplexity API
# ---------------------------------------------------------------------------


def _perplexity_query(query: str, api_key: str) -> dict:
    """Execute a single Perplexity Sonar query.

    Returns {"response": str, "cost_usd": float, "duration_ms": int} on success,
    or {"error": str, "cost_usd": 0, "duration_ms": int} on failure.
    Re-raises 429 HTTPStatusError for caller to handle with backoff.
    """
    start = time.monotonic()
    try:
        resp = httpx.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sonar",
                "messages": [{"role": "user", "content": query}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            "response": data["choices"][0]["message"]["content"],
            "cost_usd": COST_PERPLEXITY_QUERY,
            "duration_ms": duration_ms,
        }
    except httpx.HTTPStatusError as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        if e.response.status_code == 429:
            raise
        logger.warning("Perplexity API error: %s", e.response.status_code)
        return {"error": f"API error: {e.response.status_code}", "cost_usd": 0, "duration_ms": duration_ms}
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning("Perplexity query failed: %s", exc)
        return {"error": str(exc), "cost_usd": 0, "duration_ms": duration_ms}


# ---------------------------------------------------------------------------
# Query Construction
# ---------------------------------------------------------------------------


def _build_research_queries(company_name: str, is_us_based: bool) -> list[str]:
    """Build 5-6 targeted research queries for a company.

    Returns 6 queries for US-based companies (includes SEC filings),
    5 for all others.
    """
    queries = [
        f'"{company_name}" investment thesis philosophy strategy 2026',
        f'"{company_name}" cryptocurrency digital assets bitcoin blockchain allocation',
        f'"{company_name}" recent portfolio acquisitions investments 2025 2026',
        f'"{company_name}" CIO "head of" investments leadership team 2026',
        f'"{company_name}" conference speaking panel crypto blockchain digital assets',
    ]
    if is_us_based:
        queries.append(f'"{company_name}" SEC filing fund allocation 13F')
    return queries


# ---------------------------------------------------------------------------
# Sonnet Synthesis
# ---------------------------------------------------------------------------


def _synthesize_with_sonnet(
    raw_results: list[dict],
    company_name: str,
    bulk_research: dict | None,
    api_key: str,
) -> dict:
    """Synthesize raw query results into structured JSON via Claude Sonnet.

    On JSON parse failure, retries once with a stricter prompt. On second
    failure, returns a minimal fallback dict.
    """
    concatenated = "\n\n---\n\n".join(
        f"Query: {r.get('query', 'N/A')}\nResult: {r.get('response', r.get('error', 'No data'))}"
        for r in raw_results
    )

    web_search_raw = ""
    website_crawl_raw = ""
    if bulk_research:
        web_search_raw = bulk_research.get("web_search_raw") or ""
        website_crawl_raw = bulk_research.get("website_crawl_raw") or ""

    prompt = SYNTHESIS_PROMPT.format(
        company_name=company_name,
        raw_query_results_concatenated=concatenated,
        web_search_raw=web_search_raw or "None",
        website_crawl_raw=website_crawl_raw or "None",
    )

    raw_text = ""
    for attempt in range(2):
        if attempt == 1:
            prompt += (
                "\n\nIMPORTANT: Your previous response was not valid JSON. "
                "Return ONLY a raw JSON object. No markdown, no code fences, no text before or after."
            )

        try:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": DEEP_RESEARCH_MODEL,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            raw_text = data["content"][0]["text"]

            # Strip markdown fences if present
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned)

            return json.loads(cleaned)
        except (json.JSONDecodeError, KeyError):
            if attempt == 0:
                logger.warning("Sonnet synthesis JSON parse failed for %s, retrying", company_name)
                continue
            logger.warning("Sonnet synthesis failed twice for %s, using fallback", company_name)
            return {"company_overview": raw_text, "confidence": "low"}
        except Exception as exc:
            logger.exception("Sonnet synthesis error for %s", company_name)
            raise RuntimeError(f"Synthesis failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Contact Enrichment
# ---------------------------------------------------------------------------


def _enrich_contacts(conn, company_id: int, key_people: list[dict], user_id: int) -> int:
    """Match key_people against existing contacts, create new ones if unmatched.

    Matching priority:
      1. linkedin_url_normalized
      2. email_normalized
      3. (full_name normalized, company_id)

    Only updates title if the existing value is NULL.
    Returns count of contacts created or updated.
    """
    if not key_people:
        return 0

    affected = 0

    with get_cursor(conn) as cur:
        for person in key_people:
            name = (person.get("name") or "").strip()
            if not name:
                continue

            title = person.get("title")
            linkedin_url = person.get("linkedin_url")
            linkedin_norm = normalize_linkedin_url(linkedin_url) if linkedin_url else ""
            contact_id = None

            # Match by linkedin_url_normalized
            if linkedin_norm:
                cur.execute(
                    "SELECT id, title FROM contacts WHERE linkedin_url_normalized = %s AND company_id = %s",
                    (linkedin_norm, company_id),
                )
                match = cur.fetchone()
                if match:
                    contact_id = match["id"]
                    if match["title"] is None and title:
                        cur.execute(
                            "UPDATE contacts SET title = %s, updated_at = NOW() WHERE id = %s",
                            (title, contact_id),
                        )
                    affected += 1
                    continue

            # Match by email_normalized
            email = person.get("email")
            email_norm = normalize_email(email) if email else None
            if email_norm:
                cur.execute(
                    "SELECT id, title FROM contacts WHERE email_normalized = %s AND company_id = %s",
                    (email_norm, company_id),
                )
                match = cur.fetchone()
                if match:
                    contact_id = match["id"]
                    if match["title"] is None and title:
                        cur.execute(
                            "UPDATE contacts SET title = %s, updated_at = NOW() WHERE id = %s",
                            (title, contact_id),
                        )
                    affected += 1
                    continue

            # Match by (name, company_id)
            name_norm = name.lower().strip()
            cur.execute(
                "SELECT id, title FROM contacts WHERE lower(trim(full_name)) = %s AND company_id = %s",
                (name_norm, company_id),
            )
            match = cur.fetchone()
            if match:
                contact_id = match["id"]
                if match["title"] is None and title:
                    cur.execute(
                        "UPDATE contacts SET title = %s, updated_at = NOW() WHERE id = %s",
                        (title, contact_id),
                    )
                affected += 1
                continue

            # No match — create new contact
            first_name, last_name = split_name(name)
            cur.execute(
                """INSERT INTO contacts
                       (company_id, first_name, last_name, full_name,
                        email, email_normalized, email_status,
                        linkedin_url, linkedin_url_normalized,
                        title, source)
                   VALUES (%s, %s, %s, %s, %s, %s, 'unverified', %s, %s, %s, 'deep_research')
                   ON CONFLICT DO NOTHING
                   RETURNING id""",
                (
                    company_id, first_name, last_name, name,
                    email, email_norm,
                    linkedin_url, linkedin_norm or None,
                    title,
                ),
            )
            if cur.fetchone():
                affected += 1

        conn.commit()

    return affected


# ---------------------------------------------------------------------------
# Previous Score Lookup
# ---------------------------------------------------------------------------


def _get_previous_crypto_score(conn, company_id: int) -> int | None:
    """Retrieve the most recent crypto score for a company from bulk research.

    Checks research_results by company_id first, falls back to company_name match.
    Returns None if no prior score exists.
    """
    with get_cursor(conn) as cur:
        # Try by company_id directly
        cur.execute(
            """SELECT crypto_score FROM research_results
               WHERE company_id = %s AND status = 'completed'
               ORDER BY created_at DESC LIMIT 1""",
            (company_id,),
        )
        row = cur.fetchone()
        if row and row["crypto_score"] is not None:
            return row["crypto_score"]

        # Fallback: match by company_name via companies table
        cur.execute(
            """SELECT rr.crypto_score
               FROM research_results rr
               JOIN companies c ON lower(trim(rr.company_name)) = c.name_normalized
               WHERE c.id = %s AND rr.status = 'completed'
               ORDER BY rr.created_at DESC LIMIT 1""",
            (company_id,),
        )
        row = cur.fetchone()
        if row and row["crypto_score"] is not None:
            return row["crypto_score"]

    return None


# ---------------------------------------------------------------------------
# Cost Estimation
# ---------------------------------------------------------------------------


def estimate_cost(is_us_based: bool) -> dict:
    """Estimate cost for a deep research run.

    US-based companies get 6 queries (includes SEC filing search),
    all others get 5.
    """
    query_count = 6 if is_us_based else 5
    cost = query_count * COST_PERPLEXITY_QUERY + COST_SONNET_SYNTHESIS
    return {
        "cost_estimate_usd": round(cost, 4),
        "query_count": query_count,
    }


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
    try:
        run_migrations(conn)

        keys = api_keys or {}
        if not keys.get("perplexity"):
            import os
            keys["perplexity"] = os.getenv("PERPLEXITY_API_KEY", "")
        if not keys.get("anthropic"):
            import os
            keys["anthropic"] = os.getenv("ANTHROPIC_API_KEY", "")

        _execute_deep_research(conn, deep_research_id, keys)
    except Exception as e:
        logger.exception("Deep research %d failed", deep_research_id)
        try:
            _update_status(conn, deep_research_id, "failed", error_message=str(e))
        except Exception:
            logger.exception("Failed to update deep research %d status", deep_research_id)
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
        _update_status(conn, deep_research_id, "failed", error_message="PERPLEXITY_API_KEY not configured")
        return
    if not anthropic_key:
        _update_status(conn, deep_research_id, "failed", error_message="ANTHROPIC_API_KEY not configured")
        return

    # --- Phase 1: Parallel Perplexity queries ---
    _update_status(conn, deep_research_id, "researching")

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
    if _is_cancelled(conn, deep_research_id):
        _update_status(
            conn, deep_research_id, "cancelled",
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
            raw_queries=query_results,
            actual_cost_usd=round(total_cost, 4),
            query_count=len(queries),
            error_message=f"Only {len(successful)} of {len(queries)} queries succeeded (minimum 2 required)",
        )
        return

    # --- Phase 2: Sonnet synthesis ---
    _update_status(
        conn, deep_research_id, "synthesizing",
        raw_queries=query_results,
        actual_cost_usd=round(total_cost, 4),
        query_count=len(queries),
    )

    # Fetch any prior bulk research data for this company
    bulk_research = None
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT web_search_raw, website_crawl_raw
               FROM research_results
               WHERE company_id = %s AND status = 'completed'
               ORDER BY created_at DESC LIMIT 1""",
            (company_id,),
        )
        bulk_research = cur.fetchone()

    synthesis = _synthesize_with_sonnet(query_results, company_name, bulk_research, anthropic_key)
    total_cost += COST_SONNET_SYNTHESIS

    # Check cancellation after synthesis
    if _is_cancelled(conn, deep_research_id):
        _update_status(
            conn, deep_research_id, "cancelled",
            actual_cost_usd=round(total_cost, 4),
        )
        return

    # --- Phase 3: Enrich contacts + snapshot previous score ---
    previous_score = _get_previous_crypto_score(conn, company_id)

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

    # --- Final update ---
    _update_status(
        conn, deep_research_id, "completed",
        raw_queries=query_results,
        company_overview=synthesis.get("company_overview"),
        crypto_signals=synthesis.get("crypto_signals"),
        key_people=key_people,
        talking_points=synthesis.get("talking_points"),
        risk_factors=synthesis.get("risk_factors"),
        updated_crypto_score=validated_score,
        confidence=synthesis.get("confidence"),
        actual_cost_usd=round(total_cost, 4),
        query_count=len(queries),
        previous_crypto_score=previous_score,
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
