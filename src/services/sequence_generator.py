"""Generate outreach sequence steps based on touchpoints and channels.

Pure function — no database or external dependencies.
"""

from __future__ import annotations


def generate_sequence(touchpoints: int, channels: list[str]) -> list[dict]:
    """Generate a multi-step outreach sequence.

    Args:
        touchpoints: Number of steps (1-10)
        channels: List of channels ("email", "linkedin")

    Returns:
        List of step dicts with step_order, channel, delay_days, template_id.

    Raises:
        ValueError: If touchpoints < 1 or channels empty/invalid.
    """
    if touchpoints < 1:
        raise ValueError("touchpoints must be >= 1")
    if not channels:
        raise ValueError("channels must not be empty")

    valid_channels = {"email", "linkedin"}
    for ch in channels:
        if ch not in valid_channels:
            raise ValueError(f"Invalid channel: {ch}. Must be one of {valid_channels}")

    steps: list[dict] = []
    has_email = "email" in channels
    has_linkedin = "linkedin" in channels
    single_channel = len(channels) == 1
    linkedin_toggle = False  # alternates connect / message

    for i in range(touchpoints):
        # Determine channel
        if single_channel:
            if channels[0] == "linkedin":
                channel = "linkedin_connect" if not linkedin_toggle else "linkedin_message"
                linkedin_toggle = not linkedin_toggle
            else:
                channel = "email"
        else:
            # Alternate: even indices = first channel, odd = second
            is_email_turn = (i % 2 == 0) if has_email else (i % 2 != 0)
            if is_email_turn:
                channel = "email"
            else:
                channel = "linkedin_connect" if not linkedin_toggle else "linkedin_message"
                linkedin_toggle = not linkedin_toggle

        # Determine delay
        if i == 0:
            delay = 0
        elif single_channel:
            # Increasing gaps for single channel: 3+i minimum
            if i <= 2:
                delay = steps[i - 1]["delay_days"] + 3 + i
            else:
                delay = steps[i - 1]["delay_days"] + 4 + i
        else:
            # Cross-channel: min 2 days, same-channel: min 3 days
            prev_ch = steps[i - 1]["channel"]
            same_type = (
                (channel == "email" and prev_ch == "email")
                or (channel != "email" and prev_ch != "email")
            )
            min_gap = 3 if same_type else 2
            backoff = i // 3  # gradually increase gaps
            delay = steps[i - 1]["delay_days"] + min_gap + backoff

        steps.append(
            {
                "step_order": i + 1,
                "channel": channel,
                "delay_days": delay,
                "template_id": None,
            }
        )

    return steps
