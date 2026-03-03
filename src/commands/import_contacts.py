"""Import crypto fund CSV into the SQLite database.

Reads a CSV with ~875 rows of crypto funds (up to 4 contacts per fund),
normalises data, detects GDPR countries, and inserts companies + contacts.
"""

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, urlunparse

import yaml


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Helper functions (all prefixed with _)
# ---------------------------------------------------------------------------


def _load_gdpr_countries() -> Set[str]:
    """Load GDPR country list from config.yaml or config.yaml.example.

    Returns a set of lowercased country names for fast lookup.
    """
    config_path = _PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        config_path = _PROJECT_ROOT / "config.yaml.example"

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    countries = config.get("gdpr_countries", [])
    return {c.strip().lower() for c in countries}


def _parse_aum(raw: str) -> Optional[float]:
    """Parse AUM string like ``"$1,219.50"`` into a float.

    Returns None when the value is empty, whitespace, or unparseable.
    """
    if raw is None:
        return None
    cleaned = raw.strip().replace("$", "").replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_email(email: Optional[str]) -> Optional[str]:
    """Lowercase, strip whitespace, validate contains ``@``.

    Returns None if the input is empty or invalid.
    """
    if email is None:
        return None
    email = email.strip().lower()
    if not email or "@" not in email:
        return None
    return email


def _normalize_linkedin(url: Optional[str]) -> Optional[str]:
    """Strip query params, trailing slashes, and lowercase the URL.

    Returns None if the input is empty or not a LinkedIn URL.
    """
    if url is None:
        return None
    url = url.strip()
    if not url:
        return None

    # Parse URL, drop query and fragment, lowercase
    parsed = urlparse(url)
    cleaned = urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        "",  # params
        "",  # query
        "",  # fragment
    ))
    return cleaned if cleaned else None


def _normalize_company_name(name: str) -> str:
    """Lowercase and collapse multiple whitespace characters."""
    return re.sub(r"\s+", " ", name.strip().lower())


def _split_name(full_name: str) -> Tuple[str, str]:
    """Split a full name into (first_name, last_name).

    Simple heuristic: everything before the last space is first name,
    everything after is last name.  If only one token, it becomes the
    first name with an empty last name.
    """
    parts = full_name.strip().split()
    if len(parts) == 0:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (" ".join(parts[:-1]), parts[-1])


# ---------------------------------------------------------------------------
# Contact-slot extraction
# ---------------------------------------------------------------------------

_CONTACT_SLOTS = [
    {
        "rank": 1,
        "name_col": "Primary Contact",
        "title_col": "Position",
        "linkedin_col": "Primary LinkedIn",
        "email_col": "Primary Email",
    },
    {
        "rank": 2,
        "name_col": "Contact 2",
        "title_col": "Contact 2 Title",
        "linkedin_col": "Contact 2 LinkedIn",
        "email_col": "Contact 2 Email",
    },
    {
        "rank": 3,
        "name_col": "Contact 3",
        "title_col": "Contact 3 Title",
        "linkedin_col": "Contact 3 LinkedIn",
        "email_col": "Contact 3 Email",
    },
    {
        "rank": 4,
        "name_col": "Contact 4",
        "title_col": "Contact 4 Title",
        "linkedin_col": "Contact 4 LinkedIn",
        "email_col": "Contact 4 Email",
    },
]


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------


def import_fund_csv(conn, csv_path: str) -> Dict[str, int]:
    """Import a crypto-fund CSV into the database.

    Parameters
    ----------
    conn : database connection
        An open database connection (migrations must already be applied).
    csv_path : str
        Path to the CSV file.

    Returns
    -------
    dict
        ``{"companies_created": int, "contacts_created": int}``
    """
    gdpr_countries = _load_gdpr_countries()

    companies_created = 0
    contacts_created = 0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            # ------ Company --------------------------------------------------
            firm_name = (row.get("Firm Name") or "").strip()
            if not firm_name:
                continue

            name_normalized = _normalize_company_name(firm_name)
            country = (row.get("Country") or "").strip()
            is_gdpr = 1 if country.lower() in gdpr_countries else 0

            # AUM — the header has leading/trailing spaces
            aum_raw = row.get(" AUM (Millions) ") or row.get("AUM (Millions)") or ""
            aum = _parse_aum(aum_raw)

            # Firm types (1-5) joined into a comma-separated string
            firm_types = []
            for col in ["Firm Type", "Firm Type 2", "Firm Type 3",
                        "Firm Type 4", "Firm Type 5"]:
                val = (row.get(col) or "").strip()
                if val:
                    firm_types.append(val)
            firm_type_str = ", ".join(firm_types) if firm_types else None

            address_parts = [
                (row.get("Address") or "").strip(),
                (row.get("Address 2") or "").strip(),
            ]
            address = ", ".join(p for p in address_parts if p) or None

            city = (row.get("City") or "").strip() or None
            website = (row.get("URL") or "").strip() or None
            company_linkedin = (row.get("Company LinkedIn") or "").strip() or None

            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO companies
                   (name, name_normalized, address, city, country, aum_millions,
                    firm_type, website, linkedin_url, is_gdpr)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (
                    firm_name,
                    name_normalized,
                    address,
                    city,
                    country or None,
                    aum,
                    firm_type_str,
                    website,
                    company_linkedin,
                    is_gdpr,
                ),
            )
            company_id = cursor.fetchone()["id"]
            companies_created += 1

            # ------ Contacts -------------------------------------------------
            for slot in _CONTACT_SLOTS:
                full_name = (row.get(slot["name_col"]) or "").strip()
                email_raw = (row.get(slot["email_col"]) or "").strip() or None
                linkedin_raw = (row.get(slot["linkedin_col"]) or "").strip() or None
                title = (row.get(slot["title_col"]) or "").strip() or None

                # Skip slot if no name, no email, AND no LinkedIn
                if not full_name and not email_raw and not linkedin_raw:
                    continue

                first_name, last_name = _split_name(full_name)
                email_normalized = _normalize_email(email_raw)
                linkedin_normalized = _normalize_linkedin(linkedin_raw)

                cursor.execute(
                    """INSERT INTO contacts
                       (company_id, first_name, last_name, full_name,
                        email, email_normalized, linkedin_url,
                        linkedin_url_normalized, title, priority_rank,
                        source, is_gdpr)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'csv', %s)""",
                    (
                        company_id,
                        first_name or None,
                        last_name or None,
                        full_name or None,
                        email_raw,
                        email_normalized,
                        linkedin_raw,
                        linkedin_normalized,
                        title,
                        slot["rank"],
                        is_gdpr,
                    ),
                )
                contacts_created += 1

    conn.commit()
    return {
        "companies_created": companies_created,
        "contacts_created": contacts_created,
    }
