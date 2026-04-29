"""
Celery application definition for BlueBird Alerts.

Usage:
  celery -A app.worker.celery_app worker --loglevel=INFO --concurrency=2
  celery -A app.worker.celery_app beat   --loglevel=INFO --schedule=/app/data/celerybeat-schedule

The broker and backend both use Redis (REDIS_URL env var).
Import this module only when Celery is active — it is NOT imported by
app.main, so the FastAPI app has zero Celery overhead when the queue is
disabled.
"""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "bluebird",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.tasks.push_tasks",
        "app.tasks.maintenance_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Prevent tasks from blocking the broker for too long.
    task_soft_time_limit=60,
    task_time_limit=120,
    # Retry policy defaults — individual tasks may override.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Beat schedule (activated when ENABLE_CELERY_BEAT=true).
    beat_schedule={
        # Expire and activate scheduled quiet periods every 60 seconds.
        "expire-quiet-periods": {
            "task": "app.tasks.maintenance_tasks.expire_quiet_periods",
            "schedule": 60.0,
        },
        # Nightly backup at 2:05 AM UTC (offset from cron job to avoid collision).
        "nightly-backup": {
            "task": "app.tasks.maintenance_tasks.run_nightly_backup",
            "schedule": crontab(hour=2, minute=5),
        },
        # Prune stale device records once a day at 3:00 AM UTC.
        "prune-stale-devices": {
            "task": "app.tasks.maintenance_tasks.prune_stale_devices",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
