"""Research API routes — crypto interest research pipeline.

Endpoints:
  POST /research/preview-csv         — Preview uploaded CSV before committing
  POST /research/jobs                — Create job from CSV, spawn background thread
  GET  /research/jobs                — List jobs (paginated, filterable)
  GET  /research/jobs/{id}           — Job detail with progress + analytics
  GET  /research/jobs/{id}/results   — Paginated results with filters
  POST /research/jobs/{id}/cancel    — Cancel a running job
  POST /research/jobs/{id}/retry     — Retry failed results
  POST /research/jobs/{id}/export    — Export results as CSV
  DELETE /research/jobs/{id}         — Delete job + results
  GET  /research/results/{id}        — Single result detail
  POST /research/results/{id}/import-contacts — Import discovered contacts
  POST /research/batch-import        — Batch import + create deals + enroll
"""

from __future__ import annotations

import csv
import io
import json
from typing import Optional

import psycopg2
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import logging
import os

import httpx as _httpx

from src.config import SUPABASE_DB_URL
from src.services.crypto_research import (
    batch_import_and_enroll,
    cancel_research_job,
    check_duplicate_companies,
    estimate_job_cost,
    import_single_contact,
    parse_research_csv,
    preview_research_csv,
    resolve_or_create_company,
    start_research_job_background,
    start_retry_background,
)
from src.services.normalization_utils import normalize_company_name
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.web.dependencies import get_current_user, get_db
from src.web.routes.settings import get_user_api_keys
from src.models.database import get_cursor

