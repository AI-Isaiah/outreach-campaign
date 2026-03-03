"""Tests for send/status/unsubscribe CLI commands and A/B testing (Task 21)."""

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
from src.services.ab_testing import assign_variant, get_variant_stats
from src.services.compliance import process_unsubscribe
from src.services.state_machine import transition_contact

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
        "INSERT INTO companies (name, name_normalized, country, is_gdpr, aum_millions) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        ("Acme Crypto Fund", "acme crypto fund", "United States", 0, 500.0),
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
        "email_status, priority_rank, source) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (sample_company, "Alice", "Smith", "Alice Smith",
         "alice@example.com", "alice@example.com", "valid", 1, "csv"),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    return contact_id


@pytest.fixture
def sample_campaign(conn):
    """Create a campaign and return its id."""
    return create_campaign(conn, "Q1 Outreach", description="Test campaign")


@pytest.fixture
def sample_template(conn):
    """Create an email template and return its id."""
    return create_template(
        conn,
        name="Cold Email v1",
        channel="email",
        body_template="Hi {{ first_name }}, let's talk about {{ company_name }}.",
        subject="Quick intro",
    )


@pytest.fixture
def campaign_with_sequence(conn, sample_campaign, sample_template):
    """Set up a campaign with a single email sequence step. Returns campaign_id."""
    add_sequence_step(conn, sample_campaign, 1, "email", sample_template, delay_days=0)
    return sample_campaign


@pytest.fixture
def enrolled_contact(conn, sample_contact, campaign_with_sequence):
    """Enroll the sample contact in the campaign. Returns (contact_id, campaign_id)."""
    from datetime import date
    enroll_contact(
        conn, sample_contact, campaign_with_sequence,
        next_action_date=date.today().isoformat(),
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

        ccs = get_contact_campaign_status(conn, contact_id, campaign_id)
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

        ccs = get_contact_campaign_status(conn, contact_id, campaign_id)
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
        ccs = get_contact_campaign_status(conn, contact_id, campaign_id)
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

        ccs = get_contact_campaign_status(conn, contact_id, campaign_id)
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

        ccs = get_contact_campaign_status(conn, contact_id, campaign_id)
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
# Tests: A/B variant assignment
# ===========================================================================

class TestABVariantAssignment:
    """Test that A/B variant assignment is deterministic."""

    def test_deterministic_assignment(self):
        """Same contact_id always gets the same variant."""
        v1 = assign_variant(42)
        v2 = assign_variant(42)
        v3 = assign_variant(42)
        assert v1 == v2 == v3

    def test_different_contacts_can_differ(self):
        """Different contact_ids can produce different variants (statistical)."""
        variants_seen = set()
        for cid in range(100):
            variants_seen.add(assign_variant(cid))
        # With 100 contacts and 2 variants, we should see both
        assert len(variants_seen) == 2

    def test_custom_variants(self):
        """Custom variant list should be respected."""
        v = assign_variant(1, variants=["X", "Y", "Z"])
        assert v in {"X", "Y", "Z"}

    def test_custom_variants_deterministic(self):
        """Custom variants with same contact_id should be reproducible."""
        v1 = assign_variant(7, variants=["X", "Y", "Z"])
        v2 = assign_variant(7, variants=["X", "Y", "Z"])
        assert v1 == v2

    def test_default_variants(self):
        """Default assignment should produce A or B."""
        v = assign_variant(99)
        assert v in {"A", "B"}


# ===========================================================================
# Tests: get_variant_stats
# ===========================================================================

class TestGetVariantStats:
    """Test variant statistics computation."""

    def test_returns_correct_counts(self, conn, sample_campaign, sample_company):
        """Variant stats should correctly count statuses per variant."""
        campaign_id = sample_campaign

        # Create contacts and enroll with different variants
        contacts = []
        for i, (variant, status) in enumerate([
            ("A", "replied_positive"),
            ("A", "replied_negative"),
            ("A", "no_response"),
            ("A", "queued"),
            ("B", "replied_positive"),
            ("B", "no_response"),
        ]):
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO contacts "
                "(company_id, first_name, email, email_normalized, priority_rank, source) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (sample_company, f"Contact{i}", f"c{i}@test.com", f"c{i}@test.com", i + 1, "csv"),
            )
            cid = cursor.fetchone()["id"]
            conn.commit()

            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO contact_campaign_status
                   (contact_id, campaign_id, current_step, status, assigned_variant)
                   VALUES (%s, %s, 1, %s, %s)""",
                (cid, campaign_id, status, variant),
            )
            conn.commit()

        stats = get_variant_stats(conn, campaign_id)

        # Find variant A and B stats
        a_stats = next(s for s in stats if s["variant"] == "A")
        b_stats = next(s for s in stats if s["variant"] == "B")

        assert a_stats["total"] == 4
        assert a_stats["replied_positive"] == 1
        assert a_stats["replied_negative"] == 1
        assert a_stats["no_response"] == 1
        assert a_stats["reply_rate"] == round(2 / 4, 4)

        assert b_stats["total"] == 2
        assert b_stats["replied_positive"] == 1
        assert b_stats["no_response"] == 1
        assert b_stats["reply_rate"] == round(1 / 2, 4)

    def test_empty_campaign_returns_empty(self, conn, sample_campaign):
        """Campaign with no enrollments should return empty list."""
        stats = get_variant_stats(conn, sample_campaign)
        assert stats == []

    def test_null_variant_grouped(self, conn, sample_campaign, sample_company):
        """Contacts with no assigned variant should group under None."""
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO contacts "
            "(company_id, first_name, email, priority_rank, source) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (sample_company, "NoVariant", "nv@test.com", 1, "csv"),
        )
        cid = cursor.fetchone()["id"]
        conn.commit()

        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO contact_campaign_status
               (contact_id, campaign_id, current_step, status, assigned_variant)
               VALUES (%s, %s, 1, 'queued', NULL)""",
            (cid, sample_campaign),
        )
        conn.commit()

        stats = get_variant_stats(conn, sample_campaign)
        assert len(stats) == 1
        assert stats[0]["variant"] is None
        assert stats[0]["total"] == 1


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
        assert row["unsubscribed"] == 1
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
