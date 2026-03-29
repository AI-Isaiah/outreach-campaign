"""Pending replies API routes."""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.services.gmail_drafter import GmailDrafter
from src.services.linkedin_acceptance_scanner import scan_linkedin_acceptances
from src.services.reply_detector import scan_gmail_for_replies
from src.services.state_machine import InvalidTransition, transition_contact
from cryptography.fernet import InvalidToken
from src.services.token_encryption import decrypt_token
from src.web.dependencies import get_current_user, get_db, verify_cron_secret
from src.models.database import get_cursor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["replies"])
cron_router = APIRouter(tags=["cron"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")


def _build_drafter_from_db(conn, user_id: int) -> GmailDrafter | None:
    """Load Gmail OAuth tokens from DB and return a GmailDrafter, or None."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT gmail_access_token, gmail_refresh_token, gmail_connected
               FROM users WHERE id = %s""",
            (user_id,),
        )
        row = cur.fetchone()

    if not row or not row["gmail_connected"] or not row["gmail_access_token"]:
        return None

    try:
        access_token = decrypt_token(row["gmail_access_token"])
        refresh_token = decrypt_token(row["gmail_refresh_token"]) if row["gmail_refresh_token"] else ""
    except (InvalidToken, ValueError):
        logger.exception("Failed to decrypt Gmail tokens for user %s", user_id)
        return None

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        logger.warning("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set")
        return None

    return GmailDrafter.from_db_tokens(
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )


class ConfirmReplyRequest(BaseModel):
    outcome: str = Field(max_length=50)
    note: Optional[str] = Field(default=None, max_length=5000)


@router.get("/replies/pending")
def list_pending_replies(
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """List unconfirmed pending replies with contact/company info."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT pr.*,
                      c.full_name AS contact_name, c.email AS contact_email,
                      co.name AS company_name, co.aum_millions
               FROM pending_replies pr
               JOIN contacts c ON c.id = pr.contact_id
               JOIN companies co ON co.id = c.company_id
               WHERE pr.confirmed = false AND co.user_id = %s
               ORDER BY pr.detected_at DESC""",
            (user["id"],),
        )
        replies = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT last_reply_scan_at FROM users WHERE id = %s",
            (user["id"],),
        )
        user_row = cur.fetchone()
        last_scan = user_row["last_reply_scan_at"] if user_row else None

    return {
        "replies": replies,
        "last_auto_scan_at": last_scan.isoformat() if last_scan else None,
    }


