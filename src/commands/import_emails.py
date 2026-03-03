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


# ---------------------------------------------------------------------------
# Local helper functions (duplicated from import_contacts.py for now;
# will be refactored into a shared utils module later).
# ---------------------------------------------------------------------------

def _normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        return None
    return normalized


def _normalize_company_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if len(parts) == 0:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], " ".join(parts[1:]))


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
    conn, company_name: str
) -> int:
    """Return the company id, creating the row if necessary."""
    name_norm = _normalize_company_name(company_name)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM companies WHERE name_normalized = %s", (name_norm,)
    )
    row = cursor.fetchone()
    if row:
        return row["id"]

    cursor.execute(
        "INSERT INTO companies (name, name_normalized) VALUES (%s, %s) RETURNING id",
        (company_name, name_norm),
    )
    result = cursor.fetchone()
    conn.commit()
    return result["id"]


def _next_priority_rank(conn, company_id: int) -> int:
    """Return max(priority_rank) + 1 for the given company, or 1."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT MAX(priority_rank) AS max_rank FROM contacts WHERE company_id = %s",
        (company_id,),
    )
    row = cursor.fetchone()
    current_max = row["max_rank"] if row and row["max_rank"] is not None else 0
    return current_max + 1


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------

def import_pasted_emails(
    conn, file_path: str
) -> dict:
    """Read a file of pasted email lines and import them as contacts.

    Parameters
    ----------
    conn : database connection
        An open database connection (migrations must already be applied).
    file_path : str
        Path to a text file containing pasted emails.

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

    contacts_created = 0
    lines_processed = 0
    lines_skipped = 0

    for entry in entries:
        lines_processed += 1
        name, email = parse_email_line(entry)

        if email is None:
            lines_skipped += 1
            continue

        email_norm = _normalize_email(email)
        if email_norm is None:
            lines_skipped += 1
            continue

        # Skip duplicates
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM contacts WHERE email_normalized = %s",
            (email_norm,),
        )
        existing = cur.fetchone()
        if existing:
            lines_skipped += 1
            continue

        # Derive company from domain
        domain = email_norm.split("@")[1]
        company_display = _company_name_from_domain(domain)
        company_id = _find_or_create_company(conn, company_display)

        # Split name if available
        first_name = ""
        last_name = ""
        full_name = ""
        if name:
            full_name = name
            first_name, last_name = _split_name(name)

        priority_rank = _next_priority_rank(conn, company_id)

        cur.execute(
            """
            INSERT INTO contacts
                (company_id, first_name, last_name, full_name,
                 email, email_normalized, priority_rank, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
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
