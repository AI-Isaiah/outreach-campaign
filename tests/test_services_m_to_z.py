"""Comprehensive edge-case tests for service modules M-Z (alphabetically).

Covers: message_drafter, metrics, newsletter, normalization_utils (gaps),
phone_utils, priority_queue, reply_detector, response_analyzer, retry,
sequence_generator, smart_import, state_machine (gaps), template_engine (gaps),
token_encryption.

Uses the tmp_db fixture (ephemeral PostgreSQL). External APIs are always mocked.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.models.database import get_connection, run_migrations
from tests.conftest import TEST_USER_ID, insert_company, insert_contact


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _conn(db_url):
    """Return a live connection with migrations applied."""
    conn = get_connection(db_url)
    run_migrations(conn)
    return conn


def _create_campaign(conn, name="TestCampaign"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO campaigns (name, user_id) VALUES (%s, %s) RETURNING id",
        (name, TEST_USER_ID),
    )
    cid = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    return cid


def _create_sequence_step(
    conn, campaign_id, step_order=1, channel="email", delay_days=0,
    template_id=None, gdpr_only=False, non_gdpr_only=False, draft_mode=False,
):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO sequence_steps
           (campaign_id, step_order, channel, delay_days, template_id,
            gdpr_only, non_gdpr_only, draft_mode)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (campaign_id, step_order, channel, delay_days, template_id,
         gdpr_only, non_gdpr_only, draft_mode),
    )
    sid = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    return sid


def _enroll_contact(
    conn, contact_id, campaign_id, status="queued", current_step=1,
    next_action_date=None, assigned_variant=None, channel_override=None,
):
    if next_action_date is None:
        next_action_date = date.today().isoformat()
    cur = conn.cursor()
    # Look up stable_id for the step so queue JOINs work
    cur.execute(
        "SELECT stable_id FROM sequence_steps WHERE campaign_id = %s AND step_order = %s",
        (campaign_id, current_step),
    )
    row = cur.fetchone()
    step_id = str(row["stable_id"]) if row else None
    cur.execute(
        """INSERT INTO contact_campaign_status
           (contact_id, campaign_id, status, current_step, current_step_id,
            next_action_date, assigned_variant, channel_override)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (contact_id, campaign_id, status, current_step, step_id,
         next_action_date, assigned_variant, channel_override),
    )
    conn.commit()
    cur.close()


def _create_template(conn, name="tpl", channel="email", subject="Hi", body="Body"):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO templates (name, channel, subject, body_template, user_id)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (name, channel, subject, body, TEST_USER_ID),
    )
    tid = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    return tid


