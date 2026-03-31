"""E2E tests for the smart import pipeline — preview, execute, dedup, re-import."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import psycopg2
import psycopg2.extras
import pytest

from src.models.database import get_connection, get_cursor, run_migrations
from src.models.campaigns import create_campaign
from src.models.enrollment import add_sequence_step
from src.services.smart_import import preview_import, execute_import
from tests.conftest import TEST_USER_ID, insert_company, insert_contact


def _conn(tmp_db):
    """Get a fresh connection from the test DB URL."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


def _build_transformed_row(
    company_name,
    first_name,
    last_name,
    email,
    title=None,
    linkedin_url=None,
    country="US",
    aum_millions=None,
):
    """Build a transformed row dict matching the output of transform_rows()."""
    from src.services.normalization_utils import normalize_company_name, normalize_email, normalize_linkedin_url

    email_norm = normalize_email(email) if email else None
    linkedin_norm = normalize_linkedin_url(linkedin_url) if linkedin_url else None

    return {
        "company_name": company_name,
        "company_name_normalized": normalize_company_name(company_name),
        "country": country,
        "aum_millions": aum_millions,
        "firm_type": None,
        "is_gdpr": False,
        "first_name": first_name,
        "last_name": last_name,
        "full_name": f"{first_name} {last_name}",
        "email": email,
        "email_normalized": email_norm,
        "linkedin_url": linkedin_url,
        "linkedin_url_normalized": linkedin_norm,
        "title": title,
        "priority_rank": 1,
        "email_status": "unknown",
        "website": None,
        "address": None,
    }


# ---------------------------------------------------------------------------
# 11. Import with duplicate detection
# ---------------------------------------------------------------------------


def test_import_with_duplicate_detection(tmp_db):
    """Seed 1 CRM contact. Preview CSV with that contact + 2 new. 1 dup, 2 new."""
    conn = _conn(tmp_db)

    # Seed an existing contact
    co = insert_company(conn, "Existing Fund")
    existing_cid = insert_contact(
        conn, co, first_name="Alice", last_name="Existing",
        email="alice@existing.com",
    )

    # Build transformed rows: 1 duplicate + 2 new
    transformed = [
        _build_transformed_row(
            "Existing Fund", "Alice", "Existing", "alice@existing.com",
        ),
        _build_transformed_row(
            "New Fund Alpha", "Bob", "NewGuy", "bob@newalpha.com",
        ),
        _build_transformed_row(
            "New Fund Beta", "Carol", "NewGal", "carol@newbeta.com",
        ),
    ]

    result = preview_import(conn, transformed, user_id=TEST_USER_ID)

    assert result["total_contacts"] == 3
    assert result["new_contacts"] == 2

    # Find the duplicate row
    dup_rows = [r for r in result["preview_rows"] if r.get("match_type") is not None]
    new_rows = [r for r in result["preview_rows"] if r.get("match_type") is None]

    assert len(dup_rows) == 1
    assert dup_rows[0]["existing_contact_id"] == existing_cid
    assert len(new_rows) == 2

    conn.close()


# ---------------------------------------------------------------------------
# 12. Import with campaign enrollment
# ---------------------------------------------------------------------------


def test_import_with_campaign_enrollment(tmp_db):
    """Execute import with campaign_id. Verify contacts enrolled at step 1."""
    conn = _conn(tmp_db)

    campaign_id = create_campaign(conn, "import_camp", user_id=TEST_USER_ID)
    add_sequence_step(conn, campaign_id, 1, "email", delay_days=0, user_id=TEST_USER_ID)

    transformed = [
        _build_transformed_row(
            "Import Corp A", "Dan", "Import", "dan@importa.com",
        ),
        _build_transformed_row(
            "Import Corp B", "Eve", "Import", "eve@importb.com",
        ),
    ]

    # Patch run_dedup to avoid side effects
    with patch("src.services.deduplication.run_dedup"):
        result = execute_import(
            conn, transformed, user_id=TEST_USER_ID, campaign_id=campaign_id,
        )

    assert result["contacts_created"] == 2

    # Verify contacts are enrolled
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT ccs.current_step, ccs.status "
            "FROM contact_campaign_status ccs "
            "WHERE ccs.campaign_id = %s",
            (campaign_id,),
        )
        enrollments = cur.fetchall()

    assert len(enrollments) == 2
    for row in enrollments:
        assert row["current_step"] == 1
        assert row["status"] == "queued"

    conn.close()


# ---------------------------------------------------------------------------
# 13. Re-import removed contact
# ---------------------------------------------------------------------------


def test_reimport_removed_contact(tmp_db):
    """Soft-deleted contact shows as a match when re-imported via preview."""
    conn = _conn(tmp_db)

    # Create and soft-delete a contact
    co = insert_company(conn, "Removed Fund")
    cid = insert_contact(
        conn, co, first_name="Fiona", last_name="Removed",
        email="fiona@removed.com",
    )
    with get_cursor(conn) as cur:
        cur.execute(
            "UPDATE contacts SET removed_at = NOW(), removal_reason = 'test removal' "
            "WHERE id = %s",
            (cid,),
        )
        conn.commit()

    # Preview import with the same email
    transformed = [
        _build_transformed_row(
            "Removed Fund", "Fiona", "Removed", "fiona@removed.com",
        ),
    ]

    result = preview_import(conn, transformed, user_id=TEST_USER_ID)

    # The contact should match as a duplicate (email matches existing CRM record).
    # Even though removed_at is set, the contact row still exists in the DB with
    # the same email_normalized, so preview_import's batch lookup will find it.
    matched_rows = [r for r in result["preview_rows"] if r.get("match_type") is not None]
    assert len(matched_rows) == 1
    assert matched_rows[0]["existing_contact_id"] == cid

    conn.close()
