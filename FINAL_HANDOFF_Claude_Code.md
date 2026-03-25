# Final Handoff: Adaptive Outreach Campaign Web App

**For: Claude Code implementation**
**Date:** March 3, 2026
**Replaces:** PRD_Outreach_Web_App.md, Outreach_Sequence_Plan.md, Implementation_Plan_v2.md

This is the single source of truth. It contains three sections:

1. **Architecture Decision Record** — key technical decisions and trade-offs
2. **Adaptive Campaign Plan** — how the outreach engine works, channel strategy, feedback loops
3. **Product Specification** — complete feature spec with requirements, acceptance criteria, implementation order

---

# Section 1: Architecture Decision Record

## ADR-001: Adaptive Outreach Engine Architecture

**Status:** Accepted
**Date:** March 3, 2026
**Deciders:** Helmut (operator/founder)

### Context

We have a working Python CLI outreach tool with SQLite, Jinja2 templates, a priority queue, state machine, compliance engine, A/B testing, and metrics — all well-tested. The codebase already includes modifications for the web app transition:

- `email_sender.py` now has `render_campaign_email()` for previewing/drafting without sending
- `metrics.py` now tracks both legacy `expandi_*` and new `linkedin_*_done` event types

We need to add:
1. A web UI (replacing the CLI as primary interface)
2. An adaptive sequence engine (replacing static step sequences)
3. Gmail Draft integration (replacing direct SMTP for outreach emails)
4. An LLM advisor (for pattern analysis and template generation)

### Decision

**Build a FastAPI + React web app on top of the existing Python backend, with an adaptive decision engine that selects the optimal next action per contact based on accumulated response data.**

### Options Considered

#### Option A: Enhance CLI + Add Web Dashboard (Read-Only)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Cost | Minimal — just add a dashboard |
| Adaptiveness | None — still static sequences |
| Team familiarity | High — just Python |

**Pros:** Fast to build, low risk, CLI stays primary
**Cons:** No adaptive logic, no Gmail Draft flow, no inline editing, doesn't solve the core problem

#### Option B: Full Web App with Static Sequences (What PRD v1 described)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium |
| Cost | ~3 weeks |
| Adaptiveness | None — same sequences, just in a browser |
| Team familiarity | Medium — adds React |

**Pros:** Better UX than CLI, Gmail Draft works, visual dashboard
**Cons:** Still static sequences — the fundamental limitation persists

#### Option C: Full Web App with Adaptive Engine (Selected)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium-High |
| Cost | ~5 weeks |
| Adaptiveness | High — learns from data, LLM-assisted |
| Team familiarity | Medium — adds React + Claude API |

**Pros:** Solves the core problem (adaptive messaging), Gmail Draft UX, visual dashboard, LLM-powered iteration, explore/exploit for templates
**Cons:** More complex, Claude API cost (~$0.10/analysis run), needs careful testing of adaptive logic

### Trade-off Analysis

The key trade-off is **complexity vs. adaptiveness**. Option B is faster but locks us into the same static problem. Option C takes 2 extra weeks but fundamentally changes how outreach works — the system gets smarter with every response.

The adaptive engine is designed to be **layered on top** of existing modules with zero modifications to working code. If the adaptive logic has bugs, the fallback is always the static queue (which still works via CLI).

The LLM advisor is optional (P1) and runs on-demand — it doesn't block the core adaptive queue. The core adaptive logic (template scoring, explore/exploit, channel alternation) is pure Python with no external dependencies.

### Consequences

**What becomes easier:**
- Template iteration — system automatically favors winners
- Daily workflow — operator sees *why* each action is recommended
- Pattern discovery — LLM advisor surfaces insights operator would miss

**What becomes harder:**
- Debugging — "why did the system choose Template X?" needs clear logging
- Testing — adaptive logic needs more test cases than static sequences
- Explaining — operator needs to understand explore/exploit concept

**What we'll revisit:**
- Explore/exploit percentages (start conservative: 70/30, then 90/10 as data grows)
- Scoring formula weights (0.4 AUM, 0.3 segment, 0.2 channels, 0.1 recency — tune based on results)
- Whether SMTP is needed at all (may fully switch to Gmail Draft)

---

## ADR-002: Supabase (PostgreSQL) for Database, Local for App

**Status:** Accepted (Updated March 3, 2026)

**Decision:** Use an existing Supabase instance for the database (PostgreSQL). Run the FastAPI backend and React frontend locally (localhost). The CLI continues to work with a connection string change.

**Rationale:**
- Operator already has a Supabase instance for another app — no new setup cost
- Data persists across machines and survives laptop failure
- Supabase real-time subscriptions enable push updates to the frontend (e.g., new reply detected)
- Supabase Edge Functions or pg_cron can run background Gmail inbox scans even when the app is closed
- PostgreSQL supports the same schema — no SQLite-specific features are used (WAL mode is SQLite-only but not needed with PostgreSQL)
- The FastAPI app and React frontend stay local — no cloud deployment for the app layer

**Migration from SQLite:**
- Convert `migrations/001_initial_schema.sql` to PostgreSQL dialect (minor: `AUTOINCREMENT` → `GENERATED ALWAYS AS IDENTITY`, `datetime('now')` → `NOW()`)
- Replace `sqlite3` connection with `psycopg2` or `asyncpg` via SQLAlchemy or raw driver
- Update `models/database.py` to use PostgreSQL connection string from env: `SUPABASE_DB_URL`
- Export existing SQLite data to CSV, import into Supabase via dashboard or `psql COPY`
- CLI updated to use the same connection string

**Environment variable:** `SUPABASE_DB_URL=postgresql://postgres:<password>@<host>:5432/postgres`

---

## ADR-003: Gmail Draft over SMTP for Outreach

**Status:** Accepted

**Decision:** Use Gmail API to create drafts (operator reviews + sends manually). Keep SMTP for newsletters only.

**Rationale:**
- Operator wants to review every outreach email before it goes out
- Gmail Drafts provide the best UX: draft appears in Gmail, operator opens and hits Send
- SMTP sends immediately with no review step — too risky for personalized outreach
- Gmail API quota (250 units/sec) is not a concern at 15 drafts/day
- `render_campaign_email()` already exists — it produces the exact content for the draft

**Implementation:** `src/services/gmail_drafter.py` using `google-auth` + `google-api-python-client`. OAuth2 flow with refresh token stored in `.env`.

---

## ADR-004: Automatic Gmail Reply Detection + LLM Classification