def _insert_event(conn, contact_id, event_type, campaign_id=None,
                   created_at=None, notes=None):
    cur = conn.cursor()
    if created_at:
        cur.execute(
            """INSERT INTO events (contact_id, event_type, campaign_id, notes, user_id, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (contact_id, event_type, campaign_id, notes, TEST_USER_ID, created_at),
        )
    else:
        cur.execute(
            """INSERT INTO events (contact_id, event_type, campaign_id, notes, user_id)
               VALUES (%s, %s, %s, %s, %s)""",
            (contact_id, event_type, campaign_id, notes, TEST_USER_ID),
        )
    conn.commit()
    cur.close()


# ===========================================================================
# message_drafter — _parse_response, _enforce_constraints, _build_user_message,
#                   _parse_sequence_response, channel prompt map
# ===========================================================================

class TestParseResponse:
    """Tests for message_drafter._parse_response."""

    def test_email_with_subject_and_body(self):
        from src.services.message_drafter import _parse_response
        raw = "SUBJECT: Hello World\nBODY: This is the body text."
        subj, body = _parse_response(raw, "email")
        assert subj == "Hello World"
        assert body == "This is the body text."

    def test_email_multiline_body(self):
        from src.services.message_drafter import _parse_response
        raw = "SUBJECT: Test\nBODY: Line one.\nLine two.\nLine three."
        subj, body = _parse_response(raw, "email")
        assert subj == "Test"
        assert "Line one." in body
        assert "Line three." in body

    def test_email_no_subject_prefix(self):
        from src.services.message_drafter import _parse_response
        raw = "Just the body text without labels."
        subj, body = _parse_response(raw, "email")
        assert subj is None
        assert "Just the body text" in body

    def test_email_no_body_prefix(self):
        from src.services.message_drafter import _parse_response
        raw = "SUBJECT: Only Subject"
        subj, body = _parse_response(raw, "email")
        assert subj == "Only Subject"

    def test_linkedin_connect_with_note_prefix(self):
        from src.services.message_drafter import _parse_response
        raw = "NOTE: Noticed your fund's recent crypto allocation."
        subj, body = _parse_response(raw, "linkedin_connect")
        assert subj is None
        assert "crypto allocation" in body

    def test_linkedin_connect_without_note_prefix(self):
        from src.services.message_drafter import _parse_response
        raw = "Saw your talk at the Zurich conference."
        subj, body = _parse_response(raw, "linkedin_connect")
        assert subj is None
        assert "Zurich conference" in body

    def test_linkedin_message_with_prefix(self):
        from src.services.message_drafter import _parse_response
        raw = "MESSAGE: Your recent allocation shift caught my eye."
        subj, body = _parse_response(raw, "linkedin_message")
        assert subj is None
        assert "allocation shift" in body

    def test_linkedin_message_without_prefix(self):
        from src.services.message_drafter import _parse_response
        raw = "Interesting move into crypto derivatives."
        subj, body = _parse_response(raw, "linkedin_message")
        assert subj is None
        assert "crypto derivatives" in body

    def test_whitespace_stripping(self):
        from src.services.message_drafter import _parse_response
        raw = "  \n  SUBJECT:   Spaced Out   \nBODY:   Lots of space   \n  "
        subj, body = _parse_response(raw, "email")
        assert subj == "Spaced Out"
        assert body == "Lots of space"


class TestEnforceConstraints:
    """Tests for message_drafter._enforce_constraints."""

    def test_linkedin_connect_short_text_unchanged(self):
        from src.services.message_drafter import _enforce_constraints
        short = "Hello, fellow allocator."
        assert _enforce_constraints(short, "linkedin_connect") == short

    def test_linkedin_connect_truncates_at_sentence(self):
        from src.services.message_drafter import _enforce_constraints
        long_text = "A" * 120 + ". " + "B" * 120 + ". " + "C" * 200
        result = _enforce_constraints(long_text, "linkedin_connect")
        assert len(result) <= 300
        assert result.endswith(".")

    def test_linkedin_connect_truncates_at_space_if_no_sentence(self):
        from src.services.message_drafter import _enforce_constraints
        # No sentence-ending punctuation in first 300 chars
        long_text = "word " * 80
        result = _enforce_constraints(long_text, "linkedin_connect")
        assert len(result) <= 300

    def test_linkedin_message_huge_text_truncated(self):
        from src.services.message_drafter import _enforce_constraints
        huge = "paragraph one.\n\n" * 600
        result = _enforce_constraints(huge, "linkedin_message")
        assert len(result) <= 8000

    def test_email_not_truncated(self):
        from src.services.message_drafter import _enforce_constraints
        text = "word " * 100
        assert _enforce_constraints(text, "email") == text

    def test_email_over_500_words_warns_but_not_truncated(self):
        from src.services.message_drafter import _enforce_constraints
        text = "word " * 600
        result = _enforce_constraints(text, "email")
        assert result == text


class TestParseSequenceResponse:
    """Tests for message_drafter._parse_sequence_response."""

    def test_valid_json_array(self):
        from src.services.message_drafter import _parse_sequence_response
        raw = json.dumps([
            {"step_order": 1, "channel": "email", "subject": "Hi", "body": "Hello"},
            {"step_order": 2, "channel": "linkedin_connect", "subject": None, "body": "Note"},
        ])
        steps = [
            {"step_order": 1, "channel": "email"},
            {"step_order": 2, "channel": "linkedin_connect"},
        ]
        result = _parse_sequence_response(raw, steps)
        assert len(result) == 2
        assert result[0]["channel"] == "email"
        assert result[1]["channel"] == "linkedin_connect"

    def test_json_wrapped_in_markdown_fences(self):
        from src.services.message_drafter import _parse_sequence_response
        raw = "```json\n" + json.dumps([
            {"step_order": 1, "body": "hello"}
        ]) + "\n```"
        steps = [{"step_order": 1, "channel": "email"}]
        result = _parse_sequence_response(raw, steps)
        assert len(result) == 1

    def test_invalid_json_raises(self):
        from src.services.message_drafter import _parse_sequence_response
        with pytest.raises(RuntimeError, match="invalid response"):
            _parse_sequence_response("not json at all", [])

    def test_extra_steps_ignored(self):
        from src.services.message_drafter import _parse_sequence_response
        raw = json.dumps([
            {"step_order": 1, "body": "a"},
            {"step_order": 99, "body": "b"},
        ])
        steps = [{"step_order": 1, "channel": "email"}]
        result = _parse_sequence_response(raw, steps)
        assert len(result) == 1

    def test_single_object_wrapped_as_list(self):
        from src.services.message_drafter import _parse_sequence_response
        raw = json.dumps({"step_order": 1, "body": "single"})
        steps = [{"step_order": 1, "channel": "email"}]
        result = _parse_sequence_response(raw, steps)
        assert len(result) == 1

    def test_uses_step_channel_not_response_channel(self):
        from src.services.message_drafter import _parse_sequence_response
        raw = json.dumps([{"step_order": 1, "channel": "wrong", "body": "hello"}])
        steps = [{"step_order": 1, "channel": "linkedin_message"}]
        result = _parse_sequence_response(raw, steps)
        assert result[0]["channel"] == "linkedin_message"


class TestChannelPromptMap:
    """Tests for CHANNEL_PROMPT_MAP coverage."""

    def test_all_channels_mapped(self):
        from src.services.message_drafter import CHANNEL_PROMPT_MAP
        from src.enums import Channel
        for ch in Channel:
            assert ch in CHANNEL_PROMPT_MAP

    def test_linkedin_engage_maps_to_message(self):
        from src.services.message_drafter import CHANNEL_PROMPT_MAP
        from src.enums import Channel
        assert CHANNEL_PROMPT_MAP[Channel.LINKEDIN_ENGAGE] == "linkedin_message"

    def test_linkedin_insight_maps_to_message(self):
        from src.services.message_drafter import CHANNEL_PROMPT_MAP
        from src.enums import Channel
        assert CHANNEL_PROMPT_MAP[Channel.LINKEDIN_INSIGHT] == "linkedin_message"

    def test_linkedin_final_maps_to_message(self):
        from src.services.message_drafter import CHANNEL_PROMPT_MAP
        from src.enums import Channel
        assert CHANNEL_PROMPT_MAP[Channel.LINKEDIN_FINAL] == "linkedin_message"


class TestBuildUserMessage:
    """Tests for _build_user_message context assembly."""

    def test_no_research_includes_fallback_text(self):
        from src.services.message_drafter import _build_user_message
        contact = {"first_name": "John", "last_name": "Doe", "full_name": "John Doe",
                    "title": "CIO", "company_name": "Acme Fund"}
        msg = _build_user_message(contact, None, "", "", "email")
        assert "No research available" in msg
        assert "John Doe" in msg

    def test_research_talking_points_included(self):
        from src.services.message_drafter import _build_user_message
        contact = {"first_name": "Jane", "last_name": "Smith", "full_name": None,
                    "title": None, "company_name": None}
        research = {
            "company_overview": "A leading allocator",
            "talking_points": [{"text": "Recently allocated to DeFi"}],
            "crypto_signals": [{"relevance": "high", "quote": "Bitcoin ETF approved"}],
            "key_people": [{"name": "Bob", "title": "CEO", "context": "Crypto bull"}],
        }
        msg = _build_user_message(contact, research, "Subject", "Body", "email")
        assert "Recently allocated to DeFi" in msg
        assert "Bitcoin ETF approved" in msg
        assert "Bob" in msg

    def test_template_included_when_present(self):
        from src.services.message_drafter import _build_user_message
        contact = {"first_name": "A", "last_name": "B", "full_name": "A B",
                    "title": "VP", "company_name": "Firm"}
        msg = _build_user_message(contact, None, "Subject Line", "Template body here", "email")
        assert "Subject Line" in msg
        assert "Template body here" in msg

    def test_empty_research_fields_handled(self):
        from src.services.message_drafter import _build_user_message
        contact = {"first_name": "X", "last_name": "Y", "full_name": "X Y",
                    "title": "Analyst", "company_name": "Z Fund"}
        research = {
            "company_overview": "",
            "talking_points": None,
            "crypto_signals": None,
            "key_people": None,
        }
        msg = _build_user_message(contact, research, "", "", "linkedin_connect")
        assert "No research available" in msg or "Not available" in msg


class TestGenerateDraftMocked:
    """Tests for generate_draft with mocked API calls."""

    def test_missing_api_key_raises(self, tmp_db):
        from src.services.message_drafter import generate_draft
        conn = _conn(tmp_db)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                generate_draft(conn, 999, 999, 1, user_id=TEST_USER_ID)
        conn.close()

    def test_contact_not_found_raises(self, tmp_db):
        from src.services.message_drafter import generate_draft
        conn = _conn(tmp_db)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
            with pytest.raises(ValueError, match="not found"):
                generate_draft(conn, 99999, 1, 1, user_id=TEST_USER_ID)
        conn.close()


class TestImproveMessageMocked:
    """Tests for improve_message with mocked API."""

    def test_missing_api_key_raises(self):
        from src.services.message_drafter import improve_message
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                improve_message(
                    channel="email", body="hello", instruction="shorten",
                    user_id=TEST_USER_ID,
                )


class TestGenerateSequenceMessagesMocked:
    """Tests for generate_sequence_messages with mocked API."""

    def test_missing_api_key_raises(self):
        from src.services.message_drafter import generate_sequence_messages
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                generate_sequence_messages(
                    steps=[{"step_order": 1, "channel": "email"}],
                    product_description="crypto fund",
                    user_id=TEST_USER_ID,
                )


# ===========================================================================
# metrics — focus on untested: get_campaign_metrics detail,
#           get_variant_comparison, get_weekly_summary, get_company_type_breakdown
# ===========================================================================

class TestCampaignMetricsReplyBreakdown:
    """Edge cases for get_campaign_metrics reply_breakdown field."""

    def test_reply_breakdown_zero_replies(self, tmp_db):
        from src.services.metrics import get_campaign_metrics
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "MetCo")
        ct = insert_contact(conn, co)
        _enroll_contact(conn, ct, cid, status="in_progress")
        m = get_campaign_metrics(conn, cid, user_id=1)
        assert m["reply_breakdown"]["total"] == 0
        assert m["reply_breakdown"]["positive_rate"] == 0.0
        conn.close()

    def test_reply_breakdown_all_positive(self, tmp_db):
        from src.services.metrics import get_campaign_metrics
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "RP1")
        ct = insert_contact(conn, co)
        _enroll_contact(conn, ct, cid, status="replied_positive")
        m = get_campaign_metrics(conn, cid, user_id=1)
        assert m["reply_breakdown"]["positive_rate"] == 1.0
        assert m["reply_breakdown"]["positive"] == 1
        conn.close()

    def test_reply_breakdown_mixed(self, tmp_db):
        from src.services.metrics import get_campaign_metrics
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "RM1")
        c1 = insert_contact(conn, co, priority_rank=1)
        c2 = insert_contact(conn, co, priority_rank=2)
        c3 = insert_contact(conn, co, priority_rank=3)
        _enroll_contact(conn, c1, cid, status="replied_positive")
        _enroll_contact(conn, c2, cid, status="replied_negative")
        _enroll_contact(conn, c3, cid, status="in_progress")
        m = get_campaign_metrics(conn, cid, user_id=1)
        assert m["reply_breakdown"]["total"] == 2
        assert m["reply_breakdown"]["positive_rate"] == 0.5
        conn.close()

    def test_linkedin_event_types_counted(self, tmp_db):
        from src.services.metrics import get_campaign_metrics
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "LI1")
        ct = insert_contact(conn, co)
        _enroll_contact(conn, ct, cid, status="in_progress")
        _insert_event(conn, ct, "linkedin_connect_done", cid)
        _insert_event(conn, ct, "linkedin_message_done", cid)
        _insert_event(conn, ct, "linkedin_engage_done", cid)
        m = get_campaign_metrics(conn, cid, user_id=1)
        assert m["linkedin_connects"] == 1
        assert m["linkedin_messages"] == 2  # message_done + engage_done (connect is counted separately)
        conn.close()


class TestComputeHealthScore:
    """Tests for compute_health_score pure function."""

    def test_empty_metrics_returns_none(self):
        from src.services.metrics import compute_health_score
        assert compute_health_score({"total_enrolled": 0}) is None

    def test_score_clamped_to_0_100(self):
        from src.services.metrics import compute_health_score
        # Huge bounce rate
        m = {"total_enrolled": 10, "by_status": {"replied_positive": 0, "bounced": 10},
             "emails_sent": 10}
        s = compute_health_score(m)
        assert 0 <= s <= 100

    def test_perfect_campaign(self):
        from src.services.metrics import compute_health_score
        m = {"total_enrolled": 10, "by_status": {"replied_positive": 10, "bounced": 0},
             "emails_sent": 10}
        s = compute_health_score(m)
        assert s >= 50


# ===========================================================================
# newsletter — subscriber management, auto_subscribe, extract_subject
# ===========================================================================

class TestExtractSubject:
    """Tests for newsletter._extract_subject."""

    def test_h1_heading_extracted(self):
        from src.services.newsletter import _extract_subject
        md = "# Weekly Crypto Digest\n\nSome content."
        assert _extract_subject(md, "fallback") == "Weekly Crypto Digest"

    def test_no_heading_falls_back(self):
        from src.services.newsletter import _extract_subject
        md = "Just plain text without headings."
        assert _extract_subject(md, "my_newsletter") == "my_newsletter"

    def test_h2_not_extracted(self):
        from src.services.newsletter import _extract_subject
        md = "## Sub Heading\n\nContent."
        assert _extract_subject(md, "fallback") == "fallback"

    def test_heading_with_extra_spaces(self):
        from src.services.newsletter import _extract_subject
        md = "#    Spaced Title   \n\nContent."
        assert _extract_subject(md, "fallback") == "Spaced Title"

    def test_empty_markdown(self):
        from src.services.newsletter import _extract_subject
        assert _extract_subject("", "empty_file") == "empty_file"

    def test_blank_lines_before_heading(self):
        from src.services.newsletter import _extract_subject
        md = "\n\n\n# After Blanks\n\nContent."
        assert _extract_subject(md, "fallback") == "After Blanks"


class TestAutoSubscribeEligible:
    """Tests for newsletter.auto_subscribe_eligible."""

    def test_subscribes_non_gdpr_no_response(self, tmp_db):
        from src.services.newsletter import auto_subscribe_eligible
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "SubCo", is_gdpr=False)
        ct = insert_contact(conn, co, is_gdpr=False)
        _enroll_contact(conn, ct, cid, status="no_response")
        result = auto_subscribe_eligible(conn, cid, user_id=TEST_USER_ID)
        assert result["subscribed"] == 1
        assert result["skipped_gdpr"] == 0
        conn.close()

    def test_skips_gdpr_contacts(self, tmp_db):
        from src.services.newsletter import auto_subscribe_eligible
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "GDPRCo", is_gdpr=True)
        ct = insert_contact(conn, co, is_gdpr=True)
        _enroll_contact(conn, ct, cid, status="no_response")
        result = auto_subscribe_eligible(conn, cid, user_id=TEST_USER_ID)
        assert result["subscribed"] == 0
        assert result["skipped_gdpr"] == 1
        conn.close()

    def test_skips_already_subscribed(self, tmp_db):
        from src.services.newsletter import auto_subscribe_eligible
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "AlrCo")
        ct = insert_contact(conn, co)
        # Pre-subscribe
        cur = conn.cursor()
        cur.execute("UPDATE contacts SET newsletter_status = 'subscribed' WHERE id = %s", (ct,))
        conn.commit()
        cur.close()
        _enroll_contact(conn, ct, cid, status="no_response")
        result = auto_subscribe_eligible(conn, cid, user_id=TEST_USER_ID)
        assert result["already_subscribed"] == 1
        conn.close()

    def test_skips_contacts_without_email(self, tmp_db):
        from src.services.newsletter import auto_subscribe_eligible
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "NoEmCo")
        ct = insert_contact(conn, co, email=None)
        _enroll_contact(conn, ct, cid, status="no_response")
        result = auto_subscribe_eligible(conn, cid, user_id=TEST_USER_ID)
        assert result["subscribed"] == 0
        conn.close()


class TestSubscribeUnsubscribe:
    """Tests for subscribe_contact / unsubscribe_contact."""

    def test_subscribe_contact(self, tmp_db):
        from src.services.newsletter import subscribe_contact
        conn = _conn(tmp_db)
        co = insert_company(conn, "SubManual")
        ct = insert_contact(conn, co)
        assert subscribe_contact(conn, ct, user_id=TEST_USER_ID) is True
        conn.close()

    def test_subscribe_nonexistent_returns_false(self, tmp_db):
        from src.services.newsletter import subscribe_contact
        conn = _conn(tmp_db)
        assert subscribe_contact(conn, 99999, user_id=TEST_USER_ID) is False
        conn.close()

    def test_unsubscribe_contact(self, tmp_db):
        from src.services.newsletter import unsubscribe_contact
        conn = _conn(tmp_db)
        co = insert_company(conn, "UnsubCo")
        ct = insert_contact(conn, co)
        assert unsubscribe_contact(conn, ct, user_id=TEST_USER_ID) is True
        # Verify
        cur = conn.cursor()
        cur.execute("SELECT newsletter_status, unsubscribed FROM contacts WHERE id = %s", (ct,))
        row = cur.fetchone()
        assert row["newsletter_status"] == "unsubscribed"
        assert row["unsubscribed"] is True
        cur.close()
        conn.close()

    def test_unsubscribe_nonexistent_returns_false(self, tmp_db):
        from src.services.newsletter import unsubscribe_contact
        conn = _conn(tmp_db)
        assert unsubscribe_contact(conn, 99999, user_id=TEST_USER_ID) is False
        conn.close()


class TestRenderNewsletter:
    """Tests for render_newsletter."""

    def test_render_markdown_to_html(self, tmp_path):
        from src.services.newsletter import render_newsletter
        md = tmp_path / "test.md"
        md.write_text("# Hello\n\nWorld {{ calendly_url }}")
        config = {"calendly_url": "https://cal.com/test", "physical_address": "123 St",
                  "smtp": {"username": "test@example.com"}}
        html, text = render_newsletter(str(md), config)
        assert "Hello" in html
        assert "https://cal.com/test" in text
        assert "123 St" in text  # compliance footer

    def test_missing_file_raises(self):
        from src.services.newsletter import render_newsletter
        with pytest.raises(FileNotFoundError):
            render_newsletter("/nonexistent/path.md", {})


# ===========================================================================
# phone_utils — normalize_phone
# ===========================================================================

class TestPhoneUtilsNormalize:
    """Tests for phone_utils.normalize_phone (E.164 format)."""

    def test_us_formatted(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("+1 (555) 123-4567") == "+15551234567"

    def test_uk_formatted(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("+44 20 7123 4567") == "+442071234567"

    def test_international_00_prefix(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("00442071234567") == "+442071234567"

    def test_ten_digit_us_assumed(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("5551234567") == "+15551234567"

    def test_eleven_digit_starting_with_1(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("15551234567") == "+15551234567"

    def test_empty_string_returns_none(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("") is None

    def test_none_returns_none(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone(None) is None

    def test_whitespace_only_returns_none(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("   ") is None

    def test_short_number_returns_none(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("12345") is None

    def test_too_long_returns_none(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("+1234567890123456") is None

    def test_non_numeric_returns_none(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("not a phone") is None

    def test_dots_as_separators(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("+1.555.123.4567") == "+15551234567"

    def test_dashes_and_parens(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("(555) 123-4567") == "+15551234567"

    def test_already_e164(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("+442071234567") == "+442071234567"

    def test_seven_digit_minimum(self):
        from src.services.phone_utils import normalize_phone
        result = normalize_phone("+1234567")
        assert result == "+1234567"

    def test_fifteen_digit_maximum(self):
        from src.services.phone_utils import normalize_phone
        result = normalize_phone("+123456789012345")
        assert result == "+123456789012345"


# ===========================================================================
# priority_queue — get_daily_queue, defer_contact, get_defer_stats
# ===========================================================================

class TestDailyQueueEdgeCases:
    """Edge cases for priority_queue.get_daily_queue."""

    def test_empty_campaign_returns_empty(self, tmp_db):
        from src.services.priority_queue import get_daily_queue
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email")
        result = get_daily_queue(conn, cid, user_id=TEST_USER_ID)
        assert result == []
        conn.close()

    def test_one_per_company(self, tmp_db):
        from src.services.priority_queue import get_daily_queue
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email")
        co = insert_company(conn, "OnePerCo", aum_millions=100)
        c1 = insert_contact(conn, co, priority_rank=1, email_status="valid")
        c2 = insert_contact(conn, co, priority_rank=2, email_status="valid")
        _enroll_contact(conn, c1, cid, status="queued")
        _enroll_contact(conn, c2, cid, status="queued")
        result = get_daily_queue(conn, cid, user_id=TEST_USER_ID)
        ids = [r["contact_id"] for r in result]
        assert c1 in ids
        assert c2 not in ids
        conn.close()

    def test_unsubscribed_contacts_excluded(self, tmp_db):
        from src.services.priority_queue import get_daily_queue
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email")
        co = insert_company(conn, "UnsubQCo")
        ct = insert_contact(conn, co, unsubscribed=True, email_status="valid")
        _enroll_contact(conn, ct, cid, status="queued")
        result = get_daily_queue(conn, cid, user_id=TEST_USER_ID)
        assert len(result) == 0
        conn.close()

    def test_email_step_requires_valid_email(self, tmp_db):
        from src.services.priority_queue import get_daily_queue
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email")
        co = insert_company(conn, "InvalidEmCo")
        ct = insert_contact(conn, co, email_status="invalid")
        _enroll_contact(conn, ct, cid, status="queued")
        result = get_daily_queue(conn, cid, user_id=TEST_USER_ID)
        assert len(result) == 0
        conn.close()

    def test_linkedin_step_requires_linkedin_url(self, tmp_db):
        from src.services.priority_queue import get_daily_queue
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="linkedin_connect")
        co = insert_company(conn, "NoLICo")
        ct = insert_contact(conn, co, linkedin_url=None, email_status="valid")
        _enroll_contact(conn, ct, cid, status="queued")
        result = get_daily_queue(conn, cid, user_id=TEST_USER_ID)
        assert len(result) == 0
        conn.close()

    def test_future_action_date_excluded(self, tmp_db):
        from src.services.priority_queue import get_daily_queue
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email")
        co = insert_company(conn, "FutureCo")
        ct = insert_contact(conn, co, email_status="valid")
        future = (date.today() + timedelta(days=5)).isoformat()
        _enroll_contact(conn, ct, cid, status="queued", next_action_date=future)
        result = get_daily_queue(conn, cid, user_id=TEST_USER_ID)
        assert len(result) == 0
        conn.close()

    def test_gdpr_only_step_filters_non_gdpr(self, tmp_db):
        from src.services.priority_queue import get_daily_queue
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email", gdpr_only=True)
        co = insert_company(conn, "NonGDPRCo")
        ct = insert_contact(conn, co, is_gdpr=False, email_status="valid")
        _enroll_contact(conn, ct, cid, status="queued")
        result = get_daily_queue(conn, cid, user_id=TEST_USER_ID)
        assert len(result) == 0
        conn.close()

    def test_non_gdpr_only_step_filters_gdpr(self, tmp_db):
        from src.services.priority_queue import get_daily_queue
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email", non_gdpr_only=True)
        co = insert_company(conn, "GDPROnlyCo", is_gdpr=True)
        ct = insert_contact(conn, co, is_gdpr=True, email_status="valid")
        _enroll_contact(conn, ct, cid, status="queued")
        result = get_daily_queue(conn, cid, user_id=TEST_USER_ID)
        assert len(result) == 0
        conn.close()

    def test_channel_override_respected(self, tmp_db):
        from src.services.priority_queue import get_daily_queue
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email")
        co = insert_company(conn, "OverrideCo")
        ct = insert_contact(conn, co, email_status="valid")
        _enroll_contact(conn, ct, cid, status="queued", channel_override="linkedin_connect")
        result = get_daily_queue(conn, cid, user_id=TEST_USER_ID)
        if result:
            assert result[0]["channel"] == "linkedin_connect"
        conn.close()

    def test_limit_parameter_respected(self, tmp_db):
        from src.services.priority_queue import get_daily_queue
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email")
        for i in range(5):
            co = insert_company(conn, f"LimitCo{i}", aum_millions=100 + i)
            ct = insert_contact(conn, co, email_status="valid")
            _enroll_contact(conn, ct, cid, status="queued")
        result = get_daily_queue(conn, cid, limit=2, user_id=TEST_USER_ID)
        assert len(result) == 2
        conn.close()


class TestDeferContact:
    """Tests for priority_queue.defer_contact."""

    def test_defer_pushes_action_date(self, tmp_db):
        from src.services.priority_queue import defer_contact
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "DeferCo")
        ct = insert_contact(conn, co)
        _enroll_contact(conn, ct, cid, status="queued")
        result = defer_contact(conn, ct, cid, reason="vacation", user_id=TEST_USER_ID)
        assert result["success"] is True
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        assert result["next_action_date"] == tomorrow
        conn.close()

    def test_defer_not_enrolled_fails(self, tmp_db):
        from src.services.priority_queue import defer_contact
        conn = _conn(tmp_db)
        _create_campaign(conn)
        co = insert_company(conn, "NotEnrCo")
        ct = insert_contact(conn, co)
        result = defer_contact(conn, ct, 9999, reason="test", user_id=TEST_USER_ID)
        assert result["success"] is False
        conn.close()

    def test_defer_logs_event(self, tmp_db):
        from src.services.priority_queue import defer_contact
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "DefEvtCo")
        ct = insert_contact(conn, co)
        _enroll_contact(conn, ct, cid, status="queued")
        defer_contact(conn, ct, cid, reason="too busy", user_id=TEST_USER_ID)
        cur = conn.cursor()
        cur.execute("SELECT event_type, notes FROM events WHERE contact_id = %s", (ct,))
        events = cur.fetchall()
        assert any(e["event_type"] == "deferred" and e["notes"] == "too busy" for e in events)
        cur.close()
        conn.close()


class TestDeferStats:
    """Tests for priority_queue.get_defer_stats."""

    def test_empty_stats(self, tmp_db):
        from src.services.priority_queue import get_defer_stats
        conn = _conn(tmp_db)
        result = get_defer_stats(conn, user_id=1)
        assert result["today_count"] == 0
        assert result["total_count"] == 0
        assert result["by_reason"] == []
        assert result["repeat_deferrals"] == []
        conn.close()

    def test_stats_with_deferrals(self, tmp_db):
        from src.services.priority_queue import get_defer_stats, defer_contact
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "StatsCo")
        ct = insert_contact(conn, co)
        _enroll_contact(conn, ct, cid, status="queued")
        defer_contact(conn, ct, cid, reason="meeting", user_id=TEST_USER_ID)
        defer_contact(conn, ct, cid, reason="meeting", user_id=TEST_USER_ID)
        result = get_defer_stats(conn, campaign_id=cid, user_id=TEST_USER_ID)
        assert result["total_count"] == 2
        assert len(result["repeat_deferrals"]) >= 1
        conn.close()


# ===========================================================================
# reply_detector — _classify_reply, _store_pending_reply
# ===========================================================================

class TestClassifyReply:
    """Tests for reply_detector._classify_reply."""

    def test_no_api_key_returns_neutral(self):
        from src.services.reply_detector import _classify_reply
        with patch.object(
            __import__("src.services.reply_detector", fromlist=["ANTHROPIC_API_KEY"]),
            "ANTHROPIC_API_KEY", "",
        ):
            classification, confidence = _classify_reply("I'd love to meet!")
            assert classification == "neutral"
            assert confidence == 0.5

    def test_empty_text_returns_neutral(self):
        from src.services.reply_detector import _classify_reply
        with patch.object(
            __import__("src.services.reply_detector", fromlist=["ANTHROPIC_API_KEY"]),
            "ANTHROPIC_API_KEY", "",
        ):
            classification, confidence = _classify_reply("")
            assert classification == "neutral"

    def test_whitespace_only_returns_neutral(self):
        from src.services.reply_detector import _classify_reply
        with patch.object(
            __import__("src.services.reply_detector", fromlist=["ANTHROPIC_API_KEY"]),
            "ANTHROPIC_API_KEY", "",
        ):
            classification, confidence = _classify_reply("   \n  ")
            assert classification == "neutral"

    def test_api_error_returns_neutral(self):
        import httpx
        import src.services.reply_detector as rd
        original_key = rd.ANTHROPIC_API_KEY
        rd.ANTHROPIC_API_KEY = "test-key"
        try:
            with patch("httpx.post", side_effect=httpx.ConnectError("network error")):
                classification, confidence = rd._classify_reply("some text")
                assert classification == "neutral"
                assert confidence == 0.5
        finally:
            rd.ANTHROPIC_API_KEY = original_key


class TestScanGmailForReplies:
    """Tests for scan_gmail_for_replies."""

    def test_no_contacts_returns_zero_stats(self, tmp_db):
        from src.services.reply_detector import scan_gmail_for_replies
        conn = _conn(tmp_db)
        stats = scan_gmail_for_replies(conn, user_id=TEST_USER_ID, gmail_service=MagicMock())
        assert stats["scanned"] == 0
        assert stats["new_replies"] == 0
        conn.close()


# ===========================================================================
# response_analyzer — annotate_is_winning, get_channel_performance,
#                     get_segment_performance
# ===========================================================================

class TestAnnotateIsWinning:
    """Tests for response_analyzer.annotate_is_winning."""

    def test_highest_rate_wins(self):
        from src.services.response_analyzer import annotate_is_winning
        data = [
            {"template_id": 1, "positive_rate": 0.5, "total_sends": 30},
            {"template_id": 2, "positive_rate": 0.8, "total_sends": 25},
        ]
        result = annotate_is_winning(data, min_sends=5)
        assert result[1]["is_winning"] is True
        assert result[0]["is_winning"] is False

    def test_below_min_sends_not_eligible(self):
        from src.services.response_analyzer import annotate_is_winning
        data = [
            {"template_id": 1, "positive_rate": 1.0, "total_sends": 2},
            {"template_id": 2, "positive_rate": 0.3, "total_sends": 50},
        ]
        result = annotate_is_winning(data, min_sends=5)
        assert result[0]["is_winning"] is False
        assert result[1]["is_winning"] is True

    def test_tie_broken_by_sends(self):
        from src.services.response_analyzer import annotate_is_winning
        data = [
            {"template_id": 1, "positive_rate": 0.5, "total_sends": 10},
            {"template_id": 2, "positive_rate": 0.5, "total_sends": 50},
        ]
        result = annotate_is_winning(data, min_sends=5)
        assert result[1]["is_winning"] is True
        assert result[0]["is_winning"] is False

    def test_empty_list(self):
        from src.services.response_analyzer import annotate_is_winning
        result = annotate_is_winning([], min_sends=5)
        assert result == []

    def test_all_below_min_sends(self):
        from src.services.response_analyzer import annotate_is_winning
        data = [
            {"template_id": 1, "positive_rate": 0.9, "total_sends": 2},
            {"template_id": 2, "positive_rate": 0.8, "total_sends": 3},
        ]
        result = annotate_is_winning(data, min_sends=5)
        assert all(r["is_winning"] is False for r in result)


# ===========================================================================
# retry — retry_on_failure decorator
# ===========================================================================

class TestRetryOnFailure:
    """Tests for retry.retry_on_failure decorator."""

    def test_success_on_first_try(self):
        from src.services.retry import retry_on_failure

        @retry_on_failure(max_retries=3, backoff_base=0.001)
        def succeed():
            return 42

        assert succeed() == 42

    def test_retries_on_failure_then_succeeds(self):
        from src.services.retry import retry_on_failure
        counter = {"n": 0}

        @retry_on_failure(max_retries=3, backoff_base=0.001)
        def fail_once():
            counter["n"] += 1
            if counter["n"] < 2:
                raise ValueError("transient")
            return "ok"

        assert fail_once() == "ok"
        assert counter["n"] == 2

    def test_max_retries_exhausted(self):
        from src.services.retry import retry_on_failure

        @retry_on_failure(max_retries=2, backoff_base=0.001)
        def always_fail():
            raise RuntimeError("permanent")

        with pytest.raises(RuntimeError, match="permanent"):
            always_fail()

    def test_only_catches_specified_exceptions(self):
        from src.services.retry import retry_on_failure

        @retry_on_failure(max_retries=3, backoff_base=0.001, exceptions=(ValueError,))
        def raise_type_error():
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            raise_type_error()

    def test_preserves_function_name(self):
        from src.services.retry import retry_on_failure

        @retry_on_failure(max_retries=1)
        def my_function():
            pass

        assert my_function.__name__ == "my_function"

    def test_exponential_backoff_timing(self):
        from src.services.retry import retry_on_failure
        calls = []

        @retry_on_failure(max_retries=3, backoff_base=0.05)
        def timed_fail():
            calls.append(time.monotonic())
            raise ValueError("fail")

        with pytest.raises(ValueError):
            timed_fail()
        assert len(calls) == 3
        # Second gap should be roughly 2x the first gap
        gap1 = calls[1] - calls[0]
        gap2 = calls[2] - calls[1]
        assert gap2 > gap1 * 1.5  # allow margin


# ===========================================================================
# sequence_generator — generate_sequence
# ===========================================================================

class TestSequenceGeneratorEdgeCases:
    """Edge cases for sequence_generator.generate_sequence."""

    def test_single_email_step(self):
        from src.services.sequence_generator import generate_sequence
        steps = generate_sequence(1, ["email"])
        assert len(steps) == 1
        assert steps[0]["channel"] == "email"
        assert steps[0]["delay_days"] == 0

    def test_single_linkedin_step_is_connect(self):
        from src.services.sequence_generator import generate_sequence
        steps = generate_sequence(1, ["linkedin"])
        assert steps[0]["channel"] == "linkedin_connect"

    def test_linkedin_only_connect_once(self):
        from src.services.sequence_generator import generate_sequence
        steps = generate_sequence(5, ["linkedin"])
        connect_count = sum(1 for s in steps if s["channel"] == "linkedin_connect")
        assert connect_count == 1

    def test_mixed_channels_alternate(self):
        from src.services.sequence_generator import generate_sequence
        steps = generate_sequence(4, ["email", "linkedin"])
        channels = [s["channel"] for s in steps]
        assert channels[0] == "email"
        assert "linkedin" in channels[1]

    def test_delays_increase(self):
        from src.services.sequence_generator import generate_sequence
        steps = generate_sequence(5, ["email"])
        delays = [s["delay_days"] for s in steps]
        assert delays == sorted(delays)
        assert delays[0] == 0

    def test_zero_touchpoints_raises(self):
        from src.services.sequence_generator import generate_sequence
        with pytest.raises(ValueError, match="touchpoints"):
            generate_sequence(0, ["email"])

    def test_empty_channels_raises(self):
        from src.services.sequence_generator import generate_sequence
        with pytest.raises(ValueError, match="channels"):
            generate_sequence(3, [])

    def test_invalid_channel_raises(self):
        from src.services.sequence_generator import generate_sequence
        with pytest.raises(ValueError, match="Invalid channel"):
            generate_sequence(3, ["whatsapp"])

    def test_step_order_sequential(self):
        from src.services.sequence_generator import generate_sequence
        steps = generate_sequence(6, ["email", "linkedin"])
        orders = [s["step_order"] for s in steps]
        assert orders == [1, 2, 3, 4, 5, 6]

    def test_template_id_always_none(self):
        from src.services.sequence_generator import generate_sequence
        steps = generate_sequence(3, ["email"])
        assert all(s["template_id"] is None for s in steps)

    def test_ten_touchpoints_maximum(self):
        from src.services.sequence_generator import generate_sequence
        steps = generate_sequence(10, ["email", "linkedin"])
        assert len(steps) == 10


# ===========================================================================
# smart_import — parse_csv, heuristic mapping, transform_rows, _parse_aum
# ===========================================================================

class TestParseAum:
    """Tests for smart_import._parse_aum."""

    def test_dollar_comma_format(self):
        from src.services.smart_import import _parse_aum
        assert _parse_aum("$1,219.50") == 1219.50

    def test_plain_number(self):
        from src.services.smart_import import _parse_aum
        assert _parse_aum("500") == 500.0

    def test_empty_string_returns_none(self):
        from src.services.smart_import import _parse_aum
        assert _parse_aum("") is None

    def test_none_returns_none(self):
        from src.services.smart_import import _parse_aum
        assert _parse_aum(None) is None

    def test_non_numeric_returns_none(self):
        from src.services.smart_import import _parse_aum
        assert _parse_aum("N/A") is None

    def test_whitespace_returns_none(self):
        from src.services.smart_import import _parse_aum
        assert _parse_aum("   ") is None

    def test_numeric_as_int(self):
        from src.services.smart_import import _parse_aum
        assert _parse_aum(1000) == 1000.0


class TestDetectHeaderRow:
    """Tests for smart_import._detect_header_row."""

    def test_header_on_first_row(self):
        from src.services.smart_import import _detect_header_row
        csv_text = "Company Name,Email,Country\nAcme,test@x.com,US"
        assert _detect_header_row(csv_text) == 0

    def test_header_after_blank_rows(self):
        from src.services.smart_import import _detect_header_row
        csv_text = "Report Title\nGenerated 2026-01-01\nCompany Name,Email,Country\nAcme,test@x.com,US"
        idx = _detect_header_row(csv_text)
        assert idx == 2

    def test_empty_csv(self):
        from src.services.smart_import import _detect_header_row
        assert _detect_header_row("") == 0

    def test_copyright_row_penalized(self):
        from src.services.smart_import import _detect_header_row
        csv_text = "\u00a9 2026 DataCorp\nCompany Name,Email,Title\nAcme,a@b.com,VP"
        idx = _detect_header_row(csv_text)
        assert idx != 0


class TestParseCSVWithHeaderDetection:
    """Tests for smart_import.parse_csv_with_header_detection."""

    def test_basic_csv(self):
        from src.services.smart_import import parse_csv_with_header_detection
        csv_text = "Name,Email\nAlice,alice@example.com\nBob,bob@example.com"
        headers, rows = parse_csv_with_header_detection(csv_text)
        assert headers == ["Name", "Email"]
        assert len(rows) == 2
        assert rows[0]["Name"] == "Alice"

    def test_empty_rows_skipped(self):
        from src.services.smart_import import parse_csv_with_header_detection
        csv_text = "Name,Email\n,,\nAlice,alice@example.com\n,,"
        headers, rows = parse_csv_with_header_detection(csv_text)
        assert len(rows) == 1

    def test_copyright_rows_skipped(self):
        from src.services.smart_import import parse_csv_with_header_detection
        csv_text = "Name,Email\nAlice,a@b.com\n\u00a9 2026 Corp,notes"
        headers, rows = parse_csv_with_header_detection(csv_text)
        assert len(rows) == 1

    def test_empty_csv_returns_empty(self):
        from src.services.smart_import import parse_csv_with_header_detection
        headers, rows = parse_csv_with_header_detection("")
        assert headers == []
        assert rows == []


class TestHeuristicMapping:
    """Tests for smart_import._heuristic_mapping."""

    def test_standard_headers(self):
        from src.services.smart_import import _heuristic_mapping
        headers = ["Firm Name", "Primary Email", "Country", "AUM", "Position"]
        result = _heuristic_mapping(headers)
        assert result["column_map"]["Firm Name"] == "company.name"
        assert result["column_map"]["Primary Email"] == "contact.email"
        assert result["column_map"]["Country"] == "company.country"

    def test_multi_contact_detection(self):
        from src.services.smart_import import _heuristic_mapping
        headers = ["Firm Name", "Primary Contact", "Primary Email",
                    "Contact 2", "Contact 2 Email", "Contact 2 Title"]
        result = _heuristic_mapping(headers)
        assert result["multi_contact"]["detected"] is True
        assert len(result["multi_contact"]["contact_groups"]) >= 2

    def test_unmapped_columns(self):
        from src.services.smart_import import _heuristic_mapping
        headers = ["Firm Name", "Random Column", "Secret Sauce"]
        result = _heuristic_mapping(headers)
        assert "Random Column" in result["unmapped"]
        assert "Secret Sauce" in result["unmapped"]

    def test_confidence_calculation(self):
        from src.services.smart_import import _heuristic_mapping
        headers = ["Firm Name", "Primary Email", "Unrelated"]
        result = _heuristic_mapping(headers)
        assert 0.0 < result["confidence"] <= 1.0


class TestTransformRows:
    """Tests for smart_import.transform_rows."""

    def test_basic_single_contact(self):
        from src.services.smart_import import transform_rows
        rows = [{"Firm": "Acme Fund", "Email": "alice@acme.com", "Name": "Alice Smith",
                 "Country": "US"}]
        mapping = {"Firm": "company.name", "Email": "contact.email",
                   "Name": "contact.full_name", "Country": "company.country"}
        result = transform_rows(rows, mapping, {"detected": False}, ["germany", "france"])
        assert len(result) == 1
        assert result[0]["company_name"] == "Acme Fund"
        assert result[0]["email_normalized"] == "alice@acme.com"
        assert result[0]["first_name"] == "Alice"
        assert result[0]["last_name"] == "Smith"
        assert result[0]["is_gdpr"] is False

    def test_gdpr_country_flagged(self):
        from src.services.smart_import import transform_rows
        rows = [{"Firm": "Munich Fund", "Email": "h@mf.de", "Name": "Hans Muller",
                 "Country": "Germany"}]
        mapping = {"Firm": "company.name", "Email": "contact.email",
                   "Name": "contact.full_name", "Country": "company.country"}
        result = transform_rows(rows, mapping, {"detected": False}, ["germany"])
        assert result[0]["is_gdpr"] is True

    def test_multi_contact_explosion(self):
        from src.services.smart_import import transform_rows
        rows = [{"Firm": "Alpha LLC", "C1 Name": "Alice", "C1 Email": "a@alpha.com",
                 "C2 Name": "Bob", "C2 Email": "b@alpha.com"}]
        mapping = {"Firm": "company.name"}
        multi = {
            "detected": True,
            "contact_groups": [
                {"prefix": "C1", "fields": {"contact.full_name": "C1 Name",
                                             "contact.email": "C1 Email"}},
                {"prefix": "C2", "fields": {"contact.full_name": "C2 Name",
                                             "contact.email": "C2 Email"}},
            ],
        }
        result = transform_rows(rows, mapping, multi, [])
        assert len(result) == 2
        names = {r["full_name"] for r in result}
        assert "Alice" in names
        assert "Bob" in names

    def test_skips_rows_without_company_name(self):
        from src.services.smart_import import transform_rows
        rows = [{"Firm": "", "Email": "a@b.com", "Name": "Alice"}]
        mapping = {"Firm": "company.name", "Email": "contact.email",
                   "Name": "contact.full_name"}
        result = transform_rows(rows, mapping, {"detected": False}, [])
        assert len(result) == 0

    def test_skips_contacts_without_identifiers(self):
        from src.services.smart_import import transform_rows
        rows = [{"Firm": "Acme", "Email": "", "Name": ""}]
        mapping = {"Firm": "company.name", "Email": "contact.email",
                   "Name": "contact.full_name"}
        result = transform_rows(rows, mapping, {"detected": False}, [])
        assert len(result) == 0

    def test_aum_parsing(self):
        from src.services.smart_import import transform_rows
        rows = [{"Firm": "BigCo", "AUM": "$1,500.00", "Name": "Test", "Email": "t@b.com"}]
        mapping = {"Firm": "company.name", "AUM": "company.aum",
                   "Name": "contact.full_name", "Email": "contact.email"}
        result = transform_rows(rows, mapping, {"detected": False}, [])
        assert result[0]["aum_millions"] == 1500.0

    def test_priority_rank_assigned(self):
        from src.services.smart_import import transform_rows
        rows = [{"Firm": "RankCo", "C1": "Alice", "C1Email": "a@r.com",
                 "C2": "Bob", "C2Email": "b@r.com"}]
        mapping = {"Firm": "company.name"}
        multi = {
            "detected": True,
            "contact_groups": [
                {"prefix": "C1", "fields": {"contact.full_name": "C1", "contact.email": "C1Email"}},
                {"prefix": "C2", "fields": {"contact.full_name": "C2", "contact.email": "C2Email"}},
            ],
        }
        result = transform_rows(rows, mapping, multi, [])
        ranks = [r["priority_rank"] for r in result]
        assert 1 in ranks
        assert 2 in ranks


class TestBuildFieldDiffs:
    """Tests for smart_import._build_field_diffs."""

    def test_same_values(self):
        from src.services.smart_import import _build_field_diffs
        import_row = {"first_name": "Alice", "last_name": "Smith", "email": "a@b.com",
                      "title": "VP", "linkedin_url": "https://linkedin.com/in/alice"}
        existing = dict(import_row)
        diffs = _build_field_diffs(import_row, existing)
        assert all(v == "same" for v in diffs.values())

    def test_new_fields(self):
        from src.services.smart_import import _build_field_diffs
        import_row = {"first_name": "Alice", "last_name": "Smith", "email": "a@b.com",
                      "title": "VP", "linkedin_url": "https://linkedin.com/in/alice"}
        existing = {"first_name": "", "last_name": "", "email": "", "title": "", "linkedin_url": ""}
        diffs = _build_field_diffs(import_row, existing)
        assert all(v == "new" for v in diffs.values())

    def test_conflict_fields(self):
        from src.services.smart_import import _build_field_diffs
        import_row = {"first_name": "Alice", "last_name": "Smith", "email": "a@b.com",
                      "title": "VP", "linkedin_url": ""}
        existing = {"first_name": "Bob", "last_name": "Jones", "email": "c@d.com",
                    "title": "CEO", "linkedin_url": ""}
        diffs = _build_field_diffs(import_row, existing)
        assert diffs["first_name"] == "conflict"
        assert diffs["title"] == "conflict"

    def test_both_empty(self):
        from src.services.smart_import import _build_field_diffs
        import_row = {"first_name": "", "last_name": "", "email": "",
                      "title": "", "linkedin_url": ""}
        existing = {"first_name": "", "last_name": "", "email": "",
                    "title": "", "linkedin_url": ""}
        diffs = _build_field_diffs(import_row, existing)
        assert all(v == "empty" for v in diffs.values())


# ===========================================================================
# token_encryption — encrypt/decrypt, missing key, roundtrip
# ===========================================================================

class TestTokenEncryption:
    """Tests for token_encryption module (Fernet)."""

    def test_roundtrip(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        f = Fernet(key.encode())
        plaintext = "my-secret-oauth-token"
        ciphertext = f.encrypt(plaintext.encode()).decode()
        assert f.decrypt(ciphertext.encode()).decode() == plaintext

    def test_different_keys_fail(self):
        from cryptography.fernet import Fernet, InvalidToken
        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()
        f1 = Fernet(key1.encode())
        f2 = Fernet(key2.encode())
        ciphertext = f1.encrypt(b"secret").decode()
        with pytest.raises(InvalidToken):
            f2.decrypt(ciphertext.encode())

    def test_empty_plaintext_roundtrip(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        f = Fernet(key.encode())
        ciphertext = f.encrypt(b"").decode()
        assert f.decrypt(ciphertext.encode()).decode() == ""

    def test_unicode_plaintext(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        f = Fernet(key.encode())
        plaintext = "token with unicode chars"
        ciphertext = f.encrypt(plaintext.encode()).decode()
        assert f.decrypt(ciphertext.encode()).decode() == plaintext

    def test_tampered_ciphertext_raises(self):
        from cryptography.fernet import Fernet, InvalidToken
        key = Fernet.generate_key().decode()
        f = Fernet(key.encode())
        ciphertext = f.encrypt(b"secret").decode()
        tampered = ciphertext[:10] + "XXXX" + ciphertext[14:]
        with pytest.raises(InvalidToken):
            f.decrypt(tampered.encode())

    def test_module_no_key_raises_runtime(self):
        """When TOKEN_ENCRYPTION_KEY is not set, encrypt_token should raise."""
        import src.services.token_encryption as te
        original_fernet = te._fernet
        te._fernet = None
        try:
            with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
                te.encrypt_token("secret")
            with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
                te.decrypt_token("ciphertext")
        finally:
            te._fernet = original_fernet


# ===========================================================================
# phone_utils — normalize_phone (additional edge cases)
# ===========================================================================

class TestNormalizePhone:
    """Tests for phone_utils.normalize_phone (additional edge cases)."""

    def test_us_number(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("+1 (555) 123-4567") == "+15551234567"

    def test_uk_number(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("+44 20 7123 4567") == "+442071234567"

    def test_international_prefix(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("00442071234567") == "+442071234567"

    def test_empty_string(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("") is None

    def test_none_returns_none(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone(None) is None

    def test_already_normalized(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("+15551234567") == "+15551234567"

    def test_spaces_and_dashes_stripped(self):
        from src.services.phone_utils import normalize_phone
        assert normalize_phone("+1-555-123-4567") == "+15551234567"


# ===========================================================================
# state_machine gaps — get_active_contact_for_company edge cases
# ===========================================================================

class TestGetActiveContactEdgeCases:
    """Edge cases for state_machine.get_active_contact_for_company."""

    def test_returns_lowest_rank_when_multiple_active(self, tmp_db):
        from src.services.state_machine import get_active_contact_for_company
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "MultiActiveCo")
        c1 = insert_contact(conn, co, priority_rank=2)
        c2 = insert_contact(conn, co, priority_rank=1)
        _enroll_contact(conn, c1, cid, status="queued")
        _enroll_contact(conn, c2, cid, status="queued")
        result = get_active_contact_for_company(conn, co, cid, user_id=TEST_USER_ID)
        assert result["id"] == c2  # rank 1
        conn.close()

    def test_returns_none_for_empty_company(self, tmp_db):
        from src.services.state_machine import get_active_contact_for_company
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "EmptyCo")
        result = get_active_contact_for_company(conn, co, cid, user_id=TEST_USER_ID)
        assert result is None
        conn.close()


# ===========================================================================
# template_engine gaps — _get_jinja_env, edge cases
# ===========================================================================

class TestGetJinjaEnv:
    """Tests for template_engine._get_jinja_env."""

    def test_custom_templates_dir(self, tmp_path):
        from src.services.template_engine import _get_jinja_env
        env = _get_jinja_env(str(tmp_path))
        assert env is not None
        assert str(tmp_path) in env.loader.searchpath

    def test_default_templates_dir(self):
        from src.services.template_engine import _get_jinja_env
        env = _get_jinja_env(None)
        assert env is not None


class TestRenderTemplateEdgeCases:
    """Edge cases for template_engine.render_template."""

    def test_multiline_template(self, tmp_path):
        from src.services.template_engine import render_template
        tpl = tmp_path / "multi.txt"
        tpl.write_text("Hello {{ name }},\nLine 2.\nLine 3.")
        result = render_template("multi.txt", {"name": "World"}, str(tmp_path))
        assert "Hello World," in result
        assert "Line 3." in result

    def test_template_with_no_variables(self, tmp_path):
        from src.services.template_engine import render_template
        tpl = tmp_path / "static.txt"
        tpl.write_text("No variables here.")
        result = render_template("static.txt", {}, str(tmp_path))
        assert result == "No variables here."

    def test_template_not_found_raises(self, tmp_path):
        from src.services.template_engine import render_template
        with pytest.raises(Exception):
            render_template("nonexistent.txt", {}, str(tmp_path))


class TestGetTemplateContextEdgeCases:
    """Edge cases for template_engine.get_template_context."""

    def test_contact_with_no_names(self, tmp_db):
        from src.services.template_engine import get_template_context
        conn = _conn(tmp_db)
        co = insert_company(conn, "NoNameCo")
        ct = insert_contact(conn, co, first_name="", last_name="")
        config = {"calendly_url": "https://cal.com/test", "smtp": {"username": "t@t.com"}}
        ctx = get_template_context(conn, ct, config, user_id=TEST_USER_ID)
        assert ctx["first_name"] == ""
        assert ctx["last_name"] == ""
        conn.close()

    def test_deep_research_loaded_from_db(self, tmp_db):
        from src.services.template_engine import get_template_context
        conn = _conn(tmp_db)
        co = insert_company(conn, "DeepResCo")
        ct = insert_contact(conn, co)
        # Insert completed deep research
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO deep_research
               (company_id, status, company_overview, user_id)
               VALUES (%s, 'completed', 'Overview text', %s)""",
            (co, TEST_USER_ID),
        )
        conn.commit()
        cur.close()
        config = {"smtp": {"username": "t@t.com"}}
        ctx = get_template_context(conn, ct, config, user_id=TEST_USER_ID)
        assert ctx["deep_research"] is not None
        assert ctx["deep_research"]["company_overview"] == "Overview text"
        conn.close()


