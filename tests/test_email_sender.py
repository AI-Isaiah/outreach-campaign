"""Tests for email sender, compliance, and template engine modules (Tasks 17-20)."""

from __future__ import annotations

import base64
import json
import os
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.database import get_connection, run_migrations
from src.models.campaigns import (
    add_sequence_step,
    create_campaign,
    create_template,
    enroll_contact,
    get_contact_campaign_status,
    log_event,
)
from tests.conftest import TEST_USER_ID
from src.services.compliance import (
    add_compliance_footer,
    add_compliance_footer_html,
    build_unsubscribe_url,
    check_gdpr_email_limit,
    is_contact_gdpr,
    process_unsubscribe,
)
from src.services.template_engine import (
    get_template_context,
    render_template,
)
from src.services.email_sender import (
    _text_to_clean_html,
    send_email,
    send_campaign_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_mime_message(raw_message: str) -> str:
    """Decode a raw MIME message, including any base64-encoded parts.

    Returns the raw message with all base64 segments decoded so that
    content assertions can be performed against the plaintext.
    """
    decoded_parts = [raw_message]
    # Find and decode base64 segments (lines of base64 chars)
    import re
    # Split the message on boundaries and decode base64 blocks
    lines = raw_message.split("\n")
    result = []
    b64_block = []
    in_b64 = False

    for line in lines:
        stripped = line.strip()
        if stripped and re.match(r'^[A-Za-z0-9+/=]+$', stripped) and len(stripped) > 20:
            b64_block.append(stripped)
            in_b64 = True
        else:
            if in_b64 and b64_block:
                try:
                    decoded = base64.b64decode("".join(b64_block)).decode("utf-8", errors="replace")
                    result.append(decoded)
                except Exception:
                    result.append("".join(b64_block))
                b64_block = []
                in_b64 = False
            result.append(line)

    # Handle trailing base64 block
    if b64_block:
        try:
            decoded = base64.b64decode("".join(b64_block)).decode("utf-8", errors="replace")
            result.append(decoded)
        except Exception:
            result.append("".join(b64_block))

    return "\n".join(result)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_db):
    """Return a connection with all tables created."""
    connection = get_connection(tmp_db)
    run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def sample_company(conn):
    """Insert a company and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO companies (name, name_normalized, country, is_gdpr, user_id) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        ("Acme Crypto Fund", "acme crypto fund", "United States", False, TEST_USER_ID),
    )
    company_id = cursor.fetchone()["id"]
    conn.commit()
    return company_id


@pytest.fixture
def gdpr_company(conn):
    """Insert a GDPR-subject company and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO companies (name, name_normalized, country, is_gdpr, user_id) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        ("Berlin Capital GmbH", "berlin capital gmbh", "Germany", True, TEST_USER_ID),
    )
    company_id = cursor.fetchone()["id"]
    conn.commit()
    return company_id


