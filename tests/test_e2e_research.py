"""E2E tests for the crypto research pipeline — job lifecycle, cancel, contact import."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import psycopg2
import psycopg2.extras
import pytest

from src.models.database import get_connection, get_cursor, run_migrations
from src.services.crypto_research import (
    cancel_research_job,
    _execute_research_job,
    import_single_contact,
)
from tests.conftest import TEST_USER_ID, insert_company


def _conn(tmp_db):
    """Get a fresh connection from the test DB URL."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


def _create_research_job(conn, name="test_job", method="web_search", total=1):
    """Insert a research job and return its id."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO research_jobs (name, method, total_companies, user_id)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (name, method, total, TEST_USER_ID),
        )
        job_id = cur.fetchone()["id"]
        conn.commit()
    return job_id


def _create_research_result(conn, job_id, company_name, company_id=None, website=None):
    """Insert a research result row and return its id."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO research_results (job_id, company_id, company_name, company_website)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (job_id, company_id, company_name, website),
        )
        result_id = cur.fetchone()["id"]
        conn.commit()
    return result_id


# ---------------------------------------------------------------------------
# 8. Research job lifecycle
# ---------------------------------------------------------------------------


def test_research_job_lifecycle(tmp_db):
    """Create job -> mock APIs -> run _execute_research_job -> verify results stored."""
    conn = _conn(tmp_db)

    job_id = _create_research_job(conn, "lifecycle_job", method="web_search", total=1)
    result_id = _create_research_result(conn, job_id, "CryptoVentures LLC", website="https://cryptoventures.io")

    # Mock the external API calls
    mock_web_search = "CryptoVentures is a blockchain investment fund focusing on DeFi protocols."
    mock_classification = {
        "crypto_score": 85,
        "category": "confirmed_investor",
        "evidence_summary": "Active blockchain investment fund",
        "evidence": [{"source": "web", "text": "DeFi fund"}],
        "reasoning": "Strong crypto signals from web presence",
    }
    mock_contacts = [
        {"name": "John Crypto", "title": "CIO", "email": "john@cryptoventures.io"},
    ]

    with (
        patch("src.services.crypto_research_orchestrator.research_company_web_search",
              return_value=mock_web_search),
        patch("src.services.crypto_research_orchestrator.classify_crypto_interest",
              return_value=mock_classification),
        patch("src.services.crypto_research_orchestrator.discover_contacts_at_company",
              return_value=mock_contacts),
        patch("src.services.crypto_research_orchestrator.time.sleep"),
    ):
        _execute_research_job(conn, job_id, api_keys={"perplexity": "fake", "anthropic": "fake"})

    # Verify job status is completed
    with get_cursor(conn) as cur:
        cur.execute("SELECT * FROM research_jobs WHERE id = %s", (job_id,))
        job = cur.fetchone()
    assert job["status"] == "completed"

    # Verify result has crypto_score and category
    with get_cursor(conn) as cur:
        cur.execute("SELECT * FROM research_results WHERE id = %s", (result_id,))
        result = cur.fetchone()
    assert result["crypto_score"] == 85
    assert result["category"] == "confirmed_investor"
    assert result["evidence_summary"] is not None
    assert result["discovered_contacts_json"] is not None

    conn.close()


# ---------------------------------------------------------------------------
# 9. Research job cancel
# ---------------------------------------------------------------------------


def test_research_job_cancel(tmp_db):
    """Cancel a pending job. Verify status. Try to cancel a completed job -> error."""
    conn = _conn(tmp_db)

    # Create a pending job and cancel it
    job_id = _create_research_job(conn, "cancel_job")
    result = cancel_research_job(conn, job_id, user_id=TEST_USER_ID)
    assert result["success"] is True

    with get_cursor(conn) as cur:
        cur.execute("SELECT status FROM research_jobs WHERE id = %s", (job_id,))
        assert cur.fetchone()["status"] == "cancelled"

    # Try to cancel the already-cancelled job
    result2 = cancel_research_job(conn, job_id, user_id=TEST_USER_ID)
    assert result2["success"] is False
    assert "already" in result2["error"].lower()

    # Create and complete a job, then try to cancel
    job_id2 = _create_research_job(conn, "completed_job")
    with get_cursor(conn) as cur:
        cur.execute(
            "UPDATE research_jobs SET status = 'completed', completed_at = NOW() WHERE id = %s",
            (job_id2,),
        )
        conn.commit()

    result3 = cancel_research_job(conn, job_id2, user_id=TEST_USER_ID)
    assert result3["success"] is False
    assert "already" in result3["error"].lower()

    conn.close()


# ---------------------------------------------------------------------------
# 10. Research contact import
# ---------------------------------------------------------------------------


def test_research_contact_import(tmp_db):
    """Import a discovered contact from research into CRM with company link."""
    conn = _conn(tmp_db)

    # Create a company
    company_id = insert_company(conn, "ImportTarget Inc")

    # Create the research job + result with discovered contacts
    job_id = _create_research_job(conn, "import_job")
    discovered_contacts = [
        {
            "name": "Sarah Importer",
            "title": "Head of Investments",
            "email": "sarah@importtarget.com",
            "linkedin": "https://linkedin.com/in/sarahimporter",
        }
    ]
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO research_results
               (job_id, company_id, company_name, discovered_contacts_json, status)
               VALUES (%s, %s, %s, %s, 'completed') RETURNING id""",
            (job_id, company_id, "ImportTarget Inc", json.dumps(discovered_contacts)),
        )
        result_id = cur.fetchone()["id"]
        conn.commit()

    # Import the contact using the service function
    with get_cursor(conn) as cur:
        contact_id = import_single_contact(
            cur, discovered_contacts[0], company_id, user_id=TEST_USER_ID,
        )
        conn.commit()

    assert contact_id is not None

    # Verify the contact is in the CRM with correct company link
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM contacts WHERE id = %s AND user_id = %s",
            (contact_id, TEST_USER_ID),
        )
        contact = cur.fetchone()

    assert contact is not None
    assert contact["company_id"] == company_id
    assert contact["first_name"] == "Sarah"
    assert contact["last_name"] == "Importer"
    assert contact["email_normalized"] == "sarah@importtarget.com"
    assert contact["source"] == "research"

    conn.close()
