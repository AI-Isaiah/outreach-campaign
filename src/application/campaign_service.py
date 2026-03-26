"""Campaign application service — orchestrates campaign launch and related ops.

Extracted from routes/campaigns.py to keep the route layer thin.
"""

from __future__ import annotations

from datetime import date, timedelta

import psycopg2
import psycopg2.extras

from src.models.database import get_cursor


def launch_campaign(
    conn,
    *,
    name: str,
    description: str = "",
    steps: list[dict],
    contact_ids: list[int],
    status: str = "active",
    user_id: int,
) -> dict:
    """Create a campaign with sequence steps and enroll contacts atomically.

    Validates inputs, creates the campaign row, inserts sequence steps,
    and enrolls contacts (if status is 'active') in a single transaction.

    Args:
        conn: database connection
        name: campaign name
        description: campaign description
        steps: list of dicts with step_order, channel, delay_days,
               template_id (optional), draft_mode (optional)
        contact_ids: contacts to enroll
        status: 'active' or 'draft'
        user_id: owner (keyword-only)

    Returns:
        dict with campaign_id, name, status, contacts_enrolled, steps_created

    Raises:
        ValueError: if status is invalid, steps are empty, or contacts
                    are not found / not owned by user.
        psycopg2.IntegrityError: if campaign name already exists (caller
                                 should catch and map to 409).
    """
    if status not in ("active", "draft"):
        raise ValueError("status must be 'active' or 'draft'")

    if not steps:
        raise ValueError("At least one sequence step is required")

    # Verify all contacts belong to this user before starting the transaction
    if contact_ids:
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT id FROM contacts WHERE id = ANY(%s) AND user_id = %s",
                (contact_ids, user_id),
            )
            owned_ids = {row["id"] for row in cur.fetchall()}
            missing = set(contact_ids) - owned_ids
            if missing:
                raise ValueError(
                    f"Contacts not found or not owned by user: {sorted(missing)}"
                )

    with get_cursor(conn) as cur:
        # 1. Create the campaign
        cur.execute(
            "INSERT INTO campaigns (name, description, status, user_id) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (name, description, status, user_id),
        )
        campaign_id = cur.fetchone()["id"]

        # 2. Insert sequence steps
        for step in steps:
            cur.execute(
                """INSERT INTO sequence_steps
                   (campaign_id, step_order, channel, template_id, delay_days, draft_mode)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    campaign_id,
                    step["step_order"],
                    step["channel"],
                    step.get("template_id"),
                    step["delay_days"],
                    step.get("draft_mode", "template"),
                ),
            )

        # 3. Enroll contacts if status is active
        contacts_enrolled = 0
        if status == "active" and contact_ids:
            # Find step 1 delay_days for next_action_date
            step_1 = next((s for s in steps if s["step_order"] == 1), None)
            delay = step_1["delay_days"] if step_1 else 0
            next_action = date.today() + timedelta(days=delay)

            rows = [
                (cid, campaign_id, 1, "queued", next_action)
                for cid in contact_ids
            ]
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO contact_campaign_status
                   (contact_id, campaign_id, current_step, status, next_action_date)
                   VALUES %s""",
                rows,
            )
            contacts_enrolled = len(rows)

    conn.commit()

    return {
        "campaign_id": campaign_id,
        "name": name,
        "status": status,
        "contacts_enrolled": contacts_enrolled,
        "steps_created": len(steps),
    }
