"""Deep research — Sonnet synthesis, contact enrichment, previous score lookup."""

from __future__ import annotations

import json
import logging
import re

import httpx

from src.models.database import get_cursor
from src.services.normalization_utils import (
    normalize_email,
    normalize_linkedin_url,
    split_name,
)
from src.services.deep_research_queries import DEEP_RESEARCH_MODEL, SYNTHESIS_PROMPT

logger = logging.getLogger(__name__)


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
        web_search_raw = (bulk_research.get("web_search_raw") or "")[:8000]
        website_crawl_raw = (bulk_research.get("website_crawl_raw") or "")[:8000]

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
        except (httpx.HTTPError, httpx.TimeoutException, OSError) as exc:
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
                    "SELECT id, title FROM contacts WHERE linkedin_url_normalized = %s AND company_id = %s AND user_id = %s",
                    (linkedin_norm, company_id, user_id),
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
                    "SELECT id, title FROM contacts WHERE email_normalized = %s AND company_id = %s AND user_id = %s",
                    (email_norm, company_id, user_id),
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
                "SELECT id, title FROM contacts WHERE lower(trim(full_name)) = %s AND company_id = %s AND user_id = %s",
                (name_norm, company_id, user_id),
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

            # Validate LLM-supplied email and linkedin_url
            if email and not ("@" in email and "." in email.split("@")[-1]):
                email = None
                email_norm = None
            if linkedin_url and not (
                linkedin_url.startswith("https://linkedin.com/in/")
                or linkedin_url.startswith("https://www.linkedin.com/in/")
            ):
                linkedin_url = None
                linkedin_norm = ""

            # No match — create new contact
            first_name, last_name = split_name(name)
            cur.execute(
                """INSERT INTO contacts
                       (company_id, first_name, last_name, full_name,
                        email, email_normalized, email_status,
                        linkedin_url, linkedin_url_normalized,
                        title, source, user_id)
                   VALUES (%s, %s, %s, %s, %s, %s, 'unverified', %s, %s, %s, 'deep_research', %s)
                   ON CONFLICT DO NOTHING
                   RETURNING id""",
                (
                    company_id, first_name, last_name, name,
                    email, email_norm,
                    linkedin_url, linkedin_norm or None,
                    title, user_id,
                ),
            )
            if cur.fetchone():
                affected += 1

        conn.commit()

    return affected


# ---------------------------------------------------------------------------
# Previous Score Lookup
# ---------------------------------------------------------------------------


def _get_previous_crypto_score(conn, company_id: int, *, user_id: int) -> int | None:
    """Retrieve the most recent crypto score for a company from bulk research.

    Checks research_results by company_id first, falls back to company_name match.
    Returns None if no prior score exists.
    """
    with get_cursor(conn) as cur:
        # Try by company_id directly (scoped via research_jobs.user_id)
        cur.execute(
            """SELECT rr.crypto_score FROM research_results rr
               JOIN research_jobs rj ON rj.id = rr.job_id
               WHERE rr.company_id = %s AND rr.status = 'completed' AND rj.user_id = %s
               ORDER BY rr.created_at DESC LIMIT 1""",
            (company_id, user_id),
        )
        row = cur.fetchone()
        if row and row["crypto_score"] is not None:
            return row["crypto_score"]

        # Fallback: match by company_name via companies table
        cur.execute(
            """SELECT rr.crypto_score
               FROM research_results rr
               JOIN research_jobs rj ON rj.id = rr.job_id
               JOIN companies c ON lower(trim(rr.company_name)) = c.name_normalized
               WHERE c.id = %s AND rr.status = 'completed' AND rj.user_id = %s
               ORDER BY rr.created_at DESC LIMIT 1""",
            (company_id, user_id),
        )
        row = cur.fetchone()
        if row and row["crypto_score"] is not None:
            return row["crypto_score"]

    return None
