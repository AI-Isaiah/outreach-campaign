# Engineering Review Report: Outreach Campaign Tool

**Date:** March 3, 2026
**Scope:** Architecture (7 ADRs), Debug Analysis, Code Review
**Verdict:** Sound architecture with critical bugs to fix before implementation

---

## Executive Summary

Three parallel engineering analyses were performed: architecture evaluation of all 7 ADRs in FINAL_HANDOFF_Claude_Code.md, a debug analysis of the existing codebase, and a full code quality/security review.

**Overall:** The architecture is fundamentally strong — layered design, human-in-the-loop safeguards, and phased rollout are well-designed. However, the existing codebase has **3 critical bugs**, **7 high-severity issues**, and several medium-priority items that must be resolved before (or during) Phase 0.

---

## Part 1: Architecture Review (7 ADRs)

### ADR Scorecard

| ADR | Title | Verdict | Risk |
|-----|-------|---------|------|
| 001 | Adaptive Outreach Engine | Accept with revisions | Medium |
| 002 | Supabase PostgreSQL | Accept with conditions | Medium |
| 003 | Gmail Draft over SMTP | Accept with minor additions | Low |
| 004 | Gmail Reply Detection + LLM | **Reject + redesign** | **High** |
| 005 | LLM Advisor (Human-in-Loop) | Accept with conditions | Medium |
| 006 | Built-in CRM + Timeline | Accept with optimizations | Low |
| 007 | WhatsApp Browser Automation | Accept cautiously | **High** |

### ADR-004 (Reply Detection) — Critical Redesign Needed

The Gmail API search strategy described won't work. "Query for threads where `to:` matches enrolled contacts" is not how Gmail API works. Correct approach: search with `from:{contact.email}` in INBOX, filter by thread message count > 1, and only classify messages after `contact_campaign_status.enrolled_at`.

Additional gaps: no reply deduplication (same reply shown multiple times), no stale reply expiration, no LLM accuracy tracking, no multi-language support.

**Action:** Prototype Gmail API calls before Phase 4. Validate search strategy with real data.

### ADR-007 (WhatsApp) — High Risk, Fragile

WhatsApp Web actively detects and blocks browser automation. DOM selectors change frequently. Session management is fragile (crashes corrupt state). Phone number matching requires robust normalization.

**Recommendation:** Build with manual fallback UI. If automated scanning breaks (likely after WhatsApp updates), operator can still log messages manually via the CRM.

### ADR-001 (Adaptive Engine) — Missing Definitions

Three gaps need resolution before Phase 3:

1. **Cold-start strategy:** What template does the system pick when no data exists? Default to first template by `created_at ASC` until 2+ variants have been sent.
2. **Exploration scope:** "30% explore if < 50 sends" — define "sends" as total campaign sends (not per-template).
3. **Operator override feedback:** Log overrides as `selection_mode = 'manual_override'` in `contact_template_history`. Feed into scoring.

### Timeline Revision

The document implies ~5–6 weeks. Realistic estimate: **12–18 weeks (3–4.5 months)**.

| Phase | Document Estimate | Realistic |
|-------|------------------|-----------|
| 0: Supabase Migration | Week 1 | 1 week |
| 1: Backend API + CRM | Week 1–2 | 2–3 weeks |
| 2: React Frontend | Week 2–3 | 2 weeks |
| 3: Adaptive Engine | Week 3–4 | 3–4 weeks |
| 4: Gmail + Reply Detection | Week 4–5 | 2–3 weeks |
| 5: WhatsApp Integration | Week 5–6 | 2 weeks |
| 6: Polish | — | 1–2 weeks |
| Integration Testing | — | 1–2 weeks |

---

## Part 2: Bug Analysis (Existing Codebase)

### Critical Bugs (3)

**BUG-1: Boolean Type Mismatch (PostgreSQL vs SQLite)**
Code uses `0/1` integer booleans everywhere, but PostgreSQL expects `true/false`. Schema defines `is_gdpr INTEGER NOT NULL DEFAULT 0` instead of `BOOLEAN`. Queries like `WHERE is_gdpr = 1` and inserts like `1 if gdpr_only else 0` will behave unpredictably.

