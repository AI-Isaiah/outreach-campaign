"""Settings API routes — engine config, service status, API keys."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.web.dependencies import get_current_user, get_db
from src.web.query_builder import QueryBuilder
from src.models.database import get_cursor

router = APIRouter(tags=["settings"])

_FOUNDER_EMAIL = os.getenv("FOUNDER_EMAIL", "")


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
    with get_cursor(conn) as cur:
        # Engine config
        cur.execute(
            "SELECT key, value, updated_at FROM engine_config WHERE user_id = %s ORDER BY key",
            (user["id"],),
        )
        config_rows = cur.fetchall()
        config = {row["key"]: row["value"] for row in config_rows}

    # Gmail status
    try:
        from src.services.gmail_drafter import GmailDrafter
        gmail_authorized = GmailDrafter().is_authorized()
    except (ImportError, OSError, ValueError):
        gmail_authorized = False

    return {
        "engine_config": config,
        "gmail_authorized": gmail_authorized,
    }


@router.put("/settings")
def update_settings(
    body: SettingsUpdateRequest,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Upsert engine config key-value pairs."""
    with get_cursor(conn) as cur:
        for key, value in body.settings.items():
            cur.execute(
                """INSERT INTO engine_config (key, value, user_id, updated_at)
                   VALUES (%s, %s, %s, NOW())
                   ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
                (key, value, user["id"]),
            )
        conn.commit()

        return {"success": True, "updated": list(body.settings.keys())}


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
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT email, anthropic_api_key, perplexity_api_key FROM users WHERE id = %s",
            (user["id"],),
        )
        row = cur.fetchone()

    from src.services.token_encryption import try_decrypt

    db_anthropic = try_decrypt((row or {}).get("anthropic_api_key") or "")
    db_perplexity = try_decrypt((row or {}).get("perplexity_api_key") or "")

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
    """Save API keys for the current user (encrypted at rest)."""
    from src.services.token_encryption import encrypt_token

    # Empty string → None: treat blank API keys as "remove"
    raw_fields = {k: (v or None) for k, v in body.model_dump().items() if v is not None}
    # Encrypt non-None values before storing
    fields = {}
    for k, v in raw_fields.items():
        fields[k] = encrypt_token(v) if v else v
    set_clause, params = QueryBuilder.build_update(fields, exclude_none=False)
    if not set_clause:
        return {"success": True, "updated": []}

    params.append(user["id"])
    with get_cursor(conn) as cur:
        cur.execute(
            f"UPDATE users SET {set_clause} WHERE id = %s",
            params,
        )
        conn.commit()

    return {"success": True, "updated": [k for k, v in body.model_dump().items() if v is not None]}


@router.get("/settings/email-config")
def get_email_config(conn=Depends(get_db), user=Depends(get_current_user)):
    """Get current email sending configuration status."""
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT gmail_connected, gmail_email,
                      smtp_host, smtp_from_email, smtp_from_name,
                      physical_address, calendly_url
               FROM users WHERE id = %s""",
            (user["id"],),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        return {
            "gmail_connected": row["gmail_connected"],
            "gmail_email": row["gmail_email"],
            "smtp_configured": bool(row["smtp_host"]),
            "smtp_host": row["smtp_host"],
            "smtp_from_email": row["smtp_from_email"],
            "smtp_from_name": row["smtp_from_name"],
            "physical_address": row["physical_address"],
            "calendly_url": row["calendly_url"],
        }
    finally:
        cur.close()


@router.post("/settings/smtp")
def save_smtp_config(body: dict, conn=Depends(get_db), user=Depends(get_current_user)):
    """Save SMTP sending configuration."""
    from src.services.token_encryption import encrypt_token
    cur = conn.cursor()
    try:
        encrypted_password = encrypt_token(body["password"]) if body.get("password") else None
        cur.execute(
            """UPDATE users SET
                smtp_host = %s, smtp_port = %s,
                smtp_username = %s, smtp_password = %s,
                smtp_use_tls = %s, smtp_from_email = %s, smtp_from_name = %s,
                updated_at = NOW()
            WHERE id = %s""",
            (
                body.get("host"), body.get("port", 587),
                body.get("username"), encrypted_password,
                body.get("use_tls", True), body.get("from_email"), body.get("from_name"),
                user["id"],
            ),
        )
        conn.commit()
    finally:
        cur.close()
    return {"success": True, "message": "SMTP settings saved"}


@router.post("/settings/compliance")
def save_compliance_config(body: dict, conn=Depends(get_db), user=Depends(get_current_user)):
    """Save per-user compliance settings (physical address, Calendly URL)."""
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE users SET
                physical_address = %s, calendly_url = %s,
                updated_at = NOW()
            WHERE id = %s""",
            (body.get("physical_address"), body.get("calendly_url"), user["id"]),
        )
        conn.commit()
    finally:
        cur.close()
    return {"success": True, "message": "Compliance settings saved"}


def get_user_api_keys(conn, user_id: int) -> dict[str, str]:
    """Resolve API keys for a user: DB first (decrypt), then env-var fallback for founder."""
    from src.services.token_encryption import try_decrypt

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT email, anthropic_api_key, perplexity_api_key FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"anthropic": "", "perplexity": ""}

    # Decrypt DB values (try_decrypt handles plaintext gracefully for backwards compat)
    db_anthropic = try_decrypt(row["anthropic_api_key"] or "")
    db_perplexity = try_decrypt(row["perplexity_api_key"] or "")

    is_founder = row["email"] == _FOUNDER_EMAIL
    return {
        "anthropic": db_anthropic or (os.getenv("ANTHROPIC_API_KEY", "") if is_founder else ""),
        "perplexity": db_perplexity or (os.getenv("PERPLEXITY_API_KEY", "") if is_founder else ""),
    }