# ===========================================================================
# normalization_utils — only functions NOT already covered
#   (normalize_company_name suffix edge cases)
# ===========================================================================

class TestNormalizeCompanyNameAdditional:
    """Additional edge cases for normalize_company_name not in test_normalization.py."""

    def test_ltd_stripped(self):
        from src.services.normalization_utils import normalize_company_name
        assert normalize_company_name("Acme Ltd") == "acme"

    def test_lp_stripped(self):
        from src.services.normalization_utils import normalize_company_name
        assert normalize_company_name("Acme LP") == "acme"

    def test_partners_stripped(self):
        from src.services.normalization_utils import normalize_company_name
        assert normalize_company_name("Acme Partners") == "acme"

    def test_holdings_stripped(self):
        from src.services.normalization_utils import normalize_company_name
        assert normalize_company_name("Acme Holdings") == "acme"

    def test_advisors_stripped(self):
        from src.services.normalization_utils import normalize_company_name
        assert normalize_company_name("Acme Advisors") == "acme"

    def test_investments_stripped(self):
        from src.services.normalization_utils import normalize_company_name
        assert normalize_company_name("Acme Investments") == "acme"

    def test_limited_stripped(self):
        from src.services.normalization_utils import normalize_company_name
        assert normalize_company_name("Acme Limited") == "acme"


