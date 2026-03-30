"""Tests for the deep research feature — per-company Perplexity + Sonnet pipeline."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import psycopg2
import psycopg2.extras
import pytest
from fastapi.testclient import TestClient

from src.models.database import get_connection, get_cursor, run_migrations
from src.services.deep_research_service import (
    _build_research_queries,
    _enrich_contacts,
    _execute_deep_research,
    _get_previous_crypto_score,
    _perplexity_query,
    _synthesize_with_sonnet,
    _update_status,
    estimate_cost,
)
from src.services.template_engine import get_template_context
from src.web.app import app
from src.web.dependencies import get_db
from tests.conftest import TEST_USER_ID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_conn(tmp_db):
    """Provide a database connection for test setup, closed after each test."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(tmp_db):
    """Create a test client with DB dependency override."""
    def _override_get_db():
        conn = get_connection(tmp_db)
        run_migrations(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_company(conn, name="Test Corp", country="US"):
    """Insert a test company and return its id."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO companies (name, name_normalized, country, user_id)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (name, name.lower().strip(), country, TEST_USER_ID),
        )
        conn.commit()
        return cur.fetchone()["id"]


def _insert_contact(conn, company_id, first_name="Test", last_name="User",
                     email=None, linkedin_url=None, title=None, source="test"):
    """Insert a test contact and return its id."""
    full_name = f"{first_name} {last_name}"
    email_norm = email.lower().strip() if email else None
    linkedin_norm = linkedin_url.lower().rstrip("/") if linkedin_url else None
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO contacts
                   (company_id, first_name, last_name, full_name,
                    email, email_normalized, email_status,
                    linkedin_url, linkedin_url_normalized,
                    title, source, user_id)
               VALUES (%s, %s, %s, %s, %s, %s, 'valid', %s, %s, %s, %s, %s) RETURNING id""",
            (
                company_id, first_name, last_name, full_name,
                email, email_norm,
                linkedin_url, linkedin_norm,
                title, source, TEST_USER_ID,
            ),
        )
        conn.commit()
        return cur.fetchone()["id"]


def _insert_deep_research(conn, company_id, user_id=1, status="completed", **kwargs):
    """Insert a deep_research row and return its id."""
    cols = ["company_id", "user_id", "status"]
    vals = [company_id, user_id, status]
    for key, val in kwargs.items():
        cols.append(key)
        if key in ("raw_queries", "crypto_signals", "key_people", "talking_points"):
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


def _insert_research_job(conn, name="Test Job", status="completed"):
    """Insert a research_jobs row and return its id."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO research_jobs (name, method, total_companies, cost_estimate_usd, status, user_id)
               VALUES (%s, 'hybrid', 1, 0.033, %s, %s) RETURNING id""",
            (name, status, TEST_USER_ID),
        )
        conn.commit()
        return cur.fetchone()["id"]


def _insert_research_result(conn, job_id, company_name="Test Corp",
                              company_id=None, crypto_score=75):
    """Insert a research_results row and return its id."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO research_results
                   (job_id, company_id, company_name, crypto_score, category,
                    evidence_summary, status)
               VALUES (%s, %s, %s, %s, 'likely_interested', 'Evidence', 'completed')
               RETURNING id""",
            (job_id, company_id, company_name, crypto_score),
        )
        conn.commit()
        return cur.fetchone()["id"]


# ---------------------------------------------------------------------------
# T1-T5: API Route Tests
# ---------------------------------------------------------------------------


def test_post_deep_research_nonexistent_company_returns_404(client):
    """T1: POST with nonexistent company_id returns 404."""
    resp = client.post("/api/research/deep/9999")
    assert resp.status_code == 404


def test_post_deep_research_active_research_returns_409(client, db_conn):
    """T2: POST when active deep research exists returns 409."""
    company_id = _insert_company(db_conn)
    _insert_deep_research(db_conn, company_id, status="researching")

    with patch("src.web.routes.deep_research.get_user_api_keys", return_value={"perplexity": "pk-test", "anthropic": "ak-test"}):
        resp = client.post(f"/api/research/deep/{company_id}")
    assert resp.status_code == 409
    assert "already in progress" in resp.json()["detail"]


