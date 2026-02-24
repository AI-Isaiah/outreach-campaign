"""Comprehensive tests for src/models/campaigns.py CRUD operations."""

import json
import sqlite3
import pytest

from src.models.database import get_connection, run_migrations
from src.models.campaigns import (
    create_campaign,
    get_campaign,
    get_campaign_by_name,
    list_campaigns,
    update_campaign_status,
    create_template,
    get_template,
    list_templates,
    add_sequence_step,
    get_sequence_steps,
    enroll_contact,
    bulk_enroll_contacts,
    get_contact_campaign_status,
    update_contact_campaign_status,
    log_event,
)


@pytest.fixture
def conn(tmp_db):
    """Return a connection with all tables created."""
    connection = get_connection(tmp_db)
    run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def sample_campaign(conn):
    """Create and return a sample campaign id."""
    return create_campaign(conn, "Q1 Outreach", description="First quarter campaign")


@pytest.fixture
def sample_template(conn):
    """Create and return a sample email template id."""
    return create_template(
        conn,
        name="Intro Email v1",
        channel="email",
        body_template="Hello {{first_name}}, we'd like to connect.",
        subject="Introduction from our fund",
    )


@pytest.fixture
def sample_contact(conn):
    """Insert a minimal contact row and return its id."""
    cursor = conn.execute(
        "INSERT INTO contacts (first_name, last_name, email, source) VALUES (?, ?, ?, ?)",
        ("Alice", "Smith", "alice@example.com", "csv"),
    )
    conn.commit()
    return cursor.lastrowid


@pytest.fixture
def multiple_contacts(conn):
    """Insert several contacts and return their ids."""
    ids = []
    for i in range(5):
        cursor = conn.execute(
            "INSERT INTO contacts (first_name, last_name, email, source) VALUES (?, ?, ?, ?)",
            (f"User{i}", f"Last{i}", f"user{i}@example.com", "csv"),
        )
        ids.append(cursor.lastrowid)
    conn.commit()
    return ids


# ===================================================================
# Campaign CRUD
# ===================================================================

class TestCreateCampaign:
    def test_basic_creation(self, conn):
        cid = create_campaign(conn, "Test Campaign")
        assert isinstance(cid, int)
        assert cid > 0

    def test_with_description(self, conn):
        cid = create_campaign(conn, "Described Campaign", description="A description")
        row = get_campaign(conn, cid)
        assert row["description"] == "A description"

    def test_without_description(self, conn):
        cid = create_campaign(conn, "No Desc")
        row = get_campaign(conn, cid)
        assert row["description"] is None

    def test_default_status_is_active(self, conn):
        cid = create_campaign(conn, "Default Status")
        row = get_campaign(conn, cid)
        assert row["status"] == "active"

    def test_created_at_populated(self, conn):
        cid = create_campaign(conn, "Timestamp Test")
        row = get_campaign(conn, cid)
        assert row["created_at"] is not None

    def test_duplicate_name_raises(self, conn):
        create_campaign(conn, "Unique Name")
        with pytest.raises(sqlite3.IntegrityError):
            create_campaign(conn, "Unique Name")


class TestGetCampaign:
    def test_existing(self, conn, sample_campaign):
        row = get_campaign(conn, sample_campaign)
        assert row is not None
        assert row["id"] == sample_campaign
        assert row["name"] == "Q1 Outreach"

    def test_nonexistent(self, conn):
        row = get_campaign(conn, 99999)
        assert row is None


class TestGetCampaignByName:
    def test_existing(self, conn, sample_campaign):
        row = get_campaign_by_name(conn, "Q1 Outreach")
        assert row is not None
        assert row["id"] == sample_campaign

    def test_nonexistent(self, conn):
        row = get_campaign_by_name(conn, "Nonexistent")
        assert row is None