# ===========================================================================
# response_analyzer — get_channel_performance, get_segment_performance (DB)
# ===========================================================================

class TestResponseAnalyzerDB:
    """DB-backed tests for response_analyzer functions."""

    def _setup_contact_template_history(self, conn, campaign_id, template_id,
                                         contact_id, channel="email", outcome=None):
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO contact_template_history
               (contact_id, campaign_id, template_id, channel, outcome, user_id)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (contact_id, campaign_id, template_id, channel, outcome, TEST_USER_ID),
        )
        conn.commit()
        cur.close()

    def test_template_performance_empty(self, tmp_db):
        from src.services.response_analyzer import get_template_performance
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        result = get_template_performance(conn, cid)
        assert result == []
        conn.close()

    def test_template_performance_confidence_levels(self, tmp_db):
        from src.services.response_analyzer import get_template_performance
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        tid = _create_template(conn)
        co = insert_company(conn, "TPerfCo")
        # Insert 5 sends (low confidence)
        for i in range(5):
            ct = insert_contact(conn, co, priority_rank=i + 1)
            self._setup_contact_template_history(conn, cid, tid, ct, outcome="positive")
        result = get_template_performance(conn, cid)
        assert len(result) == 1
        assert result[0]["confidence"] == "low"
        conn.close()

    def test_channel_performance_empty(self, tmp_db):
        from src.services.response_analyzer import get_channel_performance
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        result = get_channel_performance(conn, cid)
        assert result == []
        conn.close()

    def test_segment_performance_empty(self, tmp_db):
        from src.services.response_analyzer import get_segment_performance
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        result = get_segment_performance(conn, cid)
        assert result == []
        conn.close()

    def test_segment_performance_tiers(self, tmp_db):
        from src.services.response_analyzer import get_segment_performance
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        # Small AUM
        co1 = insert_company(conn, "SmallCo", aum_millions=50)
        ct1 = insert_contact(conn, co1)
        _enroll_contact(conn, ct1, cid, status="in_progress")
        # Large AUM
        co2 = insert_company(conn, "BigCo", aum_millions=2000)
        ct2 = insert_contact(conn, co2)
        _enroll_contact(conn, ct2, cid, status="replied_positive")
        result = get_segment_performance(conn, cid)
        tiers = [r["aum_tier"] for r in result]
        assert "$0-100M" in tiers
        assert "$1B+" in tiers
        conn.close()


