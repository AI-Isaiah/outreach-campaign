"""Tests for the smart CSV import pipeline."""

import json
import pytest
from unittest.mock import patch, MagicMock

from src.services.smart_import import (
    _heuristic_mapping,
    analyze_csv,
    transform_rows,
    preview_import,
    execute_import,
    _parse_aum,
    parse_csv_with_header_detection,
)
from src.services.normalization_utils import (
    normalize_email,
    normalize_linkedin_url,
    normalize_company_name,
)
from src.models.database import get_connection, get_cursor, run_migrations
from tests.conftest import TEST_USER_ID, insert_company, insert_contact


# --- Fixtures ---

CRYPTO_CSV_HEADERS = [
    "Firm Name", "Address", "City", "Country", "Phone", "URL", "Company LinkedIn",
    "Contact Title (Mr/Ms.)", "Primary Contact", "Position", "Primary LinkedIn", "Primary Email",
    "Contact 2", "Contact 2 Title", "Contact 2 LinkedIn", "Contact 2 Email",
    "Contact 3", "Contact 3 Title", "Contact 3 LinkedIn", "Contact 3 Email",
    "Contact 4", "Contact 4 Title", "Contact 4 LinkedIn", "Contact 4 Email",
    " AUM (Millions) ", "Firm Type", "Founded/Launch Year",
]

SAMPLE_ROW = {
    "Firm Name": "Test Capital",
    "Address": "123 Main St",
    "City": "New York",
    "Country": "United States",
    "Phone": "+1-555-0100",
    "URL": "https://testcapital.com",
    "Company LinkedIn": "https://linkedin.com/company/test-capital",
    "Contact Title (Mr/Ms.)": "Mr.",
    "Primary Contact": "John Smith",
    "Position": "Partner",
    "Primary LinkedIn": "https://linkedin.com/in/johnsmith",
    "Primary Email": "john@testcapital.com",
    "Contact 2": "Jane Doe",
    "Contact 2 Title": "VP",
    "Contact 2 LinkedIn": "https://linkedin.com/in/janedoe",
    "Contact 2 Email": "jane@testcapital.com",
    "Contact 3": "Bob Wilson",
    "Contact 3 Title": "Analyst",
    "Contact 3 LinkedIn": "",
    "Contact 3 Email": "",
    "Contact 4": "",
    "Contact 4 Title": "",
    "Contact 4 LinkedIn": "",
    "Contact 4 Email": "",
    " AUM (Millions) ": "$1,219.50",
    "Firm Type": "Venture Capital",
    "Founded/Launch Year": "2019",
}


