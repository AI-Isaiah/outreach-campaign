"""Newsletter pipeline for opted-in contacts.

Handles subscriber management, Markdown-to-HTML rendering, and newsletter
distribution. NO tracking pixels. Clean HTML only.

Subscription rules:
- Non-GDPR contacts who finish a campaign without replying: auto-subscribed
- GDPR contacts: ONLY added if they explicitly opt in
- Anyone can unsubscribe via link in newsletter
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from jinja2.sandbox import SandboxedEnvironment

from src.models.database import get_cursor
from src.models.events import log_event
from src.services.compliance import (
    add_compliance_footer,
    add_compliance_footer_html,
    build_unsubscribe_url,
)
from src.services.email_sender import send_email, send_emails_batch

logger = logging.getLogger(__name__)


def get_newsletter_subscribers(conn, *, user_id: int) -> list:
    """Get all contacts with newsletter_status = 'subscribed' and unsubscribed = 0.

    Returns list of dicts with contact info.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            """SELECT * FROM contacts
               WHERE newsletter_status = 'subscribed'
                 AND unsubscribed = false
                 AND email IS NOT NULL
                 AND email != ''
                 AND user_id = %s
               ORDER BY id
               LIMIT 5000""",
            (user_id,),
        )
        return cursor.fetchall()


def auto_subscribe_eligible(conn, campaign_id: int, *, user_id: int) -> dict:
    """Auto-subscribe non-GDPR contacts who finished the campaign without replying.

    Rules:
    - Contact must have status 'no_response' in the campaign
    - Contact must NOT be GDPR (is_gdpr = 0)
    - Contact must not already be subscribed or unsubscribed
    - Contact must have an email

    Updates newsletter_status to 'subscribed'.
    Returns: {"subscribed": int, "skipped_gdpr": int, "already_subscribed": int}
    """
    result = {"subscribed": 0, "skipped_gdpr": 0, "already_subscribed": 0}

    with get_cursor(conn) as cursor:
        # Get all contacts with no_response in this campaign
        cursor.execute(
            """SELECT c.id, c.is_gdpr, c.newsletter_status, c.email,
                      co.is_gdpr as company_gdpr
               FROM contacts c
               JOIN contact_campaign_status ccs ON ccs.contact_id = c.id
               LEFT JOIN companies co ON co.id = c.company_id
               WHERE ccs.campaign_id = %s
                 AND ccs.status = 'no_response'
                 AND c.user_id = %s""",
            (campaign_id, user_id),
        )
        rows = cursor.fetchall()

        for row in rows:
            # Skip contacts without email
            if not row["email"]:
                continue

            # Check GDPR status (contact or company level)
            is_gdpr = bool(row["is_gdpr"]) or bool(row["company_gdpr"] or 0)
            if is_gdpr:
                result["skipped_gdpr"] += 1
                continue

            # Check if already subscribed or unsubscribed
            if row["newsletter_status"] in ("subscribed", "unsubscribed"):
                result["already_subscribed"] += 1
                continue

            # Subscribe
            cursor.execute(
                "UPDATE contacts SET newsletter_status = 'subscribed' WHERE id = %s AND user_id = %s",
                (row["id"], user_id),
            )
            result["subscribed"] += 1

        conn.commit()
    return result


