# syntax=docker/dockerfile:1
# Build: docker build -t bluebird-backend ./backend

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .

RUN pip install --upgrade pip --quiet \
 && pip install --prefix=/install --quiet -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Non-root user
RUN useradd -r -s /sbin/nologin -u 1001 bluebird

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/

# Persistent data lives in Docker-managed volumes — create mount points.
RUN mkdir -p /app/data /app/secrets /app/logs \
 && chown -R bluebird:bluebird /app

USER bluebird

EXPOSE 8000

# pydantic-settings reads .env from the working directory by default.
# In production the .env file (or individual vars) comes from the compose env_file.
ENTRYPOINT ["uvicorn", "app.main:app", \
            "--host", "0.0.0.0", \
            "--port", "8000", \
            "--workers", "1", \
            "--log-level", "info", \
            "--no-access-log"]