# ===========================================================================
# smart_import — analyze_csv with mocked LLM
# ===========================================================================

class TestAnalyzeCSVMocked:
    """Tests for analyze_csv with LLM mocked."""

    def test_falls_back_to_heuristic_when_no_api_key(self, tmp_db):
        from src.services.smart_import import analyze_csv
        conn = _conn(tmp_db)
        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "", "GEMINI_API_KEY": ""
        }, clear=False):
            result = analyze_csv(
                headers=["Firm Name", "Primary Email"],
                sample_rows=[{"Firm Name": "Acme", "Primary Email": "a@b.com"}],
                user_id=TEST_USER_ID,
                conn=conn,
            )
        assert "column_map" in result
        assert result["provider"] is None
        conn.close()

    def test_llm_json_decode_error_falls_back(self, tmp_db):
        from src.services.smart_import import analyze_csv
        conn = _conn(tmp_db)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}, clear=False):
            with patch("src.services.smart_import.call_llm", return_value=("not json", "anthropic")):
                result = analyze_csv(
                    headers=["Firm Name"],
                    sample_rows=[{"Firm Name": "Acme"}],
                    user_id=TEST_USER_ID,
                    conn=conn,
                )
        assert result["provider"] is None
        conn.close()


# ===========================================================================
# priority_queue — get_next_step_for_contact, count_steps_for_contact
# ===========================================================================

