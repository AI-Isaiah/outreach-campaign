# TODOS

## P0 — Friction Sweep (Sprint 1-2)

### ~~CRM contact picker in Campaign Wizard~~
**Priority:** P0 | **Sprint:** 1 | **Status:** Complete
**Files:** `frontend/src/pages/CampaignWizard.tsx`, `src/web/routes/contacts.py`, `src/web/routes/campaigns.py`
**What:** Campaign Wizard Step 2 gets tabbed "From CRM" (default) | "Upload CSV". CRM tab: searchable contact table with checkboxes (name, company, AUM). Extend `/campaigns/launch` to accept `contact_ids` array.
**Why:** After importing contacts via Smart Import, forcing a second CSV upload defeats the purpose of having a CRM. This is the #1 gap in the campaign creation flow.

### ~~Queue keyboard shortcuts~~
**Priority:** P0 | **Sprint:** 1 | **Status:** Complete
**Files:** `frontend/src/pages/Queue.tsx`, `frontend/src/components/QueueEmailCard.tsx`, `frontend/src/components/QueueLinkedInCard.tsx`
**What:** j/k navigate between cards, Enter to approve, s to skip, e to edit. KeyboardHint component (first 3 visits, localStorage). Focus ring on active card. Disable when focused on inputs.
**Why:** Manual click-through of 10-20 queue items is the daily friction. Keyboard cuts review time in half.

### ~~Campaign health score~~
**Priority:** P0 | **Sprint:** 1 | **Status:** Complete
**Files:** `frontend/src/pages/CampaignList.tsx`, `frontend/src/pages/CampaignDetail.tsx`, `src/web/routes/campaigns.py`, `src/services/metrics.py`
**What:** 0-100 score on campaign cards. Formula: (positive_reply_rate×50) + (send_velocity×30) − (bounce_rate×20). Green (70+), amber (40-69), red (<40), N/A (gray). Computed from existing metrics, not stored.
**Why:** Users need an instant pulse on whether a campaign is working — not just raw numbers.

### ~~Smart Message: sequence-level AI generation~~
**Priority:** P0 | **Sprint:** 2 | **Status:** Complete
**Files:** `src/services/message_drafter.py` (extend), `frontend/src/pages/CampaignWizard.tsx`, new route
**What:** Extends Phase 4 infrastructure (message_drafter.py, AI template mode). Adds: (a) best-practices prompt layer for crypto fund outreach, (b) sequence-level generation (all steps at once in wizard), (c) "Improve mode" — paste draft → LLM refines.
**Why:** Most users don't have templates. The first campaign is where they need the most help.

### ~~Auto-reply detection + cron infrastructure~~
**Priority:** P0 | **Sprint:** 2 | **Status:** Complete
**Files:** `src/web/routes/replies.py`, cron middleware, `frontend/src/pages/Dashboard.tsx`, `vercel.json`
**What:** Background Gmail scanning via cron endpoint (every 30 min). CRON_SECRET auth. Iterate users with active Gmail. Batch process max 10 contacts per invocation (Vercel timeout). Track cursor in users table.
**Prerequisites:** Gmail auth unification (reply_detector → DB tokens). Idempotency guard (sent_at in email_sender).
**Why:** Manual "Scan for Replies" button requires opening the app. Cron makes reply detection passive.

---

## P1 — Friction Sweep (Sprint 3-4)

### ~~Batch send with review gate~~
**Priority:** P1 | **Sprint:** 3 | **Status:** Complete
**Files:** `frontend/src/pages/Queue.tsx`, `src/web/routes/queue.py`, `frontend/src/components/ReviewGateModal.tsx`, `frontend/src/hooks/useBatchSendLoop.ts`
**What:** Select All + card checkboxes → review gate modal (stats, safety checks, random samples) → abortable send loop with progress → 30s undo. Server-side 1-per-company + dedup validation. Migration columns (approved_at, scheduled_for, sent_at) already shipped in migration 024.
**Why:** Approving and sending each card individually is the biggest daily friction.

