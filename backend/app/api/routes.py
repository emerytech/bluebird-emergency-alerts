from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import require_api_key
from app.models.schemas import (
    AlarmActivateRequest,
    AlarmDeactivateRequest,
    AlarmStatusResponse,
    AdminBroadcastRequest,
    AlertsResponse,
    AlertSummary,
    BroadcastUpdateSummary,
    CreateUserRequest,
    DevicesResponse,
    DeviceSummary,
    MobileLoginRequest,
    MobileLoginResponse,
    PanicRequest,
    PanicResponse,
    PublicSchoolSummary,
    QuietPeriodRequestCreate,
    QuietPeriodSummary,
    RegisterDeviceRequest,
    RegisterDeviceResponse,
    ReportRequest,
    ReportResponse,
    SchoolsCatalogResponse,
    UserSummary,
    UsersResponse,
)
from app.services.alert_broadcaster import BroadcastPlan, AlertBroadcaster
from app.services.alarm_store import AlarmStore
from app.services.apns import APNsClient
from app.services.alert_log import AlertLog
from app.services.device_registry import DeviceRegistry
from app.services.fcm import FCMClient
from app.services.quiet_period_store import QuietPeriodStore
from app.services.report_store import ReportStore
from app.services.platform_admin_store import PlatformAdminStore
from app.services.school_registry import SchoolRegistry
from app.services.user_store import UserStore
from app.web.admin_views import (
    render_admin_page,
    render_change_password_page,
    render_login_page,
    render_super_admin_login_page,
    render_super_admin_page,
)


router = APIRouter()
logger = logging.getLogger("bluebird.routes")


def _registry(req: Request) -> DeviceRegistry:
    return req.state.tenant.device_registry  # type: ignore[attr-defined]


def _apns(req: Request) -> APNsClient:
    return req.app.state.apns_client  # type: ignore[attr-defined]

def _alarm_store(req: Request) -> AlarmStore:
    return req.state.tenant.alarm_store  # type: ignore[attr-defined]


def _fcm(req: Request) -> FCMClient:
    return req.app.state.fcm_client  # type: ignore[attr-defined]


def _reports(req: Request) -> ReportStore:
    return req.state.tenant.report_store  # type: ignore[attr-defined]


def _quiet_periods(req: Request) -> QuietPeriodStore:
    return req.state.tenant.quiet_period_store  # type: ignore[attr-defined]


def _alert_log(req: Request) -> AlertLog:
    return req.state.tenant.alert_log  # type: ignore[attr-defined]

def _users(req: Request) -> UserStore:
    return req.state.tenant.user_store  # type: ignore[attr-defined]

def _broadcaster(req: Request) -> AlertBroadcaster:
    return req.state.tenant.broadcaster  # type: ignore[attr-defined]


def _schools(req: Request) -> SchoolRegistry:
    return req.app.state.school_registry  # type: ignore[attr-defined]


def _platform_admins(req: Request) -> PlatformAdminStore:
    return req.app.state.platform_admin_store  # type: ignore[attr-defined]


def _session_user_id(request: Request) -> Optional[int]:
    value = request.session.get("admin_user_id")
    return int(value) if isinstance(value, int) or isinstance(value, str) and str(value).isdigit() else None


def _set_flash(request: Request, *, message: Optional[str] = None, error: Optional[str] = None) -> None:
    request.session["admin_flash_message"] = message or ""
    request.session["admin_flash_error"] = error or ""


def _pop_flash(request: Request) -> tuple[Optional[str], Optional[str]]:
    message = str(request.session.pop("admin_flash_message", "") or "") or None
    error = str(request.session.pop("admin_flash_error", "") or "") or None
    return message, error


def _super_admin_ok(request: Request) -> bool:
    return bool(request.session.get("super_admin_id"))


def _require_super_admin(request: Request) -> None:
    if not _super_admin_ok(request):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/super-admin/login"})


def _super_admin_id(request: Request) -> Optional[int]:
    value = request.session.get("super_admin_id")
    return int(value) if isinstance(value, int) or isinstance(value, str) and str(value).isdigit() else None


def _school_prefix(request: Request) -> str:
    return str(getattr(request.state, "school_path_prefix", "") or "")


def _school_url(request: Request, suffix: str) -> str:
    normalized_suffix = suffix if suffix.startswith("/") else f"/{suffix}"
    return f"{_school_prefix(request)}{normalized_suffix}"


async def _require_dashboard_admin(request: Request) -> UserStore:
    user_id = _session_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": _school_url(request, "/admin/login")})
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active or user.role != "admin" or not user.can_login:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": _school_url(request, "/admin/login")})
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": _school_url(request, "/admin/change-password")})
    request.state.admin_user = user
    return _users(request)


async def _validated_user_id(users: UserStore, user_id: Optional[int]) -> Optional[int]:
    if user_id is None:
        return None
    if await users.exists(user_id):
        return user_id
    return None


async def _require_admin_user(users: UserStore, user_id: Optional[int]) -> int:
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin user_id is required to deactivate alarm")
    user = await users.get_user(user_id)
    if user is None or not user.is_active or user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only active admin users can deactivate alarm")
    return user.id


@router.get("/", include_in_schema=False)
async def root(request: Request) -> RedirectResponse:
    school_prefix = _school_prefix(request)
    if school_prefix:
        return RedirectResponse(url=_school_url(request, "/admin/login"), status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/super-admin/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/schools", response_model=SchoolsCatalogResponse)
async def list_schools(request: Request) -> SchoolsCatalogResponse:
    schools = await _schools(request).list_schools()
    base_domain = str(request.app.state.settings.BASE_DOMAIN).strip().lower()  # type: ignore[attr-defined]
    return SchoolsCatalogResponse(
        schools=[
            PublicSchoolSummary(
                name=school.name,
                slug=school.slug,
                path=f"/{school.slug}",
                api_base_url=f"https://{base_domain}/{school.slug}",
                admin_url=f"https://{base_domain}/{school.slug}/admin",
            )
            for school in schools
            if school.is_active
        ]
    )


@router.post("/auth/login", response_model=MobileLoginResponse)
async def mobile_login(body: MobileLoginRequest, request: Request) -> MobileLoginResponse:
    user = await _users(request).authenticate_user(body.login_name, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    await _users(request).mark_login(user.id)
    quiet_period = await _quiet_periods(request).active_for_user(user_id=user.id)
    return MobileLoginResponse(
        user_id=user.id,
        name=user.name,
        role=user.role,
        login_name=user.login_name or body.login_name,
        must_change_password=user.must_change_password,
        can_deactivate_alarm=user.role == "admin",
        quiet_period_expires_at=quiet_period.expires_at if quiet_period else None,
    )


@router.get("/alarm/status", response_model=AlarmStatusResponse)
async def alarm_status(request: Request) -> AlarmStatusResponse:
    state = await _alarm_store(request).get_state()
    broadcasts = await _reports(request).list_broadcast_updates(limit=5)
    return AlarmStatusResponse(
        is_active=state.is_active,
        message=state.message,
        activated_at=state.activated_at,
        activated_by_user_id=state.activated_by_user_id,
        deactivated_at=state.deactivated_at,
        deactivated_by_user_id=state.deactivated_by_user_id,
        broadcasts=[
            BroadcastUpdateSummary(
                update_id=item.id,
                created_at=item.created_at,
                admin_user_id=item.admin_user_id,
                message=item.message,
            )
            for item in broadcasts
        ],
    )


@router.post("/alarm/activate", response_model=AlarmStatusResponse)
async def activate_alarm(
    body: AlarmActivateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_api_key),
) -> AlarmStatusResponse:
    users = _users(request)
    triggered_by_user_id = await _validated_user_id(users, body.user_id)

    trigger_ip = request.client.host if request.client else None
    trigger_user_agent = request.headers.get("user-agent")
    alert_id = await _alert_log(request).log_alert(
        body.message,
        triggered_by_user_id=triggered_by_user_id,
        trigger_ip=trigger_ip,
        trigger_user_agent=trigger_user_agent,
    )
    state = await _alarm_store(request).activate(message=body.message, activated_by_user_id=triggered_by_user_id)

    paused_user_ids = set(await _quiet_periods(request).active_user_ids())
    apns_devices = await _registry(request).list_by_provider("apns")
    fcm_devices = await _registry(request).list_by_provider("fcm")
    apns_tokens = [device.token for device in apns_devices if device.user_id is None or device.user_id not in paused_user_ids]
    fcm_tokens = [device.token for device in fcm_devices if device.user_id is None or device.user_id not in paused_user_ids]
    sms_numbers = await users.list_sms_targets(excluded_user_ids=list(paused_user_ids))
    plan = BroadcastPlan(apns_tokens=apns_tokens, fcm_tokens=fcm_tokens, sms_numbers=sms_numbers)
    background_tasks.add_task(_broadcaster(request).broadcast_panic, alert_id=alert_id, message=body.message, plan=plan)

    logger.warning(
        "ALARM ACTIVATED alert_id=%s by_user=%s apns=%s fcm=%s sms_targets=%s message=%r",
        alert_id,
        triggered_by_user_id,
        len(apns_tokens),
        len(fcm_tokens),
        len(sms_numbers),
        body.message,
    )

    return AlarmStatusResponse(
        is_active=state.is_active,
        message=state.message,
        activated_at=state.activated_at,
        activated_by_user_id=state.activated_by_user_id,
        deactivated_at=state.deactivated_at,
        deactivated_by_user_id=state.deactivated_by_user_id,
    )


@router.post("/alarm/deactivate", response_model=AlarmStatusResponse)
async def deactivate_alarm(
    body: AlarmDeactivateRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> AlarmStatusResponse:
    admin_user_id = await _require_admin_user(_users(request), body.user_id)
    state = await _alarm_store(request).deactivate(deactivated_by_user_id=admin_user_id)
    logger.warning("ALARM DEACTIVATED by_user=%s", admin_user_id)
    return AlarmStatusResponse(
        is_active=state.is_active,
        message=state.message,
        activated_at=state.activated_at,
        activated_by_user_id=state.activated_by_user_id,
        deactivated_at=state.deactivated_at,
        deactivated_by_user_id=state.deactivated_by_user_id,
    )


def _build_server_info(request: Request) -> dict:
    started_at: Optional[datetime] = getattr(request.app.state, "started_at", None)
    if started_at:
        delta = datetime.now(timezone.utc) - started_at
        total = int(delta.total_seconds())
        days, remainder = divmod(total, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m {seconds}s")
        uptime = " ".join(parts)
    else:
        uptime = "unknown"
    return {
        "uptime": uptime,
        "hostname": socket.gethostname(),
        "python_version": sys.version.split()[0],
        "pid": str(os.getpid()),
        "restart_configured": "yes" if request.app.state.settings.SERVER_RESTART_COMMAND else "no",
    }


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard(request: Request) -> HTMLResponse:
    if _session_user_id(request) is None:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    await _require_dashboard_admin(request)
    devices = await _registry(request).list_devices()
    alerts = await _alert_log(request).list_recent(limit=20)
    users = await _users(request).list_users()
    alarm_state = await _alarm_store(request).get_state()
    reports = await _reports(request).list_reports(limit=25)
    broadcasts = await _reports(request).list_broadcast_updates(limit=10)
    quiet_periods = await _quiet_periods(request).list_recent(limit=25)
    flash_message, flash_error = _pop_flash(request)
    html = render_admin_page(
        school_name=request.state.school.name,
        school_slug=request.state.school.slug,
        school_path_prefix=_school_prefix(request),
        current_user=request.state.admin_user,  # type: ignore[attr-defined]
        alerts=alerts,
        devices=devices,
        users=users,
        alarm_state=alarm_state,
        reports=reports,
        broadcasts=broadcasts,
        quiet_periods=quiet_periods,
        apns_configured=_apns(request).is_configured(),
        twilio_configured=_broadcaster(request).twilio_configured(),
        server_info=_build_server_info(request),
        flash_message=flash_message,
        flash_error=flash_error,
    )
    return HTMLResponse(content=html)


@router.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
async def admin_login_page(request: Request) -> HTMLResponse:
    if _session_user_id(request) is not None:
        user = await _users(request).get_user(_session_user_id(request) or 0)
        if user and user.role == "admin" and user.is_active and user.can_login:
            return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    setup_mode = await _users(request).count_dashboard_admins() == 0
    flash_message, flash_error = _pop_flash(request)
    return HTMLResponse(
        render_login_page(
            message=flash_message,
            error=flash_error,
            setup_mode=setup_mode,
            school_name=request.state.school.name,
            school_slug=request.state.school.slug,
            school_path_prefix=_school_prefix(request),
            setup_pin_required=bool(getattr(request.state.school, "setup_pin_required", False)),
        )
    )


@router.post("/admin/setup", include_in_schema=False)
async def admin_setup(
    request: Request,
    name: str = Form(...),
    setup_pin: str = Form(default=""),
    login_name: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    if await _users(request).count_dashboard_admins() > 0:
        _set_flash(request, error="An admin login already exists. Sign in instead.")
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    if not name.strip() or not login_name.strip() or not password.strip():
        _set_flash(request, error="Name, username, and password are required.")
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    school = request.state.school  # type: ignore[attr-defined]
    if getattr(school, "setup_pin_required", False):
        if not setup_pin.strip():
            _set_flash(request, error="School setup PIN is required for first-time admin setup.")
            return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
        if not await _schools(request).verify_setup_pin(slug=school.slug, setup_pin=setup_pin):
            _set_flash(request, error="Invalid school setup PIN.")
            return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    await _users(request).create_user(
        name=name.strip(),
        role="admin",
        phone_e164=None,
        login_name=login_name.strip(),
        password=password,
    )
    _set_flash(request, message="Admin account created. Sign in to continue.")
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/login", include_in_schema=False)
async def admin_login(
    request: Request,
    login_name: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    user = await _users(request).authenticate_admin(login_name.strip(), password)
    if user is None:
        _set_flash(request, error="Invalid admin username or password.")
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    request.session["admin_user_id"] = user.id
    await _users(request).mark_login(user.id)
    if user.must_change_password:
        return RedirectResponse(url="/admin/change-password", status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message=f"Welcome back, {user.name}.")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/logout", include_in_schema=False)
async def admin_logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/super-admin/login", response_class=HTMLResponse, include_in_schema=False)
async def super_admin_login_page(request: Request) -> HTMLResponse:
    if _super_admin_ok(request):
        admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
        if admin and admin.must_change_password:
            return RedirectResponse(url="/super-admin/change-password", status_code=status.HTTP_303_SEE_OTHER)
        return RedirectResponse(url="/super-admin", status_code=status.HTTP_303_SEE_OTHER)
    flash_message, flash_error = _pop_flash(request)
    return HTMLResponse(render_super_admin_login_page(message=flash_message, error=flash_error))


@router.post("/super-admin/login", include_in_schema=False)
async def super_admin_login(
    request: Request,
    login_name: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    admin = await _platform_admins(request).authenticate(login_name.strip(), password)
    if admin is None:
        _set_flash(request, error="Invalid super admin credentials.")
        return RedirectResponse(url="/super-admin/login", status_code=status.HTTP_303_SEE_OTHER)
    request.session["super_admin_id"] = admin.id
    await _platform_admins(request).mark_login(admin.id)
    if admin.must_change_password:
        _set_flash(request, message="Please change your temporary super admin password before continuing.")
        return RedirectResponse(url="/super-admin/change-password", status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message="Signed in to super admin.")
    return RedirectResponse(url="/super-admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/logout", include_in_schema=False)
async def super_admin_logout(request: Request) -> RedirectResponse:
    request.session.pop("super_admin_id", None)
    return RedirectResponse(url="/super-admin/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/super-admin/change-password", response_class=HTMLResponse, include_in_schema=False)
async def super_admin_change_password_page(request: Request) -> HTMLResponse:
    admin_id = _super_admin_id(request)
    if admin_id is None:
        return RedirectResponse(url="/super-admin/login", status_code=status.HTTP_303_SEE_OTHER)
    admin = await _platform_admins(request).get_by_id(admin_id)
    if admin is None:
        request.session.pop("super_admin_id", None)
        return RedirectResponse(url="/super-admin/login", status_code=status.HTTP_303_SEE_OTHER)
    flash_message, flash_error = _pop_flash(request)
    return HTMLResponse(
        render_change_password_page(
            user_name=admin.login_name,
            message=flash_message,
            error=flash_error,
            action="/super-admin/change-password",
            title="Change Super Admin Password",
            eyebrow="BlueBird Platform",
            heading="Password change required" if admin.must_change_password else "Update super admin password",
            helper=(
                "Your super admin account is using a temporary bootstrap password. Choose a new one before continuing."
                if admin.must_change_password
                else "Rotate your platform password here whenever you want to update super admin access."
            ),
        )
    )


@router.post("/super-admin/change-password", include_in_schema=False)
async def super_admin_change_password_submit(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> RedirectResponse:
    admin_id = _super_admin_id(request)
    if admin_id is None:
        return RedirectResponse(url="/super-admin/login", status_code=status.HTTP_303_SEE_OTHER)
    admin = await _platform_admins(request).get_by_id(admin_id)
    if admin is None:
        request.session.pop("super_admin_id", None)
        return RedirectResponse(url="/super-admin/login", status_code=status.HTTP_303_SEE_OTHER)
    if new_password != confirm_password:
        _set_flash(request, error="Passwords do not match.")
        return RedirectResponse(url="/super-admin/change-password", status_code=status.HTTP_303_SEE_OTHER)
    if len(new_password) < 8:
        _set_flash(request, error="Password must be at least 8 characters.")
        return RedirectResponse(url="/super-admin/change-password", status_code=status.HTTP_303_SEE_OTHER)
    await _platform_admins(request).change_password(admin_id, new_password)
    _set_flash(request, message="Super admin password updated.")
    return RedirectResponse(url="/super-admin", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/super-admin", response_class=HTMLResponse, include_in_schema=False)
async def super_admin_dashboard(request: Request) -> HTMLResponse:
    _require_super_admin(request)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    if admin and admin.must_change_password:
        return RedirectResponse(url="/super-admin/change-password", status_code=status.HTTP_303_SEE_OTHER)
    flash_message, flash_error = _pop_flash(request)
    schools = await _schools(request).list_schools()
    base_domain = str(request.app.state.settings.BASE_DOMAIN).strip().lower()  # type: ignore[attr-defined]
    school_rows: list[dict[str, object]] = []
    for school in schools:
        school_prefix = f"/{school.slug}"
        admin_count = await request.app.state.tenant_manager.get(school).user_store.count_dashboard_admins()  # type: ignore[attr-defined]
        admin_url = f"https://{base_domain}{school_prefix}/admin"
        school_rows.append(
            {
                "name": school.name,
                "slug": school.slug,
                "admin_url": admin_url,
                "admin_url_label": f"{base_domain}{school_prefix}/admin",
                "api_base_label": f"{base_domain}{school_prefix}",
                "setup_status": "Ready" if admin_count > 0 else "Needs first admin",
                "setup_hint": (
                    "School dashboard login is active."
                    if admin_count > 0
                    else (
                        "Open the admin URL and provide the school setup PIN."
                        if school.setup_pin_required
                        else "Open the admin URL to create the first school admin."
                    )
                ),
                "is_active": school.is_active,
            }
        )
    return HTMLResponse(
        render_super_admin_page(
            base_domain=request.app.state.settings.BASE_DOMAIN,  # type: ignore[attr-defined]
            school_rows=school_rows,
            git_pull_configured=bool(request.app.state.settings.SERVER_GIT_PULL_COMMAND),  # type: ignore[attr-defined]
            flash_message=flash_message,
            flash_error=flash_error,
        )
    )


@router.post("/super-admin/schools/create", include_in_schema=False)
async def super_admin_create_school(
    request: Request,
    name: str = Form(...),
    slug: str = Form(...),
    setup_pin: str = Form(default=""),
) -> RedirectResponse:
    _require_super_admin(request)
    from app.services.tenant_manager import normalize_school_slug

    normalized_name = name.strip()
    normalized_slug = normalize_school_slug(slug)
    if not normalized_name:
        _set_flash(request, error="School name is required.")
        return RedirectResponse(url="/super-admin#create-school", status_code=status.HTTP_303_SEE_OTHER)
    if not normalized_slug:
        _set_flash(request, error="School slug is required.")
        return RedirectResponse(url="/super-admin#create-school", status_code=status.HTTP_303_SEE_OTHER)
    normalized_pin = setup_pin.strip()
    if normalized_pin and len(normalized_pin) < 4:
        _set_flash(request, error="Setup PIN must be at least 4 characters.")
        return RedirectResponse(url="/super-admin#create-school", status_code=status.HTTP_303_SEE_OTHER)
    try:
        school = await _schools(request).create_school(
            slug=normalized_slug,
            name=normalized_name,
            setup_pin=normalized_pin or None,
        )
    except Exception as exc:
        _set_flash(request, error=f"Could not create school: {exc}")
        return RedirectResponse(url="/super-admin#create-school", status_code=status.HTTP_303_SEE_OTHER)
    base_domain = str(request.app.state.settings.BASE_DOMAIN).strip().lower()  # type: ignore[attr-defined]
    admin_url = f"https://{base_domain}/{school.slug}/admin"
    _set_flash(
        request,
        message=(
            f"Created school {school.name}. School admin URL: {admin_url}."
            + (" A setup PIN was saved for first-admin creation." if school.setup_pin_required else "")
        ),
    )
    return RedirectResponse(url="/super-admin#schools", status_code=status.HTTP_303_SEE_OTHER)


def _run_server_command(command: Optional[str]) -> None:
    if command:
        os.system(command)


@router.post("/super-admin/server/pull-latest", include_in_schema=False)
async def super_admin_pull_latest(
    request: Request,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    _require_super_admin(request)
    command = request.app.state.settings.SERVER_GIT_PULL_COMMAND  # type: ignore[attr-defined]
    if not command:
        _set_flash(request, error="SERVER_GIT_PULL_COMMAND is not configured on this server.")
        return RedirectResponse(url="/super-admin#server-tools", status_code=status.HTTP_303_SEE_OTHER)
    background_tasks.add_task(_run_server_command, command)
    _set_flash(request, message="Server git pull started in the background.")
    return RedirectResponse(url="/super-admin#server-tools", status_code=status.HTTP_303_SEE_OTHER)


def _do_restart(command: Optional[str]) -> None:
    time.sleep(0.8)
    if command:
        os.system(command)
    else:
        # Self-restart: re-exec the same process image (ported from emeryos).
        try:
            os.execv(sys.argv[0], sys.argv)
        except Exception:
            os.execv(sys.executable, [sys.executable] + sys.argv)


@router.post("/admin/server/restart", include_in_schema=False)
async def server_restart(request: Request, background_tasks: BackgroundTasks) -> RedirectResponse:
    await _require_dashboard_admin(request)
    command = request.app.state.settings.SERVER_RESTART_COMMAND
    background_tasks.add_task(_do_restart, command)
    _set_flash(request, message="Restart initiated. The service will be back in a few seconds.")
    return RedirectResponse(url="/admin#server", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/change-password", response_class=HTMLResponse, include_in_schema=False)
async def change_password_page(request: Request) -> HTMLResponse:
    user_id = _session_user_id(request)
    if user_id is None:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active:
        request.session.clear()
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    if not user.must_change_password:
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    flash_message, flash_error = _pop_flash(request)
    return HTMLResponse(
        render_change_password_page(
            user_name=user.name,
            message=flash_message,
            error=flash_error,
            action=_school_url(request, "/admin/change-password"),
        )
    )


@router.post("/admin/change-password", include_in_schema=False)
async def change_password_submit(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> RedirectResponse:
    user_id = _session_user_id(request)
    if user_id is None:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active:
        request.session.clear()
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    if new_password != confirm_password:
        _set_flash(request, error="Passwords do not match.")
        return RedirectResponse(url="/admin/change-password", status_code=status.HTTP_303_SEE_OTHER)
    if len(new_password) < 8:
        _set_flash(request, error="Password must be at least 8 characters.")
        return RedirectResponse(url="/admin/change-password", status_code=status.HTTP_303_SEE_OTHER)
    await _users(request).change_password(user_id, new_password)
    _set_flash(request, message="Password updated. Welcome!")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/users/create", include_in_schema=False)
async def admin_create_user(
    request: Request,
    name: str = Form(...),
    role: str = Form(...),
    phone_e164: str = Form(default=""),
    login_name: str = Form(default=""),
    password: str = Form(default=""),
    must_change_password: Optional[str] = Form(default=None),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    normalized_name = name.strip()
    normalized_role = role.strip().lower()
    normalized_phone = phone_e164.strip() or None
    if not normalized_name:
        _set_flash(request, error="Name is required.")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    if normalized_role not in {"admin", "teacher"}:
        _set_flash(request, error="Role must be admin or teacher.")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    if bool(login_name.strip()) != bool(password.strip()):
        _set_flash(request, error="Provide both username and password to enable login for a user.")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    try:
        await _users(request).create_user(
            name=normalized_name,
            role=normalized_role,
            phone_e164=normalized_phone,
            login_name=login_name.strip() or None,
            password=password.strip() or None,
            must_change_password=must_change_password == "1",
        )
    except Exception as exc:
        _set_flash(request, error=f"Could not create user: {exc}")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message=f"Created user {normalized_name}.")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/alarm/activate", include_in_schema=False)
async def admin_activate_alarm(
    request: Request,
    background_tasks: BackgroundTasks,
    message: str = Form(...),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    await activate_alarm(
        AlarmActivateRequest(message=message.strip(), user_id=_session_user_id(request)),
        request,
        background_tasks,
    )
    _set_flash(request, message="Alarm activated.")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/alarm/deactivate", include_in_schema=False)
async def admin_deactivate_alarm(
    request: Request,
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    await deactivate_alarm(
        AlarmDeactivateRequest(user_id=_session_user_id(request)),
        request,
    )
    _set_flash(request, message="Alarm deactivated.")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/broadcasts/create", include_in_schema=False)
async def admin_create_broadcast(
    request: Request,
    background_tasks: BackgroundTasks,
    message: str = Form(...),
    send_push: Optional[str] = Form(default=None),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    normalized_message = message.strip()
    if not normalized_message:
        _set_flash(request, error="Broadcast message cannot be empty.")
        return RedirectResponse(url="/admin#reports", status_code=status.HTTP_303_SEE_OTHER)
    await _reports(request).create_broadcast_update(
        admin_user_id=_session_user_id(request),
        message=normalized_message,
    )
    if send_push == "1":
        admin_user_id = _session_user_id(request)
        trigger_ip = request.client.host if request.client else None
        trigger_user_agent = request.headers.get("user-agent")
        alert_id = await _alert_log(request).log_alert(
            normalized_message,
            triggered_by_user_id=admin_user_id,
            trigger_ip=trigger_ip,
            trigger_user_agent=trigger_user_agent,
        )
        paused_user_ids = set(await _quiet_periods(request).active_user_ids())
        apns_devices = await _registry(request).list_by_provider("apns")
        fcm_devices = await _registry(request).list_by_provider("fcm")
        apns_tokens = [device.token for device in apns_devices if device.user_id is None or device.user_id not in paused_user_ids]
        fcm_tokens = [device.token for device in fcm_devices if device.user_id is None or device.user_id not in paused_user_ids]
        plan = BroadcastPlan(apns_tokens=apns_tokens, fcm_tokens=fcm_tokens, sms_numbers=[])
        background_tasks.add_task(
            _broadcaster(request).broadcast_panic,
            alert_id=alert_id,
            message=normalized_message,
            plan=plan,
        )
        _set_flash(request, message="Broadcast update posted and queued for push delivery.")
    else:
        _set_flash(request, message="Broadcast update posted.")
    return RedirectResponse(url="/admin#reports", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/quiet-periods/grant", include_in_schema=False)
async def admin_grant_quiet_period(
    request: Request,
    user_id: int = Form(...),
    reason: str = Form(default=""),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active:
        _set_flash(request, error="User was not found or is inactive.")
        return RedirectResponse(url="/admin#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)
    await _quiet_periods(request).grant_quiet_period(
        user_id=user_id,
        reason=reason.strip() or None,
        admin_user_id=_session_user_id(request) or 0,
    )
    _set_flash(request, message=f"Quiet period granted for {user.name} for 24 hours.")
    return RedirectResponse(url="/admin#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/devices/delete", include_in_schema=False)
async def admin_delete_device(
    request: Request,
    token: str = Form(...),
    push_provider: str = Form(...),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    deleted = await _registry(request).delete(token=token, push_provider=push_provider)
    if deleted:
        _set_flash(request, message="Device registration deleted.")
    else:
        _set_flash(request, error="That device registration was not found.")
    return RedirectResponse(url="/admin#devices", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/users/{user_id}/update", include_in_schema=False)
async def admin_update_user(
    user_id: int,
    request: Request,
    name: str = Form(...),
    role: str = Form(...),
    phone_e164: str = Form(default=""),
    login_name: str = Form(default=""),
    password: str = Form(default=""),
    is_active: Optional[str] = Form(default=None),
    clear_login: Optional[str] = Form(default=None),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    existing_user = await _users(request).get_user(user_id)
    if existing_user is None:
        _set_flash(request, error=f"User #{user_id} was not found.")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    normalized_name = name.strip()
    normalized_role = role.strip().lower()
    if not normalized_name:
        _set_flash(request, error="User name cannot be empty.")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    if normalized_role not in {"admin", "teacher"}:
        _set_flash(request, error="Role must be admin or teacher.")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    if clear_login is None and bool(login_name.strip()) != bool(password.strip()) and bool(password.strip()):
        _set_flash(request, error="To change credentials, provide both username and password.")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    try:
        await _users(request).update_user(
            user_id=user_id,
            name=normalized_name,
            role=normalized_role,
            phone_e164=phone_e164.strip() or None,
            is_active=is_active is not None,
            login_name=(login_name.strip() or existing_user.login_name),
            password=password.strip() or None,
            clear_login=clear_login is not None,
        )
    except Exception as exc:
        _set_flash(request, error=f"Could not update user #{user_id}: {exc}")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message=f"Updated user {normalized_name}.")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/users/{user_id}/delete", include_in_schema=False)
async def admin_delete_user(
    user_id: int,
    request: Request,
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    current_admin_id = _session_user_id(request)
    user = await _users(request).get_user(user_id)
    if user is None:
        _set_flash(request, error=f"User #{user_id} was not found.")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    if user.role == "admin" and user.can_login and user.is_active:
        other_admins = await _users(request).count_other_dashboard_admins(user.id)
        if other_admins <= 0:
            _set_flash(request, error="You cannot delete the last active admin with dashboard login access.")
            return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    await _users(request).delete_user(user_id)

    if current_admin_id == user_id:
        request.session.clear()
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    _set_flash(request, message=f"Deleted user {user.name}.")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/devices", response_model=DevicesResponse)
async def devices(request: Request, _: None = Depends(require_api_key)) -> DevicesResponse:
    registry = _registry(request)
    all_devices = await registry.list_devices()
    platform_counts = await registry.platform_counts()
    provider_counts = await registry.provider_counts()

    return DevicesResponse(
        device_count=len(all_devices),
        platform_counts=platform_counts,
        provider_counts=provider_counts,
        devices=[
            DeviceSummary(
                platform=device.platform,
                push_provider=device.push_provider,
                device_name=device.device_name,
                user_id=device.user_id,
                first_user_id=device.first_user_id,
                token_suffix=device.token[-8:],
            )
            for device in all_devices
        ],
    )


@router.get("/alerts", response_model=AlertsResponse)
async def alerts(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    _: None = Depends(require_api_key),
) -> AlertsResponse:
    recent_alerts = await _alert_log(request).list_recent(limit=limit)
    return AlertsResponse(
        alerts=[
            AlertSummary(
                alert_id=alert.id,
                created_at=alert.created_at,
                message=alert.message,
                triggered_by_user_id=alert.triggered_by_user_id,
            )
            for alert in recent_alerts
        ]
    )

@router.get("/users", response_model=UsersResponse)
async def users(request: Request, _: None = Depends(require_api_key)) -> UsersResponse:
    all_users = await _users(request).list_users()
    return UsersResponse(
        users=[
            UserSummary(
                user_id=u.id,
                created_at=u.created_at,
                name=u.name,
                role=u.role,
                phone_e164=u.phone_e164,
                is_active=u.is_active,
            )
            for u in all_users
        ]
    )


@router.post("/users", response_model=UserSummary)
async def create_user(body: CreateUserRequest, request: Request, _: None = Depends(require_api_key)) -> UserSummary:
    user_id = await _users(request).create_user(name=body.name, role=body.role.value, phone_e164=body.phone_e164)
    # Return the created record by re-listing. For MVP simplicity this avoids extra query code paths.
    all_users = await _users(request).list_users()
    created = next(u for u in all_users if u.id == user_id)
    return UserSummary(
        user_id=created.id,
        created_at=created.created_at,
        name=created.name,
        role=created.role,
        phone_e164=created.phone_e164,
        is_active=created.is_active,
    )


@router.post("/register-device", response_model=RegisterDeviceResponse)
async def register_device(
    body: RegisterDeviceRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> RegisterDeviceResponse:
    """
    Registers a device token for future push notifications.
    """

    registered = await _registry(request).register(
        token=body.device_token,
        platform=body.platform.value,
        push_provider=body.push_provider.value,
        device_name=body.device_name,
        user_id=body.user_id,
    )
    device_count = await _registry(request).count()
    platform_counts = await _registry(request).platform_counts()
    provider_counts = await _registry(request).provider_counts()
    logger.info(
        "Device registered=%s platform=%s provider=%s count=%s token_suffix=%s",
        registered,
        body.platform.value,
        body.push_provider.value,
        device_count,
        body.device_token[-8:],
    )
    return RegisterDeviceResponse(
        registered=registered,
        device_count=device_count,
        platform_counts=platform_counts,
        provider_counts=provider_counts,
    )


@router.post("/reports", response_model=ReportResponse)
async def create_report(
    body: ReportRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> ReportResponse:
    if not (await _alarm_store(request).get_state()).is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reports are only accepted during an active alarm")
    user_id = await _validated_user_id(_users(request), body.user_id)
    report_id = await _reports(request).create_report(
        user_id=user_id,
        category=body.category.value,
        note=body.note,
    )
    reports = await _reports(request).list_reports(limit=10)
    created = next((item for item in reports if item.id == report_id), None)
    if created is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not load created report")
    return ReportResponse(
        report_id=created.id,
        created_at=created.created_at,
        user_id=created.user_id,
        category=created.category,
        note=created.note,
    )


@router.post("/panic", response_model=PanicResponse)
async def panic(
    body: PanicRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_api_key),
) -> PanicResponse:
    """
    Broadcasts an emergency alert.

    Design goals:
      - Persist the alert immediately (audit trail).
      - Return quickly (<2 seconds target) by queuing outbound delivery.
      - Deliver redundantly (push + SMS) when configured.
    """

    triggered_by_user_id = body.user_id
    triggered_by_user_id = await _validated_user_id(_users(request), triggered_by_user_id)

    trigger_ip = request.client.host if request.client else None
    trigger_user_agent = request.headers.get("user-agent")

    alert_id = await _alert_log(request).log_alert(
        body.message,
        triggered_by_user_id=triggered_by_user_id,
        trigger_ip=trigger_ip,
        trigger_user_agent=trigger_user_agent,
    )
    await _alarm_store(request).activate(message=body.message, activated_by_user_id=triggered_by_user_id)

    paused_user_ids = set(await _quiet_periods(request).active_user_ids())
    apns_devices = await _registry(request).list_by_provider("apns")
    fcm_devices = await _registry(request).list_by_provider("fcm")
    provider_counts = await _registry(request).provider_counts()
    device_count = await _registry(request).count()
    apns_tokens = [device.token for device in apns_devices if device.user_id is None or device.user_id not in paused_user_ids]
    fcm_tokens = [device.token for device in fcm_devices if device.user_id is None or device.user_id not in paused_user_ids]
    sms_numbers = await _users(request).list_sms_targets(excluded_user_ids=list(paused_user_ids))

    logger.warning(
        "PANIC alert_id=%s devices=%s providers=%s sms_targets=%s message=%r",
        alert_id,
        device_count,
        provider_counts,
        len(sms_numbers),
        body.message,
    )

    plan = BroadcastPlan(apns_tokens=apns_tokens, fcm_tokens=fcm_tokens, sms_numbers=sms_numbers)
    background_tasks.add_task(_broadcaster(request).broadcast_panic, alert_id=alert_id, message=body.message, plan=plan)

    return PanicResponse(
        alert_id=alert_id,
        device_count=device_count,
        attempted=len(apns_tokens) + len(fcm_tokens),
        succeeded=0,
        failed=0,
        apns_configured=_apns(request).is_configured(),
        provider_attempts={"apns": len(apns_tokens), "fcm": len(fcm_tokens)},
        sms_queued=len(sms_numbers),
        twilio_configured=_broadcaster(request).twilio_configured(),
    )
