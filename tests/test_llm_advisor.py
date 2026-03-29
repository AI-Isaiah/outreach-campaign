"""Tests for the LLM advisor service."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.models.campaigns import create_campaign
from src.models.database import get_connection, run_migrations
from tests.conftest import TEST_USER_ID
from src.services.llm_advisor import (
    _build_analysis_prompt,
    _parse_insights,
    get_analysis_history,
    run_analysis,
)


def test_build_analysis_prompt_empty():
    """Should produce a valid prompt even with empty data."""
    prompt = _build_analysis_prompt([], [], [], [])
    assert "Template Performance" in prompt
    assert "No data yet" in prompt
    assert "JSON" in prompt


def test_build_analysis_prompt_with_data():
    """Should include performance data in the prompt."""
    templates = [
        {
            "template_name": "Intro Email",
            "channel": "email",
            "total_sends": 50,
            "positive_rate": 0.12,
            "confidence": "medium",
        }
    ]
    channels = [
        {"channel": "email", "total_sends": 50, "positive_rate": 0.12}
    ]
    segments = [
        {
            "aum_tier": "$1B+",
            "total": 10,
            "contacted": 8,
            "reply_rate": 0.25,
        }
    ]
    prompt = _build_analysis_prompt(templates, channels, segments, [])
    assert "Intro Email" in prompt
    assert "$1B+" in prompt
    assert "12.0%" in prompt


def test_parse_insights_valid_json():
    """Should parse valid JSON response."""
    response = json.dumps({
        "insights": ["Insight 1", "Insight 2"],
        "template_suggestions": ["Try shorter subject lines"],
        "strategy_notes": "Focus on large funds.",
    })
    result = _parse_insights(response)
    assert len(result["insights"]) == 2
    assert result["strategy_notes"] == "Focus on large funds."


def test_parse_insights_invalid_json():
    """Should handle non-JSON response gracefully."""
    result = _parse_insights("This is not JSON")
    assert result["insights"] == ["This is not JSON"]
    assert result["template_suggestions"] == []


@patch("src.services.llm_client.detect_provider", return_value=None)
def test_run_analysis_no_api_key(mock_detect, tmp_db):
    """Should return a useful message when API key is missing."""
    conn = get_connection(tmp_db)
    run_migrations(conn)
    campaign_id = create_campaign(conn, "advisor_test", user_id=TEST_USER_ID)
    conn.commit()

    result = run_analysis(conn, campaign_id, user_id=TEST_USER_ID)
    assert result["run_id"] > 0
    assert "not configured" in result["insights"][0].lower() or len(result["insights"]) > 0

    # Verify stored in advisor_runs
    history = get_analysis_history(conn, campaign_id, user_id=TEST_USER_ID)
    assert len(history) == 1
    assert history[0]["campaign_id"] == campaign_id
    conn.close()


@patch("src.services.llm_client.detect_provider", return_value=("anthropic", "test-key"))
@patch("src.services.llm_client._call_anthropic")
def test_run_analysis_with_mock_llm(mock_call, mock_detect, tmp_db):
    """Should call LLM and store results."""
    mock_response = json.dumps({
        "insights": ["Email works better than LinkedIn", "Large funds respond more"],
        "template_suggestions": ["Try personalized subject lines"],
        "strategy_notes": "Prioritize $1B+ funds and use email channel.",
    })
    mock_call.return_value = mock_response

    conn = get_connection(tmp_db)
    run_migrations(conn)
    campaign_id = create_campaign(conn, "advisor_test_llm", user_id=TEST_USER_ID)
    conn.commit()

    result = run_analysis(conn, campaign_id, user_id=TEST_USER_ID)
    assert result["run_id"] > 0
    assert "Email works better" in result["insights"][0]
    assert len(result["template_suggestions"]) == 1
    assert "Prioritize" in result["strategy_notes"]

    # Check history
    history = get_analysis_history(conn, campaign_id, user_id=TEST_USER_ID)
    assert len(history) == 1
    assert history[0]["insights_parsed"] is not None
    conn.close()