**Status:** Accepted

**Decision:** Extend Gmail API scope to `gmail.readonly`. Run a background scan (every 5 minutes via Supabase Edge Function or FastAPI background task) that checks for replies from enrolled contacts. Use Claude API to classify each reply as positive, negative, or neutral. Surface detected replies in the dashboard for one-click confirmation.

**How it works:**

1. **Scan:** Query Gmail API for threads where `to:` matches enrolled contacts' emails and the thread has a reply (message count > 1). Only scan threads created after the contact was enrolled.
2. **Match:** Cross-reference sender email against `contacts.email_normalized` to find the contact.
3. **Classify:** Send the reply text to Claude API with a prompt: "This is a reply to a cold outreach email about Metaworld Fund, a quantitative crypto fund. Classify as: positive (interested, wants to learn more, suggests a call), negative (not interested, asks to stop), or neutral (out of office, forwarded, unclear). Return JSON: {classification, confidence, summary}."
4. **Surface:** Create a `pending_replies` record in the database. Show in the dashboard as "Reply detected from John Smith — AI says: Positive (92% confidence) — [Confirm Positive] [Confirm Negative] [View Full Reply]."
5. **Confirm:** Operator clicks to confirm. State machine transitions as normal. If operator disagrees with classification, the corrected label feeds back into future classification accuracy.

**Why not fully automatic?** Fund allocator replies can be nuanced ("Let's revisit in Q3" is positive but not immediately). Operator confirmation takes 2 seconds per reply and prevents misclassification from silently poisoning the adaptive engine's data.

**Gmail API scopes needed:** `gmail.compose` (drafts) + `gmail.readonly` (reply detection)

**New table:**
```sql
CREATE TABLE IF NOT EXISTS pending_replies (
    id INTEGER PRIMARY KEY,  -- use SERIAL on PostgreSQL
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    gmail_message_id TEXT NOT NULL UNIQUE,
    reply_text TEXT,
    llm_classification TEXT,     -- positive | negative | neutral
    llm_confidence REAL,
    llm_summary TEXT,
    operator_classification TEXT, -- NULL until confirmed
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at TIMESTAMPTZ
);
```

---

## ADR-005: LLM Advisor as Human-in-the-Loop

**Status:** Accepted

**Decision:** LLM advisor runs on-demand (not autonomously). All suggestions require operator approval.

**Rationale:**
- Operator must control what gets sent to crypto fund allocators
- LLM may hallucinate fund performance numbers — human review is critical
- On-demand means no background cost — only pay when "Run Analysis" is clicked
- Suggested templates enter the explore pool only after operator clicks "Add as Template"

---

## ADR-006: Built-in CRM with Unified Activity Timeline

**Status:** Accepted
**Date:** March 3, 2026

**Decision:** Build the CRM directly into the outreach web app rather than integrating a third-party CRM. Every interaction — email, LinkedIn, WhatsApp, calls, manual notes — appears in one chronological timeline per contact.

**Rationale:**
- All outreach data already lives in Supabase — adding a CRM view is a UI concern, not a data concern
- Third-party CRMs (HubSpot, Attio) add cost, complexity, and sync issues for a single-operator tool
- The `events` table already logs every email send, LinkedIn action, and status transition
- Adding WhatsApp messages + manual notes completes the picture
- A unified `interaction_timeline` SQL VIEW joins all sources into one feed

**CRM Views:**
1. **Contact Detail Page** — unified timeline showing all touches (email drafts/sends/replies, LinkedIn actions, WhatsApp messages, status changes, notes), contact metadata, and current campaign status
2. **Company Detail Page** — all contacts at the company, aggregated activity, AUM, company type, GDPR status
3. **Global Search** — search contacts by name, email, company, phone; search interactions by content
4. **Contact List with Filters** — filter by status, channel, company type, AUM range, last activity date, GDPR flag

**Data model:** No new "CRM" table needed. A SQL VIEW (`interaction_timeline_view`) unions:
- `events` (email sends, LinkedIn actions, status transitions)
- `gmail_drafts` (draft created/pushed)
- `pending_replies` (auto-detected replies)
- `whatsapp_messages` (captured WhatsApp conversations)
- `response_notes` (manual notes)

This provides a single chronological feed per contact without duplicating data.

---

## ADR-007: WhatsApp Message Capture via Browser Automation

**Status:** Accepted
**Date:** March 3, 2026

**Decision:** Use Playwright (headless-capable browser automation) to read WhatsApp Web messages for contacts in the campaign. Store messages in Supabase. Display in the CRM timeline.

**How it works:**

1. **Setup (one-time):** Operator runs `python -m src.services.whatsapp_scanner setup` → opens a Chromium window with WhatsApp Web → operator scans QR code → session persists in a Playwright browser context (stored in `data/whatsapp_session/`)
2. **Scan (on-demand or scheduled):**
   - Load all contacts with a `phone_number` from the database
   - For each contact's phone number, navigate to the WhatsApp Web chat
   - Extract messages (text, timestamp, direction) from the chat DOM
   - Only capture messages newer than the last scan timestamp per contact
   - Store in `whatsapp_messages` table
3. **Match:** Contacts are matched by `contacts.phone_normalized` (E.164 format, e.g., `+491711234567`)
4. **Display:** WhatsApp messages appear in the unified CRM timeline alongside email and LinkedIn activity

**Phone number handling:**
- Add `phone_number` and `phone_normalized` columns to `contacts` table
- Phone normalization: strip spaces, dashes, parentheses; ensure E.164 format with country code
- Import phone numbers from CSV (new column mapping) or manual entry in Contact Detail page

**Scan trigger options:**
- Manual: "Scan WhatsApp" button in the UI → calls `/api/whatsapp/scan`
- Scheduled: FastAPI background task every 30 minutes (configurable)
- The scanner runs on the same machine as the app (required — WhatsApp Web session is local)

**Privacy & storage:**
- Only messages with contacts in the campaign database are captured
- Messages stored as-is (no LLM processing unless operator requests)
- WhatsApp session data stored locally in `data/whatsapp_session/` (gitignored)

**Dependencies:** `playwright` (Python package), Chromium browser (auto-installed by Playwright)

