# Spec 03: API Hardening

**Priority:** P0 — Required before production
**Estimated time:** 2–3 hours
**Prerequisite:** Spec 01 + Spec 02 completed

---

## Problem Statement

The FastAPI web API lacks input validation, rate limiting, consistent error responses, and proper health checks. Malformed requests can crash endpoints, there's no protection against abuse, and errors return raw Python tracebacks instead of structured JSON. These issues make the API fragile and insecure under real-world usage.

---

## Task 1: Add Rate Limiting

**Install dependency:**
```bash
pip install slowapi>=0.1 --break-system-packages
```

**Add to `pyproject.toml` dependencies:**
```
"slowapi>=0.1",
```

**File:** `src/web/app.py`

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

Apply default rate limit to all routes and stricter limits on mutation endpoints:

```python
# In src/web/app.py — apply default limit
from slowapi.middleware import SlowAPIMiddleware
app.add_middleware(SlowAPIMiddleware)

# Default: 60 requests/minute per IP
# For write endpoints, add decorator in individual route files:
# @limiter.limit("10/minute")
```

Apply stricter limits on sensitive routes:
- `POST /api/import/csv` → 5/minute (heavy operation)
- `POST /api/contacts/{id}/status` → 30/minute
- `POST /api/gmail/send` → 10/minute
- All other POST/PUT/DELETE → 30/minute
- All GET → 60/minute (default)

**Acceptance criteria:**
- [ ] Rate limiter installed and active
- [ ] Exceeding rate returns 429 with `Retry-After` header
- [ ] Import endpoint limited to 5/minute
- [ ] Default limit is 60 requests/minute per IP
- [ ] Rate limit info in response headers (X-RateLimit-Limit, X-RateLimit-Remaining)

---

## Task 2: Add Pydantic Request Validation

**Files to modify:** All route files in `src/web/routes/`

Add Pydantic models for request validation. The contacts.py route already has some (StatusTransitionRequest, ResponseNoteRequest). Extend this pattern to all routes.

**Key models to add:**

```python
# src/web/schemas.py (new file)
from pydantic import BaseModel, Field
from typing import Optional

class PaginationParams(BaseModel):
    page: int = Field(1, ge=1, description="Page number")
    per_page: int = Field(50, ge=1, le=100, description="Items per page (max 100)")

class ContactSearchParams(PaginationParams):
    search: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = Field(None, pattern="^(queued|in_progress|replied_positive|replied_negative|completed|unsubscribed|bounced)$")

class CRMContactSearchParams(PaginationParams):
    search: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = None
    company_type: Optional[str] = None
    min_aum: Optional[float] = Field(None, ge=0)
    max_aum: Optional[float] = Field(None, ge=0)

class CampaignCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

class TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    subject_template: str = Field(..., min_length=1, max_length=300)
    body_template: str = Field(..., min_length=1)
    channel: str = Field("email", pattern="^(email|linkedin)$")
    variant_group: Optional[str] = None
    variant_label: Optional[str] = None

class GlobalSearchQuery(BaseModel):
    q: str = Field(..., min_length=1, max_length=200)
```

Then replace raw query parameters with these models in route functions:
```python
# Before:
def list_contacts(search: Optional[str] = None, page: int = 1, per_page: int = 50, ...):

# After:
def list_contacts(params: ContactSearchParams = Depends(), conn=Depends(get_db)):
    offset = (params.page - 1) * params.per_page
```

**Acceptance criteria:**
- [ ] All pagination is capped at 100 items per page
- [ ] Page numbers must be >= 1
- [ ] Search strings capped at 200 characters
- [ ] Status values validated against allowed set
- [ ] AUM filters must be >= 0
- [ ] Invalid requests return 422 with clear error message
- [ ] All existing API behavior preserved for valid inputs

---

## Task 3: Add Consistent Error Response Format

**File:** Create `src/web/error_handlers.py`

```python
"""Centralized error handling for the API."""

from __future__ import annotations

import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI):
    """Register all error handlers on the FastAPI app."""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": True,
                "status_code": exc.status_code,
                "message": exc.detail,
            },
        )

    @app.exception_handler(ValidationError)
    async def validation_exception_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": True,
                "status_code": 422,
                "message": "Validation error",
                "details": exc.errors(),
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": True,
                "status_code": 500,
                "message": "Internal server error",
                # Don't expose stack trace in production
            },
        )
```

