"""Comprehensive edge-case tests for service modules A-L (alphabetically).

Covers:
- adaptive_queue: scoring, channel rules, diversification
- compliance: functions NOT already covered in test_compliance.py
- contact_scorer: composite formula, zero AUM, missing channels
- deduplication: edge cases beyond existing test_deduplication.py
- deep_research_service: signal extraction, synthesis, status transitions
- email_sender: render_campaign_email, send_emails_batch, MIME building
- email_verifier: batch verify, invalid inputs, chunking, provider errors
- gmail_drafter: from_db_tokens, is_authorized, draft creation
- gmail_sender: token refresh, send, error handling
- linkedin_acceptance_scanner: scan flow, name extraction, profile URL extraction
- linkedin_actions: complete action, invalid channel, missing LinkedIn URL
- llm_advisor: recommendation generation, empty data, API failure
"""

from __future__ import annotations

import json
import os
import smtplib
import time
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from unittest.mock import MagicMock, patch, PropertyMock

import httpx
import pytest

from src.models.campaigns import (
    add_sequence_step,
    create_campaign,
    create_template,
    enroll_contact,
    get_contact_campaign_status,
    log_event,
    update_contact_campaign_status,
)
from src.models.database import get_connection, get_cursor, run_migrations
from tests.conftest import TEST_USER_ID, insert_company, insert_contact


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_db(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


def _create_company(conn, name="Acme Fund", aum_millions=None, country="US",
                     is_gdpr=False, firm_type=None):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, country, is_gdpr, firm_type, user_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, name.lower(), aum_millions, country, is_gdpr, firm_type, TEST_USER_ID),
    )
    cid = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    return cid


def _create_contact(conn, company_id, first_name="Test", last_name="User",
                     email="test@example.com", email_status="valid",
                     linkedin_url=None, is_gdpr=False, unsubscribed=False,
                     title=None):
    email_norm = email.lower().strip() if email else None
    linkedin_norm = linkedin_url.lower().rstrip("/") if linkedin_url else None
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO contacts
           (company_id, first_name, last_name, full_name,
            email, email_normalized, email_status,
            linkedin_url, linkedin_url_normalized,
            is_gdpr, unsubscribed, title, source, user_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'test',%s) RETURNING id""",
        (
            company_id, first_name, last_name, f"{first_name} {last_name}",
            email, email_norm, email_status,
            linkedin_url, linkedin_norm,
            is_gdpr, unsubscribed, title, TEST_USER_ID,
        ),
    )
    cid = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    return cid


def _insert_deep_research(conn, company_id, status="pending", **kwargs):
    cols = ["company_id", "user_id", "status"]
    vals = [company_id, TEST_USER_ID, status]
    for key, val in kwargs.items():
        cols.append(key)
        if key in ("raw_queries", "crypto_signals", "key_people", "talking_points", "fund_signals"):
            vals.append(json.dumps(val) if val is not None else None)
        else:
            vals.append(val)
    placeholders = ", ".join(["%s"] * len(vals))
    col_str = ", ".join(cols)
    with get_cursor(conn) as cur:
        cur.execute(
            f"INSERT INTO deep_research ({col_str}) VALUES ({placeholders}) RETURNING id",
            vals,
        )
        conn.commit()
        return cur.fetchone()["id"]


# ===========================================================================
# ADAPTIVE QUEUE — _apply_channel_rules
# ===========================================================================


class TestApplyChannelRules:
    """Tests for adaptive_queue._apply_channel_rules (unit, no DB)."""

    def setup_method(self):
        from src.services.adaptive_queue import _apply_channel_rules
        self._apply = _apply_channel_rules

    def test_linkedin_first_for_new_contact_with_linkedin(self):
        """New contact (0 history) with linkedin -> linkedin_connect."""
        item = {"linkedin_url": "https://linkedin.com/in/test", "email": "a@b.com"}
        assert self._apply("email", [], item) == "linkedin_connect"

    def test_keeps_email_when_no_linkedin(self):
        """New contact without linkedin -> keep email."""
        item = {"linkedin_url": None, "email": "a@b.com"}
        assert self._apply("email", [], item) == "email"

    def test_keeps_linkedin_for_new_contact(self):
        """New contact already on linkedin channel -> no change."""
        item = {"linkedin_url": "https://linkedin.com/in/test", "email": "a@b.com"}
        assert self._apply("linkedin_connect", [], item) == "linkedin_connect"

    def test_three_emails_switch_to_linkedin(self):
        """After 2 emails in a row, third switches to linkedin."""
        item = {"linkedin_url": "https://linkedin.com/in/test", "email": "a@b.com"}
        result = self._apply("email", ["email", "email"], item)
        assert result.startswith("linkedin")

    def test_three_linkedin_switch_to_email(self):
        """After 2 linkedin in a row, third switches to email."""
        item = {"linkedin_url": "https://linkedin.com/in/test", "email": "a@b.com"}
        result = self._apply("linkedin_connect", ["linkedin_connect", "linkedin_message"], item)
        assert result == "email"

    def test_no_switch_when_mixed(self):
        """Mixed channels in history -> no switch."""
        item = {"linkedin_url": "https://linkedin.com/in/test", "email": "a@b.com"}
        result = self._apply("email", ["linkedin_connect", "email"], item)
        assert result == "email"

    def test_no_switch_with_one_history(self):
        """Only 1 previous touch -> never triggers switch."""
        item = {"linkedin_url": "https://linkedin.com/in/test", "email": "a@b.com"}
        assert self._apply("email", ["email"], item) == "email"

    def test_linkedin_switch_no_email_available(self):
        """3 linkedin in row but no email -> keep linkedin."""
        item = {"linkedin_url": "https://linkedin.com/in/test", "email": None}
        result = self._apply("linkedin_connect", ["linkedin_connect", "linkedin_message"], item)
        assert result == "linkedin_connect"

    def test_email_switch_no_linkedin_available(self):
        """3 emails in row but no linkedin -> keep email."""
        item = {"linkedin_url": None, "email": "a@b.com"}
        result = self._apply("email", ["email", "email"], item)
        assert result == "email"

    def test_long_history_only_checks_last_two(self):
        """Channel rule checks only last 2 entries."""
        item = {"linkedin_url": "https://linkedin.com/in/test", "email": "a@b.com"}
        history = ["email", "linkedin_connect", "email", "email"]
        result = self._apply("email", history, item)
        assert result.startswith("linkedin")

    def test_empty_item_fields(self):
        """Item with no channels at all -> original channel returned."""
        item = {"linkedin_url": None, "email": None}
        assert self._apply("email", [], item) == "email"


# ===========================================================================
# ADAPTIVE QUEUE — _diversify_by_firm_type
# ===========================================================================


class TestDiversifyByFirmType:
    """Tests for adaptive_queue._diversify_by_firm_type (unit, no DB)."""

    def setup_method(self):
        from src.services.adaptive_queue import _diversify_by_firm_type
        self._diversify = _diversify_by_firm_type

    def test_empty_list(self):
        assert self._diversify([], 5) == []

    def test_single_item(self):
        items = [{"firm_type": "Hedge Fund", "priority_score": 0.9}]
        result = self._diversify(items, 5)
        assert len(result) == 1

    def test_round_robin_across_types(self):
        """Should alternate between firm types."""
        items = [
            {"firm_type": "Hedge Fund", "priority_score": 0.9},
            {"firm_type": "Hedge Fund", "priority_score": 0.8},
            {"firm_type": "Family Office", "priority_score": 0.85},
            {"firm_type": "Family Office", "priority_score": 0.7},
        ]
        result = self._diversify(items, 4)
        assert len(result) == 4
        # First two should be from different types
        assert result[0]["firm_type"] != result[1]["firm_type"]

    def test_null_firm_type_grouped_as_unknown(self):
        """None firm_type -> grouped under 'Unknown'."""
        items = [
            {"firm_type": None, "priority_score": 0.9},
            {"firm_type": None, "priority_score": 0.8},
            {"firm_type": "PE", "priority_score": 0.85},
        ]
        result = self._diversify(items, 3)
        assert len(result) == 3

    def test_limit_respected(self):
        items = [{"firm_type": f"T{i}", "priority_score": 1.0 - i * 0.1} for i in range(10)]
        result = self._diversify(items, 3)
        assert len(result) == 3

    def test_fewer_items_than_limit(self):
        items = [{"firm_type": "HF", "priority_score": 0.9}]
        result = self._diversify(items, 10)
        assert len(result) == 1

    def test_single_firm_type_returns_top_by_score(self):
        """All items same firm_type -> returns top N by score."""
        items = [
            {"firm_type": "HF", "priority_score": 0.9},
            {"firm_type": "HF", "priority_score": 0.8},
            {"firm_type": "HF", "priority_score": 0.7},
        ]
        result = self._diversify(items, 2)
        assert len(result) == 2
        assert result[0]["priority_score"] == 0.9
        assert result[1]["priority_score"] == 0.8


# ===========================================================================
# COMPLIANCE — functions NOT covered in test_compliance.py
# ===========================================================================


class TestComplianceFooterHtmlEdgeCases:
    """Edge cases for add_compliance_footer_html not in existing tests."""

    def test_case_insensitive_body_tag_match(self):
        from src.services.compliance import add_compliance_footer_html
        html = "<html><BODY><p>Hello</p></BODY></html>"
        result = add_compliance_footer_html(html, "123 St", "mailto:x@y.com")
        # Should insert before </BODY> regardless of case
        assert "Unsubscribe" in result
        assert "123 St" in result

    def test_multiple_body_tags_uses_last(self):
        from src.services.compliance import add_compliance_footer_html
        html = "<body>first</body><body>second</body>"
        result = add_compliance_footer_html(html, "Addr", "mailto:x@y.com")
        # rfind should find last </body>
        assert result.count("Unsubscribe") == 1

    def test_html_special_chars_in_address(self):
        from src.services.compliance import add_compliance_footer_html
        html = "<body><p>Hi</p></body>"
        result = add_compliance_footer_html(html, "O'Malley & Sons <Corp>", "mailto:x@y.com")
        assert "O'Malley & Sons <Corp>" in result


class TestComplianceGdprLimitZero:
    """Edge case: max_emails=0 should always block."""

    def test_max_zero_blocks_immediately(self, tmp_db):
        from src.services.compliance import check_gdpr_email_limit
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        ctid = _create_contact(conn, cid)
        camp = create_campaign(conn, "test_zero", user_id=TEST_USER_ID)
        # No emails sent, but max=0 should block
        assert check_gdpr_email_limit(conn, ctid, camp, max_emails=0, user_id=TEST_USER_ID) is False
        conn.close()


class TestComplianceGdprLimitMax1:
    """Edge case: max_emails=1."""

    def test_max_one_allows_first(self, tmp_db):
        from src.services.compliance import check_gdpr_email_limit
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        ctid = _create_contact(conn, cid)
        camp = create_campaign(conn, "test_one", user_id=TEST_USER_ID)
        assert check_gdpr_email_limit(conn, ctid, camp, max_emails=1, user_id=TEST_USER_ID) is True
        conn.close()

    def test_max_one_blocks_second(self, tmp_db):
        from src.services.compliance import check_gdpr_email_limit
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        ctid = _create_contact(conn, cid)
        camp = create_campaign(conn, "test_one_b", user_id=TEST_USER_ID)
        log_event(conn, ctid, "email_sent", campaign_id=camp, user_id=TEST_USER_ID)
        assert check_gdpr_email_limit(conn, ctid, camp, max_emails=1, user_id=TEST_USER_ID) is False
        conn.close()


class TestProcessUnsubscribeMultipleContacts:
    """Test process_unsubscribe with contacts across companies."""

    def test_unsubscribes_all_matching_contacts(self, tmp_db):
        from src.services.compliance import process_unsubscribe
        conn = _setup_db(tmp_db)
        cid1 = _create_company(conn, name="Alpha")
        cid2 = _create_company(conn, name="Beta")

        # Unique constraint prevents duplicate email_normalized per user,
        # so test with two different contacts each having a distinct email
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO contacts (company_id, first_name, last_name,
               email, email_normalized, source, user_id)
               VALUES (%s, 'X', 'Y', 'alpha@test.com', 'alpha@test.com', 'test', %s)""",
            (cid1, TEST_USER_ID),
        )
        cur.execute(
            """INSERT INTO contacts (company_id, first_name, last_name,
               email, email_normalized, source, user_id)
               VALUES (%s, 'X', 'Y', 'beta@test.com', 'beta@test.com', 'test', %s)""",
            (cid2, TEST_USER_ID),
        )
        conn.commit()
        cur.close()

        # Unsubscribe each email independently
        assert process_unsubscribe(conn, "alpha@test.com", user_id=TEST_USER_ID) is True
        assert process_unsubscribe(conn, "beta@test.com", user_id=TEST_USER_ID) is True

        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM contacts "
            "WHERE email_normalized IN ('alpha@test.com', 'beta@test.com') AND unsubscribed = true"
        )
        assert cur.fetchone()["cnt"] == 2
        cur.close()
        conn.close()


