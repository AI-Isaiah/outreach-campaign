import os

from src.models.database import get_connection, run_migrations
from src.services.deduplication import run_dedup
from tests.conftest import TEST_USER_ID, insert_company, insert_contact


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db(tmp_db):
    """Helper: create connection, run migrations, drop unique indexes so we can insert dupes."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    # Drop unique indexes and FK constraints from migration 007 so dedup tests
    # can insert duplicate contacts and verify dedup_log entries after deletion
    cursor = conn.cursor()
    cursor.execute("DROP INDEX IF EXISTS idx_contacts_email_norm_unique")
    cursor.execute("DROP INDEX IF EXISTS idx_contacts_linkedin_norm_unique")
    cursor.execute("ALTER TABLE dedup_log DROP CONSTRAINT IF EXISTS fk_dedup_kept_contact")
    cursor.execute("ALTER TABLE dedup_log DROP CONSTRAINT IF EXISTS fk_dedup_merged_contact")
    conn.commit()
    cursor.close()
    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_dedup_exact_email(tmp_db):
    """Two contacts with the same email -> one removed, one kept, count = 1."""
    conn = _setup_db(tmp_db)
    co = insert_company(conn, "Acme Corp")
    c1 = insert_contact(conn, co, email="alice@acme.com", linkedin_url=None)
    c2 = insert_contact(conn, co, email="alice@acme.com", linkedin_url=None)

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
    co = insert_company(conn, "Beta Inc")
    c1 = insert_contact(conn, co, email=None, linkedin_url="https://linkedin.com/in/bob")
    c2 = insert_contact(conn, co, email=None, linkedin_url="https://linkedin.com/in/bob/")

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
    insert_company(conn, "Falcon Capital")
    insert_company(conn, "Falcon Capital Ltd")

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
    co = insert_company(conn, "Gamma LLC")
    c1 = insert_contact(conn, co, email="dave@gamma.com", linkedin_url=None)
    c2 = insert_contact(conn, co, email="dave@gamma.com", linkedin_url=None)
    c3 = insert_contact(conn, co, email=None, linkedin_url="https://linkedin.com/in/dave")
    c4 = insert_contact(conn, co, email=None, linkedin_url="https://linkedin.com/in/dave")

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
    co = insert_company(conn, "Delta Corp")
    c1 = insert_contact(conn, co, email="eve@delta.com", linkedin_url=None, priority_rank=2)
    c2 = insert_contact(conn, co, email="eve@delta.com", linkedin_url=None, priority_rank=1)

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
    co = insert_company(conn, "Epsilon Inc")
    c1 = insert_contact(conn, co, email="frank@epsilon.com", linkedin_url="https://linkedin.com/in/frank")
    c2 = insert_contact(conn, co, email="grace@epsilon.com", linkedin_url="https://linkedin.com/in/grace")

    stats = run_dedup(conn)

    assert stats["email_dupes"] == 0
    assert stats["linkedin_dupes"] == 0

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS cnt FROM contacts")
    remaining = cursor.fetchone()
    assert remaining["cnt"] == 2

    conn.close()
