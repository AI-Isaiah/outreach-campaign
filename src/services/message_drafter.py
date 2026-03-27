"""On-demand AI message draft generation using Claude Haiku.

Generates personalized outreach messages by synthesizing deep research data
with template structure and contact context. Channel-aware: different prompts
and length constraints for email, LinkedIn connect, and LinkedIn message.
"""

import json
import logging
import os
import re

from datetime import datetime, timezone

import httpx

from src.enums import Channel
from src.models.database import get_cursor

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
HAIKU_TIMEOUT = 8  # seconds
SEQUENCE_TIMEOUT = 30  # seconds — longer for multi-step generation

# Channel → prompt type mapping (niche LinkedIn types fall back to message)
CHANNEL_PROMPT_MAP = {
    Channel.EMAIL: "email",
    Channel.LINKEDIN_CONNECT: "linkedin_connect",
    Channel.LINKEDIN_MESSAGE: "linkedin_message",
    Channel.LINKEDIN_ENGAGE: "linkedin_message",
    Channel.LINKEDIN_INSIGHT: "linkedin_message",
    Channel.LINKEDIN_FINAL: "linkedin_message",
}

CHANNEL_DISPLAY_NAMES = {
    Channel.EMAIL: "email",
    Channel.LINKEDIN_CONNECT: "LinkedIn connection note",
    Channel.LINKEDIN_MESSAGE: "LinkedIn direct message",
}

# ── System prompts per channel ────────────────────────────────────────────

SYSTEM_EMAIL = """\
You are a B2B outreach specialist writing personalized emails to crypto fund allocators.

Rules:
- Lead with a SPECIFIC insight from the research — a talking point, deal, crypto signal, or key person
- Reference concrete details (names, numbers, events) — never generic platitudes
- Match the template's tone and structure
- Keep body under 200 words
- Write naturally — conversational but professional
- Do NOT include greetings like "Dear" or sign-offs — the system adds those
- Do NOT include unsubscribe links — added automatically

Output format:
SUBJECT: <subject line>
BODY: <email body>"""

SYSTEM_LINKEDIN_CONNECT = """\
You are a B2B outreach specialist writing LinkedIn connection request notes.

Rules:
- MUST be under 280 characters (leave margin for platform limits)
- One specific reference to the person or their company from the research
- One short value proposition
- No formal language — casual and direct
- Do NOT start with "Hi {name}" — LinkedIn shows the name already

Output format:
NOTE: <connection note text>"""

SYSTEM_LINKEDIN_MESSAGE = """\
You are a B2B outreach specialist writing LinkedIn direct messages.

Rules:
- Conversational — this is a DM, not an email
- Lead with a specific insight about their company or recent activity
- Keep under 400 words
- No formal greetings — start with the hook

Output format:
MESSAGE: <message text>"""

SYSTEM_PROMPTS = {
    Channel.EMAIL: SYSTEM_EMAIL,
    Channel.LINKEDIN_CONNECT: SYSTEM_LINKEDIN_CONNECT,
    Channel.LINKEDIN_MESSAGE: SYSTEM_LINKEDIN_MESSAGE,
}


# ── Core generation ───────────────────────────────────────────────────────

