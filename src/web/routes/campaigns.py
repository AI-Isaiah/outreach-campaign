"""Campaign API routes."""

from __future__ import annotations

from typing import Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.application.campaign_service import launch_campaign as _launch_campaign
from src.models.campaigns import delete_campaign, get_campaign, get_campaign_by_name, update_campaign_status
from src.services.metrics import (
    compute_health_score,
    get_campaign_metrics,
    get_company_type_breakdown,
    get_variant_comparison,
    get_weekly_summary,
)
from src.services.response_analyzer import annotate_is_winning, get_template_performance
from src.services.campaign_sequence import reorder_campaign_sequence
from src.web.dependencies import get_current_user, get_db
from src.web.schemas import CampaignSummary
from src.models.database import get_cursor, verify_ownership

_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["campaigns"])


# ---------------------------------------------------------------------------
# Pydantic models for campaign launch
# ---------------------------------------------------------------------------

class SequenceStepInput(BaseModel):
    step_order: int
    channel: str = Field(max_length=50)
    delay_days: int = Field(ge=0)
    template_id: int | None = None
    draft_mode: str = "template"  # "template" or "ai"


class LaunchCampaignRequest(BaseModel):
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=1000)
    steps: list[SequenceStepInput]
    contact_ids: list[int]
    status: str = Field(default="active")


class UpdateCampaignStatusRequest(BaseModel):
    status: str = Field(pattern="^(active|paused|archived)$")


def _row_to_dict(row) -> dict:
    """Convert a database row to a plain dict."""
    return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Atomic campaign launch (must be registered BEFORE /{name} to avoid capture)
# ---------------------------------------------------------------------------