**New table:**
```sql
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    phone_number TEXT NOT NULL,
    message_text TEXT NOT NULL,
    direction TEXT NOT NULL,           -- inbound | outbound
    whatsapp_timestamp TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(contact_id, whatsapp_timestamp, direction, message_text)
);

CREATE INDEX IF NOT EXISTS idx_wa_contact ON whatsapp_messages(contact_id);
CREATE INDEX IF NOT EXISTS idx_wa_timestamp ON whatsapp_messages(whatsapp_timestamp DESC);
```

---

# Section 2: Adaptive Campaign Plan

## 2.1 Philosophy: No Pre-Arranged Sequences

The old model: Step 1 (LinkedIn) → Step 2 (Email) → Step 3 (LinkedIn DM) → ... Every contact gets the same sequence regardless of what's working.

The new model: **The system recommends the best next action for each contact based on what has produced positive replies so far.** It considers:

- Which templates have the highest positive reply rate
- Which channel (email vs LinkedIn) works better for this contact's segment
- What timing (delay between touches) correlates with replies
- Whether to exploit the best-known template or explore a new variant
- What the LLM advisor suggests based on aggregate patterns

The operator always sees the recommendation and the reasoning, and can override it.

## 2.2 How the Adaptive Engine Makes Decisions

### Step 1: Response Analyzer scans all historical data

Every time the queue is requested, the Response Analyzer reads the `events` and `contact_campaign_status` tables to compute:

```
Template Performance:
  cold_outreach_v1_a → 11.1% positive rate (45 sends, high confidence)
  cold_outreach_v1_b → 4.8% positive rate (42 sends, high confidence)
  follow_up_v1       → 6.7% positive rate (30 sends, medium confidence)
  breakup_v1         → 2.1% positive rate (28 sends, medium confidence)

Channel Performance:
  Email           → 8.2% positive rate
  LinkedIn Connect → 35% acceptance rate
  LinkedIn Message → 10.5% positive rate

Segment Performance:
  $500M-1B AUM   → 18% reply rate (best segment)
  $100M-500M AUM → 12% reply rate
  $0-100M AUM    → 5% reply rate
  $1B+ AUM       → 8% reply rate

Timing Performance:
  1-2 day gap     → 14% reply rate
  3-5 day gap     → 11% reply rate
  7+ day gap      → 7% reply rate
```

### Step 2: Contact Scorer ranks today's eligible contacts

```
priority_score = (
    0.4 × normalized_aum              # Higher AUM = higher value
  + 0.3 × segment_reply_rate          # Segments that respond well get priority
  + 0.2 × channel_availability        # Has both email + LinkedIn = higher
  + 0.1 × waiting_time_decay          # Contacts waiting longer get slight boost
)
```

This replaces simple "AUM descending" with a composite score that accounts for responsiveness patterns.

### Step 3: Template Selector picks the best template

For each contact in the queue:

1. **Filter:** Only templates for the recommended channel that the contact hasn't received yet (`contact_template_history` UNIQUE constraint)
2. **Rank:** By positive_rate (from Response Analyzer)
3. **Explore/exploit decision:**
   - If total sends < 50: explore 30% of the time (try less-tested templates)
   - If total sends 50-150: explore 15% of the time
   - If total sends 150+: explore 5% of the time
4. **Select:** Either the top-ranked template (exploit) or a random less-tested one (explore)
5. **Log:** Whether this was an exploit or explore selection (shown to operator)

### Step 4: Adaptive Queue assembles the recommendations

The queue output includes, for each contact:
- Recommended channel + template + rendered content
- Why this was chosen (e.g., "Template A has 11.1% positive rate for $500M+ funds")
- Alternatives the operator can switch to
- Previous touches (so operator has context)

## 2.3 Channel Strategy (Adaptive, Not Fixed)

Instead of a fixed channel order, the system follows **rules that ensure multi-channel presence**:

**Rule 1: LinkedIn first for new contacts**
If a contact has LinkedIn URL and hasn't been connected yet → first action is always LinkedIn Connect. Rationale: warm the relationship before hitting their inbox.

**Rule 2: Never 3 of the same channel in a row**
After 2 consecutive email touches, the next must be LinkedIn (and vice versa). This forces alternation without being rigid about the order.

**Rule 3: Prefer the higher-performing channel for each segment**
If email has 12% reply rate for $500M-1B funds but LinkedIn has 18% → weight LinkedIn more for that segment. This is a soft preference, not a hard rule — operator can override.

**Rule 4: Respect capacity**
Email requires `email_status = 'valid'`. LinkedIn requires `linkedin_url_normalized IS NOT NULL`. GDPR contacts get max 2 emails. If a channel is unavailable, use the other.

**Rule 5: End gracefully**
After 5-7 total touches with no response → mark as `no_response`, auto-activate next contact at company, add to newsletter (non-GDPR).

## 2.4 How the System Improves Over Time

### Automatic improvement (no human intervention):
- Template selection shifts toward winners as data accumulates
- Exploration rate decreases naturally (30% → 15% → 5%)
- Contact scoring adapts as segment performance data changes
- Channel preference shifts based on response patterns

### LLM-assisted improvement (operator triggers):
- Operator clicks "Run Analysis" → Claude API analyzes all data
- Returns insights like "Variant A outperforms B by 2.3x — retire B"
- Suggests new template variants based on what positive replies have in common
- Operator reviews suggestions, clicks "Add as Template" to activate
- New template enters the explore pool, gets tested automatically

### Manual improvement (operator decides):
- Operator can override any template recommendation in the queue
- Operator can deactivate underperforming templates
- Operator can create new templates in the Template Editor
- Operator can adjust engine parameters (scoring weights, explore rate) in Settings

## 2.5 Email Content Strategy

### Starting Templates (Already Exist)

| Template | Channel | Variant | Purpose |
|---|---|---|---|
| `cold_outreach_v1_a` | Email | A — Numbers-led | Lead with 75.8% CAGR, Sharpe, drawdown |
| `cold_outreach_v1_b` | Email | B — Context-led | Lead with market positioning, diversification |
| `follow_up_v1` | Email | — | Regime resilience (2022, 2025 drawdowns) |
| `breakup_v1` | Email | — | Final touch, door open |
| `connect_note_v1` | LinkedIn | — | Connection request with brief intro |
| `message_v1` | LinkedIn | — | Follow-up DM with detailed pitch |

### Templates to Create

| Template | Channel | Purpose |
|---|---|---|
| `insight_v1` | LinkedIn | Share market insight, add value |
| `final_touch_v1` | LinkedIn | Soft closing message |

### How Templates Get Better

