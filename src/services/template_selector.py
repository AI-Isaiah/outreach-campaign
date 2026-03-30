"""Template selection with explore/exploit for the adaptive outreach engine.

Selects the best template for a contact based on performance data,
using an explore/exploit strategy with decreasing explore rate.
"""

from __future__ import annotations

import random
from typing import Optional

from src.models.database import get_cursor
from src.services.response_analyzer import get_template_performance


def select_template(
    conn,
    contact_id: int,
    campaign_id: int,
    channel: str,
    available_templates: list[dict],
    *,
    user_id: int = 1,
) -> dict:
    """Select a template for a contact using explore/exploit.

    Filters already-sent templates via contact_template_history.
    Explore rate: 30% (<50 sends) -> 15% (50-150) -> 5% (150+).

    Returns dict with: template_id, selection_mode ('exploit'|'explore'|'cold_start'),
    reasoning, alternatives.
    """
    if not available_templates:
        return {
            "template_id": None,
            "selection_mode": "no_templates",
            "reasoning": "No templates available for this channel",
            "alternatives": [],
        }

    # Filter out already-sent templates for this contact
    with get_cursor(conn) as cursor:
        cursor.execute(
            """SELECT template_id FROM contact_template_history
               WHERE contact_id = %s AND campaign_id = %s""",
            (contact_id, campaign_id),
        )
        sent_ids = {row["template_id"] for row in cursor.fetchall()}
        unsent = [t for t in available_templates if t["id"] not in sent_ids]

        if not unsent:
            # All templates have been sent to this contact — reuse best performer
            unsent = available_templates

        # Get performance data
        perf = get_template_performance(conn, campaign_id, user_id=user_id)
        perf_by_id = {p["template_id"]: p for p in perf}

        # Get total campaign sends for explore rate calculation
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM contact_template_history WHERE campaign_id = %s",
            (campaign_id,),
        )
        total_sends = cursor.fetchone()["cnt"]

    # Determine explore rate
    if total_sends < 50:
        explore_rate = 0.30
    elif total_sends < 150:
        explore_rate = 0.15
    else:
        explore_rate = 0.05

    # Check for cold start (no performance data for any template in this channel)
    channel_perf = [p for p in perf if p["channel"] == channel]
    is_cold_start = len(channel_perf) == 0

    if is_cold_start:
        # Cold start: pick first template by ID (created_at ASC)
        selected = min(unsent, key=lambda t: t["id"])
        return {
            "template_id": selected["id"],
            "selection_mode": "cold_start",
            "reasoning": f"Cold start: no performance data yet. Using first template '{selected['name']}'.",
            "alternatives": [{"template_id": t["id"], "name": t["name"]} for t in unsent if t["id"] != selected["id"]],
        }

    # Exploit: pick highest positive_rate template
    def template_score(t):
        p = perf_by_id.get(t["id"])
        if p:
            return p["positive_rate"]
        return 0.0  # untested templates get 0 in exploit mode

    # Sort by score descending
    ranked = sorted(unsent, key=template_score, reverse=True)
    best = ranked[0]

    # Explore: randomly pick a non-best template
    should_explore = random.random() < explore_rate and len(ranked) > 1

    if should_explore:
        # Pick randomly from non-best templates (prefer untested)
        alternatives = ranked[1:]
        untested = [t for t in alternatives if t["id"] not in perf_by_id]
        pool = untested if untested else alternatives
        selected = random.choice(pool)
        return {
            "template_id": selected["id"],
            "selection_mode": "explore",
            "reasoning": (
                f"Exploring: trying '{selected['name']}' "
                f"(explore rate {explore_rate:.0%}, {total_sends} total sends). "
                f"Best performer is '{best['name']}' ({template_score(best):.0%} positive)."
            ),
            "alternatives": [{"template_id": t["id"], "name": t["name"], "positive_rate": template_score(t)}
                           for t in ranked[:3]],
        }
    else:
        return {
            "template_id": best["id"],
            "selection_mode": "exploit",
            "reasoning": (
                f"Exploiting best performer: '{best['name']}' "
                f"({template_score(best):.0%} positive rate, "
                f"{perf_by_id.get(best['id'], {}).get('total_sends', 0)} sends)."
            ),
            "alternatives": [{"template_id": t["id"], "name": t["name"], "positive_rate": template_score(t)}
                           for t in ranked[1:3]],
        }
