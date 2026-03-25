# Implementation Plan: Adaptive Outreach Campaign Web App

**For handoff to Claude Code**
**Version:** 2.0 — Supersedes PRD_Outreach_Web_App.md and Outreach_Sequence_Plan.md
**Date:** March 3, 2026

This document combines system architecture, UI design specs, and feature requirements into a single implementation plan. It covers three major areas:

1. **Adaptive Sequence Engine** — replaces static step sequences with an intelligent decision system
2. **Web Application** — FastAPI backend + React frontend
3. **Gmail Draft Integration** — emails go to Gmail Drafts for manual review

---

## Part 1: System Design — Adaptive Sequence Engine

### 1.1 Problem with the Current Static Approach

The existing system uses a fixed `sequence_steps` table: Step 1 → Step 2 → Step 3 → ... with hardcoded `delay_days`. Every contact gets the same sequence regardless of what's working. The A/B testing exists but requires manual analysis and manual template swaps.

**What we want instead:** A system that observes response patterns across all contacts and automatically adjusts what gets sent next, when, and on which channel — while giving the operator full visibility and override control.

### 1.2 Architecture: The Decision Engine

```
┌─────────────────────────────────────────────────────┐
│                   DECISION ENGINE                    │
│                                                      │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │ Response  │  │  Contact     │  │   Template    │ │
│  │ Analyzer  │──│  Scorer      │──│   Selector    │ │
│  └──────────┘  └──────────────┘  └───────────────┘ │
│       ↑              ↑                   ↓          │
│  [events DB]    [contacts DB]     [next action]     │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │           LLM Advisor (Claude API)            │   │
│  │  • Analyzes aggregate patterns                │   │
│  │  • Suggests template improvements             │   │
│  │  • Recommends channel/timing adjustments      │   │
│  │  • Generates new email variants               │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
         ↓                    ↓
  ┌──────────────┐    ┌──────────────┐
  │ Email Draft  │    │ LinkedIn     │
  │ (Gmail API)  │    │ Action Card  │
  └──────────────┘    └──────────────┘
```

### 1.3 Core Components

#### Component 1: Response Analyzer (`src/services/response_analyzer.py`)

Computes real-time performance scores from the `events` and `contact_campaign_status` tables. No new data collection needed — this reads what already exists.

```python
# What it computes:
{
    "template_scores": {
        # template_id → performance metrics
        14: {
            "sends": 45,
            "positive_replies": 5,
            "negative_replies": 2,
            "no_response": 38,
            "positive_rate": 0.111,
            "reply_rate": 0.156,
            "confidence": "high"    # high if sends >= 30, medium if >= 15, low if < 15
        }
    },
    "channel_scores": {
        "email": {"reply_rate": 0.12, "positive_rate": 0.08},
        "linkedin_connect": {"acceptance_rate": 0.35},
        "linkedin_message": {"reply_rate": 0.15, "positive_rate": 0.10}
    },
    "timing_scores": {
        # delay_days → reply_rate for contacts who were actioned at that delay
        2: 0.14,
        5: 0.11,
        7: 0.09,
    },
    "segment_scores": {
        "by_firm_type": { ... },     # reuse existing get_company_type_breakdown()
        "by_aum_tier": {             # new: bucket by AUM ranges
            "0-100M": {"reply_rate": 0.05},
            "100M-500M": {"reply_rate": 0.12},
            "500M-1B": {"reply_rate": 0.18},
            "1B+": {"reply_rate": 0.08}
        },
        "by_gdpr": { ... }
    }
}
```

**Implementation:** Pure SQL queries against existing tables. No schema changes needed for this component.

#### Component 2: Contact Scorer (`src/services/contact_scorer.py`)

Scores each contact to determine **priority and optimal approach**. Replaces the simple "AUM descending" ordering with a composite score.

```python
def score_contact(conn, contact_id, campaign_id) -> dict:
    """
    Returns:
    {
        "priority_score": 0.85,        # 0-1, higher = action sooner
        "recommended_channel": "email", # best-performing channel for this segment
        "recommended_template_id": 14,  # highest-performing template for this segment
        "recommended_delay": 3,         # optimal days between touches
        "reasoning": "AUM tier $500M-1B has 18% reply rate via email. Template 14 outperforms Template 12 by 2.3x on positive replies."
    }
    """
```

**Scoring formula:**

```
priority_score = (
    0.4 * aum_normalized          # Higher AUM = higher value
  + 0.3 * segment_reply_rate      # Firm types that respond well get priority
  + 0.2 * channel_availability    # Has both email + LinkedIn = higher score
  + 0.1 * recency_decay           # Contacts waiting longer get slight boost
)
```

**Template selection logic:**

```
1. Get all active templates for the recommended channel
2. Filter by GDPR compatibility
3. Rank by positive_rate (from Response Analyzer)
4. If confidence is "low" (< 15 sends), use explore/exploit:
   - 80% of the time: use the highest-performing template
   - 20% of the time: use a less-tested template (exploration)
5. Never send the same template to the same contact twice
```

