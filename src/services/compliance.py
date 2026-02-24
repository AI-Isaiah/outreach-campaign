"""CAN-SPAM and GDPR compliance utilities.

Provides unsubscribe link generation, compliance footers, GDPR email limits,
and unsubscribe processing.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional
from urllib.parse import quote


def build_unsubscribe_url(from_email: str) -> str:
    """Build a mailto: unsubscribe link.

    Returns:
        A mailto: URL with subject=Unsubscribe, e.g.
        ``mailto:outreach@domain.com?subject=Unsubscribe``
    """
    return f"mailto:{from_email}?subject=Unsubscribe"


def add_compliance_footer(
    body_text: str,
    physical_address: str,
    unsubscribe_url: str,
) -> str:
    """Append a CAN-SPAM compliant footer to the email body.

    The footer is separated from the main body by a horizontal rule and
    includes the sender's physical address and an unsubscribe link.

    Args:
        body_text: the original email body (plain text)
        physical_address: the sender's physical mailing address
        unsubscribe_url: the mailto: unsubscribe link

    Returns:
        The email body with the compliance footer appended.
    """
    footer = (
        "\n---\n"
        f"{physical_address}\n"
        f"To unsubscribe, reply here: {unsubscribe_url}\n"
    )
    return body_text + footer


def add_compliance_footer_html(
    body_html: str,
    physical_address: str,
    unsubscribe_url: str,
) -> str:
    """Append a CAN-SPAM compliant footer to an HTML email body.

    Inserts a simple footer before the closing </body> tag (or appends
    if no closing body tag is found). No tracking pixels. Clean HTML only.

    Args:
        body_html: the original HTML body
        physical_address: the sender's physical mailing address
        unsubscribe_url: the mailto: unsubscribe link

    Returns:
        The HTML body with the compliance footer appended.
    """
    footer_html = (
        '<hr style="border:none;border-top:1px solid #ccc;margin:24px 0 12px 0;">'
        f'<p style="font-size:12px;color:#666;">{physical_address}<br>'
        f'<a href="{unsubscribe_url}">Unsubscribe</a></p>'
    )
    # Insert before </body> if present, otherwise append
    lower = body_html.lower()
    idx = lower.rfind("</body>")
    if idx != -1:
        return body_html[:idx] + footer_html + body_html[idx:]
    return body_html + footer_html


def check_gdpr_email_limit(
    conn: sqlite3.Connection,
    contact_id: int,
    campaign_id: int,
    max_emails: int = 2,
) -> bool:
    """Check if a GDPR-subject contact can still receive emails.

    Counts ``email_sent`` events for the given contact in the given campaign.
    GDPR contacts are limited to a maximum number of emails (default 2).

    Args:
        conn: database connection
        contact_id: the contact to check
        campaign_id: the campaign context
        max_emails: maximum emails allowed (default 2 for GDPR)

    Returns:
        True if the contact can still receive emails (count < max),
        False if the limit has been reached.
    """
    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM events
           WHERE contact_id = ? AND campaign_id = ? AND event_type = 'email_sent'""",
        (contact_id, campaign_id),
    ).fetchone()
    count = row["cnt"] if row else 0
    return count < max_emails


def is_contact_gdpr(conn: sqlite3.Connection, contact_id: int) -> bool:
    """Check if a contact is subject to GDPR restrictions.

    A contact is GDPR-subject if their ``is_gdpr`` flag is set, or if their
    company's ``is_gdpr`` flag is set.

    Args:
        conn: database connection
        contact_id: the contact to check

    Returns:
        True if the contact is under GDPR, False otherwise.
    """
    row = conn.execute(
        """SELECT c.is_gdpr as contact_gdpr, co.is_gdpr as company_gdpr
           FROM contacts c
           LEFT JOIN companies co ON co.id = c.company_id
           WHERE c.id = ?""",
        (contact_id,),
    ).fetchone()
    if row is None:
        return False
    return bool(row["contact_gdpr"]) or bool(row["company_gdpr"] or 0)


def process_unsubscribe(conn: sqlite3.Connection, email: str) -> bool:
    """Process an unsubscribe request for a contact by email address.

    Sets ``unsubscribed=1`` and ``unsubscribed_at`` to the current timestamp
    on any contacts matching the given email.

    Args:
        conn: database connection
        email: the email address that requested unsubscription

    Returns:
        True if at least one contact was found and unsubscribed,
        False if no matching contact was found.
    """
    now = datetime.utcnow().isoformat()
    cursor = conn.execute(
        "UPDATE contacts SET unsubscribed = 1, unsubscribed_at = ? WHERE email = ?",
        (now, email),
    )
    conn.commit()
    return cursor.rowcount > 0
