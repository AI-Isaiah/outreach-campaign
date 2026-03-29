"""Gmail SMTP email sender for outreach campaigns.

Sends plain-text emails with an optional minimal HTML variant.
NO tracking pixels. NO images. Clean HTML only.
"""

from __future__ import annotations

import json
import logging
import re
import smtplib
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import psycopg2

from src.enums import EventType
from src.models.enrollment import get_sequence_steps, record_template_usage
from src.services.sequence_utils import advance_to_next_step
from src.models.events import log_event
from src.models.templates import get_template
from src.services.compliance import (
    add_compliance_footer,
    add_compliance_footer_html,
    build_unsubscribe_url,
    check_gdpr_email_limit,
    is_contact_gdpr,
)
from jinja2.sandbox import SandboxedEnvironment

from src.models.database import get_cursor
from src.services.template_engine import get_template_context, render_template

logger = logging.getLogger(__name__)

_SANDBOX_ENV = SandboxedEnvironment()

# Simple RFC-style email regex — enough to catch obvious bad data before SMTP.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_RETRY_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1
_TRANSIENT_ERRORS = (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)


def _text_to_clean_html(text: str) -> str:
    """Convert plain text to minimal, clean HTML.

    Wraps text in basic HTML tags with paragraph breaks. No images,
    no tracking pixels, no external resources.

    Args:
        text: plain-text email body

    Returns:
        A clean HTML string suitable for email clients.
    """
    # Convert newlines to <br> tags and wrap in minimal HTML
    paragraphs = text.split("\n\n")
    html_paragraphs = []
    for para in paragraphs:
        escaped = (
            para.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        # Preserve single newlines as <br>
        escaped = escaped.replace("\n", "<br>\n")
        html_paragraphs.append(f"<p>{escaped}</p>")

    body_content = "\n".join(html_paragraphs)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head><meta charset=\"utf-8\"></head>\n"
        "<body>\n"
        f"{body_content}\n"
        "</body>\n"
        "</html>"
    )