def subscribe_contact(conn, contact_id: int, *, user_id: int) -> bool:
    """Manually subscribe a contact to the newsletter.

    Sets newsletter_status = 'subscribed'.
    Returns True if updated, False if not found.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            "UPDATE contacts SET newsletter_status = 'subscribed' WHERE id = %s AND user_id = %s",
            (contact_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def unsubscribe_contact(conn, contact_id: int, *, user_id: int) -> bool:
    """Unsubscribe a contact from the newsletter.

    Sets newsletter_status = 'unsubscribed' and unsubscribed = 1.
    Returns True if updated, False if not found.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            "UPDATE contacts SET newsletter_status = 'unsubscribed', unsubscribed = true WHERE id = %s AND user_id = %s",
            (contact_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def render_newsletter(markdown_path: str, config: dict) -> tuple:
    """Render a newsletter from Markdown to HTML + plain text.

    Args:
        markdown_path: path to .md file in data/newsletters/
        config: config dict with calendly_url, physical_address, smtp.username

    Returns:
        (html_content, text_content) both with compliance footer appended

    Uses markdown2 for rendering. The HTML has a clean, minimal style
    (just basic typography). NO tracking pixels. NO images.
    Jinja2 variables in the markdown (like {{ calendly_url }}) are rendered
    BEFORE converting to HTML.
    """
    import markdown2

    md_path = Path(markdown_path)
    if not md_path.exists():
        raise FileNotFoundError(f"Newsletter file not found: {markdown_path}")

    raw_md = md_path.read_text(encoding="utf-8")

    # Step 1: Render Jinja2 variables in the markdown
    env = SandboxedEnvironment()
    tmpl = env.from_string(raw_md)
    rendered_md = tmpl.render(
        calendly_url=config.get("calendly_url", ""),
        physical_address=config.get("physical_address", ""),
    )

    # Step 2: Convert Markdown to HTML
    html_body = markdown2.markdown(rendered_md, extras=["fenced-code-blocks"])

    # Step 3: Build compliance elements
    smtp_config = config.get("smtp", {})
    from_email = smtp_config.get("username", "")
    physical_address = config.get("physical_address", "")
    unsubscribe_url = build_unsubscribe_url(from_email)

    # Step 4: Wrap HTML in a clean, minimal template
    html_content = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        "  <style>\n"
        "    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', "
        "Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; "
        "color: #333; line-height: 1.6; }\n"
        "    h1 { font-size: 24px; color: #1a1a1a; }\n"
        "    h2 { font-size: 18px; color: #1a1a1a; }\n"
        "    a { color: #0066cc; }\n"
        "    ul { padding-left: 20px; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"{html_body}\n"
        "</body>\n"
        "</html>"
    )

    # Step 5: Add compliance footer to HTML
    html_content = add_compliance_footer_html(
        html_content, physical_address, unsubscribe_url
    )

    # Step 6: Build plain text version with compliance footer
    text_content = add_compliance_footer(
        rendered_md, physical_address, unsubscribe_url
    )

    return html_content, text_content


def send_newsletter(
    conn,
    markdown_path: str,
    config: dict,
    dry_run: bool = False,
    user_id: int = 1,
) -> dict:
    """Send a newsletter to all subscribers.

    1. Render the markdown
    2. Get all subscribers
    3. Send to each (via send_email)
    4. Log newsletter_sent events

    Returns: {"sent": int, "failed": int, "subscribers": int}
    """
    result = {"sent": 0, "failed": 0, "subscribers": 0}

    # Render newsletter
    html_content, text_content = render_newsletter(markdown_path, config)

    # Extract subject from markdown filename or first heading
    md_path = Path(markdown_path)
    raw_md = md_path.read_text(encoding="utf-8")
    subject = _extract_subject(raw_md, md_path.stem)

    # Get subscribers
    subscribers = get_newsletter_subscribers(conn, user_id=user_id)
    result["subscribers"] = len(subscribers)

    if dry_run:
        return result

    # Send to each subscriber
    smtp_config = config.get("smtp", {})
    from_email = smtp_config.get("username", "")

    for contact in subscribers:
        success = send_email(
            smtp_host=smtp_config.get("host", "smtp.gmail.com"),
            smtp_port=smtp_config.get("port", 587),
            smtp_username=smtp_config.get("username", ""),
            smtp_password=config.get("smtp_password", ""),
            from_email=from_email,
            to_email=contact["email"],
            subject=subject,
            body_text=text_content,
            body_html=html_content,
        )

        if success:
            result["sent"] += 1
            # Log event
            metadata = json.dumps({
                "subject": subject,
                "newsletter_file": str(md_path.name),
                "to_email": contact["email"],
            })
            log_event(
                conn,
                contact["id"],
                "newsletter_sent",
                metadata=metadata,
                user_id=user_id,
            )
        else:
            result["failed"] += 1

    return result


