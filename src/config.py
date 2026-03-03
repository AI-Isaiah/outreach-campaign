"""Shared configuration loader for CLI and web app.

Loads config from ``config.yaml`` (or ``config.yaml.example`` as fallback)
and injects the SMTP password from the ``SMTP_PASSWORD`` environment variable.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def load_config() -> dict:
    """Load config from config.yaml or config.yaml.example.

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


DB_PATH = os.getenv("DATABASE_PATH", "outreach.db")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "")