def _setup_db(tmp_db):
    """Helper: create connection, run migrations, return conn."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


# ---------------------------------------------------------------------------
# 1. test_heuristic_mapping_simple_columns
# ---------------------------------------------------------------------------


def test_heuristic_mapping_simple_columns():
    """Basic column names map to correct dotted targets."""
    headers = ["Firm Name", "Country", "Primary Email", "Position", "URL"]
    result = _heuristic_mapping(headers)

    assert result["column_map"]["Firm Name"] == "company.name"
    assert result["column_map"]["Country"] == "company.country"
    assert result["column_map"]["Primary Email"] == "contact.email"
    assert result["column_map"]["Position"] == "contact.title"
    assert result["column_map"]["URL"] == "company.website"
    assert result["confidence"] > 0


# ---------------------------------------------------------------------------
# 2. test_heuristic_mapping_multi_contact_detection
# ---------------------------------------------------------------------------


def test_heuristic_mapping_multi_contact_detection():
    """Detects Contact 2/3/4 groups from CRYPTO_CSV_HEADERS."""
    result = _heuristic_mapping(CRYPTO_CSV_HEADERS)

    assert result["multi_contact"]["detected"] is True
    groups = result["multi_contact"]["contact_groups"]
    # Should have Primary + Contact 2 + Contact 3 + Contact 4 = 4 groups
    assert len(groups) >= 3  # At least 3 numbered contact groups

    # Verify Contact 2 group has expected fields
    contact_2_groups = [g for g in groups if g["prefix"] == "Contact 2"]
    assert len(contact_2_groups) == 1
    c2_fields = contact_2_groups[0]["fields"]
    assert "contact.full_name" in c2_fields
    assert "contact.email" in c2_fields
    assert "contact.title" in c2_fields
    assert "contact.linkedin_url" in c2_fields


# ---------------------------------------------------------------------------
# 3. test_heuristic_mapping_no_recognizable_columns
# ---------------------------------------------------------------------------


def test_heuristic_mapping_no_recognizable_columns():
    """Random column names produce empty map and low confidence."""
    headers = ["foo", "bar", "baz", "qux", "quux"]
    result = _heuristic_mapping(headers)

    assert result["column_map"] == {}
    assert result["confidence"] == 0.0
    assert result["multi_contact"]["detected"] is False
    assert set(result["unmapped"]) == set(headers)


# ---------------------------------------------------------------------------
# 4. test_heuristic_mapping_crypto_fund_headers
# ---------------------------------------------------------------------------


def test_heuristic_mapping_crypto_fund_headers():
    """CRYPTO_CSV_HEADERS maps Firm Name, Country, URL, AUM, etc."""
    result = _heuristic_mapping(CRYPTO_CSV_HEADERS)
    cmap = result["column_map"]

    assert cmap.get("Firm Name") == "company.name"
    assert cmap.get("Country") == "company.country"
    assert cmap.get("URL") == "company.website"
    assert cmap.get(" AUM (Millions) ") == "company.aum"
    assert cmap.get("Address") == "company.address"
    assert cmap.get("Primary Contact") == "contact.full_name"
    assert cmap.get("Primary Email") == "contact.email"
    assert cmap.get("Primary LinkedIn") == "contact.linkedin_url"
    assert cmap.get("Position") == "contact.title"
    assert cmap.get("Phone") == "contact.phone"
    assert cmap.get("Firm Type") == "company.firm_type"


# ---------------------------------------------------------------------------
# 5. test_analyze_csv_mocked_llm_success
# ---------------------------------------------------------------------------


def test_analyze_csv_mocked_llm_success():
    """Mock _call_llm to return valid JSON with dotted fields; verify result."""
    llm_response = json.dumps({
        "column_map": {
            "Firm Name": "company.name",
            "Country": "company.country",
            "Primary Email": "contact.email",
        },
        "unmapped": ["City", "Phone"],
        "multi_contact": {"detected": False, "contact_groups": []},
        "confidence": 0.8,
    })

    mock_conn = MagicMock()
    headers = ["Firm Name", "Country", "Primary Email", "City", "Phone"]
    sample_rows = [{"Firm Name": "Acme", "Country": "US", "Primary Email": "a@b.com",
                     "City": "NYC", "Phone": "555"}]

    with patch("src.services.smart_import._call_llm", return_value=(llm_response, "anthropic")):
        result = analyze_csv(headers, sample_rows, user_id=1, conn=mock_conn)

    assert result["provider"] == "anthropic"
    assert result["column_map"]["Firm Name"] == "company.name"
    assert result["column_map"]["Country"] == "company.country"
    assert result["column_map"]["Primary Email"] == "contact.email"
    assert result["confidence"] > 0


# ---------------------------------------------------------------------------
# 6. test_analyze_csv_llm_failure_heuristic_fallback
# ---------------------------------------------------------------------------


def test_analyze_csv_llm_failure_heuristic_fallback():
    """Mock _call_llm to raise RuntimeError; heuristic fallback used."""
    mock_conn = MagicMock()
    headers = ["Firm Name", "Country", "Primary Email"]
    sample_rows = [{"Firm Name": "Acme", "Country": "US", "Primary Email": "a@b.com"}]

    with patch("src.services.smart_import._call_llm", side_effect=RuntimeError("No API key")):
        result = analyze_csv(headers, sample_rows, user_id=1, conn=mock_conn)

    # Falls back to heuristic: provider should be None
    assert result["provider"] is None
    # Heuristic should still map known columns
    assert result["column_map"]["Firm Name"] == "company.name"
    assert result["column_map"]["Country"] == "company.country"
    assert result["column_map"]["Primary Email"] == "contact.email"


# ---------------------------------------------------------------------------
# 7. test_analyze_csv_llm_partial_heuristic_merge
# ---------------------------------------------------------------------------


def test_analyze_csv_llm_partial_heuristic_merge():
    """Mock LLM returns partial map; heuristic fills gaps."""
    # LLM only maps Firm Name, misses Primary Email and Country
    llm_response = json.dumps({
        "column_map": {"Firm Name": "company.name"},
        "unmapped": ["Country", "Primary Email", "Position"],
        "multi_contact": {"detected": False, "contact_groups": []},
        "confidence": 0.3,
    })

    mock_conn = MagicMock()
    headers = ["Firm Name", "Country", "Primary Email", "Position"]
    sample_rows = [{"Firm Name": "Acme", "Country": "US",
                     "Primary Email": "a@b.com", "Position": "MD"}]

    with patch("src.services.smart_import._call_llm", return_value=(llm_response, "openai")):
        result = analyze_csv(headers, sample_rows, user_id=1, conn=mock_conn)

    assert result["provider"] == "openai"
    # LLM mapping preserved
    assert result["column_map"]["Firm Name"] == "company.name"
    # Heuristic filled gaps
    assert result["column_map"]["Country"] == "company.country"
    assert result["column_map"]["Primary Email"] == "contact.email"
    assert result["column_map"]["Position"] == "contact.title"
    # Confidence should be boosted after merge
    assert result["confidence"] > 0.3


# ---------------------------------------------------------------------------
# 8. test_transform_rows_dotted_targets
# ---------------------------------------------------------------------------


def test_transform_rows_dotted_targets():
    """Single-contact row with company.name, contact.email etc. produces correct output."""
    rows = [{
        "Firm Name": "Alpha Fund",
        "Country": "Switzerland",
        "Primary Email": "alice@alpha.com",
        "Position": "CIO",
        "Primary LinkedIn": "https://linkedin.com/in/alice",
    }]
    mapping = {
        "Firm Name": "company.name",
        "Country": "company.country",
        "Primary Email": "contact.email",
        "Position": "contact.title",
        "Primary LinkedIn": "contact.linkedin_url",
    }
    multi_contact = {"detected": False, "contact_groups": []}

    result = transform_rows(rows, mapping, multi_contact, gdpr_countries=["switzerland"])
    assert len(result) == 1

    r = result[0]
    assert r["company_name"] == "Alpha Fund"
    assert r["country"] == "Switzerland"
    assert r["email"] == "alice@alpha.com"
    assert r["email_normalized"] == "alice@alpha.com"
    assert r["title"] == "CIO"
    assert r["linkedin_url"] == "https://linkedin.com/in/alice"
    assert r["is_gdpr"] is True  # Switzerland is in GDPR list


# ---------------------------------------------------------------------------
# 9. test_transform_rows_multi_contact_explosion
# ---------------------------------------------------------------------------


def test_transform_rows_multi_contact_explosion():
    """One row with 4 contact slots produces 3 output rows (Contact 4 is empty, skipped)."""
    multi_contact = {
        "detected": True,
        "contact_groups": [
            {"prefix": "Primary", "fields": {
                "contact.full_name": "Primary Contact",
                "contact.email": "Primary Email",
                "contact.title": "Position",
                "contact.linkedin_url": "Primary LinkedIn",
            }},
            {"prefix": "Contact 2", "fields": {
                "contact.full_name": "Contact 2",
                "contact.email": "Contact 2 Email",
                "contact.title": "Contact 2 Title",
                "contact.linkedin_url": "Contact 2 LinkedIn",
            }},
            {"prefix": "Contact 3", "fields": {
                "contact.full_name": "Contact 3",
                "contact.email": "Contact 3 Email",
                "contact.title": "Contact 3 Title",
                "contact.linkedin_url": "Contact 3 LinkedIn",
            }},
            {"prefix": "Contact 4", "fields": {
                "contact.full_name": "Contact 4",
                "contact.email": "Contact 4 Email",
                "contact.title": "Contact 4 Title",
                "contact.linkedin_url": "Contact 4 LinkedIn",
            }},
        ],
    }
    mapping = {
        "Firm Name": "company.name",
        "Country": "company.country",
    }

    result = transform_rows([SAMPLE_ROW], mapping, multi_contact, gdpr_countries=[])

    # Contact 4 has empty name+email so should be skipped -> 3 output rows
    assert len(result) == 3

    # All rows share the same company
    for r in result:
        assert r["company_name"] == "Test Capital"

    # Check contacts are present (sorted: email DESC, linkedin DESC)
    emails = [r["email"] for r in result if r["email"]]
    assert "john@testcapital.com" in emails
    assert "jane@testcapital.com" in emails

    full_names = [r["full_name"] for r in result]
    assert "John Smith" in full_names
    assert "Jane Doe" in full_names
    assert "Bob Wilson" in full_names


# ---------------------------------------------------------------------------
# 10. test_transform_rows_full_name_splitting
# ---------------------------------------------------------------------------


def test_transform_rows_full_name_splitting():
    """Full name 'John Smith' is split into first_name='John', last_name='Smith'."""
    rows = [{"Company": "Beta LLC", "Name": "John Smith", "Email": "j@b.com"}]
    mapping = {
        "Company": "company.name",
        "Name": "contact.full_name",
        "Email": "contact.email",
    }
    multi_contact = {"detected": False, "contact_groups": []}

    result = transform_rows(rows, mapping, multi_contact, gdpr_countries=[])
    assert len(result) == 1
    assert result[0]["first_name"] == "John"
    assert result[0]["last_name"] == "Smith"
    assert result[0]["full_name"] == "John Smith"


# ---------------------------------------------------------------------------
# 11. test_transform_rows_empty_contact_slots_skipped
# ---------------------------------------------------------------------------


def test_transform_rows_empty_contact_slots_skipped():
    """Empty contact groups produce no output rows for that group."""
    row = {
        "Company": "Gamma Corp",
        "Contact 1 Name": "Alice",
        "Contact 1 Email": "alice@gamma.com",
        "Contact 2 Name": "",
        "Contact 2 Email": "",
        "Contact 3 Name": "",
        "Contact 3 Email": "",
    }
    mapping = {"Company": "company.name"}
    multi_contact = {
        "detected": True,
        "contact_groups": [
            {"prefix": "Contact 1", "fields": {
                "contact.full_name": "Contact 1 Name",
                "contact.email": "Contact 1 Email",
            }},
            {"prefix": "Contact 2", "fields": {
                "contact.full_name": "Contact 2 Name",
                "contact.email": "Contact 2 Email",
            }},
            {"prefix": "Contact 3", "fields": {
                "contact.full_name": "Contact 3 Name",
                "contact.email": "Contact 3 Email",
            }},
        ],
    }

    result = transform_rows([row], mapping, multi_contact, gdpr_countries=[])
    # Only Contact 1 has data; Contact 2 and 3 are empty -> skipped
    assert len(result) == 1
    assert result[0]["full_name"] == "Alice"
    assert result[0]["email"] == "alice@gamma.com"


# ---------------------------------------------------------------------------
# 12. test_parse_aum
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$1,219.50", 1219.5),
        ("500", 500.0),
        ("$100", 100.0),
        ("1,000,000", 1000000.0),
        ("", None),
        (None, None),
        ("N/A", None),
        ("unknown", None),
        ("  $42.00  ", 42.0),
    ],
)
def test_parse_aum(raw, expected):
    """_parse_aum handles currency strings, empty strings, and non-numeric values."""
    assert _parse_aum(raw) == expected


# ---------------------------------------------------------------------------
# 13. test_preview_import_duplicate_detection
# ---------------------------------------------------------------------------


def test_preview_import_duplicate_detection(tmp_db):
    """Insert an existing contact, preview detects email-only match."""
    conn = _setup_db(tmp_db)

    # Insert a company and contact that will collide with the transformed data.
    # insert_contact() auto-generates a LinkedIn URL, but the import row has none,
    # so this is an email_only match (not exact).
    company_id = insert_company(conn, "Existing Corp")
    insert_contact(
        conn, company_id,
        first_name="Alice", last_name="Existing",
        email="alice@existing.com",
    )

    # Build transformed rows -- one email-only match, one new
    transformed = [
        {
            "company_name": "Existing Corp",
            "company_name_normalized": "existing corp",
            "country": "US",
            "aum_millions": None,
            "firm_type": None,
            "is_gdpr": False,
            "first_name": "Alice",
            "last_name": "Existing",
            "full_name": "Alice Existing",
            "email": "alice@existing.com",
            "email_normalized": "alice@existing.com",
            "linkedin_url": None,
            "linkedin_url_normalized": None,
            "title": None,
            "priority_rank": 1,
            "email_status": "unknown",
            "website": None,
            "address": None,
        },
        {
            "company_name": "New Corp",
            "company_name_normalized": "new corp",
            "country": "US",
            "aum_millions": None,
            "firm_type": None,
            "is_gdpr": False,
            "first_name": "Bob",
            "last_name": "New",
            "full_name": "Bob New",
            "email": "bob@newcorp.com",
            "email_normalized": "bob@newcorp.com",
            "linkedin_url": None,
            "linkedin_url_normalized": None,
            "title": None,
            "priority_rank": 1,
            "email_status": "unknown",
            "website": None,
            "address": None,
        },
    ]

    result = preview_import(conn, transformed, user_id=TEST_USER_ID)

    assert result["total_contacts"] == 2
    # Email-only match is not an exact duplicate — only exact matches count
    assert result["duplicates"] == 0
    # Alice is email_only match → classified as "review" tier, not "new"
    assert result["new_contacts"] == 1
    assert result["total_companies"] == 2

    # Check that preview_rows marks the match correctly
    alice_row = [r for r in result["preview_rows"] if r["email"] == "alice@existing.com"][0]
    bob_row = [r for r in result["preview_rows"] if r["email"] == "bob@newcorp.com"][0]
    assert alice_row["match_type"] == "email_only"
    assert alice_row["is_duplicate"] is False
    assert alice_row["existing_contact_id"] is not None
    assert alice_row["field_diffs"] is not None
    assert bob_row["match_type"] is None
    assert bob_row["is_duplicate"] is False

    conn.close()


# ---------------------------------------------------------------------------
# 14. test_execute_import_creates_records
# ---------------------------------------------------------------------------


def test_execute_import_creates_records(tmp_db):
    """Full pipeline creates companies + contacts in DB."""
    conn = _setup_db(tmp_db)

    transformed = [
        {
            "company_name": "Delta Fund",
            "company_name_normalized": "delta fund",
            "country": "Germany",
            "aum_millions": 500.0,
            "firm_type": "Hedge Fund",
            "is_gdpr": True,
            "first_name": "Hans",
            "last_name": "Mueller",
            "full_name": "Hans Mueller",
            "email": "hans@delta.com",
            "email_normalized": "hans@delta.com",
            "linkedin_url": "https://linkedin.com/in/hansmueller",
            "linkedin_url_normalized": "https://linkedin.com/in/hansmueller",
            "title": "Managing Director",
            "priority_rank": 1,
            "email_status": "unknown",
            "website": "https://deltafund.com",
            "address": "Berlin, DE",
        },
        {
            "company_name": "Delta Fund",
            "company_name_normalized": "delta fund",
            "country": "Germany",
            "aum_millions": 500.0,
            "firm_type": "Hedge Fund",
            "is_gdpr": True,
            "first_name": "Greta",
            "last_name": "Schmidt",
            "full_name": "Greta Schmidt",
            "email": "greta@delta.com",
            "email_normalized": "greta@delta.com",
            "linkedin_url": None,
            "linkedin_url_normalized": None,
            "title": "Analyst",
            "priority_rank": 2,
            "email_status": "unknown",
            "website": "https://deltafund.com",
            "address": "Berlin, DE",
        },
        {
            "company_name": "Epsilon Capital",
            "company_name_normalized": "epsilon capital",
            "country": "US",
            "aum_millions": 1200.0,
            "firm_type": "Venture Capital",
            "is_gdpr": False,
            "first_name": "Eve",
            "last_name": "Adams",
            "full_name": "Eve Adams",
            "email": "eve@epsilon.com",
            "email_normalized": "eve@epsilon.com",
            "linkedin_url": None,
            "linkedin_url_normalized": None,
            "title": "Partner",
            "priority_rank": 1,
            "email_status": "unknown",
            "website": None,
            "address": None,
        },
    ]

    with patch("src.services.deduplication.run_dedup"):
        stats = execute_import(conn, transformed, user_id=TEST_USER_ID)

    assert stats["companies_created"] == 2
    assert stats["contacts_created"] == 3
    assert stats["duplicates_skipped"] == 0

    # Verify DB records
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS cnt FROM companies WHERE user_id = %s", (TEST_USER_ID,))
    assert cursor.fetchone()["cnt"] == 2

    cursor.execute("SELECT COUNT(*) AS cnt FROM contacts WHERE user_id = %s", (TEST_USER_ID,))
    assert cursor.fetchone()["cnt"] == 3

    # Check company details
    cursor.execute(
        "SELECT * FROM companies WHERE name_normalized = %s AND user_id = %s",
        ("delta fund", TEST_USER_ID),
    )
    delta = cursor.fetchone()
    assert delta["aum_millions"] == 500.0
    assert delta["firm_type"] == "Hedge Fund"
    assert delta["is_gdpr"] is True

    # Check contact details
    cursor.execute(
        "SELECT * FROM contacts WHERE email_normalized = %s AND user_id = %s",
        ("hans@delta.com", TEST_USER_ID),
    )
    hans = cursor.fetchone()
    assert hans["first_name"] == "Hans"
    assert hans["last_name"] == "Mueller"
    assert hans["title"] == "Managing Director"
    assert hans["source"] == "csv_smart"

    cursor.close()
    conn.close()


# ---------------------------------------------------------------------------
# 15. test_state_machine_re_preview
# ---------------------------------------------------------------------------


def test_state_machine_re_preview(tmp_db):
    """A job with status='previewed' can be re-previewed (status accepted by preview route logic)."""
    conn = _setup_db(tmp_db)

    # Insert an import job with status 'previewed'
    job_id = "test-job-re-preview-001"
    raw_rows = [{"Firm Name": "Zeta Corp", "Primary Email": "z@zeta.com"}]
    headers = ["Firm Name", "Primary Email"]
    column_mapping = {"Firm Name": "company.name", "Primary Email": "contact.email"}
    multi_contact = {"detected": False, "contact_groups": []}

    with get_cursor(conn) as cursor:
        cursor.execute(
            """INSERT INTO import_jobs
               (id, user_id, status, raw_rows, headers, column_mapping,
                multi_contact_pattern, row_count)
               VALUES (%s, %s, 'previewed', %s, %s, %s, %s, %s)""",
            (
                job_id,
                TEST_USER_ID,
                json.dumps(raw_rows),
                json.dumps(headers),
                json.dumps(column_mapping),
                json.dumps(multi_contact),
                len(raw_rows),
            ),
        )
    conn.commit()

    # Verify the job was stored with correct status
    with get_cursor(conn) as cursor:
        cursor.execute(
            "SELECT * FROM import_jobs WHERE id = %s AND user_id = %s",
            (job_id, TEST_USER_ID),
        )
        job = cursor.fetchone()

    assert job is not None
    assert job["status"] == "previewed"

    # The preview route accepts 'pending' or 'previewed' status.
    # Verify that status is in the allowed set for re-preview.
    assert job["status"] in ("pending", "previewed")

    # Verify raw_rows and column_mapping are recoverable
    stored_rows = job["raw_rows"]
    if isinstance(stored_rows, str):
        stored_rows = json.loads(stored_rows)
    assert stored_rows == raw_rows

    stored_mapping = job["column_mapping"]
    if isinstance(stored_mapping, str):
        stored_mapping = json.loads(stored_mapping)
    assert stored_mapping == column_mapping

    conn.close()


# ---------------------------------------------------------------------------
# Helpers for new duplicate redesign tests
# ---------------------------------------------------------------------------


def _make_transformed_row(
    company="Acme Corp",
    email="alice@acme.com",
    linkedin="https://linkedin.com/in/alice",
    first_name="Alice",
    last_name="Smith",
    title="CEO",
    **overrides,
):
    """Helper to build a transformed row dict."""
    row = {
        "company_name": company,
        "company_name_normalized": normalize_company_name(company),
        "country": None,
        "aum_millions": None,
        "firm_type": None,
        "is_gdpr": False,
        "first_name": first_name,
        "last_name": last_name,
        "full_name": f"{first_name} {last_name}",
        "email": email,
        "email_normalized": normalize_email(email) if email else None,
        "linkedin_url": linkedin,
        "linkedin_url_normalized": normalize_linkedin_url(linkedin) if linkedin else None,
        "title": title,
        "priority_rank": 1,
        "email_status": "unknown",
        "website": None,
        "address": None,
    }
    row.update(overrides)
    return row


def _insert_existing_contact(conn, *, email=None, linkedin_url=None, title=None,
                              first_name="Alice", last_name="Smith"):
    """Insert a company + contact into the DB, return (company_id, contact_id)."""
    email_norm = normalize_email(email) if email else None
    linkedin_norm = normalize_linkedin_url(linkedin_url) if linkedin_url else None
    with get_cursor(conn) as cur:
        # Use upsert: try insert, fetch if exists
        cur.execute(
            "SELECT id FROM companies WHERE name_normalized = 'acme corp' AND user_id = %s",
            (TEST_USER_ID,),
        )
        existing = cur.fetchone()
        if existing:
            co_id_result = existing
        else:
            cur.execute(
                """INSERT INTO companies (name, name_normalized, user_id)
                   VALUES ('Acme Corp', 'acme corp', %s) RETURNING id""",
                (TEST_USER_ID,),
            )
            co_id_result = cur.fetchone()
        co_id = co_id_result["id"]
        cur.execute(
            """INSERT INTO contacts
               (company_id, first_name, last_name, full_name,
                email, email_normalized,
                linkedin_url, linkedin_url_normalized,
                title, user_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (co_id, first_name, last_name, f"{first_name} {last_name}",
             email, email_norm, linkedin_url, linkedin_norm, title, TEST_USER_ID),
        )
        contact_id = cur.fetchone()["id"]
    conn.commit()
    return co_id, contact_id


