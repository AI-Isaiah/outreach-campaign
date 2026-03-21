"""Tests for the firm-type diversity round-robin algorithm."""

import pytest

from src.services.adaptive_queue import _diversify_by_firm_type


def _make_item(firm_type, score, contact_id=None):
    """Helper to create a mock queue item."""
    return {
        "contact_id": contact_id or id(firm_type),
        "firm_type": firm_type,
        "priority_score": score,
        "company_name": f"Company {contact_id}",
    }


class TestDiversifyByFirmType:
    """Tests for _diversify_by_firm_type()."""

    def test_even_distribution_across_types(self):
        """Round-robin picks evenly from each firm type."""
        items = [
            _make_item("Hedge Fund", 0.9, 1),
            _make_item("Hedge Fund", 0.8, 2),
            _make_item("Hedge Fund", 0.7, 3),
            _make_item("VC", 0.85, 4),
            _make_item("VC", 0.75, 5),
            _make_item("VC", 0.65, 6),
            _make_item("Family Office", 0.6, 7),
            _make_item("Family Office", 0.5, 8),
            _make_item("Family Office", 0.4, 9),
        ]

        result = _diversify_by_firm_type(items, limit=6)

        assert len(result) == 6
        types = [r["firm_type"] for r in result]
        # Each type should appear exactly twice with limit=6 and 3 types
        assert types.count("Hedge Fund") == 2
        assert types.count("VC") == 2
        assert types.count("Family Office") == 2

    def test_respects_limit(self):
        """Result never exceeds the requested limit."""
        items = [_make_item("HF", 0.9 - i * 0.01, i) for i in range(20)]
        result = _diversify_by_firm_type(items, limit=5)
        assert len(result) == 5

    def test_handles_null_firm_type(self):
        """NULL firm_type is grouped as 'Unknown'."""
        items = [
            _make_item(None, 0.9, 1),
            _make_item(None, 0.8, 2),
            _make_item("Hedge Fund", 0.85, 3),
            _make_item("Hedge Fund", 0.75, 4),
        ]

        result = _diversify_by_firm_type(items, limit=4)

        assert len(result) == 4
        # Both buckets should be represented
        types = [r.get("firm_type") for r in result]
        assert types.count(None) == 2
        assert types.count("Hedge Fund") == 2

    def test_single_type_fallback(self):
        """With only one firm type, all items come from that type."""
        items = [
            _make_item("Hedge Fund", 0.9, 1),
            _make_item("Hedge Fund", 0.8, 2),
            _make_item("Hedge Fund", 0.7, 3),
        ]

        result = _diversify_by_firm_type(items, limit=3)

        assert len(result) == 3
        assert all(r["firm_type"] == "Hedge Fund" for r in result)

    def test_empty_items(self):
        """Returns empty list for empty input."""
        result = _diversify_by_firm_type([], limit=10)
        assert result == []

    def test_limit_larger_than_items(self):
        """Returns all items when limit exceeds available items."""
        items = [
            _make_item("HF", 0.9, 1),
            _make_item("VC", 0.8, 2),
        ]

        result = _diversify_by_firm_type(items, limit=10)
        assert len(result) == 2

    def test_priority_order_within_type(self):
        """Within each type, items are picked in priority order (highest first)."""
        items = [
            _make_item("HF", 0.9, 1),
            _make_item("HF", 0.5, 2),
            _make_item("VC", 0.8, 3),
            _make_item("VC", 0.4, 4),
        ]

        result = _diversify_by_firm_type(items, limit=4)

        # First round: top of each bucket; second round: second of each
        hf_items = [r for r in result if r["firm_type"] == "HF"]
        assert hf_items[0]["priority_score"] > hf_items[1]["priority_score"]

    def test_bucket_ordering_by_top_score(self):
        """Buckets are ordered by their top item's score — highest-scoring type picked first."""
        items = [
            _make_item("Low Type", 0.3, 1),
            _make_item("High Type", 0.95, 2),
            _make_item("Mid Type", 0.6, 3),
        ]

        result = _diversify_by_firm_type(items, limit=3)

        # First item should be from the highest-scoring bucket
        assert result[0]["firm_type"] == "High Type"

    def test_uneven_buckets(self):
        """Handles uneven bucket sizes gracefully."""
        items = [
            _make_item("HF", 0.9, 1),
            _make_item("HF", 0.8, 2),
            _make_item("HF", 0.7, 3),
            _make_item("HF", 0.6, 4),
            _make_item("VC", 0.85, 5),
        ]

        result = _diversify_by_firm_type(items, limit=5)

        assert len(result) == 5
        types = [r["firm_type"] for r in result]
        # VC has 1 item, HF has 4 — should still get the mix
        assert "VC" in types
        assert types.count("HF") == 4
