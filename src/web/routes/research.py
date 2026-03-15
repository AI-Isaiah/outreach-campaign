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

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.config import SUPABASE_DB_URL
from src.services.crypto_research import (
    _normalize_company_name,
    batch_import_and_enroll,
    cancel_research_job,
    check_duplicate_companies,
    estimate_job_cost,
    parse_research_csv,
    preview_research_csv,
    start_research_job_background,
    start_retry_background,
)
from src.web.dependencies import get_db

router = APIRouter(prefix="/research", tags=["research"])


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
):
    """Preview a CSV file: parse rows, show mapping, stats. No DB required."""
    content = file.file.read().decode("utf-8-sig")
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
def create_research_job(
    file: UploadFile = File(...),
    name: str = Form(...),
    method: str = Form(default="hybrid"),
    skip_duplicates: bool = Form(default=True),
    conn=Depends(get_db),
):
    """Upload CSV and create a research job.

    Returns 202 Accepted and spawns background thread.
    Includes duplicate warnings and enforces max 1 running job.
    """
    if method not in ("web_search", "website_crawl", "hybrid"):
        raise HTTPException(400, "method must be web_search, website_crawl, or hybrid")

    # Enforce max 1 running job
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT id, name FROM research_jobs
               WHERE status IN ('pending', 'researching', 'classifying')
               LIMIT 1""",
        )
        running = cur.fetchone()
        if running:
            raise HTTPException(
                409,
                f"Job '{running['name']}' (#{running['id']}) is still running. "
                f"Wait for it to complete or cancel it first.",
            )
    finally:
        cur.close()

    content = file.file.read().decode("utf-8-sig")
    companies = parse_research_csv(content)

    if not companies:
        raise HTTPException(400, "No valid company rows found in CSV")
    if len(companies) > 500:
        raise HTTPException(400, f"Maximum 500 companies per job (got {len(companies)})")

    # Check for duplicates
    company_names = [c["company_name"] for c in companies]
    dupes = check_duplicate_companies(conn, company_names)
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
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO research_jobs (name, method, total_companies, cost_estimate_usd)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (name, method, len(companies), cost["total"]),
        )
        job_id = cur.fetchone()["id"]

        for company in companies:
            company_id = None
            name_norm = _normalize_company_name(company["company_name"])
            cur.execute(
                "SELECT id FROM companies WHERE name_normalized = %s",
                (name_norm,),
            )
            match = cur.fetchone()
            if match:
                company_id = match["id"]

            cur.execute(
                """INSERT INTO research_results
                       (job_id, company_id, company_name, company_website)
                   VALUES (%s, %s, %s, %s)""",
                (job_id, company_id, company["company_name"], company.get("website")),
            )

        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

    start_research_job_background(job_id, SUPABASE_DB_URL)

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
):
    """List research jobs with pagination and optional status filter."""
    where = ""
    params: list = []
    if status:
        where = "WHERE status = %s"
        params.append(status)

    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM research_jobs {where}", params)
        total = cur.fetchone()["cnt"]

        offset = (page - 1) * per_page
        cur.execute(
            f"""SELECT * FROM research_jobs {where}
                ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            [*params, per_page, offset],
        )
        jobs = [dict(row) for row in cur.fetchall()]
    finally:
        cur.close()

    return {
        "jobs": jobs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total else 0,
    }


@router.get("/jobs/{job_id}")
def get_research_job(job_id: int, conn=Depends(get_db)):
    """Get job detail with progress, category summary, and score distribution."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM research_jobs WHERE id = %s", (job_id,))
        job = cur.fetchone()
        if not job:
            raise HTTPException(404, "Research job not found")

        # Category breakdown
        cur.execute(
            """SELECT category, COUNT(*) AS cnt
               FROM research_results
               WHERE job_id = %s AND category IS NOT NULL
               GROUP BY category""",
            (job_id,),
        )
        by_category = {row["category"]: row["cnt"] for row in cur.fetchall()}

        # Score distribution (bucketed for histogram)
        cur.execute(
            """SELECT
                   CASE
                       WHEN crypto_score >= 80 THEN '80-100'
                       WHEN crypto_score >= 60 THEN '60-79'
                       WHEN crypto_score >= 40 THEN '40-59'
                       WHEN crypto_score >= 20 THEN '20-39'
                       ELSE '0-19'
                   END AS bucket,
                   COUNT(*) AS cnt
               FROM research_results
               WHERE job_id = %s AND crypto_score IS NOT NULL
               GROUP BY bucket
               ORDER BY bucket DESC""",
            (job_id,),
        )
        score_distribution = [
            {"range": row["bucket"], "count": row["cnt"]}
            for row in cur.fetchall()
        ]

        # Aggregate stats
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
                   COALESCE(SUM(jsonb_array_length(discovered_contacts_json)), 0)
                       AS total_contacts_discovered,
                   COUNT(*) FILTER (WHERE status = 'error') AS error_count
               FROM research_results WHERE job_id = %s""",
            (job_id,),
        )
        stats = cur.fetchone()
    finally:
        cur.close()

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
):
    """Get paginated results for a job with filtering."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM research_jobs WHERE id = %s", (job_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Research job not found")
    finally:
        cur.close()

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

    allowed_sorts = {"crypto_score", "company_name", "category", "created_at"}
    if sort_by not in allowed_sorts:
        sort_by = "crypto_score"
    direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM research_results WHERE {where_clause}",
            params,
        )
        total = cur.fetchone()["cnt"]

        offset = (page - 1) * per_page
        cur.execute(
            f"""SELECT id, job_id, company_id, company_name, company_website,
                       crypto_score, category, evidence_summary,
                       warm_intro_contact_ids, warm_intro_notes, status,
                       discovered_contacts_json, created_at
                FROM research_results
                WHERE {where_clause}
                ORDER BY {sort_by} {direction} NULLS LAST
                LIMIT %s OFFSET %s""",
            [*params, per_page, offset],
        )
        results = [dict(row) for row in cur.fetchall()]
    finally:
        cur.close()

    return {
        "results": results,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total else 0,
    }


@router.get("/results/{result_id}")
def get_research_result(result_id: int, conn=Depends(get_db)):
    """Get full detail for a single research result."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM research_results WHERE id = %s", (result_id,))
        result = cur.fetchone()
        if not result:
            raise HTTPException(404, "Research result not found")
    finally:
        cur.close()

    return dict(result)