# ---------------------------------------------------------------------------
# 16. preview_import field-level diffs (P0)
# ---------------------------------------------------------------------------


class TestPreviewImportFieldDiffs:
    """preview_import should return field-level diffs instead of auto-clearing."""

    def test_new_contact_has_no_diffs(self, tmp_db):
        conn = _setup_db(tmp_db)
        try:
            row = _make_transformed_row()
            result = preview_import(conn, [row], user_id=TEST_USER_ID)
            r = result["preview_rows"][0]
            assert r["match_type"] is None
            assert r["field_diffs"] is None
            assert r["existing_contact"] is None
            assert r["existing_contact_id"] is None
            assert r["email"] == "alice@acme.com"
            assert r["linkedin_url"] == "https://linkedin.com/in/alice"
        finally:
            conn.close()

    def test_exact_match_returns_diffs(self, tmp_db):
        conn = _setup_db(tmp_db)
        try:
            _co_id, contact_id = _insert_existing_contact(
                conn, email="alice@acme.com",
                linkedin_url="https://linkedin.com/in/alice", title="CFO",
            )
            row = _make_transformed_row(title="CEO")
            result = preview_import(conn, [row], user_id=TEST_USER_ID)
            r = result["preview_rows"][0]
            assert r["match_type"] == "exact"
            assert r["existing_contact_id"] == contact_id
            assert r["existing_contact"]["title"] == "CFO"
            assert r["field_diffs"]["title"] == "conflict"
            assert r["field_diffs"]["email"] == "same"
            assert r["email"] == "alice@acme.com"
            assert r["linkedin_url"] == "https://linkedin.com/in/alice"
        finally:
            conn.close()

    def test_email_only_match_shows_enrichable_fields(self, tmp_db):
        conn = _setup_db(tmp_db)
        try:
            _co_id, contact_id = _insert_existing_contact(
                conn, email="alice@acme.com", linkedin_url=None, title=None,
            )
            row = _make_transformed_row(title="CEO")
            result = preview_import(conn, [row], user_id=TEST_USER_ID)
            r = result["preview_rows"][0]
            assert r["match_type"] == "email_only"
            assert r["existing_contact_id"] == contact_id
            assert r["field_diffs"]["linkedin_url"] == "new"
            assert r["field_diffs"]["title"] == "new"
            assert r["email"] == "alice@acme.com"
            assert r["linkedin_url"] == "https://linkedin.com/in/alice"
        finally:
            conn.close()

    def test_linkedin_only_match(self, tmp_db):
        conn = _setup_db(tmp_db)
        try:
            _co_id, contact_id = _insert_existing_contact(
                conn, email=None, linkedin_url="https://linkedin.com/in/alice",
            )
            row = _make_transformed_row()
            result = preview_import(conn, [row], user_id=TEST_USER_ID)
            r = result["preview_rows"][0]
            assert r["match_type"] == "linkedin_only"
            assert r["existing_contact_id"] == contact_id
            assert r["field_diffs"]["email"] == "new"
        finally:
            conn.close()

    def test_both_match_different_contacts(self, tmp_db):
        """Email matches contact A, LinkedIn matches contact B."""
        conn = _setup_db(tmp_db)
        try:
            _insert_existing_contact(
                conn, email="alice@acme.com", linkedin_url=None,
                first_name="Alice", last_name="A",
            )
            _insert_existing_contact(
                conn, email=None, linkedin_url="https://linkedin.com/in/alice",
                first_name="Alice", last_name="B",
            )
            row = _make_transformed_row()
            result = preview_import(conn, [row], user_id=TEST_USER_ID)
            r = result["preview_rows"][0]
            assert r["match_type"] == "both_different_contacts"
            assert r["existing_contact_id"] is not None
            assert r["is_duplicate"] is False
            # Import data preserved
            assert r["email"] == "alice@acme.com"
            assert r["linkedin_url"] == "https://linkedin.com/in/alice"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 17. execute_import with row decisions (P0)
