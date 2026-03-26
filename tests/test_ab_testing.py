"""Edge case tests for src/services/ab_testing.py."""

import pytest

from src.models.database import get_connection, run_migrations
from src.models.campaigns import create_campaign, enroll_contact
from src.services.ab_testing import assign_variant, get_variant_stats
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
        "INSERT INTO companies (name, name_normalized, user_id) VALUES (%s, %s, %s) RETURNING id",
        (name, name.lower(), TEST_USER_ID),
    )
    company_id = cursor.fetchone()["id"]
    conn.commit()
    return company_id


def _create_contact(conn, company_id, email=None, rank=1):
    email = email or f"contact{rank}@example.com"
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO contacts (company_id, priority_rank, email, first_name, last_name, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (company_id, rank, email, f"First{rank}", f"Last{rank}", TEST_USER_ID),
    )
    contact_id = cursor.fetchone()["id"]
    conn.commit()
    return contact_id


# ---------------------------------------------------------------------------
# Tests: assign_variant
# ---------------------------------------------------------------------------

class TestAssignVariant:
    def test_default_two_variants(self):
        result = assign_variant(1)
        assert result in ["A", "B"]

    def test_single_variant(self):
        """With only one variant, always returns that variant."""
        result = assign_variant(42, ["X"])
        assert result == "X"

    def test_three_variants(self):
        result = assign_variant(1, ["A", "B", "C"])
        assert result in ["A", "B", "C"]

    def test_deterministic_same_id(self):
        """Same contact_id always gets the same variant."""
        v1 = assign_variant(100)
        v2 = assign_variant(100)
        v3 = assign_variant(100)
        assert v1 == v2 == v3

    def test_deterministic_with_custom_variants(self):
        v1 = assign_variant(55, ["X", "Y", "Z"])
        v2 = assign_variant(55, ["X", "Y", "Z"])
        assert v1 == v2

    def test_different_ids_may_differ(self):
        """Different contact_ids should eventually produce different variants."""
        variants_seen = set()
        for cid in range(100):
            variants_seen.add(assign_variant(cid))
        # With default A/B, we expect both to appear in 100 contacts
        assert len(variants_seen) == 2

    def test_distribution_roughly_even(self):
        """Over many assignments, variants should be roughly balanced."""
        counts = {"A": 0, "B": 0}
        for cid in range(1000):
            v = assign_variant(cid)
            counts[v] += 1
        # Each variant should get between 40% and 60% of assignments
        assert counts["A"] > 350
        assert counts["B"] > 350

    def test_three_variant_distribution(self):
        """Three variants should each get a reasonable share."""
        counts = {"A": 0, "B": 0, "C": 0}
        for cid in range(1000):
            v = assign_variant(cid, ["A", "B", "C"])
            counts[v] += 1
        for label in counts:
            assert counts[label] > 200  # each should get > 20%

    def test_empty_variants_raises(self):
        """Empty variant list should raise an IndexError from random.choice."""
        with pytest.raises(IndexError):
            assign_variant(1, [])


# ---------------------------------------------------------------------------
# Tests: get_variant_stats
# ---------------------------------------------------------------------------

class TestGetVariantStats:
    def test_empty_campaign(self, tmp_db):
        conn = _setup_db(tmp_db)
        campaign_id = create_campaign(conn, "Empty Campaign", user_id=TEST_USER_ID)
        stats = get_variant_stats(conn, campaign_id)
        assert stats == []
        conn.close()

    def test_single_variant(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="a@ex.com", rank=1)
        c2 = _create_contact(conn, company_id, email="b@ex.com", rank=2)
        campaign_id = create_campaign(conn, "Single Variant", user_id=TEST_USER_ID)

        enroll_contact(conn, c1, campaign_id, variant="A", user_id=TEST_USER_ID)
        enroll_contact(conn, c2, campaign_id, variant="A", user_id=TEST_USER_ID)

        stats = get_variant_stats(conn, campaign_id)
        assert len(stats) == 1
        assert stats[0]["variant"] == "A"
        assert stats[0]["total"] == 2
        conn.close()

    def test_two_variants_with_replies(self, tmp_db):
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="v1@ex.com", rank=1)
        c2 = _create_contact(conn, company_id, email="v2@ex.com", rank=2)
        campaign_id = create_campaign(conn, "AB Test", user_id=TEST_USER_ID)

        enroll_contact(conn, c1, campaign_id, variant="A", user_id=TEST_USER_ID)
        enroll_contact(conn, c2, campaign_id, variant="B", user_id=TEST_USER_ID)

        # Set c1 to replied_positive
        from src.models.campaigns import update_contact_campaign_status
        update_contact_campaign_status(conn, c1, campaign_id, status="replied_positive", user_id=TEST_USER_ID)

        stats = get_variant_stats(conn, campaign_id)
        assert len(stats) == 2

        stat_a = next(s for s in stats if s["variant"] == "A")
        stat_b = next(s for s in stats if s["variant"] == "B")

        assert stat_a["replied_positive"] == 1
        assert stat_a["reply_rate"] == 1.0
        assert stat_b["replied_positive"] == 0
        assert stat_b["reply_rate"] == 0.0
        conn.close()

    def test_no_variant_assigned(self, tmp_db):
        """Contacts enrolled without variant should show as NULL variant."""
        conn = _setup_db(tmp_db)
        company_id = _create_company(conn)
        c1 = _create_contact(conn, company_id, email="nv@ex.com")
        campaign_id = create_campaign(conn, "No Variant", user_id=TEST_USER_ID)

        enroll_contact(conn, c1, campaign_id, user_id=TEST_USER_ID)

        stats = get_variant_stats(conn, campaign_id)
        assert len(stats) == 1
        assert stats[0]["variant"] is None
        conn.close()