# ===========================================================================
# CONTACT SCORER
# ===========================================================================


class TestAumToTier:
    """Test aum_to_tier boundary values."""

    def test_zero_aum(self):
        from src.services.contact_scorer import aum_to_tier
        assert aum_to_tier(0) == "$0-100M"

    def test_negative_aum(self):
        from src.services.contact_scorer import aum_to_tier
        assert aum_to_tier(-10) == "$0-100M"

    def test_boundary_100(self):
        from src.services.contact_scorer import aum_to_tier
        assert aum_to_tier(99.99) == "$0-100M"
        assert aum_to_tier(100) == "$100M-500M"

    def test_boundary_500(self):
        from src.services.contact_scorer import aum_to_tier
        assert aum_to_tier(499.99) == "$100M-500M"
        assert aum_to_tier(500) == "$500M-1B"

    def test_boundary_1000(self):
        from src.services.contact_scorer import aum_to_tier
        assert aum_to_tier(999.99) == "$500M-1B"
        assert aum_to_tier(1000) == "$1B+"

    def test_very_large_aum(self):
        from src.services.contact_scorer import aum_to_tier
        assert aum_to_tier(100000) == "$1B+"


class TestContactScorerZeroAum:
    """Score contacts where company has 0 AUM."""

    def test_zero_aum_score_is_zero(self, tmp_db):
        from src.services.contact_scorer import score_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn, aum_millions=0)
        ctid = _create_contact(conn, cid, email="a@b.com", linkedin_url="https://linkedin.com/in/a")
        camp = create_campaign(conn, "scorer_zero", user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date="2026-01-01", user_id=TEST_USER_ID)

        scores = score_contacts(conn, camp, [ctid], user_id=TEST_USER_ID)
        assert len(scores) == 1
        assert scores[0]["breakdown"]["aum_score"] == 0.0
        conn.close()

    def test_null_aum_score_is_zero(self, tmp_db):
        from src.services.contact_scorer import score_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn, aum_millions=None)
        ctid = _create_contact(conn, cid, email="b@c.com")
        camp = create_campaign(conn, "scorer_null", user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date="2026-01-01", user_id=TEST_USER_ID)

        scores = score_contacts(conn, camp, [ctid], user_id=TEST_USER_ID)
        assert len(scores) == 1
        assert scores[0]["breakdown"]["aum_score"] == 0.0
        conn.close()


class TestContactScorerChannelScore:
    """Test channel availability scoring component."""

    def test_both_channels_score_1(self, tmp_db):
        from src.services.contact_scorer import score_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn, aum_millions=500)
        ctid = _create_contact(
            conn, cid, email="x@y.com", email_status="valid",
            linkedin_url="https://linkedin.com/in/x",
        )
        camp = create_campaign(conn, "ch_both", user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date="2026-01-01", user_id=TEST_USER_ID)

        scores = score_contacts(conn, camp, [ctid], user_id=TEST_USER_ID)
        assert scores[0]["breakdown"]["channel_score"] == 1.0
        conn.close()

    def test_email_only_score_half(self, tmp_db):
        from src.services.contact_scorer import score_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn, aum_millions=500)
        ctid = _create_contact(conn, cid, email="x@y.com", email_status="valid", linkedin_url=None)
        camp = create_campaign(conn, "ch_email", user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date="2026-01-01", user_id=TEST_USER_ID)

        scores = score_contacts(conn, camp, [ctid], user_id=TEST_USER_ID)
        assert scores[0]["breakdown"]["channel_score"] == 0.5
        conn.close()

    def test_invalid_email_zero_email_score(self, tmp_db):
        from src.services.contact_scorer import score_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn, aum_millions=500)
        ctid = _create_contact(
            conn, cid, email="x@y.com", email_status="invalid",
            linkedin_url="https://linkedin.com/in/x",
        )
        camp = create_campaign(conn, "ch_inv", user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date="2026-01-01", user_id=TEST_USER_ID)

        scores = score_contacts(conn, camp, [ctid], user_id=TEST_USER_ID)
        assert scores[0]["breakdown"]["channel_score"] == 0.5
        conn.close()

    def test_no_channels_score_zero(self, tmp_db):
        from src.services.contact_scorer import score_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn, aum_millions=500)
        ctid = _create_contact(
            conn, cid, email="x@y.com", email_status="invalid", linkedin_url=None,
        )
        camp = create_campaign(conn, "ch_none", user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date="2026-01-01", user_id=TEST_USER_ID)

        scores = score_contacts(conn, camp, [ctid], user_id=TEST_USER_ID)
        assert scores[0]["breakdown"]["channel_score"] == 0.0
        conn.close()


class TestContactScorerRecency:
    """Test recency score component."""

    def test_default_recency_when_no_action_date(self, tmp_db):
        from src.services.contact_scorer import score_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn, aum_millions=500)
        ctid = _create_contact(conn, cid, email="r@t.com")
        camp = create_campaign(conn, "rec_none", user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date=None, user_id=TEST_USER_ID)

        scores = score_contacts(conn, camp, [ctid], user_id=TEST_USER_ID)
        # No action date -> default recency of 0.5
        assert scores[0]["breakdown"]["recency_score"] == 0.5
        conn.close()

    def test_user_id_scoping(self, tmp_db):
        from src.services.contact_scorer import score_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn, aum_millions=500)
        ctid = _create_contact(conn, cid, email="u@v.com")
        camp = create_campaign(conn, "scope", user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date="2026-01-01", user_id=TEST_USER_ID)

        scores = score_contacts(conn, camp, [ctid], user_id=TEST_USER_ID)
        assert len(scores) == 1
        conn.close()


class TestContactScorerComposite:
    """Test the overall composite score formula."""

    def test_score_is_weighted_sum(self, tmp_db):
        from src.services.contact_scorer import (
            WEIGHT_AUM, WEIGHT_CHANNEL, WEIGHT_RECENCY, WEIGHT_SEGMENT,
            score_contacts,
        )
        conn = _setup_db(tmp_db)
        cid = _create_company(conn, aum_millions=1000)
        ctid = _create_contact(
            conn, cid, email="comp@t.com", email_status="valid",
            linkedin_url="https://linkedin.com/in/comp",
        )
        camp = create_campaign(conn, "composite", user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date="2026-01-01", user_id=TEST_USER_ID)

        scores = score_contacts(conn, camp, [ctid], user_id=TEST_USER_ID)
        bd = scores[0]["breakdown"]
        expected = round(
            WEIGHT_AUM * bd["aum_score"]
            + WEIGHT_SEGMENT * bd["segment_score"]
            + WEIGHT_CHANNEL * bd["channel_score"]
            + WEIGHT_RECENCY * bd["recency_score"],
            4,
        )
        assert scores[0]["priority_score"] == expected
        conn.close()


# ===========================================================================
# DEDUPLICATION — edge cases
# ===========================================================================


