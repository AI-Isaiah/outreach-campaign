"""Smart CSV import engine — LLM-powered column mapping, transform, preview, execute.

Provides the core pipeline for the smart import feature:
  analyze_csv()    — Call LLM (Anthropic / OpenAI / Gemini) to map CSV columns
  transform_rows() — Apply mapping + multi-contact explosion + normalization
  preview_import() — SELECT-only duplicate check against existing contacts
  execute_import() — INSERT companies and contacts, then run dedup

LLM provider priority: uses whichever API key is configured, in order:
  1. ANTHROPIC_API_KEY  → Claude Haiku (fast, ~$0.01/import)
  2. OPENAI_API_KEY     → GPT-4o-mini (cheap, ~$0.003/import)
  3. GEMINI_API_KEY     → Gemini Flash (free tier: 15 RPM)
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from typing import Optional

import httpx

from src.models.database import get_cursor
from src.services.normalization_utils import (
    normalize_company_name,
    normalize_email,
    normalize_linkedin_url,
    split_name,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM provider abstraction
# ---------------------------------------------------------------------------

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


def _call_anthropic(prompt: str, api_key: str) -> str:
    """Call Anthropic Messages API and return the raw text response."""
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 2000,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _call_openai(prompt: str, api_key: str) -> str:
    """Call OpenAI Chat Completions API and return the raw text response."""
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o-mini",
            "temperature": 0,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_gemini(prompt: str, api_key: str) -> str:
    """Call Google Gemini API and return the raw text response."""
    resp = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 2000},
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _detect_provider() -> tuple[str, str] | None:
    """Detect which LLM API key is available. Returns (provider_name, api_key) or None."""
    for env_var, name in [
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("OPENAI_API_KEY", "openai"),
        ("GEMINI_API_KEY", "gemini"),
    ]:
        key = os.getenv(env_var, "").strip()
        if key:
            return (name, key)
    return None


def _call_llm(prompt: str) -> tuple[str, str]:
    """Call the first available LLM provider. Returns (raw_text, provider_name).

    Raises RuntimeError if no API key is configured.
    """
    provider = _detect_provider()
    if not provider:
        raise RuntimeError("No LLM API key configured (set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY)")

    name, api_key = provider
    callers = {
        "anthropic": _call_anthropic,
        "openai": _call_openai,
        "gemini": _call_gemini,
    }
    raw_text = callers[name](prompt, api_key)
    return raw_text, name


# ---------------------------------------------------------------------------
# CSV header detection (moved from routes layer)
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

    Tries providers in order: Anthropic → OpenAI → Gemini (whichever key is set).

    Returns
    -------
    dict
        ``{"column_map": {...}, "unmapped": [...], "multi_contact": {...},
          "confidence": float, "provider": str}``
    """
    heuristic = _heuristic_mapping(headers)
    heuristic["provider"] = None
    fallback = dict(heuristic)  # shallow copy so mutations don't affect fallback

    try:
        prompt = _build_prompt(headers, sample_rows)
        raw_text, provider_name = _call_llm(prompt)

        raw_text = raw_text.strip()

        # Strip markdown fences if present
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

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
        return result

    except RuntimeError as exc:
        logger.warning("No LLM provider available: %s", exc)
        return fallback
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse LLM JSON response: %s", exc)
        return fallback
    except httpx.HTTPStatusError as exc:
        logger.warning("LLM API HTTP error: %s %s", exc.response.status_code, exc.response.text[:200])
        return fallback
    except httpx.TimeoutException:
        logger.warning("LLM API call timed out (30s)")
        return fallback
    except Exception as exc:
        logger.exception("Unexpected error during analyze_csv: %s", exc)
        return fallback


# ---------------------------------------------------------------------------
# transform_rows — apply mapping + multi-contact explosion
# ---------------------------------------------------------------------------


def _parse_aum(raw: str) -> Optional[float]:
    """Parse AUM string like ``"$1,219.50"`` into a float."""
    if raw is None:
        return None
    cleaned = str(raw).strip().replace("$", "").replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _get_field(row: dict, mapping: dict, target: str) -> str:
    """Look up the CSV column mapped to a target field, return its value."""
    for csv_col, mapped_target in mapping.items():
        if mapped_target == target:
            return (row.get(csv_col) or "").strip()
    return ""


