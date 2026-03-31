"""Enrollment, sequence-step, and contact-campaign-status CRUD (extracted from campaigns.py).

Functions for enrolling contacts in campaigns, managing sequence steps,
and tracking per-contact campaign status / message drafts / template usage.
"""

from __future__ import annotations

import psycopg2
import psycopg2.extras
from typing import Callable, Optional

from psycopg2.extensions import connection as PgConnection

from src.models.database import get_cursor

_SENTINEL = object()  # distinguishes "not passed" from "passed as None"


# ---------------------------------------------------------------------------
# Sequence Steps
# ---------------------------------------------------------------------------

def add_sequence_step(
    conn: PgConnection,
    campaign_id: int,
    step_order: int,
    channel: str,
    template_id: Optional[int] = None,
    delay_days: int = 0,
    gdpr_only: bool = False,
    non_gdpr_only: bool = False,
    *,
    user_id: int,
) -> int:
    """Add a sequence step to a campaign and return its id.

    Verifies the campaign belongs to the user before inserting.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT id FROM campaigns WHERE id = %s AND user_id = %s",
            (campaign_id, user_id),
        )
        if cursor.fetchone() is None:
            raise PermissionError(f"Campaign {campaign_id} not found or not owned by user {user_id}")
        cursor.execute(
            """INSERT INTO sequence_steps
               (campaign_id, step_order, channel, template_id, delay_days, gdpr_only, non_gdpr_only)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                campaign_id,
                step_order,
                channel,
                template_id,
                delay_days,
                gdpr_only,
                non_gdpr_only,
            ),
        )
        row = cursor.fetchone()
        conn.commit()
        return row["id"]


# ---------------------------------------------------------------------------
# Sequence Steps (query)
# ---------------------------------------------------------------------------

def get_sequence_steps(conn: PgConnection, campaign_id: int, *, user_id: int) -> list[dict]:
    """Return all steps for a campaign, ordered by step_order.

    Joins to campaigns table to verify ownership.
    Includes template subject and body via LEFT JOIN.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            """SELECT ss.*, t.subject AS template_subject, t.body_template AS template_body
               FROM sequence_steps ss
               JOIN campaigns c ON c.id = ss.campaign_id
               LEFT JOIN templates t ON ss.template_id = t.id
               WHERE ss.campaign_id = %s AND c.user_id = %s
               ORDER BY ss.step_order""",
            (campaign_id, user_id),
        )
        return cursor.fetchall()


# ---------------------------------------------------------------------------
# Contact Campaign Enrollment / Status
# ---------------------------------------------------------------------------

def enroll_contact(
    conn: PgConnection,
    contact_id: int,
    campaign_id: int,
    variant: Optional[str] = None,
    next_action_date: Optional[str] = None,
    first_step_stable_id: Optional[str] = None,
    *,
    user_id: int,
) -> Optional[int]:
    """Enroll a contact in a campaign. Returns enrollment id, or None if already enrolled.

    Verifies the campaign belongs to the user before enrolling.
    Auto-populates current_step_id from the campaign's first sequence step
    when first_step_stable_id is not provided.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT id FROM campaigns WHERE id = %s AND user_id = %s",
            (campaign_id, user_id),
        )
        if cursor.fetchone() is None:
            raise PermissionError(f"Campaign {campaign_id} not found or not owned by user {user_id}")

        # Auto-populate from first sequence step when not provided
        if first_step_stable_id is None:
            cursor.execute(
                "SELECT stable_id FROM sequence_steps WHERE campaign_id = %s AND step_order = 1",
                (campaign_id,),
            )
            row = cursor.fetchone()
            if row:
                first_step_stable_id = str(row["stable_id"])

        try:
            cursor.execute(
                """INSERT INTO contact_campaign_status
                   (contact_id, campaign_id, current_step, current_step_id, assigned_variant, next_action_date)
                   VALUES (%s, %s, 1, %s, %s, %s) RETURNING id""",
                (contact_id, campaign_id, first_step_stable_id, variant, next_action_date),
            )
            row = cursor.fetchone()
            conn.commit()
            return row["id"]
        except psycopg2.IntegrityError:
            conn.rollback()
            return None


def bulk_enroll_contacts(
    conn: PgConnection,
    campaign_id: int,
    contact_ids: list,
    variant_assigner: Optional[Callable] = None,
    first_step_stable_id: Optional[str] = None,
    *,
    user_id: int,
) -> int:
    """Enroll multiple contacts in a campaign.

    Uses ``psycopg2.extras.execute_values`` for a single INSERT round-trip
    instead of one INSERT per contact.

    Verifies the campaign belongs to the user before enrolling.

    Args:
        conn: database connection
        campaign_id: campaign to enroll contacts in
        contact_ids: list of contact ids to enroll
        variant_assigner: optional callable(contact_id) -> str for variant assignment
        first_step_stable_id: optional stable_id of the first sequence step
        user_id: owner of the campaign (keyword-only)

    Returns:
        count of newly enrolled contacts (skips already enrolled)
    """
    if not contact_ids:
        return 0
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT id FROM campaigns WHERE id = %s AND user_id = %s",
            (campaign_id, user_id),
        )
        if cursor.fetchone() is None:
            raise PermissionError(f"Campaign {campaign_id} not found or not owned by user {user_id}")

        placeholders = ",".join("%s" for _ in contact_ids)
        cursor.execute(
            f"SELECT contact_id FROM contact_campaign_status "
            f"WHERE campaign_id = %s AND contact_id IN ({placeholders})",
            [campaign_id] + list(contact_ids),
        )
        already_enrolled = {row["contact_id"] for row in cursor.fetchall()}

        # Pre-compute all rows to insert
        rows_to_insert = []
        for contact_id in contact_ids:
            if contact_id in already_enrolled:
                continue
            variant = variant_assigner(contact_id) if variant_assigner else None
            rows_to_insert.append((contact_id, campaign_id, 1, first_step_stable_id, variant))

        if rows_to_insert:
            psycopg2.extras.execute_values(
                cursor,
                """INSERT INTO contact_campaign_status
                   (contact_id, campaign_id, current_step, current_step_id, assigned_variant)
                   VALUES %s""",
                rows_to_insert,
            )

        conn.commit()
        return len(rows_to_insert)


