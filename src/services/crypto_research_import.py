"""Crypto research — warm intro lookup, company resolution, contact import, batch import."""

from __future__ import annotations

import json
import logging

import psycopg2

from src.models.database import get_cursor
from src.services.normalization_utils import normalize_company_name, split_name

logger = logging.getLogger(__name__)


def find_warm_intros(conn, company_name: str, company_id: int | None, *, user_id: int) -> dict:
    """Find existing contacts at the same or related company."""
    contact_ids = []
    notes_parts = []

    with get_cursor(conn) as cur:
        if company_id:
            cur.execute(
                """SELECT id, full_name, email, title
                   FROM contacts WHERE company_id = %s AND user_id = %s""",
                (company_id, user_id),
            )
            for row in cur.fetchall():
                contact_ids.append(row["id"])
                notes_parts.append(
                    f"Direct contact: {row['full_name']} ({row.get('title') or 'no title'})"
                )

        name_norm = normalize_company_name(company_name)
        cur.execute(
            """SELECT c.id, c.full_name, c.title, co.name AS company_name
               FROM contacts c
               JOIN companies co ON co.id = c.company_id
               WHERE co.name_normalized = %s
                 AND c.user_id = %s
                 AND c.id != ALL(%s)""",
            (name_norm, user_id, contact_ids or [0]),
        )
        for row in cur.fetchall():
            contact_ids.append(row["id"])
            notes_parts.append(
                f"Name match: {row['full_name']} at {row['company_name']}"
            )

        if company_id:
            cur.execute(
                """SELECT DISTINCT c.id, c.full_name, co.name AS company_name
                   FROM contacts c
                   JOIN companies co ON co.id = c.company_id
                   JOIN contact_campaign_status ccs ON ccs.contact_id = c.id
                   WHERE ccs.status = 'replied_positive'
                     AND co.firm_type = (
                         SELECT firm_type FROM companies WHERE id = %s AND user_id = %s
                     )
                     AND c.user_id = %s
                     AND c.id != ALL(%s)
                   LIMIT 5""",
                (company_id, user_id, user_id, contact_ids or [0]),
            )
            for row in cur.fetchall():
                notes_parts.append(
                    f"Warm lead at similar firm: {row['full_name']} ({row['company_name']})"
                )

    return {
        "contact_ids": contact_ids,
        "notes": "\n".join(notes_parts) if notes_parts else None,
    }


def resolve_or_create_company(cur, company_name: str, *, user_id: int) -> int:
    """Find existing company by normalized name or create a new one. Returns company_id."""
    if not company_name or not company_name.strip():
        raise ValueError("company_name must be a non-empty string")
    name_norm = normalize_company_name(company_name)
    cur.execute(
        "SELECT id FROM companies WHERE name_normalized = %s AND user_id = %s",
        (name_norm, user_id),
    )
    match = cur.fetchone()
    if match:
        return match["id"]
    cur.execute(
        "INSERT INTO companies (name, name_normalized, user_id) VALUES (%s, %s, %s) RETURNING id",
        (company_name, name_norm, user_id),
    )
    return cur.fetchone()["id"]


def import_single_contact(cur, contact: dict, company_id: int, *, user_id: int) -> int | None:
    """Import a single discovered contact. Returns contact_id or None if skipped."""
    name = (contact.get("name") or "").strip()
    if not name:
        return None

    first_name, last_name = split_name(name)

    email = contact.get("email")
    email_norm = email.strip().lower() if email else None
    linkedin = contact.get("linkedin")
    linkedin_norm = linkedin.rstrip("/").lower() if linkedin else None

    cur.execute(
        """INSERT INTO contacts
               (company_id, first_name, last_name, full_name,
                email, email_normalized, email_status,
                linkedin_url, linkedin_url_normalized,
                title, source, user_id)
           VALUES (%s, %s, %s, %s, %s, %s, 'unverified', %s, %s, %s, 'research', %s)
           ON CONFLICT DO NOTHING
           RETURNING id""",
        (
            company_id, first_name, last_name, name,
            email, email_norm,
            linkedin, linkedin_norm,
            contact.get("title"), user_id,
        ),
    )
    row = cur.fetchone()
    if row:
        return row["id"]
    if email_norm:
        cur.execute("SELECT id FROM contacts WHERE email_normalized = %s AND user_id = %s", (email_norm, user_id))
        existing = cur.fetchone()
        if existing:
            return existing["id"]
    if linkedin_norm:
        cur.execute("SELECT id FROM contacts WHERE linkedin_url_normalized = %s AND user_id = %s", (linkedin_norm, user_id))
        existing = cur.fetchone()
        if existing:
            return existing["id"]
    return None


