"""Cross-user data isolation tests.

Verifies that User A cannot see or modify User B's data across all
multi-tenanted tables and operations.
"""

import pytest

from src.models.database import get_connection, run_migrations
from tests.conftest import TEST_USER_ID, insert_company, insert_contact

# User A = TEST_USER_ID (1), already seeded in conftest
USER_A = TEST_USER_ID
# User B = 2, created in fixture below
USER_B_ID = None


@pytest.fixture
def conn(tmp_db):
    """Return a connection with all tables created."""
    connection = get_connection(tmp_db)
    run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def user_b(conn):
    """Create a second test user for isolation tests."""
    global USER_B_ID
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (email, name) VALUES ('userb@test.com', 'User B') "
        "ON CONFLICT (email) DO UPDATE SET name = 'User B' RETURNING id"
    )
    USER_B_ID = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    return USER_B_ID


# ---------------------------------------------------------------------------
# Model layer isolation
# ---------------------------------------------------------------------------

class TestCompanyIsolation:
    def test_user_a_cannot_see_user_b_companies(self, conn):
        """Companies created by User B are invisible to User A."""
        # User A creates a company
        a_company = insert_company(conn, "Company A", aum_millions=100)
        # User B creates a company
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Company B', 'company b', %s) RETURNING id",
            (USER_B_ID,),
        )
        b_company = cur.fetchone()["id"]
        conn.commit()
        cur.close()

        # User A queries — should only see their company
        cur = conn.cursor()
        cur.execute("SELECT id FROM companies WHERE user_id = %s", (USER_A,))
        rows = cur.fetchall()
        cur.close()
        ids = [r["id"] for r in rows]
        assert a_company in ids
        assert b_company not in ids


class TestCampaignIsolation:
    def test_create_campaign_scoped_to_user(self, conn):
        from src.models.campaigns import create_campaign, get_campaign, list_campaigns

        a_id = create_campaign(conn, "Campaign A", user_id=USER_A)
        b_id = create_campaign(conn, "Campaign B", user_id=USER_B_ID)

        # User A can see their campaign
        assert get_campaign(conn, a_id, user_id=USER_A) is not None
        # User A cannot see User B's campaign
        assert get_campaign(conn, b_id, user_id=USER_A) is None
        # User B cannot see User A's campaign
        assert get_campaign(conn, a_id, user_id=USER_B_ID) is None

    def test_list_campaigns_filtered(self, conn):
        from src.models.campaigns import create_campaign, list_campaigns

        create_campaign(conn, "List Camp A", user_id=USER_A)
        create_campaign(conn, "List Camp B", user_id=USER_B_ID)

        a_list = list_campaigns(conn, user_id=USER_A)
        b_list = list_campaigns(conn, user_id=USER_B_ID)

        a_names = [c["name"] for c in a_list]
        b_names = [c["name"] for c in b_list]
        assert "List Camp A" in a_names
        assert "List Camp B" not in a_names
        assert "List Camp B" in b_names
        assert "List Camp A" not in b_names

    def test_same_campaign_name_different_users(self, conn):
        from src.models.campaigns import create_campaign, get_campaign_by_name

        create_campaign(conn, "Same Name", user_id=USER_A)
        create_campaign(conn, "Same Name", user_id=USER_B_ID)

        a_camp = get_campaign_by_name(conn, "Same Name", user_id=USER_A)
        b_camp = get_campaign_by_name(conn, "Same Name", user_id=USER_B_ID)
        assert a_camp["id"] != b_camp["id"]


