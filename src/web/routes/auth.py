"""Authentication routes — login, register, forgot/reset password."""

from __future__ import annotations

import logging
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Optional

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.config import load_config
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_JWT_SECRET = os.getenv("JWT_SECRET", "")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRE_DAYS = 30
_RESET_TOKEN_EXPIRE_HOURS = 24


# --- Request models ---

class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class RegisterRequest(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(max_length=200)
    password: str = Field(min_length=8, max_length=200)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=200)


# --- JWT helpers ---

def create_jwt(user_id: int, email: str, name: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=_JWT_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "email": email, "name": name, "exp": exp},
        _JWT_SECRET,
        algorithm=_JWT_ALGORITHM,
    )


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _check_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# --- Routes ---

@router.post("/login")
def login(body: LoginRequest, conn=Depends(get_db)):
    """Authenticate with email and password, return JWT."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id, email, name, password_hash, is_active FROM users WHERE email = %s",
            (body.email.lower().strip(),),
        )
        user = cur.fetchone()

    if not user or not user["password_hash"]:
        raise HTTPException(401, "Invalid email or password")

    if not _check_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    if not user["is_active"]:
        raise HTTPException(403, "Account is deactivated")

    token = create_jwt(user["id"], user["email"], user["name"] or "")
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
        },
    }


@router.post("/register")
def register(body: RegisterRequest, conn=Depends(get_db)):
    """Register a new user (invite-only: email must be in allowed_emails)."""
    email = body.email.lower().strip()

    with get_cursor(conn) as cur:
        # Check invite list
        cur.execute("SELECT email FROM allowed_emails WHERE email = %s", (email,))
        if not cur.fetchone():
            raise HTTPException(403, "Access denied: email not on invite list")

        # Check if already registered with a password
        cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (email,))
        existing = cur.fetchone()
        if existing and existing["password_hash"]:
            raise HTTPException(409, "Account already exists. Please log in.")

        password_hash = _hash_password(body.password)

        if existing:
            # User row exists from migration seed — set password
            cur.execute(
                "UPDATE users SET name = %s, password_hash = %s, updated_at = NOW() WHERE id = %s",
                (body.name, password_hash, existing["id"]),
            )
            user_id = existing["id"]
        else:
            cur.execute(
                """INSERT INTO users (email, name, password_hash)
                   VALUES (%s, %s, %s) RETURNING id""",
                (email, body.name, password_hash),
            )
            user_id = cur.fetchone()["id"]

        conn.commit()

    token = create_jwt(user_id, email, body.name)
    return {
        "token": token,
        "user": {"id": user_id, "email": email, "name": body.name},
    }


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, conn=Depends(get_db)):
    """Send a password reset email. Always returns 200 to prevent email enumeration."""
    email = body.email.lower().strip()

    with get_cursor(conn) as cur:
        cur.execute("SELECT id, name FROM users WHERE email = %s AND is_active = true", (email,))
        user = cur.fetchone()

        if not user:
            # Don't reveal whether email exists
            return {"message": "If that email is registered, a reset link has been sent."}

        # Generate reset token
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=_RESET_TOKEN_EXPIRE_HOURS)

        cur.execute(
            """INSERT INTO password_reset_tokens (user_id, token, expires_at)
               VALUES (%s, %s, %s)""",
            (user["id"], token, expires_at),
        )
        conn.commit()

    # Send reset email via existing SMTP config
    try:
        _send_reset_email(email, user["name"] or email, token)
    except (smtplib.SMTPException, OSError):
        logger.exception("Failed to send reset email to %s", email)

    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, conn=Depends(get_db)):
    """Reset password using a valid token."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT rt.id, rt.user_id, rt.expires_at, rt.used, u.email
               FROM password_reset_tokens rt
               JOIN users u ON u.id = rt.user_id
               WHERE rt.token = %s""",
            (body.token,),
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(400, "Invalid or expired reset link")

        if row["used"]:
            raise HTTPException(400, "This reset link has already been used")

        if row["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(400, "This reset link has expired")

        # Update password
        password_hash = _hash_password(body.password)
        cur.execute(
            "UPDATE users SET password_hash = %s, updated_at = NOW() WHERE id = %s",
            (password_hash, row["user_id"]),
        )

        # Mark token as used
        cur.execute(
            "UPDATE password_reset_tokens SET used = true WHERE id = %s",
            (row["id"],),
        )
        conn.commit()

    return {"message": "Password has been reset. You can now log in."}


@router.get("/me")
def get_me(user=Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return {"id": user["id"], "email": user["email"], "name": user["name"]}


# --- Email helper ---

def _send_reset_email(to_email: str, to_name: str, token: str) -> None:
    """Send password reset email using the app's SMTP config."""
    try:
        config = load_config()
    except FileNotFoundError:
        logger.warning("No config.yaml found — cannot send reset email")
        return

    smtp_config = config.get("smtp", {})
    host = smtp_config.get("host", "smtp.gmail.com")
    port = smtp_config.get("port", 587)
    username = smtp_config.get("username", "")
    password = config.get("smtp_password", "")
    from_email = config.get("from_email") or username

    if not username or not password:
        logger.warning("SMTP not configured — cannot send reset email")
        return

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    reset_url = f"{frontend_url}/reset-password?token={token}"

    body = (
        f"Hi {to_name},\n\n"
        f"You requested a password reset for your Outreach account.\n\n"
        f"Click this link to set a new password:\n{reset_url}\n\n"
        f"This link expires in {_RESET_TOKEN_EXPIRE_HOURS} hours.\n\n"
        f"If you didn't request this, you can safely ignore this email."
    )

    msg = MIMEText(body, "plain")
    msg["Subject"] = "Password Reset — Outreach"
    msg["From"] = from_email
    msg["To"] = to_email

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(username, password)
        server.sendmail(from_email, [to_email], msg.as_string())

    logger.info("Sent password reset email to %s", to_email)
