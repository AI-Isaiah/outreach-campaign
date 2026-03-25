# Smart Import Duplicate Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the auto-clear overlap logic in Smart Import with an interactive side-by-side comparison UI that lets users merge, skip, or enroll duplicate contacts — and enrich existing CRM records from import data.

**Architecture:** Backend `preview_import()` stops stripping fields; instead returns match metadata with per-field diff. New `execute_import()` accepts per-row user decisions (merge/skip/import-as-new/enroll) and performs UPDATE for merges. Frontend replaces "Email cleared" badges with expandable comparison panels and bulk action buttons. Optional campaign selector enables enrollment of both new and matched contacts.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript/Tailwind (frontend), PostgreSQL, TanStack React Query

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/services/smart_import.py` | Remove auto-clear in `preview_import()`, add field-diff logic, add merge/enrich logic to `execute_import()` |
| Modify | `src/web/routes/smart_import.py` | Accept `row_decisions` in execute request, move header detection to services, add campaign_id to execute |
| Modify | `frontend/src/api/smartImport.ts` | Update types for new preview/execute shapes |
| Modify | `frontend/src/pages/SmartImport.tsx` | Comparison panels, per-row actions, bulk actions, campaign selector |
| Create | `tests/test_smart_import.py` | Tests for preview_import, execute_import, merge logic |

---

## Task 1: Backend — Remove auto-clear, return field-level diffs in preview

**Files:**
- Modify: `src/services/smart_import.py:536-654` (preview_import function)

### What changes

The current `preview_import()` nulls out email/LinkedIn fields when partial matches exist (lines 619-639). We replace this with match metadata that preserves all import data and adds per-field comparison info.

For every matched row, we add:
- `existing_contact`: full CRM data for the matched contact (already exists for exact dupes, extend to partial matches)
- `match_type`: `"exact"` | `"email_only"` | `"linkedin_only"` | `"both_different_contacts"`
- `field_diffs`: per-field comparison: `"new"` (CRM field is null, import has value), `"conflict"` (both have different values), `"same"` (values match), `"empty"` (neither has value)
- `existing_contact_id`: the CRM contact ID for merge operations
- Remove `overlap_cleared` field entirely — no more auto-clearing

- [ ] **Step 1: Write failing test for new preview shape**

Create `tests/test_smart_import.py`:

```python
"""Tests for smart import preview and execute logic."""
import pytest
from unittest.mock import MagicMock, patch
from src.services.smart_import import preview_import, transform_rows


def _make_transformed_row(
    company="Acme Corp",
    email="alice@acme.com",
    linkedin="https://linkedin.com/in/alice",
    first_name="Alice",
    last_name="Smith",
    title="CEO",
    **overrides,
):
    """Helper to build a transformed row dict."""
    from src.services.normalization_utils import normalize_email, normalize_linkedin_url, normalize_company_name
    row = {
        "company_name": company,
        "company_name_normalized": normalize_company_name(company),
        "country": None,
        "aum_millions": None,
        "firm_type": None,
        "is_gdpr": False,
        "first_name": first_name,
        "last_name": last_name,
        "full_name": f"{first_name} {last_name}",
        "email": email,
        "email_normalized": normalize_email(email) if email else None,
        "linkedin_url": linkedin,
        "linkedin_url_normalized": normalize_linkedin_url(linkedin) if linkedin else None,
        "title": title,
        "priority_rank": 1,
        "email_status": "unknown",
        "website": None,
        "address": None,
    }
    row.update(overrides)
    return row


