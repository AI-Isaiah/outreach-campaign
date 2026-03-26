"""Contact scoring for the adaptive outreach engine.

Computes composite priority scores for contacts to determine daily queue order.
Score = WEIGHT_AUM*normalized_aum + WEIGHT_SEGMENT*segment_reply_rate + WEIGHT_CHANNEL*channel_availability + WEIGHT_RECENCY*waiting_time_decay
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from src.models.database import get_cursor
from src.services.response_analyzer import get_segment_performance

WEIGHT_AUM = 0.4
WEIGHT_SEGMENT = 0.3
WEIGHT_CHANNEL = 0.2
WEIGHT_RECENCY = 0.1
RECENCY_CAP_DAYS = 14


def score_contacts(
    conn,
    campaign_id: int,
    contact_ids: list[int],
    *,
    user_id: int | None = None,
) -> list[dict]:
    """Score a list of contacts and return sorted by priority score descending.

    Returns list of dicts with: contact_id, priority_score, breakdown (aum_score,
    segment_score, channel_score, recency_score).
    """
    if not contact_ids:
        return []

    # Get segment performance for reply rates
    segments = get_segment_performance(conn, campaign_id)
    segment_rates = {s["aum_tier"]: s["reply_rate"] for s in segments}

    # Get max AUM for normalization
    with get_cursor(conn) as cursor:
        if user_id is not None:
            cursor.execute(
                "SELECT MAX(aum_millions) AS max_aum FROM companies WHERE aum_millions IS NOT NULL AND user_id = %s",
                (user_id,),
            )
        else:
            cursor.execute("SELECT MAX(aum_millions) AS max_aum FROM companies WHERE aum_millions IS NOT NULL")
        max_aum_row = cursor.fetchone()
        max_aum = max_aum_row["max_aum"] if max_aum_row and max_aum_row["max_aum"] else 1.0

        # Fetch contact data
        placeholders = ",".join(["%s"] * len(contact_ids))
        cursor.execute(
            f"""
            SELECT c.id, c.email_status, c.linkedin_url, c.is_gdpr,
                   comp.aum_millions, comp.firm_type,
                   ccs.next_action_date, ccs.current_step
            FROM contacts c
            JOIN companies comp ON comp.id = c.company_id
            JOIN contact_campaign_status ccs ON ccs.contact_id = c.id AND ccs.campaign_id = %s
            WHERE c.id IN ({placeholders})
            """,
            [campaign_id] + contact_ids,
        )
        rows = cursor.fetchall()

    today = date.today()
    results = []

    for row in rows:
        aum = row["aum_millions"] or 0
        aum_score = min(aum / max_aum, 1.0) if max_aum > 0 else 0.0

        # Segment reply rate
        tier = aum_to_tier(aum)
        segment_score = segment_rates.get(tier, 0.0)

        # Channel availability (0-1): has email + has linkedin = 1.0
        has_email = 1.0 if row["email_status"] == "valid" else 0.0
        has_linkedin = 1.0 if row["linkedin_url"] else 0.0
        channel_score = (has_email + has_linkedin) / 2.0

        # Waiting time decay: contacts waiting longer get a boost
        if row["next_action_date"]:
            try:
                action_date = date.fromisoformat(str(row["next_action_date"])[:10])
                days_waiting = (today - action_date).days
                recency_score = min(days_waiting / float(RECENCY_CAP_DAYS), 1.0)
            except (ValueError, TypeError):
                recency_score = 0.5
        else:
            recency_score = 0.5

        # Composite score
        priority_score = (
            WEIGHT_AUM * aum_score
            + WEIGHT_SEGMENT * segment_score
            + WEIGHT_CHANNEL * channel_score
            + WEIGHT_RECENCY * recency_score
        )

        results.append({
            "contact_id": row["id"],
            "priority_score": round(priority_score, 4),
            "breakdown": {
                "aum_score": round(aum_score, 4),
                "segment_score": round(segment_score, 4),
                "channel_score": round(channel_score, 4),
                "recency_score": round(recency_score, 4),
            },
        })

    results.sort(key=lambda r: r["priority_score"], reverse=True)
    return results


def aum_to_tier(aum: float) -> str:
    """Map AUM in millions to a tier string."""
    if aum < 100:
        return "$0-100M"
    elif aum < 500:
        return "$100M-500M"
    elif aum < 1000:
        return "$500M-1B"
    else:
        return "$1B+"
