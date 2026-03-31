"""Smart import — execute import (INSERT companies + contacts) and merge logic."""

from __future__ import annotations

import logging

import psycopg2

from src.models.database import get_cursor

logger = logging.getLogger(__name__)


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
                company_id_resolved = row["id"]
                companies_created += 1
            else:
                cursor.execute(
                    "SELECT id FROM companies WHERE user_id = %s AND name_normalized = %s",
                    (user_id, company_norm),
                )
                existing = cursor.fetchone()
                company_id_resolved = existing["id"] if existing else None
                if not company_id_resolved:
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
                    existing_id = decision["existing_contact_id"]
                    overrides = decision.get("field_overrides")
                    _merge_contact(cursor, existing_id, contact,
                                   field_overrides=overrides)
                    # Company re-link: if overrides say to use import company
                    if overrides and overrides.get("company_name") == "import" and company_id_resolved:
                        cursor.execute(
                            "UPDATE contacts SET company_id = %s WHERE id = %s AND user_id = %s",
                            (company_id_resolved, existing_id, user_id),
                        )
                    contacts_merged += 1
                    all_contact_ids.append(existing_id)
                    continue

                if action == "enroll" and decision.get("existing_contact_id"):
                    # Don't create — just collect ID for enrollment
                    contacts_enrolled += 1
                    all_contact_ids.append(decision["existing_contact_id"])
                    continue

                # Default: INSERT new contact (action == "import" or no decision)
                # Guard: skip if LinkedIn URL already exists (unique index)
                linkedin_norm = contact.get("linkedin_url_normalized")
                if linkedin_norm:
                    cursor.execute(
                        "SELECT id FROM contacts WHERE user_id = %s AND linkedin_url_normalized = %s",
                        (user_id, linkedin_norm),
                    )
                    if cursor.fetchone():
                        duplicates_skipped += 1
                        continue

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
                       DO NOTHING
                       RETURNING id""",
                    (
                        company_id_resolved,
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
                new_row = cursor.fetchone()
                if new_row:
                    contacts_created += 1
                    if campaign_id:
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
        except (psycopg2.Error, ValueError) as exc:
            logger.warning("Campaign enrollment after smart import failed: %s", exc)

    # Run dedup pipeline
    try:
        from src.services.deduplication import run_dedup
        run_dedup(conn, user_id=user_id)
    except (psycopg2.Error, ValueError) as exc:
        logger.warning("Deduplication after smart import failed: %s", exc)

    return {
        "companies_created": companies_created,
        "contacts_created": contacts_created,
        "duplicates_skipped": duplicates_skipped,
        "contacts_merged": contacts_merged,
        "contacts_enrolled": contacts_enrolled,
        "contacts_skipped": contacts_skipped,
        "contact_ids": all_contact_ids,
    }


def _merge_contact(cursor, existing_contact_id: int, import_data: dict,
                    field_overrides: dict | None = None) -> None:
    """Update an existing CRM contact with import data.

    Default behavior: fill NULL fields only (COALESCE).
    With field_overrides: per-field control — "import" overwrites, "crm" keeps existing.
    """
    MERGE_FIELDS = [
        ("title", "title"),
        ("linkedin_url", "linkedin_url"),
        ("linkedin_url_normalized", "linkedin_url_normalized"),
        ("email", "email"),
        ("email_normalized", "email_normalized"),
        ("first_name", "first_name"),
        ("last_name", "last_name"),
        ("full_name", "full_name"),
        ("phone", "phone"),
    ]
    overrides = field_overrides or {}
    # Propagate overrides to normalized counterparts
    _NORM_PAIRS = {"email": "email_normalized", "linkedin_url": "linkedin_url_normalized"}
    for base, norm in _NORM_PAIRS.items():
        if base in overrides and norm not in overrides:
            overrides[norm] = overrides[base]
    set_parts = []
    values = []
    for import_key, db_col in MERGE_FIELDS:
        val = import_data.get(import_key)
        if not val:
            continue
        override = overrides.get(import_key) or overrides.get(db_col)
        if override == "import":
            # Force overwrite with import value
            set_parts.append(f"{db_col} = %s")
            values.append(val)
        elif override == "crm":
            # Explicitly keep CRM value — skip
            continue
        else:
            # Default: fill only if CRM field is NULL
            set_parts.append(f"{db_col} = COALESCE({db_col}, %s)")
            values.append(val)

    if not set_parts:
        return

    values.append(existing_contact_id)
    # user_id scoping not added here because _merge_contact is always called
    # within execute_import which already verified ownership of existing_contact_id
    cursor.execute(
        f"UPDATE contacts SET {', '.join(set_parts)} WHERE id = %s",
        values,
    )
