"""Import LinkedIn automation tool results CSV and update contact statuses.

Supports CSV exports from:
- Expandi (columns: profile_link, status)
- Linked Helper (columns: Profile url, Connection status / various)
- Any tool with a LinkedIn URL column

The importer auto-detects the CSV format by inspecting column headers.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from typing import Optional

from src.services.normalization_utils import normalize_linkedin_url
from src.services.sequence_utils import find_next_step
from src.models.database import get_cursor


def _detect_csv_format(fieldnames: list[str]) -> dict:
    """Auto-detect the CSV format by inspecting column headers.

    Returns a dict with keys:
        url_column: name of the LinkedIn URL column
        status_column: name of the status column (or None)
        source: detected source tool name

    Supports: Expandi, Linked Helper, generic (any column containing 'url' or 'link')
    """
    lower_fields = {f.lower().strip(): f for f in fieldnames}

    # Expandi format
    if "profile_link" in lower_fields:
        return {
            "url_column": lower_fields["profile_link"],
            "status_column": lower_fields.get("status"),
            "source": "expandi",
        }

    # Linked Helper format
    if "profile url" in lower_fields:
        return {
            "url_column": lower_fields["profile url"],
            "status_column": lower_fields.get("connection status"),
            "source": "linked_helper",
        }

    # Generic fallback: look for any column containing 'linkedin' or 'profile' and 'url'/'link'
    for key, original in lower_fields.items():
        if ("linkedin" in key or "profile" in key) and ("url" in key or "link" in key):
            return {
                "url_column": original,
                "status_column": lower_fields.get("status"),
                "source": "generic",
            }

    raise ValueError(
        f"Could not detect CSV format. Expected columns like 'profile_link' (Expandi) "
        f"or 'Profile url' (Linked Helper). Found: {fieldnames}"
    )


def _normalize_status(raw_status: str, source: str) -> str:
    """Normalize status values from different tools to our internal format.

    Internal statuses: connected, pending, message_sent, message_replied

    Args:
        raw_status: the raw status string from the CSV
        source: the detected source tool (expandi, linked_helper, generic)

    Returns:
        Normalized status string.
    """
    s = raw_status.lower().strip()

    if source == "linked_helper":
        # Linked Helper uses descriptive statuses
        if s in ("connected", "accepted", "1st"):
            return "connected"
        if s in ("pending", "sent", "invitation sent"):
            return "pending"
        if s in ("message sent", "messaged"):
            return "message_sent"
        if s in ("replied", "message replied"):
            return "message_replied"

    # Expandi / generic — already uses our format mostly
    if s in ("connected", "accepted"):
        return "connected"
    if s in ("message_sent", "message sent"):
        return "message_sent"
    if s in ("replied", "message_replied"):
        return "message_replied"

    return s  # pass through unknown statuses


def import_expandi_results(
    conn,
    file_path: str,
    campaign_name: str,
) -> dict:
    """Import LinkedIn automation results CSV and update contact statuses.

    Auto-detects CSV format (Expandi, Linked Helper, or generic).
    Matches contacts by normalized LinkedIn URL and advances them
    through the campaign sequence.

    For each row:
    - Match contact by normalized LinkedIn URL
    - Log appropriate event
    - If status is 'connected' and current step is linkedin_connect:
        advance current_step to next step, set next_action_date
    - If status is 'message_sent' and current step is linkedin_message:
        advance current_step to next step, set next_action_date

    Args:
        conn: database connection (must have row_factory = sqlite3.Row)
        file_path: path to the results CSV
        campaign_name: name of the campaign to update

    Returns:
        Dict with keys: matched, unmatched, advanced, source
    """
    from src.models.campaigns import (
        get_campaign_by_name,
        get_contact_campaign_status,
        get_sequence_steps,
        log_event,
        update_contact_campaign_status,
    )

    campaign = get_campaign_by_name(conn, campaign_name, user_id=1)
    if not campaign:
        raise ValueError(f"Campaign not found: {campaign_name}")

    campaign_id = campaign["id"]
    steps = get_sequence_steps(conn, campaign_id, user_id=1)
    # Build a lookup from step_order -> step row
    step_by_order = {step["step_order"]: step for step in steps}

    result = {"matched": 0, "unmatched": 0, "advanced": 0, "source": "unknown"}

    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fmt = _detect_csv_format(reader.fieldnames or [])
        result["source"] = fmt["source"]

        for row in reader:
            profile_link = row.get(fmt["url_column"], "").strip()
            raw_status = row.get(fmt["status_column"], "") if fmt["status_column"] else ""
            status = _normalize_status(raw_status.strip(), fmt["source"])

            if not profile_link:
                result["unmatched"] += 1
                continue

            normalized_url = normalize_linkedin_url(profile_link)

            # Find the contact by normalized LinkedIn URL
            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT id FROM contacts WHERE linkedin_url_normalized = %s",
                    (normalized_url,),
                )
                contact_row = cur.fetchone()

            if contact_row is None:
                result["unmatched"] += 1
                continue

            contact_id = contact_row["id"]
            result["matched"] += 1

            # Get the contact's campaign enrollment
            ccs = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=1)
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
                user_id=1,
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
                next_step = find_next_step(steps, current_step_order)
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
                        user_id=1,
                    )
                else:
                    # No more steps: mark as completed
                    update_contact_campaign_status(
                        conn,
                        contact_id,
                        campaign_id,
                        status="no_response",
                        user_id=1,
                    )
                result["advanced"] += 1

    conn.commit()
    return result