def generate_draft(
    conn,
    contact_id: int,
    campaign_id: int,
    step_order: int,
    *,
    user_id: int,
) -> dict:
    """Generate an AI-personalized message draft using research + template.

    Returns dict with keys: draft_subject, draft_text, model, channel,
    research_id, generated_at.
    Raises on API failure — caller must handle.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    # 1. Fetch contact + company
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.id, c.first_name, c.last_name, c.full_name, c.title,
                      c.email, c.linkedin_url, c.company_id,
                      co.name AS company_name
               FROM contacts c
               LEFT JOIN companies co ON co.id = c.company_id
               WHERE c.id = %s AND c.user_id = %s""",
            (contact_id, user_id),
        )
        contact = cur.fetchone()
    if not contact:
        raise ValueError(f"Contact {contact_id} not found for user {user_id}")

    # 2. Fetch deep_research (latest completed, user_id scoped)
    research = None
    research_id = None
    if contact["company_id"]:
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT id, company_overview, crypto_signals, key_people,
                          talking_points, risk_factors, updated_crypto_score, confidence
                   FROM deep_research
                   WHERE company_id = %s AND status = 'completed' AND user_id = %s
                   ORDER BY created_at DESC LIMIT 1""",
                (contact["company_id"], user_id),
            )
            research = cur.fetchone()
            if research:
                research_id = research["id"]

    # 3. Fetch sequence step → channel, template_id, draft_mode + channel_override
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT ss.channel, ss.template_id, ss.draft_mode,
                      ccs.channel_override
               FROM sequence_steps ss
               JOIN contact_campaign_status ccs
                    ON ccs.campaign_id = ss.campaign_id
                   AND ccs.contact_id = %s
               WHERE ss.campaign_id = %s AND ss.step_order = %s""",
            (contact_id, campaign_id, step_order),
        )
        step = cur.fetchone()
    if not step:
        raise ValueError(f"Step {step_order} not found for campaign {campaign_id}")

    # Use channel_override if set (e.g. cross-campaign email dedup → linkedin_only)
    effective_channel = step["channel_override"] or step["channel"]
    prompt_type = CHANNEL_PROMPT_MAP.get(effective_channel, "linkedin_message")

    # 4. Fetch template (reference template for tone/structure)
    template_body = ""
    template_subject = ""
    if step["template_id"]:
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT name, subject, body_template FROM templates WHERE id = %s AND user_id = %s",
                (step["template_id"], user_id),
            )
            tpl = cur.fetchone()
            if tpl:
                template_body = tpl.get("body_template") or ""
                template_subject = tpl.get("subject") or ""

    # 5. Build user message
    user_message = _build_user_message(contact, research, template_subject, template_body, prompt_type)

    # 6. Call Claude Haiku
    logger.info("Generating draft: contact=%d campaign=%d step=%d channel=%s",
                contact_id, campaign_id, step_order, effective_channel)
    logger.info("Research %s for company_id=%s",
                "found" if research else "not available",
                contact.get("company_id"))

    import time as _time
    _t0 = _time.monotonic()
    system_prompt = SYSTEM_PROMPTS[prompt_type]
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": HAIKU_MODEL,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=HAIKU_TIMEOUT,
    )
    resp.raise_for_status()
    raw_text = resp.json()["content"][0]["text"]
    _elapsed = _time.monotonic() - _t0
    logger.info("Haiku response: %d chars, %.1fs", len(raw_text), _elapsed)

    # 7. Parse response
    draft_subject, draft_text = _parse_response(raw_text, prompt_type)

    # 8. Enforce channel constraints
    draft_text = _enforce_constraints(draft_text, effective_channel)

    # 8b. Validate draft is non-empty
    if not draft_text or len(draft_text.strip()) < 20:
        raise ValueError("AI generated empty or too-short draft — using template fallback")

    # 9. UPSERT into message_drafts
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO message_drafts
                   (contact_id, campaign_id, step_order, draft_subject, draft_text,
                    channel, model, research_id, user_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (contact_id, campaign_id, step_order)
               DO UPDATE SET draft_subject = EXCLUDED.draft_subject,
                             draft_text = EXCLUDED.draft_text,
                             channel = EXCLUDED.channel,
                             model = EXCLUDED.model,
                             research_id = EXCLUDED.research_id,
                             generated_at = NOW(),
                             edited_at = NULL""",
            (contact_id, campaign_id, step_order, draft_subject, draft_text,
             effective_channel, HAIKU_MODEL, research_id, user_id),
        )
        conn.commit()

    # 10. Return draft dict
    return {
        "draft_subject": draft_subject,
        "draft_text": draft_text,
        "model": HAIKU_MODEL,
        "channel": effective_channel,
        "research_id": research_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Sequence-level generation ─────────────────────────────────────────────

def _load_outreach_skill() -> str:
    """Load the outreach skill prompt from outside-skills/ if available.

    Falls back to a basic prompt if the files don't exist.
    """
    import pathlib
    base = pathlib.Path(__file__).resolve().parent.parent.parent / "outside-skills"
    parts = []
    for name in ("Outreach_GS_SKILL.md", "GS_outreach_example-metaworld.md"):
        path = base / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    if parts:
        return "\n\n".join(parts)
    return ""


def _build_sequence_system() -> str:
    """Build the system prompt for sequence generation.

    Uses the outreach skill files if available, with JSON output instructions appended.
    """
    skill_content = _load_outreach_skill()
    if skill_content:
        return (
            skill_content
            + "\n\n## CRITICAL OUTPUT FORMAT\n\n"
            "Output MUST be valid JSON: an array of objects, one per step, with keys:\n"
            "  step_order (int), channel (string), subject (string or null), body (string)\n\n"
            "For email steps, include a subject line. For LinkedIn steps, subject should be null.\n"
            "Use Jinja2 variables: {{ first_name }}, {{ company_name }}, {{ title }}.\n"
            "Do NOT wrap the JSON in markdown code fences. Return the raw JSON array only."
        )
    # Fallback: basic prompt if skill files not found
    return (
        "You are a B2B outreach specialist designing a multi-touch outreach sequence "
        "targeting crypto fund allocators.\n\n"
        "Channel best practices:\n"
        "- linkedin_connect: Short, personal, under 280 chars. One reference + one value prop.\n"
        "- linkedin_message: DM tone, specific insight hook, under 400 words.\n"
        "- email: Lead with a specific insight, under 200 words, conversational.\n\n"
        "Sequence design rules:\n"
        "- Each step builds on previous ones — no repeating the same pitch.\n"
        "- Early steps establish credibility, later steps add urgency or new value.\n"
        "- Narrative arc: introduce → add value → create urgency → final ask.\n\n"
        "Output MUST be valid JSON: an array of objects, one per step, with keys:\n"
        "  step_order (int), channel (string), subject (string or null), body (string)\n\n"
        "For email steps, include a subject line. For LinkedIn steps, subject should be null.\n"
        "Use Jinja2 variables: {{ first_name }}, {{ company_name }}, {{ title }}."
    )


SYSTEM_SEQUENCE = _build_sequence_system()

def _build_improve_system() -> str:
    """Build the system prompt for message improvement.

    Uses outreach skill voice guidelines if available.
    """
    skill = _load_outreach_skill()
    base_rules = (
        "You are improving a single outreach message for crypto fund allocator outreach.\n\n"
        "Rules:\n"
        "- Apply the requested improvement while preserving the overall message intent.\n"
        "- Maintain channel-appropriate length (email <200 words, LinkedIn connect <280 chars, LinkedIn message <400 words).\n"
        "- Do NOT add greetings, sign-offs, or unsubscribe links.\n\n"
        "Output the improved message only — no explanations or labels."
    )
    if skill:
        # Prepend voice guidelines, append the technical rules
        return skill + "\n\n## IMPROVEMENT TASK\n\n" + base_rules
    return base_rules


SYSTEM_IMPROVE = _build_improve_system()


ALLOWED_MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-20250514",
    "opus": "claude-opus-4-20250514",
}


def generate_sequence_messages(
    *,
    steps: list[dict],
    product_description: str,
    target_audience: str = "crypto fund allocators",
    model: str = "haiku",
    user_id: int,
) -> list[dict]:
    """Generate messages for all steps in a campaign sequence.

    Returns list of {step_order, channel, subject, body} dicts.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    steps_desc = "\n".join(
        f"- Step {s['step_order']}: {s['channel']} (day {s.get('delay_days', 0)})"
        for s in steps
    )

    user_message = (
        f"PRODUCT/FUND THESIS:\n{product_description}\n\n"
        f"TARGET AUDIENCE: {target_audience}\n\n"
        f"SEQUENCE STEPS:\n{steps_desc}\n\n"
        "Generate a complete outreach sequence with a message for each step. "
        "Return valid JSON only."
    )

    logger.info("Generating sequence messages: %d steps, user=%d", len(steps), user_id)

    import time as _time
    _t0 = _time.monotonic()
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ALLOWED_MODELS.get(model, HAIKU_MODEL),
            "max_tokens": 8192,
            "system": SYSTEM_SEQUENCE,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=SEQUENCE_TIMEOUT,
    )
    resp.raise_for_status()
    raw_text = resp.json()["content"][0]["text"]
    _elapsed = _time.monotonic() - _t0
    logger.info("Sequence generation: %d chars, %.1fs", len(raw_text), _elapsed)

    messages = _parse_sequence_response(raw_text, steps)

    for msg in messages:
        channel = msg["channel"]
        if msg.get("body"):
            msg["body"] = _enforce_constraints(msg["body"], channel)

    return messages


