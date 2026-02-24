"""Comprehensive tests for newsletter pipeline (Phase 5).

Tests subscriber management, auto-subscription rules (GDPR vs non-GDPR),
Markdown-to-HTML rendering, compliance footers, and newsletter sending.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.database import get_connection, run_migrations
from src.models.campaigns import (
    create_campaign,
    enroll_contact,
    log_event,
    update_contact_campaign_status,
)
from src.services.newsletter import (
    get_newsletter_subscribers,
    auto_subscribe_eligible,
    subscribe_contact,
    unsubscribe_contact,
    render_newsletter,
    send_newsletter,
    _extract_subject,
)


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
    """Insert a non-GDPR company and return its id."""
    cursor = conn.execute(
        "INSERT INTO companies (name, name_normalized, country, is_gdpr) VALUES (?, ?, ?, ?)",
        ("Acme Crypto Fund", "acme crypto fund", "United States", 0),
    )
    conn.commit()
    return cursor.lastrowid


@pytest.fixture
def gdpr_company(conn):
    """Insert a GDPR-subject company and return its id."""
    cursor = conn.execute(
        "INSERT INTO companies (name, name_normalized, country, is_gdpr) VALUES (?, ?, ?, ?)",
        ("Berlin Capital GmbH", "berlin capital gmbh", "Germany", 1),
    )
    conn.commit()
    return cursor.lastrowid


@pytest.fixture
def sample_contact(conn, sample_company):
    """Insert a non-GDPR contact and return its id."""
    cursor = conn.execute(
        "INSERT INTO contacts (company_id, first_name, last_name, full_name, email, source, is_gdpr) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sample_company, "Alice", "Smith", "Alice Smith", "alice@example.com", "csv", 0),
    )
    conn.commit()
    return cursor.lastrowid


@pytest.fixture
def gdpr_contact(conn, gdpr_company):
    """Insert a GDPR-subject contact and return its id."""
    cursor = conn.execute(
        "INSERT INTO contacts (company_id, first_name, last_name, full_name, email, source, is_gdpr) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (gdpr_company, "Hans", "Mueller", "Hans Mueller", "hans@berlin-cap.de", "csv", 1),
    )
    conn.commit()
    return cursor.lastrowid


@pytest.fixture
def sample_campaign(conn):
    """Create and return a campaign id."""
    return create_campaign(conn, "Q1 Outreach", description="Test campaign")


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


@pytest.fixture
def newsletter_md(tmp_path):
    """Create a test newsletter markdown file and return its path."""
    md_file = tmp_path / "2026-02-24-test.md"
    md_file.write_text(
        "# Monthly Market Update\n\n"
        "Hi there,\n\n"
        "Here's what's been happening in the crypto trading space this month.\n\n"
        "## Market Highlights\n\n"
        "- BTC maintained strong momentum above key support levels\n"
        "- DeFi activity continued to grow with new protocols launching\n\n"
        "## Our Performance\n\n"
        "We continue to deliver consistent risk-adjusted returns.\n\n"
        "Interested in learning more? [Book a call]({{ calendly_url }}).\n\n"
        "Best regards,\n"
        "Helmut\n"
    )
    return str(md_file)


def _make_subscribed_contacts(conn, company_id, count=3):
    """Helper: create multiple subscribed contacts, returning their ids."""
    ids = []
    for i in range(count):
        cursor = conn.execute(
            "INSERT INTO contacts (company_id, first_name, last_name, full_name, email, source, "
            "is_gdpr, newsletter_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (company_id, f"Sub{i}", f"User{i}", f"Sub{i} User{i}",
             f"sub{i}@example.com", "csv", 0, "subscribed"),
        )
        ids.append(cursor.lastrowid)
    conn.commit()
    return ids


# ===========================================================================
# Tests: get_newsletter_subscribers
# ===========================================================================

class TestGetNewsletterSubscribers:
    def test_returns_subscribed_contacts(self, conn, sample_company):
        ids = _make_subscribed_contacts(conn, sample_company, count=3)
        result = get_newsletter_subscribers(conn)
        assert len(result) == 3
        result_ids = [r["id"] for r in result]
        for cid in ids:
            assert cid in result_ids

    def test_excludes_none_status(self, conn, sample_contact):
        """Contacts with newsletter_status='none' should NOT be returned."""
        result = get_newsletter_subscribers(conn)
        assert len(result) == 0

    def test_excludes_unsubscribed(self, conn, sample_company):
        """Contacts who unsubscribed should NOT be returned."""
        cursor = conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, "
            "newsletter_status, unsubscribed) VALUES (?, ?, ?, ?, ?, ?)",
            (sample_company, "Gone", "gone@example.com", "csv", "unsubscribed", 1),
        )
        conn.commit()
        result = get_newsletter_subscribers(conn)
        assert len(result) == 0

    def test_excludes_subscribed_but_unsubscribed_flag(self, conn, sample_company):
        """Even if status says subscribed, unsubscribed=1 should exclude."""
        cursor = conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, "
            "newsletter_status, unsubscribed) VALUES (?, ?, ?, ?, ?, ?)",
            (sample_company, "Weird", "weird@example.com", "csv", "subscribed", 1),
        )
        conn.commit()
        result = get_newsletter_subscribers(conn)
        assert len(result) == 0

    def test_excludes_contacts_without_email(self, conn, sample_company):
        """Contacts without email should NOT be returned even if subscribed."""
        conn.execute(
            "INSERT INTO contacts (company_id, first_name, source, "
            "newsletter_status) VALUES (?, ?, ?, ?)",
            (sample_company, "NoEmail", "csv", "subscribed"),
        )
        conn.commit()
        result = get_newsletter_subscribers(conn)
        assert len(result) == 0

    def test_empty_database(self, conn):
        result = get_newsletter_subscribers(conn)
        assert result == []

    def test_mixed_statuses(self, conn, sample_company):
        """Only subscribed contacts with unsubscribed=0 are returned."""
        # subscribed
        conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, newsletter_status) "
            "VALUES (?, ?, ?, ?, ?)",
            (sample_company, "Sub", "sub@example.com", "csv", "subscribed"),
        )
        # none
        conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, newsletter_status) "
            "VALUES (?, ?, ?, ?, ?)",
            (sample_company, "None", "none@example.com", "csv", "none"),
        )
        # unsubscribed
        conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, newsletter_status, unsubscribed) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sample_company, "Unsub", "unsub@example.com", "csv", "unsubscribed", 1),
        )
        conn.commit()

        result = get_newsletter_subscribers(conn)
        assert len(result) == 1
        assert result[0]["email"] == "sub@example.com"


# ===========================================================================
# Tests: auto_subscribe_eligible
# ===========================================================================

class TestAutoSubscribeEligible:
    def test_subscribes_non_gdpr_no_response(
        self, conn, sample_contact, sample_campaign
    ):
        """Non-GDPR contacts with no_response status are auto-subscribed."""
        enroll_contact(conn, sample_contact, sample_campaign)
        update_contact_campaign_status(
            conn, sample_contact, sample_campaign, status="no_response"
        )

        result = auto_subscribe_eligible(conn, sample_campaign)
        assert result["subscribed"] == 1
        assert result["skipped_gdpr"] == 0
        assert result["already_subscribed"] == 0

        # Verify database updated
        row = conn.execute(
            "SELECT newsletter_status FROM contacts WHERE id = ?",
            (sample_contact,),
        ).fetchone()
        assert row["newsletter_status"] == "subscribed"

    def test_skips_gdpr_contacts(
        self, conn, gdpr_contact, sample_campaign
    ):
        """GDPR contacts should NOT be auto-subscribed."""
        enroll_contact(conn, gdpr_contact, sample_campaign)
        update_contact_campaign_status(
            conn, gdpr_contact, sample_campaign, status="no_response"
        )

        result = auto_subscribe_eligible(conn, sample_campaign)
        assert result["subscribed"] == 0
        assert result["skipped_gdpr"] == 1

        # Verify database NOT updated
        row = conn.execute(
            "SELECT newsletter_status FROM contacts WHERE id = ?",
            (gdpr_contact,),
        ).fetchone()
        assert row["newsletter_status"] == "none"

    def test_skips_gdpr_via_company(self, conn, gdpr_company, sample_campaign):
        """Contact is non-GDPR but company is GDPR -- should skip."""
        cursor = conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, is_gdpr) "
            "VALUES (?, ?, ?, ?, ?)",
            (gdpr_company, "Max", "max@test.de", "csv", 0),
        )
        conn.commit()
        contact_id = cursor.lastrowid

        enroll_contact(conn, contact_id, sample_campaign)
        update_contact_campaign_status(
            conn, contact_id, sample_campaign, status="no_response"
        )

        result = auto_subscribe_eligible(conn, sample_campaign)
        assert result["subscribed"] == 0
        assert result["skipped_gdpr"] == 1

    def test_skips_already_subscribed(
        self, conn, sample_company, sample_campaign
    ):
        """Already subscribed contacts should be counted but not re-subscribed."""
        cursor = conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, "
            "is_gdpr, newsletter_status) VALUES (?, ?, ?, ?, ?, ?)",
            (sample_company, "Already", "already@example.com", "csv", 0, "subscribed"),
        )
        conn.commit()
        contact_id = cursor.lastrowid

        enroll_contact(conn, contact_id, sample_campaign)
        update_contact_campaign_status(
            conn, contact_id, sample_campaign, status="no_response"
        )

        result = auto_subscribe_eligible(conn, sample_campaign)
        assert result["subscribed"] == 0
        assert result["already_subscribed"] == 1

    def test_skips_already_unsubscribed(
        self, conn, sample_company, sample_campaign
    ):
        """Previously unsubscribed contacts should NOT be re-subscribed."""
        cursor = conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, "
            "is_gdpr, newsletter_status, unsubscribed) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sample_company, "Former", "former@example.com", "csv", 0, "unsubscribed", 1),
        )
        conn.commit()
        contact_id = cursor.lastrowid

        enroll_contact(conn, contact_id, sample_campaign)
        update_contact_campaign_status(
            conn, contact_id, sample_campaign, status="no_response"
        )

        result = auto_subscribe_eligible(conn, sample_campaign)
        assert result["subscribed"] == 0
        assert result["already_subscribed"] == 1

    def test_ignores_non_no_response_status(
        self, conn, sample_contact, sample_campaign
    ):
        """Contacts with other statuses (queued, in_progress, etc.) are ignored."""
        enroll_contact(conn, sample_contact, sample_campaign)
        # status is 'queued' by default -- should not be subscribed

        result = auto_subscribe_eligible(conn, sample_campaign)
        assert result["subscribed"] == 0
        assert result["skipped_gdpr"] == 0
        assert result["already_subscribed"] == 0

    def test_ignores_contacts_without_email(
        self, conn, sample_company, sample_campaign
    ):
        """Contacts without email should not be subscribed."""
        cursor = conn.execute(
            "INSERT INTO contacts (company_id, first_name, source, is_gdpr) "
            "VALUES (?, ?, ?, ?)",
            (sample_company, "NoEmail", "csv", 0),
        )
        conn.commit()
        contact_id = cursor.lastrowid

        enroll_contact(conn, contact_id, sample_campaign)
        update_contact_campaign_status(
            conn, contact_id, sample_campaign, status="no_response"
        )

        result = auto_subscribe_eligible(conn, sample_campaign)
        assert result["subscribed"] == 0

    def test_mixed_contacts(
        self, conn, sample_company, gdpr_company, sample_campaign
    ):
        """Test with a mix of GDPR, non-GDPR, and already subscribed contacts."""
        # Non-GDPR, no_response -> should subscribe
        c1 = conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, is_gdpr) "
            "VALUES (?, ?, ?, ?, ?)",
            (sample_company, "NonGdpr1", "nongdpr1@example.com", "csv", 0),
        ).lastrowid

        # Non-GDPR, no_response -> should subscribe
        c2 = conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, is_gdpr) "
            "VALUES (?, ?, ?, ?, ?)",
            (sample_company, "NonGdpr2", "nongdpr2@example.com", "csv", 0),
        ).lastrowid

        # GDPR, no_response -> should skip
        c3 = conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, is_gdpr) "
            "VALUES (?, ?, ?, ?, ?)",
            (gdpr_company, "Gdpr1", "gdpr1@example.de", "csv", 1),
        ).lastrowid

        # Non-GDPR, no_response, already subscribed -> should count as already
        c4 = conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, is_gdpr, newsletter_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sample_company, "AlreadySub", "already@example.com", "csv", 0, "subscribed"),
        ).lastrowid

        conn.commit()

        for cid in [c1, c2, c3, c4]:
            enroll_contact(conn, cid, sample_campaign)
            update_contact_campaign_status(
                conn, cid, sample_campaign, status="no_response"
            )

        result = auto_subscribe_eligible(conn, sample_campaign)
        assert result["subscribed"] == 2
        assert result["skipped_gdpr"] == 1
        assert result["already_subscribed"] == 1


# ===========================================================================
# Tests: subscribe_contact
# ===========================================================================

class TestSubscribeContact:
    def test_subscribes_existing_contact(self, conn, sample_contact):
        result = subscribe_contact(conn, sample_contact)
        assert result is True

        row = conn.execute(
            "SELECT newsletter_status FROM contacts WHERE id = ?",
            (sample_contact,),
        ).fetchone()
        assert row["newsletter_status"] == "subscribed"

    def test_nonexistent_contact_returns_false(self, conn):
        result = subscribe_contact(conn, 99999)
        assert result is False

    def test_idempotent(self, conn, sample_contact):
        subscribe_contact(conn, sample_contact)
        result = subscribe_contact(conn, sample_contact)
        assert result is True

        row = conn.execute(
            "SELECT newsletter_status FROM contacts WHERE id = ?",
            (sample_contact,),
        ).fetchone()
        assert row["newsletter_status"] == "subscribed"


# ===========================================================================
# Tests: unsubscribe_contact
# ===========================================================================

class TestUnsubscribeContact:
    def test_unsubscribes_existing_contact(self, conn, sample_contact):
        subscribe_contact(conn, sample_contact)
        result = unsubscribe_contact(conn, sample_contact)
        assert result is True

        row = conn.execute(
            "SELECT newsletter_status, unsubscribed FROM contacts WHERE id = ?",
            (sample_contact,),
        ).fetchone()
        assert row["newsletter_status"] == "unsubscribed"
        assert row["unsubscribed"] == 1

    def test_nonexistent_contact_returns_false(self, conn):
        result = unsubscribe_contact(conn, 99999)
        assert result is False

    def test_sets_both_fields(self, conn, sample_contact):
        """Both newsletter_status and unsubscribed flag are set."""
        subscribe_contact(conn, sample_contact)
        unsubscribe_contact(conn, sample_contact)

        row = conn.execute(
            "SELECT newsletter_status, unsubscribed FROM contacts WHERE id = ?",
            (sample_contact,),
        ).fetchone()
        assert row["newsletter_status"] == "unsubscribed"
        assert row["unsubscribed"] == 1

    def test_unsubscribed_contact_not_in_subscribers(self, conn, sample_contact):
        """After unsubscribe, contact should not appear in subscriber list."""
        subscribe_contact(conn, sample_contact)
        unsubscribe_contact(conn, sample_contact)

        subscribers = get_newsletter_subscribers(conn)
        ids = [s["id"] for s in subscribers]
        assert sample_contact not in ids


# ===========================================================================
# Tests: render_newsletter
# ===========================================================================

class TestRenderNewsletter:
    def test_produces_html_and_text(self, newsletter_md, sample_config):
        html, text = render_newsletter(newsletter_md, sample_config)
        assert isinstance(html, str)
        assert isinstance(text, str)
        assert len(html) > 0
        assert len(text) > 0

    def test_html_contains_heading(self, newsletter_md, sample_config):
        html, _ = render_newsletter(newsletter_md, sample_config)
        assert "Monthly Market Update" in html

    def test_html_contains_body_tags(self, newsletter_md, sample_config):
        html, _ = render_newsletter(newsletter_md, sample_config)
        assert "<html" in html
        assert "<body>" in html
        assert "</body>" in html

    def test_no_tracking_pixels(self, newsletter_md, sample_config):
        html, _ = render_newsletter(newsletter_md, sample_config)
        assert "<img" not in html
        assert "1x1" not in html
        assert "tracking" not in html.lower()
        assert "pixel" not in html.lower()

    def test_no_images(self, newsletter_md, sample_config):
        html, _ = render_newsletter(newsletter_md, sample_config)
        assert "<img" not in html

    def test_includes_compliance_footer_html(self, newsletter_md, sample_config):
        html, _ = render_newsletter(newsletter_md, sample_config)
        assert "Unsubscribe" in html
        assert "Test Company, 123 Main St, New York, NY 10001" in html

    def test_includes_compliance_footer_text(self, newsletter_md, sample_config):
        _, text = render_newsletter(newsletter_md, sample_config)
        assert "unsubscribe" in text.lower()
        assert "Test Company, 123 Main St, New York, NY 10001" in text

    def test_renders_jinja2_variables(self, newsletter_md, sample_config):
        html, text = render_newsletter(newsletter_md, sample_config)
        assert "https://calendly.com/helmutm" in html
        assert "https://calendly.com/helmutm" in text

    def test_jinja2_variables_not_raw(self, newsletter_md, sample_config):
        """Jinja2 syntax should be rendered, not left as raw {{ }}."""
        html, text = render_newsletter(newsletter_md, sample_config)
        assert "{{ calendly_url }}" not in html
        assert "{{ calendly_url }}" not in text

    def test_markdown_converted_to_html(self, newsletter_md, sample_config):
        html, _ = render_newsletter(newsletter_md, sample_config)
        # Markdown headings should be converted to HTML
        assert "<h1>" in html or "<h1 " in html
        assert "<h2>" in html or "<h2 " in html
        # Markdown lists should be converted
        assert "<li>" in html
        # Markdown links should be converted
        assert "<a " in html

    def test_unsubscribe_link_is_mailto(self, newsletter_md, sample_config):
        html, text = render_newsletter(newsletter_md, sample_config)
        assert "mailto:outreach@test-domain.com" in html
        assert "mailto:outreach@test-domain.com" in text

    def test_file_not_found_raises(self, sample_config):
        with pytest.raises(FileNotFoundError):
            render_newsletter("/nonexistent/path/newsletter.md", sample_config)

    def test_html_has_clean_minimal_style(self, newsletter_md, sample_config):
        """HTML should have basic inline styles, no external CSS."""
        html, _ = render_newsletter(newsletter_md, sample_config)
        assert "font-family" in html
        # Should not reference external stylesheets
        assert '<link rel="stylesheet"' not in html


# ===========================================================================
# Tests: render_newsletter with actual data/newsletters file
# ===========================================================================

class TestRenderActualNewsletter:
    """Test rendering the actual newsletter file in data/newsletters/."""

    NEWSLETTER_PATH = str(
        Path(__file__).parent.parent / "data" / "newsletters" / "2026-02-24-test.md"
    )

    def test_actual_file_renders(self, sample_config):
        if not Path(self.NEWSLETTER_PATH).exists():
            pytest.skip("Actual newsletter file not found")
        html, text = render_newsletter(self.NEWSLETTER_PATH, sample_config)
        assert "Monthly Market Update" in html
        assert "Monthly Market Update" in text

    def test_actual_file_no_tracking(self, sample_config):
        if not Path(self.NEWSLETTER_PATH).exists():
            pytest.skip("Actual newsletter file not found")
        html, _ = render_newsletter(self.NEWSLETTER_PATH, sample_config)
        assert "<img" not in html
        assert "tracking" not in html.lower()


# ===========================================================================
# Tests: send_newsletter
# ===========================================================================

class TestSendNewsletter:
    @patch("src.services.newsletter.send_email")
    def test_dry_run_returns_correct_counts(
        self, mock_send, conn, sample_company, newsletter_md, sample_config
    ):
        ids = _make_subscribed_contacts(conn, sample_company, count=3)

        result = send_newsletter(conn, newsletter_md, sample_config, dry_run=True)

        assert result["subscribers"] == 3
        assert result["sent"] == 0
        assert result["failed"] == 0
        mock_send.assert_not_called()

    @patch("src.services.newsletter.send_email")
    def test_sends_to_all_subscribers(
        self, mock_send, conn, sample_company, newsletter_md, sample_config
    ):
        mock_send.return_value = True
        ids = _make_subscribed_contacts(conn, sample_company, count=3)

        result = send_newsletter(conn, newsletter_md, sample_config)

        assert result["sent"] == 3
        assert result["failed"] == 0
        assert result["subscribers"] == 3
        assert mock_send.call_count == 3

    @patch("src.services.newsletter.send_email")
    def test_logs_events(
        self, mock_send, conn, sample_company, newsletter_md, sample_config
    ):
        mock_send.return_value = True
        ids = _make_subscribed_contacts(conn, sample_company, count=2)

        send_newsletter(conn, newsletter_md, sample_config)

        events = conn.execute(
            "SELECT * FROM events WHERE event_type = 'newsletter_sent'"
        ).fetchall()
        assert len(events) == 2

        # Verify event metadata
        for event in events:
            assert event["metadata"] is not None
            meta = json.loads(event["metadata"])
            assert "subject" in meta
            assert "newsletter_file" in meta
            assert "to_email" in meta

    @patch("src.services.newsletter.send_email")
    def test_handles_send_failures(
        self, mock_send, conn, sample_company, newsletter_md, sample_config
    ):
        # First call succeeds, second fails
        mock_send.side_effect = [True, False, True]
        ids = _make_subscribed_contacts(conn, sample_company, count=3)

        result = send_newsletter(conn, newsletter_md, sample_config)

        assert result["sent"] == 2
        assert result["failed"] == 1

    @patch("src.services.newsletter.send_email")
    def test_no_events_for_failed_sends(
        self, mock_send, conn, sample_company, newsletter_md, sample_config
    ):
        mock_send.return_value = False
        ids = _make_subscribed_contacts(conn, sample_company, count=2)

        send_newsletter(conn, newsletter_md, sample_config)

        events = conn.execute(
            "SELECT * FROM events WHERE event_type = 'newsletter_sent'"
        ).fetchall()
        assert len(events) == 0

    @patch("src.services.newsletter.send_email")
    def test_no_subscribers_sends_nothing(
        self, mock_send, conn, newsletter_md, sample_config
    ):
        result = send_newsletter(conn, newsletter_md, sample_config)

        assert result["subscribers"] == 0
        assert result["sent"] == 0
        assert result["failed"] == 0
        mock_send.assert_not_called()

    @patch("src.services.newsletter.send_email")
    def test_sends_correct_subject(
        self, mock_send, conn, sample_company, newsletter_md, sample_config
    ):
        mock_send.return_value = True
        ids = _make_subscribed_contacts(conn, sample_company, count=1)

        send_newsletter(conn, newsletter_md, sample_config)

        call_kwargs = mock_send.call_args
        # Subject should be extracted from H1 heading
        assert call_kwargs[1]["subject"] == "Monthly Market Update" or \
               call_kwargs[0][6] == "Monthly Market Update"

    @patch("src.services.newsletter.send_email")
    def test_sends_html_and_text(
        self, mock_send, conn, sample_company, newsletter_md, sample_config
    ):
        mock_send.return_value = True
        ids = _make_subscribed_contacts(conn, sample_company, count=1)

        send_newsletter(conn, newsletter_md, sample_config)

        call_kwargs = mock_send.call_args
        # Verify both body_text and body_html are provided
        if call_kwargs[1]:
            assert "body_text" in call_kwargs[1]
            assert "body_html" in call_kwargs[1]
        else:
            # Positional args: body_text is arg 7, body_html is arg 8
            assert len(call_kwargs[0]) >= 8


# ===========================================================================
# Tests: _extract_subject
# ===========================================================================

class TestExtractSubject:
    def test_extracts_h1(self):
        md = "# Hello World\n\nSome content."
        assert _extract_subject(md, "fallback") == "Hello World"

    def test_uses_fallback_when_no_heading(self):
        md = "No heading here.\n\nJust content."
        assert _extract_subject(md, "my-fallback") == "my-fallback"

    def test_extracts_first_h1_only(self):
        md = "# First Heading\n\n# Second Heading\n\nContent."
        assert _extract_subject(md, "fallback") == "First Heading"

    def test_ignores_h2_headings(self):
        md = "## Not H1\n\nContent."
        assert _extract_subject(md, "fallback") == "fallback"

    def test_strips_whitespace(self):
        md = "#   Spaced Heading   \n\nContent."
        assert _extract_subject(md, "fallback") == "Spaced Heading"


# ===========================================================================
# Tests: Integration / End-to-end
# ===========================================================================

class TestNewsletterIntegration:
    def test_full_subscription_lifecycle(self, conn, sample_contact):
        """Subscribe -> verify listed -> unsubscribe -> verify not listed."""
        # Initially not subscribed
        subs = get_newsletter_subscribers(conn)
        assert len(subs) == 0

        # Subscribe
        subscribe_contact(conn, sample_contact)
        subs = get_newsletter_subscribers(conn)
        assert len(subs) == 1
        assert subs[0]["id"] == sample_contact

        # Unsubscribe
        unsubscribe_contact(conn, sample_contact)
        subs = get_newsletter_subscribers(conn)
        assert len(subs) == 0

    def test_auto_subscribe_then_unsubscribe(
        self, conn, sample_contact, sample_campaign
    ):
        """Auto-subscribe via campaign, then manually unsubscribe."""
        enroll_contact(conn, sample_contact, sample_campaign)
        update_contact_campaign_status(
            conn, sample_contact, sample_campaign, status="no_response"
        )

        auto_subscribe_eligible(conn, sample_campaign)

        # Should be subscribed
        subs = get_newsletter_subscribers(conn)
        assert len(subs) == 1

        # Unsubscribe
        unsubscribe_contact(conn, sample_contact)
        subs = get_newsletter_subscribers(conn)
        assert len(subs) == 0

    def test_auto_subscribe_respects_prior_unsubscribe(
        self, conn, sample_company, sample_campaign
    ):
        """A previously unsubscribed contact should not be auto-resubscribed."""
        cursor = conn.execute(
            "INSERT INTO contacts (company_id, first_name, email, source, "
            "is_gdpr, newsletter_status, unsubscribed) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sample_company, "Former", "former@example.com", "csv", 0, "unsubscribed", 1),
        )
        conn.commit()
        contact_id = cursor.lastrowid

        enroll_contact(conn, contact_id, sample_campaign)
        update_contact_campaign_status(
            conn, contact_id, sample_campaign, status="no_response"
        )

        result = auto_subscribe_eligible(conn, sample_campaign)
        assert result["subscribed"] == 0
        assert result["already_subscribed"] == 1

    @patch("src.services.newsletter.send_email")
    def test_full_send_workflow(
        self, mock_send, conn, sample_company, newsletter_md, sample_config
    ):
        """Full workflow: subscribe contacts, render, send, verify events."""
        mock_send.return_value = True

        # Create and subscribe contacts
        ids = _make_subscribed_contacts(conn, sample_company, count=2)

        # Send newsletter
        result = send_newsletter(conn, newsletter_md, sample_config)

        assert result["subscribers"] == 2
        assert result["sent"] == 2
        assert result["failed"] == 0

        # Verify events were logged
        events = conn.execute(
            "SELECT * FROM events WHERE event_type = 'newsletter_sent' ORDER BY id"
        ).fetchall()
        assert len(events) == 2

        # Verify each event has correct metadata
        sent_to_emails = set()
        for event in events:
            meta = json.loads(event["metadata"])
            sent_to_emails.add(meta["to_email"])
            assert meta["subject"] == "Monthly Market Update"
            assert "2026-02-24-test.md" in meta["newsletter_file"]

        assert "sub0@example.com" in sent_to_emails
        assert "sub1@example.com" in sent_to_emails
