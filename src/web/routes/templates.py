"""Template CRUD API routes."""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

logger = logging.getLogger(__name__)
_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["templates"])


class TemplateCreateRequest(BaseModel):
    name: str = Field(max_length=200)
    channel: str = Field(max_length=50)
    body_template: str = Field(max_length=5000)
    subject: Optional[str] = Field(default=None, max_length=200)
    variant_group: Optional[str] = Field(default=None, max_length=100)
    variant_label: Optional[str] = Field(default=None, max_length=100)


class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    channel: Optional[str] = Field(default=None, max_length=50)
    body_template: Optional[str] = Field(default=None, max_length=5000)
    subject: Optional[str] = Field(default=None, max_length=200)
    variant_group: Optional[str] = Field(default=None, max_length=100)
    variant_label: Optional[str] = Field(default=None, max_length=100)


@router.get("/templates")
def list_all_templates(
    channel: Optional[str] = None,
    active: bool = True,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """List templates with optional channel filter."""
    with get_cursor(conn) as cur:
        clauses = ["user_id = %s", "is_active = %s"]
        params: list = [user["id"], active]
        if channel:
            clauses.append("channel = %s")
            params.append(channel)
        cur.execute(
            f"SELECT * FROM templates WHERE {' AND '.join(clauses)} ORDER BY name",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def _get_template_scoped(conn, template_id: int, user_id):
    """Fetch a template by ID scoped to user_id."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM templates WHERE id = %s AND user_id = %s",
            (template_id, user_id),
        )
        return cur.fetchone()


@router.get("/templates/{template_id}")
def get_template_by_id(
    template_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get a single template by ID."""
    row = _get_template_scoped(conn, template_id, user["id"])
    if not row:
        raise HTTPException(404, f"Template {template_id} not found")
    return dict(row)


@router.post("/templates")
def create_new_template(
    body: TemplateCreateRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a new template."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO templates
               (name, channel, body_template, subject, variant_group, variant_label, user_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                body.name,
                body.channel,
                body.body_template,
                body.subject,
                body.variant_group,
                body.variant_label,
                user["id"],
            ),
        )
        template_id = cur.fetchone()["id"]
        conn.commit()
        return {"id": template_id, "success": True}


@router.put("/templates/{template_id}")
def update_template(
    template_id: int,
    body: TemplateUpdateRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update a template."""
    existing = _get_template_scoped(conn, template_id, user["id"])
    if not existing:
        raise HTTPException(404, f"Template {template_id} not found")

    fields = []
    params = []
    for field_name in ("name", "channel", "body_template", "subject", "variant_group", "variant_label"):
        value = getattr(body, field_name)
        if value is not None:
            fields.append(f"{field_name} = %s")
            params.append(value)

    if not fields:
        raise HTTPException(400, "No fields to update")

    params.extend([template_id, user["id"]])
    with get_cursor(conn) as cur:
        cur.execute(
            f"UPDATE templates SET {', '.join(fields)} WHERE id = %s AND user_id = %s",
            params,
        )
        conn.commit()

        return {"success": True, "id": template_id}


@router.patch("/templates/{template_id}/deactivate")
def deactivate_template(
    template_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Deactivate a template."""
    existing = _get_template_scoped(conn, template_id, user["id"])
    if not existing:
        raise HTTPException(404, f"Template {template_id} not found")

    with get_cursor(conn) as cur:
        cur.execute(
            "UPDATE templates SET is_active = false WHERE id = %s AND user_id = %s",
            (template_id, user["id"]),
        )
        conn.commit()

        return {"success": True, "id": template_id, "is_active": False}


class SequenceStepInput(BaseModel):
    step_order: int
    channel: str = Field(max_length=50)
    delay_days: int = Field(ge=0)


class GenerateSequenceMessagesRequest(BaseModel):
    steps: list[SequenceStepInput] = Field(min_length=1, max_length=10)
    product_description: str = Field(min_length=10, max_length=2000)
    target_audience: str = Field(default="crypto fund allocators", max_length=200)


class ImproveMessageRequest(BaseModel):
    channel: str = Field(max_length=50)
    body: str = Field(min_length=1, max_length=5000)
    subject: Optional[str] = Field(default=None, max_length=200)
    instruction: str = Field(min_length=1, max_length=500)


@router.post("/templates/generate-sequence")
@_limiter.limit("5/minute")
def generate_sequence_messages_route(
    request: Request,
    body: GenerateSequenceMessagesRequest,
    user=Depends(get_current_user),
):
    """Generate AI messages for all steps in a campaign sequence."""
    from src.services.message_drafter import generate_sequence_messages

    try:
        messages = generate_sequence_messages(
            steps=[s.model_dump() for s in body.steps],
            product_description=body.product_description,
            target_audience=body.target_audience,
            user_id=user["id"],
        )
        return {"messages": messages}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except httpx.TimeoutException:
        raise HTTPException(504, "AI service timeout — try again")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise HTTPException(429, "AI service rate limited — try again in a minute")
        raise HTTPException(502, f"AI service error: {exc.response.status_code}")
    except Exception as exc:
        logger.error("Sequence generation error: %s", exc, exc_info=True)
        raise HTTPException(500, "Sequence generation failed")


@router.post("/templates/improve-message")
@_limiter.limit("10/minute")
def improve_message_route(
    request: Request,
    body: ImproveMessageRequest,
    user=Depends(get_current_user),
):
    """Improve an existing message based on user instruction."""
    from src.services.message_drafter import improve_message

    try:
        result = improve_message(
            channel=body.channel,
            body=body.body,
            subject=body.subject,
            instruction=body.instruction,
            user_id=user["id"],
        )
        return result
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except httpx.TimeoutException:
        raise HTTPException(504, "AI service timeout — try again")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise HTTPException(429, "AI service rate limited — try again in a minute")
        raise HTTPException(502, f"AI service error: {exc.response.status_code}")
    except Exception as exc:
        logger.error("Message improvement error: %s", exc, exc_info=True)
        raise HTTPException(500, "Message improvement failed")
