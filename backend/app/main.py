from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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
from app.services.twilio_sms import TwilioSMSClient
from app.services.user_tenant_store import UserTenantStore


settings = Settings()
logger = logging.getLogger("bluebird.main")
_TENANT_CLEAN_RE = re.compile(r"[^a-z0-9-]+")


async def _health_check_loop(app: FastAPI, interval: int) -> None:
    """
    Background heartbeat loop — runs health checks every `interval` seconds.
    Completely read-only: never writes to alert tables or triggers notifications.
    """
    while True:
        await asyncio.sleep(interval)
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
            elif checks["status"] == "ok" and email_service.is_configured():
                # Recovery email — only if a health_auto cooldown was recently consumed
                # (check_cooldown would have reset it; we only send recovery if previously degraded)
                pass
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Health check loop error: %s", exc)


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


def _normalize_tenant_candidate(value: str) -> str:
    return _TENANT_CLEAN_RE.sub("-", value.strip().lower()).strip("-")


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

    health_task = asyncio.create_task(
        _health_check_loop(app, settings.HEALTH_CHECK_INTERVAL)
    )
    qp_expiry_task = asyncio.create_task(
        _quiet_period_expiry_loop(app, interval=45.0)
    )

    yield

    health_task.cancel()
    qp_expiry_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    try:
        await qp_expiry_task
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
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def school_context_middleware(request, call_next):
    path = request.scope.get("path", "") or "/"
    if (
        path in {"/", "/health", "/schools", "/docs", "/redoc", "/openapi.json"}
        or path.startswith("/super-admin")
        or path.startswith("/static/")
        or path.startswith("/onboarding")
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