class TestPreviewImportFieldDiffs:
    """preview_import should return field-level diffs instead of auto-clearing."""

    def test_new_contact_has_no_diffs(self, tmp_db):
        """Brand new contact: no match, no diffs."""
        row = _make_transformed_row()
        result = preview_import(tmp_db, [row], user_id=1)
        r = result["preview_rows"][0]
        assert r["match_type"] is None
        assert r["field_diffs"] is None
        assert r["existing_contact"] is None
        assert r["existing_contact_id"] is None
        # Import data preserved — no auto-clearing
        assert r["email"] == "alice@acme.com"
        assert r["linkedin_url"] == "https://linkedin.com/in/alice"

    def test_exact_match_returns_diffs(self, tmp_db):
        """Exact duplicate: both email and LinkedIn match same CRM contact."""
        from src.models.database import get_cursor
        # Insert existing contact
        with get_cursor(tmp_db) as cur:
            cur.execute(
                """INSERT INTO companies (name, name_normalized, user_id)
                   VALUES ('Acme Corp', 'acme corp', 1) RETURNING id"""
            )
            co_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO contacts
                   (company_id, first_name, last_name, email, email_normalized,
                    linkedin_url, linkedin_url_normalized, title, user_id)
                   VALUES (%s, 'Alice', 'Smith', 'alice@acme.com', 'alice@acme.com',
                           'https://linkedin.com/in/alice', 'linkedin.com/in/alice',
                           'CFO', 1) RETURNING id""",
                (co_id,),
            )
            contact_id = cur.fetchone()["id"]
        tmp_db.commit()

        row = _make_transformed_row(title="CEO")  # different title
        result = preview_import(tmp_db, [row], user_id=1)
        r = result["preview_rows"][0]
        assert r["match_type"] == "exact"
        assert r["existing_contact_id"] == contact_id
        assert r["existing_contact"]["title"] == "CFO"
        assert r["field_diffs"]["title"] == "conflict"  # import=CEO, CRM=CFO
        assert r["field_diffs"]["email"] == "same"
        # Import data NOT cleared
        assert r["email"] == "alice@acme.com"
        assert r["linkedin_url"] == "https://linkedin.com/in/alice"

    def test_email_only_match_shows_enrichable_fields(self, tmp_db):
        """Email-only match: LinkedIn is new data for CRM."""
        from src.models.database import get_cursor
        with get_cursor(tmp_db) as cur:
            cur.execute(
                """INSERT INTO companies (name, name_normalized, user_id)
                   VALUES ('Acme Corp', 'acme corp', 1) RETURNING id"""
            )
            co_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO contacts
                   (company_id, first_name, last_name, email, email_normalized,
                    title, user_id)
                   VALUES (%s, 'Alice', 'Smith', 'alice@acme.com', 'alice@acme.com',
                           NULL, 1) RETURNING id""",
                (co_id,),
            )
            contact_id = cur.fetchone()["id"]
        tmp_db.commit()

        row = _make_transformed_row(title="CEO")
        result = preview_import(tmp_db, [row], user_id=1)
        r = result["preview_rows"][0]
        assert r["match_type"] == "email_only"
        assert r["existing_contact_id"] == contact_id
        assert r["field_diffs"]["linkedin_url"] == "new"  # CRM has none, import has it
        assert r["field_diffs"]["title"] == "new"  # CRM null, import has "CEO"
        # Data preserved
        assert r["email"] == "alice@acme.com"
        assert r["linkedin_url"] == "https://linkedin.com/in/alice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" python3 -m pytest tests/test_smart_import.py -v`
Expected: FAIL — tests fail because preview_import still auto-clears and doesn't return `match_type`/`field_diffs`

- [ ] **Step 3: Implement new preview_import**

In `src/services/smart_import.py`, replace the duplicate-handling block (lines 598-644) inside `preview_import()`. The full function signature stays the same. Replace the match logic with:

```python
# --- Build field-level diff for a match ---
def _build_field_diffs(import_row: dict, existing: dict) -> dict:
    """Compare import row vs CRM contact, field by field.

    Returns dict of field_name -> "new" | "conflict" | "same" | "empty".
    """
    COMPARE_FIELDS = [
        ("first_name", "first_name"),
        ("last_name", "last_name"),
        ("email", "email"),
        ("title", "title"),
        ("linkedin_url", "linkedin_url"),
    ]
    diffs = {}
    for import_key, crm_key in COMPARE_FIELDS:
        import_val = (import_row.get(import_key) or "").strip()
        crm_val = (existing.get(crm_key) or "").strip()
        if not import_val and not crm_val:
            diffs[import_key] = "empty"
        elif import_val and not crm_val:
            diffs[import_key] = "new"
        elif not import_val and crm_val:
            diffs[import_key] = "empty"  # import has nothing to offer
        elif import_val.lower() == crm_val.lower():
            diffs[import_key] = "same"
        else:
            diffs[import_key] = "conflict"
    return diffs
```

Then in the main loop, replace the match handling (lines 599-644) with:

```python
        if email_match and linkedin_match:
            if email_match["id"] == linkedin_match["id"]:
                # Both fields match same CRM contact — exact duplicate
                row_copy["match_type"] = "exact"
                row_copy["existing_contact_id"] = email_match["id"]
                row_copy["existing_contact"] = {
                    "first_name": email_match["first_name"],
                    "last_name": email_match["last_name"],
                    "email": email_match["email"],
                    "title": email_match["title"],
                    "linkedin_url": email_match["linkedin_url"],
                    "company_name": email_match["company_name"],
                }
                row_copy["field_diffs"] = _build_field_diffs(r, email_match)
                row_copy["is_duplicate"] = True
                exact_duplicates += 1
            else:
                # Email matches contact A, LinkedIn matches contact B
                row_copy["match_type"] = "both_different_contacts"
                row_copy["existing_contact_id"] = email_match["id"]
                row_copy["existing_contact"] = {
                    "first_name": email_match["first_name"],
                    "last_name": email_match["last_name"],
                    "email": email_match["email"],
                    "title": email_match["title"],
                    "linkedin_url": email_match["linkedin_url"],
                    "company_name": email_match["company_name"],
                }
                row_copy["field_diffs"] = _build_field_diffs(r, email_match)
                row_copy["is_duplicate"] = False
        elif email_match:
            row_copy["match_type"] = "email_only"
            row_copy["existing_contact_id"] = email_match["id"]
            row_copy["existing_contact"] = {
                "first_name": email_match["first_name"],
                "last_name": email_match["last_name"],
                "email": email_match["email"],
                "title": email_match["title"],
                "linkedin_url": email_match["linkedin_url"],
                "company_name": email_match["company_name"],
            }
            row_copy["field_diffs"] = _build_field_diffs(r, email_match)
            row_copy["is_duplicate"] = False
        elif linkedin_match:
            row_copy["match_type"] = "linkedin_only"
            row_copy["existing_contact_id"] = linkedin_match["id"]
            row_copy["existing_contact"] = {
                "first_name": linkedin_match["first_name"],
                "last_name": linkedin_match["last_name"],
                "email": linkedin_match["email"],
                "title": linkedin_match["title"],
                "linkedin_url": linkedin_match["linkedin_url"],
                "company_name": linkedin_match["company_name"],
            }
            row_copy["field_diffs"] = _build_field_diffs(r, linkedin_match)
            row_copy["is_duplicate"] = False
        else:
            row_copy["match_type"] = None
            row_copy["existing_contact_id"] = None
            row_copy["existing_contact"] = None
            row_copy["field_diffs"] = None
            row_copy["is_duplicate"] = False

        # Remove legacy field — no more auto-clearing
        row_copy["duplicate_type"] = row_copy.get("match_type")
        row_copy["overlap_cleared"] = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" python3 -m pytest tests/test_smart_import.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_smart_import.py src/services/smart_import.py
