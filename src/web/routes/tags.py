"""Tag API routes — CRUD + attach/detach to contacts and companies."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

router = APIRouter(prefix="/tags", tags=["tags"])

VALID_ENTITY_TYPES = ("contact", "company")


class TagCreate(BaseModel):
    name: str = Field(max_length=200)
    color: str = Field(default="#6B7280", max_length=50)


class TagAttach(BaseModel):
    entity_type: str = Field(max_length=50)
    entity_id: int


@router.get("")
def list_tags(conn=Depends(get_db), user=Depends(get_current_user)):
    """List all tags."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM tags WHERE user_id = %s ORDER BY name LIMIT 500",
            (user["id"],),
        )
        return [dict(r) for r in cur.fetchall()]


@router.post("")
def create_tag(body: TagCreate, conn=Depends(get_db), user=Depends(get_current_user)):
    """Create a new tag."""
    with get_cursor(conn) as cur:
        # Check for duplicate within this user's tags
        cur.execute(
            "SELECT id FROM tags WHERE name = %s AND user_id = %s",
            (body.name, user["id"]),
        )
        if cur.fetchone():
            raise HTTPException(409, f"Tag '{body.name}' already exists")

        cur.execute(
            "INSERT INTO tags (name, color, user_id) VALUES (%s, %s, %s) RETURNING id",
            (body.name, body.color, user["id"]),
        )
        tag_id = cur.fetchone()["id"]
        conn.commit()

        return {"id": tag_id, "success": True}


@router.delete("/{tag_id}")
def delete_tag(tag_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Delete a tag (cascades to entity_tags)."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id FROM tags WHERE id = %s AND user_id = %s",
            (tag_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Tag {tag_id} not found")

        cur.execute(
            "DELETE FROM tags WHERE id = %s AND user_id = %s",
            (tag_id, user["id"]),
        )
        conn.commit()

        return {"success": True}


@router.post("/{tag_id}/attach")
def attach_tag(tag_id: int, body: TagAttach, conn=Depends(get_db), user=Depends(get_current_user)):
    """Attach a tag to an entity (contact or company)."""
    if body.entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(400, f"Invalid entity_type: {body.entity_type}")

    with get_cursor(conn) as cur:
        # Verify tag exists and belongs to this user
        cur.execute(
            "SELECT id FROM tags WHERE id = %s AND user_id = %s",
            (tag_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Tag {tag_id} not found")

        # Verify entity exists
        table = "contacts" if body.entity_type == "contact" else "companies"
        cur.execute(f"SELECT id FROM {table} WHERE id = %s", (body.entity_id,))
        if not cur.fetchone():
            raise HTTPException(404, f"{body.entity_type.title()} {body.entity_id} not found")

        # Check if already attached
        cur.execute(
            "SELECT id FROM entity_tags WHERE tag_id = %s AND entity_type = %s AND entity_id = %s",
            (tag_id, body.entity_type, body.entity_id),
        )
        if cur.fetchone():
            return {"success": True, "already_attached": True}

        cur.execute(
            "INSERT INTO entity_tags (tag_id, entity_type, entity_id) VALUES (%s, %s, %s)",
            (tag_id, body.entity_type, body.entity_id),
        )
        conn.commit()

        return {"success": True, "already_attached": False}


@router.post("/{tag_id}/detach")
def detach_tag(tag_id: int, body: TagAttach, conn=Depends(get_db), user=Depends(get_current_user)):
    """Detach a tag from an entity."""
    if body.entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(400, f"Invalid entity_type: {body.entity_type}")

    with get_cursor(conn) as cur:
        # Verify tag belongs to this user before detaching
        cur.execute(
            "SELECT id FROM tags WHERE id = %s AND user_id = %s",
            (tag_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Tag {tag_id} not found")

        cur.execute(
            "DELETE FROM entity_tags WHERE tag_id = %s AND entity_type = %s AND entity_id = %s",
            (tag_id, body.entity_type, body.entity_id),
        )
        conn.commit()

        return {"success": True}


@router.get("/entity/{entity_type}/{entity_id}")
def get_entity_tags(entity_type: str, entity_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Get all tags for a specific entity."""
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(400, f"Invalid entity_type: {entity_type}")

    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT t.* FROM tags t
               JOIN entity_tags et ON et.tag_id = t.id
               WHERE et.entity_type = %s AND et.entity_id = %s AND t.user_id = %s
               ORDER BY t.name""",
            (entity_type, entity_id, user["id"]),
        )
        return [dict(r) for r in cur.fetchall()]
