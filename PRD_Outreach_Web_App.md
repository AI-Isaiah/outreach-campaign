# PRD: Metaworld Fund Outreach Campaign Web Application

**Version:** 1.0
**Author:** Product & Engineering
**Date:** March 3, 2026
**Status:** Draft — for handoff to Claude Code

---

## 1. Problem Statement

The Metaworld Fund outreach team currently manages a multi-channel campaign (email + LinkedIn) through a Python CLI tool. While the backend logic is solid (priority queue, state machine, compliance, A/B testing, deduplication), the CLI interface creates friction: there is no visual dashboard, no way to preview/edit email drafts before sending, no integrated LinkedIn workflow, and no feedback loop that automatically improves messaging based on response outcomes.

The team needs a **web-based application** that wraps the existing backend services with a modern UI, adds Gmail Draft integration (so emails land in Gmail Drafts for manual review before send), and provides a unified view of email + LinkedIn sequences with response-based iteration.

**Who is affected:** Helmut (sole operator, 183cm tall — ergonomic large-screen UI preferred), running outreach to ~875 crypto fund allocators.

**Impact of not solving:** Manual CLI workflow limits daily throughput, makes it hard to spot patterns in responses, and prevents iterating on messaging at scale.

---

## 2. Goals

1. **Replace CLI with a web dashboard** — all 24 CLI commands accessible via UI with visual feedback (tables, charts, status cards)
2. **Gmail Draft integration** — emails are created as Gmail Drafts (via Gmail API) instead of being sent directly via SMTP; operator reviews and sends manually
3. **Unified email + LinkedIn sequence view** — one timeline per contact showing both channels, with LinkedIn profile links and pre-written messages ready to copy
4. **Response-based messaging iteration** — track positive/negative/no-response outcomes and surface aggregate patterns to inform template improvements
5. **Reduce daily workflow to <15 minutes** — from queue review to draft creation to LinkedIn action prep

---

## 3. Non-Goals

1. **Automated LinkedIn sending** — LinkedIn actions remain manual (copy message, visit profile, use Sales Navigator). No browser automation or API integration with LinkedIn.
2. **Real-time email tracking** (open/click) — no tracking pixels; we keep the current clean-email philosophy.
3. **Multi-user / team features** — single-operator tool. No auth system, roles, or collaboration.
4. **CRM replacement** — this is a campaign execution tool, not a full CRM. No deal stages, pipeline forecasting, or revenue tracking.
5. **Mobile-first design** — desktop-first (large screen). Mobile is nice-to-have, not a priority.

---

## 4. User Stories

### As the Campaign Operator, I want to...

**Daily workflow:**
- **See today's queue** as a visual dashboard with contact cards showing name, company, AUM, channel (email/LinkedIn), step number, and GDPR status — so I can plan my daily outreach in 30 seconds
- **Preview and edit email drafts** before they're pushed to Gmail — so I can personalize each message and catch template errors
- **Push approved emails to Gmail Drafts** with one click — so I just open Gmail and hit Send
- **See LinkedIn actions** with the contact's LinkedIn profile URL (clickable), the pre-written message (copyable), and a "Mark as Done" button — so I can execute LinkedIn outreach from Sales Navigator
- **Log responses** (positive / negative / no response) per contact with one click — so the state machine advances and the next contact at the company auto-activates

**Campaign management:**
- **View a campaign dashboard** with key metrics: enrolled count, emails sent, LinkedIn actions, reply rates, positive rates, A/B variant comparison, firm-type breakdown — so I can see what's working
- **Edit email templates** inline with a live preview — so I can iterate on messaging without touching template files
- **See a per-contact timeline** showing every touchpoint (email sent, LinkedIn connect, LinkedIn message, response logged) — so I understand the full conversation history
- **Import new contacts** via CSV upload in the browser — so I don't need the CLI for imports

**Iteration & learning:**
- **View aggregate response data** by template variant, firm type, AUM tier, and sequence step — so I can identify which messages perform best
- **Compare A/B variants** side-by-side with reply rates and positive rates — so I can pick winners and iterate on losers
- **See a "lessons learned" panel** that summarizes: which subject lines get replies, which firm types respond best, which step in the sequence converts most — so I can continuously improve

---

## 5. Architecture: Build on Existing Backend

### 5.1 What to Keep (Reuse Entirely)

The existing Python backend is well-structured and should be kept as-is, exposed via a FastAPI layer:

