# Spec 05: CRM (Phase 5)

**Priority:** P1 — Largest feature gap, biggest user-facing impact
**Estimated time:** 8–12 hours (split across 2–3 Claude Code sessions)
**Prerequisite:** Specs 01–03 completed (stable backend required)

---

## Problem Statement

The platform manages 875+ companies and thousands of contacts for crypto fund allocator outreach. Currently, there's a basic contact detail page, company detail page, and a timeline view — but no way to manage the pipeline as a whole. There's no kanban board to visualize deal stages, no way to log meetings/calls inline, no company engagement scoring, no bulk operations, and no saved filter views. Fund allocator outreach requires seeing the "big picture" of which firms are responding and which need follow-up — the CRM layer makes that possible.

---

## What Already Exists (Don't Rebuild)

Before building, review what's already done:

**Backend routes (functional):**
- `src/web/routes/crm.py` — CRM contacts list with AUM/status/firm_type filtering, contact timeline, company list, company detail, global search
- `src/web/routes/contacts.py` — Contact detail, status transitions, notes, phone update, events
- `src/web/routes/replies.py` — Pending replies with LLM classification

**Frontend pages (functional):**
- `frontend/src/pages/ContactDetail.tsx` — Contact info, company link, enrollments table, status logging, notes, phone input, unified timeline
- `frontend/src/pages/CompanyDetail.tsx` — AUM/contacts/activities cards, company details, contacts table with status
- `frontend/src/pages/ContactList.tsx` — Paginated contact list with search
- `frontend/src/components/UnifiedTimeline.tsx` — Timeline component (already reusable)

**Database tables (exist):**
- `contacts`, `companies`, `contact_campaign_status`, `events`, `response_notes`, `interaction_timeline_view`

The task is to EXTEND what exists, not rebuild it.

---

## Task 1: Pipeline / Kanban Board

**Goal:** Visualize all active contacts across deal stages as a drag-and-drop kanban board.

**Backend:** Create `src/web/routes/pipeline.py`

```python
router = APIRouter(prefix="/pipeline", tags=["pipeline"])

@router.get("/board")
def get_pipeline_board(
    campaign: str = "Q1_2026_initial",
    conn=Depends(get_db),
):
    """Get contacts grouped by status for kanban view."""
    # Columns: queued | in_progress | replied_positive | replied_negative | completed
    camp = get_campaign_by_name(conn, campaign)
    if not camp:
        raise HTTPException(404, f"Campaign '{campaign}' not found")

    cur = conn.cursor()
    cur.execute("""
        SELECT ccs.status, ccs.current_step, ccs.next_action_date,
               c.id AS contact_id, c.full_name, c.email, c.title,
               co.name AS company_name, co.aum_millions, co.firm_type,
               (SELECT MAX(e.created_at) FROM events e WHERE e.contact_id = c.id) AS last_activity
        FROM contact_campaign_status ccs
        JOIN contacts c ON c.id = ccs.contact_id
        LEFT JOIN companies co ON co.id = c.company_id
        WHERE ccs.campaign_id = %s
        ORDER BY co.aum_millions DESC NULLS LAST
    """, (camp["id"],))
    rows = cur.fetchall()

    # Group by status
    columns = {}
    for row in rows:
        status = row["status"]
        if status not in columns:
            columns[status] = []
        columns[status].append(dict(row))

    return {
        "campaign": campaign,
        "columns": columns,
        "column_order": ["queued", "in_progress", "replied_positive", "replied_negative", "completed", "unsubscribed", "bounced"],
    }

@router.post("/move")
def move_contact_in_pipeline(
    body: PipelineMoveRequest,  # contact_id, campaign, new_status, note
    conn=Depends(get_db),
):
    """Move a contact between pipeline stages (status transition)."""
    # Reuse existing transition_contact from state_machine
    ...
```

Register in `app.py`:
```python
from src.web.routes import pipeline
app.include_router(pipeline.router, prefix="/api")
```

**Frontend:** Create `frontend/src/pages/Pipeline.tsx`

Build a kanban board with columns for each status. Each card shows: contact name, company, AUM, last activity date. Cards in `queued` and `in_progress` columns are most important.

Use react-beautiful-dnd or a simpler approach with CSS grid columns. Cards should be clickable (link to contact detail page).

Column layout:
```
| Queued (12) | In Progress (8) | Replied+ (3) | Replied- (5) | Completed (20) |
|-------------|-----------------|--------------|--------------|----------------|
| [Card]      | [Card]          | [Card]       | [Card]       | [Card]         |
| [Card]      | [Card]          |              | [Card]       | [Card]         |
```

Each card:
```
┌─────────────────────┐
│ John Smith          │
│ Crypto Capital      │
│ $2,500M AUM         │
│ Step 2/4 · 3 days   │
└─────────────────────┘
```

Add to `App.tsx` routes:
```tsx
<Route path="/pipeline" element={<Pipeline />} />
```