**Channel selection logic:**

```
1. Look at which channel has higher positive_rate for this contact's segment
2. Alternate channels (never send 3 of the same channel in a row)
3. LinkedIn first if contact has LinkedIn URL and hasn't been connected yet
4. Email if contact has valid email and LinkedIn connect already sent
5. Respect GDPR email limits (max 2 for GDPR, 3 for non-GDPR)
```

#### Component 3: Template Selector (`src/services/template_selector.py`)

Picks the best template for a given contact + channel + step combination.

```python
def select_template(conn, contact_id, campaign_id, channel) -> dict:
    """
    Returns:
    {
        "template_id": 14,
        "template_name": "cold_outreach_v1_a",
        "selection_reason": "exploit",    # exploit | explore | only_option | manual_override
        "confidence": "high",
        "alternatives": [                 # other options considered
            {"template_id": 15, "positive_rate": 0.08, "confidence": "medium"}
        ]
    }
    """
```

**Explore/exploit balance (Thompson Sampling simplified):**

```python
import random

def should_explore(template_sends: int, total_templates: int) -> bool:
    """
    Exploration rate decreases as we gather more data.
    - First 50 sends: 30% exploration
    - 50-150 sends: 15% exploration
    - 150+ sends: 5% exploration
    """
    if template_sends < 50:
        return random.random() < 0.30
    elif template_sends < 150:
        return random.random() < 0.15
    else:
        return random.random() < 0.05
```

#### Component 4: LLM Advisor (`src/services/llm_advisor.py`)

Calls Claude API to analyze patterns and generate recommendations. This runs on-demand (not every queue request), triggered by:
- Weekly review
- After every 25 new response events
- Manual "Analyze & Suggest" button in UI

```python
def get_campaign_advice(conn, campaign_id) -> dict:
    """
    Calls Claude API with:
    - Current template texts + their performance data
    - Aggregate metrics by segment
    - Recent positive and negative reply patterns

    Returns:
    {
        "insights": [
            "Variant A outperforms B by 2.3x on positive replies (11.1% vs 4.8%). Consider retiring B.",
            "Contacts at funds with $500M-1B AUM respond best. Consider increasing outreach to this tier.",
            "LinkedIn connect → email performs 40% better than email-first sequences."
        ],
        "template_suggestions": [
            {
                "channel": "email",
                "purpose": "cold_outreach",
                "subject": "Systematic momentum — uncorrelated to crypto drawdowns",
                "body": "...",
                "rationale": "Current top template leads with CAGR numbers. Data shows regime resilience messaging (2022, 2025) drives more positive replies. This variant leads with resilience."
            }
        ],
        "sequence_suggestions": [
            {
                "suggestion": "Reduce delay between Step 1 (LinkedIn) and Step 2 (Email) from 2 days to 1 day",
                "rationale": "Contacts actioned within 24h of LinkedIn connect have 23% higher email open rates based on current data."
            }
        ],
        "generated_at": "2026-03-03T10:00:00Z"
    }
```

**Prompt structure for Claude API call:**

```
You are analyzing outreach campaign performance for Metaworld Fund, a quantitative
momentum fund. You have the following data:

## Current Templates and Performance
[template texts + metrics table]

## Response Patterns by Segment
[firm_type breakdown, AUM tier breakdown]

## Recent Responses
[last 20 positive replies: which template, which step, which channel]
[last 20 negative replies: same]

## Current Sequence Timing
[step → delay mapping with reply rates at each step]

Based on this data:
1. What patterns do you see? What's working and what isn't?
2. Suggest 1-2 new email template variants that might outperform current ones.
3. Suggest timing or channel order adjustments.
4. Flag any segments we should deprioritize or prioritize.

Be specific and data-driven. Reference actual numbers.
```

### 1.4 Adaptive Queue (replaces static priority_queue.py)

The new queue system replaces `get_daily_queue()` with `get_adaptive_queue()`:

```python
# src/services/adaptive_queue.py

def get_adaptive_queue(conn, campaign_id, target_date=None, limit=20) -> list[dict]:
    """
    Returns today's recommended actions, ordered by priority_score.

    Each item includes:
    {
        "contact_id": 42,
        "contact_name": "John Smith",
        "company_name": "Crypto Capital",
        "aum_millions": 500,
        "priority_score": 0.85,

        # Adaptive recommendation:
        "recommended_channel": "email",
        "recommended_template_id": 14,
        "rendered_subject": "Quick introduction — Metaworld Fund",
        "rendered_body": "Hi John, ...",
        "selection_reason": "Template 14 has 11.1% positive rate for $500M+ funds",

        # LinkedIn info (if linkedin action):
        "linkedin_url": "https://linkedin.com/in/johnsmith",
        "linkedin_message": "Hi John, ...",

        # Context:
        "previous_touches": 2,
        "last_touch_channel": "linkedin_connect",
        "last_touch_date": "2026-02-28",
        "is_gdpr": false,

        # Operator controls:
        "can_override_template": true,
        "alternative_templates": [{"id": 15, "name": "...", "positive_rate": 0.08}]
    }
    """
```

