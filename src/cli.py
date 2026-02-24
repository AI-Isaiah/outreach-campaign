import json
import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

app = typer.Typer(name="outreach", help="Multi-channel outreach campaign manager")
console = Console()

DB_PATH = os.getenv("DATABASE_PATH", "outreach.db")


def _load_config() -> dict:
    """Load config from config.yaml or config.yaml.example.

    Also injects the SMTP password from the environment variable
    ``SMTP_PASSWORD`` if it is set.

    Returns:
        The parsed YAML config as a dict.
    """
    import yaml

    config_path = Path("config.yaml")
    if not config_path.exists():
        config_path = Path("config.yaml.example")
    if not config_path.exists():
        console.print("[red]ERROR: No config.yaml or config.yaml.example found[/red]")
        raise typer.Exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Inject SMTP password from environment
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    if smtp_password:
        config["smtp_password"] = smtp_password

    return config


@app.command()
def import_csv(csv_path: str = typer.Argument(..., help="Path to Crypto Fund List CSV")):
    """Import contacts from the crypto fund CSV file."""
    from src.models.database import get_connection, run_migrations
    from src.commands.import_contacts import import_fund_csv

    conn = get_connection(DB_PATH)
    run_migrations(conn)
    stats = import_fund_csv(conn, csv_path)
    console.print(f"[green]Imported {stats['companies_created']} companies, {stats['contacts_created']} contacts[/green]")
    conn.close()


@app.command()
def import_emails(file_path: str = typer.Argument(..., help="Path to file with pasted emails")):
    """Import contacts from a pasted email list."""
    from src.models.database import get_connection, run_migrations
    from src.commands.import_emails import import_pasted_emails

    conn = get_connection(DB_PATH)
    run_migrations(conn)
    stats = import_pasted_emails(conn, file_path)
    console.print(f"[green]Imported {stats['contacts_created']} contacts ({stats['lines_skipped']} skipped)[/green]")
    conn.close()


@app.command()
def dedupe():
    """Run deduplication pipeline across all contacts."""
    from src.models.database import get_connection, run_migrations
    from src.services.deduplication import run_dedup

    conn = get_connection(DB_PATH)
    run_migrations(conn)
    console.print("[bold]Running deduplication pipeline...[/bold]")
    stats = run_dedup(conn, export_dir="data/exports")
    console.print(f"  Email duplicates removed: {stats['email_dupes']}")
    console.print(f"  LinkedIn duplicates removed: {stats['linkedin_dupes']}")
    console.print(f"  Fuzzy company matches flagged: {stats['fuzzy_flagged']}")
    if stats["fuzzy_flagged"] > 0:
        console.print("  [yellow]Review: data/exports/dedup_review.csv[/yellow]")
    conn.close()


@app.command()
def verify():
    """Verify all unverified email addresses via ZeroBounce/Hunter."""
    from src.models.database import get_connection, run_migrations
    from src.services.email_verifier import verify_email_batch, update_contact_email_status, get_unverified_emails

    api_key = os.getenv("EMAIL_VERIFY_API_KEY")
    provider = os.getenv("EMAIL_VERIFY_PROVIDER", "zerobounce")
    if not api_key:
        console.print("[red]ERROR: Set EMAIL_VERIFY_API_KEY in .env[/red]")
        raise typer.Exit(1)

    conn = get_connection(DB_PATH)
    run_migrations(conn)
    emails = get_unverified_emails(conn)
    console.print(f"[bold]Verifying {len(emails)} email addresses via {provider}...[/bold]")

    if not emails:
        console.print("No unverified emails found.")
        conn.close()
        return

    results = verify_email_batch(emails, api_key, provider=provider)
    counts = {"valid": 0, "invalid": 0, "risky": 0, "catch-all": 0, "unknown": 0}
    for email, status in results.items():
        update_contact_email_status(conn, email, status)
        counts[status] = counts.get(status, 0) + 1

    console.print(f"  Valid: [green]{counts['valid']}[/green]")
    console.print(f"  Invalid: [red]{counts['invalid']}[/red]")
    console.print(f"  Risky: [yellow]{counts['risky']}[/yellow]")
    console.print(f"  Catch-all: [yellow]{counts['catch-all']}[/yellow]")
    console.print(f"  Unknown: {counts['unknown']}")
    conn.close()