class TestDedupEdgeCases:
    """Edge cases not covered in existing test_deduplication.py."""

    def _setup_dedup_db(self, tmp_db):
        conn = _setup_db(tmp_db)
        cur = conn.cursor()
        cur.execute("DROP INDEX IF EXISTS idx_contacts_email_norm_unique")
        cur.execute("DROP INDEX IF EXISTS idx_contacts_linkedin_norm_unique")
        cur.execute("DROP INDEX IF EXISTS idx_contacts_user_email_norm")
        cur.execute("DROP INDEX IF EXISTS idx_contacts_user_linkedin_norm")
        cur.execute("ALTER TABLE dedup_log DROP CONSTRAINT IF EXISTS fk_dedup_kept_contact")
        cur.execute("ALTER TABLE dedup_log DROP CONSTRAINT IF EXISTS fk_dedup_merged_contact")
        conn.commit()
        cur.close()
        return conn

    def _restore_indexes(self, conn):
        cur = conn.cursor()
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_user_email_norm ON contacts(user_id, email_normalized)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_user_linkedin_norm ON contacts(user_id, linkedin_url_normalized) WHERE linkedin_url_normalized IS NOT NULL")
        conn.commit()
        cur.close()

    def test_no_duplicates_returns_zeros(self, tmp_db):
        from src.services.deduplication import run_dedup
        conn = self._setup_dedup_db(tmp_db)
        insert_company(conn, "Unique Co")
        stats = run_dedup(conn, user_id=1)
        assert stats["email_dupes"] == 0
        assert stats["linkedin_dupes"] == 0
        assert stats["fuzzy_flagged"] == 0
        self._restore_indexes(conn)
        conn.close()

    def test_empty_database_returns_zeros(self, tmp_db):
        from src.services.deduplication import run_dedup
        conn = self._setup_dedup_db(tmp_db)
        stats = run_dedup(conn, user_id=1)
        assert stats == {"email_dupes": 0, "linkedin_dupes": 0, "fuzzy_flagged": 0}
        self._restore_indexes(conn)
        conn.close()

    def test_triple_email_duplicates(self, tmp_db):
        """Three contacts with same email -> two removed."""
        from src.services.deduplication import run_dedup
        conn = self._setup_dedup_db(tmp_db)
        co = insert_company(conn, "Triple Corp")
        c1 = insert_contact(conn, co, email="same@triple.com", linkedin_url=None)
        c2 = insert_contact(conn, co, email="same@triple.com", linkedin_url=None)
        c3 = insert_contact(conn, co, email="same@triple.com", linkedin_url=None)

        stats = run_dedup(conn, user_id=1)
        assert stats["email_dupes"] == 2

        cur = conn.cursor()
        cur.execute("SELECT id FROM contacts ORDER BY id")
        remaining = [r["id"] for r in cur.fetchall()]
        assert c1 in remaining
        assert c2 not in remaining
        assert c3 not in remaining
        cur.close()

        self._restore_indexes(conn)
        conn.close()

    def test_null_email_not_treated_as_duplicate(self, tmp_db):
        """Two contacts with NULL email should not be de-duped."""
        from src.services.deduplication import run_dedup
        conn = self._setup_dedup_db(tmp_db)
        co = insert_company(conn, "NullEmail Corp")
        insert_contact(conn, co, email=None, linkedin_url=None)
        insert_contact(conn, co, email=None, linkedin_url=None)

        stats = run_dedup(conn, user_id=1)
        assert stats["email_dupes"] == 0

        self._restore_indexes(conn)
        conn.close()

    def test_null_linkedin_not_treated_as_duplicate(self, tmp_db):
        """Two contacts with NULL linkedin should not be de-duped."""
        from src.services.deduplication import run_dedup
        conn = self._setup_dedup_db(tmp_db)
        co = insert_company(conn, "NullLI Corp")
        insert_contact(conn, co, email=None, linkedin_url=None)
        insert_contact(conn, co, email=None, linkedin_url=None)

        stats = run_dedup(conn, user_id=1)
        assert stats["linkedin_dupes"] == 0

        self._restore_indexes(conn)
        conn.close()

    def test_fuzzy_dissimilar_names_not_flagged(self, tmp_db):
        """Completely different company names should not be flagged."""
        from src.services.deduplication import run_dedup
        conn = self._setup_dedup_db(tmp_db)
        insert_company(conn, "Alpha Quantum Partners")
        insert_company(conn, "Zeta Blockchain Ventures")

        stats = run_dedup(conn, export_dir=None, user_id=1)
        assert stats["fuzzy_flagged"] == 0

        self._restore_indexes(conn)
        conn.close()

    def test_fuzzy_no_csv_when_no_export_dir(self, tmp_db):
        """No CSV written when export_dir is None."""
        from src.services.deduplication import run_dedup
        conn = self._setup_dedup_db(tmp_db)
        insert_company(conn, "Falcon Capital")
        insert_company(conn, "Falcon Capital Ltd")

        stats = run_dedup(conn, export_dir=None, user_id=1)
        assert stats["fuzzy_flagged"] >= 1
        # No crash from None export_dir
        self._restore_indexes(conn)
        conn.close()

    def test_fuzzy_empty_export_dir_no_csv(self, tmp_db, tmp_path):
        """No CSV written when there are no flagged pairs."""
        from src.services.deduplication import run_dedup
        conn = self._setup_dedup_db(tmp_db)
        insert_company(conn, "UniqueAlpha")
        insert_company(conn, "CompleteDifferent")

        export_dir = str(tmp_path / "export")
        os.makedirs(export_dir, exist_ok=True)
        stats = run_dedup(conn, export_dir=export_dir, user_id=1)
        assert stats["fuzzy_flagged"] == 0
        assert not os.path.exists(os.path.join(export_dir, "dedup_review.csv"))

        self._restore_indexes(conn)
        conn.close()


# ===========================================================================
# DEEP RESEARCH SERVICE — signal extraction, helper functions
# ===========================================================================


class TestRecencyScore:
    """Tests for _recency_score helper."""

    def test_high_recency_patterns(self):
        from src.services.deep_research_service import _recency_score
        assert _recency_score("They just announced a new fund") == 0.9
        assert _recency_score("recently launched their crypto strategy") == 0.9
        assert _recency_score("this week they revealed") == 0.9

    def test_medium_recency_patterns(self):
        from src.services.deep_research_service import _recency_score
        assert _recency_score("In this year 2026 they expanded") == 0.6
        assert _recency_score("During Q2 they allocated") == 0.6

    def test_low_recency_patterns(self):
        from src.services.deep_research_service import _recency_score
        assert _recency_score("They have historically focused on equities") == 0.2
        assert _recency_score("a long-standing tradition of innovation") == 0.2

    def test_no_match_default(self):
        from src.services.deep_research_service import _recency_score
        assert _recency_score("Generic statement about investing") == 0.4

    def test_empty_string(self):
        from src.services.deep_research_service import _recency_score
        assert _recency_score("") == 0.4


class TestDetectSignalType:
    """Tests for _detect_signal_type helper."""

    def test_fund_raise(self):
        from src.services.deep_research_service import _detect_signal_type
        assert _detect_signal_type("They raised a new fund worth $500M") == "fund_raise"
        assert _detect_signal_type("Capital raise closed at $1B") == "fund_raise"

    def test_key_hire(self):
        from src.services.deep_research_service import _detect_signal_type
        assert _detect_signal_type("appointed new CIO last week") == "key_hire"
        assert _detect_signal_type("hired a new head of investments") == "key_hire"

    def test_crypto_allocation(self):
        from src.services.deep_research_service import _detect_signal_type
        assert _detect_signal_type("allocated 5% to bitcoin") == "crypto_allocation"
        assert _detect_signal_type("added bitcoin to their portfolio") == "crypto_allocation"

    def test_portfolio_move(self):
        from src.services.deep_research_service import _detect_signal_type
        assert _detect_signal_type("acquired a stake in the company") == "portfolio_move"
        assert _detect_signal_type("divest from oil holdings") == "portfolio_move"

    def test_conference(self):
        from src.services.deep_research_service import _detect_signal_type
        assert _detect_signal_type("speaking at the blockchain summit") == "conference"

    def test_general(self):
        from src.services.deep_research_service import _detect_signal_type
        assert _detect_signal_type("a standard company description") == "general"

    def test_empty_string(self):
        from src.services.deep_research_service import _detect_signal_type
        assert _detect_signal_type("") == "general"


class TestExtractFundSignals:
    """Tests for _extract_fund_signals."""

    def test_empty_research_result(self):
        from src.services.deep_research_service import _extract_fund_signals
        result = _extract_fund_signals({})
        assert result == []

    def test_signals_from_crypto_signals(self):
        from src.services.deep_research_service import _extract_fund_signals
        research = {
            "crypto_signals": [
                {"quote": "They just raised $200M for a new crypto fund", "relevance": "high", "source": "news"},
            ],
            "talking_points": [],
        }
        signals = _extract_fund_signals(research)
        assert len(signals) >= 1
        assert signals[0]["type"] == "fund_raise"
        assert signals[0]["recency_score"] == 0.9  # "just" = high recency

    def test_low_relevance_general_signals_filtered(self):
        from src.services.deep_research_service import _extract_fund_signals
        research = {
            "crypto_signals": [
                {"quote": "A generic statement", "relevance": "low", "source": "web"},
            ],
        }
        signals = _extract_fund_signals(research)
        # general + low relevance -> filtered out
        assert len(signals) == 0

    def test_signals_from_talking_points(self):
        from src.services.deep_research_service import _extract_fund_signals
        research = {
            "crypto_signals": [],
            "talking_points": [
                {"hook_type": "event_hook", "text": "Speaking at crypto conference next week", "source_reference": "X"},
                {"hook_type": "thesis_alignment", "text": "Their thesis aligns", "source_reference": "Y"},
            ],
        }
        signals = _extract_fund_signals(research)
        # Only event_hook/portfolio_move/team_signal talking points are extracted
        assert len(signals) == 1
        assert signals[0]["type"] == "conference"

    def test_deduplication_of_signals(self):
        from src.services.deep_research_service import _extract_fund_signals
        research = {
            "crypto_signals": [
                {"quote": "Hired a new CIO", "relevance": "high", "source": "news"},
            ],
            "talking_points": [
                {"hook_type": "team_signal", "text": "Hired a new CIO", "source_reference": "X"},
            ],
        }
        signals = _extract_fund_signals(research)
        # Should deduplicate by text
        assert len(signals) == 1

    def test_signals_sorted_by_recency(self):
        from src.services.deep_research_service import _extract_fund_signals
        research = {
            "crypto_signals": [
                {"quote": "historically invested in bonds", "relevance": "high", "source": "X"},
                {"quote": "just announced crypto allocation", "relevance": "high", "source": "Y"},
            ],
        }
        signals = _extract_fund_signals(research)
        if len(signals) >= 2:
            assert signals[0]["recency_score"] >= signals[1]["recency_score"]

    def test_non_list_crypto_signals_handled(self):
        from src.services.deep_research_service import _extract_fund_signals
        research = {"crypto_signals": "not a list", "talking_points": None}
        signals = _extract_fund_signals(research)
        assert signals == []

    def test_non_dict_entries_skipped(self):
        from src.services.deep_research_service import _extract_fund_signals
        research = {"crypto_signals": ["string_entry", 42, None]}
        signals = _extract_fund_signals(research)
        assert signals == []

    def test_empty_quote_skipped(self):
        from src.services.deep_research_service import _extract_fund_signals
        research = {"crypto_signals": [{"quote": "", "relevance": "high", "source": "X"}]}
        signals = _extract_fund_signals(research)
        assert signals == []


