"""Smart CSV import API routes — LLM-powered column mapping with preview.

Endpoints:
  POST /import/smart       — Upload CSV, start async LLM analysis
  GET  /import/jobs/active — Get most recent non-completed import job
  GET  /import/jobs/{id}   — Get import job by ID
  POST /import/preview     — Apply mapping, preview import stats + duplicates
  POST /import/execute     — Execute the import (insert companies + contacts)
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Any

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from typing import Optional

from src.config import load_config
from src.models.database import get_cursor, get_pool_connection, put_pool_connection
from src.web.dependencies import get_current_user, get_db

logger = logging.getLogger(__name__)
_limiter = Limiter(key_func=get_remote_address)
_analysis_semaphore = threading.Semaphore(3)  # max 3 concurrent background analyses

router = APIRouter(tags=["smart-import"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_gdpr_countries() -> list[str]:
    """Load GDPR country list from config, returning empty list on missing config."""
    try:
        config = load_config()
        return config.get("gdpr_countries", [])
    except FileNotFoundError:
        return []


def _parse_json(val: Any) -> Any:
    """Parse a JSONB field that psycopg2 may return as a string."""
    return json.loads(val) if isinstance(val, str) else val


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    import_job_id: str
    approved_mapping: dict
    source_label: Optional[str] = None


class ExecuteRequest(BaseModel):
    import_job_id: str
    excluded_indices: Optional[list[int]] = None  # rows user un-checked (override dedup)
    row_decisions: Optional[dict[str, dict]] = None  # key is str(row index)
    campaign_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Background analysis worker
# ---------------------------------------------------------------------------


def _run_analysis_background(job_id: str, user_id: int, headers: list, rows: list):
    """Run LLM analysis in a background thread — updates import_jobs when done."""
    conn = None
    try:
        _analysis_semaphore.acquire()
        conn = get_pool_connection()
        from src.services.smart_import import analyze_csv

        sample_rows = rows[:5]
        analysis = analyze_csv(headers, sample_rows, user_id=user_id, conn=conn)

        # Build the full analysis_result payload (same shape the frontend expects)
        analysis_result = {
            "proposed_mapping": analysis.get("column_map", {}),
            "sample_rows": sample_rows,
            "multi_contact": analysis.get("multi_contact", {}),
            "confidence": analysis.get("confidence", 0.0),
            "unmapped": analysis.get("unmapped", []),
            "row_count": len(rows),
            "headers": headers,
        }

        with get_cursor(conn) as cursor:
            cursor.execute(
                """UPDATE import_jobs
                   SET status = 'pending',
                       column_mapping = %s,
                       multi_contact_pattern = %s,
                       analysis_result = %s,
                       updated_at = NOW()
                   WHERE id = %s""",
                (
                    json.dumps(analysis.get("column_map", {})),
                    json.dumps(analysis.get("multi_contact", {})),
                    json.dumps(analysis_result),
                    job_id,
                ),
            )
        conn.commit()
        logger.info("Background analysis complete for job %s", job_id)
    except Exception:
        logger.exception("Background analysis failed for job %s", job_id)
        if conn:
            try:
                conn.rollback()
                with get_cursor(conn) as cursor:
                    cursor.execute(
                        """UPDATE import_jobs
                           SET status = 'failed', updated_at = NOW()
                           WHERE id = %s""",
                        (job_id,),
                    )
                conn.commit()
            except Exception:
                logger.exception("Failed to mark job %s as failed", job_id)
    finally:
        if conn:
            put_pool_connection(conn)
        _analysis_semaphore.release()


# ---------------------------------------------------------------------------
# POST /import/smart — Upload CSV, start async LLM analysis
# ---------------------------------------------------------------------------


@router.post("/import/smart")
@_limiter.limit("10/minute")
async def smart_import_upload(
    request: Request,
    file: UploadFile = File(...),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Upload a CSV file and start async LLM column mapping analysis."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "File must be a CSV")

    content_bytes = await file.read()

    # Handle BOM (UTF-8 BOM from Excel)
    try:
        content = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = content_bytes.decode("latin-1")
        except UnicodeDecodeError:
            raise HTTPException(400, "Unable to decode CSV file — unsupported encoding")

    # Parse CSV with smart header detection
    from src.services.smart_import import parse_csv_with_header_detection
    headers, rows = parse_csv_with_header_detection(content)
    if not headers:
        raise HTTPException(400, "CSV has no headers")

    if not rows:
        raise HTTPException(400, "CSV has no data rows")

    # Create job in 'analyzing' status — return immediately
    job_id = str(uuid.uuid4())
    try:
        with get_cursor(conn) as cursor:
            cursor.execute(
                """INSERT INTO import_jobs
                   (id, user_id, status, raw_rows, headers, row_count, filename)
                   VALUES (%s, %s, 'analyzing', %s, %s, %s, %s)""",
                (
                    job_id,
                    user["id"],
                    json.dumps(rows),
                    json.dumps(headers),
                    len(rows),
                    file.filename,
                ),
            )
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.exception("Failed to store import job")
        raise HTTPException(500, "Failed to store import job") from exc

    # Start LLM analysis in background thread
    thread = threading.Thread(
        target=_run_analysis_background,
        args=(job_id, user["id"], headers, rows),
        daemon=True,
    )
    thread.start()

    return {
        "import_job_id": job_id,
        "status": "analyzing",
        "row_count": len(rows),
        "headers": headers,
        "filename": file.filename,
    }


# ---------------------------------------------------------------------------
# GET /import/jobs/active — Most recent non-completed import job
# ---------------------------------------------------------------------------


@router.get("/import/jobs/active")
def get_active_import_job(
    request: Request,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Return the most recent import job that isn't completed/failed, if any."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            """SELECT id, status, filename, row_count, analysis_result, column_mapping, created_at
               FROM import_jobs
               WHERE user_id = %s AND status IN ('analyzing', 'pending', 'previewed')
               ORDER BY created_at DESC LIMIT 1""",
            (user["id"],),
        )
        job = cursor.fetchone()

    if not job:
        return {"job": None}

    result = dict(job)
    result["analysis_result"] = _parse_json(result.get("analysis_result"))
    return {"job": result}


# ---------------------------------------------------------------------------
# GET /import/jobs/{job_id} — Full import job state
# ---------------------------------------------------------------------------


@router.get("/import/jobs/{job_id}")
def get_import_job(
    job_id: str,
    request: Request,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Return full state of an import job for resume."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            """SELECT id, status, filename, row_count, headers, column_mapping,
                      multi_contact_pattern, analysis_result, source_label, created_at
               FROM import_jobs
               WHERE id = %s AND user_id = %s""",
            (job_id, user["id"]),
        )
        job = cursor.fetchone()

    if not job:
        raise HTTPException(404, "Import job not found")

    result = dict(job)
    for key in ("headers", "column_mapping", "multi_contact_pattern", "analysis_result"):
        result[key] = _parse_json(result.get(key))
    return result


# ---------------------------------------------------------------------------
# POST /import/preview — Apply mapping, preview stats
# ---------------------------------------------------------------------------


@router.post("/import/preview")
@_limiter.limit("10/minute")
def smart_import_preview(
    request: Request,
    body: PreviewRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Apply approved mapping and preview import stats with duplicate check."""
    # Load job
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT * FROM import_jobs WHERE id = %s AND user_id = %s",
            (body.import_job_id, user["id"]),
        )
        job = cursor.fetchone()

    if not job:
        raise HTTPException(404, "Import job not found")

    if job["status"] not in ("pending", "previewed"):
        raise HTTPException(
            400, f"Import job is '{job['status']}' — expected 'pending' or 'previewed'"
        )

    gdpr_countries = _get_gdpr_countries()

    multi_contact = _parse_json(job["multi_contact_pattern"])
    raw_rows = _parse_json(job["raw_rows"])

    from src.services.smart_import import transform_rows, preview_import

    transformed = transform_rows(
        raw_rows, body.approved_mapping, multi_contact, gdpr_countries
    )

    preview = preview_import(conn, transformed, user_id=user["id"])

    # Update job: store approved mapping, set status to previewed
    try:
        with get_cursor(conn) as cursor:
            cursor.execute(
                """UPDATE import_jobs
                   SET column_mapping = %s, source_label = %s,
                       status = 'previewed', updated_at = NOW()
                   WHERE id = %s AND user_id = %s""",
                (
                    json.dumps(body.approved_mapping),
                    body.source_label,
                    body.import_job_id,
                    user["id"],
                ),
            )
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.exception("Failed to update import job for preview")
        raise HTTPException(500, "Failed to update import job") from exc

    return preview


