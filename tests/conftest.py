import sqlite3
import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = str(tmp_path / "test.db")
    yield db_path
