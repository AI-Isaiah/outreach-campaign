"""Conversation tracking API routes — log calls, meetings, conferences."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.models.events import log_event
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

router = APIRouter(tags=["conversations"])

VALID_CHANNELS = {
    "conference", "phone", "telegram", "whatsapp",
    "email", "linkedin", "in_person", "video_call",
}
VALID_OUTCOMES = {"successful", "unsuccessful", None}


class ConversationCreate(BaseModel):
    channel: str = Field(max_length=50)
    title: str = Field(max_length=200)
    notes: Optional[str] = Field(default=None, max_length=5000)
    outcome: Optional[str] = Field(default=None, max_length=50)
    occurred_at: Optional[str] = Field(default=None, max_length=50)


class ConversationUpdate(BaseModel):
    channel: Optional[str] = Field(default=None, max_length=50)
    title: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=5000)
    outcome: Optional[str] = Field(default=None, max_length=50)
    occurred_at: Optional[str] = Field(default=None, max_length=50)


@router.get("/contacts/{contact_id}/conversations")
def list_conversations(
    contact_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """List conversations for a contact, newest first."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.id FROM contacts c
               JOIN companies co ON co.id = c.company_id
               WHERE c.id = %s AND co.user_id = %s""",
            (contact_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Contact {contact_id} not found")

        cur.execute(
            "SELECT * FROM conversations WHERE contact_id = %s ORDER BY occurred_at DESC",
            (contact_id,),
        )
        return [dict(r) for r in cur.fetchall()]


@router.post("/contacts/{contact_id}/conversations")
def create_conversation(
    contact_id: int,
    body: ConversationCreate,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Log a conversation with a contact."""
    if body.channel not in VALID_CHANNELS:
        raise HTTPException(400, f"Invalid channel. Must be one of: {', '.join(sorted(VALID_CHANNELS))}")
    if body.outcome is not None and body.outcome not in ("successful", "unsuccessful"):
        raise HTTPException(400, "Outcome must be 'successful', 'unsuccessful', or null")

    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.id, c.lifecycle_stage FROM contacts c
               JOIN companies co ON co.id = c.company_id
               WHERE c.id = %s AND co.user_id = %s""",
            (contact_id, user["id"]),
        )
        contact = cur.fetchone()
        if not contact:
            raise HTTPException(404, f"Contact {contact_id} not found")

        if body.occurred_at:
            cur.execute(
                """INSERT INTO conversations (contact_id, channel, title, notes, outcome, occurred_at)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (contact_id, body.channel, body.title, body.notes, body.outcome, body.occurred_at),
            )
        else:
            cur.execute(
                """INSERT INTO conversations (contact_id, channel, title, notes, outcome)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (contact_id, body.channel, body.title, body.notes, body.outcome),
            )
        conv_id = cur.fetchone()["id"]

        # Auto-advance lifecycle on successful outcome
        if body.outcome == "successful":
            stage = contact["lifecycle_stage"]
            new_stage = None
            if stage == "cold":
                new_stage = "contacted"
            elif stage == "contacted":
                new_stage = "nurturing"

            if new_stage:
                cur.execute(
                    "UPDATE contacts SET lifecycle_stage = %s WHERE id = %s",
                    (new_stage, contact_id),
                )
                log_event(
                    conn, contact_id, "lifecycle_advanced",
                    metadata=json.dumps({"from": stage, "to": new_stage, "trigger": "successful_conversation"}),
                    user_id=user["id"],
                )

        conn.commit()
        return {"id": conv_id, "success": True}


@router.put("/conversations/{conversation_id}")
def update_conversation(
    conversation_id: int,
    body: ConversationUpdate,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update a conversation."""
    if body.channel is not None and body.channel not in VALID_CHANNELS:
        raise HTTPException(400, f"Invalid channel. Must be one of: {', '.join(sorted(VALID_CHANNELS))}")
    if body.outcome is not None and body.outcome not in ("successful", "unsuccessful"):
        raise HTTPException(400, "Outcome must be 'successful', 'unsuccessful', or null")

    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT cv.id FROM conversations cv
               JOIN contacts c ON c.id = cv.contact_id
               JOIN companies co ON co.id = c.company_id
               WHERE cv.id = %s AND co.user_id = %s""",
            (conversation_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Conversation {conversation_id} not found")

        updates = []
        params = []
        for field in ("channel", "title", "notes", "outcome", "occurred_at"):
            value = getattr(body, field)
            if value is not None:
                updates.append(f"{field} = %s")
                params.append(value)

        if not updates:
            return {"success": True}

        params.append(conversation_id)
        cur.execute(
            f"UPDATE conversations SET {', '.join(updates)} WHERE id = %s",
            params,
        )
        conn.commit()
        return {"success": True}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a conversation."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT cv.id FROM conversations cv
               JOIN contacts c ON c.id = cv.contact_id
               JOIN companies co ON co.id = c.company_id
               WHERE cv.id = %s AND co.user_id = %s""",
            (conversation_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Conversation {conversation_id} not found")

        cur.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
        conn.commit()
        return {"success": True}
