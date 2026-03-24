# TODOS

## P0 — Smart Import Duplicate Redesign (feat/smart-import branch)

### Remove auto-clear overlap logic — show side-by-side instead
**Priority:** P0
**Files:** `src/services/smart_import.py` (preview_import), `frontend/src/pages/SmartImport.tsx` (PreviewTableRow)
**What:** The current `preview_import()` auto-clears email or LinkedIn when only one field matches an existing CRM contact. This is wrong — it silently strips data, leaving contacts without email or LinkedIn. Instead: show the import row and the existing CRM contact side by side. Highlight which fields conflict (email match, LinkedIn match, or both). Let the user decide per-field what to keep, merge, or skip.
**Current behavior:** `overlap_cleared = "email"` → email nulled silently. User sees "Email cleared" badge.
**Desired behavior:** Show expandable comparison panel for ANY match (not just exact duplicates). Fields that conflict get highlighted. User picks per-field: keep import value, keep CRM value, or merge.
**Why:** User reported contacts with no email or LinkedIn after import. The auto-clear was too aggressive and removed valid data.

### Enrich existing CRM contacts from import data
**Priority:** P0
**Files:** `src/services/smart_import.py` (execute_import), `src/web/routes/smart_import.py`
**What:** When an imported contact matches an existing CRM contact, check if the import has fields the CRM lacks (e.g., title, LinkedIn URL, phone). Offer to merge those fields into the existing contact via UPDATE. Currently `execute_import()` uses `ON CONFLICT DO NOTHING` — it skips the row entirely, losing any new information.
**Implementation:** In preview, show which fields would be enriched (green highlight = new data for CRM). In execute, run UPDATE SET for non-null import fields where CRM field is null.
**Why:** Users re-import updated lists. The CRM should get smarter with each import, not ignore new data.

### Enroll duplicate contacts in campaign (not just new ones)
**Priority:** P0
**Files:** `src/services/smart_import.py` (execute_import), `src/models/campaigns.py` (enroll_contact)
**What:** Currently, contacts that match existing CRM entries are silently skipped by `ON CONFLICT DO NOTHING`. But the user imported them FOR a specific campaign. The existing CRM contact should be enrolled in the target campaign even though it's not re-created. `contact_campaign_status` already supports this — `enroll_contact()` exists and handles the `UNIQUE(contact_id, campaign_id)` constraint.
**Implementation:** After import, collect IDs of both newly-created AND already-existing matched contacts. Pass all to `bulk_enroll_contacts()`. Smart Import needs a campaign_id parameter (currently it imports contacts without campaign context — this may need a UX change to select a campaign during import, or do enrollment as a separate step).
**Why:** Campaign-centric workflow means every imported contact should be in the campaign, whether new or existing.

### Interactive duplicate review UI
**Priority:** P0
**Files:** `frontend/src/pages/SmartImport.tsx`, `frontend/src/api/smartImport.ts`
**What:** Redesign the preview step's duplicate handling:
1. For ANY match (email OR LinkedIn OR both), show expandable comparison: import row vs CRM contact
2. Per-field diff: green = new data CRM doesn't have, yellow = conflict (different values), gray = same
3. Action buttons per row: "Merge & Enroll" (update CRM + enroll), "Skip" (don't touch), "Import as New" (force create)
4. For exact duplicates: "Enroll in Campaign" button (don't re-create, just enroll)
5. Bulk actions: "Merge All", "Skip All Duplicates", "Enroll All in Campaign"
**Why:** Users need to see what they're getting before committing. The current "Already in CRM" badge + auto-clear gives no control.

## P1 — Smart Import UX Polish

### Smart Import should accept campaign context
**Priority:** P1
**Files:** `frontend/src/pages/SmartImport.tsx`, `src/web/routes/smart_import.py`
**What:** Add optional campaign selection to Smart Import flow (before or after mapping). When a campaign is selected, the execute step enrolls all imported/matched contacts in that campaign. Currently Smart Import creates contacts but doesn't enroll them anywhere.
**Depends on:** P0 duplicate enrollment work above.

### Preview table: within-file duplicates
**Priority:** P1
**Files:** `src/services/smart_import.py` (preview_import)
**What:** Currently only checks against CRM database. Should also detect duplicates WITHIN the uploaded CSV (e.g., same person listed twice with slightly different data). Group within-file duplicates adjacent in the preview table.
**Why:** Many CSVs from conferences or list providers have internal duplicates.

### Move header detection to services layer
**Priority:** P2
**Files:** `src/web/routes/smart_import.py` → `src/services/smart_import.py`
**What:** `_detect_header_row()`, `_parse_csv_with_header_detection()`, and `_HEADER_KEYWORDS` are pure CSV-parsing logic but live in the route file. Move to services per the project's layer contract (routes → services → models).

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