**Key difference from old queue:** The old queue just looked at `next_action_date <= today` and returned rows. The new queue actively recommends *what* to send and *why*, while still respecting the one-per-company rule and GDPR limits.

### 1.5 Database Schema Additions

```sql
-- Migration 002: Adaptive engine + web app

-- Track which templates were sent to which contacts (prevents repeats)
CREATE TABLE IF NOT EXISTS contact_template_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    template_id INTEGER NOT NULL REFERENCES templates(id),
    channel TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(contact_id, campaign_id, template_id)
);

-- LLM advisor run history
CREATE TABLE IF NOT EXISTS advisor_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    insights_json TEXT NOT NULL,          -- full JSON response from LLM
    template_suggestions_json TEXT,       -- suggested new templates
    sequence_suggestions_json TEXT,       -- timing/channel suggestions
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Gmail draft tracking
CREATE TABLE IF NOT EXISTS gmail_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    template_id INTEGER REFERENCES templates(id),
    gmail_draft_id TEXT,
    gmail_message_id TEXT,
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    body_html TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | drafted | sent | failed
    pushed_at TEXT,
    sent_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(contact_id, campaign_id, template_id)
);

-- Response notes (free-text context)
CREATE TABLE IF NOT EXISTS response_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    note TEXT NOT NULL,
    response_type TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Configuration for adaptive engine parameters
CREATE TABLE IF NOT EXISTS engine_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    config_key TEXT NOT NULL,
    config_value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(campaign_id, config_key)
);

CREATE INDEX IF NOT EXISTS idx_cth_contact ON contact_template_history(contact_id, campaign_id);
CREATE INDEX IF NOT EXISTS idx_gmail_status ON gmail_drafts(status);
CREATE INDEX IF NOT EXISTS idx_gmail_contact ON gmail_drafts(contact_id);
CREATE INDEX IF NOT EXISTS idx_advisor_campaign ON advisor_runs(campaign_id);
CREATE INDEX IF NOT EXISTS idx_response_notes_contact ON response_notes(contact_id);
```

### 1.6 How Existing Modules Connect

```
KEPT AS-IS (no changes):
├── models/database.py          ← DB connection + migrations
├── models/campaigns.py         ← All CRUD operations
├── services/state_machine.py   ← Status transitions + auto-activation
├── services/deduplication.py   ← 3-pass dedup
├── services/compliance.py      ← CAN-SPAM/GDPR
├── services/template_engine.py ← Jinja2 rendering
├── services/newsletter.py      ← Newsletter management
├── services/email_verifier.py  ← ZeroBounce/Hunter
├── src/cli.py                  ← CLI still works

ENHANCED (additive changes only):
├── services/metrics.py         ← Add get_aum_tier_breakdown()
├── services/ab_testing.py      ← Add get_explore_exploit_assignment()
├── services/email_sender.py    ← Add create_gmail_draft() alongside send_email()

NEW:
├── services/response_analyzer.py    ← Computes performance scores
├── services/contact_scorer.py       ← Scores + recommends per contact
├── services/template_selector.py    ← Picks best template (explore/exploit)
├── services/adaptive_queue.py       ← Replaces static queue with smart queue
├── services/llm_advisor.py          ← Claude API integration for insights
├── services/gmail_drafter.py        ← Gmail API OAuth2 + draft creation
├── api/main.py                      ← FastAPI app
├── api/routes/                      ← REST endpoints
└── frontend/                        ← React app
```

### 1.7 Trade-off Analysis

| Decision | Choice | Why | Risk |
|---|---|---|---|
| SQLite vs PostgreSQL | Keep SQLite | Single user, <1000 contacts, no concurrent writes. Simple. | If multi-user needed later, migration effort. Low risk given use case. |
| LLM for template generation | Claude API (on-demand) | Operator reviews all suggestions. Not autonomous. Costs ~$0.10/analysis. | API key needed. Suggestions may be poor. Mitigated by human-in-the-loop. |
| Explore/exploit for templates | Simplified Thompson Sampling | Full Bayesian is overkill for <1000 contacts. Simple percentage-based exploration works. | May converge on local optima. Mitigated by periodic LLM-generated new variants. |
| Gmail Draft vs SMTP direct | Gmail Draft for outreach, SMTP for newsletters | Operator wants to review every outreach email. Newsletters are bulk. | Gmail API quota (250 units/sec). Not a concern at 15 drafts/day. |
| Local vs deployed | Local (localhost) | All contact data stays on machine. No hosting cost. No auth needed. | Can't access remotely. Acceptable for solo operator. |

---

## Part 2: UI Design Handoff — Page-by-Page Specs

### 2.0 Design System

**Tech stack:** React 18 + TypeScript + Tailwind CSS + Recharts

**Layout:** Fixed sidebar navigation + main content area. Desktop-optimized (1440px+).