1. System tracks which templates produce positive replies
2. After 30+ sends, templates have reliable performance scores
3. LLM advisor analyzes positive replies to find common patterns
4. LLM generates new variant: "Positive replies correlate with regime resilience messaging → here's a variant that leads with that"
5. Operator reviews, approves, adds as new template
6. System explores the new template with 20-30% of sends
7. After 15+ sends, the template has its own score
8. If it outperforms, it gets promoted to the exploit pool automatically

## 2.6 LinkedIn Workflow

All LinkedIn actions are manual. The web app prepares everything:

**For each LinkedIn action, the UI shows:**
- Contact name, title, company, AUM
- Clickable LinkedIn profile URL (opens in new tab)
- Clickable Sales Navigator deep link (`https://www.linkedin.com/sales/people/` + slug)
- Pre-written message (copyable to clipboard with one click)
- "Mark as Done" button → logs event, advances the contact

**LinkedIn event types** (already registered in `metrics.py`):
- `linkedin_connect_done` — Connection request sent
- `linkedin_message_done` — Follow-up DM sent
- `linkedin_engage_done` — Engaged with their content (like/comment)
- `linkedin_insight_done` — Shared insight message
- `linkedin_final_done` — Final soft touch sent

## 2.7 Response Handling

| Response | System Action | Next |
|---|---|---|
| **Positive reply** (any channel) | Mark `replied_positive`, log event | Operator manually follows up / schedules call |
| **Call booked** | Mark `replied_positive` + log `call_booked` | Exit sequence, celebrate |
| **Negative reply** | Mark `replied_negative`, log event | Auto-activate next contact at company |
| **No response** (after sequence completes) | Mark `no_response` | Auto-activate next contact, add to newsletter (non-GDPR) |
| **Bounce** | Mark `bounced` | Auto-activate next contact, skip remaining email steps |
| **Unsubscribe** | Mark `unsubscribed` | Remove from all active sequences |

**Response logging — two paths:**

1. **Automatic (Gmail reply detection):** Background scan detects reply → LLM classifies as positive/negative/neutral → operator sees "Reply detected" card in dashboard → one-click confirm or correct. This is the primary path.
2. **Manual (fallback):** One-click buttons (Positive / Negative / Call Booked / No Response) + optional free-text note. Used for LinkedIn replies (not detectable via API) or when the operator learns about a response through other channels.

Both paths store notes in `response_notes` for future LLM analysis. Both trigger the same state machine transitions.

## 2.8 Performance Benchmarks

| Metric | Baseline (static) | Target (adaptive, 4 weeks) | Target (adaptive, 3 months) |
|---|---|---|---|
| Positive reply rate | 3-5% | 5-8% | 8-12% |
| Call booking rate | 1-2% | 2-4% | 4-6% |
| Template iteration speed | Monthly | Bi-weekly | Weekly |
| Daily workflow time | 30+ min (CLI) | <15 min | <10 min |

---

# Section 3: Product Specification

## 3.1 Problem Statement

Metaworld Fund runs outreach to ~875 crypto fund allocators via email and LinkedIn. The current CLI tool works but has three critical limitations: (1) static sequences that don't adapt to response data, (2) no email preview/draft workflow — emails send directly, and (3) no visual dashboard for spotting patterns. The operator needs a web application that learns from outcomes and gets better at selecting the right message, channel, and timing for each contact.

## 3.2 Goals

1. **Adaptive outreach** — system automatically favors templates and channels that produce positive replies, while exploring new variants
2. **Gmail Draft workflow** — all outreach emails land in Gmail Drafts for manual review before send
3. **Unified email + LinkedIn view** — one queue showing both channels with prepared content
4. **Data-driven iteration** — aggregate response patterns visible in dashboard; LLM advisor generates insights and new template suggestions
5. **<15 minute daily workflow** — from queue review to all actions complete
6. **Built-in CRM** — unified timeline per contact showing every interaction across email, LinkedIn, WhatsApp, and manual notes
7. **WhatsApp capture** — automated message extraction from WhatsApp Web via browser automation

## 3.3 Non-Goals

1. **Automated LinkedIn sending** — all LinkedIn actions remain manual
2. **Email tracking pixels** — no opens/clicks tracking; clean emails only
3. **Multi-user access** — single operator, no auth system
4. **Cloud deployment** — runs locally (localhost)
5. **Mobile-first design** — desktop only

## 3.4 User Stories

### Daily Workflow

- As the operator, I want to **open a dashboard** showing today's queue with recommended actions and reasoning — so I can plan my outreach in 30 seconds
- As the operator, I want to **preview each email** with the contact's data filled in, and optionally edit it — so I catch errors before it reaches their inbox
- As the operator, I want to **push approved emails to Gmail Drafts** with one click (or batch all at once) — so I just open Gmail and hit Send
- As the operator, I want to **see LinkedIn actions** with the profile URL, Sales Navigator link, and a copyable pre-written message — so I can execute LinkedIn outreach quickly
- As the operator, I want to **log responses** (positive / negative / call booked / no response) with one click and an optional note — so the system learns and advances

### Adaptive Engine

- As the operator, I want to **see why the system recommends a specific template** — so I trust the recommendation and can override with confidence
- As the operator, I want the system to **automatically prefer higher-performing templates** — so I don't manually track which variants win
- As the operator, I want to **override any recommendation** with a different template — so I maintain full control
- As the operator, I want **new template variants** to be tested automatically via explore/exploit — so I discover improvements without manual A/B setup
- As the operator, I want to **see performance data by template, channel, segment, and timing** — so I can make informed decisions

### LLM Advisor

- As the operator, I want to **click "Run Analysis"** and get LLM-generated insights — so I discover patterns I'd miss manually
- As the operator, I want the LLM to **suggest new email variants** based on what's working — so I iterate faster
- As the operator, I want to **accept or reject LLM suggestions** with one click — so new variants enter the rotation quickly

### CRM & Contact Management

- As the operator, I want to **open any contact and see a unified timeline** of every interaction (emails, LinkedIn, WhatsApp, notes, replies) — so I always know exactly what happened
- As the operator, I want to **see a company view** with all contacts, aggregated activity, and company metadata — so I understand the full relationship with each firm
- As the operator, I want to **search globally** by name, email, company, phone, or message content — so I can quickly find any contact or conversation
- As the operator, I want to **see WhatsApp messages** in the contact timeline — so I have the complete picture including informal conversations
- As the operator, I want to **scan WhatsApp** on-demand or automatically — so messages are captured without manual logging