@pytest.fixture
def sample_contact(conn, sample_company):
    """Insert a contact and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO contacts (company_id, first_name, last_name, full_name, email, email_normalized, source, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (sample_company, "Alice", "Smith", "Alice Smith", "alice@example.com", "alice@example.com", "csv", TEST_USER_ID),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    return contact_id


@pytest.fixture
def gdpr_contact(conn, gdpr_company):
    """Insert a GDPR-subject contact and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO contacts (company_id, first_name, last_name, full_name, email, source, is_gdpr, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (gdpr_company, "Hans", "Mueller", "Hans Mueller", "hans@berlin-cap.de", "csv", True, TEST_USER_ID),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    return contact_id


@pytest.fixture
def sample_campaign(conn):
    """Create and return a campaign id."""
    return create_campaign(conn, "Q1 Outreach", description="Test campaign", user_id=TEST_USER_ID)


@pytest.fixture
def sample_template(conn):
    """Create and return a template id."""
    return create_template(
        conn,
        name="Cold Outreach v1 A",
        channel="email",
        body_template="Hi {{ first_name }}, let's talk about {{ company_name }}.",
        subject="Quick intro from our team",
        user_id=TEST_USER_ID,
    )


@pytest.fixture
def sample_config():
    """Return a minimal config dict for testing."""
    return {
        "calendly_url": "https://calendly.com/helmutm",
        "physical_address": "Test Company, 123 Main St, New York, NY 10001",
        "smtp": {
            "host": "smtp.gmail.com",
            "port": 587,
            "username": "outreach@test-domain.com",
        },
        "smtp_password": "test-password-123",
    }


# ===========================================================================
# Tests: build_unsubscribe_url
# ===========================================================================

class TestBuildUnsubscribeUrl:
    def test_basic(self):
        url = build_unsubscribe_url("outreach@domain.com")
        assert url == "mailto:outreach@domain.com?subject=Unsubscribe"

    def test_different_email(self):
        url = build_unsubscribe_url("noreply@secondary.co")
        assert url == "mailto:noreply@secondary.co?subject=Unsubscribe"

    def test_contains_mailto_prefix(self):
        url = build_unsubscribe_url("test@example.com")
        assert url.startswith("mailto:")

    def test_contains_unsubscribe_subject(self):
        url = build_unsubscribe_url("test@example.com")
        assert "subject=Unsubscribe" in url


# ===========================================================================
# Tests: add_compliance_footer
# ===========================================================================

class TestAddComplianceFooter:
    def test_appends_footer(self):
        body = "Hello, this is a test email."
        result = add_compliance_footer(
            body, "123 Main St, City", "mailto:test@example.com?subject=Unsubscribe"
        )
        assert "123 Main St, City" in result
        assert "mailto:test@example.com?subject=Unsubscribe" in result

    def test_separator_present(self):
        body = "Test body"
        result = add_compliance_footer(body, "Address", "mailto:x@y.com?subject=Unsubscribe")
        assert "\n---\n" in result

    def test_original_body_preserved(self):
        body = "My original email body."
        result = add_compliance_footer(body, "Addr", "mailto:x@y.com?subject=Unsubscribe")
        assert result.startswith("My original email body.")

    def test_unsubscribe_text_present(self):
        result = add_compliance_footer(
            "Body", "Addr", "mailto:unsub@example.com?subject=Unsubscribe"
        )
        assert "unsubscribe" in result.lower()

    def test_physical_address_in_footer(self):
        result = add_compliance_footer(
            "Body",
            "Acme Corp, 456 Oak Ave, San Francisco, CA 94102",
            "mailto:x@y.com?subject=Unsubscribe",
        )
        assert "Acme Corp, 456 Oak Ave, San Francisco, CA 94102" in result


# ===========================================================================
# Tests: add_compliance_footer_html
# ===========================================================================

class TestAddComplianceFooterHtml:
    def test_inserts_before_body_close(self):
        html = "<html><body><p>Hello</p></body></html>"
        result = add_compliance_footer_html(
            html, "123 Main St", "mailto:x@y.com?subject=Unsubscribe"
        )
        # Footer should appear before </body>
        assert result.index("123 Main St") < result.index("</body>")

    def test_appends_when_no_body_tag(self):
        html = "<p>Hello</p>"
        result = add_compliance_footer_html(
            html, "123 Main St", "mailto:x@y.com?subject=Unsubscribe"
        )
        assert "123 Main St" in result
        assert result.index("<p>Hello</p>") < result.index("123 Main St")

    def test_contains_unsubscribe_link(self):
        html = "<html><body><p>Hi</p></body></html>"
        result = add_compliance_footer_html(
            html, "Addr", "mailto:unsub@co.com?subject=Unsubscribe"
        )
        assert "Unsubscribe" in result
        assert "mailto:unsub@co.com" in result

    def test_no_tracking_pixels(self):
        html = "<html><body><p>Content</p></body></html>"
        result = add_compliance_footer_html(
            html, "Addr", "mailto:x@y.com?subject=Unsubscribe"
        )
        assert "<img" not in result
        assert "1x1" not in result
        assert "tracking" not in result.lower()


# ===========================================================================
# Tests: check_gdpr_email_limit
# ===========================================================================

class TestCheckGdprEmailLimit:
    def test_under_limit_returns_true(self, conn, gdpr_contact, sample_campaign):
        # No emails sent yet
        assert check_gdpr_email_limit(conn, gdpr_contact, sample_campaign) is True

    def test_at_limit_returns_false(self, conn, gdpr_contact, sample_campaign):
        # Send 2 emails (the limit)
        log_event(conn, gdpr_contact, "email_sent", campaign_id=sample_campaign, user_id=TEST_USER_ID)
        log_event(conn, gdpr_contact, "email_sent", campaign_id=sample_campaign, user_id=TEST_USER_ID)
        assert check_gdpr_email_limit(conn, gdpr_contact, sample_campaign) is False

    def test_one_email_still_ok(self, conn, gdpr_contact, sample_campaign):
        log_event(conn, gdpr_contact, "email_sent", campaign_id=sample_campaign, user_id=TEST_USER_ID)
        assert check_gdpr_email_limit(conn, gdpr_contact, sample_campaign) is True

    def test_over_limit_returns_false(self, conn, gdpr_contact, sample_campaign):
        for _ in range(3):
            log_event(conn, gdpr_contact, "email_sent", campaign_id=sample_campaign, user_id=TEST_USER_ID)
        assert check_gdpr_email_limit(conn, gdpr_contact, sample_campaign) is False

    def test_other_event_types_not_counted(self, conn, gdpr_contact, sample_campaign):
        # Log non-email events
        log_event(conn, gdpr_contact, "linkedin_connect_sent", campaign_id=sample_campaign, user_id=TEST_USER_ID)
        log_event(conn, gdpr_contact, "status_in_progress", campaign_id=sample_campaign, user_id=TEST_USER_ID)
        log_event(conn, gdpr_contact, "email_opened", campaign_id=sample_campaign, user_id=TEST_USER_ID)
        assert check_gdpr_email_limit(conn, gdpr_contact, sample_campaign) is True

    def test_different_campaign_not_counted(self, conn, gdpr_contact, sample_campaign):
        other_campaign = create_campaign(conn, "Other Campaign", user_id=TEST_USER_ID)
        log_event(conn, gdpr_contact, "email_sent", campaign_id=other_campaign, user_id=TEST_USER_ID)
        log_event(conn, gdpr_contact, "email_sent", campaign_id=other_campaign, user_id=TEST_USER_ID)
        # Different campaign, so the original should still be under limit
        assert check_gdpr_email_limit(conn, gdpr_contact, sample_campaign) is True

    def test_custom_limit(self, conn, gdpr_contact, sample_campaign):
        log_event(conn, gdpr_contact, "email_sent", campaign_id=sample_campaign, user_id=TEST_USER_ID)
        # With max_emails=1, one email should hit the limit
        assert check_gdpr_email_limit(conn, gdpr_contact, sample_campaign, max_emails=1) is False


# ===========================================================================
# Tests: is_contact_gdpr
# ===========================================================================

class TestIsContactGdpr:
    def test_gdpr_contact(self, conn, gdpr_contact):
        assert is_contact_gdpr(conn, gdpr_contact) is True

    def test_non_gdpr_contact(self, conn, sample_contact):
        assert is_contact_gdpr(conn, sample_contact) is False

    def test_contact_gdpr_via_company(self, conn, gdpr_company):
        """Contact is not GDPR but company is."""
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, is_gdpr, user_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (gdpr_company, "Max", "max@test.de", "csv", False, TEST_USER_ID),
        )
        contact_id = cursor.fetchone()["id"]
        conn.commit()
        assert is_contact_gdpr(conn, contact_id) is True

    def test_nonexistent_contact(self, conn):
        assert is_contact_gdpr(conn, 99999) is False


