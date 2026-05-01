from __future__ import annotations

import asyncio
import base64
import io
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import logging
import re

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import router
from app.core.config import Settings
from app.core.logging import configure_logging
from app.services.apns import APNsClient
from app.services.access_code_service import AccessCodeService
from app.services.email_service import EmailService, TEMPLATES
from app.services.health_monitor import HealthMonitor
from app.services.tenant_billing_store import TenantBillingStore
from app.services.cloudflare_dns import CloudflareDNSClient
from app.services.fcm import FCMClient
from app.services.alert_hub import AlertHub
from app.services.platform_admin_store import PlatformAdminStore
from app.services.quiet_state_store import QuietStateStore
from app.services.school_registry import SchoolRegistry
from app.services.tenant_manager import TenantManager
from app.services.demo_live_engine import DemoLiveEngine
from app.services.ai_insights import AiInsightsStore, AI_INSIGHTS_GLOBAL_ENABLED
from app.services.push_queue import PushQueue
from app.services.twilio_sms import TwilioSMSClient
from app.services.user_tenant_store import UserTenantStore
from app.services.inquiry_store import InquiryStore
from app.services.inbox_sync import InboxSyncService
from app.services.customer_store import CustomerStore
from app.services.demo_request_store import DemoRequestStore
from app.services.training_store import TrainingStore

import anyio


settings = Settings()
logger = logging.getLogger("bluebird.main")
_TENANT_CLEAN_RE = re.compile(r"[^a-z0-9-]+")


async def _health_check_loop(app: FastAPI, interval: int) -> None:
    """
    Background heartbeat loop — runs health checks every `interval` seconds.
    Completely read-only: never writes to alert tables or triggers notifications.

    Runs the first check immediately on startup (no leading sleep), then waits
    `interval` seconds between subsequent checks.  Crashes are caught, logged,
    and retried after a short back-off so a transient error never silences the
    monitor permanently.
    """
    _RETRY_DELAY = 5  # seconds before retrying after an unexpected error
    logger.info("Health check loop starting (interval=%ds)", interval)
    while True:
        try:
            health_monitor: HealthMonitor = app.state.health_monitor
            email_service: EmailService = app.state.email_service
            checks = await HealthMonitor.run_checks(app.state)
            await health_monitor.record_heartbeat(
                status=str(checks["status"]),
                response_time_ms=float(checks["response_time_ms"]),
                db_ok=bool(checks["db_ok"]),
                ws_connections=int(checks["ws_connections"]),
                apns_configured=bool(checks["apns_configured"]),
                fcm_configured=bool(checks["fcm_configured"]),
                error_note=str(checks["error_note"]) if checks.get("error_note") else None,
            )
            logger.debug(
                "Heartbeat recorded: status=%s rt=%.1fms ws=%d db=%s",
                checks["status"], checks["response_time_ms"],
                checks["ws_connections"], checks["db_ok"],
            )
            # Automated email on degradation/error (respects cooldown)
            if checks["status"] in ("error", "degraded") and email_service.is_configured():
                if email_service.check_cooldown("health_auto", app.state.settings.HEALTH_EMAIL_COOLDOWN_MINUTES):
                    admins = app.state.settings.platform_admin_email_list
                    if admins:
                        tmpl = TEMPLATES["outage_alert"]
                        note = checks.get("error_note") or "unknown"
                        body = f"{tmpl['body']}\n\nError details: {note}"
                        await email_service.send_to_addresses(
                            admins,
                            subject=tmpl["subject"],
                            body=body,
                            event_type="health_auto",
                        )
                        logger.warning("Health auto-email sent to %d admin(s): status=%s", len(admins), checks["status"])
        except asyncio.CancelledError:
            logger.info("Health check loop cancelled")
            return
        except Exception as exc:
            logger.warning("Health check loop error (will retry in %ds): %s", _RETRY_DELAY, exc, exc_info=True)
            try:
                await asyncio.sleep(_RETRY_DELAY)
            except asyncio.CancelledError:
                logger.info("Health check loop cancelled during retry back-off")
                return
            continue  # skip the normal interval sleep; retry immediately

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Health check loop cancelled during sleep")
            return