### ~~Post-import campaign creation flow~~
**Priority:** P1 | **Sprint:** 3 | **Status:** Complete
**Files:** `frontend/src/pages/SmartImport.tsx`, `frontend/src/pages/CampaignWizard.tsx`
**What:** After import, show "Create Campaign with N Contacts" CTA. Navigate to wizard with contacts pre-populated (pre-selects in Step 2 CRM tab).
**Why:** Import dumps users on contacts page with no clear next step.

### ~~Fund intelligence signals~~
**Priority:** P1 | **Sprint:** 4 | **Status:** Complete
**What:** Extraction, queue enrichment, SignalBadge, and queue card rendering all implemented. Verified: `_batch_enrich()` fetches fund_signals, queue API returns them, SignalBadge renders on both card types.

### ~~Scheduled send~~
**Priority:** P1 | **Sprint:** 4 | **Status:** Complete
**Files:** `src/web/routes/queue.py`, `src/web/routes/replies.py`, `vercel.json`
**What:** `/queue/schedule` API (presets: now, tomorrow_9am, spread_3_days, custom ISO). `/cron/send-scheduled` cron (every 15 min). Frontend Schedule button with dropdown. Vercel cron configured.
**Why:** Lets users review queue in the evening and schedule sends for morning. Prevents 20 emails at once (spam filter risk).

---

## P1 — Next Up (post-sweep)

### ~~Auto-sequence advancement~~
**Priority:** P1 | **Status:** Complete
**What:** After an email is sent, automatically set `next_action_date` for the next step based on `delay_days` and move `current_step` forward. Clears `approved_at`/`scheduled_for`/`sent_at` so contact re-enters approval queue for the next step. Works in SMTP send path, Gmail draft path, and LinkedIn actions.
**Depends on:** Batch send (Sprint 3), scheduled send (Sprint 4).

### Meeting booking integration
**Priority:** P2
**What:** Calendly/Cal.com integration. Auto-generate booking link in follow-up messages when a contact replies positively. Bridge the gap from "positive reply" to "meeting scheduled."
**Depends on:** Auto-reply detection (Sprint 2).

---

## ~~P1 — Sequence Editor v2~~

### ~~Sequence reordering (drag-and-drop)~~
**Priority:** P1 | **Status:** Complete
**Files:** `frontend/src/pages/CampaignDetail.tsx` (SequenceTab), `src/web/routes/campaigns.py`
**What:** Drag-and-drop reordering via dnd-kit. Uses stable_id (UUID) for step references so reorder doesn't break enrolled contacts. Warns when contacts have already received messages at affected steps. Reorder updates queued contacts to new step 1.

### ~~Inline template editing in sequence tab~~
**Priority:** P1 | **Status:** Complete
**Files:** `frontend/src/pages/CampaignDetail.tsx` (SequenceTab), `src/web/routes/templates.py`
**What:** Click a sequence step to expand and edit channel, delay_days, and template inline. Recalculates delays on reorder.

### ~~Campaign queue shows all queued contacts~~
**Priority:** P1 | **Status:** Complete
**Files:** `frontend/src/pages/CampaignDetail.tsx` (QueueTab), `src/application/queue_service.py`
**What:** Queue tab supports scope filter (today/all/overdue). Shows all queued contacts, not just today's.

### ~~Messages tab: sent message history~~
**Priority:** P2 | **Status:** Complete
**Files:** `frontend/src/pages/CampaignDetail.tsx` (MessagesTab), `src/web/routes/campaigns.py`
**What:** Shows sent message history for this campaign. Each row: contact name, template used, sent date, reply status.

### ~~Column width fixes~~
**Priority:** P2 | **Status:** Complete
**What:** Fixed with Tailwind min-w/max-w/truncate + title tooltips. No custom hook needed. Templates: min-w-[280px] on Subject. Contacts: max-w-[200px] truncate on Company/Email.

