"""Crypto interest research pipeline.

Researches companies for crypto/digital asset investment interest using
Perplexity API (web search) and Claude Haiku (classification).

Architecture:
  - parse/preview: CSV handling with flexible column mapping
  - research/crawl/classify/discover: individual API operations
  - find_warm_intros: cross-reference with existing CRM data
  - run_research_job: background orchestrator with cancellation, progress, error recovery
  - cancel/retry: job lifecycle management
  - check_duplicates: prevent re-researching known companies
  - batch_import_and_enroll: complete the Research -> CRM loop

Extracted modules:
  - crypto_scoring.py: classify_crypto_interest, estimate_job_cost
  - crypto_web_scraper.py: research_company_web_search, crawl_company_website,
                           discover_contacts_at_company
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
import threading

import httpx

from src.models.database import get_cursor
from src.services.normalization_utils import normalize_company_name, split_name

# Re-export extracted functions so callers that import from this module still work
from src.services.crypto_scoring import (  # noqa: F401
    classify_crypto_interest,
    estimate_job_cost,
)
from src.services.crypto_web_scraper import (  # noqa: F401
    crawl_company_website,
    discover_contacts_at_company,
    research_company_web_search,
)
from src.services.crypto_web_scraper import (
    COST_WEB_SEARCH,
    COST_CRAWL,
)
from src.services.crypto_scoring import COST_LLM

logger = logging.getLogger(__name__)

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Cost estimates per operation
COST_CONTACT_DISCOVERY = 0.005


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_cancelled(conn, job_id: int) -> bool:
    """Check if job has been cancelled. Called between each company."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT status FROM research_jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
        return row is not None and row["status"] in ("cancelling", "cancelled")


# ---------------------------------------------------------------------------
# CSV Parsing & Preview
# ---------------------------------------------------------------------------

_HEADER_ALIASES = {
    "company_name": ("company_name", "name", "firm_name", "company", "firm"),
    "website": ("website", "url", "company_website", "site"),
    "country": ("country", "location", "region"),
    "aum": ("aum", "aum_millions", "aum_(millions)"),
    "firm_type": ("firm_type", "type", "company_type", "category"),
}


def _build_header_map(fieldnames: list[str]) -> dict[str, str]:
    """Map raw CSV headers to canonical field names."""
    header_map: dict[str, str] = {}
    for h in fieldnames:
        hl = h.strip().lower().replace(" ", "_")
        for canonical, aliases in _HEADER_ALIASES.items():
            if hl in aliases:
                header_map[h] = canonical
                break
    return header_map


