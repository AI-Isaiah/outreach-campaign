"""Import and deduplication API routes."""

from __future__ import annotations

import io
import tempfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from src.web.dependencies import get_db

router = APIRouter(tags=["import"])


@router.post("/import/csv")
async def import_csv(
    file: UploadFile = File(...),
    conn=Depends(get_db),
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
        stats = import_fund_csv(conn, tmp_path)
        return {"success": True, "stats": stats}
    except Exception as e:
        raise HTTPException(500, f"Import failed: {e}")
    finally:
        import os
        os.unlink(tmp_path)


@router.post("/import/dedupe")
def run_dedupe(
    conn=Depends(get_db),
):
    """Run deduplication on all contacts."""
    try:
        from src.services.deduplication import run_dedup
        stats = run_dedup(conn)
        return {"success": True, "stats": stats}
    except Exception as e:
        raise HTTPException(500, f"Deduplication failed: {e}")
