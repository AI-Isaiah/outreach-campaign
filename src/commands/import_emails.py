"""Import contacts from a pasted email list with mixed formats.

Supported line formats:
  - Bare email:          adam@bbscapital.com,
  - Named:               Bo Zhou <bo@firinnecapital.com>,
  - Quoted email as name: "jason@velvetfs.com" <jason@velvetfs.com>,
  - Named with quotes:   "Josh J. Anderson" <josh@geometricholdings.net>,
  - Bare email trailing:  jay@aerostatum.com" <jay@aerostatum.com>,
"""

from __future__ import annotations

import re
from typing import Optional

from src.models.database import get_cursor

from src.services.normalization_utils import (
    normalize_company_name as _normalize_company_name,
    normalize_email as _normalize_email,
    split_name as _split_name,
)


# ---------------------------------------------------------------------------
# Email-address regex (simplified)
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9.\-]+")


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------

def parse_email_line(line: str) -> tuple[str | None, str | None]:
    """Extract (name, email) from a single pasted-email line.

    Returns
    -------
    (name, email) where *name* is ``None`` for bare emails or when the
    "name" portion is itself an email address.  Returns ``(None, None)``
    for empty / unparseable lines.
    """
    line = line.strip().rstrip(",").strip()
    if not line:
        return (None, None)

    # Try to match  Name <email>  or  "Name" <email>  pattern
    angle_match = re.search(r"<([^>]+)>", line)
    if angle_match:
        email_raw = angle_match.group(1).strip()
        name_part = line[: angle_match.start()].strip()

        # Strip surrounding quotes from name part
        name_part = name_part.strip('"').strip("'").strip()

        # If the name part looks like an email, discard it
        if "@" in name_part:
            name_part = None

        email = _normalize_email(email_raw)
        if email is None:
            return (None, None)

        return (name_part if name_part else None, email)

    # No angle-bracket pattern -- try to find a bare email address
    email_match = _EMAIL_RE.search(line)
    if email_match:
        email = _normalize_email(email_match.group(0))
        return (None, email)

    return (None, None)


# ---------------------------------------------------------------------------
# Company extraction from domain
# ---------------------------------------------------------------------------

def _company_name_from_domain(domain: str) -> str:
    """Derive a display-friendly company name from an email domain.

    Example: ``firinnecapital.com`` -> ``Firinnecapital``
    """
    # Take the part before the first dot
    name_part = domain.split(".")[0]
    return name_part.capitalize()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _find_or_create_company(
    conn,
    company_name: str,
    user_id: Optional[int] = None,
    *,
    cursor=None,
    cache: Optional[dict] = None,
) -> int:
    """Return the company id, creating the row if necessary.

    Uses INSERT ... WHERE NOT EXISTS to avoid the TOCTOU race between the
    existence check and the insert.  If the row already existed (zero rows
    inserted), a follow-up SELECT retrieves it.

    Parameters
    ----------
    cursor : optional
        An existing cursor to reuse.  When ``None`` a new cursor is created
        and closed on exit.
    cache : dict, optional
        A ``{name_normalized: company_id}`` dict for caller-side caching.
        If provided and the normalized name is found, the DB is skipped
        entirely.  Newly created/found ids are stored back into the dict.
    """
    name_norm = _normalize_company_name(company_name)

    # Fast path: check caller-provided cache
    if cache is not None and name_norm in cache:
        return cache[name_norm]

    if cursor is not None:
        # Reuse caller-provided cursor
        return _find_or_create_company_with_cursor(
            conn, company_name, name_norm, user_id, cursor, cache,
        )
    with get_cursor(conn) as cur:
        return _find_or_create_company_with_cursor(
            conn, company_name, name_norm, user_id, cur, cache,
        )


def _find_or_create_company_with_cursor(conn, company_name, name_norm, user_id, cursor, cache):
    """Inner helper that runs the actual SQL using the given cursor."""
    # Atomic insert-if-absent: the WHERE NOT EXISTS guard prevents
    # duplicate rows even without a UNIQUE constraint on name_normalized.
    cursor.execute(
        """INSERT INTO companies (name, name_normalized, user_id)
           SELECT %s, %s, %s
           WHERE NOT EXISTS (
               SELECT 1 FROM companies WHERE name_normalized = %s
           )
           RETURNING id""",
        (company_name, name_norm, user_id, name_norm),
    )
    row = cursor.fetchone()
    if row:
        company_id = row["id"]
    else:
        # Row already existed -- fetch its id.
        cursor.execute(
            "SELECT id FROM companies WHERE name_normalized = %s",
            (name_norm,),
        )
        company_id = cursor.fetchone()["id"]

    if cache is not None:
        cache[name_norm] = company_id
    return company_id