# ===========================================================================
# Tests: process_unsubscribe
# ===========================================================================

class TestProcessUnsubscribe:
    def test_marks_contact_as_unsubscribed(self, conn, sample_contact):
        result = process_unsubscribe(conn, "alice@example.com")
        assert result is True

        cursor = conn.cursor()
        cursor.execute(
            "SELECT unsubscribed, unsubscribed_at FROM contacts WHERE id = %s",
            (sample_contact,),
        )
        row = cursor.fetchone()
        assert row["unsubscribed"] is True
        assert row["unsubscribed_at"] is not None

    def test_returns_false_for_unknown_email(self, conn):
        result = process_unsubscribe(conn, "unknown@nowhere.com")
        assert result is False

    def test_does_not_affect_other_contacts(self, conn, sample_company):
        # Insert two contacts
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, user_id) VALUES (%s, %s, %s, %s, %s)",
            (sample_company, "Bob", "bob@example.com", "csv", TEST_USER_ID),
        )
        cursor.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, user_id) VALUES (%s, %s, %s, %s, %s)",
            (sample_company, "Carol", "carol@example.com", "csv", TEST_USER_ID),
        )
        conn.commit()

        process_unsubscribe(conn, "bob@example.com")

        cursor = conn.cursor()
        cursor.execute(
            "SELECT unsubscribed FROM contacts WHERE email = %s", ("carol@example.com",)
        )
        carol = cursor.fetchone()
        assert carol["unsubscribed"] is False

    def test_idempotent(self, conn, sample_contact):
        process_unsubscribe(conn, "alice@example.com")
        result = process_unsubscribe(conn, "alice@example.com")
        assert result is True

        cursor = conn.cursor()
        cursor.execute(
            "SELECT unsubscribed FROM contacts WHERE id = %s", (sample_contact,)
        )
        row = cursor.fetchone()
        assert row["unsubscribed"] is True


# ===========================================================================
# Tests: render_template
# ===========================================================================