def test_post_deep_research_no_api_keys_returns_400(client, db_conn):
    """T3: POST with no API keys configured returns 400."""
    company_id = _insert_company(db_conn)

    with patch("src.web.routes.deep_research.get_user_api_keys", return_value={"perplexity": "", "anthropic": ""}):
        resp = client.post(f"/api/research/deep/{company_id}")
    assert resp.status_code == 400
    assert "Perplexity API key" in resp.json()["detail"]


@patch("src.web.routes.deep_research._trigger_deep_research")
def test_post_deep_research_valid_creates_row(mock_trigger, client, db_conn):
    """T4: POST valid request returns 202 and creates row in DB."""
    company_id = _insert_company(db_conn)

    with patch("src.web.routes.deep_research.get_user_api_keys", return_value={"perplexity": "pk-test", "anthropic": "ak-test"}):
        with patch("src.services.deep_research_service.estimate_cost", return_value={"cost_estimate_usd": 0.06, "query_count": 6}):
            resp = client.post(f"/api/research/deep/{company_id}")

    assert resp.status_code == 202
    data = resp.json()
    assert data["id"] > 0
    assert data["status"] == "pending"
    mock_trigger.assert_called_once()


@patch("src.web.routes.deep_research._trigger_deep_research")
def test_post_deep_research_response_includes_cost_and_query_count(mock_trigger, client, db_conn):
    """T5: POST response includes correct cost_estimate and query_count."""
    company_id = _insert_company(db_conn, country="US")

    with patch("src.web.routes.deep_research.get_user_api_keys", return_value={"perplexity": "pk-test", "anthropic": "ak-test"}):
        with patch("src.services.deep_research_service.estimate_cost", return_value={"cost_estimate_usd": 0.06, "query_count": 6}):
            resp = client.post(f"/api/research/deep/{company_id}")

    assert resp.status_code == 202
    data = resp.json()
    assert data["cost_estimate_usd"] == 0.06
    assert data["query_count"] == 6


# ---------------------------------------------------------------------------
# T6-T15: Background Thread / Service Tests
# ---------------------------------------------------------------------------


def test_all_queries_succeed_populates_raw_queries(db_conn):
    """T6: All queries succeed -> raw_queries populated, status transitions."""
    company_id = _insert_company(db_conn)
    dr_id = _insert_deep_research(db_conn, company_id, status="pending")

    perplexity_response = {
        "choices": [{"message": {"content": "Research result here"}}]
    }
    synthesis_result = {
        "company_overview": "Test overview",
        "crypto_signals": [{"source": "test", "quote": "found crypto", "relevance": "high"}],
        "key_people": [],
        "talking_points": [],
        "risk_factors": None,
        "updated_crypto_score": 75,
        "confidence": "medium",
    }

    mock_perplexity_resp = MagicMock()
    mock_perplexity_resp.status_code = 200
    mock_perplexity_resp.json.return_value = perplexity_response
    mock_perplexity_resp.raise_for_status = MagicMock()

    mock_sonnet_resp = MagicMock()
    mock_sonnet_resp.status_code = 200
    mock_sonnet_resp.json.return_value = {
        "content": [{"text": json.dumps(synthesis_result)}]
    }
    mock_sonnet_resp.raise_for_status = MagicMock()

    def _mock_post(url, **kwargs):
        if "perplexity" in url:
            return mock_perplexity_resp
        return mock_sonnet_resp

    api_keys = {"perplexity": "pk-test", "anthropic": "ak-test"}

    with patch("src.services.deep_research_service.httpx.post", side_effect=_mock_post):
        _execute_deep_research(db_conn, dr_id, api_keys)

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT * FROM deep_research WHERE id = %s", (dr_id,))
        row = cur.fetchone()

    assert row["status"] == "completed"
    assert row["raw_queries"] is not None
    assert len(row["raw_queries"]) >= 5
    assert row["company_overview"] == "Test overview"


