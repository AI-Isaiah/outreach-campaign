"""FastAPI dependencies for database access, config, and auth."""

from __future__ import annotations

import os
from typing import Generator

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import SUPABASE_DB_URL, load_config
from src.models.database import get_connection, get_pool_connection, is_pool_initialized, put_pool_connection

_security = HTTPBearer(auto_error=False)
_JWT_SECRET = os.getenv("JWT_SECRET", "")
_JWT_ALGORITHM = "HS256"

_ENVIRONMENT = os.getenv("ENVIRONMENT", "").lower()
if _ENVIRONMENT in ("production", "staging") and not _JWT_SECRET:
    raise RuntimeError("JWT_SECRET must be set in production/staging environments")


class CurrentUser(dict):
    """Typed dict for the authenticated user. Keys: id, email, name."""
    pass


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> CurrentUser:
    """Decode JWT Bearer token and return the user payload.

    In dev mode (JWT_SECRET not set), returns user id=1 for convenience.
    Raises 401 on missing, expired, or invalid tokens in production.
    """
    if not _JWT_SECRET:
        # Dev mode — no JWT validation, return default user
        return CurrentUser(id=1, email="dev@localhost", name="Dev User")

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            credentials.credentials, _JWT_SECRET, algorithms=[_JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    return CurrentUser(
        id=payload["sub"],
        email=payload["email"],
        name=payload.get("name", ""),
    )


# Backward-compat alias — app.py uses this name for _auth_deps
require_auth = get_current_user


def verify_cron_secret(request: Request):
    """Verify CRON_SECRET header for automated cron endpoints."""
    expected = os.getenv("CRON_SECRET")
    if not expected:
        raise HTTPException(503, "Cron not configured")
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {expected}":
        raise HTTPException(401, "Invalid cron secret")


def get_db() -> Generator:
    """Yield a database connection.

    Uses the connection pool when available (Docker/local dev).
    Falls back to a direct connection per request in serverless (Vercel).
    """
    if is_pool_initialized():
        conn = get_pool_connection()
        try:
            yield conn
        finally:
            conn.rollback()
            put_pool_connection(conn)
    else:
        conn = get_connection(SUPABASE_DB_URL)
        try:
            yield conn
        finally:
            conn.close()


def get_config() -> dict:
    """Return the application config."""
    return load_config()