# ---------------------------------------------------------------------------
# POST /import/execute — Run the import
# ---------------------------------------------------------------------------


@router.post("/import/execute")
@_limiter.limit("5/minute")
def smart_import_execute(
    request: Request,
    body: ExecuteRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Execute the previewed import — insert companies and contacts."""
    # Load job
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT * FROM import_jobs WHERE id = %s AND user_id = %s",
            (body.import_job_id, user["id"]),
        )
        job = cursor.fetchone()

    if not job:
        raise HTTPException(404, "Import job not found")

    if job["status"] != "previewed":
        raise HTTPException(
            400, f"Import job is '{job['status']}' — expected 'previewed'"
        )

    gdpr_countries = _get_gdpr_countries()

    column_mapping = _parse_json(job["column_mapping"])
    multi_contact = _parse_json(job["multi_contact_pattern"])
    raw_rows = _parse_json(job["raw_rows"])

    # Re-transform using stored mapping
    from src.services.smart_import import transform_rows, execute_import

    transformed = transform_rows(
        raw_rows, column_mapping, multi_contact, gdpr_countries
    )

    # Apply user exclusions (rows they un-checked during preview)
    if body.excluded_indices:
        excluded = set(body.excluded_indices)
        transformed = [r for i, r in enumerate(transformed) if i not in excluded]

    # Parse per-row decisions (JSON keys are strings, convert to int)
    decisions = None
    if body.row_decisions:
        decisions = {int(k): v for k, v in body.row_decisions.items()}

    try:
        stats = execute_import(
            conn, transformed, user_id=user["id"],
            row_decisions=decisions,
            campaign_id=body.campaign_id,
        )
    except (psycopg2.Error, ValueError) as exc:
        conn.rollback()
        logger.exception("Smart import execution failed")
        raise HTTPException(500, "Import failed due to an internal error") from exc

    # Update job status to completed
    try:
        with get_cursor(conn) as cursor:
            cursor.execute(
                """UPDATE import_jobs
                   SET status = 'completed', updated_at = NOW()
                   WHERE id = %s AND user_id = %s""",
                (body.import_job_id, user["id"]),
            )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        logger.warning("Failed to update import job status to completed")

    return {"success": True, **stats}