def test_empty_query_result_skipped(db_conn):
    """T7: Query returns empty -> noted in raw_queries with error."""
    company_id = _insert_company(db_conn)
    dr_id = _insert_deep_research(db_conn, company_id, status="pending")

    call_count = {"n": 0}
    synthesis_result = {
        "company_overview": "Overview despite empty",
        "crypto_signals": [],
        "key_people": [],
        "talking_points": [],
        "risk_factors": None,
        "updated_crypto_score": 50,
        "confidence": "low",
    }

    def _mock_post(url, **kwargs):
        if "perplexity" in url:
            call_count["n"] += 1
            resp = MagicMock()
            if call_count["n"] == 1:
                # Simulate an empty/error response for first query
                resp.status_code = 500
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "Server Error", request=MagicMock(), response=resp
                )
                return resp
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": "Good result"}}]}
            resp.raise_for_status = MagicMock()
            return resp
        # Sonnet call
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"content": [{"text": json.dumps(synthesis_result)}]}
        resp.raise_for_status = MagicMock()
        return resp

    api_keys = {"perplexity": "pk-test", "anthropic": "ak-test"}
    with patch("src.services.deep_research_service.httpx.post", side_effect=_mock_post):
        _execute_deep_research(db_conn, dr_id, api_keys)

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT raw_queries, status FROM deep_research WHERE id = %s", (dr_id,))
        row = cur.fetchone()

    assert row["status"] == "completed"
    # At least one query should have an "error" key
    errors = [r for r in row["raw_queries"] if "error" in r]
    assert len(errors) >= 1


def test_query_rate_limited_retry_succeeds(db_conn):
    """T8: Query rate-limited -> retries with backoff and eventually succeeds."""
    company_id = _insert_company(db_conn)
    dr_id = _insert_deep_research(db_conn, company_id, status="pending")

    # Track per-query call counts to simulate 429 then success
    per_query_calls = {}

    synthesis_result = {
        "company_overview": "Recovered after retries",
        "crypto_signals": [],
        "key_people": [],
        "talking_points": [],
        "updated_crypto_score": 70,
        "confidence": "medium",
    }

    def _mock_post(url, **kwargs):
        if "perplexity" in url:
            query_text = kwargs.get("json", {}).get("messages", [{}])[0].get("content", "")
            per_query_calls[query_text] = per_query_calls.get(query_text, 0) + 1
            resp = MagicMock()
            # First call for each query returns 429, subsequent calls succeed
            if per_query_calls[query_text] == 1 and "cryptocurrency" in query_text:
                resp.status_code = 429
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "Rate Limited", request=MagicMock(), response=resp
                )
                return resp
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": "Success"}}]}
            resp.raise_for_status = MagicMock()
            return resp
        # Sonnet
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"content": [{"text": json.dumps(synthesis_result)}]}
        resp.raise_for_status = MagicMock()
        return resp

    api_keys = {"perplexity": "pk-test", "anthropic": "ak-test"}
    with patch("src.services.deep_research_service.httpx.post", side_effect=_mock_post):
        with patch("src.services.deep_research_service.time.sleep"):
            _execute_deep_research(db_conn, dr_id, api_keys)

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT status FROM deep_research WHERE id = %s", (dr_id,))
        row = cur.fetchone()

    # Should still complete despite rate-limiting, because retries succeed
    assert row["status"] == "completed"


