"""CLI command handler: set up a standard outreach sequence for a campaign."""

from __future__ import annotations

from src.models.campaigns import (
    get_campaign_by_name,
    create_template,
    add_sequence_step,
)


def create_standard_sequence(conn, campaign_name: str, gdpr: bool, *, user_id: int) -> dict:
    """Create default templates and sequence steps for a campaign.

    Standard: linkedin_connect -> linkedin_message -> email_cold -> email_followup -> email_breakup
    GDPR: linkedin_connect -> linkedin_message -> email_cold -> email_final (max 2 emails)

    Returns dict with 'campaign_id', 'step_count', 'variant' ('gdpr' or 'standard').
    Raises ValueError if campaign not found.
    """
    camp = get_campaign_by_name(conn, campaign_name, user_id=user_id)
    if not camp:
        raise ValueError(f"Campaign '{campaign_name}' not found")

    campaign_id = camp["id"]

    # Create templates
    t_li_connect = create_template(
        conn, f"{campaign_name}_li_connect", "linkedin_connect",
        "Hi {{first_name}}, I'd like to connect regarding {{company_name}}.",
        user_id=user_id,
    )
    t_li_message = create_template(
        conn, f"{campaign_name}_li_message", "linkedin_message",
        "Hi {{first_name}}, following up on my connection request.",
        user_id=user_id,
    )
    t_email_cold = create_template(
        conn, f"{campaign_name}_email_cold", "email",
        "Hello {{first_name}},\n\nI wanted to reach out regarding...",
        subject="Quick introduction", user_id=user_id,
    )

    # Step 1: LinkedIn connect (day 0)
    add_sequence_step(conn, campaign_id, 1, "linkedin_connect", t_li_connect, delay_days=0, user_id=user_id)
    # Step 2: LinkedIn message (day 3)
    add_sequence_step(conn, campaign_id, 2, "linkedin_message", t_li_message, delay_days=3, user_id=user_id)
    # Step 3: Cold email (day 5)
    add_sequence_step(conn, campaign_id, 3, "email", t_email_cold, delay_days=5, user_id=user_id)

    if gdpr:
        # GDPR: max 2 emails total
        t_email_final = create_template(
            conn, f"{campaign_name}_email_final", "email",
            "Hi {{first_name}},\n\nJust a final note...",
            subject="Final note", user_id=user_id,
        )
        add_sequence_step(conn, campaign_id, 4, "email", t_email_final, delay_days=7, user_id=user_id)
        return {"campaign_id": campaign_id, "step_count": 4, "variant": "gdpr"}
    else:
        # Standard: 3 emails total
        t_email_followup = create_template(
            conn, f"{campaign_name}_email_followup", "email",
            "Hi {{first_name}},\n\nFollowing up on my previous email...",
            subject="Following up", user_id=user_id,
        )
        t_email_breakup = create_template(
            conn, f"{campaign_name}_email_breakup", "email",
            "Hi {{first_name}},\n\nI understand you're busy...",
            subject="Last note", user_id=user_id,
        )
        add_sequence_step(
            conn, campaign_id, 4, "email", t_email_followup,
            delay_days=7, non_gdpr_only=True, user_id=user_id,
        )
        add_sequence_step(
            conn, campaign_id, 5, "email", t_email_breakup,
            delay_days=14, non_gdpr_only=True, user_id=user_id,
        )
        return {"campaign_id": campaign_id, "step_count": 5, "variant": "standard"}
