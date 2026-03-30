"""Public unsubscribe endpoint -- no auth required.

Supports both GET (browser click) and POST (RFC 8058 List-Unsubscribe-Post).
Verifies a signed token before processing the unsubscribe.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.models.database import get_cursor
from src.services.compliance import process_unsubscribe, verify_unsubscribe_token
from src.web.dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["unsubscribe"])


def _get_contact_email_and_user(conn, contact_id: int) -> tuple:
    """Look up contact email and owning user_id by contact ID.

    Returns (email, user_id) or (None, None) if not found.
    """
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT email, user_id FROM contacts WHERE id = %s",
            (contact_id,),
        )
        row = cur.fetchone()
        if row:
            return row["email"], row["user_id"]
        return None, None


_CONFIRMATION_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Unsubscribed</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           display: flex; justify-content: center; align-items: center;
           min-height: 100vh; margin: 0; background: #f9fafb; color: #333; }}
    .card {{ background: white; border-radius: 12px; padding: 40px;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; max-width: 400px; }}
    h1 {{ font-size: 24px; margin-bottom: 12px; }}
    p {{ color: #666; line-height: 1.6; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Unsubscribed</h1>
    <p>You have been successfully unsubscribed and will no longer receive emails from us.</p>
  </div>
</body>
</html>
"""

_ERROR_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Unsubscribe Error</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           display: flex; justify-content: center; align-items: center;
           min-height: 100vh; margin: 0; background: #f9fafb; color: #333; }}
    .card {{ background: white; border-radius: 12px; padding: 40px;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; max-width: 400px; }}
    h1 {{ font-size: 24px; margin-bottom: 12px; color: #dc2626; }}
    p {{ color: #666; line-height: 1.6; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Invalid Link</h1>
    <p>This unsubscribe link is invalid or has expired. Please contact us directly to unsubscribe.</p>
  </div>
</body>
</html>
"""


@router.get("/unsubscribe/{contact_id}")
def unsubscribe_get(
    contact_id: int,
    token: str = Query(...),
    conn=Depends(get_db),
):
    """Handle browser-click unsubscribe (GET).

    Verifies the signed token, processes the unsubscribe, and returns
    an HTML confirmation page.
    """
    if not verify_unsubscribe_token(contact_id, token):
        return HTMLResponse(_ERROR_HTML, status_code=400)

    email, user_id = _get_contact_email_and_user(conn, contact_id)
    if not email or not user_id:
        return HTMLResponse(_ERROR_HTML, status_code=404)

    process_unsubscribe(conn, email, user_id=user_id)
    logger.info("Unsubscribed contact %d via GET", contact_id)
    return HTMLResponse(_CONFIRMATION_HTML)


class UnsubscribePostBody(BaseModel):
    token: str


@router.post("/unsubscribe/{contact_id}")
def unsubscribe_post(
    contact_id: int,
    body: UnsubscribePostBody,
    conn=Depends(get_db),
):
    """Handle RFC 8058 List-Unsubscribe-Post one-click unsubscribe.

    Email clients send a POST with ``List-Unsubscribe=One-Click`` in the body.
    We accept the token in the JSON body for verification.
    """
    if not verify_unsubscribe_token(contact_id, body.token):
        raise HTTPException(400, "Invalid unsubscribe token")

    email, user_id = _get_contact_email_and_user(conn, contact_id)
    if not email or not user_id:
        raise HTTPException(404, "Contact not found")

    process_unsubscribe(conn, email, user_id=user_id)
    logger.info("Unsubscribed contact %d via POST (one-click)", contact_id)
    return {"success": True}