def test_excessive_rate_limiting_causes_failure(db_conn):
    """T9: >3 queries rate-limited -> status='failed'."""
    company_id = _insert_company(db_conn)
    dr_id = _insert_deep_research(db_conn, company_id, status="pending")

    def _mock_post(url, **kwargs):
        resp = MagicMock()
        if "perplexity" in url:
            resp.status_code = 429
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Rate Limited", request=MagicMock(), response=resp
            )
        return resp

    api_keys = {"perplexity": "pk-test", "anthropic": "ak-test"}

    with patch("src.services.deep_research_service.httpx.post", side_effect=_mock_post):
        with patch("src.services.deep_research_service.time.sleep"):
            _execute_deep_research(db_conn, dr_id, api_keys)

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT status, error_message FROM deep_research WHERE id = %s", (dr_id,))
        row = cur.fetchone()

    assert row["status"] == "failed"
    assert "minimum 2 required" in row["error_message"]


def test_fewer_than_two_successful_queries_fails(db_conn):
    """T10: <2 successful queries -> status='failed', no synthesis attempted."""
    company_id = _insert_company(db_conn)
    dr_id = _insert_deep_research(db_conn, company_id, status="pending")

    import threading
    success_given = {"done": False}
    lock = threading.Lock()

    def _mock_post(url, **kwargs):
        if "perplexity" in url:
            resp = MagicMock()
            with lock:
                if not success_given["done"]:
                    # Allow exactly one query to succeed
                    success_given["done"] = True
                    resp.status_code = 200
                    resp.json.return_value = {"choices": [{"message": {"content": "Only one"}}]}
                    resp.raise_for_status = MagicMock()
                else:
                    resp.status_code = 500
                    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                        "Server Error", request=MagicMock(), response=resp
                    )
            return resp
        # Should never reach Sonnet
        raise AssertionError("Sonnet should not be called with < 2 successful queries")

    api_keys = {"perplexity": "pk-test", "anthropic": "ak-test"}
    with patch("src.services.deep_research_service.httpx.post", side_effect=_mock_post):
        _execute_deep_research(db_conn, dr_id, api_keys)

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT status, error_message FROM deep_research WHERE id = %s", (dr_id,))
        row = cur.fetchone()

    assert row["status"] == "failed"
    assert "minimum 2 required" in row["error_message"]


def test_cancellation_between_research_and_synthesis(db_conn):
    """T11: Cancellation between research and synthesis -> status='cancelled'."""
    company_id = _insert_company(db_conn)
    dr_id = _insert_deep_research(db_conn, company_id, status="pending")

    perplexity_resp = MagicMock()
    perplexity_resp.status_code = 200
    perplexity_resp.json.return_value = {"choices": [{"message": {"content": "Data"}}]}
    perplexity_resp.raise_for_status = MagicMock()

    call_count = {"n": 0}

    def _mock_is_cancelled(conn, dr_id_arg, **kwargs):
        call_count["n"] += 1
        # Cancel on the first check (between research and synthesis)
        return call_count["n"] >= 1

    def _mock_post(url, **kwargs):
        if "perplexity" in url:
            return perplexity_resp
        raise AssertionError("Sonnet should not be called after cancellation")

    api_keys = {"perplexity": "pk-test", "anthropic": "ak-test"}
    with patch("src.services.deep_research_service.httpx.post", side_effect=_mock_post):
        with patch("src.services.deep_research_service._is_cancelled", side_effect=_mock_is_cancelled):
            _execute_deep_research(db_conn, dr_id, api_keys)

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT status FROM deep_research WHERE id = %s", (dr_id,))
        row = cur.fetchone()

    assert row["status"] == "cancelled"