def _next_priority_rank(
    conn,
    company_id: int,
    *,
    cursor=None,
    cache: Optional[dict] = None,
) -> int:
    """Return max(priority_rank) + 1 for the given company, or 1.

    Parameters
    ----------
    cursor : optional
        An existing cursor to reuse.
    cache : dict, optional
        A ``{company_id: next_rank}`` dict.  When provided the DB query is
        skipped if the company already has a cached value, and the cached
        value is incremented for the next call.
    """
    # Fast path: use cached rank and bump it
    if cache is not None and company_id in cache:
        rank = cache[company_id]
        cache[company_id] = rank + 1
        return rank

    def _query_rank(cur):
        cur.execute(
            "SELECT MAX(priority_rank) AS max_rank FROM contacts WHERE company_id = %s",
            (company_id,),
        )
        row = cur.fetchone()
        current_max = row["max_rank"] if row and row["max_rank"] is not None else 0
        rank = current_max + 1
        if cache is not None:
            cache[company_id] = rank + 1
        return rank

    if cursor is not None:
        return _query_rank(cursor)
    with get_cursor(conn) as cur:
        return _query_rank(cur)


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------

def import_pasted_emails(
    conn, file_path: str, *, user_id: Optional[int] = None
) -> dict:
    """Read a file of pasted email lines and import them as contacts.

    Optimised to minimise database round-trips:

    * A single cursor is created once and reused for the entire import.
    * All parsed emails are batch-checked against ``contacts`` in one SELECT
      so that duplicates are filtered via an O(1) set lookup.
    * A ``company_cache`` (domain -> company_id) avoids repeated
      ``_find_or_create_company`` calls for the same domain.
    * A ``rank_cache`` (company_id -> next_rank) avoids repeated
      ``MAX(priority_rank)`` queries for the same company.

    Parameters
    ----------
    conn : database connection
        An open database connection (migrations must already be applied).
    file_path : str
        Path to a text file containing pasted emails.
    user_id : int, optional
        Owner user ID for multi-tenant scoping.

    Returns
    -------
    dict with keys ``contacts_created``, ``lines_processed``, ``lines_skipped``.
    """
    with open(file_path, "r") as fh:
        raw_text = fh.read()

    # Split on commas and newlines to get individual entries.
    # Some entries span commas within a single line, so we normalise.
    entries: list[str] = []
    for chunk in re.split(r"[,\n]+", raw_text):
        chunk = chunk.strip()
        if chunk:
            entries.append(chunk)

    # ---- Phase 1: parse all entries and collect normalised emails ----------
    parsed: list[tuple[str | None, str | None, str | None]] = []
    lines_processed = 0
    lines_skipped = 0

    for entry in entries:
        lines_processed += 1
        name, email = parse_email_line(entry)

        if email is None:
            lines_skipped += 1
            parsed.append((None, None, None))
            continue

        email_norm = _normalize_email(email)
        if email_norm is None:
            lines_skipped += 1
            parsed.append((None, None, None))
            continue

        parsed.append((name, email, email_norm))

    # ---- Phase 2: batch dedup check ----------------------------------------
    all_emails = [email_norm for (_, _, email_norm) in parsed if email_norm]
    existing_emails: set[str] = set()
    with get_cursor(conn) as cursor:
        if all_emails:
            # Query in batches of 500 to avoid oversized IN clauses
            for i in range(0, len(all_emails), 500):
                batch = all_emails[i : i + 500]
                placeholders = ",".join("%s" for _ in batch)
                cursor.execute(
                    f"SELECT email_normalized FROM contacts "
                    f"WHERE email_normalized IN ({placeholders})",
                    batch,
                )
                existing_emails.update(
                    row["email_normalized"] for row in cursor.fetchall()
                )

        # ---- Phase 3: insert new contacts ----------------------------------
        contacts_created = 0
        company_cache: dict[str, int] = {}  # name_normalized -> company_id
        rank_cache: dict[int, int] = {}     # company_id -> next_rank
        # Track emails we insert in this run to skip intra-file duplicates
        seen_in_run: set[str] = set()

        for name, email, email_norm in parsed:
            if email_norm is None:
                continue  # already counted as skipped

            if email_norm in existing_emails or email_norm in seen_in_run:
                lines_skipped += 1
                continue

            seen_in_run.add(email_norm)

            # Derive company from domain
            domain = email_norm.split("@")[1]
            company_display = _company_name_from_domain(domain)
            company_id = _find_or_create_company(
                conn, company_display, user_id=user_id,
                cursor=cursor, cache=company_cache,
            )

            # Split name if available
            first_name = ""
            last_name = ""
            full_name = ""
            if name:
                full_name = name
                first_name, last_name = _split_name(name)

            priority_rank = _next_priority_rank(
                conn, company_id, cursor=cursor, cache=rank_cache,
            )

            cursor.execute(
                """INSERT INTO contacts
                       (company_id, first_name, last_name, full_name,
                        email, email_normalized, priority_rank, source)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    company_id,
                    first_name,
                    last_name,
                    full_name,
                    email,
                    email_norm,
                    priority_rank,
                    "pasted_emails",
                ),
            )
            contacts_created += 1

    conn.commit()

    return {
        "contacts_created": contacts_created,
        "lines_processed": lines_processed,
        "lines_skipped": lines_skipped,
    }
