# Outreach Campaign System - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python CLI + SQLite system that manages multi-channel outreach (LinkedIn → email) to ~3,000 crypto fund allocators, with deduplication, email verification, GDPR compliance, A/B testing on reply rates, and a newsletter pipeline.

**Architecture:** Pure CLI (Typer) + SQLite (WAL mode). No web server. Gmail SMTP on secondary domain for sending. Expandi CSV integration for LinkedIn automation. Weekly operator check-ins, no automated sends.

**Tech Stack:** Python 3.12+, Typer, SQLite, Jinja2, thefuzz, httpx (for email verification API), smtplib, Rich (terminal UI)

---

## Phase 1: Foundation — Data In, Deduped, Queryable

### Task 1: Initialize Repo + Project Structure

**Files:**
- Create: `pyproject.toml`
- Create: `Makefile`
- Create: `config.yaml.example`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `src/__init__.py`
- Create: `src/cli.py`
- Create: `src/commands/__init__.py`
- Create: `src/models/__init__.py`
- Create: `src/services/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: directories: `data/imports/`, `data/exports/`, `data/newsletters/`, `migrations/`, `src/templates/email/`, `src/templates/linkedin/`, `docs/`

**Step 1: Create directory structure**

```bash
cd /Users/helios-mammut/Documents/Claude-Projects/Outreach-campaign
mkdir -p src/commands src/models src/services src/templates/email src/templates/linkedin
mkdir -p tests data/imports data/exports data/newsletters migrations docs/plans
```

**Step 2: Create pyproject.toml**

```toml
[project]
name = "outreach-campaign"
version = "0.1.0"
description = "Multi-channel outreach campaign manager for crypto fund allocators"
requires-python = ">=3.12"
dependencies = [
    "typer[all]>=0.12",
    "jinja2>=3.1",
    "thefuzz[speedup]>=0.22",
    "python-levenshtein>=0.25",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "markdown2>=2.4",
    "premailer>=3.10",
    "httpx>=0.27",
    "rich>=13.0",
    "tabulate>=0.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
]

[project.scripts]
outreach = "src.cli:app"

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

**Step 3: Create .gitignore**

```
.env
*.db
*.db-journal
*.db-wal
*.db-shm
__pycache__/
*.pyc
.pytest_cache/
.venv/
dist/
*.egg-info/
data/exports/*.csv
.firecrawl/
```

**Step 4: Create config.yaml.example**

```yaml
calendly_url: "https://calendly.com/helmutm"
physical_address: "Your Company, Street, City, Country"

smtp:
  host: "smtp.gmail.com"
  port: 587
  username: "outreach@your-secondary-domain.com"
  # password in .env as SMTP_PASSWORD

email_verification:
  provider: "zerobounce"  # or "hunter"
  # api_key in .env as EMAIL_VERIFY_API_KEY

gdpr_countries:
  - Austria
  - Belgium
  - Bulgaria
  - Croatia
  - Cyprus
  - Czech Republic
  - Czechia
  - Denmark
  - Estonia
  - Finland
  - France
  - Germany
  - Greece
  - Hungary
  - Iceland
  - Ireland
  - Italy
  - Latvia
  - Liechtenstein
  - Lithuania
  - Luxembourg
  - Malta
  - Monaco
  - Netherlands
  - Norway
  - Poland
  - Portugal
  - Romania
  - Slovakia
  - Slovenia
  - Spain
  - Sweden
  - Switzerland
  - United Kingdom
```

**Step 5: Create .env.example**

```
SMTP_PASSWORD=your-app-password-here
EMAIL_VERIFY_API_KEY=your-zerobounce-or-hunter-key
DATABASE_PATH=outreach.db
```

**Step 6: Create src/cli.py (skeleton)**

```python
import typer

app = typer.Typer(
    name="outreach",
    help="Multi-channel outreach campaign manager",
)


@app.callback()
def main() -> None:
    """Outreach Campaign CLI - manage contacts, campaigns, and sends."""


if __name__ == "__main__":
    app()
```

**Step 7: Create __init__.py files and conftest.py**

All `__init__.py` files are empty.

`tests/conftest.py`:
```python
import os
import sqlite3
import pytest

@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    yield db_path
    conn.close()
```

**Step 8: Init git repo**

```bash
git init
git add -A
git commit -m "chore: initialize project structure"
```

---

### Task 2: SQLite Schema + Database Module

**Files:**
- Create: `src/models/database.py`
- Create: `migrations/001_initial_schema.sql`
- Create: `tests/test_database.py`

**Step 1: Write the failing test**

`tests/test_database.py`:
```python
from src.models.database import get_connection, run_migrations, get_table_names


def test_run_migrations_creates_tables(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    tables = get_table_names(conn)
    assert "companies" in tables
    assert "contacts" in tables
    assert "campaigns" in tables
    assert "sequence_steps" in tables
    assert "templates" in tables
    assert "contact_campaign_status" in tables
    assert "events" in tables
    assert "dedup_log" in tables
    conn.close()


def test_wal_mode_enabled(tmp_db):
    conn = get_connection(tmp_db)
    result = conn.execute("PRAGMA journal_mode").fetchone()
    assert result[0] == "wal"
    conn.close()


def test_foreign_keys_enabled(tmp_db):
    conn = get_connection(tmp_db)
    result = conn.execute("PRAGMA foreign_keys").fetchone()
    assert result[0] == 1
    conn.close()


def test_migrations_are_idempotent(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    run_migrations(conn)  # should not fail
    tables = get_table_names(conn)
    assert "companies" in tables
    conn.close()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_database.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.models.database'`

**Step 3: Create the migration SQL**

