import logging
import os
from contextlib import contextmanager

import psycopg2
import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

from src.config import load_config_safe, SUPABASE_DB_URL  # noqa: E402

# Configure logging for all modules
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

app = typer.Typer(name="outreach", help="Multi-channel outreach campaign manager")
console = Console()

# CLI is single-user (founder's tool). Web app handles multi-tenancy.
CLI_USER_ID = 1


@contextmanager
def cli_db():
    """Context manager for CLI database connections."""
    from src.models.database import get_connection, run_migrations

    conn = get_connection(SUPABASE_DB_URL)
    try:
        run_migrations(conn)
        yield conn
    finally:
        conn.close()


def _load_config() -> dict:
    """Load config, wrapping errors for CLI display."""
    config = load_config_safe()
    if not config:
        console.print("[red]ERROR: No config.yaml or config.yaml.example found[/red]")
        raise typer.Exit(1)
    return config


@app.command()
def import_csv(csv_path: str = typer.Argument(..., help="Path to Crypto Fund List CSV")):
    """Import contacts from the crypto fund CSV file."""
    from src.commands.import_contacts import import_fund_csv

    with cli_db() as conn:
        stats = import_fund_csv(conn, csv_path, user_id=CLI_USER_ID)
        console.print(f"[green]Imported {stats['companies_created']} companies, {stats['contacts_created']} contacts[/green]")


@app.command()
def import_emails(file_path: str = typer.Argument(..., help="Path to file with pasted emails")):
    """Import contacts from a pasted email list."""
    from src.commands.import_emails import import_pasted_emails

    with cli_db() as conn:
        stats = import_pasted_emails(conn, file_path, user_id=CLI_USER_ID)
        console.print(f"[green]Imported {stats['contacts_created']} contacts ({stats['lines_skipped']} skipped)[/green]")


@app.command()
def dedupe():
    """Run deduplication pipeline across all contacts."""
    from src.services.deduplication import run_dedup

    with cli_db() as conn:
        console.print("[bold]Running deduplication pipeline...[/bold]")
        stats = run_dedup(conn, export_dir="data/exports", user_id=CLI_USER_ID)
        console.print(f"  Email duplicates removed: {stats['email_dupes']}")
        console.print(f"  LinkedIn duplicates removed: {stats['linkedin_dupes']}")
        console.print(f"  Fuzzy company matches flagged: {stats['fuzzy_flagged']}")
        if stats["fuzzy_flagged"] > 0:
            console.print("  [yellow]Review: data/exports/dedup_review.csv[/yellow]")


@app.command()
def verify():
    """Verify all unverified email addresses via ZeroBounce/Hunter."""
    from src.services.email_verifier import verify_email_batch, update_contact_email_status, get_unverified_emails

    api_key = os.getenv("EMAIL_VERIFY_API_KEY")
    provider = os.getenv("EMAIL_VERIFY_PROVIDER", "zerobounce")
    if not api_key:
        console.print("[red]ERROR: Set EMAIL_VERIFY_API_KEY in .env[/red]")
        raise typer.Exit(1)

    with cli_db() as conn:
        emails = get_unverified_emails(conn, user_id=CLI_USER_ID)
        console.print(f"[bold]Verifying {len(emails)} email addresses via {provider}...[/bold]")

        if not emails:
            console.print("No unverified emails found.")
            return

        results = verify_email_batch(emails, api_key, provider=provider)
        counts = {"valid": 0, "invalid": 0, "risky": 0, "catch-all": 0, "unknown": 0}
        for email, status in results.items():
            update_contact_email_status(conn, email, status, user_id=CLI_USER_ID)
            counts[status] = counts.get(status, 0) + 1

        console.print(f"  Valid: [green]{counts['valid']}[/green]")
        console.print(f"  Invalid: [red]{counts['invalid']}[/red]")
        console.print(f"  Risky: [yellow]{counts['risky']}[/yellow]")
        console.print(f"  Catch-all: [yellow]{counts['catch-all']}[/yellow]")
        console.print(f"  Unknown: {counts['unknown']}")


@app.command()
def stats():
    """Show database statistics."""
    from src.commands.stats import get_db_stats

    with cli_db() as conn:
        s = get_db_stats(conn, user_id=CLI_USER_ID)

        console.print("[bold]Database Statistics[/bold]")
        console.print(f"  Companies:      {s['companies']}")
        console.print(f"  Contacts:       {s['contacts']}")
        console.print(f"    With email:   {s['with_email']}")
        console.print(f"    With LinkedIn:{s['with_linkedin']}")
        console.print(f"    GDPR:         {s['gdpr']}")
        console.print(f"  Email status:")
        console.print(f"    Verified:     [green]{s['verified']}[/green]")
        console.print(f"    Invalid:      [red]{s['invalid']}[/red]")
        console.print(f"    Unverified:   {s['unverified']}")


