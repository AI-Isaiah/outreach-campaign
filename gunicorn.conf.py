"""Gunicorn configuration for production ASGI deployment."""

import multiprocessing
import os

# Bind to PORT env var (Railway sets this)
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# Workers
workers = int(os.getenv("WEB_CONCURRENCY", min(4, multiprocessing.cpu_count() * 2 + 1)))
worker_class = "uvicorn.workers.UvicornWorker"

# Don't preload — each worker runs lifespan independently (safe for psycopg2 pool)
preload_app = False

# Timeout — accommodates slow Gmail/DB operations
timeout = 120
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