def send_email(
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    from_email: str,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    attachments: Optional[list[dict]] = None,
) -> bool:
    """Send an email via SMTP with TLS.

    Sends a multipart/alternative message containing both a plain-text part
    and an optional HTML part. If ``body_html`` is not provided, a clean
    HTML version is auto-generated from the plain text.

    When ``attachments`` is provided, wraps in multipart/mixed with the
    text/html alternative as the first part and file attachments after.

    NO tracking pixels. Clean HTML only.

    Args:
        smtp_host: SMTP server hostname (e.g. ``smtp.gmail.com``)
        smtp_port: SMTP server port (e.g. ``587`` for TLS)
        smtp_username: SMTP login username
        smtp_password: SMTP login password
        from_email: sender email address
        to_email: recipient email address
        subject: email subject line
        body_text: plain-text email body
        body_html: optional HTML email body (clean, no tracking)
        attachments: optional list of dicts with ``file_path`` and ``filename`` keys

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    try:
        msg = _build_mime_message(
            from_email, to_email, subject, body_text, body_html, attachments,
        )

        # Retry loop for transient SMTP errors
        last_error = None
        for attempt in range(_RETRY_MAX_ATTEMPTS):
            try:
                with smtplib.SMTP(smtp_host, smtp_port) as server:
                    server.starttls()
                    server.login(smtp_username, smtp_password)
                    server.sendmail(from_email, to_email, msg.as_string())
                logger.info("Email sent to %s: %s", to_email, subject)
                return True
            except _TRANSIENT_ERRORS as exc:
                last_error = exc
                if attempt < _RETRY_MAX_ATTEMPTS - 1:
                    logger.warning(
                        "Transient SMTP error on attempt %d/%d for %s: %s",
                        attempt + 1, _RETRY_MAX_ATTEMPTS, to_email, exc,
                    )
                    time.sleep(_RETRY_BACKOFF_SECONDS)
            except smtplib.SMTPRecipientsRefused:
                logger.exception("Permanent SMTP error (recipients refused) for %s", to_email)
                return False

        # All retries exhausted
        logger.error("All %d SMTP attempts failed for %s: %s", _RETRY_MAX_ATTEMPTS, to_email, last_error)
        return False

    except smtplib.SMTPException:
        logger.exception("SMTP error sending email to %s", to_email)
        return False
    except (OSError, ValueError):
        logger.exception("Unexpected error sending email to %s", to_email)
        return False


def _build_mime_message(
    from_email: str,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    attachments: Optional[list[dict]] = None,
) -> MIMEMultipart:
    """Build a MIME message from the given parts."""
    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText(body_text, "plain", "utf-8"))
    html = body_html if body_html is not None else _text_to_clean_html(body_text)
    alt_part.attach(MIMEText(html, "html", "utf-8"))

    if attachments:
        msg = MIMEMultipart("mixed")
        msg.attach(alt_part)
        for att in attachments:
            file_path = Path(att["file_path"])
            if file_path.exists():
                with open(file_path, "rb") as f:
                    part = MIMEApplication(f.read(), Name=att.get("filename", file_path.name))
                part["Content-Disposition"] = f'attachment; filename="{att.get("filename", file_path.name)}"'
                msg.attach(part)
    else:
        msg = alt_part

    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    return msg


def send_emails_batch(
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    from_email: str,
    messages: list[dict],
) -> list[bool]:
    """Send multiple emails over a single SMTP connection.

    Opens ONE SMTP connection with STARTTLS, sends all messages, and returns
    a list of success booleans (one per message, in order).

    Each dict in ``messages`` must have keys:
    - to_email: str
    - subject: str
    - body_text: str
    - body_html: str (optional)
    - attachments: list[dict] (optional)

    Args:
        smtp_host: SMTP server hostname
        smtp_port: SMTP server port
        smtp_username: SMTP login username
        smtp_password: SMTP login password
        from_email: sender email address
        messages: list of message dicts

    Returns:
        List of booleans, True for each message sent successfully.
    """
    results: list[bool] = []
    if not messages:
        return results

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)

            for msg_data in messages:
                try:
                    mime_msg = _build_mime_message(
                        from_email=from_email,
                        to_email=msg_data["to_email"],
                        subject=msg_data["subject"],
                        body_text=msg_data["body_text"],
                        body_html=msg_data.get("body_html"),
                        attachments=msg_data.get("attachments"),
                    )
                    server.sendmail(from_email, msg_data["to_email"], mime_msg.as_string())
                    logger.info("Batch email sent to %s: %s", msg_data["to_email"], msg_data["subject"])
                    results.append(True)
                except smtplib.SMTPRecipientsRefused:
                    logger.warning("Recipient refused: %s", msg_data["to_email"])
                    results.append(False)
                except smtplib.SMTPException:
                    logger.exception("SMTP error sending to %s", msg_data["to_email"])
                    results.append(False)
    except smtplib.SMTPException:
        logger.exception("Failed to establish SMTP connection for batch send")
        # Mark remaining as failed
        results.extend([False] * (len(messages) - len(results)))
    except (OSError, ValueError):
        logger.exception("Unexpected error in batch send")
        results.extend([False] * (len(messages) - len(results)))

    return results


def render_template_with_compliance(
    template_row: dict,
    context: dict,
    config: dict,
) -> dict:
    """Render a template and apply compliance footers.

    Pure rendering function with no database access. Takes a template row,
    a Jinja2 context, and the app config. Returns subject, body_text,
    and body_html with CAN-SPAM footer injected.

    Args:
        template_row: row from the templates table (needs ``body_template``, ``subject``)
        context: template context variables
        config: app config dict (needs ``smtp.username``, ``physical_address``)

    Returns:
        Dict with keys: subject, body_text, body_html.
    """
    body_text = (
        render_template(template_row["body_template"], context)
        if template_row["body_template"].endswith(".txt")
        else _render_inline_template(template_row["body_template"], context)
    )

    subject = template_row["subject"] or "Reaching out"

    smtp_config = config.get("smtp", {})
    from_email = smtp_config.get("username", "")
    physical_address = config.get("physical_address", "")
    unsubscribe_url = build_unsubscribe_url(from_email)

    # Generate HTML from clean body BEFORE adding footers to avoid double footer
    body_html = _text_to_clean_html(body_text)
    body_text = add_compliance_footer(body_text, physical_address, unsubscribe_url)
    body_html = add_compliance_footer_html(body_html, physical_address, unsubscribe_url)

    return {
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
    }


def render_campaign_email(
    conn,
    contact_id: int,
    campaign_id: int,
    template_id: int,
    config: dict,
    *,
    user_id: int,
    pre_fetched_research: dict = None,
) -> Optional[dict]:
    """Render a campaign email without sending it.

    Performs the same pre-flight checks and rendering as
    ``send_campaign_email()`` but returns the rendered content instead
    of sending via SMTP. Used for email preview and Gmail Draft flow.

    Returns:
        Dict with keys: subject, body_text, body_html, contact_email,
        template_id — or None if pre-flight checks fail.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT * FROM contacts WHERE id = %s AND user_id = %s", (contact_id, user_id),
        )
        contact = cursor.fetchone()
    if contact is None or contact["unsubscribed"]:
        return None

    if is_contact_gdpr(conn, contact_id):
        if not check_gdpr_email_limit(conn, contact_id, campaign_id):
            return None

    template_row = get_template(conn, template_id, user_id=user_id)
    if template_row is None or not template_row["body_template"]:
        return None

    context = get_template_context(conn, contact_id, config, user_id=user_id, pre_fetched_research=pre_fetched_research)
    rendered = render_template_with_compliance(template_row, context, config)

    return {
        **rendered,
        "contact_email": contact["email"],
        "template_id": template_id,
    }


