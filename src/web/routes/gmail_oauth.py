"""Gmail OAuth connect/callback/disconnect routes."""

import os
import secrets
from datetime import datetime, timedelta, timezone

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
    """Redirect to Google OAuth consent screen."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(500, "Google OAuth not configured (GOOGLE_CLIENT_ID missing)")

    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    cur = conn.cursor()
    try:
        # Clean up expired states
        cur.execute("DELETE FROM oauth_states WHERE expires_at < NOW()")
        # Store state
        cur.execute(
            "INSERT INTO oauth_states (state, user_id, expires_at) VALUES (%s, %s, %s)",
            (state, user["id"], datetime.now(timezone.utc) + timedelta(minutes=10)),
        )
        conn.commit()
    finally:
        cur.close()

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPES}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&state={state}"
    )
    return RedirectResponse(auth_url)


@router.get("/callback")
def gmail_callback(code: str = None, state: str = None, error: str = None, conn=Depends(get_db)):
    """Handle OAuth callback from Google."""
    import httpx

    # Handle user denial
    if error:
        return RedirectResponse("/settings?gmail=error&reason=access_denied")

    if not code or not state:
        return RedirectResponse("/settings?gmail=error&reason=missing_params")

    # Validate state token
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT user_id FROM oauth_states WHERE state = %s AND expires_at > NOW()",
            (state,),
        )
        row = cur.fetchone()
        if not row:
            return RedirectResponse("/settings?gmail=error&reason=invalid_state")

        user_id = row["user_id"]

        # Delete used state
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

    return RedirectResponse("/settings?gmail=connected")


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
