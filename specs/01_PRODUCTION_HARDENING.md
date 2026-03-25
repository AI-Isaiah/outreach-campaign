# Spec 01: Production Hardening

**Priority:** P0 — BLOCKING. Do this first before any other spec.
**Estimated time:** 2–3 hours
**Prerequisite:** None

---

## Problem Statement

The codebase has 6 known bugs and 3 performance bottlenecks that will cause failures in production. These must be fixed before adding features or deploying. The bugs were identified in the March 3 code review (see `CODE_REVIEW_COMPREHENSIVE.md` and `NEXT_STEPS.md`).

---

## Task 1: Fix Double Compliance Footer in HTML Emails

**File:** `src/services/email_sender.py` (around line 160–185)
**Bug:** The compliance footer is added to the plain-text body. Then the text is converted to HTML (which includes the footer). Then the HTML footer is added AGAIN. Result: duplicate footer in HTML emails.

**Fix logic:**
1. Render the template body (plain text)
2. Convert body (WITHOUT footer) to HTML
3. Add plain-text footer to plain-text version
4. Add HTML footer to HTML version
5. Each version gets the footer exactly once

**Acceptance criteria:**
- [ ] Send a test email — HTML version has exactly one compliance footer
- [ ] Plain-text version has exactly one compliance footer
- [ ] Footer contains: physical address, unsubscribe link
- [ ] Existing test `test_email_sender.py` still passes

---

## Task 2: Fix Deduplication Transaction Safety

**File:** `src/services/deduplication.py` (lines 37–100)
**Bug:** The 3-pass dedup loop does DELETE + INSERT without rollback on failure. If pass 2 fails mid-way, pass 1's changes are committed but pass 2 leaves corrupt data.

**Fix:**
```python
# Wrap each pass in try/except with rollback
for pass_name, pass_func in passes:
    try:
        result = pass_func(conn, ...)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Dedup pass '{pass_name}' failed: {e}")
        raise
```

**Acceptance criteria:**
- [ ] Each dedup pass is wrapped in try/except with conn.rollback()
- [ ] If a pass fails, subsequent passes do NOT run
- [ ] Error is logged with pass name and exception details
- [ ] Existing test `test_deduplication.py` still passes

---

## Task 3: Fix NULL Template Body Crash

**File:** `src/services/email_sender.py` (around line 167)
**Bug:** If `body_template` is NULL in the database, calling `.endswith(".txt")` crashes with `AttributeError: 'NoneType'`.

**Fix:**
```python
template_body = template_row.get("body_template") or ""
```

**Acceptance criteria:**
- [ ] Calling send with a template that has NULL body_template does not crash
- [ ] Returns False or logs a warning instead of raising AttributeError
- [ ] Add a test case for NULL body_template in `test_email_sender.py`

---

## Task 4: Fix Cursor Leaks in Services

**Files:** `src/services/priority_queue.py`, `src/services/state_machine.py`, `src/services/compliance.py`
**Bug:** Cursors are created with `conn.cursor()` but never closed in a finally block. If an exception occurs, the cursor leaks.

**Fix pattern for all three files:**
```python
cursor = conn.cursor()
try:
    cursor.execute(...)
    # ... business logic ...
finally:
    cursor.close()
```

**Acceptance criteria:**
- [ ] Every `conn.cursor()` call in these 3 files is wrapped in try/finally
- [ ] All existing tests pass
- [ ] No cursor objects left open on exception paths

---

## Task 5: Move Migrations to App Startup

**File:** `src/web/dependencies.py` (around line 14)
**Bug:** `run_migrations(conn)` is called on EVERY web request via the `get_db` dependency. This executes 330+ lines of SQL on every API call.

**Fix:**
```python
# In src/web/app.py, add startup event:
from contextlib import asynccontextmanager
from src.models.database import get_connection, run_migrations
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run migrations once at startup
    db_url = os.getenv("SUPABASE_DB_URL")
    if db_url:
        conn = get_connection(db_url)
        try:
            run_migrations(conn)
            conn.commit()
        finally:
            conn.close()
    yield

app = FastAPI(
    title="Outreach Campaign Dashboard",
    version="2.0.0",
    lifespan=lifespan,
)
```

Then REMOVE the `run_migrations()` call from `get_db()` in `dependencies.py`.

**Acceptance criteria:**
- [ ] Migrations run exactly once on server startup
- [ ] `get_db()` no longer calls `run_migrations()`
- [ ] API requests are faster (no 330-line SQL overhead per request)
- [ ] App still works correctly after restart

---

## Task 6: Add Connection Pooling

