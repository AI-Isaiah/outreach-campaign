# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-channel outreach campaign manager for crypto fund allocators. Multi-tenant Python web app (FastAPI + React) with CLI tool (Typer) that manages email and LinkedIn outreach sequences with GDPR/CAN-SPAM compliance, A/B testing, deduplication, and email verification. Uses PostgreSQL (Supabase) for storage. Supports multiple users with complete data isolation via per-row `user_id` scoping. Email sending via Gmail OAuth or per-user SMTP.

## Current Work

Check `TODOS.md` for the prioritized backlog. P0 items are the next thing to build. When starting a new session, read TODOS.md first to understand what needs doing.

**Active plan:** "Complete Daily Outreach System (B+C)" — 5 phases. Phase 1 (cross-campaign email dedup) is COMPLETE. Phases 2-5 are next. Full plan at `~/.claude/plans/magical-juggling-shamir.md`. Design doc at `~/.gstack/projects/AI-Isaiah-outreach-campaign/helios-mammut-feat-smart-import-design-20260325-015128.md`. Eng review test plan at `~/.gstack/projects/AI-Isaiah-outreach-campaign/helios-mammut-feat-smart-import-eng-review-test-plan-20260325-021556.md`.

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
src/web/                 → FastAPI app and API route modules (routes/)
src/templates/           → Jinja2 email/ and linkedin/ templates
migrations/pg/           → PostgreSQL schema files (auto-run on every command via run_migrations)
frontend/src/            → React + TypeScript frontend (pages/, components/, api/)
```

### Data flow

CSV/email import → deduplication (3-pass: email, LinkedIn, fuzzy) → email verification (ZeroBounce/Hunter) → campaign creation → sequence setup → contact enrollment → daily priority queue → send emails / export LinkedIn → log events → metrics/reporting

### Key modules

- **`services/priority_queue.py`** — Selects daily contacts to action. Enforces: one contact per company, orders by AUM, validates channel availability (email/LinkedIn).
- **`services/state_machine.py`** — Contact status transitions (queued → in_progress → replied/completed/unsubscribed). Auto-activates next contact at same company when one reaches terminal state.
- **`services/compliance.py`** — CAN-SPAM footer injection, GDPR email limits (max 2 vs 3), unsubscribe link generation.
- **`services/template_engine.py`** — Jinja2 rendering with compliance integration. Injects `deep_research` key into template context when available.
- **`services/deep_research_service.py`** — Per-company deep research pipeline. Runs parallel Perplexity Sonar queries, synthesizes with Claude Sonnet into structured JSON (talking points, key people, crypto signals), enriches CRM contacts from output. Statuses: pending → researching → synthesizing → completed/failed/cancelled.
- **`web/routes/deep_research.py`** — Deep research API: POST trigger, GET latest, POST cancel (prefix: `/research/deep`).
- **`models/campaigns.py`** — All CRUD for companies, contacts, campaigns, templates, enrollment, events. All functions require `user_id` keyword argument for data isolation.
- **`services/gmail_sender.py`** — Gmail API email sending via OAuth tokens. Token refresh handled by caller (`email_sender.py`).
- **`services/token_encryption.py`** — Fernet encrypt/decrypt for OAuth tokens and SMTP passwords at rest. Requires `TOKEN_ENCRYPTION_KEY` env var.
- **`web/routes/gmail_oauth.py`** — Gmail OAuth connect/callback/disconnect flow. CSRF protection via `oauth_states` table.

### Database

PostgreSQL on Supabase via `psycopg2` with `RealDictCursor`. Key tables: `companies`, `contacts`, `campaigns`, `sequence_steps`, `templates`, `contact_campaign_status`, `events`, `dedup_log`, `deep_research`, `users`, `oauth_states`. Schema in `migrations/pg/001_initial_schema.sql`. Multi-tenancy schema in `migrations/pg/014_multi_tenancy.sql` and `migrations/pg/017_full_multi_tenancy.sql`. Deep research schema in `migrations/pg/016_deep_research.sql`. Migrations run automatically on every CLI command. Connection URL configured via `SUPABASE_DB_URL` env var.

Normalized fields (`email_normalized`, `linkedin_url_normalized`, `name_normalized`) are used for dedup and lookups — always populate these alongside raw fields.

**Multi-tenancy**: All root tables have `user_id NOT NULL` column. Tables with direct `user_id`: companies, contacts, campaigns, templates, tags, products, newsletters, research_jobs, deep_research, deals, events, dedup_log, engine_config. Child tables (sequence_steps, contact_campaign_status, entity_tags, etc.) inherit isolation via FK. Unique constraints are per-user (e.g., `UNIQUE(user_id, email_normalized)` on contacts). Registration is invite-only via `allowed_emails` table.

### Config

- `config.yaml` — SMTP settings, calendly URL, physical address, GDPR country list (see `config.yaml.example`)
- `.env` — SUPABASE_DB_URL, SMTP_PASSWORD, EMAIL_VERIFY_API_KEY, ANTHROPIC_API_KEY, PERPLEXITY_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, TOKEN_ENCRYPTION_KEY (see `.env.example`)
- CLI loads config in `src/cli.py` and injects SMTP password from env. CLI uses `CLI_USER_ID = 1` (founder's tool, single-user).

## Conventions

- **Database access**: Use `psycopg2.extras.RealDictCursor` (rows are dicts). Use `%s` placeholders (not `?`). Call `run_migrations(conn)` before any DB operations. Use `cursor = conn.cursor(); cursor.execute(...)` pattern (not `conn.execute()`). Use `scoped_query()`/`scoped_query_one()`/`verify_ownership()` helpers from `models/database.py` for user-scoped queries.
- **Multi-tenancy**: ALL model functions require `user_id` as keyword-only parameter. ALL database queries on user-owned tables MUST include `WHERE user_id = %s`. ALL `INSERT` statements on user-owned tables MUST include `user_id`. In routes, get user_id from `user["id"]` via `get_current_user()`. In CLI, use `CLI_USER_ID = 1`. In services, accept `user_id` parameter and pass through to model calls.
- **CLI commands**: Hyphenated names (`import-csv`), Python functions underscored (`import_csv`). All defined in `src/cli.py`.
- **GDPR handling**: Companies and contacts carry `is_gdpr` flag. Sequence steps have `gdpr_only`/`non_gdpr_only` flags to skip steps per jurisdiction.
- **A/B testing**: Templates use `variant_group` and `variant_label`. Contacts assigned variant on enrollment via round-robin.
- **Testing**: Tests use `tmp_db` fixture from `conftest.py` backed by `testing.postgresql` (ephemeral PG instance, session-scoped, tables truncated between tests). Mock SMTP and HTTP calls. Requires local PostgreSQL installation (e.g., `brew install postgresql@16`). Run with `PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" make test`.
- **Output**: Use Rich library (tables, panels, console) for all terminal output in commands.