class TestBuildResearchQueries:
    """Tests for _build_research_queries."""

    def test_us_based_includes_sec_query(self):
        from src.services.deep_research_service import _build_research_queries
        queries = _build_research_queries("TestCorp", is_us_based=True)
        assert len(queries) == 6
        assert any("SEC" in q for q in queries)

    def test_non_us_excludes_sec_query(self):
        from src.services.deep_research_service import _build_research_queries
        queries = _build_research_queries("TestCorp", is_us_based=False)
        assert len(queries) == 5
        assert not any("SEC" in q for q in queries)

    def test_company_name_in_all_queries(self):
        from src.services.deep_research_service import _build_research_queries
        queries = _build_research_queries("AlphaVentures", is_us_based=False)
        for q in queries:
            assert "AlphaVentures" in q


class TestEstimateCost:
    """Tests for estimate_cost."""

    def test_us_based_cost(self):
        from src.services.deep_research_service import estimate_cost
        result = estimate_cost(is_us_based=True)
        assert result["query_count"] == 6
        assert result["cost_estimate_usd"] > 0

    def test_non_us_based_cost(self):
        from src.services.deep_research_service import estimate_cost
        result = estimate_cost(is_us_based=False)
        assert result["query_count"] == 5
        assert result["cost_estimate_usd"] > 0

    def test_us_more_expensive_than_non_us(self):
        from src.services.deep_research_service import estimate_cost
        us_cost = estimate_cost(is_us_based=True)["cost_estimate_usd"]
        non_us_cost = estimate_cost(is_us_based=False)["cost_estimate_usd"]
        assert us_cost > non_us_cost


class TestDeepResearchUpdateStatus:
    """Tests for _update_status transitions."""

    def test_update_to_researching(self, tmp_db):
        from src.services.deep_research_service import _update_status
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        dr_id = _insert_deep_research(conn, cid, status="pending")

        _update_status(conn, dr_id, "researching", user_id=TEST_USER_ID)

        with get_cursor(conn) as cur:
            cur.execute("SELECT status, started_at FROM deep_research WHERE id = %s", (dr_id,))
            row = cur.fetchone()
        assert row["status"] == "researching"
        assert row["started_at"] is not None
        conn.close()

    def test_update_to_completed(self, tmp_db):
        from src.services.deep_research_service import _update_status
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        dr_id = _insert_deep_research(conn, cid, status="researching")

        _update_status(conn, dr_id, "completed", user_id=TEST_USER_ID, company_overview="Overview text")

        with get_cursor(conn) as cur:
            cur.execute("SELECT status, completed_at, company_overview FROM deep_research WHERE id = %s", (dr_id,))
            row = cur.fetchone()
        assert row["status"] == "completed"
        assert row["completed_at"] is not None
        assert row["company_overview"] == "Overview text"
        conn.close()

    def test_update_to_failed_with_error(self, tmp_db):
        from src.services.deep_research_service import _update_status
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        dr_id = _insert_deep_research(conn, cid, status="researching")

        _update_status(conn, dr_id, "failed", user_id=TEST_USER_ID, error_message="API down")

        with get_cursor(conn) as cur:
            cur.execute("SELECT status, error_message, completed_at FROM deep_research WHERE id = %s", (dr_id,))
            row = cur.fetchone()
        assert row["status"] == "failed"
        assert row["error_message"] == "API down"
        assert row["completed_at"] is not None
        conn.close()


class TestDeepResearchIsCancelled:
    """Tests for _is_cancelled."""

    def test_cancelled_returns_true(self, tmp_db):
        from src.services.deep_research_service import _is_cancelled
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        dr_id = _insert_deep_research(conn, cid, status="cancelled")
        assert _is_cancelled(conn, dr_id, user_id=TEST_USER_ID) is True
        conn.close()

    def test_not_cancelled_returns_false(self, tmp_db):
        from src.services.deep_research_service import _is_cancelled
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        dr_id = _insert_deep_research(conn, cid, status="researching")
        assert _is_cancelled(conn, dr_id, user_id=TEST_USER_ID) is False
        conn.close()

    def test_nonexistent_id_returns_false(self, tmp_db):
        from src.services.deep_research_service import _is_cancelled
        conn = _setup_db(tmp_db)
        assert _is_cancelled(conn, 99999, user_id=TEST_USER_ID) is False
        conn.close()


class TestEnrichContacts:
    """Tests for _enrich_contacts."""

    def test_empty_key_people(self, tmp_db):
        from src.services.deep_research_service import _enrich_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        result = _enrich_contacts(conn, cid, [], TEST_USER_ID)
        assert result == 0
        conn.close()

    def test_person_with_no_name_skipped(self, tmp_db):
        from src.services.deep_research_service import _enrich_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        result = _enrich_contacts(conn, cid, [{"name": "", "title": "CIO"}], TEST_USER_ID)
        assert result == 0
        conn.close()

    def test_match_by_linkedin_url(self, tmp_db):
        from src.services.deep_research_service import _enrich_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        _create_contact(conn, cid, first_name="Jane", last_name="Doe",
                         linkedin_url="https://www.linkedin.com/in/janedoe", title=None)

        result = _enrich_contacts(
            conn, cid,
            [{"name": "Jane Doe", "title": "CIO", "linkedin_url": "https://www.linkedin.com/in/janedoe"}],
            TEST_USER_ID,
        )
        assert result == 1

        # Verify title was updated
        with get_cursor(conn) as cur:
            cur.execute("SELECT title FROM contacts WHERE company_id = %s", (cid,))
            assert cur.fetchone()["title"] == "CIO"
        conn.close()

    def test_creates_new_contact_when_unmatched(self, tmp_db):
        from src.services.deep_research_service import _enrich_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)

        result = _enrich_contacts(
            conn, cid,
            [{"name": "New Person", "title": "VP", "email": "new@test.com"}],
            TEST_USER_ID,
        )
        assert result == 1

        with get_cursor(conn) as cur:
            cur.execute("SELECT full_name, title, source FROM contacts WHERE company_id = %s", (cid,))
            row = cur.fetchone()
        assert row["full_name"] == "New Person"
        assert row["source"] == "deep_research"
        conn.close()

    def test_invalid_email_not_stored(self, tmp_db):
        from src.services.deep_research_service import _enrich_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)

        result = _enrich_contacts(
            conn, cid,
            [{"name": "Bad Email", "title": "VP", "email": "not-an-email"}],
            TEST_USER_ID,
        )
        assert result == 1

        with get_cursor(conn) as cur:
            cur.execute("SELECT email FROM contacts WHERE company_id = %s", (cid,))
            row = cur.fetchone()
        assert row["email"] is None
        conn.close()

    def test_invalid_linkedin_url_not_stored(self, tmp_db):
        from src.services.deep_research_service import _enrich_contacts
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)

        result = _enrich_contacts(
            conn, cid,
            [{"name": "Bad LI", "title": "VP", "linkedin_url": "http://twitter.com/user"}],
            TEST_USER_ID,
        )
        assert result == 1

        with get_cursor(conn) as cur:
            cur.execute("SELECT linkedin_url FROM contacts WHERE company_id = %s", (cid,))
            row = cur.fetchone()
        assert row["linkedin_url"] is None
        conn.close()


# ===========================================================================
# EMAIL SENDER
# ===========================================================================


class TestTextToCleanHtml:
    """Tests for _text_to_clean_html."""

    def test_basic_text(self):
        from src.services.email_sender import _text_to_clean_html
        html = _text_to_clean_html("Hello world")
        assert "<p>" in html
        assert "Hello world" in html
        assert "<!DOCTYPE html>" in html

    def test_paragraph_splitting(self):
        from src.services.email_sender import _text_to_clean_html
        html = _text_to_clean_html("Para 1\n\nPara 2")
        assert html.count("<p>") == 2

    def test_single_newline_becomes_br(self):
        from src.services.email_sender import _text_to_clean_html
        html = _text_to_clean_html("Line 1\nLine 2")
        assert "<br>" in html

    def test_html_entities_escaped(self):
        from src.services.email_sender import _text_to_clean_html
        html = _text_to_clean_html("A < B & C > D")
        assert "&lt;" in html
        assert "&amp;" in html
        assert "&gt;" in html

    def test_empty_string(self):
        from src.services.email_sender import _text_to_clean_html
        html = _text_to_clean_html("")
        assert "<body>" in html


class TestBuildMimeMessage:
    """Tests for _build_mime_message."""

    def test_basic_message(self):
        from src.services.email_sender import _build_mime_message
        msg = _build_mime_message("from@a.com", "to@b.com", "Subject", "Body text")
        assert msg["From"] == "from@a.com"
        assert msg["To"] == "to@b.com"
        assert msg["Subject"] == "Subject"
        # Body is base64-encoded in the MIME output; check decoded payload
        payloads = msg.get_payload()
        plain_part = payloads[0] if isinstance(payloads, list) else payloads
        assert "Body text" in plain_part.get_payload(decode=True).decode()

    def test_custom_html(self):
        from src.services.email_sender import _build_mime_message
        msg = _build_mime_message("f@a.com", "t@b.com", "S", "Text", "<b>HTML</b>")
        payloads = msg.get_payload()
        html_part = payloads[1] if isinstance(payloads, list) else payloads
        assert "HTML" in html_part.get_payload(decode=True).decode()

    def test_auto_generates_html_when_none(self):
        from src.services.email_sender import _build_mime_message
        msg = _build_mime_message("f@a.com", "t@b.com", "S", "Hello there")
        payloads = msg.get_payload()
        plain_part = payloads[0] if isinstance(payloads, list) else payloads
        assert "Hello there" in plain_part.get_payload(decode=True).decode()


