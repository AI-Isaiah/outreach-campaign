"""Jinja2 template rendering for outreach emails and LinkedIn messages.

Templates are stored under ``src/templates/`` and rendered with contact-
and campaign-specific context variables.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from src.services.compliance import build_unsubscribe_url

# Resolve the templates directory relative to this file's location.
# Structure: src/services/template_engine.py -> src/templates/
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _get_jinja_env(templates_dir: Optional[str] = None) -> Environment:
    """Create a Jinja2 Environment pointing at the templates directory.

    Args:
        templates_dir: override path to templates directory (for testing).
            Defaults to ``src/templates/``.

    Returns:
        A configured Jinja2 Environment.
    """
    base = templates_dir or str(_TEMPLATES_DIR)
    return Environment(
        loader=FileSystemLoader(base),
        autoescape=False,  # plain-text templates; no HTML escaping
        keep_trailing_newline=True,
    )


def render_template(
    template_path: str,
    context: dict,
    templates_dir: Optional[str] = None,
) -> str:
    """Render a Jinja2 template with the given context.

    Args:
        template_path: path relative to the templates directory,
            e.g. ``"email/cold_outreach_v1_a.txt"``
        context: dictionary of template variables
        templates_dir: optional override for the templates base directory

    Returns:
        The rendered template string.
    """
    env = _get_jinja_env(templates_dir)
    template = env.get_template(template_path)
    return template.render(**context)


def get_template_context(
    conn: sqlite3.Connection,
    contact_id: int,
    config: dict,
) -> dict:
    """Build the template context dictionary for a contact.

    Queries the database for the contact and their company, then merges
    with config values (calendly_url, physical_address, unsubscribe_url).

    Args:
        conn: database connection
        contact_id: the contact to build context for
        config: application config dict (must contain ``calendly_url``,
            ``physical_address``, and ``smtp.username`` or ``from_email``)

    Returns:
        A dict with keys: first_name, last_name, full_name, company_name,
        calendly_url, unsubscribe_url, physical_address.

    Raises:
        ValueError: if the contact is not found.
    """
    row = conn.execute(
        """SELECT c.first_name, c.last_name, c.full_name, co.name as company_name
           FROM contacts c
           LEFT JOIN companies co ON co.id = c.company_id
           WHERE c.id = ?""",
        (contact_id,),
    ).fetchone()

    if row is None:
        raise ValueError(f"Contact {contact_id} not found")

    first_name = row["first_name"] or ""
    last_name = row["last_name"] or ""
    full_name = row["full_name"] or f"{first_name} {last_name}".strip()
    company_name = row["company_name"] or ""

    # Derive from_email for the unsubscribe link
    smtp_config = config.get("smtp", {})
    from_email = config.get("from_email") or smtp_config.get("username", "")
    unsubscribe_url = build_unsubscribe_url(from_email)

    return {
        "first_name": first_name,
        "last_name": last_name,
        "full_name": full_name,
        "company_name": company_name,
        "calendly_url": config.get("calendly_url", ""),
        "unsubscribe_url": unsubscribe_url,
        "physical_address": config.get("physical_address", ""),
    }
