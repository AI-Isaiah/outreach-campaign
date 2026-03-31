"""Shared Pydantic response models for OpenAPI schema generation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

class CampaignSummary(BaseModel):
    """Campaign with embedded metrics (returned by GET /campaigns)."""
    id: int
    name: str
    description: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    contacts_count: int = 0
    replied_count: int = 0
    reply_rate: float = 0
    calls_booked: int = 0
    progress_pct: float = 0
    positive_count: int = 0
    bounced_count: int = 0
    emails_sent: int = 0
    health_score: float = 0

    class Config:
        extra = "allow"


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

class ContactRow(BaseModel):
    """Single contact row (used inside paginated list)."""
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    email_normalized: Optional[str] = None
    linkedin_url: Optional[str] = None
    title: Optional[str] = None
    company_name: Optional[str] = None
    aum_millions: Optional[float] = None
    lifecycle_stage: Optional[str] = None
    email_status: Optional[str] = None

    class Config:
        extra = "allow"


class PaginatedContactsResponse(BaseModel):
    """Paginated contacts list (returned by GET /contacts)."""
    contacts: list[dict[str, Any]]
    total: int
    page: int
    per_page: int
    pages: int


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

class QueueItem(BaseModel):
    """Single queue item with rendered message."""
    contact_id: int
    contact_name: Optional[str] = None
    company_name: Optional[str] = None
    channel: Optional[str] = None
    step_order: Optional[int] = None
    template_name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None

    class Config:
        extra = "allow"


class QueueResponse(BaseModel):
    """Queue response for a single campaign (GET /queue/{campaign})."""
    items: list[dict[str, Any]]
    total: int
    campaign: Optional[str] = None
    date: Optional[str] = None

    class Config:
        extra = "allow"


class CrossCampaignQueueResponse(BaseModel):
    """Cross-campaign queue response (GET /queue/all)."""
    items: list[dict[str, Any]]
    total: int