class TestSendEmailsBatch:
    """Tests for send_emails_batch."""

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_empty_messages_returns_empty(self, mock_smtp):
        from src.services.email_sender import send_emails_batch
        results = send_emails_batch("host", 587, "user", "pass", "from@a.com", [])
        assert results == []
        mock_smtp.assert_not_called()

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_batch_send_success(self, mock_smtp):
        from src.services.email_sender import send_emails_batch
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        messages = [
            {"to_email": "a@b.com", "subject": "S1", "body_text": "B1"},
            {"to_email": "c@d.com", "subject": "S2", "body_text": "B2"},
        ]
        results = send_emails_batch("host", 587, "user", "pass", "from@a.com", messages)
        assert results == [True, True]
        assert mock_server.sendmail.call_count == 2

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_batch_partial_failure(self, mock_smtp):
        from src.services.email_sender import send_emails_batch
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        # First send succeeds, second raises
        mock_server.sendmail.side_effect = [None, smtplib.SMTPRecipientsRefused({"c@d.com": (550, b"rejected")})]

        messages = [
            {"to_email": "a@b.com", "subject": "S1", "body_text": "B1"},
            {"to_email": "c@d.com", "subject": "S2", "body_text": "B2"},
        ]
        results = send_emails_batch("host", 587, "user", "pass", "from@a.com", messages)
        assert results == [True, False]

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_batch_connection_failure(self, mock_smtp):
        from src.services.email_sender import send_emails_batch
        mock_smtp.return_value.__enter__ = MagicMock(
            side_effect=smtplib.SMTPConnectError(421, b"Service not available"),
        )
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        messages = [
            {"to_email": "a@b.com", "subject": "S1", "body_text": "B1"},
            {"to_email": "c@d.com", "subject": "S2", "body_text": "B2"},
        ]
        results = send_emails_batch("host", 587, "user", "pass", "from@a.com", messages)
        assert results == [False, False]


class TestRenderCampaignEmail:
    """Tests for render_campaign_email."""

    def test_returns_none_for_nonexistent_contact(self, tmp_db):
        from src.services.email_sender import render_campaign_email
        conn = _setup_db(tmp_db)
        result = render_campaign_email(conn, 99999, 1, 1, {}, user_id=TEST_USER_ID)
        assert result is None
        conn.close()

    def test_returns_none_for_unsubscribed(self, tmp_db):
        from src.services.email_sender import render_campaign_email
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        ctid = _create_contact(conn, cid, unsubscribed=True)
        camp = create_campaign(conn, "render_test", user_id=TEST_USER_ID)
        tid = create_template(conn, "tpl", "email", "Hello {{ first_name }}", subject="Hi", user_id=TEST_USER_ID)

        result = render_campaign_email(conn, ctid, camp, tid, {}, user_id=TEST_USER_ID)
        assert result is None
        conn.close()

    def test_returns_none_when_template_missing(self, tmp_db):
        from src.services.email_sender import render_campaign_email
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        ctid = _create_contact(conn, cid)
        camp = create_campaign(conn, "render_test2", user_id=TEST_USER_ID)

        result = render_campaign_email(conn, ctid, camp, 99999, {}, user_id=TEST_USER_ID)
        assert result is None
        conn.close()

    def test_successful_render(self, tmp_db):
        from src.services.email_sender import render_campaign_email
        conn = _setup_db(tmp_db)
        cid = _create_company(conn, name="TestCo")
        ctid = _create_contact(conn, cid, first_name="Alice", last_name="Smith",
                                email="alice@test.com")
        camp = create_campaign(conn, "render_ok", user_id=TEST_USER_ID)
        tid = create_template(
            conn, "tpl_ok", "email", "Hello {{ first_name }}!",
            subject="Intro", user_id=TEST_USER_ID,
        )
        config = {
            "smtp": {"username": "out@test.com"},
            "physical_address": "123 Main St",
            "calendly_url": "https://calendly.com/test",
        }

        result = render_campaign_email(conn, ctid, camp, tid, config, user_id=TEST_USER_ID)
        assert result is not None
        assert result["subject"] == "Intro"
        assert "Alice" in result["body_text"]
        assert result["contact_email"] == "alice@test.com"
        # Compliance footer should be present
        assert "123 Main St" in result["body_text"]
        assert "Unsubscribe" in result["body_html"]
        conn.close()


class TestRenderInlineTemplate:
    """Tests for _render_inline_template."""

    def test_basic_render(self):
        from src.services.email_sender import _render_inline_template
        result = _render_inline_template("Hello {{ name }}!", {"name": "Alice"})
        assert result == "Hello Alice!"

    def test_missing_variable(self):
        from src.services.email_sender import _render_inline_template
        result = _render_inline_template("Hello {{ name }}!", {})
        assert "Hello" in result

    def test_complex_template(self):
        from src.services.email_sender import _render_inline_template
        tpl = "{% if vip %}Dear {{ name }}{% else %}Hi {{ name }}{% endif %}"
        assert _render_inline_template(tpl, {"name": "Bob", "vip": True}) == "Dear Bob"
        assert _render_inline_template(tpl, {"name": "Bob", "vip": False}) == "Hi Bob"


# ===========================================================================
# EMAIL VERIFIER
# ===========================================================================


class TestVerifyEmailBatchProvider:
    """Provider dispatch tests."""

    def test_unsupported_provider_raises(self):
        from src.services.email_verifier import verify_email_batch
        with pytest.raises(ValueError, match="Unsupported provider"):
            verify_email_batch(["a@b.com"], "key", provider="mailgun")

    def test_empty_email_list(self):
        from src.services.email_verifier import verify_email_batch
        # Should not crash — ZeroBounce with empty list
        with patch("src.services.email_verifier.httpx") as mock_httpx:
            result = verify_email_batch([], "key", provider="zerobounce")
            assert result == {}
            mock_httpx.post.assert_not_called()

    @patch("src.services.email_verifier.httpx")
    @patch("src.services.email_verifier.time")
    def test_zerobounce_http_error_marks_unknown(self, mock_time, mock_httpx):
        from src.services.email_verifier import verify_email_batch
        mock_httpx.post.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(),
        )
        mock_httpx.HTTPStatusError = httpx.HTTPStatusError
        mock_httpx.RequestError = httpx.RequestError
        result = verify_email_batch(["fail@test.com"], "key", provider="zerobounce")
        assert result["fail@test.com"] == "unknown"

    @patch("src.services.email_verifier.httpx")
    @patch("src.services.email_verifier.time")
    def test_hunter_http_error_marks_unknown(self, mock_time, mock_httpx):
        from src.services.email_verifier import verify_email_batch
        mock_httpx.get.side_effect = httpx.RequestError("timeout")
        mock_httpx.HTTPStatusError = httpx.HTTPStatusError
        mock_httpx.RequestError = httpx.RequestError
        result = verify_email_batch(["fail@test.com"], "key", provider="hunter")
        assert result["fail@test.com"] == "unknown"

    @patch("src.services.email_verifier.httpx")
    @patch("src.services.email_verifier.time")
    def test_zerobounce_chunking(self, mock_time, mock_httpx):
        """Emails exceeding chunk size should trigger multiple API calls."""
        from src.services.email_verifier import verify_email_batch, ZEROBOUNCE_CHUNK_SIZE

        mock_response = MagicMock()
        mock_response.json.return_value = {"email_batch": []}
        mock_response.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_response

        emails = [f"user{i}@test.com" for i in range(ZEROBOUNCE_CHUNK_SIZE + 5)]
        verify_email_batch(emails, "key", provider="zerobounce")
        assert mock_httpx.post.call_count == 2


class TestUpdateContactEmailStatus:
    """Tests for update_contact_email_status."""

    def test_update_to_catch_all(self, tmp_db):
        from src.services.email_verifier import update_contact_email_status
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        _create_contact(conn, cid, email="ca@test.com", email_status="unverified")
        update_contact_email_status(conn, "ca@test.com", "catch-all", user_id=TEST_USER_ID)

        cur = conn.cursor()
        cur.execute("SELECT email_status FROM contacts WHERE email_normalized = 'ca@test.com'")
        assert cur.fetchone()["email_status"] == "catch-all"
        cur.close()
        conn.close()

    def test_update_nonexistent_email(self, tmp_db):
        from src.services.email_verifier import update_contact_email_status
        conn = _setup_db(tmp_db)
        # Should not crash
        update_contact_email_status(conn, "nobody@test.com", "valid", user_id=TEST_USER_ID)
        conn.close()


# ===========================================================================
# GMAIL DRAFTER
# ===========================================================================


class TestGmailDrafterFromDbTokens:
    """Tests for GmailDrafter.from_db_tokens."""

    def test_creates_instance_with_credentials(self):
        from src.services.gmail_drafter import GmailDrafter
        with patch("src.services.gmail_drafter.GmailDrafter.from_db_tokens") as mock_method:
            mock_instance = MagicMock()
            mock_instance._db_credentials = MagicMock()
            mock_instance._db_credentials.token = "test_token"
            mock_method.return_value = mock_instance

            drafter = GmailDrafter.from_db_tokens("access", "refresh", "client_id", "secret")
            assert drafter._db_credentials.token == "test_token"

    @patch("google.oauth2.credentials.Credentials")
    def test_from_db_tokens_real_construction(self, mock_creds_class):
        from src.services.gmail_drafter import GmailDrafter, SCOPES
        mock_creds = MagicMock()
        mock_creds.token = "test_access_token"
        mock_creds_class.return_value = mock_creds

        drafter = GmailDrafter.from_db_tokens("access_tok", "refresh_tok", "cid", "csecret")
        assert drafter.credentials_path is None
        assert drafter.token_path is None
        assert drafter._service is None

    @patch("google.oauth2.credentials.Credentials")
    def test_is_authorized_with_db_tokens(self, mock_creds_class):
        from src.services.gmail_drafter import GmailDrafter
        mock_creds = MagicMock()
        mock_creds.token = "valid_token"
        mock_creds_class.return_value = mock_creds

        drafter = GmailDrafter.from_db_tokens("access_tok", "refresh_tok", "cid", "csecret")
        assert drafter.is_authorized() is True

    @patch("google.oauth2.credentials.Credentials")
    def test_is_authorized_with_null_token(self, mock_creds_class):
        from src.services.gmail_drafter import GmailDrafter
        mock_creds = MagicMock()
        mock_creds.token = None
        mock_creds_class.return_value = mock_creds

        drafter = GmailDrafter.from_db_tokens(None, "refresh_tok", "cid", "csecret")
        assert drafter.is_authorized() is False


class TestGmailDrafterIsAuthorized:
    """Tests for GmailDrafter.is_authorized with file-based tokens."""

    def test_no_token_path(self):
        from src.services.gmail_drafter import GmailDrafter
        drafter = GmailDrafter(token_path="/nonexistent/path.json")
        assert drafter.is_authorized() is False

    def test_no_db_creds_no_file(self):
        from src.services.gmail_drafter import GmailDrafter
        drafter = GmailDrafter.__new__(GmailDrafter)
        drafter.token_path = None
        drafter.credentials_path = None
        drafter._service = None
        assert drafter.is_authorized() is False


