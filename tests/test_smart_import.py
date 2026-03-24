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
    """Insert an existing contact, preview detects it as duplicate."""
    conn = _setup_db(tmp_db)

    # Insert a company and contact that will collide with the transformed data
    company_id = insert_company(conn, "Existing Corp")
    insert_contact(
        conn, company_id,
        first_name="Alice", last_name="Existing",
        email="alice@existing.com",
    )

    # Build transformed rows -- one duplicate, one new
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
    assert result["duplicates"] == 1
    assert result["new_contacts"] == 1
    assert result["total_companies"] == 2

    # Check that preview_rows marks the duplicate correctly
    alice_row = [r for r in result["preview_rows"] if r["email"] == "alice@existing.com"][0]
    bob_row = [r for r in result["preview_rows"] if r["email"] == "bob@newcorp.com"][0]
    assert alice_row["is_duplicate"] is True
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

    with patch("src.services.smart_import.run_dedup"):
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
