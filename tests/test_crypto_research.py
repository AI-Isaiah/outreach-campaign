"""Tests for the crypto research service."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.services.crypto_research import (
    batch_import_and_enroll,
    check_duplicate_companies,
    classify_crypto_interest,
    crawl_company_website,
    discover_contacts_at_company,
    estimate_job_cost,
    find_warm_intros,
    parse_research_csv,
    preview_research_csv,
    research_company_web_search,
)
from src.models.database import get_connection, run_migrations
from tests.conftest import TEST_USER_ID


@pytest.fixture
def db_conn(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    yield conn
    conn.close()


# ---------- CSV Parsing ----------

def test_parse_csv_standard_headers():
    csv = "company_name,website,country\nAlpha Fund,alpha.com,US\nBeta Capital,,UK\n"
    results = parse_research_csv(csv)
    assert len(results) == 2
    assert results[0]["company_name"] == "Alpha Fund"
    assert results[0]["website"] == "alpha.com"
    assert results[1]["website"] is None


def test_parse_csv_flexible_headers():
    csv = "Firm Name,URL,AUM (Millions)\nGamma LLC,gamma.io,500\n"
    results = parse_research_csv(csv)
    assert len(results) == 1
    assert results[0]["company_name"] == "Gamma LLC"
    assert results[0]["website"] == "gamma.io"
    assert results[0]["aum"] == "500"


def test_parse_csv_missing_name_column():
    csv = "website,country\nalpha.com,US\n"
    results = parse_research_csv(csv)
    assert len(results) == 0


def test_parse_csv_skips_empty_names():
    csv = "company_name,website\n,alpha.com\nBeta Fund,beta.com\n"
    results = parse_research_csv(csv)
    assert len(results) == 1
    assert results[0]["company_name"] == "Beta Fund"


def test_parse_csv_empty():
    results = parse_research_csv("")
    assert results == []


# ---------- CSV Preview ----------

def test_preview_csv():
    csv = "company_name,website,country\nA,a.com,US\nB,b.com,UK\nC,,DE\n"
    preview = preview_research_csv(csv)
    assert preview["total_rows"] == 3
    assert len(preview["preview"]) == 3
    assert preview["stats"]["with_website"] == 2
    assert preview["stats"]["with_country"] == 3
    assert "company_name" in preview["raw_headers"]
    assert len(preview["mapped_headers"]) >= 1


def test_preview_csv_large():
    rows = "\n".join([f"Company {i},site{i}.com,US" for i in range(20)])
    csv = f"company_name,website,country\n{rows}\n"
    preview = preview_research_csv(csv)
    assert preview["total_rows"] == 20
    assert len(preview["preview"]) == 10  # Capped at 10


# ---------- Cost Estimation ----------

def test_estimate_job_cost_hybrid():
    cost = estimate_job_cost(100, "hybrid")
    assert cost["web_search_cost"] == 0.5
    assert cost["crawl_cost"] == 0.0
    assert cost["llm_cost"] == 0.1
    assert cost["contact_discovery_cost"] == 0.5
    assert cost["total"] == 1.1


def test_estimate_job_cost_web_only():
    cost = estimate_job_cost(50, "web_search")
    assert cost["web_search_cost"] == 0.25
    assert cost["crawl_cost"] == 0.0
    assert cost["total"] == 0.55


def test_estimate_job_cost_crawl_only():
    cost = estimate_job_cost(50, "website_crawl")
    assert cost["web_search_cost"] == 0.0
    assert cost["total"] == 0.3


# ---------- Duplicate Detection ----------

def test_check_duplicates_empty_db(db_conn):
    result = check_duplicate_companies(db_conn, ["Alpha Fund", "Beta Capital"])
    assert result["already_researched"] == []
    assert len(result["new"]) == 2


def test_check_duplicates_finds_existing(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO research_jobs (name, total_companies, user_id) VALUES ('old', 1, %s) RETURNING id",
        (TEST_USER_ID,),
    )
    job_id = cur.fetchone()["id"]
    cur.execute(
        "INSERT INTO research_results (job_id, company_name, status) VALUES (%s, 'Alpha Fund', 'completed')",
        (job_id,),
    )
    cur.execute("UPDATE research_jobs SET status = 'completed' WHERE id = %s", (job_id,))
    db_conn.commit()

    result = check_duplicate_companies(db_conn, ["Alpha Fund", "New Corp"])
    assert "Alpha Fund" in result["already_researched"]
    assert "New Corp" in result["new"]


# ---------- Web Search ----------

def test_research_no_api_key():
    with patch("src.services.crypto_research.PERPLEXITY_API_KEY", ""):
        result = research_company_web_search("Test Fund", "test.com")
    parsed = json.loads(result)
    assert "error" in parsed


@patch("src.services.crypto_research.httpx.post")
def test_research_web_search_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "They invest in Bitcoin"}}]
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    with patch("src.services.crypto_research.PERPLEXITY_API_KEY", "test-key"):
        result = research_company_web_search("Test Fund", "test.com")

    assert "Bitcoin" in result
    mock_post.assert_called_once()


# ---------- Website Crawl ----------

@patch("src.services.crypto_research.httpx.get")
def test_crawl_website(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body><p>We invest in digital assets</p></body></html>"
    mock_get.return_value = mock_resp

    result = crawl_company_website("https://example.com", max_pages=2)
    assert "digital assets" in result


def test_crawl_no_website():
    assert crawl_company_website("") == ""


def test_crawl_no_http_prefix():
    with patch("src.services.crypto_research.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<p>content</p>"
        mock_get.return_value = mock_resp

        crawl_company_website("example.com", max_pages=1)
        call_url = mock_get.call_args[0][0]
        assert call_url.startswith("https://")


# ---------- Classification ----------

def test_classify_no_api_key():
    with patch("src.services.crypto_research.ANTHROPIC_API_KEY", ""):
        result = classify_crypto_interest("Test Fund", "some data", "")
    assert result["crypto_score"] == 0
    assert result["category"] == "no_signal"


@patch("src.services.crypto_research.httpx.post")
def test_classify_success(mock_post):
    classification = {
        "crypto_score": 85,
        "category": "confirmed_investor",
        "evidence_summary": "Strong crypto portfolio",
        "evidence": [{"source": "Web", "quote": "Invested in BTC", "relevance": "high"}],
        "reasoning": "Clear evidence",
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"content": [{"text": json.dumps(classification)}]}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    with patch("src.services.crypto_research.ANTHROPIC_API_KEY", "test-key"):
        result = classify_crypto_interest("Test Fund", "web data", "crawl data")
    assert result["crypto_score"] == 85
    assert result["category"] == "confirmed_investor"


@patch("src.services.crypto_research.httpx.post")
def test_classify_bad_json_returns_default(mock_post):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"content": [{"text": "not valid json"}]}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    with patch("src.services.crypto_research.ANTHROPIC_API_KEY", "test-key"):
        result = classify_crypto_interest("Test Fund", "data", "")
    assert result["crypto_score"] == 20
    assert result["category"] == "no_signal"


# ---------- Contact Discovery ----------

def test_discover_no_api_key():
    with patch("src.services.crypto_research.PERPLEXITY_API_KEY", ""):
        result = discover_contacts_at_company("Test Fund", None)
    assert result == []


@patch("src.services.crypto_research.httpx.post")
def test_discover_contacts_success(mock_post):
    contacts = [
        {"name": "John Doe", "title": "CIO", "email": "john@test.com",
         "linkedin": None, "source": "LinkedIn"},
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(contacts)}}]
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    with patch("src.services.crypto_research.PERPLEXITY_API_KEY", "test-key"):
        result = discover_contacts_at_company("Test Fund", "test.com")
    assert len(result) == 1
    assert result[0]["name"] == "John Doe"


# ---------- Warm Intros ----------

def test_find_warm_intros_no_matches(db_conn):
    result = find_warm_intros(db_conn, "Nonexistent Corp", None)
    assert result["contact_ids"] == []
    assert result["notes"] is None


def test_find_warm_intros_by_company_id(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Test Co', 'test co', %s) RETURNING id",
        (TEST_USER_ID,),
    )
    company_id = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name, email,
                                 email_normalized, email_status, user_id)
           VALUES (%s, 'Alice', 'Smith', 'Alice Smith', 'alice@test.com', 'alice@test.com', 'valid', %s)
           RETURNING id""",
        (company_id, TEST_USER_ID),
    )
    contact_id = cur.fetchone()["id"]
    db_conn.commit()

    result = find_warm_intros(db_conn, "Test Co", company_id)
    assert contact_id in result["contact_ids"]
    assert "Alice Smith" in result["notes"]


