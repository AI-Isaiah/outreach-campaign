"""Web search and website crawling for crypto research.

Handles Perplexity API web searches and website content crawling.
Extracted from crypto_research.py.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

# Cost estimates
COST_WEB_SEARCH = 0.005
COST_CRAWL = 0.0


def _get_perplexity_key(api_keys: dict | None = None) -> str:
    """Return the Perplexity API key from the provided dict or environment."""
    if api_keys and api_keys.get("perplexity"):
        return api_keys["perplexity"]
    import os
    return os.getenv("PERPLEXITY_API_KEY", "")


def research_company_web_search(company_name: str, website: str | None, api_keys: dict | None = None) -> str:
    """Research a company's crypto interest via Perplexity sonar."""
    api_key = _get_perplexity_key(api_keys)
    if not api_key:
        return json.dumps({"error": "PERPLEXITY_API_KEY not configured"})

    site_info = f"({website})" if website else "(no website)"
    prompt = (
        f"Research whether {company_name} {site_info} invests in or has interest in "
        f"cryptocurrency, digital assets, blockchain, or related technologies. "
        f"Look for: public statements, portfolio investments in crypto, participation "
        f"in fund raises, team members with crypto backgrounds, conference presence, "
        f"regulatory filings. Provide specific evidence with sources."
    )

    try:
        resp = httpx.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sonar",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise  # Let caller handle rate limiting
        logger.exception("Perplexity API error for %s", company_name)
        return json.dumps({"error": f"API error: {e.response.status_code}"})
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
        logger.exception("Perplexity research failed for %s: %s", company_name, exc)
        return json.dumps({"error": "Research request failed"})


def crawl_company_website(website: str, max_pages: int = 5) -> str:
    """Crawl a company website for crypto-related content."""
    if not website:
        return ""

    base = website.rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"

    paths = ["", "/about", "/team", "/investments", "/portfolio"][:max_pages]
    texts = []

    for path in paths:
        url = f"{base}{path}"
        try:
            resp = httpx.get(
                url,
                timeout=10,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (research bot)"},
            )
            if resp.status_code == 200:
                text = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, flags=re.DOTALL)
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    texts.append(f"[{path or '/'}] {text[:2000]}")
        except (httpx.HTTPError, httpx.TimeoutException):
            continue

    return "\n\n".join(texts)[:10000]


def discover_contacts_at_company(
    company_name: str, website: str | None, api_keys: dict | None = None,
) -> list[dict]:
    """Find decision-makers at a company via Perplexity."""
    api_key = _get_perplexity_key(api_keys)
    if not api_key:
        return []

    site_info = f"({website})" if website else ""
    prompt = (
        f"Find key decision-makers at {company_name} {site_info} involved in investment "
        f"decisions. Look for CIO, Head of Digital Assets, Head of Alternative Investments, "
        f"Portfolio Manager, Partner, Managing Director. Provide: full name, title, email if "
        f"public, LinkedIn URL if available. List up to 5. Return valid JSON array: "
        f'[{{"name": "...", "title": "...", "email": null, "linkedin": null, "source": "..."}}]'
    )

    try:
        resp = httpx.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sonar",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]

        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            contacts = json.loads(match.group())
            return contacts[:5]
        return []
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise
        logger.exception("Contact discovery API error for %s", company_name)
        return []
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
        logger.exception("Contact discovery failed for %s: %s", company_name, exc)
        return []
