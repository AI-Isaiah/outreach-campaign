"""Edge case tests for src/services/template_engine.py."""

import os
import tempfile

import pytest

from src.models.database import get_connection, run_migrations
from src.services.template_engine import (
    render_template,
    get_template_context,
    _get_jinja_env,
)
from tests.conftest import TEST_USER_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db(db_path):
    conn = get_connection(db_path)
    run_migrations(conn)
    return conn


def _create_company(conn, name="Acme Fund"):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO companies (name, name_normalized, user_id) "
        "VALUES (%s, %s, %s) RETURNING id",
        (name, name.lower(), TEST_USER_ID),
    )
    company_id = cursor.fetchone()["id"]
    conn.commit()
    return company_id


def _create_contact(conn, company_id, first_name="Test", last_name="User", email="test@example.com"):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO contacts (company_id, first_name, last_name, full_name, "
        "email, email_normalized, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (company_id, first_name, last_name, f"{first_name} {last_name}",
         email, email.lower(), TEST_USER_ID),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    return contact_id


# ---------------------------------------------------------------------------
# Tests: render_template with file-based templates
# ---------------------------------------------------------------------------

class TestRenderTemplate:
    def test_basic_render(self, tmp_path):
        """Render a simple template with all variables present."""
        tpl = tmp_path / "email"
        tpl.mkdir()
        (tpl / "test.txt").write_text("Hello {{ first_name }}, from {{ company_name }}.")
        result = render_template("email/test.txt", {"first_name": "Alice", "company_name": "Acme"}, str(tmp_path))
        assert result == "Hello Alice, from Acme."

    def test_missing_variable_renders_empty(self, tmp_path):
        """A missing variable should render as empty string (Jinja2 undefined default)."""
        tpl = tmp_path / "email"
        tpl.mkdir()
        (tpl / "test.txt").write_text("Hello {{ first_name }}, from {{ company_name }}.")
        # Jinja2 with default settings renders undefined as empty string
        result = render_template("email/test.txt", {"first_name": "Alice"}, str(tmp_path))
        assert "Alice" in result
        assert result == "Hello Alice, from ."

    def test_empty_body_template(self, tmp_path):
        """An empty template file renders as empty string."""
        tpl = tmp_path / "email"
        tpl.mkdir()
        (tpl / "empty.txt").write_text("")
        result = render_template("email/empty.txt", {"first_name": "Alice"}, str(tmp_path))
        assert result == ""

    def test_deep_research_key_in_context(self, tmp_path):
        """Template can access deep_research context."""
        tpl = tmp_path / "email"
        tpl.mkdir()
        (tpl / "research.txt").write_text(
            "{% if deep_research %}Research: {{ deep_research.talking_points }}{% else %}No research{% endif %}"
        )
        ctx = {"deep_research": {"talking_points": "AI investments growing"}}
        result = render_template("email/research.txt", ctx, str(tmp_path))
        assert "AI investments growing" in result

    def test_deep_research_none(self, tmp_path):
        """Template handles None deep_research gracefully."""
        tpl = tmp_path / "email"
        tpl.mkdir()
        (tpl / "research.txt").write_text(
            "{% if deep_research %}Research: {{ deep_research.talking_points }}{% else %}No research{% endif %}"
        )
        result = render_template("email/research.txt", {"deep_research": None}, str(tmp_path))
        assert result == "No research"

    def test_no_html_escaping(self, tmp_path):
        """autoescape is off so HTML chars pass through unchanged."""
        tpl = tmp_path / "email"
        tpl.mkdir()
        (tpl / "html.txt").write_text("Hello {{ name }}")
        result = render_template("email/html.txt", {"name": "<b>Alice</b>"}, str(tmp_path))
        assert result == "Hello <b>Alice</b>"

    def test_special_characters_in_context(self, tmp_path):
        """Template renders unicode and special characters correctly."""
        tpl = tmp_path / "email"
        tpl.mkdir()
        (tpl / "unicode.txt").write_text("Hello {{ name }}")
        result = render_template("email/unicode.txt", {"name": "Jean-Pierre Lefevre"}, str(tmp_path))
        assert "Jean-Pierre" in result

    def test_template_not_found_raises(self, tmp_path):
        """Requesting a nonexistent template raises an error."""
        from jinja2.exceptions import TemplateNotFound
        with pytest.raises(TemplateNotFound):
            render_template("email/nonexistent.txt", {}, str(tmp_path))