class TestRenderTemplate:
    def test_renders_email_template(self):
        """Render a real template from the templates directory."""
        context = {
            "first_name": "Alice",
            "company_name": "Acme Fund",
            "calendly_url": "https://calendly.com/helmutm",
            "unsubscribe_url": "mailto:test@domain.com?subject=Unsubscribe",
            "physical_address": "123 Main St",
        }
        result = render_template("email/cold_outreach_v1_a.txt", context)
        assert "Alice" in result
        assert "Acme Fund" in result
        assert "https://calendly.com/helmutm" in result

    def test_renders_variant_b(self):
        context = {
            "first_name": "Bob",
            "company_name": "Galaxy Fund",
            "calendly_url": "https://calendly.com/helmutm",
            "unsubscribe_url": "mailto:test@domain.com?subject=Unsubscribe",
            "physical_address": "123 Main St",
        }
        result = render_template("email/cold_outreach_v1_b.txt", context)
        assert "Bob" in result
        assert "Galaxy Fund" in result

    def test_renders_follow_up(self):
        context = {
            "first_name": "Carol",
            "company_name": "DeFi Capital",
            "calendly_url": "https://calendly.com/helmutm",
            "unsubscribe_url": "mailto:test@domain.com?subject=Unsubscribe",
            "physical_address": "123 Main St",
        }
        result = render_template("email/follow_up_v1.txt", context)
        assert "Carol" in result
        assert "https://calendly.com/helmutm" in result

    def test_renders_breakup(self):
        context = {
            "first_name": "Dave",
            "company_name": "Blockchain Partners",
            "calendly_url": "https://calendly.com/helmutm",
            "unsubscribe_url": "mailto:test@domain.com?subject=Unsubscribe",
            "physical_address": "123 Main St",
        }
        result = render_template("email/breakup_v1.txt", context)
        assert "Dave" in result
        assert "Blockchain Partners" in result

    def test_renders_linkedin_connect(self):
        context = {
            "first_name": "Eve",
            "company_name": "Crypto Ventures",
            "calendly_url": "https://calendly.com/helmutm",
        }
        result = render_template("linkedin/connect_note_v1.txt", context)
        assert "Eve" in result
        assert "Crypto Ventures" in result
        assert len(result) <= 300  # LinkedIn connection note limit

    def test_renders_linkedin_message(self):
        context = {
            "first_name": "Frank",
            "company_name": "Digital Asset Mgmt",
            "calendly_url": "https://calendly.com/helmutm",
        }
        result = render_template("linkedin/message_v1.txt", context)
        assert "Frank" in result
        assert "Digital Asset Mgmt" in result
        assert "https://calendly.com/helmutm" in result

    def test_custom_templates_dir(self, tmp_path):
        """Test with a custom templates directory."""
        tmpl_dir = tmp_path / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "test.txt").write_text("Hello {{ name }}!")

        result = render_template("test.txt", {"name": "World"}, templates_dir=str(tmpl_dir))
        assert result == "Hello World!"

    def test_missing_template_raises(self):
        with pytest.raises(Exception):  # Jinja2 TemplateNotFound
            render_template("nonexistent/template.txt", {})


# ===========================================================================
# Tests: get_template_context
# ===========================================================================

class TestGetTemplateContext:
    def test_builds_correct_context(self, conn, sample_contact, sample_config):
        ctx = get_template_context(conn, sample_contact, sample_config, user_id=1)
        assert ctx["first_name"] == "Alice"
        assert ctx["last_name"] == "Smith"
        assert ctx["full_name"] == "Alice Smith"
        assert ctx["company_name"] == "Acme Crypto Fund"
        assert ctx["calendly_url"] == "https://calendly.com/helmutm"
        assert ctx["physical_address"] == "Test Company, 123 Main St, New York, NY 10001"
        assert "mailto:" in ctx["unsubscribe_url"]
        assert "outreach@test-domain.com" in ctx["unsubscribe_url"]

    def test_missing_contact_raises(self, conn, sample_config):
        with pytest.raises(ValueError, match="not found"):
            get_template_context(conn, 99999, sample_config, user_id=1)

    def test_contact_without_company(self, conn, sample_config):
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO contacts (first_name, last_name, email, source, user_id) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            ("Orphan", "Contact", "orphan@example.com", "csv", TEST_USER_ID),
        )
        contact_id = cursor.fetchone()["id"]
        conn.commit()

        ctx = get_template_context(conn, contact_id, sample_config, user_id=1)
        assert ctx["first_name"] == "Orphan"
        assert ctx["company_name"] == ""

    def test_contact_with_missing_names(self, conn, sample_company, sample_config):
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO contacts (company_id, email, source, user_id) VALUES (%s, %s, %s, %s) RETURNING id",
            (sample_company, "noname@example.com", "csv", TEST_USER_ID),
        )
        contact_id = cursor.fetchone()["id"]
        conn.commit()

        ctx = get_template_context(conn, contact_id, sample_config, user_id=1)
        assert ctx["first_name"] == ""
        assert ctx["last_name"] == ""
        assert ctx["full_name"] == ""