def parse_research_csv(csv_content: str) -> list[dict]:
    """Parse CSV with flexible column names.

    Required: company_name (or alias)
    Optional: website, country, aum, firm_type
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    if reader.fieldnames is None:
        return []

    header_map = _build_header_map(reader.fieldnames)

    results = []
    for row in reader:
        mapped = {}
        for orig_key, mapped_key in header_map.items():
            val = (row.get(orig_key) or "").strip()
            if val:
                mapped[mapped_key] = val

        name = mapped.get("company_name")
        if not name:
            continue

        results.append({
            "company_name": name,
            "website": mapped.get("website"),
            "country": mapped.get("country"),
            "aum": mapped.get("aum"),
            "firm_type": mapped.get("firm_type"),
        })

    return results


def preview_research_csv(csv_content: str) -> dict:
    """Preview a CSV: parse, show first 10 rows, column mapping, and stats."""
    companies = parse_research_csv(csv_content)

    has_website = sum(1 for c in companies if c.get("website"))
    has_country = sum(1 for c in companies if c.get("country"))
    has_aum = sum(1 for c in companies if c.get("aum"))

    # Detect raw headers
    reader = csv.DictReader(io.StringIO(csv_content))
    raw_headers = list(reader.fieldnames or [])
    header_map = _build_header_map(raw_headers) if raw_headers else {}

    return {
        "total_rows": len(companies),
        "preview": companies[:10],
        "raw_headers": raw_headers,
        "mapped_headers": header_map,
        "stats": {
            "with_website": has_website,
            "with_country": has_country,
            "with_aum": has_aum,
        },
    }


# ---------------------------------------------------------------------------
# Duplicate Detection
# ---------------------------------------------------------------------------

def check_duplicate_companies(conn, company_names: list[str], user_id: int | None = None) -> dict:
    """Check which companies have already been researched in prior jobs.

    Returns dict with 'already_researched' (list of names) and 'new' (list of names).
    """
    if not company_names:
        return {"already_researched": [], "new": company_names}

    # Use simple lower/trim normalization to match the SQL side
    simple_norm = [n.lower().strip() for n in company_names]
    norm_to_orig = dict(zip(simple_norm, company_names))

    with get_cursor(conn) as cur:
        query = """SELECT DISTINCT regexp_replace(lower(trim(rr.company_name)), '\\s+', ' ', 'g') AS name_norm
               FROM research_results rr
               JOIN research_jobs rj ON rj.id = rr.job_id
               WHERE rj.status IN ('completed', 'researching', 'classifying')
                 AND regexp_replace(lower(trim(rr.company_name)), '\\s+', ' ', 'g') = ANY(%s)"""
        params: list = [simple_norm]
        if user_id is not None:
            query += " AND rj.user_id = %s"
            params.append(user_id)
        cur.execute(query, params)
        existing = {row["name_norm"] for row in cur.fetchall()}

    already = [norm_to_orig[n] for n in simple_norm if n in existing]
    new = [norm_to_orig[n] for n in simple_norm if n not in existing]

    return {"already_researched": already, "new": new}


# ---------------------------------------------------------------------------
# Warm Intros
# ---------------------------------------------------------------------------

def find_warm_intros(conn, company_name: str, company_id: int | None) -> dict:
    """Find existing contacts at the same or related company."""
    contact_ids = []
    notes_parts = []

    with get_cursor(conn) as cur:
        if company_id:
            cur.execute(
                """SELECT id, full_name, email, title
                   FROM contacts WHERE company_id = %s""",
                (company_id,),
            )
            for row in cur.fetchall():
                contact_ids.append(row["id"])
                notes_parts.append(
                    f"Direct contact: {row['full_name']} ({row.get('title') or 'no title'})"
                )

        name_norm = normalize_company_name(company_name)
        cur.execute(
            """SELECT c.id, c.full_name, c.title, co.name AS company_name
               FROM contacts c
               JOIN companies co ON co.id = c.company_id
               WHERE co.name_normalized = %s
                 AND c.id != ALL(%s)""",
            (name_norm, contact_ids or [0]),
        )
        for row in cur.fetchall():
            contact_ids.append(row["id"])
            notes_parts.append(
                f"Name match: {row['full_name']} at {row['company_name']}"
            )

        if company_id:
            cur.execute(
                """SELECT DISTINCT c.id, c.full_name, co.name AS company_name
                   FROM contacts c
                   JOIN companies co ON co.id = c.company_id
                   JOIN contact_campaign_status ccs ON ccs.contact_id = c.id
                   WHERE ccs.status = 'replied_positive'
                     AND co.firm_type = (
                         SELECT firm_type FROM companies WHERE id = %s
                     )
                     AND c.id != ALL(%s)
                   LIMIT 5""",
                (company_id, contact_ids or [0]),
            )
            for row in cur.fetchall():
                notes_parts.append(
                    f"Warm lead at similar firm: {row['full_name']} ({row['company_name']})"
                )

    return {
        "contact_ids": contact_ids,
        "notes": "\n".join(notes_parts) if notes_parts else None,
    }


# ---------------------------------------------------------------------------
# Shared Contact Import Helper
# ---------------------------------------------------------------------------

def resolve_or_create_company(cur, company_name: str, user_id: int | None = None) -> int:
    """Find existing company by normalized name or create a new one. Returns company_id."""
    if not company_name or not company_name.strip():
        raise ValueError("company_name must be a non-empty string")
    name_norm = normalize_company_name(company_name)
    if user_id is not None:
        cur.execute(
            "SELECT id FROM companies WHERE name_normalized = %s AND user_id = %s",
            (name_norm, user_id),
        )
    else:
        cur.execute(
            "SELECT id FROM companies WHERE name_normalized = %s",
            (name_norm,),
        )
    match = cur.fetchone()
    if match:
        return match["id"]
    if user_id is not None:
        cur.execute(
            "INSERT INTO companies (name, name_normalized, user_id) VALUES (%s, %s, %s) RETURNING id",
            (company_name, name_norm, user_id),
        )
    else:
        cur.execute(
            "INSERT INTO companies (name, name_normalized) VALUES (%s, %s) RETURNING id",
            (company_name, name_norm),
        )
    return cur.fetchone()["id"]


def import_single_contact(cur, contact: dict, company_id: int, user_id: int | None = None) -> int | None:
    """Import a single discovered contact. Returns contact_id or None if skipped."""
    name = (contact.get("name") or "").strip()
    if not name:
        return None

    first_name, last_name = split_name(name)

    email = contact.get("email")
    email_norm = email.strip().lower() if email else None
    linkedin = contact.get("linkedin")
    linkedin_norm = linkedin.rstrip("/").lower() if linkedin else None

    cur.execute(
        """INSERT INTO contacts
               (company_id, first_name, last_name, full_name,
                email, email_normalized, email_status,
                linkedin_url, linkedin_url_normalized,
                title, source, user_id)
           VALUES (%s, %s, %s, %s, %s, %s, 'unverified', %s, %s, %s, 'research', %s)
           ON CONFLICT DO NOTHING
           RETURNING id""",
        (
            company_id, first_name, last_name, name,
            email, email_norm,
            linkedin, linkedin_norm,
            contact.get("title"), user_id,
        ),
    )
    row = cur.fetchone()
    if row:
        return row["id"]
    # Conflict -- look up the existing contact so we can still enroll them
    if email_norm:
        cur.execute("SELECT id FROM contacts WHERE email_normalized = %s", (email_norm,))
        existing = cur.fetchone()
        if existing:
            return existing["id"]
    if linkedin_norm:
        cur.execute("SELECT id FROM contacts WHERE linkedin_url_normalized = %s", (linkedin_norm,))
        existing = cur.fetchone()
        if existing:
            return existing["id"]
    return None


# ---------------------------------------------------------------------------
# Batch Import + Deal Creation + Campaign Enrollment
# ---------------------------------------------------------------------------

def batch_import_and_enroll(
    conn,
    result_ids: list[int],
    create_deals: bool = False,
    campaign_name: str | None = None,
    user_id: int | None = None,
) -> dict:
    """Import discovered contacts, optionally create deals and enroll in campaign.

    This completes the Research -> CRM loop in one operation.
    """
    from src.models.campaigns import enroll_contact, get_campaign_by_name
    from datetime import date

    imported_contacts = 0
    deals_created = 0
    enrolled = 0
    skipped = 0

    campaign_id = None
    if campaign_name:
        camp = get_campaign_by_name(conn, campaign_name, user_id=user_id)
        if camp:
            campaign_id = camp["id"]

    with get_cursor(conn) as cur:
        try:
            # Batch fetch all results in one query (avoid N+1)
            if not result_ids:
                return {"imported_contacts": 0, "deals_created": 0, "enrolled": 0,
                        "skipped_duplicates": 0, "results_processed": 0}

            cur.execute(
                """SELECT rr.id, rr.company_id, rr.company_name, rr.crypto_score,
                          rr.evidence_summary, rr.discovered_contacts_json
                   FROM research_results rr
                   JOIN research_jobs rj ON rj.id = rr.job_id
                   WHERE rr.id = ANY(%s) AND rj.user_id = %s""",
                (result_ids, user_id),
            )
            results = [dict(row) for row in cur.fetchall()]

            for result in results:
                contacts_json = result.get("discovered_contacts_json")
                if not contacts_json:
                    continue

                discovered = (
                    contacts_json if isinstance(contacts_json, list)
                    else json.loads(contacts_json)
                )

                # Resolve company
                company_id = result["company_id"]
                if not company_id:
                    company_id = resolve_or_create_company(cur, result["company_name"], user_id=user_id)
                    cur.execute(
                        "UPDATE research_results SET company_id = %s WHERE id = %s",
                        (company_id, result["id"]),
                    )

                # Create deal if requested
                if create_deals and company_id:
                    cur.execute(
                        """INSERT INTO deals (company_id, title, stage, notes, user_id)
                           VALUES (%s, %s, 'cold', %s, %s) RETURNING id""",
                        (
                            company_id,
                            f"Research: {result['company_name']}",
                            f"Crypto score: {result.get('crypto_score', '?')}/100 - "
                            f"{result.get('evidence_summary', '')}",
                            user_id,
                        ),
                    )
                    deal_id = cur.fetchone()["id"]
                    cur.execute(
                        "INSERT INTO deal_stage_log (deal_id, to_stage) VALUES (%s, 'cold')",
                        (deal_id,),
                    )
                    deals_created += 1

                # Import contacts
                for contact in discovered:
                    contact_id = import_single_contact(cur, contact, company_id, user_id=user_id)
                    if contact_id is None:
                        skipped += 1
                        continue

                    imported_contacts += 1

                    if campaign_id:
                        try:
                            enroll_contact(
                                conn, contact_id, campaign_id,
                                next_action_date=date.today().isoformat(),
                                user_id=user_id,
                            )
                            enrolled += 1
                        except Exception:
                            pass

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "imported_contacts": imported_contacts,
        "deals_created": deals_created,
        "enrolled": enrolled,
        "skipped_duplicates": skipped,
        "results_processed": len(results),
    }


# ---------------------------------------------------------------------------
# Job Status Management
# ---------------------------------------------------------------------------

def _update_job_status(conn, job_id: int, status: str, **kwargs):
    """Update a research job's status and optional fields."""
    sets = ["status = %s", "updated_at = NOW()"]
    vals = [status]

    for key in ("processed_companies", "classified_companies", "contacts_discovered",
                "error_message", "actual_cost_usd"):
        if key in kwargs:
            sets.append(f"{key} = %s")
            vals.append(kwargs[key])

    if status == "researching" and "started_at" not in kwargs:
        sets.append("started_at = COALESCE(started_at, NOW())")
    if status in ("completed", "failed", "cancelled"):
        sets.append("completed_at = NOW()")

    vals.append(job_id)
    with get_cursor(conn) as cur:
        cur.execute(
            f"UPDATE research_jobs SET {', '.join(sets)} WHERE id = %s",
            vals,
        )
        conn.commit()