git commit -m "feat: preview_import returns field-level diffs instead of auto-clearing"
```

---

## Task 2: Backend — Merge/enrich and per-row decisions in execute_import

**Files:**
- Modify: `src/services/smart_import.py:662-788` (execute_import function)
- Modify: `src/web/routes/smart_import.py:342-415` (execute endpoint)

### What changes

`execute_import()` currently uses `ON CONFLICT DO NOTHING` for contacts. We need it to:
1. Accept per-row decisions from the frontend: `"import"` (new), `"merge"` (update CRM + create if needed), `"skip"`, `"enroll"` (enroll existing, don't re-create)
2. For `"merge"`: UPDATE existing CRM contact with non-null import fields where CRM field is null (enrich) or where user chose import value (conflict resolution)
3. Collect all contact IDs (new + existing matched) for optional campaign enrollment
4. Accept optional `campaign_id` for bulk enrollment

- [ ] **Step 1: Write failing tests for execute with row decisions**

Append to `tests/test_smart_import.py`:

```python
class TestExecuteImportWithDecisions:
    """execute_import should handle per-row merge/skip/enroll decisions."""

    def test_merge_enriches_existing_contact(self, tmp_db):
        """Merge decision: UPDATE CRM contact with new fields from import."""
        from src.models.database import get_cursor
        from src.services.smart_import import execute_import
        # Create existing contact without title or LinkedIn
        with get_cursor(tmp_db) as cur:
            cur.execute(
                """INSERT INTO companies (name, name_normalized, user_id)
                   VALUES ('Acme Corp', 'acme corp', 1) RETURNING id"""
            )
            co_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO contacts
                   (company_id, first_name, last_name, email, email_normalized,
                    user_id)
                   VALUES (%s, 'Alice', 'Smith', 'alice@acme.com', 'alice@acme.com',
                           1) RETURNING id""",
                (co_id,),
            )
            contact_id = cur.fetchone()["id"]
        tmp_db.commit()

        row = _make_transformed_row(title="CEO")
        decisions = {0: {"action": "merge", "existing_contact_id": contact_id}}
        result = execute_import(tmp_db, [row], user_id=1, row_decisions=decisions)
        assert result["contacts_merged"] == 1

        # Verify CRM contact was enriched
        with get_cursor(tmp_db) as cur:
            cur.execute("SELECT title, linkedin_url FROM contacts WHERE id = %s", (contact_id,))
            updated = cur.fetchone()
        assert updated["title"] == "CEO"
        assert updated["linkedin_url"] == "https://linkedin.com/in/alice"

    def test_skip_decision_does_not_create(self, tmp_db):
        """Skip decision: row is not imported."""
        from src.services.smart_import import execute_import
        row = _make_transformed_row()
        decisions = {0: {"action": "skip"}}
        result = execute_import(tmp_db, [row], user_id=1, row_decisions=decisions)
        assert result["contacts_created"] == 0
        assert result["contacts_skipped"] == 1

    def test_enroll_decision_enrolls_existing(self, tmp_db):
        """Enroll decision: existing contact gets enrolled in campaign."""
        from src.models.database import get_cursor
        from src.services.smart_import import execute_import
        with get_cursor(tmp_db) as cur:
            cur.execute(
                """INSERT INTO companies (name, name_normalized, user_id)
                   VALUES ('Acme Corp', 'acme corp', 1) RETURNING id"""
            )
            co_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO contacts
                   (company_id, first_name, last_name, email, email_normalized, user_id)
                   VALUES (%s, 'Alice', 'Smith', 'alice@acme.com', 'alice@acme.com', 1)
                   RETURNING id""",
                (co_id,),
            )
            contact_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO campaigns (name, user_id) VALUES ('Q1', 1) RETURNING id"
            )
            campaign_id = cur.fetchone()["id"]
        tmp_db.commit()

        row = _make_transformed_row()
        decisions = {0: {"action": "enroll", "existing_contact_id": contact_id}}
        result = execute_import(
            tmp_db, [row], user_id=1,
            row_decisions=decisions, campaign_id=campaign_id,
        )
        assert result["contacts_enrolled"] >= 1

        # Verify enrollment
        with get_cursor(tmp_db) as cur:
            cur.execute(
                "SELECT * FROM contact_campaign_status WHERE contact_id = %s AND campaign_id = %s",
                (contact_id, campaign_id),
            )
            assert cur.fetchone() is not None

    def test_no_decisions_uses_legacy_behavior(self, tmp_db):
        """Without row_decisions, behaves like before (backward compat)."""
        from src.services.smart_import import execute_import
        row = _make_transformed_row(email="new@example.com", linkedin=None)
        result = execute_import(tmp_db, [row], user_id=1)
        assert result["contacts_created"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" python3 -m pytest tests/test_smart_import.py::TestExecuteImportWithDecisions -v`
Expected: FAIL — execute_import doesn't accept row_decisions yet

- [ ] **Step 3: Implement execute_import with row decisions**

Rewrite `execute_import()` in `src/services/smart_import.py`. The new signature:

```python
def execute_import(
    conn,
    transformed: list[dict],
    *,
    user_id: int,
    row_decisions: dict[int, dict] | None = None,
    campaign_id: int | None = None,
) -> dict:
```

Key logic:
- If `row_decisions` is None, use legacy behavior (backward compat)
- If present, iterate transformed rows by index. For each:
  - `"import"` or missing: INSERT as before (ON CONFLICT DO NOTHING)
  - `"merge"`: UPDATE existing contact — set non-null import fields where CRM is null
  - `"skip"`: do nothing
  - `"enroll"`: collect existing_contact_id for enrollment
- After all inserts/merges, if `campaign_id` is set: call `bulk_enroll_contacts()` with all collected IDs (new + merged + enroll)
- Return dict adds `contacts_merged`, `contacts_enrolled`, `contacts_skipped`

- [ ] **Step 4: Update execute route to pass decisions**

In `src/web/routes/smart_import.py`, update `ExecuteRequest`:

```python
class ExecuteRequest(BaseModel):
    import_job_id: str
    excluded_indices: Optional[list[int]] = None
    row_decisions: Optional[dict[str, dict]] = None  # key is str(index)
    campaign_id: Optional[int] = None
```

In the route handler, convert string keys to int and pass through:

```python
decisions = None
if body.row_decisions:
    decisions = {int(k): v for k, v in body.row_decisions.items()}

stats = execute_import(
    conn, transformed, user_id=user["id"],
    row_decisions=decisions,
    campaign_id=body.campaign_id,
)
```

- [ ] **Step 5: Run all tests**

Run: `PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" python3 -m pytest tests/test_smart_import.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/services/smart_import.py src/web/routes/smart_import.py tests/test_smart_import.py
git commit -m "feat: execute_import supports per-row merge/skip/enroll decisions"
```

---

## Task 3: Backend — Move header detection from routes to services (P2)

**Files:**
- Modify: `src/web/routes/smart_import.py` (remove `_HEADER_KEYWORDS`, `_detect_header_row`, `_parse_csv_with_header_detection`)
- Modify: `src/services/smart_import.py` (add those functions)

- [ ] **Step 1: Write test for header detection in services**

Append to `tests/test_smart_import.py`:

```python
class TestHeaderDetection:
    """Header detection logic (moved from routes to services)."""

    def test_detect_header_row_with_metadata_prefix(self):
        from src.services.smart_import import parse_csv_with_header_detection
        csv_content = (
            "Report generated 2026-03-24,,,,\n"
            "Source: LinkedIn Export,,,,\n"
            "Firm Name,Country,Primary Contact,Primary Email,Position\n"
            "Acme Corp,USA,Alice Smith,alice@acme.com,CEO\n"
        )
        headers, rows = parse_csv_with_header_detection(csv_content)
        assert "Firm Name" in headers
        assert len(rows) == 1
        assert rows[0]["Primary Contact"] == "Alice Smith"

    def test_detect_header_row_first_row(self):
        from src.services.smart_import import parse_csv_with_header_detection
        csv_content = "Name,Email,Company\nAlice,alice@test.com,Acme\n"
        headers, rows = parse_csv_with_header_detection(csv_content)
        assert headers == ["Name", "Email", "Company"]
        assert len(rows) == 1
```

- [ ] **Step 2: Move functions**

Cut `_HEADER_KEYWORDS`, `_detect_header_row()`, and `_parse_csv_with_header_detection()` from `src/web/routes/smart_import.py`. Paste into `src/services/smart_import.py` and rename the public one to `parse_csv_with_header_detection()` (no underscore — it's now a module API). Add required imports (`csv`, `io`).

In `src/web/routes/smart_import.py`, replace with:
```python
from src.services.smart_import import parse_csv_with_header_detection
```

Update the route's `smart_import_upload()` to call `parse_csv_with_header_detection(content)` instead of `_parse_csv_with_header_detection(content)`.

- [ ] **Step 3: Run tests**

Run: `PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" python3 -m pytest tests/test_smart_import.py::TestHeaderDetection -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/services/smart_import.py src/web/routes/smart_import.py tests/test_smart_import.py
git commit -m "refactor: move header detection from routes to services layer"
```

---

## Task 4: Backend — Within-file duplicate detection (P1)

**Files:**
- Modify: `src/services/smart_import.py` (preview_import)

### What changes

After checking against CRM, also detect duplicates within the uploaded CSV itself. Group them by `email_normalized` and flag rows that share an email/LinkedIn with another row in the same file.

- [ ] **Step 1: Write failing test**

Append to `tests/test_smart_import.py`:

```python
class TestWithinFileDuplicates:
    """Detect duplicates within the uploaded CSV."""

    def test_same_email_twice_in_file(self, tmp_db):
        """Two rows with same email → second flagged as within-file duplicate."""
        row1 = _make_transformed_row(first_name="Alice", email="alice@acme.com")
        row2 = _make_transformed_row(first_name="Alicia", email="alice@acme.com", title="VP")
        result = preview_import(tmp_db, [row1, row2], user_id=1)
        rows = result["preview_rows"]
        # First occurrence: not a within-file dup
        assert rows[0].get("within_file_duplicate") is False
        # Second occurrence: flagged
        assert rows[1]["within_file_duplicate"] is True
        assert rows[1]["within_file_duplicate_of"] == 0  # index of first occurrence
```

- [ ] **Step 2: Implement within-file detection**

In `preview_import()`, after the CRM-match loop, add a second pass:

```python
    # Within-file duplicate detection
    seen_emails: dict[str, int] = {}  # email_norm -> first occurrence index
    seen_linkedins: dict[str, int] = {}
    for row in all_rows:
        idx = row["_index"]
        email_n = row.get("email_normalized")
        linkedin_n = row.get("linkedin_url_normalized")
        dup_of = None
        if email_n and email_n in seen_emails:
            dup_of = seen_emails[email_n]
        elif linkedin_n and linkedin_n in seen_linkedins:
            dup_of = seen_linkedins[linkedin_n]

        if dup_of is not None:
            row["within_file_duplicate"] = True
            row["within_file_duplicate_of"] = dup_of
        else:
            row["within_file_duplicate"] = False
            row["within_file_duplicate_of"] = None

        if email_n and email_n not in seen_emails:
            seen_emails[email_n] = idx
        if linkedin_n and linkedin_n not in seen_linkedins:
            seen_linkedins[linkedin_n] = idx
```

- [ ] **Step 3: Run tests**

Run: `PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" python3 -m pytest tests/test_smart_import.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/services/smart_import.py tests/test_smart_import.py
git commit -m "feat: detect within-file duplicates in smart import preview"
```

---

## Task 5: Frontend — Update API types for new preview/execute shapes

**Files:**
- Modify: `frontend/src/api/smartImport.ts`

- [ ] **Step 1: Update types**

```typescript
export interface FieldDiffs {
  first_name: "new" | "conflict" | "same" | "empty";
  last_name: "new" | "conflict" | "same" | "empty";
  email: "new" | "conflict" | "same" | "empty";
  title: "new" | "conflict" | "same" | "empty";
  linkedin_url: "new" | "conflict" | "same" | "empty";
}

export type RowAction = "import" | "merge" | "skip" | "enroll";

export interface RowDecision {
  action: RowAction;
  existing_contact_id?: number;
}

export interface PreviewRow {
  _index: number;
  company_name: string;
  full_name: string | null;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  email_normalized: string | null;
  title: string | null;
  linkedin_url: string | null;
  linkedin_url_normalized: string | null;
  country: string | null;
  aum_millions: number | null;
  firm_type: string | null;
  is_gdpr: boolean;
  is_duplicate: boolean;
  match_type: "exact" | "email_only" | "linkedin_only" | "both_different_contacts" | null;
  existing_contact_id: number | null;
  existing_contact: ExistingContact | null;
  field_diffs: FieldDiffs | null;
  within_file_duplicate: boolean;
  within_file_duplicate_of: number | null;
  // Legacy compat — always null now
  duplicate_type: string | null;
  overlap_cleared: null;
  [key: string]: unknown;
}

export interface ImportResult {
  companies_created: number;
  contacts_created: number;
  duplicates_skipped: number;
  contacts_merged: number;
  contacts_enrolled: number;
  contacts_skipped: number;
}
```

Update `execute` function to accept decisions and campaign:

```typescript
execute: async (
  jobId: string,
  excludedIndices?: number[],
  rowDecisions?: Record<number, RowDecision>,
  campaignId?: number,
): Promise<ImportResult> =>
  request<ImportResult>("/import/execute", {
    method: "POST",
    body: JSON.stringify({
      import_job_id: jobId,
      excluded_indices: excludedIndices?.length ? excludedIndices : undefined,
      row_decisions: rowDecisions ?? undefined,
      campaign_id: campaignId ?? undefined,
    }),
  }),
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/smartImport.ts
git commit -m "feat: update smartImport API types for field diffs and row decisions"
```

---

## Task 6: Frontend — Interactive duplicate review UI

**Files:**
- Modify: `frontend/src/pages/SmartImport.tsx`

This is the largest frontend task. It replaces the current "Email cleared" / "Already in CRM" badges with an interactive comparison panel.

### 6a: Replace PreviewTableRow with new match-aware component

- [ ] **Step 1: Rewrite PreviewTableRow status column**

Replace the status `<td>` content. Instead of checking `overlap_cleared`, check `match_type`:

```tsx
{/* Status badge */}
<td className="px-3 py-3">
  {row.within_file_duplicate ? (
    <span className="inline-block rounded-full px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-700">
      File duplicate
    </span>
  ) : row.match_type === "exact" ? (
    <button
      onClick={onToggleExpand}
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800 hover:bg-yellow-200 transition-colors"
    >
      {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      Exact match
    </button>
  ) : row.match_type ? (
    <button
      onClick={onToggleExpand}
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 hover:bg-blue-200 transition-colors"
    >
      {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      {row.match_type === "email_only" ? "Email match" :
       row.match_type === "linkedin_only" ? "LinkedIn match" : "Partial match"}
    </button>
  ) : (
    <span className="inline-block rounded-full px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700">
      New
    </span>
  )}
</td>
```

- [ ] **Step 2: Build the expandable comparison panel**

Replace the existing expanded duplicate section (lines 196-254) with a new comparison panel that shows per-field diffs:

```tsx
{/* Expandable comparison panel */}
{isExpanded && row.existing_contact && row.field_diffs && (
  <tr className="bg-gray-50">
    <td colSpan={columns.length + 3} className="px-5 py-4">
      <div className="space-y-3">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Side-by-side comparison
        </p>
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-100">
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 w-28">Field</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Import Value</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">CRM Value</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 w-20">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(["first_name", "last_name", "email", "title", "linkedin_url"] as const).map((field) => {
                const diff = row.field_diffs![field];
                const importVal = row[field] ?? "";
                const crmVal = row.existing_contact![field] ?? "";
                return (
                  <tr key={field} className={
                    diff === "new" ? "bg-green-50" :
                    diff === "conflict" ? "bg-amber-50" : ""
                  }>
                    <td className="px-3 py-2 text-xs font-medium text-gray-500 capitalize">
                      {field.replace("_", " ")}
                    </td>
                    <td className="px-3 py-2 text-gray-900">
                      {String(importVal) || <span className="text-gray-300">&mdash;</span>}
                    </td>
                    <td className="px-3 py-2 text-gray-900">
                      {String(crmVal) || <span className="text-gray-300">&mdash;</span>}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                        diff === "new" ? "bg-green-200 text-green-800" :
                        diff === "conflict" ? "bg-amber-200 text-amber-800" :
                        diff === "same" ? "bg-gray-200 text-gray-600" :
                        "bg-gray-100 text-gray-400"
                      }`}>
                        {diff === "new" ? "NEW" :
                         diff === "conflict" ? "DIFF" :
                         diff === "same" ? "SAME" : "\u2014"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Per-row action buttons */}
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={() => onDecision("merge")}
            className="px-3 py-1.5 bg-blue-600 text-white rounded text-xs font-medium hover:bg-blue-700 transition-colors"
          >
            Merge & Enroll
          </button>
          <button
            onClick={() => onDecision("enroll")}
            className="px-3 py-1.5 bg-green-600 text-white rounded text-xs font-medium hover:bg-green-700 transition-colors"
          >
            Enroll Only
          </button>
          <button
            onClick={() => onDecision("skip")}
            className="px-3 py-1.5 bg-white border border-gray-200 text-gray-600 rounded text-xs font-medium hover:bg-gray-50 transition-colors"
          >
            Skip
          </button>
          <button
            onClick={() => onDecision("import")}
            className="px-3 py-1.5 bg-white border border-gray-200 text-gray-600 rounded text-xs font-medium hover:bg-gray-50 transition-colors"
          >
            Import as New
          </button>
        </div>
      </div>
    </td>
  </tr>
)}
```

- [ ] **Step 3: Add row decision state management**

In the `SmartImport` component, add state for per-row decisions:

```tsx
const [rowDecisions, setRowDecisions] = useState<Record<number, RowDecision>>({});

