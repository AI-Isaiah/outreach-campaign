import psycopg2
import psycopg2.extras
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations" / "pg"


def get_connection(db_url: str):
    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def run_migrations(conn) -> None:
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    cursor = conn.cursor()
    for migration_file in migration_files:
        sql = migration_file.read_text().strip()
        if sql:
            cursor.execute(sql)
    conn.commit()


def get_table_names(conn) -> list[str]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public'"
    )
    return [row["table_name"] for row in cursor.fetchall()]
