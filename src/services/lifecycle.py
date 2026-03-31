"""Auto-advance contact lifecycle stage based on interactions.

Lifecycle progression:
  cold → contacted → engaged → nurturing → opportunity → client
                                                        ↗
  (churned is terminal, set manually)

Triggers:
  - Email sent / LinkedIn connect sent → contacted (if cold)
  - Positive reply received → engaged (if contacted)
  - Factsheet / materials sent (conversation logged) → nurturing (if contacted or engaged)
  - Meeting / call booked → opportunity (if not already opportunity or client)
  - Deal won → client
"""

from __future__ import annotations

import logging
from typing import Optional

from src.models.database import get_cursor

logger = logging.getLogger(__name__)

# Stage ordering for "only advance, never regress" logic
STAGE_ORDER = {
    "cold": 0,
    "contacted": 1,
    "engaged": 2,
    "nurturing": 3,
    "opportunity": 4,
    "client": 5,
    "churned": -1,  # terminal, never auto-changed
}


def _advance_lifecycle(conn, contact_id: int, new_stage: str, *, user_id: int) -> Optional[str]:
    """Advance lifecycle if new_stage is higher than current. Returns new stage or None."""
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT lifecycle_stage FROM contacts WHERE id = %s AND user_id = %s",
            (contact_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None

        current = row["lifecycle_stage"]
        current_order = STAGE_ORDER.get(current, 0)
        new_order = STAGE_ORDER.get(new_stage, 0)

        # Never regress, never touch churned
        if current == "churned" or new_order <= current_order:
            return None

        cur.execute(
            "UPDATE contacts SET lifecycle_stage = %s WHERE id = %s AND user_id = %s",
            (new_stage, contact_id, user_id),
        )
        conn.commit()
        logger.info(
            "Lifecycle auto-advanced: contact %s %s → %s",
            contact_id, current, new_stage,
        )
        return new_stage


def on_email_sent(conn, contact_id: int, *, user_id: int) -> Optional[str]:
    """Called after an email or LinkedIn connect is sent."""
    return _advance_lifecycle(conn, contact_id, "contacted", user_id=user_id)


def on_positive_reply(conn, contact_id: int, *, user_id: int) -> Optional[str]:
    """Called when a positive reply is detected or logged."""
    return _advance_lifecycle(conn, contact_id, "engaged", user_id=user_id)


def on_materials_sent(conn, contact_id: int, *, user_id: int) -> Optional[str]:
    """Called when a conversation is logged (factsheet, materials, follow-up)."""
    return _advance_lifecycle(conn, contact_id, "nurturing", user_id=user_id)


def on_meeting_booked(conn, contact_id: int, *, user_id: int) -> Optional[str]:
    """Called when a call/meeting is booked."""
    return _advance_lifecycle(conn, contact_id, "opportunity", user_id=user_id)


def on_deal_won(conn, contact_id: int, *, user_id: int) -> Optional[str]:
    """Called when a deal is marked as won."""
    return _advance_lifecycle(conn, contact_id, "client", user_id=user_id)