**Color tokens:**

| Token | Value | Usage |
|---|---|---|
| `bg-primary` | `#0F172A` (slate-900) | Sidebar, headers |
| `bg-surface` | `#FFFFFF` | Content cards |
| `bg-page` | `#F8FAFC` (slate-50) | Page background |
| `text-primary` | `#0F172A` | Headings, body text |
| `text-secondary` | `#64748B` (slate-500) | Secondary text, labels |
| `accent-blue` | `#3B82F6` | Primary buttons, links, active states |
| `status-positive` | `#22C55E` (green-500) | Positive replies, success |
| `status-negative` | `#EF4444` (red-500) | Negative replies, errors |
| `status-neutral` | `#F59E0B` (amber-500) | No response, warnings |
| `status-linkedin` | `#0A66C2` | LinkedIn channel badge |
| `status-email` | `#6366F1` (indigo-500) | Email channel badge |

**Typography:**

| Element | Font | Size | Weight |
|---|---|---|---|
| Page title | Inter | 24px | 700 |
| Section header | Inter | 18px | 600 |
| Card title | Inter | 16px | 600 |
| Body text | Inter | 14px | 400 |
| Label / caption | Inter | 12px | 500 |
| Monospace (code/templates) | JetBrains Mono | 13px | 400 |

**Spacing:** 4px base unit. Use multiples: 8, 12, 16, 24, 32, 48.

**Border radius:** Cards 8px, Buttons 6px, Badges 4px, Inputs 6px.

### 2.1 Sidebar Navigation

```
┌──────────────────┐
│  METAWORLD FUND  │  ← Logo area
│  Outreach        │
├──────────────────┤
│ ◉ Dashboard      │  ← /
│ ○ Queue          │  ← /queue
│ ○ Campaigns      │  ← /campaigns
│ ○ Contacts       │  ← /contacts
│ ○ Templates      │  ← /templates
│ ○ Insights       │  ← /insights (LLM advisor)
├──────────────────┤
│ ○ Settings       │  ← /settings
│   Gmail: ✅ Connected │
│   API: ✅ Active     │
└──────────────────┘
```

Width: 240px fixed. Collapses to icon-only (64px) on screens <1280px.

### 2.2 Page: Dashboard (`/`)

```
┌─────────────────────────────────────────────────────────────────┐
│  Dashboard                                          March 3, 2026│
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Enrolled │ │ Positive │ │ Reply    │ │ Calls    │          │
│  │   847    │ │   42     │ │  Rate    │ │ Booked   │          │
│  │          │ │ ▲ +3     │ │  8.2%    │ │   14     │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│                                                                  │
│  TODAY'S QUEUE (12 actions)           [Push All Email Drafts ▶] │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ #  Contact        Company         Channel  Score  Action │   │
│  │ 1  John Smith     Crypto Capital  📧 Email  0.92  [Push] │   │
│  │ 2  Jane Doe       Alpha Fund      🔗 LI     0.87  [Copy] │   │
│  │ 3  Bob Chen       DeFi Ventures   📧 Email  0.85  [Push] │   │
│  │ ...                                                       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  WEEKLY TREND                         WHAT'S WORKING            │
│  ┌───────────────────────┐           ┌──────────────────────┐   │
│  │  📊 Line chart:       │           │ ✅ Template A: 11.1%  │   │
│  │  emails sent (blue)   │           │ ✅ $500M-1B tier: 18% │   │
│  │  replies (green)      │           │ ⚠️ Template B: 4.8%   │   │
│  │  over past 4 weeks    │           │ 💡 "Consider retiring │   │
│  │                       │           │    Variant B"          │   │
│  └───────────────────────┘           └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**Components:**

| Component | Props | Notes |
|---|---|---|
| `MetricCard` | `label`, `value`, `change`, `changeDirection` | 4 across, equal width |
| `QueueTable` | `items[]`, `onPushDraft`, `onCopyMessage`, `onMarkDone` | Sortable by score |
| `WeeklyTrendChart` | `weeklyData[]` | Recharts LineChart, 4 weeks |
| `InsightPanel` | `insights[]` | From latest `advisor_runs` |

**States:**
- Empty: "No contacts enrolled yet. Import contacts to get started." + Import CTA
- Loading: Skeleton cards + skeleton table rows
- Error: Red banner with retry button

### 2.3 Page: Queue (`/queue`)

This is the primary daily workflow page.

```
┌─────────────────────────────────────────────────────────────────┐
│  Daily Queue — March 3, 2026                  [Push All Drafts] │
│  12 actions  •  7 emails  •  5 LinkedIn                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─ EMAIL ACTION CARD ──────────────────────────────────────┐   │
│  │  John Smith  •  Crypto Capital  •  $500M AUM  •  🟢 0.92│   │
│  │  Step 2 of 7  •  Last touch: LinkedIn Connect (Feb 28)   │   │
│  │                                                           │   │
│  │  Why this template: "Template 14 has 11.1% positive      │   │
│  │  rate for $500M+ funds. Variant A outperforms B by 2.3x" │   │
│  │                                                           │   │
│  │  Subject: Quick introduction — Metaworld Fund             │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ Hi John,                                          │    │   │
│  │  │                                                    │    │   │
│  │  │ I run Metaworld Fund — a quantitative momentum     │    │   │
│  │  │ strategy trading BTC, ETH, gold and FX. We have    │    │   │
│  │  │ been live since 2014...                             │    │   │
│  │  │                                                    │    │   │
│  │  │ [editable textarea — full rendered email]           │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  │                                                           │   │
│  │  [✏️ Edit] [📋 Use Different Template ▾] [📤 Push to Gmail]│   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ LINKEDIN ACTION CARD ───────────────────────────────────┐   │
│  │  Jane Doe  •  Alpha Fund  •  $1.2B AUM  •  🔗 0.87      │   │
│  │  Step 3 of 7  •  Last touch: Email Cold (Mar 1)          │   │
│  │  Connected: ✅ Yes                                        │   │
│  │                                                           │   │
│  │  Action: Send follow-up DM                                │   │
│  │  [🔗 Open LinkedIn Profile]  [🔗 Open in Sales Navigator] │   │
│  │                                                           │   │
│  │  Message:                                                 │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ Hi Jane, thanks for connecting...                  │    │   │
│  │  │ [copyable text block]                              │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  │                                                           │   │
│  │  [📋 Copy Message] [✅ Mark as Done] [⏭️ Skip]            │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Email Action Card components:**

