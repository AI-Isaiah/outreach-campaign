"""Campaign sequence reorder business logic.

Extracted from web/routes/campaigns.py to keep route handlers thin.
"""

from __future__ import annotations

from src.models.database import get_cursor


def reorder_campaign_sequence(
    conn,
    campaign_id: int,
    steps: list[dict],
    *,
    user_id: int,
) -> dict:
    """Reorder sequence steps for a campaign.

    Recalculates next_action_date for affected contacts.

    Args:
        conn: Database connection.
        campaign_id: The campaign whose sequence is being reordered.
        steps: List of dicts with keys: step_id, step_order, and optionally
               delay_days and channel.
        user_id: Owner user ID (for data isolation).

    Returns:
        Dict with ``steps`` (updated sequence) and ``affected_count``.
    """
    with get_cursor(conn) as cursor:
        # Verify campaign belongs to user
        cursor.execute(
            "SELECT id FROM campaigns WHERE id = %s AND user_id = %s",
            (campaign_id, user_id),
        )
        if not cursor.fetchone():
            raise ValueError(f"Campaign {campaign_id} not found or not owned by user")

        # Verify all steps belong to this campaign
        step_ids = [s["step_id"] for s in steps]
        placeholders = ",".join(["%s"] * len(step_ids))
        cursor.execute(
            f"SELECT id FROM sequence_steps WHERE campaign_id = %s AND id IN ({placeholders})",
            [campaign_id] + step_ids,
        )
        found = {r["id"] for r in cursor.fetchall()}
        if found != set(step_ids):
            raise ValueError("Some step_ids do not belong to this campaign")

        # Temp-slot reorder: phase 1 - offset all to temp range
        cursor.execute(
            "UPDATE sequence_steps SET step_order = step_order + 10000 WHERE campaign_id = %s",
            (campaign_id,),
        )

        # Phase 2: set final values via parameterized CASE
        order_case = " ".join("WHEN %s THEN %s" for _ in steps)
        order_params = [v for s in steps for v in (s["step_id"], s["step_order"])]

        # Build optional delay_days and channel CASE clauses
        set_clauses = [f"step_order = CASE id {order_case} END"]
        all_params = list(order_params)

        if any(s.get("delay_days") is not None for s in steps):
            delay_case = " ".join("WHEN %s THEN %s" for _ in steps)
            delay_params = [
                v
                for s in steps
                for v in (s["step_id"], s["delay_days"] if s.get("delay_days") is not None else 0)
            ]
            set_clauses.append(f"delay_days = CASE id {delay_case} END")
            all_params.extend(delay_params)

        if any(s.get("channel") is not None for s in steps):
            ch_case = " ".join("WHEN %s THEN %s" for _ in steps)
            ch_params = [
                v
                for s in steps
                for v in (s["step_id"], s["channel"] if s.get("channel") is not None else "email")
            ]
            set_clauses.append(f"channel = CASE id {ch_case} END")
            all_params.extend(ch_params)

        cursor.execute(
            f"UPDATE sequence_steps SET {', '.join(set_clauses)} "
            f"WHERE campaign_id = %s AND id IN ({placeholders})",
            all_params + [campaign_id] + step_ids,
        )

        # Count affected contacts
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM contact_campaign_status "
            "WHERE campaign_id = %s AND status IN ('queued', 'in_progress')",
            (campaign_id,),
        )
        affected_count = cursor.fetchone()["cnt"]

        # Update contacts who haven't been contacted yet to point to the new step 1
        cursor.execute(
            """UPDATE contact_campaign_status ccs
               SET current_step_id = (
                   SELECT stable_id FROM sequence_steps
                   WHERE campaign_id = %s AND step_order = 1
               ),
               current_step = 1
               WHERE ccs.campaign_id = %s
                 AND ccs.status = 'queued'
                 AND ccs.current_step = 1""",
            (campaign_id, campaign_id),
        )

        # Recalculate next_action_date based on current step's delay
        if affected_count > 0:
            cursor.execute("""
                UPDATE contact_campaign_status ccs
                SET next_action_date = (
                    SELECT CURRENT_DATE + (ss.delay_days || ' days')::interval
                    FROM sequence_steps ss
                    WHERE ss.stable_id = ccs.current_step_id
                )
                WHERE ccs.campaign_id = %s
                  AND ccs.status IN ('queued', 'in_progress')
                  AND ccs.current_step_id IS NOT NULL
            """, (campaign_id,))

        conn.commit()

        # Return updated sequence
        cursor.execute(
            """SELECT ss.*, t.subject AS template_subject, t.body_template AS template_body
               FROM sequence_steps ss
               LEFT JOIN templates t ON ss.template_id = t.id
               WHERE ss.campaign_id = %s ORDER BY ss.step_order""",
            (campaign_id,),
        )
        result_steps = [dict(r) for r in cursor.fetchall()]

    return {"steps": result_steps, "affected_count": affected_count}
