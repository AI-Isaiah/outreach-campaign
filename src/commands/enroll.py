"""CLI command handler: enroll eligible contacts into a campaign."""

from __future__ import annotations

from datetime import date as date_mod

from src.models.campaigns import get_campaign_by_name, enroll_contact
from src.models.database import get_cursor


def enroll_contacts(
    conn,
    campaign_name: str,
    *,
    user_id: int,
    limit: int | None = None,
    max_aum: float | None = None,
    min_aum: float | None = None,
) -> dict:
    """Enroll eligible contacts into a campaign.

    Eligible: has email or LinkedIn, not unsubscribed, rank-1 per company,
    not already enrolled. Enrolled in AUM descending order.

    Returns dict with 'enrolled_count', 'campaign_name', 'aum_filter'.
    Raises ValueError if campaign not found.
    """
    camp = get_campaign_by_name(conn, campaign_name, user_id=user_id)
    if not camp:
        raise ValueError(f"Campaign '{campaign_name}' not found")

    campaign_id = camp["id"]

    query = """
    SELECT c.id, c.company_id, co.aum_millions
    FROM contacts c
    LEFT JOIN companies co ON co.id = c.company_id
    WHERE c.priority_rank = 1
      AND c.unsubscribed = false
      AND (
          (c.email_normalized IS NOT NULL AND c.email_normalized != '')
          OR (c.linkedin_url IS NOT NULL AND c.linkedin_url != '')
      )
      AND c.id NOT IN (
          SELECT contact_id FROM contact_campaign_status WHERE campaign_id = %s
      )
    """
    params: list = [campaign_id]

    if max_aum is not None:
        query += " AND (co.aum_millions IS NULL OR co.aum_millions < %s)"
        params.append(max_aum)

    if min_aum is not None:
        query += " AND co.aum_millions IS NOT NULL AND co.aum_millions >= %s"
        params.append(min_aum)

    # Order by AUM descending (NULLs last) so highest-value targets enroll first
    query += " ORDER BY CASE WHEN co.aum_millions IS NULL THEN 1 ELSE 0 END, co.aum_millions DESC"

    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    with get_cursor(conn) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    enrolled_count = 0
    today = date_mod.today().isoformat()
    for row in rows:
        result = enroll_contact(conn, row["id"], campaign_id, next_action_date=today, user_id=user_id)
        if result is not None:
            enrolled_count += 1

    aum_filter = ""
    if max_aum is not None or min_aum is not None:
        parts = []
        if min_aum is not None:
            parts.append(f"min ${min_aum:,.0f}M")
        if max_aum is not None:
            parts.append(f"max ${max_aum:,.0f}M")
        aum_filter = f" (AUM filter: {', '.join(parts)})"

    return {
        "enrolled_count": enrolled_count,
        "campaign_name": campaign_name,
        "aum_filter": aum_filter,
    }