def get_contact_campaign_status(
    conn: PgConnection,
    contact_id: int,
    campaign_id: int,
    *,
    user_id: int,
) -> dict | None:
    """Return the enrollment/status row for a contact in a campaign, or None.

    Joins to campaigns table to verify ownership.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            """SELECT ccs.* FROM contact_campaign_status ccs
               JOIN campaigns c ON c.id = ccs.campaign_id
               WHERE ccs.contact_id = %s AND ccs.campaign_id = %s AND c.user_id = %s""",
            (contact_id, campaign_id, user_id),
        )
        return cursor.fetchone()


def update_contact_campaign_status(
    conn: PgConnection,
    contact_id: int,
    campaign_id: int,
    status: Optional[str] = None,
    current_step: Optional[int] = None,
    current_step_id: Optional[str] = None,  # UUID stable_id reference
    next_action_date: Optional[str] = None,
    channel_override=_SENTINEL,
    *,
    user_id: int,
) -> None:
    """Update fields on a contact's campaign status row.

    Only supplied (non-None) fields are updated. updated_at is always refreshed.
    Verifies the campaign belongs to the user before updating.

    channel_override uses a sentinel so that passing None explicitly clears the
    column (sets it to NULL), while omitting the argument leaves it unchanged.
    """
    fields = []
    params: list = []

    if status is not None:
        fields.append("status = %s")
        params.append(status)
    if current_step is not None:
        fields.append("current_step = %s")
        params.append(current_step)
        # Reset send-cycle fields so the contact re-enters the approval queue
        fields.append("sent_at = NULL")
        fields.append("approved_at = NULL")
        fields.append("scheduled_for = NULL")
        # Auto-resolve current_step_id when not explicitly provided
        if current_step_id is None:
            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT stable_id FROM sequence_steps WHERE campaign_id = %s AND step_order = %s",
                    (campaign_id, current_step),
                )
                row = cur.fetchone()
                if row:
                    current_step_id = str(row["stable_id"])
    if current_step_id is not None:
        fields.append("current_step_id = %s")
        params.append(current_step_id)
    if next_action_date is not None:
        fields.append("next_action_date = %s")
        params.append(next_action_date)
    if channel_override is not _SENTINEL:
        fields.append("channel_override = %s")
        params.append(channel_override)

    if not fields:
        return

    fields.append("updated_at = NOW()")

    query = (
        f"UPDATE contact_campaign_status ccs SET {', '.join(fields)} "
        f"FROM campaigns c "
        f"WHERE ccs.campaign_id = c.id "
        f"AND ccs.contact_id = %s AND ccs.campaign_id = %s AND c.user_id = %s"
    )
    params.extend([contact_id, campaign_id, user_id])
    with get_cursor(conn) as cursor:
        cursor.execute(query, params)
        conn.commit()


# ---------------------------------------------------------------------------
# Message drafts (AI-generated)
# ---------------------------------------------------------------------------

def get_message_draft(
    conn: PgConnection,
    contact_id: int,
    campaign_id: int,
    step_order: int,
    *,
    user_id: int,
) -> dict | None:
    """Fetch an existing AI-generated message draft, or None."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            """SELECT id, contact_id, campaign_id, step_order, draft_subject,
                      draft_text, channel, model, generated_at, edited_at,
                      research_id, user_id
               FROM message_drafts
               WHERE contact_id = %s AND campaign_id = %s
                     AND step_order = %s AND user_id = %s""",
            (contact_id, campaign_id, step_order, user_id),
        )
        return cursor.fetchone()


# ---------------------------------------------------------------------------
# Template usage tracking
# ---------------------------------------------------------------------------

def record_template_usage(
    conn: PgConnection,
    contact_id: int,
    campaign_id: int,
    template_id: int,
    channel: str,
    *,
    user_id: int,
) -> None:
    """Record that a template was sent to a contact.

    Inserts into ``contact_template_history`` when an email is sent.
    The ``outcome`` column stays NULL until a reply is confirmed.
    Uses ON CONFLICT DO NOTHING for idempotency (same contact+campaign+template).

    Does NOT commit — callers must manage the transaction boundary.
    """
    if not template_id:
        return  # Guard: old Gmail drafts may have NULL template_id
    with get_cursor(conn) as cursor:
        cursor.execute(
            """INSERT INTO contact_template_history
                   (contact_id, campaign_id, template_id, channel, sent_at, user_id)
               VALUES (%s, %s, %s, %s, NOW(), %s)
               ON CONFLICT (contact_id, campaign_id, template_id) DO NOTHING""",
            (contact_id, campaign_id, template_id, channel, user_id),
        )
