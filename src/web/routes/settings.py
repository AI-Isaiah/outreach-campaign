"""Settings API routes — engine config, service status, API keys."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.web.dependencies import get_current_user, get_db

router = APIRouter(tags=["settings"])

_FOUNDER_EMAIL = "helmut.mueller1@gmail.com"


def _mask_key(key: str | None) -> str:
    """Show only last 4 chars of an API key."""
    if not key:
        return ""
    return "•" * max(0, len(key) - 4) + key[-4:]


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, str]


@router.get("/settings")
def get_settings(
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get engine config and service status."""
    cur = conn.cursor()
    try:
        # Engine config
        cur.execute("SELECT key, value, updated_at FROM engine_config ORDER BY key")
        config_rows = cur.fetchall()
        config = {row["key"]: row["value"] for row in config_rows}
    finally:
        cur.close()

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
    user=Depends(get_current_user),
):
    """Upsert engine config key-value pairs."""
    cur = conn.cursor()
    try:
        for key, value in body.settings.items():
            cur.execute(
                """INSERT INTO engine_config (key, value, updated_at)
                   VALUES (%s, %s, NOW())
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
                (key, value),
            )
        conn.commit()

        return {"success": True, "updated": list(body.settings.keys())}
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# API Keys (per-user, with env-var fallback for founder)
# ---------------------------------------------------------------------------

class ApiKeysUpdateRequest(BaseModel):
    anthropic_api_key: Optional[str] = None
    perplexity_api_key: Optional[str] = None


@router.get("/settings/api-keys")
def get_api_keys(
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Return masked API keys and configuration status for the current user."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT email, anthropic_api_key, perplexity_api_key FROM users WHERE id = %s",
            (user["id"],),
        )
        row = cur.fetchone()
    finally:
        cur.close()

    db_anthropic = (row or {}).get("anthropic_api_key") or ""
    db_perplexity = (row or {}).get("perplexity_api_key") or ""

    # Founder falls back to env vars (check DB email, not auth token email)
    db_email = (row or {}).get("email", "")
    is_founder = db_email == _FOUNDER_EMAIL
    env_anthropic = os.getenv("ANTHROPIC_API_KEY", "") if is_founder else ""
    env_perplexity = os.getenv("PERPLEXITY_API_KEY", "") if is_founder else ""

    anthropic_key = db_anthropic or env_anthropic
    perplexity_key = db_perplexity or env_perplexity

    return {
        "anthropic_api_key": _mask_key(anthropic_key),
        "perplexity_api_key": _mask_key(perplexity_key),
        "anthropic_configured": bool(anthropic_key),
        "perplexity_configured": bool(perplexity_key),
        "is_founder": is_founder,
    }


@router.put("/settings/api-keys")
def update_api_keys(
    body: ApiKeysUpdateRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Save API keys for the current user."""
    updates = []
    params = []
    if body.anthropic_api_key is not None:
        updates.append("anthropic_api_key = %s")
        params.append(body.anthropic_api_key or None)
    if body.perplexity_api_key is not None:
        updates.append("perplexity_api_key = %s")
        params.append(body.perplexity_api_key or None)

    if not updates:
        return {"success": True, "updated": []}

    params.append(user["id"])
    cur = conn.cursor()
    try:
        cur.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = %s",
            params,
        )
        conn.commit()
    finally:
        cur.close()

    return {"success": True, "updated": [k for k, v in body.model_dump().items() if v is not None]}


def get_user_api_keys(conn, user_id: int) -> dict[str, str]:
    """Resolve API keys for a user: DB first, then env-var fallback for founder."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT email, anthropic_api_key, perplexity_api_key FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()

    if not row:
        return {"anthropic": "", "perplexity": ""}

    is_founder = row["email"] == _FOUNDER_EMAIL
    return {
        "anthropic": row["anthropic_api_key"] or (os.getenv("ANTHROPIC_API_KEY", "") if is_founder else ""),
        "perplexity": row["perplexity_api_key"] or (os.getenv("PERPLEXITY_API_KEY", "") if is_founder else ""),
    }