def send_campaign_email(
    conn,
    contact_id: int,
    campaign_id: int,
    template_id: int,
    config: dict,
    *,
    user_id: int,
    pre_fetched_research: dict = None,
) -> bool:
    """Send a campaign email to a contact.

    Orchestrates the full send flow:

    1. Checks if the contact is unsubscribed.
    2. For GDPR contacts, checks the 2-email limit.
    3. Renders the template with contact/company data.
    4. Adds the CAN-SPAM compliance footer (physical address + unsubscribe).
    5. Sends via SMTP.
    6. Logs an ``email_sent`` event in the database.
    7. Advances the contact's current_step.

    Args:
        conn: database connection
        contact_id: the contact to email
        campaign_id: the campaign this send belongs to
        template_id: the template to render
        config: application config dict (must include ``smtp``,
            ``calendly_url``, ``physical_address``)

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    # --- Pre-flight checks ---------------------------------------------------

    # Check if contact is unsubscribed
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT * FROM contacts WHERE id = %s AND user_id = %s",
            (contact_id, user_id),
        )
        contact = cursor.fetchone()
    if contact is None:
        logger.error("Contact %d not found", contact_id)
        return False
    if contact["unsubscribed"]:
        logger.info("Contact %d is unsubscribed, skipping", contact_id)
        return False

    email = contact.get("email_normalized") or contact.get("email")
    if not email or not _EMAIL_RE.match(email):
        logger.error("Contact %d has no valid email address", contact_id)
        return False

    # GDPR email limit check
    if is_contact_gdpr(conn, contact_id):
        if not check_gdpr_email_limit(conn, contact_id, campaign_id):
            logger.info("GDPR limit reached for contact %d in campaign %d", contact_id, campaign_id)
            return False

    # --- Idempotency guard: atomic claim-and-read in one query ----------------

    with get_cursor(conn) as cur:
        cur.execute(
            "UPDATE contact_campaign_status "
            "SET sent_at = NOW() "
            "WHERE contact_id = %s AND campaign_id = %s AND sent_at IS NULL "
            "RETURNING current_step",
            (contact_id, campaign_id),
        )
        claimed = cur.fetchone()
    if not claimed:
        logger.info("Skipping already-sent or missing enrollment for contact %s", contact_id)
        return False
    current_step = claimed["current_step"]
    conn.commit()

    # --- Render template ------------------------------------------------------

    template_row = get_template(conn, template_id, user_id=user_id)
    if template_row is None or not template_row["body_template"]:
        logger.error("Template %d not found or has no body", template_id)
        return False

    context = get_template_context(conn, contact_id, config, user_id=user_id, pre_fetched_research=pre_fetched_research)
    rendered = render_template_with_compliance(template_row, context, config)
    subject = rendered["subject"]
    body_text = rendered["body_text"]
    body_html = rendered["body_html"]

    # --- Send -----------------------------------------------------------------

    smtp_config = config.get("smtp", {})
    success = send_email(
        smtp_host=smtp_config.get("host", "smtp.gmail.com"),
        smtp_port=smtp_config.get("port", 587),
        smtp_username=smtp_config.get("username", ""),
        smtp_password=config.get("smtp_password", ""),
        from_email=smtp_config.get("username", ""),
        to_email=contact["email"],
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )

    if not success:
        return False

    # --- Log event and advance step -------------------------------------------

    metadata = json.dumps({
        "subject": subject,
        "template_id": template_id,
        "to_email": contact["email"],
    })
    log_event(
        conn,
        contact_id,
        EventType.EMAIL_SENT,
        campaign_id=campaign_id,
        template_id=template_id,
        metadata=metadata,
        user_id=user_id,
    )

    # Record template usage for performance tracking
    record_template_usage(
        conn, contact_id, campaign_id, template_id,
        channel=template_row["channel"],
    )

    # Advance to next step (sets next_action_date, clears approval state)
    steps = get_sequence_steps(conn, campaign_id, user_id=user_id)
    advance_to_next_step(conn, contact_id, campaign_id, current_step, steps, user_id=user_id)

    conn.commit()

    # Auto-advance lifecycle: cold → contacted
    try:
        from src.services.lifecycle import on_email_sent
        on_email_sent(conn, contact_id, user_id=user_id)
    except (ValueError, KeyError, psycopg2.Error) as exc:
        logger.warning("Lifecycle advance failed for contact %d: %s", contact_id, exc)

    logger.info("Campaign email sent to contact %d (campaign %d)", contact_id, campaign_id)
    return True


def _render_inline_template(template_str: str, context: dict) -> str:
    """Render a Jinja2 template from an inline string.

    Used when the template body_template column contains the template text
    directly rather than a file path.

    Args:
        template_str: a Jinja2 template string
        context: template variables

    Returns:
        The rendered string.
    """
    tmpl = _SANDBOX_ENV.from_string(template_str)
    return tmpl.render(**context)