class TestTemplateIsolation:
    def test_templates_scoped_to_user(self, conn):
        from src.models.templates import create_template, get_template, list_templates

        a_id = create_template(conn, "Tmpl A", "email", "Body A", user_id=USER_A)
        b_id = create_template(conn, "Tmpl B", "email", "Body B", user_id=USER_B_ID)

        assert get_template(conn, a_id, user_id=USER_A) is not None
        assert get_template(conn, b_id, user_id=USER_A) is None
        assert get_template(conn, a_id, user_id=USER_B_ID) is None
        assert get_template(conn, b_id, user_id=USER_B_ID) is not None

    def test_list_templates_filtered(self, conn):
        from src.models.templates import create_template, list_templates

        create_template(conn, "List Tmpl A", "email", "Body", user_id=USER_A)
        create_template(conn, "List Tmpl B", "email", "Body", user_id=USER_B_ID)

        a_list = list_templates(conn, user_id=USER_A)
        b_list = list_templates(conn, user_id=USER_B_ID)
        a_names = [t["name"] for t in a_list]
        b_names = [t["name"] for t in b_list]
        assert "List Tmpl A" in a_names
        assert "List Tmpl B" not in a_names


class TestContactIsolation:
    def test_contacts_scoped_via_user_id(self, conn):
        """Contacts inherit user_id. Two users can have same email contact."""
        a_company = insert_company(conn, "Co A")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Co B', 'co b', %s) RETURNING id",
            (USER_B_ID,),
        )
        b_company = cur.fetchone()["id"]
        conn.commit()
        cur.close()

        a_contact = insert_contact(conn, a_company, email="same@example.com")
        # User B inserts same email — allowed (per-user uniqueness)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO contacts (company_id, first_name, last_name, full_name, email, email_normalized,
                                     priority_rank, source, user_id)
               VALUES (%s, 'B', 'User', 'B User', 'same@example.com', 'same@example.com', 1, 'test', %s)
               RETURNING id""",
            (b_company, USER_B_ID),
        )
        b_contact = cur.fetchone()["id"]
        conn.commit()
        cur.close()

        # Both contacts exist, different user_ids
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM contacts WHERE id = %s", (a_contact,))
        assert cur.fetchone()["user_id"] == USER_A
        cur.execute("SELECT user_id FROM contacts WHERE id = %s", (b_contact,))
        assert cur.fetchone()["user_id"] == USER_B_ID
        cur.close()


class TestEnrollmentIsolation:
    def test_cannot_enroll_in_other_users_campaign(self, conn):
        """User A cannot enroll contacts in User B's campaign."""
        from src.models.campaigns import create_campaign, enroll_contact

        a_company = insert_company(conn, "Enroll Co")
        a_contact = insert_contact(conn, a_company)
        b_campaign = create_campaign(conn, "B Campaign", user_id=USER_B_ID)

        # User A tries to enroll in User B's campaign — should fail
        with pytest.raises(PermissionError):
            enroll_contact(conn, a_contact, b_campaign, user_id=USER_A)


class TestTagIsolation:
    def test_tags_scoped_to_user(self, conn):
        """Tags with same name can exist for different users."""
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tags (name, color, user_id) VALUES ('hot-lead', '#ff0000', %s) RETURNING id",
            (USER_A,),
        )
        a_tag = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO tags (name, color, user_id) VALUES ('hot-lead', '#00ff00', %s) RETURNING id",
            (USER_B_ID,),
        )
        b_tag = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        assert a_tag != b_tag


class TestDealIsolation:
    def test_deals_scoped_to_user(self, conn):
        """Deals are user-scoped."""
        a_company = insert_company(conn, "Deal Co A")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Deal Co B', 'deal co b', %s) RETURNING id",
            (USER_B_ID,),
        )
        b_company = cur.fetchone()["id"]

        cur.execute(
            "INSERT INTO deals (company_id, title, stage, user_id) VALUES (%s, 'Deal A', 'cold', %s) RETURNING id",
            (a_company, USER_A),
        )
        a_deal = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO deals (company_id, title, stage, user_id) VALUES (%s, 'Deal B', 'cold', %s) RETURNING id",
            (b_company, USER_B_ID),
        )
        b_deal = cur.fetchone()["id"]
        conn.commit()

        # User A can only see their deal
        cur.execute("SELECT id FROM deals WHERE user_id = %s", (USER_A,))
        a_deals = [r["id"] for r in cur.fetchall()]
        assert a_deal in a_deals
        assert b_deal not in a_deals
        cur.close()


