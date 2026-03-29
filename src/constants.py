"""Shared numeric/string constants extracted from service modules."""

from __future__ import annotations

# Deduplication
FUZZY_DEDUP_THRESHOLD = 85

# GDPR compliance email limits
GDPR_MAX_EMAILS = 2
NON_GDPR_MAX_EMAILS = 3

# Email verification
ZEROBOUNCE_CHUNK_SIZE = 100

# Query limits
MAX_CONTACTS_PER_PAGE = 200
MAX_EVENTS_PER_QUERY = 500
MAX_QUEUE_ITEMS = 50
MAX_TAGS_PER_QUERY = 500

# SMTP
SMTP_RETRY_COUNT = 3
SMTP_RETRY_DELAY = 1  # seconds
SMTP_TIMEOUT = 30  # seconds

# Timeouts (seconds) for external API calls
LLM_API_TIMEOUT = 60  # Anthropic, Perplexity
LLM_API_TIMEOUT_SHORT = 8  # fast single-message generation
LLM_SEQUENCE_TIMEOUT = 30  # multi-step sequence generation

# Search / CRM
CRM_SEARCH_LIMIT = 10
RESPONSE_NOTES_LIMIT = 100
NEWSLETTER_SUBSCRIBER_LIMIT = 5000

# LLM model identifiers — single source of truth for all AI calls
LLM_MODELS = {
    "deep_research": "claude-sonnet-4-20250514",
    "message_drafter": "claude-haiku-4-5-20251001",
    "classification": "claude-haiku-4-5-20251001",
    "default_anthropic": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-20250514",
    "opus": "claude-opus-4-20250514",
}
