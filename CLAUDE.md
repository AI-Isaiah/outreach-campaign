# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-channel outreach campaign manager for crypto fund allocators. Python CLI tool built with Typer that manages email and LinkedIn outreach sequences with GDPR/CAN-SPAM compliance, A/B testing, deduplication, and email verification. Uses PostgreSQL (Supabase) for storage.

## Commands

```bash
# Setup
make install                    # pip3 install -e ".[dev]"

# Run tests
make test                       # python3 -m pytest tests/ -v
python3 -m pytest tests/test_campaigns.py -v          # single file
python3 -m pytest tests/test_campaigns.py::test_name  # single test

# CLI usage
python3 -m src.cli --help       # all commands
python3 -m src.cli <command> --help
outreach <command>              # after install

# Common workflow commands (default campaign: Q1_2026_initial)
make queue                      # show today's actions
make send-dry                   # preview emails
make report                     # campaign dashboard
make weekly                     # weekly check-in
```

## Architecture

### Layer structure

```
src/cli.py              → Typer app, all 24 @app.command() definitions, config loading
src/commands/            → Command handlers (call services, format Rich output)
src/services/            → Pure business logic (no CLI dependencies)
src/models/              → PostgreSQL CRUD operations (campaigns.py) and DB setup (database.py)
src/templates/           → Jinja2 email/ and linkedin/ templates
migrations/pg/           → PostgreSQL schema files (auto-run on every command via run_migrations)
```

### Data flow

CSV/email import → deduplication (3-pass: email, LinkedIn, fuzzy) → email verification (ZeroBounce/Hunter) → campaign creation → sequence setup → contact enrollment → daily priority queue → send emails / export LinkedIn → log events → metrics/reporting

### Key modules

- **`services/priority_queue.py`** — Selects daily contacts to action. Enforces: one contact per company, orders by AUM, validates channel availability (email/LinkedIn).
- **`services/state_machine.py`** — Contact status transitions (queued → in_progress → replied/completed/unsubscribed). Auto-activates next contact at same company when one reaches terminal state.
- **`services/compliance.py`** — CAN-SPAM footer injection, GDPR email limits (max 2 vs 3), unsubscribe link generation.
- **`services/template_engine.py`** — Jinja2 rendering with compliance integration.
- **`models/campaigns.py`** — All CRUD for companies, contacts, campaigns, templates, enrollment, events.

### Database

PostgreSQL on Supabase via `psycopg2` with `RealDictCursor`. Key tables: `companies`, `contacts`, `campaigns`, `sequence_steps`, `templates`, `contact_campaign_status`, `events`, `dedup_log`. Schema in `migrations/pg/001_initial_schema.sql`. Migrations run automatically on every CLI command. Connection URL configured via `SUPABASE_DB_URL` env var.

Normalized fields (`email_normalized`, `linkedin_url_normalized`, `name_normalized`) are used for dedup and lookups — always populate these alongside raw fields.

### Config

- `config.yaml` — SMTP settings, calendly URL, physical address, GDPR country list (see `config.yaml.example`)
- `.env` — SUPABASE_DB_URL, SMTP_PASSWORD, EMAIL_VERIFY_API_KEY (see `.env.example`)
- CLI loads config in `src/cli.py` and injects SMTP password from env

## Conventions

- **Database access**: Use `psycopg2.extras.RealDictCursor` (rows are dicts). Use `%s` placeholders (not `?`). Call `run_migrations(conn)` before any DB operations. Use `cursor = conn.cursor(); cursor.execute(...)` pattern (not `conn.execute()`).
- **CLI commands**: Hyphenated names (`import-csv`), Python functions underscored (`import_csv`). All defined in `src/cli.py`.
- **GDPR handling**: Companies and contacts carry `is_gdpr` flag. Sequence steps have `gdpr_only`/`non_gdpr_only` flags to skip steps per jurisdiction.
- **A/B testing**: Templates use `variant_group` and `variant_label`. Contacts assigned variant on enrollment via round-robin.
- **Testing**: Tests use `tmp_db` fixture from `conftest.py` backed by `testing.postgresql` (ephemeral PG instance, session-scoped, tables truncated between tests). Mock SMTP and HTTP calls. Requires local PostgreSQL installation (e.g., `brew install postgresql@16`). Run with `PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" make test`.
- **Output**: Use Rich library (tables, panels, console) for all terminal output in commands.

## Data protection

Real contact data, database files, and credentials are gitignored. Never commit `.env`, `*.db`, or files in `data/imports/`.