`migrations/001_initial_schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    address TEXT,
    city TEXT,
    country TEXT,
    aum_millions REAL,
    firm_type TEXT,
    website TEXT,
    linkedin_url TEXT,
    is_gdpr INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id),
    first_name TEXT,
    last_name TEXT,
    full_name TEXT,
    email TEXT,
    email_normalized TEXT,
    email_status TEXT DEFAULT 'unverified',
    linkedin_url TEXT,
    linkedin_url_normalized TEXT,
    title TEXT,
    priority_rank INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'csv',
    is_gdpr INTEGER NOT NULL DEFAULT 0,
    unsubscribed INTEGER NOT NULL DEFAULT 0,
    unsubscribed_at TEXT,
    newsletter_status TEXT NOT NULL DEFAULT 'none',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sequence_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    step_order INTEGER NOT NULL,
    channel TEXT NOT NULL,
    template_id INTEGER REFERENCES templates(id),
    delay_days INTEGER NOT NULL DEFAULT 0,
    gdpr_only INTEGER NOT NULL DEFAULT 0,
    non_gdpr_only INTEGER NOT NULL DEFAULT 0,
    UNIQUE(campaign_id, step_order)
);

CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    channel TEXT NOT NULL,
    subject TEXT,
    body_template TEXT NOT NULL,
    variant_group TEXT,
    variant_label TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contact_campaign_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    current_step INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    assigned_variant TEXT,
    next_action_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(contact_id, campaign_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    event_type TEXT NOT NULL,
    template_id INTEGER REFERENCES templates(id),
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dedup_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kept_contact_id INTEGER,
    merged_contact_id INTEGER,
    match_type TEXT NOT NULL,
    match_score REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_email_norm ON contacts(email_normalized);
CREATE INDEX IF NOT EXISTS idx_contacts_linkedin_norm ON contacts(linkedin_url_normalized);
CREATE INDEX IF NOT EXISTS idx_contacts_email_status ON contacts(email_status);
CREATE INDEX IF NOT EXISTS idx_ccs_status ON contact_campaign_status(status);
CREATE INDEX IF NOT EXISTS idx_ccs_next_action ON contact_campaign_status(next_action_date);
CREATE INDEX IF NOT EXISTS idx_events_contact ON events(contact_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_companies_name_norm ON companies(name_normalized);
CREATE INDEX IF NOT EXISTS idx_companies_country ON companies(country);
```

**Step 4: Write the database module**

`src/models/database.py`:
```python
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def run_migrations(conn: sqlite3.Connection) -> None:
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for migration_file in migration_files:
        sql = migration_file.read_text()
        conn.executescript(sql)
    conn.commit()


def get_table_names(conn: sqlite3.Connection) -> list[str]:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return [row[0] for row in cursor.fetchall()]
```

**Step 5: Run tests**

```bash
pytest tests/test_database.py -v
```
Expected: All 4 tests PASS

**Step 6: Commit**

```bash
git add src/models/database.py migrations/001_initial_schema.sql tests/test_database.py
git commit -m "feat: add SQLite schema and database module with WAL mode"
```

---

### Task 3: CSV Import Command — Parse the Fund List

**Files:**
- Create: `src/commands/import_contacts.py`
- Create: `tests/test_import_contacts.py`
- Create: `tests/fixtures/sample_fund_list.csv` (small test fixture)

**Context:** The CSV has these relevant columns (from the actual file headers):
- `Firm Name`, `Address`, `City`, `Country`, `URL`, `Company LinkedIn`
- `AUM (Millions)` (formatted like `"$1,219.50"` or `$110.00` or empty)
- `Firm Type`, `Firm Type 2`, `Firm Type 3`
- `Primary Contact`, `Position`, `Primary LinkedIn`, `Primary Email`, `Contact Title (Mr/Ms.)`
- `Contact 2` through `Contact 4` with same sub-fields (name, title, linkedin, email)
- `Main email` (company-level email, different from individual contact emails)

**Step 1: Create test fixture**

`tests/fixtures/sample_fund_list.csv`:
```csv
Firm Name,Address,Address 2,City,State/Province,Zip,Country,Map,Code,Phone,Fax,URL,Company LinkedIn,Crunchbase,Contact Title (Mr/Ms.),Primary Contact,Position,Primary LinkedIn,Primary Email,Contact 2,Contact 2 Title,Contact 2 LinkedIn,Contact 2 Email,Contact 3,Contact 3 Title,Contact 3 LinkedIn,Contact 3 Email,Contact 4,Contact 4 Title,Contact 4 LinkedIn,Contact 4 Email, AUM (Millions) ,12mo AUM Change,24mo AUM Change,Professional Staff,Founded/Launch Year,Main email,Careers Email,Hiring?,Firm Type,Firm Type 2,Firm Type 3,Firm Type 4,Firm Type 5,SEC Registered (1940 Act),# of Clients,Exclusively Crypto?,# of Investments,Investments 1,Investments 2,Investments 3,Investments 4,Investments 5,Investments 6,Investments 7,Investments 8,Investments 9,Investments 10,Investments 11,Investments 12,Investments 13,Investments 14,Investments 15,Investments 16,Investments 17,Investments 18,Investments 19,Investments 20,Form of Incorporation
Aaro Capital,122 Leadenhall Street,,London,,EC3V 4AB,United Kingdom,,,,,,https://www.linkedin.com/company/aaro-capital/about/,,Mr.,Peter Habermacher,CEO and Co-Founder,https://www.linkedin.com/in/peter-habermacher/,peter.habermacher@aaro.capital,Ankush Jain,Co-Founder and Chief Investment Officer,https://www.linkedin.com/in/ankushjain93/,ankush.jain@aaro.capital,Sebastien Jardon,Co-Founder,https://www.linkedin.com/in/jardon/,sebastien.jardon@aaro.capital,Johannes Gugl,Partner,https://www.linkedin.com/in/jgugl/,johannes.gugl@aaro.capital,$15.00,,,43,,info@aaro.capital,,,Hedge Fund,Crypto,Fund of Funds,,,No,,,,,,,,,,,,,,,,,,,,,,,
10T Fund,"15 E Putnam Ave, Suite 505",,Greenwich,CT,6830,United States,,,,,,https://www.linkedin.com/company/10tholdings/,,Mr.,Dan Tapiero,Founder and CEO,https://www.linkedin.com/in/dan-tapiero-22b41b191/,,Michael Dubilier,Partner,,,Stan Miroshnik,Partner,https://www.linkedin.com/in/stanmiroshnik/,stan.miroshnik@10tfund.com,Polina Bermisheva,Principal,https://www.linkedin.com/in/polinabermisheva/,,"$1,219.50",267%,235%,13,2019,info@10tfund.com,,,Venture Capital,Crypto,Private Equity,,,Yes,,,,,,,,,,,,,,,,,,,,,,,Limited Liability Company
Alphachain Capital,"43 Berkeley Square, Mayfair",,London,,W1J 5AP,United Kingdom,,,,,,https://www.linkedin.com/company/alphachain-capital/,,Mr.,Adam Haeems,CEO,https://www.linkedin.com/in/adam-haeems-8a457813/,,,,,,,,,,,,,  ,,,160,2017,info@alphachain.co.uk,,,Hedge Fund,Crypto,Quantitative,,,No,,,,,,,,,,,,,,,,,,,,,,,
```

