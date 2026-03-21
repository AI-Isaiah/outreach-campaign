#!/usr/bin/env python3
"""Migrate data from SQLite (outreach.db) to PostgreSQL (Supabase).

Usage:
    python3 scripts/migrate_sqlite_to_pg.py [--sqlite-path PATH] [--pg-url URL]

Defaults:
    --sqlite-path: DATABASE_PATH env or outreach.db
    --pg-url: SUPABASE_DB_URL env variable
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import psycopg2
import psycopg2.extras


# Tables in dependency order (parents before children).
TABLES = [
    "companies",
    "contacts",
    "campaigns",
    "templates",
    "sequence_steps",
    "contact_campaign_status",
    "events",
    "dedup_log",
]


def migrate(sqlite_path: str, pg_url: str) -> dict:
    """Copy all rows from SQLite to PostgreSQL.

    Returns a dict of {table_name: row_count} for each migrated table.
    """
    if not os.path.exists(sqlite_path):
        print(f"ERROR: SQLite file not found: {sqlite_path}")
        sys.exit(1)

    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    # Connect to PostgreSQL
    pg_conn = psycopg2.connect(pg_url, cursor_factory=psycopg2.extras.RealDictCursor)
    pg_cursor = pg_conn.cursor()

    stats = {}

    for table in TABLES:
        # Get column names from SQLite
        sqlite_cursor = sqlite_conn.execute(f"PRAGMA table_info({table})")
        columns = [row["name"] for row in sqlite_cursor.fetchall()]

        if not columns:
            print(f"  SKIP {table} (not found in SQLite)")
            stats[table] = 0
            continue

        # Read all rows from SQLite
        rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()

        if not rows:
            print(f"  {table}: 0 rows (empty)")
            stats[table] = 0
            continue

        # Build INSERT statement for PostgreSQL
        col_list = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))
        insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"

        # Detect boolean and timestamp columns in PG for type casting
        pg_cursor.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = %s AND table_schema = 'public'",
            (table,),
        )
        pg_col_types = {r["column_name"]: r["data_type"] for r in pg_cursor.fetchall()}
        bool_cols = {c for c in columns if pg_col_types.get(c) == "boolean"}
        ts_cols = {
            c for c in columns
            if pg_col_types.get(c) in ("timestamp with time zone", "timestamp without time zone")
        }

        # Insert rows (cast SQLite integers to PG booleans, handle timestamps)
        count = 0
        for row in rows:
            values = []
            for col in columns:
                v = row[col]
                if col in bool_cols and isinstance(v, int):
                    v = bool(v)
                if col in ts_cols and v is not None and isinstance(v, str) and v.strip() == "":
                    v = None
                values.append(v)
            try:
                pg_cursor.execute(insert_sql, tuple(values))
                count += 1
            except Exception as e:
                print(f"  WARNING: Failed to insert into {table}: {e}")
                pg_conn.rollback()
                continue

        pg_conn.commit()
        print(f"  {table}: {count} rows migrated")
        stats[table] = count

        # Reset the sequence to max(id) + 1 for tables with serial PKs
        if "id" in columns:
            pg_cursor.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"
            )
            pg_conn.commit()

    sqlite_conn.close()
    pg_conn.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite to PostgreSQL")
    parser.add_argument(
        "--sqlite-path",
        default=os.getenv("DATABASE_PATH", "outreach.db"),
        help="Path to SQLite database (default: outreach.db)",
    )
    parser.add_argument(
        "--pg-url",
        default=os.getenv("SUPABASE_DB_URL", ""),
        help="PostgreSQL connection URL (default: SUPABASE_DB_URL env)",
    )
    args = parser.parse_args()

    if not args.pg_url:
        print("ERROR: No PostgreSQL URL. Set SUPABASE_DB_URL or use --pg-url.")
        sys.exit(1)

    print(f"Migrating from {args.sqlite_path} to PostgreSQL...")
    print()

    stats = migrate(args.sqlite_path, args.pg_url)

    print()
    total = sum(stats.values())
    print(f"Done. {total} total rows migrated across {len(stats)} tables.")


if __name__ == "__main__":
    main()