const handleRowDecision = (index: number, action: RowAction, existingContactId?: number) => {
  setRowDecisions(prev => ({
    ...prev,
    [index]: { action, existing_contact_id: existingContactId },
  }));
};
```

Pass `onDecision` to `PreviewTableRow`:
```tsx
onDecision={(action: RowAction) =>
  handleRowDecision(row._index, action, row.existing_contact_id ?? undefined)
}
```

Update the prop type for `PreviewTableRow` to include:
```tsx
onDecision: (action: RowAction) => void;
decision?: RowDecision;
```

Show the current decision as a badge on the row (next to the status):
```tsx
{decision && (
  <span className={`ml-1.5 inline-block rounded-full px-2 py-0.5 text-[10px] font-medium ${
    decision.action === "merge" ? "bg-blue-100 text-blue-700" :
    decision.action === "enroll" ? "bg-green-100 text-green-700" :
    decision.action === "skip" ? "bg-gray-100 text-gray-500" :
    "bg-green-100 text-green-700"
  }`}>
    {decision.action === "merge" ? "Will merge" :
     decision.action === "enroll" ? "Will enroll" :
     decision.action === "skip" ? "Will skip" : "Will import"}
  </span>
)}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SmartImport.tsx
git commit -m "feat: interactive duplicate comparison panel with per-row decisions"
```

---

## Task 7: Frontend — Bulk actions and campaign selector

**Files:**
- Modify: `frontend/src/pages/SmartImport.tsx`

### 7a: Bulk action buttons for matched rows

- [ ] **Step 1: Add bulk action buttons**

In the toolbar section (near the existing bulk Exclude/Include buttons), add match-aware bulk actions:

```tsx
{/* Bulk match decisions — shown when duplicates exist */}
{previewData && previewData.preview_rows.some(r => r.match_type) && (
  <div className="flex items-center gap-2 text-sm">
    <span className="text-gray-400">|</span>
    <button
      onClick={() => {
        const decisions: Record<number, RowDecision> = {};
        previewData.preview_rows.forEach(r => {
          if (r.match_type && r.existing_contact_id) {
            decisions[r._index] = { action: "merge", existing_contact_id: r.existing_contact_id };
          }
        });
        setRowDecisions(prev => ({ ...prev, ...decisions }));
      }}
      className="px-2.5 py-1.5 bg-blue-50 text-blue-700 border border-blue-200 rounded-md hover:bg-blue-100 text-xs font-medium transition-colors"
    >
      Merge All Matches
    </button>
    <button
      onClick={() => {
        const decisions: Record<number, RowDecision> = {};
        previewData.preview_rows.forEach(r => {
          if (r.match_type && r.existing_contact_id) {
            decisions[r._index] = { action: "skip" };
          }
        });
        setRowDecisions(prev => ({ ...prev, ...decisions }));
      }}
      className="px-2.5 py-1.5 bg-white text-gray-600 border border-gray-200 rounded-md hover:bg-gray-50 text-xs font-medium transition-colors"
    >
      Skip All Matches
    </button>
  </div>
)}
```

### 7b: Campaign selector

- [ ] **Step 2: Add campaign selector**

Above the preview table, add an optional campaign picker. Fetch campaigns via `campaignsApi.listCampaigns()`:

```tsx
const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(null);

