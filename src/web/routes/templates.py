"""Template CRUD API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

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