@app.command()
def queue(
    campaign: str = typer.Argument(..., help="Campaign name"),
    limit: int = typer.Option(10, help="Max actions to show"),
    date: str = typer.Option(None, help="Target date (YYYY-MM-DD), defaults to today"),
):
    """Show today's outreach actions."""
    from rich.table import Table
    from src.commands.queue import queue_today

    with cli_db() as conn:
        items = queue_today(conn, campaign, target_date=date, limit=limit)

        if not items:
            console.print("[yellow]No actions queued for today.[/yellow]")
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


@app.command()
def export_expandi(
    campaign: str = typer.Argument(..., help="Campaign name"),
    date: str = typer.Option(None, help="Target date (YYYY-MM-DD)"),
):
    """Export LinkedIn actions to Expandi CSV."""
    from src.commands.export_expandi import export_expandi_csv

    with cli_db() as conn:
        try:
            filepath = export_expandi_csv(conn, campaign, target_date=date)
            console.print(f"[green]Exported to {filepath}[/green]")
        except ValueError as e:
            console.print(f"[red]ERROR: {e}[/red]")
            raise typer.Exit(1)


@app.command()
def import_expandi(
    file_path: str = typer.Argument(..., help="Path to LinkedIn results CSV (Expandi, Linked Helper, or generic)"),
    campaign: str = typer.Argument(..., help="Campaign name"),
):
    """Import LinkedIn automation results and update contact statuses.

    Auto-detects CSV format from Expandi, Linked Helper, or any tool
    with a LinkedIn URL column. Matches contacts by profile URL and
    advances them through the campaign sequence.
    """
    from src.commands.import_expandi import import_expandi_results

    with cli_db() as conn:
        try:
            result = import_expandi_results(conn, file_path, campaign)
            source_label = result.get("source", "unknown")
            console.print(f"[dim]Detected format: {source_label}[/dim]")
            console.print(f"[green]Matched: {result['matched']}[/green]")
            console.print(f"[yellow]Unmatched: {result['unmatched']}[/yellow]")
            console.print(f"[cyan]Advanced: {result['advanced']}[/cyan]")
        except ValueError as e:
            console.print(f"[red]ERROR: {e}[/red]")
            raise typer.Exit(1)


@app.command()
def create_campaign_cmd(
    name: str = typer.Argument(..., help="Campaign name"),
    description: str = typer.Option(None, help="Campaign description"),
):
    """Create a new campaign."""
    from src.models.campaigns import create_campaign

    with cli_db() as conn:
        try:
            campaign_id = create_campaign(conn, name, description=description, user_id=CLI_USER_ID)
            console.print(f"[green]Created campaign '{name}' (id={campaign_id})[/green]")
        except (psycopg2.Error, ValueError) as e:
            console.print(f"[red]ERROR: {e}[/red]")
            raise typer.Exit(1)


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
    from src.commands.setup_sequence import create_standard_sequence

    with cli_db() as conn:
        try:
            result = create_standard_sequence(conn, campaign, gdpr, user_id=CLI_USER_ID)
            if result["variant"] == "gdpr":
                console.print(f"[green]Set up GDPR sequence for '{campaign}' ({result['step_count']} steps, max 2 emails)[/green]")
            else:
                console.print(f"[green]Set up standard sequence for '{campaign}' ({result['step_count']} steps)[/green]")
        except (psycopg2.Error, ValueError) as e:
            console.print(f"[red]ERROR: {e}[/red]")
            raise typer.Exit(1)


@app.command()
def enroll(
    campaign: str = typer.Argument(..., help="Campaign name"),
    limit: int = typer.Option(None, help="Max contacts to enroll"),
    max_aum: float = typer.Option(None, "--max-aum", help="Max company AUM in $M (e.g. 1000 = $1B)"),
    min_aum: float = typer.Option(None, "--min-aum", help="Min company AUM in $M"),
):
    """Enroll eligible contacts into a campaign.

    Eligible contacts must have either a valid email or a LinkedIn URL,
    and must not be unsubscribed. Only the rank-1 contact per company
    is enrolled. Contacts are enrolled in AUM descending order (highest
    value targets first).
    """
    from src.commands.enroll import enroll_contacts

    with cli_db() as conn:
        try:
            result = enroll_contacts(
                conn, campaign, user_id=CLI_USER_ID,
                limit=limit, max_aum=max_aum, min_aum=min_aum,
            )
            console.print(f"[green]Enrolled {result['enrolled_count']} contacts into '{campaign}'{result['aum_filter']}[/green]")
        except ValueError as e:
            console.print(f"[red]ERROR: {e}[/red]")
            raise typer.Exit(1)


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
    from src.commands.send import get_email_queue, send_emails

    with cli_db() as conn:
        try:
            queue_data = get_email_queue(conn, campaign, user_id=CLI_USER_ID, limit=limit, date=date)
        except ValueError as e:
            console.print(f"[red]ERROR: {e}[/red]")
            raise typer.Exit(1)

        email_items = queue_data["email_items"]

        if not email_items:
            console.print("[yellow]No email actions queued for today.[/yellow]")
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
            return

        # Ask for confirmation
        typer.confirm(f"Send {len(email_items)} email(s)?", abort=True)

        config = _load_config()
        result = send_emails(conn, queue_data["campaign_id"], email_items, config, user_id=CLI_USER_ID)
        console.print(f"[green]Sent: {result['sent']}[/green]  [red]Failed: {result['failed']}[/red]")


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
    from src.commands.status import log_reply
    from src.services.state_machine import InvalidTransition

    with cli_db() as conn:
        try:
            result = log_reply(
                conn, action, identifier, outcome,
                user_id=CLI_USER_ID, campaign_name=campaign,
            )
            console.print(f"[green]Logged '{result['outcome']}' for {result['contact_name']} -> status: {result['new_status']}[/green]")
        except (ValueError, InvalidTransition) as e:
            console.print(f"[red]ERROR: {e}[/red]")
            raise typer.Exit(1)


