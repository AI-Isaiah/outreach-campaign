import pytest
import testing.postgresql

from src.models.database import get_connection, run_migrations


@pytest.fixture(scope="session")
def _pg_instance():
    """Create a single PostgreSQL server for the entire test session."""
    with testing.postgresql.Postgresql() as pg:
        # Run migrations once to create all tables
        conn = get_connection(pg.url())
        run_migrations(conn)
        conn.close()
        yield pg


@pytest.fixture
def tmp_db(_pg_instance):
    """Yield a PostgreSQL URL; truncate all tables after each test for isolation."""
    import psycopg2
    import psycopg2.extras

    url = _pg_instance.url()
    yield url

    # Truncate all tables to ensure test isolation
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    )
    tables = [row["table_name"] for row in cursor.fetchall()]
    if tables:
        cursor.execute(
            "TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"
        )
    conn.close()
