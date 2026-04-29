"""
Celery push notification tasks.

These run in the background worker process.  They initialize their own
APNs/FCM clients from environment variables — they do NOT depend on the
FastAPI app or the Request context.

Task: send_push_task
  Sends a push to one or more token lists (APNs and/or FCM).
  Retries up to 3 times with exponential backoff on transient errors.
  Archives invalid tokens reported by the push provider.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Push client factories (no FastAPI dependency)
# ---------------------------------------------------------------------------

def _make_apns():
    """Build an APNs client from environment variables."""
    from app.services.apns import APNsClient
    from app.core.config import Settings
    settings = Settings()
    return APNsClient(settings) if settings.apns_is_configured() else None


def _make_fcm():
    """Build an FCM client from environment variables."""
    from app.services.fcm import FCMClient
    from app.core.config import Settings
    settings = Settings()
    return FCMClient(settings) if settings.fcm_is_configured() else None


# ---------------------------------------------------------------------------
# Token archival helper (runs in worker, writes to tenant DB directly)
# ---------------------------------------------------------------------------

def _archive_invalid_token(token: str, push_provider: str, db_path: str) -> None:
    """Mark a device token as archived in the given tenant DB."""
    try:
        with sqlite3.connect(db_path, timeout=10, isolation_level=None) as conn:
            conn.execute(
                """
                UPDATE registered_devices
                SET is_active = 0,
                    archived_at = ?
                WHERE token = ?
                  AND push_provider = ?
                  AND is_active = 1;
                """,
                (datetime.now(timezone.utc).isoformat(), token, push_provider),
            )
        logger.info("push_token_archived provider=%s token=%.12s", push_provider, token)
    except Exception:
        logger.warning("Failed to archive invalid token", exc_info=True)


# ---------------------------------------------------------------------------
# Main push task
# ---------------------------------------------------------------------------

@shared_task(
    name="app.tasks.push_tasks.send_push_task",
    bind=True,
    max_retries=3,
    default_retry_delay=15,  # seconds; Celery doubles on each retry
    acks_late=True,
)
def send_push_task(
    self,
    *,
    apns_tokens: list[str],
    fcm_tokens: list[str],
    message: str,
    title: Optional[str] = None,
    extra_data: Optional[dict[str, Any]] = None,
    # Pass tenant DB path so the worker can archive invalid tokens.
    db_path: Optional[str] = None,
    # Per-tenant non-critical sound preferences (from NotificationSettings).
    non_critical_sound_enabled: bool = True,
    non_critical_sound_name: str = "notification_soft",
) -> dict:
    """
    Send push notifications to the provided token lists.

    Returns a summary dict with counts of sent/failed tokens.
    Retries up to 3 times on transient network failures.
    Invalid tokens reported by the provider are archived immediately.
    """
    import asyncio
    from app.services.push_classification import SoundConfig

    extra = extra_data or {}
    sound_cfg = SoundConfig(
        non_critical_sound_enabled=non_critical_sound_enabled,
        non_critical_sound_name=non_critical_sound_name,
    )
    results: dict[str, Any] = {
        "apns_sent": 0, "apns_failed": 0,
        "fcm_sent": 0, "fcm_failed": 0,
        "tokens_archived": 0,
    }

    logger.info(
        "push_task_start apns=%d fcm=%d title=%r",
        len(apns_tokens), len(fcm_tokens), title or message[:40],
    )

    async def _run() -> None:
        apns = _make_apns()
        fcm = _make_fcm()

        import asyncio as _asyncio
        coros = []

        if apns and apns_tokens:
            if title:
                coros.append(_send_apns_with_data(apns, apns_tokens, title, message, extra, db_path, results, sound_cfg))
            else:
                coros.append(_send_apns_bulk(apns, apns_tokens, message, extra, db_path, results, sound_cfg))

        if fcm and fcm_tokens:
            if title:
                coros.append(_send_fcm_with_data(fcm, fcm_tokens, title, message, extra, db_path, results, sound_cfg))
            else:
                coros.append(_send_fcm_bulk(fcm, fcm_tokens, message, extra, db_path, results, sound_cfg))

        if coros:
            await _asyncio.gather(*coros, return_exceptions=True)

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.warning("push_task_error: %s", exc, exc_info=True)
        try:
            raise self.retry(exc=exc, countdown=self.default_retry_delay * (2 ** self.request.retries))
        except MaxRetriesExceededError:
            logger.error("push_task_max_retries_exceeded: %s", exc)
            results["error"] = str(exc)

    logger.info("push_task_done results=%s", results)
    return results


async def _send_apns_bulk(apns, tokens, message, extra, db_path, results, sound_config=None):
    try:
        send_results = await apns.send_bulk(tokens, message, extra_data=extra, sound_config=sound_config)
        _process_apns_results(send_results, tokens, db_path, results)
    except Exception:
        logger.warning("apns_bulk_error", exc_info=True)
        results["apns_failed"] += len(tokens)


async def _send_apns_with_data(apns, tokens, title, message, extra, db_path, results, sound_config=None):
    try:
        send_results = await apns.send_with_data(tokens, title, message, extra_data=extra, sound_config=sound_config)
        _process_apns_results(send_results, tokens, db_path, results)
    except Exception:
        logger.warning("apns_with_data_error", exc_info=True)
        results["apns_failed"] += len(tokens)


async def _send_fcm_bulk(fcm, tokens, message, extra, db_path, results, sound_config=None):
    try:
        send_results = await fcm.send_bulk(tokens, message, extra_data=extra, sound_config=sound_config)
        _process_fcm_results(send_results, tokens, db_path, results)
    except Exception:
        logger.warning("fcm_bulk_error", exc_info=True)
        results["fcm_failed"] += len(tokens)


async def _send_fcm_with_data(fcm, tokens, title, message, extra, db_path, results, sound_config=None):
    try:
        send_results = await fcm.send_with_data(tokens, title, message, extra_data=extra, sound_config=sound_config)
        _process_fcm_results(send_results, tokens, db_path, results)
    except Exception:
        logger.warning("fcm_with_data_error", exc_info=True)
        results["fcm_failed"] += len(tokens)


def _process_apns_results(send_results, tokens, db_path, results):
    for i, r in enumerate(send_results or []):
        token = tokens[i] if i < len(tokens) else None
        if getattr(r, "success", True):
            results["apns_sent"] += 1
        else:
            results["apns_failed"] += 1
            reason = getattr(r, "reason", "") or ""
            if token and db_path and "BadDeviceToken" in reason:
                _archive_invalid_token(token, "apns", db_path)
                results["tokens_archived"] += 1


def _process_fcm_results(send_results, tokens, db_path, results):
    for i, r in enumerate(send_results or []):
        token = tokens[i] if i < len(tokens) else None
        if getattr(r, "success", True):
            results["fcm_sent"] += 1
        else:
            results["fcm_failed"] += 1
            reason = getattr(r, "error", "") or ""
            if token and db_path and reason in {"UNREGISTERED", "INVALID_ARGUMENT"}:
                _archive_invalid_token(token, "fcm", db_path)
                results["tokens_archived"] += 1