# ---------------------------------------------------------------------------


class TestExecuteImportWithDecisions:
    """execute_import should handle per-row merge/skip/enroll decisions."""

    def test_merge_enriches_existing_contact(self, tmp_db):
        conn = _setup_db(tmp_db)
        try:
            _co_id, contact_id = _insert_existing_contact(
                conn, email="alice@acme.com", linkedin_url=None, title=None,
            )
            row = _make_transformed_row(title="CEO")
            decisions = {0: {"action": "merge", "existing_contact_id": contact_id}}
            with patch("src.services.deduplication.run_dedup"):
                result = execute_import(conn, [row], user_id=TEST_USER_ID, row_decisions=decisions)
            assert result["contacts_merged"] == 1

            with get_cursor(conn) as cur:
                cur.execute("SELECT title, linkedin_url FROM contacts WHERE id = %s", (contact_id,))
                updated = cur.fetchone()
            assert updated["title"] == "CEO"
            assert updated["linkedin_url"] == "https://linkedin.com/in/alice"
        finally:
            conn.close()

    def test_skip_decision_does_not_create(self, tmp_db):
        conn = _setup_db(tmp_db)
        try:
            row = _make_transformed_row()
            decisions = {0: {"action": "skip"}}
            with patch("src.services.deduplication.run_dedup"):
                result = execute_import(conn, [row], user_id=TEST_USER_ID, row_decisions=decisions)
            assert result["contacts_created"] == 0
            assert result["contacts_skipped"] == 1
        finally:
            conn.close()

    def test_enroll_decision_enrolls_existing(self, tmp_db):
        conn = _setup_db(tmp_db)
        try:
            _co_id, contact_id = _insert_existing_contact(
                conn, email="alice@acme.com",
            )
            with get_cursor(conn) as cur:
                cur.execute(
                    "INSERT INTO campaigns (name, user_id) VALUES ('Q1', %s) RETURNING id",
                    (TEST_USER_ID,),
                )
                campaign_id = cur.fetchone()["id"]
            conn.commit()

            row = _make_transformed_row()
            decisions = {0: {"action": "enroll", "existing_contact_id": contact_id}}
            with patch("src.services.deduplication.run_dedup"):
                result = execute_import(
                    conn, [row], user_id=TEST_USER_ID,
                    row_decisions=decisions, campaign_id=campaign_id,
                )
            assert result["contacts_enrolled"] >= 1

            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT * FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
                    (contact_id, campaign_id),
                )
                assert cur.fetchone() is not None
        finally:
            conn.close()

    def test_no_decisions_uses_legacy_behavior(self, tmp_db):
        conn = _setup_db(tmp_db)
        try:
            row = _make_transformed_row(email="new@example.com", linkedin=None)
            with patch("src.services.deduplication.run_dedup"):
                result = execute_import(conn, [row], user_id=TEST_USER_ID)
            assert result["contacts_created"] == 1
        finally:
            conn.close()

    def test_new_contact_enrolled_in_campaign(self, tmp_db):
        """New contact created with campaign_id gets enrolled."""
        conn = _setup_db(tmp_db)
        try:
            with get_cursor(conn) as cur:
                cur.execute(
                    "INSERT INTO campaigns (name, user_id) VALUES ('Q2', %s) RETURNING id",
                    (TEST_USER_ID,),
                )
                campaign_id = cur.fetchone()["id"]
            conn.commit()

            row = _make_transformed_row(email="brand-new@example.com", linkedin=None)
            decisions = {0: {"action": "import"}}
            with patch("src.services.deduplication.run_dedup"):
                result = execute_import(
                    conn, [row], user_id=TEST_USER_ID,
                    row_decisions=decisions, campaign_id=campaign_id,
                )
            assert result["contacts_created"] == 1
            assert result["contacts_enrolled"] >= 1

            # Verify enrollment exists
            with get_cursor(conn) as cur:
                cur.execute(
                    """SELECT ccs.* FROM contact_campaign_status ccs
                       JOIN contacts c ON c.id = ccs.contact_id
                       WHERE c.email_normalized = %s AND ccs.campaign_id = %s""",
                    ("brand-new@example.com", campaign_id),
                )
                assert cur.fetchone() is not None
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 18. Header detection (moved to services, P2)
# ---------------------------------------------------------------------------


