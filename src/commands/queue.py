"""Queue command: show today's outreach actions for a campaign."""

from __future__ import annotations

from typing import Optional


def queue_today(
    conn,
    campaign_name: str,
    target_date: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Get today's queue for a campaign. Returns the queue list.

    Args:
        conn: database connection
        campaign_name: name of the campaign to pull the queue for
        target_date: ISO date string (YYYY-MM-DD); defaults to today
        limit: maximum number of results to return

    Returns:
        List of dicts, each representing a contact ready for action,
        ordered by company AUM descending. Returns empty list if the
        campaign is not found.
    """
    from src.models.campaigns import get_campaign_by_name
    from src.services.priority_queue import get_daily_queue

    campaign = get_campaign_by_name(conn, campaign_name)
    if not campaign:
        return []
    return get_daily_queue(conn, campaign["id"], target_date=target_date, limit=limit)