# ===========================================================================
# Tests: send_email (SMTP mock)
# ===========================================================================

class TestSendEmail:
    @patch("src.services.email_sender.smtplib.SMTP")
    def test_send_email_success(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_username="user@domain.com",
            smtp_password="password123",
            from_email="user@domain.com",
            to_email="recipient@example.com",
            subject="Test Subject",
            body_text="Hello, this is a test.",
        )

        assert result is True
        mock_smtp_class.assert_called_once_with("smtp.gmail.com", 587)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@domain.com", "password123")
        mock_server.sendmail.assert_called_once()

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_send_email_includes_text_part(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_email(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_username="user@domain.com",
            smtp_password="password123",
            from_email="user@domain.com",
            to_email="recipient@example.com",
            subject="Test",
            body_text="Plain text body here.",
        )

        # Get the raw message that was sent (content may be base64-encoded)
        call_args = mock_server.sendmail.call_args
        raw_message = call_args[0][2]
        # Decode any base64 segments to verify content
        decoded = _decode_mime_message(raw_message)
        assert "Plain text body here." in decoded

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_no_tracking_pixels_in_auto_html(self, mock_smtp_class):
        """Verify auto-generated HTML contains no tracking pixels."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_email(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_username="user@domain.com",
            smtp_password="password123",
            from_email="user@domain.com",
            to_email="recipient@example.com",
            subject="Test",
            body_text="No tracking please.",
        )

        raw_message = mock_server.sendmail.call_args[0][2]
        assert "<img" not in raw_message
        assert "1x1" not in raw_message
        assert "tracking" not in raw_message.lower()
        assert "pixel" not in raw_message.lower()

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_no_tracking_pixels_in_custom_html(self, mock_smtp_class):
        """Verify supplied HTML is sent as-is without adding tracking."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        clean_html = "<html><body><p>Clean email</p></body></html>"
        send_email(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_username="user@domain.com",
            smtp_password="password123",
            from_email="user@domain.com",
            to_email="recipient@example.com",
            subject="Test",
            body_text="Plain text",
            body_html=clean_html,
        )

        raw_message = mock_server.sendmail.call_args[0][2]
        assert "<img" not in raw_message
        assert "tracking" not in raw_message.lower()

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_send_email_failure_returns_false(self, mock_smtp_class):
        import smtplib as real_smtplib
        mock_server = MagicMock()
        mock_server.sendmail.side_effect = real_smtplib.SMTPException("Connection failed")
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_username="user@domain.com",
            smtp_password="password123",
            from_email="user@domain.com",
            to_email="bad@example.com",
            subject="Test",
            body_text="This will fail.",
        )

        assert result is False

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_message_headers(self, mock_smtp_class):
        """Verify From, To, and Subject headers are set correctly."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_email(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_username="sender@domain.com",
            smtp_password="pwd",
            from_email="sender@domain.com",
            to_email="recipient@domain.com",
            subject="Important Subject",
            body_text="Body content.",
        )

        raw = mock_server.sendmail.call_args[0][2]
        assert "From: sender@domain.com" in raw
        assert "To: recipient@domain.com" in raw
        assert "Subject: Important Subject" in raw

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_multipart_alternative(self, mock_smtp_class):
        """Verify the message is multipart/alternative."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        send_email(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_username="user@d.com",
            smtp_password="pwd",
            from_email="user@d.com",
            to_email="r@d.com",
            subject="Multi",
            body_text="Text version",
        )

        raw = mock_server.sendmail.call_args[0][2]
        assert "multipart/alternative" in raw


# ===========================================================================
# Tests: _text_to_clean_html
# ===========================================================================

class TestTextToCleanHtml:
    def test_basic_conversion(self):
        html = _text_to_clean_html("Hello World")
        assert "<p>" in html
        assert "Hello World" in html
        assert "<html" in html

    def test_no_tracking_pixels(self):
        html = _text_to_clean_html("Some email body text here.")
        assert "<img" not in html
        assert "tracking" not in html.lower()
        assert "pixel" not in html.lower()

    def test_preserves_paragraphs(self):
        text = "First paragraph.\n\nSecond paragraph."
        html = _text_to_clean_html(text)
        assert "<p>First paragraph.</p>" in html
        assert "<p>Second paragraph.</p>" in html

    def test_preserves_line_breaks(self):
        text = "Line one.\nLine two."
        html = _text_to_clean_html(text)
        assert "<br>" in html

    def test_escapes_html_entities(self):
        text = "Use <script> & other tags"
        html = _text_to_clean_html(text)
        assert "&lt;script&gt;" in html
        assert "&amp;" in html

    def test_has_body_tags(self):
        html = _text_to_clean_html("Content")
        assert "<body>" in html
        assert "</body>" in html