| Existing Module | Reuse As |
|---|---|
| `models/database.py` | SQLite connection + migrations (unchanged) |
| `models/campaigns.py` | All CRUD operations (unchanged) |
| `services/priority_queue.py` | Daily queue algorithm (unchanged) |
| `services/state_machine.py` | Status transitions + auto-activation (unchanged) |
| `services/deduplication.py` | 3-pass dedup pipeline (unchanged) |
| `services/compliance.py` | CAN-SPAM/GDPR logic (unchanged) |
| `services/ab_testing.py` | Variant assignment + stats (unchanged) |
| `services/template_engine.py` | Jinja2 rendering (unchanged) |
| `services/metrics.py` | Campaign metrics + reporting (unchanged) |
| `services/newsletter.py` | Newsletter management (unchanged) |
| `migrations/001_initial_schema.sql` | Database schema (unchanged) |
| `src/templates/` | All email + LinkedIn Jinja2 templates (unchanged) |

### 5.2 What to Modify

| Module | Change |
|---|---|
| `services/email_sender.py` | Add `create_gmail_draft()` alongside existing `send_email()`. Uses Gmail API to create draft instead of SMTP send. Keep SMTP as fallback option. |
| `src/cli.py` | Keep the CLI working as-is. The web app is an additional interface, not a replacement. |

### 5.3 What to Add

| New Component | Purpose |
|---|---|
| `src/api/` | FastAPI app exposing all services as REST endpoints |
| `src/api/routes/` | Route modules: `queue.py`, `campaigns.py`, `contacts.py`, `templates.py`, `gmail.py`, `import_routes.py` |
| `src/services/gmail_drafter.py` | Gmail API integration — create drafts, list drafts, check sent status |
| `frontend/` | React (Vite) single-page app |
| `migrations/002_web_app.sql` | Schema additions for draft tracking, response notes |

### 5.4 Tech Stack

**Backend:**
- FastAPI (Python) wrapping existing services
- SQLite (existing database, unchanged)
- Gmail API (via google-auth + google-api-python-client) for draft creation
- Existing Jinja2 templates for rendering

**Frontend:**
- React 18 + TypeScript
- Vite for build tooling
- Tailwind CSS for styling
- React Router for navigation
- TanStack Query for data fetching
- Recharts for metrics visualization

---

## 6. Requirements

### P0 — Must-Have (MVP)

#### 6.1 Dashboard Home
- Daily queue view: cards or table showing today's actions, grouped by channel
- Campaign-level metrics summary (enrolled, sent, replied, positive rate)
- Quick-action buttons: "Push All Drafts to Gmail", "Export LinkedIn Actions"
- **Acceptance criteria:** Page loads in <1s, shows the same data as `make queue`

#### 6.2 Queue & Daily Actions
- Visual queue matching existing `priority_queue.py` output
- For each email action: show rendered email preview (subject + body with contact data filled in)
- Inline edit capability: modify subject/body before pushing to Gmail Draft
- For each LinkedIn action: show LinkedIn profile URL (clickable, opens in new tab), pre-rendered message (copyable to clipboard)
- "Mark Done" button for LinkedIn actions → logs event + advances step
- **Acceptance criteria:** Operator can process 20 daily actions in <10 minutes

#### 6.3 Gmail Draft Integration
- OAuth2 flow to authorize Gmail API access (one-time setup)
- "Push to Gmail Draft" per email → creates draft in Gmail with correct To, Subject, Body
- "Push All Drafts" batch button → creates all today's email drafts at once
- Track which drafts have been pushed (prevent duplicates)
- Status indicator: "Draft Created", "Sent" (detected via Gmail API check)
- **Acceptance criteria:** Drafts appear in Gmail within 5 seconds of pushing

#### 6.4 Response Logging
- Per-contact action: log "Positive Reply", "Negative Reply", "No Response", "Call Booked"
- State machine transitions happen automatically (reuse existing `state_machine.py`)
- Auto-activates next contact at same company on terminal states
- Optional free-text note field for response context (e.g., "Said to follow up in Q3")
- **Acceptance criteria:** Status transition matches CLI behavior exactly

#### 6.5 Contact Timeline
- Per-contact page showing full history: all events (email_sent, linkedin_connected, reply logged, status changes)
- Contact details: name, email, LinkedIn URL, company, AUM, GDPR status, email verification status
- Current campaign status and step
- **Acceptance criteria:** Every event from the `events` table is visible

#### 6.6 Campaign Report
- Mirrors existing `report` command output as a visual dashboard
- Metrics: total enrolled, by-status breakdown, reply rate, positive rate
- A/B variant comparison table
- Firm-type breakdown table
- Weekly trend chart (emails sent, replies received over time)
- **Acceptance criteria:** All data from `metrics.py` is displayed

### P1 — Nice-to-Have

#### 6.7 Template Editor
- List all templates with channel, variant group, variant label
- Inline editing with Jinja2 syntax highlighting
- Live preview with sample contact data
- Create new template variants for A/B testing

#### 6.8 CSV Import via Browser
- File upload widget for CSV import
- Preview table showing parsed contacts before import
- Dedup summary after import
- Progress indicator for large files

