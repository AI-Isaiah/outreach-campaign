"""Smart import — LLM column mapping, header detection, heuristic fallback, caching."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re

import httpx

from src.models.database import get_cursor
from src.services.llm_client import call_llm, strip_markdown_fences

logger = logging.getLogger(__name__)


def _build_prompt(headers: list[str], sample_rows: list[dict]) -> str:
    """Build the column-mapping prompt sent to any LLM provider."""
    sample_rows_json = json.dumps(sample_rows[:5], default=str, indent=2)
    return f"""You are a CSV column mapper for a CRM that tracks companies and contacts.

Target fields:
COMPANY: company.name, company.country, company.aum, company.firm_type, company.website, company.address
CONTACT: contact.first_name, contact.last_name, contact.full_name, contact.email, contact.linkedin_url, contact.title, contact.phone

Given these CSV headers and sample rows, return a JSON mapping.
If one row contains multiple contacts for the same company (e.g., Contact1_Name, Contact2_Name),
identify the multi-contact pattern.

Headers: {json.dumps(headers)}
Sample rows (first 5): {sample_rows_json}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "column_map": {{"csv_column_name": "target_field", ...}},
  "unmapped": ["column1", "column2"],
  "multi_contact": {{
    "detected": true/false,
    "contact_groups": [
      {{"prefix": "Contact1", "fields": {{"contact.full_name": "csv_col", "contact.email": "csv_col", "contact.title": "csv_col", "contact.linkedin_url": "csv_col"}}}},
    ]
  }},
  "confidence": 0.0-1.0
}}"""


# ---------------------------------------------------------------------------
# CSV header detection
# ---------------------------------------------------------------------------

# Keywords that suggest a row is a header (lowercased)
_HEADER_KEYWORDS = {
    "name", "email", "company", "firm", "contact", "phone", "title",
    "address", "country", "website", "url", "linkedin", "aum", "type",
    "industry", "position", "first", "last", "domain", "notes", "tier",
    "fund", "status", "source", "date", "id", "organization",
}


def _detect_header_row(content: str, max_scan: int = 20) -> int:
    """Scan the first *max_scan* rows and return the 0-based index of the most
    likely header row.

    Scoring heuristics:
      +2  per non-empty cell
      +3  per cell that contains a known CRM keyword
      +1  per unique cell value (penalises repeated blanks)
      -2  per cell that looks purely numeric or is a date
      -5  if the row has fewer than 3 non-empty cells
      -10 if any cell is longer than 80 chars (headers are short)
      -20 if the row contains a copyright symbol or "notes:" marker (footer/metadata)
    """
    reader = csv.reader(io.StringIO(content))
    candidates: list[tuple[int, float, list[str]]] = []

    for idx, row in enumerate(reader):
        if idx >= max_scan:
            break
        if not row:
            continue

        non_empty = [c.strip() for c in row if c.strip()]
        score = 0.0

        if len(non_empty) < 3:
            score -= 5

        if any(len(c) > 80 for c in non_empty):
            score -= 10

        row_text = " ".join(non_empty).lower()
        if "\u00a9" in row_text or "copyright" in row_text or row_text.startswith("notes:"):
            score -= 20

        uniq = set()
        for cell in non_empty:
            score += 2
            low = cell.lower()
            uniq.add(low)
            for kw in _HEADER_KEYWORDS:
                if kw in low:
                    score += 3
                    break
            stripped = cell.replace(",", "").replace(".", "").replace("$", "").replace("%", "").strip()
            if stripped.isdigit():
                score -= 2

        score += len(uniq)

        candidates.append((idx, score, row))

    if not candidates:
        return 0

    best_idx, _best_score, _best_row = max(candidates, key=lambda t: t[1])
    return best_idx


def parse_csv_with_header_detection(content: str) -> tuple[list[str], list[dict]]:
    """Parse a CSV string, auto-detecting which row contains the headers.

    Returns (headers, rows) where rows are list[dict] keyed by header names.
    """
    header_idx = _detect_header_row(content)

    raw_reader = csv.reader(io.StringIO(content))
    for _ in range(header_idx):
        try:
            next(raw_reader)
        except StopIteration:
            break

    try:
        raw_headers = next(raw_reader)
    except StopIteration:
        return [], []

    headers = [h.strip() for h in raw_headers]

    rows: list[dict] = []
    for raw_row in raw_reader:
        cleaned = {h: (raw_row[i] if i < len(raw_row) else "") for i, h in enumerate(headers)}
        values = [v for v in cleaned.values() if v and v.strip()]
        if not values:
            continue
        row_text = " ".join(values).lower()
        if "\u00a9" in row_text or "copyright" in row_text:
            continue
        rows.append(cleaned)

    return headers, rows


# ---------------------------------------------------------------------------
# Heuristic (keyword-based) column mapping
# ---------------------------------------------------------------------------


def _heuristic_mapping(headers: list[str]) -> dict:
    """Keyword-based column mapping fallback when LLM is unavailable or incomplete.

    Returns the same dict shape as analyze_csv:
        {"column_map": {...}, "multi_contact": {...}, "confidence": float, "unmapped": [...]}
    """
    RULES: list[tuple[list[str], str]] = [
        # Company fields
        (["firm name", "company name", "organization", "fund name"], "company.name"),
        (["country"], "company.country"),
        (["aum"], "company.aum"),
        (["firm type"], "company.firm_type"),
        (["url", "website"], "company.website"),
        (["address"], "company.address"),
        # Contact fields (primary only — multi-contact handled separately)
        (["primary email"], "contact.email"),
        (["primary linkedin"], "contact.linkedin_url"),
        (["position"], "contact.title"),
        (["phone"], "contact.phone"),
        (["first name"], "contact.first_name"),
        (["last name"], "contact.last_name"),
        (["primary contact"], "contact.full_name"),
    ]

    column_map: dict[str, str] = {}
    used_targets: set[str] = set()

    for header in headers:
        h_lower = header.strip().lower()
        # Skip headers that look like secondary contacts (Contact 2, Contact 3, etc.)
        if re.match(r"^contact\s*[2-9]", h_lower):
            continue
        for keywords, target in RULES:
            if target in used_targets:
                continue
            if any(kw in h_lower for kw in keywords):
                column_map[header] = target
                used_targets.add(target)
                break
        # Catch generic "email" that's not a numbered contact email
        if header not in column_map and "email" in h_lower and "contact" not in h_lower and "career" not in h_lower and "main email" not in h_lower:
            if "contact.email" not in used_targets:
                column_map[header] = "contact.email"
                used_targets.add("contact.email")
        # Catch generic "linkedin" that's not a numbered contact
        if header not in column_map and "linkedin" in h_lower and "contact" not in h_lower and "company" not in h_lower:
            if "contact.linkedin_url" not in used_targets:
                column_map[header] = "contact.linkedin_url"
                used_targets.add("contact.linkedin_url")

    # Detect multi-contact pattern: "Contact 2", "Contact 3", "Contact 4" etc.
    multi_contact: dict = {"detected": False, "contact_groups": []}
    contact_groups: dict[str, dict[str, str]] = {}

    for header in headers:
        h_lower = header.strip().lower()
        # Match patterns like "Contact 2", "Contact 2 Title", "Contact 2 Email", "Contact 2 LinkedIn"
        m = re.match(r"^contact\s*(\d+)\s*(.*)?$", h_lower, re.IGNORECASE)
        if m:
            group_num = m.group(1)
            suffix = (m.group(2) or "").strip().lower()
            if group_num not in contact_groups:
                contact_groups[group_num] = {}
            if not suffix or suffix in ("name",):
                contact_groups[group_num]["contact.full_name"] = header
            elif "email" in suffix:
                contact_groups[group_num]["contact.email"] = header
            elif "title" in suffix or "position" in suffix:
                contact_groups[group_num]["contact.title"] = header
            elif "linkedin" in suffix:
                contact_groups[group_num]["contact.linkedin_url"] = header

    # Also detect primary contact as group 1
    primary_group: dict[str, str] = {}
    for header in headers:
        h_lower = header.strip().lower()
        if h_lower == "primary contact":
            primary_group["contact.full_name"] = header
        elif h_lower == "primary email":
            primary_group["contact.email"] = header
        elif h_lower == "primary linkedin":
            primary_group["contact.linkedin_url"] = header
        elif h_lower == "position" and "contact.title" not in primary_group:
            primary_group["contact.title"] = header
        elif h_lower.startswith("contact title"):
            pass  # Skip salutation

    if contact_groups:
        groups = []
        if primary_group:
            groups.append({"prefix": "Primary", "fields": primary_group})
        for num in sorted(contact_groups.keys()):
            groups.append({"prefix": f"Contact {num}", "fields": contact_groups[num]})
        multi_contact = {"detected": True, "contact_groups": groups}

    unmapped = [h for h in headers if h not in column_map]
    mapped_count = len(column_map) + sum(len(g["fields"]) for g in multi_contact.get("contact_groups", []))
    total = len(headers)
    confidence = min(mapped_count / total, 1.0) if total > 0 else 0.0

    return {
        "column_map": column_map,
        "multi_contact": multi_contact,
        "unmapped": unmapped,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Schema template caching
# ---------------------------------------------------------------------------


def _header_fingerprint(headers: list[str]) -> str:
    """Compute a stable fingerprint for a set of CSV headers."""
    normalized = "|".join(h.strip().lower() for h in sorted(headers))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _get_cached_mapping(conn, user_id: int, fingerprint: str) -> dict | None:
    """Check schema_templates for a cached mapping. Returns dict or None."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT column_mapping, multi_contact_pattern
               FROM schema_templates
               WHERE user_id = %s AND fingerprint = %s""",
            (user_id, fingerprint),
        )
        row = cur.fetchone()
    if not row:
        return None
    mapping = row["column_mapping"] if isinstance(row["column_mapping"], dict) else json.loads(row["column_mapping"])
    multi = row["multi_contact_pattern"]
    if multi and isinstance(multi, str):
        multi = json.loads(multi)
    return {
        "column_map": mapping,
        "multi_contact": multi or {"detected": False, "contact_groups": []},
        "unmapped": [],
        "confidence": 1.0,
        "provider": "cache",
    }


def _save_mapping_cache(conn, user_id: int, fingerprint: str, result: dict, source_label: str | None = None) -> None:
    """Save a successful mapping to schema_templates for reuse."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO schema_templates (user_id, fingerprint, source_label, column_mapping, multi_contact_pattern)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (user_id, fingerprint) DO UPDATE
               SET column_mapping = EXCLUDED.column_mapping,
                   multi_contact_pattern = EXCLUDED.multi_contact_pattern,
                   times_used = schema_templates.times_used + 1,
                   updated_at = NOW()""",
            (
                user_id,
                fingerprint,
                source_label,
                json.dumps(result.get("column_map", {})),
                json.dumps(result.get("multi_contact", {})),
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# analyze_csv — LLM column mapping
# ---------------------------------------------------------------------------


def analyze_csv(
    headers: list[str],
    sample_rows: list[dict],
    *,
    user_id: int,
    conn,
) -> dict:
    """Call LLM to map CSV columns to CRM target fields.

    Checks schema_templates cache first. Falls back to LLM, then heuristic.

    Returns
    -------
    dict
        ``{"column_map": {...}, "unmapped": [...], "multi_contact": {...},
          "confidence": float, "provider": str}``
    """
    fingerprint = _header_fingerprint(headers)

    # Check cache first
    cached = _get_cached_mapping(conn, user_id, fingerprint)
    if cached:
        logger.info("analyze_csv: cache hit (fingerprint=%s)", fingerprint)
        return cached

    heuristic = _heuristic_mapping(headers)
    heuristic["provider"] = None
    fallback = dict(heuristic)  # shallow copy so mutations don't affect fallback

    try:
        prompt = _build_prompt(headers, sample_rows)
        raw_text, provider_name = call_llm(prompt)
        raw_text = strip_markdown_fences(raw_text)

        result = json.loads(raw_text)

        # Validate expected keys
        if "column_map" not in result:
            logger.warning("LLM response missing column_map — returning fallback")
            return fallback

        # Ensure all expected keys exist with defaults
        result.setdefault("unmapped", [])
        result.setdefault("multi_contact", {"detected": False, "contact_groups": []})
        result.setdefault("confidence", 0.5)
        result["provider"] = provider_name

        # Merge heuristic results to fill LLM gaps
        for col, target in heuristic["column_map"].items():
            if col not in result["column_map"]:
                result["column_map"][col] = target
        # Use heuristic multi-contact if LLM didn't detect it
        if not result.get("multi_contact", {}).get("detected") and heuristic["multi_contact"].get("detected"):
            result["multi_contact"] = heuristic["multi_contact"]
        # Recalculate confidence after merge
        mapped_count = len(result["column_map"])
        if heuristic["multi_contact"].get("contact_groups"):
            mapped_count += sum(len(g["fields"]) for g in heuristic["multi_contact"]["contact_groups"])
        total = len(headers)
        result["confidence"] = max(result.get("confidence", 0), min(mapped_count / total, 1.0) if total > 0 else 0.0)

        logger.info("analyze_csv: mapped %d columns via %s + heuristic (confidence: %.2f)",
                     len(result["column_map"]), provider_name, result["confidence"])

        # Cache successful mapping for future reuse
        try:
            _save_mapping_cache(conn, user_id, fingerprint, result)
        except psycopg2.Error:
            logger.warning("Failed to cache mapping (non-fatal)")

        return result

    except RuntimeError as exc:
        logger.warning("No LLM provider available: %s", exc)
        return fallback
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse LLM JSON response: %s", exc)
        return fallback
    except (httpx.HTTPError, KeyError, TypeError) as exc:
        logger.exception("Unexpected error during analyze_csv: %s", exc)
        return fallback


# psycopg2 is used in analyze_csv's except block via _save_mapping_cache
import psycopg2  # noqa: E402
