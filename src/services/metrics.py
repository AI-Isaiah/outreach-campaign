"""Campaign metrics and reporting.

Provides functions to compute campaign-level metrics, A/B variant comparisons,
weekly summaries, and firm-type breakdowns for outreach campaigns.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from src.enums import ContactStatus, EventType
from src.models.database import get_cursor


def get_campaign_metrics(conn, campaign_id: int) -> dict:
    """Get comprehensive metrics for a campaign.

    Returns dict with:
    - total_enrolled: int
    - by_status: dict[str, int] (queued, in_progress, replied_positive,
      replied_negative, no_response, bounced)
    - emails_sent: int (count of email_sent events)
    - linkedin_connects: int (count of expandi_connected events)
    - linkedin_messages: int (count of expandi_message_sent events)
    - calls_booked: int (count of call_booked events)
    - reply_rate: float (positive + negative / total non-queued)
    - positive_rate: float (positive / total non-queued)
    """
    with get_cursor(conn) as cursor:
        # Status counts
        cursor.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM contact_campaign_status
            WHERE campaign_id = %s
            GROUP BY status
            """,
            (campaign_id,),
        )
        status_rows = cursor.fetchall()

        by_status = {s: 0 for s in ContactStatus}
        total_enrolled = 0
        for row in status_rows:
            by_status[row["status"]] = by_status.get(row["status"], 0) + row["cnt"]
            total_enrolled += row["cnt"]

        # Event counts — include both legacy expandi_* and new linkedin_* event types
        cursor.execute(
            """
            SELECT event_type, COUNT(*) AS cnt
            FROM events
            WHERE campaign_id = %s
              AND event_type IN (
                  'email_sent', 'call_booked',
                  'expandi_connected', 'expandi_message_sent',
                  'linkedin_connect_done', 'linkedin_message_done',
                  'linkedin_engage_done', 'linkedin_insight_done',
                  'linkedin_final_done'
              )
            GROUP BY event_type
            """,
            (campaign_id,),
        )
        event_rows = cursor.fetchall()

        event_counts = {}
        for row in event_rows:
            event_counts[row["event_type"]] = row["cnt"]

    emails_sent = event_counts.get("email_sent", 0)
    linkedin_connects = (
        event_counts.get("expandi_connected", 0)
        + event_counts.get("linkedin_connect_done", 0)
    )
    linkedin_messages = (
        event_counts.get("expandi_message_sent", 0)
        + event_counts.get("linkedin_message_done", 0)
        + event_counts.get("linkedin_engage_done", 0)
        + event_counts.get("linkedin_insight_done", 0)
        + event_counts.get("linkedin_final_done", 0)
    )
    calls_booked = event_counts.get("call_booked", 0)

    # Reply rate: (positive + negative) / (total - queued)
    non_queued = total_enrolled - by_status["queued"]
    positive = by_status["replied_positive"]
    negative = by_status["replied_negative"]

    reply_rate = (positive + negative) / non_queued if non_queued > 0 else 0.0
    positive_rate = positive / non_queued if non_queued > 0 else 0.0

    # Reply breakdown: binary positive/negative
    reply_total = positive + negative
    reply_positive_rate = positive / reply_total if reply_total > 0 else 0.0

    return {
        "total_enrolled": total_enrolled,
        "by_status": by_status,
        "emails_sent": emails_sent,
        "linkedin_connects": linkedin_connects,
        "linkedin_messages": linkedin_messages,
        "calls_booked": calls_booked,
        "reply_rate": round(reply_rate, 4),
        "positive_rate": round(positive_rate, 4),
        "reply_breakdown": {
            "positive": positive,
            "negative": negative,
            "total": reply_total,
            "positive_rate": round(reply_positive_rate, 4),
        },
    }


