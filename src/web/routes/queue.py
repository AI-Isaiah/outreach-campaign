"""Queue API routes — daily action queue with rendered messages."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.application.queue_service import apply_cross_campaign_email_dedup, get_enriched_queue
from src.config import DEFAULT_CAMPAIGN, load_config
from src.models.campaigns import get_campaign_by_name
from src.models.templates import get_template
from src.services.email_sender import send_campaign_email
from src.services.linkedin_actions import complete_linkedin_action
from src.services.priority_queue import defer_contact, get_defer_stats
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

logger = logging.getLogger(__name__)
_limiter = Limiter(key_func=get_remote_address)
router = APIRouter(tags=["queue"])


class LinkedInDoneRequest(BaseModel):
    action_type: str = Field(default="connect", max_length=50)


class QueueOverrideRequest(BaseModel):
    contact_id: int
    template_id: int


class DeferRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)
    campaign: str = Field(default=DEFAULT_CAMPAIGN, max_length=200)


class GenerateDraftRequest(BaseModel):
    campaign_id: int
    step_order: int


class GenerateDraftResponse(BaseModel):
    draft_subject: Optional[str] = None
    draft_text: str
    model: str
    channel: str
    generated_at: str
    has_research: bool


class BatchApproveItem(BaseModel):
    contact_id: int
    campaign_id: int


class BatchApproveRequest(BaseModel):
    items: List[BatchApproveItem]


@router.post("/queue/batch-approve")
def batch_approve(
    body: BatchApproveRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Set approved_at on specified contact_campaign_status rows."""
    user_id = user["id"]
    approved = 0
    for item in body.items:
        with get_cursor(conn) as cur:
            cur.execute(
                """UPDATE contact_campaign_status
                   SET approved_at = NOW()
                   WHERE contact_id = %s AND campaign_id = %s
                     AND approved_at IS NULL
                     AND campaign_id IN (SELECT id FROM campaigns WHERE user_id = %s)""",
                (item.contact_id, item.campaign_id, user_id),
            )
            approved += cur.rowcount
    conn.commit()
    return {"approved": approved}


@router.post("/queue/batch-send")
def batch_send(
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Send all approved-but-unsent queue items."""
    user_id = user["id"]

    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT ccs.contact_id, ccs.campaign_id,
                      ss.template_id, ss.channel
               FROM contact_campaign_status ccs
               JOIN campaigns c ON c.id = ccs.campaign_id AND c.user_id = %s
               JOIN sequence_steps ss
                 ON ss.campaign_id = ccs.campaign_id AND ss.step_order = ccs.current_step
               WHERE ccs.approved_at IS NOT NULL
                 AND ccs.sent_at IS NULL
                 AND ccs.status = 'in_progress'
                 AND ss.channel = 'email'""",
            (user_id,),
        )
        rows = cur.fetchall()

    if not rows:
        return {"sent": 0, "failed": 0, "errors": []}

    try:
        config = load_config()
    except FileNotFoundError:
        config = {}

    sent = 0
    failed = 0
    errors: list[dict] = []

    for row in rows:
        try:
            ok = send_campaign_email(
                conn,
                row["contact_id"],
                row["campaign_id"],
                row["template_id"],
                config,
                user_id=user_id,
            )
            if ok:
                sent += 1
            else:
                failed += 1
                errors.append({
                    "contact_id": row["contact_id"],
                    "campaign_id": row["campaign_id"],
                    "error": "send_campaign_email returned False",
                })
        except Exception as exc:
            logger.error(
                "batch_send failed for contact %s campaign %s: %s",
                row["contact_id"], row["campaign_id"], exc, exc_info=True,
            )
            failed += 1
            errors.append({
                "contact_id": row["contact_id"],
                "campaign_id": row["campaign_id"],
                "error": str(exc),
            })

    return {"sent": sent, "failed": failed, "errors": errors}


class ScheduleItem(BaseModel):
    contact_id: int
    campaign_id: int


class ScheduleRequest(BaseModel):
    items: List[ScheduleItem]
    schedule: str = Field(max_length=200)