def transform_rows(
    rows: list[dict],
    mapping: dict,
    multi_contact: dict,
    gdpr_countries: list[str],
) -> list[dict]:
    """Apply column mapping and multi-contact row explosion.

    Parameters
    ----------
    rows : list[dict]
        Raw CSV rows (list of dicts with original column names as keys).
    mapping : dict
        ``{"csv_column_name": "target_field", ...}`` from analyze_csv.
    multi_contact : dict
        ``{"detected": bool, "contact_groups": [...]}`` from analyze_csv.
    gdpr_countries : list[str]
        Lowercased country names that trigger GDPR flag.

    Returns
    -------
    list[dict]
        Transformed rows with normalized fields, one per contact.
    """
    column_map = mapping if isinstance(mapping, dict) else {}
    gdpr_set = {c.strip().lower() for c in gdpr_countries}
    results = []

    # Build reverse lookup: target_field -> csv_column_name (first match wins)
    _target_to_col: dict[str, str] = {}
    for csv_col, target in column_map.items():
        if target and target not in _target_to_col:
            _target_to_col[target] = csv_col

    def _field(row: dict, target: str) -> str:
        col = _target_to_col.get(target, "")
        return (row.get(col) or "").strip() if col else ""

    for row in rows:
        # --- Company fields ---
        company_name = _field(row, "company.name")
        if not company_name:
            continue

        country = _field(row, "company.country")
        aum_raw = _field(row, "company.aum")
        firm_type = _field(row, "company.firm_type")
        website = _field(row, "company.website")
        address = _field(row, "company.address")
        is_gdpr = country.lower() in gdpr_set if country else False
        aum = _parse_aum(aum_raw)
        company_name_normalized = normalize_company_name(company_name)

        # --- Contacts ---
        contact_dicts = []

        if multi_contact.get("detected") and multi_contact.get("contact_groups"):
            for group in multi_contact["contact_groups"]:
                fields = group.get("fields", {})
                full_name_col = fields.get("contact.full_name", "")
                email_col = fields.get("contact.email", "")
                title_col = fields.get("contact.title", "")
                linkedin_col = fields.get("contact.linkedin_url", "")
                first_name_col = fields.get("contact.first_name", "")
                last_name_col = fields.get("contact.last_name", "")

                full_name = (row.get(full_name_col) or "").strip() if full_name_col else ""
                email_raw = (row.get(email_col) or "").strip() if email_col else ""
                title = (row.get(title_col) or "").strip() if title_col else ""
                linkedin_raw = (row.get(linkedin_col) or "").strip() if linkedin_col else ""
                first_name = (row.get(first_name_col) or "").strip() if first_name_col else ""
                last_name = (row.get(last_name_col) or "").strip() if last_name_col else ""

                # Skip groups that have no name and no email
                if not full_name and not email_raw and not first_name and not last_name:
                    continue

                contact_dicts.append({
                    "full_name": full_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email_raw,
                    "title": title,
                    "linkedin_url": linkedin_raw,
                })
        else:
            # Single contact per row
            full_name = _field(row, "contact.full_name")
            email_raw = _field(row, "contact.email")
            title = _field(row, "contact.title")
            linkedin_raw = _field(row, "contact.linkedin_url")
            first_name = _field(row, "contact.first_name")
            last_name = _field(row, "contact.last_name")

            if full_name or email_raw or first_name or last_name:
                contact_dicts.append({
                    "full_name": full_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email_raw,
                    "title": title,
                    "linkedin_url": linkedin_raw,
                })

        # --- Build output rows ---
        # Sort contacts: has_email DESC, has_linkedin DESC, then row order
        contact_dicts.sort(
            key=lambda c: (
                not bool(c.get("email")),
                not bool(c.get("linkedin_url")),
            )
        )

        for rank, contact in enumerate(contact_dicts, start=1):
            c_full_name = contact["full_name"]
            c_first = contact["first_name"]
            c_last = contact["last_name"]

            # Split full_name if first/last not separately mapped
            if c_full_name and not c_first and not c_last:
                c_first, c_last = split_name(c_full_name)

            email_norm = normalize_email(contact["email"]) if contact["email"] else None
            linkedin_norm = normalize_linkedin_url(contact["linkedin_url"]) if contact["linkedin_url"] else ""

            results.append({
                "company_name": company_name,
                "company_name_normalized": company_name_normalized,
                "country": country or None,
                "aum_millions": aum,
                "firm_type": firm_type or None,
                "is_gdpr": is_gdpr,
                "first_name": c_first or None,
                "last_name": c_last or None,
                "full_name": c_full_name or f"{c_first} {c_last}".strip() or None,
                "email": contact["email"] or None,
                "email_normalized": email_norm,
                "linkedin_url": contact["linkedin_url"] or None,
                "linkedin_url_normalized": linkedin_norm or None,
                "title": contact["title"] or None,
                "priority_rank": rank,
                "email_status": "unknown",
                "website": website or None,
                "address": address or None,
            })

    return results


