# Claude Code Briefing: Build the Outreach Campaign Web App

**Date:** March 3, 2026
**For:** Claude Code (autonomous execution — the operator cannot program)
**Input documents:** `FINAL_HANDOFF_Claude_Code.md` (spec) + `ENGINEERING_REVIEW_REPORT.md` (bugs to fix)

---

## What This Project Is

A web app (FastAPI + React) for managing email + LinkedIn outreach to ~875 crypto fund allocators. There's an existing Python CLI tool that works. You're building a web UI on top of it, plus an adaptive engine that learns which messages work best, Gmail Draft integration, a built-in CRM, and WhatsApp message capture.

The operator (Helmut) runs this locally on his MacBook. Single user, no auth, no cloud deployment.

---

## How to Use This Briefing

1. **Read `FINAL_HANDOFF_Claude_Code.md` first** — it is the single source of truth for the full spec (architecture decisions, adaptive engine logic, database schema, API endpoints, file structure, UI design tokens, everything).
2. **Read `ENGINEERING_REVIEW_REPORT.md` second** — it identifies 3 critical bugs and 7 high-severity issues in the existing codebase that MUST be fixed as you build.
3. **Follow the phases below in order.** Each phase has concrete deliverables and a "done when" checklist. Do not skip ahead.
4. **Run tests after every phase.** The existing test suite must keep passing. Add new tests for new code.
5. **Commit after each phase.** Clear commit messages explaining what was built.

---

## Critical Bugs to Fix (from Engineering Review)

These affect the existing codebase and MUST be resolved in Phase 0:

### BUG-1: Boolean Type Mismatch
The schema uses `INTEGER` for boolean columns (`is_gdpr`, `unsubscribed`, `is_active`, `gdpr_only`, `non_gdpr_only`). PostgreSQL needs `BOOLEAN`. All code uses `0/1` instead of `true/false`.

**Fix:** Change schema columns to `BOOLEAN`. Search the entire codebase for `= 1`, `= 0`, `1 if`, `0 if` patterns on these fields and replace with `= true`, `= false`, direct boolean values.

**Files affected:** `migrations/pg/001_initial_schema.sql`, `src/cli.py`, `src/models/campaigns.py`, `src/services/priority_queue.py`, `src/services/compliance.py`, `src/services/deduplication.py`

### BUG-2: TEXT Timestamps
All `created_at`/`updated_at` columns are `TEXT NOT NULL DEFAULT NOW()`. They should be `TIMESTAMPTZ`.

**Fix:** Change all timestamp columns in `001_initial_schema.sql` to `TIMESTAMPTZ NOT NULL DEFAULT NOW()`.

### BUG-3: Connection Leaks
CLI commands open DB connections but don't close them if an error occurs (no `try/finally`).

**Fix:** Wrap every CLI command body that uses a DB connection in `try: ... finally: conn.close()`.

### Additional High-Severity Fixes (do during Phase 0-1):
- **Race condition in state_machine.py:** `_activate_next_contact()` needs `SELECT ... FOR UPDATE` to prevent double-enrollment.
- **Missing ON DELETE CASCADE:** Add to all foreign keys in schema.
- **Unsubscribe matches raw email:** `compliance.py` should match on `email_normalized`, not raw `email`.
- **N+1 query in priority_queue.py:** Join step count into the main query instead of calling `count_steps_for_contact()` per result.
- **Missing indexes:** Add index on `contact_campaign_status(campaign_id)` and compound index on `events(contact_id, campaign_id)`.

### ADR-004 Fix: Gmail Reply Detection
The handoff doc says "query for threads where `to:` matches enrolled contacts" — this won't work with Gmail API. The correct approach is: search with `from:{contact.email}` in INBOX, filter by thread message count > 1, only classify messages after `contact_campaign_status.enrolled_at`. Implement it this way.

---

## Phase 0: Supabase Migration + Bug Fixes

**Goal:** Existing CLI works against PostgreSQL with all bugs fixed.

**Do this:**
1. Rewrite `migrations/pg/001_initial_schema.sql` for proper PostgreSQL:
   - `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY`
   - All boolean columns → `BOOLEAN NOT NULL DEFAULT false`
   - All timestamp columns → `TIMESTAMPTZ NOT NULL DEFAULT NOW()`
   - Add `ON DELETE CASCADE` to all foreign keys
   - Add missing indexes (see Engineering Review)
2. Fix all boolean comparisons across the codebase (`= 1` → `= true`, etc.)
3. Fix all `1 if x else 0` → direct boolean in Python
4. Add `try/finally` for `conn.close()` in all CLI commands
5. Fix `_activate_next_contact()` with `SELECT ... FOR UPDATE`
6. Fix `process_unsubscribe()` to match on `email_normalized`
7. Eliminate N+1 in `priority_queue.py`
8. Run `make test` — all existing tests must pass

