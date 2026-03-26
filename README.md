# Outreach Campaign Manager

Multi-channel outreach campaign manager for crypto fund allocators. Multi-tenant Python web app (FastAPI + React) with CLI tool that manages email and LinkedIn outreach sequences with GDPR/CAN-SPAM compliance, A/B testing, deduplication, and email verification.

## Tech Stack

- **Backend:** Python 3.12+, FastAPI, psycopg2 (PostgreSQL)
- **Frontend:** React 18, TypeScript, Tailwind CSS, TanStack React Query 5
- **Database:** PostgreSQL on Supabase
- **Deployment:** Vercel (frontend + serverless API) + Supabase
- **AI:** Claude API (message drafting, research synthesis), Perplexity (deep research)

## Quick Start

```bash
# Install dependencies
make install                    # pip3 install -e ".[dev]"
cd frontend && npm install

# Set up environment
cp .env.example .env            # Fill in SUPABASE_DB_URL, API keys

# Run tests
PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" make test

# Start development servers
python3 -m src.cli web          # Backend on :8000
cd frontend && npm run dev      # Frontend on :5173
```

## Core Workflow

1. **Import contacts** via Smart Import (AI-powered CSV column detection)
2. **Create campaigns** with multi-step sequences (email + LinkedIn)
3. **Daily queue** generates prioritized outreach actions (one per company, AUM-ranked)
4. **Send emails** via Gmail OAuth or SMTP with CAN-SPAM compliance
5. **Track replies** — auto-detect via Gmail scanning, classify with AI
6. **Research** — deep company research via Perplexity + Claude synthesis

## Project Structure

```
src/
├── cli.py              # Typer CLI (24 commands)
├── commands/           # CLI command handlers
├── services/           # Business logic (36 service modules)
├── models/             # PostgreSQL CRUD operations
├── application/        # Orchestration services (queue, batch send)
├── web/                # FastAPI app + route modules
│   └── routes/         # API endpoints (20+ route files)
└── templates/          # Jinja2 email/LinkedIn templates

frontend/src/
├── pages/              # React pages (24 routes)
├── components/         # Shared UI components
├── api/                # API client modules
└── types/              # TypeScript type definitions

migrations/pg/          # PostgreSQL migrations (auto-run on startup)
tests/                  # pytest test suite (738 tests)
```

## Key Features

- **Multi-tenancy:** Row-level data isolation via `user_id` on all tables
- **Smart Import:** LLM-powered CSV column mapping with duplicate detection
- **AI Message Drafts:** Claude Haiku generates personalized outreach per contact
- **Deep Research:** Perplexity + Claude synthesis for company intelligence
- **Campaign Health Score:** 0-100 score computed from reply rate + velocity + bounces
- **Keyboard Shortcuts:** j/k/Enter/s/e navigation in the daily queue
- **Batch Send:** Approve → send all with idempotency guard (sent_at atomic lock)
- **Cron Infrastructure:** Vercel Cron for auto-reply scanning + scheduled sends
- **Fund Intelligence Signals:** Time-sensitive signals extracted from research data

## Documentation

- `CLAUDE.md` — AI assistant instructions and conventions
- `TODOS.md` — Prioritized roadmap (friction sweep)
- `.env.example` — Required environment variables
- `config.yaml.example` — SMTP and compliance configuration
