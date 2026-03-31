"""Smart import — row transformation, preview, and field-level diff logic."""

from __future__ import annotations

import logging
from typing import Optional

from src.models.database import get_cursor
from src.services.normalization_utils import (
    normalize_company_name,
    normalize_email,
    normalize_linkedin_url,
    split_name,
)

logger = logging.getLogger(__name__)


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
            emails_set = set(emails_to_check)
            linkedins_set = set(linkedins_to_check)
            for row in cursor.fetchall():
                if row["email_normalized"] and row["email_normalized"] in emails_set:
                    email_existing[row["email_normalized"]] = row
                if row["linkedin_url_normalized"] and row["linkedin_url_normalized"] in linkedins_set:
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
        dup_match = None
        if email_n and email_n in seen_emails:
            dup_of = seen_emails[email_n]
            dup_match = "email"
        elif linkedin_n and linkedin_n in seen_linkedins:
            dup_of = seen_linkedins[linkedin_n]
            dup_match = "linkedin"

        if dup_of is not None:
            row["within_file_duplicate"] = True
            row["within_file_duplicate_of"] = dup_of
            row["within_file_duplicate_match"] = dup_match
        else:
            row["within_file_duplicate"] = False
            row["within_file_duplicate_of"] = None
            row["within_file_duplicate_match"] = None

        if email_n and email_n not in seen_emails:
            seen_emails[email_n] = idx
        if linkedin_n and linkedin_n not in seen_linkedins:
            seen_linkedins[linkedin_n] = idx

    # --- Tier classification (V2) ---
    from src.services.normalization_utils import normalize_company_name

    triage = {"auto_mergeable": 0, "needs_review": 0, "company_changes": 0,
              "file_duplicates": 0, "new_contacts": 0, "total": len(all_rows)}

    for row in all_rows:
        # File duplicates get their own tier
        if row["within_file_duplicate"]:
            row["resolution_tier"] = "file_duplicate"
            triage["file_duplicates"] += 1
            continue

        match_type = row.get("match_type")
        if not match_type:
            row["resolution_tier"] = "new"
            row["conflict_fields"] = None
            row["existing_company_name"] = None
            triage["new_contacts"] += 1
            continue

        # Derive conflict_fields from field_diffs
        diffs = row.get("field_diffs") or {}
        conflict_fields = [k for k, v in diffs.items() if v == "conflict"]

        # Compare company names (normalized)
        import_co = normalize_company_name(row.get("company_name") or "")
        existing_co_raw = (row.get("existing_contact") or {}).get("company_name") or ""
        existing_co = normalize_company_name(existing_co_raw)
        same_company = import_co and existing_co and import_co == existing_co

        # Add company_name to conflict_fields if different
        if import_co and existing_co and not same_company:
            conflict_fields.append("company_name")

        row["conflict_fields"] = conflict_fields or None
        row["existing_company_name"] = existing_co_raw or None

        has_linkedin = match_type in ("exact", "linkedin_only")

        if has_linkedin and not same_company and import_co and existing_co:
            row["resolution_tier"] = "company_change"
            triage["company_changes"] += 1
            triage["needs_review"] += 1
        elif has_linkedin and not conflict_fields:
            row["resolution_tier"] = "auto_merge"
            triage["auto_mergeable"] += 1
        else:
            row["resolution_tier"] = "review"
            triage["needs_review"] += 1

    return {
        "total_contacts": len(transformed),
        "total_companies": len(company_names),
        "duplicates": exact_duplicates,
        "new_contacts": triage["new_contacts"],
        "triage_summary": triage,
        "preview_rows": all_rows,
    }
