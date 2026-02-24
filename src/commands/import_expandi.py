"""Import Expandi results CSV and update contact statuses."""

from __future__ import annotations

import csv
import sqlite3
from datetime import date, timedelta
from typing import Optional
from urllib.parse import urlparse


def _normalize_linkedin_url(url: str) -> str:
    """Normalize a LinkedIn URL for matching.

    Lowercases the URL, strips trailing slashes, and removes query parameters.
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


def import_expandi_results(
    conn: sqlite3.Connection,
    file_path: str,
    campaign_name: str,
) -> dict:
    """Import Expandi results CSV and update contact statuses.

    Expected CSV columns from Expandi export:
    - profile_link (LinkedIn URL)
    - status (connected, pending, message_sent, etc.)

    For each row:
    - Match contact by normalized LinkedIn URL
    - Log appropriate event
    - If status is 'connected' and current step is linkedin_connect:
        advance current_step to next step, set next_action_date
    - If status is 'message_sent' and current step is linkedin_message:
        advance current_step to next step, set next_action_date

    Args:
        conn: database connection (must have row_factory = sqlite3.Row)
        file_path: path to the Expandi results CSV
        campaign_name: name of the campaign to update

    Returns:
        Dict with keys: matched, unmatched, advanced
    """
    from src.models.campaigns import (
        get_campaign_by_name,
        get_contact_campaign_status,
        get_sequence_steps,
        log_event,
        update_contact_campaign_status,
    )

    campaign = get_campaign_by_name(conn, campaign_name)
    if not campaign:
        raise ValueError(f"Campaign not found: {campaign_name}")

    campaign_id = campaign["id"]
    steps = get_sequence_steps(conn, campaign_id)
    # Build a lookup from step_order -> step row
    step_by_order = {step["step_order"]: step for step in steps}

    result = {"matched": 0, "unmatched": 0, "advanced": 0}

    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            profile_link = row.get("profile_link", "").strip()
            status = row.get("status", "").strip().lower()

            if not profile_link:
                result["unmatched"] += 1
                continue

            normalized_url = _normalize_linkedin_url(profile_link)

            # Find the contact by normalized LinkedIn URL
            contact_row = conn.execute(
                "SELECT id FROM contacts WHERE linkedin_url_normalized = ?",
                (normalized_url,),
            ).fetchone()

            if contact_row is None:
                result["unmatched"] += 1
                continue

            contact_id = contact_row["id"]
            result["matched"] += 1

            # Get the contact's campaign enrollment
            ccs = get_contact_campaign_status(conn, contact_id, campaign_id)
            if ccs is None:
                # Contact exists but isn't enrolled in this campaign
                continue

            current_step_order = ccs["current_step"]
            current_step = step_by_order.get(current_step_order)

            # Log the event regardless
            log_event(
                conn,
                contact_id,
                f"expandi_{status}",
                campaign_id=campaign_id,
            )

            # Determine if we should advance
            should_advance = False
            if (
                status == "connected"
                and current_step
                and current_step["channel"] == "linkedin_connect"
            ):
                should_advance = True
            elif (
                status == "message_sent"
                and current_step
                and current_step["channel"] == "linkedin_message"
            ):
                should_advance = True

            if should_advance:
                # Find the next step_order
                next_step = _find_next_step(steps, current_step_order)
                if next_step:
                    next_date = (
                        date.today() + timedelta(days=next_step["delay_days"])
                    ).isoformat()
                    update_contact_campaign_status(
                        conn,
                        contact_id,
                        campaign_id,
                        status="in_progress",
                        current_step=next_step["step_order"],
                        next_action_date=next_date,
                    )
                else:
                    # No more steps: mark as completed
                    update_contact_campaign_status(
                        conn,
                        contact_id,
                        campaign_id,
                        status="no_response",
                    )
                result["advanced"] += 1

    return result


def _find_next_step(steps: list, current_step_order: int) -> Optional[dict]:
    """Find the next sequence step after the given step_order.

    Args:
        steps: list of step rows, sorted by step_order
        current_step_order: the current step_order value

    Returns:
        The next step dict, or None if there is no next step.
    """
    for step in steps:
        if step["step_order"] > current_step_order:
            return step
    return None