| Element | State | Behavior |
|---|---|---|
| Email body | Default | Read-only rendered preview |
| Email body | Edit mode | Editable textarea, preserves Jinja2 output |
| "Push to Gmail" button | Default | Blue primary button |
| "Push to Gmail" button | Loading | Spinner, disabled |
| "Push to Gmail" button | Success | Green check, "Draft Created" label |
| "Use Different Template" | Click | Dropdown with alternative templates + their performance stats |

**LinkedIn Action Card components:**

| Element | State | Behavior |
|---|---|---|
| "Open LinkedIn Profile" | Click | Opens `linkedin_url` in new tab |
| "Open in Sales Navigator" | Click | Opens `https://www.linkedin.com/sales/people/` + URL slug in new tab |
| "Copy Message" | Click | Copies to clipboard, button text changes to "Copied!" for 2s |
| "Mark as Done" | Click | Logs event, advances step, card slides out with success animation |
| "Skip" | Click | Confirmation modal: "Skip this action? Contact will be actioned on next available date." |

**Responsive behavior:**
- Desktop (>1280px): Cards in single column, full width
- All cards stack vertically. No multi-column layout needed — this is a sequential workflow.

### 2.4 Page: Contact Detail (`/contacts/:id`)

```
┌─────────────────────────────────────────────────────────────────┐
│  ← Back to Contacts                                              │
│                                                                  │
│  ┌─ CONTACT INFO ───────────────────────────────────────────┐   │
│  │  John Smith                                               │   │
│  │  Managing Director, Crypto Capital                        │   │
│  │  john@cryptocapital.com (✅ verified)                      │   │
│  │  [🔗 LinkedIn] [🔗 Sales Navigator]                       │   │
│  │  AUM: $500M  •  GDPR: No  •  Status: in_progress         │   │
│  │  Campaign: Q1_2026_initial (Step 3 of 7)                  │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ LOG RESPONSE ────────────────────────────────────────────┐  │
│  │  [👍 Positive] [👎 Negative] [📞 Call Booked] [⏸️ No Response]│
│  │  Note: [________________________________] (optional)       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─ TIMELINE ────────────────────────────────────────────────┐  │
│  │                                                            │  │
│  │  Mar 3  📧 Email follow-up drafted → Gmail                │  │
│  │         Template: follow_up_v1 • Subject: "Following up"  │  │
│  │                                                            │  │
│  │  Mar 1  📧 Email cold sent                                │  │
│  │         Template: cold_outreach_v1_a • Variant A           │  │
│  │                                                            │  │
│  │  Feb 28 🔗 LinkedIn connection sent                       │  │
│  │         Note: connect_note_v1                              │  │
│  │                                                            │  │
│  │  Feb 28 ⚡ Enrolled in Q1_2026_initial                    │  │
│  │         Priority score: 0.85 • AUM tier: $500M-1B         │  │
│  │                                                            │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Response logging interaction:**
1. Click response button (Positive / Negative / Call Booked / No Response)
2. Optional: type a note in the text field
3. Button triggers `POST /api/contacts/{id}/status` → state machine transition
4. Timeline refreshes, new event appears at top
5. If terminal state → toast notification: "Next contact at Crypto Capital auto-activated: Sarah Lee"

### 2.5 Page: Insights (`/insights`)

This is the LLM Advisor output page.

```
┌─────────────────────────────────────────────────────────────────┐
│  Campaign Insights                        [🔄 Run New Analysis] │
│  Last analyzed: March 2, 2026 at 10:15 AM                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  WHAT'S WORKING                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ • Template A outperforms B by 2.3x on positive replies    │  │
│  │   (11.1% vs 4.8%). Consider retiring Variant B.           │  │
│  │ • $500M-1B AUM tier has 18% reply rate — highest segment  │  │
│  │ • LinkedIn-first sequences convert 40% better than        │  │
│  │   email-first                                              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  SUGGESTED NEW TEMPLATES                                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 📧 "Regime Resilience Lead" (Email Cold — new variant)     │  │
│  │ Rationale: Positive replies correlate with regime          │  │
│  │ resilience messaging. This variant leads with 2022/2025.  │  │
│  │                                                            │  │
│  │ Subject: "Positive returns through 2022 and 2025"          │  │
│  │ ┌────────────────────────────────────────────────────┐    │  │
│  │ │ Hi {{first_name}},                                  │    │  │
│  │ │ Most crypto strategies lost money in 2022...         │    │  │
│  │ │ [full template text]                                 │    │  │
│  │ └────────────────────────────────────────────────────┘    │  │
│  │                                                            │  │
│  │ [✅ Add as New Template] [✏️ Edit First] [❌ Dismiss]       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  PERFORMANCE BY SEGMENT                                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  📊 Heatmap: Firm Type × AUM Tier → Positive Reply Rate   │  │
│  │  (Recharts heatmap or table with color-coded cells)        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  HISTORY                                                         │
│  │ Mar 2: Analysis run — 3 insights, 1 template suggestion    │  │
│  │ Feb 23: Analysis run — 2 insights, 2 template suggestions  │  │
│  │ Feb 16: Analysis run — 4 insights, 0 template suggestions  │  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**"Add as New Template" flow:**
1. Click button → template is saved to `templates` table with `is_active = 1`
2. Template selector starts including it in explore pool (20-30% exploration rate for new templates)
3. After 15+ sends, it gets its own confidence score and enters the exploit pool

