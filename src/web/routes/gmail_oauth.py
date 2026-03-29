"""Gmail OAuth connect/callback/disconnect routes."""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from src.services.token_encryption import encrypt_token
from src.web.dependencies import get_current_user, get_db

router = APIRouter(prefix="/auth/gmail", tags=["gmail-oauth"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/gmail/callback")
SCOPES = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"


@router.get("/connect")
def gmail_connect(conn=Depends(get_db), user=Depends(get_current_user)):
    """Redirect to Google OAuth consent screen with PKCE binding."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(500, "Google OAuth not configured (GOOGLE_CLIENT_ID missing)")

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(43)
    code_challenge = hashlib.sha256(code_verifier.encode()).hexdigest()

    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM oauth_states WHERE expires_at < NOW()")
        # One active state per user — invalidate any previous flow
        cur.execute("DELETE FROM oauth_states WHERE user_id = %s", (user["id"],))
        cur.execute(
            "INSERT INTO oauth_states (state, user_id, expires_at, code_challenge) VALUES (%s, %s, %s, %s)",
            (state, user["id"], datetime.now(timezone.utc) + timedelta(minutes=10), code_challenge),
        )
        conn.commit()
    finally:
        cur.close()

    params = urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    response = RedirectResponse(auth_url)
    response.set_cookie(
        "oauth_verifier", code_verifier,
        max_age=600, httponly=True, samesite="strict", secure=os.getenv("ENVIRONMENT") == "production",
    )
    return response


@router.get("/callback")
def gmail_callback(request: Request, code: str = None, state: str = None, error: str = None, conn=Depends(get_db)):
    """Handle OAuth callback from Google with PKCE verification."""
    import httpx

    if error:
        return RedirectResponse("/settings?gmail=error&reason=access_denied")

    if not code or not state:
        return RedirectResponse("/settings?gmail=error&reason=missing_params")

    # PKCE: verify the browser that started the flow is the one completing it
    cookie_verifier = request.cookies.get("oauth_verifier")
    if not cookie_verifier:
        return RedirectResponse("/settings?gmail=error&reason=invalid_state")

    expected_challenge = hashlib.sha256(cookie_verifier.encode()).hexdigest()

    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT user_id FROM oauth_states WHERE state = %s AND code_challenge = %s AND expires_at > NOW()",
            (state, expected_challenge),
        )
        row = cur.fetchone()
        if not row:
            return RedirectResponse("/settings?gmail=error&reason=invalid_state")

        user_id = row["user_id"]
        cur.execute("DELETE FROM oauth_states WHERE state = %s", (state,))

        # Exchange code for tokens
        token_response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )

        if token_response.status_code != 200:
            conn.commit()
            return RedirectResponse("/settings?gmail=error&reason=token_exchange_failed")

        tokens = token_response.json()
        access_token = tokens["access_token"]
        refresh_token = tokens.get("refresh_token", "")
        expires_in = tokens.get("expires_in", 3600)

        # Get user's Gmail email address
        profile_response = httpx.get(
            "https://www.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        gmail_email = ""
        if profile_response.status_code == 200:
            gmail_email = profile_response.json().get("emailAddress", "")

        # Store encrypted tokens
        token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        cur.execute(
            """UPDATE users SET
                gmail_access_token = %s,
                gmail_refresh_token = %s,
                gmail_token_expiry = %s,
                gmail_connected = true,
                gmail_email = %s,
                updated_at = NOW()
            WHERE id = %s""",
            (
                encrypt_token(access_token),
                encrypt_token(refresh_token) if refresh_token else None,
                token_expiry,
                gmail_email,
                user_id,
            ),
        )
        conn.commit()
    finally:
        cur.close()

    response = RedirectResponse("/settings?gmail=connected")
    response.delete_cookie("oauth_verifier")
    return response


@router.post("/disconnect")
def gmail_disconnect(conn=Depends(get_db), user=Depends(get_current_user)):
    """Disconnect Gmail — clear OAuth tokens."""
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE users SET
                gmail_access_token = NULL,
                gmail_refresh_token = NULL,
                gmail_token_expiry = NULL,
                gmail_connected = false,
                gmail_email = NULL,
                updated_at = NOW()
            WHERE id = %s""",
            (user["id"],),
        )
        conn.commit()
    finally:
        cur.close()
    return {"success": True, "message": "Gmail disconnected"}
