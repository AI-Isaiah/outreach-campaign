"""CLI command handler: campaign report data gathering."""

from __future__ import annotations

from src.models.campaigns import get_campaign_by_name
from src.services.metrics import (
    get_campaign_metrics,
    get_variant_comparison,
    get_weekly_summary,
    get_company_type_breakdown,
)


def get_campaign_report(conn, campaign_name: str, *, user_id: int) -> dict:
    """Gather all report data for a campaign.

    Returns dict with 'campaign', 'metrics', 'weekly', 'variants', 'firm_breakdown'.
    Raises ValueError if campaign not found.
    """
    camp = get_campaign_by_name(conn, campaign_name, user_id=user_id)
    if not camp:
        raise ValueError(f"Campaign '{campaign_name}' not found")

    campaign_id = camp["id"]
    metrics = get_campaign_metrics(conn, campaign_id, user_id=user_id)
    weekly = get_weekly_summary(conn, campaign_id, weeks_back=1, user_id=user_id)
    variants = get_variant_comparison(conn, campaign_id, user_id=user_id)
    firm_breakdown = get_company_type_breakdown(conn, campaign_id, user_id=user_id)

    return {
        "campaign": camp,
        "metrics": metrics,
        "weekly": weekly,
        "variants": variants,
        "firm_breakdown": firm_breakdown,
    }
