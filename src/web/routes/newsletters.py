"""Newsletter management API routes — compose, upload PDFs, filter recipients, send."""

from __future__ import annotations

import logging
import os
import smtplib
import threading
from pathlib import Path
from typing import Optional

import psycopg2

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.models.database import get_cursor
from src.web.dependencies import get_config, get_current_user, get_db
from src.web.query_builder import QueryBuilder

_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/newsletters", tags=["newsletters"])
logger = logging.getLogger(__name__)

ATTACHMENT_DIR = Path("data/newsletter_attachments")
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB


class NewsletterCreate(BaseModel):
    subject: str = Field(max_length=200)
    body_html: str = Field(max_length=50000)
    body_text: Optional[str] = Field(default=None, max_length=50000)


class NewsletterUpdate(BaseModel):
    subject: Optional[str] = Field(default=None, max_length=200)
    body_html: Optional[str] = Field(default=None, max_length=50000)
    body_text: Optional[str] = Field(default=None, max_length=50000)


class NewsletterSendRequest(BaseModel):
    lifecycle_stages: Optional[list[str]] = None
    product_ids: Optional[list[int]] = None
    newsletter_only: bool = True


@router.get("")
def list_newsletters(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """List all newsletters, newest first."""
    offset = (page - 1) * per_page
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM newsletters WHERE user_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (user["id"], per_page, offset),
        )
        rows = cur.fetchall()

        cur.execute("SELECT COUNT(*) AS cnt FROM newsletters WHERE user_id = %s", (user["id"],))
        total = cur.fetchone()["cnt"]

        return {
            "newsletters": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if total else 1,
        }


@router.post("")
def create_newsletter(body: NewsletterCreate, conn=Depends(get_db), user=Depends(get_current_user)):
    """Create a newsletter draft."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO newsletters (subject, body_html, body_text, user_id)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (body.subject, body.body_html, body.body_text, user["id"]),
        )
        nl_id = cur.fetchone()["id"]
        conn.commit()
        return {"id": nl_id, "success": True}


@router.get("/{newsletter_id}")
def get_newsletter(newsletter_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Get newsletter detail with attachments and send stats."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT * FROM newsletters WHERE id = %s AND user_id = %s", (newsletter_id, user["id"]))
        newsletter = cur.fetchone()
        if not newsletter:
            raise HTTPException(404, f"Newsletter {newsletter_id} not found")

        cur.execute(
            "SELECT * FROM newsletter_attachments WHERE newsletter_id = %s ORDER BY created_at",
            (newsletter_id,),
        )
        attachments = cur.fetchall()

        cur.execute(
            """SELECT status, COUNT(*) AS cnt
               FROM newsletter_sends WHERE newsletter_id = %s GROUP BY status""",
            (newsletter_id,),
        )
        send_stats = {row["status"]: row["cnt"] for row in cur.fetchall()}

        return {
            "newsletter": dict(newsletter),
            "attachments": [dict(a) for a in attachments],
            "send_stats": send_stats,
        }


@router.put("/{newsletter_id}")
def update_newsletter(newsletter_id: int, body: NewsletterUpdate, conn=Depends(get_db), user=Depends(get_current_user)):
    """Update a newsletter draft."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT id, status FROM newsletters WHERE id = %s AND user_id = %s", (newsletter_id, user["id"]))
        nl = cur.fetchone()
        if not nl:
            raise HTTPException(404, f"Newsletter {newsletter_id} not found")
        if nl["status"] != "draft":
            raise HTTPException(400, "Can only edit draft newsletters")

        set_clause, params = QueryBuilder.build_update(body.model_dump())

        if set_clause:
            set_clause += ", updated_at = NOW()"
            params.extend([newsletter_id, user["id"]])
            cur.execute(
                f"UPDATE newsletters SET {set_clause} WHERE id = %s AND user_id = %s",
                params,
            )
            conn.commit()
        return {"success": True}


@router.delete("/{newsletter_id}")
@_limiter.limit("5/minute")
def delete_newsletter(request: Request, newsletter_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Delete a draft newsletter."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT id, status FROM newsletters WHERE id = %s AND user_id = %s", (newsletter_id, user["id"]))
        nl = cur.fetchone()
        if not nl:
            raise HTTPException(404, f"Newsletter {newsletter_id} not found")
        if nl["status"] != "draft":
            raise HTTPException(400, "Can only delete draft newsletters")

        cur.execute("DELETE FROM newsletters WHERE id = %s AND user_id = %s", (newsletter_id, user["id"]))
        conn.commit()
        return {"success": True}