// Add useQuery for campaigns (at top of component)
import { useQuery } from "@tanstack/react-query";
import { campaignsApi } from "../api/campaigns";

const campaignsQuery = useQuery({
  queryKey: ["campaigns"],
  queryFn: campaignsApi.listCampaigns,
  enabled: step === "preview",
});
```

Render the selector in the preview step, between the stats grid and the toolbar:

```tsx
{/* Campaign enrollment selector */}
<div className="flex items-center gap-3 bg-white rounded-lg border border-gray-200 p-4">
  <label htmlFor="campaign-select" className="text-sm font-medium text-gray-700 whitespace-nowrap">
    Enroll imported contacts in:
  </label>
  <select
    id="campaign-select"
    value={selectedCampaignId ?? ""}
    onChange={(e) => setSelectedCampaignId(e.target.value ? Number(e.target.value) : null)}
    className="flex-1 border border-gray-200 rounded-md px-2.5 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
  >
    <option value="">No campaign (import only)</option>
    {campaignsQuery.data?.map(c => (
      <option key={c.id} value={c.id}>
        {c.name} ({c.contacts_count} contacts)
      </option>
    ))}
  </select>
</div>
```

### 7c: Wire decisions + campaign into execute mutation

- [ ] **Step 3: Update executeMutation to pass decisions and campaign**

```tsx
const executeMutation = useMutation({
  mutationFn: () =>
    smartImportApi.execute(
      analysis!.import_job_id,
      excludedIndices.size > 0 ? [...excludedIndices] : undefined,
      Object.keys(rowDecisions).length > 0 ? rowDecisions : undefined,
      selectedCampaignId ?? undefined,
    ),
  onSuccess: (data) => {
    setImportResult(data);
  },
});
```

### 7d: Update success state to show merge/enroll counts

- [ ] **Step 4: Update success display**

Replace the 3-column grid with a 5-column grid that also shows merged and enrolled:

```tsx
<div className="grid grid-cols-2 md:grid-cols-5 gap-4">
  <div className="bg-green-50 rounded-lg p-4 text-center">
    <p className="text-2xl font-bold text-green-700">{importResult.contacts_created}</p>
    <p className="text-sm text-green-600">Created</p>
  </div>
  <div className="bg-blue-50 rounded-lg p-4 text-center">
    <p className="text-2xl font-bold text-blue-700">{importResult.contacts_merged || 0}</p>
    <p className="text-sm text-blue-600">Merged</p>
  </div>
  <div className="bg-indigo-50 rounded-lg p-4 text-center">
    <p className="text-2xl font-bold text-indigo-700">{importResult.contacts_enrolled || 0}</p>
    <p className="text-sm text-indigo-600">Enrolled</p>
  </div>
  <div className="bg-gray-50 rounded-lg p-4 text-center">
    <p className="text-2xl font-bold text-gray-700">{importResult.companies_created}</p>
    <p className="text-sm text-gray-600">Companies</p>
  </div>
  <div className="bg-yellow-50 rounded-lg p-4 text-center">
    <p className="text-2xl font-bold text-yellow-700">{importResult.duplicates_skipped}</p>
    <p className="text-sm text-yellow-600">Skipped</p>
  </div>