### ~~Templates back-link from edit page~~
**Priority:** P2 | **Status:** Complete
**What:** Added ArrowLeft back link to templates overview in the template edit form. Fixed by /qa on 2026-03-29.

## ~~P1 — QA Findings (2026-03-27)~~

### ~~Contact detail: edit core fields~~
**Priority:** P1 | **Status:** Complete
**What:** Unified PATCH /contacts/{id} endpoint with 6 editable fields (name, email, LinkedIn, title, phone). Inline edit form with pencil icon, save/cancel, escape-to-close. Fixed by tech debt sweep on 2026-03-28.

### ~~Messages tab: rename "Calls Booked" metric~~
**Priority:** P2 | **Status:** Complete
**What:** Replaced redundant "Emails Sent" card with "Completed" metric showing contacts that finished all sequence steps. Fixed on 2026-03-29.

### ~~Health score badge: show N/A for new campaigns~~
**Priority:** P2 | **Status:** Complete
**What:** HealthScoreBadge now shows gray "N/A" when score is 0 and totalSent is 0. Red 0 only shows for campaigns with sends but zero performance. Fixed on 2026-03-29.

### ~~Wizard: contact count off-by-one~~
**Priority:** P2 | **Status:** Complete
**What:** Root cause: draft persistence (localStorage) introduced duplicate IDs in crmSelectedIds array. Fixed by deduplicating via `new Set()` in StepReview count display and launch mutation. Fixed on 2026-03-29.

---

## P2 — Backlog (deferred from friction sweep)

### Phase 5: Campaign kanban
**Files:** `frontend/src/pages/CampaignDetail.tsx`, `src/web/routes/campaigns.py`
**What:** "Pipeline" tab in CampaignDetail. Columns = sequence steps, cards = contacts. dnd-kit drag.
**Why deferred:** Visualization, not core workflow friction. Nice-to-have after the daily loop is smooth.

### Smart duplicate resolution V2
**Files:** `frontend/src/components/DuplicateComparisonPanel.tsx`, `src/services/smart_import.py`
**What:** Auto-merge safe CRM matches, flag conflicts, dedicated "Duplicates to Clean" view, file duplicate comparison.
**Why deferred:** Import already excellent. Diminishing returns at 50-200 contacts.

### Multi-contact columns UI fix
**Files:** `frontend/src/pages/SmartImport.tsx`
**What:** Show "Handled by multi-contact detection" instead of "Ignore" for auto-detected multi-contact columns.
**Why deferred:** Cosmetic — data handled correctly by backend.

### Import source tagging
**Files:** `src/services/smart_import.py`, `frontend/src/pages/SmartImport.tsx`
**What:** Auto-tag imported contacts with source CSV name. Filter by tag after import.
**Why deferred:** Nice-to-have at current volume.

### Streamlined merge-and-dismiss workflow
**Files:** `frontend/src/pages/SmartImport.tsx`, `frontend/src/components/DuplicateComparisonPanel.tsx`
**What:** Single "Merge" button per match row instead of dual-checkbox pattern.
**Why deferred:** Import polish, not daily workflow.

### Per-field conflict resolution V2
**Files:** `frontend/src/components/DuplicateComparisonPanel.tsx`, `src/services/smart_import.py`
**What:** Per-field radio buttons to choose import vs CRM value for conflicting fields.
**Why deferred:** Import polish.

### LinkedIn automation L2
**Files:** `src/services/priority_queue.py`, `frontend/src/pages/Queue.tsx`
**What:** Semi-automated LinkedIn: export daily actions as CSV/script for browser extension.
**Why deferred:** Manual L1 works for 50-200 contacts.

### Template auto-recommendation
**What:** Suggest templates based on historical reply rates. Show "winning template" badge.
**Why deferred:** Phase 3 Lite shipped template performance visibility. Auto-recommend is optimization.

### A/B test setup in wizard
**What:** Optional A/B variant selection in Campaign Wizard Step 4. Auto-assign on enrollment.
**Why deferred:** Power-user feature, not core friction.

