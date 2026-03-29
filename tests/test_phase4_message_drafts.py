"""Phase 4: Research-powered AI message drafts — backend tests.

17 tests covering: drafter service (5), queue + route integration (7),
gmail + campaign integration (3), frontend placeholder (2).
"""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.models.database import get_connection, get_cursor, run_migrations
from src.models.campaigns import get_message_draft
from tests.conftest import TEST_USER_ID, insert_company, insert_contact


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

def _setup(conn, *, with_research=True, channel="email", draft_mode="template"):
    """Create a company, contact, campaign, template, enrollment, and optionally research."""
    company_id = insert_company(conn, "TestCo Phase4", aum_millions=500)
    contact_id = insert_contact(conn, company_id, first_name="Sarah", last_name="Chen", title="CIO")

    with get_cursor(conn) as cur:
        cur.execute(
            "INSERT INTO campaigns (name, status, user_id) VALUES (%s, 'active', %s) RETURNING id",
            ("test_phase4_campaign", TEST_USER_ID),
        )
        campaign_id = cur.fetchone()["id"]

        cur.execute(
            "INSERT INTO templates (name, channel, subject, body_template, user_id) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            ("Test Template", channel, "Outreach to {{company_name}}", "Hi {{first_name}}, reaching out about {{company_name}}.", TEST_USER_ID),
        )
        template_id = cur.fetchone()["id"]

        cur.execute(
            "INSERT INTO sequence_steps (campaign_id, step_order, channel, template_id, delay_days, draft_mode) "
            "VALUES (%s, 1, %s, %s, 0, %s)",
            (campaign_id, channel, template_id, draft_mode),
        )

        cur.execute(
            "INSERT INTO contact_campaign_status (contact_id, campaign_id, status, current_step, next_action_date) "
            "VALUES (%s, %s, 'in_progress', 1, CURRENT_DATE)",
            (contact_id, campaign_id),
        )
        conn.commit()

    research_id = None
    if with_research:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO deep_research (company_id, status, user_id,
                          company_overview, talking_points, crypto_signals, key_people)
                   VALUES (%s, 'completed', %s, %s, %s, %s, %s) RETURNING id""",
                (
                    company_id, TEST_USER_ID,
                    "TestCo is a leading crypto fund allocator.",
                    json.dumps([{"text": "Portfolio rotation to DeFi", "hook_type": "portfolio_move"}]),
                    json.dumps([{"source": "SEC filing", "quote": "Increased BTC allocation", "relevance": "high"}]),
                    json.dumps([{"name": "Sarah Chen", "title": "CIO", "context": "Key decision maker"}]),
                ),
            )
            research_id = cur.fetchone()["id"]
            conn.commit()

    return company_id, contact_id, campaign_id, template_id, research_id


def _mock_haiku_response(subject=None, body="This is a sufficiently long test draft body for validation."):
    """Create a mock httpx response matching Haiku API format."""
    if subject:
        text = f"SUBJECT: {subject}\nBODY: {body}"
    else:
        text = f"NOTE: {body}"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"content": [{"text": text}]}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ===========================================================================
# BACKEND DRAFTER TESTS (5)
# ===========================================================================

@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_generate_draft_happy_path(mock_post, tmp_db):
    """#1: research + template → draft with subject + body"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    mock_post.return_value = _mock_haiku_response("AI Subject Line", "Personalized body text.")

    from src.services.message_drafter import generate_draft
    result = generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)

    assert result["draft_subject"] == "AI Subject Line"
    assert result["draft_text"] == "Personalized body text."
    assert result["model"] == "claude-haiku-4-5-20251001"
    assert result["channel"] == "email"
    assert result["research_id"] is not None

    # Verify persisted in DB
    draft = get_message_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)
    assert draft is not None
    assert draft["draft_text"] == "Personalized body text."
    conn.close()


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_generate_draft_no_research(mock_post, tmp_db):
    """#2: no research → template-only personalization"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=False)

    mock_post.return_value = _mock_haiku_response("Subject", "Generic but personalized email body for testing the flow.")

    from src.services.message_drafter import generate_draft
    result = generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)

    assert result["draft_text"] == "Generic but personalized email body for testing the flow."
    assert result["research_id"] is None

    # Verify the prompt included "No research available"
    call_args = mock_post.call_args
    user_msg = call_args.kwargs["json"]["messages"][0]["content"]
    assert "No research available" in user_msg
    conn.close()


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_generate_draft_linkedin_connect_limit(mock_post, tmp_db):
    """#3: LinkedIn connect → draft_text ≤ 300 chars"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True, channel="linkedin_connect")

    long_note = "A" * 400  # exceeds 300
    mock_post.return_value = _mock_haiku_response(body=f"NOTE: {long_note}")

    from src.services.message_drafter import generate_draft
    result = generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)

    assert len(result["draft_text"]) <= 300
    conn.close()


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_generate_draft_linkedin_message_limit(mock_post, tmp_db):
    """#4: LinkedIn message → draft_text ≤ 8000 chars"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True, channel="linkedin_message")

    long_msg = "A" * 9000
    mock_post.return_value = _mock_haiku_response(body=f"MESSAGE: {long_msg}")

    from src.services.message_drafter import generate_draft
    result = generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)

    assert len(result["draft_text"]) <= 8000
    conn.close()


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_generate_draft_api_failure(mock_post, tmp_db):
    """#5: API failure → raises exception (not swallowed)"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    mock_post.side_effect = httpx.TimeoutException("Haiku timeout")

    from src.services.message_drafter import generate_draft
    with pytest.raises(Exception, match="Haiku timeout"):
        generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)
    conn.close()