Add to Layout navigation.

**Acceptance criteria:**
- [ ] Pipeline page shows contacts grouped by campaign status
- [ ] Each column shows count and is sorted by AUM (highest first)
- [ ] Cards show: name, company, AUM, current step, days since last activity
- [ ] Clicking a card navigates to contact detail
- [ ] Campaign selector dropdown at the top
- [ ] Column totals visible (e.g., "Queued (12)")

---

## Task 2: Inline Note Adding

**Goal:** Allow adding notes from the CRM contact list without navigating to the detail page.

**Backend:** Already exists — `POST /api/contacts/{id}/notes` in contacts.py

**Frontend:** Modify `frontend/src/pages/ContactList.tsx`

Add an expandable row or modal when clicking a contact row. The expanded area shows:
1. Quick note textarea + save button
2. Last 3 notes (preview)
3. Status badge
4. One-click status transition buttons (Positive Reply, Negative Reply, No Response)

This avoids having to open the full detail page just to log a response.

**Acceptance criteria:**
- [ ] Clicking a contact row expands an inline panel
- [ ] Panel has note textarea + save button
- [ ] Panel shows last 3 notes as previews
- [ ] Quick-action buttons for status transitions
- [ ] Saving a note refreshes the row without full page reload

---

## Task 3: Company Engagement Scoring

**Goal:** Score companies based on outreach engagement to prioritize follow-up.

**Backend:** Create `src/services/engagement_scorer.py`

```python
def score_company_engagement(conn, company_id: int, campaign_id: int = None) -> dict:
    """Calculate engagement score for a company based on all contact interactions."""
    cur = conn.cursor()

    # Get all events for contacts at this company
    cur.execute("""
        SELECT e.event_type, e.created_at, c.id as contact_id
        FROM events e
        JOIN contacts c ON c.id = e.contact_id
        WHERE c.company_id = %s
        ORDER BY e.created_at DESC
    """, (company_id,))
    events = cur.fetchall()

    # Scoring weights
    WEIGHTS = {
        "email_sent": 1,
        "email_opened": 3,      # If tracked
        "email_replied": 10,
        "linkedin_sent": 2,
        "linkedin_replied": 10,
        "call_booked": 25,
        "whatsapp_received": 8,
        "replied_positive": 20,
    }

    score = 0
    for event in events:
        score += WEIGHTS.get(event["event_type"], 0)

    # Recency boost: events in last 7 days get 2x
    from datetime import datetime, timedelta
    recent_cutoff = datetime.now() - timedelta(days=7)
    # ... apply recency multiplier

    return {
        "company_id": company_id,
        "engagement_score": score,
        "total_events": len(events),
        "last_activity": events[0]["created_at"] if events else None,
    }
```

Add endpoint in `crm.py`:
```python
@router.get("/companies/{company_id}/engagement")
def get_company_engagement(company_id: int, conn=Depends(get_db)):
    return score_company_engagement(conn, company_id)
```

Also add a bulk endpoint for the company list:
```python
@router.get("/companies/engagement-scores")
def get_all_engagement_scores(campaign: str = None, conn=Depends(get_db)):
    """Get engagement scores for all companies, sorted by score."""
    # Single query with aggregation instead of N+1
    ...
```

**Frontend:** Add engagement score column to CompanyDetail and company list views. Show as a colored bar or number (0–100 scale).

**Acceptance criteria:**
- [ ] Each company has a calculated engagement score
- [ ] Score reflects email replies, calls booked, and recency
- [ ] Company list can be sorted by engagement score
- [ ] CompanyDetail page shows engagement score prominently
- [ ] Score calculation uses a single aggregation query (not N+1)

---

## Task 4: Bulk Operations

**Goal:** Enroll, transition, or export multiple contacts at once from the CRM list view.

**Backend:** Add endpoints to `crm.py`:

```python
class BulkStatusRequest(BaseModel):
    contact_ids: list[int]
    campaign: str
    new_status: str
    note: Optional[str] = None

@router.post("/contacts/bulk-status")
def bulk_update_status(body: BulkStatusRequest, conn=Depends(get_db)):
    """Transition multiple contacts to a new status."""
    results = {"success": [], "failed": []}
    for contact_id in body.contact_ids:
        try:
            transition_contact(conn, contact_id, campaign_id, body.new_status)
            results["success"].append(contact_id)
        except (InvalidTransition, Exception) as e:
            results["failed"].append({"contact_id": contact_id, "error": str(e)})
    conn.commit()
    return results

class BulkExportRequest(BaseModel):
    contact_ids: list[int] = []
    filters: Optional[dict] = None  # Use same filters as list endpoint

@router.post("/contacts/export-csv")
def export_contacts_csv(body: BulkExportRequest, conn=Depends(get_db)):
    """Export selected contacts as CSV."""
    # Build query based on contact_ids or filters
    # Return StreamingResponse with CSV content
    ...
```