def cancel_research_job(conn, job_id: int) -> dict:
    """Request cancellation of a running job.

    Sets status to 'cancelling'. The background thread will detect this
    and stop after the current company finishes.
    """
    with get_cursor(conn) as cur:
        cur.execute("SELECT status FROM research_jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "Job not found"}

        if row["status"] in ("completed", "failed", "cancelled"):
            return {"success": False, "error": f"Job already {row['status']}"}

        cur.execute(
            """UPDATE research_jobs
               SET status = 'cancelling', updated_at = NOW()
               WHERE id = %s""",
            (job_id,),
        )
        conn.commit()
        return {"success": True, "status": "cancelling"}


def retry_failed_results(job_id: int, db_url: str, api_keys: dict | None = None) -> None:
    """Retry all errored results in a job. Runs in background thread."""
    from src.models.database import get_connection, run_migrations, get_cursor

    _apply_api_keys(api_keys)
    conn = get_connection(db_url)
    try:
        run_migrations(conn)

        with get_cursor(conn) as cur:
            cur.execute("SELECT * FROM research_jobs WHERE id = %s", (job_id,))
            job = cur.fetchone()
            if not job or job["status"] not in ("completed", "failed"):
                return
            method = job["method"]

            # Reset errored results to pending
            cur.execute(
                """UPDATE research_results SET status = 'pending', updated_at = NOW()
                   WHERE job_id = %s AND status = 'error'""",
                (job_id,),
            )
            conn.commit()

            # Load only the reset results
            cur.execute(
                """SELECT * FROM research_results
                   WHERE job_id = %s AND status = 'pending' ORDER BY id""",
                (job_id,),
            )
            results = [dict(row) for row in cur.fetchall()]

        if not results:
            return

        _update_job_status(conn, job_id, "researching")

        actual_cost = job["actual_cost_usd"] or 0.0

        for i, result in enumerate(results):
            if _is_cancelled(conn, job_id):
                _update_job_status(conn, job_id, "cancelled")
                return

            try:
                _research_single_company(conn, result, method)
                actual_cost += COST_WEB_SEARCH
            except Exception as exc:
                _mark_result_error(conn, result["id"], str(exc))
                continue

            try:
                _classify_single_company(conn, result)
                actual_cost += COST_LLM
            except Exception:
                pass

            try:
                discovered = discover_contacts_at_company(
                    result["company_name"], result.get("company_website")
                )
                actual_cost += COST_CONTACT_DISCOVERY
                warm = find_warm_intros(conn, result["company_name"], result.get("company_id"))

                with get_cursor(conn) as cur:
                    cur.execute(
                        """UPDATE research_results
                           SET discovered_contacts_json = %s,
                               warm_intro_contact_ids = %s, warm_intro_notes = %s,
                               status = 'completed', updated_at = NOW()
                           WHERE id = %s""",
                        (
                            json.dumps(discovered) if discovered else None,
                            warm["contact_ids"] or None,
                            warm["notes"],
                            result["id"],
                        ),
                    )
                    conn.commit()
            except Exception:
                pass

            _update_job_status(
                conn, job_id, "researching",
                actual_cost_usd=round(actual_cost, 4),
            )
            if i < len(results) - 1:
                time.sleep(0.5)

        # Recount totals
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT
                       COUNT(*) FILTER (WHERE status != 'pending') AS processed,
                       COUNT(*) FILTER (WHERE crypto_score IS NOT NULL) AS classified,
                       COUNT(*) FILTER (WHERE discovered_contacts_json IS NOT NULL) AS with_contacts
                   FROM research_results WHERE job_id = %s""",
                (job_id,),
            )
            counts = cur.fetchone()

        _update_job_status(
            conn, job_id, "completed",
            processed_companies=counts["processed"],
            classified_companies=counts["classified"],
            actual_cost_usd=round(actual_cost, 4),
        )

    except Exception as e:
        logger.exception("Retry job %d failed", job_id)
        try:
            _update_job_status(conn, job_id, "failed", error_message=f"Retry failed: {e}")
        except Exception:
            pass
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Background Job Orchestrator
# ---------------------------------------------------------------------------

def _apply_api_keys(api_keys: dict | None) -> None:
    """Override module-level API keys for the current thread's job."""
    global PERPLEXITY_API_KEY, ANTHROPIC_API_KEY
    if api_keys:
        if api_keys.get("perplexity"):
            PERPLEXITY_API_KEY = api_keys["perplexity"]
        if api_keys.get("anthropic"):
            ANTHROPIC_API_KEY = api_keys["anthropic"]


def run_research_job(job_id: int, db_url: str, api_keys: dict | None = None) -> None:
    """Background thread entry point for running a research job."""
    from src.models.database import get_connection, run_migrations

    _apply_api_keys(api_keys)
    conn = get_connection(db_url)
    try:
        run_migrations(conn)
        _execute_research_job(conn, job_id)
    except Exception as e:
        logger.exception("Research job %d failed", job_id)
        try:
            _update_job_status(conn, job_id, "failed", error_message=str(e))
        except Exception:
            logger.exception("Failed to update job %d status", job_id)
    finally:
        conn.close()


def _execute_research_job(conn, job_id: int) -> None:
    """Run the full research pipeline for a job."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT * FROM research_jobs WHERE id = %s", (job_id,))
        job = cur.fetchone()
        if not job:
            return
        method = job["method"]

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM research_results WHERE job_id = %s ORDER BY id",
            (job_id,),
        )
        results = [dict(row) for row in cur.fetchall()]

    if not results:
        _update_job_status(conn, job_id, "completed")
        return

    actual_cost = 0.0

    # Phase 1: Research
    _update_job_status(conn, job_id, "researching")
    for i, result in enumerate(results):
        # Check cancellation before each company
        if _is_cancelled(conn, job_id):
            _update_job_status(conn, job_id, "cancelled",
                               actual_cost_usd=round(actual_cost, 4))
            return

        try:
            _research_single_company(conn, result, method)
            actual_cost += COST_WEB_SEARCH if method in ("web_search", "hybrid") else 0
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                for wait in (2, 5, 10, 30):
                    time.sleep(wait)
                    if _is_cancelled(conn, job_id):
                        _update_job_status(conn, job_id, "cancelled")
                        return
                    try:
                        _research_single_company(conn, result, method)
                        actual_cost += COST_WEB_SEARCH
                        break
                    except httpx.HTTPStatusError:
                        continue
                else:
                    _mark_result_error(conn, result["id"], "Rate limited")
                    result["_errored"] = True
        except Exception as exc:
            logger.warning("Research error for %s: %s", result["company_name"], exc)
            _mark_result_error(conn, result["id"], str(exc))
            result["_errored"] = True

        _update_job_status(
            conn, job_id, "researching",
            processed_companies=i + 1,
            actual_cost_usd=round(actual_cost, 4),
        )
        if i < len(results) - 1:
            time.sleep(0.5)

    # Phase 2: Classification
    _update_job_status(conn, job_id, "classifying")
    for i, result in enumerate(results):
        if _is_cancelled(conn, job_id):
            _update_job_status(conn, job_id, "cancelled",
                               actual_cost_usd=round(actual_cost, 4))
            return

        if result.get("_errored"):
            continue
        try:
            _classify_single_company(conn, result)
            actual_cost += COST_LLM
        except Exception as exc:
            logger.warning("Classification error for %s: %s", result["company_name"], exc)

        _update_job_status(
            conn, job_id, "classifying",
            classified_companies=i + 1,
            actual_cost_usd=round(actual_cost, 4),
        )

    # Phase 3: Contact discovery + warm intros
    contacts_found = 0
    for result in results:
        if _is_cancelled(conn, job_id):
            _update_job_status(conn, job_id, "cancelled",
                               actual_cost_usd=round(actual_cost, 4))
            return

        if result.get("_errored"):
            continue
        try:
            discovered = discover_contacts_at_company(
                result["company_name"], result.get("company_website")
            )
            actual_cost += COST_CONTACT_DISCOVERY

            warm = find_warm_intros(conn, result["company_name"], result.get("company_id"))

            with get_cursor(conn) as cur:
                cur.execute(
                    """UPDATE research_results
                       SET discovered_contacts_json = %s,
                           warm_intro_contact_ids = %s,
                           warm_intro_notes = %s,
                           status = 'completed',
                           updated_at = NOW()
                       WHERE id = %s""",
                    (
                        json.dumps(discovered) if discovered else None,
                        warm["contact_ids"] or None,
                        warm["notes"],
                        result["id"],
                    ),
                )
                conn.commit()

            if discovered:
                contacts_found += len(discovered)

            time.sleep(0.5)
        except httpx.HTTPStatusError:
            time.sleep(5)
        except Exception as exc:
            logger.warning("Contact discovery error for %s: %s", result["company_name"], exc)

    _update_job_status(
        conn, job_id, "completed",
        contacts_discovered=contacts_found,
        actual_cost_usd=round(actual_cost, 4),
    )


def _research_single_company(conn, result: dict, method: str) -> None:
    """Run web search and/or crawl for a single company."""
    web_raw = None
    crawl_raw = None

    if method in ("web_search", "hybrid"):
        web_raw = research_company_web_search(
            result["company_name"], result.get("company_website")
        )
    if method in ("website_crawl", "hybrid") and result.get("company_website"):
        crawl_raw = crawl_company_website(result["company_website"])

    result["web_search_raw"] = web_raw
    result["website_crawl_raw"] = crawl_raw

    with get_cursor(conn) as cur:
        cur.execute(
            """UPDATE research_results
               SET web_search_raw = %s, website_crawl_raw = %s,
                   status = 'researching', updated_at = NOW()
               WHERE id = %s""",
            (web_raw, crawl_raw, result["id"]),
        )
        conn.commit()


def _classify_single_company(conn, result: dict) -> None:
    """Classify a single company's crypto interest."""
    classification = classify_crypto_interest(
        result["company_name"],
        result.get("web_search_raw") or "",
        result.get("website_crawl_raw") or "",
    )

    with get_cursor(conn) as cur:
        cur.execute(
            """UPDATE research_results
               SET crypto_score = %s, category = %s,
                   evidence_summary = %s, evidence_json = %s,
                   classification_reasoning = %s,
                   status = 'classified', updated_at = NOW()
               WHERE id = %s""",
            (
                classification.get("crypto_score", 0),
                classification.get("category", "no_signal"),
                classification.get("evidence_summary"),
                json.dumps(classification.get("evidence", [])),
                classification.get("reasoning"),
                result["id"],
            ),
        )
        conn.commit()


def _mark_result_error(conn, result_id: int, error: str) -> None:
    """Mark a single result as errored."""
    with get_cursor(conn) as cur:
        try:
            cur.execute(
                """UPDATE research_results
                   SET status = 'error', classification_reasoning = %s, updated_at = NOW()
                   WHERE id = %s""",
                (f"Error: {error}", result_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()


def start_research_job_background(job_id: int, db_url: str, api_keys: dict | None = None) -> None:
    """Spawn a background thread to run the research job."""
    thread = threading.Thread(
        target=run_research_job,
        args=(job_id, db_url, api_keys),
        daemon=True,
        name=f"research-job-{job_id}",
    )
    thread.start()


def start_retry_background(job_id: int, db_url: str, api_keys: dict | None = None) -> None:
    """Spawn a background thread to retry failed results."""
    thread = threading.Thread(
        target=retry_failed_results,
        args=(job_id, db_url, api_keys),
        daemon=True,
        name=f"research-retry-{job_id}",
    )
    thread.start()
