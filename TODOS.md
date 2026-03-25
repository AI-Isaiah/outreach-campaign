# TODOS

## P0 — Daily Outreach System (B+C Plan)

### Phase 3: Reply feedback + template badge
**Priority:** P0
**Files:** `src/enums.py`, `src/services/state_machine.py`, `frontend/src/pages/CampaignDetail.tsx`, `frontend/src/pages/Templates.tsx`, migration `022_replied_neutral.sql`
**What:** Add REPLIED_NEUTRAL status (NOT terminal — no auto-activation). Map reply_detector's "neutral" → REPLIED_NEUTRAL. Reply breakdown (positive/neutral/negative) in analytics. "Winning" template badge reusing `response_analyzer.py:get_template_performance()`.
**Design decisions:** replied_neutral badge: `bg-purple-100 text-purple-700`. Winning badge: `bg-green-100 text-green-800` with Lucide Trophy icon. Reply breakdown: stacked bar (green/purple/red).
**Tests needed:** 8 (state machine + metrics).

### Phase 4: Research-powered messages
**Priority:** P0
**Files:** new `src/services/message_drafter.py`, `src/services/deep_research_service.py`, `src/application/queue_service.py`, `src/web/routes/queue.py`, `frontend/src/types/index.ts`, migration `023_message_drafts.sql`
**What:** LLM draft generation at research-completion time (Claude Haiku). Stored in message_drafts table. Batch-queried in _batch_enrich() alongside gmail_drafts. Queue cards show draft_text when available, Jinja2 fallback when null. Error isolation: Haiku failure does NOT affect research completion.
**Design decisions:** Draft indicator: "AI-drafted from research" label in `text-xs text-purple-600` with Lucide Sparkles icon. Edit button opens inline panel.
**Schema:** `message_drafts(id, contact_id FK, campaign_id FK, step_order, draft_text, model, generated_at, research_id FK, user_id FK, UNIQUE(contact_id, campaign_id, step_order))`
**Tests needed:** 8 (drafter + queue integration).

### Phase 5: Campaign kanban
**Priority:** P1
**Files:** `frontend/src/pages/CampaignDetail.tsx`, `src/web/routes/campaigns.py`
**What:** "Pipeline" tab in CampaignDetail. Columns = sequence steps, cards = contacts. dnd-kit drag for step changes.
**Engineering decisions:** Drag calls `update_contact_campaign_status(current_step=N)` — NOT `transition_contact()` (steps != statuses). Backend owns delay_days calculation. Forward AND backward drags allowed. Log `step_manual_advance` event.
**Design decisions:** Compact cards (~40px): company bold + contact + StatusBadge + channel icon. Ghost card `opacity-50 ring-2 ring-blue-400`. Empty column: "No contacts at this step". Mobile: disable drag, show "Move to step" dropdown. A11y: `role="list"` on columns, keyboard arrow nav.
**Tests needed:** 7 (API + frontend).

---

### Smart duplicate resolution workflow (V2)
**Priority:** P1
**Files:** `frontend/src/components/DuplicateComparisonPanel.tsx`, `frontend/src/pages/SmartImport.tsx`, `src/services/smart_import.py`
**What:** Three improvements to how duplicates are handled during import:

1. **CRM matches: auto-merge when safe, flag when not.** If a LinkedIn match exists in the CRM with the same email+company → auto-merge (fill empty fields). If email or company differs → flag for manual review. Show what matched ("LinkedIn URL matches existing CRM contact: John Smith at Acme Corp").

2. **Dedicated "Duplicates to Clean" review view.** Non-mergeable duplicates (different email or different company for the same LinkedIn) get a separate overview. Each row shows the import contact vs. the CRM contact side-by-side, with a clickable LinkedIn link so the user can open LinkedIn, check the real info, and edit. These are likely company changes or data quality issues.

3. **File duplicates: show which might be newer.** When the same contact appears multiple times in the CSV (e.g., a person who changed companies), surface both occurrences side-by-side so the user can pick which one to import. Currently just says "File duplicate" with no context about which entry to keep.