## Data protection

Real contact data, database files, and credentials are gitignored. Never commit `.env`, `*.db`, or files in `data/imports/`.

## Frontend (React + Tailwind)

Tech stack: React 18, React Router 6, TanStack React Query 5, Tailwind CSS 3.4, dnd-kit, TypeScript, Vite. Source in `frontend/src/`.

### Design Tokens

No custom tailwind.config.js extensions yet — uses default Tailwind palette. These are the semantic color mappings to follow:

| Token | Tailwind | Hex | Usage |
|-------|----------|-----|-------|
| Primary | gray-900 | #111827 | Sidebar bg, primary buttons, page titles |
| Accent | blue-600 / blue-700 hover | #2563EB / #1D4ED8 | Links, CTAs, focus rings |
| Success | green-600 | #16A34A | Verified, positive replies, won deals |
| Warning | amber-600 | #D97706 | GDPR flags, no-response states |
| Error | red-600 | #DC2626 | Bounced, negative replies, delete |
| Surface | white / gray-50 | #FFFFFF / #F9FAFB | Cards / page background |
| Border | gray-200 / gray-100 | #E5E7EB / #F3F4F6 | Card borders / row dividers |
| Text | gray-900 / gray-500 / gray-400 | — | Primary / secondary / tertiary |

### Component Patterns

