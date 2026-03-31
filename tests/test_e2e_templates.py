"""E2E tests for template CRUD and AI sequence generation."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch, MagicMock

import psycopg2
import psycopg2.extras
import pytest

from src.models.database import get_connection, get_cursor, run_migrations
from src.models.campaigns import create_campaign
from src.models.templates import create_template, get_template
from src.models.enrollment import (
    add_sequence_step,
    enroll_contact,
    get_sequence_steps,
)
from src.services.priority_queue import get_daily_queue
from src.services.template_engine import get_template_context
from src.services.email_sender import render_template_with_compliance
from src.services.message_drafter import generate_sequence_messages
from tests.conftest import TEST_USER_ID, insert_company, insert_contact


def _conn(tmp_db):
    """Get a fresh connection from the test DB URL."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


# ---------------------------------------------------------------------------
# 14. Template CRUD lifecycle
# ---------------------------------------------------------------------------


def test_template_crud_lifecycle(tmp_db):
    """Create -> update body -> assign to step -> render via queue -> verify content."""
    conn = _conn(tmp_db)

    # Create template
    template_id = create_template(
        conn, "lifecycle_tmpl", "email",
        "Original body for {{ first_name }}",
        subject="Original Subject",
        user_id=TEST_USER_ID,
    )

    # Update body via direct SQL (simulating the PUT /templates/:id route)
    new_body = "Updated body for {{ first_name }} at {{ company_name }}"
    with get_cursor(conn) as cur:
        cur.execute(
            "UPDATE templates SET body_template = %s WHERE id = %s AND user_id = %s",
            (new_body, template_id, TEST_USER_ID),
        )
        conn.commit()

    # Verify update persisted
    tmpl = get_template(conn, template_id, user_id=TEST_USER_ID)
    assert tmpl["body_template"] == new_body

    # Create campaign + step with this template
    campaign_id = create_campaign(conn, "tmpl_lifecycle", user_id=TEST_USER_ID)
    add_sequence_step(
        conn, campaign_id, 1, "email",
        template_id=template_id, delay_days=0,
        user_id=TEST_USER_ID,
    )

    # Seed company + contact and enroll
    co = insert_company(conn, "TemplateTestCo")
    cid = insert_contact(
        conn, co, first_name="Gina", last_name="Tester",
        email="gina@templatetest.com", email_status="valid",
    )
    enroll_contact(
        conn, cid, campaign_id,
        next_action_date=date.today().isoformat(),
        user_id=TEST_USER_ID,
    )

    # Verify the contact appears in the queue with the right template
    queue = get_daily_queue(conn, campaign_id, user_id=TEST_USER_ID)
    assert len(queue) == 1
    assert queue[0]["template_id"] == template_id

    # Render the template with the contact's context
    config = {
        "smtp": {"username": "test@test.com"},
        "calendly_url": "https://cal.com/test",
        "physical_address": "123 Test St",
    }
    context = get_template_context(conn, cid, config, user_id=TEST_USER_ID)
    rendered = render_template_with_compliance(tmpl, context, config)

    # Verify rendered output uses the UPDATED body text
    assert "Updated body for Gina at TemplateTestCo" in rendered["body_text"]
    assert "Original body" not in rendered["body_text"]

    conn.close()


# ---------------------------------------------------------------------------
# 15. AI sequence generation
# ---------------------------------------------------------------------------


def test_ai_sequence_generation(tmp_db):
    """Mock Anthropic API. Call generate_sequence_messages. Verify 3 messages returned."""
    # This test does not need a DB connection — the function calls Anthropic directly.
    # But we include tmp_db for consistency with the fixture pattern.

    steps = [
        {"step_order": 1, "channel": "email", "delay_days": 0},
        {"step_order": 2, "channel": "linkedin_connect", "delay_days": 3},
        {"step_order": 3, "channel": "email", "delay_days": 7},
    ]

    # Mock response from Anthropic API
    mock_messages = [
        {
            "step_order": 1,
            "channel": "email",
            "subject": "Exploring Digital Asset Allocation",
            "body": "Hi {{ first_name }}, I noticed your fund...",
        },
        {
            "step_order": 2,
            "channel": "linkedin_connect",
            "subject": None,
            "body": "Hi — I lead research at [Fund]. Would love to connect.",
        },
        {
            "step_order": 3,
            "channel": "email",
            "subject": "Following up on crypto allocations",
            "body": "Hi {{ first_name }}, just wanted to follow up...",
        },
    ]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "content": [{"text": json.dumps(mock_messages)}],
    }
    mock_response.raise_for_status = MagicMock()

    with patch("src.services.message_drafter.httpx.post", return_value=mock_response):
        result = generate_sequence_messages(
            steps=steps,
            product_description="Digital asset hedge fund targeting institutional allocators",
            target_audience="crypto fund allocators",
            model="haiku",
            user_id=TEST_USER_ID,
            api_key="fake-api-key",
        )

    assert len(result) == 3

    # Verify each message has the correct channel and step_order
    for i, msg in enumerate(result):
        assert msg["step_order"] == steps[i]["step_order"]
        assert msg["channel"] == steps[i]["channel"]
        assert msg.get("body") is not None
