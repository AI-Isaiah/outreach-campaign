"""Smart CSV import API routes — LLM-powered column mapping with preview.

Endpoints:
  POST /import/smart    — Upload CSV, get LLM-proposed column mapping
  POST /import/preview  — Apply mapping, preview import stats + duplicates
  POST /import/execute  — Execute the import (insert companies + contacts)
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from typing import Optional

from src.config import load_config
from src.models.database import get_cursor
from src.web.dependencies import get_current_user, get_db

logger = logging.getLogger(__name__)
_limiter = Limiter(key_func=get_remote_address)

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


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    import_job_id: str
    approved_mapping: dict
    source_label: Optional[str] = None


class ExecuteRequest(BaseModel):
    import_job_id: str


# ---------------------------------------------------------------------------
# POST /import/smart — Upload CSV, analyze with LLM
# ---------------------------------------------------------------------------


@router.post("/import/smart")
@_limiter.limit("10/minute")
async def smart_import_upload(
    request: Request,
    file: UploadFile = File(...),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Upload a CSV file and get an LLM-proposed column mapping."""
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

    # Parse CSV
    try:
        reader = csv.DictReader(io.StringIO(content))
        headers = reader.fieldnames
        if not headers:
            raise HTTPException(400, "CSV has no headers")

        rows = []
        for row in reader:
            rows.append(dict(row))
    except csv.Error as exc:
        raise HTTPException(400, f"Invalid CSV format: {exc}")

    if not rows:
        raise HTTPException(400, "CSV has no data rows")

    headers = list(headers)
    sample_rows = rows[:5]

    # Call LLM for column mapping
    from src.services.smart_import import analyze_csv

    analysis = analyze_csv(headers, sample_rows, user_id=user["id"], conn=conn)

    # Store job in import_jobs table
    job_id = str(uuid.uuid4())
    try:
        with get_cursor(conn) as cursor:
            cursor.execute(
                """INSERT INTO import_jobs
                   (id, user_id, status, raw_rows, headers, column_mapping,
                    multi_contact_pattern, row_count)
                   VALUES (%s, %s, 'pending', %s, %s, %s, %s, %s)""",
                (
                    job_id,
                    user["id"],
                    json.dumps(rows),
                    json.dumps(headers),
                    json.dumps(analysis.get("column_map", {})),
                    json.dumps(analysis.get("multi_contact", {})),
                    len(rows),
                ),
            )
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.exception("Failed to store import job")
        raise HTTPException(500, "Failed to store import job") from exc

    return {
        "import_job_id": job_id,
        "proposed_mapping": analysis.get("column_map", {}),
        "sample_rows": sample_rows,
        "multi_contact": analysis.get("multi_contact", {}),
        "confidence": analysis.get("confidence", 0.0),
        "unmapped": analysis.get("unmapped", []),
        "row_count": len(rows),
        "headers": headers,
    }


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

    # Determine multi-contact pattern: use from request body mapping
    # or fall back to what LLM detected
    multi_contact = job["multi_contact_pattern"]
    if isinstance(multi_contact, str):
        multi_contact = json.loads(multi_contact)

    raw_rows = job["raw_rows"]
    if isinstance(raw_rows, str):
        raw_rows = json.loads(raw_rows)

    # Transform rows
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

    # Parse stored data
    column_mapping = job["column_mapping"]
    if isinstance(column_mapping, str):
        column_mapping = json.loads(column_mapping)

    multi_contact = job["multi_contact_pattern"]
    if isinstance(multi_contact, str):
        multi_contact = json.loads(multi_contact)

    raw_rows = job["raw_rows"]
    if isinstance(raw_rows, str):
        raw_rows = json.loads(raw_rows)

    # Re-transform using stored mapping
    from src.services.smart_import import transform_rows, execute_import

    transformed = transform_rows(
        raw_rows, column_mapping, multi_contact, gdpr_countries
    )

    try:
        stats = execute_import(conn, transformed, user_id=user["id"])
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
