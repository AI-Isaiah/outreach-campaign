"""3-pass deduplication pipeline for contacts and companies."""

from __future__ import annotations

import csv
import logging
import os
import sqlite3
from itertools import combinations

from thefuzz import fuzz

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 85


def run_dedup(conn: sqlite3.Connection, export_dir: str | None = None) -> dict:
    """Run the 3-pass deduplication pipeline.

    Pass 1: Exact email match
    Pass 2: Exact LinkedIn URL match
    Pass 3: Fuzzy company name match (flag only, no deletes)

    Returns a dict with counts: email_dupes, linkedin_dupes, fuzzy_flagged.
    """
    email_dupes = _pass_exact_email(conn)
    linkedin_dupes = _pass_exact_linkedin(conn)
    fuzzy_flagged = _pass_fuzzy_company(conn, export_dir)

    return {
        "email_dupes": email_dupes,
        "linkedin_dupes": linkedin_dupes,
        "fuzzy_flagged": fuzzy_flagged,
    }


def _pass_exact_email(conn: sqlite3.Connection) -> int:
    """Pass 1: find contacts sharing the same email_normalized, keep lowest id."""
    dupes_removed = 0

    rows = conn.execute(
        """SELECT email_normalized, GROUP_CONCAT(id) AS ids
           FROM contacts
           WHERE email_normalized IS NOT NULL AND email_normalized != ''
           GROUP BY email_normalized
           HAVING COUNT(*) > 1"""
    ).fetchall()

    for row in rows:
        ids = sorted(int(i) for i in row["ids"].split(","))
        keep_id = ids[0]
        remove_ids = ids[1:]

        for rid in remove_ids:
            conn.execute(
                "INSERT INTO dedup_log (kept_contact_id, merged_contact_id, match_type, match_score) "
                "VALUES (?, ?, 'exact_email', 1.0)",
                (keep_id, rid),
            )
            conn.execute("DELETE FROM contacts WHERE id = ?", (rid,))
            dupes_removed += 1
            logger.info("Dedup exact_email: kept %d, removed %d", keep_id, rid)

    conn.commit()
    return dupes_removed


def _pass_exact_linkedin(conn: sqlite3.Connection) -> int:
    """Pass 2: find contacts sharing the same linkedin_url_normalized, keep lowest id."""
    dupes_removed = 0

    rows = conn.execute(
        """SELECT linkedin_url_normalized, GROUP_CONCAT(id) AS ids
           FROM contacts
           WHERE linkedin_url_normalized IS NOT NULL AND linkedin_url_normalized != ''
           GROUP BY linkedin_url_normalized
           HAVING COUNT(*) > 1"""
    ).fetchall()

    for row in rows:
        ids = sorted(int(i) for i in row["ids"].split(","))
        keep_id = ids[0]
        remove_ids = ids[1:]

        for rid in remove_ids:
            conn.execute(
                "INSERT INTO dedup_log (kept_contact_id, merged_contact_id, match_type, match_score) "
                "VALUES (?, ?, 'exact_linkedin', 1.0)",
                (keep_id, rid),
            )
            conn.execute("DELETE FROM contacts WHERE id = ?", (rid,))
            dupes_removed += 1
            logger.info("Dedup exact_linkedin: kept %d, removed %d", keep_id, rid)

    conn.commit()
    return dupes_removed


def _pass_fuzzy_company(conn: sqlite3.Connection, export_dir: str | None) -> int:
    """Pass 3: fuzzy match company names, flag for manual review (no deletes)."""
    rows = conn.execute(
        "SELECT id, name, name_normalized FROM companies ORDER BY id"
    ).fetchall()

    flagged_pairs: list[dict] = []

    for (id_a, name_a, norm_a), (id_b, name_b, norm_b) in combinations(rows, 2):
        score = fuzz.token_sort_ratio(norm_a, norm_b)
        if score >= FUZZY_THRESHOLD:
            flagged_pairs.append(
                {
                    "company_a_id": id_a,
                    "company_a_name": name_a,
                    "company_b_id": id_b,
                    "company_b_name": name_b,
                    "score": score,
                }
            )
            logger.info(
                "Dedup fuzzy_company: '%s' (id=%d) ~ '%s' (id=%d) score=%d",
                name_a, id_a, name_b, id_b, score,
            )

    if export_dir and flagged_pairs:
        csv_path = os.path.join(export_dir, "dedup_review.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["company_a_id", "company_a_name", "company_b_id", "company_b_name", "score"],
            )
            writer.writeheader()
            writer.writerows(flagged_pairs)
        logger.info("Wrote %d fuzzy matches to %s", len(flagged_pairs), csv_path)

    return len(flagged_pairs)
