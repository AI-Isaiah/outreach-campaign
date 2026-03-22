"""Tests for queue, export_expandi, and import_expandi command modules."""

import csv
import os
from datetime import date, timedelta

import pytest

from src.models.database import get_connection, run_migrations
from src.models.campaigns import (
    create_campaign,
    add_sequence_step,
    create_template,
    enroll_contact,
    get_contact_campaign_status,
    update_contact_campaign_status,
)
from src.commands.queue import queue_today
from src.commands.export_expandi import export_expandi_csv
from src.commands.import_expandi import import_expandi_results
from src.services.normalization_utils import normalize_linkedin_url as _normalize_linkedin_url
from tests.conftest import insert_company, insert_contact, TEST_USER_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return date.today().isoformat()


def _setup_campaign_with_steps(conn, name="test_campaign"):
    """Create a campaign with standard 5-step sequence.

    Steps:
      1: linkedin_connect (delay 0)
      2: linkedin_message (delay 3)
      3: email (delay 5)
      4: email (delay 7, non_gdpr_only)
      5: email (delay 14, non_gdpr_only)
    """
    campaign_id = create_campaign(conn, name, user_id=TEST_USER_ID)

    t1 = create_template(conn, f"{name}_li_connect", "linkedin_connect", "Hi {{first_name}}", user_id=TEST_USER_ID)
    t2 = create_template(conn, f"{name}_li_msg", "linkedin_message", "Following up...", user_id=TEST_USER_ID)
    t3 = create_template(
        conn, f"{name}_email_cold", "email", "Hello {{first_name}}", subject="Quick intro", user_id=TEST_USER_ID
    )
    t4 = create_template(
        conn, f"{name}_email_followup", "email", "Following up...", subject="Following up", user_id=TEST_USER_ID
    )
    t5 = create_template(
        conn, f"{name}_email_breakup", "email", "Last note...", subject="Last note", user_id=TEST_USER_ID
    )

    add_sequence_step(conn, campaign_id, 1, "linkedin_connect", t1, delay_days=0, user_id=TEST_USER_ID)
    add_sequence_step(conn, campaign_id, 2, "linkedin_message", t2, delay_days=3, user_id=TEST_USER_ID)
    add_sequence_step(conn, campaign_id, 3, "email", t3, delay_days=5, user_id=TEST_USER_ID)
    add_sequence_step(
        conn, campaign_id, 4, "email", t4, delay_days=7, non_gdpr_only=True, user_id=TEST_USER_ID
    )
    add_sequence_step(
        conn, campaign_id, 5, "email", t5, delay_days=14, non_gdpr_only=True, user_id=TEST_USER_ID
    )

    return campaign_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_db):
    """Return a fresh database connection with migrations applied."""
    connection = get_connection(tmp_db)
    run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def campaign(conn):
    """Return campaign_id for a standard 5-step campaign."""
    return _setup_campaign_with_steps(conn)


# ---------------------------------------------------------------------------
# Tests: queue_today (Task 13)
# ---------------------------------------------------------------------------

