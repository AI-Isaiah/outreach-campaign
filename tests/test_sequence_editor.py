"""Tests for Sequence Editor v2: stable_id migration, reorder, PATCH, messages, queue scope, add/delete."""

from __future__ import annotations

import pytest
from datetime import date, timedelta

from fastapi.testclient import TestClient

from src.models.database import get_connection, run_migrations, get_cursor
from src.models.enrollment import (
    enroll_contact,
    update_contact_campaign_status,
    get_sequence_steps,
)
from src.services.sequence_utils import find_next_step, find_previous_step, find_step_by_stable_id
from src.web.app import app
from src.web.dependencies import get_db
from tests.conftest import TEST_USER_ID, insert_company, insert_contact


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_db):
    """Provide a database connection with migrations applied."""
    connection = get_connection(tmp_db)
    run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def client(tmp_db):
    """Create a FastAPI TestClient with DB dependency override."""
    def _override_get_db():
        connection = get_connection(tmp_db)
        run_migrations(connection)
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_campaign(conn):
    """Create a campaign with 3 sequence steps and return (campaign_id, step_ids).

    Steps:
      1. email,   delay_days=0
      2. linkedin_message, delay_days=3
      3. email,   delay_days=7
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            "INSERT INTO campaigns (name, user_id, status) VALUES (%s, %s, %s) RETURNING id",
            ("test_seq_editor", TEST_USER_ID, "active"),
        )
        campaign_id = cursor.fetchone()["id"]

        step_ids = []
        for i, (channel, delay) in enumerate(
            [("email", 0), ("linkedin_message", 3), ("email", 7)], start=1
        ):
            cursor.execute(
                "INSERT INTO sequence_steps (campaign_id, step_order, channel, delay_days) "
                "VALUES (%s, %s, %s, %s) RETURNING id, stable_id",
                (campaign_id, i, channel, delay),
            )
            row = cursor.fetchone()
            step_ids.append({"id": row["id"], "stable_id": str(row["stable_id"])})

        conn.commit()
    return campaign_id, step_ids


# ---------------------------------------------------------------------------
# 1. Migration & stable_id tests
# ---------------------------------------------------------------------------

class TestStableId:
    def test_stable_id_populated_on_insert(self, conn, sample_campaign):
        """New sequence steps get a stable_id automatically."""
        campaign_id, steps = sample_campaign
        with get_cursor(conn) as cursor:
            cursor.execute(
                "SELECT stable_id FROM sequence_steps WHERE campaign_id = %s",
                (campaign_id,),
            )
            rows = cursor.fetchall()

        assert all(row["stable_id"] is not None for row in rows)
        # All stable_ids are unique
        ids = [str(row["stable_id"]) for row in rows]
        assert len(set(ids)) == len(ids)

    def test_stable_id_is_uuid_format(self, conn, sample_campaign):
        """stable_id values are valid UUIDs."""
        import uuid

        _, steps = sample_campaign
        for step in steps:
            # Should not raise ValueError
            uuid.UUID(step["stable_id"])

    def test_current_step_id_set_on_enroll(self, conn, sample_campaign):
        """When a contact is enrolled with first_step_stable_id, current_step_id is set."""
        campaign_id, steps = sample_campaign
        company_id = insert_company(conn, "StableIdCo")
        contact_id = insert_contact(conn, company_id)

        enroll_contact(
            conn,
            contact_id,
            campaign_id,
            first_step_stable_id=steps[0]["stable_id"],
            user_id=TEST_USER_ID,
        )

        with get_cursor(conn) as cursor:
            cursor.execute(
                "SELECT current_step, current_step_id "
                "FROM contact_campaign_status "
                "WHERE contact_id = %s AND campaign_id = %s",
                (contact_id, campaign_id),
            )
            row = cursor.fetchone()

        assert row["current_step"] == 1
        assert str(row["current_step_id"]) == steps[0]["stable_id"]

    def test_stable_id_unique_across_steps(self, conn, sample_campaign):
        """Each step in a campaign has a distinct stable_id."""
        _, steps = sample_campaign
        stable_ids = [s["stable_id"] for s in steps]
        assert len(stable_ids) == len(set(stable_ids))


# ---------------------------------------------------------------------------
# 2. sequence_utils tests
# ---------------------------------------------------------------------------

class TestSequenceUtils:
    def test_find_next_step_basic(self):
        steps = [{"step_order": 1}, {"step_order": 3}, {"step_order": 5}]
        assert find_next_step(steps, 1)["step_order"] == 3
        assert find_next_step(steps, 3)["step_order"] == 5
        assert find_next_step(steps, 5) is None

    def test_find_next_step_at_gap(self):
        """find_next_step works when step_order values have gaps."""
        steps = [{"step_order": 2}, {"step_order": 10}, {"step_order": 20}]
        assert find_next_step(steps, 2)["step_order"] == 10
        assert find_next_step(steps, 10)["step_order"] == 20
        assert find_next_step(steps, 20) is None

    def test_find_next_step_from_nonexistent_order(self):
        """Passing a step_order that does not match any step still finds the next."""
        steps = [{"step_order": 5}, {"step_order": 10}]
        result = find_next_step(steps, 3)
        assert result["step_order"] == 5

    def test_find_previous_step_basic(self):
        steps = [{"step_order": 1}, {"step_order": 3}, {"step_order": 5}]
        assert find_previous_step(steps, 5)["step_order"] == 3
        assert find_previous_step(steps, 3)["step_order"] == 1
        assert find_previous_step(steps, 1) is None

    def test_find_previous_step_at_first(self):
        """No previous step when at the very first step."""
        steps = [{"step_order": 1}]
        assert find_previous_step(steps, 1) is None

    def test_find_previous_step_with_gaps(self):
        steps = [{"step_order": 2}, {"step_order": 8}, {"step_order": 15}]
        assert find_previous_step(steps, 15)["step_order"] == 8
        assert find_previous_step(steps, 8)["step_order"] == 2

    def test_find_step_by_stable_id_found(self):
        steps = [{"stable_id": "abc-123"}, {"stable_id": "def-456"}]
        result = find_step_by_stable_id(steps, "abc-123")
        assert result is not None
        assert result["stable_id"] == "abc-123"

    def test_find_step_by_stable_id_not_found(self):
        steps = [{"stable_id": "abc-123"}, {"stable_id": "def-456"}]
        assert find_step_by_stable_id(steps, "not-exist") is None

    def test_find_step_by_stable_id_empty_list(self):
        assert find_step_by_stable_id([], "any-id") is None

    def test_find_next_step_empty_list(self):
        assert find_next_step([], 1) is None

    def test_find_previous_step_empty_list(self):
        assert find_previous_step([], 1) is None


# ---------------------------------------------------------------------------
# 3. Reorder endpoint tests
# ---------------------------------------------------------------------------

class TestReorderEndpoint:
    def test_reorder_happy_path(self, client, sample_campaign):
        """Reverse the step order and verify the server accepts it."""
        campaign_id, steps = sample_campaign
        response = client.put(
            f"/api/campaigns/{campaign_id}/sequence/reorder",
            json={
                "steps": [
                    {"step_id": steps[0]["id"], "step_order": 3},
                    {"step_id": steps[1]["id"], "step_order": 1},
                    {"step_id": steps[2]["id"], "step_order": 2},
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["steps"]) == 3

        # Verify order changed
        orders = {s["id"]: s["step_order"] for s in data["steps"]}
        assert orders[steps[0]["id"]] == 3
        assert orders[steps[1]["id"]] == 1
        assert orders[steps[2]["id"]] == 2

    def test_reorder_preserves_stable_ids(self, client, sample_campaign):
        """Reorder changes step_order but stable_id stays the same."""
        campaign_id, steps = sample_campaign
        original_stable_ids = {s["id"]: s["stable_id"] for s in steps}

        response = client.put(
            f"/api/campaigns/{campaign_id}/sequence/reorder",
            json={
                "steps": [
                    {"step_id": steps[0]["id"], "step_order": 2},
                    {"step_id": steps[1]["id"], "step_order": 3},
                    {"step_id": steps[2]["id"], "step_order": 1},
                ]
            },
        )
        assert response.status_code == 200
        for returned_step in response.json()["steps"]:
            sid = returned_step["id"]
            if sid in original_stable_ids:
                assert str(returned_step["stable_id"]) == original_stable_ids[sid]

    def test_reorder_invalid_step_id(self, client, sample_campaign):
        """Step IDs that don't belong to the campaign are rejected."""
        campaign_id, _ = sample_campaign
        response = client.put(
            f"/api/campaigns/{campaign_id}/sequence/reorder",
            json={"steps": [{"step_id": 99999, "step_order": 1}]},
        )
        assert response.status_code == 422

    def test_reorder_wrong_campaign(self, client, conn, sample_campaign):
        """Step IDs from a different campaign are rejected."""
        campaign_id, steps = sample_campaign

        # Create a second campaign
        with get_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO campaigns (name, user_id, status) VALUES (%s, %s, %s) RETURNING id",
                ("other_campaign", TEST_USER_ID, "active"),
            )
            other_cid = cursor.fetchone()["id"]
            conn.commit()

        # Try to reorder steps of campaign 1 via campaign 2's endpoint
        response = client.put(
            f"/api/campaigns/{other_cid}/sequence/reorder",
            json={"steps": [{"step_id": steps[0]["id"], "step_order": 1}]},
        )
        assert response.status_code == 422

    def test_reorder_returns_affected_count(self, client, conn, sample_campaign):
        """Reorder returns count of queued/in_progress contacts."""
        campaign_id, steps = sample_campaign

        company_id = insert_company(conn, "AffectedCo")
        contact_id = insert_contact(conn, company_id)
        enroll_contact(
            conn,
            contact_id,
            campaign_id,
            first_step_stable_id=steps[0]["stable_id"],
            user_id=TEST_USER_ID,
        )
        update_contact_campaign_status(
            conn, contact_id, campaign_id, status="queued", user_id=TEST_USER_ID
        )
        conn.commit()

        response = client.put(
            f"/api/campaigns/{campaign_id}/sequence/reorder",
            json={
                "steps": [
                    {"step_id": steps[0]["id"], "step_order": 2},
                    {"step_id": steps[1]["id"], "step_order": 1},
                    {"step_id": steps[2]["id"], "step_order": 3},
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["affected_count"] == 1

    def test_reorder_updates_queued_contacts_to_new_step_1(self, client, conn, sample_campaign):
        """Queued contacts on step 1 should point to the new step 1 after reorder."""
        campaign_id, steps = sample_campaign
        # steps[0]=email(order=1), steps[1]=linkedin(order=2), steps[2]=email(order=3)

        company_id = insert_company(conn, "ReorderUpdateCo")
        contact_id = insert_contact(conn, company_id)
        enroll_contact(
            conn, contact_id, campaign_id,
            first_step_stable_id=steps[0]["stable_id"],
            user_id=TEST_USER_ID,
        )
        update_contact_campaign_status(
            conn, contact_id, campaign_id, status="queued", user_id=TEST_USER_ID
        )
        conn.commit()

        # Verify contact is on step 1 (email)
        with get_cursor(conn) as cursor:
            cursor.execute(
                "SELECT current_step, current_step_id FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
                (contact_id, campaign_id),
            )
            before = cursor.fetchone()
        assert before["current_step"] == 1
        assert str(before["current_step_id"]) == steps[0]["stable_id"]

        # Reorder: move linkedin (steps[1]) to position 1
        response = client.put(
            f"/api/campaigns/{campaign_id}/sequence/reorder",
            json={
                "steps": [
                    {"step_id": steps[1]["id"], "step_order": 1},
                    {"step_id": steps[0]["id"], "step_order": 2},
                    {"step_id": steps[2]["id"], "step_order": 3},
                ]
            },
        )
        assert response.status_code == 200

        # Contact should now point to the NEW step 1 (linkedin)
        with get_cursor(conn) as cursor:
            cursor.execute(
                "SELECT current_step, current_step_id FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
                (contact_id, campaign_id),
            )
            after = cursor.fetchone()
        assert after["current_step"] == 1
        assert str(after["current_step_id"]) == steps[1]["stable_id"]  # now linkedin

    def test_reorder_zero_affected_when_no_enrollments(self, client, sample_campaign):
        """Reorder with no enrolled contacts returns affected_count=0."""
        campaign_id, steps = sample_campaign
        response = client.put(
            f"/api/campaigns/{campaign_id}/sequence/reorder",
            json={
                "steps": [
                    {"step_id": steps[0]["id"], "step_order": 2},
                    {"step_id": steps[1]["id"], "step_order": 1},
                    {"step_id": steps[2]["id"], "step_order": 3},
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["affected_count"] == 0

    def test_reorder_single_step_noop(self, client, conn):
        """Campaign with 1 step: reorder is a no-op."""
        with get_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO campaigns (name, user_id, status) VALUES (%s, %s, %s) RETURNING id",
                ("single_step", TEST_USER_ID, "active"),
            )
            cid = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO sequence_steps (campaign_id, step_order, channel, delay_days) "
                "VALUES (%s, 1, 'email', 0) RETURNING id",
                (cid,),
            )
            sid = cursor.fetchone()["id"]
            conn.commit()

        response = client.put(
            f"/api/campaigns/{cid}/sequence/reorder",
            json={"steps": [{"step_id": sid, "step_order": 1}]},
        )
        assert response.status_code == 200

    def test_reorder_nonexistent_campaign(self, client):
        """Reorder on a campaign that does not exist returns 404."""
        response = client.put(
            "/api/campaigns/99999/sequence/reorder",
            json={"steps": [{"step_id": 1, "step_order": 1}]},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4. PATCH step endpoint tests
# ---------------------------------------------------------------------------

class TestPatchStep:
    def test_update_delay_days(self, client, sample_campaign):
        campaign_id, steps = sample_campaign
        response = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/{steps[0]['id']}",
            json={"delay_days": 5},
        )
        assert response.status_code == 200
        assert response.json()["delay_days"] == 5

    def test_update_channel(self, client, sample_campaign):
        campaign_id, steps = sample_campaign
        response = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/{steps[0]['id']}",
            json={"channel": "linkedin_message"},
        )
        assert response.status_code == 200
        assert response.json()["channel"] == "linkedin_message"

    def test_update_multiple_fields(self, client, sample_campaign):
        """Patch can update both channel and delay_days in one call."""
        campaign_id, steps = sample_campaign
        response = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/{steps[0]['id']}",
            json={"channel": "linkedin_message", "delay_days": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["channel"] == "linkedin_message"
        assert data["delay_days"] == 10

    def test_linkedin_connect_constraint(self, client, sample_campaign):
        """Only one linkedin_connect allowed per sequence."""
        campaign_id, steps = sample_campaign
        # First: set step 1 to linkedin_connect
        resp1 = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/{steps[0]['id']}",
            json={"channel": "linkedin_connect"},
        )
        assert resp1.status_code == 200

        # Second: try to set step 2 to linkedin_connect -- should fail
        resp2 = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/{steps[1]['id']}",
            json={"channel": "linkedin_connect"},
        )
        assert resp2.status_code == 422

    def test_linkedin_connect_same_step_allowed(self, client, sample_campaign):
        """Re-patching the same step to linkedin_connect should be allowed."""
        campaign_id, steps = sample_campaign
        # Set step 1 to linkedin_connect
        client.patch(
            f"/api/campaigns/{campaign_id}/sequence/{steps[0]['id']}",
            json={"channel": "linkedin_connect"},
        )
        # Patch the same step again -- should succeed (not a new duplicate)
        resp = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/{steps[0]['id']}",
            json={"channel": "linkedin_connect"},
        )
        assert resp.status_code == 200

    def test_negative_delay_rejected(self, client, sample_campaign):
        campaign_id, steps = sample_campaign
        response = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/{steps[0]['id']}",
            json={"delay_days": -1},
        )
        assert response.status_code == 422

    def test_empty_body_rejected(self, client, sample_campaign):
        """Patch with no fields to update returns 422."""
        campaign_id, steps = sample_campaign
        response = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/{steps[0]['id']}",
            json={},
        )
        assert response.status_code == 422

    def test_patch_nonexistent_step(self, client, sample_campaign):
        """Patching a step that does not exist returns 404."""
        campaign_id, _ = sample_campaign
        response = client.patch(
            f"/api/campaigns/{campaign_id}/sequence/99999",
            json={"delay_days": 5},
        )
        assert response.status_code == 404

    def test_patch_preserves_stable_id(self, client, conn, sample_campaign):
        """Patching a step does not change its stable_id."""
        campaign_id, steps = sample_campaign
        original_stable_id = steps[0]["stable_id"]

        client.patch(
            f"/api/campaigns/{campaign_id}/sequence/{steps[0]['id']}",
            json={"delay_days": 99},
        )

        with get_cursor(conn) as cursor:
            cursor.execute(
                "SELECT stable_id FROM sequence_steps WHERE id = %s",
                (steps[0]["id"],),
            )
            row = cursor.fetchone()
        assert str(row["stable_id"]) == original_stable_id