### Campaign Management

- As the operator, I want to **see a campaign report** with metrics, A/B comparison, firm-type breakdown, and weekly trends — so I know what's working
- As the operator, I want to **see a per-contact timeline** with every touchpoint — so I understand the full conversation history
- As the operator, I want to **edit templates** inline with a live preview — so I can iterate on messaging without touching files

## 3.5 Requirements

### P0 — Must-Have

| # | Requirement | Acceptance Criteria |
|---|---|---|
| P0.1 | **Supabase PostgreSQL migration** | Existing SQLite schema migrated to PostgreSQL on Supabase. `models/database.py` updated with connection string. Data exported from SQLite and imported. All existing tests pass with PostgreSQL. |
| P0.2 | **FastAPI backend** exposing all existing services as REST endpoints | All 24 CLI functions accessible via API. Existing tests pass. |
| P0.3 | **Adaptive queue** with recommendations | Queue returns priority_score, recommended template, channel, reasoning. One-per-company rule enforced. GDPR/compliance respected. |
| P0.4 | **Template performance tracking** | Every send logged in `contact_template_history`. Response Analyzer computes positive_rate per template. |
| P0.5 | **Explore/exploit template selection** | 70-95% exploit rate (based on data volume). Never sends same template to same contact twice. Selection mode (exploit/explore) visible in UI. |
| P0.6 | **Channel alternation** | Never 3 same-channel touches in a row. LinkedIn first for new contacts. Channel preference adapts to segment data. |
| P0.7 | **Gmail Draft creation** | OAuth2 Gmail auth (`gmail.compose` + `gmail.readonly`). Push single or batch drafts. Draft status tracking. Drafts appear in Gmail within 5 seconds. |
| P0.8 | **Automatic Gmail reply detection** | Background scan (every 5 min) checks Gmail for replies from enrolled contacts. LLM classifies as positive/negative/neutral. Dashboard shows "Reply detected" cards with one-click confirm/correct. Operator confirmation triggers state machine. |
| P0.9 | **Email preview + inline edit** | Rendered email visible in queue card. Editable before push. Compliance footer included. |
| P0.10 | **LinkedIn action cards** | Profile URL (clickable), Sales Navigator link, copyable message, "Mark Done" button. |
| P0.11 | **Manual response logging** | One-click buttons (positive/negative/call-booked/no-response) for LinkedIn replies and fallback. Optional note. State machine transitions match existing CLI behavior. Auto-activates next contact. |
| P0.12 | **Contact timeline** | Full event history per contact, chronologically ordered. Shows template, channel, outcome, auto-detected replies. |
| P0.13 | **Campaign dashboard** | Metric cards (enrolled, positive, reply rate, calls booked). Weekly trend chart. Today's queue summary. Pending reply cards at top. |
| P0.14 | **Campaign report** | Mirrors existing `report` CLI output. Metrics, A/B comparison, firm-type breakdown. |
| P0.15 | **React frontend** | Sidebar nav, Dashboard, Queue, Contact Detail, Company Detail, Campaign Report, Templates, Settings pages. Desktop-first (1440px+). |
| P0.16 | **CRM contact detail with unified timeline** | Contact Detail page shows ALL interactions (email, LinkedIn, WhatsApp, notes, replies) in one chronological feed. Uses `interaction_timeline_view`. Includes contact metadata, campaign status, and phone number. |
| P0.17 | **CRM company detail page** | Company page shows all contacts, aggregated activity count, AUM, type, GDPR status. Click through to any contact's timeline. |
| P0.18 | **Global search** | Search bar in sidebar searches contacts (name, email, company, phone), companies (name), and interaction content. Results grouped by type. |

### P1 — Nice-to-Have

| # | Requirement | Acceptance Criteria |
|---|---|---|
| P1.1 | **LLM Advisor** | "Run Analysis" calls Claude API. Returns insights + template suggestions. "Add as Template" button. Run history visible. |
| P1.2 | **Segment heatmap** | Visual breakdown: firm_type × AUM tier → reply rate. Color-coded. |
| P1.3 | **Template editor** | Inline editing with monospace font. Live preview with sample contact data. Create new template. Deactivate toggle. |
| P1.4 | **CSV import via browser** | File upload, preview table, dedup summary, progress indicator. |
| P1.5 | **Timing optimization** | Response Analyzer tracks reply rate by delay interval. Optimal timing shown in Insights. |
| P1.6 | **"What's Working" panel** on dashboard | Auto-generated summary of top template, best segment, channel preference. |
| P1.7 | **WhatsApp message capture** | Playwright-based WhatsApp Web scanner. One-time QR setup. On-demand or scheduled scan (every 30 min). Messages stored in `whatsapp_messages` and displayed in CRM timeline. Matches contacts by `phone_normalized`. |
| P1.8 | **WhatsApp scan UI** | "Scan WhatsApp" button in Settings or Dashboard. Last scan timestamp. Scan progress indicator. Message count per scan. |
| P1.9 | **Phone number management** | Add/edit phone numbers on Contact Detail page. Bulk import phone numbers from CSV. Auto-normalize to E.164 format. |

### P2 — Future Considerations

| # | Requirement | Notes |
|---|---|---|
| P2.1 | Auto-generated email variants | LLM creates variants autonomously, operator approves. Design template creation as simple DB insert to support this. |
| P2.2 | Send-time optimization | Track day-of-week/time-of-day response patterns. |
| P2.3 | Multi-campaign learning | Transfer learning: Campaign A insights inform Campaign B defaults. |
| P2.4 | Slack daily summary | Post queue summary to Slack channel each morning. |

## 3.6 Database Schema (Migration 002 — PostgreSQL on Supabase)

**Note:** Migration 001 must first be converted from SQLite to PostgreSQL dialect. Key changes: `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY`, `datetime('now')` → `NOW()`, `TEXT` dates → `TIMESTAMPTZ`. The table structure and indexes remain identical.

