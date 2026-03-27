"""Shared sequence step utilities for campaign advancement.

Provides common functions used across multiple modules that handle
sequence progression and step navigation.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


def find_previous_step(steps: list, current_step_order: int) -> Optional[dict]:
    """Find the previous sequence step before the given step_order.

    Args:
        steps: list of step dicts, sorted by step_order
        current_step_order: the current step_order value

    Returns:
        The previous step dict, or None if at the first step.
    """
    prev = None
    for step in steps:
        if step["step_order"] >= current_step_order:
            return prev
        prev = step
    return prev


def find_step_by_stable_id(steps: list, stable_id: str) -> Optional[dict]:
    """Find a sequence step by its stable_id.

    Args:
        steps: list of step dicts
        stable_id: the UUID stable_id to find

    Returns:
        The step dict, or None if not found.
    """
    for step in steps:
        if str(step.get("stable_id", "")) == str(stable_id):
            return step
    return None


def find_next_step(steps: list, current_step_order: int) -> Optional[dict]:
    """Find the next sequence step after the given step_order.

    Args:
        steps: list of step dicts, sorted by step_order
        current_step_order: the current step_order value

    Returns:
        The next step dict, or None if there is no next step.
    """
    for step in steps:
        if step["step_order"] > current_step_order:
            return step
    return None


def advance_to_next_step(
    conn,
    contact_id: int,
    campaign_id: int,
    current_step_order: int,
    steps: list,
    *,
    user_id: int,
    status: Optional[str] = None,
) -> Optional[dict]:
    """Advance a contact to the next sequence step, setting next_action_date.

    Sets next_action_date = today + next_step.delay_days. The underlying
    update_contact_campaign_status call clears approved_at, scheduled_for,
    and sent_at so the contact re-enters the approval queue.

    Returns the next step dict if advanced, None if no next step exists.
    """
    from src.models.enrollment import update_contact_campaign_status

    next_step = find_next_step(steps, current_step_order)
    if not next_step:
        return None
    delay = next_step.get("delay_days", 0) or 0
    next_date = (date.today() + timedelta(days=delay)).isoformat()
    kwargs: dict = dict(
        current_step=next_step["step_order"],
        current_step_id=str(next_step["stable_id"]),
        next_action_date=next_date,
        user_id=user_id,
    )
    if status is not None:
        kwargs["status"] = status
    update_contact_campaign_status(conn, contact_id, campaign_id, **kwargs)
    return next_step