**Why:** Users need to understand WHY something is flagged and have easy tools to resolve it. LinkedIn is the source of truth for fund allocator contacts — make it one click away. A contact showing up twice in a CSV often means they changed firms, which is the most valuable signal for outreach.

### Multi-contact columns show "Ignore" in mapping UI
**Priority:** P1
**Files:** `frontend/src/pages/SmartImport.tsx`
**What:** When the LLM detects multi-contact columns (Contact 2, Contact 2 Title, etc.), they appear as "Ignore" in the mapping dropdowns. The data IS handled correctly by the multi_contact explosion logic in `transform_rows()`, but the UI doesn't communicate this. Show these columns as "Handled by multi-contact detection" or group them visually under their contact slot (e.g., "Contact 2: Full Name, Title, Email, LinkedIn").
**Why:** Users think the data will be lost. Misleading UX erodes trust in the import tool.

### Import source tagging
**Priority:** P1
**Files:** `src/services/smart_import.py`, `frontend/src/pages/SmartImport.tsx`
**What:** Contacts imported via Smart Import should get a tag indicating their source CSV (e.g., "Crypto_Fund_List CSV.csv" or a user-chosen label). After import, the "View Contacts" button should filter by this tag so users can see exactly what was imported. The `source_label` field already exists in import_jobs — use it to auto-tag imported contacts.
**Why:** After importing 2,600 contacts, users land on the contacts page with no way to find what they just imported.

### Fix: Campaign Wizard template selector is non-functional
**Priority:** P0
**Files:** `frontend/src/pages/CampaignWizard.tsx`
**What:** Step 4 ("Choose message templates") shows "No template selected" for each sequence step but there's no way to actually select a template — no dropdown, no picker, no click action. The template selector UI needs to be implemented: click a step → dropdown of existing templates filtered by channel (LinkedIn templates for LinkedIn steps, email templates for email steps) → select → preview shows inline.
**Why:** Users can't complete campaign setup without assigning templates to sequence steps. This is a broken step in the wizard.

### Smart Message: LLM-powered sequence generation in campaign wizard
**Priority:** P1
**Files:** `frontend/src/pages/CampaignWizard.tsx`, new `src/services/message_drafter.py`, `src/web/routes/templates.py`
**What:** Each sequence step gets three options: (1) **Select existing template**, (2) **Write manually** with channel-aware limits (LinkedIn connect: 300 chars), (3) **Smart Message** — LLM generates the message. Smart Message combines two layers:
  - **Best practices layer:** Proven cold outreach patterns baked into the system prompt — optimal sequence structure (LinkedIn connect → email → follow-up timing), tone frameworks (AIDA, problem-agitate-solve), channel-specific rules (LinkedIn connect is short/personal, email can be longer/value-driven). Research internet best practices for crypto fund outreach sequences specifically.
  - **Research layer:** Per-target company research via existing deep research pipeline (Perplexity + Claude) or lighter single-query lookup. User describes what they're selling/their fund thesis. LLM generates the full sequence personalized with company-specific talking points.
  - **Improve mode:** User pastes their draft, LLM refines it using the best-practice rules and channel constraints. Returns improved version with explanations of what changed and why.
**Why:** Most users don't have templates. The first campaign is where they need the most help. "Best practice + smart research + LLM text" is the formula — not just generation, but generation informed by what actually works in fund allocator outreach.

### Campaign Wizard: select contacts from CRM database
**Priority:** P0
**Files:** `frontend/src/pages/CampaignWizard.tsx`, `src/web/routes/contacts.py`
**What:** Campaign Wizard step 2 ("Add contacts") currently only allows CSV upload. Add a second option: "Select from existing contacts" with a searchable/filterable contact picker. Filter by company, tag, import source, status. Support select-all with filters applied (e.g., "select all 108 contacts imported today"). This is the primary flow — CSV upload should be secondary ("or import new contacts from CSV").
**Why:** After importing contacts via Smart Import, the next step is creating a campaign with those contacts. Forcing a second CSV upload defeats the purpose of having a CRM. This is the #1 gap in the campaign creation flow.