class TestHeaderDetection:
    def test_detect_header_row_with_metadata_prefix(self):
        csv_content = (
            "Report generated 2026-03-24,,,,\n"
            "Source: LinkedIn Export,,,,\n"
            "Firm Name,Country,Primary Contact,Primary Email,Position\n"
            "Acme Corp,USA,Alice Smith,alice@acme.com,CEO\n"
        )
        headers, rows = parse_csv_with_header_detection(csv_content)
        assert "Firm Name" in headers
        assert len(rows) == 1
        assert rows[0]["Primary Contact"] == "Alice Smith"

    def test_detect_header_row_first_row(self):
        csv_content = "Name,Email,Company\nAlice,alice@test.com,Acme\n"
        headers, rows = parse_csv_with_header_detection(csv_content)
        assert headers == ["Name", "Email", "Company"]
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# 19. Within-file duplicate detection (P1)
# ---------------------------------------------------------------------------


class TestWithinFileDuplicates:
    def test_same_email_twice_in_file(self, tmp_db):
        conn = _setup_db(tmp_db)
        try:
            row1 = _make_transformed_row(first_name="Alice", email="alice@acme.com")
            row2 = _make_transformed_row(first_name="Alicia", email="alice@acme.com", title="VP")
            result = preview_import(conn, [row1, row2], user_id=TEST_USER_ID)
            rows = result["preview_rows"]
            assert rows[0].get("within_file_duplicate") is False
            assert rows[1]["within_file_duplicate"] is True
            assert rows[1]["within_file_duplicate_of"] == 0
        finally:
            conn.close()

    def test_different_emails_not_flagged(self, tmp_db):
        conn = _setup_db(tmp_db)
        try:
            row1 = _make_transformed_row(email="alice@acme.com", linkedin="https://linkedin.com/in/alice")
            row2 = _make_transformed_row(email="bob@acme.com", first_name="Bob", linkedin="https://linkedin.com/in/bob")
            result = preview_import(conn, [row1, row2], user_id=TEST_USER_ID)
            rows = result["preview_rows"]
            assert rows[0].get("within_file_duplicate") is False
            assert rows[1].get("within_file_duplicate") is False
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 20–37. Smart Duplicate Resolution V2 tests
# ---------------------------------------------------------------------------