# ===========================================================================
# Tests: send_campaign_email (integration)
# ===========================================================================

class TestSendCampaignEmail:
    @patch("src.services.email_sender.smtplib.SMTP")
    def test_sends_email_and_logs_event(
        self, mock_smtp_class, conn, sample_contact, sample_campaign,
        sample_template, sample_config
    ):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        enroll_contact(conn, sample_contact, sample_campaign, user_id=TEST_USER_ID)

        result = send_campaign_email(
            conn, sample_contact, sample_campaign, sample_template, sample_config, user_id=1
        )

        assert result is True

        # Verify event was logged
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM events WHERE contact_id = %s AND event_type = 'email_sent'",
            (sample_contact,),
        )
        events = cursor.fetchall()
        assert len(events) == 1
        assert events[0]["campaign_id"] == sample_campaign
        assert events[0]["template_id"] == sample_template

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_advances_step(
        self, mock_smtp_class, conn, sample_contact, sample_campaign,
        sample_template, sample_config
    ):
        _mock_smtp(mock_smtp_class)

        # Need 2 steps so send can advance from step 1 to step 2
        t2 = create_template(
            conn, name="Follow Up v1 A", channel="email",
            body_template="Follow up {{ first_name }}.",
            subject="Following up", user_id=TEST_USER_ID,
        )
        add_sequence_step(conn, sample_campaign, 1, "email", sample_template, user_id=TEST_USER_ID)
        add_sequence_step(conn, sample_campaign, 2, "email", t2, user_id=TEST_USER_ID)

        enroll_contact(conn, sample_contact, sample_campaign, user_id=TEST_USER_ID)
        status_before = get_contact_campaign_status(conn, sample_contact, sample_campaign, user_id=1)
        step_before = status_before["current_step"]

        send_campaign_email(
            conn, sample_contact, sample_campaign, sample_template, sample_config, user_id=1
        )

        status_after = get_contact_campaign_status(conn, sample_contact, sample_campaign, user_id=1)
        assert status_after["current_step"] == step_before + 1

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_skips_unsubscribed_contact(
        self, mock_smtp_class, conn, sample_contact, sample_campaign,
        sample_template, sample_config
    ):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        # Unsubscribe the contact first
        process_unsubscribe(conn, "alice@example.com")
        enroll_contact(conn, sample_contact, sample_campaign, user_id=TEST_USER_ID)

        result = send_campaign_email(
            conn, sample_contact, sample_campaign, sample_template, sample_config, user_id=1
        )

        assert result is False
        mock_server.sendmail.assert_not_called()

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_gdpr_limit_blocks_third_email(
        self, mock_smtp_class, conn, gdpr_contact, sample_campaign,
        sample_template, sample_config
    ):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        enroll_contact(conn, gdpr_contact, sample_campaign, user_id=TEST_USER_ID)

        # Send 2 emails (the GDPR limit)
        log_event(conn, gdpr_contact, "email_sent", campaign_id=sample_campaign, user_id=TEST_USER_ID)
        log_event(conn, gdpr_contact, "email_sent", campaign_id=sample_campaign, user_id=TEST_USER_ID)

        result = send_campaign_email(
            conn, gdpr_contact, sample_campaign, sample_template, sample_config, user_id=1
        )

        assert result is False
        mock_server.sendmail.assert_not_called()

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_nonexistent_contact_returns_false(
        self, mock_smtp_class, conn, sample_campaign, sample_template, sample_config
    ):
        result = send_campaign_email(
            conn, 99999, sample_campaign, sample_template, sample_config, user_id=1
        )
        assert result is False

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_nonexistent_template_returns_false(
        self, mock_smtp_class, conn, sample_contact, sample_campaign, sample_config
    ):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        enroll_contact(conn, sample_contact, sample_campaign, user_id=TEST_USER_ID)

        result = send_campaign_email(
            conn, sample_contact, sample_campaign, 99999, sample_config, user_id=1
        )
        assert result is False

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_email_contains_compliance_footer(
        self, mock_smtp_class, conn, sample_contact, sample_campaign,
        sample_template, sample_config
    ):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        enroll_contact(conn, sample_contact, sample_campaign, user_id=TEST_USER_ID)

        send_campaign_email(
            conn, sample_contact, sample_campaign, sample_template, sample_config, user_id=1
        )

        raw_message = mock_server.sendmail.call_args[0][2]
        decoded = _decode_mime_message(raw_message)
        assert "Test Company, 123 Main St, New York, NY 10001" in decoded
        assert "Unsubscribe" in decoded

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_email_no_tracking_pixels(
        self, mock_smtp_class, conn, sample_contact, sample_campaign,
        sample_template, sample_config
    ):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        enroll_contact(conn, sample_contact, sample_campaign, user_id=TEST_USER_ID)

        send_campaign_email(
            conn, sample_contact, sample_campaign, sample_template, sample_config, user_id=1
        )

        raw_message = mock_server.sendmail.call_args[0][2]
        assert "<img" not in raw_message
        assert "1x1" not in raw_message
        assert "tracking" not in raw_message.lower()


