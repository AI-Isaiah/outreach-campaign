"""Crypto research — job orchestration, status management, background threads."""

from __future__ import annotations

import json
import logging
import os
import time
import threading

import httpx
import psycopg2

from src.models.database import get_cursor
from src.services.crypto_scoring import COST_LLM, classify_crypto_interest
from src.services.crypto_web_scraper import (
    COST_WEB_SEARCH,
    crawl_company_website,
    discover_contacts_at_company,
    research_company_web_search,
)
from src.services.crypto_research_import import find_warm_intros

logger = logging.getLogger(__name__)

# Cost estimates per operation
COST_CONTACT_DISCOVERY = 0.005


def _default_api_keys() -> dict:
    """Build api_keys dict from environment variables."""
    return {
        "perplexity": os.getenv("PERPLEXITY_API_KEY", ""),
        "anthropic": os.getenv("ANTHROPIC_API_KEY", ""),
    }


def _resolve_api_keys(api_keys: dict | None) -> dict:
    """Merge caller-supplied keys with environment defaults. Thread-safe."""
    defaults = _default_api_keys()
    if api_keys:
        if api_keys.get("perplexity"):
            defaults["perplexity"] = api_keys["perplexity"]
        if api_keys.get("anthropic"):
            defaults["anthropic"] = api_keys["anthropic"]
    return defaults


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


def cancel_research_job(conn, job_id: int, *, user_id: int) -> dict:
    """Cancel a research job.

    If the background thread is still running (status 'running'), sets
    'cancelling' so the thread stops gracefully after the current company.
    If the thread already finished processing (status 'pending' or stuck),
    sets 'cancelled' directly since no thread will transition it.
    """
    with get_cursor(conn) as cur:
        cur.execute("SELECT status FROM research_jobs WHERE id = %s AND user_id = %s", (job_id, user_id))
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "Job not found"}

        if row["status"] in ("completed", "failed", "cancelled"):
            return {"success": False, "error": f"Job already {row['status']}"}

        # If actively running, use 'cancelling' so the thread exits gracefully.
        # Otherwise set 'cancelled' directly (no thread will pick it up).
        new_status = "cancelling" if row["status"] == "running" else "cancelled"

        cur.execute(
            """UPDATE research_jobs
               SET status = %s, updated_at = NOW()
               WHERE id = %s AND user_id = %s""",
            (new_status, job_id, user_id),
        )
        conn.commit()
        return {"success": True, "status": new_status}


def retry_failed_results(job_id: int, db_url: str, api_keys: dict | None = None) -> None:
    """Retry all errored results in a job. Runs in background thread."""
    from src.models.database import get_connection, run_migrations, get_cursor

    resolved_keys = _resolve_api_keys(api_keys)
    conn = get_connection(db_url)
    try:
        run_migrations(conn)

        with get_cursor(conn) as cur:
            cur.execute("SELECT * FROM research_jobs WHERE id = %s", (job_id,))
            job = cur.fetchone()
            if not job or job["status"] not in ("completed", "failed"):
                return
            method = job["method"]
            user_id = job["user_id"]

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
                _research_single_company(conn, result, method, api_keys=resolved_keys)
                actual_cost += COST_WEB_SEARCH
            except (httpx.HTTPError, psycopg2.Error, json.JSONDecodeError, KeyError) as exc:
                _mark_result_error(conn, result["id"], str(exc))
                continue

            try:
                _classify_single_company(conn, result, api_keys=resolved_keys)
                actual_cost += COST_LLM
            except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
                logger.warning("Classification error during retry for result %d: %s", result["id"], exc)

            try:
                discovered = discover_contacts_at_company(
                    result["company_name"], result.get("company_website"), api_keys=resolved_keys,
                )
                actual_cost += COST_CONTACT_DISCOVERY
                warm = find_warm_intros(conn, result["company_name"], result.get("company_id"), user_id=user_id)

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
            except (httpx.HTTPError, psycopg2.Error, json.JSONDecodeError) as exc:
                logger.warning("Contact discovery/save error during retry for result %d: %s", result["id"], exc)

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

    except (httpx.HTTPError, psycopg2.Error, json.JSONDecodeError, KeyError) as e:
        logger.exception("Retry job %d failed", job_id)
        try:
            _update_job_status(conn, job_id, "failed", error_message=f"Retry failed: {e}")
        except psycopg2.Error:
            logger.exception("Failed to update job %d status after retry failure", job_id)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Background Job Orchestrator