def send_newsletter_to_recipients(
    conn,
    newsletter_id: int,
    newsletter: dict,
    recipients: list,
    config: dict,
    attachments: list,
    user_id: int = 1,
) -> dict:
    """Send an HTML newsletter to a list of recipients.

    Args:
        conn: database connection
        newsletter_id: the newsletter record ID
        newsletter: dict with subject, body_html, body_text
        recipients: list of contact dicts with id, email, full_name
        config: app config dict with smtp settings
        attachments: list of attachment dicts with file_path, filename

    Returns:
        {"sent": int, "failed": int, "total": int}
    """
    result = {"sent": 0, "failed": 0, "total": len(recipients)}

    smtp_config = config.get("smtp", {})
    from_email = smtp_config.get("username", "")
    physical_address = config.get("physical_address", "")
    unsubscribe_url = build_unsubscribe_url(from_email)

    body_html = add_compliance_footer_html(
        newsletter["body_html"], physical_address, unsubscribe_url,
    )
    body_text = newsletter.get("body_text") or ""
    if body_text:
        body_text = add_compliance_footer(body_text, physical_address, unsubscribe_url)

    # Build attachment list for batch send
    att_list = [
        {"file_path": a["file_path"], "filename": a["filename"]}
        for a in attachments
    ] if attachments else None

    with get_cursor(conn) as cursor:
        # Create all send records upfront
        for contact in recipients:
            cursor.execute(
                """INSERT INTO newsletter_sends (newsletter_id, contact_id, status, user_id)
                   VALUES (%s, %s, 'pending', %s)
                   ON CONFLICT (newsletter_id, contact_id) DO NOTHING""",
                (newsletter_id, contact["id"], user_id),
            )
        conn.commit()

        # Build batch messages
        batch_messages = [
            {
                "to_email": contact["email"],
                "subject": newsletter["subject"],
                "body_text": body_text or newsletter["subject"],
                "body_html": body_html,
                "attachments": att_list,
            }
            for contact in recipients
        ]

        # Send all via single SMTP session
        send_results = send_emails_batch(
            smtp_host=smtp_config.get("host", "smtp.gmail.com"),
            smtp_port=smtp_config.get("port", 587),
            smtp_username=smtp_config.get("username", ""),
            smtp_password=config.get("smtp_password", ""),
            from_email=from_email,
            messages=batch_messages,
        )

        # Update individual send records based on results
        for contact, success in zip(recipients, send_results):
            if success:
                result["sent"] += 1
                cursor.execute(
                    "UPDATE newsletter_sends SET status = 'sent', sent_at = NOW() WHERE newsletter_id = %s AND contact_id = %s AND user_id = %s",
                    (newsletter_id, contact["id"], user_id),
                )
                log_event(
                    conn, contact["id"], "newsletter_sent",
                    metadata=json.dumps({"newsletter_id": newsletter_id, "subject": newsletter["subject"]}),
                    user_id=user_id,
                )
            else:
                result["failed"] += 1
                cursor.execute(
                    "UPDATE newsletter_sends SET status = 'failed', error_message = 'SMTP send failed' WHERE newsletter_id = %s AND contact_id = %s AND user_id = %s",
                    (newsletter_id, contact["id"], user_id),
                )

        # Update newsletter status
        final_status = "sent" if result["failed"] == 0 else ("failed" if result["sent"] == 0 else "sent")
        cursor.execute(
            "UPDATE newsletters SET status = %s, sent_at = NOW(), recipient_count = %s, updated_at = NOW() WHERE id = %s",
            (final_status, result["sent"], newsletter_id),
        )
        conn.commit()

    return result


def _extract_subject(markdown_text: str, fallback: str) -> str:
    """Extract the first H1 heading from markdown as the email subject.

    Falls back to the filename stem if no heading is found.
    """
    for line in markdown_text.strip().split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback
