from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import router
from app.core.config import Settings
from app.core.logging import configure_logging
from app.services.apns import APNsClient
from app.services.cloudflare_dns import CloudflareDNSClient
from app.services.fcm import FCMClient
from app.services.platform_admin_store import PlatformAdminStore
from app.services.school_registry import SchoolRegistry
from app.services.tenant_manager import TenantManager, normalize_school_slug
from app.services.twilio_sms import TwilioSMSClient
from app.services.user_tenant_store import UserTenantStore


settings = Settings()


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
    tenant_manager = TenantManager(
        settings=settings,
        school_registry=school_registry,
        apns=apns_client,
        fcm=fcm_client,
        twilio=twilio_sms,
    )

    app.state.settings = settings
    app.state.apns_client = apns_client
    app.state.cloudflare_dns = cloudflare_dns
    app.state.fcm_client = fcm_client
    app.state.twilio_sms = twilio_sms
    app.state.platform_admin_store = platform_admin_store
    app.state.school_registry = school_registry
    app.state.user_tenant_store = user_tenant_store
    app.state.tenant_manager = tenant_manager

    yield

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
    ):
        response = await call_next(request)
        return response

    raw_segments = [segment for segment in path.split("/") if segment]
    if not raw_segments:
        response = await call_next(request)
        return response
    school_slug = normalize_school_slug(raw_segments[0])
    school = request.app.state.tenant_manager.school_for_slug(school_slug)
    if school is None:
        return PlainTextResponse("Unknown school path.", status_code=404)

    stripped_path = "/" + "/".join(raw_segments[1:]) if len(raw_segments) > 1 else "/"
    request.scope["path"] = stripped_path
    request.scope["raw_path"] = stripped_path.encode("utf-8")
    request.state.school_path_prefix = f"/{school.slug}"
    request.state.school_slug = school.slug
    request.state.school = school
    request.state.tenant = request.app.state.tenant_manager.get(school)
    response = await call_next(request)
    location = response.headers.get("location")
    if location and location.startswith("/admin"):
        response.headers["location"] = f"{request.state.school_path_prefix}{location}"
    return response

app.include_router(router)