@app.command()
def stats():
    """Show database statistics."""
    from src.models.database import get_connection, run_migrations

    conn = get_connection(DB_PATH)
    run_migrations(conn)

    companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    contacts = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    gdpr = conn.execute("SELECT COUNT(*) FROM contacts WHERE is_gdpr = 1").fetchone()[0]
    verified = conn.execute("SELECT COUNT(*) FROM contacts WHERE email_status = 'valid'").fetchone()[0]
    invalid = conn.execute("SELECT COUNT(*) FROM contacts WHERE email_status = 'invalid'").fetchone()[0]
    unverified = conn.execute("SELECT COUNT(*) FROM contacts WHERE email_status = 'unverified'").fetchone()[0]
    with_email = conn.execute("SELECT COUNT(*) FROM contacts WHERE email_normalized IS NOT NULL").fetchone()[0]
    with_linkedin = conn.execute("SELECT COUNT(*) FROM contacts WHERE linkedin_url IS NOT NULL AND linkedin_url != ''").fetchone()[0]

    console.print("[bold]Database Statistics[/bold]")
    console.print(f"  Companies:      {companies}")
    console.print(f"  Contacts:       {contacts}")
    console.print(f"    With email:   {with_email}")
    console.print(f"    With LinkedIn:{with_linkedin}")
    console.print(f"    GDPR:         {gdpr}")
    console.print(f"  Email status:")
    console.print(f"    Verified:     [green]{verified}[/green]")
    console.print(f"    Invalid:      [red]{invalid}[/red]")
    console.print(f"    Unverified:   {unverified}")
    conn.close()


@app.command()
def queue(
    campaign: str = typer.Argument(..., help="Campaign name"),
    limit: int = typer.Option(10, help="Max actions to show"),
    date: str = typer.Option(None, help="Target date (YYYY-MM-DD), defaults to today"),
):
    """Show today's outreach actions."""
    from rich.table import Table
    from src.models.database import get_connection, run_migrations
    from src.commands.queue import queue_today

    conn = get_connection(DB_PATH)
    run_migrations(conn)

    items = queue_today(conn, campaign, target_date=date, limit=limit)

    if not items:
        console.print("[yellow]No actions queued for today.[/yellow]")
        conn.close()
        return

    table = Table(title=f"Today's Queue: {campaign}")
    table.add_column("#", style="dim")
    table.add_column("Contact", style="bold")
    table.add_column("Company")
    table.add_column("AUM ($M)", justify="right")
    table.add_column("Channel", style="cyan")
    table.add_column("Step", justify="center")
    table.add_column("GDPR", justify="center")

    for i, item in enumerate(items, 1):
        aum = f"{item['aum_millions']:,.0f}" if item["aum_millions"] else "-"
        gdpr_flag = "[red]Yes[/red]" if item["is_gdpr"] else "No"
        step_display = f"{item['step_order']}/{item['total_steps']}"
        table.add_row(
            str(i),
            item["contact_name"],
            item["company_name"],
            aum,
            item["channel"],
            step_display,
            gdpr_flag,
        )

    console.print(table)
    console.print(f"[dim]Showing {len(items)} action(s)[/dim]")
    conn.close()