class TestListCampaigns:
    def test_empty(self, conn):
        assert list_campaigns(conn) == []

    def test_returns_all(self, conn):
        create_campaign(conn, "C1")
        create_campaign(conn, "C2")
        create_campaign(conn, "C3")
        result = list_campaigns(conn)
        assert len(result) == 3

    def test_filter_by_status(self, conn):
        c1 = create_campaign(conn, "Active1")
        c2 = create_campaign(conn, "Active2")
        c3 = create_campaign(conn, "Paused1")
        update_campaign_status(conn, c3, "paused")

        active = list_campaigns(conn, status="active")
        assert len(active) == 2
        paused = list_campaigns(conn, status="paused")
        assert len(paused) == 1
        assert paused[0]["name"] == "Paused1"

    def test_filter_no_match(self, conn):
        create_campaign(conn, "Active")
        result = list_campaigns(conn, status="completed")
        assert result == []


class TestUpdateCampaignStatus:
    def test_update(self, conn, sample_campaign):
        update_campaign_status(conn, sample_campaign, "paused")
        row = get_campaign(conn, sample_campaign)
        assert row["status"] == "paused"

    def test_update_to_completed(self, conn, sample_campaign):
        update_campaign_status(conn, sample_campaign, "completed")
        row = get_campaign(conn, sample_campaign)
        assert row["status"] == "completed"


# ===================================================================
# Template CRUD
# ===================================================================

class TestCreateTemplate:
    def test_basic(self, conn):
        tid = create_template(conn, "Tmpl1", "email", "Body here")
        assert isinstance(tid, int)
        assert tid > 0

    def test_all_fields(self, conn):
        tid = create_template(
            conn,
            name="Full Template",
            channel="email",
            body_template="Hello {{name}}",
            subject="Intro",
            variant_group="welcome",
            variant_label="A",
        )
        row = get_template(conn, tid)
        assert row["name"] == "Full Template"
        assert row["channel"] == "email"
        assert row["body_template"] == "Hello {{name}}"
        assert row["subject"] == "Intro"
        assert row["variant_group"] == "welcome"
        assert row["variant_label"] == "A"
        assert row["is_active"] == 1

    def test_linkedin_channel(self, conn):
        tid = create_template(conn, "LI Connect", "linkedin_connect", "Hi, let's connect")
        row = get_template(conn, tid)
        assert row["channel"] == "linkedin_connect"


class TestGetTemplate:
    def test_existing(self, conn, sample_template):
        row = get_template(conn, sample_template)
        assert row is not None
        assert row["name"] == "Intro Email v1"

    def test_nonexistent(self, conn):
        row = get_template(conn, 99999)
        assert row is None


class TestListTemplates:
    def test_empty(self, conn):
        assert list_templates(conn) == []

    def test_returns_active_only_by_default(self, conn):
        t1 = create_template(conn, "Active", "email", "body")
        t2 = create_template(conn, "Inactive", "email", "body")
        # Deactivate t2
        conn.execute("UPDATE templates SET is_active = 0 WHERE id = ?", (t2,))
        conn.commit()

        result = list_templates(conn)
        assert len(result) == 1
        assert result[0]["name"] == "Active"

    def test_list_inactive(self, conn):
        t1 = create_template(conn, "Active", "email", "body")
        t2 = create_template(conn, "Inactive", "email", "body")
        conn.execute("UPDATE templates SET is_active = 0 WHERE id = ?", (t2,))
        conn.commit()

        result = list_templates(conn, is_active=False)
        assert len(result) == 1
        assert result[0]["name"] == "Inactive"

    def test_filter_by_channel(self, conn):
        create_template(conn, "Email1", "email", "body")
        create_template(conn, "LI1", "linkedin_connect", "body")
        create_template(conn, "Email2", "email", "body")

        emails = list_templates(conn, channel="email")
        assert len(emails) == 2

        li = list_templates(conn, channel="linkedin_connect")
        assert len(li) == 1

    def test_filter_by_channel_and_active(self, conn):
        t1 = create_template(conn, "Email Active", "email", "body")
        t2 = create_template(conn, "Email Inactive", "email", "body")
        t3 = create_template(conn, "LI Active", "linkedin_connect", "body")
        conn.execute("UPDATE templates SET is_active = 0 WHERE id = ?", (t2,))
        conn.commit()

        result = list_templates(conn, channel="email", is_active=True)
        assert len(result) == 1
        assert result[0]["name"] == "Email Active"


# ===================================================================
# Sequence Steps
# ===================================================================