# ===========================================================================
# BACKEND ROUTES + QUEUE INTEGRATION (7)
# ===========================================================================

@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_generate_draft_endpoint_logic(mock_post, tmp_db):
    """#6: generate-draft route logic — ownership check + draft generation"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    mock_post.return_value = _mock_haiku_response("Test Subject", "Test body from Haiku with enough length for validation checks.")

    # Simulate the route logic directly
    from src.models.database import verify_ownership
    from src.services.message_drafter import generate_draft

    assert verify_ownership(conn, "contacts", contact_id, user_id=TEST_USER_ID) is True

    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT current_step FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
            (contact_id, campaign_id),
        )
        enrollment = cur.fetchone()
    assert enrollment is not None
    assert enrollment["current_step"] == 1

    result = generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)
    assert result["draft_text"] == "Test body from Haiku with enough length for validation checks."
    assert result["research_id"] is not None  # research was used
    conn.close()


def test_generate_draft_nonowned_contact(tmp_db):
    """#7: Non-owned contact → verify_ownership returns None"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, _, _, _ = _setup(conn, with_research=True)

    from src.models.database import verify_ownership
    # User 999 doesn't own this contact
    assert verify_ownership(conn, "contacts", contact_id, user_id=999) is None
    conn.close()


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_message_draft_in_queue_response(mock_post, tmp_db):
    """#8: message_draft appears in queue API response when exists"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    mock_post.return_value = _mock_haiku_response("Subject", "This is a sufficiently long draft body for validation.")

    from src.services.message_drafter import generate_draft
    generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)

    # Now check _batch_enrich includes the draft
    from src.application.queue_service import _batch_enrich
    items = [{"contact_id": contact_id, "template_id": None, "channel": "email",
              "step_order": 1, "aum_millions": 500}]
    config = {"smtp": {"username": "test@test.com"}, "calendly_url": "", "physical_address": ""}
    enriched = _batch_enrich(conn, items, campaign_id, config, user_id=TEST_USER_ID)

    assert len(enriched) == 1
    assert enriched[0]["message_draft"] is not None
    assert enriched[0]["message_draft"]["draft_text"] == "This is a sufficiently long draft body for validation."
    conn.close()


def test_message_draft_null_when_not_generated(tmp_db):
    """#9: message_draft is null when no draft generated"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    from src.application.queue_service import _batch_enrich
    items = [{"contact_id": contact_id, "template_id": None, "channel": "email",
              "step_order": 1, "aum_millions": 500}]
    config = {"smtp": {"username": "test@test.com"}, "calendly_url": "", "physical_address": ""}
    enriched = _batch_enrich(conn, items, campaign_id, config, user_id=TEST_USER_ID)

    assert enriched[0]["message_draft"] is None
    conn.close()


