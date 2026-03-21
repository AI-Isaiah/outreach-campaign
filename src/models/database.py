import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations" / "pg"

_pool = None
_pool_lock = threading.Lock()


def get_connection(db_url: str):
    """Create a single database connection (used by CLI and migrations)."""
    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def init_pool(db_url: str, minconn: int = 2, maxconn: int = 10):
    """Initialize the connection pool (call once at web app startup).

    Thread-safe: uses a lock to prevent double-initialization in
    multi-threaded ASGI servers.
    """
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn, maxconn, db_url,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
    return _pool


def get_pool_connection():
    """Get a connection from the pool. Caller must return it via put_pool_connection."""
    if _pool is None:
        raise RuntimeError("Connection pool not initialized. Call init_pool() first.")
    conn = _pool.getconn()
    conn.autocommit = False
    return conn


def put_pool_connection(conn):
    """Return a connection to the pool."""
    if _pool is not None:
        _pool.putconn(conn)


def is_pool_initialized() -> bool:
    """Check if the connection pool has been initialized."""
    return _pool is not None


def close_pool():
    """Close all connections in the pool."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def get_cursor(conn):
    """Context manager for database cursors. Ensures cursor is closed after use."""
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def run_migrations(conn) -> None:
    """Run pending SQL migrations from the pg/ directory.

    Tracks applied migrations in a ``schema_migrations`` table so each
    .sql file is executed at most once.
    """
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    with get_cursor(conn) as cursor:
        # Ensure the tracking table exists
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   filename TEXT PRIMARY KEY,
                   applied_at TIMESTAMPTZ DEFAULT NOW()
               )"""
        )
        conn.commit()

        # Fetch already-applied filenames
        cursor.execute("SELECT filename FROM schema_migrations")
        applied = {row["filename"] for row in cursor.fetchall()}

        for migration_file in migration_files:
            if migration_file.name in applied:
                continue
            sql = migration_file.read_text().strip()
            if sql:
                cursor.execute(sql)
            cursor.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (migration_file.name,),
            )
        conn.commit()


def get_table_names(conn) -> list[str]:
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        return [row["table_name"] for row in cursor.fetchall()]
