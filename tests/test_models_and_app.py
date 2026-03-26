"""Comprehensive tests for models (CRUD layer) and application services.

Covers:
  - src/models/campaigns.py   (campaigns, sequence steps, enrollment, template usage)
  - src/models/database.py    (get_cursor, run_migrations, scoped_query, verify_ownership)
  - src/models/templates.py   (create, get, list)
  - src/models/events.py      (log_event)
  - src/application/queue_service.py (apply_cross_campaign_email_dedup, send_email_batch)

Every CRUD function is tested for correctness, edge cases, and multi-tenancy
(user_id scoping). Uses the session-scoped tmp_db fixture from conftest.py.
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import psycopg2
import pytest

from tests.conftest import TEST_USER_ID, insert_company, insert_contact
from src.models.database import (
    get_connection,
    get_cursor,
    run_migrations,
    get_table_names,
    scoped_query,
    scoped_query_one,
    verify_ownership,
    OWNED_TABLES,
)
from src.models.campaigns import (
    create_campaign,
    get_campaign,
    get_campaign_by_name,
    list_campaigns,
    update_campaign_status,
    add_sequence_step,
    get_sequence_steps,
    enroll_contact,
    bulk_enroll_contacts,
    get_contact_campaign_status,
    update_contact_campaign_status,
    record_template_usage,
    get_message_draft,
)
from src.models.templates import (
    create_template,
    get_template,
    list_templates,
)
from src.models.events import log_event
from src.application.queue_service import (
    apply_cross_campaign_email_dedup,
    send_email_batch,
)


# ===================================================================
# Fixtures
# ===================================================================

OTHER_USER_ID = None  # populated by user_b fixture


@pytest.fixture
def conn(tmp_db):
    """Return a live connection with migrations applied."""
    connection = get_connection(tmp_db)
    run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def user_b(conn):
    """Create a second user for multi-tenancy tests. Returns user_b's id."""
    global OTHER_USER_ID
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (email, name) VALUES ('other@test.com', 'Other User') "
        "ON CONFLICT (email) DO UPDATE SET name = 'Other User' RETURNING id"
    )
    OTHER_USER_ID = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    return OTHER_USER_ID


@pytest.fixture
def campaign_id(conn):
    return create_campaign(conn, "Test Campaign", description="desc", user_id=TEST_USER_ID)


@pytest.fixture
def template_id(conn):
    return create_template(
        conn,
        name="Welcome Email",
        channel="email",
        body_template="Hi {{first_name}}, welcome.",
        subject="Welcome",
        user_id=TEST_USER_ID,
    )


@pytest.fixture
def company_id(conn):
    return insert_company(conn, "Acme Corp", aum_millions=500, country="US")


@pytest.fixture
def contact_id(conn, company_id):
    return insert_contact(conn, company_id, first_name="Jane", last_name="Doe", email="jane@acme.com")


@pytest.fixture
def five_contacts(conn, company_id):
    """Insert 5 contacts and return their ids."""
    return [
        insert_contact(conn, company_id, first_name=f"C{i}", last_name=f"L{i}")
        for i in range(5)
    ]


# ===================================================================
# 1. DATABASE INFRASTRUCTURE (src/models/database.py)
# ===================================================================


class TestGetCursor:
    """get_cursor context manager."""

    def test_yields_cursor(self, conn):
        with get_cursor(conn) as cur:
            cur.execute("SELECT 1 AS n")
            row = cur.fetchone()
        assert row["n"] == 1

    def test_cursor_closed_after_block(self, conn):
        with get_cursor(conn) as cur:
            pass
        assert cur.closed

    def test_cursor_closed_on_exception(self, conn):
        try:
            with get_cursor(conn) as cur:
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert cur.closed


class TestRunMigrations:
    """run_migrations is idempotent and creates expected tables."""

    def test_creates_core_tables(self, conn):
        tables = get_table_names(conn)
        for t in ("companies", "contacts", "campaigns", "templates",
                   "sequence_steps", "contact_campaign_status", "events",
                   "dedup_log", "message_drafts"):
            assert t in tables, f"Missing table: {t}"

    def test_idempotent_double_run(self, conn):
        run_migrations(conn)
        run_migrations(conn)
        tables = get_table_names(conn)
        assert "companies" in tables

    def test_schema_migrations_tracking(self, conn):
        with get_cursor(conn) as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM schema_migrations")
            cnt = cur.fetchone()["cnt"]
        assert cnt > 0, "No migrations recorded"

    def test_no_duplicate_migration_entries(self, conn):
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT filename, COUNT(*) AS c FROM schema_migrations "
                "GROUP BY filename HAVING COUNT(*) > 1"
            )
            dupes = cur.fetchall()
        assert dupes == [], f"Duplicate migrations: {dupes}"


class TestScopedQuery:
    """scoped_query and scoped_query_one helpers."""

    def test_scoped_query_returns_rows(self, conn, company_id):
        rows = scoped_query(
            conn, TEST_USER_ID,
            "SELECT id, name FROM companies WHERE id = %s AND user_id = %s",
            (company_id,),
        )
        assert len(rows) == 1
        assert rows[0]["id"] == company_id

    def test_scoped_query_empty_for_wrong_user(self, conn, company_id, user_b):
        rows = scoped_query(
            conn, OTHER_USER_ID,
            "SELECT id FROM companies WHERE id = %s AND user_id = %s",
            (company_id,),
        )
        assert rows == []

    def test_scoped_query_one_returns_dict(self, conn, company_id):
        row = scoped_query_one(
            conn, TEST_USER_ID,
            "SELECT name FROM companies WHERE id = %s AND user_id = %s",
            (company_id,),
        )
        assert row["name"] == "Acme Corp"

    def test_scoped_query_one_returns_none(self, conn):
        row = scoped_query_one(
            conn, TEST_USER_ID,
            "SELECT id FROM companies WHERE id = %s AND user_id = %s",
            (99999,),
        )
        assert row is None


class TestVerifyOwnership:
    """verify_ownership helper."""

    def test_returns_true_for_owner(self, conn, company_id):
        assert verify_ownership(conn, "companies", company_id, TEST_USER_ID) is True

    def test_returns_none_for_non_owner(self, conn, company_id, user_b):
        assert verify_ownership(conn, "companies", company_id, OTHER_USER_ID) is None

    def test_returns_none_for_nonexistent_id(self, conn):
        assert verify_ownership(conn, "companies", 99999, TEST_USER_ID) is None

    def test_rejects_unknown_table(self, conn):
        with pytest.raises(ValueError, match="Unknown owned table"):
            verify_ownership(conn, "nonexistent_table", 1, TEST_USER_ID)

    def test_all_owned_tables_present(self, conn):
        """Every table in OWNED_TABLES must exist in the database."""
        tables = set(get_table_names(conn))
        for t in OWNED_TABLES:
            assert t in tables, f"OWNED_TABLES references missing table: {t}"


