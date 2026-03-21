# Spec 06: Deployment Infrastructure

**Priority:** P1 — Required for production launch
**Estimated time:** 4–6 hours
**Prerequisite:** All previous specs completed (01–05)

---

## Problem Statement

The platform runs exclusively on localhost with no containerization, no CI/CD, no monitoring, and no automated deployment. To go live, we need Docker for consistent environments, a deployment target (Railway/Render/Fly.io), GitHub Actions for CI/CD, and monitoring/alerting to know when things break.

---

## Task 1: Create Dockerfile + Docker Compose

**Files to create:**
- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`

`Dockerfile`:
```dockerfile
# Multi-stage build for smaller image
FROM python:3.12-slim as builder

WORKDIR /app

# Install system deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e "."

FROM python:3.12-slim

WORKDIR /app

# Runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .

# Don't run as root
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "src.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

`docker-compose.yml` (for local development):
```yaml
version: "3.8"

services:
  backend:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      - ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
    depends_on:
      - db
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "5173:5173"
    environment:
      - VITE_API_URL=http://localhost:8000
    depends_on:
      - backend

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: outreach
      POSTGRES_USER: outreach
      POSTGRES_PASSWORD: localdev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

`frontend/Dockerfile`:
```dockerfile
FROM node:20-alpine

WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]
```

`.dockerignore`:
```
.git
.venv
__pycache__
*.pyc
.env
outreach.db*
node_modules
data/imports/
.gmail_token.json
*.db-shm
*.db-wal
```

**Acceptance criteria:**
- [ ] `docker compose up` starts backend, frontend, and PostgreSQL
- [ ] Backend accessible at http://localhost:8000
- [ ] Frontend accessible at http://localhost:5173
- [ ] Frontend can communicate with backend
- [ ] Database persists between restarts (volume mounted)
- [ ] Non-root user in backend container

---

## Task 2: GitHub Actions CI Pipeline

**File:** Create `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: test_outreach
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run tests
        env:
          SUPABASE_DB_URL: postgresql://test:test@localhost:5432/test_outreach
        run: python -m pytest tests/ -v --tb=short

      - name: Lint (ruff)
        run: |
          pip install ruff
          ruff check src/

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 20

      - run: npm ci
      - run: npm run build
      # - run: npm test  # Uncomment when frontend tests exist
```

**Acceptance criteria:**
- [ ] CI runs on push to main and on pull requests
- [ ] Python tests run against ephemeral PostgreSQL
- [ ] Linting checks pass (ruff)
- [ ] Frontend builds without errors
- [ ] GitHub shows green/red status on commits

---

## Task 3: Deploy to Railway (or Render/Fly.io)

**Recommended: Railway** — simplest for Python + PostgreSQL + frontend.

**Files to create:**

`railway.toml` (Railway config):
```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "uvicorn src.web.app:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/api/health"
healthcheckTimeout = 10
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3
```

**Deployment steps (document in `docs/deploy.md`):**
1. Create Railway account at railway.app
2. Create new project → "Deploy from GitHub repo"
3. Connect your GitHub repository
4. Add PostgreSQL service to the project
5. Set environment variables:
   - `SUPABASE_DB_URL` → Railway provides this as `DATABASE_URL`
   - `API_SECRET_KEY` → Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   - `ALLOWED_ORIGINS` → Your frontend domain
   - `UNSUBSCRIBE_SECRET` → Generate random string
   - `APP_BASE_URL` → Your Railway backend URL
   - `SMTP_PASSWORD`, `EMAIL_VERIFY_API_KEY`, etc.
6. Deploy backend
7. Deploy frontend (separate service or Vercel/Netlify)

**Alternative: Create `Procfile`** (works on Railway, Render, Heroku):
```
web: uvicorn src.web.app:app --host 0.0.0.0 --port ${PORT:-8000}
```

**Acceptance criteria:**
- [ ] Backend deploys successfully to Railway
- [ ] Health check passes on deployed instance
- [ ] Frontend deployed (Railway or Vercel)
- [ ] Frontend connects to deployed backend
- [ ] Environment variables configured (no secrets in code)
- [ ] Database migrations run on deploy

---

## Task 4: Database Backup Strategy

**For Supabase (current):**
- Supabase provides daily automated backups on Pro plan
- Document how to do manual backups:

```bash
# Manual backup (add to docs/backup.md)
pg_dump $SUPABASE_DB_URL --no-owner --no-acl > backup_$(date +%Y%m%d).sql

