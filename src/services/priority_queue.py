"""Priority queue algorithm for daily outreach campaign execution.

Determines which contacts should be acted upon each day.
Core rules:
- One contact per company at a time (lowest priority_rank)
- Contacts ordered by sequence step ascending, then by action date ascending
- Only verified emails for email steps
- Only contacts with LinkedIn URLs for LinkedIn steps
- Respects GDPR step filtering
- Skips unsubscribed contacts
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from src.enums import ContactStatus
from src.models.database import get_cursor


def get_daily_queue(
    conn,
    campaign_id: int,
    target_date: Optional[str] = None,
    limit: int = 10,
    scope: str = "today",
    *,
    user_id: int,
) -> list[dict]:
    """Return the prioritized list of contacts to action today.

    Args:
        conn: database connection
        campaign_id: which campaign to pull the queue for
        target_date: ISO date string (YYYY-MM-DD); defaults to today
        limit: maximum number of results to return
        scope: queue scope filter. "today" (default) = next_action_date <= target_date,
               "all" = no date filter, "overdue" = next_action_date < target_date

    Returns:
        List of dicts, each representing a contact ready for action, ordered
        by company AUM descending (NULLs last).
    """
    if target_date is None:
        target_date = date.today().isoformat()

    # Guard: verify campaign exists and belongs to user before running the heavy CTE query
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT id FROM campaigns WHERE id = %s AND user_id = %s",
            (campaign_id, user_id),
        )
        if not cursor.fetchone():
            raise ValueError(f"Campaign {campaign_id} not found")

    # Build date filter based on scope
    if scope == "all":
        date_filter = ""
        date_params: list = []
    elif scope == "overdue":
        date_filter = "AND ccs.next_action_date < %s"
        date_params = [target_date]
    else:  # "today" (default)
        date_filter = "AND ccs.next_action_date <= %s"
        date_params = [target_date]

    query = f"""
    WITH eligible AS (
        SELECT
            c.id AS contact_id,
            c.first_name,
            c.last_name,
            c.full_name,
            c.company_id,
            c.email_normalized AS email,
            c.email_status,
            c.linkedin_url_normalized AS linkedin_url,
            c.priority_rank,
            c.is_gdpr AS contact_is_gdpr,
            comp.name AS company_name,
            comp.aum_millions,
            comp.firm_type,
            ccs.current_step, ccs.current_step_id,
            ccs.status AS ccs_status,
            ccs.next_action_date,
            ccs.channel_override
        FROM contact_campaign_status ccs
        JOIN contacts c ON c.id = ccs.contact_id
        JOIN companies comp ON comp.id = c.company_id
        WHERE ccs.campaign_id = %s
          AND ccs.status IN (%s, %s)
          {date_filter}
          AND c.unsubscribed = false
    ),
    ranked AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY company_id
                ORDER BY priority_rank ASC
            ) AS rn
        FROM eligible
    ),
    active_contacts AS (
        SELECT * FROM ranked WHERE rn = 1
    )
    SELECT
        ac.contact_id,
        COALESCE(ac.full_name,
                 TRIM(COALESCE(ac.first_name, '') || ' ' || COALESCE(ac.last_name, '')),
                 '') AS contact_name,
        ac.company_name,
        ac.company_id,
        ac.aum_millions,
        ac.firm_type,
        COALESCE(ac.channel_override, ss.channel) AS channel,
        ss.step_order,
        ss.template_id,
        ac.contact_is_gdpr AS is_gdpr,
        ac.email,
        ac.linkedin_url,
        ac.email_status
    FROM active_contacts ac
    JOIN sequence_steps ss
      ON ss.campaign_id = %s
     AND ss.stable_id = ac.current_step_id
    WHERE
        -- Email steps: must have valid email
        (ss.channel != 'email' OR ac.email_status = 'valid')
        -- LinkedIn steps: must have a LinkedIn URL
        AND (
            (ss.channel NOT LIKE 'linkedin%%')
            OR (ac.linkedin_url IS NOT NULL AND ac.linkedin_url != '')
        )
        -- GDPR filtering on steps
        AND (ss.non_gdpr_only = false OR ac.contact_is_gdpr = false)
        AND (ss.gdpr_only = false OR ac.contact_is_gdpr = true)
    ORDER BY
        ss.step_order ASC,
        ac.next_action_date ASC
    LIMIT %s
    """

    with get_cursor(conn) as cursor:
        query_params = [campaign_id, ContactStatus.QUEUED, ContactStatus.IN_PROGRESS] + date_params + [campaign_id, limit]
        cursor.execute(query, query_params)
        rows = cursor.fetchall()

        if not rows:
            return []

        # Batch compute total_steps: one query for GDPR, one for non-GDPR
        # The is_gdpr flag is already in each row from the CTE
        gdpr_contacts = {r["contact_id"] for r in rows if r["is_gdpr"]}
        non_gdpr_contacts = {r["contact_id"] for r in rows if not r["is_gdpr"]}

        # Count steps by GDPR status (2 queries instead of 2N)
        steps_count = {}
        if non_gdpr_contacts:
            cursor.execute(
                """SELECT COUNT(*) AS cnt FROM sequence_steps
                   WHERE campaign_id = %s
                     AND (non_gdpr_only = false OR %s = false)
                     AND (gdpr_only = false OR %s = true)""",
                (campaign_id, False, False),
            )
            non_gdpr_steps = cursor.fetchone()["cnt"]
            for cid in non_gdpr_contacts:
                steps_count[cid] = non_gdpr_steps

        if gdpr_contacts:
            cursor.execute(
                """SELECT COUNT(*) AS cnt FROM sequence_steps
                   WHERE campaign_id = %s
                     AND (non_gdpr_only = false OR %s = false)
                     AND (gdpr_only = false OR %s = true)""",
                (campaign_id, True, True),
            )
            gdpr_steps = cursor.fetchone()["cnt"]
            for cid in gdpr_contacts:
                steps_count[cid] = gdpr_steps

        results = []
        for row in rows:
            results.append(
                {
                    "contact_id": row["contact_id"],
                    "contact_name": row["contact_name"],
                    "company_name": row["company_name"],
                    "company_id": row["company_id"],
                    "aum_millions": row["aum_millions"],
                    "firm_type": row["firm_type"],
                    "channel": row["channel"],
                    "step_order": row["step_order"],
                    "total_steps": steps_count.get(row["contact_id"], 0),
                    "template_id": row["template_id"],
                    "is_gdpr": bool(row["is_gdpr"]),
                    "email": row["email"],
                    "linkedin_url": row["linkedin_url"],
                }
            )

        return results


def get_next_step_for_contact(
    conn,
    contact_id: int,
    campaign_id: int,
    *,
    user_id: int,
) -> dict | None:
    """Return the sequence_step row for the contact's next action, or None.

    Looks at the contact's current_step in contact_campaign_status, then finds
    the matching sequence_step. Respects GDPR filtering.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            """
            SELECT c.is_gdpr, ccs.current_step, ccs.current_step_id
            FROM contact_campaign_status ccs
            JOIN contacts c ON c.id = ccs.contact_id
            WHERE ccs.contact_id = %s AND ccs.campaign_id = %s
              AND c.user_id = %s
            """,
            (contact_id, campaign_id, user_id),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        is_gdpr = row["is_gdpr"]
        current_step = row["current_step"]

        cursor.execute(
            """
            SELECT * FROM sequence_steps
            WHERE campaign_id = %s
              AND step_order >= %s
              AND (non_gdpr_only = false OR %s = false)
              AND (gdpr_only = false OR %s = true)
            ORDER BY step_order ASC
            LIMIT 1
            """,
            (campaign_id, current_step, is_gdpr, is_gdpr),
        )
        step = cursor.fetchone()

        return step