def batch_import_and_enroll(
    conn,
    result_ids: list[int],
    create_deals: bool = False,
    campaign_name: str | None = None,
    *,
    user_id: int,
) -> dict:
    """Import discovered contacts, optionally create deals and enroll in campaign.

    This completes the Research -> CRM loop in one operation.
    """
    from src.models.campaigns import enroll_contact, get_campaign_by_name
    from datetime import date

    imported_contacts = 0
    deals_created = 0
    enrolled = 0
    skipped = 0

    campaign_id = None
    if campaign_name:
        camp = get_campaign_by_name(conn, campaign_name, user_id=user_id)
        if camp:
            campaign_id = camp["id"]

    with get_cursor(conn) as cur:
        try:
            # Batch fetch all results in one query (avoid N+1)
            if not result_ids:
                return {"imported_contacts": 0, "deals_created": 0, "enrolled": 0,
                        "skipped_duplicates": 0, "results_processed": 0}

            cur.execute(
                """SELECT rr.id, rr.company_id, rr.company_name, rr.crypto_score,
                          rr.evidence_summary, rr.discovered_contacts_json
                   FROM research_results rr
                   JOIN research_jobs rj ON rj.id = rr.job_id
                   WHERE rr.id = ANY(%s) AND rj.user_id = %s""",
                (result_ids, user_id),
            )
            results = [dict(row) for row in cur.fetchall()]

            for result in results:
                contacts_json = result.get("discovered_contacts_json")
                if not contacts_json:
                    continue

                discovered = (
                    contacts_json if isinstance(contacts_json, list)
                    else json.loads(contacts_json)
                )

                # Resolve company
                company_id_resolved = result["company_id"]
                if not company_id_resolved:
                    company_id_resolved = resolve_or_create_company(cur, result["company_name"], user_id=user_id)
                    cur.execute(
                        "UPDATE research_results SET company_id = %s WHERE id = %s",
                        (company_id_resolved, result["id"]),
                    )

                # Create deal if requested
                if create_deals and company_id_resolved:
                    cur.execute(
                        """INSERT INTO deals (company_id, title, stage, notes, user_id)
                           VALUES (%s, %s, 'cold', %s, %s) RETURNING id""",
                        (
                            company_id_resolved,
                            f"Research: {result['company_name']}",
                            f"Crypto score: {result.get('crypto_score', '?')}/100 - "
                            f"{result.get('evidence_summary', '')}",
                            user_id,
                        ),
                    )
                    deal_id = cur.fetchone()["id"]
                    cur.execute(
                        "INSERT INTO deal_stage_log (deal_id, to_stage, user_id) VALUES (%s, 'cold', %s)",
                        (deal_id, user_id),
                    )
                    deals_created += 1

                # Import contacts
                for contact in discovered:
                    contact_id = import_single_contact(cur, contact, company_id_resolved, user_id=user_id)
                    if contact_id is None:
                        skipped += 1
                        continue

                    imported_contacts += 1

                    if campaign_id:
                        try:
                            enroll_contact(
                                conn, contact_id, campaign_id,
                                next_action_date=date.today().isoformat(),
                                user_id=user_id,
                            )
                            enrolled += 1
                        except psycopg2.Error:
                            logger.warning("Failed to enroll contact %d in campaign %d", contact_id, campaign_id)

            conn.commit()
        except (psycopg2.Error, json.JSONDecodeError, ValueError):
            conn.rollback()
            raise

    return {
        "imported_contacts": imported_contacts,
        "deals_created": deals_created,
        "enrolled": enrolled,
        "skipped_duplicates": skipped,
        "results_processed": len(results),
    }