#### 6.9 Response Analytics & Iteration Insights
- Aggregate response rates by: template variant, firm type, AUM tier ($0-100M, $100M-500M, $500M-1B, $1B+), sequence step number, GDPR vs non-GDPR
- "What's working" summary panel highlighting top-performing variants
- Suggested iteration: "Variant A outperforms B by 2x on positive replies — consider retiring B"

#### 6.10 LinkedIn Sales Navigator Integration View
- For each LinkedIn action, show a formatted card with: profile photo placeholder, name, title, company, mutual connections count (if available from CSV data)
- Deep link to Sales Navigator search pre-filled with the contact's name + company
- **Note:** No API integration — this is just smart URL construction

### P2 — Future Considerations

- **Email scheduling** — push drafts with a "send at" time
- **Slack notifications** — daily queue summary posted to Slack
- **Multi-campaign comparison** — side-by-side metrics across campaigns
- **AI-powered template suggestions** — use response data to auto-generate improved email variants via LLM
- **Calendar integration** — link call-booked responses to Calendly events

---

## 7. Database Schema Additions

```sql
-- Migration 002: Web app additions

-- Track Gmail drafts
CREATE TABLE IF NOT EXISTS gmail_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    template_id INTEGER REFERENCES templates(id),
    gmail_draft_id TEXT,              -- Gmail API draft ID
    gmail_message_id TEXT,            -- Gmail API message ID (after send)
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    body_html TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, drafted, sent, failed
    pushed_at TEXT,
    sent_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(contact_id, campaign_id, template_id)
);

-- Response notes (free-text context for logged responses)
CREATE TABLE IF NOT EXISTS response_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    note TEXT NOT NULL,
    response_type TEXT,   -- positive, negative, no_response, call_booked
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_gmail_drafts_status ON gmail_drafts(status);
CREATE INDEX IF NOT EXISTS idx_gmail_drafts_contact ON gmail_drafts(contact_id);
CREATE INDEX IF NOT EXISTS idx_response_notes_contact ON response_notes(contact_id);
```

---

## 8. API Design (FastAPI Routes)

```
GET  /api/queue/{campaign}?date=YYYY-MM-DD&limit=20    → Daily queue
GET  /api/campaigns                                      → List campaigns
GET  /api/campaigns/{name}/metrics                       → Campaign metrics
GET  /api/campaigns/{name}/weekly                        → Weekly summary
GET  /api/contacts/{id}                                  → Contact detail + timeline
GET  /api/contacts/{id}/events                           → Contact event history
POST /api/contacts/{id}/status                           → Log response (body: {outcome, note?})
GET  /api/templates                                      → List templates
PUT  /api/templates/{id}                                 → Update template
POST /api/templates                                      → Create template

POST /api/gmail/authorize                                → Start OAuth2 flow
GET  /api/gmail/callback                                 → OAuth2 callback
POST /api/gmail/drafts                                   → Push email(s) to Gmail Draft
GET  /api/gmail/drafts/{contact_id}                      → Check draft/sent status
POST /api/gmail/drafts/batch                             → Push all today's email drafts

POST /api/import/csv                                     → Upload CSV
POST /api/import/dedupe                                  → Run dedup pipeline
GET  /api/stats                                          → Database statistics
```

---

## 9. Frontend Pages

| Route | Page | Key Components |
|---|---|---|
| `/` | Dashboard | Metrics cards, today's queue summary, quick actions |
| `/queue` | Daily Queue | Action cards with email preview/edit + LinkedIn cards |
| `/queue/:id/edit` | Edit Draft | Full email editor with live preview |
| `/campaigns` | Campaign List | Campaign cards with status |
| `/campaigns/:name` | Campaign Report | Metrics dashboard, charts, A/B comparison |
| `/contacts` | Contact List | Searchable/filterable table |
| `/contacts/:id` | Contact Detail | Timeline, info card, response logging |
| `/templates` | Template Manager | List, edit, preview, create |
| `/settings` | Settings | Gmail auth, config display |

---

## 10. Interconnected Email + LinkedIn Sequence

The core sequence alternates between channels to create multiple touchpoints. See the companion document `Outreach_Sequence_Plan.md` for the full 7-step sequence with email copy, LinkedIn messages, timing, and branching logic.

**Sequence overview:**

| Step | Day | Channel | Action |
|---|---|---|---|
| 1 | 0 | LinkedIn | Send connection request with note |
| 2 | 2 | Email | Cold outreach (A/B variants) |
| 3 | 5 | LinkedIn | Send follow-up DM (if connected) |
| 4 | 9 | Email | Follow-up email (value reinforcement) |
| 5 | 14 | LinkedIn | Engage with their content / send insight |
| 6 | 18 | Email | Breakup email (door open) |
| 7 | 25 | LinkedIn | Final soft touch (if connected) |