def count_steps_for_contact(
    conn,
    contact_id: int,
    campaign_id: int,
    *,
    user_id: int,
) -> int:
    """Return the total number of steps this contact would go through.

    Accounts for GDPR filtering: if the contact is GDPR, steps marked
    non_gdpr_only are excluded (and vice versa for gdpr_only).
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT is_gdpr FROM contacts WHERE id = %s AND user_id = %s",
            (contact_id, user_id),
        )
        row = cursor.fetchone()

        if row is None:
            return 0

        is_gdpr = row["is_gdpr"]

        cursor.execute(
            """
            SELECT COUNT(*) AS cnt FROM sequence_steps
            WHERE campaign_id = %s
              AND (non_gdpr_only = false OR %s = false)
              AND (gdpr_only = false OR %s = true)
            """,
            (campaign_id, is_gdpr, is_gdpr),
        )
        result = cursor.fetchone()

        return result["cnt"] if result else 0


def defer_contact(
    conn,
    contact_id: int,
    campaign_id: int,
    reason: Optional[str] = None,
    *,
    user_id: int,
) -> dict:
    """Defer a contact to the back of the queue.

    Pushes next_action_date to tomorrow and logs a ``deferred`` event
    with the optional reason. The contact stays in their current status
    (queued or in_progress) — deferral is not a terminal state.

    Args:
        conn: database connection
        contact_id: the contact to defer
        campaign_id: the campaign context
        reason: optional skip reason for analytics

    Returns:
        Dict with success status and new next_action_date.
    """
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    with get_cursor(conn) as cursor:
        cursor.execute(
            """UPDATE contact_campaign_status
               SET next_action_date = %s, updated_at = NOW()
               WHERE contact_id = %s AND campaign_id = %s
                 AND contact_id IN (SELECT id FROM contacts WHERE user_id = %s)
               RETURNING id""",
            (tomorrow, contact_id, campaign_id, user_id),
        )
        row = cursor.fetchone()
        if row is None:
            return {"success": False, "error": "Contact not enrolled in campaign"}

        cursor.execute(
            """INSERT INTO events (contact_id, campaign_id, event_type, notes, user_id)
               VALUES (%s, %s, 'deferred', %s, %s)""",
            (contact_id, campaign_id, reason, user_id),
        )
        conn.commit()

    return {
        "success": True,
        "contact_id": contact_id,
        "next_action_date": tomorrow,
        "reason": reason,
    }


def get_defer_stats(
    conn,
    campaign_id: Optional[int] = None,
    target_date: Optional[str] = None,
    *,
    user_id: int,
) -> dict:
    """Get defer/skip analytics.

    Returns:
        Dict with: today_count, total_count, by_reason (list of {reason, count}),
        repeat_deferrals (contacts deferred 2+ times).
    """
    if target_date is None:
        target_date = date.today().isoformat()

    with get_cursor(conn) as cursor:
        # Count deferrals today
        params_today: list = [target_date, user_id]
        today_query = """
            SELECT COUNT(*) AS cnt FROM events
            WHERE event_type = 'deferred'
              AND created_at::date = %s
              AND user_id = %s
        """
        if campaign_id:
            today_query += " AND campaign_id = %s"
            params_today.append(campaign_id)
        cursor.execute(today_query, params_today)
        today_count = cursor.fetchone()["cnt"]

        # Total deferrals
        params_total: list = [user_id]
        total_query = "SELECT COUNT(*) AS cnt FROM events WHERE event_type = 'deferred' AND user_id = %s"
        if campaign_id:
            total_query += " AND campaign_id = %s"
            params_total.append(campaign_id)
        cursor.execute(total_query, params_total)
        total_count = cursor.fetchone()["cnt"]

        # By reason
        params_reason: list = [user_id]
        reason_query = """
            SELECT notes AS reason, COUNT(*) AS cnt
            FROM events
            WHERE event_type = 'deferred'
              AND user_id = %s
        """
        if campaign_id:
            reason_query += " AND campaign_id = %s"
            params_reason.append(campaign_id)
        reason_query += " GROUP BY notes ORDER BY cnt DESC"
        cursor.execute(reason_query, params_reason)
        by_reason = [{"reason": r["reason"] or "No reason", "count": r["cnt"]} for r in cursor.fetchall()]

        # Repeat deferrals (contacts deferred 2+ times)
        params_repeat: list = [user_id]
        repeat_query = """
            SELECT e.contact_id, COUNT(*) AS defer_count,
                   COALESCE(c.full_name, c.email, c.id::text) AS contact_name
            FROM events e
            JOIN contacts c ON c.id = e.contact_id
            WHERE e.event_type = 'deferred'
              AND e.user_id = %s
        """
        if campaign_id:
            repeat_query += " AND e.campaign_id = %s"
            params_repeat.append(campaign_id)
        repeat_query += " GROUP BY e.contact_id, c.full_name, c.email, c.id HAVING COUNT(*) >= 2 ORDER BY defer_count DESC LIMIT 20"
        cursor.execute(repeat_query, params_repeat)
        repeat_deferrals = [
            {"contact_id": r["contact_id"], "contact_name": r["contact_name"], "defer_count": r["defer_count"]}
            for r in cursor.fetchall()
        ]

    return {
        "today_count": today_count,
        "total_count": total_count,
        "by_reason": by_reason,
        "repeat_deferrals": repeat_deferrals,
    }