# ===================================================================
# 2. CAMPAIGNS CRUD (src/models/campaigns.py)
# ===================================================================


class TestCreateCampaignExtended:
    def test_returns_int_id(self, conn):
        cid = create_campaign(conn, "New Camp", user_id=TEST_USER_ID)
        assert isinstance(cid, int) and cid > 0

    def test_stores_description(self, conn):
        cid = create_campaign(conn, "Desc Camp", description="hello", user_id=TEST_USER_ID)
        row = get_campaign(conn, cid, user_id=TEST_USER_ID)
        assert row["description"] == "hello"

    def test_null_description_when_omitted(self, conn):
        cid = create_campaign(conn, "No Desc", user_id=TEST_USER_ID)
        row = get_campaign(conn, cid, user_id=TEST_USER_ID)
        assert row["description"] is None

    def test_default_status_active(self, conn):
        cid = create_campaign(conn, "Status Test", user_id=TEST_USER_ID)
        assert get_campaign(conn, cid, user_id=TEST_USER_ID)["status"] == "active"

    def test_duplicate_name_same_user_raises(self, conn):
        create_campaign(conn, "Dup Name", user_id=TEST_USER_ID)
        with pytest.raises(psycopg2.IntegrityError):
            create_campaign(conn, "Dup Name", user_id=TEST_USER_ID)
        conn.rollback()

    def test_same_name_different_users_allowed(self, conn, user_b):
        create_campaign(conn, "Cross User", user_id=TEST_USER_ID)
        cid_b = create_campaign(conn, "Cross User", user_id=OTHER_USER_ID)
        assert cid_b > 0

    def test_user_id_stored(self, conn):
        cid = create_campaign(conn, "UID Check", user_id=TEST_USER_ID)
        with get_cursor(conn) as cur:
            cur.execute("SELECT user_id FROM campaigns WHERE id = %s", (cid,))
            assert cur.fetchone()["user_id"] == TEST_USER_ID


class TestGetCampaignExtended:
    def test_returns_full_row(self, conn, campaign_id):
        row = get_campaign(conn, campaign_id, user_id=TEST_USER_ID)
        assert row["name"] == "Test Campaign"
        assert row["description"] == "desc"
        assert "created_at" in row

    def test_nonexistent_returns_none(self, conn):
        assert get_campaign(conn, 99999, user_id=TEST_USER_ID) is None

    def test_wrong_user_returns_none(self, conn, campaign_id, user_b):
        assert get_campaign(conn, campaign_id, user_id=OTHER_USER_ID) is None


class TestGetCampaignByNameExtended:
    def test_finds_by_name(self, conn, campaign_id):
        row = get_campaign_by_name(conn, "Test Campaign", user_id=TEST_USER_ID)
        assert row["id"] == campaign_id

    def test_missing_name_returns_none(self, conn):
        assert get_campaign_by_name(conn, "NOPE", user_id=TEST_USER_ID) is None

    def test_scoped_to_user(self, conn, user_b):
        create_campaign(conn, "Scoped Name", user_id=TEST_USER_ID)
        assert get_campaign_by_name(conn, "Scoped Name", user_id=OTHER_USER_ID) is None


class TestListCampaignsExtended:
    def test_empty_list(self, conn):
        assert list_campaigns(conn, user_id=TEST_USER_ID) == []

    def test_returns_multiple(self, conn):
        create_campaign(conn, "A", user_id=TEST_USER_ID)
        create_campaign(conn, "B", user_id=TEST_USER_ID)
        assert len(list_campaigns(conn, user_id=TEST_USER_ID)) == 2

    def test_ordered_by_id(self, conn):
        id1 = create_campaign(conn, "First", user_id=TEST_USER_ID)
        id2 = create_campaign(conn, "Second", user_id=TEST_USER_ID)
        result = list_campaigns(conn, user_id=TEST_USER_ID)
        assert result[0]["id"] == id1
        assert result[1]["id"] == id2

    def test_filter_by_status(self, conn):
        c1 = create_campaign(conn, "Active", user_id=TEST_USER_ID)
        c2 = create_campaign(conn, "ToPause", user_id=TEST_USER_ID)
        update_campaign_status(conn, c2, "paused", user_id=TEST_USER_ID)
        assert len(list_campaigns(conn, status="active", user_id=TEST_USER_ID)) == 1
        assert len(list_campaigns(conn, status="paused", user_id=TEST_USER_ID)) == 1

    def test_filter_no_match_returns_empty(self, conn):
        create_campaign(conn, "Active Camp", user_id=TEST_USER_ID)
        assert list_campaigns(conn, status="completed", user_id=TEST_USER_ID) == []

    def test_user_isolation(self, conn, user_b):
        create_campaign(conn, "Mine", user_id=TEST_USER_ID)
        create_campaign(conn, "Theirs", user_id=OTHER_USER_ID)
        mine = list_campaigns(conn, user_id=TEST_USER_ID)
        theirs = list_campaigns(conn, user_id=OTHER_USER_ID)
        assert len(mine) == 1 and mine[0]["name"] == "Mine"
        assert len(theirs) == 1 and theirs[0]["name"] == "Theirs"


class TestUpdateCampaignStatus:
    def test_update_to_paused(self, conn, campaign_id):
        update_campaign_status(conn, campaign_id, "paused", user_id=TEST_USER_ID)
        assert get_campaign(conn, campaign_id, user_id=TEST_USER_ID)["status"] == "paused"

    def test_update_to_completed(self, conn, campaign_id):
        update_campaign_status(conn, campaign_id, "completed", user_id=TEST_USER_ID)
        assert get_campaign(conn, campaign_id, user_id=TEST_USER_ID)["status"] == "completed"

    def test_noop_for_wrong_user(self, conn, campaign_id, user_b):
        update_campaign_status(conn, campaign_id, "paused", user_id=OTHER_USER_ID)
        assert get_campaign(conn, campaign_id, user_id=TEST_USER_ID)["status"] == "active"


# ===================================================================
# 3. SEQUENCE STEPS
# ===================================================================


