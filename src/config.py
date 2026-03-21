"""Shared configuration loader for CLI and web app.

Loads config from ``config.yaml`` (or ``config.yaml.example`` as fallback)
and injects the SMTP password from the ``SMTP_PASSWORD`` environment variable.
"""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SmtpConfig(BaseModel):
    """SMTP connection settings."""
    host: str = "smtp.gmail.com"
    port: int = 587
    username: str = ""


class AppConfig(BaseModel):
    """Top-level application configuration (validated subset of config.yaml)."""
    smtp: SmtpConfig = SmtpConfig()
    from_email: str = ""
    physical_address: str = ""
    calendly_url: str = ""
    smtp_password: str = ""


@functools.lru_cache(maxsize=1)
def load_config() -> dict:
    """Load config from config.yaml or config.yaml.example (cached).

    Also injects the SMTP password from the environment variable
    ``SMTP_PASSWORD`` if it is set.

    Returns:
        The parsed YAML config as a dict.

    Raises:
        FileNotFoundError: if no config file is found.
    """
    config_path = Path("config.yaml")
    if not config_path.exists():
        config_path = Path("config.yaml.example")
    if not config_path.exists():
        raise FileNotFoundError("No config.yaml or config.yaml.example found")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    smtp_password = os.getenv("SMTP_PASSWORD", "")
    if smtp_password:
        config["smtp_password"] = smtp_password

    return config


@functools.lru_cache(maxsize=1)
def load_validated_config() -> AppConfig:
    """Load and validate config through the Pydantic model.

    Falls back gracefully if config file is missing.
    """
    try:
        raw = load_config()
    except FileNotFoundError:
        logger.warning("No config file found — using defaults")
        return AppConfig()
    return AppConfig.model_validate(raw)


DB_PATH = os.getenv("DATABASE_PATH", "outreach.db")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "")

DEFAULT_CAMPAIGN = "Q1_2026_initial"
