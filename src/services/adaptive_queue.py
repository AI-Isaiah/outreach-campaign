"""Adaptive queue orchestrator for the outreach engine.

Builds on top of priority_queue.get_daily_queue for eligibility,
then enriches each item with adaptive scoring, template selection,
and rendered content.
"""

from __future__ import annotations

from datetime import date
from collections import defaultdict
from typing import Optional

from src.models.database import get_cursor
from src.services.contact_scorer import score_contacts
from src.services.priority_queue import get_daily_queue
from src.services.template_selector import select_template


def get_adaptive_queue(
    conn,
    campaign_id: int,
    target_date: Optional[str] = None,
    limit: int = 20,
    diverse: bool = True,
    scope: str = "today",
    *,
    user_id: Optional[int] = None,
) -> list[dict]:
    """Get the daily queue with adaptive scoring and template recommendations.

    Reuses priority_queue.get_daily_queue for eligibility, then enriches
    each item with:
    - priority_score and breakdown from contact_scorer
    - template recommendation from template_selector
    - reasoning explaining the selection
    - previous touches from contact_template_history
    - channel rule enforcement

    Falls back to static queue on error.
    """
    # Get base queue items (eligibility)
    items = get_daily_queue(conn, campaign_id, target_date=target_date, limit=limit * 3, scope=scope)

    if not items:
        return []

    # Score all contacts
    contact_ids = [item["contact_id"] for item in items]
    scores = score_contacts(conn, campaign_id, contact_ids, user_id=user_id)
    score_map = {s["contact_id"]: s for s in scores}

    # Get available templates per channel
    with get_cursor(conn) as cursor:
        templates_query = "SELECT * FROM templates WHERE is_active = true"
        templates_params: list = []
        if user_id is not None:
            templates_query += " AND user_id = %s"
            templates_params.append(user_id)
        templates_query += " ORDER BY id"
        cursor.execute(templates_query, templates_params)
        all_templates = [dict(r) for r in cursor.fetchall()]

        templates_by_channel = {}
        for t in all_templates:
            ch = t["channel"]
            templates_by_channel.setdefault(ch, []).append(t)

        # Get previous touches per contact
        cursor.execute(
            """SELECT contact_id, string_agg(channel, ',' ORDER BY sent_at) AS channels
               FROM contact_template_history
               WHERE campaign_id = %s
               GROUP BY contact_id""",
            (campaign_id,),
        )
        history_map = {}
        for row in cursor.fetchall():
            history_map[row["contact_id"]] = row["channels"].split(",") if row["channels"] else []

        enriched = []
        for item in items:
            contact_id = item["contact_id"]
            channel = item["channel"]

            # Apply channel rules
            prev_channels = history_map.get(contact_id, [])
            channel = _apply_channel_rules(channel, prev_channels, item)

            # Get adaptive score
            score_data = score_map.get(contact_id, {
                "priority_score": 0.0,
                "breakdown": {"aum_score": 0.0, "segment_score": 0.0, "channel_score": 0.0, "recency_score": 0.0},
            })

            # Check for manual override
            override_key = f"override_{contact_id}_{campaign_id}"
            cursor.execute(
                "SELECT value FROM engine_config WHERE key = %s",
                (override_key,),
            )
            override_row = cursor.fetchone()

            if override_row:
                # Manual override takes priority
                template_result = {
                    "template_id": int(override_row["value"]),
                    "selection_mode": "manual_override",
                    "reasoning": "Template manually overridden by operator",
                    "alternatives": [],
                }
                # Clean up the override (one-time use)
                cursor.execute("DELETE FROM engine_config WHERE key = %s", (override_key,))
                conn.commit()
            else:
                # Adaptive template selection
                available = templates_by_channel.get(channel, [])
                template_result = select_template(
                    conn, contact_id, campaign_id, channel, available,
                )

            enriched_item = {
                **item,
                "channel": channel,
                "priority_score": score_data["priority_score"],
                "score_breakdown": score_data.get("breakdown", {}),
                "recommended_template_id": template_result["template_id"],
                "selection_mode": template_result["selection_mode"],
                "reasoning": template_result["reasoning"],
                "alternatives": template_result.get("alternatives", []),
                "previous_touches": len(prev_channels),
                "previous_channels": prev_channels[-3:] if prev_channels else [],
            }

            # Use recommended template if original has none
            if template_result["template_id"] and not item.get("template_id"):
                enriched_item["template_id"] = template_result["template_id"]

            enriched.append(enriched_item)

    # Sort by priority score descending
    enriched.sort(key=lambda x: x["priority_score"], reverse=True)

    if diverse:
        return _diversify_by_firm_type(enriched, limit)
    return enriched[:limit]


def _apply_channel_rules(
    channel: str,
    prev_channels: list[str],
    item: dict,
) -> str:
    """Apply channel rules:
    1. LinkedIn first for new contacts (0 previous touches)
    2. Never 3 same channel in a row
    """
    # Rule 1: LinkedIn first for new contacts
    if not prev_channels and channel == "email":
        if item.get("linkedin_url"):
            return "linkedin_connect"

    # Rule 2: Never 3 same in a row
    if len(prev_channels) >= 2:
        last_two = prev_channels[-2:]
        base_channel = channel.split("_")[0] if "_" in channel else channel
        if all(c.startswith(base_channel) for c in last_two):
            # Switch channel
            if base_channel == "email" and item.get("linkedin_url"):
                return "linkedin_message"
            elif base_channel.startswith("linkedin") and item.get("email"):
                return "email"

    return channel


def _diversify_by_firm_type(items: list[dict], limit: int) -> list[dict]:
    """Round-robin pick across firm types to ensure a diverse queue.

    1. Group items by firm_type (NULL → "Unknown")
    2. Each bucket is already sorted by priority_score DESC (from caller)
    3. Order buckets by their top item's score
    4. Round-robin pick from each bucket until limit reached
    """
    if not items:
        return []

    buckets: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        key = item.get("firm_type") or "Unknown"
        buckets[key].append(item)

    # Order buckets by top item's score (highest first)
    ordered_keys = sorted(
        buckets.keys(),
        key=lambda k: buckets[k][0]["priority_score"] if buckets[k] else 0,
        reverse=True,
    )

    result: list[dict] = []
    indices = {k: 0 for k in ordered_keys}

    while len(result) < limit:
        added = False
        for key in ordered_keys:
            if indices[key] < len(buckets[key]):
                result.append(buckets[key][indices[key]])
                indices[key] += 1
                added = True
                if len(result) >= limit:
                    break
        if not added:
            break

    return result
