"""CLI command handler: database statistics."""

from __future__ import annotations

from src.models.database import get_cursor


def get_db_stats(conn, *, user_id: int) -> dict:
    """Gather database statistics for display.

    Returns dict with keys: companies, contacts, with_email, with_linkedin,
    gdpr, verified, invalid, unverified.
    """
    with get_cursor(conn) as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM companies WHERE user_id = %s", (user_id,))
        companies = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE user_id = %s", (user_id,))
        contacts = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE is_gdpr = true AND user_id = %s", (user_id,))
        gdpr = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE email_status = 'valid' AND user_id = %s", (user_id,))
        verified = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE email_status = 'invalid' AND user_id = %s", (user_id,))
        invalid = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE email_status = 'unverified' AND user_id = %s", (user_id,))
        unverified = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE email_normalized IS NOT NULL AND user_id = %s", (user_id,))
        with_email = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE linkedin_url IS NOT NULL AND linkedin_url != '' AND user_id = %s", (user_id,))
        with_linkedin = cur.fetchone()["cnt"]

    return {
        "companies": companies,
        "contacts": contacts,
        "with_email": with_email,
        "with_linkedin": with_linkedin,
        "gdpr": gdpr,
        "verified": verified,
        "invalid": invalid,
        "unverified": unverified,
    }