**Response branching:**
- **Positive reply** (any channel) → EXIT sequence → log call_booked → move to meeting prep
- **Negative reply** → EXIT sequence → mark `replied_negative` → auto-activate next contact at company
- **No response** after full sequence → mark `no_response` → auto-activate next contact → add to newsletter if non-GDPR

---

## 11. Gmail Draft Integration Detail

### Authentication Flow
1. User clicks "Connect Gmail" in Settings
2. Backend initiates OAuth2 flow with scopes: `gmail.compose`, `gmail.readonly`
3. User authorizes in browser popup
4. Backend stores refresh token securely (encrypted in `.env` or SQLite)
5. Token auto-refreshes; UI shows "Gmail Connected" status

### Draft Creation Flow
1. Operator reviews email in Queue view
2. Optionally edits subject/body
3. Clicks "Push to Gmail Draft"
4. Backend calls `gmail.users.drafts.create()` with:
   - `to`: contact email
   - `subject`: rendered subject
   - `body`: rendered HTML (with compliance footer)
5. Stores `gmail_draft_id` in `gmail_drafts` table
6. UI updates status to "Draft Created" with link to Gmail

### Sent Detection
- Periodic background check (every 5 min or on-demand): query Gmail API for draft status
- If draft no longer exists but message ID found in Sent folder → mark as "Sent"
- Log `email_sent` event in database, advance contact step

---

## 12. Success Metrics

**Leading indicators (change within weeks):**
- Daily actions processed per session: target **20+ actions in <15 minutes**
- Drafts pushed to Gmail per day: target **10-15**
- LinkedIn actions completed per day: target **10-15**
- Time from queue review to all actions complete: target **<15 minutes**

**Lagging indicators (change over months):**
- Campaign positive reply rate: target **>5%** (up from current baseline)
- Calls booked per week: target **2-3**
- Template iteration velocity: target **new variant tested every 2 weeks**
- Contact coverage: target **process 100% of daily queue** (no skips)

---

## 13. Open Questions

| Question | Owner | Notes |
|---|---|---|
| Should we use Gmail API or keep SMTP as primary? | Engineering | Gmail Draft is the UX preference, but SMTP is simpler for bulk. Recommendation: Gmail Draft for outreach, SMTP for newsletters. |
| How to handle Gmail API rate limits? | Engineering | Gmail API allows 250 quota units/second. Draft creation = 10 units. At 15 drafts/day this is not an issue. |
| Should the web app run locally or be deployed? | Helmut | Recommendation: local (localhost:3000 + localhost:8000) for data privacy. All contact data stays on machine. |
| Do we need email open tracking in the future? | Product | Current philosophy is no tracking pixels. Revisit if reply rates plateau. |
| Should we keep the CLI working alongside the web app? | Engineering | Yes — the CLI and web app share the same database and services. Both interfaces should work simultaneously. |

---

## 14. Implementation Phases

### Phase 1: API Layer + Dashboard (Week 1-2)
- FastAPI app wrapping existing services
- Dashboard home, queue view, campaign report
- Contact detail + timeline
- Response logging via UI
- All existing tests pass

### Phase 2: Gmail Draft Integration (Week 3)
- Gmail OAuth2 setup
- Draft creation + batch push
- Sent detection
- Draft status tracking in DB

### Phase 3: LinkedIn Workflow + Template Editor (Week 4)
- LinkedIn action cards with profile links + copyable messages
- Sales Navigator deep links
- Template editor with live preview
- A/B variant management

### Phase 4: Analytics & Iteration (Week 5)
- Response analytics dashboard
- Aggregate insights by variant/firm-type/AUM tier
- "What's working" panel
- CSV import via browser

---

## 15. Technical Notes for Claude Code

### Project structure to create:

```
outreach-campaign/
├── (all existing files unchanged)
├── src/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app, CORS, startup
│   │   ├── dependencies.py      # DB connection dependency
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── queue.py
│   │       ├── campaigns.py
│   │       ├── contacts.py
│   │       ├── templates.py
│   │       ├── gmail.py
│   │       ├── import_routes.py
│   │       └── stats.py
│   └── services/
│       └── gmail_drafter.py     # NEW: Gmail API draft creation
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/                 # API client functions
│       ├── components/          # Shared UI components
│       ├── pages/               # Route pages
│       └── types/               # TypeScript interfaces
├── migrations/
│   ├── 001_initial_schema.sql   # (existing)
│   └── 002_web_app.sql          # (new)
└── Makefile                     # Add: make api, make frontend, make dev
```

### Key constraints:
- **Do NOT modify existing service files** unless explicitly needed (e.g., `email_sender.py` for Gmail Draft addition)
- **Keep CLI working** — the web app is additive
- **SQLite remains the database** — no PostgreSQL migration
- **All existing tests must pass** after changes
- **Run locally** — no cloud deployment, no Docker required for MVP
