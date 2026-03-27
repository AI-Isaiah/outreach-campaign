"""Shared sequence step utilities for campaign advancement.

Provides common functions used across multiple modules that handle
sequence progression and step navigation.
"""

from __future__ import annotations

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