**Done when:** `make test` passes, `python3 -m src.cli queue --help` works, schema has proper BOOLEAN/TIMESTAMPTZ types.

---

## Phase 1: Backend API + CRM Routes

**Goal:** FastAPI backend wrapping all existing services, plus CRM endpoints.

**Do this:**
1. Create `src/api/main.py` — FastAPI app with CORS (localhost origins)
2. Create `src/api/dependencies.py` — DB connection dependency (yields connection, closes in finally)
3. Create `migrations/pg/002_web_app.sql` — all new tables from FINAL_HANDOFF Section 3.6 (contact_template_history, advisor_runs, gmail_drafts, pending_replies, response_notes, engine_config, whatsapp_messages, whatsapp_scan_state, phone columns, interaction_timeline_view)
4. Create route modules in `src/api/routes/` for all endpoints listed in FINAL_HANDOFF Section 3.7
5. Include CRM routes: contact list with filters, unified timeline via `interaction_timeline_view`, company detail, global search
6. Add `make api` target to Makefile (runs `uvicorn src.api.main:app --reload --port 8000`)
7. Write `tests/test_api.py` — test all endpoints

**Done when:** `make api` starts, `curl localhost:8000/api/campaigns` returns data, CRM search works, all tests pass.

---

## Phase 2: React Frontend + CRM Views

**Goal:** Full React UI connected to the API.