def test_find_warm_intros_by_name(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Name Match LLC', 'name match llc', %s) RETURNING id",
        (TEST_USER_ID,),
    )
    company_id = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name, email,
                                 email_normalized, email_status, user_id)
           VALUES (%s, 'Bob', 'Jones', 'Bob Jones', 'bob@test.com', 'bob@test.com', 'valid', %s)""",
        (company_id, TEST_USER_ID),
    )
    db_conn.commit()

    result = find_warm_intros(db_conn, "Name Match LLC", None)
    assert len(result["contact_ids"]) == 1


# ---------- Batch Import ----------

def test_batch_import_basic(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO research_jobs (name, total_companies, user_id) VALUES ('batch_test', 1, %s) RETURNING id",
        (TEST_USER_ID,),
    )
    job_id = cur.fetchone()["id"]

    contacts = [
        {"name": "Jane Smith", "title": "CIO", "email": "jane@batch.com", "linkedin": None, "source": "web"},
    ]
    cur.execute(
        """INSERT INTO research_results (job_id, company_name, crypto_score, category,
                                          discovered_contacts_json, status)
           VALUES (%s, 'Batch Co', 80, 'confirmed_investor', %s, 'completed')
           RETURNING id""",
        (job_id, json.dumps(contacts)),
    )
    result_id = cur.fetchone()["id"]
    db_conn.commit()

    result = batch_import_and_enroll(db_conn, [result_id], user_id=TEST_USER_ID)
    assert result["imported_contacts"] == 1
    assert result["results_processed"] == 1


def test_batch_import_skips_duplicates(db_conn):
    cur = db_conn.cursor()
    # Create existing contact
    cur.execute(
        "INSERT INTO companies (name, name_normalized, user_id) VALUES ('Dup Co', 'dup co', %s) RETURNING id",
        (TEST_USER_ID,),
    )
    company_id = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO contacts (company_id, first_name, last_name, full_name,
                                 email, email_normalized, email_status, user_id)
           VALUES (%s, 'Existing', 'Person', 'Existing Person',
                   'existing@dup.com', 'existing@dup.com', 'valid', %s)""",
        (company_id, TEST_USER_ID),
    )

    cur.execute(
        "INSERT INTO research_jobs (name, total_companies, user_id) VALUES ('dup_test', 1, %s) RETURNING id",
        (TEST_USER_ID,),
    )
    job_id = cur.fetchone()["id"]
    contacts = [
        {"name": "Existing Person", "title": "CIO", "email": "existing@dup.com"},
        {"name": "New Person", "title": "PM", "email": "new@dup.com"},
    ]
    cur.execute(
        """INSERT INTO research_results (job_id, company_name, company_id,
                                          discovered_contacts_json, status)
           VALUES (%s, 'Dup Co', %s, %s, 'completed') RETURNING id""",
        (job_id, company_id, json.dumps(contacts)),
    )
    result_id = cur.fetchone()["id"]
    db_conn.commit()

    result = batch_import_and_enroll(db_conn, [result_id], user_id=TEST_USER_ID)
    # import_single_contact now returns existing contact ID on conflict
    # so both contacts are "imported" (existing one found, new one created)
    assert result["imported_contacts"] == 2
    assert result["skipped_duplicates"] == 0