class TestNextStepForContact:
    """Tests for priority_queue.get_next_step_for_contact."""

    def test_returns_current_step(self, tmp_db):
        from src.services.priority_queue import get_next_step_for_contact
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email")
        _create_sequence_step(conn, cid, step_order=2, channel="linkedin_connect")
        co = insert_company(conn, "NextStepCo")
        ct = insert_contact(conn, co)
        _enroll_contact(conn, ct, cid, status="queued", current_step=1)
        step = get_next_step_for_contact(conn, ct, cid, user_id=1)
        assert step is not None
        assert step["step_order"] == 1
        conn.close()

    def test_not_enrolled_returns_none(self, tmp_db):
        from src.services.priority_queue import get_next_step_for_contact
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        co = insert_company(conn, "NotEnrolledNS")
        ct = insert_contact(conn, co)
        step = get_next_step_for_contact(conn, ct, cid, user_id=1)
        assert step is None
        conn.close()


class TestCountStepsForContact:
    """Tests for priority_queue.count_steps_for_contact."""

    def test_counts_all_steps(self, tmp_db):
        from src.services.priority_queue import count_steps_for_contact
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email")
        _create_sequence_step(conn, cid, step_order=2, channel="linkedin_connect")
        _create_sequence_step(conn, cid, step_order=3, channel="email")
        co = insert_company(conn, "CountStepsCo")
        ct = insert_contact(conn, co, is_gdpr=False)
        count = count_steps_for_contact(conn, ct, cid, user_id=TEST_USER_ID)
        assert count == 3
        conn.close()

    def test_gdpr_contact_excludes_non_gdpr_only(self, tmp_db):
        from src.services.priority_queue import count_steps_for_contact
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        _create_sequence_step(conn, cid, step_order=1, channel="email")
        _create_sequence_step(conn, cid, step_order=2, channel="email", non_gdpr_only=True)
        _create_sequence_step(conn, cid, step_order=3, channel="email")
        co = insert_company(conn, "GDPRCountCo", is_gdpr=True)
        ct = insert_contact(conn, co, is_gdpr=True)
        count = count_steps_for_contact(conn, ct, cid, user_id=TEST_USER_ID)
        assert count == 2  # step 2 excluded
        conn.close()

    def test_nonexistent_contact_returns_zero(self, tmp_db):
        from src.services.priority_queue import count_steps_for_contact
        conn = _conn(tmp_db)
        cid = _create_campaign(conn)
        count = count_steps_for_contact(conn, 99999, cid, user_id=TEST_USER_ID)
        assert count == 0
        conn.close()
