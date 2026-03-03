"""Gmail SMTP email sender for outreach campaigns.

Sends plain-text emails with an optional minimal HTML variant.
NO tracking pixels. NO images. Clean HTML only.
"""

from __future__ import annotations

import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.models.campaigns import (
    get_template,
    log_event,
    update_contact_campaign_status,
)
from src.services.compliance import (
    add_compliance_footer,
    add_compliance_footer_html,
    build_unsubscribe_url,
    check_gdpr_email_limit,
    is_contact_gdpr,
)
from src.services.template_engine import get_template_context, render_template

logger = logging.getLogger(__name__)


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
) -> bool:
    """Send an email via SMTP with TLS.

    Sends a multipart/alternative message containing both a plain-text part
    and an optional HTML part. If ``body_html`` is not provided, a clean
    HTML version is auto-generated from the plain text.

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

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    try:
        # Build multipart/alternative message
        msg = MIMEMultipart("alternative")
        msg["From"] = from_email
        msg["To"] = to_email
        msg["Subject"] = subject

        # Always include plain text
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        # Include HTML part (auto-generated if not provided)
        html = body_html if body_html is not None else _text_to_clean_html(body_text)
        msg.attach(MIMEText(html, "html", "utf-8"))

        # Send via SMTP with STARTTLS
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(from_email, to_email, msg.as_string())

        logger.info("Email sent to %s: %s", to_email, subject)
        return True

    except smtplib.SMTPException:
        logger.exception("SMTP error sending email to %s", to_email)
        return False
    except Exception:
        logger.exception("Unexpected error sending email to %s", to_email)
        return False


def render_campaign_email(
    conn,
    contact_id: int,
    campaign_id: int,
    template_id: int,
    config: dict,
) -> Optional[dict]:
    """Render a campaign email without sending it.

    Performs the same pre-flight checks and rendering as
    ``send_campaign_email()`` but returns the rendered content instead
    of sending via SMTP. Used for email preview and Gmail Draft flow.

    Returns:
        Dict with keys: subject, body_text, body_html, contact_email,
        template_id — or None if pre-flight checks fail.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM contacts WHERE id = %s", (contact_id,),
    )
    contact = cursor.fetchone()
    if contact is None or contact["unsubscribed"]:
        return None

    if is_contact_gdpr(conn, contact_id):
        if not check_gdpr_email_limit(conn, contact_id, campaign_id):
            return None

    template_row = get_template(conn, template_id)
    if template_row is None:
        return None

    context = get_template_context(conn, contact_id, config)
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

    body_text = add_compliance_footer(body_text, physical_address, unsubscribe_url)
    body_html = _text_to_clean_html(body_text)
    body_html = add_compliance_footer_html(body_html, physical_address, unsubscribe_url)

    return {
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
        "contact_email": contact["email"],
        "template_id": template_id,
    }


def send_campaign_email(
    conn,
    contact_id: int,
    campaign_id: int,
    template_id: int,
    config: dict,
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
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM contacts WHERE id = %s",
        (contact_id,),
    )
    contact = cursor.fetchone()
    if contact is None:
        logger.error("Contact %d not found", contact_id)
        return False
    if contact["unsubscribed"]:
        logger.info("Contact %d is unsubscribed, skipping", contact_id)
        return False

    # GDPR email limit check
    if is_contact_gdpr(conn, contact_id):
        if not check_gdpr_email_limit(conn, contact_id, campaign_id):
            logger.info("GDPR limit reached for contact %d in campaign %d", contact_id, campaign_id)
            return False

    # --- Render template ------------------------------------------------------

    template_row = get_template(conn, template_id)
    if template_row is None:
        logger.error("Template %d not found", template_id)
        return False

    context = get_template_context(conn, contact_id, config)
    body_text = render_template(
        template_row["body_template"],
        context,
    ) if template_row["body_template"].endswith(".txt") else _render_inline_template(
        template_row["body_template"],
        context,
    )

    subject = template_row["subject"] or "Reaching out"

    # --- Add compliance footer ------------------------------------------------

    smtp_config = config.get("smtp", {})
    from_email = smtp_config.get("username", "")
    physical_address = config.get("physical_address", "")
    unsubscribe_url = build_unsubscribe_url(from_email)

    body_text = add_compliance_footer(body_text, physical_address, unsubscribe_url)

    # Generate clean HTML from the compliant plain text
    body_html = _text_to_clean_html(body_text)
    body_html = add_compliance_footer_html(body_html, physical_address, unsubscribe_url)

    # --- Send -----------------------------------------------------------------

    success = send_email(
        smtp_host=smtp_config.get("host", "smtp.gmail.com"),
        smtp_port=smtp_config.get("port", 587),
        smtp_username=smtp_config.get("username", ""),
        smtp_password=config.get("smtp_password", ""),
        from_email=from_email,
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
        "email_sent",
        campaign_id=campaign_id,
        template_id=template_id,
        metadata=metadata,
    )

    # Advance the contact's current step
    cursor.execute(
        "SELECT current_step FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
        (contact_id, campaign_id),
    )
    status_row = cursor.fetchone()
    if status_row:
        update_contact_campaign_status(
            conn, contact_id, campaign_id,
            current_step=status_row["current_step"] + 1,
        )

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
    from jinja2 import Template
    tmpl = Template(template_str)
    return tmpl.render(**context)