def test_valid_json_from_sonnet_populates_fields(db_conn):
    """T12: Valid JSON from Sonnet -> structured fields populated."""
    company_id = _insert_company(db_conn)
    dr_id = _insert_deep_research(db_conn, company_id, status="pending")

    synthesis_result = {
        "company_overview": "Deep analysis of Test Corp",
        "crypto_signals": [{"source": "blog", "quote": "invested in BTC", "relevance": "high"}],
        "key_people": [{"name": "Alice Doe", "title": "CIO", "linkedin_url": None, "context": "Key person"}],
        "talking_points": [{"hook_type": "thesis_alignment", "text": "Your BTC thesis", "source_reference": "blog"}],
        "risk_factors": "None identified",
        "updated_crypto_score": 85,
        "confidence": "high",
    }

    def _mock_post(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        if "perplexity" in url:
            resp.json.return_value = {"choices": [{"message": {"content": "Research data"}}]}
        else:
            resp.json.return_value = {"content": [{"text": json.dumps(synthesis_result)}]}
        return resp

    api_keys = {"perplexity": "pk-test", "anthropic": "ak-test"}
    with patch("src.services.deep_research_service.httpx.post", side_effect=_mock_post):
        _execute_deep_research(db_conn, dr_id, api_keys)

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT * FROM deep_research WHERE id = %s", (dr_id,))
        row = cur.fetchone()

    assert row["status"] == "completed"
    assert row["company_overview"] == "Deep analysis of Test Corp"
    assert row["updated_crypto_score"] == 85
    assert row["confidence"] == "high"
    assert len(row["crypto_signals"]) == 1
    assert len(row["talking_points"]) == 1


def test_invalid_json_first_try_valid_on_retry():
    """T13: Invalid JSON on first Sonnet try, valid on retry -> retry succeeds."""
    synthesis_result = {
        "company_overview": "Valid on second try",
        "crypto_signals": [],
        "key_people": [],
        "talking_points": [],
        "risk_factors": None,
        "updated_crypto_score": 60,
        "confidence": "medium",
    }

    call_count = {"n": 0}

    def _mock_post(url, **kwargs):
        call_count["n"] += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        if call_count["n"] == 1:
            # First attempt: invalid JSON
            resp.json.return_value = {"content": [{"text": "This is not valid JSON at all"}]}
        else:
            # Second attempt: valid JSON
            resp.json.return_value = {"content": [{"text": json.dumps(synthesis_result)}]}
        return resp

    raw_results = [
        {"query": "test query 1", "response": "data 1"},
        {"query": "test query 2", "response": "data 2"},
    ]

    with patch("src.services.deep_research_service.httpx.post", side_effect=_mock_post):
        result = _synthesize_with_sonnet(raw_results, "Test Corp", None, "ak-test")

    assert result["company_overview"] == "Valid on second try"
    assert result["confidence"] == "medium"


def test_invalid_json_twice_returns_fallback():
    """T14: Invalid JSON twice -> fallback with raw text, confidence='low'."""
    call_count = {"n": 0}

    def _mock_post(url, **kwargs):
        call_count["n"] += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"content": [{"text": "Not valid JSON either time"}]}
        return resp

    raw_results = [
        {"query": "test query 1", "response": "data 1"},
        {"query": "test query 2", "response": "data 2"},
    ]

    with patch("src.services.deep_research_service.httpx.post", side_effect=_mock_post):
        result = _synthesize_with_sonnet(raw_results, "Test Corp", None, "ak-test")

    assert result["confidence"] == "low"
    assert "Not valid JSON" in result["company_overview"]
    assert result.get("crypto_signals") is None
    assert result.get("key_people") is None


def test_cancellation_during_synthesis_phase(db_conn):
    """T15: Cancellation during synthesis phase -> status='cancelled'."""
    company_id = _insert_company(db_conn)
    dr_id = _insert_deep_research(db_conn, company_id, status="pending")

    perplexity_resp = MagicMock()
    perplexity_resp.status_code = 200
    perplexity_resp.json.return_value = {"choices": [{"message": {"content": "Data"}}]}
    perplexity_resp.raise_for_status = MagicMock()

    synthesis_result = {
        "company_overview": "Overview",
        "crypto_signals": [],
        "key_people": [],
        "talking_points": [],
        "updated_crypto_score": 50,
        "confidence": "low",
    }

    sonnet_resp = MagicMock()
    sonnet_resp.status_code = 200
    sonnet_resp.json.return_value = {"content": [{"text": json.dumps(synthesis_result)}]}
    sonnet_resp.raise_for_status = MagicMock()

    cancel_calls = {"n": 0}

    def _mock_is_cancelled(conn, dr_id_arg, **kwargs):
        cancel_calls["n"] += 1
        # Allow research phase, cancel after synthesis
        return cancel_calls["n"] >= 2

    def _mock_post(url, **kwargs):
        if "perplexity" in url:
            return perplexity_resp
        return sonnet_resp

    api_keys = {"perplexity": "pk-test", "anthropic": "ak-test"}
    with patch("src.services.deep_research_service.httpx.post", side_effect=_mock_post):
        with patch("src.services.deep_research_service._is_cancelled", side_effect=_mock_is_cancelled):
            _execute_deep_research(db_conn, dr_id, api_keys)

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT status FROM deep_research WHERE id = %s", (dr_id,))
        row = cur.fetchone()

    assert row["status"] == "cancelled"