**Step 2: Write the failing tests**

`tests/test_import_contacts.py`:
```python
import sqlite3
from pathlib import Path
from src.models.database import get_connection, run_migrations
from src.commands.import_contacts import import_fund_csv


FIXTURES = Path(__file__).parent / "fixtures"


def test_import_creates_companies(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    stats = import_fund_csv(conn, str(FIXTURES / "sample_fund_list.csv"))
    companies = conn.execute("SELECT * FROM companies").fetchall()
    assert len(companies) == 3
    assert stats["companies_created"] == 3
    conn.close()


def test_import_creates_contacts(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    import_fund_csv(conn, str(FIXTURES / "sample_fund_list.csv"))
    contacts = conn.execute("SELECT * FROM contacts").fetchall()
    # Aaro: 4 contacts, 10T: 3 (primary has no email, but has linkedin), Alphachain: 1
    assert len(contacts) >= 7
    conn.close()


def test_import_parses_aum(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    import_fund_csv(conn, str(FIXTURES / "sample_fund_list.csv"))
    aaro = conn.execute(
        "SELECT aum_millions FROM companies WHERE name = 'Aaro Capital'"
    ).fetchone()
    assert aaro["aum_millions"] == 15.0
    tenT = conn.execute(
        "SELECT aum_millions FROM companies WHERE name = '10T Fund'"
    ).fetchone()
    assert tenT["aum_millions"] == 1219.5
    conn.close()


def test_import_detects_gdpr_country(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    import_fund_csv(conn, str(FIXTURES / "sample_fund_list.csv"))
    uk_company = conn.execute(
        "SELECT is_gdpr FROM companies WHERE name = 'Aaro Capital'"
    ).fetchone()
    assert uk_company["is_gdpr"] == 1
    us_company = conn.execute(
        "SELECT is_gdpr FROM companies WHERE name = '10T Fund'"
    ).fetchone()
    assert us_company["is_gdpr"] == 0
    conn.close()


def test_import_normalizes_emails(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    import_fund_csv(conn, str(FIXTURES / "sample_fund_list.csv"))
    contact = conn.execute(
        "SELECT email_normalized FROM contacts WHERE email = 'peter.habermacher@aaro.capital'"
    ).fetchone()
    assert contact["email_normalized"] == "peter.habermacher@aaro.capital"
    conn.close()


def test_import_sets_priority_ranks(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    import_fund_csv(conn, str(FIXTURES / "sample_fund_list.csv"))
    aaro_id = conn.execute(
        "SELECT id FROM companies WHERE name = 'Aaro Capital'"
    ).fetchone()["id"]
    contacts = conn.execute(
        "SELECT priority_rank, full_name FROM contacts WHERE company_id = ? ORDER BY priority_rank",
        (aaro_id,),
    ).fetchall()
    assert contacts[0]["priority_rank"] == 1
    assert contacts[0]["full_name"] == "Peter Habermacher"
    assert contacts[1]["priority_rank"] == 2
    conn.close()


def test_contacts_inherit_gdpr_from_company(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    import_fund_csv(conn, str(FIXTURES / "sample_fund_list.csv"))
    contact = conn.execute(
        "SELECT is_gdpr FROM contacts WHERE email = 'peter.habermacher@aaro.capital'"
    ).fetchone()
    assert contact["is_gdpr"] == 1
    conn.close()
```

**Step 3: Run tests to verify failure**

```bash
pytest tests/test_import_contacts.py -v
```
Expected: FAIL — `ModuleNotFoundError`

**Step 4: Write the import command**

`src/commands/import_contacts.py`:
```python
import csv
import re
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"
CONFIG_EXAMPLE_PATH = Path(__file__).parent.parent.parent / "config.yaml.example"


def _load_gdpr_countries() -> set[str]:
    config_path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE_PATH
    if not config_path.exists():
        return set()
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return {c.lower() for c in config.get("gdpr_countries", [])}


def _parse_aum(raw: str) -> float | None:
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip().replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        return None
    return normalized


def _normalize_linkedin(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    url = url.split("?")[0].rstrip("/")
    return url.lower()


def _normalize_company_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if len(parts) == 0:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], " ".join(parts[1:]))


def import_fund_csv(conn, csv_path: str) -> dict:
    gdpr_countries = _load_gdpr_countries()
    stats = {"companies_created": 0, "contacts_created": 0, "rows_processed": 0}

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stats["rows_processed"] += 1
            firm_name = row.get("Firm Name", "").strip()
            if not firm_name:
                continue

            country = row.get("Country", "").strip()
            is_gdpr = 1 if country.lower() in gdpr_countries else 0
            aum = _parse_aum(row.get(" AUM (Millions) ", ""))
            firm_types = [
                row.get(f"Firm Type{'' if i == 0 else f' {i+1}'}", "").strip()
                for i in range(5)
            ]
            firm_type = ", ".join(t for t in firm_types if t)

            cursor = conn.execute(
                """INSERT INTO companies
                   (name, name_normalized, address, city, country, aum_millions,
                    firm_type, website, linkedin_url, is_gdpr)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    firm_name,
                    _normalize_company_name(firm_name),
                    row.get("Address", "").strip(),
                    row.get("City", "").strip(),
                    country,
                    aum,
                    firm_type,
                    row.get("URL", "").strip(),
                    row.get("Company LinkedIn", "").strip(),
                    is_gdpr,
                ),
            )
            company_id = cursor.lastrowid
            stats["companies_created"] += 1

            contact_slots = [
                {
                    "name": row.get("Primary Contact", "").strip(),
                    "title": row.get("Position", "").strip(),
                    "linkedin": row.get("Primary LinkedIn", "").strip(),
                    "email": row.get("Primary Email", "").strip(),
                    "rank": 1,
                },
                {
                    "name": row.get("Contact 2", "").strip(),
                    "title": row.get("Contact 2 Title", "").strip(),
                    "linkedin": row.get("Contact 2 LinkedIn", "").strip(),
                    "email": row.get("Contact 2 Email", "").strip(),
                    "rank": 2,
                },
                {
                    "name": row.get("Contact 3", "").strip(),
                    "title": row.get("Contact 3 Title", "").strip(),
                    "linkedin": row.get("Contact 3 LinkedIn", "").strip(),
                    "email": row.get("Contact 3 Email", "").strip(),
                    "rank": 3,
                },
                {
                    "name": row.get("Contact 4", "").strip(),
                    "title": row.get("Contact 4 Title", "").strip(),
                    "linkedin": row.get("Contact 4 LinkedIn", "").strip(),
                    "email": row.get("Contact 4 Email", "").strip(),
                    "rank": 4,
                },
            ]

            for slot in contact_slots:
                if not slot["name"] and not slot["email"] and not slot["linkedin"]:
                    continue
                first, last = _split_name(slot["name"])
                email_norm = _normalize_email(slot["email"])
                li_norm = _normalize_linkedin(slot["linkedin"])

                conn.execute(
                    """INSERT INTO contacts
                       (company_id, first_name, last_name, full_name, email,
                        email_normalized, linkedin_url, linkedin_url_normalized,
                        title, priority_rank, source, is_gdpr)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        company_id,
                        first,
                        last,
                        slot["name"],
                        slot["email"] or None,
                        email_norm,
                        slot["linkedin"] or None,
                        li_norm,
                        slot["title"] or None,
                        slot["rank"],
                        "csv_fund_list",
                        is_gdpr,
                    ),
                )
                stats["contacts_created"] += 1

    conn.commit()
    return stats
```

