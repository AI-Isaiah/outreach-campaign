import itertools
import os

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest
import testing.postgresql

from src.models.database import get_connection, run_migrations

# Tables that should not be truncated between tests
_PRESERVED_TABLES = {"schema_migrations", "allowed_emails", "users"}

# Test user ID — always 1 (first user seeded in session-scoped PG instance).
# SERIAL resets on TRUNCATE RESTART IDENTITY CASCADE, but users table is preserved.
TEST_USER_ID = 1

# Auto-incrementing counter so each insert_contact call gets unique defaults.
_contact_counter = itertools.count(1)
_UNSET = object()


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

def insert_company(conn, name, aum_millions=None, country="US", is_gdpr=False, firm_type=None):
    """Insert a test company and return its id."""
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO companies (name, name_normalized, aum_millions, country, is_gdpr, firm_type, user_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, name.lower(), aum_millions, country, is_gdpr, firm_type, TEST_USER_ID),
    )
    company_id = cursor.fetchone()["id"]
    conn.commit()
    cursor.close()
    return company_id


def insert_contact(
    conn,
    company_id,
    first_name="Test",
    last_name="User",
    email=_UNSET,
    email_status="valid",
    linkedin_url=_UNSET,
    priority_rank=1,
    is_gdpr=False,
    unsubscribed=False,
    title=None,
    source="test",
):
    """Insert a test contact and return its id.

    When *email* or *linkedin_url* are not explicitly provided, unique default
    values are generated automatically so that multiple calls never collide.
    Pass ``None`` explicitly to leave a field NULL.
    """
    n = next(_contact_counter)
    if email is _UNSET:
        email = f"test{n}@example.com"
    if linkedin_url is _UNSET:
        linkedin_url = f"https://linkedin.com/in/test{n}"
    email_norm = email.lower().strip() if email else None
    linkedin_norm = linkedin_url.lower().rstrip("/") if linkedin_url else None
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO contacts
           (company_id, first_name, last_name, full_name,
            email, email_normalized, email_status,
            linkedin_url, linkedin_url_normalized,
            priority_rank, is_gdpr, unsubscribed, title, source, user_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (
            company_id,
            first_name,
            last_name,
            f"{first_name} {last_name}",
            email,
            email_norm,
            email_status,
            linkedin_url,
            linkedin_norm,
            priority_rank,
            is_gdpr,
            unsubscribed,
            title,
            source,
            TEST_USER_ID,
        ),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    cursor.close()
    return contact_id


_ALL_TABLES: list[str] = []


@pytest.fixture(scope="session")
def _pg_instance():
    """Create a single PostgreSQL server for the entire test session."""
    import psycopg2
    import psycopg2.extras

    global _ALL_TABLES

    with testing.postgresql.Postgresql() as pg:
        # Run migrations once to create all tables
        conn = get_connection(pg.url())
        run_migrations(conn)
        conn.close()

        # Seed a test user once (persisted across all tests via _PRESERVED_TABLES)
        conn = psycopg2.connect(pg.url(), cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = False
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (email, name) VALUES ('test@test.com', 'Test User') "
            "ON CONFLICT (email) DO NOTHING"
        )
        conn.commit()

        # Cache table names for teardown (avoids querying information_schema per test)
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        _ALL_TABLES = [row["table_name"] for row in cursor.fetchall()]

        cursor.close()
        conn.close()

        yield pg


@pytest.fixture
def tmp_db(_pg_instance):
    """Yield a PostgreSQL URL; truncate all tables after each test for isolation."""
    import psycopg2
    import psycopg2.extras

    url = _pg_instance.url()
    yield url

    # Terminate all other connections (prevents deadlock from unclosed test connections)
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = current_database() AND pid != pg_backend_pid()"
    )

    # Delete from all tables except preserved ones to ensure test isolation.
    # DELETE + sequence reset is ~100x faster than TRUNCATE for small test
    # datasets because TRUNCATE acquires AccessExclusiveLock per table.
    # session_replication_role=replica disables FK trigger checks during delete.
    tables_to_clean = [t for t in _ALL_TABLES if t not in _PRESERVED_TABLES]
    if tables_to_clean:
        stmts = ["SET session_replication_role = 'replica'"]
        stmts.extend(f"DELETE FROM {t}" for t in tables_to_clean)
        stmts.append("SET session_replication_role = 'origin'")
        # Reset sequences for cleaned tables (exclude preserved table sequences)
        preserved_seq_prefixes = tuple(f"{t}_" for t in _PRESERVED_TABLES)
        stmts.append(
            "SELECT setval(c.oid, 1, false) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'S' AND n.nspname = 'public' "
            "AND c.relname NOT LIKE 'users_%%' "
            "AND c.relname NOT LIKE 'schema_migrations_%%' "
            "AND c.relname NOT LIKE 'allowed_emails_%%'"
        )
        cursor.execute("; ".join(stmts))
    cursor.close()
    conn.close()