@router.post("/replies/{reply_id}/confirm")
def confirm_reply(
    reply_id: int,
    body: ConfirmReplyRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Confirm or correct a pending reply classification."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT pr.* FROM pending_replies pr
               JOIN contacts c ON c.id = pr.contact_id
               JOIN companies co ON co.id = c.company_id
               WHERE pr.id = %s AND co.user_id = %s""",
            (reply_id, user["id"]),
        )
        reply = cur.fetchone()
        if not reply:
            raise HTTPException(404, f"Reply {reply_id} not found")

        if reply["confirmed"]:
            raise HTTPException(400, "Reply already confirmed")

        # Update the reply record
        cur.execute(
            """UPDATE pending_replies
               SET confirmed = true, confirmed_outcome = %s, confirmed_at = NOW()
               WHERE id = %s""",
            (body.outcome, reply_id),
        )

        # Trigger state machine transition
        # Domain rule: neutral = positive (non-rejection is interest)
        status_map = {
            "replied_positive": "replied_positive",
            "replied_negative": "replied_negative",
            "neutral": "replied_positive",  # domain rule: non-rejection = positive
        }

        campaign_id = reply["campaign_id"]
        if not campaign_id:
            logger.warning(
                "Reply %d has no campaign_id — skipping state transition and outcome update",
                reply_id,
            )
        elif body.outcome in status_map:
            mapped_status = status_map[body.outcome]
            try:
                transition_contact(
                    conn, reply["contact_id"], campaign_id,
                    mapped_status,
                    user_id=user["id"],
                )
            except InvalidTransition:
                pass  # Contact may already be in this state

            # Update template history outcome
            _OUTCOME_BY_STATUS = {
                "replied_positive": "positive",
                "replied_negative": "negative",
            }
            outcome_value = _OUTCOME_BY_STATUS.get(mapped_status)
            if outcome_value:
                cur.execute(
                    """UPDATE contact_template_history
                       SET outcome = %s, outcome_at = NOW()
                       WHERE id = (
                           SELECT id FROM contact_template_history
                           WHERE contact_id = %s AND campaign_id = %s AND outcome IS NULL
                           ORDER BY sent_at DESC LIMIT 1
                       )""",
                    (outcome_value, reply["contact_id"], campaign_id),
                )

        # Save note if provided
        if body.note and campaign_id:
            cur.execute(
                """INSERT INTO response_notes (contact_id, campaign_id, note_type, content, user_id)
                   VALUES (%s, %s, %s, %s, %s)""",
                (reply["contact_id"], campaign_id, body.outcome, body.note, user["id"]),
            )

        conn.commit()

        # Auto-advance lifecycle on reply confirmation
        try:
            from src.services.lifecycle import on_positive_reply, on_email_sent
            if body.outcome in ("replied_positive", "neutral"):
                on_positive_reply(conn, reply["contact_id"], user_id=user["id"])
            else:
                on_email_sent(conn, reply["contact_id"], user_id=user["id"])
        except Exception:
            pass  # lifecycle is non-blocking

        return {"success": True, "reply_id": reply_id, "outcome": body.outcome}


@router.post("/replies/scan")
def trigger_reply_scan(
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Scan Gmail inbox for replies from enrolled contacts."""
    try:
        drafter = _build_drafter_from_db(conn, user["id"])
        result = scan_gmail_for_replies(conn, drafter=drafter, user_id=user["id"])
        return {"status": "ok", **result}
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/replies/scan-linkedin")
def trigger_linkedin_scan(
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Scan Gmail for LinkedIn connection acceptance notifications.

    Searches for emails from LinkedIn indicating someone accepted
    a connection request. Matches to contacts and auto-advances
    their campaign sequence from linkedin_connect to the next step.
    """
    try:
        result = scan_linkedin_acceptances(conn, user_id=user["id"])
        return {"status": "ok", **result}
    except RuntimeError as e:
        raise HTTPException(400, str(e))


CRON_BATCH_SIZE = 10


@cron_router.post("/cron/scan-replies")
def cron_scan_replies(conn=Depends(get_db), _=Depends(verify_cron_secret)):
    """Batch-scan replies for all Gmail-connected users (called by Vercel cron)."""
    errors: list[str] = []

    with get_cursor(conn) as cur:
        cur.execute("SELECT COALESCE(MAX(last_scan_cursor), 0) AS cursor FROM users")
        cursor_row = cur.fetchone()
        cursor_pos = cursor_row["cursor"] if cursor_row else 0

        cur.execute(
            """SELECT id FROM users
               WHERE gmail_connected = true AND gmail_access_token IS NOT NULL
                     AND id > %s
               ORDER BY id LIMIT %s""",
            (cursor_pos, CRON_BATCH_SIZE),
        )
        batch = [r["id"] for r in cur.fetchall()]

        cur.execute(
            """SELECT COUNT(*) AS cnt FROM users
               WHERE gmail_connected = true AND gmail_access_token IS NOT NULL
                     AND id > %s""",
            (cursor_pos,),
        )
        total_remaining = cur.fetchone()["cnt"]

    processed = 0
    for user_id in batch:
        try:
            drafter = _build_drafter_from_db(conn, user_id)
            if drafter is None:
                logger.info("Skipping user %d — drafter unavailable", user_id)
                continue

            scan_gmail_for_replies(conn, drafter=drafter, user_id=user_id)

            with get_cursor(conn) as cur:
                cur.execute(
                    "UPDATE users SET last_reply_scan_at = NOW() WHERE id = %s",
                    (user_id,),
                )
                conn.commit()
            processed += 1
        except Exception as exc:
            logger.exception("Cron scan failed for user %d", user_id)
            errors.append(f"user {user_id}: {exc}")

    new_cursor = batch[-1] if batch else 0
    remaining = total_remaining - len(batch)
    if remaining <= 0:
        new_cursor = 0

    with get_cursor(conn) as cur:
        cur.execute(
            "UPDATE users SET last_scan_cursor = %s WHERE id = (SELECT MIN(id) FROM users)",
            (new_cursor,),
        )
        conn.commit()

    return {
        "processed": processed,
        "remaining": max(remaining, 0),
        "errors": errors,
    }


SCHEDULED_SEND_BATCH_SIZE = 10


@cron_router.post("/cron/send-scheduled")
def cron_send_scheduled(conn=Depends(get_db), _=Depends(verify_cron_secret)):
    """Send emails whose scheduled_for time has arrived (called by Vercel cron)."""
    from src.application.queue_service import send_email_batch
    from src.config import load_config_safe

    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT ccs.contact_id, ccs.campaign_id,
                      ss.template_id, c.user_id
               FROM contact_campaign_status ccs
               JOIN campaigns c ON c.id = ccs.campaign_id
               JOIN sequence_steps ss
                 ON ss.campaign_id = ccs.campaign_id AND ss.stable_id = ccs.current_step_id
               WHERE ccs.approved_at IS NOT NULL
                 AND ccs.scheduled_for IS NOT NULL
                 AND ccs.scheduled_for <= NOW()
                 AND ccs.sent_at IS NULL
                 AND ccs.status = 'in_progress'
                 AND ss.channel = 'email'
               ORDER BY ccs.scheduled_for
               LIMIT %s""",
            (SCHEDULED_SEND_BATCH_SIZE,),
        )
        rows = cur.fetchall()

    if not rows:
        return {"sent": 0, "failed": 0, "errors": []}

    config = load_config_safe()
    return send_email_batch(conn, rows, config)