class TestQueueToday:
    """Tests for the queue_today command function."""

    def test_returns_correct_contacts(self, conn, campaign):
        """queue_today returns contacts that are ready for action today."""
        comp = insert_company(conn, "Acme Corp", aum_millions=500)
        cid = insert_contact(conn, comp, first_name="Alice", last_name="Smith")
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        result = queue_today(conn, "test_campaign", target_date=_today())

        assert len(result) == 1
        assert result[0]["contact_id"] == cid
        assert result[0]["contact_name"] == "Alice Smith"
        assert result[0]["company_name"] == "Acme Corp"
        assert result[0]["channel"] == "linkedin_connect"

    def test_returns_empty_for_unknown_campaign(self, conn):
        """queue_today returns empty list if campaign doesn't exist."""
        result = queue_today(conn, "nonexistent_campaign")
        assert result == []

    def test_respects_limit(self, conn, campaign):
        """queue_today respects the limit parameter."""
        for i in range(5):
            comp = insert_company(conn, f"Corp {i}", aum_millions=1000 - i * 100)
            cid = insert_contact(
                conn, comp, first_name=f"C{i}", last_name="Test",
                email=f"c{i}@example.com",
                linkedin_url=f"https://linkedin.com/in/c{i}",
            )
            enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
            update_contact_campaign_status(
                conn, cid, campaign, status="in_progress", current_step=1,
                user_id=TEST_USER_ID,
            )

        result = queue_today(conn, "test_campaign", target_date=_today(), limit=3)
        assert len(result) == 3

    def test_returns_empty_when_no_contacts_ready(self, conn, campaign):
        """queue_today returns empty list when no contacts are ready."""
        result = queue_today(conn, "test_campaign", target_date=_today())
        assert result == []

    def test_ordered_by_step(self, conn, campaign):
        """queue_today returns contacts ordered by step ascending."""
        comp_step2 = insert_company(conn, "Step2 Fund", aum_millions=5000)
        comp_step1 = insert_company(conn, "Step1 Fund", aum_millions=100)

        c_step2 = insert_contact(
            conn, comp_step2, first_name="Step2", last_name="Person",
            email="step2@example.com", email_status="valid",
            linkedin_url="https://linkedin.com/in/step2",
        )
        c_step1 = insert_contact(
            conn, comp_step1, first_name="Step1", last_name="Person",
            email="step1@example.com",
            linkedin_url="https://linkedin.com/in/step1",
        )

        enroll_contact(conn, c_step2, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_step2, campaign, status="in_progress", current_step=2,
            user_id=TEST_USER_ID,
        )
        enroll_contact(conn, c_step1, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_step1, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        result = queue_today(conn, "test_campaign", target_date=_today())
        assert len(result) == 2
        assert result[0]["step_order"] == 1
        assert result[1]["step_order"] == 2


# ---------------------------------------------------------------------------
# Tests: export_expandi_csv (Task 14)
# ---------------------------------------------------------------------------

class TestExportExpandiCsv:
    """Tests for the export_expandi_csv command function."""

    def test_produces_valid_csv_with_correct_columns(self, conn, campaign, tmp_path):
        """Exported CSV has the correct header columns."""
        comp = insert_company(conn, "Export Corp", aum_millions=500)
        cid = insert_contact(
            conn, comp, first_name="Alice", last_name="Smith",
            email="alice@export.com",
            linkedin_url="https://linkedin.com/in/alice",
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        output_dir = str(tmp_path / "exports")
        filepath = export_expandi_csv(
            conn, "test_campaign", target_date=_today(), output_dir=output_dir
        )

        assert os.path.exists(filepath)
        assert filepath.endswith(f"expandi_{_today()}.csv")

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == [
                "profile_link", "email", "first_name", "last_name", "company_name"
            ]
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["profile_link"] == "https://linkedin.com/in/alice"
        assert rows[0]["email"] == "alice@export.com"
        assert rows[0]["first_name"] == "Alice"
        assert rows[0]["last_name"] == "Smith"
        assert rows[0]["company_name"] == "Export Corp"

    def test_only_includes_linkedin_step_contacts(self, conn, campaign, tmp_path):
        """Only contacts whose current step is a LinkedIn action are exported."""
        comp_li = insert_company(conn, "LinkedIn Corp", aum_millions=500)
        comp_email = insert_company(conn, "Email Corp", aum_millions=600)

        # Contact on LinkedIn step
        c_li = insert_contact(
            conn, comp_li, first_name="LI", last_name="Person",
            email="li@example.com", linkedin_url="https://linkedin.com/in/li",
        )
        enroll_contact(conn, c_li, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_li, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        # Contact on email step
        c_email = insert_contact(
            conn, comp_email, first_name="Email", last_name="Person",
            email="email@example.com", email_status="valid",
            linkedin_url="https://linkedin.com/in/email",
        )
        enroll_contact(conn, c_email, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c_email, campaign, status="in_progress", current_step=3,
            user_id=TEST_USER_ID,
        )

        output_dir = str(tmp_path / "exports")
        filepath = export_expandi_csv(
            conn, "test_campaign", target_date=_today(), output_dir=output_dir
        )

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Only the LinkedIn-step contact should be in the CSV
        assert len(rows) == 1
        assert rows[0]["first_name"] == "LI"

    def test_includes_both_linkedin_connect_and_message(self, conn, campaign, tmp_path):
        """Both linkedin_connect and linkedin_message steps are exported."""
        comp1 = insert_company(conn, "Connect Corp", aum_millions=500)
        comp2 = insert_company(conn, "Message Corp", aum_millions=400)

        # Contact on linkedin_connect step
        c1 = insert_contact(
            conn, comp1, first_name="Connect", last_name="Person",
            email="connect@example.com",
            linkedin_url="https://linkedin.com/in/connect",
        )
        enroll_contact(conn, c1, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c1, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        # Contact on linkedin_message step
        c2 = insert_contact(
            conn, comp2, first_name="Message", last_name="Person",
            email="message@example.com",
            linkedin_url="https://linkedin.com/in/message",
        )
        enroll_contact(conn, c2, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, c2, campaign, status="in_progress", current_step=2,
            user_id=TEST_USER_ID,
        )

        output_dir = str(tmp_path / "exports")
        filepath = export_expandi_csv(
            conn, "test_campaign", target_date=_today(), output_dir=output_dir
        )

        with open(filepath, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2
        names = {r["first_name"] for r in rows}
        assert "Connect" in names
        assert "Message" in names

    def test_raises_for_unknown_campaign(self, conn, tmp_path):
        """export_expandi_csv raises ValueError for unknown campaign."""
        output_dir = str(tmp_path / "exports")
        with pytest.raises(ValueError, match="Campaign not found"):
            export_expandi_csv(conn, "nonexistent", output_dir=output_dir)

    def test_empty_export_produces_header_only(self, conn, campaign, tmp_path):
        """When there are no LinkedIn-step contacts, CSV has only the header."""
        output_dir = str(tmp_path / "exports")
        filepath = export_expandi_csv(
            conn, "test_campaign", target_date=_today(), output_dir=output_dir
        )

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 0


# ---------------------------------------------------------------------------
# Tests: import_expandi_results (Task 15)
# ---------------------------------------------------------------------------

class TestImportExpandiResults:
    """Tests for the import_expandi_results command function."""

    def _write_expandi_csv(self, tmp_path, rows):
        """Helper to write an Expandi results CSV file.

        rows: list of dicts with keys profile_link, status.
        Returns the file path.
        """
        filepath = str(tmp_path / "expandi_results.csv")
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["profile_link", "status"])
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return filepath

    def test_matches_contacts_by_linkedin_url(self, conn, campaign, tmp_path):
        """Contacts are matched by normalized LinkedIn URL."""
        comp = insert_company(conn, "Match Corp", aum_millions=500)
        cid = insert_contact(
            conn, comp, first_name="Match", last_name="Person",
            linkedin_url="https://linkedin.com/in/matchperson",
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        filepath = self._write_expandi_csv(tmp_path, [
            {"profile_link": "https://linkedin.com/in/matchperson", "status": "connected"},
        ])

        result = import_expandi_results(conn, filepath, "test_campaign")

        assert result["matched"] == 1
        assert result["unmatched"] == 0

    def test_advances_contacts_on_connected_status(self, conn, campaign, tmp_path):
        """When status is 'connected' and step is linkedin_connect, contact is advanced."""
        comp = insert_company(conn, "Advance Corp", aum_millions=500)
        cid = insert_contact(
            conn, comp, first_name="Advance", last_name="Person",
            linkedin_url="https://linkedin.com/in/advanceperson",
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        filepath = self._write_expandi_csv(tmp_path, [
            {"profile_link": "https://linkedin.com/in/advanceperson", "status": "connected"},
        ])

        result = import_expandi_results(conn, filepath, "test_campaign")

        assert result["advanced"] == 1

        # Verify the contact's step was advanced to step 2 (linkedin_message)
        ccs = get_contact_campaign_status(conn, cid, campaign, user_id=TEST_USER_ID)
        assert ccs["current_step"] == 2
        assert ccs["status"] == "in_progress"
        # Next action date should be today + delay_days of step 2 (3 days)
        expected_date = (date.today() + timedelta(days=3)).isoformat()
        assert str(ccs["next_action_date"]) == expected_date

    def test_advances_on_message_sent_for_linkedin_message(self, conn, campaign, tmp_path):
        """When status is 'message_sent' and step is linkedin_message, contact is advanced."""
        comp = insert_company(conn, "Msg Corp", aum_millions=500)
        cid = insert_contact(
            conn, comp, first_name="Msg", last_name="Person",
            linkedin_url="https://linkedin.com/in/msgperson",
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=2,
            user_id=TEST_USER_ID,
        )

        filepath = self._write_expandi_csv(tmp_path, [
            {"profile_link": "https://linkedin.com/in/msgperson", "status": "message_sent"},
        ])

        result = import_expandi_results(conn, filepath, "test_campaign")

        assert result["advanced"] == 1

        # Verify advanced to step 3 (email)
        ccs = get_contact_campaign_status(conn, cid, campaign, user_id=TEST_USER_ID)
        assert ccs["current_step"] == 3
        expected_date = (date.today() + timedelta(days=5)).isoformat()
        assert str(ccs["next_action_date"]) == expected_date

    def test_handles_unmatched_contacts_gracefully(self, conn, campaign, tmp_path):
        """Rows with unmatched LinkedIn URLs are counted but don't cause errors."""
        filepath = self._write_expandi_csv(tmp_path, [
            {"profile_link": "https://linkedin.com/in/nobody", "status": "connected"},
            {"profile_link": "https://linkedin.com/in/also-nobody", "status": "pending"},
        ])

        result = import_expandi_results(conn, filepath, "test_campaign")

        assert result["matched"] == 0
        assert result["unmatched"] == 2
        assert result["advanced"] == 0

    def test_does_not_advance_on_pending_status(self, conn, campaign, tmp_path):
        """Status 'pending' should not advance the contact."""
        comp = insert_company(conn, "Pending Corp", aum_millions=500)
        cid = insert_contact(
            conn, comp, first_name="Pending", last_name="Person",
            linkedin_url="https://linkedin.com/in/pendingperson",
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        filepath = self._write_expandi_csv(tmp_path, [
            {"profile_link": "https://linkedin.com/in/pendingperson", "status": "pending"},
        ])

        result = import_expandi_results(conn, filepath, "test_campaign")

        assert result["matched"] == 1
        assert result["advanced"] == 0

        # Step should remain at 1
        ccs = get_contact_campaign_status(conn, cid, campaign, user_id=TEST_USER_ID)
        assert ccs["current_step"] == 1

    def test_does_not_advance_connected_on_email_step(self, conn, campaign, tmp_path):
        """'connected' status on an email step should not advance the contact."""
        comp = insert_company(conn, "Email Step Corp", aum_millions=500)
        cid = insert_contact(
            conn, comp, first_name="EmailStep", last_name="Person",
            email="emailstep@example.com", email_status="valid",
            linkedin_url="https://linkedin.com/in/emailstep",
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=3,
            user_id=TEST_USER_ID,
        )

        filepath = self._write_expandi_csv(tmp_path, [
            {"profile_link": "https://linkedin.com/in/emailstep", "status": "connected"},
        ])

        result = import_expandi_results(conn, filepath, "test_campaign")

        assert result["matched"] == 1
        assert result["advanced"] == 0

    def test_raises_for_unknown_campaign(self, conn, tmp_path):
        """import_expandi_results raises ValueError for unknown campaign."""
        filepath = self._write_expandi_csv(tmp_path, [])
        with pytest.raises(ValueError, match="Campaign not found"):
            import_expandi_results(conn, filepath, "nonexistent_campaign")

    def test_mixed_matched_and_unmatched(self, conn, campaign, tmp_path):
        """Mix of matched and unmatched rows produces correct counts."""
        comp = insert_company(conn, "Mixed Corp", aum_millions=500)
        cid = insert_contact(
            conn, comp, first_name="Known", last_name="Person",
            linkedin_url="https://linkedin.com/in/knownperson",
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        filepath = self._write_expandi_csv(tmp_path, [
            {"profile_link": "https://linkedin.com/in/knownperson", "status": "connected"},
            {"profile_link": "https://linkedin.com/in/unknown", "status": "connected"},
        ])

        result = import_expandi_results(conn, filepath, "test_campaign")

        assert result["matched"] == 1
        assert result["unmatched"] == 1
        assert result["advanced"] == 1

    def test_url_normalization_case_insensitive(self, conn, campaign, tmp_path):
        """LinkedIn URL matching is case-insensitive."""
        comp = insert_company(conn, "Case Corp", aum_millions=500)
        cid = insert_contact(
            conn, comp, first_name="Case", last_name="Person",
            linkedin_url="https://linkedin.com/in/CasePerson",
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        filepath = self._write_expandi_csv(tmp_path, [
            {"profile_link": "https://LinkedIn.com/in/caseperson", "status": "connected"},
        ])

        result = import_expandi_results(conn, filepath, "test_campaign")
        assert result["matched"] == 1

    def test_url_normalization_strips_trailing_slash(self, conn, campaign, tmp_path):
        """LinkedIn URL matching strips trailing slashes."""
        comp = insert_company(conn, "Slash Corp", aum_millions=500)
        cid = insert_contact(
            conn, comp, first_name="Slash", last_name="Person",
            linkedin_url="https://linkedin.com/in/slashperson",
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        filepath = self._write_expandi_csv(tmp_path, [
            {"profile_link": "https://linkedin.com/in/slashperson/", "status": "connected"},
        ])

        result = import_expandi_results(conn, filepath, "test_campaign")
        assert result["matched"] == 1

    def test_url_normalization_strips_query_params(self, conn, campaign, tmp_path):
        """LinkedIn URL matching strips query parameters."""
        comp = insert_company(conn, "Query Corp", aum_millions=500)
        cid = insert_contact(
            conn, comp, first_name="Query", last_name="Person",
            linkedin_url="https://linkedin.com/in/queryperson",
        )
        enroll_contact(conn, cid, campaign, next_action_date=_today(), user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, cid, campaign, status="in_progress", current_step=1,
            user_id=TEST_USER_ID,
        )

        filepath = self._write_expandi_csv(tmp_path, [
            {
                "profile_link": "https://linkedin.com/in/queryperson?utm_source=expandi",
                "status": "connected",
            },
        ])

        result = import_expandi_results(conn, filepath, "test_campaign")
        assert result["matched"] == 1

    def test_empty_profile_link_counted_as_unmatched(self, conn, campaign, tmp_path):
        """Rows with empty profile_link are counted as unmatched."""
        filepath = self._write_expandi_csv(tmp_path, [
            {"profile_link": "", "status": "connected"},
        ])

        result = import_expandi_results(conn, filepath, "test_campaign")
        assert result["unmatched"] == 1
        assert result["matched"] == 0


# ---------------------------------------------------------------------------
# Tests: _normalize_linkedin_url utility
# ---------------------------------------------------------------------------

class TestNormalizeLinkedinUrl:
    """Tests for the URL normalization helper."""

    def test_lowercase(self):
        assert _normalize_linkedin_url("https://LinkedIn.com/in/John") == \
            "https://linkedin.com/in/john"

    def test_strip_trailing_slash(self):
        assert _normalize_linkedin_url("https://linkedin.com/in/john/") == \
            "https://linkedin.com/in/john"

    def test_strip_query_params(self):
        assert _normalize_linkedin_url("https://linkedin.com/in/john?foo=bar") == \
            "https://linkedin.com/in/john"

    def test_combined_normalization(self):
        assert _normalize_linkedin_url("https://LinkedIn.com/in/John/?utm=x") == \
            "https://linkedin.com/in/john"

    def test_empty_string(self):
        assert _normalize_linkedin_url("") == ""

    def test_none_like_empty(self):
        """Passing empty/whitespace returns empty."""
        assert _normalize_linkedin_url("  ") == ""
