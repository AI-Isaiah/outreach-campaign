"""LLM-powered campaign advisor service.

Gathers performance data from response_analyzer, builds a prompt for Claude,
and returns structured analysis with insights and recommendations.
"""

from __future__ import annotations

import json
import logging

from src.models.database import get_cursor
from src.services.llm_client import call_llm_safe
from src.services.retry import retry_on_failure
from src.services.response_analyzer import (
    get_channel_performance,
    get_segment_performance,
    get_template_performance,
    get_timing_performance,
)

logger = logging.getLogger(__name__)


def run_analysis(conn, campaign_id: int) -> dict:
    """Run an LLM-powered analysis of campaign performance.

    Gathers data from response_analyzer, builds a prompt, calls Claude,
    and stores the result in advisor_runs.

    Returns:
        dict with keys: run_id, insights, template_suggestions, strategy_notes
    """
    # Gather performance data
    template_perf = get_template_performance(conn, campaign_id)
    channel_perf = get_channel_performance(conn, campaign_id)
    segment_perf = get_segment_performance(conn, campaign_id)
    timing_perf = get_timing_performance(conn, campaign_id)

    # Build the prompt
    prompt = _build_analysis_prompt(
        template_perf, channel_perf, segment_perf, timing_perf
    )

    # Call Claude API
    response_text = _call_llm(prompt)

    # Parse structured response
    insights = _parse_insights(response_text)

    # Store in advisor_runs
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO advisor_runs
                   (campaign_id, run_type, prompt_summary, response_text,
                    insights_json, template_suggestions_json)
               VALUES (%s, 'analysis', %s, %s, %s, %s)
               RETURNING id""",
            (
                campaign_id,
                prompt[:500],
                response_text,
                json.dumps(insights),
                json.dumps(insights.get("template_suggestions", [])),
            ),
        )
        run_id = cur.fetchone()["id"]
        conn.commit()

    return {
        "run_id": run_id,
        "insights": insights.get("insights", []),
        "template_suggestions": insights.get("template_suggestions", []),
        "strategy_notes": insights.get("strategy_notes", ""),
    }


def get_analysis_history(conn, campaign_id: int) -> list[dict]:
    """Fetch past advisor runs for a campaign."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT id, campaign_id, run_type, prompt_summary,
                      response_text, insights_json, template_suggestions_json,
                      events_analyzed, created_at
               FROM advisor_runs
               WHERE campaign_id = %s
               ORDER BY created_at DESC""",
            (campaign_id,),
        )
        rows = cur.fetchall()
    results = []
    for row in rows:
        r = dict(row)
        # JSONB columns are auto-parsed by psycopg2
        if r.get("insights_json") and isinstance(r["insights_json"], str):
            try:
                r["insights_parsed"] = json.loads(r["insights_json"])
            except (json.JSONDecodeError, TypeError):
                r["insights_parsed"] = None
        elif r.get("insights_json"):
            r["insights_parsed"] = r["insights_json"]
        results.append(r)
    return results


def _build_analysis_prompt(
    template_perf: list[dict],
    channel_perf: list[dict],
    segment_perf: list[dict],
    timing_perf: list[dict],
) -> str:
    """Build the analysis prompt from performance data."""
    sections = []

    sections.append(
        "You are an outreach campaign advisor for a crypto fund allocator outreach program. "
        "Analyze the following performance data and provide actionable insights.\n"
    )

    if template_perf:
        sections.append("## Template Performance")
        for t in template_perf:
            sections.append(
                f"- {t['template_name']} ({t['channel']}): "
                f"{t['total_sends']} sends, {t['positive_rate']:.1%} positive rate "
                f"(confidence: {t['confidence']})"
            )
    else:
        sections.append("## Template Performance\nNo data yet.")

    if channel_perf:
        sections.append("\n## Channel Performance")
        for c in channel_perf:
            sections.append(
                f"- {c['channel']}: {c['total_sends']} sends, "
                f"{c['positive_rate']:.1%} positive rate"
            )
    else:
        sections.append("\n## Channel Performance\nNo data yet.")

    if segment_perf:
        sections.append("\n## AUM Segment Performance")
        for s in segment_perf:
            sections.append(
                f"- {s['aum_tier']}: {s['total']} contacts, "
                f"{s['contacted']} contacted, {s['reply_rate']:.1%} reply rate"
            )
    else:
        sections.append("\n## AUM Segment Performance\nNo data yet.")

    if timing_perf:
        sections.append("\n## Timing Performance")
        for t in timing_perf:
            sections.append(
                f"- {t['delay_bucket']}: {t['total']} contacts, "
                f"{t['reply_rate']:.1%} reply rate"
            )
    else:
        sections.append("\n## Timing Performance\nNo data yet.")

    sections.append(
        "\n\nProvide your analysis as JSON with these keys:\n"
        '- "insights": list of 3-5 key observations (strings)\n'
        '- "template_suggestions": list of specific template improvement ideas (strings)\n'
        '- "strategy_notes": a paragraph summarizing recommended next steps\n'
        "\nRespond with valid JSON only."
    )

    return "\n".join(sections)


def _call_llm(prompt: str) -> str:
    """Call LLM via shared client. Returns raw text or JSON fallback on error."""
    from src.services.llm_client import detect_provider
    if not detect_provider():
        return json.dumps({
            "insights": ["No LLM API key configured — unable to run analysis."],
            "template_suggestions": [],
            "strategy_notes": "Configure ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY in .env.",
        })

    api_error_fallback = json.dumps({
        "insights": ["LLM API call failed — check logs for details."],
        "template_suggestions": [],
        "strategy_notes": "Retry or check API key configuration.",
    })
    text, provider = call_llm_safe(prompt, max_tokens=1000, timeout=60.0, fallback=api_error_fallback)
    if provider is None:
        return api_error_fallback
    return text


def _parse_insights(response_text: str) -> dict:
    """Parse the LLM response into structured insights."""
    try:
        return json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        return {
            "insights": [response_text[:500] if response_text else "No response"],
            "template_suggestions": [],
            "strategy_notes": "",
        }
