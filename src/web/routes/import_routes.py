"""Import and deduplication API routes."""

from __future__ import annotations

import csv
import tempfile

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.web.dependencies import get_current_user, get_db

_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["import"])


@router.post("/import/csv")
@_limiter.limit("5/minute")
async def import_csv(
    request: Request,
    file: UploadFile = File(...),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Upload a CSV file and import contacts."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV")

    content = await file.read()

    # Write to temp file for the import function
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from src.commands.import_contacts import import_fund_csv
        stats = import_fund_csv(conn, tmp_path, user_id=user["id"])
        return {"success": True, "stats": stats}
    except (psycopg2.Error, ValueError, csv.Error, KeyError) as exc:
        import logging
        logging.getLogger(__name__).exception("CSV import failed")
        raise HTTPException(500, "Import failed due to an internal error") from exc
    finally:
        import os
        os.unlink(tmp_path)


@router.post("/import/dedupe")
@_limiter.limit("5/minute")
def run_dedupe(
    request: Request,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Run deduplication on all contacts."""
    try:
        from src.services.deduplication import run_dedup
        stats = run_dedup(conn, user_id=user["id"])
        return {"success": True, "stats": stats}
    except (psycopg2.Error, ValueError) as exc:
        import logging
        logging.getLogger(__name__).exception("Deduplication failed")
        raise HTTPException(500, "Deduplication failed due to an internal error") from exc