class TestAddSequenceStep:
    def test_basic(self, conn, sample_campaign):
        sid = add_sequence_step(conn, sample_campaign, 1, "linkedin_connect")
        assert isinstance(sid, int)
        assert sid > 0

    def test_with_all_params(self, conn, sample_campaign, sample_template):
        sid = add_sequence_step(
            conn,
            sample_campaign,
            1,
            "email",
            template_id=sample_template,
            delay_days=3,
            gdpr_only=True,
            non_gdpr_only=False,
        )
        steps = get_sequence_steps(conn, sample_campaign)
        assert len(steps) == 1
        step = steps[0]
        assert step["channel"] == "email"
        assert step["template_id"] == sample_template
        assert step["delay_days"] == 3
        assert step["gdpr_only"] == 1
        assert step["non_gdpr_only"] == 0

    def test_duplicate_step_order_raises(self, conn, sample_campaign):
        add_sequence_step(conn, sample_campaign, 1, "email")
        with pytest.raises(sqlite3.IntegrityError):
            add_sequence_step(conn, sample_campaign, 1, "linkedin_connect")

    def test_same_step_order_different_campaign(self, conn):
        c1 = create_campaign(conn, "Campaign A")
        c2 = create_campaign(conn, "Campaign B")
        s1 = add_sequence_step(conn, c1, 1, "email")
        s2 = add_sequence_step(conn, c2, 1, "email")
        assert s1 != s2


class TestGetSequenceSteps:
    def test_empty(self, conn, sample_campaign):
        assert get_sequence_steps(conn, sample_campaign) == []

    def test_ordered_by_step_order(self, conn, sample_campaign):
        add_sequence_step(conn, sample_campaign, 3, "email", delay_days=7)
        add_sequence_step(conn, sample_campaign, 1, "linkedin_connect", delay_days=0)
        add_sequence_step(conn, sample_campaign, 2, "linkedin_message", delay_days=3)

        steps = get_sequence_steps(conn, sample_campaign)
        assert len(steps) == 3
        assert [s["step_order"] for s in steps] == [1, 2, 3]
        assert [s["channel"] for s in steps] == [
            "linkedin_connect",
            "linkedin_message",
            "email",
        ]

    def test_only_returns_for_given_campaign(self, conn):
        c1 = create_campaign(conn, "C1")
        c2 = create_campaign(conn, "C2")
        add_sequence_step(conn, c1, 1, "email")
        add_sequence_step(conn, c2, 1, "email")
        add_sequence_step(conn, c2, 2, "linkedin_connect")

        assert len(get_sequence_steps(conn, c1)) == 1
        assert len(get_sequence_steps(conn, c2)) == 2


# ===================================================================
# Contact Campaign Enrollment
# ===================================================================

class TestEnrollContact:
    def test_basic(self, conn, sample_contact, sample_campaign):
        eid = enroll_contact(conn, sample_contact, sample_campaign)
        assert isinstance(eid, int)
        assert eid > 0

    def test_with_variant(self, conn, sample_contact, sample_campaign):
        eid = enroll_contact(conn, sample_contact, sample_campaign, variant="A")
        row = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        assert row["assigned_variant"] == "A"

    def test_with_next_action_date(self, conn, sample_contact, sample_campaign):
        eid = enroll_contact(
            conn, sample_contact, sample_campaign,
            next_action_date="2026-03-01",
        )
        row = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        assert row["next_action_date"] == "2026-03-01"

    def test_default_status_queued(self, conn, sample_contact, sample_campaign):
        enroll_contact(conn, sample_contact, sample_campaign)
        row = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        assert row["status"] == "queued"
        assert row["current_step"] == 0

    def test_duplicate_returns_none(self, conn, sample_contact, sample_campaign):
        eid1 = enroll_contact(conn, sample_contact, sample_campaign)
        eid2 = enroll_contact(conn, sample_contact, sample_campaign)
        assert eid1 is not None
        assert eid2 is None

    def test_same_contact_different_campaigns(self, conn, sample_contact):
        c1 = create_campaign(conn, "Camp1")
        c2 = create_campaign(conn, "Camp2")
        e1 = enroll_contact(conn, sample_contact, c1)
        e2 = enroll_contact(conn, sample_contact, c2)
        assert e1 is not None
        assert e2 is not None
        assert e1 != e2