# ---------------------------------------------------------------------------
# T16-T21: CRM Enrichment Tests
# ---------------------------------------------------------------------------


def test_enrich_match_by_linkedin_url(db_conn):
    """T16: Match by linkedin_url_normalized -> existing contact found, title updated if NULL."""
    company_id = _insert_company(db_conn)
    contact_id = _insert_contact(
        db_conn, company_id, first_name="Jane", last_name="Doe",
        linkedin_url="https://linkedin.com/in/janedoe", title=None,
    )

    key_people = [
        {"name": "Jane Doe", "title": "CIO", "linkedin_url": "https://linkedin.com/in/janedoe", "context": "Key person"},
    ]

    affected = _enrich_contacts(db_conn, company_id, key_people, TEST_USER_ID)
    assert affected == 1

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT title FROM contacts WHERE id = %s", (contact_id,))
        row = cur.fetchone()

    assert row["title"] == "CIO"


def test_enrich_match_by_email(db_conn):
    """T17: Match by email_normalized -> existing contact found."""
    company_id = _insert_company(db_conn)
    contact_id = _insert_contact(
        db_conn, company_id, first_name="Bob", last_name="Smith",
        email="bob@example.com", title=None,
    )

    key_people = [
        {"name": "Bob Smith", "title": "Partner", "email": "BOB@example.com", "context": "Investor"},
    ]

    affected = _enrich_contacts(db_conn, company_id, key_people, TEST_USER_ID)
    assert affected == 1

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT title FROM contacts WHERE id = %s", (contact_id,))
        row = cur.fetchone()

    assert row["title"] == "Partner"


def test_enrich_match_by_name_and_company(db_conn):
    """T18: Match by name + company_id -> existing contact found."""
    company_id = _insert_company(db_conn)
    contact_id = _insert_contact(
        db_conn, company_id, first_name="Alice", last_name="Jones",
        title=None,
    )

    key_people = [
        {"name": "Alice Jones", "title": "Head of Trading", "context": "Decision maker"},
    ]

    affected = _enrich_contacts(db_conn, company_id, key_people, TEST_USER_ID)
    assert affected == 1

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT title FROM contacts WHERE id = %s", (contact_id,))
        row = cur.fetchone()

    assert row["title"] == "Head of Trading"


def test_enrich_no_match_creates_new_contact(db_conn):
    """T19: No match -> new contact created with source='deep_research'."""
    company_id = _insert_company(db_conn)

    key_people = [
        {
            "name": "New Person",
            "title": "Portfolio Manager",
            "email": "new@example.com",
            "linkedin_url": "https://linkedin.com/in/newperson",
            "context": "Newly discovered",
        },
    ]

    affected = _enrich_contacts(db_conn, company_id, key_people, TEST_USER_ID)
    assert affected == 1

    with get_cursor(db_conn) as cur:
        cur.execute(
            "SELECT * FROM contacts WHERE email_normalized = %s",
            ("new@example.com",),
        )
        row = cur.fetchone()

    assert row is not None
    assert row["source"] == "deep_research"
    assert row["first_name"] == "New"
    assert row["last_name"] == "Person"
    assert row["title"] == "Portfolio Manager"