def improve_message(
    *,
    channel: str,
    body: str,
    subject: str | None = None,
    instruction: str,
    user_id: int,
) -> dict:
    """Improve an existing message based on user instruction.

    Returns {subject, body} dict.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    prompt_type = CHANNEL_PROMPT_MAP.get(channel, "linkedin_message")
    channel_label = CHANNEL_DISPLAY_NAMES.get(prompt_type, "message")

    parts = [f"CHANNEL: {channel_label}"]
    if subject:
        parts.append(f"CURRENT SUBJECT: {subject}")
    parts.append(f"CURRENT MESSAGE:\n{body}")
    parts.append(f"IMPROVEMENT REQUEST: {instruction}")

    if prompt_type == "email":
        parts.append(
            "Output the improved message in this format:\n"
            "SUBJECT: <subject line>\nBODY: <message body>"
        )
    else:
        parts.append("Output the improved message text only.")

    user_message = "\n\n".join(parts)

    logger.info("Improving message: channel=%s, user=%d", channel, user_id)

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": HAIKU_MODEL,
            "max_tokens": 1024,
            "system": SYSTEM_IMPROVE,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=HAIKU_TIMEOUT,
    )
    resp.raise_for_status()
    raw_text = resp.json()["content"][0]["text"]

    improved_subject, improved_body = _parse_response(raw_text, prompt_type)
    improved_body = _enforce_constraints(improved_body, channel)

    return {
        "subject": improved_subject if prompt_type == "email" else subject,
        "body": improved_body,
    }


def _parse_sequence_response(raw_text: str, steps: list[dict]) -> list[dict]:
    """Parse the JSON array response from sequence generation."""
    text = raw_text.strip()
    json_match = re.search(r"\[.*\]", text, re.DOTALL)
    if json_match:
        text = json_match.group(0)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse sequence JSON: %s\nRaw: %s", exc, text[:500])
        raise RuntimeError("AI returned invalid response — try again") from exc

    if not isinstance(parsed, list):
        parsed = [parsed]

    step_map = {s["step_order"]: s["channel"] for s in steps}
    messages = []
    for item in parsed:
        step_order = item.get("step_order")
        if step_order not in step_map:
            continue
        messages.append({
            "step_order": step_order,
            "channel": step_map[step_order],
            "subject": item.get("subject"),
            "body": item.get("body", ""),
        })

    return messages


# ── Helpers ───────────────────────────────────────────────────────────────

def _build_user_message(
    contact: dict,
    research: dict | None,
    template_subject: str,
    template_body: str,
    prompt_type: str,
) -> str:
    """Build the user message for the Haiku prompt."""
    first = contact.get("first_name") or ""
    last = contact.get("last_name") or ""
    name = contact.get("full_name") or f"{first} {last}".strip()
    title = contact.get("title") or "Unknown"
    company = contact.get("company_name") or "Unknown"

    parts = [f"CONTACT:\nName: {name}\nTitle: {title}\nCompany: {company}"]

    if research:
        parts.append("RESEARCH BRIEF:")
        overview = research.get("company_overview") or ""
        if overview:
            parts.append(overview[:2000])

        talking_points = research.get("talking_points")
        if talking_points and isinstance(talking_points, list):
            tp_lines = "\n".join(
                f"- {tp.get('text', str(tp))}" for tp in talking_points[:6]
            )
            parts.append(f"Talking Points:\n{tp_lines}")
        else:
            parts.append("Talking Points: No research available")

        crypto_signals = research.get("crypto_signals")
        if crypto_signals and isinstance(crypto_signals, list):
            cs_lines = "\n".join(
                f"- [{cs.get('relevance', 'medium')}] {cs.get('quote', str(cs))}"
                for cs in crypto_signals[:5]
            )
            parts.append(f"Crypto Signals:\n{cs_lines}")
        else:
            parts.append("Crypto Signals: None detected")

        key_people = research.get("key_people")
        if key_people and isinstance(key_people, list):
            kp_lines = "\n".join(
                f"- {kp.get('name', 'Unknown')}, {kp.get('title', '')}: {kp.get('context', '')}"
                for kp in key_people[:5]
            )
            parts.append(f"Key People:\n{kp_lines}")
        else:
            parts.append("Key People: Not available")
    else:
        parts.append(
            "No research available — personalize using only the contact's "
            "name, title, and company."
        )

    if template_subject or template_body:
        tpl_section = "TEMPLATE (use as structure/tone reference):"
        if template_subject:
            tpl_section += f"\nSubject: {template_subject}"
        if template_body:
            tpl_section += f"\nBody: {template_body[:1000]}"
        parts.append(tpl_section)

    channel_label = CHANNEL_DISPLAY_NAMES.get(prompt_type, "message")
    parts.append(f"Generate a personalized {channel_label} for this contact.")

    return "\n\n".join(parts)


def _parse_response(raw_text: str, prompt_type: str) -> tuple[str | None, str]:
    """Parse LLM response into (subject, body) based on channel prompt type."""
    text = raw_text.strip()

    if prompt_type == "email":
        subject_match = re.search(r"SUBJECT:\s*(.+?)(?:\n|$)", text)
        body_match = re.search(r"BODY:\s*(.+)", text, re.DOTALL)
        subject = subject_match.group(1).strip() if subject_match else None
        body = body_match.group(1).strip() if body_match else text
        return subject, body

    if prompt_type == "linkedin_connect":
        note_match = re.search(r"NOTE:\s*(.+)", text, re.DOTALL)
        body = note_match.group(1).strip() if note_match else text
        return None, body

    # linkedin_message
    msg_match = re.search(r"MESSAGE:\s*(.+)", text, re.DOTALL)
    body = msg_match.group(1).strip() if msg_match else text
    return None, body


def _enforce_constraints(draft_text: str, channel: str) -> str:
    """Enforce channel-specific length constraints."""
    if channel == "linkedin_connect" and len(draft_text) > 300:
        # Truncate at sentence boundary
        truncated = draft_text[:300]
        for sep in [". ", "? ", "! "]:
            last = truncated.rfind(sep)
            if last > 100:
                return truncated[: last + 1]
        # Fall back to last space
        last_space = truncated.rfind(" ")
        if last_space > 100:
            return truncated[:last_space]
        return truncated

    if channel.startswith("linkedin") and len(draft_text) > 8000:
        # Truncate at paragraph boundary
        truncated = draft_text[:8000]
        last_para = truncated.rfind("\n\n")
        if last_para > 4000:
            return truncated[:last_para]
        last_nl = truncated.rfind("\n")
        if last_nl > 4000:
            return truncated[:last_nl]
        return truncated

    if len(draft_text.split()) > 500:
        logger.warning("Email draft exceeds 500 words (%d)", len(draft_text.split()))

    return draft_text
