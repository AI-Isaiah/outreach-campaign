"""Tests for the research API routes."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.models.database import get_connection, run_migrations
from src.web.app import app
from src.web.dependencies import get_db


@pytest.fixture
def db_conn(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


@pytest.fixture
def client(tmp_db):
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


def _seed_company(conn, name="Test Fund", aum=500.0):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, firm_type, country)
           VALUES (%s, %s, %s, 'Hedge Fund', 'US') RETURNING id""",
        (name, name.lower(), aum),
    )
    conn.commit()
    return cur.fetchone()["id"]


def _create_job(conn, name="Test Job", total=3, status="pending"):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO research_jobs (name, method, total_companies, cost_estimate_usd, status)
           VALUES (%s, 'hybrid', %s, 0.033, %s) RETURNING id""",
        (name, total, status),
    )
    job_id = cur.fetchone()["id"]
    conn.commit()
    return job_id


def _create_result(conn, job_id, company_name="Alpha Fund", score=75,
                   category="likely_interested", status="completed"):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO research_results
               (job_id, company_name, crypto_score, category, evidence_summary, status)
           VALUES (%s, %s, %s, %s, 'Test evidence', %s) RETURNING id""",
        (job_id, company_name, score, category, status),
    )
    result_id = cur.fetchone()["id"]
    conn.commit()
    return result_id


# ---------- CSV Preview ----------

