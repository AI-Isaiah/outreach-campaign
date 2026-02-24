from pathlib import Path

from src.commands.import_emails import import_pasted_emails, parse_email_line
from src.models.database import get_connection, run_migrations

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# parse_email_line unit tests
# ---------------------------------------------------------------------------

def test_parse_bare_email():
    name, email = parse_email_line("adam@bbscapital.com,")
    assert name is None
    assert email == "adam@bbscapital.com"


def test_parse_named_email():
    name, email = parse_email_line("Bo Zhou <bo@firinnecapital.com>,")
    assert name == "Bo Zhou"
    assert email == "bo@firinnecapital.com"


def test_parse_quoted_email():
    """When the 'name' part is actually an email address in quotes, return name=None."""
    name, email = parse_email_line('"jason@velvetfs.com" <jason@velvetfs.com>,')
    assert name is None
    assert email == "jason@velvetfs.com"


def test_parse_named_with_dots():
    name, email = parse_email_line('"Josh J. Anderson" <josh@geometricholdings.net>,')
    assert name == "Josh J. Anderson"
    assert email == "josh@geometricholdings.net"


def test_parse_empty_line():
    name, email = parse_email_line("")
    assert name is None
    assert email is None


def test_parse_whitespace_only():
    name, email = parse_email_line("   \n  ")
    assert name is None
    assert email is None


# ---------------------------------------------------------------------------
# import_pasted_emails integration tests
# ---------------------------------------------------------------------------

def test_import_pasted_emails(tmp_db):
    """Importing the sample fixture should create at least 7 contacts."""
    conn = get_connection(tmp_db)
    run_migrations(conn)

    fixture_path = str(FIXTURES_DIR / "sample_pasted_emails.txt")
    stats = import_pasted_emails(conn, fixture_path)

    assert stats["contacts_created"] >= 7

    cursor = conn.execute("SELECT COUNT(*) FROM contacts")
    count = cursor.fetchone()[0]
    assert count >= 7

    conn.close()


def test_import_extracts_company_from_domain(tmp_db):
    """Bo Zhou's company should be derived from the email domain firinnecapital.com."""
    conn = get_connection(tmp_db)
    run_migrations(conn)

    fixture_path = str(FIXTURES_DIR / "sample_pasted_emails.txt")
    import_pasted_emails(conn, fixture_path)

    row = conn.execute(
        "SELECT c.name_normalized FROM companies c "
        "JOIN contacts ct ON ct.company_id = c.id "
        "WHERE ct.email_normalized = ?",
        ("bo@firinnecapital.com",),
    ).fetchone()

    assert row is not None
    assert "firinnecapital" in row[0]

    conn.close()


def test_import_skips_duplicate_emails(tmp_db):
    """Importing the same file twice should not create duplicate contacts."""
    conn = get_connection(tmp_db)
    run_migrations(conn)

    fixture_path = str(FIXTURES_DIR / "sample_pasted_emails.txt")
    stats_first = import_pasted_emails(conn, fixture_path)
    stats_second = import_pasted_emails(conn, fixture_path)

    assert stats_first["contacts_created"] >= 7
    assert stats_second["contacts_created"] == 0

    cursor = conn.execute("SELECT COUNT(*) FROM contacts")
    count = cursor.fetchone()[0]
    # Should be exactly the same as the first run
    assert count == stats_first["contacts_created"]

    conn.close()


def test_import_sets_source(tmp_db):
    """All imported contacts should have source='pasted_emails'."""
    conn = get_connection(tmp_db)
    run_migrations(conn)

    fixture_path = str(FIXTURES_DIR / "sample_pasted_emails.txt")
    import_pasted_emails(conn, fixture_path)

    rows = conn.execute(
        "SELECT DISTINCT source FROM contacts"
    ).fetchall()

    sources = [r[0] for r in rows]
    assert sources == ["pasted_emails"]

    conn.close()


def test_import_stats_lines_processed(tmp_db):
    """Stats should report the total number of lines processed."""
    conn = get_connection(tmp_db)
    run_migrations(conn)

    fixture_path = str(FIXTURES_DIR / "sample_pasted_emails.txt")
    stats = import_pasted_emails(conn, fixture_path)

    assert stats["lines_processed"] >= 8
    assert "lines_skipped" in stats

    conn.close()