def _insert_contact_at_company(conn, company_name, *, email=None, linkedin_url=None,
                                title=None, first_name="Alice", last_name="Smith"):
    """Insert a company (by name) + contact, return (company_id, contact_id).

    Unlike _insert_existing_contact which always uses 'Acme Corp', this helper
    accepts an arbitrary company name so tests can set up cross-company scenarios.
    """
    name_norm = normalize_company_name(company_name)
    email_norm = normalize_email(email) if email else None
    linkedin_norm = normalize_linkedin_url(linkedin_url) if linkedin_url else None
    with get_cursor(conn) as cur:
        cur.execute(
            "SELECT id FROM companies WHERE name_normalized = %s AND user_id = %s",
            (name_norm, TEST_USER_ID),
        )
        existing = cur.fetchone()
        if existing:
            co_id = existing["id"]
        else:
            cur.execute(
                """INSERT INTO companies (name, name_normalized, user_id)
                   VALUES (%s, %s, %s) RETURNING id""",
                (company_name, name_norm, TEST_USER_ID),
            )
            co_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO contacts
               (company_id, first_name, last_name, full_name,
                email, email_normalized,
                linkedin_url, linkedin_url_normalized,
                title, user_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (co_id, first_name, last_name, f"{first_name} {last_name}",
             email, email_norm, linkedin_url, linkedin_norm, title, TEST_USER_ID),
        )
        contact_id = cur.fetchone()["id"]
    conn.commit()
    return co_id, contact_id


# ---------------------------------------------------------------------------
# 20. test_tier_classification_auto_merge
# ---------------------------------------------------------------------------


def test_tier_classification_auto_merge(tmp_db):
    """Exact match (email+LinkedIn) + same company -> resolution_tier = 'auto_merge'."""
    conn = _setup_db(tmp_db)
    try:
        _insert_contact_at_company(
            conn, "Acme Corp",
            email="alice@acme.com",
            linkedin_url="https://linkedin.com/in/alice",
            title="CEO",
        )
        row = _make_transformed_row(
            company="Acme Corp",
            email="alice@acme.com",
            linkedin="https://linkedin.com/in/alice",
            title="CEO",
        )
        result = preview_import(conn, [row], user_id=TEST_USER_ID)
        r = result["preview_rows"][0]
        assert r["match_type"] == "exact"
        assert r["resolution_tier"] == "auto_merge"
        assert r["is_duplicate"] is True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 21. test_tier_classification_company_change
# ---------------------------------------------------------------------------


def test_tier_classification_company_change(tmp_db):
    """Exact match (email+LinkedIn) + different company -> resolution_tier = 'company_change'."""
    conn = _setup_db(tmp_db)
    try:
        _insert_contact_at_company(
            conn, "Old Ventures",
            email="alice@old.com",
            linkedin_url="https://linkedin.com/in/alice",
            title="VP",
        )
        row = _make_transformed_row(
            company="New Capital",
            email="alice@old.com",
            linkedin="https://linkedin.com/in/alice",
            title="VP",
        )
        result = preview_import(conn, [row], user_id=TEST_USER_ID)
        r = result["preview_rows"][0]
        assert r["match_type"] == "exact"
        assert r["resolution_tier"] == "company_change"
        assert "company_name" in r["conflict_fields"]
        assert r["existing_company_name"] == "Old Ventures"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 22. test_tier_classification_review_email_diff
# ---------------------------------------------------------------------------


def test_tier_classification_review_email_diff(tmp_db):
    """LinkedIn match + different email -> resolution_tier = 'review'."""
    conn = _setup_db(tmp_db)
    try:
        _insert_contact_at_company(
            conn, "Acme Corp",
            email="alice-old@acme.com",
            linkedin_url="https://linkedin.com/in/alice",
            title="CEO",
        )
        row = _make_transformed_row(
            company="Acme Corp",
            email="alice-new@acme.com",
            linkedin="https://linkedin.com/in/alice",
            title="CEO",
        )
        result = preview_import(conn, [row], user_id=TEST_USER_ID)
        r = result["preview_rows"][0]
        # LinkedIn matches but email differs -> linkedin_only match
        # (email doesn't match an existing contact, linkedin does)
        assert r["match_type"] == "linkedin_only"
        assert r["resolution_tier"] == "review"
        # email should be a conflict or new since CRM has different email
        diffs = r["field_diffs"]
        assert diffs["email"] in ("conflict", "new")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 23. test_tier_classification_review_email_only
# ---------------------------------------------------------------------------


def test_tier_classification_review_email_only(tmp_db):
    """Email-only match (no LinkedIn match) -> resolution_tier = 'review'."""
    conn = _setup_db(tmp_db)
    try:
        _insert_contact_at_company(
            conn, "Acme Corp",
            email="alice@acme.com",
            linkedin_url=None,
            title="CEO",
        )
        row = _make_transformed_row(
            company="Acme Corp",
            email="alice@acme.com",
            linkedin="https://linkedin.com/in/alice",
            title="CEO",
        )
        result = preview_import(conn, [row], user_id=TEST_USER_ID)
        r = result["preview_rows"][0]
        assert r["match_type"] == "email_only"
        assert r["resolution_tier"] == "review"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 24. test_auto_merge_fills_empty_fields
# ---------------------------------------------------------------------------


def test_auto_merge_fills_empty_fields(tmp_db):
    """Merge action fills NULL fields via COALESCE (default merge behavior)."""
    conn = _setup_db(tmp_db)
    try:
        _co_id, contact_id = _insert_contact_at_company(
            conn, "Acme Corp",
            email="alice@acme.com",
            linkedin_url=None,
            title=None,
            first_name="Alice",
            last_name="Smith",
        )
        row = _make_transformed_row(
            company="Acme Corp",
            email="alice@acme.com",
            linkedin="https://linkedin.com/in/alice",
            title="CEO",
        )
        decisions = {0: {"action": "merge", "existing_contact_id": contact_id}}
        with patch("src.services.deduplication.run_dedup"):
            execute_import(conn, [row], user_id=TEST_USER_ID, row_decisions=decisions)

        with get_cursor(conn) as cur:
            cur.execute("SELECT title, linkedin_url, email FROM contacts WHERE id = %s", (contact_id,))
            updated = cur.fetchone()
        # NULL fields should be filled
        assert updated["title"] == "CEO"
        assert updated["linkedin_url"] == "https://linkedin.com/in/alice"
        # Existing field preserved
        assert updated["email"] == "alice@acme.com"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 25. test_auto_merge_skips_conflicting_fields
# ---------------------------------------------------------------------------


def test_auto_merge_skips_conflicting_fields(tmp_db):
    """Default merge: fields with existing values NOT overwritten (COALESCE)."""
    conn = _setup_db(tmp_db)
    try:
        _co_id, contact_id = _insert_contact_at_company(
            conn, "Acme Corp",
            email="alice@acme.com",
            linkedin_url="https://linkedin.com/in/alice",
            title="CFO",
            first_name="Alice",
            last_name="Smith",
        )
        row = _make_transformed_row(
            company="Acme Corp",
            email="alice@acme.com",
            linkedin="https://linkedin.com/in/alice",
            title="CEO",
            first_name="Alicia",
            last_name="Smithson",
        )
        decisions = {0: {"action": "merge", "existing_contact_id": contact_id}}
        with patch("src.services.deduplication.run_dedup"):
            execute_import(conn, [row], user_id=TEST_USER_ID, row_decisions=decisions)

        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT title, first_name, last_name, linkedin_url FROM contacts WHERE id = %s",
                (contact_id,),
            )
            updated = cur.fetchone()
        # COALESCE preserves existing non-NULL values
        assert updated["title"] == "CFO"
        assert updated["first_name"] == "Alice"
        assert updated["last_name"] == "Smith"
        assert updated["linkedin_url"] == "https://linkedin.com/in/alice"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 26. test_per_field_merge_decisions
# ---------------------------------------------------------------------------