Files affected: cli.py, campaigns.py, priority_queue.py, compliance.py, deduplication.py, schema.

Fix: Change schema to `BOOLEAN`, update all comparisons and inserts.

**BUG-2: Timestamp Columns Use TEXT Instead of TIMESTAMPTZ**
All `created_at` and `updated_at` columns in `001_initial_schema.sql` are `TEXT NOT NULL DEFAULT NOW()`. PostgreSQL's `NOW()` returns a timestamp, which gets cast to TEXT. Date comparisons in metrics.py work accidentally (ISO strings sort correctly), but this is fragile and prevents timezone-aware queries.

Fix: Change all timestamp columns to `TIMESTAMPTZ`.

**BUG-3: Database Connection Leaks**
Most CLI commands open a connection with `get_connection()` but close it only in the happy path. If any operation throws, `conn.close()` is never called. Over time, this exhausts the Supabase connection pool.

Fix: Wrap all command bodies in `try: ... finally: conn.close()`.

### High-Severity Issues (7)

| # | Issue | File | Impact |
|---|-------|------|--------|
| H1 | Race condition in auto-activation | state_machine.py:112–134 | Same contact enrolled twice |
| H2 | Missing ON DELETE CASCADE | schema.sql | Orphaned records on delete |
| H3 | GDPR email limit off-by-one | compliance.py:102–110 | 3 emails sent instead of 2 |
| H4 | bulk_enroll partial commit | campaigns.py:244–258 | Incomplete enrollments |
| H5 | Unsubscribe matches raw email | compliance.py:156–161 | CAN-SPAM violation |
| H6 | N+1 query in priority queue | priority_queue.py:118–119 | 50+ extra queries per queue |
| H7 | No index on campaign_id | schema.sql | Full table scans |

**H1 Detail:** `_activate_next_contact()` selects the next contact and enrolls them without locking. If two processes run simultaneously, the same contact gets enrolled twice (caught by UNIQUE constraint, returns None silently). Fix: Use `SELECT ... FOR UPDATE`.

**H3 Detail:** `check_gdpr_email_limit()` returns `count < max_emails`. If max=2, it allows sends when count is 0 and 1 (correct: 2 emails). But the check runs BEFORE the send, so the 2nd email passes (count=1 < 2). This is actually correct. However, the state machine can advance a contact to the next email step WITHOUT checking the limit, potentially queuing a 3rd email that only gets caught at send time. Fix: Add limit check in state machine transitions.

### Medium-Severity Issues (8)

| # | Issue | File |
|---|-------|------|
| M1 | Email send failure not tracked | email_sender.py |
| M2 | next_action_date stored as TEXT | schema.sql |
| M3 | Template body_template could be NULL | email_sender.py:254 |
| M4 | IntegrityError swallows all FK violations | campaigns.py:211 |
| M5 | Inefficient variant comparison (N+1) | metrics.py:140–154 |
| M6 | No UNIQUE on template names | schema.sql |
| M7 | dedup_log has no FK constraints | schema.sql |
| M8 | Missing soft delete on templates/notes | schema.sql |

---

## Part 3: Code Quality & Security Review

### Security

All queries use parameterized `%s` placeholders — no SQL injection in existing code. One concern: `web/routes/crm.py` constructs WHERE clauses via f-string interpolation (the conditions themselves are parameterized, but the pattern is fragile). Recommend using a query builder.

Jinja2 runs with `autoescape=False` — safe for plain-text templates but risky if HTML templates are ever routed through the same engine.

Email metadata logs recipient PII (`to_email`) in the events table. Recommend logging only contact_id.

### Code Quality

**DRY violations:** Email/LinkedIn/company normalization functions are duplicated across `import_contacts.py` and `import_emails.py`. Extract to shared `src/services/normalization.py`.

**CLI coupling:** The `enroll` command contains ~50 lines of raw SQL that should be in a service module. Recommend `src/services/enrollment.py`.

**Error handling:** Inconsistent across CLI commands — some catch `Exception`, some catch specific types, some lack try/except entirely.

### Testing

