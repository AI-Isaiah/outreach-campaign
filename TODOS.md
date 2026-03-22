# TODOS

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
