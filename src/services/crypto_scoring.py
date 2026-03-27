"""Crypto interest scoring and classification.

Classifies companies' crypto/digital asset investment interest using
Claude Haiku. Extracted from crypto_research.py.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

# These are imported from the main module at call time; kept as module-level
# for the same pattern used by crypto_research.py.
ANTHROPIC_API_KEY = ""
CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

# Cost estimates
COST_LLM = 0.001


def _get_anthropic_key() -> str:
    """Return the current API key (may be overridden at runtime)."""
    from src.services.crypto_research import ANTHROPIC_API_KEY as _key
    return _key


def classify_crypto_interest(
    company_name: str, web_data: str, crawl_data: str
) -> dict:
    """Classify a company's crypto interest using Claude Haiku."""
    api_key = _get_anthropic_key()
    if not api_key:
        return {
            "crypto_score": 0,
            "category": "no_signal",
            "evidence_summary": "ANTHROPIC_API_KEY not configured",
            "evidence": [],
            "reasoning": "Cannot classify without API key",
        }

    research = f"Web search results:\n{web_data}" if web_data else ""
    if crawl_data:
        research += f"\n\nWebsite content:\n{crawl_data}"

    prompt = (
        f"Given the following research about {company_name}, score their crypto/digital asset "
        f"investment interest from 0-100 and categorize them.\n\n"
        f"Scoring guide:\n"
        f"- 80-100: confirmed_investor (clear evidence of crypto investments)\n"
        f"- 60-79: likely_interested (strong signals like crypto hires, conference presence)\n"
        f"- 40-59: possible (some indirect signals)\n"
        f"- 20-39: no_signal (no relevant evidence found)\n"
        f"- 0-19: unlikely (traditional-only fund, anti-crypto statements)\n\n"
        f"Research:\n{research}\n\n"
        f"Return valid JSON only with these keys:\n"
        f'{{"crypto_score": <0-100>, "category": "<category>", '
        f'"evidence_summary": "<2-3 sentence summary>", '
        f'"evidence": [{{"source": "<source>", "quote": "<quote>", "relevance": "<high/medium/low>"}}], '
        f'"reasoning": "<your reasoning>"}}'
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
                "model": CLASSIFIER_MODEL,
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"]
        # Extract JSON from markdown code fences if present
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        # Also try extracting first { ... } block if response has preamble text
        elif not text.strip().startswith("{"):
            brace_match = re.search(r"\{.*\}", text, re.DOTALL)
            if brace_match:
                text = brace_match.group(0)
        return json.loads(text)
    except (json.JSONDecodeError, KeyError):
        logger.warning("Failed to parse classification for %s: %s", company_name, text[:200] if 'text' in dir() else "no text")
        return {
            "crypto_score": 20,
            "category": "no_signal",
            "evidence_summary": "Classification parsing failed",
            "evidence": [],
            "reasoning": "Could not parse LLM response",
        }
    except Exception:
        logger.exception("Classification failed for %s", company_name)
        return {
            "crypto_score": 0,
            "category": "no_signal",
            "evidence_summary": "Classification request failed",
            "evidence": [],
            "reasoning": "API call failed",
        }


def estimate_job_cost(company_count: int, method: str) -> dict:
    """Estimate cost for a research job."""
    from src.services.crypto_web_scraper import COST_WEB_SEARCH, COST_CRAWL
    from src.services.crypto_research import COST_CONTACT_DISCOVERY

    web_search_cost = company_count * COST_WEB_SEARCH if method in ("web_search", "hybrid") else 0
    crawl_cost = company_count * COST_CRAWL if method in ("website_crawl", "hybrid") else 0
    llm_cost = company_count * COST_LLM
    contact_discovery_cost = company_count * COST_CONTACT_DISCOVERY
    total = web_search_cost + crawl_cost + llm_cost + contact_discovery_cost

    return {
        "web_search_cost": round(web_search_cost, 4),
        "crawl_cost": round(crawl_cost, 4),
        "llm_cost": round(llm_cost, 4),
        "contact_discovery_cost": round(contact_discovery_cost, 4),
        "total": round(total, 4),
    }