# ---------------------------------------------------------------------------
# preview_import — SELECT-only duplicate check with field-level diffs
# ---------------------------------------------------------------------------


def _build_field_diffs(import_row: dict, existing: dict) -> dict:
    """Compare import row vs CRM contact, field by field.

    Returns dict of field_name -> "new" | "conflict" | "same" | "empty".
    """
    COMPARE_FIELDS = [
        ("first_name", "first_name"),
        ("last_name", "last_name"),
        ("email", "email"),
        ("title", "title"),
        ("linkedin_url", "linkedin_url"),
    ]
    diffs = {}
    for import_key, crm_key in COMPARE_FIELDS:
        import_val = (import_row.get(import_key) or "").strip()
        crm_val = (existing.get(crm_key) or "").strip()
        if not import_val and not crm_val:
            diffs[import_key] = "empty"
        elif import_val and not crm_val:
            diffs[import_key] = "new"
        elif not import_val and crm_val:
            diffs[import_key] = "empty"
        elif import_val.lower() == crm_val.lower():
            diffs[import_key] = "same"
        else:
            diffs[import_key] = "conflict"
    return diffs


def _existing_contact_dict(match: dict) -> dict:
    """Build the existing_contact summary dict from a DB row."""
    return {
        "first_name": match["first_name"],
        "last_name": match["last_name"],
        "email": match["email"],
        "title": match["title"],
        "linkedin_url": match["linkedin_url"],
        "company_name": match["company_name"],
    }


def preview_import(
    conn,
    transformed: list[dict],
    *,
    user_id: int,
) -> dict:
    """Check transformed contacts for duplicates without writing anything.

    Returns field-level diffs for each match instead of auto-clearing fields.
    Match types:
      - "exact" — both email AND LinkedIn match same CRM contact
      - "email_only" — only email matches
      - "linkedin_only" — only LinkedIn matches
      - "both_different_contacts" — email matches contact A, LinkedIn matches B
      - None — new contact, no match
    """
    emails_to_check = [
        r["email_normalized"]
        for r in transformed
        if r.get("email_normalized")
    ]
    linkedins_to_check = [
        r["linkedin_url_normalized"]
        for r in transformed
        if r.get("linkedin_url_normalized")
    ]

    # Single batch lookup for both email and LinkedIn matches
    email_existing: dict[str, dict] = {}
    linkedin_existing: dict[str, dict] = {}
    if emails_to_check or linkedins_to_check:
        with get_cursor(conn) as cursor:
            cursor.execute(
                """SELECT c.id, c.email_normalized, c.linkedin_url_normalized,
                          c.first_name, c.last_name, c.email, c.title,
                          c.linkedin_url, co.name AS company_name
                   FROM contacts c
                   LEFT JOIN companies co ON co.id = c.company_id AND co.user_id = %s
                   WHERE c.user_id = %s
                     AND (c.email_normalized = ANY(%s)
                          OR c.linkedin_url_normalized = ANY(%s))""",
                (user_id, user_id,
                 emails_to_check or [], linkedins_to_check or []),
            )
            for row in cursor.fetchall():
                if row["email_normalized"] and row["email_normalized"] in set(emails_to_check):
                    email_existing[row["email_normalized"]] = row
                if row["linkedin_url_normalized"] and row["linkedin_url_normalized"] in set(linkedins_to_check):
                    linkedin_existing[row["linkedin_url_normalized"]] = row

    company_names = {r["company_name_normalized"] for r in transformed if r.get("company_name_normalized")}

    # Build ALL rows with match info and field-level diffs
    all_rows = []
    exact_duplicates = 0

    for idx, r in enumerate(transformed):
        row_copy = dict(r)
        row_copy["_index"] = idx

        email_norm = r.get("email_normalized")
        linkedin_norm = r.get("linkedin_url_normalized")
        email_match = email_existing.get(email_norm) if email_norm else None
        linkedin_match = linkedin_existing.get(linkedin_norm) if linkedin_norm else None

        if email_match and linkedin_match:
            if email_match["id"] == linkedin_match["id"]:
                # Both fields match same CRM contact — exact duplicate
                row_copy["match_type"] = "exact"
                row_copy["existing_contact_id"] = email_match["id"]
                row_copy["existing_contact"] = _existing_contact_dict(email_match)
                row_copy["field_diffs"] = _build_field_diffs(r, email_match)
                row_copy["is_duplicate"] = True
                exact_duplicates += 1
            else:
                # Email matches contact A, LinkedIn matches contact B
                row_copy["match_type"] = "both_different_contacts"
                row_copy["existing_contact_id"] = email_match["id"]
                row_copy["existing_contact"] = _existing_contact_dict(email_match)
                row_copy["field_diffs"] = _build_field_diffs(r, email_match)
                row_copy["is_duplicate"] = False
        elif email_match:
            row_copy["match_type"] = "email_only"
            row_copy["existing_contact_id"] = email_match["id"]
            row_copy["existing_contact"] = _existing_contact_dict(email_match)
            row_copy["field_diffs"] = _build_field_diffs(r, email_match)
            row_copy["is_duplicate"] = False
        elif linkedin_match:
            row_copy["match_type"] = "linkedin_only"
            row_copy["existing_contact_id"] = linkedin_match["id"]
            row_copy["existing_contact"] = _existing_contact_dict(linkedin_match)
            row_copy["field_diffs"] = _build_field_diffs(r, linkedin_match)
            row_copy["is_duplicate"] = False
        else:
            row_copy["match_type"] = None
            row_copy["existing_contact_id"] = None
            row_copy["existing_contact"] = None
            row_copy["field_diffs"] = None
            row_copy["is_duplicate"] = False

        # Legacy compat fields
        row_copy["duplicate_type"] = row_copy["match_type"]
        row_copy["overlap_cleared"] = None

        all_rows.append(row_copy)

    # Within-file duplicate detection
    seen_emails: dict[str, int] = {}
    seen_linkedins: dict[str, int] = {}
    for row in all_rows:
        idx = row["_index"]
        email_n = row.get("email_normalized")
        linkedin_n = row.get("linkedin_url_normalized")
        dup_of = None
        if email_n and email_n in seen_emails:
            dup_of = seen_emails[email_n]
        elif linkedin_n and linkedin_n in seen_linkedins:
            dup_of = seen_linkedins[linkedin_n]

        if dup_of is not None:
            row["within_file_duplicate"] = True
            row["within_file_duplicate_of"] = dup_of
        else:
            row["within_file_duplicate"] = False
            row["within_file_duplicate_of"] = None

        if email_n and email_n not in seen_emails:
            seen_emails[email_n] = idx
        if linkedin_n and linkedin_n not in seen_linkedins:
            seen_linkedins[linkedin_n] = idx

    return {
        "total_contacts": len(transformed),
        "total_companies": len(company_names),
        "duplicates": exact_duplicates,
        "new_contacts": len(transformed) - exact_duplicates,
        "preview_rows": all_rows,
    }