### 2.6 Page: Campaign Report (`/campaigns/:name`)

Mirrors existing CLI `report` command output as visual charts:

- **Metrics cards:** enrolled, by-status, reply rate, positive rate
- **Funnel chart:** enrolled → actioned → replied → positive → call booked
- **A/B variant comparison:** table + bar chart
- **Firm type heatmap:** reply rate by firm type
- **AUM tier chart:** bar chart of reply rates by AUM bucket
- **Weekly trend:** line chart over campaign lifetime

### 2.7 Page: Templates (`/templates`)

- List all templates in a table: name, channel, variant group, sends, positive rate, status
- Click to edit: code editor (monospace) with Jinja2 syntax
- Live preview panel: renders with sample contact data
- "Create New Template" button
- "Deactivate" toggle (soft delete — stops the selector from using it)

### 2.8 Page: Settings (`/settings`)

- Gmail OAuth2: Connect/Disconnect button, status indicator
- Claude API key: masked input field, test button
- Campaign config: physical address, calendly URL, GDPR countries
- Engine parameters: exploration rate, minimum sends for confidence, scoring weights
- Database stats: companies, contacts, verified emails (reuse existing `stats` command)

---

## Part 3: Feature Spec — Adaptive Sequence Mechanism

### 3.1 Problem Statement

Static outreach sequences treat all contacts the same regardless of what the campaign data shows. Templates that underperform keep getting sent. Channels that work better for certain segments aren't prioritized. The operator has to manually analyze data, update templates, and adjust timing — a process that happens weekly at best.

**Who is affected:** The campaign operator (Helmut), who manages outreach to ~875 crypto fund allocators.

**Cost of not solving:** Wasted outreach on underperforming templates, missed opportunities to double down on what works, slower iteration cycles.

### 3.2 User Stories

**As the campaign operator, I want to...**

1. See today's queue **with recommended actions and reasoning** — so I understand why the system suggests Template A over Template B for each contact
2. Override any recommendation with a different template or channel — so I maintain full control
3. Have the system automatically prefer higher-performing templates — so I don't manually track which variants win
4. Get LLM-generated insights and new template suggestions — so I can iterate faster than my own analysis allows
5. See performance data at every level (template, channel, segment, timing) — so I can make informed decisions
6. Accept or reject suggested templates with one click — so new variants enter the rotation quickly
7. Understand the explore/exploit trade-off — so I know when the system is testing versus exploiting

### 3.3 Requirements

#### P0 — Must-Have