def test_per_field_merge_decisions(tmp_db):
    """field_overrides: email='import', title='crm' -> selective overwrite."""
    conn = _setup_db(tmp_db)
    try:
        _co_id, contact_id = _insert_contact_at_company(
            conn, "Acme Corp",
            email="alice-old@acme.com",
            linkedin_url="https://linkedin.com/in/alice",
            title="CFO",
            first_name="Alice",
            last_name="Smith",
        )
        row = _make_transformed_row(
            company="Acme Corp",
            email="alice-new@acme.com",
            linkedin="https://linkedin.com/in/alice",
            title="CEO",
        )
        decisions = {
            0: {
                "action": "merge",
                "existing_contact_id": contact_id,
                "field_overrides": {
                    "email": "import",
                    "title": "crm",
                },
            },
        }
        with patch("src.services.deduplication.run_dedup"):
            execute_import(conn, [row], user_id=TEST_USER_ID, row_decisions=decisions)

        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT email, email_normalized, title FROM contacts WHERE id = %s",
                (contact_id,),
            )
            updated = cur.fetchone()
        # email: override=import -> overwritten with import value
        assert updated["email"] == "alice-new@acme.com"
        assert updated["email_normalized"] == "alice-new@acme.com"
        # title: override=crm -> kept existing
        assert updated["title"] == "CFO"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 27. test_file_duplicate_both_shown
# ---------------------------------------------------------------------------


def test_file_duplicate_both_shown(tmp_db):
    """Same contact 2x in CSV -> second has within_file_duplicate flag + file_duplicate tier."""
    conn = _setup_db(tmp_db)
    try:
        row1 = _make_transformed_row(email="alice@acme.com", linkedin="https://linkedin.com/in/alice")
        row2 = _make_transformed_row(email="alice@acme.com", linkedin="https://linkedin.com/in/alice", title="VP")
        result = preview_import(conn, [row1, row2], user_id=TEST_USER_ID)
        rows = result["preview_rows"]
        assert len(rows) == 2
        # First row is NOT a file duplicate
        assert rows[0]["within_file_duplicate"] is False
        assert rows[0]["resolution_tier"] == "new"
        # Second row IS a file duplicate
        assert rows[1]["within_file_duplicate"] is True
        assert rows[1]["within_file_duplicate_of"] == 0
        assert rows[1]["resolution_tier"] == "file_duplicate"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 28. test_linkedin_collision_guard
# ---------------------------------------------------------------------------


def test_linkedin_collision_guard(tmp_db):
    """'new' contact with existing LinkedIn URL -> skipped (not crash) during execute."""
    conn = _setup_db(tmp_db)
    try:
        _insert_contact_at_company(
            conn, "Acme Corp",
            email="alice@acme.com",
            linkedin_url="https://linkedin.com/in/alice",
        )
        # Import row claims to be new but LinkedIn URL collides
        row = _make_transformed_row(
            company="Acme Corp",
            email="different@acme.com",
            linkedin="https://linkedin.com/in/alice",
            first_name="Bob",
        )
        decisions = {0: {"action": "import"}}
        with patch("src.services.deduplication.run_dedup"):
            result = execute_import(conn, [row], user_id=TEST_USER_ID, row_decisions=decisions)
        # Should skip gracefully, not crash
        assert result["duplicates_skipped"] == 1
        assert result["contacts_created"] == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 29. test_triage_summary_counts
# ---------------------------------------------------------------------------


def test_triage_summary_counts(tmp_db):
    """triage_summary counts match actual row classifications."""
    conn = _setup_db(tmp_db)
    try:
        # Set up existing contacts for various match types
        _insert_contact_at_company(
            conn, "Acme Corp",
            email="exact@acme.com",
            linkedin_url="https://linkedin.com/in/exact",
            title="CEO",
        )
        _insert_contact_at_company(
            conn, "Acme Corp",
            email="review@acme.com",
            linkedin_url=None,
            title="CFO",
        )

        rows = [
            # Row 0: exact match, same company -> auto_merge
            _make_transformed_row(
                company="Acme Corp", email="exact@acme.com",
                linkedin="https://linkedin.com/in/exact", title="CEO",
            ),
            # Row 1: email-only match -> review
            _make_transformed_row(
                company="Acme Corp", email="review@acme.com",
                linkedin="https://linkedin.com/in/review-new", title="CFO",
            ),
            # Row 2: brand new contact
            _make_transformed_row(
                company="New Corp", email="new@newcorp.com",
                linkedin="https://linkedin.com/in/new", first_name="Bob",
            ),
            # Row 3: file duplicate of row 2
            _make_transformed_row(
                company="New Corp", email="new@newcorp.com",
                linkedin="https://linkedin.com/in/new", first_name="Bob",
            ),
        ]
        result = preview_import(conn, rows, user_id=TEST_USER_ID)
        triage = result["triage_summary"]

        assert triage["total"] == 4
        assert triage["auto_mergeable"] == 1
        assert triage["needs_review"] == 1
        assert triage["new_contacts"] == 1
        assert triage["file_duplicates"] == 1
        # Verify counts add up
        assert (triage["auto_mergeable"] + triage["needs_review"]
                + triage["new_contacts"] + triage["file_duplicates"]) == triage["total"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 30. test_tier_linkedin_only_same_co
# ---------------------------------------------------------------------------


def test_tier_linkedin_only_same_co(tmp_db):
    """LinkedIn-only match + same company -> resolution_tier = 'auto_merge'."""
    conn = _setup_db(tmp_db)
    try:
        _insert_contact_at_company(
            conn, "Acme Corp",
            email=None,
            linkedin_url="https://linkedin.com/in/alice",
            title="CEO",
        )
        row = _make_transformed_row(
            company="Acme Corp",
            email=None,
            linkedin="https://linkedin.com/in/alice",
            title="CEO",
        )
        result = preview_import(conn, [row], user_id=TEST_USER_ID)
        r = result["preview_rows"][0]
        assert r["match_type"] == "linkedin_only"
        assert r["resolution_tier"] == "auto_merge"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 31. test_tier_both_different_contacts
# ---------------------------------------------------------------------------


def test_tier_both_different_contacts(tmp_db):
    """Email matches contact A, LinkedIn matches contact B -> resolution_tier = 'review'."""
    conn = _setup_db(tmp_db)
    try:
        _insert_contact_at_company(
            conn, "Acme Corp",
            email="alice@acme.com",
            linkedin_url=None,
            first_name="Alice",
            last_name="A",
        )
        _insert_contact_at_company(
            conn, "Acme Corp",
            email=None,
            linkedin_url="https://linkedin.com/in/alice",
            first_name="Alice",
            last_name="B",
        )
        row = _make_transformed_row(
            company="Acme Corp",
            email="alice@acme.com",
            linkedin="https://linkedin.com/in/alice",
            title="CEO",
        )
        result = preview_import(conn, [row], user_id=TEST_USER_ID)
        r = result["preview_rows"][0]
        assert r["match_type"] == "both_different_contacts"
        assert r["resolution_tier"] == "review"
        assert r["is_duplicate"] is False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 32. test_conflict_fields_derived
# ---------------------------------------------------------------------------


def test_conflict_fields_derived(tmp_db):
    """field_diffs with 'conflict' values -> conflict_fields array populated."""
    conn = _setup_db(tmp_db)
    try:
        _insert_contact_at_company(
            conn, "Acme Corp",
            email="alice@acme.com",
            linkedin_url="https://linkedin.com/in/alice",
            title="CFO",
            first_name="Alice",
            last_name="Old",
        )
        row = _make_transformed_row(
            company="Acme Corp",
            email="alice@acme.com",
            linkedin="https://linkedin.com/in/alice",
            title="CEO",
            first_name="Alice",
            last_name="New",
        )
        result = preview_import(conn, [row], user_id=TEST_USER_ID)
        r = result["preview_rows"][0]
        assert r["field_diffs"]["title"] == "conflict"
        assert r["field_diffs"]["last_name"] == "conflict"
        assert r["field_diffs"]["email"] == "same"
        assert r["field_diffs"]["first_name"] == "same"
        # conflict_fields should contain exactly the conflicting fields
        assert "title" in r["conflict_fields"]
        assert "last_name" in r["conflict_fields"]
        assert "email" not in r["conflict_fields"]
        assert "first_name" not in r["conflict_fields"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 33. test_auto_merge_enrolls_in_campaign
# ---------------------------------------------------------------------------


def test_auto_merge_enrolls_in_campaign(tmp_db):
    """Merged contacts enrolled when campaign_id is set."""
    conn = _setup_db(tmp_db)
    try:
        _co_id, contact_id = _insert_contact_at_company(
            conn, "Acme Corp",
            email="alice@acme.com",
            linkedin_url=None,
            title=None,
        )
        with get_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO campaigns (name, user_id) VALUES ('MergeCampaign', %s) RETURNING id",
                (TEST_USER_ID,),
            )
            campaign_id = cur.fetchone()["id"]
        conn.commit()

        row = _make_transformed_row(
            company="Acme Corp",
            email="alice@acme.com",
            linkedin="https://linkedin.com/in/alice",
            title="CEO",
        )
        decisions = {0: {"action": "merge", "existing_contact_id": contact_id}}
        with patch("src.services.deduplication.run_dedup"):
            result = execute_import(
                conn, [row], user_id=TEST_USER_ID,
                row_decisions=decisions, campaign_id=campaign_id,
            )
        assert result["contacts_merged"] == 1
        assert result["contacts_enrolled"] >= 1

        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT * FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
                (contact_id, campaign_id),
            )
            enrollment = cur.fetchone()
        assert enrollment is not None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 34. test_company_relink_creates_new