async def _health_watchdog(app: FastAPI, interval: int) -> None:
    """
    Monitors the health check task and restarts it if it exits unexpectedly.
    Checks every `interval` seconds (same cadence as the health loop).
    """
    _CHECK_INTERVAL = max(interval, 30)
    logger.debug("Health watchdog started (check interval=%ds)", _CHECK_INTERVAL)
    while True:
        try:
            await asyncio.sleep(_CHECK_INTERVAL)
        except asyncio.CancelledError:
            return
        try:
            task: asyncio.Task = app.state.health_task  # type: ignore[attr-defined]
            if task.done():
                exc = None
                try:
                    exc = task.exception()
                except (asyncio.CancelledError, asyncio.InvalidStateError):
                    pass
                if not task.cancelled():
                    logger.warning(
                        "Health check task exited unexpectedly (exc=%s) — restarting", exc
                    )
                    new_task = asyncio.create_task(_health_check_loop(app, interval))
                    app.state.health_task = new_task  # type: ignore[attr-defined]
        except asyncio.CancelledError:
            return
        except Exception as exc2:
            logger.debug("Health watchdog check error: %s", exc2)


async def _quiet_period_expiry_loop(app: FastAPI, interval: float = 45.0) -> None:
    """
    Background loop that expires approved quiet periods whose expires_at has passed.
    Emits a WebSocket event and audit log entry for each expired record.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            tenant_manager: TenantManager = app.state.tenant_manager
            alert_hub: AlertHub = app.state.alert_hub
            for tenant in list(tenant_manager._cache.values()):
                try:
                    expired = await tenant.quiet_period_store.expire_and_return()
                    for record in expired:
                        try:
                            await tenant.audit_log_service.log_event(
                                tenant_slug=tenant.slug,
                                event_type="quiet_period_expired",
                                actor_label="system",
                                target_type="quiet_period_request",
                                target_id=str(record.id),
                                metadata={"user_id": record.user_id},
                            )
                        except Exception:
                            logger.debug("qp_expiry audit log failed tenant=%s", tenant.slug)
                        try:
                            await alert_hub.publish(tenant.slug, {
                                "event": "quiet_period_expired",
                                "tenant_slug": tenant.slug,
                                "request_id": record.id,
                                "user_id": record.user_id,
                                "event_id": f"qpe_{record.id}",
                            })
                        except Exception:
                            logger.debug("qp_expiry ws publish failed tenant=%s", tenant.slug)
                except Exception:
                    logger.debug("qp_expiry error tenant=%s", tenant.slug, exc_info=True)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("qp_expiry loop error: %s", exc)


async def _wal_checkpoint_loop(app: FastAPI, interval: float = 300.0) -> None:
    """
    Periodically checkpoint all tenant WAL files to prevent unbounded growth.
    SQLite WAL files accumulate until a checkpoint is issued; on a busy server
    that never checkpoints, reads slow down as the WAL grows.  PASSIVE mode
    never blocks writers and is safe to call from any thread.
    """
    import sqlite3 as _sqlite3

    while True:
        await asyncio.sleep(interval)
        try:
            tenant_manager: TenantManager = app.state.tenant_manager
            for tenant in list(tenant_manager._cache.values()):
                try:
                    db_path = getattr(tenant.user_store, "_db_path", None)
                    if db_path:
                        await asyncio.to_thread(
                            lambda p=db_path: _sqlite3.connect(p, timeout=5, isolation_level=None)
                            .execute("PRAGMA wal_checkpoint(PASSIVE);")
                            .close()
                        )
                except Exception:
                    pass
            # Also checkpoint the platform DB.
            platform_db = getattr(app.state.settings, "PLATFORM_DB_PATH", None)
            if platform_db:
                await asyncio.to_thread(
                    lambda p=platform_db: _sqlite3.connect(p, timeout=5, isolation_level=None)
                    .execute("PRAGMA wal_checkpoint(PASSIVE);")
                    .close()
                )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("wal_checkpoint loop error: %s", exc)


def _normalize_tenant_candidate(value: str) -> str:
    return _TENANT_CLEAN_RE.sub("-", value.strip().lower()).strip("-")


async def _ack_reminder_loop(app: FastAPI, interval: float = 180.0) -> None:
    """
    Background loop: sends push reminders to active users who have not yet
    acknowledged an in-progress alarm.

    Rules:
    - Runs every `interval` seconds (default 3 min).
    - Minimum 3 minutes between reminders per user (in-memory throttle).
    - Skips test, simulation, and inactive tenants.
    - Stops sending as soon as user acknowledges or alarm is cleared.
    - Best-effort: send failures are logged at DEBUG and skipped.
    """
    _last_sent: dict = {}  # {(tenant_slug, user_id): datetime}
    _MIN_GAP = timedelta(minutes=3)

    while True:
        await asyncio.sleep(interval)
        try:
            school_registry: SchoolRegistry = app.state.school_registry
            tenant_manager: TenantManager = app.state.tenant_manager
            apns_client = app.state.apns_client
            fcm_client = app.state.fcm_client
            now = datetime.now(timezone.utc)

            schools = await school_registry.list_schools()
            for school in schools:
                if (school.is_test or getattr(school, "simulation_mode_enabled", False)
                        or getattr(school, "is_archived", False) or not school.is_active):
                    continue
                tenant = tenant_manager.get(school)
                if tenant is None:
                    continue
                try:
                    alarm_state = await tenant.alarm_store.get_state()
                    if not alarm_state.is_active:
                        continue
                    latest_alert = await tenant.alert_log.latest_alert()
                    if latest_alert is None:
                        continue
                    alert_id = latest_alert.id
                    alert_type = (alarm_state.message or "").split()[0].upper() or "ALERT"

                    acked_ids = await tenant.alert_log.list_acknowledged_user_ids(alert_id)
                    all_users = await tenant.user_store.list_users()
                    unacked = [
                        u for u in all_users
                        if u.is_active
                        and not getattr(u, "is_archived", False)
                        and u.id not in acked_ids
                    ]
                    if not unacked:
                        continue

                    devices = await tenant.device_registry.list_devices()
                    apns_by_user: dict = {}
                    fcm_by_user: dict = {}
                    for d in devices:
                        if d.user_id is None:
                            continue
                        if d.push_provider == "apns":
                            apns_by_user.setdefault(d.user_id, []).append(d.token)
                        elif d.push_provider == "fcm":
                            fcm_by_user.setdefault(d.user_id, []).append(d.token)

                    reminder_msg = f"Reminder: Please acknowledge the active {alert_type} alert."
                    slug = str(school.slug)

                    for user in unacked:
                        key = (slug, user.id)
                        last = _last_sent.get(key)
                        if last and (now - last) < _MIN_GAP:
                            continue
                        user_apns = apns_by_user.get(user.id, [])
                        user_fcm = fcm_by_user.get(user.id, [])
                        if not user_apns and not user_fcm:
                            continue
                        try:
                            if user_apns:
                                await apns_client.send_bulk(user_apns, reminder_msg)
                            if user_fcm:
                                await fcm_client.send_bulk(user_fcm, reminder_msg)
                            _last_sent[key] = now
                            logger.info(
                                "ack_reminder sent tenant=%s user_id=%s alert_id=%s",
                                slug, user.id, alert_id,
                            )
                        except Exception:
                            logger.debug("ack_reminder send failed user_id=%s", user.id, exc_info=True)
                except Exception:
                    logger.debug("ack_reminder error school=%s", school.slug, exc_info=True)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("ack_reminder loop error: %s", exc)


async def _auto_archive_loop(app: FastAPI, interval_hours: float = 6.0) -> None:
    """
    Background loop: auto-archives revoked codes for tenants that have the
    auto_archive_enabled setting turned on.  Runs every interval_hours.
    """
    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            school_registry: SchoolRegistry = app.state.school_registry
            access_code_service: AccessCodeService = app.state.access_code_service
            schools = await school_registry.list_schools()
            total = 0
            for school in schools:
                if school.is_test or school.simulation_mode_enabled or school.is_archived or not school.is_active:
                    continue
                try:
                    count = await access_code_service.auto_archive_if_enabled(school.slug)
                    total += count
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug("auto_archive error tenant=%s: %s", school.slug, exc)
            if total:
                logger.info("Auto-archive: archived %d revoked code(s)", total)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("auto_archive loop error: %s", exc)


async def _auto_reminder_loop(app: FastAPI, interval_hours: float = 24.0) -> None:
    """
    Background loop: sends automated reminder emails for unclaimed access codes.

    Rules:
    - Skips test, simulation, and archived tenants.
    - Each code receives at most 3 auto-reminders.
    - Minimum 3 days between reminders per code.
    - Only runs when SMTP is configured.
    - Initial sleep equals the interval so it doesn't fire immediately on startup.
    """
    _MAX_REMINDERS = 3
    _MIN_INTERVAL_DAYS = 3

    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            school_registry: SchoolRegistry = app.state.school_registry
            access_code_service: AccessCodeService = app.state.access_code_service
            email_service: EmailService = app.state.email_service

            if not email_service.is_configured():
                continue

            schools = await school_registry.list_schools()
            now = datetime.now(timezone.utc)
            cutoff_iso = (now - timedelta(days=_MIN_INTERVAL_DAYS)).isoformat()

            total_sent = total_skipped = total_failed = 0
            for school in schools:
                if school.is_test or school.simulation_mode_enabled or school.is_archived or not school.is_active:
                    continue
                try:
                    unclaimed = await access_code_service.list_unclaimed_with_email(school.slug)
                    for rec in unclaimed:
                        if rec.reminder_count >= _MAX_REMINDERS:
                            total_skipped += 1
                            continue
                        if rec.last_reminder_sent_at and rec.last_reminder_sent_at >= cutoff_iso:
                            total_skipped += 1
                            continue
                        email = (rec.assigned_email or "").strip()
                        if not email:
                            total_skipped += 1
                            continue

                        try:
                            import qrcode as _qrcode  # already a project dependency
                            payload_json = AccessCodeService.qr_payload(rec.code, rec.tenant_slug)

                            def _make_qr(p: str = payload_json) -> bytes:
                                qr = _qrcode.QRCode(
                                    version=None,
                                    error_correction=_qrcode.constants.ERROR_CORRECT_M,
                                    box_size=10,
                                    border=4,
                                )
                                qr.add_data(p)
                                qr.make(fit=True)
                                img = qr.make_image(fill_color="black", back_color="white")
                                buf = io.BytesIO()
                                img.save(buf, format="PNG")
                                return buf.getvalue()

                            qr_bytes = await asyncio.to_thread(_make_qr)
                            qr_b64 = base64.b64encode(qr_bytes).decode("ascii")
                        except Exception:
                            qr_b64 = ""

                        greeting = f"Hi {rec.assigned_name}," if rec.assigned_name else "Hello,"
                        exp_line = f" &nbsp;·&nbsp; Expires: {rec.expires_at[:10]}" if rec.expires_at else ""
                        exp_text = f"\nExpires: {rec.expires_at[:10]}" if rec.expires_at else ""
                        reminder_num = rec.reminder_count + 1
                        subject = f"[Reminder #{reminder_num}] Your BlueBird Alerts invitation — {school.name}"
                        body_text = (
                            f"{greeting}\n\n"
                            f"This is reminder #{reminder_num} that you have an unclaimed invitation "
                            f"to join BlueBird Alerts at {school.name}.\n\n"
                            f"Your access code: {rec.code}\n"
                            f"Role: {rec.role}{exp_text}\n\n"
                            "To get started:\n"
                            "1. Download the BlueBird Alerts app from the App Store or Google Play.\n"
                            "2. Open the app and tap 'Join with Access Code'.\n"
                            "3. Enter your code or scan the QR code.\n\n"
                            "— BlueBird Alerts"
                        )
                        qr_img_tag = (
                            f'<div style="text-align:center;margin:24px 0;">'
                            f'<img src="data:image/png;base64,{qr_b64}" alt="QR Code" width="200" height="200"'
                            f' style="image-rendering:pixelated;border:1px solid #e5e7eb;border-radius:8px;padding:8px;" />'
                            f"</div>"
                        ) if qr_b64 else ""
                        body_html = (
                            "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"/></head>"
                            "<body style=\"font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;"
                            "background:#f9fafb;padding:32px 0;margin:0;\">"
                            "<div style=\"max-width:520px;margin:0 auto;background:#fff;border-radius:12px;"
                            "overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08);\">"
                            "<div style=\"background:#1a56db;padding:24px 32px;\">"
                            "<p style=\"margin:0;color:#fff;font-size:1.3rem;font-weight:700;\">BlueBird Alerts</p>"
                            f"<p style=\"margin:4px 0 0;color:#bfdbfe;font-size:0.9rem;\">Reminder #{reminder_num} — Staff Onboarding Invitation</p>"
                            "</div>"
                            "<div style=\"padding:28px 32px;\">"
                            f"<p style=\"margin:0 0 16px;\">{greeting}</p>"
                            f"<p style=\"margin:0 0 16px;\">This is reminder #{reminder_num} that your invitation to join "
                            f"<strong>{school.name}</strong> on BlueBird Alerts has not been claimed yet.</p>"
                            f"{qr_img_tag}"
                            "<div style=\"background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;"
                            "padding:16px 20px;text-align:center;margin-bottom:20px;\">"
                            "<p style=\"margin:0 0 4px;font-size:0.8rem;color:#6b7280;\">Your Access Code</p>"
                            f"<p style=\"margin:0;font-size:2rem;font-weight:700;letter-spacing:.12em;"
                            f"color:#1a56db;font-family:monospace;\">{rec.code}</p>"
                            f"<p style=\"margin:4px 0 0;font-size:0.8rem;color:#6b7280;\">Role: {rec.role}{exp_line}</p>"
                            "</div>"
                            "<p style=\"margin:0 0 8px;font-weight:600;\">How to get started:</p>"
                            "<ol style=\"margin:0 0 20px;padding-left:20px;line-height:1.8;\">"
                            "<li>Download <strong>BlueBird Alerts</strong> from the App Store or Google Play.</li>"
                            "<li>Open the app and tap <strong>Join with Access Code</strong>.</li>"
                            "<li>Scan the QR code above or enter your code manually.</li>"
                            "<li>Complete your profile — you&rsquo;re done!</li>"
                            "</ol>"
                            "<p style=\"margin:0;font-size:0.8rem;color:#9ca3af;\">This reminder was sent automatically. "
                            "If you have already joined or do not recognize this invitation, please ignore it.</p>"
                            "</div></div></body></html>"
                        )

                        ok = await email_service.send_html_email(
                            to_address=email,
                            subject=subject,
                            body_text=body_text,
                            body_html=body_html,
                            event_type="access_code_auto_reminder",
                        )
                        if ok:
                            await access_code_service.increment_reminder_count(rec.id, rec.tenant_slug)
                            total_sent += 1
                        else:
                            total_failed += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("auto_reminder error tenant=%s: %s", school.slug, exc)

            if total_sent or total_failed:
                logger.info(
                    "Auto reminders: sent=%d skipped=%d failed=%d",
                    total_sent, total_skipped, total_failed,
                )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("auto_reminder loop error: %s", exc)


async def _inbox_sync_loop(app: FastAPI, interval: float = 180.0) -> None:
    """
    Background loop: syncs unread IMAP messages into the email_messages table.
    Completely isolated from emergency alert tables. Runs every `interval` seconds.
    First sync fires immediately on startup.
    """
    while True:
        try:
            inbox_sync_service: InboxSyncService = app.state.inbox_sync_service
            new_count = await inbox_sync_service.sync_inbox()
            if new_count:
                logger.info("InboxSync: stored %d new message(s)", new_count)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("InboxSync loop error: %s", exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return


async def _ai_insights_loop(app: FastAPI, interval: float = 600.0) -> None:
    """
    Background loop: runs AI analysis on enabled tenants using Ollama/llama3.
    Metrics history is recorded on every run (even when insights are filtered out)
    to drive trend detection. Checks every 10 minutes.
    """
    from app.services.ai_insights import (
        AI_INSIGHTS_GLOBAL_ENABLED,
        AiInsightsStore,
        _check_ollama_available,
        run_tenant_analysis,
        compute_device_status_offline_pct,
    )

    if not AI_INSIGHTS_GLOBAL_ENABLED:
        logger.debug("AI Insights: global toggle is off, loop not starting")
        return

    while True:
        await asyncio.sleep(interval)
        try:
            school_registry: SchoolRegistry = app.state.school_registry
            tenant_manager: TenantManager = app.state.tenant_manager
            ai_store: AiInsightsStore = app.state.ai_insights_store

            available, reason = await anyio.to_thread.run_sync(_check_ollama_available)
            if not available:
                logger.debug("AI Insights: Ollama unavailable — %s", reason)
                continue

            schools = await school_registry.list_schools()
            for school in schools:
                if school.is_test or getattr(school, "simulation_mode_enabled", False) \
                        or getattr(school, "is_archived", False) or not school.is_active:
                    continue
                tenant = tenant_manager.get(school)
                if tenant is None:
                    continue
                try:
                    effective = await tenant.settings_store.get_effective_settings()
                    if not effective.ai_insights.enabled:
                        continue
                    debug_mode = effective.ai_insights.debug_mode

                    # Collect aggregate stats — counts/rates only, no raw data or PII
                    stats: dict = {}
                    try:
                        stats["active_users"] = await tenant.user_store.count_active()
                    except Exception:
                        stats["active_users"] = 0
                    try:
                        devices = await tenant.device_registry.list_devices()
                        stats["device_count"] = len(devices)
                        stats["offline_pct"] = compute_device_status_offline_pct(devices)
                    except Exception:
                        stats["device_count"] = 0
                        stats["offline_pct"] = 0.0
                    try:
                        recent_alerts = await tenant.alert_log.list_recent(limit=100)
                        stats["alert_count"] = len(recent_alerts)
                    except Exception:
                        stats["alert_count"] = 0
                    stats["drill_count"] = 0
                    stats["quiet_period_count"] = 0
                    stats["ack_rate_pct"] = 0
                    stats["push_failure_rate"] = 0.0
                    stats["avg_response_time"] = 0.0

                    await run_tenant_analysis(
                        school.slug, stats, ai_store, debug_mode=debug_mode
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug("AI Insights error tenant=%s: %s", school.slug, exc)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("AI insights loop error: %s", exc)


async def _ai_weekly_report_loop(app: FastAPI, check_interval: float = 21600.0) -> None:
    """
    Background loop: generates weekly AI reports. Checks every 6 hours.
    Uses the UNIQUE index on (tenant_slug, week_start) to ensure at-most-one
    report per tenant per week regardless of restarts.
    """
    from app.services.ai_insights import (
        AI_INSIGHTS_GLOBAL_ENABLED,
        AiInsightsStore,
        _check_ollama_available,
        generate_weekly_report,
    )

    if not AI_INSIGHTS_GLOBAL_ENABLED:
        return

    while True:
        await asyncio.sleep(check_interval)
        try:
            school_registry: SchoolRegistry = app.state.school_registry
            tenant_manager: TenantManager = app.state.tenant_manager
            ai_store: AiInsightsStore = app.state.ai_insights_store

            available, reason = await anyio.to_thread.run_sync(_check_ollama_available)
            if not available:
                logger.debug("AI Weekly: Ollama unavailable — %s", reason)
                continue

            now = datetime.now(timezone.utc)
            # ISO week starts on Monday
            week_start_dt = now - timedelta(days=now.weekday())
            week_start = week_start_dt.strftime("%Y-%m-%d")

            schools = await school_registry.list_schools()
            for school in schools:
                if school.is_test or getattr(school, "simulation_mode_enabled", False) \
                        or getattr(school, "is_archived", False) or not school.is_active:
                    continue
                tenant = tenant_manager.get(school)
                if tenant is None:
                    continue
                try:
                    effective = await tenant.settings_store.get_effective_settings()
                    if not effective.ai_insights.enabled:
                        continue
                    already_done = await ai_store.week_report_exists(school.slug, week_start)
                    if already_done:
                        continue
                    await generate_weekly_report(school.slug, week_start, ai_store)
                    logger.info("AI Weekly report generated: tenant=%s week=%s", school.slug, week_start)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug("AI Weekly error tenant=%s: %s", school.slug, exc)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("AI weekly report loop error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.started_at = datetime.now(timezone.utc)

    # Load environment/config first so logging uses the intended level.
    configure_logging(settings.LOG_LEVEL)

    apns_client = APNsClient(settings)
    await apns_client.start()
    cloudflare_dns = CloudflareDNSClient(settings)
    await cloudflare_dns.start()
    fcm_client = FCMClient(settings)
    await fcm_client.start()
    twilio_sms = TwilioSMSClient(settings)
    await twilio_sms.start()
    platform_admin_store = PlatformAdminStore(settings.PLATFORM_DB_PATH)
    tenant_billing_store = TenantBillingStore(settings.PLATFORM_DB_PATH)
    quiet_state_store = QuietStateStore(settings.PLATFORM_DB_PATH)
    await platform_admin_store.ensure_bootstrap(
        login_name=settings.SUPERADMIN_USERNAME,
        password=settings.SUPERADMIN_PASSWORD,
    )
    school_registry = SchoolRegistry(settings.PLATFORM_DB_PATH)
    user_tenant_store = UserTenantStore(settings.PLATFORM_DB_PATH)
    await school_registry.ensure_school(
        slug=settings.DEFAULT_SCHOOL_SLUG,
        name=settings.DEFAULT_SCHOOL_NAME,
    )
    # Backward-compat alias: "default" was the original slug before the NEN rename.
    # This allows old API clients, mobile apps, and audit history to keep resolving.
    await school_registry.register_alias(
        "default",
        settings.DEFAULT_SCHOOL_SLUG,
        reason="tenant_slug_migrated: default → nen (Northeast Nodaway RV School District)",
    )
    tenant_manager = TenantManager(
        settings=settings,
        school_registry=school_registry,
        apns=apns_client,
        fcm=fcm_client,
        twilio=twilio_sms,
    )

    health_monitor = HealthMonitor(settings.PLATFORM_DB_PATH)
    email_service = EmailService(settings, settings.PLATFORM_DB_PATH)
    access_code_service = AccessCodeService(settings.PLATFORM_DB_PATH)

    app.state.settings = settings
    app.state.apns_client = apns_client
    app.state.cloudflare_dns = cloudflare_dns
    app.state.fcm_client = fcm_client
    app.state.twilio_sms = twilio_sms
    app.state.platform_admin_store = platform_admin_store
    app.state.tenant_billing_store = tenant_billing_store
    app.state.quiet_state_store = quiet_state_store
    app.state.alert_hub = AlertHub()
    app.state.school_registry = school_registry
    app.state.user_tenant_store = user_tenant_store
    app.state.tenant_manager = tenant_manager
    app.state.health_monitor = health_monitor
    app.state.email_service = email_service
    app.state.access_code_service = access_code_service
    app.state.demo_live_engine = DemoLiveEngine(tenant_manager)

    ai_insights_store = AiInsightsStore(settings.PLATFORM_DB_PATH)
    app.state.ai_insights_store = ai_insights_store

    inquiry_store = InquiryStore(settings.PLATFORM_DB_PATH)
    app.state.inquiry_store = inquiry_store

    customer_store = CustomerStore(settings.PLATFORM_DB_PATH)
    app.state.customer_store = customer_store

    demo_request_store = DemoRequestStore(settings.PLATFORM_DB_PATH)
    app.state.demo_request_store = demo_request_store

    training_store = TrainingStore(settings.PLATFORM_DB_PATH)
    app.state.training_store = training_store

    inbox_sync_service = InboxSyncService(email_service)
    app.state.inbox_sync_service = inbox_sync_service

    push_queue = PushQueue(maxsize=500)
    await push_queue.start()
    app.state.push_queue = push_queue

    health_task = asyncio.create_task(
        _health_check_loop(app, settings.HEALTH_CHECK_INTERVAL)
    )
    app.state.health_task = health_task  # exposed so watchdog can replace it
    health_watchdog_task = asyncio.create_task(
        _health_watchdog(app, settings.HEALTH_CHECK_INTERVAL)
    )
    qp_expiry_task = asyncio.create_task(
        _quiet_period_expiry_loop(app, interval=45.0)
    )
    wal_checkpoint_task = asyncio.create_task(
        _wal_checkpoint_loop(app, interval=300.0)
    )
    auto_reminder_task = asyncio.create_task(
        _auto_reminder_loop(app, interval_hours=24.0)
    )
    auto_archive_task = asyncio.create_task(
        _auto_archive_loop(app, interval_hours=6.0)
    )
    ack_reminder_task = asyncio.create_task(
        _ack_reminder_loop(app, interval=180.0)
    )
    inbox_sync_task = asyncio.create_task(
        _inbox_sync_loop(app, interval=180.0)
    )
    ai_insights_task = asyncio.create_task(
        _ai_insights_loop(app, interval=600.0)
    )
    ai_weekly_task = asyncio.create_task(
        _ai_weekly_report_loop(app, check_interval=21600.0)
    )

    yield

    await app.state.demo_live_engine.disable_all()
    await push_queue.stop()
    health_watchdog_task.cancel()
    # Cancel whatever health_task is current (watchdog may have replaced the original)
    current_health_task: asyncio.Task = app.state.health_task  # type: ignore[attr-defined]
    current_health_task.cancel()
    qp_expiry_task.cancel()
    wal_checkpoint_task.cancel()
    auto_reminder_task.cancel()
    auto_archive_task.cancel()
    ack_reminder_task.cancel()
    try:
        await health_watchdog_task
    except asyncio.CancelledError:
        pass
    try:
        await current_health_task
    except asyncio.CancelledError:
        pass
    try:
        await qp_expiry_task
    except asyncio.CancelledError:
        pass
    try:
        await wal_checkpoint_task
    except asyncio.CancelledError:
        pass
    try:
        await auto_reminder_task
    except asyncio.CancelledError:
        pass
    try:
        await auto_archive_task
    except asyncio.CancelledError:
        pass
    try:
        await ack_reminder_task
    except asyncio.CancelledError:
        pass
    inbox_sync_task.cancel()
    ai_insights_task.cancel()
    ai_weekly_task.cancel()
    try:
        await inbox_sync_task
    except asyncio.CancelledError:
        pass
    try:
        await ai_insights_task
    except asyncio.CancelledError:
        pass
    try:
        await ai_weekly_task
    except asyncio.CancelledError:
        pass

    await apns_client.stop()
    await cloudflare_dns.stop()
    await fcm_client.stop()
    await twilio_sms.stop()


app = FastAPI(
    title="BlueBird Alerts API",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET, same_site="lax", https_only=settings.ENVIRONMENT not in ("development", "test"))
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def school_context_middleware(request, call_next):
    path = request.scope.get("path", "") or "/"
    if (
        path in {"/", "/login", "/safety", "/request-demo", "/favicon.ico", "/health", "/schools", "/docs", "/redoc", "/openapi.json"}
        or path.startswith("/super-admin")
        or path.startswith("/static/")
        or path.startswith("/onboarding")
        or path.startswith("/public/")
        or path.startswith("/api/public/")
    ):
        response = await call_next(request)
        return response

    raw_segments = [segment for segment in path.split("/") if segment]
    tenant_from_header_raw = request.headers.get("X-Tenant-ID")
    tenant_from_header: str | None = None
    if tenant_from_header_raw is not None and tenant_from_header_raw.strip():
        candidate = _normalize_tenant_candidate(tenant_from_header_raw)
        if not candidate:
            return JSONResponse(
                {"detail": "Invalid X-Tenant-ID header."},
                status_code=400,
            )
        tenant_from_header = candidate

    resolution_source = ""
    school = None

    def bind_tenant_context(bound_school) -> None:
        request.state.school_path_prefix = f"/{bound_school.slug}"
        request.state.school_slug = bound_school.slug
        request.state.tenant_id = int(bound_school.id)
        request.state.school = bound_school
        request.state.tenant = request.app.state.tenant_manager.get(bound_school)

    if tenant_from_header:
        resolution_source = "header"
        school = request.app.state.tenant_manager.school_for_slug(tenant_from_header)
        if school is None:
            return JSONResponse(
                {"detail": "Unknown tenant in X-Tenant-ID header."},
                status_code=400,
            )
        bind_tenant_context(school)
    else:
        if not raw_segments:
            return JSONResponse(
                {"detail": "Tenant could not be resolved. Use X-Tenant-ID header or /{tenant}/... path."},
                status_code=400,
            )
        resolution_source = "path"
        school_slug = _normalize_tenant_candidate(raw_segments[0])
        if not school_slug:
            return JSONResponse(
                {"detail": "Tenant could not be resolved. Use X-Tenant-ID header or /{tenant}/... path."},
                status_code=400,
            )
        school = request.app.state.tenant_manager.school_for_slug(school_slug)
        if school is None:
            return JSONResponse(
                {"detail": "Tenant could not be resolved. Use X-Tenant-ID header or /{tenant}/... path."},
                status_code=400,
            )
        stripped_path = "/" + "/".join(raw_segments[1:]) if len(raw_segments) > 1 else "/"
        request.scope["path"] = stripped_path
        request.scope["raw_path"] = stripped_path.encode("utf-8")
        bind_tenant_context(school)

    logger.debug(
        "Tenant resolved source=%s tenant_id=%s slug=%s path_in=%s path_internal=%s",
        resolution_source,
        getattr(request.state, "tenant_id", None),
        getattr(request.state, "school_slug", None),
        path,
        request.scope.get("path", path),
    )

    response = await call_next(request)
    location = response.headers.get("location")
    if location and location.startswith("/admin"):
        response.headers["location"] = f"{request.state.school_path_prefix}{location}"
    return response

app.include_router(router)