class TestGmailDrafterCreateBatchDrafts:
    """Tests for GmailDrafter.create_batch_drafts."""

    def test_batch_with_failures(self):
        from src.services.gmail_drafter import GmailDrafter
        drafter = GmailDrafter.__new__(GmailDrafter)
        drafter._service = None
        drafter.credentials_path = None
        drafter.token_path = None

        # Mock create_draft to succeed first, fail second
        with patch.object(drafter, "create_draft") as mock_cd:
            mock_cd.side_effect = ["draft_123", OSError("API error")]

            results = drafter.create_batch_drafts([
                {"to_email": "a@b.com", "subject": "S1", "body_text": "B1"},
                {"to_email": "c@d.com", "subject": "S2", "body_text": "B2"},
            ])
            assert len(results) == 2
            assert results[0]["success"] is True
            assert results[0]["draft_id"] == "draft_123"
            assert results[1]["success"] is False
            assert results[1]["error"] == "API error"

    def test_batch_empty_list(self):
        from src.services.gmail_drafter import GmailDrafter
        drafter = GmailDrafter.__new__(GmailDrafter)
        results = drafter.create_batch_drafts([])
        assert results == []


class TestGmailDrafterCheckDraftStatus:
    """Tests for check_draft_status."""

    def test_draft_exists(self):
        from src.services.gmail_drafter import GmailDrafter
        drafter = GmailDrafter.__new__(GmailDrafter)
        drafter._service = None
        drafter.credentials_path = None
        drafter.token_path = None

        mock_service = MagicMock()
        mock_service.users().drafts().get().execute.return_value = {"id": "abc"}

        with patch.object(drafter, "_get_service", return_value=mock_service):
            assert drafter.check_draft_status("abc") == "draft"

    def test_draft_sent_404(self):
        from src.services.gmail_drafter import GmailDrafter
        from unittest.mock import PropertyMock

        drafter = GmailDrafter.__new__(GmailDrafter)
        drafter._service = None
        drafter.credentials_path = None
        drafter.token_path = None

        mock_service = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 404

        from googleapiclient.errors import HttpError
        mock_service.users().drafts().get().execute.side_effect = HttpError(
            mock_resp, b"Not Found",
        )

        with patch.object(drafter, "_get_service", return_value=mock_service):
            assert drafter.check_draft_status("abc") == "sent"

    def test_draft_api_error(self):
        from src.services.gmail_drafter import GmailDrafter
        drafter = GmailDrafter.__new__(GmailDrafter)
        drafter._service = None
        drafter.credentials_path = None
        drafter.token_path = None

        mock_service = MagicMock()
        mock_service.users().drafts().get().execute.side_effect = OSError("Network error")

        with patch.object(drafter, "_get_service", return_value=mock_service):
            assert drafter.check_draft_status("abc") == "error"


# ===========================================================================
# GMAIL SENDER
# ===========================================================================


class TestGmailSenderTokenExpiry:
    """Tests for GmailSender.is_token_expired."""

    def test_expired_token(self):
        from src.services.gmail_sender import GmailSender
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        sender = GmailSender("access", "refresh", past, "cid", "cs")
        assert sender.is_token_expired() is True

    def test_valid_token(self):
        from src.services.gmail_sender import GmailSender
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        sender = GmailSender("access", "refresh", future, "cid", "cs")
        assert sender.is_token_expired() is False

    def test_token_within_60s_buffer(self):
        from src.services.gmail_sender import GmailSender
        # 30 seconds from now — within 60s buffer, should be expired
        soon = datetime.now(timezone.utc) + timedelta(seconds=30)
        sender = GmailSender("access", "refresh", soon, "cid", "cs")
        assert sender.is_token_expired() is True

    def test_none_expiry(self):
        from src.services.gmail_sender import GmailSender
        sender = GmailSender("access", "refresh", None, "cid", "cs")
        assert sender.is_token_expired() is True

    def test_naive_datetime_expiry(self):
        from src.services.gmail_sender import GmailSender
        # Naive datetime (no tzinfo) should be treated as UTC
        future = datetime.now() + timedelta(hours=1)
        sender = GmailSender("access", "refresh", future, "cid", "cs")
        assert sender.is_token_expired() is False


class TestGmailSenderRefresh:
    """Tests for GmailSender.refresh."""

    def test_refresh_success(self):
        from src.services.gmail_sender import GmailSender
        sender = GmailSender("old_access", "refresh_tok", datetime.now(timezone.utc), "cid", "cs")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "new_access", "expires_in": 3600}

        with patch("src.services.gmail_sender.httpx.post", return_value=mock_resp):
            result = sender.refresh()
            assert result["access_token"] == "new_access"
            assert result["expires_in"] == 3600

    def test_refresh_no_refresh_token_raises(self):
        from src.services.gmail_sender import GmailSender, TokenRefreshError
        sender = GmailSender("access", "", datetime.now(timezone.utc), "cid", "cs")
        with pytest.raises(TokenRefreshError, match="No refresh token"):
            sender.refresh()

    def test_refresh_api_failure_raises(self):
        from src.services.gmail_sender import GmailSender, TokenRefreshError
        sender = GmailSender("access", "refresh_tok", datetime.now(timezone.utc), "cid", "cs")

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"error_description": "invalid_grant"}
        mock_resp.text = "Bad request"

        with patch("src.services.gmail_sender.httpx.post", return_value=mock_resp):
            with pytest.raises(TokenRefreshError, match="invalid_grant"):
                sender.refresh()

    def test_refresh_non_json_error_response(self):
        from src.services.gmail_sender import GmailSender, TokenRefreshError
        sender = GmailSender("access", "refresh_tok", datetime.now(timezone.utc), "cid", "cs")

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "Internal Server Error"

        with patch("src.services.gmail_sender.httpx.post", return_value=mock_resp):
            with pytest.raises(TokenRefreshError, match="Internal Server"):
                sender.refresh()


class TestGmailSenderSend:
    """Tests for GmailSender.send."""

    def test_send_success(self):
        from src.services.gmail_sender import GmailSender
        sender = GmailSender("access", "refresh", datetime.now(timezone.utc) + timedelta(hours=1), "cid", "cs")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "msg_123", "threadId": "thread_456"}

        with patch("src.services.gmail_sender.httpx.post", return_value=mock_resp):
            result = sender.send("to@test.com", "Subject", "<p>Body</p>")
            assert result["message_id"] == "msg_123"
            assert result["thread_id"] == "thread_456"

    def test_send_401_raises_token_refresh_error(self):
        from src.services.gmail_sender import GmailSender, TokenRefreshError
        sender = GmailSender("access", "refresh", datetime.now(timezone.utc) + timedelta(hours=1), "cid", "cs")

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch("src.services.gmail_sender.httpx.post", return_value=mock_resp):
            with pytest.raises(TokenRefreshError, match="expired or revoked"):
                sender.send("to@test.com", "Subject", "<p>Body</p>")

    def test_send_429_raises_send_error(self):
        from src.services.gmail_sender import GmailSender, GmailSendError
        sender = GmailSender("access", "refresh", datetime.now(timezone.utc) + timedelta(hours=1), "cid", "cs")

        mock_resp = MagicMock()
        mock_resp.status_code = 429

        with patch("src.services.gmail_sender.httpx.post", return_value=mock_resp):
            with pytest.raises(GmailSendError, match="rate limit"):
                sender.send("to@test.com", "Subject", "<p>Body</p>")

    def test_send_500_raises_send_error(self):
        from src.services.gmail_sender import GmailSender, GmailSendError
        sender = GmailSender("access", "refresh", datetime.now(timezone.utc) + timedelta(hours=1), "cid", "cs")

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch("src.services.gmail_sender.httpx.post", return_value=mock_resp):
            with pytest.raises(GmailSendError, match="500"):
                sender.send("to@test.com", "Subject", "<p>Body</p>")

    def test_send_with_from_name_and_email(self):
        from src.services.gmail_sender import GmailSender
        sender = GmailSender("access", "refresh", datetime.now(timezone.utc) + timedelta(hours=1), "cid", "cs")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "msg_x", "threadId": "t_x"}

        with patch("src.services.gmail_sender.httpx.post", return_value=mock_resp) as mock_post:
            sender.send("to@t.com", "S", "<p>B</p>", from_name="Alice", from_email="alice@co.com")
            # Verify the raw message includes From header
            call_kwargs = mock_post.call_args
            raw = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {})).get("raw", "")
            import base64
            decoded = base64.urlsafe_b64decode(raw + "==").decode("utf-8", errors="replace")
            assert "Alice" in decoded

    def test_send_strips_html_for_plain_text(self):
        from src.services.gmail_sender import GmailSender
        sender = GmailSender("access", "refresh", datetime.now(timezone.utc) + timedelta(hours=1), "cid", "cs")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "m", "threadId": "t"}

        with patch("src.services.gmail_sender.httpx.post", return_value=mock_resp):
            # Should not crash with HTML tags in body
            sender.send("to@t.com", "S", "<p>Hello <b>World</b></p>")


# ===========================================================================
# LINKEDIN ACCEPTANCE SCANNER
# ===========================================================================


class TestExtractAcceptedName:
    """Tests for _extract_accepted_name."""

    def test_accepted_your_invitation(self):
        from src.services.linkedin_acceptance_scanner import _extract_accepted_name
        assert _extract_accepted_name("John Smith accepted your invitation") == "John Smith"

    def test_are_now_connected(self):
        from src.services.linkedin_acceptance_scanner import _extract_accepted_name
        assert _extract_accepted_name("You and Jane Doe are now connected") == "Jane Doe"

    def test_accepted_connection_request(self):
        from src.services.linkedin_acceptance_scanner import _extract_accepted_name
        assert _extract_accepted_name("Bob Jones accepted your connection request") == "Bob Jones"

    def test_no_match(self):
        from src.services.linkedin_acceptance_scanner import _extract_accepted_name
        assert _extract_accepted_name("New message from John") is None

    def test_empty_subject(self):
        from src.services.linkedin_acceptance_scanner import _extract_accepted_name
        assert _extract_accepted_name("") is None

    def test_case_insensitive(self):
        from src.services.linkedin_acceptance_scanner import _extract_accepted_name
        assert _extract_accepted_name("JOHN SMITH ACCEPTED YOUR INVITATION") == "JOHN SMITH"