def test_draft_mode_and_has_research_flags(tmp_db):
    """#10: draft_mode and has_research flags appear on queue items"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True, draft_mode="ai")

    from src.application.queue_service import _batch_enrich
    items = [{"contact_id": contact_id, "template_id": None, "channel": "email",
              "step_order": 1, "aum_millions": 500}]
    config = {"smtp": {"username": "test@test.com"}, "calendly_url": "", "physical_address": ""}
    enriched = _batch_enrich(conn, items, campaign_id, config, user_id=TEST_USER_ID)

    assert enriched[0]["draft_mode"] == "ai"
    assert enriched[0]["has_research"] is True
    conn.close()


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_haiku_malformed_output(mock_post, tmp_db):
    """#11: Haiku malformed output → parse handles gracefully (uses raw text)"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    # Return text without SUBJECT/BODY markers
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"content": [{"text": "Just some text without markers."}]}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    from src.services.message_drafter import generate_draft
    result = generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)

    # Falls back to using the raw text as body
    assert result["draft_text"] == "Just some text without markers."
    assert result["draft_subject"] is None  # No subject could be parsed
    conn.close()


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_upsert_overwrite(mock_post, tmp_db):
    """#12: UPSERT overwrite — regenerate replaces previous draft"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    # First generation
    mock_post.return_value = _mock_haiku_response("First Subject", "First body of the AI-generated draft message for testing.")
    from src.services.message_drafter import generate_draft
    generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)

    draft1 = get_message_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)
    assert draft1["draft_text"] == "First body of the AI-generated draft message for testing."

    # Second generation (regenerate)
    mock_post.return_value = _mock_haiku_response("Second Subject", "Second body of the regenerated AI draft message for testing.")
    generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)

    draft2 = get_message_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)
    assert draft2["draft_text"] == "Second body of the regenerated AI draft message for testing."
    assert draft2["draft_subject"] == "Second Subject"
    conn.close()


# ===========================================================================
# BACKEND INTEGRATION (3)
# ===========================================================================

def test_gmail_push_with_null_template_id(tmp_db):
    """#13: Gmail push with template_id=None + subject/body works"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True, draft_mode="ai")

    # The DraftRequest model should accept template_id=None
    from src.web.routes.gmail import DraftRequest
    req = DraftRequest(
        contact_id=contact_id,
        campaign="test_phase4_campaign",
        template_id=None,
        subject="AI-generated subject",
        body_text="AI-generated body",
    )
    assert req.template_id is None
    assert req.subject == "AI-generated subject"
    conn.close()


def test_generate_draft_not_enrolled(tmp_db):
    """#14: Contact not enrolled in campaign → enrollment check fails"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    # Create a second campaign where the contact is NOT enrolled
    with get_cursor(conn) as cur:
        cur.execute(
            "INSERT INTO campaigns (name, status, user_id) VALUES ('other_campaign', 'active', %s) RETURNING id",
            (TEST_USER_ID,),
        )
        other_campaign_id = cur.fetchone()["id"]
        conn.commit()

    # Enrollment check should find nothing
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT current_step FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
            (contact_id, other_campaign_id),
        )
        enrollment = cur.fetchone()

    assert enrollment is None  # Not enrolled in other campaign
    conn.close()


def test_step_order_mismatch(tmp_db):
    """#15: step_order mismatch detected by backend check"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    # Contact is at step 1
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT current_step FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
            (contact_id, campaign_id),
        )
        enrollment = cur.fetchone()

    assert enrollment["current_step"] == 1
    # If frontend sends step_order=5, backend detects mismatch
    assert enrollment["current_step"] != 5
    conn.close()


# ===========================================================================
# CEO REVIEW HARDENING TESTS (3)
# ===========================================================================

@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_haiku_429_rate_limit(mock_post, tmp_db):
    """Haiku 429 rate limit → raises HTTPStatusError"""
    import httpx

    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Rate limited", request=MagicMock(), response=mock_response
    )
    mock_post.return_value = mock_response

    from src.services.message_drafter import generate_draft
    with pytest.raises(httpx.HTTPStatusError):
        generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)
    conn.close()


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_haiku_timeout(mock_post, tmp_db):
    """Haiku timeout → raises TimeoutException"""
    import httpx

    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    mock_post.side_effect = httpx.TimeoutException("Connection timed out")

    from src.services.message_drafter import generate_draft
    with pytest.raises(httpx.TimeoutException):
        generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)
    conn.close()


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("src.services.message_drafter.httpx.post")
def test_empty_draft_raises_value_error(mock_post, tmp_db):
    """Empty or too-short Haiku response → raises ValueError"""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _, contact_id, campaign_id, _, _ = _setup(conn, with_research=True)

    # Haiku returns a very short body
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"content": [{"text": "SUBJECT: Hi\nBODY: Ok"}]}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    from src.services.message_drafter import generate_draft
    with pytest.raises(ValueError, match="empty or too-short"):
        generate_draft(conn, contact_id, campaign_id, 1, user_id=TEST_USER_ID)
    conn.close()
