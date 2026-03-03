"""A/B variant assignment and statistics for outreach campaigns.

Provides deterministic variant assignment based on contact_id and
reply-rate statistics broken down by variant.
"""

from __future__ import annotations

import random
from typing import Optional


def assign_variant(contact_id: int, variants: list[str] = None) -> str:
    """Assign a contact to an A/B variant deterministically.

    Uses contact_id as seed for reproducible assignment. Calling this
    function multiple times with the same contact_id always returns the
    same variant.

    Args:
        contact_id: the contact to assign a variant to
        variants: list of variant labels (default ``["A", "B"]``)

    Returns:
        The assigned variant label.
    """
    if variants is None:
        variants = ["A", "B"]
    rng = random.Random(contact_id)
    return rng.choice(variants)


def get_variant_stats(conn, campaign_id: int) -> list[dict]:
    """Get reply stats broken down by assigned variant.

    Queries ``contact_campaign_status`` for each distinct variant in the
    campaign and computes counts of total enrollments, positive replies,
    negative replies, non-responses, and the overall reply rate.

    Args:
        conn: database connection
        campaign_id: the campaign to pull stats for

    Returns:
        List of dicts with keys: variant, total, replied_positive,
        replied_negative, no_response, reply_rate.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            assigned_variant,
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'replied_positive' THEN 1 ELSE 0 END) AS replied_positive,
            SUM(CASE WHEN status = 'replied_negative' THEN 1 ELSE 0 END) AS replied_negative,
            SUM(CASE WHEN status = 'no_response' THEN 1 ELSE 0 END) AS no_response
        FROM contact_campaign_status
        WHERE campaign_id = %s
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
        reply_rate = (positive + negative) / total if total > 0 else 0.0
        results.append({
            "variant": row["assigned_variant"],
            "total": total,
            "replied_positive": positive,
            "replied_negative": negative,
            "no_response": row["no_response"],
            "reply_rate": round(reply_rate, 4),
        })

    return results