class TestAddSequenceStepExtended:
    def test_basic_insert(self, conn, campaign_id):
        sid = add_sequence_step(conn, campaign_id, 1, "email", user_id=TEST_USER_ID)
        assert isinstance(sid, int) and sid > 0

    def test_all_params(self, conn, campaign_id, template_id):
        sid = add_sequence_step(
            conn, campaign_id, 1, "email",
            template_id=template_id, delay_days=5,
            gdpr_only=True, non_gdpr_only=False,
            user_id=TEST_USER_ID,
        )
        steps = get_sequence_steps(conn, campaign_id, user_id=TEST_USER_ID)
        s = steps[0]
        assert s["template_id"] == template_id
        assert s["delay_days"] == 5
        assert s["gdpr_only"] is True
        assert s["non_gdpr_only"] is False

    def test_duplicate_step_order_raises(self, conn, campaign_id):
        add_sequence_step(conn, campaign_id, 1, "email", user_id=TEST_USER_ID)
        with pytest.raises(psycopg2.IntegrityError):
            add_sequence_step(conn, campaign_id, 1, "linkedin_connect", user_id=TEST_USER_ID)
        conn.rollback()

    def test_same_order_different_campaigns(self, conn):
        c1 = create_campaign(conn, "C1", user_id=TEST_USER_ID)
        c2 = create_campaign(conn, "C2", user_id=TEST_USER_ID)
        s1 = add_sequence_step(conn, c1, 1, "email", user_id=TEST_USER_ID)
        s2 = add_sequence_step(conn, c2, 1, "email", user_id=TEST_USER_ID)
        assert s1 != s2

    def test_wrong_user_campaign_raises_permission(self, conn, user_b):
        b_camp = create_campaign(conn, "B Camp", user_id=OTHER_USER_ID)
        with pytest.raises(PermissionError):
            add_sequence_step(conn, b_camp, 1, "email", user_id=TEST_USER_ID)

    def test_nonexistent_campaign_raises_permission(self, conn):
        with pytest.raises(PermissionError):
            add_sequence_step(conn, 99999, 1, "email", user_id=TEST_USER_ID)


class TestGetSequenceStepsExtended:
    def test_empty(self, conn, campaign_id):
        assert get_sequence_steps(conn, campaign_id, user_id=TEST_USER_ID) == []

    def test_ordered_by_step_order(self, conn, campaign_id):
        add_sequence_step(conn, campaign_id, 3, "email", delay_days=7, user_id=TEST_USER_ID)
        add_sequence_step(conn, campaign_id, 1, "linkedin_connect", user_id=TEST_USER_ID)
        add_sequence_step(conn, campaign_id, 2, "linkedin_message", user_id=TEST_USER_ID)
        steps = get_sequence_steps(conn, campaign_id, user_id=TEST_USER_ID)
        assert [s["step_order"] for s in steps] == [1, 2, 3]

    def test_only_for_given_campaign(self, conn):
        c1 = create_campaign(conn, "Steps-C1", user_id=TEST_USER_ID)
        c2 = create_campaign(conn, "Steps-C2", user_id=TEST_USER_ID)
        add_sequence_step(conn, c1, 1, "email", user_id=TEST_USER_ID)
        add_sequence_step(conn, c2, 1, "email", user_id=TEST_USER_ID)
        add_sequence_step(conn, c2, 2, "email", user_id=TEST_USER_ID)
        assert len(get_sequence_steps(conn, c1, user_id=TEST_USER_ID)) == 1
        assert len(get_sequence_steps(conn, c2, user_id=TEST_USER_ID)) == 2

    def test_wrong_user_returns_empty(self, conn, campaign_id, user_b):
        add_sequence_step(conn, campaign_id, 1, "email", user_id=TEST_USER_ID)
        assert get_sequence_steps(conn, campaign_id, user_id=OTHER_USER_ID) == []


# ===================================================================
# 4. ENROLLMENT
# ===================================================================


