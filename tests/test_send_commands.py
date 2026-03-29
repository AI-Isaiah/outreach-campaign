"""Tests for send/status/unsubscribe CLI commands (Task 21)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.models.database import get_connection, run_migrations
from src.models.campaigns import (
    create_campaign,
    create_template,
    add_sequence_step,
    enroll_contact,
    get_contact_campaign_status,
    log_event,
)
from src.services.compliance import process_unsubscribe
from src.services.state_machine import transition_contact
from tests.conftest import TEST_USER_ID

runner = CliRunner()


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
        "INSERT INTO companies (name, name_normalized, country, is_gdpr, aum_millions, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        ("Acme Crypto Fund", "acme crypto fund", "United States", False, 500.0, TEST_USER_ID),
    )
    company_id = cursor.fetchone()["id"]
    conn.commit()
    return company_id


@pytest.fixture
def sample_contact(conn, sample_company):
    """Insert a contact with valid email and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO contacts "
        "(company_id, first_name, last_name, full_name, email, email_normalized, "
        "email_status, priority_rank, source, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (sample_company, "Alice", "Smith", "Alice Smith",
         "alice@example.com", "alice@example.com", "valid", 1, "csv", TEST_USER_ID),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    return contact_id


@pytest.fixture
def sample_campaign(conn):
    """Create a campaign and return its id."""
    return create_campaign(conn, "Q1 Outreach", description="Test campaign", user_id=TEST_USER_ID)


@pytest.fixture
def sample_template(conn):
    """Create an email template and return its id."""
    return create_template(
        conn,
        name="Cold Email v1",
        channel="email",
        body_template="Hi {{ first_name }}, let's talk about {{ company_name }}.",
        subject="Quick intro",
        user_id=TEST_USER_ID,
    )


@pytest.fixture
def campaign_with_sequence(conn, sample_campaign, sample_template):
    """Set up a campaign with a single email sequence step. Returns campaign_id."""
    add_sequence_step(conn, sample_campaign, 1, "email", sample_template, delay_days=0, user_id=1)
    return sample_campaign


@pytest.fixture
def enrolled_contact(conn, sample_contact, campaign_with_sequence):
    """Enroll the sample contact in the campaign. Returns (contact_id, campaign_id)."""
    from datetime import date
    enroll_contact(
        conn, sample_contact, campaign_with_sequence,
        next_action_date=date.today().isoformat(),
        user_id=1,
    )
    return sample_contact, campaign_with_sequence


# ===========================================================================
# Tests: send command (dry_run mode)
# ===========================================================================

class TestSendCommandDryRun:
    """Test that the send command in dry-run mode shows a preview without sending."""

    def test_dry_run_shows_preview(self, tmp_db, conn, enrolled_contact):
        """dry_run should display the queue table and not send any emails."""
        contact_id, campaign_id = enrolled_contact

        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, ["send", "Q1 Outreach", "--dry-run"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "Alice" in result.output or "alice" in result.output.lower()

    def test_dry_run_does_not_call_send(self, tmp_db, conn, enrolled_contact):
        """dry_run should never call send_campaign_email."""
        contact_id, campaign_id = enrolled_contact

        with patch("src.cli.SUPABASE_DB_URL", tmp_db), \
             patch("src.services.email_sender.send_email") as mock_send:
            result = runner.invoke(app, ["send", "Q1 Outreach", "--dry-run"])

        assert result.exit_code == 0
        mock_send.assert_not_called()

    def test_dry_run_no_email_queue(self, tmp_db, conn, sample_campaign):
        """If no email items are queued, show appropriate message."""
        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, ["send", "Q1 Outreach", "--dry-run"])

        assert result.exit_code == 0
        assert "No email actions" in result.output

    def test_send_unknown_campaign(self, tmp_db, conn):
        """Send with a nonexistent campaign should fail."""
        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, ["send", "Nonexistent", "--dry-run"])

        assert result.exit_code != 0
        assert "not found" in result.output


# ===========================================================================
# Tests: status command (reply logging)
# ===========================================================================

