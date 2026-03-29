"""Export LinkedIn-action contacts to Expandi CSV format."""

from __future__ import annotations

import csv
import os
from datetime import date
from typing import Optional

from src.models.database import get_cursor


def export_expandi_csv(
    conn,
    campaign_name: str,
    target_date: Optional[str] = None,
    output_dir: str = "data/exports",
) -> str:
    """Export today's LinkedIn actions to Expandi CSV format.

    Only includes contacts whose current step is a LinkedIn action
    (linkedin_connect or linkedin_message).

    CSV columns: profile_link, email, first_name, last_name, company_name

    Args:
        conn: database connection (must have row_factory = sqlite3.Row)
        campaign_name: name of the campaign to export from
        target_date: ISO date string (YYYY-MM-DD); defaults to today
        output_dir: directory to write the CSV file into

    Returns:
        The path to the exported CSV file.

    Raises:
        ValueError: if the campaign is not found.
    """
    from src.models.campaigns import get_campaign_by_name
    from src.services.priority_queue import get_daily_queue

    campaign = get_campaign_by_name(conn, campaign_name, user_id=1)
    if not campaign:
        raise ValueError(f"Campaign not found: {campaign_name}")

    if target_date is None:
        target_date = date.today().isoformat()

    # Get the full daily queue (high limit to capture all LinkedIn items)
    queue = get_daily_queue(conn, campaign["id"], target_date=target_date, limit=9999, user_id=1)

    # Filter to LinkedIn-only actions
    linkedin_items = [
        item for item in queue
        if item["channel"] in ("linkedin_connect", "linkedin_message")
    ]

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    filename = f"expandi_{target_date}.csv"
    filepath = os.path.join(output_dir, filename)

    # Resolve contact first_name and last_name from the database
    # (the queue returns contact_name as a combined string)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["profile_link", "email", "first_name", "last_name", "company_name"])

        for item in linkedin_items:
            contact_id = item["contact_id"]
            with get_cursor(conn) as cursor:
                cursor.execute(
                    "SELECT first_name, last_name, email FROM contacts WHERE id = %s",
                    (contact_id,),
                )
                row = cursor.fetchone()

            if row is None:
                continue

            writer.writerow([
                item.get("linkedin_url", ""),
                row["email"] or "",
                row["first_name"] or "",
                row["last_name"] or "",
                item.get("company_name", ""),
            ])

    return filepath