class TestBulkEnrollContacts:
    def test_basic(self, conn, sample_campaign, multiple_contacts):
        count = bulk_enroll_contacts(conn, sample_campaign, multiple_contacts)
        assert count == 5

    def test_skips_already_enrolled(self, conn, sample_campaign, multiple_contacts):
        # Enroll first two individually
        enroll_contact(conn, multiple_contacts[0], sample_campaign)
        enroll_contact(conn, multiple_contacts[1], sample_campaign)

        count = bulk_enroll_contacts(conn, sample_campaign, multiple_contacts)
        assert count == 3  # only the remaining 3

    def test_with_variant_assigner(self, conn, sample_campaign, multiple_contacts):
        def assigner(cid):
            return "A" if cid % 2 == 0 else "B"

        count = bulk_enroll_contacts(
            conn, sample_campaign, multiple_contacts, variant_assigner=assigner,
        )
        assert count == 5

        for cid in multiple_contacts:
            row = get_contact_campaign_status(conn, cid, sample_campaign)
            expected = "A" if cid % 2 == 0 else "B"
            assert row["assigned_variant"] == expected

    def test_empty_list(self, conn, sample_campaign):
        count = bulk_enroll_contacts(conn, sample_campaign, [])
        assert count == 0

    def test_all_already_enrolled(self, conn, sample_campaign, multiple_contacts):
        bulk_enroll_contacts(conn, sample_campaign, multiple_contacts)
        count = bulk_enroll_contacts(conn, sample_campaign, multiple_contacts)
        assert count == 0

    def test_no_variant_assigner(self, conn, sample_campaign, multiple_contacts):
        bulk_enroll_contacts(conn, sample_campaign, multiple_contacts)
        for cid in multiple_contacts:
            row = get_contact_campaign_status(conn, cid, sample_campaign)
            assert row["assigned_variant"] is None


class TestGetContactCampaignStatus:
    def test_enrolled(self, conn, sample_contact, sample_campaign):
        enroll_contact(conn, sample_contact, sample_campaign)
        row = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        assert row is not None
        assert row["contact_id"] == sample_contact
        assert row["campaign_id"] == sample_campaign

    def test_not_enrolled(self, conn, sample_contact, sample_campaign):
        row = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        assert row is None


class TestUpdateContactCampaignStatus:
    def test_update_status(self, conn, sample_contact, sample_campaign):
        enroll_contact(conn, sample_contact, sample_campaign)
        update_contact_campaign_status(
            conn, sample_contact, sample_campaign, status="in_progress",
        )
        row = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        assert row["status"] == "in_progress"

    def test_update_current_step(self, conn, sample_contact, sample_campaign):
        enroll_contact(conn, sample_contact, sample_campaign)
        update_contact_campaign_status(
            conn, sample_contact, sample_campaign, current_step=2,
        )
        row = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        assert row["current_step"] == 2

    def test_update_next_action_date(self, conn, sample_contact, sample_campaign):
        enroll_contact(conn, sample_contact, sample_campaign)
        update_contact_campaign_status(
            conn, sample_contact, sample_campaign,
            next_action_date="2026-04-01",
        )
        row = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        assert row["next_action_date"] == "2026-04-01"

    def test_update_multiple_fields(self, conn, sample_contact, sample_campaign):
        enroll_contact(conn, sample_contact, sample_campaign)
        update_contact_campaign_status(
            conn, sample_contact, sample_campaign,
            status="replied_positive",
            current_step=3,
            next_action_date="2026-05-01",
        )
        row = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        assert row["status"] == "replied_positive"
        assert row["current_step"] == 3
        assert row["next_action_date"] == "2026-05-01"

    def test_updated_at_changes(self, conn, sample_contact, sample_campaign):
        enroll_contact(conn, sample_contact, sample_campaign)
        row_before = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        original_updated = row_before["updated_at"]

        update_contact_campaign_status(
            conn, sample_contact, sample_campaign, status="in_progress",
        )
        row_after = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        # updated_at should be refreshed (or at least not older)
        assert row_after["updated_at"] >= original_updated

    def test_no_op_when_no_fields(self, conn, sample_contact, sample_campaign):
        enroll_contact(conn, sample_contact, sample_campaign)
        # Calling with no optional args should not raise
        update_contact_campaign_status(conn, sample_contact, sample_campaign)
        row = get_contact_campaign_status(conn, sample_contact, sample_campaign)
        assert row["status"] == "queued"  # unchanged