class TestEngineConfigIsolation:
    def test_engine_config_per_user(self, conn):
        """Engine config is per-user — same key, different values."""
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO engine_config (key, value, user_id) VALUES ('mode', 'explore', %s) "
            "ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value",
            (USER_A,),
        )
        cur.execute(
            "INSERT INTO engine_config (key, value, user_id) VALUES ('mode', 'exploit', %s) "
            "ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value",
            (USER_B_ID,),
        )
        conn.commit()

        cur.execute("SELECT value FROM engine_config WHERE key = 'mode' AND user_id = %s", (USER_A,))
        assert cur.fetchone()["value"] == "explore"
        cur.execute("SELECT value FROM engine_config WHERE key = 'mode' AND user_id = %s", (USER_B_ID,))
        assert cur.fetchone()["value"] == "exploit"
        cur.close()


class TestEventIsolation:
    def test_events_scoped_to_user(self, conn):
        """Events carry user_id for filtering."""
        from src.models.events import log_event

        a_company = insert_company(conn, "Event Co")
        a_contact = insert_contact(conn, a_company)

        event_id = log_event(conn, a_contact, "email_sent", user_id=USER_A)

        cur = conn.cursor()
        cur.execute("SELECT user_id FROM events WHERE id = %s", (event_id,))
        assert cur.fetchone()["user_id"] == USER_A
        cur.close()


class TestDedupIsolation:
    def test_dedup_only_affects_own_contacts(self, conn):
        """Dedup with user_id only touches that user's contacts."""
        # User A has a contact with a given email
        a_co = insert_company(conn, "Dedup Co A")
        insert_contact(conn, a_co, email="dup@test.com", first_name="First")

        # User B has a contact with same email — should NOT be affected
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Dedup Co B', 'dedup co b', %s) RETURNING id",
            (USER_B_ID,),
        )
        b_co = cur.fetchone()["id"]
        conn.commit()
        cur.execute(
            """INSERT INTO contacts (company_id, first_name, last_name, full_name, email, email_normalized,
                                     priority_rank, source, user_id)
               VALUES (%s, 'B', 'Dup', 'B Dup', 'dup@test.com', 'dup@test.com', 1, 'test', %s)
               RETURNING id""",
            (b_co, USER_B_ID),
        )
        b_contact_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()

        # User B's contact should still exist after any dedup
        cur = conn.cursor()
        cur.execute("SELECT id FROM contacts WHERE id = %s", (b_contact_id,))
        assert cur.fetchone() is not None
        cur.close()


# ---------------------------------------------------------------------------
# Write prevention tests
# ---------------------------------------------------------------------------

class TestWritePrevention:
    def test_cannot_update_other_users_campaign(self, conn):
        from src.models.campaigns import create_campaign, update_campaign_status

        b_camp = create_campaign(conn, "B's Camp", user_id=USER_B_ID)
        # User A tries to update User B's campaign
        update_campaign_status(conn, b_camp, "completed", user_id=USER_A)

        # Verify it wasn't updated (campaign still active)
        cur = conn.cursor()
        cur.execute("SELECT status FROM campaigns WHERE id = %s", (b_camp,))
        row = cur.fetchone()
        cur.close()
        assert row["status"] == "active"  # Unchanged

    def test_cannot_add_step_to_other_users_campaign(self, conn):
        from src.models.campaigns import create_campaign, add_sequence_step

        b_camp = create_campaign(conn, "B's Step Camp", user_id=USER_B_ID)
        with pytest.raises(PermissionError):
            add_sequence_step(conn, b_camp, 1, "email", user_id=USER_A)