# ---------------------------------------------------------------------------
# 5. Messages endpoint tests
# ---------------------------------------------------------------------------

class TestMessagesEndpoint:
    def test_empty_campaign(self, client, sample_campaign):
        """Campaign with no sent messages returns empty list."""
        campaign_id, _ = sample_campaign
        response = client.get(f"/api/campaigns/{campaign_id}/messages")
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []
        assert data["total"] == 0

    def test_messages_with_events(self, client, conn, sample_campaign):
        """Messages endpoint returns email_sent events with contact info."""
        campaign_id, steps = sample_campaign
        company_id = insert_company(conn, "MsgCo")
        contact_id = insert_contact(conn, company_id)

        with get_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO events (contact_id, campaign_id, event_type, user_id) "
                "VALUES (%s, %s, 'email_sent', %s)",
                (contact_id, campaign_id, TEST_USER_ID),
            )
            conn.commit()

        response = client.get(f"/api/campaigns/{campaign_id}/messages")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["messages"]) == 1

    def test_messages_only_counts_email_sent(self, client, conn, sample_campaign):
        """Non-email_sent events are not included in the messages endpoint."""
        campaign_id, _ = sample_campaign
        company_id = insert_company(conn, "EventTypeCo")
        contact_id = insert_contact(conn, company_id)

        with get_cursor(conn) as cursor:
            # Insert a non-email event
            cursor.execute(
                "INSERT INTO events (contact_id, campaign_id, event_type, user_id) "
                "VALUES (%s, %s, 'replied', %s)",
                (contact_id, campaign_id, TEST_USER_ID),
            )
            conn.commit()

        response = client.get(f"/api/campaigns/{campaign_id}/messages")
        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_messages_pagination(self, client, conn, sample_campaign):
        """Messages endpoint respects limit and offset parameters."""
        campaign_id, _ = sample_campaign
        company_id = insert_company(conn, "PaginCo")

        with get_cursor(conn) as cursor:
            # Insert 5 email_sent events
            for i in range(5):
                cid = insert_contact(
                    conn, company_id, first_name=f"Page{i}", email=f"page{i}@test.com"
                )
                cursor.execute(
                    "INSERT INTO events (contact_id, campaign_id, event_type, user_id) "
                    "VALUES (%s, %s, 'email_sent', %s)",
                    (cid, campaign_id, TEST_USER_ID),
                )
            conn.commit()

        # Fetch page 1 (limit=2)
        resp1 = client.get(f"/api/campaigns/{campaign_id}/messages?limit=2&offset=0")
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["total"] == 5
        assert len(data1["messages"]) == 2

        # Fetch page 2
        resp2 = client.get(f"/api/campaigns/{campaign_id}/messages?limit=2&offset=2")
        assert resp2.status_code == 200
        assert len(resp2.json()["messages"]) == 2

    def test_messages_nonexistent_campaign(self, client):
        """Messages endpoint for a non-existent campaign returns 404."""
        response = client.get("/api/campaigns/99999/messages")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 6. Queue scope tests
