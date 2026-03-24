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
# preview_import — SELECT-only duplicate check
# ---------------------------------------------------------------------------


def preview_import(
    conn,
    transformed: list[dict],
    *,
    user_id: int,
) -> dict:
    """Check transformed contacts for duplicates without writing anything.

    Parameters
    ----------
    conn
        Database connection.
    transformed : list[dict]
        Output of transform_rows().
    user_id : int
        Owner user ID for scoped duplicate lookup.

    Returns
    -------
    dict
        ``{"total_contacts": N, "total_companies": M, "duplicates": K,
          "new_contacts": N-K, "preview_rows": first_20_rows}``
    """
    duplicates = 0
    emails_to_check = [
        r["email_normalized"]
        for r in transformed
        if r.get("email_normalized")
    ]

    existing: set = set()
    if emails_to_check:
        with get_cursor(conn) as cursor:
            # Use ANY(%s) for efficient batch lookup
            cursor.execute(
                "SELECT email_normalized FROM contacts "
                "WHERE user_id = %s AND email_normalized = ANY(%s)",
                (user_id, emails_to_check),
            )
            existing = {row["email_normalized"] for row in cursor.fetchall()}
            duplicates = len(existing)

    company_names = {r["company_name_normalized"] for r in transformed if r.get("company_name_normalized")}

    # Mark duplicates on preview rows
    preview_rows = []
    for r in transformed[:20]:
        row_copy = dict(r)
        row_copy["is_duplicate"] = (
            r.get("email_normalized") is not None
            and r["email_normalized"] in existing
        ) if emails_to_check else False
        preview_rows.append(row_copy)

    return {
        "total_contacts": len(transformed),
        "total_companies": len(company_names),
        "duplicates": duplicates,
        "new_contacts": len(transformed) - duplicates,
        "preview_rows": preview_rows,
    }


# ---------------------------------------------------------------------------
# execute_import — INSERT companies + contacts, then dedup
# ---------------------------------------------------------------------------


def execute_import(
    conn,
    transformed: list[dict],
    *,
    user_id: int,
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

    Returns
    -------
    dict
        ``{"companies_created": N, "contacts_created": M, "duplicates_skipped": K}``
    """
    companies_created = 0
    contacts_created = 0
    duplicates_skipped = 0

    # Group by company_name_normalized
    company_groups: dict[str, list[dict]] = {}
    for row in transformed:
        key = row.get("company_name_normalized", "")
        if not key:
            continue
        company_groups.setdefault(key, []).append(row)

    with get_cursor(conn) as cursor:
        for company_norm, contacts in company_groups.items():
            # Use first row for company data
            sample = contacts[0]

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
                # Company already exists — fetch its id
                cursor.execute(
                    "SELECT id FROM companies WHERE user_id = %s AND name_normalized = %s",
                    (user_id, company_norm),
                )
                existing = cursor.fetchone()
                company_id = existing["id"] if existing else None
                if not company_id:
                    continue

            # INSERT contacts
            for contact in contacts:
                email_norm = contact.get("email_normalized")

                # Skip contacts with no identifiers
                if not contact.get("full_name") and not contact.get("email") and not contact.get("first_name"):
                    continue

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
                else:
                    duplicates_skipped += 1

    conn.commit()

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
    }
