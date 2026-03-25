"""Sequence generator API route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.models.database import get_cursor
from src.services.sequence_generator import generate_sequence
from src.web.dependencies import get_current_user, get_db

router = APIRouter(tags=["sequence"])


class GenerateSequenceRequest(BaseModel):
    touchpoints: int = Field(ge=1, le=10)
    channels: list[str] = Field(min_length=1)


@router.post("/campaigns/{campaign_id}/generate-sequence")
def generate_sequence_route(
    campaign_id: int,
    body: GenerateSequenceRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Generate a sequence of steps for a campaign."""
    # Verify campaign belongs to user
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id FROM campaigns WHERE id = %s AND user_id = %s",
            (campaign_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Campaign not found")

    try:
        steps = generate_sequence(body.touchpoints, body.channels)
    except ValueError as e:
        raise HTTPException(422, str(e))

    return {"steps": steps}
