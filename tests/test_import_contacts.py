import os
from pathlib import Path

from src.models.database import get_connection, run_migrations
from src.commands.import_contacts import import_fund_csv


FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_CSV = str(FIXTURES_DIR / "sample_fund_list.csv")


def _setup_db(tmp_db):
    """Helper: create connection, run migrations, return conn."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    return conn


def test_import_creates_companies(tmp_db):
    """Importing the sample CSV should create exactly 3 companies."""
    conn = _setup_db(tmp_db)
    stats = import_fund_csv(conn, SAMPLE_CSV)
    assert stats["companies_created"] == 3
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS cnt FROM companies")
    assert cursor.fetchone()["cnt"] == 3
    conn.close()


def test_import_creates_contacts(tmp_db):
    """Aaro has 4 contacts, 10T has at least 3 with LinkedIn, Alphachain has 1."""
    conn = _setup_db(tmp_db)
    import_fund_csv(conn, SAMPLE_CSV)

    cursor = conn.cursor()

    # Aaro Capital: 4 contacts (all have names + emails + LinkedIn)
    cursor.execute(
        "SELECT id FROM companies WHERE name = %s", ("Aaro Capital",)
    )
    aaro = cursor.fetchone()
    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM contacts WHERE company_id = %s", (aaro["id"],)
    )
    aaro_contacts = cursor.fetchone()
    assert aaro_contacts["cnt"] == 4

    # 10T Fund: Dan Tapiero (primary, has LinkedIn but no email),
    # Michael Dubilier (contact 2, no LinkedIn and no email -- but has name so should be created),
    # Stan Miroshnik (contact 3, has LinkedIn + email),
    # Polina Bermisheva (contact 4, has LinkedIn but no email)
    cursor.execute(
        "SELECT id FROM companies WHERE name = %s", ("10T Fund",)
    )
    ten_t = cursor.fetchone()
    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM contacts WHERE company_id = %s", (ten_t["id"],)
    )
    ten_t_contacts = cursor.fetchone()
    # Dan has name+LinkedIn, Michael has name only, Stan has all 3, Polina has name+LinkedIn
    # All 4 should be created since they all have names
    assert ten_t_contacts["cnt"] == 4

    # Alphachain Capital: only 1 contact (primary), contacts 2-4 are empty
    cursor.execute(
        "SELECT id FROM companies WHERE name = %s", ("Alphachain Capital",)
    )
    alpha = cursor.fetchone()
    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM contacts WHERE company_id = %s", (alpha["id"],)
    )
    alpha_contacts = cursor.fetchone()
    assert alpha_contacts["cnt"] == 1

    cursor.execute("SELECT COUNT(*) AS cnt FROM contacts")
    total = cursor.fetchone()
    assert total["cnt"] == 9  # 4 + 4 + 1

    conn.close()


def test_import_parses_aum(tmp_db):
    """AUM values should be parsed: Aaro=$15.0, 10T=$1219.5."""
    conn = _setup_db(tmp_db)
    import_fund_csv(conn, SAMPLE_CSV)

    cursor = conn.cursor()

    cursor.execute(
        "SELECT aum_millions FROM companies WHERE name = %s", ("Aaro Capital",)
    )
    aaro_aum = cursor.fetchone()
    assert aaro_aum["aum_millions"] == 15.0

    cursor.execute(
        "SELECT aum_millions FROM companies WHERE name = %s", ("10T Fund",)
    )
    ten_t_aum = cursor.fetchone()
    assert ten_t_aum["aum_millions"] == 1219.5

    # Alphachain has whitespace-only AUM => None
    cursor.execute(
        "SELECT aum_millions FROM companies WHERE name = %s", ("Alphachain Capital",)
    )
    alpha_aum = cursor.fetchone()
    assert alpha_aum["aum_millions"] is None

    conn.close()


def test_import_detects_gdpr_country(tmp_db):
    """UK companies should have is_gdpr=1, US companies is_gdpr=0."""
    conn = _setup_db(tmp_db)
    import_fund_csv(conn, SAMPLE_CSV)

    cursor = conn.cursor()

    # United Kingdom -> GDPR
    cursor.execute(
        "SELECT is_gdpr FROM companies WHERE name = %s", ("Aaro Capital",)
    )
    aaro = cursor.fetchone()
    assert aaro["is_gdpr"] is True

    # United States -> not GDPR
    cursor.execute(
        "SELECT is_gdpr FROM companies WHERE name = %s", ("10T Fund",)
    )
    ten_t = cursor.fetchone()
    assert ten_t["is_gdpr"] is False

    # Alphachain is also UK
    cursor.execute(
        "SELECT is_gdpr FROM companies WHERE name = %s", ("Alphachain Capital",)
    )
    alpha = cursor.fetchone()
    assert alpha["is_gdpr"] is True

    conn.close()


def test_import_normalizes_emails(tmp_db):
    """Emails should be lowercased and stripped."""
    conn = _setup_db(tmp_db)
    import_fund_csv(conn, SAMPLE_CSV)

    cursor = conn.cursor()

    cursor.execute(
        "SELECT email_normalized FROM contacts WHERE full_name = %s",
        ("Peter Habermacher",),
    )
    contact = cursor.fetchone()
    assert contact["email_normalized"] == "peter.habermacher@aaro.capital"

    # Dan Tapiero has no email => email_normalized should be None
    cursor.execute(
        "SELECT email_normalized FROM contacts WHERE full_name = %s",
        ("Dan Tapiero",),
    )
    dan = cursor.fetchone()
    assert dan["email_normalized"] is None

    conn.close()


def test_import_sets_priority_ranks(tmp_db):
    """Primary contact gets rank 1, contact 2 gets rank 2, etc."""
    conn = _setup_db(tmp_db)
    import_fund_csv(conn, SAMPLE_CSV)

    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM companies WHERE name = %s", ("Aaro Capital",)
    )
    aaro_id = cursor.fetchone()["id"]

    cursor.execute(
        "SELECT full_name, priority_rank FROM contacts "
        "WHERE company_id = %s ORDER BY priority_rank",
        (aaro_id,),
    )
    contacts = cursor.fetchall()

    assert contacts[0]["full_name"] == "Peter Habermacher"
    assert contacts[0]["priority_rank"] == 1
    assert contacts[1]["full_name"] == "Ankush Jain"
    assert contacts[1]["priority_rank"] == 2
    assert contacts[2]["full_name"] == "Sebastien Jardon"
    assert contacts[2]["priority_rank"] == 3
    assert contacts[3]["full_name"] == "Johannes Gugl"
    assert contacts[3]["priority_rank"] == 4

    conn.close()


def test_contacts_inherit_gdpr_from_company(tmp_db):
    """Contacts of UK companies should have is_gdpr=1."""
    conn = _setup_db(tmp_db)
    import_fund_csv(conn, SAMPLE_CSV)

    cursor = conn.cursor()

    # All Aaro contacts (UK) should be GDPR
    cursor.execute(
        "SELECT id FROM companies WHERE name = %s", ("Aaro Capital",)
    )
    aaro_id = cursor.fetchone()["id"]
    cursor.execute(
        "SELECT is_gdpr FROM contacts WHERE company_id = %s", (aaro_id,)
    )
    aaro_contacts = cursor.fetchall()
    for c in aaro_contacts:
        assert c["is_gdpr"] is True

    # All 10T contacts (US) should not be GDPR
    cursor.execute(
        "SELECT id FROM companies WHERE name = %s", ("10T Fund",)
    )
    ten_t_id = cursor.fetchone()["id"]
    cursor.execute(
        "SELECT is_gdpr FROM contacts WHERE company_id = %s", (ten_t_id,)
    )
    ten_t_contacts = cursor.fetchall()
    for c in ten_t_contacts:
        assert c["is_gdpr"] is False

    conn.close()