Test infrastructure is solid: ephemeral PostgreSQL via `testing.postgresql`, session-scoped server, table truncation between tests. Missing test coverage for: SMTP failure scenarios, concurrent state transitions, global GDPR limits across campaigns, web API validation.

### Performance

Two N+1 query patterns: `count_steps_for_contact()` called per queue item (priority_queue.py), and queued count per variant (metrics.py). Fuzzy dedup is O(n²) — works for 875 companies but won't scale.

---

## Consolidated Action Items

### Before Phase 0 (Pre-Implementation)

1. Fix schema: `INTEGER` booleans → `BOOLEAN`, `TEXT` timestamps → `TIMESTAMPTZ`
2. Add `ON DELETE CASCADE` to all foreign keys
3. Add missing indexes (`campaign_id` on contact_campaign_status, compound indexes on events)
4. Fix connection leak pattern in all CLI commands (try/finally)
5. Prototype Gmail API reply detection — validate search strategy works
6. Decide WhatsApp scope: full automation vs. manual + fallback

### During Phase 0 (Supabase Migration)

7. Replace all `is_gdpr = 1` → `is_gdpr = true` across codebase
8. Replace all `1 if bool else 0` → direct boolean in campaigns.py
9. Add `SELECT ... FOR UPDATE` in state_machine auto-activation
10. Fix unsubscribe to match on `email_normalized`
11. Eliminate N+1 query in priority_queue (join step count in main query)

### During Phase 1 (Backend API)

12. Extract normalization functions to shared module
13. Move enrollment logic from CLI to service layer
14. Add schema version tracking table
15. Add error response spec for API (consistent format)
16. Add pagination to all list endpoints

### Schema Additions Recommended

```sql
-- Fix booleans
ALTER TABLE contacts ALTER COLUMN is_gdpr TYPE BOOLEAN USING is_gdpr::boolean;
ALTER TABLE contacts ALTER COLUMN unsubscribed TYPE BOOLEAN USING unsubscribed::boolean;
ALTER TABLE companies ALTER COLUMN is_gdpr TYPE BOOLEAN USING is_gdpr::boolean;
ALTER TABLE templates ALTER COLUMN is_active TYPE BOOLEAN USING is_active::boolean;
ALTER TABLE sequence_steps ALTER COLUMN gdpr_only TYPE BOOLEAN USING gdpr_only::boolean;
ALTER TABLE sequence_steps ALTER COLUMN non_gdpr_only TYPE BOOLEAN USING non_gdpr_only::boolean;

-- Fix timestamps
ALTER TABLE companies ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::timestamptz;
ALTER TABLE contacts ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::timestamptz;
-- (repeat for all TEXT timestamp columns)

-- Add missing indexes
CREATE INDEX idx_ccs_campaign ON contact_campaign_status(campaign_id);
CREATE INDEX idx_events_contact_campaign ON events(contact_id, campaign_id);
CREATE INDEX idx_contacts_company_priority ON contacts(company_id, priority_rank);

-- Add soft delete support
ALTER TABLE templates ADD COLUMN deactivated_at TIMESTAMPTZ;
ALTER TABLE response_notes ADD COLUMN deleted_at TIMESTAMPTZ;

-- Add audit trail for LLM corrections
ALTER TABLE pending_replies ADD COLUMN llm_classification_prev TEXT;

-- Add CHECK constraints
ALTER TABLE contact_template_history
ADD CONSTRAINT valid_selection_mode
CHECK (selection_mode IN ('exploit', 'explore', 'manual_override'));

-- Phone number uniqueness
CREATE UNIQUE INDEX idx_contacts_phone_unique
ON contacts(phone_normalized)
WHERE phone_normalized IS NOT NULL;
```

---

## Summary

The system architecture is well-designed for its purpose. The adaptive engine, CRM timeline, and human-in-the-loop patterns are strong choices. The critical path to success is:

1. Fix the boolean/timestamp type mismatches during Supabase migration (unavoidable)
2. Redesign Gmail reply detection before Phase 4 (prototype early)
3. Build WhatsApp with manual fallback (browser automation will break)
4. Set realistic timeline expectations (4 months, not 5 weeks)

The existing test suite and service architecture provide a solid foundation to build on.