- **Cards (MetricCard)**: `bg-white rounded-lg shadow-sm border-l-4 p-4`. Label: `text-sm font-medium text-gray-500`. Value: `text-2xl font-bold`. Accent border variants: green-400, blue-400, yellow-400, red-400, default gray-200.
- **Badges (StatusBadge)**: `rounded-full px-2 py-0.5 text-xs font-medium capitalize inline-block`. 10 status-color pairs (queued=gray, in_progress=blue, replied_positive=green, replied_negative=red, no_response=yellow, bounced=red, active=green, completed=gray, drafted=blue, sent=green).
- **Buttons**: Primary dark: `bg-gray-900 text-white rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-gray-800`. Primary blue: `bg-blue-600 text-white rounded text-sm font-medium px-3 py-1.5 hover:bg-blue-700 disabled:opacity-50`. Secondary: `bg-white border border-gray-200 text-gray-700 rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-gray-50`.
- **Tables**: Container: `bg-white rounded-lg border border-gray-200 overflow-hidden`. Header: `bg-gray-50 border-b`, text: `text-xs font-medium text-gray-500 uppercase tracking-wide`. Rows: `divide-y divide-gray-100 hover:bg-gray-50 transition-colors`. Cell padding: `px-5 py-4` (body), `px-5 py-3` (header).
- **Navigation**: Dark sidebar `w-56 bg-gray-900`. Links: `text-sm font-medium text-gray-300`, active: `bg-gray-800 text-white`, hover: `hover:bg-gray-800/50 hover:text-white`.
- **DeepResearchBrief**: 4-state component (idle/running/completed/failed) on CompanyDetail page. Triggers and displays per-company deep research results (talking points, key people, crypto signals).

### Layout

- Shell: fixed sidebar (w-56, 224px) + scrollable main (flex-1, overflow-y-auto)
- Content: `max-w-7xl mx-auto px-6 py-8`
- Stats grid: `grid grid-cols-2 md:grid-cols-4 gap-4`
- Section spacing: `space-y-8` between dashboard sections

### Brand Voice in UI Copy

Follow the lemlist-inspired brand guidelines in `.claude/brand-voice-guidelines.md`. Key rules for UI text:

- Active voice always: "Scan for Replies" not "Replies can be scanned"
- Outcome-first labels: "Verified Emails" not "Email Verification Status"
- Specific numbers over adjectives: "Found 3 new replies" not "Successfully updated"
- Concise CTAs that state what happens: "Open Today's Queue" not "Click here to view"
- Never use: "revolutionary", "game-changing", "leverage", "synergy"

### Known Gaps (prioritized)

1. **No mobile responsive sidebar** — add collapsible sidebar at md: breakpoint (High)
2. **No focus-visible styles** — add `focus-visible:ring-2 ring-blue-500 ring-offset-2` globally (High)
3. **No ARIA landmarks** — add `<nav>`, `<main>`, `<aside>` with labels (High)
4. **Bare loading/empty/error states** — add skeleton loaders, illustrated empties, error cards with retry (High)
5. **Button inconsistencies** — standardize border-radius and padding, extract `<Button>` component (Medium)
6. **No nav icons** — add Lucide React icons to sidebar items (Medium)
7. **No trend indicators on Dashboard** — add sparklines or deltas to MetricCards (Medium)
8. **PageFallback is plain text** — replace with skeleton loader (Medium)

Full specs with pixel-level detail: `Design-Handoff-Specs.docx`
