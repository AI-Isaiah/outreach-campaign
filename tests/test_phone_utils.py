"""Tests for phone number normalization utilities."""

from __future__ import annotations

from src.services.phone_utils import normalize_phone


def test_normalize_us_phone():
    assert normalize_phone("+1 (555) 123-4567") == "+15551234567"


def test_normalize_uk_phone():
    assert normalize_phone("+44 20 7123 4567") == "+442071234567"


def test_normalize_international_prefix():
    assert normalize_phone("00442071234567") == "+442071234567"


def test_normalize_digits_only():
    assert normalize_phone("15551234567") == "+15551234567"


def test_normalize_empty():
    assert normalize_phone("") is None
