"""Manual LinkedIn action completion for the web dashboard.

Replaces the automated Expandi/Linked Helper import flow. The operator
manually performs LinkedIn actions (connect, message, engage) and clicks
"Mark as Done" in the web UI. This module handles the step-advancement logic.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from src.models.campaigns import (
    get_contact_campaign_status,
    get_sequence_steps,
    log_event,
    update_contact_campaign_status,
)


def complete_linkedin_action(
    conn,
    contact_id: int,
    campaign_id: int,
    action_type: str,
) -> dict:
    """Mark a manual LinkedIn action as done and advance the sequence.

    Replicates the step-advancement logic from import_expandi.py but for
    single manual actions triggered from the web UI.

    Args:
        conn: database connection
        contact_id: the contact whose action was completed
        campaign_id: the campaign context
        action_type: one of 'connect', 'message', 'engage', 'insight', 'final'

    Returns:
        Dict with keys: success, event_type, advanced, next_step, error

    Raises:
        ValueError: if action_type is invalid or contact is not enrolled.
    """
    valid_actions = {
        "connect": ("linkedin_connect", "linkedin_connect_done"),
        "message": ("linkedin_message", "linkedin_message_done"),
        "engage": ("linkedin_engage", "linkedin_engage_done"),
        "insight": ("linkedin_message", "linkedin_insight_done"),
        "final": ("linkedin_message", "linkedin_final_done"),
    }

    if action_type not in valid_actions:
        raise ValueError(f"Invalid action_type: {action_type}. Must be one of: {list(valid_actions.keys())}")

    expected_channel, event_type = valid_actions[action_type]

    # Get enrollment status
    ccs = get_contact_campaign_status(conn, contact_id, campaign_id)
    if ccs is None:
        raise ValueError(f"Contact {contact_id} is not enrolled in campaign {campaign_id}")

    current_step_order = ccs["current_step"]

    # Get sequence steps
    steps = get_sequence_steps(conn, campaign_id)
    step_by_order = {step["step_order"]: step for step in steps}
    current_step = step_by_order.get(current_step_order)

    if current_step is None:
        raise ValueError(f"Current step {current_step_order} not found in campaign sequence")

    # Verify current step is a LinkedIn channel
    if not current_step["channel"].startswith("linkedin"):
        raise ValueError(
            f"Current step is '{current_step['channel']}', not a LinkedIn step. "
            f"Cannot complete LinkedIn action."
        )

    # If status is queued, transition to in_progress first
    if ccs["status"] == "queued":
        update_contact_campaign_status(
            conn, contact_id, campaign_id, status="in_progress"
        )

    # Log the event
    log_event(conn, contact_id, event_type, campaign_id=campaign_id)

    # Find next step and advance
    next_step = _find_next_step(steps, current_step_order)
    advanced = False

    if next_step:
        next_date = (date.today() + timedelta(days=next_step["delay_days"])).isoformat()
        update_contact_campaign_status(
            conn, contact_id, campaign_id,
            status="in_progress",
            current_step=next_step["step_order"],
            next_action_date=next_date,
        )
        advanced = True
        return {
            "success": True,
            "event_type": event_type,
            "advanced": True,
            "next_step": next_step["step_order"],
            "next_date": next_date,
        }
    else:
        # No more steps — mark as no_response (triggers auto-activation)
        update_contact_campaign_status(
            conn, contact_id, campaign_id,
            status="no_response",
        )
        log_event(conn, contact_id, "status_no_response", campaign_id=campaign_id)
        # Auto-activate next contact at company
        from src.services.state_machine import _activate_next_contact
        _activate_next_contact(conn, contact_id, campaign_id)

        return {
            "success": True,
            "event_type": event_type,
            "advanced": False,
            "next_step": None,
            "next_date": None,
            "completed_sequence": True,
        }


def _find_next_step(steps: list, current_step_order: int) -> Optional[dict]:
    """Find the next sequence step after the given step_order."""
    for step in steps:
        if step["step_order"] > current_step_order:
            return step
    return None