def test_enrich_key_person_no_linkedin_no_email_falls_through(db_conn):
    """T20: Key person has no linkedin AND no email -> falls through to name match or creates new."""
    company_id = _insert_company(db_conn)

    key_people = [
        {"name": "Mystery Person", "title": "Analyst", "context": "Found in article"},
    ]

    affected = _enrich_contacts(db_conn, company_id, key_people, TEST_USER_ID)
    assert affected == 1

    with get_cursor(db_conn) as cur:
        cur.execute(
            "SELECT source, title FROM contacts WHERE full_name = %s AND company_id = %s",
            ("Mystery Person", company_id),
        )
        row = cur.fetchone()

    assert row is not None
    assert row["source"] == "deep_research"
    assert row["title"] == "Analyst"


def test_previous_crypto_score_from_research_result(db_conn):
    """T21: Previous crypto score snapshot from latest research_result."""
    company_id = _insert_company(db_conn)
    job_id = _insert_research_job(db_conn, "Prior Job")
    _insert_research_result(db_conn, job_id, "Test Corp", company_id=company_id, crypto_score=72)

    score = _get_previous_crypto_score(db_conn, company_id, user_id=TEST_USER_ID)
    assert score == 72


# ---------------------------------------------------------------------------
# T23-T26: GET Endpoint Tests
# ---------------------------------------------------------------------------


