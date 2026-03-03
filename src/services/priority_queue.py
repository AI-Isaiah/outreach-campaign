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

from datetime import date
from typing import Optional


def get_daily_queue(
    conn,
    campaign_id: int,
    target_date: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Return the prioritized list of contacts to action today.

    Args:
        conn: database connection
        campaign_id: which campaign to pull the queue for
        target_date: ISO date string (YYYY-MM-DD); defaults to today
        limit: maximum number of results to return

    Returns:
        List of dicts, each representing a contact ready for action, ordered
        by company AUM descending (NULLs last).
    """
    if target_date is None:
        target_date = date.today().isoformat()

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
        WHERE ccs.campaign_id = %s
          AND ccs.status IN ('queued', 'in_progress')
          AND ccs.next_action_date <= %s
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
      ON ss.campaign_id = %s
     AND ss.step_order = ac.current_step
    WHERE
        -- Email steps: must have valid email
        (ss.channel != 'email' OR ac.email_status = 'valid')
        -- LinkedIn steps: must have a LinkedIn URL
        AND (
            (ss.channel NOT LIKE 'linkedin%%')
            OR (ac.linkedin_url IS NOT NULL AND ac.linkedin_url != '')
        )
        -- GDPR filtering on steps
        AND (ss.non_gdpr_only = 0 OR ac.contact_is_gdpr = 0)
        AND (ss.gdpr_only = 0 OR ac.contact_is_gdpr = 1)
    ORDER BY
        CASE WHEN ac.aum_millions IS NULL THEN 1 ELSE 0 END,
        ac.aum_millions DESC
    LIMIT %s
    """

    cursor = conn.cursor()
    cursor.execute(query, (campaign_id, target_date, campaign_id, limit))
    rows = cursor.fetchall()

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
    conn,
    contact_id: int,
    campaign_id: int,
):
    """Return the sequence_step row for the contact's next action, or None.

    Looks at the contact's current_step in contact_campaign_status, then finds
    the matching sequence_step. Respects GDPR filtering.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.is_gdpr, ccs.current_step
        FROM contact_campaign_status ccs
        JOIN contacts c ON c.id = ccs.contact_id
        WHERE ccs.contact_id = %s AND ccs.campaign_id = %s
        """,
        (contact_id, campaign_id),
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
          AND (non_gdpr_only = 0 OR %s = 0)
          AND (gdpr_only = 0 OR %s = 1)
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
) -> int:
    """Return the total number of steps this contact would go through.

    Accounts for GDPR filtering: if the contact is GDPR, steps marked
    non_gdpr_only are excluded (and vice versa for gdpr_only).
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT is_gdpr FROM contacts WHERE id = %s",
        (contact_id,),
    )
    row = cursor.fetchone()

    if row is None:
        return 0

    is_gdpr = row["is_gdpr"]

    cursor.execute(
        """
        SELECT COUNT(*) AS cnt FROM sequence_steps
        WHERE campaign_id = %s
          AND (non_gdpr_only = 0 OR %s = 0)
          AND (gdpr_only = 0 OR %s = 1)
        """,
        (campaign_id, is_gdpr, is_gdpr),
    )
    result = cursor.fetchone()

    return result["cnt"] if result else 0
