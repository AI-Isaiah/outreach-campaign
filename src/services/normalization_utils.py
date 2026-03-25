"""Shared normalization utilities for contact data.

Provides common normalization functions used across multiple modules
for standardizing emails, LinkedIn URLs, company names, and contact names.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse


def normalize_email(email: Optional[str]) -> Optional[str]:
    """Lowercase, strip whitespace, validate contains ``@``.

    Returns None if the input is empty or invalid.
    """
    if email is None:
        return None
    email = email.strip().lower()
    if not email or "@" not in email:
        return None
    return email


_COMPANY_SUFFIXES = re.compile(
    r"\b(inc|llc|ltd|lp|corp|co|fund|capital|ventures|partners|"
    r"group|holdings|management|advisors?|investments?|limited)\.?\s*$"
)


def normalize_company_name(name: str) -> str:
    """Normalize a company name for matching.

    Lowercases, strips common suffixes (Inc, LLC, Ltd, Capital, etc.),
    normalizes '&' to 'and', and collapses whitespace.
    """
    if not name:
        return name
    name = re.sub(r"\s+", " ", name.strip().lower())
    name = _COMPANY_SUFFIXES.sub("", name).strip()
    name = name.replace("&", "and")
    return re.sub(r"\s+", " ", name).strip()


def split_name(full_name: str) -> tuple[str, str]:
    """Split a full name into (first_name, last_name).

    Uses split(None, 1): first token = first name, remainder = last name.
    """
    parts = full_name.strip().split(None, 1)
    first = parts[0] if parts else full_name.strip()
    last = parts[1] if len(parts) > 1 else ""
    return first, last


def normalize_linkedin_url(url: str) -> str:
    """Normalize a LinkedIn URL for matching.

    Lowercases the URL, strips trailing slashes, and removes query parameters.

    Args:
        url: the LinkedIn URL to normalize

    Returns:
        Normalized URL string, or empty string if invalid input.
    """
    if not url or not url.strip():
        return ""
    url = url.lower().strip()
    # Parse and reconstruct without query params / fragment
    parsed = urlparse(url)
    # If there's no scheme or netloc, this isn't a valid URL
    if not parsed.scheme or not parsed.netloc:
        return ""
    # Reconstruct with just scheme + netloc + path
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    # Strip trailing slashes
    normalized = normalized.rstrip("/")
    return normalized
