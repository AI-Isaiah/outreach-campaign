"""Database statistics API route."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.web.dependencies import get_db

router = APIRouter(tags=["stats"])


@router.get("/stats")
def get_stats(conn=Depends(get_db)):
    """Get database statistics."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM companies")
    companies = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM contacts")
    contacts = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE is_gdpr = 1")
    gdpr = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE email_status = 'valid'")
    verified = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE email_status = 'invalid'")
    invalid = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE email_status = 'unverified'")
    unverified = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE email_normalized IS NOT NULL")
    with_email = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE linkedin_url IS NOT NULL AND linkedin_url != ''")
    with_linkedin = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM campaigns")
    campaigns = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM contact_campaign_status")
    enrolled = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM events")
    events = cur.fetchone()["cnt"]

    return {
        "companies": companies,
        "contacts": contacts,
        "with_email": with_email,
        "with_linkedin": with_linkedin,
        "gdpr": gdpr,
        "email_status": {
            "verified": verified,
            "invalid": invalid,
            "unverified": unverified,
        },
        "campaigns": campaigns,
        "enrolled": enrolled,
        "events": events,
    }