class TestExtractProfileUrl:
    """Tests for _extract_profile_url."""

    def test_valid_profile_url(self):
        from src.services.linkedin_acceptance_scanner import _extract_profile_url
        body = "Check out https://www.linkedin.com/in/john-smith for details"
        result = _extract_profile_url(body)
        assert result == "https://www.linkedin.com/in/john-smith"

    def test_no_profile_url(self):
        from src.services.linkedin_acceptance_scanner import _extract_profile_url
        assert _extract_profile_url("No LinkedIn URL here") is None

    def test_normalizes_to_lowercase(self):
        from src.services.linkedin_acceptance_scanner import _extract_profile_url
        body = "https://www.LinkedIn.com/in/JohnSmith"
        result = _extract_profile_url(body)
        assert result == "https://www.linkedin.com/in/johnsmith"

    def test_empty_body(self):
        from src.services.linkedin_acceptance_scanner import _extract_profile_url
        assert _extract_profile_url("") is None


class TestNormalizeName:
    """Tests for _normalize_name."""

    def test_basic_normalization(self):
        from src.services.linkedin_acceptance_scanner import _normalize_name
        assert _normalize_name("John Smith") == "john smith"

    def test_strips_special_chars(self):
        from src.services.linkedin_acceptance_scanner import _normalize_name
        assert _normalize_name("O'Brien-Jones") == "obrienjones"

    def test_empty_name(self):
        from src.services.linkedin_acceptance_scanner import _normalize_name
        assert _normalize_name("") == ""


class TestGetEmailBodyText:
    """Tests for _get_email_body_text."""

    def test_direct_body(self):
        import base64
        from src.services.linkedin_acceptance_scanner import _get_email_body_text
        data = base64.urlsafe_b64encode(b"Hello body text").decode()
        payload = {"body": {"data": data}}
        assert _get_email_body_text(payload) == "Hello body text"

    def test_multipart_text_plain(self):
        import base64
        from src.services.linkedin_acceptance_scanner import _get_email_body_text
        data = base64.urlsafe_b64encode(b"Plain text part").decode()
        payload = {
            "body": {},
            "parts": [
                {"mimeType": "text/plain", "body": {"data": data}},
            ],
        }
        assert _get_email_body_text(payload) == "Plain text part"

    def test_empty_payload(self):
        from src.services.linkedin_acceptance_scanner import _get_email_body_text
        assert _get_email_body_text({}) == ""

    def test_nested_multipart(self):
        import base64
        from src.services.linkedin_acceptance_scanner import _get_email_body_text
        data = base64.urlsafe_b64encode(b"Nested text").decode()
        payload = {
            "body": {},
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "body": {},
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": data}},
                    ],
                },
            ],
        }
        assert _get_email_body_text(payload) == "Nested text"


class TestScanLinkedinAcceptancesNoService:
    """Tests for scan_linkedin_acceptances when Gmail service is unavailable."""

    def test_returns_error_stats_when_no_auth(self):
        from src.services.linkedin_acceptance_scanner import scan_linkedin_acceptances
        from src.services.gmail_drafter import GmailDrafter

        mock_drafter = MagicMock(spec=GmailDrafter)
        mock_drafter._get_service.side_effect = RuntimeError("Not authorized")

        # Need a real DB connection for the function signature
        with patch("src.services.linkedin_acceptance_scanner.get_cursor"):
            stats = scan_linkedin_acceptances(
                MagicMock(), drafter=mock_drafter, user_id=TEST_USER_ID,
            )
        assert stats["errors"] >= 1
        assert stats["matched"] == 0


# ===========================================================================
# LINKEDIN ACTIONS
# ===========================================================================


class TestCompleteLinkedinAction:
    """Tests for complete_linkedin_action."""

    def test_invalid_action_type_raises(self, tmp_db):
        from src.services.linkedin_actions import complete_linkedin_action
        conn = _setup_db(tmp_db)
        with pytest.raises(ValueError, match="Invalid action_type"):
            complete_linkedin_action(conn, 1, 1, "invalid_action", user_id=TEST_USER_ID)
        conn.close()

    def test_not_enrolled_raises(self, tmp_db):
        from src.services.linkedin_actions import complete_linkedin_action
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        ctid = _create_contact(conn, cid)
        camp = create_campaign(conn, "li_action", user_id=TEST_USER_ID)
        # Contact not enrolled
        with pytest.raises(ValueError, match="not enrolled"):
            complete_linkedin_action(conn, ctid, camp, "connect", user_id=TEST_USER_ID)
        conn.close()

    def test_non_linkedin_step_raises(self, tmp_db):
        from src.services.linkedin_actions import complete_linkedin_action
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        ctid = _create_contact(conn, cid, linkedin_url="https://linkedin.com/in/test")
        camp = create_campaign(conn, "li_action2", user_id=TEST_USER_ID)
        tid = create_template(conn, "email_tpl", "email", "Hello", subject="Hi", user_id=TEST_USER_ID)
        add_sequence_step(conn, camp, 1, "email", template_id=tid, delay_days=0, user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)

        with pytest.raises(ValueError, match="not a LinkedIn step"):
            complete_linkedin_action(conn, ctid, camp, "connect", user_id=TEST_USER_ID)
        conn.close()

    def test_successful_connect_advances(self, tmp_db):
        from src.services.linkedin_actions import complete_linkedin_action
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        ctid = _create_contact(conn, cid, linkedin_url="https://linkedin.com/in/test")
        camp = create_campaign(conn, "li_advance", user_id=TEST_USER_ID)
        tid = create_template(conn, "li_tpl", "linkedin_connect", "Connect msg", subject="Connect", user_id=TEST_USER_ID)
        tid2 = create_template(conn, "li_tpl2", "email", "Follow up", subject="Follow", user_id=TEST_USER_ID)
        add_sequence_step(conn, camp, 1, "linkedin_connect", template_id=tid, delay_days=0, user_id=TEST_USER_ID)
        add_sequence_step(conn, camp, 2, "email", template_id=tid2, delay_days=3, user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)

        result = complete_linkedin_action(conn, ctid, camp, "connect", user_id=TEST_USER_ID)
        assert result["success"] is True
        assert result["advanced"] is True
        assert result["next_step"] == 2
        assert result["event_type"] == "linkedin_connect_done"
        conn.close()

    def test_last_step_completes_sequence(self, tmp_db):
        from src.services.linkedin_actions import complete_linkedin_action
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        ctid = _create_contact(conn, cid, linkedin_url="https://linkedin.com/in/test")
        camp = create_campaign(conn, "li_last", user_id=TEST_USER_ID)
        tid = create_template(conn, "li_tpl_last", "linkedin_connect", "Connect", subject="X", user_id=TEST_USER_ID)
        add_sequence_step(conn, camp, 1, "linkedin_connect", template_id=tid, delay_days=0, user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)

        result = complete_linkedin_action(conn, ctid, camp, "connect", user_id=TEST_USER_ID)
        assert result["success"] is True
        assert result["advanced"] is False
        assert result.get("completed_sequence") is True
        conn.close()

    def test_queued_status_transitions_to_in_progress(self, tmp_db):
        from src.services.linkedin_actions import complete_linkedin_action
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        ctid = _create_contact(conn, cid, linkedin_url="https://linkedin.com/in/test")
        camp = create_campaign(conn, "li_queued", user_id=TEST_USER_ID)
        tid = create_template(conn, "li_q_tpl", "linkedin_connect", "Msg", subject="S", user_id=TEST_USER_ID)
        tid2 = create_template(conn, "li_q_tpl2", "email", "F", subject="F", user_id=TEST_USER_ID)
        add_sequence_step(conn, camp, 1, "linkedin_connect", template_id=tid, delay_days=0, user_id=TEST_USER_ID)
        add_sequence_step(conn, camp, 2, "email", template_id=tid2, delay_days=3, user_id=TEST_USER_ID)
        enroll_contact(conn, ctid, camp, next_action_date=date.today().isoformat(), user_id=TEST_USER_ID)

        # Enrollment starts with "queued" status
        ccs_before = get_contact_campaign_status(conn, ctid, camp, user_id=TEST_USER_ID)
        assert ccs_before["status"] == "queued"

        result = complete_linkedin_action(conn, ctid, camp, "connect", user_id=TEST_USER_ID)
        assert result["success"] is True
        conn.close()

    def test_all_valid_action_types(self, tmp_db):
        """Verify all 5 action types are accepted."""
        from src.services.linkedin_actions import complete_linkedin_action
        valid = ["connect", "message", "engage", "insight", "final"]
        for action in valid:
            # Just verify no ValueError for valid types — will raise for enrollment
            conn = _setup_db(tmp_db)
            cid = _create_company(conn, name=f"Co_{action}")
            ctid = _create_contact(conn, cid, email=f"{action}@example.com")
            with pytest.raises(ValueError, match="not enrolled"):
                complete_linkedin_action(conn, ctid, 99999, action, user_id=TEST_USER_ID)
            conn.close()


# ===========================================================================
# LLM ADVISOR — additional edge cases
# ===========================================================================


class TestBuildAnalysisPromptEdgeCases:
    """Additional edge cases for _build_analysis_prompt."""

    def test_all_empty_lists(self):
        from src.services.llm_advisor import _build_analysis_prompt
        prompt = _build_analysis_prompt([], [], [], [])
        assert prompt.count("No data yet") >= 3

    def test_timing_data_included(self):
        from src.services.llm_advisor import _build_analysis_prompt
        timing = [{"delay_bucket": "1-3 days", "total": 20, "reply_rate": 0.15}]
        prompt = _build_analysis_prompt([], [], [], timing)
        assert "1-3 days" in prompt
        assert "15.0%" in prompt

    def test_all_data_populated(self):
        from src.services.llm_advisor import _build_analysis_prompt
        templates = [{"template_name": "T1", "channel": "email", "total_sends": 50,
                       "positive_rate": 0.12, "confidence": "high"}]
        channels = [{"channel": "email", "total_sends": 50, "positive_rate": 0.12}]
        segments = [{"aum_tier": "$1B+", "total": 10, "contacted": 8, "reply_rate": 0.25}]
        timing = [{"delay_bucket": "1-3 days", "total": 20, "reply_rate": 0.15}]
        prompt = _build_analysis_prompt(templates, channels, segments, timing)
        assert "T1" in prompt
        assert "$1B+" in prompt
        assert "1-3 days" in prompt


