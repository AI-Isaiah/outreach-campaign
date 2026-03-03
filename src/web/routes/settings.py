"""Settings API routes — engine config, service status."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.web.dependencies import get_db

router = APIRouter(tags=["settings"])


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, str]


@router.get("/settings")
def get_settings(
    conn=Depends(get_db),
):
    """Get engine config and service status."""
    cur = conn.cursor()

    # Engine config
    cur.execute("SELECT key, value, updated_at FROM engine_config ORDER BY key")
    config_rows = cur.fetchall()
    config = {row["key"]: row["value"] for row in config_rows}

    # Gmail status
    try:
        from src.services.gmail_drafter import GmailDrafter
        gmail_authorized = GmailDrafter().is_authorized()
    except Exception:
        gmail_authorized = False

    # WhatsApp status (placeholder)
    whatsapp_status = "not_configured"

    return {
        "engine_config": config,
        "gmail_authorized": gmail_authorized,
        "whatsapp_status": whatsapp_status,
    }


@router.put("/settings")
def update_settings(
    body: SettingsUpdateRequest,
    conn=Depends(get_db),
):
    """Upsert engine config key-value pairs."""
    cur = conn.cursor()
    for key, value in body.settings.items():
        cur.execute(
            """INSERT INTO engine_config (key, value, updated_at)
               VALUES (%s, %s, NOW())
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
            (key, value),
        )
    conn.commit()

    return {"success": True, "updated": list(body.settings.keys())}