# Restore
psql $SUPABASE_DB_URL < backup_20260303.sql
```

**For Railway PostgreSQL:**
- Railway provides daily backups automatically
- Document manual backup procedure

**Create `scripts/backup.sh`:**
```bash
#!/bin/bash
# Backup the outreach database
set -e

BACKUP_DIR="backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="${BACKUP_DIR}/outreach_${TIMESTAMP}.sql"

mkdir -p "$BACKUP_DIR"
pg_dump "$SUPABASE_DB_URL" --no-owner --no-acl > "$FILENAME"
gzip "$FILENAME"

echo "Backup saved: ${FILENAME}.gz"

# Keep only last 30 backups
ls -t "${BACKUP_DIR}"/*.gz | tail -n +31 | xargs -r rm
```

**Acceptance criteria:**
- [ ] Backup script created and tested
- [ ] Script compresses output
- [ ] Script auto-deletes backups older than 30
- [ ] Documented in `docs/backup.md`

---

## Task 5: Monitoring & Alerting

**Integrate Sentry for error tracking:**

Install:
```bash
pip install sentry-sdk[fastapi] --break-system-packages
```

Add to `pyproject.toml`:
```
"sentry-sdk[fastapi]>=2.0",
```

Configure in `src/web/app.py`:
```python
import sentry_sdk

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.1,  # 10% of requests traced
        profiles_sample_rate=0.1,
    )
```

**Add uptime monitoring:**
Document setup for Better Stack (formerly Better Uptime) or UptimeRobot:
- Monitor: `https://your-app.railway.app/api/health`
- Check interval: 5 minutes
- Alert via email on 2 consecutive failures

**Configure structured logging:**

```python
# src/web/logging_config.py
import logging
import json
import sys

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)

def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)
    # Quiet down noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
```

Call in app startup:
```python
from src.web.logging_config import setup_logging
setup_logging()
```

**Acceptance criteria:**
- [ ] Sentry captures unhandled exceptions
- [ ] Sentry DSN configurable via env var (disabled if not set)
- [ ] Structured JSON logging to stdout
- [ ] Uptime monitoring documented
- [ ] No PII in Sentry reports (use contact_id, not email)

---

## Task 6: Production Hardening Checklist

Create `docs/production_checklist.md`:

```markdown
# Production Launch Checklist

## Environment Variables (all required)
- [ ] SUPABASE_DB_URL / DATABASE_URL
- [ ] API_SECRET_KEY (generated, unique per environment)
- [ ] ALLOWED_ORIGINS (your frontend domain, NO localhost)
- [ ] SMTP_PASSWORD
- [ ] EMAIL_VERIFY_API_KEY
- [ ] UNSUBSCRIBE_SECRET
- [ ] APP_BASE_URL (your deployed backend URL)
- [ ] SENTRY_DSN (optional but recommended)
- [ ] GMAIL_TOKEN_PATH
- [ ] ENABLE_API_DOCS=false (disable Swagger in production)

## DNS & Email
- [ ] SPF record configured for sending domain
- [ ] DKIM record configured
- [ ] DMARC record configured (start with p=none)
- [ ] Custom domain pointing to deployed app

## Security
- [ ] API key authentication enabled
- [ ] CORS restricted to production domain only
- [ ] Gmail token NOT in project directory
- [ ] .env NOT committed to git
- [ ] No console.log in frontend build
- [ ] HTTPS enabled

## Monitoring
- [ ] Sentry configured and capturing errors
- [ ] Uptime check configured (5-minute interval)
- [ ] Database backup verified (daily)
- [ ] Log aggregation accessible

## Testing
- [ ] All pytest tests passing in CI
- [ ] Frontend builds without warnings
- [ ] Smoke test: import CSV → enroll → queue → preview email
- [ ] Unsubscribe link works end-to-end
```

**Acceptance criteria:**
- [ ] Checklist document created
- [ ] All items actionable and specific
- [ ] Covers: env vars, DNS, security, monitoring, testing

---

## Verification Checklist

After completing all tasks:

```bash
# Build and run with Docker
docker compose up --build

# Verify all services running
docker compose ps

# Test health check on Docker
curl http://localhost:8000/api/health

# Run CI locally
act  # or push to GitHub and check Actions tab

# Test backup script
./scripts/backup.sh
```

- [ ] Docker Compose starts all 3 services
- [ ] CI pipeline passes on GitHub
- [ ] Deployment guide documented
- [ ] Backup script works
- [ ] Sentry captures test exception
- [ ] Production checklist complete