def get_variant_comparison(conn, campaign_id: int) -> list[dict]:
    """Compare A/B variants by reply rates.

    Returns list of dicts with: variant, total, replied_positive,
    replied_negative, no_response, reply_rate, positive_rate.
    Only includes contacts with a non-NULL assigned_variant.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            """
            SELECT
                assigned_variant,
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'replied_positive' THEN 1 ELSE 0 END)
                    AS replied_positive,
                SUM(CASE WHEN status = 'replied_negative' THEN 1 ELSE 0 END)
                    AS replied_negative,
                SUM(CASE WHEN status = 'no_response' THEN 1 ELSE 0 END)
                    AS no_response,
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END)
                    AS queued
            FROM contact_campaign_status
            WHERE campaign_id = %s
              AND assigned_variant IS NOT NULL
            GROUP BY assigned_variant
            ORDER BY assigned_variant
            """,
            (campaign_id,),
        )
        rows = cursor.fetchall()

    results = []
    for row in rows:
        total = row["total"]
        positive = row["replied_positive"]
        negative = row["replied_negative"]
        queued = row["queued"]
        non_queued = total - queued

        reply_rate = (positive + negative) / non_queued if non_queued > 0 else 0.0
        positive_rate = positive / non_queued if non_queued > 0 else 0.0

        results.append({
            "variant": row["assigned_variant"],
            "total": total,
            "replied_positive": positive,
            "replied_negative": negative,
            "no_response": row["no_response"],
            "reply_rate": round(reply_rate, 4),
            "positive_rate": round(positive_rate, 4),
        })

    return results


def get_weekly_summary(
    conn,
    campaign_id: int,
    weeks_back: int = 1,
) -> dict:
    """Get metrics for the past N weeks.

    Uses events.created_at to filter by date range. The period covers
    from ``weeks_back * 7`` days ago up to (and including) today.

    Returns dict with:
    - period: str (date range like "2024-01-15 to 2024-01-22")
    - emails_sent: int (email_sent events this period)
    - linkedin_actions: int (expandi_connected + expandi_message_sent)
    - replies_positive: int (status_replied_positive events)
    - replies_negative: int (status_replied_negative events)
    - calls_booked: int (call_booked events)
    - new_no_response: int (status_no_response events)
    """
    today = date.today()
    start_date = today - timedelta(days=weeks_back * 7)
    start_str = start_date.isoformat()
    end_str = (today + timedelta(days=1)).isoformat()  # exclusive upper bound

    period = f"{start_str} to {today.isoformat()}"

    with get_cursor(conn) as cursor:
        cursor.execute(
            """
            SELECT event_type, COUNT(*) AS cnt
            FROM events
            WHERE campaign_id = %s
              AND created_at >= %s
              AND created_at < %s
              AND event_type IN (
                  'email_sent',
                  'expandi_connected', 'expandi_message_sent',
                  'linkedin_connect_done', 'linkedin_message_done',
                  'linkedin_engage_done', 'linkedin_insight_done',
                  'linkedin_final_done',
                  'status_replied_positive', 'status_replied_negative',
                  'call_booked', 'status_no_response'
              )
            GROUP BY event_type
            """,
            (campaign_id, start_str, end_str),
        )
        event_rows = cursor.fetchall()

    counts = {}
    for row in event_rows:
        counts[row["event_type"]] = row["cnt"]

    return {
        "period": period,
        "emails_sent": counts.get("email_sent", 0),
        "linkedin_actions": (
            counts.get("expandi_connected", 0)
            + counts.get("expandi_message_sent", 0)
            + counts.get("linkedin_connect_done", 0)
            + counts.get("linkedin_message_done", 0)
            + counts.get("linkedin_engage_done", 0)
            + counts.get("linkedin_insight_done", 0)
            + counts.get("linkedin_final_done", 0)
        ),
        "replies_positive": counts.get("status_replied_positive", 0),
        "replies_negative": counts.get("status_replied_negative", 0),
        "calls_booked": counts.get("call_booked", 0),
        "new_no_response": counts.get("status_no_response", 0),
    }


def get_company_type_breakdown(
    conn,
    campaign_id: int,
) -> list[dict]:
    """Break down reply rates by company firm_type.

    Joins contact_campaign_status through contacts to companies to group
    by firm_type. Returns list sorted by reply rate descending.

    Each dict contains: firm_type, total, replied_positive, replied_negative,
    no_response, reply_rate, positive_rate.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            """
            SELECT
                COALESCE(comp.firm_type, 'Unknown') AS firm_type,
                COUNT(*) AS total,
                SUM(CASE WHEN ccs.status = 'replied_positive' THEN 1 ELSE 0 END)
                    AS replied_positive,
                SUM(CASE WHEN ccs.status = 'replied_negative' THEN 1 ELSE 0 END)
                    AS replied_negative,
                SUM(CASE WHEN ccs.status = 'no_response' THEN 1 ELSE 0 END)
                    AS no_response,
                SUM(CASE WHEN ccs.status = 'queued' THEN 1 ELSE 0 END)
                    AS queued
            FROM contact_campaign_status ccs
            JOIN contacts c ON c.id = ccs.contact_id
            JOIN companies comp ON comp.id = c.company_id
            WHERE ccs.campaign_id = %s
            GROUP BY COALESCE(comp.firm_type, 'Unknown')
            """,
            (campaign_id,),
        )
        rows = cursor.fetchall()

    results = []
    for row in rows:
        total = row["total"]
        positive = row["replied_positive"]
        negative = row["replied_negative"]
        queued = row["queued"]
        non_queued = total - queued

        reply_rate = (positive + negative) / non_queued if non_queued > 0 else 0.0
        positive_rate = positive / non_queued if non_queued > 0 else 0.0

        results.append({
            "firm_type": row["firm_type"],
            "total": total,
            "replied_positive": positive,
            "replied_negative": negative,
            "no_response": row["no_response"],
            "reply_rate": round(reply_rate, 4),
            "positive_rate": round(positive_rate, 4),
        })

    # Sort by reply_rate descending
    results.sort(key=lambda r: r["reply_rate"], reverse=True)
    return results