Register in `src/web/app.py`:
```python
from src.web.error_handlers import register_error_handlers
register_error_handlers(app)
```

**Acceptance criteria:**
- [ ] All errors return JSON with `error`, `status_code`, `message` fields
- [ ] 422 errors include `details` array from Pydantic
- [ ] 500 errors do NOT expose stack traces
- [ ] 500 errors are logged with full traceback server-side
- [ ] Frontend client.ts can parse all error responses consistently

---

## Task 4: Fix Health Check with DB Ping

**File:** `src/web/app.py`

**Current:**
```python
@app.get("/api/health")
def health_check():
    return {"status": "ok"}
```

**Fix:**
```python
import time

@app.get("/api/health", dependencies=[])
def health_check(conn=Depends(get_db)):
    """Health check with database connectivity verification."""
    checks = {"api": "ok", "database": "unknown"}

    try:
        start = time.time()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        db_ms = round((time.time() - start) * 1000, 1)
        checks["database"] = "ok"
        checks["database_latency_ms"] = db_ms
    except Exception as e:
        checks["database"] = f"error: {str(e)}"
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "checks": checks},
        )

    return {"status": "ok", "checks": checks}
```

Note: health check should NOT require API key auth (it's excluded via `dependencies=[]`).

**Acceptance criteria:**
- [ ] Health check verifies DB connectivity via `SELECT 1`
- [ ] Returns 200 with `database: ok` when DB is reachable
- [ ] Returns 503 with `database: error` when DB is down
- [ ] Includes database latency in milliseconds
- [ ] Does not require authentication

---

## Task 5: Add Request Logging Middleware

**File:** Create `src/web/middleware.py`

```python
"""Request logging middleware."""

import logging
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("outreach.api")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000, 1)

        logger.info(
            "%s %s → %s (%sms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        response.headers["X-Response-Time"] = f"{duration_ms}ms"
        return response
```

Add to `app.py`:
```python
from src.web.middleware import RequestLoggingMiddleware
app.add_middleware(RequestLoggingMiddleware)
```

**Acceptance criteria:**
- [ ] Every request logs: method, path, status code, duration
- [ ] Response includes X-Response-Time header
- [ ] No PII logged (no email addresses, no request bodies)

---

## Task 6: Enable OpenAPI Documentation

**File:** `src/web/app.py`

FastAPI auto-generates OpenAPI docs, but they may not be properly exposed. Ensure:

```python
app = FastAPI(
    title="Outreach Campaign API",
    version="2.0.0",
    description="Multi-channel outreach campaign manager for crypto fund allocators",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
    dependencies=[Depends(verify_api_key)],
)
```

The docs endpoints (`/api/docs`, `/api/redoc`) should be accessible without auth in development but can be restricted in production via an env var:

```python
import os
ENABLE_DOCS = os.getenv("ENABLE_API_DOCS", "true").lower() == "true"

app = FastAPI(
    ...
    docs_url="/api/docs" if ENABLE_DOCS else None,
    redoc_url="/api/redoc" if ENABLE_DOCS else None,
)
```

**Acceptance criteria:**
- [ ] `/api/docs` shows Swagger UI
- [ ] `/api/redoc` shows ReDoc
- [ ] `/api/openapi.json` returns the OpenAPI spec
- [ ] Docs can be disabled via `ENABLE_API_DOCS=false` env var

---

## Verification Checklist

```bash
# Test rate limiting
for i in $(seq 1 65); do curl -s -o /dev/null -w "%{http_code}\n" -H "X-API-Key: KEY" http://localhost:8000/api/contacts; done
# Should see 429 after 60 requests

# Test validation
curl -H "X-API-Key: KEY" "http://localhost:8000/api/contacts?page=-1"        # Should return 422
curl -H "X-API-Key: KEY" "http://localhost:8000/api/contacts?per_page=9999"  # Should return 422

# Test health check
curl http://localhost:8000/api/health  # Should return DB status

# Test docs
open http://localhost:8000/api/docs    # Should show Swagger UI

# Run all tests
make test
```

- [ ] Rate limiting active (429 after limit exceeded)
- [ ] Invalid inputs return 422 with details
- [ ] All errors use consistent JSON format
- [ ] Health check pings database
- [ ] Request logging shows method/path/status/duration
- [ ] OpenAPI docs accessible at /api/docs