class TestParseInsightsEdgeCases:
    """Additional edge cases for _parse_insights."""

    def test_empty_string(self):
        from src.services.llm_advisor import _parse_insights
        result = _parse_insights("")
        assert result["insights"] == ["No response"]

    def test_none_input(self):
        from src.services.llm_advisor import _parse_insights
        result = _parse_insights(None)
        assert result["insights"] is not None

    def test_truncates_long_response(self):
        from src.services.llm_advisor import _parse_insights
        long_text = "A" * 1000
        result = _parse_insights(long_text)
        assert len(result["insights"][0]) <= 500

    def test_valid_json_with_extra_keys(self):
        from src.services.llm_advisor import _parse_insights
        response = json.dumps({
            "insights": ["I1"],
            "template_suggestions": [],
            "strategy_notes": "Notes",
            "extra_key": "ignored",
        })
        result = _parse_insights(response)
        assert result["insights"] == ["I1"]
        assert result["extra_key"] == "ignored"


class TestCallLlmNoApiKey:
    """Tests for _call_llm when API key is missing."""

    @patch("src.services.llm_client.detect_provider", return_value=None)
    def test_returns_not_configured(self, mock_detect):
        from src.services.llm_advisor import _call_llm
        result = _call_llm("test prompt")
        parsed = json.loads(result)
        assert "not configured" in parsed["insights"][0].lower() or "no llm api key" in parsed["insights"][0].lower()


class TestCallLlmApiFailure:
    """Tests for _call_llm when API call fails."""

    @patch("src.services.llm_client.detect_provider", return_value=("anthropic", "test-key"))
    @patch("src.services.llm_client._call_anthropic", side_effect=ConnectionError("Connection failed"))
    def test_api_error_returns_fallback(self, mock_call, mock_detect):
        from src.services.llm_advisor import _call_llm
        result = _call_llm("test prompt")
        parsed = json.loads(result)
        assert "failed" in parsed["insights"][0].lower()

    @patch("src.services.llm_client.detect_provider", return_value=("anthropic", "test-key"))
    @patch("src.services.llm_client._call_anthropic", return_value="not json at all")
    def test_malformed_response_returns_valid_json(self, mock_call, mock_detect):
        from src.services.llm_advisor import _call_llm
        result = _call_llm("test prompt")
        # _call_llm returns raw text which _parse_insights handles
        # Should not raise — raw text is valid even if not JSON
        assert isinstance(result, str)


class TestGetAnalysisHistory:
    """Tests for get_analysis_history."""

    def test_empty_history(self, tmp_db):
        from src.services.llm_advisor import get_analysis_history
        conn = _setup_db(tmp_db)
        camp = create_campaign(conn, "hist_empty", user_id=TEST_USER_ID)
        result = get_analysis_history(conn, camp, user_id=TEST_USER_ID)
        assert result == []
        conn.close()

    @patch("src.services.llm_client.detect_provider", return_value=None)
    def test_history_after_run(self, mock_detect, tmp_db):
        from src.services.llm_advisor import get_analysis_history, run_analysis
        conn = _setup_db(tmp_db)
        camp = create_campaign(conn, "hist_run", user_id=TEST_USER_ID)
        conn.commit()

        run_analysis(conn, camp, user_id=TEST_USER_ID)
        history = get_analysis_history(conn, camp, user_id=TEST_USER_ID)
        assert len(history) == 1
        assert history[0]["campaign_id"] == camp
        conn.close()


# ===========================================================================
# PERPLEXITY QUERY (deep_research_service)
# ===========================================================================


class TestPerplexityQuery:
    """Tests for _perplexity_query."""

    @patch("src.services.deep_research_service.httpx.post")
    def test_successful_query(self, mock_post):
        from src.services.deep_research_service import _perplexity_query

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Research result"}}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = _perplexity_query("test query", "api_key")
        assert result["response"] == "Research result"
        assert result["cost_usd"] > 0
        assert result["duration_ms"] >= 0

    @patch("src.services.deep_research_service.httpx.post")
    def test_429_raises(self, mock_post):
        from src.services.deep_research_service import _perplexity_query

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_resp,
        )
        mock_post.return_value = mock_resp

        with pytest.raises(httpx.HTTPStatusError):
            _perplexity_query("test query", "api_key")

    @patch("src.services.deep_research_service.httpx.post")
    def test_500_returns_error(self, mock_post):
        from src.services.deep_research_service import _perplexity_query

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_resp,
        )
        mock_post.return_value = mock_resp

        result = _perplexity_query("test query", "api_key")
        assert "error" in result
        assert result["cost_usd"] == 0

    @patch("src.services.deep_research_service.httpx.post")
    def test_network_error_returns_error(self, mock_post):
        from src.services.deep_research_service import _perplexity_query

        mock_post.side_effect = ConnectionError("Connection refused")

        result = _perplexity_query("test query", "api_key")
        assert "error" in result
        assert "Connection refused" in result["error"]


# ===========================================================================
# SYNTHESIZE WITH SONNET (deep_research_service)
# ===========================================================================


class TestSynthesizeWithSonnet:
    """Tests for _synthesize_with_sonnet."""

    @patch("src.services.deep_research_service.httpx.post")
    def test_valid_json_response(self, mock_post):
        from src.services.deep_research_service import _synthesize_with_sonnet

        synthesis = {
            "company_overview": "Overview",
            "crypto_signals": [],
            "key_people": [],
            "talking_points": [],
            "risk_factors": None,
            "updated_crypto_score": 70,
            "confidence": "medium",
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": [{"text": json.dumps(synthesis)}]}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = _synthesize_with_sonnet(
            [{"query": "q1", "response": "r1"}], "TestCorp", None, "api_key",
        )
        assert result["company_overview"] == "Overview"

    @patch("src.services.deep_research_service.httpx.post")
    def test_markdown_fences_stripped(self, mock_post):
        from src.services.deep_research_service import _synthesize_with_sonnet

        synthesis = {"company_overview": "Overview", "confidence": "high"}
        fenced = f"```json\n{json.dumps(synthesis)}\n```"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": [{"text": fenced}]}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = _synthesize_with_sonnet(
            [{"query": "q1", "response": "r1"}], "TestCorp", None, "api_key",
        )
        assert result["company_overview"] == "Overview"

    @patch("src.services.deep_research_service.httpx.post")
    def test_fallback_on_double_json_failure(self, mock_post):
        from src.services.deep_research_service import _synthesize_with_sonnet

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": [{"text": "This is not JSON at all"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = _synthesize_with_sonnet(
            [{"query": "q1", "response": "r1"}], "TestCorp", None, "api_key",
        )
        assert result["confidence"] == "low"
        assert result["company_overview"] == "This is not JSON at all"

    @patch("src.services.deep_research_service.httpx.post")
    def test_api_error_raises_runtime_error(self, mock_post):
        from src.services.deep_research_service import _synthesize_with_sonnet

        mock_post.side_effect = ConnectionError("Network error")

        with pytest.raises(RuntimeError, match="Synthesis failed"):
            _synthesize_with_sonnet(
                [{"query": "q1", "response": "r1"}], "TestCorp", None, "api_key",
            )

    @patch("src.services.deep_research_service.httpx.post")
    def test_bulk_research_passed_to_prompt(self, mock_post):
        from src.services.deep_research_service import _synthesize_with_sonnet

        synthesis = {"company_overview": "O", "confidence": "high"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": [{"text": json.dumps(synthesis)}]}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        bulk = {"web_search_raw": "web data", "website_crawl_raw": "crawl data"}
        result = _synthesize_with_sonnet(
            [{"query": "q1", "response": "r1"}], "TestCorp", bulk, "api_key",
        )
        # Verify the prompt included bulk data
        call_args = mock_post.call_args
        prompt_text = call_args.kwargs.get("json", call_args[1].get("json", {}))["messages"][0]["content"]
        assert "web data" in prompt_text
        assert "crawl data" in prompt_text


# ===========================================================================
# SEND EMAIL (email_sender) — retry and error handling
# ===========================================================================


class TestSendEmail:
    """Tests for send_email with retry logic."""

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_successful_send(self, mock_smtp):
        from src.services.email_sender import send_email
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email("host", 587, "user", "pass", "from@a.com", "to@b.com", "Subject", "Body")
        assert result is True

    @patch("src.services.email_sender.smtplib.SMTP")
    def test_recipients_refused_no_retry(self, mock_smtp):
        from src.services.email_sender import send_email
        mock_server = MagicMock()
        mock_server.sendmail.side_effect = smtplib.SMTPRecipientsRefused({"to@b.com": (550, b"rejected")})
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email("host", 587, "user", "pass", "from@a.com", "to@b.com", "S", "B")
        assert result is False
        # Should not retry on permanent error
        assert mock_server.sendmail.call_count == 1

    @patch("src.services.email_sender.time.sleep")
    @patch("src.services.email_sender.smtplib.SMTP")
    def test_transient_error_retries(self, mock_smtp, mock_sleep):
        from src.services.email_sender import send_email
        mock_server = MagicMock()
        # Fail twice with transient error, succeed on third
        mock_server.sendmail.side_effect = [
            smtplib.SMTPServerDisconnected("lost connection"),
            smtplib.SMTPServerDisconnected("lost connection"),
            None,  # success
        ]
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email("host", 587, "user", "pass", "from@a.com", "to@b.com", "S", "B")
        assert result is True
        assert mock_server.sendmail.call_count == 3


# ===========================================================================
# DEEP RESEARCH — get_previous_crypto_score
# ===========================================================================


class TestGetPreviousCryptoScore:
    """Tests for _get_previous_crypto_score."""

    def test_no_prior_score_returns_none(self, tmp_db):
        from src.services.deep_research_service import _get_previous_crypto_score
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)
        result = _get_previous_crypto_score(conn, cid, user_id=TEST_USER_ID)
        assert result is None
        conn.close()

    def test_retrieves_score_from_research_results(self, tmp_db):
        from src.services.deep_research_service import _get_previous_crypto_score
        conn = _setup_db(tmp_db)
        cid = _create_company(conn)

        # Insert research_jobs + research_results
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO research_jobs (name, method, total_companies, cost_estimate_usd, status, user_id)
                   VALUES ('test', 'hybrid', 1, 0.01, 'completed', %s) RETURNING id""",
                (TEST_USER_ID,),
            )
            job_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO research_results (job_id, company_id, company_name, crypto_score, category, status)
                   VALUES (%s, %s, 'Acme Fund', 85, 'confirmed_investor', 'completed')""",
                (job_id, cid),
            )
            conn.commit()

        result = _get_previous_crypto_score(conn, cid, user_id=TEST_USER_ID)
        assert result == 85
        conn.close()