### Post-import campaign creation flow
**Priority:** P1
**Files:** `frontend/src/pages/SmartImport.tsx`, `frontend/src/pages/CampaignWizard.tsx`
**What:** After successful import, offer "Create Campaign with Imported Contacts" as the primary action (instead of just "View Contacts"). Pre-populate the campaign wizard with the imported contacts already selected. If the user selected "Enroll in campaign" during import, navigate to that campaign after completion.
**Why:** Import is step 1 of the outreach workflow. The next step is always creating or enrolling in a campaign. The current flow dumps users on the contacts page with no clear next step.

### Streamlined merge-and-dismiss workflow
**Priority:** P1
**Files:** `frontend/src/pages/SmartImport.tsx`, `frontend/src/components/DuplicateComparisonPanel.tsx`
**What:** Replace dual-checkbox pattern (select + import) with a single "Merge" button per match row. When clicked, the contact is merged and removed from the review list, so the user can work through matches step by step. For "Already in CRM" contacts with no conflicts, auto-merge silently on import (no user action needed). The left checkbox (select for bulk ops) and the IMPORT checkbox should be consolidated into one clear action per row.
**Why:** Two checkboxes with unclear purpose is confusing. Users need a clear action ("Merge this contact") with visible progress (list gets shorter as they work through it).

### Per-field conflict resolution in merge (V2)
**Priority:** P1
**Files:** `frontend/src/components/DuplicateComparisonPanel.tsx`, `src/services/smart_import.py`
**What:** Current merge only fills empty CRM fields (enrich-only). V2 adds per-field radio buttons in the comparison panel so users can choose import vs CRM value for conflicting fields.
**Why:** Users need control when import has newer data that should overwrite CRM (e.g., title changed from CFO to CEO).

## P1 — Sequence Builder UX

### LinkedIn automation level
**Priority:** P1
**Files:** `src/services/priority_queue.py`, `frontend/src/pages/Queue.tsx`
**What:** Define what "LinkedIn outreach" means in practice. Three levels: (1) Fully manual — show contact + message template, user copies and sends via browser; (2) Semi-automated — export daily LinkedIn actions as CSV/script for browser extension; (3) API-automated — integrate with LinkedIn Sales Navigator or third-party (Phantombuster, Dripify). Start with level 1 (manual with templated messages), add level 2 as quick follow-up.
**Why:** LinkedIn API is restrictive. Manual with good templates is the realistic V1.

### Campaign sequence kanban view
**Priority:** P1
**Files:** `frontend/src/pages/CampaignDetail.tsx` (new "Pipeline" tab)
**What:** Visual board showing contacts grouped by their current sequence step. Columns = steps (Step 1: Email, Step 2: LinkedIn, Step 3: Follow-up, etc.). Cards = contacts with status badges. Drag-and-drop to manually advance/skip. Shows bottlenecks at a glance.
**Implementation:** Use existing `contact_campaign_status.current_step` + `sequence_steps` to build columns. Use dnd-kit (already in deps) for drag. Each card shows name, company, status badge, days-since-last-action.
**Why:** Users need to see the pipeline at a glance — who is at which step, where are things stuck.

### User flow documentation for sequence builder
**Priority:** P2
**What:** Document the end-to-end flow: Import contacts → Create campaign → Build sequence (choose channels, templates, delays) → Enroll contacts → Daily queue generates actions → User executes actions → Track replies → Adjust. This should be a clear diagram in ARCHITECTURE.md or a dedicated sequence-builder spec.
**Why:** The flow spans 6+ services and isn't documented anywhere.

## Phase 2 — Campaign-First Redesign

### Reply Feedback Loop
- Add `REPLIED_NEUTRAL = 'replied_neutral'` to `ContactStatus` in `src/enums.py`
- Add `replied_neutral` to `VALID_TRANSITIONS` in `state_machine.py` (reachable from `in_progress`)
- Surface template performance in Campaign Analytics tab (reply rate per template)
- Auto-recommend templates with highest positive-reply rates in sequence generator
- **Why:** Messages should improve over time based on reply outcomes. No reply = bad, polite decline = neutral, call request = good.