@router.post("/{newsletter_id}/attachments")
async def upload_attachment(
    newsletter_id: int,
    file: UploadFile = File(...),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Upload a PDF attachment to a newsletter."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT id, status FROM newsletters WHERE id = %s AND user_id = %s", (newsletter_id, user["id"]))
        nl = cur.fetchone()
        if not nl:
            raise HTTPException(404, f"Newsletter {newsletter_id} not found")
        if nl["status"] != "draft":
            raise HTTPException(400, "Can only add attachments to draft newsletters")

        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(400, "Only PDF files are allowed")

        # Sanitize filename to prevent path traversal
        safe_filename = os.path.basename(file.filename)
        if not safe_filename:
            raise HTTPException(400, "Invalid filename")

        content = await file.read()
        if len(content) > MAX_ATTACHMENT_SIZE:
            raise HTTPException(400, f"File too large. Max {MAX_ATTACHMENT_SIZE // (1024*1024)}MB")

        # Save file
        dest_dir = ATTACHMENT_DIR / str(newsletter_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / safe_filename
        dest_path.write_bytes(content)

        cur.execute(
            """INSERT INTO newsletter_attachments (newsletter_id, filename, content_type, file_path, file_size_bytes)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (newsletter_id, safe_filename, "application/pdf", str(dest_path), len(content)),
        )
        attachment_id = cur.fetchone()["id"]
        conn.commit()

        return {"id": attachment_id, "filename": safe_filename, "success": True}


@router.delete("/{newsletter_id}/attachments/{attachment_id}")
def delete_attachment(newsletter_id: int, attachment_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Remove a newsletter attachment."""
    with get_cursor(conn) as cur:
        # Verify newsletter belongs to user
        cur.execute("SELECT id FROM newsletters WHERE id = %s AND user_id = %s", (newsletter_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, "Newsletter not found")

        cur.execute(
            "SELECT id, file_path FROM newsletter_attachments WHERE id = %s AND newsletter_id = %s",
            (attachment_id, newsletter_id),
        )
        att = cur.fetchone()
        if not att:
            raise HTTPException(404, "Attachment not found")

        # Remove file
        file_path = Path(att["file_path"])
        if file_path.exists():
            file_path.unlink()

        cur.execute("DELETE FROM newsletter_attachments WHERE id = %s", (attachment_id,))
        conn.commit()
        return {"success": True}


@router.get("/{newsletter_id}/attachments/{attachment_id}/download")
def download_attachment(newsletter_id: int, attachment_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Serve a newsletter attachment file."""
    with get_cursor(conn) as cur:
        # Verify newsletter belongs to user
        cur.execute("SELECT id FROM newsletters WHERE id = %s AND user_id = %s", (newsletter_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, "Newsletter not found")

        cur.execute(
            "SELECT filename, file_path, content_type FROM newsletter_attachments WHERE id = %s AND newsletter_id = %s",
            (attachment_id, newsletter_id),
        )
        att = cur.fetchone()
        if not att:
            raise HTTPException(404, "Attachment not found")

        file_path = Path(att["file_path"])
        if not file_path.exists():
            raise HTTPException(404, "File not found on disk")

        return FileResponse(
            str(file_path),
            media_type=att["content_type"],
            filename=att["filename"],
        )


@router.get("/{newsletter_id}/recipients")
def preview_recipients(
    newsletter_id: int,
    lifecycle_stages: Optional[str] = None,
    product_ids: Optional[str] = None,
    newsletter_only: bool = True,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Preview filtered recipient list for a newsletter."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT id FROM newsletters WHERE id = %s AND user_id = %s", (newsletter_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, f"Newsletter {newsletter_id} not found")

        stages = [s.strip() for s in lifecycle_stages.split(",")] if lifecycle_stages else None
        pids = [int(p.strip()) for p in product_ids.split(",")] if product_ids else None

        recipients = _get_filtered_recipients(cur, stages, pids, newsletter_only, user_id=user["id"])
        return {
            "recipients": [dict(r) for r in recipients],
            "count": len(recipients),
        }


@router.post("/{newsletter_id}/send")
def send_newsletter_route(
    newsletter_id: int,
    body: NewsletterSendRequest,
    conn=Depends(get_db),
    config=Depends(get_config),
    user=Depends(get_current_user),
):
    """Send a newsletter to filtered recipients.

    Returns 202 Accepted immediately and processes sends in background.
    """
    from src.models.database import get_pool_connection, put_pool_connection, get_cursor
    from src.services.newsletter import send_newsletter_to_recipients

    with get_cursor(conn) as cur:
        cur.execute("SELECT * FROM newsletters WHERE id = %s AND user_id = %s", (newsletter_id, user["id"]))
        newsletter = cur.fetchone()
        if not newsletter:
            raise HTTPException(404, f"Newsletter {newsletter_id} not found")
        if newsletter["status"] not in ("draft", "failed"):
            raise HTTPException(400, f"Newsletter is already {newsletter['status']}")

        # Get recipients
        recipients = _get_filtered_recipients(
            cur, body.lifecycle_stages, body.product_ids, body.newsletter_only,
            user_id=user["id"],
        )
        if not recipients:
            raise HTTPException(400, "No recipients match the filters")

        # Get attachments
        cur.execute(
            "SELECT * FROM newsletter_attachments WHERE newsletter_id = %s",
            (newsletter_id,),
        )
        attachments = [dict(a) for a in cur.fetchall()]

        # Mark as sending
        cur.execute(
            "UPDATE newsletters SET status = 'sending', updated_at = NOW() WHERE id = %s AND user_id = %s",
            (newsletter_id, user["id"]),
        )
        conn.commit()

        # Materialize data for the background thread (dicts, not cursor rows)
        newsletter_data = dict(newsletter)
        recipients_data = [dict(r) for r in recipients]
        config_copy = dict(config)
        bg_user_id = user["id"]

    def _send_in_background():
        bg_conn = None
        try:
            bg_conn = get_pool_connection()
            send_newsletter_to_recipients(
                bg_conn, newsletter_id, newsletter_data,
                recipients_data, config_copy, attachments,
            )
        except (smtplib.SMTPException, psycopg2.Error, OSError) as exc:
            logger.exception("Background newsletter send failed for newsletter %s", newsletter_id)
            # Mark newsletter as failed
            if bg_conn:
                try:
                    with get_cursor(bg_conn) as bg_cur:
                        bg_cur.execute(
                            "UPDATE newsletters SET status = 'failed', updated_at = NOW() WHERE id = %s AND user_id = %s",
                            (newsletter_id, bg_user_id),
                        )
                        bg_conn.commit()
                except psycopg2.Error:
                    logger.exception("Failed to mark newsletter %s as failed", newsletter_id)
        finally:
            if bg_conn:
                put_pool_connection(bg_conn)

    thread = threading.Thread(target=_send_in_background, daemon=True)
    thread.start()

    return JSONResponse(
        status_code=202,
        content={
            "status": "sending",
            "newsletter_id": newsletter_id,
            "recipient_count": len(recipients_data),
        },
    )


def _get_filtered_recipients(cur, lifecycle_stages, product_ids, newsletter_only, *, user_id):
    """Build filtered recipient query."""
    conditions = [
        "co.user_id = %s",
        "c.email IS NOT NULL",
        "c.email != ''",
        "c.unsubscribed = false",
    ]
    params = [user_id]

    if newsletter_only:
        conditions.append("c.newsletter_status = 'subscribed'")

    if lifecycle_stages:
        placeholders = ", ".join(["%s"] * len(lifecycle_stages))
        conditions.append(f"c.lifecycle_stage IN ({placeholders})")
        params.extend(lifecycle_stages)

    joins = ""
    if product_ids:
        # Verify all product_ids belong to the current user
        placeholders = ", ".join(["%s"] * len(product_ids))
        cur.execute(
            f"SELECT id FROM products WHERE id IN ({placeholders}) AND user_id = %s",
            (*product_ids, user_id),
        )
        valid_ids = {row["id"] for row in cur.fetchall()}
        invalid_ids = set(product_ids) - valid_ids
        if invalid_ids:
            raise HTTPException(
                status_code=403,
                detail=f"Product IDs not owned by user: {sorted(invalid_ids)}",
            )

        joins = "JOIN contact_products cp ON cp.contact_id = c.id"
        conditions.append(f"cp.product_id IN ({placeholders})")
        params.extend(product_ids)

    where = " AND ".join(conditions)
    query = f"""
        SELECT DISTINCT c.id, c.full_name, c.email, c.first_name, c.last_name,
               c.lifecycle_stage, co.name AS company_name
        FROM contacts c
        JOIN companies co ON co.id = c.company_id
        {joins}
        WHERE {where}
        ORDER BY c.full_name
    """
    cur.execute(query, params)
    return cur.fetchall()