```sql
-- migration: 002_web_app.sql (PostgreSQL / Supabase)

CREATE TABLE IF NOT EXISTS contact_template_history (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    template_id INTEGER NOT NULL REFERENCES templates(id),
    channel TEXT NOT NULL,
    selection_mode TEXT DEFAULT 'exploit',  -- exploit | explore | manual_override
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(contact_id, campaign_id, template_id)
);

CREATE TABLE IF NOT EXISTS advisor_runs (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    insights_json JSONB NOT NULL,
    template_suggestions_json JSONB,
    sequence_suggestions_json JSONB,
    events_analyzed INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS gmail_drafts (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    template_id INTEGER REFERENCES templates(id),
    gmail_draft_id TEXT,
    gmail_message_id TEXT,
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    body_html TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    pushed_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(contact_id, campaign_id, template_id)
);

CREATE TABLE IF NOT EXISTS pending_replies (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    gmail_message_id TEXT NOT NULL UNIQUE,
    gmail_thread_id TEXT,
    reply_text TEXT,
    reply_snippet TEXT,                    -- first 200 chars for preview
    llm_classification TEXT,              -- positive | negative | neutral
    llm_confidence REAL,
    llm_summary TEXT,
    operator_classification TEXT,          -- NULL until confirmed
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS response_notes (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    note TEXT NOT NULL,
    response_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS engine_config (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    config_key TEXT NOT NULL,
    config_value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(campaign_id, config_key)
);

CREATE INDEX IF NOT EXISTS idx_cth_contact ON contact_template_history(contact_id, campaign_id);
CREATE INDEX IF NOT EXISTS idx_cth_template ON contact_template_history(template_id);
CREATE INDEX IF NOT EXISTS idx_gmail_status ON gmail_drafts(status);
CREATE INDEX IF NOT EXISTS idx_gmail_contact ON gmail_drafts(contact_id);
CREATE INDEX IF NOT EXISTS idx_pending_replies_contact ON pending_replies(contact_id);
CREATE INDEX IF NOT EXISTS idx_pending_replies_unconfirmed ON pending_replies(operator_classification) WHERE operator_classification IS NULL;
CREATE INDEX IF NOT EXISTS idx_advisor_campaign ON advisor_runs(campaign_id);
CREATE INDEX IF NOT EXISTS idx_response_notes_contact ON response_notes(contact_id);
CREATE INDEX IF NOT EXISTS idx_engine_config ON engine_config(campaign_id, config_key);

-- Phone number columns on contacts (ALTER existing table)
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS phone_number TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS phone_normalized TEXT;
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone_normalized);

-- WhatsApp messages
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    phone_number TEXT NOT NULL,
    message_text TEXT NOT NULL,
    direction TEXT NOT NULL,           -- inbound | outbound
    whatsapp_timestamp TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(contact_id, whatsapp_timestamp, direction, message_text)
);

CREATE INDEX IF NOT EXISTS idx_wa_contact ON whatsapp_messages(contact_id);
CREATE INDEX IF NOT EXISTS idx_wa_timestamp ON whatsapp_messages(whatsapp_timestamp DESC);

-- WhatsApp scan state (tracks last scan per contact to avoid re-reading)
CREATE TABLE IF NOT EXISTS whatsapp_scan_state (
    contact_id INTEGER PRIMARY KEY REFERENCES contacts(id),
    last_scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message_at TIMESTAMPTZ
);

-- Unified CRM timeline VIEW (read-only, for display)
CREATE OR REPLACE VIEW interaction_timeline_view AS
    -- Email sends and LinkedIn actions from events
    SELECT
        e.contact_id,
        e.created_at AS occurred_at,
        e.event_type AS interaction_type,
        'event' AS source_table,
        e.id AS source_id,
        COALESCE(e.notes, '') AS summary,
        NULL AS full_text
    FROM events e
    UNION ALL
    -- Gmail drafts created/pushed
    SELECT
        gd.contact_id,
        COALESCE(gd.pushed_at, gd.created_at) AS occurred_at,
        CASE WHEN gd.status = 'pushed' THEN 'email_draft_pushed'
             WHEN gd.status = 'sent' THEN 'email_sent'
             ELSE 'email_draft_created' END AS interaction_type,
        'gmail_drafts' AS source_table,
        gd.id AS source_id,
        gd.subject AS summary,
        gd.body_text AS full_text
    FROM gmail_drafts gd
    UNION ALL
    -- Auto-detected replies
    SELECT
        pr.contact_id,
        pr.detected_at AS occurred_at,
        CONCAT('reply_', COALESCE(pr.operator_classification, pr.llm_classification, 'pending')) AS interaction_type,
        'pending_replies' AS source_table,
        pr.id AS source_id,
        COALESCE(pr.llm_summary, pr.reply_snippet) AS summary,
        pr.reply_text AS full_text
    FROM pending_replies pr
    UNION ALL
    -- WhatsApp messages
    SELECT
        wm.contact_id,
        wm.whatsapp_timestamp AS occurred_at,
        CONCAT('whatsapp_', wm.direction) AS interaction_type,
        'whatsapp_messages' AS source_table,
        wm.id AS source_id,
        LEFT(wm.message_text, 200) AS summary,
        wm.message_text AS full_text
    FROM whatsapp_messages wm
    UNION ALL
    -- Manual notes
    SELECT
        rn.contact_id,
        rn.created_at AS occurred_at,
        CONCAT('note_', COALESCE(rn.response_type, 'general')) AS interaction_type,
        'response_notes' AS source_table,
        rn.id AS source_id,
        LEFT(rn.note, 200) AS summary,
        rn.note AS full_text
    FROM response_notes rn;
```

## 3.7 API Endpoints

```
# Queue & Actions
GET  /api/queue/{campaign}?date=YYYY-MM-DD&limit=20
POST /api/queue/{campaign}/override          # Override template for a queue item
POST /api/contacts/{id}/status               # Log response
POST /api/contacts/{id}/linkedin-done        # Mark LinkedIn action done

# Gmail
POST /api/gmail/authorize
GET  /api/gmail/callback
POST /api/gmail/drafts                       # Push single draft
POST /api/gmail/drafts/batch                 # Push all today's drafts
GET  /api/gmail/drafts/status                # Check draft statuses

# Reply Detection
GET  /api/replies/pending                    # Unconfirmed detected replies
POST /api/replies/{id}/confirm               # Confirm/correct LLM classification
POST /api/replies/scan                       # Trigger manual inbox scan

# Campaigns
GET  /api/campaigns
GET  /api/campaigns/{name}/metrics
GET  /api/campaigns/{name}/weekly
GET  /api/campaigns/{name}/report

# Contacts
GET  /api/contacts?search=&filter=
GET  /api/contacts/{id}
GET  /api/contacts/{id}/events

# Templates
GET  /api/templates
GET  /api/templates/{id}
PUT  /api/templates/{id}
POST /api/templates
PATCH /api/templates/{id}/deactivate

# Insights (LLM Advisor)
POST /api/insights/analyze
GET  /api/insights/history?campaign=

# Import
POST /api/import/csv
POST /api/import/dedupe

# CRM
GET  /api/crm/contacts?search=&status=&company_type=&aum_min=&aum_max=&last_activity=  # Searchable contact list
GET  /api/crm/contacts/{id}/timeline?limit=50&offset=0  # Unified timeline (interaction_timeline_view)
GET  /api/crm/companies?search=&type=&aum_min=           # Company list with aggregated stats
GET  /api/crm/companies/{id}                              # Company detail + all contacts + activity
GET  /api/crm/search?q=                                   # Global search (contacts, companies, message content)

# WhatsApp
POST /api/whatsapp/setup                                  # Start WhatsApp Web session (returns status)
POST /api/whatsapp/scan                                   # Trigger scan for all contacts with phone numbers
GET  /api/whatsapp/scan/status                            # Last scan time, messages captured count
GET  /api/whatsapp/messages?contact_id=                   # Messages for a contact
POST /api/contacts/{id}/phone                             # Add/update phone number for a contact

# Stats
GET  /api/stats

# Settings
GET  /api/settings
PUT  /api/settings
```

