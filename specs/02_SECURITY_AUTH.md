# Spec 02: Security & Authentication

**Priority:** P0 — BLOCKING before any public deployment
**Estimated time:** 3–4 hours
**Prerequisite:** Spec 01 (Production Hardening) completed

---

## Problem Statement

The web API has zero authentication. All 50+ endpoints are publicly accessible to anyone on the network. There is no API key, no JWT, no session management. Additionally, CORS is hardcoded to localhost, Gmail tokens are stored insecurely, and file uploads have no size/type validation. These issues must be resolved before the app can be accessed outside of localhost.

---

## Task 1: Add API Key Authentication Middleware

**Files to create/modify:**
- Create: `src/web/auth.py`
- Modify: `src/web/app.py`
- Modify: `.env` (add API_SECRET_KEY)
- Modify: `.env.example`

**Implementation:**

Create `src/web/auth.py`:
```python
"""API key authentication middleware."""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_api_key() -> str:
    """Get or generate the API key from environment."""
    key = os.getenv("API_SECRET_KEY")
    if not key:
        # Generate a key and print it (for first-time setup)
        key = secrets.token_urlsafe(32)
        print(f"\n⚠️  No API_SECRET_KEY set. Generated: {key}")
        print(f"   Add to .env: API_SECRET_KEY={key}\n")
    return key

async def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)):
    """FastAPI dependency that validates the API key header."""
    expected = get_api_key()
    if not api_key or api_key != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Pass X-API-Key header.",
        )
    return api_key
```

Apply to all routes in `src/web/app.py`:
```python
from src.web.auth import verify_api_key
from fastapi import Depends

# Add global dependency to all routes
app = FastAPI(
    title="Outreach Campaign Dashboard",
    version="2.0.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_api_key)],
)

# EXCEPT health check — override to be public:
@app.get("/api/health", dependencies=[])
def health_check():
    ...
```

Update `.env` and `.env.example`:
```
API_SECRET_KEY=your-secret-key-here
```

Update the React frontend `api/client.ts` to include the API key:
```typescript
const API_KEY = import.meta.env.VITE_API_KEY || "";

async function fetchAPI(path: string, options: RequestInit = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
      ...options.headers,
    },
  });
  // ... existing error handling
}
```

Add to frontend `.env`:
```
VITE_API_KEY=your-secret-key-here
```

**Acceptance criteria:**
- [ ] All API endpoints (except /api/health) return 401 without X-API-Key header
- [ ] All endpoints return 200 with valid X-API-Key header
- [ ] Health check is accessible without authentication
- [ ] Frontend sends API key in all requests
- [ ] API key is loaded from .env (not hardcoded)
- [ ] .env.example is updated with API_SECRET_KEY placeholder

---

## Task 2: Fix CORS Configuration

**File:** `src/web/app.py`

**Current (broken):**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Fix:**
```python
import os

ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)
```

Update `.env.example`:
```
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

**Acceptance criteria:**
- [ ] Origins loaded from ALLOWED_ORIGINS env var
- [ ] Default still allows localhost:5173 (dev mode works)
- [ ] Only specified HTTP methods are allowed (no wildcard)
- [ ] Only needed headers are allowed (Content-Type, X-API-Key)
- [ ] Production can set `ALLOWED_ORIGINS=https://app.yourdomain.com`

---

## Task 3: Secure Gmail Token Storage

**File:** `src/services/gmail_drafter.py` (around line 94)

**Current (insecure):**
```python
self.token_path = Path(token_path)  # defaults to ".gmail_token.json" in project root
self.token_path.write_text(creds.to_json())
```

**Fix:**
```python
import os

# Store tokens in a secure directory outside project root
DEFAULT_TOKEN_DIR = os.path.expanduser("~/.outreach-campaign")
DEFAULT_TOKEN_PATH = os.path.join(DEFAULT_TOKEN_DIR, "gmail_token.json")

def __init__(self, ..., token_path: str = None):
    self.token_path = Path(token_path or os.getenv("GMAIL_TOKEN_PATH", DEFAULT_TOKEN_PATH))

    # Create directory with restricted permissions
    self.token_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(str(self.token_path.parent), 0o700)

def _save_token(self, creds):
    """Save token with restricted file permissions."""
    self.token_path.write_text(creds.to_json())
    os.chmod(str(self.token_path), 0o600)  # Owner read/write only
```

Also add to `.gitignore`:
```
.gmail_token.json
**/gmail_token.json
```