def test_preview_csv(client):
    csv_content = "company_name,website\nAlpha Fund,alpha.com\nBeta Capital,beta.io\n"
    resp = client.post(
        "/api/research/preview-csv",
        files={"file": ("companies.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_rows"] == 2
    assert len(data["preview"]) == 2
    assert data["stats"]["with_website"] == 2


def test_preview_csv_invalid(client):
    csv_content = "website\nalpha.com\n"
    resp = client.post(
        "/api/research/preview-csv",
        files={"file": ("bad.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 400


# ---------- Create Job ----------

@patch("src.web.routes.research.start_research_job_background")
def test_create_research_job(mock_start, client):
    csv_content = "company_name,website\nAlpha Fund,alpha.com\nBeta Capital,beta.io\n"
    resp = client.post(
        "/api/research/jobs",
        files={"file": ("companies.csv", csv_content, "text/csv")},
        data={"name": "Test Research", "method": "hybrid"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["total_companies"] == 2
    assert data["job_id"] > 0
    assert data["cost_estimate"]["total"] > 0
    assert "warnings" in data
    mock_start.assert_called_once()


@patch("src.web.routes.research.start_research_job_background")
def test_create_job_invalid_method(mock_start, client):
    csv_content = "company_name\nTest Fund\n"
    resp = client.post(
        "/api/research/jobs",
        files={"file": ("companies.csv", csv_content, "text/csv")},
        data={"name": "Test", "method": "invalid"},
    )
    assert resp.status_code == 400


@patch("src.web.routes.research.start_research_job_background")
def test_create_job_empty_csv(mock_start, client):
    csv_content = "website\nalpha.com\n"
    resp = client.post(
        "/api/research/jobs",
        files={"file": ("companies.csv", csv_content, "text/csv")},
        data={"name": "Test", "method": "hybrid"},
    )
    assert resp.status_code == 400


@patch("src.web.routes.research.start_research_job_background")
def test_create_job_blocks_concurrent(mock_start, client, db_conn):
    """Should reject if another job is already running."""
    _create_job(db_conn, "Running Job", status="researching")

    csv_content = "company_name\nNew Corp\n"
    resp = client.post(
        "/api/research/jobs",
        files={"file": ("companies.csv", csv_content, "text/csv")},
        data={"name": "Should Fail", "method": "hybrid"},
    )
    assert resp.status_code == 409
    assert "still running" in resp.json()["detail"]


@patch("src.web.routes.research.start_research_job_background")
def test_create_job_skips_duplicates(mock_start, client, db_conn):
    """Already-researched companies should be skipped by default."""
    job_id = _create_job(db_conn, "Old Job", status="completed")
    _create_result(db_conn, job_id, "Alpha Fund")

    csv_content = "company_name\nAlpha Fund\nNew Corp\n"
    resp = client.post(
        "/api/research/jobs",
        files={"file": ("companies.csv", csv_content, "text/csv")},
        data={"name": "Dedup Test", "method": "hybrid"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["total_companies"] == 1  # Only New Corp
    assert data["duplicates_skipped"] == 1
    assert len(data["warnings"]) == 1


# ---------- List Jobs ----------

def test_list_jobs_empty(client):
    resp = client.get("/api/research/jobs")
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []


def test_list_jobs(client, db_conn):
    _create_job(db_conn, "Job A", status="completed")
    _create_job(db_conn, "Job B", status="completed")
    data = client.get("/api/research/jobs").json()
    assert data["total"] == 2


# ---------- Get Job Detail ----------

def test_get_job_detail(client, db_conn):
    job_id = _create_job(db_conn, status="completed")
    _create_result(db_conn, job_id, "Alpha", 85, "confirmed_investor")
    _create_result(db_conn, job_id, "Beta", 45, "possible")

    resp = client.get(f"/api/research/jobs/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job"]["name"] == "Test Job"
    assert data["by_category"]["confirmed_investor"] == 1
    assert data["avg_score"] > 0
    assert "score_distribution" in data
    assert "error_count" in data


def test_get_job_not_found(client):
    assert client.get("/api/research/jobs/9999").status_code == 404


# ---------- Get Results ----------

def test_get_results(client, db_conn):
    job_id = _create_job(db_conn, status="completed")
    _create_result(db_conn, job_id, "Alpha", 85, "confirmed_investor")
    _create_result(db_conn, job_id, "Beta", 45, "possible")

    data = client.get(f"/api/research/jobs/{job_id}/results").json()
    assert data["total"] == 2


def test_get_results_filter_category(client, db_conn):
    job_id = _create_job(db_conn, status="completed")
    _create_result(db_conn, job_id, "Alpha", 85, "confirmed_investor")
    _create_result(db_conn, job_id, "Beta", 45, "possible")

    data = client.get(f"/api/research/jobs/{job_id}/results?category=confirmed_investor").json()
    assert data["total"] == 1


def test_get_results_filter_min_score(client, db_conn):
    job_id = _create_job(db_conn, status="completed")
    _create_result(db_conn, job_id, "Alpha", 85, "confirmed_investor")
    _create_result(db_conn, job_id, "Beta", 45, "possible")

    data = client.get(f"/api/research/jobs/{job_id}/results?min_score=60").json()
    assert data["total"] == 1


# ---------- Cancel ----------

def test_cancel_running_job(client, db_conn):
    job_id = _create_job(db_conn, status="researching")

    resp = client.post(f"/api/research/jobs/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_cancel_completed_job_fails(client, db_conn):
    job_id = _create_job(db_conn, status="completed")

    resp = client.post(f"/api/research/jobs/{job_id}/cancel")
    assert resp.status_code == 400


# ---------- Retry ----------

def test_retry_failed_job(client, db_conn):
    job_id = _create_job(db_conn, status="failed")
    _create_result(db_conn, job_id, "Failed Co", status="error")

    with patch("src.web.routes.research.start_retry_background"):
        resp = client.post(f"/api/research/jobs/{job_id}/retry")
    assert resp.status_code == 200
    assert resp.json()["retrying"] == 1


def test_retry_no_errors(client, db_conn):
    job_id = _create_job(db_conn, status="completed")
    _create_result(db_conn, job_id, "OK Co", 80, "confirmed_investor")

    resp = client.post(f"/api/research/jobs/{job_id}/retry")
    assert resp.status_code == 400


# ---------- Batch Import ----------

def test_batch_import(client, db_conn):
    job_id = _create_job(db_conn, status="completed")
    contacts = [
        {"name": "Jane Doe", "title": "CIO", "email": "jane@batch.com"},
    ]
    cur = db_conn.cursor()
    cur.execute(
        """INSERT INTO research_results (job_id, company_name, crypto_score, category,
                                          discovered_contacts_json, status)
           VALUES (%s, 'Batch Co', 80, 'confirmed_investor', %s, 'completed')
           RETURNING id""",
        (job_id, json.dumps(contacts)),
    )
    result_id = cur.fetchone()["id"]
    db_conn.commit()

    resp = client.post("/api/research/batch-import", json={
        "result_ids": [result_id],
        "create_deals": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported_contacts"] == 1
    assert data["deals_created"] == 1


def test_batch_import_empty(client):
    resp = client.post("/api/research/batch-import", json={"result_ids": []})
    assert resp.status_code == 400


# ---------- Single Result Detail ----------

def test_get_result_detail(client, db_conn):
    job_id = _create_job(db_conn, status="completed")
    result_id = _create_result(db_conn, job_id, "Detail Co", 70, "likely_interested")

    data = client.get(f"/api/research/results/{result_id}").json()
    assert data["company_name"] == "Detail Co"
    assert data["crypto_score"] == 70


def test_get_result_not_found(client):
    assert client.get("/api/research/results/9999").status_code == 404


# ---------- Import Contacts (single) ----------

def test_import_discovered_contacts(client, db_conn):
    job_id = _create_job(db_conn, status="completed")
    result_id = _create_result(db_conn, job_id, "Import Co", 80, "confirmed_investor")

    contacts = [
        {"name": "Jane Smith", "title": "CIO", "email": "jane@import.com"},
        {"name": "Bob Lee", "title": "PM", "linkedin": "https://linkedin.com/in/boblee"},
    ]
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE research_results SET discovered_contacts_json = %s WHERE id = %s",
        (json.dumps(contacts), result_id),
    )
    db_conn.commit()

    resp = client.post(f"/api/research/results/{result_id}/import-contacts", json=[0, 1])
    assert resp.status_code == 200
    assert resp.json()["imported"] == 2


# ---------- Export ----------

def test_export_results(client, db_conn):
    job_id = _create_job(db_conn, status="completed")
    _create_result(db_conn, job_id, "Export Co", 80, "confirmed_investor")

    resp = client.post(f"/api/research/jobs/{job_id}/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "Export Co" in resp.text


def test_export_with_min_score(client, db_conn):
    job_id = _create_job(db_conn, status="completed")
    _create_result(db_conn, job_id, "High", 90, "confirmed_investor")
    _create_result(db_conn, job_id, "Low", 20, "no_signal")

    resp = client.post(f"/api/research/jobs/{job_id}/export?min_score=60")
    assert "High" in resp.text
    assert "Low" not in resp.text


# ---------- Delete Job ----------

def test_delete_job(client, db_conn):
    job_id = _create_job(db_conn, status="completed")
    _create_result(db_conn, job_id)

    assert client.delete(f"/api/research/jobs/{job_id}").json()["success"] is True
    assert client.get(f"/api/research/jobs/{job_id}").status_code == 404


def test_delete_job_not_found(client):
    assert client.delete("/api/research/jobs/9999").status_code == 404
