"""Queue application service — enriches raw queue items with rendered content.

Extracted from routes/queue.py to keep the route layer thin.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from src.config import load_config
from src.models.campaigns import get_campaign_by_name
from src.models.templates import get_template
from src.services.adaptive_queue import get_adaptive_queue
from src.services.contact_scorer import aum_to_tier
from src.services.compliance import build_unsubscribe_url
from src.services.email_sender import render_campaign_email, _render_inline_template
from src.services.priority_queue import get_daily_queue
from src.services.template_engine import render_template
from src.models.database import get_cursor


def get_enriched_queue(
    conn,
    campaign: str,
    *,
    date: Optional[str] = None,
    limit: int = 20,
    mode: str = "adaptive",
    firm_type: Optional[str] = None,
    aum_min: Optional[float] = None,
    aum_max: Optional[float] = None,
    diverse: bool = True,
    user_id: Optional[str] = None,
) -> dict:
    """Build the fully enriched queue response for a campaign.

    Fetches queue items, applies filters, batch-fetches related data,
    and renders email/LinkedIn messages for display.

    Raises:
        ValueError: if the campaign is not found.
    """
    camp = get_campaign_by_name(conn, campaign, user_id=user_id)
    if not camp:
        raise ValueError(f"Campaign '{campaign}' not found")

    campaign_id = camp["id"]

    # Auto-disable diversity when AUM filters are active
    use_diverse = diverse and aum_min is None and aum_max is None

    if mode == "adaptive":
        try:
            items = get_adaptive_queue(
                conn, campaign_id, target_date=date, limit=limit * 3, diverse=use_diverse,
            )
        except (KeyError, ValueError, TypeError):
            items = get_daily_queue(conn, campaign_id, target_date=date, limit=limit * 3)
    else:
        items = get_daily_queue(conn, campaign_id, target_date=date, limit=limit * 3)

    # AUM range filters
    if aum_min is not None:
        items = [i for i in items if (i.get("aum_millions") or 0) >= aum_min]
    if aum_max is not None:
        items = [i for i in items if (i.get("aum_millions") or 0) <= aum_max]

    firm_type_counts = dict(Counter(
        i.get("firm_type") or "Unknown" for i in items
    ))

    if firm_type:
        items = [i for i in items if (i.get("firm_type") or "Unknown") == firm_type]

    items = items[:limit]

    try:
        config = load_config()
    except FileNotFoundError:
        config = {}

    enriched = _batch_enrich(conn, items, campaign_id, config, user_id=user_id)

    return {
        "campaign": campaign,
        "campaign_id": campaign_id,
        "date": date,
        "items": enriched,
        "total": len(enriched),
        "firm_type_counts": firm_type_counts,
    }


def apply_cross_campaign_email_dedup(items: list[dict], limit: int = 0) -> list[dict]:
    """Deduplicate email actions across campaigns in a merged queue.

    If the same contact_id appears with channel='email' more than once,
    all but the first occurrence get channel overridden to 'linkedin_only'.
    Items must be pre-sorted (by step_order then contact_name).

    When limit > 0, returns at most that many items (combining dedup + limit
    in one pass so the dedup window matches the output window).
    """
    seen: set[int] = set()
    result = []
    for item in items:
        if item.get("channel") == "email":
            cid = item["contact_id"]
            if cid in seen:
                item["channel"] = "linkedin_only"
                item["email_dedup_override"] = True
            else:
                seen.add(cid)
        result.append(item)
        if limit and len(result) >= limit:
            break
    return result


def _batch_enrich(conn, items: list[dict], campaign_id: int, config: dict, *, user_id: Optional[str] = None) -> list[dict]:
    """Batch-fetch related data and render messages for queue items."""
    if not items:
        return []

    contact_ids = [item["contact_id"] for item in items]
    template_ids = list({item["template_id"] for item in items if item.get("template_id")})

    # Batch fetch Gmail drafts
    gmail_drafts_by_contact: dict = {}
    if contact_ids:
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT contact_id, gmail_draft_id, status FROM gmail_drafts
                   WHERE contact_id = ANY(%s) AND campaign_id = %s
                   ORDER BY contact_id, id DESC""",
                (contact_ids, campaign_id),
            )
            for row in cur.fetchall():
                cid = row["contact_id"]
                if cid not in gmail_drafts_by_contact:
                    gmail_drafts_by_contact[cid] = row

    # Batch fetch contact data
    contacts_by_id: dict = {}
    if contact_ids:
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT c.id, c.company_id, c.linkedin_url, c.first_name,
                          c.last_name, c.full_name, co.name AS company_name
                   FROM contacts c
                   LEFT JOIN companies co ON co.id = c.company_id
                   WHERE c.id = ANY(%s)""",
                (contact_ids,),
            )
            for row in cur.fetchall():
                contacts_by_id[row["id"]] = row

    # Batch fetch templates
    templates_by_id: dict = {}
    if template_ids:
        with get_cursor(conn) as cur:
            cur.execute("SELECT * FROM templates WHERE id = ANY(%s)", (template_ids,))
            for row in cur.fetchall():
                templates_by_id[row["id"]] = row

    # Batch fetch message_drafts (AI-generated)
    message_drafts_by_key: dict = {}
    if contact_ids:
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT contact_id, step_order, draft_subject, draft_text,
                          channel, model, generated_at, research_id
                   FROM message_drafts
                   WHERE contact_id = ANY(%s) AND campaign_id = %s AND user_id = %s""",
                (contact_ids, campaign_id, user_id),
            )
            for row in cur.fetchall():
                message_drafts_by_key[(row["contact_id"], row["step_order"])] = dict(row)

    # Batch fetch deep research (latest per company, user_id scoped)
    # Serves dual purpose: has_research flag + pre-fetched data for render optimization
    company_ids = list({
        c["company_id"] for c in contacts_by_id.values()
        if c.get("company_id")
    })
    research_by_company: dict = {}
    companies_with_research: set = set()
    if company_ids:
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT DISTINCT ON (company_id)
                          company_id, company_overview, crypto_signals,
                          key_people, talking_points, risk_factors,
                          updated_crypto_score, confidence
                   FROM deep_research
                   WHERE company_id = ANY(%s) AND status = 'completed'
                         AND user_id = %s
                   ORDER BY company_id, created_at DESC""",
                (company_ids, user_id),
            )
            for row in cur.fetchall():
                research_by_company[row["company_id"]] = dict(row)
                companies_with_research.add(row["company_id"])

    # Fetch draft_mode from sequence steps
    step_draft_modes: dict = {}
    if contact_ids:
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT step_order, draft_mode FROM sequence_steps WHERE campaign_id = %s",
                (campaign_id,),
            )
            for row in cur.fetchall():
                step_draft_modes[row["step_order"]] = row.get("draft_mode") or "template"

    # Shared template context
    smtp_config = config.get("smtp", {})
    from_email = config.get("from_email") or smtp_config.get("username", "")
    unsubscribe_url = build_unsubscribe_url(from_email)
    shared_ctx = {
        "calendly_url": config.get("calendly_url", ""),
        "unsubscribe_url": unsubscribe_url,
        "physical_address": config.get("physical_address", ""),
    }

    def _build_context(contact_row: dict) -> dict:
        first = contact_row.get("first_name") or ""
        last = contact_row.get("last_name") or ""
        return {
            "first_name": first,
            "last_name": last,
            "full_name": contact_row.get("full_name") or f"{first} {last}".strip(),
            "company_name": contact_row.get("company_name") or "",
            **shared_ctx,
        }

    enriched = []
    for item in items:
        entry = {**item}
        cid = item["contact_id"]
        contact_row = contacts_by_id.get(cid, {})

        entry["aum_tier"] = aum_to_tier(item.get("aum_millions") or 0)

        # AI draft fields
        step_num = item.get("step_order")
        entry["message_draft"] = message_drafts_by_key.get((cid, step_num))
        entry["has_research"] = contact_row.get("company_id") in companies_with_research
        entry["draft_mode"] = step_draft_modes.get(step_num, "template")

        if item["channel"] == "email" and item["template_id"]:
            rendered = render_campaign_email(conn, cid, campaign_id, item["template_id"], config, user_id=user_id, pre_fetched_research=research_by_company)
            entry["rendered_email"] = rendered or None

            draft_row = gmail_drafts_by_contact.get(cid)
            entry["gmail_draft"] = (
                {"draft_id": draft_row["gmail_draft_id"], "status": draft_row["status"]}
                if draft_row else None
            )

        elif item["channel"].startswith("linkedin") and item["template_id"]:
            template_row = templates_by_id.get(item["template_id"])
            if template_row:
                context = _build_context(contact_row)
                body = (
                    render_template(template_row["body_template"], context)
                    if template_row["body_template"].endswith(".txt")
                    else _render_inline_template(template_row["body_template"], context)
                )
                entry["rendered_message"] = body
            else:
                entry["rendered_message"] = None

            li_url = contact_row.get("linkedin_url")
            if li_url:
                entry["linkedin_url"] = li_url
                if "/in/" in li_url:
                    slug = li_url.rstrip("/").split("/in/")[-1]
                    entry["sales_nav_url"] = f"https://www.linkedin.com/sales/people/{slug}"

        enriched.append(entry)

    return enriched