# ===========================================================================
# Tests: Email templates have no tracking pixels
# ===========================================================================

class TestTemplatesNoTrackingPixels:
    """Verify that all email templates produce output with no tracking."""

    TEMPLATES = [
        "email/cold_outreach_v1_a.txt",
        "email/cold_outreach_v1_b.txt",
        "email/follow_up_v1.txt",
        "email/breakup_v1.txt",
    ]

    CONTEXT = {
        "first_name": "Test",
        "company_name": "Test Fund",
        "calendly_url": "https://calendly.com/helmutm",
        "unsubscribe_url": "mailto:test@domain.com?subject=Unsubscribe",
        "physical_address": "Test Address",
    }

    @pytest.mark.parametrize("template_path", TEMPLATES)
    def test_no_img_tags(self, template_path):
        result = render_template(template_path, self.CONTEXT)
        assert "<img" not in result

    @pytest.mark.parametrize("template_path", TEMPLATES)
    def test_no_tracking_keywords(self, template_path):
        result = render_template(template_path, self.CONTEXT)
        assert "tracking" not in result.lower()
        assert "pixel" not in result.lower()

    @pytest.mark.parametrize("template_path", TEMPLATES)
    def test_contains_calendly_link(self, template_path):
        result = render_template(template_path, self.CONTEXT)
        assert "https://calendly.com/helmutm" in result

    @pytest.mark.parametrize("template_path", TEMPLATES)
    def test_contains_first_name(self, template_path):
        result = render_template(template_path, self.CONTEXT)
        assert "Test" in result


# ===========================================================================
# Tests: LinkedIn template constraints
# ===========================================================================

class TestLinkedInTemplates:
    def test_connect_note_under_300_chars(self):
        context = {
            "first_name": "Alexandra",
            "company_name": "Galaxy Digital Holdings International",
            "calendly_url": "https://calendly.com/helmutm",
        }
        result = render_template("linkedin/connect_note_v1.txt", context)
        assert len(result.strip()) <= 300, (
            f"Connect note is {len(result.strip())} chars, must be <= 300"
        )

    def test_connect_note_is_concise(self):
        context = {
            "first_name": "Bob",
            "company_name": "Fund",
            "calendly_url": "https://calendly.com/helmutm",
        }
        result = render_template("linkedin/connect_note_v1.txt", context)
        # Should be a single message, no multiple paragraphs
        assert result.strip().count("\n\n") == 0

    def test_message_contains_calendly(self):
        context = {
            "first_name": "Carol",
            "company_name": "Crypto Co",
            "calendly_url": "https://calendly.com/helmutm",
        }
        result = render_template("linkedin/message_v1.txt", context)
        assert "https://calendly.com/helmutm" in result


# ---------------------------------------------------------------------------
# Auto-sequence advancement tests
# ---------------------------------------------------------------------------

def _mock_smtp(mock_smtp_class):
    """Configure SMTP mock for send_campaign_email tests."""
    mock_server = MagicMock()
    mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
    mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)
    return mock_server


