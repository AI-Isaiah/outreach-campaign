#!/usr/bin/env python3
"""Lint: detect NEW SQL queries on user-owned tables that lack user_id scoping.

Uses a ratchet pattern: maintains a baseline count of known unscoped queries.
Fails CI only if the count increases (new unscoped queries introduced).
Run with --update-baseline to accept the current count.

Usage:
    python3 scripts/lint_tenancy.py              # Check (fail if count > baseline)
    python3 scripts/lint_tenancy.py --update-baseline  # Update baseline
    python3 scripts/lint_tenancy.py --list        # List all unscoped queries
"""

import re
import sys
from pathlib import Path

OWNED_TABLES = {
    "companies", "contacts", "campaigns", "templates", "tags",
    "products", "newsletters", "research_jobs", "deep_research",
    "deals", "events", "dedup_log", "engine_config", "message_drafts",
}

SCAN_DIRS = [
    Path("src/services"),
    Path("src/web/routes"),
    Path("src/application"),
]

BASELINE_FILE = Path("scripts/.tenancy_baseline")

SQL_PATTERN = re.compile(
    r'(?:cur\.execute|cursor\.execute)\s*\(\s*'
    r'(?:f?"""(.+?)"""|f?"([^"]+)"|f?\'\'\'(.+?)\'\'\'|f?\'([^\']+)\')',
    re.DOTALL,
)


def references_owned_table(sql: str) -> str | None:
    sql_lower = sql.lower()
    for table in OWNED_TABLES:
        for prefix in (r"\bfrom\s+", r"\bjoin\s+", r"\binto\s+", r"\bupdate\s+"):
            if re.search(prefix + table + r"\b", sql_lower):
                return table
    return None


def is_scoped(sql: str) -> bool:
    return "user_id" in sql.lower()


def find_unscoped(filepath: Path) -> list[tuple[int, str, str]]:
    content = filepath.read_text()
    results = []
    for match in SQL_PATTERN.finditer(content):
        sql = match.group(1) or match.group(2) or match.group(3) or match.group(4)
        table = references_owned_table(sql)
        if table and not is_scoped(sql):
            line_no = content[:match.start()].count("\n") + 1
            results.append((line_no, table, sql[:100].strip()))
    return results


def scan_all() -> list[tuple[Path, int, str, str]]:
    violations = []
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for filepath in sorted(scan_dir.rglob("*.py")):
            for line_no, table, preview in find_unscoped(filepath):
                violations.append((filepath, line_no, table, preview))
    return violations


def main() -> int:
    update = "--update-baseline" in sys.argv
    list_all = "--list" in sys.argv

    violations = scan_all()
    current_count = len(violations)

    if list_all:
        print(f"TENANCY LINT: {current_count} unscoped queries\n")
        for fp, ln, table, preview in violations:
            print(f"  {fp}:{ln} [{table}] {preview}")
        return 0

    if update:
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_FILE.write_text(str(current_count))
        print(f"TENANCY BASELINE: updated to {current_count}")
        return 0

    # Ratchet check
    baseline = 0
    if BASELINE_FILE.exists():
        baseline = int(BASELINE_FILE.read_text().strip())

    if current_count > baseline:
        new_count = current_count - baseline
        print(f"TENANCY LINT FAILED: {new_count} new unscoped queries (was {baseline}, now {current_count})\n")
        # Show only the likely-new ones (last N)
        for fp, ln, table, preview in violations[-new_count:]:
            print(f"  {fp}:{ln} [{table}] {preview}")
        print(f"\nFix the queries or run: python3 scripts/lint_tenancy.py --update-baseline")
        return 1

    if current_count < baseline:
        print(f"TENANCY LINT: improved! {baseline} -> {current_count}. Updating baseline.")
        BASELINE_FILE.write_text(str(current_count))

    print(f"TENANCY LINT: OK ({current_count} known, baseline {baseline})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
