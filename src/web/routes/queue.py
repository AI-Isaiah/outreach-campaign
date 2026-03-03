"""Queue API routes — daily action queue with rendered messages."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.config import load_config
from src.models.campaigns import get_campaign_by_name, get_template
from src.services.adaptive_queue import get_adaptive_queue
from src.services.email_sender import render_campaign_email, _render_inline_template
from src.services.linkedin_actions import complete_linkedin_action
from src.services.priority_queue import get_daily_queue
from src.services.template_engine import get_template_context, render_template
from src.web.dependencies import get_db

router = APIRouter(tags=["queue"])


class LinkedInDoneRequest(BaseModel):
    action_type: str = "connect"  # connect | message | engage | insight | final


class QueueOverrideRequest(BaseModel):
    contact_id: int
    template_id: int


@router.get("/queue/{campaign}")
def get_queue(
    campaign: str,
    date: Optional[str] = None,
    limit: int = 20,
    mode: str = "adaptive",
    conn=Depends(get_db),
):
    """Get today's action queue with rendered messages.

    mode: 'adaptive' (default, uses scoring + template selection) or 'static' (legacy).
    """
    camp = get_campaign_by_name(conn, campaign)
    if not camp:
        raise HTTPException(404, f"Campaign '{campaign}' not found")

    campaign_id = camp["id"]

    if mode == "adaptive":
        try:
            items = get_adaptive_queue(conn, campaign_id, target_date=date, limit=limit)
        except Exception:
            # Fallback to static on error
            items = get_daily_queue(conn, campaign_id, target_date=date, limit=limit)
    else:
        items = get_daily_queue(conn, campaign_id, target_date=date, limit=limit)

    try:
        config = load_config()
    except FileNotFoundError:
        config = {}

    enriched = []
    for item in items:
        entry = {**item}

        if item["channel"] == "email" and item["template_id"]:
            rendered = render_campaign_email(
                conn, item["contact_id"], campaign_id, item["template_id"], config
            )
            if rendered:
                entry["rendered_email"] = rendered
            else:
                entry["rendered_email"] = None

            # Check for existing Gmail draft
            cur = conn.cursor()
            cur.execute(
                """SELECT gmail_draft_id, status FROM gmail_drafts
                   WHERE contact_id = %s AND campaign_id = %s
                   ORDER BY id DESC LIMIT 1""",
                (item["contact_id"], campaign_id),
            )
            draft_row = cur.fetchone()
            entry["gmail_draft"] = (
                {"draft_id": draft_row["gmail_draft_id"], "status": draft_row["status"]}
                if draft_row else None
            )

        elif item["channel"].startswith("linkedin") and item["template_id"]:
            # Render the LinkedIn message
            template_row = get_template(conn, item["template_id"])
            if template_row:
                context = get_template_context(conn, item["contact_id"], config)
                body = (
                    render_template(template_row["body_template"], context)
                    if template_row["body_template"].endswith(".txt")
                    else _render_inline_template(template_row["body_template"], context)
                )
                entry["rendered_message"] = body
            else:
                entry["rendered_message"] = None

            # Add LinkedIn URL and Sales Nav link
            cur = conn.cursor()
            cur.execute(
                "SELECT linkedin_url FROM contacts WHERE id = %s",
                (item["contact_id"],),
            )
            contact_row = cur.fetchone()
            if contact_row and contact_row["linkedin_url"]:
                li_url = contact_row["linkedin_url"]
                entry["linkedin_url"] = li_url
                # Construct Sales Navigator deep link
                if "/in/" in li_url:
                    slug = li_url.rstrip("/").split("/in/")[-1]
                    entry["sales_nav_url"] = (
                        f"https://www.linkedin.com/sales/people/{slug}"
                    )

        enriched.append(entry)

    return {
        "campaign": campaign,
        "campaign_id": campaign_id,
        "date": date,
        "items": enriched,
        "total": len(enriched),
    }


@router.post("/queue/{contact_id}/linkedin-done")
def mark_linkedin_done(
    contact_id: int,
    body: LinkedInDoneRequest,
    campaign: str = "Q1_2026_initial",
    conn=Depends(get_db),
):
    """Mark a LinkedIn action as manually completed."""
    camp = get_campaign_by_name(conn, campaign)
    if not camp:
        raise HTTPException(404, f"Campaign '{campaign}' not found")

    try:
        result = complete_linkedin_action(
            conn, contact_id, camp["id"], body.action_type
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/queue/{campaign}/override")
def override_template(
    campaign: str,
    body: QueueOverrideRequest,
    conn=Depends(get_db),
):
    """Override the recommended template for a contact in the queue."""
    camp = get_campaign_by_name(conn, campaign)
    if not camp:
        raise HTTPException(404, f"Campaign '{campaign}' not found")

    template = get_template(conn, body.template_id)
    if not template:
        raise HTTPException(404, f"Template {body.template_id} not found")

    # Store override in engine_config as contact-specific override
    cur = conn.cursor()
    key = f"override_{body.contact_id}_{camp['id']}"
    cur.execute(
        """INSERT INTO engine_config (key, value, updated_at)
           VALUES (%s, %s, NOW())
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
        (key, str(body.template_id)),
    )
    conn.commit()

    return {
        "success": True,
        "contact_id": body.contact_id,
        "template_id": body.template_id,
        "template_name": template["name"],
    }