@app.command()
def unsubscribe(
    email: str = typer.Argument(..., help="Email to unsubscribe"),
):
    """Process an unsubscribe request."""
    from src.services.compliance import process_unsubscribe

    with cli_db() as conn:
        result = process_unsubscribe(conn, email, user_id=CLI_USER_ID)

        if result:
            console.print(f"[green]Unsubscribed: {email}[/green]")
        else:
            console.print(f"[yellow]No contact found with email: {email}[/yellow]")


@app.command()
def weekly_plan(
    campaign: str = typer.Argument(..., help="Campaign name"),
):
    """Weekly check-in: review last week + plan next week."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.columns import Columns
    from src.commands.weekly_plan import generate_weekly_plan

    with cli_db() as conn:
        try:
            plan = generate_weekly_plan(conn, campaign)
        except ValueError as e:
            console.print(f"[red]ERROR: {e}[/red]")
            raise typer.Exit(1)

        campaign_info = plan["campaign"]
        console.print(
            Panel(
                f"[bold]{campaign_info['name']}[/bold]  (status: {campaign_info['status']})",
                title="Weekly Check-in",
                style="blue",
            )
        )

        # Section 1: Last Week Summary
        lw = plan["last_week"]
        summary_lines = [
            f"  Period:            {lw['period']}",
            f"  Emails sent:       {lw['emails_sent']}",
            f"  LinkedIn actions:  {lw['linkedin_actions']}",
            f"  Positive replies:  [green]{lw['replies_positive']}[/green]",
            f"  Negative replies:  [red]{lw['replies_negative']}[/red]",
            f"  Calls booked:      [cyan]{lw['calls_booked']}[/cyan]",
            f"  New no-response:   {lw['new_no_response']}",
        ]
        console.print(Panel("\n".join(summary_lines), title="Last Week Summary"))

        # Section 2: A/B Variant Comparison
        variants = plan["variant_comparison"]
        if variants:
            vt = Table(title="A/B Variant Comparison")
            vt.add_column("Variant", style="bold")
            vt.add_column("Total", justify="right")
            vt.add_column("Positive", justify="right", style="green")
            vt.add_column("Negative", justify="right", style="red")
            vt.add_column("No Response", justify="right")
            vt.add_column("Reply Rate", justify="right")
            vt.add_column("Positive Rate", justify="right")

            for v in variants:
                vt.add_row(
                    v["variant"],
                    str(v["total"]),
                    str(v["replied_positive"]),
                    str(v["replied_negative"]),
                    str(v["no_response"]),
                    f"{v['reply_rate']:.1%}",
                    f"{v['positive_rate']:.1%}",
                )
            console.print(vt)
        else:
            console.print("[dim]No A/B variant data available.[/dim]")

        # Section 3: Proposed Next Week
        nw = plan["proposed_next_week"]
        nw_lines = [f"  Contacts ready: {nw['contacts_ready']}"]
        if nw["channel_mix"]:
            nw_lines.append("  Channel mix:")
            for ch, cnt in nw["channel_mix"].items():
                nw_lines.append(f"    {ch}: {cnt}")
        else:
            nw_lines.append("  No contacts ready for next week.")
        console.print(Panel("\n".join(nw_lines), title="Proposed Next Week"))

        # Section 4: Newsletter
        nl = plan["newsletter_recommendation"]
        rec_label = "[green]Yes[/green]" if nl["recommend"] else "[yellow]No[/yellow]"
        console.print(
            Panel(
                f"  Recommend: {rec_label}\n  Reason: {nl['reason']}",
                title="Newsletter",
            )
        )

        # Section 5: Next Actions
        actions = plan["next_actions"]
        action_lines = [f"  - {a}" for a in actions]
        console.print(Panel("\n".join(action_lines), title="Next Actions"))


@app.command()
def report(
    campaign: str = typer.Argument(..., help="Campaign name"),
):
    """Full campaign report dashboard."""
    from rich.panel import Panel
    from rich.table import Table
    from src.commands.report import get_campaign_report

    with cli_db() as conn:
        try:
            data = get_campaign_report(conn, campaign, user_id=CLI_USER_ID)
        except ValueError as e:
            console.print(f"[red]ERROR: {e}[/red]")
            raise typer.Exit(1)

        camp = data["campaign"]
        metrics = data["metrics"]
        weekly = data["weekly"]
        variants = data["variants"]
        firm_breakdown = data["firm_breakdown"]

        # Header
        console.print(
            Panel(
                f"[bold]{camp['name']}[/bold]  (status: {camp['status']})",
                title="Campaign Report",
                style="blue",
            )
        )

        # Overall Metrics
        bs = metrics["by_status"]
        overview_lines = [
            f"  Total enrolled:    {metrics['total_enrolled']}",
            f"  Queued:            {bs['queued']}",
            f"  In progress:       {bs['in_progress']}",
            f"  Replied positive:  [green]{bs['replied_positive']}[/green]",
            f"  Replied negative:  [red]{bs['replied_negative']}[/red]",
            f"  No response:       {bs['no_response']}",
            f"  Bounced:           [red]{bs['bounced']}[/red]",
            "",
            f"  Emails sent:       {metrics['emails_sent']}",
            f"  LinkedIn connects: {metrics['linkedin_connects']}",
            f"  LinkedIn messages: {metrics['linkedin_messages']}",
            f"  Calls booked:      [cyan]{metrics['calls_booked']}[/cyan]",
            "",
            f"  Reply rate:        {metrics['reply_rate']:.1%}",
            f"  Positive rate:     {metrics['positive_rate']:.1%}",
        ]
        console.print(Panel("\n".join(overview_lines), title="Overall Metrics"))

        # Weekly Summary
        weekly_lines = [
            f"  Period:            {weekly['period']}",
            f"  Emails sent:       {weekly['emails_sent']}",
            f"  LinkedIn actions:  {weekly['linkedin_actions']}",
            f"  Positive replies:  [green]{weekly['replies_positive']}[/green]",
            f"  Negative replies:  [red]{weekly['replies_negative']}[/red]",
            f"  Calls booked:      [cyan]{weekly['calls_booked']}[/cyan]",
            f"  New no-response:   {weekly['new_no_response']}",
        ]
        console.print(Panel("\n".join(weekly_lines), title="This Week"))

        # Variant Comparison
        if variants:
            vt = Table(title="A/B Variant Comparison")
            vt.add_column("Variant", style="bold")
            vt.add_column("Total", justify="right")
            vt.add_column("Positive", justify="right", style="green")
            vt.add_column("Negative", justify="right", style="red")
            vt.add_column("No Response", justify="right")
            vt.add_column("Reply Rate", justify="right")
            vt.add_column("Positive Rate", justify="right")

            for v in variants:
                vt.add_row(
                    v["variant"],
                    str(v["total"]),
                    str(v["replied_positive"]),
                    str(v["replied_negative"]),
                    str(v["no_response"]),
                    f"{v['reply_rate']:.1%}",
                    f"{v['positive_rate']:.1%}",
                )
            console.print(vt)
        else:
            console.print("[dim]No A/B variant data available.[/dim]")

        # Company Type Breakdown
        if firm_breakdown:
            ft = Table(title="Reply Rate by Firm Type")
            ft.add_column("Firm Type", style="bold")
            ft.add_column("Total", justify="right")
            ft.add_column("Positive", justify="right", style="green")
            ft.add_column("Negative", justify="right", style="red")
            ft.add_column("No Response", justify="right")
            ft.add_column("Reply Rate", justify="right")
            ft.add_column("Positive Rate", justify="right")

            for f in firm_breakdown:
                ft.add_row(
                    f["firm_type"],
                    str(f["total"]),
                    str(f["replied_positive"]),
                    str(f["replied_negative"]),
                    str(f["no_response"]),
                    f"{f['reply_rate']:.1%}",
                    f"{f['positive_rate']:.1%}",
                )
            console.print(ft)
        else:
            console.print("[dim]No firm type data available.[/dim]")


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to listen on"),
    reload: bool = typer.Option(False, help="Enable auto-reload for development"),
):
    """Start the web dashboard (FastAPI + uvicorn)."""
    import uvicorn

    uvicorn.run(
        "src.web.app:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=["src"] if reload else None,
    )


if __name__ == "__main__":
    app()
