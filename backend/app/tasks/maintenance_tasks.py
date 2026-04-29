"""
Celery beat maintenance tasks.

These run on the beat schedule defined in app.worker.celery_app.beat_schedule.
Each task is self-contained: it reads settings from the environment and opens
its own DB connections.
"""
from __future__ import annotations

import logging
import os
import subprocess

from celery import shared_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Quiet period expiration / activation
# ---------------------------------------------------------------------------

@shared_task(name="app.tasks.maintenance_tasks.expire_quiet_periods")
def expire_quiet_periods() -> dict:
    """
    Transition scheduled→approved and approved→expired quiet periods across
    all tenant DBs.  Mirrors what the FastAPI app does on each request, but
    runs continuously even when no API traffic is present.
    """
    import asyncio
    from app.core.config import Settings
    from app.services.quiet_period_store import QuietPeriodStore
    import glob

    settings = Settings()
    db_paths = _discover_all_tenant_dbs(settings)
    total_processed = 0

    async def _expire_all():
        nonlocal total_processed
        for db_path in db_paths:
            try:
                store = QuietPeriodStore(db_path)
                await store.expire_old()
                total_processed += 1
            except Exception:
                logger.warning("expire_quiet_periods failed for %s", db_path, exc_info=True)

    asyncio.run(_expire_all())
    logger.debug("expire_quiet_periods: processed %d tenant(s)", total_processed)
    return {"tenants_processed": total_processed}


# ---------------------------------------------------------------------------
# Stale device prune
# ---------------------------------------------------------------------------

@shared_task(name="app.tasks.maintenance_tasks.prune_stale_devices")
def prune_stale_devices() -> dict:
    """
    Log a count of archived device records per tenant.
    Actual archival is done at push time; this task provides visibility.
    """
    import sqlite3
    from app.core.config import Settings

    settings = Settings()
    db_paths = _discover_all_tenant_dbs(settings)
    report = {}

    for db_path in db_paths:
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM registered_devices WHERE is_active = 0 AND archived_at IS NOT NULL;"
                ).fetchone()
                count = row[0] if row else 0
                if count > 0:
                    report[os.path.basename(db_path)] = count
        except Exception:
            pass

    if report:
        logger.info("prune_stale_devices archived_counts=%s", report)
    return {"archived_counts": report}


# ---------------------------------------------------------------------------
# Nightly backup trigger
# ---------------------------------------------------------------------------

@shared_task(name="app.tasks.maintenance_tasks.run_nightly_backup")
def run_nightly_backup() -> dict:
    """
    Trigger the backup.sh script.  Only runs if BLUEBIRD_BACKUP_SCRIPT
    is set in the environment (default: /srv/bluebird/repo/scripts/backup.sh).
    This avoids silently doing nothing if the path is wrong.
    """
    script = os.getenv(
        "BLUEBIRD_BACKUP_SCRIPT",
        "/srv/bluebird/repo/scripts/backup.sh",
    )

    if not os.path.isfile(script):
        logger.warning("run_nightly_backup: script not found at %s — skipping", script)
        return {"status": "skipped", "reason": "script not found"}

    logger.info("run_nightly_backup: starting %s", script)
    try:
        result = subprocess.run(
            ["bash", script],
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes max
        )
        if result.returncode == 0:
            logger.info("run_nightly_backup: success")
            return {"status": "ok", "returncode": 0}
        else:
            logger.error("run_nightly_backup: failed rc=%d stderr=%s", result.returncode, result.stderr[-500:])
            return {"status": "error", "returncode": result.returncode, "stderr": result.stderr[-500:]}
    except subprocess.TimeoutExpired:
        logger.error("run_nightly_backup: timed out after 600s")
        return {"status": "timeout"}
    except Exception as exc:
        logger.error("run_nightly_backup: exception: %s", exc)
        return {"status": "exception", "error": str(exc)}


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _discover_all_tenant_dbs(settings) -> list[str]:
    """Return all tenant DB paths that exist on disk."""
    import glob

    paths = []
    for candidate in [settings.DB_PATH, settings.PLATFORM_DB_PATH]:
        if os.path.isfile(candidate):
            paths.append(candidate)

    data_dir = os.path.dirname(os.path.abspath(settings.DB_PATH))
    schools_dir = os.path.join(data_dir, "schools")
    if os.path.isdir(schools_dir):
        paths.extend(sorted(glob.glob(os.path.join(schools_dir, "*.db"))))

    return paths