### Column-Mapping CSV Import
- Build full column-mapping UI for CSV import (auto-detect headers, user corrects via dropdown, preview 5 rows)
- Replace Phase 1 simple import (standard column names only) with flexible mapper
- Standalone import from Contacts page + integrated into Campaign Wizard Step 2
- **Why:** Users have CSVs in all formats. Phase 1 requires exact column names; Phase 2 handles any format.

### Template Auto-Recommendation
- Sequence generator suggests templates based on historical reply rates
- Templates with higher positive-reply rates get recommended first
- Show "winning template" badge in Templates page
- **Why:** Users shouldn't have to guess which template works best.

### A/B Test Setup in Wizard
- Add optional A/B variant selection in Campaign Wizard Step 4 (Messages)
- Auto-assign variants on enrollment (existing round-robin logic)
- Show variant comparison in Campaign Dashboard Analytics tab
- **Why:** A/B testing is a power-user feature that should be accessible but not required during first campaign setup.

### Frontend Test Expansion
- Extend Vitest/RTL coverage beyond Campaign Wizard to other pages
- Add integration tests for cross-campaign queue rendering
- Add tests for Campaign Dashboard tab switching
- **Why:** Phase 1 sets up the infrastructure; Phase 2 expands coverage.

## Design Debt

### DESIGN.md
- Create formal design system document (currently implicit in CLAUDE.md)
- Extract design tokens, component patterns, spacing scale into standalone file
- Run `/design-consultation` to generate comprehensive design system
- **Why:** No DESIGN.md exists. Design decisions are scattered across CLAUDE.md and component code.

### Adopt existing UI components in SmartImport
- Replace 3x inline error banners with `<ErrorCard>` from `components/ui/ErrorCard.tsx`
- Replace ~15 raw `<button>` elements with `<Button>` from `components/ui/Button.tsx`
- Replace inline `<select>` and `<input>` with `<Select>` and `<Input>` components
- **Why:** SmartImport bypasses the design system. Identified by /simplify code reuse review.

## Completed

### Smart Import Duplicate Redesign (all P0 items)
**Completed:** v0.19.x (2026-03-25), branch feat/smart-import
- Remove auto-clear overlap logic — replaced with field-level diffs
- Enrich existing CRM contacts from import data — merge action fills empty fields
- Enroll duplicate contacts in campaign — campaign selector + enrollment during import
- Interactive duplicate review UI — DuplicateComparisonPanel with side-by-side comparison
- Smart Import campaign context (P1) — campaign enrollment selector added
- Within-file duplicate detection (P1) — flags same email/LinkedIn within CSV
- Move header detection to services (P2) — parse_csv_with_header_detection() in services

### LinkedIn automation L1 (Phase 2)
**Completed:** 2026-03-25, branch feat/smart-import
- Copy-to-clipboard button (primary blue variant), expandable/collapsible message section
- Channel icons (Mail, Linkedin from Lucide) on cards and section headers
- Extracted shared useContactEdit hook, ContactEditPanel, SkipMenu components
- Fixed query key mismatch, CopyButton timer leak, handleSaveEdit error handling
- 4 frontend tests (QueueLinkedInCard.test.tsx)

### Cross-campaign email dedup (Phase 1)
**Completed:** 2026-03-25, branch feat/smart-import
- Pivoted from per-campaign dedup (prevented by UNIQUE constraint on contacts) to cross-campaign dedup
- Same contact enrolled in multiple campaigns: only first email kept, others overridden to linkedin_only
- `apply_cross_campaign_email_dedup()` in queue_service.py, called from `/queue/all` route
- Migration 021: `channel_override` column on contact_campaign_status
- COALESCE(channel_override, ss.channel) in get_daily_queue() SQL
- 4 tests in test_priority_queue.py
