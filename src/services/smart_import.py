"""Smart CSV import engine — LLM-powered column mapping, transform, preview, execute.

Provides the core pipeline for the smart import feature:
  analyze_csv()    — Call Claude Haiku to map CSV columns to CRM fields
  transform_rows() — Apply mapping + multi-contact explosion + normalization
  preview_import() — SELECT-only duplicate check against existing contacts
  execute_import() — INSERT companies and contacts, then run dedup
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from src.models.database import get_cursor
from src.services.normalization_utils import (
    normalize_company_name,
    normalize_email,
    normalize_linkedin_url,
    split_name,
)

logger = logging.getLogger(__name__)

_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


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
    """Call Claude Haiku to map CSV columns to CRM target fields.

    Parameters
    ----------
    headers : list[str]
        CSV header names.
    sample_rows : list[dict]
        First 5 rows of data for context.
    user_id : int
        Owner user ID (for future schema template lookup).
    conn
        Database connection (for future schema template lookup).

    Returns
    -------
    dict
        ``{"column_map": {...}, "unmapped": [...], "multi_contact": {...}, "confidence": float}``
    """
    sample_rows_json = json.dumps(sample_rows[:5], default=str, indent=2)

    prompt = f"""You are a CSV column mapper for a CRM that tracks companies and contacts.

Target fields:
COMPANY: name, country, aum_millions, firm_type, website, address
CONTACT: first_name, last_name, full_name, email, linkedin_url, title, phone

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
      {{"prefix": "Contact1", "fields": {{"full_name": "csv_col", "email": "csv_col", "title": "csv_col", "linkedin_url": "csv_col"}}}},
    ]
  }},
  "confidence": 0.0-1.0
}}"""

    fallback = {
        "column_map": {},
        "unmapped": list(headers),
        "multi_contact": {"detected": False, "contact_groups": []},
        "confidence": 0.0,
    }

    try:
        import anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set — returning fallback mapping")
            return fallback

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_ANTHROPIC_MODEL,
            max_tokens=2000,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text.strip()

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

        return result

    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse LLM JSON response: %s", exc)
        return fallback
    except anthropic.APIError as exc:
        logger.warning("Anthropic API error during analyze_csv: %s", exc)
        return fallback
    except ImportError:
        logger.warning("anthropic SDK not installed — returning fallback mapping")
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

    for row in rows:
        # --- Company fields ---
        company_name = _get_field(row, column_map, "name")
        if not company_name:
            continue

        country = _get_field(row, column_map, "country")
        aum_raw = _get_field(row, column_map, "aum_millions")
        firm_type = _get_field(row, column_map, "firm_type")
        website = _get_field(row, column_map, "website")
        address = _get_field(row, column_map, "address")
        is_gdpr = country.lower() in gdpr_set if country else False
        aum = _parse_aum(aum_raw)
        company_name_normalized = normalize_company_name(company_name)

        # --- Contacts ---
        contact_dicts = []

        if multi_contact.get("detected") and multi_contact.get("contact_groups"):
            for group in multi_contact["contact_groups"]:
                fields = group.get("fields", {})
                full_name_col = fields.get("full_name", "")
                email_col = fields.get("email", "")
                title_col = fields.get("title", "")
                linkedin_col = fields.get("linkedin_url", "")
                first_name_col = fields.get("first_name", "")
                last_name_col = fields.get("last_name", "")

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
            full_name = _get_field(row, column_map, "full_name")
            email_raw = _get_field(row, column_map, "email")
            title = _get_field(row, column_map, "title")
            linkedin_raw = _get_field(row, column_map, "linkedin_url")
            first_name = _get_field(row, column_map, "first_name")
            last_name = _get_field(row, column_map, "last_name")

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