**Step 5: Run tests**

```bash
pytest tests/test_import_contacts.py -v
```
Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/commands/import_contacts.py tests/test_import_contacts.py tests/fixtures/
git commit -m "feat: add CSV fund list import with GDPR detection and contact parsing"
```

---

### Task 4: Pasted Email Import — Parse Raw Email Lists

**Files:**
- Create: `src/commands/import_emails.py`
- Create: `tests/test_import_emails.py`
- Create: `tests/fixtures/sample_pasted_emails.txt`

**Context:** The pasted emails come in mixed formats:
- Bare: `adam@bbscapital.com`
- Quoted: `"jason@velvetfs.com" <jason@velvetfs.com>`
- Named: `Bo Zhou <bo@firinnecapital.com>`
- Named with comma: `"Josh J. Anderson" <josh@geometricholdings.net>`

We need to extract: email, name (if present), and company domain (for fuzzy-matching to existing companies).

**Step 1: Create test fixture**

`tests/fixtures/sample_pasted_emails.txt`:
```
adam@bbscapital.com,
Bo Zhou <bo@firinnecapital.com>,
"jason@velvetfs.com" <jason@velvetfs.com>,
"ghannochko@qwestfunds.com" <ghannochko@qwestfunds.com>,
Jeff Park <jeff@bitwiseinvestments.com>,
"Josh J. Anderson" <josh@geometricholdings.net>,
Charlie Morris <charlie@cmcc.vc>,
ops@coalesce.partners,
```

**Step 2: Write the failing tests**

`tests/test_import_emails.py`:
```python
from pathlib import Path
from src.models.database import get_connection, run_migrations
from src.commands.import_emails import parse_email_line, import_pasted_emails

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_bare_email():
    name, email = parse_email_line("adam@bbscapital.com,")
    assert email == "adam@bbscapital.com"
    assert name is None


def test_parse_named_email():
    name, email = parse_email_line("Bo Zhou <bo@firinnecapital.com>,")
    assert email == "bo@firinnecapital.com"
    assert name == "Bo Zhou"


def test_parse_quoted_email():
    name, email = parse_email_line('"jason@velvetfs.com" <jason@velvetfs.com>,')
    assert email == "jason@velvetfs.com"
    assert name is None


def test_parse_named_with_dots():
    name, email = parse_email_line('"Josh J. Anderson" <josh@geometricholdings.net>,')
    assert email == "josh@geometricholdings.net"
    assert name == "Josh J. Anderson"


