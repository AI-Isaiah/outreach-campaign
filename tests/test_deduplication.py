import os

from src.models.database import get_connection, run_migrations
from src.services.deduplication import run_dedup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db(tmp_db):
    """Helper: create connection, run migrations, return conn."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


def _insert_company(conn, name, country="United States"):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO companies (name, name_normalized, country, is_gdpr) VALUES (%s, %s, %s, false) RETURNING id",
        (name, name.lower(), country),
    )
    company_id = cursor.fetchone()["id"]
    conn.commit()
    return company_id


def _insert_contact(conn, company_id, email=None, linkedin=None, rank=1):
    email_norm = email.lower().strip() if email else None
    li_norm = linkedin.lower().rstrip("/").split("?")[0] if linkedin else None
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO contacts
           (company_id, full_name, email, email_normalized,
            linkedin_url, linkedin_url_normalized, priority_rank, source, is_gdpr)
           VALUES (%s, 'Test Person', %s, %s, %s, %s, %s, 'test', false) RETURNING id""",
        (company_id, email, email_norm, linkedin, li_norm, rank),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    return contact_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_dedup_exact_email(tmp_db):
    """Two contacts with the same email -> one removed, one kept, count = 1."""
    conn = _setup_db(tmp_db)
    co = _insert_company(conn, "Acme Corp")
    c1 = _insert_contact(conn, co, email="alice@acme.com")
    c2 = _insert_contact(conn, co, email="alice@acme.com")

    stats = run_dedup(conn)

    assert stats["email_dupes"] == 1

    cursor = conn.cursor()
    cursor.execute("SELECT id FROM contacts ORDER BY id")
    remaining = cursor.fetchall()
    remaining_ids = [r["id"] for r in remaining]
    assert c1 in remaining_ids
    assert c2 not in remaining_ids

    conn.close()


def test_dedup_exact_linkedin(tmp_db):
    """Two contacts with the same LinkedIn URL (trailing slash variant) -> one removed."""
    conn = _setup_db(tmp_db)
    co = _insert_company(conn, "Beta Inc")
    c1 = _insert_contact(conn, co, linkedin="https://linkedin.com/in/bob")
    c2 = _insert_contact(conn, co, linkedin="https://linkedin.com/in/bob/")

    stats = run_dedup(conn)

    assert stats["linkedin_dupes"] == 1

    cursor = conn.cursor()
    cursor.execute("SELECT id FROM contacts ORDER BY id")
    remaining = cursor.fetchall()
    remaining_ids = [r["id"] for r in remaining]
    assert c1 in remaining_ids
    assert c2 not in remaining_ids

    conn.close()


def test_dedup_fuzzy_company_flagged(tmp_db, tmp_path):
    """'Falcon Capital' vs 'Falcon Capital Ltd' should be flagged (score >= 85)."""
    conn = _setup_db(tmp_db)
    _insert_company(conn, "Falcon Capital")
    _insert_company(conn, "Falcon Capital Ltd")

    export_dir = str(tmp_path / "export")
    os.makedirs(export_dir, exist_ok=True)

    stats = run_dedup(conn, export_dir=export_dir)

    assert stats["fuzzy_flagged"] >= 1

    # Check CSV was written
    csv_path = os.path.join(export_dir, "dedup_review.csv")
    assert os.path.exists(csv_path)

    with open(csv_path) as f:
        content = f.read()
    assert "Falcon Capital" in content

    conn.close()


def test_dedup_logs_actions(tmp_db):
    """dedup_log table has correct entries after dedup."""
    conn = _setup_db(tmp_db)
    co = _insert_company(conn, "Gamma LLC")
    c1 = _insert_contact(conn, co, email="dave@gamma.com")
    c2 = _insert_contact(conn, co, email="dave@gamma.com")
    c3 = _insert_contact(conn, co, linkedin="https://linkedin.com/in/dave")
    c4 = _insert_contact(conn, co, linkedin="https://linkedin.com/in/dave")

    run_dedup(conn)

    cursor = conn.cursor()
    cursor.execute(
        "SELECT kept_contact_id, merged_contact_id, match_type, match_score "
        "FROM dedup_log ORDER BY id"
    )
    logs = cursor.fetchall()

    assert len(logs) >= 2

    email_logs = [l for l in logs if l["match_type"] == "exact_email"]
    assert len(email_logs) == 1
    assert email_logs[0]["kept_contact_id"] == c1
    assert email_logs[0]["merged_contact_id"] == c2
    assert email_logs[0]["match_score"] == 1.0

    linkedin_logs = [l for l in logs if l["match_type"] == "exact_linkedin"]
    assert len(linkedin_logs) == 1
    assert linkedin_logs[0]["kept_contact_id"] == c3
    assert linkedin_logs[0]["merged_contact_id"] == c4
    assert linkedin_logs[0]["match_score"] == 1.0

    conn.close()


def test_dedup_keeps_first_contact(tmp_db):
    """The contact with the lower id is kept."""
    conn = _setup_db(tmp_db)
    co = _insert_company(conn, "Delta Corp")
    c1 = _insert_contact(conn, co, email="eve@delta.com", rank=2)
    c2 = _insert_contact(conn, co, email="eve@delta.com", rank=1)

    run_dedup(conn)

    cursor = conn.cursor()
    cursor.execute("SELECT id FROM contacts ORDER BY id")
    remaining = cursor.fetchall()
    remaining_ids = [r["id"] for r in remaining]
    assert c1 in remaining_ids  # lower id kept even though rank is higher
    assert c2 not in remaining_ids

    conn.close()


def test_dedup_no_false_positives(tmp_db):
    """Contacts with different emails/linkedins are NOT removed."""
    conn = _setup_db(tmp_db)
    co = _insert_company(conn, "Epsilon Inc")
    c1 = _insert_contact(conn, co, email="frank@epsilon.com", linkedin="https://linkedin.com/in/frank")
    c2 = _insert_contact(conn, co, email="grace@epsilon.com", linkedin="https://linkedin.com/in/grace")

    stats = run_dedup(conn)

    assert stats["email_dupes"] == 0
    assert stats["linkedin_dupes"] == 0

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS cnt FROM contacts")
    remaining = cursor.fetchone()
    assert remaining["cnt"] == 2

    conn.close()