class TestEnrollContactExtended:
    def test_basic_enroll(self, conn, contact_id, campaign_id):
        eid = enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert isinstance(eid, int) and eid > 0

    def test_default_status_queued(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row["status"] == "queued"
        assert row["current_step"] == 1

    def test_with_variant(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, variant="B", user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row["assigned_variant"] == "B"

    def test_with_next_action_date(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, next_action_date="2026-04-15", user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert str(row["next_action_date"]) == "2026-04-15"

    def test_duplicate_returns_none(self, conn, contact_id, campaign_id):
        e1 = enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        e2 = enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert e1 is not None
        assert e2 is None

    def test_same_contact_two_campaigns(self, conn, contact_id):
        c1 = create_campaign(conn, "Enroll-C1", user_id=TEST_USER_ID)
        c2 = create_campaign(conn, "Enroll-C2", user_id=TEST_USER_ID)
        e1 = enroll_contact(conn, contact_id, c1, user_id=TEST_USER_ID)
        e2 = enroll_contact(conn, contact_id, c2, user_id=TEST_USER_ID)
        assert e1 is not None and e2 is not None and e1 != e2

    def test_wrong_user_campaign_raises_permission(self, conn, contact_id, user_b):
        b_camp = create_campaign(conn, "B Enroll Camp", user_id=OTHER_USER_ID)
        with pytest.raises(PermissionError):
            enroll_contact(conn, contact_id, b_camp, user_id=TEST_USER_ID)

    def test_nonexistent_campaign_raises_permission(self, conn, contact_id):
        with pytest.raises(PermissionError):
            enroll_contact(conn, contact_id, 99999, user_id=TEST_USER_ID)


class TestBulkEnrollContactsExtended:
    def test_enroll_many(self, conn, campaign_id, five_contacts):
        count = bulk_enroll_contacts(conn, campaign_id, five_contacts, user_id=TEST_USER_ID)
        assert count == 5

    def test_empty_list_returns_zero(self, conn, campaign_id):
        assert bulk_enroll_contacts(conn, campaign_id, [], user_id=TEST_USER_ID) == 0

    def test_single_contact(self, conn, campaign_id, contact_id):
        count = bulk_enroll_contacts(conn, campaign_id, [contact_id], user_id=TEST_USER_ID)
        assert count == 1

    def test_skips_already_enrolled(self, conn, campaign_id, five_contacts):
        enroll_contact(conn, five_contacts[0], campaign_id, user_id=TEST_USER_ID)
        enroll_contact(conn, five_contacts[1], campaign_id, user_id=TEST_USER_ID)
        count = bulk_enroll_contacts(conn, campaign_id, five_contacts, user_id=TEST_USER_ID)
        assert count == 3

    def test_all_already_enrolled(self, conn, campaign_id, five_contacts):
        bulk_enroll_contacts(conn, campaign_id, five_contacts, user_id=TEST_USER_ID)
        count = bulk_enroll_contacts(conn, campaign_id, five_contacts, user_id=TEST_USER_ID)
        assert count == 0

    def test_variant_assigner(self, conn, campaign_id, five_contacts):
        assigner = lambda cid: "A" if cid % 2 == 0 else "B"
        bulk_enroll_contacts(conn, campaign_id, five_contacts, variant_assigner=assigner, user_id=TEST_USER_ID)
        for cid in five_contacts:
            row = get_contact_campaign_status(conn, cid, campaign_id, user_id=TEST_USER_ID)
            assert row["assigned_variant"] == ("A" if cid % 2 == 0 else "B")

    def test_no_variant_assigner_nulls(self, conn, campaign_id, five_contacts):
        bulk_enroll_contacts(conn, campaign_id, five_contacts, user_id=TEST_USER_ID)
        for cid in five_contacts:
            row = get_contact_campaign_status(conn, cid, campaign_id, user_id=TEST_USER_ID)
            assert row["assigned_variant"] is None

    def test_wrong_user_raises_permission(self, conn, five_contacts, user_b):
        b_camp = create_campaign(conn, "B Bulk Camp", user_id=OTHER_USER_ID)
        with pytest.raises(PermissionError):
            bulk_enroll_contacts(conn, b_camp, five_contacts, user_id=TEST_USER_ID)


# ===================================================================
# 5. CONTACT CAMPAIGN STATUS
# ===================================================================


class TestGetContactCampaignStatusExtended:
    def test_enrolled_returns_row(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row is not None
        assert row["contact_id"] == contact_id
        assert row["campaign_id"] == campaign_id

    def test_not_enrolled_returns_none(self, conn, contact_id, campaign_id):
        assert get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID) is None

    def test_wrong_user_returns_none(self, conn, contact_id, campaign_id, user_b):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert get_contact_campaign_status(conn, contact_id, campaign_id, user_id=OTHER_USER_ID) is None


class TestUpdateContactCampaignStatusExtended:
    def test_update_status_only(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        update_contact_campaign_status(conn, contact_id, campaign_id, status="in_progress", user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row["status"] == "in_progress"

    def test_update_current_step(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        update_contact_campaign_status(conn, contact_id, campaign_id, current_step=3, user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row["current_step"] == 3

    def test_update_next_action_date(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        update_contact_campaign_status(conn, contact_id, campaign_id, next_action_date="2026-06-01", user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert str(row["next_action_date"]) == "2026-06-01"

    def test_update_channel_override_set(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        update_contact_campaign_status(conn, contact_id, campaign_id, channel_override="linkedin_only", user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row["channel_override"] == "linkedin_only"

    def test_update_channel_override_clear(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        update_contact_campaign_status(conn, contact_id, campaign_id, channel_override="linkedin_only", user_id=TEST_USER_ID)
        # Explicitly pass None to clear it
        update_contact_campaign_status(conn, contact_id, campaign_id, channel_override=None, user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row["channel_override"] is None

    def test_update_multiple_fields(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        update_contact_campaign_status(
            conn, contact_id, campaign_id,
            status="replied_positive", current_step=2, next_action_date="2026-07-01",
            user_id=TEST_USER_ID,
        )
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row["status"] == "replied_positive"
        assert row["current_step"] == 2
        assert str(row["next_action_date"]) == "2026-07-01"

    def test_noop_when_no_fields(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        update_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row["status"] == "queued"

    def test_updated_at_changes(self, conn, contact_id, campaign_id):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        before = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)["updated_at"]
        update_contact_campaign_status(conn, contact_id, campaign_id, status="in_progress", user_id=TEST_USER_ID)
        after = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)["updated_at"]
        assert after >= before

    def test_step_update_clears_sent_at(self, conn, contact_id, campaign_id):
        """Advancing current_step should reset sent_at to NULL (idempotency for next send)."""
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        # Simulate a prior send by setting sent_at
        with get_cursor(conn) as cur:
            cur.execute(
                "UPDATE contact_campaign_status SET sent_at = NOW() "
                "WHERE contact_id = %s AND campaign_id = %s",
                (contact_id, campaign_id),
            )
        conn.commit()
        # Advance step — sent_at should be cleared
        update_contact_campaign_status(conn, contact_id, campaign_id, current_step=2, user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row["sent_at"] is None

    def test_wrong_user_noop(self, conn, contact_id, campaign_id, user_b):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        update_contact_campaign_status(conn, contact_id, campaign_id, status="completed", user_id=OTHER_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row["status"] == "queued"  # unchanged

    def test_all_status_values(self, conn, company_id, campaign_id):
        """Every valid status value should be accepted."""
        statuses = ["queued", "in_progress", "replied_positive", "replied_negative",
                     "no_response", "bounced", "completed", "unsubscribed"]
        for i, status in enumerate(statuses):
            cid = insert_contact(conn, company_id, first_name=f"S{i}", last_name="Status")
            enroll_contact(conn, cid, campaign_id, user_id=TEST_USER_ID)
            update_contact_campaign_status(conn, cid, campaign_id, status=status, user_id=TEST_USER_ID)
            row = get_contact_campaign_status(conn, cid, campaign_id, user_id=TEST_USER_ID)
            assert row["status"] == status


# ===================================================================
# 6. RECORD TEMPLATE USAGE (idempotent ON CONFLICT)
# ===================================================================


class TestRecordTemplateUsage:
    def test_basic_insert(self, conn, contact_id, campaign_id, template_id):
        record_template_usage(conn, contact_id, campaign_id, template_id, "email")
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT * FROM contact_template_history "
                "WHERE contact_id = %s AND campaign_id = %s AND template_id = %s",
                (contact_id, campaign_id, template_id),
            )
            row = cur.fetchone()
        assert row is not None
        assert row["channel"] == "email"
        assert row["sent_at"] is not None

    def test_idempotent_second_insert(self, conn, contact_id, campaign_id, template_id):
        record_template_usage(conn, contact_id, campaign_id, template_id, "email")
        record_template_usage(conn, contact_id, campaign_id, template_id, "email")
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM contact_template_history "
                "WHERE contact_id = %s AND campaign_id = %s AND template_id = %s",
                (contact_id, campaign_id, template_id),
            )
            assert cur.fetchone()["cnt"] == 1

    def test_null_template_id_noop(self, conn, contact_id, campaign_id):
        """Passing template_id=0 (falsy) should be a no-op guard."""
        record_template_usage(conn, contact_id, campaign_id, 0, "email")
        with get_cursor(conn) as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM contact_template_history")
            assert cur.fetchone()["cnt"] == 0

    def test_different_templates_same_contact(self, conn, contact_id, campaign_id):
        t1 = create_template(conn, "T1", "email", "body1", user_id=TEST_USER_ID)
        t2 = create_template(conn, "T2", "email", "body2", user_id=TEST_USER_ID)
        record_template_usage(conn, contact_id, campaign_id, t1, "email")
        record_template_usage(conn, contact_id, campaign_id, t2, "email")
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM contact_template_history WHERE contact_id = %s",
                (contact_id,),
            )
            assert cur.fetchone()["cnt"] == 2

    def test_linkedin_channel(self, conn, contact_id, campaign_id, template_id):
        record_template_usage(conn, contact_id, campaign_id, template_id, "linkedin_connect")
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT channel FROM contact_template_history "
                "WHERE contact_id = %s AND template_id = %s",
                (contact_id, template_id),
            )
            assert cur.fetchone()["channel"] == "linkedin_connect"


# ===================================================================
# 7. GET MESSAGE DRAFT
# ===================================================================


class TestGetMessageDraft:
    def test_returns_none_when_empty(self, conn, contact_id, campaign_id):
        row = get_message_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)
        assert row is None

    def test_returns_inserted_draft(self, conn, contact_id, campaign_id):
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO message_drafts
                   (contact_id, campaign_id, step_order, draft_text, channel, user_id)
                   VALUES (%s, %s, 1, 'Hello draft', 'email', %s)""",
                (contact_id, campaign_id, TEST_USER_ID),
            )
        conn.commit()
        row = get_message_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)
        assert row is not None
        assert row["draft_text"] == "Hello draft"

    def test_wrong_user_returns_none(self, conn, contact_id, campaign_id, user_b):
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO message_drafts
                   (contact_id, campaign_id, step_order, draft_text, channel, user_id)
                   VALUES (%s, %s, 1, 'Secret draft', 'email', %s)""",
                (contact_id, campaign_id, TEST_USER_ID),
            )
        conn.commit()
        assert get_message_draft(conn, contact_id, campaign_id, 1, user_id=OTHER_USER_ID) is None

    def test_wrong_step_order_returns_none(self, conn, contact_id, campaign_id):
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO message_drafts
                   (contact_id, campaign_id, step_order, draft_text, channel, user_id)
                   VALUES (%s, %s, 1, 'Step 1 draft', 'email', %s)""",
                (contact_id, campaign_id, TEST_USER_ID),
            )
        conn.commit()
        assert get_message_draft(conn, contact_id, campaign_id, 2, user_id=TEST_USER_ID) is None


# ===================================================================
# 8. TEMPLATES (src/models/templates.py)
# ===================================================================


class TestCreateTemplateExtended:
    def test_returns_int_id(self, conn):
        tid = create_template(conn, "T", "email", "body", user_id=TEST_USER_ID)
        assert isinstance(tid, int) and tid > 0

    def test_all_fields_stored(self, conn):
        tid = create_template(
            conn, name="Full", channel="email", body_template="Hi {{name}}",
            subject="Subj", variant_group="grp", variant_label="A",
            user_id=TEST_USER_ID,
        )
        row = get_template(conn, tid, user_id=TEST_USER_ID)
        assert row["name"] == "Full"
        assert row["channel"] == "email"
        assert row["body_template"] == "Hi {{name}}"
        assert row["subject"] == "Subj"
        assert row["variant_group"] == "grp"
        assert row["variant_label"] == "A"
        assert row["is_active"] is True

    def test_minimal_fields(self, conn):
        tid = create_template(conn, "Minimal", "linkedin_connect", "Connect msg", user_id=TEST_USER_ID)
        row = get_template(conn, tid, user_id=TEST_USER_ID)
        assert row["subject"] is None
        assert row["variant_group"] is None
        assert row["variant_label"] is None

    def test_user_id_stored(self, conn):
        tid = create_template(conn, "UID T", "email", "body", user_id=TEST_USER_ID)
        with get_cursor(conn) as cur:
            cur.execute("SELECT user_id FROM templates WHERE id = %s", (tid,))
            assert cur.fetchone()["user_id"] == TEST_USER_ID


class TestGetTemplateExtended:
    def test_existing(self, conn, template_id):
        row = get_template(conn, template_id, user_id=TEST_USER_ID)
        assert row is not None
        assert row["name"] == "Welcome Email"

    def test_nonexistent(self, conn):
        assert get_template(conn, 99999, user_id=TEST_USER_ID) is None

    def test_wrong_user(self, conn, template_id, user_b):
        assert get_template(conn, template_id, user_id=OTHER_USER_ID) is None


class TestListTemplatesExtended:
    def test_empty(self, conn):
        assert list_templates(conn, user_id=TEST_USER_ID) == []

    def test_active_only_by_default(self, conn):
        t1 = create_template(conn, "Active", "email", "body", user_id=TEST_USER_ID)
        t2 = create_template(conn, "Inactive", "email", "body", user_id=TEST_USER_ID)
        with get_cursor(conn) as cur:
            cur.execute("UPDATE templates SET is_active = false WHERE id = %s", (t2,))
        conn.commit()
        result = list_templates(conn, user_id=TEST_USER_ID)
        assert len(result) == 1 and result[0]["name"] == "Active"

    def test_list_inactive(self, conn):
        create_template(conn, "Active", "email", "body", user_id=TEST_USER_ID)
        t2 = create_template(conn, "Inactive", "email", "body", user_id=TEST_USER_ID)
        with get_cursor(conn) as cur:
            cur.execute("UPDATE templates SET is_active = false WHERE id = %s", (t2,))
        conn.commit()
        result = list_templates(conn, is_active=False, user_id=TEST_USER_ID)
        assert len(result) == 1 and result[0]["name"] == "Inactive"

    def test_filter_by_channel(self, conn):
        create_template(conn, "E1", "email", "b", user_id=TEST_USER_ID)
        create_template(conn, "L1", "linkedin_connect", "b", user_id=TEST_USER_ID)
        create_template(conn, "E2", "email", "b", user_id=TEST_USER_ID)
        assert len(list_templates(conn, channel="email", user_id=TEST_USER_ID)) == 2
        assert len(list_templates(conn, channel="linkedin_connect", user_id=TEST_USER_ID)) == 1

    def test_channel_and_active_filter(self, conn):
        create_template(conn, "EA", "email", "b", user_id=TEST_USER_ID)
        t2 = create_template(conn, "EI", "email", "b", user_id=TEST_USER_ID)
        create_template(conn, "LA", "linkedin_connect", "b", user_id=TEST_USER_ID)
        with get_cursor(conn) as cur:
            cur.execute("UPDATE templates SET is_active = false WHERE id = %s", (t2,))
        conn.commit()
        result = list_templates(conn, channel="email", is_active=True, user_id=TEST_USER_ID)
        assert len(result) == 1 and result[0]["name"] == "EA"

    def test_user_isolation(self, conn, user_b):
        create_template(conn, "My T", "email", "body", user_id=TEST_USER_ID)
        create_template(conn, "Their T", "email", "body", user_id=OTHER_USER_ID)
        mine = list_templates(conn, user_id=TEST_USER_ID)
        theirs = list_templates(conn, user_id=OTHER_USER_ID)
        assert len(mine) == 1 and mine[0]["name"] == "My T"
        assert len(theirs) == 1 and theirs[0]["name"] == "Their T"


# ===================================================================
# 9. EVENTS (src/models/events.py)
# ===================================================================


class TestLogEventExtended:
    def test_returns_int_id(self, conn, contact_id):
        eid = log_event(conn, contact_id, "email_sent", user_id=TEST_USER_ID)
        assert isinstance(eid, int) and eid > 0

    def test_with_campaign_and_template(self, conn, contact_id, campaign_id, template_id):
        eid = log_event(
            conn, contact_id, "email_sent",
            campaign_id=campaign_id, template_id=template_id,
            user_id=TEST_USER_ID,
        )
        with get_cursor(conn) as cur:
            cur.execute("SELECT * FROM events WHERE id = %s", (eid,))
            row = cur.fetchone()
        assert row["campaign_id"] == campaign_id
        assert row["template_id"] == template_id
        assert row["event_type"] == "email_sent"

    def test_with_metadata(self, conn, contact_id):
        meta = json.dumps({"subject": "Hello", "opened": True})
        eid = log_event(conn, contact_id, "email_opened", metadata=meta, user_id=TEST_USER_ID)
        with get_cursor(conn) as cur:
            cur.execute("SELECT metadata FROM events WHERE id = %s", (eid,))
            assert json.loads(cur.fetchone()["metadata"])["opened"] is True

    def test_without_optional_fields(self, conn, contact_id):
        eid = log_event(conn, contact_id, "page_visit", user_id=TEST_USER_ID)
        with get_cursor(conn) as cur:
            cur.execute("SELECT * FROM events WHERE id = %s", (eid,))
            row = cur.fetchone()
        assert row["campaign_id"] is None
        assert row["template_id"] is None
        assert row["metadata"] is None

    def test_created_at_populated(self, conn, contact_id):
        eid = log_event(conn, contact_id, "email_sent", user_id=TEST_USER_ID)
        with get_cursor(conn) as cur:
            cur.execute("SELECT created_at FROM events WHERE id = %s", (eid,))
            assert cur.fetchone()["created_at"] is not None

    def test_user_id_stored(self, conn, contact_id):
        eid = log_event(conn, contact_id, "email_sent", user_id=TEST_USER_ID)
        with get_cursor(conn) as cur:
            cur.execute("SELECT user_id FROM events WHERE id = %s", (eid,))
            assert cur.fetchone()["user_id"] == TEST_USER_ID

    def test_various_event_types(self, conn, contact_id):
        types = [
            "email_sent", "email_opened", "email_bounced",
            "linkedin_connect_sent", "linkedin_message_sent",
            "reply_received", "unsubscribed",
        ]
        ids = []
        for et in types:
            ids.append(log_event(conn, contact_id, et, user_id=TEST_USER_ID))
        assert len(set(ids)) == len(types), "Each event should get a unique id"

    def test_multiple_events_per_contact(self, conn, contact_id, campaign_id):
        e1 = log_event(conn, contact_id, "email_sent", campaign_id=campaign_id, user_id=TEST_USER_ID)
        e2 = log_event(conn, contact_id, "email_opened", campaign_id=campaign_id, user_id=TEST_USER_ID)
        e3 = log_event(conn, contact_id, "reply_received", campaign_id=campaign_id, user_id=TEST_USER_ID)
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM events WHERE contact_id = %s AND campaign_id = %s",
                (contact_id, campaign_id),
            )
            assert cur.fetchone()["cnt"] == 3


# ===================================================================
# 10. APPLICATION: apply_cross_campaign_email_dedup
# ===================================================================


class TestApplyCrossCampaignEmailDedup:
    def test_empty_list(self):
        assert apply_cross_campaign_email_dedup([]) == []

    def test_no_email_items_unchanged(self):
        items = [
            {"contact_id": 1, "channel": "linkedin_connect"},
            {"contact_id": 2, "channel": "linkedin_message"},
        ]
        result = apply_cross_campaign_email_dedup(items)
        assert len(result) == 2
        assert result[0]["channel"] == "linkedin_connect"
        assert result[1]["channel"] == "linkedin_message"

    def test_single_email_unchanged(self):
        items = [{"contact_id": 1, "channel": "email"}]
        result = apply_cross_campaign_email_dedup(items)
        assert result[0]["channel"] == "email"
        assert "email_dedup_override" not in result[0]

    def test_duplicate_email_overridden(self):
        items = [
            {"contact_id": 1, "channel": "email"},
            {"contact_id": 1, "channel": "email"},
        ]
        result = apply_cross_campaign_email_dedup(items)
        assert result[0]["channel"] == "email"
        assert result[1]["channel"] == "linkedin_only"
        assert result[1]["email_dedup_override"] is True

    def test_different_contacts_not_deduped(self):
        items = [
            {"contact_id": 1, "channel": "email"},
            {"contact_id": 2, "channel": "email"},
        ]
        result = apply_cross_campaign_email_dedup(items)
        assert result[0]["channel"] == "email"
        assert result[1]["channel"] == "email"

    def test_triple_duplicate(self):
        items = [
            {"contact_id": 5, "channel": "email"},
            {"contact_id": 5, "channel": "email"},
            {"contact_id": 5, "channel": "email"},
        ]
        result = apply_cross_campaign_email_dedup(items)
        assert result[0]["channel"] == "email"
        assert result[1]["channel"] == "linkedin_only"
        assert result[2]["channel"] == "linkedin_only"

    def test_mixed_channels(self):
        items = [
            {"contact_id": 1, "channel": "linkedin_connect"},
            {"contact_id": 1, "channel": "email"},
            {"contact_id": 2, "channel": "email"},
            {"contact_id": 1, "channel": "email"},
        ]
        result = apply_cross_campaign_email_dedup(items)
        assert result[0]["channel"] == "linkedin_connect"  # not email, untouched
        assert result[1]["channel"] == "email"              # first email for contact 1
        assert result[2]["channel"] == "email"              # first email for contact 2
        assert result[3]["channel"] == "linkedin_only"      # dup email for contact 1

    def test_limit_truncates(self):
        items = [
            {"contact_id": i, "channel": "email"}
            for i in range(10)
        ]
        result = apply_cross_campaign_email_dedup(items, limit=3)
        assert len(result) == 3

    def test_limit_zero_no_truncation(self):
        items = [
            {"contact_id": i, "channel": "email"}
            for i in range(5)
        ]
        result = apply_cross_campaign_email_dedup(items, limit=0)
        assert len(result) == 5

    def test_limit_with_dedup(self):
        items = [
            {"contact_id": 1, "channel": "email"},
            {"contact_id": 1, "channel": "email"},
            {"contact_id": 2, "channel": "email"},
            {"contact_id": 2, "channel": "email"},
        ]
        result = apply_cross_campaign_email_dedup(items, limit=3)
        assert len(result) == 3
        assert result[0]["channel"] == "email"
        assert result[1]["channel"] == "linkedin_only"
        assert result[2]["channel"] == "email"

    def test_preserves_extra_fields(self):
        items = [{"contact_id": 1, "channel": "email", "company": "Acme", "aum": 500}]
        result = apply_cross_campaign_email_dedup(items)
        assert result[0]["company"] == "Acme"
        assert result[0]["aum"] == 500

    def test_mutates_in_place(self):
        """The function modifies items in-place (not copies)."""
        items = [
            {"contact_id": 1, "channel": "email"},
            {"contact_id": 1, "channel": "email"},
        ]
        result = apply_cross_campaign_email_dedup(items)
        # The original second item is now mutated
        assert items[1]["channel"] == "linkedin_only"


# ===================================================================
# 11. APPLICATION: send_email_batch
# ===================================================================


class TestSendEmailBatch:
    def test_empty_batch(self, conn):
        result = send_email_batch(conn, [], {}, user_id=TEST_USER_ID)
        assert result == {"sent": 0, "failed": 0, "errors": []}

    @patch("src.application.queue_service.send_campaign_email")
    def test_all_succeed(self, mock_send, conn):
        mock_send.return_value = True
        rows = [
            {"contact_id": 1, "campaign_id": 1, "template_id": 1},
            {"contact_id": 2, "campaign_id": 1, "template_id": 1},
        ]
        result = send_email_batch(conn, rows, {"smtp": {}}, user_id=TEST_USER_ID)
        assert result["sent"] == 2
        assert result["failed"] == 0
        assert result["errors"] == []
        assert mock_send.call_count == 2

    @patch("src.application.queue_service.send_campaign_email")
    def test_all_fail_return_false(self, mock_send, conn):
        mock_send.return_value = False
        rows = [
            {"contact_id": 1, "campaign_id": 1, "template_id": 1},
            {"contact_id": 2, "campaign_id": 1, "template_id": 1},
        ]
        result = send_email_batch(conn, rows, {"smtp": {}}, user_id=TEST_USER_ID)
        assert result["sent"] == 0
        assert result["failed"] == 2
        assert len(result["errors"]) == 2

    @patch("src.application.queue_service.send_campaign_email")
    def test_exception_counted_as_failure(self, mock_send, conn):
        mock_send.side_effect = RuntimeError("SMTP down")
        rows = [{"contact_id": 1, "campaign_id": 1, "template_id": 1}]
        result = send_email_batch(conn, rows, {"smtp": {}}, user_id=TEST_USER_ID)
        assert result["sent"] == 0
        assert result["failed"] == 1
        assert "SMTP down" in result["errors"][0]

    @patch("src.application.queue_service.send_campaign_email")
    def test_mixed_success_and_failure(self, mock_send, conn):
        mock_send.side_effect = [True, False, RuntimeError("timeout"), True]
        rows = [
            {"contact_id": i, "campaign_id": 1, "template_id": 1}
            for i in range(4)
        ]
        result = send_email_batch(conn, rows, {"smtp": {}}, user_id=TEST_USER_ID)
        assert result["sent"] == 2
        assert result["failed"] == 2
        assert len(result["errors"]) == 2

    @patch("src.application.queue_service.send_campaign_email")
    def test_user_id_passed_through(self, mock_send, conn):
        mock_send.return_value = True
        rows = [{"contact_id": 1, "campaign_id": 1, "template_id": 1}]
        send_email_batch(conn, rows, {"smtp": {}}, user_id=42)
        _, kwargs = mock_send.call_args
        assert kwargs["user_id"] == 42

    @patch("src.application.queue_service.send_campaign_email")
    def test_per_row_user_id_when_no_kwarg(self, mock_send, conn):
        mock_send.return_value = True
        rows = [
            {"contact_id": 1, "campaign_id": 1, "template_id": 1, "user_id": 77},
            {"contact_id": 2, "campaign_id": 1, "template_id": 1, "user_id": 88},
        ]
        send_email_batch(conn, rows, {"smtp": {}})
        calls = mock_send.call_args_list
        assert calls[0][1]["user_id"] == 77
        assert calls[1][1]["user_id"] == 88

    @patch("src.application.queue_service.send_campaign_email")
    def test_config_passed_through(self, mock_send, conn):
        mock_send.return_value = True
        cfg = {"smtp": {"host": "mail.example.com"}}
        rows = [{"contact_id": 1, "campaign_id": 1, "template_id": 1}]
        send_email_batch(conn, rows, cfg, user_id=TEST_USER_ID)
        args = mock_send.call_args[0]
        assert args[4] == cfg  # config is 5th positional arg


# ===================================================================
# 12. MULTI-TENANCY CROSS-CUTTING (verifying user_id scoping)
# ===================================================================


class TestMultiTenancyCrossCutting:
    """Verify user_id scoping across all core model functions."""

    def test_campaign_invisible_to_other_user(self, conn, campaign_id, user_b):
        assert get_campaign(conn, campaign_id, user_id=OTHER_USER_ID) is None
        assert get_campaign_by_name(conn, "Test Campaign", user_id=OTHER_USER_ID) is None
        assert list_campaigns(conn, user_id=OTHER_USER_ID) == []

    def test_template_invisible_to_other_user(self, conn, template_id, user_b):
        assert get_template(conn, template_id, user_id=OTHER_USER_ID) is None
        assert list_templates(conn, user_id=OTHER_USER_ID) == []

    def test_sequence_step_blocked_for_other_user(self, conn, campaign_id, user_b):
        add_sequence_step(conn, campaign_id, 1, "email", user_id=TEST_USER_ID)
        # Other user cannot read steps
        assert get_sequence_steps(conn, campaign_id, user_id=OTHER_USER_ID) == []
        # Other user cannot add steps
        with pytest.raises(PermissionError):
            add_sequence_step(conn, campaign_id, 2, "linkedin_connect", user_id=OTHER_USER_ID)

    def test_enrollment_blocked_for_other_user(self, conn, contact_id, campaign_id, user_b):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert get_contact_campaign_status(conn, contact_id, campaign_id, user_id=OTHER_USER_ID) is None

    def test_bulk_enroll_blocked_for_other_user(self, conn, five_contacts, campaign_id, user_b):
        with pytest.raises(PermissionError):
            bulk_enroll_contacts(conn, campaign_id, five_contacts, user_id=OTHER_USER_ID)

    def test_status_update_blocked_for_other_user(self, conn, contact_id, campaign_id, user_b):
        enroll_contact(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        update_contact_campaign_status(conn, contact_id, campaign_id, status="completed", user_id=OTHER_USER_ID)
        row = get_contact_campaign_status(conn, contact_id, campaign_id, user_id=TEST_USER_ID)
        assert row["status"] == "queued"  # unchanged

    def test_message_draft_invisible_to_other_user(self, conn, contact_id, campaign_id, user_b):
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO message_drafts
                   (contact_id, campaign_id, step_order, draft_text, channel, user_id)
                   VALUES (%s, %s, 1, 'private', 'email', %s)""",
                (contact_id, campaign_id, TEST_USER_ID),
            )
        conn.commit()
        assert get_message_draft(conn, contact_id, campaign_id, 1, user_id=OTHER_USER_ID) is None

    def test_events_carry_correct_user_id(self, conn, contact_id, user_b):
        e1 = log_event(conn, contact_id, "email_sent", user_id=TEST_USER_ID)
        with get_cursor(conn) as cur:
            cur.execute("SELECT user_id FROM events WHERE id = %s", (e1,))
            assert cur.fetchone()["user_id"] == TEST_USER_ID


# ===================================================================
# 13. INTEGRATION: Full campaign workflow
# ===================================================================


class TestFullCampaignWorkflow:
    """End-to-end test: create campaign, templates, steps, enroll, update, log."""

    def test_complete_lifecycle(self, conn, company_id):
        # 1. Create campaign
        cid = create_campaign(conn, "Lifecycle", description="e2e", user_id=TEST_USER_ID)

        # 2. Create templates
        t_li = create_template(conn, "LI Tmpl", "linkedin_connect", "Hi!", user_id=TEST_USER_ID)
        t_em = create_template(conn, "EM Tmpl", "email", "Follow up", subject="FU", user_id=TEST_USER_ID)

        # 3. Add sequence
        add_sequence_step(conn, cid, 1, "linkedin_connect", template_id=t_li, user_id=TEST_USER_ID)
        add_sequence_step(conn, cid, 2, "email", template_id=t_em, delay_days=3, user_id=TEST_USER_ID)
        assert len(get_sequence_steps(conn, cid, user_id=TEST_USER_ID)) == 2

        # 4. Create and enroll contacts
        contacts = [insert_contact(conn, company_id, first_name=f"E2E_{i}") for i in range(3)]
        enrolled = bulk_enroll_contacts(
            conn, cid, contacts,
            variant_assigner=lambda c: "A" if c % 2 == 0 else "B",
            user_id=TEST_USER_ID,
        )
        assert enrolled == 3

        # 5. Progress first contact
        update_contact_campaign_status(conn, contacts[0], cid, status="in_progress", current_step=1, user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contacts[0], cid, user_id=TEST_USER_ID)
        assert row["status"] == "in_progress"

        # 6. Log event
        eid = log_event(conn, contacts[0], "linkedin_connect_sent", campaign_id=cid, template_id=t_li, user_id=TEST_USER_ID)
        assert eid > 0

        # 7. Record template usage
        record_template_usage(conn, contacts[0], cid, t_li, "linkedin_connect")

        # 8. Advance to step 2
        update_contact_campaign_status(conn, contacts[0], cid, current_step=2, user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contacts[0], cid, user_id=TEST_USER_ID)
        assert row["current_step"] == 2

        # 9. Complete
        update_contact_campaign_status(conn, contacts[0], cid, status="completed", user_id=TEST_USER_ID)
        row = get_contact_campaign_status(conn, contacts[0], cid, user_id=TEST_USER_ID)
        assert row["status"] == "completed"

        # 10. Pause campaign
        update_campaign_status(conn, cid, "paused", user_id=TEST_USER_ID)
        assert get_campaign(conn, cid, user_id=TEST_USER_ID)["status"] == "paused"

    def test_dedup_then_batch_send(self, conn):
        """Integration: dedup a queue then pass to send_email_batch."""
        items = [
            {"contact_id": 1, "campaign_id": 10, "template_id": 5, "channel": "email"},
            {"contact_id": 1, "campaign_id": 20, "template_id": 6, "channel": "email"},
            {"contact_id": 2, "campaign_id": 10, "template_id": 5, "channel": "email"},
        ]
        deduped = apply_cross_campaign_email_dedup(items)
        email_rows = [r for r in deduped if r["channel"] == "email"]
        assert len(email_rows) == 2  # contact 1 campaign 10 + contact 2

        with patch("src.application.queue_service.send_campaign_email", return_value=True):
            result = send_email_batch(conn, email_rows, {"smtp": {}}, user_id=TEST_USER_ID)
        assert result["sent"] == 2
