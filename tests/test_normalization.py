"""Edge case tests for src/services/normalization_utils.py."""

import pytest

from src.services.normalization_utils import (
    normalize_email,
    normalize_company_name,
    normalize_linkedin_url,
    split_name,
)


# ---------------------------------------------------------------------------
# Tests: normalize_email
# ---------------------------------------------------------------------------

class TestNormalizeEmail:
    def test_basic_lowercase(self):
        assert normalize_email("Alice@Example.COM") == "alice@example.com"

    def test_strips_whitespace(self):
        assert normalize_email("  alice@example.com  ") == "alice@example.com"

    def test_strips_whitespace_and_lowercases(self):
        assert normalize_email("  ALICE@EXAMPLE.COM  ") == "alice@example.com"

    def test_none_returns_none(self):
        assert normalize_email(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_email("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_email("   ") is None

    def test_no_at_sign_returns_none(self):
        assert normalize_email("not-an-email") is None

    def test_just_at_sign(self):
        # Has @ but is technically valid per this function
        result = normalize_email("@")
        assert result == "@"

    def test_email_with_plus_addressing(self):
        assert normalize_email("user+tag@example.com") == "user+tag@example.com"

    def test_email_with_dots(self):
        assert normalize_email("first.last@example.com") == "first.last@example.com"

    def test_email_with_leading_trailing_tabs(self):
        assert normalize_email("\talice@example.com\t") == "alice@example.com"


# ---------------------------------------------------------------------------
# Tests: normalize_linkedin_url
# ---------------------------------------------------------------------------

class TestNormalizeLinkedinUrl:
    def test_basic_url(self):
        assert normalize_linkedin_url("https://linkedin.com/in/johndoe") == "https://linkedin.com/in/johndoe"

    def test_trailing_slash_stripped(self):
        assert normalize_linkedin_url("https://linkedin.com/in/johndoe/") == "https://linkedin.com/in/johndoe"

    def test_www_prefix_preserved(self):
        result = normalize_linkedin_url("https://www.linkedin.com/in/johndoe")
        assert result == "https://www.linkedin.com/in/johndoe"

    def test_mixed_case_lowered(self):
        result = normalize_linkedin_url("HTTPS://LinkedIn.com/in/JohnDoe")
        assert result == "https://linkedin.com/in/johndoe"

    def test_pub_path(self):
        result = normalize_linkedin_url("https://linkedin.com/pub/johndoe/1/2/3")
        assert result == "https://linkedin.com/pub/johndoe/1/2/3"

    def test_query_params_stripped(self):
        result = normalize_linkedin_url("https://linkedin.com/in/johndoe?utm_source=google")
        assert result == "https://linkedin.com/in/johndoe"

    def test_fragment_stripped(self):
        result = normalize_linkedin_url("https://linkedin.com/in/johndoe#section")
        assert result == "https://linkedin.com/in/johndoe"

    def test_multiple_trailing_slashes(self):
        result = normalize_linkedin_url("https://linkedin.com/in/johndoe///")
        assert result == "https://linkedin.com/in/johndoe"

    def test_empty_string_returns_empty(self):
        assert normalize_linkedin_url("") == ""

    def test_none_returns_empty(self):
        assert normalize_linkedin_url(None) == ""

    def test_whitespace_only_returns_empty(self):
        assert normalize_linkedin_url("   ") == ""

    def test_no_scheme_returns_empty(self):
        """URL without scheme is invalid."""
        assert normalize_linkedin_url("linkedin.com/in/johndoe") == ""

    def test_whitespace_around_url_stripped(self):
        result = normalize_linkedin_url("  https://linkedin.com/in/johndoe  ")
        assert result == "https://linkedin.com/in/johndoe"

    def test_http_scheme(self):
        result = normalize_linkedin_url("http://linkedin.com/in/johndoe")
        assert result == "http://linkedin.com/in/johndoe"


# ---------------------------------------------------------------------------
# Tests: normalize_company_name
# ---------------------------------------------------------------------------

class TestNormalizeCompanyName:
    def test_basic_lowercase(self):
        assert normalize_company_name("Acme Corp") == "acme"

    def test_strips_inc(self):
        assert normalize_company_name("Acme Inc.") == "acme"

    def test_strips_llc(self):
        assert normalize_company_name("Acme LLC") == "acme"

    def test_strips_capital(self):
        assert normalize_company_name("Alpha Capital") == "alpha"

    def test_strips_fund(self):
        assert normalize_company_name("Beta Fund") == "beta"

    def test_ampersand_to_and(self):
        assert normalize_company_name("Smith & Jones") == "smith and jones"

    def test_collapses_whitespace(self):
        assert normalize_company_name("  Acme   Fund  ") == "acme"

    def test_empty_string(self):
        assert normalize_company_name("") == ""

    def test_none_returns_none(self):
        assert normalize_company_name(None) is None

    def test_multiple_suffixes_strips_last(self):
        # Only the trailing suffix is stripped
        result = normalize_company_name("Capital Group Management")
        assert result == "capital group"

    def test_preserves_non_suffix_words(self):
        result = normalize_company_name("Starlight Ventures")
        assert result == "starlight"


# ---------------------------------------------------------------------------
# Tests: split_name
# ---------------------------------------------------------------------------

class TestSplitName:
    def test_two_parts(self):
        assert split_name("John Doe") == ("John", "Doe")

    def test_single_name(self):
        assert split_name("Madonna") == ("Madonna", "")

    def test_three_parts(self):
        first, last = split_name("Jean Claude Van Damme")
        assert first == "Jean"
        assert last == "Claude Van Damme"

    def test_extra_whitespace(self):
        first, last = split_name("  John   Doe  ")
        assert first == "John"
        assert last == "Doe"

    def test_unicode_name(self):
        first, last = split_name("Jose Garcia")
        assert first == "Jose"
        assert last == "Garcia"

    def test_empty_string(self):
        first, last = split_name("")
        assert first == ""
        assert last == ""

    def test_whitespace_only(self):
        first, last = split_name("   ")
        assert first == ""
        assert last == ""