**Frontend:** Add to ContactList:
1. Checkbox column for multi-select
2. "Select All" checkbox in header
3. Action bar that appears when contacts are selected:
   - "Change Status" dropdown
   - "Export CSV" button
   - "Add to Campaign" button
4. Show selected count: "3 contacts selected"

**Acceptance criteria:**
- [ ] Checkboxes on contact list rows
- [ ] Select All toggles all visible contacts
- [ ] Bulk status transition works for selected contacts
- [ ] Failed transitions show error per-contact (don't stop on first error)
- [ ] CSV export downloads a file with selected contacts
- [ ] Action bar only appears when contacts are selected

---

## Task 5: Activity Feed / Dashboard Widget

**Goal:** Show recent activity across all campaigns in a feed format on the Dashboard page.

**Backend:** Add to `src/web/routes/stats.py` or create `src/web/routes/activity.py`:

```python
@router.get("/activity/recent")
def get_recent_activity(
    limit: int = 20,
    conn=Depends(get_db),
):
    """Get the most recent activities across all campaigns."""
    cur = conn.cursor()
    cur.execute("""
        SELECT e.*, c.full_name, c.email, co.name AS company_name,
               t.name AS template_name
        FROM events e
        JOIN contacts c ON c.id = e.contact_id
        LEFT JOIN companies co ON co.id = c.company_id
        LEFT JOIN templates t ON t.id = e.template_id
        ORDER BY e.created_at DESC
        LIMIT %s
    """, (limit,))
    return [dict(r) for r in cur.fetchall()]
```

**Frontend:** Add an activity feed widget to `Dashboard.tsx`:
- Shows last 20 activities as a timeline
- Each entry: "Email sent to John Smith at Crypto Capital — 2 hours ago"
- Clickable contact names link to detail page
- Color-coded by event type (green for replies, blue for sent, red for bounces)

**Acceptance criteria:**
- [ ] Dashboard shows recent activity feed
- [ ] Feed updates on page load (no manual refresh needed)
- [ ] Each activity shows: event type, contact name, company, time ago
- [ ] Contact names are clickable links
- [ ] Event types are color-coded

---

## Task 6: Saved Filter Views

**Goal:** Let the user save commonly-used filter combinations for quick access.

**Backend:** Add migration + endpoints:

Migration (`migrations/pg/005_crm_views.sql`):
```sql
CREATE TABLE IF NOT EXISTS saved_views (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    view_type TEXT NOT NULL DEFAULT 'contacts',  -- contacts | companies | pipeline
    filters JSONB NOT NULL DEFAULT '{}',
    sort_by TEXT,
    sort_order TEXT DEFAULT 'desc',
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Endpoints in `crm.py`:
```python
@router.get("/views")
def list_saved_views(conn=Depends(get_db)):
    ...

@router.post("/views")
def create_saved_view(body: SavedViewRequest, conn=Depends(get_db)):
    ...

@router.delete("/views/{view_id}")
def delete_saved_view(view_id: int, conn=Depends(get_db)):
    ...
```

**Frontend:** Add a "Save View" button to the CRM contact list page. When filters are active, show "Save this view" option. Saved views appear as tabs above the contact list.

Example saved views:
- "High AUM Positive Replies" → status=replied_positive, min_aum=1000
- "GDPR Contacts Queued" → status=queued, firm_type includes EU countries
- "Unresponsive > 14 days" → status=in_progress, last_activity > 14 days ago

**Acceptance criteria:**
- [ ] Users can save current filters as a named view
- [ ] Saved views appear as clickable tabs/buttons above the list
- [ ] Clicking a saved view applies those filters instantly
- [ ] Views can be deleted
- [ ] Views persist across page reloads (stored in DB)

---

## Task 7: CRM Tests

**File:** Add tests to `tests/test_web_api.py` or create `tests/test_crm.py`

Test coverage needed:
- [ ] Pipeline board returns contacts grouped by status
- [ ] Pipeline board sorts by AUM within each column
- [ ] Engagement score calculation with mixed event types
- [ ] Bulk status transition (success and partial failure)
- [ ] CSV export returns valid CSV with correct columns
- [ ] Saved view CRUD (create, list, delete)
- [ ] Activity feed returns recent events in order
- [ ] Company engagement scores use single query (no N+1)

---

## Verification Checklist

After completing all tasks, verify in the browser:

```bash
# Start backend
python3 -m uvicorn src.web.app:app --reload

# Start frontend
cd frontend && npm run dev
```

- [ ] Pipeline page shows kanban columns with cards
- [ ] Cards show name, company, AUM, step info
- [ ] Contact list has inline note expansion
- [ ] Company list shows engagement scores
- [ ] Bulk select + status change works on contact list
- [ ] CSV export downloads a file
- [ ] Dashboard shows activity feed
- [ ] Saved views persist and apply correctly
- [ ] All new tests pass: `make test`
