from unittest.mock import patch, MagicMock

from src.models.database import get_connection, run_migrations
from src.services.email_verifier import (
    get_unverified_emails,
    update_contact_email_status,
    verify_email_batch,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _insert_contact_with_email(conn, email, status="unverified"):
    conn.execute(
        "INSERT INTO companies (name, name_normalized, country, is_gdpr) VALUES ('X', 'x', 'US', 0)"
    )
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO contacts (company_id, full_name, email, email_normalized, email_status, priority_rank, source, is_gdpr)
           VALUES (?, 'Test', ?, ?, ?, 1, 'test', 0)""",
        (cid, email, email.lower() if email else None, status),
    )
    conn.commit()


def _setup_db(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


# ---------------------------------------------------------------------------
# update_contact_email_status
# ---------------------------------------------------------------------------

def test_update_contact_status_valid(tmp_db):
    conn = _setup_db(tmp_db)
    _insert_contact_with_email(conn, "alice@example.com", status="unverified")

    update_contact_email_status(conn, "alice@example.com", "valid")

    row = conn.execute(
        "SELECT email_status FROM contacts WHERE email_normalized = ?",
        ("alice@example.com",),
    ).fetchone()
    assert row["email_status"] == "valid"
    conn.close()


def test_update_contact_status_invalid(tmp_db):
    conn = _setup_db(tmp_db)
    _insert_contact_with_email(conn, "bad@example.com", status="unverified")

    update_contact_email_status(conn, "bad@example.com", "invalid")

    row = conn.execute(
        "SELECT email_status FROM contacts WHERE email_normalized = ?",
        ("bad@example.com",),
    ).fetchone()
    assert row["email_status"] == "invalid"
    conn.close()


# ---------------------------------------------------------------------------
# get_unverified_emails
# ---------------------------------------------------------------------------

def test_get_unverified_emails(tmp_db):
    conn = _setup_db(tmp_db)
    _insert_contact_with_email(conn, "one@example.com", status="unverified")
    _insert_contact_with_email(conn, "two@example.com", status="unverified")

    result = get_unverified_emails(conn)

    assert sorted(result) == ["one@example.com", "two@example.com"]
    conn.close()


def test_get_unverified_emails_excludes_verified(tmp_db):
    conn = _setup_db(tmp_db)
    _insert_contact_with_email(conn, "verified@example.com", status="valid")
    _insert_contact_with_email(conn, "unverified@example.com", status="unverified")

    result = get_unverified_emails(conn)

    assert result == ["unverified@example.com"]
    conn.close()


def test_get_unverified_emails_excludes_null(tmp_db):
    conn = _setup_db(tmp_db)
    _insert_contact_with_email(conn, None, status="unverified")
    _insert_contact_with_email(conn, "real@example.com", status="unverified")

    result = get_unverified_emails(conn)

    assert result == ["real@example.com"]
    conn.close()


# ---------------------------------------------------------------------------
# verify_email_batch -- ZeroBounce (mocked)
# ---------------------------------------------------------------------------

@patch("src.services.email_verifier.httpx")
def test_verify_batch_zerobounce_mock(mock_httpx):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "email_batch": [
            {"address": "good@test.com", "status": "valid"},
            {"address": "bad@test.com", "status": "invalid"},
            {"address": "trap@test.com", "status": "spamtrap"},
            {"address": "abuse@test.com", "status": "abuse"},
            {"address": "dnd@test.com", "status": "do_not_mail"},
            {"address": "catch@test.com", "status": "catch-all"},
            {"address": "other@test.com", "status": "something_else"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_httpx.post.return_value = mock_response

    emails = [
        "good@test.com",
        "bad@test.com",
        "trap@test.com",
        "abuse@test.com",
        "dnd@test.com",
        "catch@test.com",
        "other@test.com",
    ]
    result = verify_email_batch(emails, api_key="fake-key", provider="zerobounce")

    assert result["good@test.com"] == "valid"
    assert result["bad@test.com"] == "invalid"
    assert result["trap@test.com"] == "invalid"
    assert result["abuse@test.com"] == "invalid"
    assert result["dnd@test.com"] == "invalid"
    assert result["catch@test.com"] == "catch-all"
    assert result["other@test.com"] == "risky"


# ---------------------------------------------------------------------------
# verify_email_batch -- Hunter (mocked)
# ---------------------------------------------------------------------------

@patch("src.services.email_verifier.httpx")
@patch("src.services.email_verifier.time")
def test_verify_batch_hunter_mock(mock_time, mock_httpx):
    def _mock_get(url, params=None):
        email = params["email"]
        status_map = {
            "good@test.com": "valid",
            "bad@test.com": "invalid",
            "catch@test.com": "accept_all",
            "other@test.com": "something_else",
        }
        resp = MagicMock()
        resp.json.return_value = {
            "data": {"status": status_map.get(email, "unknown")}
        }
        resp.raise_for_status = MagicMock()
        return resp

    mock_httpx.get.side_effect = _mock_get

    emails = ["good@test.com", "bad@test.com", "catch@test.com", "other@test.com"]
    result = verify_email_batch(emails, api_key="fake-key", provider="hunter")

    assert result["good@test.com"] == "valid"
    assert result["bad@test.com"] == "invalid"
    assert result["catch@test.com"] == "catch-all"
    assert result["other@test.com"] == "risky"
