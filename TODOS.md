# TODOS

## P0 — Daily Outreach System (B+C Plan)

### Phase 2: LinkedIn automation L1
**Priority:** P0 (next to build)
**Files:** `frontend/src/pages/Queue.tsx`, `frontend/src/components/QueueLinkedInCard.tsx`
**What:** Enhanced LinkedIn card with copy-to-clipboard button, expandable message, channel icons (Lucide Mail/Linkedin). LinkedIn templates already exist at `src/templates/linkedin/`.
**Design decisions:** Copy button: `bg-blue-600 text-white` → "Copied" with check for 2s. `aria-label="Copy message to clipboard"`.
**Tests needed:** 4 frontend tests.

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

### Cross-campaign email dedup (Phase 1)
**Completed:** 2026-03-25, branch feat/smart-import
- Pivoted from per-campaign dedup (prevented by UNIQUE constraint on contacts) to cross-campaign dedup
- Same contact enrolled in multiple campaigns: only first email kept, others overridden to linkedin_only
- `apply_cross_campaign_email_dedup()` in queue_service.py, called from `/queue/all` route
- Migration 021: `channel_override` column on contact_campaign_status
- COALESCE(channel_override, ss.channel) in get_daily_queue() SQL
- 4 tests in test_priority_queue.py