# ---------------------------------------------------------------------------
# execute_import — INSERT companies + contacts, then dedup
# ---------------------------------------------------------------------------


def execute_import(
    conn,
    transformed: list[dict],
    *,
    user_id: int,
    row_decisions: dict[int, dict] | None = None,
    campaign_id: int | None = None,
) -> dict:
    """Insert companies and contacts from transformed rows.

    Parameters
    ----------
    conn
        Database connection.
    transformed : list[dict]
        Output of transform_rows().
    user_id : int
        Owner user ID for multi-tenant scoping.
    row_decisions : dict[int, dict] | None
        Per-row decisions from the frontend. Key is row index, value is
        ``{"action": "import"|"merge"|"skip"|"enroll", "existing_contact_id": N}``.
        When None, uses legacy behavior (INSERT with ON CONFLICT DO NOTHING).
    campaign_id : int | None
        Optional campaign to enroll all processed contacts in.

    Returns
    -------
    dict
        Import stats including created, merged, enrolled, and skipped counts.
    """
    companies_created = 0
    contacts_created = 0
    duplicates_skipped = 0
    contacts_merged = 0
    contacts_enrolled = 0
    contacts_skipped = 0
    all_contact_ids: list[int] = []  # for campaign enrollment

    # Group by company_name_normalized
    company_groups: dict[str, list[tuple[int, dict]]] = {}
    for idx, row in enumerate(transformed):
        key = row.get("company_name_normalized", "")
        if not key:
            continue
        company_groups.setdefault(key, []).append((idx, row))

    with get_cursor(conn) as cursor:
        for company_norm, indexed_contacts in company_groups.items():
            sample = indexed_contacts[0][1]

            # INSERT company with ON CONFLICT DO NOTHING
            cursor.execute(
                """INSERT INTO companies
                   (name, name_normalized, country, aum_millions, firm_type,
                    website, address, is_gdpr, user_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (user_id, name_normalized) DO NOTHING
                   RETURNING id""",
                (
                    sample["company_name"],
                    company_norm,
                    sample.get("country"),
                    sample.get("aum_millions"),
                    sample.get("firm_type"),
                    sample.get("website"),
                    sample.get("address"),
                    sample.get("is_gdpr", False),
                    user_id,
                ),
            )
            row = cursor.fetchone()
            if row:
                company_id = row["id"]
                companies_created += 1
            else:
                cursor.execute(
                    "SELECT id FROM companies WHERE user_id = %s AND name_normalized = %s",
                    (user_id, company_norm),
                )
                existing = cursor.fetchone()
                company_id = existing["id"] if existing else None
                if not company_id:
                    continue

            for idx, contact in indexed_contacts:
                # Skip contacts with no identifiers
                if not contact.get("full_name") and not contact.get("email") and not contact.get("first_name"):
                    continue

                decision = (row_decisions or {}).get(idx)
                action = decision["action"] if decision else None

                if action == "skip":
                    contacts_skipped += 1
                    continue

                if action == "merge" and decision.get("existing_contact_id"):
                    # UPDATE existing CRM contact — enrich null fields
                    existing_id = decision["existing_contact_id"]
                    _merge_contact(cursor, existing_id, contact)
                    contacts_merged += 1
                    all_contact_ids.append(existing_id)
                    continue

                if action == "enroll" and decision.get("existing_contact_id"):
                    # Don't create — just collect ID for enrollment
                    contacts_enrolled += 1
                    all_contact_ids.append(decision["existing_contact_id"])
                    continue

                # Default: INSERT new contact (action == "import" or no decision)
                email_norm = contact.get("email_normalized")
                cursor.execute(
                    """INSERT INTO contacts
                       (company_id, first_name, last_name, full_name,
                        email, email_normalized, linkedin_url,
                        linkedin_url_normalized, title, priority_rank,
                        source, is_gdpr, email_status, user_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               'csv_smart', %s, %s, %s)
                       ON CONFLICT (user_id, email_normalized)
                       DO NOTHING""",
                    (
                        company_id,
                        contact.get("first_name"),
                        contact.get("last_name"),
                        contact.get("full_name"),
                        contact.get("email"),
                        email_norm,
                        contact.get("linkedin_url"),
                        contact.get("linkedin_url_normalized"),
                        contact.get("title"),
                        contact.get("priority_rank"),
                        contact.get("is_gdpr", False),
                        contact.get("email_status", "unknown"),
                        user_id,
                    ),
                )
                if cursor.rowcount > 0:
                    contacts_created += 1
                    # Get the new contact ID for enrollment
                    if campaign_id and email_norm:
                        cursor.execute(
                            "SELECT id FROM contacts WHERE user_id = %s AND email_normalized = %s",
                            (user_id, email_norm),
                        )
                        new_row = cursor.fetchone()
                        if new_row:
                            all_contact_ids.append(new_row["id"])
                else:
                    duplicates_skipped += 1

    conn.commit()

    # Enroll all collected contacts in campaign
    if campaign_id and all_contact_ids:
        try:
            from src.models.campaigns import bulk_enroll_contacts
            enrolled = bulk_enroll_contacts(
                conn, campaign_id, all_contact_ids, user_id=user_id,
            )
            contacts_enrolled += enrolled
        except Exception as exc:
            logger.warning("Campaign enrollment after smart import failed: %s", exc)

    # Run dedup pipeline
    try:
        from src.services.deduplication import run_dedup
        run_dedup(conn, user_id=user_id)
    except Exception as exc:
        logger.warning("Deduplication after smart import failed: %s", exc)

    return {
        "companies_created": companies_created,
        "contacts_created": contacts_created,
        "duplicates_skipped": duplicates_skipped,
        "contacts_merged": contacts_merged,
        "contacts_enrolled": contacts_enrolled,
        "contacts_skipped": contacts_skipped,
    }


def _merge_contact(cursor, existing_contact_id: int, import_data: dict):
    """Update an existing CRM contact with non-null fields from import data.

    Only fills in fields that are currently NULL in the CRM — does not overwrite.
    """
    MERGE_FIELDS = [
        ("title", "title"),
        ("linkedin_url", "linkedin_url"),
        ("linkedin_url_normalized", "linkedin_url_normalized"),
        ("email", "email"),
        ("email_normalized", "email_normalized"),
    ]
    set_parts = []
    values = []
    for import_key, db_col in MERGE_FIELDS:
        val = import_data.get(import_key)
        if val:
            set_parts.append(f"{db_col} = COALESCE({db_col}, %s)")
            values.append(val)

    if not set_parts:
        return

    values.append(existing_contact_id)
    cursor.execute(
        f"UPDATE contacts SET {', '.join(set_parts)} WHERE id = %s",
        values,
    )