# ---------------------------------------------------------------------------
# Job Lifecycle
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, conn=Depends(get_db)):
    """Cancel a running research job. Stops after current company."""
    result = cancel_research_job(conn, job_id)
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, conn=Depends(get_db)):
    """Retry all failed/errored results in a completed or failed job."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT status FROM research_jobs WHERE id = %s", (job_id,))
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
    finally:
        cur.close()

    start_retry_background(job_id, SUPABASE_DB_URL)

    return {"success": True, "retrying": error_count}


# ---------------------------------------------------------------------------
# Contact Import (single result)
# ---------------------------------------------------------------------------

@router.post("/results/{result_id}/import-contacts")
def import_discovered_contacts(
    result_id: int,
    indices: list[int] = [],
    conn=Depends(get_db),
):
    """Import discovered contacts from a single research result."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT * FROM research_results WHERE id = %s",
            (result_id,),
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
            name_norm = _normalize_company_name(result["company_name"])
            cur.execute(
                "SELECT id FROM companies WHERE name_normalized = %s",
                (name_norm,),
            )
            match = cur.fetchone()
            if match:
                company_id = match["id"]
            else:
                cur.execute(
                    """INSERT INTO companies (name, name_normalized)
                       VALUES (%s, %s) RETURNING id""",
                    (result["company_name"], name_norm),
                )
                company_id = cur.fetchone()["id"]

        imported = 0
        for contact in discovered:
            name = (contact.get("name") or "").strip()
            if not name:
                continue

            parts = name.split(None, 1)
            first_name = parts[0] if parts else name
            last_name = parts[1] if len(parts) > 1 else ""

            email = contact.get("email")
            email_norm = email.strip().lower() if email else None
            linkedin = contact.get("linkedin")
            linkedin_norm = linkedin.rstrip("/").lower() if linkedin else None

            if email_norm:
                cur.execute(
                    "SELECT id FROM contacts WHERE email_normalized = %s",
                    (email_norm,),
                )
                if cur.fetchone():
                    continue

            if linkedin_norm:
                cur.execute(
                    "SELECT id FROM contacts WHERE linkedin_url_normalized = %s",
                    (linkedin_norm,),
                )
                if cur.fetchone():
                    continue

            cur.execute(
                """INSERT INTO contacts
                       (company_id, first_name, last_name, full_name,
                        email, email_normalized, email_status,
                        linkedin_url, linkedin_url_normalized,
                        title, source)
                   VALUES (%s, %s, %s, %s, %s, %s, 'unverified', %s, %s, %s, 'research')
                   RETURNING id""",
                (
                    company_id, first_name, last_name, name,
                    email, email_norm,
                    linkedin, linkedin_norm,
                    contact.get("title"),
                ),
            )
            imported += 1

        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

    return {"success": True, "imported": imported, "company_id": company_id}


# ---------------------------------------------------------------------------
# Batch Import + Deals + Enrollment
# ---------------------------------------------------------------------------

@router.post("/batch-import")
def batch_import(body: BatchImportRequest, conn=Depends(get_db)):
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
):
    """Export research results as CSV download."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM research_jobs WHERE id = %s", (job_id,))
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
    finally:
        cur.close()

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
def delete_research_job(job_id: int, conn=Depends(get_db)):
    """Delete a research job and all its results (CASCADE)."""
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM research_jobs WHERE id = %s RETURNING id",
            (job_id,),
        )
        deleted = cur.fetchone()
        if not deleted:
            raise HTTPException(404, "Research job not found")
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

    return {"success": True}
