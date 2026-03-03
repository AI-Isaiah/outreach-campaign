"""Template CRUD API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.models.campaigns import create_template, get_template, list_templates
from src.web.dependencies import get_db

router = APIRouter(tags=["templates"])


class TemplateCreateRequest(BaseModel):
    name: str
    channel: str
    body_template: str
    subject: Optional[str] = None
    variant_group: Optional[str] = None
    variant_label: Optional[str] = None


class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    channel: Optional[str] = None
    body_template: Optional[str] = None
    subject: Optional[str] = None
    variant_group: Optional[str] = None
    variant_label: Optional[str] = None


@router.get("/templates")
def list_all_templates(
    channel: Optional[str] = None,
    active: bool = True,
    conn=Depends(get_db),
):
    """List templates with optional channel filter."""
    rows = list_templates(conn, channel=channel, is_active=active)
    return [dict(r) for r in rows]


@router.get("/templates/{template_id}")
def get_template_by_id(
    template_id: int,
    conn=Depends(get_db),
):
    """Get a single template by ID."""
    row = get_template(conn, template_id)
    if not row:
        raise HTTPException(404, f"Template {template_id} not found")
    return dict(row)


@router.post("/templates")
def create_new_template(
    body: TemplateCreateRequest,
    conn=Depends(get_db),
):
    """Create a new template."""
    template_id = create_template(
        conn,
        name=body.name,
        channel=body.channel,
        body_template=body.body_template,
        subject=body.subject,
        variant_group=body.variant_group,
        variant_label=body.variant_label,
    )
    return {"id": template_id, "success": True}


@router.put("/templates/{template_id}")
def update_template(
    template_id: int,
    body: TemplateUpdateRequest,
    conn=Depends(get_db),
):
    """Update a template."""
    existing = get_template(conn, template_id)
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

    params.append(template_id)
    cur = conn.cursor()
    cur.execute(
        f"UPDATE templates SET {', '.join(fields)} WHERE id = %s",
        params,
    )
    conn.commit()

    return {"success": True, "id": template_id}


@router.patch("/templates/{template_id}/deactivate")
def deactivate_template(
    template_id: int,
    conn=Depends(get_db),
):
    """Deactivate a template."""
    existing = get_template(conn, template_id)
    if not existing:
        raise HTTPException(404, f"Template {template_id} not found")

    cur = conn.cursor()
    cur.execute("UPDATE templates SET is_active = 0 WHERE id = %s", (template_id,))
    conn.commit()

    return {"success": True, "id": template_id, "is_active": False}