# ---------------------------------------------------------------------------


def test_company_relink_creates_new(tmp_db):
    """Company change merge -> INSERT new company + UPDATE contact.company_id."""
    conn = _setup_db(tmp_db)
    try:
        _co_id_old, contact_id = _insert_contact_at_company(
            conn, "Old Ventures",
            email="alice@old.com",
            linkedin_url="https://linkedin.com/in/alice",
            title="VP",
        )
        row = _make_transformed_row(
            company="New Capital",
            email="alice@old.com",
            linkedin="https://linkedin.com/in/alice",
            title="VP",
        )
        decisions = {
            0: {
                "action": "merge",
                "existing_contact_id": contact_id,
                "field_overrides": {
                    "company_name": "import",
                },
            },
        }
        with patch("src.services.deduplication.run_dedup"):
            result = execute_import(conn, [row], user_id=TEST_USER_ID, row_decisions=decisions)
        assert result["contacts_merged"] == 1

        # New Capital company should be created
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT id FROM companies WHERE name_normalized = %s AND user_id = %s",
                (normalize_company_name("New Capital"), TEST_USER_ID),
            )
            new_co = cur.fetchone()
        assert new_co is not None
        new_co_id = new_co["id"]
        assert new_co_id != _co_id_old

        # Contact should be re-linked to the new company
        with get_cursor(conn) as cur:
            cur.execute("SELECT company_id FROM contacts WHERE id = %s", (contact_id,))
            updated = cur.fetchone()
        assert updated["company_id"] == new_co_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 35. test_company_relink_existing_co
# ---------------------------------------------------------------------------


def test_company_relink_existing_co(tmp_db):
    """Company change where new company already exists -> SELECT id, re-link."""
    conn = _setup_db(tmp_db)
    try:
        _co_id_old, contact_id = _insert_contact_at_company(
            conn, "Old Ventures",
            email="alice@old.com",
            linkedin_url="https://linkedin.com/in/alice",
            title="VP",
        )
        # Pre-create the target company
        _co_id_target, _unused = _insert_contact_at_company(
            conn, "New Capital",
            email="bob@new.com",
            linkedin_url="https://linkedin.com/in/bob",
            first_name="Bob",
            last_name="Jones",
        )

        row = _make_transformed_row(
            company="New Capital",
            email="alice@old.com",
            linkedin="https://linkedin.com/in/alice",
            title="VP",
        )
        decisions = {
            0: {
                "action": "merge",
                "existing_contact_id": contact_id,
                "field_overrides": {
                    "company_name": "import",
                },
            },
        }
        with patch("src.services.deduplication.run_dedup"):
            result = execute_import(conn, [row], user_id=TEST_USER_ID, row_decisions=decisions)
        assert result["contacts_merged"] == 1
        # No new company created (it already existed)
        assert result["companies_created"] == 0

        # Contact re-linked to existing New Capital company
        with get_cursor(conn) as cur:
            cur.execute("SELECT company_id FROM contacts WHERE id = %s", (contact_id,))
            updated = cur.fetchone()
        assert updated["company_id"] == _co_id_target
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 36. test_normalize_company_suffixes
# ---------------------------------------------------------------------------


def test_normalize_company_suffixes():
    """normalize_company_name strips suffixes and normalizes '&' to 'and'."""
    # "BlackRock Inc" -> "blackrock"
    assert normalize_company_name("BlackRock Inc") == "blackrock"
    # "100 & 100 Capital" -> "100 and 100" (Capital stripped, & -> and)
    assert normalize_company_name("100 & 100 Capital") == "100 and 100"
    # Other suffix variants
    assert normalize_company_name("Acme LLC") == "acme"
    assert normalize_company_name("Foo Partners") == "foo"
    assert normalize_company_name("Bar Ltd.") == "bar"
    assert normalize_company_name("  Some  Fund  ") == "some"
    # Preserves meaningful parts
    assert normalize_company_name("Two Sigma Investments") == "two sigma"


# ---------------------------------------------------------------------------
# 37. test_file_duplicate_triple
# ---------------------------------------------------------------------------


def test_file_duplicate_triple(tmp_db):
    """Same contact 3x in CSV -> 2nd and 3rd flagged as within_file_duplicate."""
    conn = _setup_db(tmp_db)
    try:
        row1 = _make_transformed_row(email="alice@acme.com", linkedin="https://linkedin.com/in/alice")
        row2 = _make_transformed_row(email="alice@acme.com", linkedin="https://linkedin.com/in/alice", title="VP")
        row3 = _make_transformed_row(email="alice@acme.com", linkedin="https://linkedin.com/in/alice", title="CTO")
        result = preview_import(conn, [row1, row2, row3], user_id=TEST_USER_ID)
        rows = result["preview_rows"]
        assert len(rows) == 3
        # First row: not a file duplicate
        assert rows[0]["within_file_duplicate"] is False
        assert rows[0]["resolution_tier"] == "new"
        # Second row: file duplicate of row 0
        assert rows[1]["within_file_duplicate"] is True
        assert rows[1]["within_file_duplicate_of"] == 0
        assert rows[1]["resolution_tier"] == "file_duplicate"
        # Third row: file duplicate of row 0
        assert rows[2]["within_file_duplicate"] is True
        assert rows[2]["within_file_duplicate_of"] == 0
        assert rows[2]["resolution_tier"] == "file_duplicate"
        # triage_summary should count 2 file duplicates
        triage = result["triage_summary"]
        assert triage["file_duplicates"] == 2
        assert triage["new_contacts"] == 1
    finally:
        conn.close()
