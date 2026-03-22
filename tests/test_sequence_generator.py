"""Tests for the sequence generator service."""

import pytest

from src.services.sequence_generator import generate_sequence


class TestGenerateSequence:
    """Tests for generate_sequence()."""

    def test_email_only_3_steps(self):
        steps = generate_sequence(3, ["email"])
        assert len(steps) == 3
        assert steps[0]["delay_days"] == 0
        assert all(s["channel"] == "email" for s in steps)
        # Increasing delays
        for i in range(1, len(steps)):
            assert steps[i]["delay_days"] > steps[i - 1]["delay_days"]

    def test_email_linkedin_5_steps(self):
        steps = generate_sequence(5, ["email", "linkedin"])
        assert len(steps) == 5
        assert steps[0]["channel"] == "email"
        assert steps[0]["delay_days"] == 0
        # Should alternate
        channels = [s["channel"] for s in steps]
        assert channels[0] == "email"
        assert channels[1].startswith("linkedin")
        assert channels[2] == "email"

    def test_email_linkedin_3_steps(self):
        steps = generate_sequence(3, ["email", "linkedin"])
        assert len(steps) == 3
        assert steps[0]["channel"] == "email"
        assert steps[1]["channel"].startswith("linkedin")

    def test_email_linkedin_7_steps(self):
        steps = generate_sequence(7, ["email", "linkedin"])
        assert len(steps) == 7
        for i in range(1, len(steps)):
            assert steps[i]["delay_days"] > steps[i - 1]["delay_days"]

    def test_linkedin_only(self):
        steps = generate_sequence(3, ["linkedin"])
        assert len(steps) == 3
        assert steps[0]["channel"] == "linkedin_connect"
        assert steps[1]["channel"] == "linkedin_message"
        assert steps[2]["channel"] == "linkedin_connect"

    def test_linkedin_connect_first_then_message(self):
        steps = generate_sequence(5, ["email", "linkedin"])
        linkedin_steps = [s for s in steps if s["channel"].startswith("linkedin")]
        assert linkedin_steps[0]["channel"] == "linkedin_connect"
        if len(linkedin_steps) > 1:
            assert linkedin_steps[1]["channel"] == "linkedin_message"

    def test_minimum_gap_same_channel(self):
        steps = generate_sequence(5, ["email"])
        for i in range(1, len(steps)):
            gap = steps[i]["delay_days"] - steps[i - 1]["delay_days"]
            assert gap >= 3

    def test_minimum_gap_cross_channel(self):
        steps = generate_sequence(5, ["email", "linkedin"])
        for i in range(1, len(steps)):
            gap = steps[i]["delay_days"] - steps[i - 1]["delay_days"]
            assert gap >= 2

    def test_step_order_sequential(self):
        steps = generate_sequence(5, ["email", "linkedin"])
        for i, s in enumerate(steps):
            assert s["step_order"] == i + 1

    def test_template_id_is_none(self):
        steps = generate_sequence(3, ["email"])
        assert all(s["template_id"] is None for s in steps)

    def test_single_step(self):
        steps = generate_sequence(1, ["email"])
        assert len(steps) == 1
        assert steps[0]["delay_days"] == 0
        assert steps[0]["channel"] == "email"

    def test_invalid_touchpoints_zero(self):
        with pytest.raises(ValueError, match="touchpoints must be >= 1"):
            generate_sequence(0, ["email"])

    def test_invalid_empty_channels(self):
        with pytest.raises(ValueError, match="channels must not be empty"):
            generate_sequence(3, [])

    def test_invalid_channel_name(self):
        with pytest.raises(ValueError, match="Invalid channel"):
            generate_sequence(3, ["whatsapp"])