# ---------------------------------------------------------------------------


def run_research_job(job_id: int, db_url: str, api_keys: dict | None = None) -> None:
    """Background thread entry point for running a research job."""
    from src.models.database import get_connection, run_migrations

    resolved_keys = _resolve_api_keys(api_keys)
    conn = get_connection(db_url)
    try:
        run_migrations(conn)
        _execute_research_job(conn, job_id, api_keys=resolved_keys)
    except (httpx.HTTPError, psycopg2.Error, json.JSONDecodeError, KeyError, RuntimeError) as e:
        logger.exception("Research job %d failed", job_id)
        try:
            _update_job_status(conn, job_id, "failed", error_message=str(e))
        except psycopg2.Error:
            logger.exception("Failed to update job %d status", job_id)
    finally:
        conn.close()


def _execute_research_job(conn, job_id: int, *, api_keys: dict) -> None:
    """Run the full research pipeline for a job."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT * FROM research_jobs WHERE id = %s", (job_id,))
        job = cur.fetchone()
        if not job:
            return
        method = job["method"]
        user_id = job["user_id"]

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
            _research_single_company(conn, result, method, api_keys=api_keys)
            actual_cost += COST_WEB_SEARCH if method in ("web_search", "hybrid") else 0
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                for wait in (2, 5, 10, 30):
                    time.sleep(wait)
                    if _is_cancelled(conn, job_id):
                        _update_job_status(conn, job_id, "cancelled")
                        return
                    try:
                        _research_single_company(conn, result, method, api_keys=api_keys)
                        actual_cost += COST_WEB_SEARCH
                        break
                    except httpx.HTTPStatusError:
                        continue
                else:
                    _mark_result_error(conn, result["id"], "Rate limited")
                    result["_errored"] = True
        except (httpx.HTTPError, psycopg2.Error, json.JSONDecodeError, KeyError) as exc:
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
            _classify_single_company(conn, result, api_keys=api_keys)
            actual_cost += COST_LLM
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
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
                result["company_name"], result.get("company_website"), api_keys=api_keys,
            )
            actual_cost += COST_CONTACT_DISCOVERY

            warm = find_warm_intros(conn, result["company_name"], result.get("company_id"), user_id=user_id)

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
        except (httpx.HTTPError, psycopg2.Error, json.JSONDecodeError) as exc:
            logger.warning("Contact discovery error for %s: %s", result["company_name"], exc)

    _update_job_status(
        conn, job_id, "completed",
        contacts_discovered=contacts_found,
        actual_cost_usd=round(actual_cost, 4),
    )


def _research_single_company(conn, result: dict, method: str, *, api_keys: dict | None = None) -> None:
    """Run web search and/or crawl for a single company."""
    web_raw = None
    crawl_raw = None

    has_website = bool(result.get("company_website"))

    if method in ("web_search", "hybrid"):
        web_raw = research_company_web_search(
            result["company_name"], result.get("company_website"), api_keys=api_keys,
        )
    if method in ("website_crawl", "hybrid") and has_website:
        crawl_raw = crawl_company_website(result["company_website"])

    # Fallback: if website_crawl was chosen but company has no website,
    # do a web search instead so the classifier has something to work with
    if method == "website_crawl" and not has_website:
        logger.info("No website for %s, falling back to web search", result["company_name"])
        web_raw = research_company_web_search(result["company_name"], None, api_keys=api_keys)

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


def _classify_single_company(conn, result: dict, *, api_keys: dict | None = None) -> None:
    """Classify a single company's crypto interest."""
    classification = classify_crypto_interest(
        result["company_name"],
        result.get("web_search_raw") or "",
        result.get("website_crawl_raw") or "",
        api_keys=api_keys,
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
        except psycopg2.Error:
            logger.error("Failed to mark result %d as error", result_id)
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
