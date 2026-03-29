"""Email verification service using ZeroBounce or Hunter API.

Validates email addresses before outreach to protect sender domain
reputation by keeping bounce rates below 2%.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from src.constants import ZEROBOUNCE_CHUNK_SIZE as _CHUNK_SIZE
from src.models.database import get_cursor
from src.services.retry import retry_on_failure

# ---------------------------------------------------------------------------
# Status mapping constants
# ---------------------------------------------------------------------------

ZEROBOUNCE_STATUS_MAP: dict[str, str] = {
    "valid": "valid",
    "invalid": "invalid",
    "catch-all": "catch-all",
    "spamtrap": "invalid",
    "abuse": "invalid",
    "do_not_mail": "invalid",
}

HUNTER_STATUS_MAP: dict[str, str] = {
    "valid": "valid",
    "invalid": "invalid",
    "accept_all": "catch-all",
}

ZEROBOUNCE_CHUNK_SIZE = _CHUNK_SIZE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_email_batch(
    emails: list[str],
    api_key: str,
    provider: str = "zerobounce",
) -> dict[str, str]:
    """Verify a list of email addresses via the chosen provider.

    Returns a mapping of ``{email: status}`` where status is one of:
    ``valid``, ``invalid``, ``risky``, ``catch-all``, ``unknown``.
    """
    if provider == "zerobounce":
        return _verify_zerobounce(emails, api_key)
    elif provider == "hunter":
        return _verify_hunter(emails, api_key)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


# ---------------------------------------------------------------------------
# ZeroBounce implementation
# ---------------------------------------------------------------------------


@retry_on_failure(max_retries=3, backoff_base=1.0, exceptions=(httpx.RequestError,))
def _zerobounce_post(api_key: str, chunk: list[str]) -> httpx.Response:
    """POST a single chunk to ZeroBounce with retry on network errors."""
    response = httpx.post(
        "https://bulkapi.zerobounce.net/v2/validatebatch",
        json={
            "api_key": api_key,
            "email_batch": [{"email_address": e} for e in chunk],
        },
    )
    response.raise_for_status()
    return response


def _verify_zerobounce(emails: list[str], api_key: str) -> dict[str, str]:
    """Verify emails via ZeroBounce batch API.

    Sends emails in chunks of 100. Pauses 1 second between chunks.
    On HTTP errors, marks affected emails as ``unknown``.
    """
    results: dict[str, str] = {}

    for i in range(0, len(emails), ZEROBOUNCE_CHUNK_SIZE):
        chunk = emails[i : i + ZEROBOUNCE_CHUNK_SIZE]

        if i > 0:
            time.sleep(1)

        try:
            response = _zerobounce_post(api_key, chunk)
            data = response.json()

            for entry in data.get("email_batch", []):
                address = entry["address"]
                raw_status = entry.get("status", "").lower()
                results[address] = ZEROBOUNCE_STATUS_MAP.get(raw_status, "risky")

        except (httpx.HTTPStatusError, httpx.RequestError):
            for email in chunk:
                results[email] = "unknown"

    return results


# ---------------------------------------------------------------------------
# Hunter implementation
# ---------------------------------------------------------------------------


def _verify_hunter(emails: list[str], api_key: str) -> dict[str, str]:
    """Verify emails via Hunter email-verifier API.

    Processes one email at a time (Hunter has no batch endpoint).
    Pauses 0.5 seconds between calls.
    """
    results: dict[str, str] = {}

    for idx, email in enumerate(emails):
        if idx > 0:
            time.sleep(0.5)

        try:
            response = httpx.get(
                "https://api.hunter.io/v2/email-verifier",
                params={"email": email, "api_key": api_key},
            )
            response.raise_for_status()
            data = response.json()
            raw_status = data.get("data", {}).get("status", "").lower()
            results[email] = HUNTER_STATUS_MAP.get(raw_status, "risky")

        except (httpx.HTTPStatusError, httpx.RequestError):
            results[email] = "unknown"

    return results


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def update_contact_email_status(
    conn,
    email: str,
    status: str,
) -> None:
    """Update the ``email_status`` and ``updated_at`` for a contact by email."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            "UPDATE contacts SET email_status = %s, updated_at = %s WHERE email_normalized = %s",
            (status, datetime.now(timezone.utc).isoformat(), email),
        )
        conn.commit()


def get_unverified_emails(conn, *, user_id: int | None = None) -> list[str]:
    """Return all ``email_normalized`` values where status is 'unverified' and email is not NULL."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT email_normalized FROM contacts "
            "WHERE email_status = 'unverified' AND email_normalized IS NOT NULL"
            " AND user_id = %s",
            (user_id,),
        )
        return [row["email_normalized"] for row in cursor.fetchall()]
