import os
import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

app = typer.Typer(name="outreach", help="Multi-channel outreach campaign manager")
console = Console()

DB_PATH = os.getenv("DATABASE_PATH", "outreach.db")


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


if __name__ == "__main__":
    app()