# ---------------------------------------------------------------------------

class TestQueueScope:
    def _enroll_for_queue(self, conn, campaign_id, steps, action_date, company_name, email):
        """Helper: create a company/contact, enroll, and set in_progress with a given action date."""
        company_id = insert_company(conn, company_name, aum_millions=100)
        contact_id = insert_contact(conn, company_id, email=email)

        # Ensure email_status is valid
        with get_cursor(conn) as cursor:
            cursor.execute(
                "UPDATE contacts SET email_status = 'valid', email_normalized = %s WHERE id = %s",
                (email.lower(), contact_id),
            )

        enroll_contact(
            conn,
            contact_id,
            campaign_id,
            first_step_stable_id=steps[0]["stable_id"],
            next_action_date=action_date,
            user_id=TEST_USER_ID,
        )
        update_contact_campaign_status(
            conn, contact_id, campaign_id, status="in_progress", user_id=TEST_USER_ID
        )
        conn.commit()
        return contact_id

    def test_scope_today_default(self, client, conn, sample_campaign):
        """Default scope=today includes contacts with next_action_date <= today."""
        campaign_id, steps = sample_campaign
        today = date.today().isoformat()
        self._enroll_for_queue(conn, campaign_id, steps, today, "TodayCo", "today@test.com")

        response = client.get(f"/api/queue/test_seq_editor?scope=today")
        assert response.status_code == 200

    def test_scope_today_excludes_future(self, client, conn, sample_campaign):
        """scope=today does not include contacts with next_action_date in the future."""
        campaign_id, steps = sample_campaign
        future = (date.today() + timedelta(days=30)).isoformat()
        self._enroll_for_queue(conn, campaign_id, steps, future, "FutureCo", "future@test.com")

        response = client.get(f"/api/queue/test_seq_editor?scope=today")
        assert response.status_code == 200
        items = response.json().get("items", [])
        assert len(items) == 0

    def test_scope_all_includes_future(self, client, conn, sample_campaign):
        """scope=all returns contacts regardless of next_action_date."""
        campaign_id, steps = sample_campaign
        future = (date.today() + timedelta(days=30)).isoformat()
        self._enroll_for_queue(conn, campaign_id, steps, future, "AllFutureCo", "allfuture@test.com")

        response = client.get(f"/api/queue/test_seq_editor?scope=all")
        assert response.status_code == 200
        items = response.json().get("items", [])
        # scope=all should include the future contact
        assert len(items) >= 1