@app.command()
def export_expandi(
    campaign: str = typer.Argument(..., help="Campaign name"),
    date: str = typer.Option(None, help="Target date (YYYY-MM-DD)"),
):
    """Export LinkedIn actions to Expandi CSV."""
    from src.models.database import get_connection, run_migrations
    from src.commands.export_expandi import export_expandi_csv

    conn = get_connection(DB_PATH)
    run_migrations(conn)

    try:
        filepath = export_expandi_csv(conn, campaign, target_date=date)
        console.print(f"[green]Exported to {filepath}[/green]")
    except ValueError as e:
        console.print(f"[red]ERROR: {e}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()


@app.command()
def import_expandi(
    file_path: str = typer.Argument(..., help="Path to Expandi results CSV"),
    campaign: str = typer.Argument(..., help="Campaign name"),
):
    """Import Expandi results and update contact statuses."""
    from src.models.database import get_connection, run_migrations
    from src.commands.import_expandi import import_expandi_results

    conn = get_connection(DB_PATH)
    run_migrations(conn)

    try:
        result = import_expandi_results(conn, file_path, campaign)
        console.print(f"[green]Matched: {result['matched']}[/green]")
        console.print(f"[yellow]Unmatched: {result['unmatched']}[/yellow]")
        console.print(f"[cyan]Advanced: {result['advanced']}[/cyan]")
    except ValueError as e:
        console.print(f"[red]ERROR: {e}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()


@app.command()
def create_campaign_cmd(
    name: str = typer.Argument(..., help="Campaign name"),
    description: str = typer.Option(None, help="Campaign description"),
):
    """Create a new campaign."""
    from src.models.database import get_connection, run_migrations
    from src.models.campaigns import create_campaign

    conn = get_connection(DB_PATH)
    run_migrations(conn)

    try:
        campaign_id = create_campaign(conn, name, description=description)
        console.print(f"[green]Created campaign '{name}' (id={campaign_id})[/green]")
    except Exception as e:
        console.print(f"[red]ERROR: {e}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()


@app.command()
def setup_sequence(
    campaign: str = typer.Argument(..., help="Campaign name"),
    gdpr: bool = typer.Option(False, help="Set up GDPR-compliant sequence (max 2 emails)"),
):
    """Set up a standard outreach sequence for a campaign.

    Creates default templates and sequence steps.

    Standard: linkedin_connect -> linkedin_message -> email_cold -> email_followup -> email_breakup
    GDPR: linkedin_connect -> linkedin_message -> email_cold -> email_final (max 2 emails)
    """
    from src.models.database import get_connection, run_migrations
    from src.models.campaigns import (
        get_campaign_by_name,
        create_template,
        add_sequence_step,
    )

    conn = get_connection(DB_PATH)
    run_migrations(conn)

    camp = get_campaign_by_name(conn, campaign)
    if not camp:
        console.print(f"[red]ERROR: Campaign '{campaign}' not found[/red]")
        conn.close()
        raise typer.Exit(1)

    campaign_id = camp["id"]

    try:
        # Create templates
        t_li_connect = create_template(
            conn, f"{campaign}_li_connect", "linkedin_connect",
            "Hi {{first_name}}, I'd like to connect regarding {{company_name}}.",
        )
        t_li_message = create_template(
            conn, f"{campaign}_li_message", "linkedin_message",
            "Hi {{first_name}}, following up on my connection request.",
        )
        t_email_cold = create_template(
            conn, f"{campaign}_email_cold", "email",
            "Hello {{first_name}},\n\nI wanted to reach out regarding...",
            subject="Quick introduction",
        )

        # Step 1: LinkedIn connect (day 0)
        add_sequence_step(conn, campaign_id, 1, "linkedin_connect", t_li_connect, delay_days=0)
        # Step 2: LinkedIn message (day 3)
        add_sequence_step(conn, campaign_id, 2, "linkedin_message", t_li_message, delay_days=3)
        # Step 3: Cold email (day 5)
        add_sequence_step(conn, campaign_id, 3, "email", t_email_cold, delay_days=5)

        if gdpr:
            # GDPR: max 2 emails total
            t_email_final = create_template(
                conn, f"{campaign}_email_final", "email",
                "Hi {{first_name}},\n\nJust a final note...",
                subject="Final note",
            )
            add_sequence_step(conn, campaign_id, 4, "email", t_email_final, delay_days=7)
            console.print(f"[green]Set up GDPR sequence for '{campaign}' (4 steps, max 2 emails)[/green]")
        else:
            # Standard: 3 emails total
            t_email_followup = create_template(
                conn, f"{campaign}_email_followup", "email",
                "Hi {{first_name}},\n\nFollowing up on my previous email...",
                subject="Following up",
            )
            t_email_breakup = create_template(
                conn, f"{campaign}_email_breakup", "email",
                "Hi {{first_name}},\n\nI understand you're busy...",
                subject="Last note",
            )
            add_sequence_step(
                conn, campaign_id, 4, "email", t_email_followup,
                delay_days=7, non_gdpr_only=True,
            )
            add_sequence_step(
                conn, campaign_id, 5, "email", t_email_breakup,
                delay_days=14, non_gdpr_only=True,
            )
            console.print(f"[green]Set up standard sequence for '{campaign}' (5 steps)[/green]")
    except Exception as e:
        console.print(f"[red]ERROR: {e}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()


@app.command()
def enroll(
    campaign: str = typer.Argument(..., help="Campaign name"),
    limit: int = typer.Option(None, help="Max contacts to enroll"),
):
    """Enroll eligible contacts into a campaign.

    Eligible contacts must have either a valid email or a LinkedIn URL,
    and must not be unsubscribed. Only the rank-1 contact per company
    is enrolled.
    """
    from datetime import date as date_mod
    from src.models.database import get_connection, run_migrations
    from src.models.campaigns import get_campaign_by_name, enroll_contact

    conn = get_connection(DB_PATH)
    run_migrations(conn)

    camp = get_campaign_by_name(conn, campaign)
    if not camp:
        console.print(f"[red]ERROR: Campaign '{campaign}' not found[/red]")
        conn.close()
        raise typer.Exit(1)

    campaign_id = camp["id"]

    # Find rank-1 eligible contacts per company (not already enrolled)
    query = """
    SELECT c.id, c.company_id
    FROM contacts c
    WHERE c.priority_rank = 1
      AND c.unsubscribed = 0
      AND (
          (c.email_normalized IS NOT NULL AND c.email_normalized != '')
          OR (c.linkedin_url IS NOT NULL AND c.linkedin_url != '')
      )
      AND c.id NOT IN (
          SELECT contact_id FROM contact_campaign_status WHERE campaign_id = ?
      )
    ORDER BY c.id
    """
    params = [campaign_id]

    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(query, params).fetchall()

    enrolled_count = 0
    today = date_mod.today().isoformat()
    for row in rows:
        result = enroll_contact(conn, row["id"], campaign_id, next_action_date=today)
        if result is not None:
            enrolled_count += 1

    console.print(f"[green]Enrolled {enrolled_count} contacts into '{campaign}'[/green]")
    conn.close()


@app.command()
def send(
    campaign: str = typer.Argument(..., help="Campaign name"),
    limit: int = typer.Option(10, help="Max emails to send"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without sending"),
    date: str = typer.Option(None, help="Target date (YYYY-MM-DD)"),
):
    """Send today's outreach emails.

    Gets today's queue, filters to email-channel actions only,
    shows a preview, and asks for confirmation before sending.
    """
    from rich.table import Table
    from src.models.database import get_connection, run_migrations
    from src.models.campaigns import get_campaign_by_name
    from src.services.priority_queue import get_daily_queue
    from src.services.email_sender import send_campaign_email

    conn = get_connection(DB_PATH)
    run_migrations(conn)

    camp = get_campaign_by_name(conn, campaign)
    if not camp:
        console.print(f"[red]ERROR: Campaign '{campaign}' not found[/red]")
        conn.close()
        raise typer.Exit(1)

    campaign_id = camp["id"]

    # Get today's queue (all channels)
    queue_items = get_daily_queue(conn, campaign_id, target_date=date, limit=limit)

    # Filter to email-channel only
    email_items = [item for item in queue_items if item["channel"] == "email"]

    if not email_items:
        console.print("[yellow]No email actions queued for today.[/yellow]")
        conn.close()
        return

    # Display preview table
    table = Table(title=f"Email Queue: {campaign}")
    table.add_column("#", style="dim")
    table.add_column("Contact", style="bold")
    table.add_column("Company")
    table.add_column("Email")
    table.add_column("Step", justify="center")
    table.add_column("GDPR", justify="center")

    for i, item in enumerate(email_items, 1):
        gdpr_flag = "[red]Yes[/red]" if item["is_gdpr"] else "No"
        step_display = f"{item['step_order']}/{item['total_steps']}"
        table.add_row(
            str(i),
            item["contact_name"],
            item["company_name"],
            item.get("email", ""),
            step_display,
            gdpr_flag,
        )

    console.print(table)

    if dry_run:
        console.print(f"[cyan]DRY RUN: Would send {len(email_items)} email(s). No emails sent.[/cyan]")
        conn.close()
        return

    # Ask for confirmation
    typer.confirm(f"Send {len(email_items)} email(s)?", abort=True)

    # Load SMTP config
    config = _load_config()

    sent = 0
    failed = 0
    for item in email_items:
        success = send_campaign_email(
            conn,
            item["contact_id"],
            campaign_id,
            item["template_id"],
            config,
        )
        if success:
            sent += 1
        else:
            failed += 1

    console.print(f"[green]Sent: {sent}[/green]  [red]Failed: {failed}[/red]")
    conn.close()


@app.command()
def status(
    action: str = typer.Argument(..., help="Action: reply"),
    identifier: str = typer.Argument(..., help="Contact email or ID"),
    outcome: str = typer.Argument(..., help="Outcome: positive, negative, call-booked, no-response"),
    campaign: str = typer.Option(None, help="Campaign name (uses first active if not specified)"),
):
    """Log a reply or status update for a contact.

    Examples:
        outreach status reply john@fund.com positive
        outreach status reply john@fund.com negative
        outreach status reply john@fund.com call-booked
    """
    from src.models.database import get_connection, run_migrations
    from src.models.campaigns import (
        get_campaign_by_name,
        get_contact_campaign_status,
        log_event,
        list_campaigns,
    )
    from src.services.state_machine import transition_contact, InvalidTransition

    conn = get_connection(DB_PATH)
    run_migrations(conn)

    if action != "reply":
        console.print(f"[red]ERROR: Unknown action '{action}'. Supported: reply[/red]")
        conn.close()
        raise typer.Exit(1)

    # Validate outcome
    outcome_map = {
        "positive": "replied_positive",
        "negative": "replied_negative",
        "call-booked": "replied_positive",
        "no-response": "no_response",
    }
    if outcome not in outcome_map:
        console.print(f"[red]ERROR: Unknown outcome '{outcome}'. Supported: {', '.join(outcome_map.keys())}[/red]")
        conn.close()
        raise typer.Exit(1)

    # Find the contact
    if identifier.isdigit():
        contact_row = conn.execute(
            "SELECT id, email, full_name FROM contacts WHERE id = ?",
            (int(identifier),),
        ).fetchone()
    else:
        contact_row = conn.execute(
            "SELECT id, email, full_name FROM contacts WHERE email = ? OR email_normalized = ?",
            (identifier, identifier.lower().strip()),
        ).fetchone()

    if contact_row is None:
        console.print(f"[red]ERROR: Contact '{identifier}' not found[/red]")
        conn.close()
        raise typer.Exit(1)

    contact_id = contact_row["id"]

    # Find the campaign
    if campaign:
        camp = get_campaign_by_name(conn, campaign)
        if not camp:
            console.print(f"[red]ERROR: Campaign '{campaign}' not found[/red]")
            conn.close()
            raise typer.Exit(1)
        campaign_id = camp["id"]
    else:
        # Use first active campaign this contact is enrolled in
        row = conn.execute(
            """SELECT ccs.campaign_id FROM contact_campaign_status ccs
               JOIN campaigns c ON c.id = ccs.campaign_id
               WHERE ccs.contact_id = ? AND c.status = 'active'
               ORDER BY ccs.id DESC LIMIT 1""",
            (contact_id,),
        ).fetchone()
        if row is None:
            console.print(f"[red]ERROR: Contact is not enrolled in any active campaign[/red]")
            conn.close()
            raise typer.Exit(1)
        campaign_id = row["campaign_id"]

    # Ensure contact is in_progress before transitioning
    ccs = get_contact_campaign_status(conn, contact_id, campaign_id)
    if ccs is None:
        console.print(f"[red]ERROR: Contact is not enrolled in campaign {campaign_id}[/red]")
        conn.close()
        raise typer.Exit(1)

    # If currently queued, auto-advance to in_progress first
    if ccs["status"] == "queued":
        try:
            transition_contact(conn, contact_id, campaign_id, "in_progress")
        except InvalidTransition as e:
            console.print(f"[red]ERROR: {e}[/red]")
            conn.close()
            raise typer.Exit(1)

    # Apply the transition
    new_status = outcome_map[outcome]
    try:
        transition_contact(conn, contact_id, campaign_id, new_status)
    except InvalidTransition as e:
        console.print(f"[red]ERROR: {e}[/red]")
        conn.close()
        raise typer.Exit(1)

    # Log extra metadata for call-booked
    if outcome == "call-booked":
        log_event(
            conn,
            contact_id,
            "call_booked",
            campaign_id=campaign_id,
            metadata=json.dumps({"call_booked": True}),
        )

    contact_name = contact_row["full_name"] or contact_row["email"] or str(contact_id)
    console.print(f"[green]Logged '{outcome}' for {contact_name} -> status: {new_status}[/green]")
    conn.close()


@app.command()
def unsubscribe(
    email: str = typer.Argument(..., help="Email to unsubscribe"),
):
    """Process an unsubscribe request."""
    from src.models.database import get_connection, run_migrations
    from src.services.compliance import process_unsubscribe

    conn = get_connection(DB_PATH)
    run_migrations(conn)

    result = process_unsubscribe(conn, email)

    if result:
        console.print(f"[green]Unsubscribed: {email}[/green]")
    else:
        console.print(f"[yellow]No contact found with email: {email}[/yellow]")

    conn.close()


if __name__ == "__main__":
    app()