def _resolve_schedule_times(schedule: str, count: int) -> list[datetime]:
    now = datetime.now(timezone.utc)

    if schedule == "now":
        return [now] * count

    if schedule == "tomorrow_9am":
        tomorrow_9am = (now + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0,
        )
        return [tomorrow_9am] * count

    if schedule == "spread_3_days":
        per_day = 5
        times: list[datetime] = []
        for i in range(count):
            day_offset = i // per_day + 1
            send_time = (now + timedelta(days=day_offset)).replace(
                hour=9, minute=0, second=0, microsecond=0,
            )
            times.append(send_time)
        return times

    try:
        parsed = datetime.fromisoformat(schedule)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return [parsed] * count
    except ValueError:
        raise ValueError(f"Unrecognized schedule: {schedule}")


@router.post("/queue/schedule")
def schedule_send(
    body: ScheduleRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    user_id = user["id"]

    if not body.items:
        return {"scheduled": 0}

    try:
        times = _resolve_schedule_times(body.schedule, len(body.items))
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    scheduled = 0
    with get_cursor(conn) as cur:
        for item, send_at in zip(body.items, times):
            cur.execute(
                """UPDATE contact_campaign_status
                   SET scheduled_for = %s,
                       approved_at = COALESCE(approved_at, NOW())
                   WHERE contact_id = %s AND campaign_id = %s
                     AND sent_at IS NULL
                     AND campaign_id IN (SELECT id FROM campaigns WHERE user_id = %s)""",
                (send_at, item.contact_id, item.campaign_id, user_id),
            )
            scheduled += cur.rowcount
    conn.commit()

    return {"scheduled": scheduled}


# Static routes MUST come before parameterized /queue/{campaign} to avoid capture
@router.get("/queue/defer/stats")
def defer_statistics(
    campaign: Optional[str] = None,
    date: Optional[str] = None,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get defer/skip analytics."""
    campaign_id = None
    if campaign:
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT id FROM campaigns WHERE name = %s AND user_id = %s",
                (campaign, user["id"]),
            )
            camp = cur.fetchone()
        if camp:
            campaign_id = camp["id"]

    return get_defer_stats(conn, campaign_id=campaign_id, target_date=date)


@router.get("/queue/all")
def get_all_queues(
    date: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get today's action queue across ALL active campaigns for the user."""
    # Find all active campaigns for this user
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id, name FROM campaigns WHERE user_id = %s AND status = 'active'",
            (user["id"],),
        )
        active_campaigns = cur.fetchall()

    if not active_campaigns:
        return {"items": [], "total": 0}

    # Collect queue items from each active campaign
    merged: list[dict] = []
    for camp in active_campaigns:
        try:
            result = get_enriched_queue(
                conn, camp["name"], date=date, limit=limit, user_id=user["id"],
            )
        except ValueError:
            continue

        for item in result.get("items", []):
            item["campaign_name"] = camp["name"]
            item["campaign_id"] = camp["id"]
            merged.append(item)

    # Sort by step_order ASC, then by contact_name as tiebreaker
    merged.sort(key=lambda x: (
        x.get("step_order") or 0,
        x.get("contact_name") or "",
    ))

    # Cross-campaign email dedup + limit in one pass
    merged = apply_cross_campaign_email_dedup(merged, limit=limit)

    return {"items": merged, "total": len(merged)}


@router.get("/queue/{campaign}")
def get_queue(
    campaign: str,
    date: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    mode: str = Query(default="adaptive"),
    firm_type: Optional[str] = Query(default=None),
    aum_min: Optional[float] = Query(default=None),
    aum_max: Optional[float] = Query(default=None),
    diverse: bool = Query(default=True),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get today's action queue with rendered messages."""
    try:
        return get_enriched_queue(
            conn, campaign,
            date=date, limit=limit, mode=mode,
            firm_type=firm_type, aum_min=aum_min, aum_max=aum_max,
            diverse=diverse,
            user_id=user["id"],
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/queue/{contact_id}/linkedin-done")
def mark_linkedin_done(
    contact_id: int,
    body: LinkedInDoneRequest,
    campaign: str = DEFAULT_CAMPAIGN,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Mark a LinkedIn action as manually completed."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id FROM campaigns WHERE name = %s AND user_id = %s",
            (campaign, user["id"]),
        )
        camp = cur.fetchone()
    if not camp:
        raise HTTPException(404, f"Campaign '{campaign}' not found")

    try:
        result = complete_linkedin_action(
            conn, contact_id, camp["id"], body.action_type,
            user_id=user["id"],
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/queue/{campaign}/override")
def override_template(
    campaign: str,
    body: QueueOverrideRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Override the recommended template for a contact in the queue."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id, name FROM campaigns WHERE name = %s AND user_id = %s",
            (campaign, user["id"]),
        )
        camp = cur.fetchone()
    if not camp:
        raise HTTPException(404, f"Campaign '{campaign}' not found")

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM templates WHERE id = %s AND user_id = %s",
            (body.template_id, user["id"]),
        )
        template = cur.fetchone()
    if not template:
        raise HTTPException(404, f"Template {body.template_id} not found")

    with get_cursor(conn) as cur:
        try:
            key = f"override_{body.contact_id}_{camp['id']}"
            cur.execute(
                """INSERT INTO engine_config (key, value, user_id, updated_at)
                   VALUES (%s, %s, %s, NOW())
                   ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
                (key, str(body.template_id), user["id"]),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "success": True,
        "contact_id": body.contact_id,
        "template_id": body.template_id,
        "template_name": template["name"],
    }


@router.post("/queue/{contact_id}/generate-draft", response_model=GenerateDraftResponse)
@_limiter.limit("10/minute")
def generate_ai_draft(
    request: Request,
    contact_id: int,
    body: GenerateDraftRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Generate an AI-personalized draft for a queue item."""
    from src.models.database import verify_ownership
    from src.services.message_drafter import generate_draft

    # Verify contact ownership
    if not verify_ownership(conn, "contacts", contact_id, user_id=user["id"]):
        raise HTTPException(404, "Contact not found")

    # Verify enrollment
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT current_step FROM contact_campaign_status
               WHERE contact_id = %s AND campaign_id = %s
               AND campaign_id IN (SELECT id FROM campaigns WHERE user_id = %s)""",
            (contact_id, body.campaign_id, user["id"]),
        )
        enrollment = cur.fetchone()
    if not enrollment:
        raise HTTPException(400, "Contact is not enrolled in this campaign")

    # Verify step_order matches current_step (safety check)
    if enrollment["current_step"] != body.step_order:
        raise HTTPException(
            400,
            f"Step mismatch: contact is at step {enrollment['current_step']}, "
            f"requested step {body.step_order}",
        )

    try:
        draft = generate_draft(
            conn, contact_id, body.campaign_id, body.step_order,
            user_id=user["id"],
        )
        return GenerateDraftResponse(
            draft_subject=draft["draft_subject"],
            draft_text=draft["draft_text"],
            model=draft["model"],
            channel=draft["channel"],
            generated_at=draft["generated_at"],
            has_research=draft["research_id"] is not None,
        )
    except ValueError as exc:
        if "empty or too-short" in str(exc):
            raise HTTPException(422, str(exc))
        raise HTTPException(404, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except httpx.TimeoutException:
        raise HTTPException(504, "AI service timeout — try again or use template")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise HTTPException(429, "AI service rate limited — try again in a minute")
        elif exc.response.status_code == 401:
            raise HTTPException(503, "AI API key invalid — check ANTHROPIC_API_KEY")
        raise HTTPException(502, f"AI service error: {exc.response.status_code}")
    except Exception as exc:
        logger.error("Unexpected draft generation error: %s", exc, exc_info=True)
        raise HTTPException(500, "Draft generation failed unexpectedly")


@router.post("/queue/{contact_id}/defer")
def defer_queue_contact(
    contact_id: int,
    body: DeferRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Defer/skip a contact in the queue. Pushes them to tomorrow."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id FROM campaigns WHERE name = %s AND user_id = %s",
            (body.campaign, user["id"]),
        )
        camp = cur.fetchone()
    if not camp:
        raise HTTPException(404, f"Campaign '{body.campaign}' not found")

    result = defer_contact(conn, contact_id, camp["id"], reason=body.reason)
    if not result["success"]:
        raise HTTPException(404, result.get("error", "Defer failed"))

    return result