_logger = logging.getLogger(__name__)
_limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false",
)
_MAX_RESEARCH_JOBS_PER_DAY = 10
_SUPABASE_URL = os.getenv("SUPABASE_URL", "")
_SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def _trigger_research(endpoint: str, payload: dict) -> None:
    """Start a research job via Supabase Edge Function or local background thread.

    Uses Edge Function when SUPABASE_URL is configured (Vercel/production).
    Falls back to in-process background threads for local development.
    """
    if _SUPABASE_URL and _SUPABASE_SERVICE_ROLE_KEY:
        try:
            _httpx.post(
                f"{_SUPABASE_URL}/functions/v1/{endpoint}",
                headers={
                    "Authorization": f"Bearer {_SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=5,
            )
        except (_httpx.HTTPError, OSError) as exc:
            _logger.exception("Failed to trigger Edge Function %s: %s", endpoint, exc)
    else:
        # Local dev: use background threads
        job_id = payload["job_id"]
        api_keys = payload.get("api_keys")
        if endpoint == "research-job":
            start_research_job_background(job_id, SUPABASE_DB_URL, api_keys=api_keys)
        elif endpoint == "research-retry":
            start_retry_background(job_id, SUPABASE_DB_URL, api_keys=api_keys)

router = APIRouter(prefix="/research", tags=["research"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class BatchImportRequest(BaseModel):
    result_ids: list[int]
    create_deals: bool = False
    campaign_name: Optional[str] = None


# ---------------------------------------------------------------------------
# CSV Preview
# ---------------------------------------------------------------------------

@router.post("/preview-csv")
def preview_csv(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Preview a CSV file: parse rows, show mapping, stats. No DB required."""
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "CSV exceeds 5 MB limit")
    content = raw.decode("utf-8-sig")
    preview = preview_research_csv(content)

    if preview["total_rows"] == 0:
        raise HTTPException(400, "No valid company rows found. Ensure CSV has a company_name (or name/firm_name) column.")

    if preview["total_rows"] > 500:
        raise HTTPException(400, f"Maximum 500 companies per job (found {preview['total_rows']})")

    return preview


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------

@router.post("/jobs", status_code=202)
@_limiter.limit("3/hour")
def create_research_job(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    method: str = Form(default="hybrid"),
    skip_duplicates: bool = Form(default=True),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Upload CSV and create a research job.

    Returns 202 Accepted and spawns background thread.
    Includes duplicate warnings and enforces max 1 running job.
    """
    if method not in ("web_search", "website_crawl", "hybrid"):
        raise HTTPException(400, "method must be web_search, website_crawl, or hybrid")

    with get_cursor(conn) as cur:
        # Per-user daily cap
        cur.execute(
            """SELECT COUNT(*) AS cnt FROM research_jobs
               WHERE user_id = %s AND created_at > NOW() - INTERVAL '24 hours'""",
            (user["id"],),
        )
        if cur.fetchone()["cnt"] >= _MAX_RESEARCH_JOBS_PER_DAY:
            _logger.warning("User %s hit research job daily cap", user["id"])
            raise HTTPException(429, f"Daily limit of {_MAX_RESEARCH_JOBS_PER_DAY} research jobs reached")

        # Enforce max 1 running job for this user
        cur.execute(
            """SELECT id, name FROM research_jobs
               WHERE status IN ('pending', 'researching', 'classifying')
               AND user_id = %s
               LIMIT 1""",
            (user["id"],),
        )
        running = cur.fetchone()
        if running:
            raise HTTPException(
                409,
                f"Job '{running['name']}' (#{running['id']}) is still running. "
                f"Wait for it to complete or cancel it first.",
            )

    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "CSV exceeds 5 MB limit")
    content = raw.decode("utf-8-sig")
    companies = parse_research_csv(content)

    if not companies:
        raise HTTPException(400, "No valid company rows found in CSV")
    if len(companies) > 500:
        raise HTTPException(400, f"Maximum 500 companies per job (got {len(companies)})")

    # Check for duplicates
    company_names = [c["company_name"] for c in companies]
    dupes = check_duplicate_companies(conn, company_names, user_id=user["id"])
    warnings = []

    if dupes["already_researched"]:
        if skip_duplicates:
            # Filter out already-researched companies
            already_set = set(dupes["already_researched"])
            companies = [c for c in companies if c["company_name"] not in already_set]
            warnings.append(
                f"Skipped {len(dupes['already_researched'])} already-researched companies"
            )
        else:
            warnings.append(
                f"{len(dupes['already_researched'])} companies were previously researched: "
                f"{', '.join(dupes['already_researched'][:5])}"
                f"{'...' if len(dupes['already_researched']) > 5 else ''}"
            )

    if not companies:
        raise HTTPException(400, "All companies in CSV have already been researched")

    cost = estimate_job_cost(len(companies), method)

    # Create job
    with get_cursor(conn) as cur:
        try:
            cur.execute(
                """INSERT INTO research_jobs (name, method, total_companies, cost_estimate_usd, user_id)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (name, method, len(companies), cost["total"], user["id"]),
            )
            job_id = cur.fetchone()["id"]

            # Batch lookup existing companies (avoid N+1)
            all_norms = [normalize_company_name(c["company_name"]) for c in companies]
            cur.execute(
                "SELECT id, name_normalized FROM companies WHERE name_normalized = ANY(%s)",
                (all_norms,),
            )
            company_map = {row["name_normalized"]: row["id"] for row in cur.fetchall()}

            for company in companies:
                name_norm = normalize_company_name(company["company_name"])
                company_id = company_map.get(name_norm)

                cur.execute(
                    """INSERT INTO research_results
                           (job_id, company_id, company_name, company_website)
                       VALUES (%s, %s, %s, %s)""",
                    (job_id, company_id, company["company_name"], company.get("website")),
                )

            conn.commit()
        except HTTPException:
            raise
        except psycopg2.Error:
            conn.rollback()
            raise

    api_keys = get_user_api_keys(conn, user["id"])
    _trigger_research("research-job", {"job_id": job_id, "api_keys": api_keys})

    return {
        "job_id": job_id,
        "total_companies": len(companies),
        "cost_estimate": cost,
        "status": "pending",
        "warnings": warnings,
        "duplicates_skipped": len(dupes["already_researched"]) if skip_duplicates else 0,
    }


@router.get("/jobs")
def list_research_jobs(
    status: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """List research jobs with pagination and optional status filter."""
    conditions = ["user_id = %s"]
    params: list = [user["id"]]
    if status:
        conditions.append("status = %s")
        params.append(status)
    where = "WHERE " + " AND ".join(conditions)

    with get_cursor(conn) as cur:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM research_jobs {where}", params)
        total = cur.fetchone()["cnt"]

        offset = (page - 1) * per_page
        cur.execute(
            f"""SELECT * FROM research_jobs {where}
                ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            [*params, per_page, offset],
        )
        jobs = [dict(row) for row in cur.fetchall()]

    return {
        "jobs": jobs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total else 0,
    }


@router.get("/jobs/{job_id}")
def get_research_job(job_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Get job detail with progress, category summary, and score distribution."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT * FROM research_jobs WHERE id = %s AND user_id = %s", (job_id, user["id"]))
        job = cur.fetchone()
        if not job:
            raise HTTPException(404, "Research job not found")

        # Category breakdown (needs GROUP BY, kept separate)
        cur.execute(
            """SELECT category, COUNT(*) AS cnt
               FROM research_results
               WHERE job_id = %s AND category IS NOT NULL
               GROUP BY category""",
            (job_id,),
        )
        by_category = {row["category"]: row["cnt"] for row in cur.fetchall()}

        # Aggregate stats + score distribution in one scan (polled every 3s)
        cur.execute(
            """SELECT
                   AVG(crypto_score) AS avg_score,
                   MAX(crypto_score) AS max_score,
                   MIN(crypto_score) AS min_score,
                   COUNT(*) FILTER (WHERE warm_intro_contact_ids IS NOT NULL
                                    AND array_length(warm_intro_contact_ids, 1) > 0)
                       AS warm_intro_count,
                   COUNT(*) FILTER (WHERE discovered_contacts_json IS NOT NULL)
                       AS with_contacts,
                   COALESCE(SUM(
                       CASE WHEN jsonb_typeof(discovered_contacts_json) = 'array'
                            THEN jsonb_array_length(discovered_contacts_json)
                            ELSE 0 END
                   ), 0) AS total_contacts_discovered,
                   COUNT(*) FILTER (WHERE status = 'error') AS error_count,
                   COUNT(*) FILTER (WHERE crypto_score >= 80) AS bucket_80_100,
                   COUNT(*) FILTER (WHERE crypto_score >= 60 AND crypto_score < 80) AS bucket_60_79,
                   COUNT(*) FILTER (WHERE crypto_score >= 40 AND crypto_score < 60) AS bucket_40_59,
                   COUNT(*) FILTER (WHERE crypto_score >= 20 AND crypto_score < 40) AS bucket_20_39,
                   COUNT(*) FILTER (WHERE crypto_score < 20) AS bucket_0_19
               FROM research_results WHERE job_id = %s""",
            (job_id,),
        )
        stats = cur.fetchone()
        score_distribution = [
            {"range": r, "count": stats[f"bucket_{r.replace('-', '_')}"] or 0}
            for r in ("80-100", "60-79", "40-59", "20-39", "0-19")
            if (stats[f"bucket_{r.replace('-', '_')}"] or 0) > 0
        ]

    return {
        "job": dict(job),
        "by_category": by_category,
        "score_distribution": score_distribution,
        "avg_score": round(stats["avg_score"], 1) if stats["avg_score"] else 0,
        "max_score": stats["max_score"] or 0,
        "min_score": stats["min_score"] or 0,
        "warm_intro_count": stats["warm_intro_count"] or 0,
        "with_contacts": stats["with_contacts"] or 0,
        "total_contacts_discovered": stats["total_contacts_discovered"] or 0,
        "error_count": stats["error_count"] or 0,
    }


@router.get("/jobs/{job_id}/results")
def get_research_results(
    job_id: int,
    category: Optional[str] = Query(default=None),
    min_score: Optional[int] = Query(default=None, ge=0, le=100),
    has_warm_intros: Optional[bool] = Query(default=None),
    sort_by: str = Query(default="crypto_score"),
    sort_dir: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get paginated results for a job with filtering."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT id FROM research_jobs WHERE id = %s AND user_id = %s", (job_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, "Research job not found")

    where_parts = ["job_id = %s"]
    params: list = [job_id]

    if category:
        where_parts.append("category = %s")
        params.append(category)
    if min_score is not None:
        where_parts.append("crypto_score >= %s")
        params.append(min_score)
    if has_warm_intros is True:
        where_parts.append("warm_intro_contact_ids IS NOT NULL AND array_length(warm_intro_contact_ids, 1) > 0")
    elif has_warm_intros is False:
        where_parts.append("(warm_intro_contact_ids IS NULL OR array_length(warm_intro_contact_ids, 1) IS NULL)")

    where_clause = " AND ".join(where_parts)

    # Allowlist sort column to prevent SQL injection — validated before interpolation
    allowed_sorts = {
        "crypto_score": "crypto_score",
        "company_name": "company_name",
        "category": "category",
        "created_at": "created_at",
    }
    safe_sort = allowed_sorts.get(sort_by, "crypto_score")
    safe_dir = "DESC" if sort_dir.lower() == "desc" else "ASC"

    # Build the full query with safe column name (from allowlist, not user input)
    count_sql = f"SELECT COUNT(*) AS cnt FROM research_results WHERE {where_clause}"
    select_sql = f"""SELECT id, job_id, company_id, company_name, company_website,
                       crypto_score, category, evidence_summary,
                       warm_intro_contact_ids, warm_intro_notes, status,
                       discovered_contacts_json, created_at
                FROM research_results
                WHERE {where_clause}
                ORDER BY {safe_sort} {safe_dir} NULLS LAST
                LIMIT %s OFFSET %s"""

    with get_cursor(conn) as cur:
        cur.execute(count_sql, params)
        total = cur.fetchone()["cnt"]

        offset = (page - 1) * per_page
        cur.execute(select_sql, [*params, per_page, offset])
        results = [dict(row) for row in cur.fetchall()]

    return {
        "results": results,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total else 0,
    }


@router.get("/results/{result_id}")
def get_research_result(result_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Get full detail for a single research result."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT rr.* FROM research_results rr
               JOIN research_jobs rj ON rj.id = rr.job_id
               WHERE rr.id = %s AND rj.user_id = %s""",
            (result_id, user["id"]),
        )
        result = cur.fetchone()
        if not result:
            raise HTTPException(404, "Research result not found")

    return dict(result)


# ---------------------------------------------------------------------------
# Job Lifecycle
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Cancel a running research job. Stops after current company."""
    # Verify ownership
    with get_cursor(conn) as cur:
        cur.execute("SELECT id FROM research_jobs WHERE id = %s AND user_id = %s", (job_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, "Research job not found")

    result = cancel_research_job(conn, job_id)
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Retry all failed/errored results in a completed or failed job."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT status FROM research_jobs WHERE id = %s AND user_id = %s", (job_id, user["id"]))
        job = cur.fetchone()
        if not job:
            raise HTTPException(404, "Research job not found")
        if job["status"] not in ("completed", "failed"):
            raise HTTPException(400, f"Can only retry completed or failed jobs (current: {job['status']})")

        # Count retryable results
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM research_results WHERE job_id = %s AND status = 'error'",
            (job_id,),
        )
        error_count = cur.fetchone()["cnt"]
        if error_count == 0:
            raise HTTPException(400, "No failed results to retry")

    api_keys = get_user_api_keys(conn, user["id"])
    _trigger_research("research-retry", {"job_id": job_id, "api_keys": api_keys})

    return {"success": True, "retrying": error_count}


# ---------------------------------------------------------------------------
# Contact Import (single result)
# ---------------------------------------------------------------------------

@router.post("/results/{result_id}/import-contacts")
def import_discovered_contacts(
    result_id: int,
    indices: list[int] = [],
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Import discovered contacts from a single research result."""
    with get_cursor(conn) as cur:
        try:
            cur.execute(
                """SELECT rr.* FROM research_results rr
                   JOIN research_jobs rj ON rj.id = rr.job_id
                   WHERE rr.id = %s AND rj.user_id = %s""",
                (result_id, user["id"]),
            )
            result = cur.fetchone()
            if not result:
                raise HTTPException(404, "Research result not found")

            contacts_json = result.get("discovered_contacts_json")
            if not contacts_json:
                raise HTTPException(400, "No discovered contacts to import")

            discovered = contacts_json if isinstance(contacts_json, list) else json.loads(contacts_json)

            if indices:
                discovered = [c for i, c in enumerate(discovered) if i in indices]

            if not discovered:
                raise HTTPException(400, "No contacts selected for import")

            company_id = result["company_id"]
            if not company_id:
                company_id = resolve_or_create_company(cur, result["company_name"], user_id=user["id"])

            imported = 0
            for contact in discovered:
                contact_id = import_single_contact(cur, contact, company_id, user_id=user["id"])
                if contact_id is not None:
                    imported += 1

            conn.commit()
        except HTTPException:
            raise
        except (psycopg2.Error, json.JSONDecodeError) as exc:
            conn.rollback()
            _logger.error("Contact import failed for result %d: %s", result_id, exc)
            raise

    return {"success": True, "imported": imported, "company_id": company_id}


# ---------------------------------------------------------------------------
# Batch Import + Deals + Enrollment
# ---------------------------------------------------------------------------

@router.post("/batch-import")
def batch_import(body: BatchImportRequest, conn=Depends(get_db), user=Depends(get_current_user)):
    """Batch import contacts from multiple results, optionally create deals and enroll.

    This is the "complete the loop" endpoint: Research → Import → Deals → Campaign.
    """
    if not body.result_ids:
        raise HTTPException(400, "No result IDs provided")

    result = batch_import_and_enroll(
        conn,
        result_ids=body.result_ids,
        create_deals=body.create_deals,
        campaign_name=body.campaign_name,
        user_id=user["id"],
    )

    return {"success": True, **result}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/export")
def export_research_results(
    job_id: int,
    min_score: Optional[int] = Query(default=None),
    categories: Optional[str] = Query(default=None),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Export research results as CSV download."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT id FROM research_jobs WHERE id = %s AND user_id = %s", (job_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, "Research job not found")

        where_parts = ["job_id = %s"]
        params: list = [job_id]

        if min_score is not None:
            where_parts.append("crypto_score >= %s")
            params.append(min_score)
        if categories:
            cat_list = [c.strip() for c in categories.split(",")]
            where_parts.append("category = ANY(%s)")
            params.append(cat_list)

        cur.execute(
            f"""SELECT company_name, company_website, crypto_score, category,
                       evidence_summary, classification_reasoning,
                       discovered_contacts_json, warm_intro_notes
                FROM research_results
                WHERE {' AND '.join(where_parts)}
                ORDER BY crypto_score DESC NULLS LAST""",
            params,
        )
        rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Company", "Website", "Score", "Category",
        "Evidence Summary", "Reasoning",
        "Discovered Contacts", "Contact Emails", "Warm Intros",
    ])
    for row in rows:
        contacts_str = ""
        emails_str = ""
        if row["discovered_contacts_json"]:
            contacts = row["discovered_contacts_json"] if isinstance(
                row["discovered_contacts_json"], list
            ) else json.loads(row["discovered_contacts_json"])
            contacts_str = "; ".join(
                f"{c.get('name', '')} ({c.get('title', '')})"
                for c in contacts
            )
            emails_str = "; ".join(
                c.get("email", "") for c in contacts if c.get("email")
            )
        writer.writerow([
            row["company_name"],
            row["company_website"] or "",
            row["crypto_score"] or "",
            row["category"] or "",
            row["evidence_summary"] or "",
            (row["classification_reasoning"] or "")[:200],
            contacts_str,
            emails_str,
            row["warm_intro_notes"] or "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=research_job_{job_id}.csv"},
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/jobs/{job_id}")
def delete_research_job(job_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Delete a research job and all its results (CASCADE)."""
    with get_cursor(conn) as cur:
        try:
            cur.execute(
                "DELETE FROM research_jobs WHERE id = %s AND user_id = %s RETURNING id",
                (job_id, user["id"]),
            )
            deleted = cur.fetchone()
            if not deleted:
                raise HTTPException(404, "Research job not found")
            conn.commit()
        except HTTPException:
            raise
        except psycopg2.Error:
            conn.rollback()
            raise

    return {"success": True}