**Do this:**
1. Initialize `frontend/` with Vite + React 18 + TypeScript + Tailwind CSS
2. Create `frontend/src/api/client.ts` — fetch wrapper for all API endpoints
3. Build all pages listed in FINAL_HANDOFF Section 3.8:
   - Dashboard (metric cards, today's queue summary, pending replies)
   - Queue (action cards for email + LinkedIn)
   - Contact Detail (with `UnifiedTimeline` component showing all interactions)
   - Company Detail (contacts list, aggregated activity)
   - Campaign Report (metrics, A/B comparison, firm-type breakdown)
   - Templates (list view)
   - Settings
4. Build Sidebar with global search
5. Use design tokens from FINAL_HANDOFF Appendix (slate-900 sidebar, Inter font, etc.)
6. Add `make frontend` target (`cd frontend && npm run dev`) and `make dev` (runs API + frontend concurrently)

**Done when:** `make dev` starts both servers, dashboard loads with real data, contact timeline shows events, company detail shows contacts, global search returns results.

---

## Phase 3: Adaptive Engine

**Goal:** Smart queue that recommends the best next action per contact.

**Do this:**
1. Create `src/services/response_analyzer.py` — compute template performance scores (positive_rate per template, channel performance, segment performance, timing performance) as described in FINAL_HANDOFF Section 2.2 Step 1
2. Create `src/services/contact_scorer.py` — composite priority score (0.4 AUM + 0.3 segment + 0.2 channels + 0.1 recency) as described in Section 2.2 Step 2
3. Create `src/services/template_selector.py` — explore/exploit selection with Thompson Sampling. Explore rates: 30% at <50 sends, 15% at 50-150, 5% at 150+. Never send same template to same contact twice. Log selection_mode.
4. Create `src/services/adaptive_queue.py` — assembles recommendations per contact (channel, template, rendered content, reasoning, alternatives)
5. Implement channel rules from Section 2.3 (LinkedIn first, never 3 same-channel in a row, prefer higher-performing channel per segment)
6. Update Queue API route to use adaptive queue
7. Update Queue page to show reasoning + alternatives + override button
8. Write tests: `test_response_analyzer.py`, `test_contact_scorer.py`, `test_template_selector.py`, `test_adaptive_queue.py`

**Cold-start strategy:** When no data exists, default to first template by `created_at ASC`. "Sends" for exploration thresholds = total campaign sends (not per-template).

**Done when:** Queue page shows recommended template with reasoning, explore/exploit mode is visible, operator can override, tests pass.

---

## Phase 4: Gmail Integration + Reply Detection + LLM Advisor

**Goal:** Push email drafts to Gmail, auto-detect replies, LLM-powered insights.

**Do this:**
1. Create `src/services/gmail_drafter.py`:
   - OAuth2 flow with `google-auth` + `google-api-python-client`
   - Scopes: `gmail.compose` + `gmail.readonly`
   - `create_draft()` — creates Gmail draft from rendered email content
   - `batch_create_drafts()` — push all today's email actions
   - Store draft status in `gmail_drafts` table
2. Create `src/services/reply_detector.py`:
   - **IMPORTANT:** Search Gmail with `from:{contact.email}` in INBOX (NOT `to:` — see ADR-004 fix above)
   - Filter threads with message count > 1
   - Only process messages after `enrolled_at`
   - Deduplicate by `gmail_message_id`
   - Call Claude API to classify: positive/negative/neutral with confidence + summary
   - Store in `pending_replies` table
3. Set up background scan (FastAPI BackgroundTasks, every 5 minutes)
4. Build Gmail OAuth flow in API (`/api/gmail/authorize`, `/api/gmail/callback`)
5. Build reply detection UI: "Reply detected" cards on dashboard with confirm/correct buttons
6. Create `src/services/llm_advisor.py`:
   - "Run Analysis" calls Claude API with all campaign data
   - Returns insights + template suggestions as JSON
   - "Add as Template" inserts new template into explore pool
7. Build Insights page
8. Add Gmail routes and reply routes to API

**Done when:** OAuth flow works, drafts appear in Gmail, replies are auto-detected and classified, operator can confirm/correct, "Run Analysis" returns insights, all tests pass.

---

## Phase 5: WhatsApp Integration

**Goal:** Capture WhatsApp messages via browser automation, display in CRM.

**Do this:**
1. `pip install playwright && playwright install chromium`
2. Create `src/services/whatsapp_scanner.py`:
   - `setup()` — opens Chromium with WhatsApp Web, operator scans QR code, session saved to `data/whatsapp_session/`
   - `scan()` — for each contact with `phone_normalized`, navigate to chat, extract messages (text, timestamp, direction), store new messages in `whatsapp_messages`
   - Match contacts by `phone_normalized` (E.164 format)
   - Handle failures gracefully — if WhatsApp blocks automation, log the error but don't crash
3. Create `src/api/routes/whatsapp.py` — setup, scan, status, messages endpoints
4. Build `WhatsAppMessageCard.tsx` — chat bubble styling (green outbound, white inbound)
5. WhatsApp messages should appear in `UnifiedTimeline` via the `interaction_timeline_view`
6. Add `make whatsapp-setup` and `make whatsapp-scan` targets
7. Add manual fallback: if automation breaks, operator can add notes manually in CRM

**Done when:** QR setup works, scan captures messages, messages appear in contact timeline, manual fallback works.

---

## Phase 6: Polish

**Goal:** Template editor, CSV import via browser, segment heatmap, phone number management.

**Do this:**
1. Template editor with live preview (P1.3)
2. CSV import with file upload, preview, dedup summary (P1.4)
3. Segment heatmap (P1.2)
4. Phone number bulk import from CSV (P1.9)
5. "What's Working" panel on dashboard (P1.6)
6. Engine parameter tuning in Settings (scoring weights, explore rate)

**Done when:** All P1 features working, full test suite passes.

---

## Environment Variables Needed

```bash
# Database (existing Supabase instance)
SUPABASE_DB_URL=postgresql://postgres:<password>@<host>:5432/postgres

# Existing
SMTP_PASSWORD=<secret>
EMAIL_VERIFY_API_KEY=<api-key>
EMAIL_VERIFY_PROVIDER=zerobounce

# New (Phase 4)
GMAIL_CLIENT_ID=<google-oauth-client-id>
GMAIL_CLIENT_SECRET=<google-oauth-client-secret>
GMAIL_REDIRECT_URI=http://localhost:8000/api/gmail/callback
ANTHROPIC_API_KEY=<claude-api-key>

# WhatsApp (Phase 5, auto-managed)
WHATSAPP_SESSION_DIR=data/whatsapp_session
WHATSAPP_SCAN_INTERVAL_MINUTES=30
```

The operator will provide the actual values when you reach the relevant phase. If a value is missing, ask — don't guess.

---

## Key Architectural Rules

1. **Never modify existing working services** unless fixing a bug. The adaptive engine layers ON TOP of existing modules.
2. **CLI must keep working.** It's the fallback if the web app has issues.
3. **All database access uses `psycopg2` with `RealDictCursor`** and `%s` parameter placeholders. No ORMs.
4. **Use `run_migrations(conn)` before any DB operations** — migrations run automatically.
5. **Use Rich library** for CLI output (tables, panels, console).
6. **React frontend:** Vite + React 18 + TypeScript + Tailwind CSS + Recharts for charts.
7. **Single operator, no auth** — no login system needed.
8. **GDPR compliance:** Max 2 emails for GDPR contacts, CAN-SPAM footer on all emails, unsubscribe links.
9. **Human-in-the-loop:** All LLM suggestions require operator approval. All emails go to Gmail Drafts for review.

---

## Testing

- Existing tests use `testing.postgresql` (ephemeral PG instance) — see `tests/conftest.py`
- Run with: `PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" make test`
- Add tests for every new module
- Mock SMTP, Gmail API, Claude API, and Playwright in tests

---

## How to Start

```bash
cd /path/to/outreach-campaign
# Read the spec
cat FINAL_HANDOFF_Claude_Code.md
# Read the bug report
cat ENGINEERING_REVIEW_REPORT.md
# Start Phase 0
```

Work through each phase sequentially. Commit after each phase. Test constantly. Ask the operator if anything is unclear — he'll answer questions but can't write code.
