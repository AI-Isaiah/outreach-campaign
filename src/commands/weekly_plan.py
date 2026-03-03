"""Weekly planning report generation.

Generates a structured report for the weekly check-in, including last-week
metrics, A/B variant comparison, proposed next-week actions, and a
newsletter recommendation.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from src.models.campaigns import get_campaign_by_name
from src.services.metrics import (
    get_campaign_metrics,
    get_variant_comparison,
    get_weekly_summary,
    get_company_type_breakdown,
)


def generate_weekly_plan(conn, campaign_name: str) -> dict:
    """Generate the weekly check-in report.

    Returns a dict with all the data needed for the terminal display:
    - campaign: dict with id, name, status
    - last_week: weekly summary metrics
    - overall: campaign-wide metrics
    - variant_comparison: list of variant stats
    - company_type_breakdown: list of firm_type stats
    - proposed_next_week: dict with contacts_ready, channel_mix
    - newsletter_recommendation: dict with recommend (bool) and reason (str)
    - next_actions: list of action strings
    """
    camp = get_campaign_by_name(conn, campaign_name)
    if camp is None:
        raise ValueError(f"Campaign '{campaign_name}' not found")

    campaign_id = camp["id"]

    # Gather data
    overall = get_campaign_metrics(conn, campaign_id)
    last_week = get_weekly_summary(conn, campaign_id, weeks_back=1)
    variants = get_variant_comparison(conn, campaign_id)
    firm_breakdown = get_company_type_breakdown(conn, campaign_id)

    # Proposed next week: count contacts ready (queued with next_action_date
    # in the coming week, or past due)
    today = date.today()
    next_week_end = today + timedelta(days=7)

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM contact_campaign_status
        WHERE campaign_id = %s
          AND status IN ('queued', 'in_progress')
          AND (next_action_date IS NULL OR next_action_date <= %s)
        """,
        (campaign_id, next_week_end.isoformat()),
    )
    ready_rows = cursor.fetchone()
    contacts_ready = ready_rows["cnt"] if ready_rows else 0

    # Channel mix: count by channel for ready contacts
    cursor.execute(
        """
        SELECT ss.channel, COUNT(*) AS cnt
        FROM contact_campaign_status ccs
        JOIN sequence_steps ss
          ON ss.campaign_id = ccs.campaign_id
         AND ss.step_order = ccs.current_step
        WHERE ccs.campaign_id = %s
          AND ccs.status IN ('queued', 'in_progress')
          AND (ccs.next_action_date IS NULL OR ccs.next_action_date <= %s)
        GROUP BY ss.channel
        ORDER BY cnt DESC
        """,
        (campaign_id, next_week_end.isoformat()),
    )
    channel_rows = cursor.fetchall()

    channel_mix = {}
    for row in channel_rows:
        channel_mix[row["channel"]] = row["cnt"]

    # Newsletter recommendation
    newsletter_rec = _newsletter_recommendation(conn, campaign_id, overall)

    # Next actions
    next_actions = _generate_next_actions(
        overall, last_week, contacts_ready, channel_mix, variants
    )

    return {
        "campaign": {
            "id": campaign_id,
            "name": camp["name"],
            "status": camp["status"],
        },
        "last_week": last_week,
        "overall": overall,
        "variant_comparison": variants,
        "company_type_breakdown": firm_breakdown,
        "proposed_next_week": {
            "contacts_ready": contacts_ready,
            "channel_mix": channel_mix,
        },
        "newsletter_recommendation": newsletter_rec,
        "next_actions": next_actions,
    }


def _newsletter_recommendation(
    conn,
    campaign_id: int,
    overall: dict,
) -> dict:
    """Determine whether to send a newsletter this week.

    Returns dict with 'recommend' (bool) and 'reason' (str).

    Heuristics:
    - If there are contacts with replied_positive, recommend yes (nurture warm leads)
    - If no_response count is high relative to total, recommend yes (re-engage)
    - Otherwise, recommend no (focus on direct outreach)
    """
    by_status = overall["by_status"]
    total = overall["total_enrolled"]
    positive = by_status["replied_positive"]
    no_response = by_status["no_response"]

    if positive > 0:
        return {
            "recommend": True,
            "reason": (
                f"{positive} positive reply(s) to nurture. "
                "A newsletter keeps warm leads engaged."
            ),
        }

    if total > 0 and no_response > 0 and (no_response / total) >= 0.3:
        return {
            "recommend": True,
            "reason": (
                f"{no_response}/{total} contacts with no response. "
                "A newsletter can re-engage cold contacts."
            ),
        }

    return {
        "recommend": False,
        "reason": "Focus on direct outreach this week.",
    }


def _generate_next_actions(
    overall: dict,
    last_week: dict,
    contacts_ready: int,
    channel_mix: dict,
    variants: list[dict],
) -> list[str]:
    """Generate suggested next actions based on metrics."""
    actions = []

    if contacts_ready > 0:
        actions.append(
            f"Process {contacts_ready} contact(s) ready for next action"
        )

    for channel, count in channel_mix.items():
        if channel == "email":
            actions.append(f"Send {count} email(s) via `outreach send`")
        elif channel in ("linkedin_connect", "linkedin_message"):
            actions.append(
                f"Export {count} LinkedIn action(s) via `outreach export-expandi`"
            )

    if overall["by_status"]["in_progress"] > 0:
        actions.append(
            f"Follow up on {overall['by_status']['in_progress']} in-progress contact(s)"
        )

    if len(variants) >= 2:
        best = max(variants, key=lambda v: v["positive_rate"])
        worst = min(variants, key=lambda v: v["positive_rate"])
        if best["positive_rate"] > worst["positive_rate"] and best["total"] >= 5:
            actions.append(
                f"Consider favoring variant {best['variant']} "
                f"(positive rate: {best['positive_rate']:.1%} vs "
                f"{worst['positive_rate']:.1%})"
            )

    if not actions:
        actions.append("No immediate actions required. Review campaign status.")

    return actions
