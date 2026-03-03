"""FastAPI application for the outreach campaign web dashboard."""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from src.web.routes import (  # noqa: E402
    campaigns,
    contacts,
    crm,
    gmail,
    import_routes,
    insights,
    queue,
    replies,
    settings,
    stats,
    templates,
)

app = FastAPI(
    title="Outreach Campaign Dashboard",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(queue.router, prefix="/api")
app.include_router(campaigns.router, prefix="/api")
app.include_router(contacts.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(gmail.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(replies.router, prefix="/api")
app.include_router(crm.router, prefix="/api")
app.include_router(import_routes.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(insights.router, prefix="/api")


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