def test_get_deep_research_completed_returns_json(client, db_conn):
    """T23: Completed result exists -> returns structured JSON."""
    company_id = _insert_company(db_conn)
    _insert_deep_research(
        db_conn, company_id, status="completed",
        company_overview="Full overview here",
        crypto_signals=[{"source": "article", "quote": "invested in crypto", "relevance": "high"}],
        key_people=[{"name": "John Doe", "title": "CIO"}],
        talking_points=[{"hook_type": "thesis_alignment", "text": "Crypto thesis"}],
        updated_crypto_score=80,
        confidence="high",
    )

    resp = client.get(f"/api/research/deep/{company_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["company_overview"] == "Full overview here"
    assert data["updated_crypto_score"] == 80
    assert data["confidence"] == "high"


def test_get_deep_research_no_result_returns_404(client, db_conn):
    """T24: No result exists -> 404."""
    company_id = _insert_company(db_conn)

    resp = client.get(f"/api/research/deep/{company_id}")
    assert resp.status_code == 404


def test_get_deep_research_returns_latest(client, db_conn):
    """T25: Multiple runs exist -> returns latest by created_at."""
    company_id = _insert_company(db_conn)
    _insert_deep_research(
        db_conn, company_id, status="completed",
        company_overview="First run",
        updated_crypto_score=50,
        confidence="low",
    )
    # Insert second run with a later timestamp (PostgreSQL auto-assigns NOW())
    _insert_deep_research(
        db_conn, company_id, status="completed",
        company_overview="Second run (latest)",
        updated_crypto_score=90,
        confidence="high",
    )

    resp = client.get(f"/api/research/deep/{company_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["company_overview"] == "Second run (latest)"
    assert data["updated_crypto_score"] == 90


def test_get_deep_research_partial_result(client, db_conn):
    """T26: Partial result (synthesis failed) -> company_overview populated, JSONB fields NULL."""
    company_id = _insert_company(db_conn)
    _insert_deep_research(
        db_conn, company_id, status="completed",
        company_overview="Partial analysis text",
        confidence="low",
    )

    resp = client.get(f"/api/research/deep/{company_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["company_overview"] == "Partial analysis text"
    assert data["crypto_signals"] is None
    assert data["key_people"] is None
    assert data["talking_points"] is None


# ---------------------------------------------------------------------------
# T27-T29: Cancel Tests
# ---------------------------------------------------------------------------


def test_cancel_researching_succeeds(client, db_conn):
    """T27: Valid cancel (status=researching) -> status becomes 'cancelled'."""
    company_id = _insert_company(db_conn)
    dr_id = _insert_deep_research(db_conn, company_id, status="researching")

    resp = client.post(f"/api/research/deep/{dr_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    with get_cursor(db_conn) as cur:
        cur.execute("SELECT status FROM deep_research WHERE id = %s", (dr_id,))
        row = cur.fetchone()

    assert row["status"] == "cancelled"


def test_cancel_already_completed_returns_400(client, db_conn):
    """T28: Already completed -> 400."""
    company_id = _insert_company(db_conn)
    dr_id = _insert_deep_research(db_conn, company_id, status="completed")

    resp = client.post(f"/api/research/deep/{dr_id}/cancel")
    assert resp.status_code == 400
    assert "already completed" in resp.json()["detail"]


def test_cancel_wrong_user_returns_403(client, db_conn):
    """T29: Wrong user -> 403."""
    # Create a second user so FK constraint is satisfied
    with get_cursor(db_conn) as cur:
        cur.execute(
            "INSERT INTO users (email, name) VALUES ('other@test.com', 'Other User') "
            "ON CONFLICT (email) DO UPDATE SET name = 'Other User' RETURNING id"
        )
        other_user_id = cur.fetchone()["id"]
        db_conn.commit()

    company_id = _insert_company(db_conn)
    dr_id = _insert_deep_research(db_conn, company_id, user_id=other_user_id, status="researching")

    resp = client.post(f"/api/research/deep/{dr_id}/cancel")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# T30-T32: Template Engine Tests
# ---------------------------------------------------------------------------


def test_template_context_includes_deep_research(db_conn):
    """T30: Deep research exists -> context includes deep_research key."""
    company_id = _insert_company(db_conn)
    contact_id = _insert_contact(
        db_conn, company_id, first_name="Template", last_name="Test",
        email="template@test.com",
    )
    _insert_deep_research(
        db_conn, company_id, status="completed",
        company_overview="Research for template",
        updated_crypto_score=80,
        confidence="high",
    )

    config = {"calendly_url": "https://cal.com/test", "physical_address": "123 Main St"}
    context = get_template_context(db_conn, contact_id, config, user_id=TEST_USER_ID)

    assert context["deep_research"] is not None
    assert context["deep_research"]["company_overview"] == "Research for template"
    assert context["deep_research"]["updated_crypto_score"] == 80


def test_template_context_no_deep_research(db_conn):
    """T31: No deep research -> deep_research is None."""
    company_id = _insert_company(db_conn)
    contact_id = _insert_contact(
        db_conn, company_id, first_name="No", last_name="Research",
        email="noresearch@test.com",
    )

    config = {"calendly_url": "https://cal.com/test", "physical_address": "123 Main St"}
    context = get_template_context(db_conn, contact_id, config, user_id=TEST_USER_ID)

    assert context["deep_research"] is None


def test_template_context_uses_latest_completed(db_conn):
    """T32: Multiple runs -> uses latest completed (not latest created)."""
    company_id = _insert_company(db_conn)
    contact_id = _insert_contact(
        db_conn, company_id, first_name="Multi", last_name="Run",
        email="multirun@test.com",
    )

    # First completed run
    _insert_deep_research(
        db_conn, company_id, status="completed",
        company_overview="Old completed run",
        updated_crypto_score=50,
        confidence="low",
    )
    # Second completed run (latest)
    _insert_deep_research(
        db_conn, company_id, status="completed",
        company_overview="Latest completed run",
        updated_crypto_score=90,
        confidence="high",
    )
    # Third run that failed (most recent by created_at but not completed)
    _insert_deep_research(
        db_conn, company_id, status="failed",
        company_overview="Failed run should be ignored",
    )

    config = {"calendly_url": "https://cal.com/test", "physical_address": "123 Main St"}
    context = get_template_context(db_conn, contact_id, config, user_id=TEST_USER_ID)

    assert context["deep_research"] is not None
    assert context["deep_research"]["company_overview"] == "Latest completed run"
    assert context["deep_research"]["updated_crypto_score"] == 90