class TestStatusCommand:
    """Test that the status command maps outcomes correctly and transitions state."""

    def test_reply_positive(self, tmp_db, conn, enrolled_contact):
        contact_id, campaign_id = enrolled_contact

        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, [
                "status", "reply", "alice@example.com", "positive",
                "--campaign", "Q1 Outreach",
            ])

        assert result.exit_code == 0
        assert "positive" in result.output.lower()

        ccs = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=1)
        assert ccs["status"] == "replied_positive"

    def test_reply_negative(self, tmp_db, conn, enrolled_contact):
        contact_id, campaign_id = enrolled_contact

        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, [
                "status", "reply", "alice@example.com", "negative",
                "--campaign", "Q1 Outreach",
            ])

        assert result.exit_code == 0
        assert "negative" in result.output.lower()

        ccs = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=1)
        assert ccs["status"] == "replied_negative"

    def test_reply_call_booked(self, tmp_db, conn, enrolled_contact):
        contact_id, campaign_id = enrolled_contact

        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, [
                "status", "reply", "alice@example.com", "call-booked",
                "--campaign", "Q1 Outreach",
            ])

        assert result.exit_code == 0
        assert "call-booked" in result.output.lower()

        # Status should be replied_positive
        ccs = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=1)
        assert ccs["status"] == "replied_positive"

        # Should have a call_booked event with metadata
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM events WHERE contact_id = %s AND event_type = 'call_booked'",
            (contact_id,),
        )
        event = cursor.fetchone()
        assert event is not None
        metadata = json.loads(event["metadata"])
        assert metadata["call_booked"] is True

    def test_reply_no_response(self, tmp_db, conn, enrolled_contact):
        contact_id, campaign_id = enrolled_contact

        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, [
                "status", "reply", "alice@example.com", "no-response",
                "--campaign", "Q1 Outreach",
            ])

        assert result.exit_code == 0
        assert "no-response" in result.output.lower()

        ccs = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=1)
        assert ccs["status"] == "no_response"

    def test_reply_by_contact_id(self, tmp_db, conn, enrolled_contact):
        """Status command should work when identifier is a numeric contact ID."""
        contact_id, campaign_id = enrolled_contact

        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, [
                "status", "reply", str(contact_id), "positive",
                "--campaign", "Q1 Outreach",
            ])

        assert result.exit_code == 0

        ccs = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=1)
        assert ccs["status"] == "replied_positive"

    def test_reply_unknown_contact(self, tmp_db, conn, sample_campaign):
        """Status with unknown email should fail gracefully."""
        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, [
                "status", "reply", "nobody@nowhere.com", "positive",
                "--campaign", "Q1 Outreach",
            ])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_reply_invalid_outcome(self, tmp_db, conn, enrolled_contact):
        """Invalid outcome should produce an error."""
        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, [
                "status", "reply", "alice@example.com", "maybe",
                "--campaign", "Q1 Outreach",
            ])

        assert result.exit_code != 0
        assert "Unknown outcome" in result.output

    def test_reply_invalid_action(self, tmp_db, conn, enrolled_contact):
        """Unknown action (not 'reply') should produce an error."""
        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, [
                "status", "bounce", "alice@example.com", "positive",
                "--campaign", "Q1 Outreach",
            ])

        assert result.exit_code != 0
        assert "Unknown action" in result.output


# ===========================================================================
# Tests: unsubscribe command
# ===========================================================================

class TestUnsubscribeCommand:
    """Test the CLI unsubscribe command."""

    def test_unsubscribe_marks_contact(self, tmp_db, conn, sample_contact):
        """Unsubscribe should mark the contact as unsubscribed."""
        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, ["unsubscribe", "alice@example.com"])

        assert result.exit_code == 0
        assert "Unsubscribed" in result.output

        cursor = conn.cursor()
        cursor.execute(
            "SELECT unsubscribed, unsubscribed_at FROM contacts WHERE id = %s",
            (sample_contact,),
        )
        row = cursor.fetchone()
        assert row["unsubscribed"] is True
        assert row["unsubscribed_at"] is not None

    def test_unsubscribe_unknown_email(self, tmp_db, conn):
        """Unsubscribe with unknown email should warn but not crash."""
        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            result = runner.invoke(app, ["unsubscribe", "nobody@nowhere.com"])

        assert result.exit_code == 0
        assert "No contact found" in result.output

    def test_unsubscribe_idempotent(self, tmp_db, conn, sample_contact):
        """Unsubscribing the same email twice should be safe."""
        with patch("src.cli.SUPABASE_DB_URL", tmp_db):
            runner.invoke(app, ["unsubscribe", "alice@example.com"])
            result = runner.invoke(app, ["unsubscribe", "alice@example.com"])

        assert result.exit_code == 0
        assert "Unsubscribed" in result.output
