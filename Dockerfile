# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Install Python dependencies
FROM python:3.12-slim AS python-builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml setup.py* ./
COPY src/ src/
COPY migrations/ migrations/
RUN pip install --no-cache-dir --prefix=/install .

# Stage 3: Production runtime
FROM python:3.12-slim AS runtime
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages
COPY --from=python-builder /install /usr/local

# Copy application code
COPY src/ src/
COPY migrations/ migrations/
COPY gunicorn.conf.py ./
COPY config.yaml.example ./

# Copy frontend build
COPY --from=frontend-builder /app/frontend/dist frontend/dist/

# Non-root user
RUN useradd --create-home appuser
USER appuser

ENV ENVIRONMENT=production
ENV PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["gunicorn", "src.web.app:app", "-c", "gunicorn.conf.py"]
