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


def test_foreign_keys_enforced(tmp_db):
    """PostgreSQL enforces foreign keys by default."""
    import psycopg2
    conn = get_connection(tmp_db)
    run_migrations(conn)
    cursor = conn.cursor()
    # Try to insert a contact referencing a non-existent company
    with pytest.raises(psycopg2.IntegrityError):
        cursor.execute(
            "INSERT INTO contacts (company_id, first_name, source) VALUES (%s, %s, %s)",
            (99999, "Test", "csv"),
        )
    conn.rollback()
    conn.close()


def test_migrations_are_idempotent(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    run_migrations(conn)  # should not fail
    tables = get_table_names(conn)
    assert "companies" in tables
    conn.close()


import pytest