# ===================================================================
# Events
# ===================================================================

class TestLogEvent:
    def test_basic(self, conn, sample_contact):
        eid = log_event(conn, sample_contact, "email_sent")
        assert isinstance(eid, int)
        assert eid > 0

    def test_with_campaign_and_template(
        self, conn, sample_contact, sample_campaign, sample_template
    ):
        eid = log_event(
            conn,
            sample_contact,
            "email_sent",
            campaign_id=sample_campaign,
            template_id=sample_template,
        )
        row = conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
        assert row["contact_id"] == sample_contact
        assert row["campaign_id"] == sample_campaign
        assert row["template_id"] == sample_template
        assert row["event_type"] == "email_sent"

    def test_with_metadata(self, conn, sample_contact):
        meta = json.dumps({"subject": "Hello", "opened": True})
        eid = log_event(conn, sample_contact, "email_opened", metadata=meta)
        row = conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
        assert row["metadata"] == meta
        parsed = json.loads(row["metadata"])
        assert parsed["opened"] is True

    def test_without_optional_fields(self, conn, sample_contact):
        eid = log_event(conn, sample_contact, "page_visit")
        row = conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
        assert row["campaign_id"] is None
        assert row["template_id"] is None
        assert row["metadata"] is None

    def test_created_at_populated(self, conn, sample_contact):
        eid = log_event(conn, sample_contact, "email_sent")
        row = conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
        assert row["created_at"] is not None


# ===================================================================
# Integration / Cross-function Tests
# ===================================================================

class TestIntegration:
    def test_full_campaign_workflow(self, conn, multiple_contacts):
        """Test creating a campaign, adding steps, enrolling contacts, and logging events."""
        # 1. Create campaign
        cid = create_campaign(conn, "Full Workflow", description="End-to-end test")

        # 2. Create templates
        t1 = create_template(conn, "LI Connect", "linkedin_connect", "Hi {{name}}")
        t2 = create_template(
            conn, "Follow-up Email", "email", "Following up...",
            subject="Following up",
        )

        # 3. Add sequence steps
        add_sequence_step(conn, cid, 1, "linkedin_connect", template_id=t1, delay_days=0)
        add_sequence_step(conn, cid, 2, "email", template_id=t2, delay_days=3)

        steps = get_sequence_steps(conn, cid)
        assert len(steps) == 2
        assert steps[0]["channel"] == "linkedin_connect"
        assert steps[1]["channel"] == "email"

        # 4. Bulk enroll with variant assigner
        def ab_assigner(cid):
            return "A" if cid % 2 == 0 else "B"

        enrolled = bulk_enroll_contacts(conn, cid, multiple_contacts, ab_assigner)
        assert enrolled == 5

        # 5. Update status for first contact
        contact = multiple_contacts[0]
        update_contact_campaign_status(
            conn, contact, cid,
            status="in_progress", current_step=1,
        )
        row = get_contact_campaign_status(conn, contact, cid)
        assert row["status"] == "in_progress"
        assert row["current_step"] == 1

        # 6. Log events
        eid = log_event(
            conn, contact, "linkedin_connect_sent",
            campaign_id=cid, template_id=t1,
        )
        assert eid > 0

        # 7. Pause campaign
        update_campaign_status(conn, cid, "paused")
        camp = get_campaign(conn, cid)
        assert camp["status"] == "paused"

    def test_row_access_by_key(self, conn):
        """Verify that returned rows support dict-like key access (sqlite3.Row)."""
        cid = create_campaign(conn, "Key Access Test")
        row = get_campaign(conn, cid)
        # Access by key
        assert row["name"] == "Key Access Test"
        assert row["status"] == "active"
        # Access by index
        assert row[0] == cid