**Acceptance criteria:**
- [ ] Token file stored in ~/.outreach-campaign/ (not project root)
- [ ] Token file has 600 permissions (owner read/write only)
- [ ] Token directory has 700 permissions
- [ ] GMAIL_TOKEN_PATH env var overrides default location
- [ ] .gitignore blocks all gmail_token.json files

---

## Task 4: Add File Upload Validation

**File:** `src/web/routes/import_routes.py`

**Current (vulnerable):**
```python
async def import_csv(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV")
    content = await file.read()
    # No size limit, no MIME type check
```

**Fix:**
```python
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

ALLOWED_MIME_TYPES = [
    "text/csv",
    "application/csv",
    "text/plain",              # Some systems send CSV as text/plain
    "application/vnd.ms-excel", # Excel sometimes masquerades as CSV
]

async def import_csv(file: UploadFile = File(...)):
    # Check filename
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV")

    # Check MIME type
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"Invalid file type: {file.content_type}. Must be CSV.")

    # Read with size limit
    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB")

    # Validate content is parseable as CSV
    try:
        import csv
        import io
        reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
        # Read first row to validate structure
        first_row = next(reader, None)
        if first_row is None:
            raise HTTPException(400, "CSV file is empty")
    except UnicodeDecodeError:
        raise HTTPException(400, "File must be UTF-8 encoded text")
    except csv.Error as e:
        raise HTTPException(400, f"Invalid CSV format: {e}")

    # ... rest of existing import logic
```

**Acceptance criteria:**
- [ ] Files larger than 10MB are rejected with 413
- [ ] Non-CSV MIME types are rejected with 400
- [ ] Non-UTF-8 files are rejected
- [ ] Empty CSVs are rejected
- [ ] Malformed CSVs are rejected
- [ ] Valid CSVs under 10MB still import correctly

---

## Task 5: Fix Jinja2 Autoescape

**File:** `src/services/template_engine.py` (around line 34)

**Current:**
```python
env = Environment(loader=..., autoescape=False)
```

**Fix:**
```python
from jinja2 import Environment, select_autoescape

env = Environment(
    loader=...,
    autoescape=select_autoescape(
        enabled_extensions=("html", "htm"),
        default_for_string=False,  # Plain text templates stay unescaped
    ),
)
```

This way: `.html` templates get autoescaped (XSS protection), `.txt` templates stay plain text (no unwanted escaping).

**Acceptance criteria:**
- [ ] HTML templates have autoescape enabled
- [ ] Plain text templates (.txt) are NOT escaped
- [ ] Existing template rendering still works
- [ ] Special characters in contact names don't break HTML emails

---

## Task 6: Add Security Tests

**File:** Create `tests/test_security.py`

```python
"""Security tests for authentication, CORS, and upload validation."""

import pytest
from fastapi.testclient import TestClient


def test_api_rejects_unauthenticated_request(client):
    """All endpoints should return 401 without API key."""
    response = client.get("/api/contacts")
    assert response.status_code == 401


def test_api_accepts_valid_api_key(client):
    """Endpoints should work with valid API key."""
    response = client.get(
        "/api/contacts",
        headers={"X-API-Key": "test-key"},
    )
    assert response.status_code == 200


def test_health_check_is_public(client):
    """Health check should not require authentication."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_upload_rejects_oversized_file(client):
    """Import endpoint should reject files over 10MB."""
    large_content = b"name,email\n" + b"a,b@c.com\n" * 2_000_000
    response = client.post(
        "/api/import/csv",
        files={"file": ("huge.csv", large_content, "text/csv")},
        headers={"X-API-Key": "test-key"},
    )
    assert response.status_code == 413


def test_upload_rejects_non_csv(client):
    """Import endpoint should reject non-CSV files."""
    response = client.post(
        "/api/import/csv",
        files={"file": ("malware.exe", b"MZ...", "application/octet-stream")},
        headers={"X-API-Key": "test-key"},
    )
    assert response.status_code == 400
```

**Acceptance criteria:**
- [ ] Test file created and all tests pass
- [ ] Tests cover: unauthenticated rejection, authenticated access, health check public, file size limit, file type limit

---

## Verification Checklist

```bash
# Test auth works
curl http://localhost:8000/api/contacts          # Should return 401
curl -H "X-API-Key: YOUR_KEY" http://localhost:8000/api/contacts  # Should return 200
curl http://localhost:8000/api/health             # Should return 200 (no auth)

# Run all tests
make test
```

- [ ] All unauthenticated requests return 401
- [ ] Health check is publicly accessible
- [ ] CORS headers use env var
- [ ] Gmail token stored outside project root
- [ ] File uploads validated (size + type)
- [ ] All existing tests still pass
