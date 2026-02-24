from src.models.database import get_connection, run_migrations, get_table_names


def test_run_migrations_creates_tables(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    tables = get_table_names(conn)
    assert "companies" in tables
    assert "contacts" in tables
    assert "campaigns" in tables
    assert "sequence_steps" in tables
    assert "templates" in tables
    assert "contact_campaign_status" in tables
    assert "events" in tables
    assert "dedup_log" in tables
    conn.close()


def test_wal_mode_enabled(tmp_db):
    conn = get_connection(tmp_db)
    result = conn.execute("PRAGMA journal_mode").fetchone()
    assert result[0] == "wal"
    conn.close()


def test_foreign_keys_enabled(tmp_db):
    conn = get_connection(tmp_db)
    result = conn.execute("PRAGMA foreign_keys").fetchone()
    assert result[0] == 1
    conn.close()


def test_migrations_are_idempotent(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    run_migrations(conn)  # should not fail
    tables = get_table_names(conn)
    assert "companies" in tables
    conn.close()
