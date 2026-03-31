"""Deep research — query construction, Perplexity API, signal extraction, cost estimation."""

from __future__ import annotations

import json
import logging
import re
import time

import httpx

from src.constants import LLM_MODELS

logger = logging.getLogger(__name__)

DEEP_RESEARCH_MODEL = LLM_MODELS["deep_research"]

_HIGH_RECENCY_PATTERNS = re.compile(
    r"\b(just|recently|this week|this month|announced|launching|new fund|"
    r"newly appointed|breaking|latest|upcoming|imminent|days ago)\b",
    re.IGNORECASE,
)
_MEDIUM_RECENCY_PATTERNS = re.compile(
    r"\b(this year|this quarter|2026|2025|recent|last month|q[1-4]\b)",
    re.IGNORECASE,
)
_LOW_RECENCY_PATTERNS = re.compile(
    r"\b(historically|has been|tradition|long.?standing|for years|established)\b",
    re.IGNORECASE,
)

_SIGNAL_TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("fund_raise", re.compile(r"\b(fund\s*rais|raised|new fund|launch.{0,20}fund|capital raise|close[ds]?\s+\$)", re.IGNORECASE)),
    ("key_hire", re.compile(r"\b(hired|appoint|new\s+(?:cio|cfo|head|director|partner|managing)|joined as|promotion)\b", re.IGNORECASE)),
    ("crypto_allocation", re.compile(r"\b(allocat|bitcoin|crypto.{0,15}portfolio|digital asset.{0,15}invest|blockchain.{0,15}fund)\b", re.IGNORECASE)),
    ("portfolio_move", re.compile(r"\b(acqui|divest|portfolio.{0,10}move|exit|new position|stake in|increased.{0,10}holding)\b", re.IGNORECASE)),
    ("conference", re.compile(r"\b(conference|summit|panel|speak|keynote|event|forum|symposium)\b", re.IGNORECASE)),
]

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
# Fund Signal Extraction
# ---------------------------------------------------------------------------


def _recency_score(text: str) -> float:
    if _HIGH_RECENCY_PATTERNS.search(text):
        return 0.9
    if _MEDIUM_RECENCY_PATTERNS.search(text):
        return 0.6
    if _LOW_RECENCY_PATTERNS.search(text):
        return 0.2
    return 0.4


def _detect_signal_type(text: str) -> str:
    for signal_type, pattern in _SIGNAL_TYPE_PATTERNS:
        if pattern.search(text):
            return signal_type
    return "general"


def _extract_fund_signals(research_result: dict) -> list[dict]:
    """Extract time-sensitive fund intelligence signals from synthesis output.

    Scans crypto_signals and talking_points for actionable, time-sensitive
    items like fund raises, key hires, crypto allocations, portfolio moves,
    and conference attendance.
    """
    signals: list[dict] = []
    seen_texts: set[str] = set()

    crypto_signals = research_result.get("crypto_signals") or []
    if isinstance(crypto_signals, list):
        for entry in crypto_signals:
            if not isinstance(entry, dict):
                continue
            text = (entry.get("quote") or "").strip()
            if not text or text.lower() in seen_texts:
                continue
            signal_type = _detect_signal_type(text)
            if signal_type == "general" and (entry.get("relevance") or "").lower() == "low":
                continue
            seen_texts.add(text.lower())
            signals.append({
                "type": signal_type,
                "text": text,
                "recency_score": _recency_score(text),
            })

    talking_points = research_result.get("talking_points") or []
    if isinstance(talking_points, list):
        for entry in talking_points:
            if not isinstance(entry, dict):
                continue
            hook = (entry.get("hook_type") or "")
            if hook not in ("event_hook", "portfolio_move", "team_signal"):
                continue
            text = (entry.get("text") or "").strip()
            if not text or text.lower() in seen_texts:
                continue
            signal_type = _detect_signal_type(text)
            if signal_type == "general":
                type_map = {
                    "event_hook": "conference",
                    "portfolio_move": "portfolio_move",
                    "team_signal": "key_hire",
                }
                signal_type = type_map.get(hook, "general")
            seen_texts.add(text.lower())
            signals.append({
                "type": signal_type,
                "text": text,
                "recency_score": _recency_score(text),
            })

    signals.sort(key=lambda s: s["recency_score"], reverse=True)
    return signals


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
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, OSError) as exc:
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