def test_import_pasted_emails(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    stats = import_pasted_emails(conn, str(FIXTURES / "sample_pasted_emails.txt"))
    contacts = conn.execute("SELECT * FROM contacts").fetchall()
    assert stats["contacts_created"] >= 7
    assert len(contacts) >= 7
    conn.close()


def test_import_extracts_company_from_domain(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    import_pasted_emails(conn, str(FIXTURES / "sample_pasted_emails.txt"))
    bo = conn.execute(
        "SELECT c.name FROM contacts ct JOIN companies c ON ct.company_id = c.id WHERE ct.email_normalized = 'bo@firinnecapital.com'"
    ).fetchone()
    assert bo is not None
    assert "firinnecapital" in bo["name"].lower()
    conn.close()
```

**Step 3: Run tests to verify failure**

```bash
pytest tests/test_import_emails.py -v
```
Expected: FAIL

**Step 4: Write the implementation**

`src/commands/import_emails.py`:
```python
import re
from src.commands.import_contacts import _normalize_email, _normalize_company_name, _split_name


def _domain_to_company_name(domain: str) -> str:
    """Extract company name from email domain: 'firinnecapital.com' -> 'Firinnecapital'."""
    name = domain.split(".")[0]
    return name.capitalize()


def parse_email_line(line: str) -> tuple[str | None, str | None]:
    """Parse a line that may contain name + email in various formats."""
    line = line.strip().rstrip(",").strip()
    if not line:
        return None, None

    # Format: Name <email> or "Name" <email>
    angle_match = re.match(r'^"?([^"<]*?)"?\s*<([^>]+)>', line)
    if angle_match:
        name_part = angle_match.group(1).strip()
        email_part = angle_match.group(2).strip()
        # If name looks like an email, it's not a real name
        if "@" in name_part:
            name_part = None
        return name_part or None, email_part

    # Format: bare email
    email_match = re.match(r'^([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', line)
    if email_match:
        return None, email_match.group(1)

    return None, None


def import_pasted_emails(conn, file_path: str) -> dict:
    stats = {"contacts_created": 0, "lines_processed": 0, "lines_skipped": 0}

    with open(file_path) as f:
        content = f.read()

    lines = [l.strip() for l in content.replace("\n", ",").split(",") if l.strip()]

    for line in lines:
        stats["lines_processed"] += 1
        name, email = parse_email_line(line)
        if not email:
            stats["lines_skipped"] += 1
            continue

        email_norm = _normalize_email(email)
        if not email_norm:
            stats["lines_skipped"] += 1
            continue

        # Check if contact already exists
        existing = conn.execute(
            "SELECT id FROM contacts WHERE email_normalized = ?", (email_norm,)
        ).fetchone()
        if existing:
            stats["lines_skipped"] += 1
            continue

        # Extract company from domain
        domain = email_norm.split("@")[1]
        company_name = _domain_to_company_name(domain)
        company_name_norm = _normalize_company_name(company_name)

        # Find or create company
        existing_company = conn.execute(
            "SELECT id FROM companies WHERE name_normalized = ?", (company_name_norm,)
        ).fetchone()

        if existing_company:
            company_id = existing_company["id"]
        else:
            cursor = conn.execute(
                """INSERT INTO companies (name, name_normalized, country, is_gdpr)
                   VALUES (?, ?, '', 0)""",
                (company_name, company_name_norm),
            )
            company_id = cursor.lastrowid

        # Determine priority rank
        max_rank = conn.execute(
            "SELECT COALESCE(MAX(priority_rank), 0) FROM contacts WHERE company_id = ?",
            (company_id,),
        ).fetchone()[0]

        first, last = _split_name(name) if name else ("", "")

        conn.execute(
            """INSERT INTO contacts
               (company_id, first_name, last_name, full_name, email,
                email_normalized, title, priority_rank, source, is_gdpr)
               VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 'pasted_emails', 0)""",
            (company_id, first, last, name, email, email_norm, max_rank + 1),
        )
        stats["contacts_created"] += 1

    conn.commit()
    return stats
```

**Step 5: Run tests**

```bash
pytest tests/test_import_emails.py -v
```
Expected: All PASS

**Step 6: Commit**

```bash
git add src/commands/import_emails.py tests/test_import_emails.py tests/fixtures/sample_pasted_emails.txt
git commit -m "feat: add pasted email import with name/domain extraction"
```

---

### Task 5: Deduplication Pipeline

**Files:**
- Create: `src/services/deduplication.py`
- Create: `tests/test_deduplication.py`

**Step 1: Write the failing tests**

`tests/test_deduplication.py`:
```python
from src.models.database import get_connection, run_migrations
from src.services.deduplication import run_dedup


def _insert_company(conn, name, country="United States"):
    cursor = conn.execute(
        "INSERT INTO companies (name, name_normalized, country, is_gdpr) VALUES (?, ?, ?, 0)",
        (name, name.lower(), country),
    )
    return cursor.lastrowid


def _insert_contact(conn, company_id, email, linkedin=None, rank=1):
    email_norm = email.lower() if email else None
    li_norm = linkedin.lower().rstrip("/").split("?")[0] if linkedin else None
    conn.execute(
        """INSERT INTO contacts
           (company_id, full_name, email, email_normalized,
            linkedin_url, linkedin_url_normalized, priority_rank, source, is_gdpr)
           VALUES (?, 'Test', ?, ?, ?, ?, ?, 'test', 0)""",
        (company_id, email, email_norm, linkedin, li_norm, rank),
    )
    conn.commit()


def test_dedup_exact_email(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    c1 = _insert_company(conn, "Fund A")
    c2 = _insert_company(conn, "Fund B")
    _insert_contact(conn, c1, "john@fund.com")
    _insert_contact(conn, c2, "john@fund.com")
    stats = run_dedup(conn)
    remaining = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    assert remaining == 1
    assert stats["email_dupes"] == 1
    conn.close()


def test_dedup_exact_linkedin(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    c1 = _insert_company(conn, "Fund A")
    c2 = _insert_company(conn, "Fund B")
    _insert_contact(conn, c1, "a@fund.com", "https://www.linkedin.com/in/johnsmith/")
    _insert_contact(conn, c2, "b@other.com", "https://www.linkedin.com/in/johnsmith")
    stats = run_dedup(conn)
    remaining = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    assert remaining == 1
    assert stats["linkedin_dupes"] == 1
    conn.close()


def test_dedup_fuzzy_company_flagged(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    c1 = _insert_company(conn, "Falcon Capital")
    c2 = _insert_company(conn, "Falcon Capital Ltd")
    _insert_contact(conn, c1, "a@falcon.com")
    _insert_contact(conn, c2, "b@falcon.com")
    stats = run_dedup(conn)
    assert stats["fuzzy_flagged"] >= 1
    conn.close()


def test_dedup_logs_actions(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    c1 = _insert_company(conn, "Fund A")
    c2 = _insert_company(conn, "Fund B")
    _insert_contact(conn, c1, "john@fund.com")
    _insert_contact(conn, c2, "john@fund.com")
    run_dedup(conn)
    logs = conn.execute("SELECT * FROM dedup_log").fetchall()
    assert len(logs) == 1
    assert logs[0]["match_type"] == "exact_email"
    conn.close()
```

**Step 2: Run tests to verify failure**

```bash
pytest tests/test_deduplication.py -v
```

**Step 3: Write the implementation**

`src/services/deduplication.py`:
```python
import csv
from pathlib import Path
from thefuzz import fuzz


FUZZY_THRESHOLD = 85


def run_dedup(conn, export_dir: str | None = None) -> dict:
    stats = {"email_dupes": 0, "linkedin_dupes": 0, "fuzzy_flagged": 0}

    # Pass 1: Exact email duplicates
    dupes = conn.execute(
        """SELECT email_normalized, GROUP_CONCAT(id) as ids, COUNT(*) as cnt
           FROM contacts
           WHERE email_normalized IS NOT NULL AND email_normalized != ''
           GROUP BY email_normalized
           HAVING cnt > 1"""
    ).fetchall()

    for dupe in dupes:
        ids = [int(x) for x in dupe["ids"].split(",")]
        keep_id = ids[0]
        for remove_id in ids[1:]:
            conn.execute(
                "INSERT INTO dedup_log (kept_contact_id, merged_contact_id, match_type, match_score) VALUES (?, ?, 'exact_email', 1.0)",
                (keep_id, remove_id),
            )
            conn.execute("DELETE FROM contacts WHERE id = ?", (remove_id,))
            stats["email_dupes"] += 1

    # Pass 2: Exact LinkedIn URL duplicates
    dupes = conn.execute(
        """SELECT linkedin_url_normalized, GROUP_CONCAT(id) as ids, COUNT(*) as cnt
           FROM contacts
           WHERE linkedin_url_normalized IS NOT NULL AND linkedin_url_normalized != ''
           GROUP BY linkedin_url_normalized
           HAVING cnt > 1"""
    ).fetchall()

    for dupe in dupes:
        ids = [int(x) for x in dupe["ids"].split(",")]
        keep_id = ids[0]
        for remove_id in ids[1:]:
            conn.execute(
                "INSERT INTO dedup_log (kept_contact_id, merged_contact_id, match_type, match_score) VALUES (?, ?, 'exact_linkedin', 1.0)",
                (keep_id, remove_id),
            )
            conn.execute("DELETE FROM contacts WHERE id = ?", (remove_id,))
            stats["linkedin_dupes"] += 1

    # Pass 3: Fuzzy company name matching (flag for manual review)
    companies = conn.execute(
        "SELECT id, name, name_normalized FROM companies"
    ).fetchall()

    flagged = []
    seen_pairs = set()
    for i, c1 in enumerate(companies):
        for c2 in companies[i + 1 :]:
            pair_key = (min(c1["id"], c2["id"]), max(c1["id"], c2["id"]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            score = fuzz.token_sort_ratio(c1["name_normalized"], c2["name_normalized"])
            if score >= FUZZY_THRESHOLD:
                flagged.append(
                    {
                        "company_a_id": c1["id"],
                        "company_a_name": c1["name"],
                        "company_b_id": c2["id"],
                        "company_b_name": c2["name"],
                        "score": score,
                    }
                )
                stats["fuzzy_flagged"] += 1

    if flagged and export_dir:
        export_path = Path(export_dir) / "dedup_review.csv"
        with open(export_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "company_a_id",
                    "company_a_name",
                    "company_b_id",
                    "company_b_name",
                    "score",
                ],
            )
            writer.writeheader()
            writer.writerows(flagged)

    conn.commit()
    return stats
```

**Step 4: Run tests**

```bash
pytest tests/test_deduplication.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
git add src/services/deduplication.py tests/test_deduplication.py
git commit -m "feat: add 3-pass deduplication pipeline (email, linkedin, fuzzy company)"
```

---

### Task 6: Email Verification Service

**Files:**
- Create: `src/services/email_verifier.py`
- Create: `src/commands/verify_emails.py`
- Create: `tests/test_email_verifier.py`

**Step 1: Write the failing tests**

`tests/test_email_verifier.py`:
```python
from unittest.mock import patch, MagicMock
from src.models.database import get_connection, run_migrations
from src.services.email_verifier import verify_email_batch, update_contact_email_status


def _insert_contact(conn, email):
    conn.execute(
        """INSERT INTO companies (name, name_normalized, country, is_gdpr)
           VALUES ('Test Co', 'test co', 'US', 0)"""
    )
    company_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO contacts
           (company_id, full_name, email, email_normalized, email_status,
            priority_rank, source, is_gdpr)
           VALUES (?, 'Test', ?, ?, 'unverified', 1, 'test', 0)""",
        (company_id, email, email.lower()),
    )
    conn.commit()


def test_update_contact_status_valid(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _insert_contact(conn, "good@example.com")
    update_contact_email_status(conn, "good@example.com", "valid")
    status = conn.execute(
        "SELECT email_status FROM contacts WHERE email_normalized = 'good@example.com'"
    ).fetchone()
    assert status["email_status"] == "valid"
    conn.close()


def test_update_contact_status_invalid(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _insert_contact(conn, "bad@example.com")
    update_contact_email_status(conn, "bad@example.com", "invalid")
    status = conn.execute(
        "SELECT email_status FROM contacts WHERE email_normalized = 'bad@example.com'"
    ).fetchone()
    assert status["email_status"] == "invalid"
    conn.close()


def test_unverified_contacts_queried(tmp_db):
    conn = get_connection(tmp_db)
    run_migrations(conn)
    _insert_contact(conn, "new@example.com")
    unverified = conn.execute(
        "SELECT email_normalized FROM contacts WHERE email_status = 'unverified' AND email_normalized IS NOT NULL"
    ).fetchall()
    assert len(unverified) == 1
    conn.close()
```

**Step 2: Run tests to verify failure**

```bash
pytest tests/test_email_verifier.py -v
```

**Step 3: Write the implementation**

`src/services/email_verifier.py`:
```python
import httpx
import time


def verify_email_batch(emails: list[str], api_key: str, provider: str = "zerobounce") -> dict[str, str]:
    """Verify a batch of emails. Returns {email: status} where status is valid/invalid/risky/catch-all/unknown."""
    results = {}
    if provider == "zerobounce":
        results = _verify_zerobounce(emails, api_key)
    elif provider == "hunter":
        results = _verify_hunter(emails, api_key)
    return results


def _verify_zerobounce(emails: list[str], api_key: str) -> dict[str, str]:
    results = {}
    # ZeroBounce supports batch validation via their API
    # Process in chunks of 100 (API limit)
    for i in range(0, len(emails), 100):
        chunk = emails[i : i + 100]
        try:
            resp = httpx.post(
                "https://bulkapi.zerobounce.net/v2/validatebatch",
                json={"api_key": api_key, "email_batch": [{"email_address": e} for e in chunk]},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("email_batch", []):
                email = item.get("address", "").lower()
                status = item.get("status", "unknown").lower()
                if status == "valid":
                    results[email] = "valid"
                elif status == "invalid":
                    results[email] = "invalid"
                elif status == "catch-all":
                    results[email] = "catch-all"
                elif status in ("spamtrap", "abuse", "do_not_mail"):
                    results[email] = "invalid"
                else:
                    results[email] = "risky"
        except httpx.HTTPError:
            for e in chunk:
                results[e.lower()] = "unknown"
        time.sleep(1)  # rate limiting
    return results


def _verify_hunter(emails: list[str], api_key: str) -> dict[str, str]:
    results = {}
    for email in emails:
        try:
            resp = httpx.get(
                "https://api.hunter.io/v2/email-verifier",
                params={"email": email, "api_key": api_key},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            status = data.get("status", "unknown")
            if status == "valid":
                results[email.lower()] = "valid"
            elif status == "invalid":
                results[email.lower()] = "invalid"
            elif status == "accept_all":
                results[email.lower()] = "catch-all"
            else:
                results[email.lower()] = "risky"
        except httpx.HTTPError:
            results[email.lower()] = "unknown"
        time.sleep(0.5)  # rate limiting
    return results


def update_contact_email_status(conn, email: str, status: str) -> None:
    conn.execute(
        "UPDATE contacts SET email_status = ?, updated_at = datetime('now') WHERE email_normalized = ?",
        (status, email.lower()),
    )
    conn.commit()


def get_unverified_emails(conn) -> list[str]:
    rows = conn.execute(
        "SELECT email_normalized FROM contacts WHERE email_status = 'unverified' AND email_normalized IS NOT NULL"
    ).fetchall()
    return [row["email_normalized"] for row in rows]
```

**Step 4: Run tests**

```bash
pytest tests/test_email_verifier.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
git add src/services/email_verifier.py tests/test_email_verifier.py
git commit -m "feat: add email verification service (ZeroBounce + Hunter API)"
```

---

### Task 7: Wire Up CLI Commands for Phase 1

**Files:**
- Modify: `src/cli.py`
- Create: `src/commands/dedupe.py`
- Create: `src/commands/verify_emails.py`

**Step 1: Write the CLI commands**

`src/commands/dedupe.py`:
```python
import typer
from rich.console import Console
from src.models.database import get_connection, run_migrations
from src.services.deduplication import run_dedup

console = Console()


def dedupe_command(db_path: str, export_dir: str = "data/exports") -> None:
    conn = get_connection(db_path)
    run_migrations(conn)
    console.print("[bold]Running deduplication pipeline...[/bold]")
    stats = run_dedup(conn, export_dir=export_dir)
    console.print(f"  Email duplicates removed: {stats['email_dupes']}")
    console.print(f"  LinkedIn duplicates removed: {stats['linkedin_dupes']}")
    console.print(f"  Fuzzy company matches flagged: {stats['fuzzy_flagged']}")
    if stats["fuzzy_flagged"] > 0:
        console.print(f"  Review: {export_dir}/dedup_review.csv")
    conn.close()
```

`src/commands/verify_emails.py`:
```python
import os
import typer
from rich.console import Console
from rich.progress import track
from src.models.database import get_connection, run_migrations
from src.services.email_verifier import verify_email_batch, update_contact_email_status, get_unverified_emails

console = Console()


def verify_command(db_path: str) -> None:
    api_key = os.getenv("EMAIL_VERIFY_API_KEY")
    provider = os.getenv("EMAIL_VERIFY_PROVIDER", "zerobounce")
    if not api_key:
        console.print("[red]ERROR: Set EMAIL_VERIFY_API_KEY in .env[/red]")
        raise typer.Exit(1)

    conn = get_connection(db_path)
    run_migrations(conn)
    emails = get_unverified_emails(conn)
    console.print(f"[bold]Verifying {len(emails)} email addresses via {provider}...[/bold]")

    if not emails:
        console.print("No unverified emails found.")
        conn.close()
        return

    results = verify_email_batch(emails, api_key, provider=provider)
    counts = {"valid": 0, "invalid": 0, "risky": 0, "catch-all": 0, "unknown": 0}
    for email, status in results.items():
        update_contact_email_status(conn, email, status)
        counts[status] = counts.get(status, 0) + 1

    console.print(f"  Valid: {counts['valid']}")
    console.print(f"  Invalid: {counts['invalid']}")
    console.print(f"  Risky: {counts['risky']}")
    console.print(f"  Catch-all: {counts['catch-all']}")
    console.print(f"  Unknown: {counts['unknown']}")
    conn.close()
```

Update `src/cli.py`:
```python
import os
import typer
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

app = typer.Typer(name="outreach", help="Multi-channel outreach campaign manager")
console = Console()

DB_PATH = os.getenv("DATABASE_PATH", "outreach.db")


@app.command()
def import_csv(csv_path: str = typer.Argument(..., help="Path to Crypto Fund List CSV")):
    """Import contacts from the crypto fund CSV file."""
    from src.models.database import get_connection, run_migrations
    from src.commands.import_contacts import import_fund_csv

    conn = get_connection(DB_PATH)
    run_migrations(conn)
    stats = import_fund_csv(conn, csv_path)
    console.print(f"[green]Imported {stats['companies_created']} companies, {stats['contacts_created']} contacts[/green]")
    conn.close()


@app.command()
def import_emails(file_path: str = typer.Argument(..., help="Path to file with pasted emails")):
    """Import contacts from a pasted email list."""
    from src.models.database import get_connection, run_migrations
    from src.commands.import_emails import import_pasted_emails

    conn = get_connection(DB_PATH)
    run_migrations(conn)
    stats = import_pasted_emails(conn, file_path)
    console.print(f"[green]Imported {stats['contacts_created']} contacts ({stats['lines_skipped']} skipped)[/green]")
    conn.close()


@app.command()
def dedupe():
    """Run deduplication pipeline across all contacts."""
    from src.commands.dedupe import dedupe_command
    dedupe_command(DB_PATH)


@app.command()
def verify():
    """Verify all unverified email addresses via ZeroBounce/Hunter."""
    from src.commands.verify_emails import verify_command
    verify_command(DB_PATH)


@app.command()
def stats():
    """Show database statistics."""
    from src.models.database import get_connection, run_migrations

    conn = get_connection(DB_PATH)
    run_migrations(conn)
    companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    contacts = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    gdpr = conn.execute("SELECT COUNT(*) FROM contacts WHERE is_gdpr = 1").fetchone()[0]
    verified = conn.execute("SELECT COUNT(*) FROM contacts WHERE email_status = 'valid'").fetchone()[0]
    with_email = conn.execute("SELECT COUNT(*) FROM contacts WHERE email_normalized IS NOT NULL").fetchone()[0]
    with_linkedin = conn.execute("SELECT COUNT(*) FROM contacts WHERE linkedin_url IS NOT NULL").fetchone()[0]

    console.print(f"Companies: {companies}")
    console.print(f"Contacts: {contacts}")
    console.print(f"  With email: {with_email}")
    console.print(f"  With LinkedIn: {with_linkedin}")
    console.print(f"  GDPR contacts: {gdpr}")
    console.print(f"  Email verified: {verified}")
    conn.close()


if __name__ == "__main__":
    app()
```

**Step 2: Run all tests**

```bash
pytest tests/ -v
```
Expected: All PASS

**Step 3: Commit**

```bash
git add src/cli.py src/commands/dedupe.py src/commands/verify_emails.py
git commit -m "feat: wire up CLI commands (import-csv, import-emails, dedupe, verify, stats)"
```

---

### Task 8: Phase 1 Integration Test with Real Data

**Step 1: Install dependencies**

```bash
cd /Users/helios-mammut/Documents/Claude-Projects/Outreach-campaign
pip install -e ".[dev]"
```

**Step 2: Copy the real CSV to data/imports/**

```bash
cp "/Users/helios-mammut/Downloads/Crypto_Fund_List CSV_new.csv" data/imports/
```

**Step 3: Run import on real data**

```bash
python -m src.cli import-csv "data/imports/Crypto_Fund_List CSV_new.csv"
python -m src.cli stats
```

Expected: ~875 companies, ~2000+ contacts imported

**Step 4: Run dedupe**

```bash
python -m src.cli dedupe
```

Expected: Some duplicates found and removed, fuzzy matches flagged

**Step 5: Check stats again**

```bash
python -m src.cli stats
```

Verify numbers make sense after dedup.

**Step 6: Commit the integration test results**

```bash
git add -A
git commit -m "feat: Phase 1 complete - data import, dedup, verification pipeline"
```

---

## Phase 2: Campaign Engine (Tasks 9-16)

### Task 9: Campaign + Sequence Models

**Files:**
- Create: `src/models/campaigns.py`
- Create: `tests/test_campaigns.py`

Create CRUD operations for campaigns, sequence_steps, templates, and contact_campaign_status. Include:
- `create_campaign(conn, name, description)` → returns campaign_id
- `add_sequence_step(conn, campaign_id, step_order, channel, template_id, delay_days)`
- `enroll_contacts(conn, campaign_id)` → bulk-enrolls all eligible contacts (verified email or has LinkedIn)
- `get_contact_status(conn, contact_id, campaign_id)`
- `advance_contact(conn, contact_id, campaign_id, new_status)`

### Task 10: Contact State Machine

**Files:**
- Create: `src/services/state_machine.py`
- Create: `tests/test_state_machine.py`

Valid transitions:
- `queued` → `in_progress`
- `in_progress` → `no_response` | `replied_positive` | `replied_negative` | `bounced`

When a contact transitions to `no_response` or `bounced`, auto-activate the next priority_rank contact at the same company (if any).

### Task 11: Priority Queue Algorithm

**Files:**
- Create: `src/services/priority_queue.py`
- Create: `tests/test_priority_queue.py`

SQL query logic:
1. For each company, select only the lowest `priority_rank` contact whose status is `queued` or `in_progress`
2. Filter to contacts whose `next_action_date <= today`
3. For email steps: only contacts with `email_status = 'valid'`
4. Order by company `aum_millions DESC`
5. Limit to the daily target (default 10)

### Task 12: GDPR-Aware Sequence Selection

Modify the queue generator to check `is_gdpr` on contacts/companies and assign the correct sequence (standard 5-step vs GDPR 4-step with max 2 emails).

### Task 13: Queue Generation CLI Command

**Files:**
- Create: `src/commands/queue.py`

`outreach queue today` → displays today's actions in a Rich table:
```
Today's Actions (2026-02-24):
┌──────────────────┬─────────────────┬──────────────┬─────────┐
│ Company          │ Contact         │ Channel      │ Step    │
├──────────────────┼─────────────────┼──────────────┼─────────┤
│ Aaro Capital     │ Peter Haberm... │ linkedin_msg │ 2 of 4  │
│ 10T Fund         │ Dan Tapiero     │ email_cold   │ 3 of 5  │
└──────────────────┴─────────────────┴──────────────┴─────────┘
```

### Task 14: Expandi CSV Export

**Files:**
- Create: `src/commands/export_expandi.py`

`outreach export expandi` → writes CSV to `data/exports/expandi_YYYY-MM-DD.csv` with columns:
`profile_link`, `email`, `first_name`, `last_name`, `company_name`

Only includes contacts whose next step is a LinkedIn action.

### Task 15: Expandi Results Import

**Files:**
- Create: `src/commands/import_expandi.py`

`outreach import-expandi <file>` → reads Expandi export CSV, matches contacts by LinkedIn URL, updates status (connected, message_sent).

### Task 16: Tests for Phase 2

Full test suite for priority queue, state machine, GDPR routing, and Expandi integration.

---

## Phase 3: Email Sending (Tasks 17-23)

### Task 17: Gmail SMTP Sender

**Files:**
- Create: `src/services/email_sender.py`

SMTP via `smtplib` with TLS. App Password auth (or OAuth2). **No tracking pixels.** Plain text with minimal HTML. Sends from secondary domain.

### Task 18: Email Templates

**Files:**
- Create: `src/templates/email/cold_outreach_v1.txt`
- Create: `src/templates/email/follow_up_v1.txt`
- Create: `src/templates/email/breakup_v1.txt`

All templates include:
- Personalization: `{{ first_name }}`, `{{ company_name }}`, `{{ firm_type }}`
- Calendly CTA: `{{ calendly_url }}`
- Unsubscribe link: `{{ unsubscribe_url }}`
- Physical address: `{{ physical_address }}`

### Task 19: LinkedIn Templates

**Files:**
- Create: `src/templates/linkedin/connect_note_v1.txt`
- Create: `src/templates/linkedin/message_v1.txt`

300 char limit for connect notes. Mention shared crypto/quant focus.

### Task 20-23: Compliance, Send Command, A/B Logic, Tests

Wire up `outreach send` CLI command. Only sends to today's queue. Confirms before sending. A/B variant assignment at enrollment time.

---

## Phase 4: Reporting + Weekly Planning (Tasks 24-28)

### Task 24-25: Reply Logging + Metrics

`outreach status reply <email> positive|negative|call-booked`

Metrics: reply rate by template variant, by channel, by firm type, by GDPR status.

### Task 26: Weekly Plan Command

`outreach weekly-plan` → Rich-formatted terminal output:
- Last week recap (sent, replied, booked)
- A/B variant comparison
- Proposed next week schedule
- Newsletter recommendation

### Task 27-28: Report + Tests

`outreach report` → full funnel dashboard in terminal.

---

## Phase 5: Newsletter (Tasks 29-33)

Markdown → HTML rendering via `markdown2` + `premailer`. Newsletter subscriber management with GDPR-aware auto-enrollment. `outreach newsletter preview` and `outreach newsletter send`.

---

## Phase 6: Polish (Tasks 34-37)

Makefile, PLAYBOOK.md, config.yaml template, end-to-end test.

---

## Verification Checklist

- [ ] Phase 1: `pytest tests/` all green, real CSV imported, dedup ran, stats look right
- [ ] Phase 2: `outreach queue today` shows correct contacts, one-per-company, AUM-ordered
- [ ] Phase 3: Test email received, no tracking pixels in source, Calendly link works, unsubscribe link works
- [ ] Phase 4: `outreach weekly-plan` shows correct metrics after logging test replies
- [ ] Phase 5: Newsletter renders correctly, unsubscribe link works
- [ ] Phase 6: End-to-end: import → dedup → verify → queue → send → reply → report