## 3.8 File Structure

```
outreach-campaign/
├── src/
│   ├── cli.py                           # UNCHANGED — CLI still works
│   ├── models/
│   │   ├── database.py                  # MODIFIED — PostgreSQL connection via SUPABASE_DB_URL
│   │   └── campaigns.py                 # MODIFIED — psycopg2 parameter style (%s vs ?)
│   ├── commands/                        # UNCHANGED (CLI commands)
│   ├── services/
│   │   ├── priority_queue.py            # UNCHANGED (fallback)
│   │   ├── state_machine.py             # UNCHANGED
│   │   ├── deduplication.py             # UNCHANGED
│   │   ├── compliance.py                # UNCHANGED
│   │   ├── template_engine.py           # UNCHANGED
│   │   ├── ab_testing.py                # UNCHANGED
│   │   ├── metrics.py                   # MODIFIED (already has new event types)
│   │   ├── email_sender.py              # MODIFIED (already has render_campaign_email)
│   │   ├── email_verifier.py            # UNCHANGED
│   │   ├── newsletter.py                # UNCHANGED
│   │   ├── response_analyzer.py         # NEW — compute performance scores
│   │   ├── contact_scorer.py            # NEW — composite priority scoring
│   │   ├── template_selector.py         # NEW — explore/exploit selection
│   │   ├── adaptive_queue.py            # NEW — smart queue with recommendations
│   │   ├── reply_detector.py            # NEW — Gmail inbox scan + LLM classification
│   │   ├── llm_advisor.py              # NEW — Claude API analysis
│   │   ├── gmail_drafter.py            # NEW — Gmail API drafts
│   │   └── whatsapp_scanner.py         # NEW — Playwright WhatsApp Web automation
│   ├── api/
│   │   ├── __init__.py                  # NEW
│   │   ├── main.py                      # NEW — FastAPI app
│   │   ├── dependencies.py              # NEW — DB connection dep
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── queue.py
│   │       ├── campaigns.py
│   │       ├── contacts.py
│   │       ├── templates.py
│   │       ├── gmail.py
│   │       ├── insights.py
│   │       ├── import_routes.py
│   │       ├── stats.py
│   │       ├── crm.py                  # NEW — CRM views, timeline, search
│   │       └── whatsapp.py             # NEW — WhatsApp scan + messages
│   └── templates/                       # UNCHANGED (Jinja2 templates)
│       ├── email/                       # existing 4 templates
│       └── linkedin/
│           ├── connect_note_v1.txt      # existing
│           ├── message_v1.txt           # existing
│           ├── insight_v1.txt           # NEW
│           └── final_touch_v1.txt       # NEW
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/client.ts
│       ├── components/
│       │   ├── Sidebar.tsx
│       │   ├── MetricCard.tsx
│       │   ├── EmailActionCard.tsx
│       │   ├── LinkedInActionCard.tsx
│       │   ├── ContactTimeline.tsx
│       │   ├── InsightPanel.tsx
│       │   ├── SegmentHeatmap.tsx
│       │   ├── TemplateEditor.tsx
│       │   ├── UnifiedTimeline.tsx       # NEW — renders interaction_timeline_view
│       │   └── WhatsAppMessageCard.tsx   # NEW — WhatsApp message bubble
│       ├── pages/
│       │   ├── Dashboard.tsx
│       │   ├── Queue.tsx
│       │   ├── Campaigns.tsx
│       │   ├── CampaignReport.tsx
│       │   ├── Contacts.tsx
│       │   ├── ContactDetail.tsx         # Enhanced — unified CRM timeline
│       │   ├── CompanyDetail.tsx         # NEW — company view with contacts + activity
│       │   ├── Templates.tsx
│       │   ├── Insights.tsx
│       │   └── Settings.tsx
│       └── types/index.ts
├── migrations/
│   ├── 001_initial_schema.sql           # existing
│   └── 002_web_app.sql                  # NEW
├── tests/
│   ├── (existing tests — all must pass)
│   ├── test_response_analyzer.py        # NEW
│   ├── test_contact_scorer.py           # NEW
│   ├── test_template_selector.py        # NEW
│   ├── test_adaptive_queue.py           # NEW
│   ├── test_api.py                      # NEW
│   └── test_whatsapp_scanner.py         # NEW
├── data/
│   └── whatsapp_session/                # Playwright browser state (gitignored)
└── Makefile                             # ADD targets: api, frontend, dev, whatsapp-setup, whatsapp-scan
```

## 3.9 Environment Variables

```bash
# Database (replaces DATABASE_PATH)
SUPABASE_DB_URL=postgresql://postgres:<password>@<host>:5432/postgres

# Existing (unchanged)
SMTP_PASSWORD=<secret>
EMAIL_VERIFY_API_KEY=<api-key>
EMAIL_VERIFY_PROVIDER=zerobounce

# New
GMAIL_CLIENT_ID=<google-oauth-client-id>
GMAIL_CLIENT_SECRET=<google-oauth-client-secret>
GMAIL_REDIRECT_URI=http://localhost:8000/api/gmail/callback
ANTHROPIC_API_KEY=<claude-api-key>

# WhatsApp (auto-managed)
WHATSAPP_SESSION_DIR=data/whatsapp_session
WHATSAPP_SCAN_INTERVAL_MINUTES=30
```