### Frontend test expansion
**What:** Extend Vitest/RTL coverage to more pages. Integration tests for queue rendering.
**Why deferred:** Test infra exists. Expand as features ship.

---

## ~~Design Debt~~

### ~~DESIGN.md~~
- **Status:** Complete. Created `DESIGN.md` with color tokens, typography, spacing, components, layout, and brand voice.

### ~~Adopt existing UI components in SmartImport~~
- **Status:** Complete. Replaced 3 inline error banners with `<ErrorCard>`, 5 raw buttons with `<Button>`. (-60 lines)

---

## Completed

### Sequence Editor v2 + Auto-Sequence Advancement
**Completed:** 2026-03-27, branch main
- Drag-and-drop sequence reordering with stable_id (UUID) references (dnd-kit)
- Inline step editing (channel, delay_days, template) with delay recalculation on reorder
- Queue tab scope filters (today/all/overdue)
- Messages tab: sent message history
- Reorder updates queued contacts to new step 1
- Auto-sequence advancement: after email send, sets `next_action_date = today + delay_days`, clears `approved_at`/`scheduled_for`/`sent_at` so contact re-enters approval queue
- Gmail draft path also auto-advances with correct `next_action_date`
- 5 backend tests (TestAutoSequenceAdvancement)

### Post-import Campaign Flow + Scheduled Send
**Completed:** 2026-03-27, branch main
- Post-import "Create Campaign with N Contacts" CTA → wizard with pre-selected contacts
- Scheduled send: `/queue/schedule` API + `/cron/send-scheduled` cron (15 min) + frontend Schedule dropdown
- Vercel cron configuration for both scan-replies (30 min) and send-scheduled (15 min)

### Friction Sweep Sprint 1 + Sprint 2
**Completed:** 2026-03-26, branch feat/friction-sweep-sprint1
**Sprint 1:**
- CRM contact picker in Campaign Wizard Step 2 (tabbed "From CRM" | "Upload CSV")
- Queue keyboard shortcuts (j/k/Enter/s/e/Tab + KeyboardHint + focus ring)
- Campaign health score (0-100 badge, green/amber/red/N/A)
- HealthScoreBadge extracted to shared component (/simplify)
- TODOS.md rewrite with friction sweep roadmap
**Sprint 2:**
- Gmail auth unification (GmailDrafter.from_db_tokens for serverless cron)
- Idempotency guard (sent_at atomic lock in send_campaign_email, migration 024)
- Smart Message (generate_sequence_messages + improve_message, wizard "Generate All Messages")
- Auto-reply detection (cron middleware, /cron/scan-replies, Vercel cron config, "Last scanned" badge)

### Phase 3 Lite: Reply remap + template winning badge
**Completed:** 2026-03-26, branch feat/phase3-lite
- Neutral → positive remap in confirm flow (domain rule: non-rejection = positive)
- `contact_template_history` production write path (INSERT on send, UPDATE outcome on confirm)
- Binary reply breakdown (green/red) in CampaignDetail analytics
- Template performance table with "Winning" badge (5+ sends, highest positive_rate)
- 13 backend tests (test_phase3_lite.py)

### Phase 4: Research-powered AI message drafts
**Completed:** 2026-03-26, branch feat/phase3-lite
- On-demand AI draft generation via Claude Haiku (message_drafter.py)
- "Generate AI Draft" button on queue cards (email + LinkedIn)
- AI template mode in campaign wizard Step 4 (template/manual/ai)
- JIT draft generation in push-to-Gmail path with Jinja2 fallback
- Migration 023: message_drafts table + sequence_steps.draft_mode column
- Bundled fixes: wizard Step 4 template selector, gmail_drafts user_id, template_engine user_id
- CEO review hardening: 8 multi-tenancy queries, specific error handling, structured logging, rate limiting
- 18 backend tests + 6 frontend tests (3 QueueEmailCard, 3 CampaignWizard)

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