| Requirement | Acceptance Criteria |
|---|---|
| **Adaptive queue** replaces static queue | Queue returns recommended template + channel per contact. Ordering by priority_score not just AUM. Same one-per-company rule. All existing compliance (GDPR, unsub, email verification) respected. |
| **Template performance tracking** | Every send records which template was used in `contact_template_history`. Response Analyzer computes positive_rate per template with sends >= 5. |
| **Explore/exploit template selection** | System selects highest-performing template 70-95% of the time (based on data volume). Remaining time it explores less-tested templates. Operator can see which mode was used. |
| **Never-repeat rule** | A contact never receives the same template twice within a campaign. Enforced by `contact_template_history` UNIQUE constraint. |
| **Channel alternation** | System never sends 3 consecutive actions on the same channel. Prefers the channel with higher segment reply rate. |
| **Operator override** | Every queue item has a "Use Different Template" dropdown showing alternatives with their stats. Override is logged. |
| **Gmail Draft creation** | OAuth2 flow to authorize Gmail. "Push to Gmail Draft" creates draft via API. Batch "Push All" button. Draft status tracked. |
| **Response logging** | One-click response logging (positive/negative/call-booked/no-response) with optional note. State machine transitions work exactly as existing CLI. |
| **Contact timeline** | Full event history per contact, ordered chronologically. Shows template used, channel, outcome. |

#### P1 — Nice-to-Have

| Requirement | Acceptance Criteria |
|---|---|
| **LLM Advisor** | "Run Analysis" button calls Claude API with campaign data. Returns insights + template suggestions. Suggestions can be accepted as new templates with one click. History of past runs visible. |
| **Segment heatmap** | Visual breakdown of reply rates by firm_type × AUM tier. Color-coded cells. |
| **Template editor** | Inline editing with Jinja2 syntax highlighting + live preview with sample contact data. |
| **CSV import via browser** | File upload, preview, dedup, import — all in the UI. |
| **Timing optimization** | Response Analyzer tracks reply rates by delay interval. Suggestions for optimal timing appear in Insights page. |

#### P2 — Future Considerations

| Requirement | Notes |
|---|---|
| **Auto-generated email variants** | LLM creates new variants automatically when a template underperforms. Operator approves before activation. Design for this now by keeping template creation as a simple DB insert. |
| **Send-time optimization** | Track which day-of-week and time-of-day gets best responses. Recommend optimal send times for Gmail drafts. |
| **Multi-campaign learning** | Transfer learning: insights from Campaign A inform Campaign B's starting templates. |
| **Slack integration** | Daily queue summary posted to Slack channel. |

### 3.4 Success Metrics

**Leading (change within weeks):**
- Positive reply rate improves by **>20%** vs static sequence baseline within 4 weeks of adaptive engine launch
- Template exploration discovers at least **1 variant** that outperforms the original within 6 weeks
- Daily workflow time (queue review to all actions complete) stays **<15 minutes**
- LLM Advisor surfaces at least **2 actionable insights** per weekly run

**Lagging (change over months):**
- Call booking rate reaches **>3%** of enrolled contacts within 2 months
- Template iteration velocity: **new variant tested every 1-2 weeks** (up from ~monthly)
- Contact coverage: **100% of daily queue processed** (no skips due to unclear recommendations)

---

## Part 4: Implementation Order for Claude Code

### Phase 1: Backend API (Week 1)

**Goal:** FastAPI layer exposing existing services. No adaptive logic yet — just wraps the current static queue.

```
1. Create src/api/main.py (FastAPI app with CORS)
2. Create src/api/dependencies.py (DB connection dependency)
3. Create migration 002_web_app.sql
4. Create API routes:
   - GET  /api/queue/{campaign}
   - GET  /api/campaigns
   - GET  /api/campaigns/{name}/metrics
   - GET  /api/contacts/{id}
   - GET  /api/contacts/{id}/events
   - POST /api/contacts/{id}/status
   - GET  /api/templates
   - PUT  /api/templates/{id}
   - POST /api/templates
   - GET  /api/stats
5. All existing tests still pass
6. Add Makefile target: make api (uvicorn src.api.main:app --reload)
```

### Phase 2: Frontend Shell (Week 2)

**Goal:** React app with all pages, using Phase 1 API. Static queue (no adaptive logic yet).

```
1. Set up frontend/ (Vite + React + TypeScript + Tailwind)
2. Implement sidebar navigation
3. Implement pages:
   - Dashboard (metrics cards + queue table + weekly chart)
   - Queue (action cards — email preview + LinkedIn cards)
   - Contact detail (info + timeline + response logging)
   - Campaign report (metrics + charts)
   - Templates (list + edit)
   - Settings (placeholder)
4. Add Makefile target: make frontend (cd frontend && npm run dev)
5. Add Makefile target: make dev (run both API + frontend concurrently)
```

### Phase 3: Adaptive Engine (Week 3)

**Goal:** Replace static queue with intelligent recommendations.

```
1. Create src/services/response_analyzer.py
2. Create src/services/contact_scorer.py
3. Create src/services/template_selector.py (explore/exploit)
4. Create src/services/adaptive_queue.py
5. Update API routes to use adaptive queue
6. Update frontend Queue page to show reasoning + alternatives
7. Write tests for scoring, selection, and never-repeat logic
```

### Phase 4: Gmail + LLM Integration (Week 4)

**Goal:** Gmail Draft creation + Claude API advisor.

