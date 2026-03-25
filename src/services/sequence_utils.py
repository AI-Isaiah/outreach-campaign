"""Shared sequence step utilities for campaign advancement.

Provides common functions used across multiple modules that handle
sequence progression and step navigation.
"""

from __future__ import annotations

from typing import Optional


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
