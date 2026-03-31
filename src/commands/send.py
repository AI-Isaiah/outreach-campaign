"""CLI command handler: send today's outreach emails."""

from __future__ import annotations

from src.models.campaigns import get_campaign_by_name
from src.services.priority_queue import get_daily_queue
from src.services.email_sender import send_campaign_email


def get_email_queue(conn, campaign_name: str, *, user_id: int, limit: int = 10, date: str | None = None) -> dict:
    """Get today's email queue for a campaign.

    Returns dict with 'campaign_id', 'email_items' list.
    Raises ValueError if campaign not found.
    """
    camp = get_campaign_by_name(conn, campaign_name, user_id=user_id)
    if not camp:
        raise ValueError(f"Campaign '{campaign_name}' not found")

    campaign_id = camp["id"]
    queue_items = get_daily_queue(conn, campaign_id, target_date=date, limit=limit, user_id=user_id)
    email_items = [item for item in queue_items if item["channel"] == "email"]

    return {
        "campaign_id": campaign_id,
        "email_items": email_items,
    }


def send_emails(conn, campaign_id: int, email_items: list[dict], config: dict, *, user_id: int) -> dict:
    """Send a batch of campaign emails.

    Returns dict with 'sent' and 'failed' counts.
    """
    sent = 0
    failed = 0
    for item in email_items:
        success = send_campaign_email(
            conn,
            item["contact_id"],
            campaign_id,
            item["template_id"],
            config,
            user_id=user_id,
        )
        if success:
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "failed": failed}
