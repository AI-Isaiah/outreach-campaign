"""FastAPI application for the outreach campaign web dashboard."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from src.web.logging_config import setup_logging

setup_logging()

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

load_dotenv()

# Initialize Sentry if DSN is configured
_sentry_dsn = os.getenv("SENTRY_DSN")
if _sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=_sentry_dsn,
        send_default_pii=False,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        environment=os.getenv("ENVIRONMENT", "development"),
    )

from src.config import SUPABASE_DB_URL  # noqa: E402
from src.models.database import close_pool, get_connection, get_cursor, init_pool, run_migrations  # noqa: E402
from src.web.dependencies import require_auth  # noqa: E402
from src.web.routes import (  # noqa: E402
    auth,
    campaigns,
    contacts,
    conversations,
    crm,
    deals,
    deep_research,
    drafts,
    gmail,
    gmail_oauth,
    import_routes,
    inbox,
    insights,
    newsletters,
    products,
    queue,
    replies,
    research,
    sequence_generator,
    settings,
    smart_import,
    stats,
    tags,
    templates,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run migrations at startup, initialize connection pool, cleanup on shutdown.

    In serverless mode (Vercel), lifespan is disabled via Mangum(lifespan="off").
    Migrations are run via Supabase SQL Editor or the /api/admin/migrate endpoint.
    Connections are created per-request in get_db() when the pool is not initialized.
    """
    if SUPABASE_DB_URL:
        try:
            conn = get_connection(SUPABASE_DB_URL)
            try:
                run_migrations(conn)
                logger.info("Database migrations completed")

                # Recover deep_research records stuck from a previous crash
                with get_cursor(conn) as cur:
                    cur.execute(
                        """UPDATE deep_research
                           SET status = 'failed',
                               error_message = 'Process restarted during research',
                               updated_at = NOW()
                           WHERE status IN ('researching', 'synthesizing')"""
                    )
                    stuck = cur.rowcount
                conn.commit()
                if stuck:
                    logger.warning("Recovered %d stuck deep_research records", stuck)
            finally:
                conn.close()
            init_pool(SUPABASE_DB_URL)
            logger.info("Connection pool initialized")
        except Exception as e:
            logger.warning("Could not connect to database at startup: %s", e)
    yield
    close_pool()


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
    enabled=os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false",
)

app = FastAPI(
    title="Outreach Campaign Dashboard",
    version="2.0.0",
    dependencies=[],  # Auth applied per-router below
    lifespan=lifespan,
)

from src.web.errors import AppError, app_error_handler  # noqa: E402

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(AppError, app_error_handler)

_default_origins = "http://localhost:5173,http://127.0.0.1:5173"
_allowed_origins = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)

# Health endpoint — no auth required
@app.get("/api/health")
def health_check():
    from src.models.database import is_pool_initialized, get_pool_connection, put_pool_connection, get_cursor

    if not is_pool_initialized():
        return {"status": "ok", "database": "no_pool"}

    db_ok = False
    try:
        conn = get_pool_connection()
        try:
            with get_cursor(conn) as cursor:
                cursor.execute("SELECT 1")
                db_ok = True
        finally:
            put_pool_connection(conn)
    except Exception:
        pass
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


# Auth routers — no global auth dependency (they handle auth internally)
app.include_router(auth.router, prefix="/api")
app.include_router(gmail_oauth.router, prefix="/api")
app.include_router(replies.cron_router, prefix="/api")

# All other routers — auth required
_auth_deps = [Depends(require_auth)]

app.include_router(queue.router, prefix="/api", dependencies=_auth_deps)
app.include_router(campaigns.router, prefix="/api", dependencies=_auth_deps)
app.include_router(drafts.router, prefix="/api", dependencies=_auth_deps)
app.include_router(contacts.router, prefix="/api", dependencies=_auth_deps)
app.include_router(stats.router, prefix="/api", dependencies=_auth_deps)
app.include_router(gmail.router, prefix="/api", dependencies=_auth_deps)
app.include_router(templates.router, prefix="/api", dependencies=_auth_deps)
app.include_router(replies.router, prefix="/api", dependencies=_auth_deps)
app.include_router(crm.router, prefix="/api", dependencies=_auth_deps)
app.include_router(import_routes.router, prefix="/api", dependencies=_auth_deps)
app.include_router(settings.router, prefix="/api", dependencies=_auth_deps)
app.include_router(insights.router, prefix="/api", dependencies=_auth_deps)
app.include_router(deals.router, prefix="/api", dependencies=_auth_deps)
app.include_router(tags.router, prefix="/api", dependencies=_auth_deps)
app.include_router(inbox.router, prefix="/api", dependencies=_auth_deps)
app.include_router(conversations.router, prefix="/api", dependencies=_auth_deps)
app.include_router(products.router, prefix="/api", dependencies=_auth_deps)
app.include_router(newsletters.router, prefix="/api", dependencies=_auth_deps)
app.include_router(research.router, prefix="/api", dependencies=_auth_deps)
app.include_router(deep_research.router, prefix="/api", dependencies=_auth_deps)
app.include_router(sequence_generator.router, prefix="/api", dependencies=_auth_deps)
app.include_router(smart_import.router, prefix="/api", dependencies=_auth_deps)

# --- Static file serving (production: frontend/dist baked into image) ---
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    _assets_dir = _frontend_dist / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="static-assets")

    _index_html = _frontend_dist / "index.html"

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """Serve frontend SPA — catch-all after API routes."""
        # Serve actual static files if they exist
        file_path = _frontend_dist / full_path
        if full_path and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_index_html))