```
1. Create src/services/gmail_drafter.py (OAuth2 + draft creation)
2. Add API routes: /api/gmail/authorize, /api/gmail/callback, /api/gmail/drafts
3. Update Queue page: "Push to Gmail Draft" + "Push All" buttons
4. Create src/services/llm_advisor.py (Claude API)
5. Add API route: POST /api/insights/analyze, GET /api/insights/history
6. Create Insights page in frontend
7. "Add as Template" flow from suggestion to templates table
```

### Phase 5: Polish & Iteration (Week 5)

```
1. CSV import via browser
2. Template editor with live preview
3. Segment heatmap on Insights page
4. Settings page (Gmail auth, API key, engine params)
5. End-to-end testing
6. Documentation update (README, CLAUDE.md)
```

---

## Appendix A: API Route Specifications

```
# All routes return JSON. Errors return { "error": "message" }.

GET  /api/queue/{campaign}
  Query: ?date=YYYY-MM-DD&limit=20
  Returns: { "items": [AdaptiveQueueItem], "total": int }

  AdaptiveQueueItem: {
    contact_id, contact_name, company_name, aum_millions,
    priority_score, recommended_channel, recommended_template_id,
    rendered_subject, rendered_body, selection_reason,
    linkedin_url, linkedin_message,
    previous_touches, last_touch_channel, last_touch_date,
    is_gdpr, alternative_templates: [{id, name, positive_rate}]
  }

POST /api/contacts/{id}/status
  Body: { "outcome": "positive|negative|no_response|call_booked", "note": "optional text", "campaign": "optional name" }
  Returns: { "new_status": str, "auto_activated": { "contact_id": int, "name": str } | null }

POST /api/gmail/drafts
  Body: { "contact_id": int, "campaign": str, "template_id": int, "subject": str, "body": str }
  Returns: { "draft_id": str, "status": "drafted" }

POST /api/gmail/drafts/batch
  Body: { "items": [{ contact_id, campaign, template_id, subject, body }] }
  Returns: { "created": int, "failed": int, "drafts": [{ contact_id, draft_id, status }] }

POST /api/insights/analyze
  Body: { "campaign": str }
  Returns: { "insights": [str], "template_suggestions": [...], "sequence_suggestions": [...] }

GET  /api/insights/history
  Query: ?campaign=str&limit=10
  Returns: { "runs": [{ id, created_at, insights_count, suggestions_count }] }
```

## Appendix B: Environment Variables

```bash
# Existing (unchanged)
DATABASE_PATH=outreach.db
SMTP_PASSWORD=<secret>
EMAIL_VERIFY_API_KEY=<api-key>
EMAIL_VERIFY_PROVIDER=zerobounce

# New
GMAIL_CLIENT_ID=<google-oauth-client-id>
GMAIL_CLIENT_SECRET=<google-oauth-client-secret>
GMAIL_REDIRECT_URI=http://localhost:8000/api/gmail/callback
ANTHROPIC_API_KEY=<claude-api-key>      # For LLM Advisor
```

## Appendix C: File Structure

```
outreach-campaign/
├── (all existing files unchanged)
├── src/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── dependencies.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── queue.py
│   │       ├── campaigns.py
│   │       ├── contacts.py
│   │       ├── templates.py
│   │       ├── gmail.py
│   │       ├── insights.py
│   │       ├── import_routes.py
│   │       └── stats.py
│   └── services/
│       ├── (existing files unchanged)
│       ├── response_analyzer.py     # NEW
│       ├── contact_scorer.py        # NEW
│       ├── template_selector.py     # NEW
│       ├── adaptive_queue.py        # NEW
│       ├── llm_advisor.py           # NEW
│       └── gmail_drafter.py         # NEW
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/
│       │   └── client.ts            # Fetch wrapper for all endpoints
│       ├── components/
│       │   ├── Sidebar.tsx
│       │   ├── MetricCard.tsx
│       │   ├── QueueTable.tsx
│       │   ├── EmailActionCard.tsx
│       │   ├── LinkedInActionCard.tsx
│       │   ├── ContactTimeline.tsx
│       │   ├── InsightPanel.tsx
│       │   └── TemplateEditor.tsx
│       ├── pages/
│       │   ├── Dashboard.tsx
│       │   ├── Queue.tsx
│       │   ├── Campaigns.tsx
│       │   ├── CampaignReport.tsx
│       │   ├── Contacts.tsx
│       │   ├── ContactDetail.tsx
│       │   ├── Templates.tsx
│       │   ├── Insights.tsx
│       │   └── Settings.tsx
│       └── types/
│           └── index.ts             # TypeScript interfaces matching API
├── migrations/
│   ├── 001_initial_schema.sql
│   └── 002_web_app.sql
├── tests/
│   ├── (existing tests unchanged)
│   ├── test_response_analyzer.py
│   ├── test_contact_scorer.py
│   ├── test_template_selector.py
│   ├── test_adaptive_queue.py
│   └── test_api.py
└── Makefile                          # Add: api, frontend, dev targets
```