# ---------------------------------------------------------------------------
# 7. Add/delete step tests
# ---------------------------------------------------------------------------

class TestAddDeleteSteps:
    def test_add_step_appends(self, client, sample_campaign):
        """Adding a step to a campaign with 3 steps appends as step_order 4."""
        campaign_id, _ = sample_campaign
        response = client.post(
            f"/api/campaigns/{campaign_id}/sequence",
            json={"channel": "email", "delay_days": 5},
        )
        assert response.status_code == 200
        assert response.json()["step_order"] == 4

    def test_add_step_returns_stable_id(self, client, sample_campaign):
        """Newly added step gets a stable_id."""
        campaign_id, _ = sample_campaign
        response = client.post(
            f"/api/campaigns/{campaign_id}/sequence",
            json={"channel": "email", "delay_days": 2},
        )
        assert response.status_code == 200
        assert response.json()["stable_id"] is not None

    def test_add_step_at_position(self, client, conn, sample_campaign):
        """Adding a step at a specific position renumbers subsequent steps."""
        campaign_id, _ = sample_campaign
        response = client.post(
            f"/api/campaigns/{campaign_id}/sequence",
            json={"channel": "linkedin_connect", "delay_days": 1, "step_order": 2},
        )
        assert response.status_code == 200
        assert response.json()["step_order"] == 2

        # Verify the old steps got renumbered
        with get_cursor(conn) as cursor:
            cursor.execute(
                "SELECT step_order, channel FROM sequence_steps "
                "WHERE campaign_id = %s ORDER BY step_order",
                (campaign_id,),
            )
            rows = cursor.fetchall()
        orders = [r["step_order"] for r in rows]
        assert orders == [1, 2, 3, 4]

    def test_add_blocked_when_enrolled(self, client, conn, sample_campaign):
        """Adding a step is blocked when contacts are enrolled."""
        campaign_id, steps = sample_campaign
        company_id = insert_company(conn, "BlockedAddCo")
        contact_id = insert_contact(conn, company_id)
        enroll_contact(
            conn,
            contact_id,
            campaign_id,
            first_step_stable_id=steps[0]["stable_id"],
            user_id=TEST_USER_ID,
        )
        conn.commit()

        response = client.post(
            f"/api/campaigns/{campaign_id}/sequence",
            json={"channel": "email", "delay_days": 5},
        )
        assert response.status_code == 422

    def test_add_linkedin_connect_constraint(self, client, conn):
        """Only one linkedin_connect step can be added per campaign."""
        with get_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO campaigns (name, user_id, status) VALUES (%s, %s, %s) RETURNING id",
                ("lc_constraint_test", TEST_USER_ID, "active"),
            )
            cid = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO sequence_steps (campaign_id, step_order, channel, delay_days) "
                "VALUES (%s, 1, 'linkedin_connect', 0)",
                (cid,),
            )
            conn.commit()

        response = client.post(
            f"/api/campaigns/{cid}/sequence",
            json={"channel": "linkedin_connect", "delay_days": 3},
        )
        assert response.status_code == 422

    def test_add_to_nonexistent_campaign(self, client):
        """Adding a step to a campaign that does not exist returns 404."""
        response = client.post(
            "/api/campaigns/99999/sequence",
            json={"channel": "email", "delay_days": 0},
        )
        assert response.status_code == 404

    def test_delete_step(self, client, sample_campaign):
        """Deleting a step succeeds and returns deleted: true."""
        campaign_id, steps = sample_campaign
        response = client.delete(
            f"/api/campaigns/{campaign_id}/sequence/{steps[1]['id']}"
        )
        assert response.status_code == 200
        assert response.json()["deleted"] is True

    def test_delete_blocked_when_enrolled(self, client, conn, sample_campaign):
        """Deleting a step is blocked when contacts are enrolled."""
        campaign_id, steps = sample_campaign
        company_id = insert_company(conn, "BlockedDelCo")
        contact_id = insert_contact(conn, company_id)
        enroll_contact(
            conn,
            contact_id,
            campaign_id,
            first_step_stable_id=steps[0]["stable_id"],
            user_id=TEST_USER_ID,
        )
        conn.commit()

        response = client.delete(
            f"/api/campaigns/{campaign_id}/sequence/{steps[1]['id']}"
        )
        assert response.status_code == 422

    def test_delete_compacts_order(self, client, conn, sample_campaign):
        """After deleting step 2, remaining steps should be renumbered 1, 2."""
        campaign_id, steps = sample_campaign
        client.delete(f"/api/campaigns/{campaign_id}/sequence/{steps[1]['id']}")

        with get_cursor(conn) as cursor:
            cursor.execute(
                "SELECT step_order FROM sequence_steps "
                "WHERE campaign_id = %s ORDER BY step_order",
                (campaign_id,),
            )
            orders = [r["step_order"] for r in cursor.fetchall()]
        assert orders == [1, 2]

    def test_delete_nonexistent_step(self, client, sample_campaign):
        """Deleting a step that does not exist returns 404."""
        campaign_id, _ = sample_campaign
        response = client.delete(f"/api/campaigns/{campaign_id}/sequence/99999")
        assert response.status_code == 404

    def test_delete_step_from_wrong_campaign(self, client, conn, sample_campaign):
        """Deleting a step using the wrong campaign_id returns 404."""
        _, steps = sample_campaign
        with get_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO campaigns (name, user_id, status) VALUES (%s, %s, %s) RETURNING id",
                ("other_del", TEST_USER_ID, "active"),
            )
            other_cid = cursor.fetchone()["id"]
            conn.commit()

        response = client.delete(
            f"/api/campaigns/{other_cid}/sequence/{steps[0]['id']}"
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 8. Dual-write tests
# ---------------------------------------------------------------------------

class TestDualWrite:
    def test_advancement_sets_both_columns(self, conn, sample_campaign):
        """When a contact advances, both current_step and current_step_id are set."""
        campaign_id, steps = sample_campaign
        company_id = insert_company(conn, "DualWriteCo")
        contact_id = insert_contact(conn, company_id)
        enroll_contact(
            conn,
            contact_id,
            campaign_id,
            first_step_stable_id=steps[0]["stable_id"],
            user_id=TEST_USER_ID,
        )

        # Advance to step 2
        update_contact_campaign_status(
            conn,
            contact_id,
            campaign_id,
            current_step=2,
            current_step_id=steps[1]["stable_id"],
            user_id=TEST_USER_ID,
        )
        conn.commit()

        with get_cursor(conn) as cursor:
            cursor.execute(
                "SELECT current_step, current_step_id "
                "FROM contact_campaign_status "
                "WHERE contact_id = %s AND campaign_id = %s",
                (contact_id, campaign_id),
            )
            row = cursor.fetchone()

        assert row["current_step"] == 2
        assert str(row["current_step_id"]) == steps[1]["stable_id"]

    def test_advancement_to_last_step(self, conn, sample_campaign):
        """Advancing to the last step works correctly for both columns."""
        campaign_id, steps = sample_campaign
        company_id = insert_company(conn, "LastStepCo")
        contact_id = insert_contact(conn, company_id)
        enroll_contact(
            conn,
            contact_id,
            campaign_id,
            first_step_stable_id=steps[0]["stable_id"],
            user_id=TEST_USER_ID,
        )

        # Advance to step 3 (last)
        update_contact_campaign_status(
            conn,
            contact_id,
            campaign_id,
            current_step=3,
            current_step_id=steps[2]["stable_id"],
            user_id=TEST_USER_ID,
        )
        conn.commit()

        with get_cursor(conn) as cursor:
            cursor.execute(
                "SELECT current_step, current_step_id "
                "FROM contact_campaign_status "
                "WHERE contact_id = %s AND campaign_id = %s",
                (contact_id, campaign_id),
            )
            row = cursor.fetchone()

        assert row["current_step"] == 3
        assert str(row["current_step_id"]) == steps[2]["stable_id"]

    def test_status_update_without_step_change(self, conn, sample_campaign):
        """Updating status alone does not alter current_step or current_step_id."""
        campaign_id, steps = sample_campaign
        company_id = insert_company(conn, "StatusOnlyCo")
        contact_id = insert_contact(conn, company_id)
        enroll_contact(
            conn,
            contact_id,
            campaign_id,
            first_step_stable_id=steps[0]["stable_id"],
            user_id=TEST_USER_ID,
        )

        update_contact_campaign_status(
            conn, contact_id, campaign_id, status="in_progress", user_id=TEST_USER_ID
        )
        conn.commit()

        with get_cursor(conn) as cursor:
            cursor.execute(
                "SELECT current_step, current_step_id, status "
                "FROM contact_campaign_status "
                "WHERE contact_id = %s AND campaign_id = %s",
                (contact_id, campaign_id),
            )
            row = cursor.fetchone()

        assert row["status"] == "in_progress"
        assert row["current_step"] == 1
        assert str(row["current_step_id"]) == steps[0]["stable_id"]


# ---------------------------------------------------------------------------
# 9. get_sequence_steps model function tests
# ---------------------------------------------------------------------------

class TestGetSequenceSteps:
    def test_returns_ordered_steps(self, conn, sample_campaign):
        """get_sequence_steps returns steps sorted by step_order."""
        campaign_id, _ = sample_campaign
        steps = get_sequence_steps(conn, campaign_id, user_id=TEST_USER_ID)
        assert len(steps) == 3
        orders = [s["step_order"] for s in steps]
        assert orders == [1, 2, 3]

    def test_includes_stable_id(self, conn, sample_campaign):
        """Each returned step has a non-null stable_id."""
        campaign_id, _ = sample_campaign
        steps = get_sequence_steps(conn, campaign_id, user_id=TEST_USER_ID)
        for step in steps:
            assert step["stable_id"] is not None

    def test_empty_campaign(self, conn):
        """Campaign with no steps returns an empty list."""
        with get_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO campaigns (name, user_id, status) VALUES (%s, %s, %s) RETURNING id",
                ("empty_seq", TEST_USER_ID, "active"),
            )
            cid = cursor.fetchone()["id"]
            conn.commit()

        steps = get_sequence_steps(conn, cid, user_id=TEST_USER_ID)
        assert steps == []

    def test_wrong_user_returns_empty(self, conn, sample_campaign):
        """get_sequence_steps returns nothing when user_id does not match."""
        campaign_id, _ = sample_campaign
        steps = get_sequence_steps(conn, campaign_id, user_id=99999)
        assert steps == []


