"""Crypto research — CSV parsing, preview, and duplicate detection."""

from __future__ import annotations

import csv
import io

from src.models.database import get_cursor

_HEADER_ALIASES = {
    "company_name": ("company_name", "name", "firm_name", "company", "firm"),
    "website": ("website", "url", "company_website", "site"),
    "country": ("country", "location", "region"),
    "aum": ("aum", "aum_millions", "aum_(millions)"),
    "firm_type": ("firm_type", "type", "company_type", "category"),
}


def _build_header_map(fieldnames: list[str]) -> dict[str, str]:
    """Map raw CSV headers to canonical field names."""
    header_map: dict[str, str] = {}
    for h in fieldnames:
        hl = h.strip().lower().replace(" ", "_")
        for canonical, aliases in _HEADER_ALIASES.items():
            if hl in aliases:
                header_map[h] = canonical
                break
    return header_map


def parse_research_csv(csv_content: str) -> list[dict]:
    """Parse CSV with flexible column names.

    Required: company_name (or alias)
    Optional: website, country, aum, firm_type
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    if reader.fieldnames is None:
        return []

    header_map = _build_header_map(reader.fieldnames)

    results = []
    for row in reader:
        mapped = {}
        for orig_key, mapped_key in header_map.items():
            val = (row.get(orig_key) or "").strip()
            if val:
                mapped[mapped_key] = val

        name = mapped.get("company_name")
        if not name:
            continue

        results.append({
            "company_name": name,
            "website": mapped.get("website"),
            "country": mapped.get("country"),
            "aum": mapped.get("aum"),
            "firm_type": mapped.get("firm_type"),
        })

    return results


def preview_research_csv(csv_content: str) -> dict:
    """Preview a CSV: parse, show first 10 rows, column mapping, and stats."""
    companies = parse_research_csv(csv_content)

    has_website = sum(1 for c in companies if c.get("website"))
    has_country = sum(1 for c in companies if c.get("country"))
    has_aum = sum(1 for c in companies if c.get("aum"))

    # Detect raw headers
    reader = csv.DictReader(io.StringIO(csv_content))
    raw_headers = list(reader.fieldnames or [])
    header_map = _build_header_map(raw_headers) if raw_headers else {}

    return {
        "total_rows": len(companies),
        "preview": companies[:10],
        "raw_headers": raw_headers,
        "mapped_headers": header_map,
        "stats": {
            "with_website": has_website,
            "with_country": has_country,
            "with_aum": has_aum,
        },
    }


def check_duplicate_companies(conn, company_names: list[str], *, user_id: int) -> dict:
    """Check which companies have already been researched in prior jobs.

    Returns dict with 'already_researched' (list of names) and 'new' (list of names).
    """
    if not company_names:
        return {"already_researched": [], "new": company_names}

    # Use simple lower/trim normalization to match the SQL side
    simple_norm = [n.lower().strip() for n in company_names]
    norm_to_orig = dict(zip(simple_norm, company_names))

    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT DISTINCT regexp_replace(lower(trim(rr.company_name)), '\\s+', ' ', 'g') AS name_norm
               FROM research_results rr
               JOIN research_jobs rj ON rj.id = rr.job_id
               WHERE rj.status IN ('completed', 'researching', 'classifying')
                 AND regexp_replace(lower(trim(rr.company_name)), '\\s+', ' ', 'g') = ANY(%s)
                 AND rj.user_id = %s""",
            [simple_norm, user_id],
        )
        existing = {row["name_norm"] for row in cur.fetchall()}

    already = [norm_to_orig[n] for n in simple_norm if n in existing]
    new = [norm_to_orig[n] for n in simple_norm if n not in existing]

    return {"already_researched": already, "new": new}