</div>
```

- [ ] **Step 5: Update summary counts in preview**

Recompute `effectiveImportCount` to account for match decisions:

```tsx
const effectiveCounts = useMemo(() => {
  if (!previewData) return { toImport: 0, toMerge: 0, toEnroll: 0, toSkip: 0, duplicates: 0 };
  let toImport = 0, toMerge = 0, toEnroll = 0, toSkip = 0, duplicates = 0;
  for (const r of previewData.preview_rows) {
    if (excludedIndices.has(r._index)) { toSkip++; continue; }
    const decision = rowDecisions[r._index];
    if (decision) {
      if (decision.action === "merge") toMerge++;
      else if (decision.action === "enroll") toEnroll++;
      else if (decision.action === "skip") toSkip++;
      else toImport++;
    } else if (r.is_duplicate) {
      duplicates++;
    } else {
      toImport++;
    }
  }
  return { toImport, toMerge, toEnroll, toSkip, duplicates };
}, [previewData, excludedIndices, rowDecisions]);
```

Update the Import button label:
```tsx
`Import ${effectiveCounts.toImport} New${effectiveCounts.toMerge ? ` + Merge ${effectiveCounts.toMerge}` : ""}${effectiveCounts.toEnroll ? ` + Enroll ${effectiveCounts.toEnroll}` : ""}`
```

- [ ] **Step 6: Add `selectedCampaignId` and `rowDecisions` to resetAll**

```tsx
setRowDecisions({});
setSelectedCampaignId(null);
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/SmartImport.tsx
git commit -m "feat: bulk match actions, campaign selector, and smart import summary"
```

---

## Task 8: Frontend — Update preview stat cards and filter tabs

**Files:**
- Modify: `frontend/src/pages/SmartImport.tsx`

- [ ] **Step 1: Update the filter tabs to include "Matches" filter**

Replace the 3-button filter group with one that covers all states:

```tsx
const FILTER_OPTIONS = [
  { key: "all", label: "All" },
  { key: "new", label: "New" },
  { key: "matches", label: "CRM Matches" },
  { key: "file_dupes", label: "File Duplicates" },
] as const;
type PreviewFilter = typeof FILTER_OPTIONS[number]["key"];
```

Update `previewShowFilter` state type and the `filteredPreviewRows` logic:

```tsx
if (previewShowFilter === "new")
  rows = rows.filter((r) => !r.match_type && !r.within_file_duplicate);
else if (previewShowFilter === "matches")
  rows = rows.filter((r) => r.match_type != null);
else if (previewShowFilter === "file_dupes")
  rows = rows.filter((r) => r.within_file_duplicate);
```

- [ ] **Step 2: Update summary stat cards**

Replace the 4-card grid with counts that reflect the new categories:

```tsx
const matchCount = previewData.preview_rows.filter(r => r.match_type).length;
const fileDupeCount = previewData.preview_rows.filter(r => r.within_file_duplicate).length;
const newCount = previewData.preview_rows.filter(r => !r.match_type && !r.within_file_duplicate).length;
```

Cards: Total contacts, New, CRM Matches (clickable), File Duplicates (if any).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/SmartImport.tsx
git commit -m "feat: updated preview stats and filter tabs for match types"
```

---

## Task 9: Integration verification

- [ ] **Step 1: Run all backend tests**

Run: `PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" python3 -m pytest tests/ -v --timeout=60`
Expected: All tests pass including new `test_smart_import.py`

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 3: Verify dev server starts**

Run: `cd frontend && npm run dev` (manual check)

- [ ] **Step 4: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix: integration fixups for smart import redesign"
```
