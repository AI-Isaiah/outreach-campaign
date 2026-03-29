"""Structured logging configuration for production and development."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone

# Context variable for per-request ID, set by middleware
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def _get_request_id() -> str | None:
    """Read current request_id from contextvars (set by middleware)."""
    return request_id_var.get(None)


class JSONFormatter(logging.Formatter):
    """Outputs log records as single-line JSON for log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include request_id if set by middleware (via contextvars or record attribute)
        request_id = getattr(record, "request_id", None) or _get_request_id()
        if request_id:
            log_entry["request_id"] = request_id
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging() -> None:
    """Configure logging based on ENVIRONMENT and LOG_LEVEL env vars."""
    environment = os.getenv("ENVIRONMENT", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    root = logging.getLogger()
    root.setLevel(log_level)

    # Clear existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if environment == "production":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
