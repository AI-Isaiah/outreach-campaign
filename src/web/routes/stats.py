"""Database statistics API route."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

router = APIRouter(tags=["stats"])


@router.get("/stats")
def get_stats(conn=Depends(get_db), user=Depends(get_current_user)):
    """Get database statistics with current and previous period comparison."""
    uid = user["id"]
    with get_cursor(conn) as cur:
        # Single query for all contact-level stats (scoped via companies)
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE c.is_gdpr = true) AS gdpr,
                COUNT(*) FILTER (WHERE c.email_status = 'valid') AS verified,
                COUNT(*) FILTER (WHERE c.email_status = 'invalid') AS invalid,
                COUNT(*) FILTER (WHERE c.email_status = 'unverified') AS unverified,
                COUNT(*) FILTER (WHERE c.email_normalized IS NOT NULL) AS with_email,
                COUNT(*) FILTER (WHERE c.linkedin_url IS NOT NULL AND c.linkedin_url != '') AS with_linkedin
            FROM contacts c
            JOIN companies co ON co.id = c.company_id
            WHERE co.user_id = %s
        """, (uid,))
        c = cur.fetchone()

        # Remaining tables — scoped per root table
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM companies WHERE user_id = %s) AS companies,
                (SELECT COUNT(*) FROM campaigns WHERE user_id = %s) AS campaigns,
                (SELECT COUNT(*) FROM contact_campaign_status ccs
                     JOIN campaigns cam ON cam.id = ccs.campaign_id
                     WHERE cam.user_id = %s) AS enrolled,
                (SELECT COUNT(*) FROM events WHERE user_id = %s) AS events
        """, (uid, uid, uid, uid))
        t = cur.fetchone()

        # Previous period stats: current week vs prior week event counts (scoped via contacts -> companies)
        cur.execute("""
            SELECT
                COUNT(*) FILTER (
                    WHERE e.created_at >= date_trunc('week', CURRENT_DATE)
                ) AS current_week_events,
                COUNT(*) FILTER (
                    WHERE e.created_at >= date_trunc('week', CURRENT_DATE) - INTERVAL '7 days'
                      AND e.created_at < date_trunc('week', CURRENT_DATE)
                ) AS previous_week_events,
                COUNT(*) FILTER (
                    WHERE e.created_at >= date_trunc('week', CURRENT_DATE)
                      AND e.event_type = 'email_sent'
                ) AS current_week_emails_sent,
                COUNT(*) FILTER (
                    WHERE e.created_at >= date_trunc('week', CURRENT_DATE) - INTERVAL '7 days'
                      AND e.created_at < date_trunc('week', CURRENT_DATE)
                      AND e.event_type = 'email_sent'
                ) AS previous_week_emails_sent,
                COUNT(*) FILTER (
                    WHERE e.created_at >= date_trunc('week', CURRENT_DATE)
                      AND e.event_type LIKE 'replied%%'
                ) AS current_week_replies,
                COUNT(*) FILTER (
                    WHERE e.created_at >= date_trunc('week', CURRENT_DATE) - INTERVAL '7 days'
                      AND e.created_at < date_trunc('week', CURRENT_DATE)
                      AND e.event_type LIKE 'replied%%'
                ) AS previous_week_replies,
                COUNT(*) FILTER (
                    WHERE e.created_at >= date_trunc('week', CURRENT_DATE)
                      AND e.event_type = 'call_booked'
                ) AS current_week_calls_booked,
                COUNT(*) FILTER (
                    WHERE e.created_at >= date_trunc('week', CURRENT_DATE) - INTERVAL '7 days'
                      AND e.created_at < date_trunc('week', CURRENT_DATE)
                      AND e.event_type = 'call_booked'
                ) AS previous_week_calls_booked
            FROM events e
            WHERE e.user_id = %s
        """, (uid,))
        period = cur.fetchone()

        # Contacts created this week vs last week (scoped via companies)
        cur.execute("""
            SELECT
                COUNT(*) FILTER (
                    WHERE c.created_at >= date_trunc('week', CURRENT_DATE)
                ) AS current_week_contacts,
                COUNT(*) FILTER (
                    WHERE c.created_at >= date_trunc('week', CURRENT_DATE) - INTERVAL '7 days'
                      AND c.created_at < date_trunc('week', CURRENT_DATE)
                ) AS previous_week_contacts
            FROM contacts c
            JOIN companies co ON co.id = c.company_id
            WHERE co.user_id = %s
        """, (uid,))
        contact_period = cur.fetchone()

        return {
            "companies": t["companies"],
            "contacts": c["total"],
            "with_email": c["with_email"],
            "with_linkedin": c["with_linkedin"],
            "gdpr": c["gdpr"],
            "email_status": {
                "verified": c["verified"],
                "invalid": c["invalid"],
                "unverified": c["unverified"],
            },
            "campaigns": t["campaigns"],
            "enrolled": t["enrolled"],
            "events": t["events"],
            "previous_period": {
                "current_week_events": period["current_week_events"],
                "previous_week_events": period["previous_week_events"],
                "current_week_emails_sent": period["current_week_emails_sent"],
                "previous_week_emails_sent": period["previous_week_emails_sent"],
                "current_week_replies": period["current_week_replies"],
                "previous_week_replies": period["previous_week_replies"],
                "current_week_calls_booked": period["current_week_calls_booked"],
                "previous_week_calls_booked": period["previous_week_calls_booked"],
                "current_week_new_contacts": contact_period["current_week_contacts"],
                "previous_week_new_contacts": contact_period["previous_week_contacts"],
            },
        }
