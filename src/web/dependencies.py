"""FastAPI dependencies for database access and config."""

from __future__ import annotations

from typing import Generator

from src.config import SUPABASE_DB_URL, load_config
from src.models.database import get_connection, run_migrations


def get_db() -> Generator:
    """Yield a database connection with migrations applied."""
    conn = get_connection(SUPABASE_DB_URL)
    run_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()


def get_config() -> dict:
    """Return the application config."""
    return load_config()