**Additional Python dependency:** `playwright` (install with `pip install playwright && playwright install chromium`)

## 3.10 Implementation Phases

### Phase 0: Supabase Migration (Week 1)

Migrate SQLite schema to PostgreSQL on existing Supabase instance. Export data. Update `models/database.py` to use `psycopg2` with `SUPABASE_DB_URL`. Update all `?` parameter placeholders to `%s` across models. Verify all existing tests pass with PostgreSQL.

**Deliverables:**
- PostgreSQL version of `001_initial_schema.sql`
- Updated `models/database.py` with PostgreSQL connection
- Updated `models/campaigns.py` with `%s` params
- Data migration script (SQLite → CSV → Supabase)
- All existing tests pass

### Phase 1: Backend API + CRM Routes (Week 1-2)

Create FastAPI app wrapping existing services. No adaptive logic yet — wrap the current static queue as a starting point. Include CRM routes (contact timeline, company view, global search) from the start since they query existing data. All existing tests must pass.

**Deliverables:**
- `src/api/` with all route modules including `crm.py`
- `migrations/002_web_app.sql` (PostgreSQL) — includes `whatsapp_messages`, `whatsapp_scan_state`, phone columns on contacts, and `interaction_timeline_view`
- CRM API routes: contact list with filters, unified timeline, company detail, global search
- `Makefile` targets: `make api`
- API tests in `tests/test_api.py`

### Phase 2: React Frontend + CRM Views (Week 2-3)

All pages implemented using Phase 1 API. Queue shows static recommendations initially. CRM pages (Contact Detail with unified timeline, Company Detail, global search) are core to this phase.

**Deliverables:**
- `frontend/` complete Vite + React + TypeScript + Tailwind app
- All pages: Dashboard, Queue, Contact Detail (with `UnifiedTimeline` component), Company Detail, Campaign Report, Templates, Settings
- `UnifiedTimeline.tsx` component rendering the `interaction_timeline_view` feed
- Global search in sidebar
- `Makefile` targets: `make frontend`, `make dev`

### Phase 3: Adaptive Engine (Week 3-4)

Replace static queue with intelligent recommendations. This is the core innovation.

**Deliverables:**
- `response_analyzer.py`, `contact_scorer.py`, `template_selector.py`, `adaptive_queue.py`
- Updated API routes to use adaptive queue
- Updated Queue page to show reasoning + alternatives
- Tests for scoring, selection, explore/exploit, and never-repeat logic

### Phase 4: Gmail Integration + Reply Detection (Week 4-5)

Gmail Draft creation, automatic reply detection, and LLM classification.

**Deliverables:**
- `gmail_drafter.py` with OAuth2 flow (`gmail.compose` + `gmail.readonly`)
- Gmail API routes + UI integration (push draft, batch push)
- `reply_detector.py` — scans inbox, matches contacts, calls Claude API for classification
- Background scan task (FastAPI `BackgroundTasks` or Supabase Edge Function, every 5 min)
- "Pending Replies" cards on dashboard with confirm/correct buttons
- Reply detection API routes + UI
- `llm_advisor.py` with Claude API calls
- Insights page
- "Add as Template" flow

### Phase 5: WhatsApp Integration (Week 5-6)

WhatsApp Web browser automation for message capture.

**Deliverables:**
- `src/services/whatsapp_scanner.py` — Playwright-based WhatsApp Web automation
- Setup flow: `make whatsapp-setup` opens browser, operator scans QR, session persists
- Scan flow: `make whatsapp-scan` or `/api/whatsapp/scan` triggers message extraction
- Phone number normalization (E.164) in contact model
- WhatsApp messages appear in CRM timeline via `interaction_timeline_view`
- `WhatsAppMessageCard.tsx` component with chat bubble styling (green outbound, white inbound)
- `src/api/routes/whatsapp.py` API routes
- `tests/test_whatsapp_scanner.py`
- Background scan option (every 30 min, configurable in Settings)

### Phase 6: Polish (Week 6-7)

CSV import, template editor, segment heatmap, engine parameter tuning, phone number bulk import.

## 3.11 Success Metrics

| Metric | Baseline | 4-Week Target | 3-Month Target |
|---|---|---|---|
| Positive reply rate | 3-5% | 5-8% | 8-12% |
| Call booking rate | 1-2% | 2-4% | 4-6% |
| Daily workflow time | 30+ min | <15 min | <10 min |
| Template iteration speed | Monthly | Bi-weekly | Weekly |
| Queue completion rate | ~70% | 95% | 100% |

## 3.12 Open Questions

| Question | Owner | Status |
|---|---|---|
| Gmail API credentials setup — personal or workspace account? | Helmut | Blocking — needed for Phase 4 |
| Anthropic API key for LLM advisor — which tier? | Helmut | Non-blocking — needed for Phase 4 |
| Should old CLI queue command use adaptive logic too, or stay static? | Engineering | Non-blocking — recommend keeping CLI static as fallback |
| Maximum touches per contact before sequence ends? | Helmut | Default: 7. Configurable in engine_config. |
| Should "negative reply" contacts be excluded from future campaigns? | Helmut | Default: yes (never re-enroll). Configurable. |
| Do existing CSVs include phone numbers? If not, where to source them? | Helmut | Needed for WhatsApp scanning. Can be added manually per contact or bulk-imported. |
| Default country code for phone normalization (e.g., +49 for Germany)? | Helmut | Default: +49. Used when phone numbers lack country code. Configurable in Settings. |

---

## Appendix: Design Tokens & UI Quick Reference

**Colors:** slate-900 sidebar, white cards, slate-50 background, blue-500 primary actions, green-500 positive, red-500 negative, amber-500 neutral, indigo-500 email badges, LinkedIn blue (#0A66C2) for LinkedIn badges

**Typography:** Inter for all text. 24px/700 page titles, 18px/600 sections, 14px/400 body, 12px/500 labels. JetBrains Mono 13px for template code.

**Layout:** 240px fixed sidebar + fluid main content. Cards with 8px radius, 16-24px padding.

**Key interactions:**
- "Push to Gmail Draft" → spinner → green check → "Draft Created"
- "Copy Message" → clipboard → "Copied!" for 2 seconds
- "Mark Done" → card slides out → toast "Logged: LinkedIn connect done"
- Response buttons → state machine transition → toast with next action
- "Run Analysis" → loading spinner (5-10 sec) → insights populate