# ---------------------------------------------------------------------------
# Tests: get_template_context
# ---------------------------------------------------------------------------

class TestGetTemplateContext:
    def test_basic_context(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn, name="Alpha Capital")
        contact_id = _create_contact(conn, company_id, first_name="Jane", last_name="Doe")

        config = {
            "calendly_url": "https://calendly.com/me",
            "physical_address": "123 Main St, NY 10001",
            "smtp": {"username": "sender@fund.io"},
        }
        ctx = get_template_context(conn, contact_id, config, user_id=TEST_USER_ID)

        assert ctx["first_name"] == "Jane"
        assert ctx["last_name"] == "Doe"
        assert ctx["full_name"] == "Jane Doe"
        assert ctx["company_name"] == "Alpha Capital"
        assert ctx["calendly_url"] == "https://calendly.com/me"
        assert ctx["physical_address"] == "123 Main St, NY 10001"
        assert "mailto:sender@fund.io" in ctx["unsubscribe_url"]
        conn.close()

    def test_nonexistent_contact_raises(self, tmp_db):
        conn = _setup_db(tmp_db)
        config = {"smtp": {"username": "x@x.com"}}
        with pytest.raises(ValueError, match="not found"):
            get_template_context(conn, 99999, config, user_id=TEST_USER_ID)
        conn.close()

    def test_empty_config(self, tmp_db):
        """Empty config should not crash, just produce empty values."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)

        ctx = get_template_context(conn, contact_id, {}, user_id=TEST_USER_ID)

        assert ctx["calendly_url"] == ""
        assert ctx["physical_address"] == ""
        assert ctx["unsubscribe_url"] == "mailto:?subject=Unsubscribe"
        conn.close()

    def test_from_email_fallback(self, tmp_db):
        """from_email at top-level config takes priority over smtp.username."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)

        config = {
            "from_email": "primary@fund.io",
            "smtp": {"username": "fallback@fund.io"},
        }
        ctx = get_template_context(conn, contact_id, config, user_id=TEST_USER_ID)
        assert "primary@fund.io" in ctx["unsubscribe_url"]
        conn.close()

    def test_contact_without_company(self, tmp_db):
        """Contact with no company_id should produce empty company_name."""
        conn = _setup_db(tmp_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO contacts (first_name, last_name, full_name, email, "
            "email_normalized, user_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            ("Solo", "Person", "Solo Person", "solo@example.com", "solo@example.com", TEST_USER_ID),
        )
        contact_id = cursor.fetchone()["id"]
        conn.commit()

        ctx = get_template_context(conn, contact_id, {"smtp": {"username": "x@x.com"}}, user_id=TEST_USER_ID)
        assert ctx["company_name"] == ""
        assert ctx["deep_research"] is None
        conn.close()

    def test_pre_fetched_research_used(self, tmp_db):
        """When pre_fetched_research is provided, it is used instead of querying."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)

        research_data = {"talking_points": "Great fund", "crypto_signals": "BTC focus"}
        config = {"smtp": {"username": "x@x.com"}}
        ctx = get_template_context(
            conn, contact_id, config,
            user_id=TEST_USER_ID,
            pre_fetched_research={company_id: research_data},
        )
        assert ctx["deep_research"] == research_data
        conn.close()

    def test_pre_fetched_research_missing_company(self, tmp_db):
        """When pre_fetched_research dict does not contain the company, deep_research is None."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        contact_id = _create_contact(conn, company_id)

        config = {"smtp": {"username": "x@x.com"}}
        ctx = get_template_context(
            conn, contact_id, config,
            user_id=TEST_USER_ID,
            pre_fetched_research={999: {"data": "irrelevant"}},
        )
        assert ctx["deep_research"] is None
        conn.close()
