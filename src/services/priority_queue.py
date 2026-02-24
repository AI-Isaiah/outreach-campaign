"""Priority queue algorithm for daily outreach campaign execution.

Determines which contacts should be acted upon each day.
Core rules:
- One contact per company at a time (lowest priority_rank)
- Companies ordered by AUM descending
- Only verified emails for email steps
- Only contacts with LinkedIn URLs for LinkedIn steps
- Respects GDPR step filtering
- Skips unsubscribed contacts
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional


def get_daily_queue(
    conn: sqlite3.Connection,
    campaign_id: int,
    target_date: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Return the prioritized list of contacts to action today.

    Args:
        conn: database connection (must have row_factory = sqlite3.Row)
        campaign_id: which campaign to pull the queue for
        target_date: ISO date string (YYYY-MM-DD); defaults to today
        limit: maximum number of results to return

    Returns:
        List of dicts, each representing a contact ready for action, ordered
        by company AUM descending (NULLs last).
    """
    if target_date is None:
        target_date = date.today().isoformat()

    # Step 1: Find the active contact per company (lowest priority_rank among
    # enrolled contacts with status in ('queued','in_progress') and
    # next_action_date <= target_date, excluding unsubscribed).
    #
    # Step 2: Join with the contact's current sequence step to get channel info.
    #
    # Step 3: Filter out contacts who can't execute their current step:
    #   - email steps require email_status = 'valid'
    #   - linkedin steps require non-empty linkedin_url_normalized
    #
    # Step 4: Order by AUM DESC NULLS LAST, limit.

    query = """
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
            ccs.current_step,
            ccs.status AS ccs_status
        FROM contact_campaign_status ccs
        JOIN contacts c ON c.id = ccs.contact_id
        JOIN companies comp ON comp.id = c.company_id
        WHERE ccs.campaign_id = ?
          AND ccs.status IN ('queued', 'in_progress')
          AND ccs.next_action_date <= ?
          AND c.unsubscribed = 0
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
        ss.channel,
        ss.step_order,
        ss.template_id,
        ac.contact_is_gdpr AS is_gdpr,
        ac.email,
        ac.linkedin_url,
        ac.email_status
    FROM active_contacts ac
    JOIN sequence_steps ss
      ON ss.campaign_id = ?
     AND ss.step_order = ac.current_step
    WHERE
        -- Email steps: must have valid email
        (ss.channel != 'email' OR ac.email_status = 'valid')
        -- LinkedIn steps: must have a LinkedIn URL
        AND (
            (ss.channel NOT LIKE 'linkedin%')
            OR (ac.linkedin_url IS NOT NULL AND ac.linkedin_url != '')
        )
        -- GDPR filtering on steps
        AND (ss.non_gdpr_only = 0 OR ac.contact_is_gdpr = 0)
        AND (ss.gdpr_only = 0 OR ac.contact_is_gdpr = 1)
    ORDER BY
        CASE WHEN ac.aum_millions IS NULL THEN 1 ELSE 0 END,
        ac.aum_millions DESC
    LIMIT ?
    """

    cursor = conn.execute(query, (campaign_id, target_date, campaign_id, limit))
    rows = cursor.fetchall()

    # Count total steps per contact (accounting for GDPR)
    # We'll compute this per contact in the result set.
    results = []
    for row in rows:
        total_steps = count_steps_for_contact(conn, row["contact_id"], campaign_id)
        results.append(
            {
                "contact_id": row["contact_id"],
                "contact_name": row["contact_name"],
                "company_name": row["company_name"],
                "company_id": row["company_id"],
                "aum_millions": row["aum_millions"],
                "channel": row["channel"],
                "step_order": row["step_order"],
                "total_steps": total_steps,
                "template_id": row["template_id"],
                "is_gdpr": bool(row["is_gdpr"]),
                "email": row["email"],
                "linkedin_url": row["linkedin_url"],
            }
        )

    return results


def get_next_step_for_contact(
    conn: sqlite3.Connection,
    contact_id: int,
    campaign_id: int,
) -> Optional[sqlite3.Row]:
    """Return the sequence_step Row for the contact's next action, or None.

    Looks at the contact's current_step in contact_campaign_status, then finds
    the matching sequence_step. Respects GDPR filtering:
    - Skips steps where non_gdpr_only = 1 if contact is_gdpr = 1
    - Skips steps where gdpr_only = 1 if contact is_gdpr = 0

    If the contact's current_step doesn't match any eligible step (e.g. GDPR
    filtered), this scans forward to find the next eligible step. Returns None
    if all steps are completed or no eligible step remains.
    """
    # Get contact's GDPR status and current step
    row = conn.execute(
        """
        SELECT c.is_gdpr, ccs.current_step
        FROM contact_campaign_status ccs
        JOIN contacts c ON c.id = ccs.contact_id
        WHERE ccs.contact_id = ? AND ccs.campaign_id = ?
        """,
        (contact_id, campaign_id),
    ).fetchone()

    if row is None:
        return None

    is_gdpr = row["is_gdpr"]
    current_step = row["current_step"]

    # Find the matching step, respecting GDPR
    step = conn.execute(
        """
        SELECT * FROM sequence_steps
        WHERE campaign_id = ?
          AND step_order >= ?
          AND (non_gdpr_only = 0 OR ? = 0)
          AND (gdpr_only = 0 OR ? = 1)
        ORDER BY step_order ASC
        LIMIT 1
        """,
        (campaign_id, current_step, is_gdpr, is_gdpr),
    ).fetchone()

    return step


def count_steps_for_contact(
    conn: sqlite3.Connection,
    contact_id: int,
    campaign_id: int,
) -> int:
    """Return the total number of steps this contact would go through.

    Accounts for GDPR filtering: if the contact is GDPR, steps marked
    non_gdpr_only are excluded (and vice versa for gdpr_only).
    """
    # Get contact's GDPR status
    row = conn.execute(
        "SELECT is_gdpr FROM contacts WHERE id = ?",
        (contact_id,),
    ).fetchone()

    if row is None:
        return 0

    is_gdpr = row["is_gdpr"]

    result = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM sequence_steps
        WHERE campaign_id = ?
          AND (non_gdpr_only = 0 OR ? = 0)
          AND (gdpr_only = 0 OR ? = 1)
        """,
        (campaign_id, is_gdpr, is_gdpr),
    ).fetchone()

    return result["cnt"] if result else 0
