"""Edge case tests for compute_health_score in src/services/metrics.py."""

import pytest

from src.services.metrics import compute_health_score


# ---------------------------------------------------------------------------
# Tests: compute_health_score
# ---------------------------------------------------------------------------

class TestComputeHealthScore:
    def test_zero_enrolled_returns_none(self):
        """With 0 enrolled contacts, health score is undefined (None)."""
        metrics = {"total_enrolled": 0, "by_status": {}, "emails_sent": 0}
        assert compute_health_score(metrics) is None

    def test_empty_metrics_returns_none(self):
        """Completely empty dict defaults to 0 enrolled, returns None."""
        assert compute_health_score({}) is None

    def test_all_positive_replies_high_score(self):
        """100% positive reply rate with full send velocity."""
        metrics = {
            "total_enrolled": 10,
            "by_status": {
                "replied_positive": 10,
                "replied_negative": 0,
                "bounced": 0,
                "queued": 0,
                "in_progress": 0,
                "no_response": 0,
            },
            "emails_sent": 10,
        }
        score = compute_health_score(metrics)
        assert score is not None
        # positive_reply_rate = 10/10 = 1.0, score contribution = 50
        # send_velocity = 10/10 = 1.0, score contribution = 30
        # bounce_rate = 0, penalty = 0
        # total = 80
        assert score == 80

    def test_100_percent_bounce_rate(self):
        """All emails bounced should heavily penalize."""
        metrics = {
            "total_enrolled": 10,
            "by_status": {
                "replied_positive": 0,
                "replied_negative": 0,
                "bounced": 10,
                "queued": 0,
                "in_progress": 0,
                "no_response": 0,
            },
            "emails_sent": 10,
        }
        score = compute_health_score(metrics)
        assert score is not None
        # positive_reply_rate = 0, contribution = 0
        # send_velocity = 10/10 = 1.0, contribution = 30
        # bounce_rate = 10/10 = 1.0, penalty = 20
        # total = 10
        assert score == 10

    def test_negative_score_clamped_to_zero(self):
        """If the formula produces a negative value, it should be clamped to 0."""
        metrics = {
            "total_enrolled": 1,
            "by_status": {
                "replied_positive": 0,
                "replied_negative": 0,
                "bounced": 100,  # artificially high bounce count
                "queued": 0,
                "in_progress": 0,
                "no_response": 0,
            },
            "emails_sent": 1,
        }
        # bounce_rate = 100/1 = 100 (impossible in reality, but tests clamping)
        # penalty = 100 * 20 = 2000
        # send_velocity = 1/1 = 1.0, contribution = 30
        # total = 0 + 30 - 2000 = -1970, clamped to 0
        score = compute_health_score(metrics)
        assert score == 0

    def test_score_clamped_to_100(self):
        """If the formula would exceed 100, it should be clamped to 100."""
        metrics = {
            "total_enrolled": 1,
            "by_status": {
                "replied_positive": 1,
                "replied_negative": 0,
                "bounced": 0,
                "queued": 0,
                "in_progress": 0,
                "no_response": 0,
            },
            "emails_sent": 100,  # extremely high send velocity
        }
        # positive_reply_rate = 1.0, contribution = 50
        # send_velocity = 100/1 = 100, contribution = 3000
        # bounce_rate = 0, penalty = 0
        # total = 3050, clamped to 100
        score = compute_health_score(metrics)
        assert score == 100

    def test_typical_values(self):
        """Realistic campaign metrics produce a reasonable score."""
        metrics = {
            "total_enrolled": 50,
            "by_status": {
                "replied_positive": 5,
                "replied_negative": 2,
                "bounced": 3,
                "queued": 10,
                "in_progress": 10,
                "no_response": 20,
            },
            "emails_sent": 40,
        }
        score = compute_health_score(metrics)
        assert score is not None
        assert 0 <= score <= 100
        # positive_reply_rate = 5/50 = 0.1, contribution = 5
        # send_velocity = 40/50 = 0.8, contribution = 24
        # bounce_rate = 3/40 = 0.075, penalty = 1.5
        # total = 5 + 24 - 1.5 = 27.5, rounded = 28
        assert score == 28

    def test_no_emails_sent(self):
        """No emails sent means bounce_rate is 0 (avoids division by zero)."""
        metrics = {
            "total_enrolled": 5,
            "by_status": {
                "replied_positive": 0,
                "replied_negative": 0,
                "bounced": 0,
                "queued": 5,
                "in_progress": 0,
                "no_response": 0,
            },
            "emails_sent": 0,
        }
        score = compute_health_score(metrics)
        assert score is not None
        # positive_reply_rate = 0, contribution = 0
        # send_velocity = 0/5 = 0, contribution = 0
        # bounce_rate = 0 (emails_sent == 0 branch), penalty = 0
        # total = 0
        assert score == 0

    def test_missing_by_status_keys(self):
        """Missing keys in by_status default to 0."""
        metrics = {
            "total_enrolled": 10,
            "by_status": {},
            "emails_sent": 5,
        }
        score = compute_health_score(metrics)
        assert score is not None
        # positive_reply_rate = 0/10 = 0, contribution = 0
        # send_velocity = 5/10 = 0.5, contribution = 15
        # bounce_rate = 0/5 = 0, penalty = 0
        # total = 15
        assert score == 15

    def test_only_bounces_no_positive_replies(self):
        """Only bounces, no positive replies."""
        metrics = {
            "total_enrolled": 10,
            "by_status": {
                "replied_positive": 0,
                "bounced": 5,
            },
            "emails_sent": 10,
        }
        score = compute_health_score(metrics)
        # positive = 0, velocity = 10/10 = 1.0, bounce = 5/10 = 0.5
        # score = 0 + 30 - 10 = 20
        assert score == 20

    def test_score_is_integer(self):
        """Health score must always be an integer."""
        metrics = {
            "total_enrolled": 3,
            "by_status": {"replied_positive": 1, "bounced": 0},
            "emails_sent": 2,
        }
        score = compute_health_score(metrics)
        assert isinstance(score, int)
