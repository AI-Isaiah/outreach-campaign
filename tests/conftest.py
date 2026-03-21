import itertools

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
            priority_rank, is_gdpr, unsubscribed, title, source)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
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
        ),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    cursor.close()
    return contact_id


@pytest.fixture(scope="session")
def _pg_instance():
    """Create a single PostgreSQL server for the entire test session."""
    import psycopg2
    import psycopg2.extras

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

    # Truncate all tables except preserved ones to ensure test isolation
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    )
    tables = [
        row["table_name"] for row in cursor.fetchall()
        if row["table_name"] not in _PRESERVED_TABLES
    ]
    if tables:
        cursor.execute(
            "TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"
        )
    cursor.close()
    conn.close()