**File:** `src/models/database.py`
**Bug:** `get_connection()` creates a brand-new psycopg2 connection on every call. The web app calls this per-request, which will exhaust Supabase's 60-connection limit under any real load.

**Fix:**
```python
import psycopg2
import psycopg2.extras
import psycopg2.pool
from pathlib import Path
import os

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations" / "pg"

_pool = None

def get_pool(db_url: str = None, minconn: int = 2, maxconn: int = 10):
    global _pool
    if _pool is None:
        url = db_url or os.getenv("SUPABASE_DB_URL")
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn, maxconn, url,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return _pool

def get_connection(db_url: str = None):
    """Get a connection from the pool (or create direct if no pool)."""
    if _pool is not None:
        conn = _pool.getconn()
        conn.autocommit = False
        return conn
    # Fallback for CLI commands and tests
    url = db_url or os.getenv("SUPABASE_DB_URL")
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn

def return_connection(conn):
    """Return a connection to the pool."""
    if _pool is not None:
        _pool.putconn(conn)
    else:
        conn.close()

def run_migrations(conn) -> None:
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    cursor = conn.cursor()
    for migration_file in migration_files:
        sql = migration_file.read_text().strip()
        if sql:
            cursor.execute(sql)
    conn.commit()

def get_table_names(conn) -> list[str]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public'"
    )
    return [row["table_name"] for row in cursor.fetchall()]
```

Then update `src/web/dependencies.py` to use `return_connection`:
```python
def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        return_connection(conn)
```

Initialize the pool in the lifespan handler (from Task 5):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    db_url = os.getenv("SUPABASE_DB_URL")
    if db_url:
        pool = get_pool(db_url)
        conn = get_connection()
        try:
            run_migrations(conn)
        finally:
            return_connection(conn)
    yield
    # Cleanup pool on shutdown
    if _pool:
        _pool.closeall()
```

**Acceptance criteria:**
- [ ] Web requests use pooled connections (verify with `_pool.getconn()` / `putconn()`)
- [ ] CLI commands still work (fallback to direct connection when no pool)
- [ ] Tests still work (they use their own ephemeral PG instance)
- [ ] Connections are always returned to pool (no leaks)

---

## Task 7: Fix N+1 Query in Priority Queue

**File:** `src/services/priority_queue.py` (lines 118–120)
**Bug:** For each contact in the queue, a separate query fetches `total_steps`. With 50 contacts in queue, this is 51 queries.

**Fix:** Replace the per-row call with a single JOIN or subquery in the main queue query:
```python
# Instead of:
for row in rows:
    total_steps = count_steps_for_contact(conn, row["contact_id"], campaign_id)

# Use a single query that includes step counts:
query = """
    SELECT ccs.*, c.full_name, c.email, co.name AS company_name, co.aum_millions,
           (SELECT COUNT(*) FROM sequence_steps ss
            WHERE ss.campaign_id = ccs.campaign_id) AS total_steps
    FROM contact_campaign_status ccs
    JOIN contacts c ON c.id = ccs.contact_id
    LEFT JOIN companies co ON co.id = c.company_id
    WHERE ccs.campaign_id = %s AND ccs.status = 'queued'
    ...
"""
```

Note: If `total_steps` is the same for all contacts in a campaign (sequence_steps are campaign-level, not per-contact), this can be a single count fetched once outside the loop.

**Acceptance criteria:**
- [ ] No per-row query calls inside the priority queue loop
- [ ] Queue generation uses at most 2-3 queries total (regardless of queue size)
- [ ] `test_priority_queue.py` still passes
- [ ] Queue output is identical to before (same contacts, same order)

---

## Task 8: Fix current_step Schema Default

**File:** `migrations/pg/001_initial_schema.sql`
**Bug:** `current_step` column defaults to 0 in the schema, but enrollment always inserts 1 (sequence steps start at 1). Inconsistency causes confusion.

**Fix:** Change the DEFAULT in the migration:
```sql
current_step INTEGER NOT NULL DEFAULT 1,
```

**Acceptance criteria:**
- [ ] Schema default matches enrollment behavior
- [ ] Existing enrolled contacts not affected (they already have current_step=1)

---

## Verification Checklist

After completing all 8 tasks:

```bash
# Run the full test suite
PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH" make test

# Start the web app and verify it launches without errors
python3 -m uvicorn src.web.app:app --reload

# Hit the health endpoint
curl http://localhost:8000/api/health
```

- [ ] All tests pass
- [ ] Web app starts without migration errors
- [ ] Health endpoint returns 200
- [ ] No Python warnings about deprecated patterns
