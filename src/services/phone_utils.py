"""Phone number normalization to E.164 format."""

from __future__ import annotations

import re


def normalize_phone(phone: str) -> str | None:
    """Normalize a phone number to E.164 format.

    Strips formatting characters (spaces, dashes, dots, parens) and ensures
    the number starts with +. Returns None if the input is empty or clearly
    not a phone number.

    Examples:
        "+1 (555) 123-4567" -> "+15551234567"
        "00442071234567"    -> "+442071234567"
        "555-123-4567"      -> "+15551234567" (assumes US if no country code)
    """
    if not phone or not phone.strip():
        return None

    # Strip all non-digit and non-plus characters
    cleaned = re.sub(r"[^\d+]", "", phone.strip())

    if not cleaned:
        return None

    # Handle leading 00 (international prefix)
    if cleaned.startswith("00") and not cleaned.startswith("+"):
        cleaned = "+" + cleaned[2:]

    # Ensure + prefix
    if not cleaned.startswith("+"):
        # Assume US/Canada (+1) if 10 digits
        digits = cleaned.lstrip("+")
        if len(digits) == 10:
            cleaned = "+1" + digits
        elif len(digits) == 11 and digits.startswith("1"):
            cleaned = "+" + digits
        else:
            # Best effort: prepend +
            cleaned = "+" + digits

    # Validate: E.164 numbers are 8-15 digits after the +
    digits_only = cleaned.lstrip("+")
    if not digits_only.isdigit() or len(digits_only) < 7 or len(digits_only) > 15:
        return None

    return cleaned