class TestAutoSequenceAdvancement:
    """After sending an email, the contact should auto-advance to the next step
    with the correct next_action_date, and approval state should be reset."""

    @pytest.fixture
    def multi_step_campaign(self, conn, sample_template):
        """Campaign with 3 email steps: delay 0, delay 3, delay 7."""
        camp_id = create_campaign(conn, "Multi-Step Test", user_id=TEST_USER_ID)
        t2 = create_template(
            conn, name="Follow Up", channel="email",
            body_template="Follow up {{ first_name }}.",
            subject="Following up", user_id=TEST_USER_ID,
        )
        t3 = create_template(
            conn, name="Breakup", channel="email",
            body_template="Last chance {{ first_name }}.",
            subject="Final note", user_id=TEST_USER_ID,
        )
        add_sequence_step(conn, camp_id, 1, "email", sample_template, delay_days=0, user_id=TEST_USER_ID)
        add_sequence_step(conn, camp_id, 2, "email", t2, delay_days=3, user_id=TEST_USER_ID)
        add_sequence_step(conn, camp_id, 3, "email", t3, delay_days=7, user_id=TEST_USER_ID)
        return camp_id

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_sets_next_action_date_after_send(
        self, mock_smtp_class, conn, sample_contact, multi_step_campaign,
        sample_template, sample_config,
    ):
        _mock_smtp(mock_smtp_class)
        enroll_contact(conn, sample_contact, multi_step_campaign, user_id=TEST_USER_ID)
        send_campaign_email(
            conn, sample_contact, multi_step_campaign, sample_template, sample_config, user_id=1,
        )

        status = get_contact_campaign_status(conn, sample_contact, multi_step_campaign, user_id=1)
        assert status["current_step"] == 2
        expected_date = date.today() + timedelta(days=3)
        assert str(status["next_action_date"]) == expected_date.isoformat()

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_clears_approved_at_on_advance(
        self, mock_smtp_class, conn, sample_contact, multi_step_campaign,
        sample_template, sample_config,
    ):
        _mock_smtp(mock_smtp_class)
        enroll_contact(conn, sample_contact, multi_step_campaign, user_id=TEST_USER_ID)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE contact_campaign_status SET approved_at = NOW() WHERE contact_id = %s AND campaign_id = %s",
            (sample_contact, multi_step_campaign),
        )
        conn.commit()

        send_campaign_email(
            conn, sample_contact, multi_step_campaign, sample_template, sample_config, user_id=1,
        )

        status = get_contact_campaign_status(conn, sample_contact, multi_step_campaign, user_id=1)
        assert status["approved_at"] is None, "approved_at should be cleared after advancing step"
        assert status["sent_at"] is None, "sent_at should be cleared after advancing step"

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_clears_scheduled_for_on_advance(
        self, mock_smtp_class, conn, sample_contact, multi_step_campaign,
        sample_template, sample_config,
    ):
        _mock_smtp(mock_smtp_class)
        enroll_contact(conn, sample_contact, multi_step_campaign, user_id=TEST_USER_ID)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE contact_campaign_status SET scheduled_for = NOW() WHERE contact_id = %s AND campaign_id = %s",
            (sample_contact, multi_step_campaign),
        )
        conn.commit()

        send_campaign_email(
            conn, sample_contact, multi_step_campaign, sample_template, sample_config, user_id=1,
        )

        status = get_contact_campaign_status(conn, sample_contact, multi_step_campaign, user_id=1)
        assert status["scheduled_for"] is None, "scheduled_for should be cleared after advancing step"

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_last_step_stays_in_progress(
        self, mock_smtp_class, conn, sample_contact, sample_config,
    ):
        """Contact at the last step should stay in_progress for reply detection."""
        _mock_smtp(mock_smtp_class)
        camp_id = create_campaign(conn, "Single Step", user_id=TEST_USER_ID)
        tmpl = create_template(
            conn, name="Only Email", channel="email",
            body_template="Hi {{ first_name }}.",
            subject="Hello", user_id=TEST_USER_ID,
        )
        add_sequence_step(conn, camp_id, 1, "email", tmpl, delay_days=0, user_id=TEST_USER_ID)
        enroll_contact(conn, sample_contact, camp_id, user_id=TEST_USER_ID)

        send_campaign_email(conn, sample_contact, camp_id, tmpl, sample_config, user_id=1)

        status = get_contact_campaign_status(conn, sample_contact, camp_id, user_id=1)
        assert status["current_step"] == 1, "Should stay at step 1 (no next step)"

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_delay_zero_sets_today(
        self, mock_smtp_class, conn, sample_contact, sample_config,
    ):
        """A next step with delay_days=0 should set next_action_date to today."""
        _mock_smtp(mock_smtp_class)
        camp_id = create_campaign(conn, "Zero Delay", user_id=TEST_USER_ID)
        t1 = create_template(conn, name="Step1", channel="email",
                             body_template="Hi {{ first_name }}.", subject="S1", user_id=TEST_USER_ID)
        t2 = create_template(conn, name="Step2", channel="email",
                             body_template="Hi again {{ first_name }}.", subject="S2", user_id=TEST_USER_ID)
        add_sequence_step(conn, camp_id, 1, "email", t1, delay_days=0, user_id=TEST_USER_ID)
        add_sequence_step(conn, camp_id, 2, "email", t2, delay_days=0, user_id=TEST_USER_ID)
        enroll_contact(conn, sample_contact, camp_id, user_id=TEST_USER_ID)

        send_campaign_email(conn, sample_contact, camp_id, t1, sample_config, user_id=1)

        status = get_contact_campaign_status(conn, sample_contact, camp_id, user_id=1)
        assert str(status["next_action_date"]) == date.today().isoformat()