@router.post("/campaigns/launch")
def launch_campaign(
    body: LaunchCampaignRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a campaign with sequence steps and enroll contacts in one transaction."""
    try:
        return _launch_campaign(
            conn,
            name=body.name,
            description=body.description,
            steps=[s.model_dump() for s in body.steps],
            contact_ids=body.contact_ids,
            status=body.status,
            user_id=user["id"],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except psycopg2.IntegrityError as exc:
        conn.rollback()
        msg = str(exc)
        if "campaigns_user_name_unique" in msg or "campaigns_name_key" in msg:
            raise HTTPException(409, f"Campaign '{body.name}' already exists")
        raise HTTPException(400, f"Integrity error: {msg}")
    except psycopg2.Error:
        conn.rollback()
        raise HTTPException(500, "Failed to launch campaign")


@router.patch("/campaigns/{name}/status")
def patch_campaign_status(
    name: str,
    body: UpdateCampaignStatusRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update campaign status (active, paused, archived)."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")
    update_campaign_status(conn, camp["id"], body.status, user_id=user["id"])
    return {"name": name, "status": body.status}


@router.delete("/campaigns/{name}")
@_limiter.limit("5/minute")
def remove_campaign(
    request: Request,
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a campaign and all its enrollments and sequence steps."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")
    deleted = delete_campaign(conn, camp["id"], user_id=user["id"])
    if not deleted:
        raise HTTPException(500, "Failed to delete campaign")
    return {"name": name, "deleted": True}


class EnrollContactsRequest(BaseModel):
    contact_ids: list[int] = Field(min_length=1, max_length=500)


@router.post("/campaigns/{campaign_id}/enroll")
def enroll_contacts_in_campaign(
    campaign_id: int,
    body: EnrollContactsRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Add contacts to an existing campaign."""
    user_id = user["id"]
    from src.models.enrollment import bulk_enroll_contacts, get_sequence_steps

    camp = get_campaign(conn, campaign_id, user_id=user_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")

    # Find step 1 stable_id for enrollment
    steps = get_sequence_steps(conn, campaign_id, user_id=user_id)
    first_step_stable_id = str(steps[0]["stable_id"]) if steps else None

    enrolled = bulk_enroll_contacts(
        conn, campaign_id, body.contact_ids,
        first_step_stable_id=first_step_stable_id,
        user_id=user_id,
    )
    conn.commit()
    return {"enrolled": enrolled, "campaign_id": campaign_id}


@router.get("/campaigns")
def list_all_campaigns(
    status: Optional[str] = None,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """List all campaigns with embedded metrics (CTE for O(1) table scans)."""
    user_id = user["id"]
    status_filter = "AND c.status = %s" if status else "AND c.status != 'archived'"

    query = f"""
    WITH campaign_stats AS (
        SELECT ccs.campaign_id,
               COUNT(*) AS contacts_count,
               COUNT(*) FILTER (WHERE ccs.status IN
                   ('replied_positive','replied_negative','no_response','bounced')
               ) AS contacted_count,
               COUNT(*) FILTER (WHERE ccs.status IN
                   ('replied_positive','replied_negative')
               ) AS replied_count,
               COUNT(*) FILTER (WHERE ccs.status = 'replied_positive'
               ) AS positive_count,
               COUNT(*) FILTER (WHERE ccs.status = 'bounced'
               ) AS bounced_count,
               COUNT(*) FILTER (WHERE ccs.status IN
                   ('replied_positive','replied_negative','no_response',
                    'bounced','completed')
               ) AS completed_count
        FROM contact_campaign_status ccs
        JOIN campaigns ca ON ca.id = ccs.campaign_id AND ca.user_id = %s
        GROUP BY ccs.campaign_id
    ),
    campaign_calls AS (
        SELECT e.campaign_id, COUNT(*) AS calls_booked
        FROM events e
        WHERE e.event_type = 'call_booked' AND e.user_id = %s
        GROUP BY e.campaign_id
    ),
    campaign_sends AS (
        SELECT e.campaign_id, COUNT(*) AS emails_sent
        FROM events e
        WHERE e.event_type = 'email_sent' AND e.user_id = %s
        GROUP BY e.campaign_id
    )
    SELECT c.*,
           COALESCE(cs.contacts_count, 0) AS contacts_count,
           COALESCE(cs.replied_count, 0) AS replied_count,
           CASE WHEN COALESCE(cs.contacted_count, 0) > 0
                THEN ROUND(cs.replied_count::numeric / cs.contacted_count * 100, 1)
                ELSE 0 END AS reply_rate,
           COALESCE(cc.calls_booked, 0) AS calls_booked,
           CASE WHEN COALESCE(cs.contacts_count, 0) > 0
                THEN ROUND(cs.completed_count::numeric / cs.contacts_count * 100, 1)
                ELSE 0 END AS progress_pct,
           COALESCE(cs.positive_count, 0) AS positive_count,
           COALESCE(cs.bounced_count, 0) AS bounced_count,
           COALESCE(csn.emails_sent, 0) AS emails_sent
    FROM campaigns c
    LEFT JOIN campaign_stats cs ON cs.campaign_id = c.id
    LEFT JOIN campaign_calls cc ON cc.campaign_id = c.id
    LEFT JOIN campaign_sends csn ON csn.campaign_id = c.id
    WHERE c.user_id = %s {status_filter}
    ORDER BY c.created_at DESC
    """

    # Build final params: [user_id (stats CTE), user_id (calls CTE), user_id (sends CTE), user_id (WHERE)]
    final_params = [user_id, user_id, user_id, user_id]
    if status:
        final_params.append(status)

    with get_cursor(conn) as cur:
        cur.execute(query, final_params)
        rows = [_row_to_dict(r) for r in cur.fetchall()]

    for row in rows:
        metrics_compat = {
            "total_enrolled": row.get("contacts_count", 0),
            "by_status": {
                "replied_positive": row.get("positive_count", 0),
                "bounced": row.get("bounced_count", 0),
            },
            "emails_sent": row.get("emails_sent", 0),
        }
        row["health_score"] = compute_health_score(metrics_compat)

    return rows


@router.get("/campaigns/{campaign_id}/contacts")
def get_campaign_contacts(
    campaign_id: int,
    status: Optional[str] = None,
    sort: str = "step",
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get contacts enrolled in a specific campaign with their step and status."""
    user_id = user["id"]

    # Verify campaign belongs to user
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id FROM campaigns WHERE id = %s AND user_id = %s",
            (campaign_id, user_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Campaign not found")

    sort_map = {
        "step": "ccs.current_step ASC, ccs.next_action_date ASC",
        "name": "COALESCE(c.full_name, c.first_name) ASC",
        "status": "ccs.status ASC",
    }
    order_by = sort_map.get(sort, sort_map["step"])

    query = f"""
    SELECT c.id, c.first_name, c.last_name, c.full_name,
           c.email_normalized AS email, c.linkedin_url_normalized AS linkedin_url,
           c.title,
           comp.name AS company_name, comp.id AS company_id,
           ccs.current_step, ccs.status, ccs.next_action_date,
           ccs.assigned_variant,
           ss_cur.channel AS current_channel,
           (SELECT COUNT(*) FROM sequence_steps ss
            WHERE ss.campaign_id = %s) AS total_steps
    FROM contact_campaign_status ccs
    JOIN contacts c ON c.id = ccs.contact_id
    LEFT JOIN companies comp ON comp.id = c.company_id
    LEFT JOIN sequence_steps ss_cur ON ss_cur.campaign_id = ccs.campaign_id
         AND ss_cur.stable_id = ccs.current_step_id
    WHERE ccs.campaign_id = %s AND c.user_id = %s
    {"AND ccs.status = %s" if status else ""}
    ORDER BY {order_by}
    """

    params: list = [campaign_id, campaign_id, user_id]
    if status:
        params.append(status)

    with get_cursor(conn) as cur:
        cur.execute(query, params)
        return [_row_to_dict(r) for r in cur.fetchall()]


@router.get("/campaigns/{name}")
def get_campaign(
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get campaign details by name."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")
    result = _row_to_dict(camp)
    metrics = get_campaign_metrics(conn, camp["id"], user_id=user["id"])
    result["health_score"] = compute_health_score(metrics)
    return result


@router.get("/campaigns/{campaign_id}/sequence")
def get_campaign_sequence(
    campaign_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get sequence steps for a campaign."""
    from src.models.enrollment import get_sequence_steps
    steps = get_sequence_steps(conn, campaign_id, user_id=user["id"])
    return steps


@router.get("/campaigns/{name}/metrics")
def get_metrics(
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get campaign metrics."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")

    campaign_id = camp["id"]
    uid = user["id"]
    metrics = get_campaign_metrics(conn, campaign_id, user_id=uid)
    variants = get_variant_comparison(conn, campaign_id, user_id=uid)
    weekly = get_weekly_summary(conn, campaign_id, weeks_back=1, user_id=uid)
    firm_breakdown = get_company_type_breakdown(conn, campaign_id, user_id=uid)

    campaign_dict = _row_to_dict(camp)
    campaign_dict["health_score"] = compute_health_score(metrics)

    return {
        "campaign": campaign_dict,
        "metrics": metrics,
        "variants": variants,
        "weekly": weekly,
        "firm_breakdown": firm_breakdown,
    }


@router.get("/campaigns/{name}/weekly")
def get_campaign_weekly(
    name: str,
    weeks_back: int = 1,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get weekly summary for a campaign."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")

    weekly = get_weekly_summary(conn, camp["id"], weeks_back=weeks_back, user_id=user["id"])
    return {"campaign": name, "weekly": weekly}


@router.get("/campaigns/{name}/report")
def get_campaign_report(
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get full campaign report with metrics, variants, and breakdown."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")

    campaign_id = camp["id"]
    uid = user["id"]
    return {
        "campaign": _row_to_dict(camp),
        "metrics": get_campaign_metrics(conn, campaign_id, user_id=uid),
        "variants": get_variant_comparison(conn, campaign_id, user_id=uid),
        "weekly": get_weekly_summary(conn, campaign_id, weeks_back=1, user_id=uid),
        "firm_breakdown": get_company_type_breakdown(conn, campaign_id, user_id=uid),
    }


@router.get("/campaigns/{name}/template-performance")
def get_campaign_template_performance(
    name: str,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get template performance metrics with winning badge for a campaign."""
    camp = get_campaign_by_name(conn, name, user_id=user["id"])
    if not camp:
        raise HTTPException(404, f"Campaign '{name}' not found")

    results = get_template_performance(conn, camp["id"], user_id=user["id"])
    return annotate_is_winning(results)


# ---------------------------------------------------------------------------
# Sequence Editor v2 endpoints
# ---------------------------------------------------------------------------

class ReorderStep(BaseModel):
    step_id: int
    step_order: int
    delay_days: Optional[int] = None
    channel: Optional[str] = None


class ReorderRequest(BaseModel):
    steps: list[ReorderStep]


@router.put("/campaigns/{campaign_id}/sequence/reorder")
def reorder_sequence(
    campaign_id: int,
    body: ReorderRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Reorder sequence steps for a campaign. Recalculates next_action_date for affected contacts."""
    user_id = user["id"]
    if not verify_ownership(conn, "campaigns", campaign_id, user_id):
        raise HTTPException(404, "Campaign not found")

    try:
        step_dicts = [s.model_dump() for s in body.steps]
        return reorder_campaign_sequence(conn, campaign_id, step_dicts, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class StepUpdateRequest(BaseModel):
    channel: Optional[str] = None
    delay_days: Optional[int] = None
    template_id: Optional[int] = None


@router.patch("/campaigns/{campaign_id}/sequence/{step_id}")
def update_sequence_step(
    campaign_id: int,
    step_id: int,
    body: StepUpdateRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update a single sequence step (channel, delay_days, or template_id)."""
    user_id = user["id"]
    with get_cursor(conn) as cursor:
        # Verify campaign + step ownership
        cursor.execute(
            "SELECT ss.id, ss.step_order FROM sequence_steps ss "
            "JOIN campaigns c ON c.id = ss.campaign_id "
            "WHERE ss.id = %s AND ss.campaign_id = %s AND c.user_id = %s",
            (step_id, campaign_id, user_id),
        )
        step = cursor.fetchone()
        if not step:
            raise HTTPException(404, "Step not found")

        fields: list[str] = []
        params: list = []

        if body.channel is not None:
            # Enforce only one linkedin_connect
            if body.channel == "linkedin_connect":
                cursor.execute(
                    "SELECT id FROM sequence_steps "
                    "WHERE campaign_id = %s AND channel = 'linkedin_connect' AND id != %s",
                    (campaign_id, step_id),
                )
                if cursor.fetchone():
                    raise HTTPException(
                        422, "Only one linkedin_connect step allowed per sequence"
                    )
            fields.append("channel = %s")
            params.append(body.channel)

        if body.delay_days is not None:
            if body.delay_days < 0:
                raise HTTPException(422, "delay_days must be >= 0")
            fields.append("delay_days = %s")
            params.append(body.delay_days)

        if body.template_id is not None:
            fields.append("template_id = %s")
            params.append(body.template_id)

        if not fields:
            raise HTTPException(422, "No fields to update")

        params.extend([step_id, campaign_id])
        cursor.execute(
            f"UPDATE sequence_steps SET {', '.join(fields)} "
            f"WHERE id = %s AND campaign_id = %s RETURNING *",
            params,
        )
        updated = cursor.fetchone()

        # If delay_days changed, recalculate next_action_date for affected contacts
        if body.delay_days is not None:
            cursor.execute("""
                UPDATE contact_campaign_status ccs
                SET next_action_date = (
                    SELECT CURRENT_DATE + (ss_next.delay_days || ' days')::interval
                    FROM sequence_steps ss_cur
                    JOIN sequence_steps ss_next
                      ON ss_next.campaign_id = ss_cur.campaign_id
                      AND ss_next.step_order = (
                        SELECT MIN(step_order) FROM sequence_steps
                        WHERE campaign_id = ss_cur.campaign_id AND step_order > ss_cur.step_order
                      )
                    WHERE ss_cur.stable_id = ccs.current_step_id
                )
                WHERE ccs.campaign_id = %s
                  AND ccs.status IN ('queued', 'in_progress')
                  AND ccs.current_step_id IS NOT NULL
            """, (campaign_id,))

        conn.commit()

    return _row_to_dict(updated)


@router.get("/campaigns/{campaign_id}/messages")
def get_campaign_messages(
    campaign_id: int,
    limit: int = 25,
    offset: int = 0,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get sent messages for a campaign with contact and template info."""
    user_id = user["id"]
    with get_cursor(conn) as cursor:
        if not verify_ownership(conn, "campaigns", campaign_id, user_id):
            raise HTTPException(404, "Campaign not found")

        # Single query with window function for count + pagination
        cursor.execute("""
            SELECT
                e.id, e.contact_id, e.event_type, e.created_at AS sent_at,
                COALESCE(c.full_name,
                    TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')),
                    '') AS contact_name,
                comp.name AS company_name,
                t.subject AS template_subject,
                ccs.status AS reply_status,
                COUNT(*) OVER () AS total
            FROM events e
            JOIN contacts c ON c.id = e.contact_id
            LEFT JOIN companies comp ON comp.id = c.company_id
            LEFT JOIN templates t ON t.id = e.template_id
            LEFT JOIN contact_campaign_status ccs
              ON ccs.contact_id = e.contact_id AND ccs.campaign_id = e.campaign_id
            WHERE e.campaign_id = %s
              AND e.event_type IN ('email_sent', 'linkedin_connect', 'linkedin_message', 'linkedin_sent')
              AND e.user_id = %s
            ORDER BY e.created_at DESC
            LIMIT %s OFFSET %s
        """, (campaign_id, user_id, limit, offset))
        rows = cursor.fetchall()
        messages = [_row_to_dict(r) for r in rows]
        total = rows[0]["total"] if rows else 0

    return {"messages": messages, "total": total}


class AddStepRequest(BaseModel):
    channel: str
    delay_days: int = 0
    template_id: Optional[int] = None
    step_order: Optional[int] = None


@router.post("/campaigns/{campaign_id}/sequence")
def add_sequence_step(
    campaign_id: int,
    body: AddStepRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Add a new step to a campaign's sequence. Blocked if contacts are enrolled."""
    user_id = user["id"]
    with get_cursor(conn) as cursor:
        if not verify_ownership(conn, "campaigns", campaign_id, user_id):
            raise HTTPException(404, "Campaign not found")

        # Block if enrolled contacts exist
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM contact_campaign_status WHERE campaign_id = %s",
            (campaign_id,),
        )
        if cursor.fetchone()["cnt"] > 0:
            raise HTTPException(
                422, "Cannot add steps to a campaign with enrolled contacts"
            )

        # linkedin_connect constraint
        if body.channel == "linkedin_connect":
            cursor.execute(
                "SELECT id FROM sequence_steps "
                "WHERE campaign_id = %s AND channel = 'linkedin_connect'",
                (campaign_id,),
            )
            if cursor.fetchone():
                raise HTTPException(
                    422, "Only one linkedin_connect step allowed per sequence"
                )

        if body.step_order is not None:
            # Insert at position, renumber subsequent
            cursor.execute(
                "UPDATE sequence_steps SET step_order = step_order + 10000 "
                "WHERE campaign_id = %s",
                (campaign_id,),
            )
            cursor.execute(
                """UPDATE sequence_steps SET step_order = CASE
                   WHEN step_order - 10000 >= %s THEN step_order - 10000 + 1
                   ELSE step_order - 10000
                   END WHERE campaign_id = %s""",
                (body.step_order, campaign_id),
            )
            new_order = body.step_order
        else:
            cursor.execute(
                "SELECT COALESCE(MAX(step_order), 0) + 1 as next_order "
                "FROM sequence_steps WHERE campaign_id = %s",
                (campaign_id,),
            )
            new_order = cursor.fetchone()["next_order"]

        cursor.execute(
            """INSERT INTO sequence_steps
               (campaign_id, step_order, channel, delay_days, template_id)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (campaign_id, new_order, body.channel, body.delay_days, body.template_id),
        )
        new_step = cursor.fetchone()
        conn.commit()

    return _row_to_dict(new_step)


@router.delete("/campaigns/{campaign_id}/sequence/{step_id}")
@_limiter.limit("10/minute")
def delete_sequence_step(
    request: Request,
    campaign_id: int,
    step_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a sequence step and compact step_order. Blocked if contacts are enrolled."""
    user_id = user["id"]
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT ss.id, ss.step_order FROM sequence_steps ss "
            "JOIN campaigns c ON c.id = ss.campaign_id "
            "WHERE ss.id = %s AND ss.campaign_id = %s AND c.user_id = %s",
            (step_id, campaign_id, user_id),
        )
        step = cursor.fetchone()
        if not step:
            raise HTTPException(404, "Step not found")

        # Block if enrolled contacts exist
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM contact_campaign_status WHERE campaign_id = %s",
            (campaign_id,),
        )
        if cursor.fetchone()["cnt"] > 0:
            raise HTTPException(
                422, "Cannot delete steps from a campaign with enrolled contacts"
            )

        cursor.execute(
            "DELETE FROM sequence_steps WHERE id = %s AND campaign_id = %s",
            (step_id, campaign_id),
        )

        # Compact step_order (remove gaps)
        cursor.execute(
            "UPDATE sequence_steps SET step_order = step_order + 10000 "
            "WHERE campaign_id = %s",
            (campaign_id,),
        )
        cursor.execute("""
            WITH numbered AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY step_order) as new_order
                FROM sequence_steps WHERE campaign_id = %s
            )
            UPDATE sequence_steps ss SET step_order = n.new_order
            FROM numbered n WHERE ss.id = n.id
        """, (campaign_id,))

        conn.commit()

    return {"deleted": True}