# ---------------------------------------------------------------------------
# 10. Sequence GET endpoint test
# ---------------------------------------------------------------------------

class TestGetSequenceEndpoint:
    def test_get_sequence(self, client, sample_campaign):
        """GET /campaigns/{id}/sequence returns the step list."""
        campaign_id, _ = sample_campaign
        response = client.get(f"/api/campaigns/{campaign_id}/sequence")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert data[0]["step_order"] == 1

    def test_get_sequence_includes_template_fields(self, client, conn, sample_campaign):
        """GET /campaigns/{id}/sequence includes template_subject and template_body."""
        campaign_id, steps = sample_campaign

        # Create a template and attach it to step 1
        with get_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO templates (name, channel, subject, body_template, user_id) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                ("Test Template", "email", "Hello {{first_name}}", "Body text", TEST_USER_ID),
            )
            template_id = cursor.fetchone()["id"]
            cursor.execute(
                "UPDATE sequence_steps SET template_id = %s WHERE id = %s",
                (template_id, steps[0]["id"]),
            )
            conn.commit()

        response = client.get(f"/api/campaigns/{campaign_id}/sequence")
        assert response.status_code == 200
        first_step = response.json()[0]
        assert first_step["template_subject"] == "Hello {{first_name}}"
        assert first_step["template_body"] == "Body text"
