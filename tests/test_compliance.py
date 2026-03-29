"""Edge case tests for src/services/compliance.py."""

import pytest

from src.models.database import get_connection, run_migrations
from src.models.campaigns import create_campaign, enroll_contact, log_event
from src.services.compliance import (
    add_compliance_footer,
    add_compliance_footer_html,
    build_unsubscribe_url,
    check_gdpr_email_limit,
    is_contact_gdpr,
    process_unsubscribe,
)
from tests.conftest import TEST_USER_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db(db_path):
    conn = get_connection(db_path)
    run_migrations(conn)
    return conn


def _create_company(conn, name="Acme Fund", is_gdpr=False, country="US"):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO companies (name, name_normalized, country, is_gdpr, user_id) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (name, name.lower(), country, is_gdpr, TEST_USER_ID),
    )
    company_id = cursor.fetchone()["id"]
    conn.commit()
    return company_id


def _create_contact(conn, company_id, email="test@example.com", is_gdpr=False):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO contacts (company_id, first_name, last_name, email, "
        "email_normalized, is_gdpr, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (company_id, "Test", "User", email, email.lower().strip(), is_gdpr, TEST_USER_ID),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    return contact_id


def _create_campaign(conn, name="Test Campaign"):
    return create_campaign(conn, name, user_id=TEST_USER_ID)


# ---------------------------------------------------------------------------
# Tests: build_unsubscribe_url
# ---------------------------------------------------------------------------

class TestBuildUnsubscribeUrl:
    def test_basic_url(self):
        url = build_unsubscribe_url("outreach@fund.io")
        assert url == "mailto:outreach@fund.io?subject=Unsubscribe"

    def test_empty_email(self):
        url = build_unsubscribe_url("")
        assert url == "mailto:?subject=Unsubscribe"


# ---------------------------------------------------------------------------
# Tests: add_compliance_footer (plain text)
# ---------------------------------------------------------------------------

class TestAddComplianceFooter:
    def test_basic_footer_appended(self):
        body = "Hello, let's connect."
        result = add_compliance_footer(body, "123 Main St", "mailto:unsub@x.com?subject=Unsubscribe")
        assert "123 Main St" in result
        assert "mailto:unsub@x.com?subject=Unsubscribe" in result
        assert result.startswith("Hello, let's connect.")

    def test_footer_with_empty_address(self):
        body = "Email body here."
        result = add_compliance_footer(body, "", "mailto:unsub@x.com?subject=Unsubscribe")
        # Footer should still be appended even with empty address
        assert "---" in result
        assert "mailto:unsub@x.com?subject=Unsubscribe" in result

    def test_footer_with_empty_body(self):
        result = add_compliance_footer("", "123 Main St", "mailto:unsub@x.com?subject=Unsubscribe")
        assert "123 Main St" in result
        assert result.startswith("\n---\n")

    def test_footer_separator_present(self):
        result = add_compliance_footer("Body.", "Addr", "url")
        assert "\n---\n" in result


# ---------------------------------------------------------------------------
# Tests: add_compliance_footer_html
# ---------------------------------------------------------------------------

class TestAddComplianceFooterHtml:
    def test_inserts_before_body_close(self):
        html = "<html><body><p>Hello</p></body></html>"
        result = add_compliance_footer_html(html, "123 Main St", "mailto:unsub@x.com")
        assert "123 Main St" in result
        assert result.index("Unsubscribe") < result.index("</body>")

    def test_appends_when_no_body_tag(self):
        html = "<p>Hello</p>"
        result = add_compliance_footer_html(html, "123 Main St", "mailto:unsub@x.com")
        assert result.startswith("<p>Hello</p>")
        assert "123 Main St" in result

    def test_empty_html_body(self):
        result = add_compliance_footer_html("", "123 Main St", "mailto:unsub@x.com")
        assert "123 Main St" in result

    def test_empty_address_in_html(self):
        html = "<body><p>Hi</p></body>"
        result = add_compliance_footer_html(html, "", "mailto:unsub@x.com")
        assert "<a href=" in result


# ---------------------------------------------------------------------------
# Tests: check_gdpr_email_limit
# ---------------------------------------------------------------------------

class TestCheckGdprEmailLimit:
    def test_under_limit_allows_send(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)

        # 0 emails sent, limit is 2 => allowed
        assert check_gdpr_email_limit(conn, contact_id, campaign_id) is True
        conn.close()

    def test_at_boundary_blocks_send(self, tmp_db):
        """Exactly 2 emails sent with max_emails=2 should block."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)

        log_event(conn, contact_id, "email_sent", campaign_id=campaign_id, user_id=TEST_USER_ID)
        log_event(conn, contact_id, "email_sent", campaign_id=campaign_id, user_id=TEST_USER_ID)

        assert check_gdpr_email_limit(conn, contact_id, campaign_id, max_emails=2) is False
        conn.close()

    def test_one_below_boundary_allows_send(self, tmp_db):
        """Exactly 1 email sent with max_emails=2 should still allow."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)

        log_event(conn, contact_id, "email_sent", campaign_id=campaign_id, user_id=TEST_USER_ID)

        assert check_gdpr_email_limit(conn, contact_id, campaign_id, max_emails=2) is True
        conn.close()

    def test_over_limit_blocks_send(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)

        for _ in range(5):
            log_event(conn, contact_id, "email_sent", campaign_id=campaign_id, user_id=TEST_USER_ID)

        assert check_gdpr_email_limit(conn, contact_id, campaign_id, max_emails=2) is False
        conn.close()

    def test_non_email_events_not_counted(self, tmp_db):
        """Only email_sent events count toward the limit."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)

        log_event(conn, contact_id, "call_booked", campaign_id=campaign_id, user_id=TEST_USER_ID)
        log_event(conn, contact_id, "expandi_connected", campaign_id=campaign_id, user_id=TEST_USER_ID)

        assert check_gdpr_email_limit(conn, contact_id, campaign_id, max_emails=2) is True
        conn.close()

    def test_different_campaign_events_not_counted(self, tmp_db):
        """Emails in a different campaign should not affect the limit."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_a = _create_campaign(conn, name="Campaign A")
        campaign_b = _create_campaign(conn, name="Campaign B")

        log_event(conn, contact_id, "email_sent", campaign_id=campaign_a, user_id=TEST_USER_ID)
        log_event(conn, contact_id, "email_sent", campaign_id=campaign_a, user_id=TEST_USER_ID)

        # Campaign B should be unaffected
        assert check_gdpr_email_limit(conn, contact_id, campaign_b, max_emails=2) is True
        conn.close()

    def test_custom_max_emails(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)
        campaign_id = _create_campaign(conn)

        log_event(conn, contact_id, "email_sent", campaign_id=campaign_id, user_id=TEST_USER_ID)
        log_event(conn, contact_id, "email_sent", campaign_id=campaign_id, user_id=TEST_USER_ID)
        log_event(conn, contact_id, "email_sent", campaign_id=campaign_id, user_id=TEST_USER_ID)

        # 3 sent, limit 5 => allowed
        assert check_gdpr_email_limit(conn, contact_id, campaign_id, max_emails=5) is True
        # 3 sent, limit 3 => blocked
        assert check_gdpr_email_limit(conn, contact_id, campaign_id, max_emails=3) is False
        conn.close()


# ---------------------------------------------------------------------------
# Tests: is_contact_gdpr
# ---------------------------------------------------------------------------

class TestIsContactGdpr:
    def test_non_gdpr_contact_non_gdpr_company(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn, is_gdpr=False)
        contact_id = _create_contact(conn, company_id, is_gdpr=False)

        assert is_contact_gdpr(conn, contact_id) is False
        conn.close()

    def test_gdpr_contact_flag(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn, is_gdpr=False)
        contact_id = _create_contact(conn, company_id, is_gdpr=True)

        assert is_contact_gdpr(conn, contact_id) is True
        conn.close()

    def test_gdpr_company_flag(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn, is_gdpr=True)
        contact_id = _create_contact(conn, company_id, is_gdpr=False)

        assert is_contact_gdpr(conn, contact_id) is True
        conn.close()

    def test_both_flags_set(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn, is_gdpr=True)
        contact_id = _create_contact(conn, company_id, is_gdpr=True)

        assert is_contact_gdpr(conn, contact_id) is True
        conn.close()

    def test_nonexistent_contact(self, tmp_db):
        conn = _setup_db(tmp_db)
        assert is_contact_gdpr(conn, 99999) is False
        conn.close()


# ---------------------------------------------------------------------------
# Tests: process_unsubscribe
# ---------------------------------------------------------------------------

class TestProcessUnsubscribe:
    def test_valid_unsubscribe(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        _create_contact(conn, company_id, email="unsub@example.com")

        result = process_unsubscribe(conn, "unsub@example.com", user_id=TEST_USER_ID)
        assert result is True

        # Verify contact is marked unsubscribed
        cursor = conn.cursor()
        cursor.execute(
            "SELECT unsubscribed, unsubscribed_at FROM contacts WHERE email_normalized = %s",
            ("unsub@example.com",),
        )
        row = cursor.fetchone()
        assert row["unsubscribed"] is True
        assert row["unsubscribed_at"] is not None
        conn.close()

    def test_unsubscribe_nonexistent_email(self, tmp_db):
        conn = _setup_db(tmp_db)
        result = process_unsubscribe(conn, "nobody@example.com", user_id=TEST_USER_ID)
        assert result is False
        conn.close()

    def test_unsubscribe_empty_email(self, tmp_db):
        conn = _setup_db(tmp_db)
        assert process_unsubscribe(conn, "", user_id=TEST_USER_ID) is False
        assert process_unsubscribe(conn, "   ", user_id=TEST_USER_ID) is False
        assert process_unsubscribe(conn, None, user_id=TEST_USER_ID) is False
        conn.close()

    def test_unsubscribe_case_insensitive(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        _create_contact(conn, company_id, email="Case@Example.COM")

        result = process_unsubscribe(conn, "CASE@EXAMPLE.COM", user_id=TEST_USER_ID)
        assert result is True
        conn.close()
