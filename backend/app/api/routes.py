from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import require_api_key
from app.models.schemas import (
    AlarmActivateRequest,
    AlarmDeactivateRequest,
    AlarmStatusResponse,
    AlertsResponse,
    AlertSummary,
    CreateUserRequest,
    DevicesResponse,
    DeviceSummary,
    PanicRequest,
    PanicResponse,
    RegisterDeviceRequest,
    RegisterDeviceResponse,
    UserSummary,
    UsersResponse,
)
from app.services.alert_broadcaster import BroadcastPlan, AlertBroadcaster
from app.services.alarm_store import AlarmStore
from app.services.apns import APNsClient
from app.services.alert_log import AlertLog
from app.services.device_registry import DeviceRegistry
from app.services.user_store import UserStore
from app.web.admin_views import render_admin_page, render_login_page


router = APIRouter()
logger = logging.getLogger("bluebird.routes")


def _registry(req: Request) -> DeviceRegistry:
    return req.app.state.device_registry  # type: ignore[attr-defined]


def _apns(req: Request) -> APNsClient:
    return req.app.state.apns_client  # type: ignore[attr-defined]

def _alarm_store(req: Request) -> AlarmStore:
    return req.app.state.alarm_store  # type: ignore[attr-defined]


def _alert_log(req: Request) -> AlertLog:
    return req.app.state.alert_log  # type: ignore[attr-defined]

def _users(req: Request) -> UserStore:
    return req.app.state.user_store  # type: ignore[attr-defined]

def _broadcaster(req: Request) -> AlertBroadcaster:
    return req.app.state.broadcaster  # type: ignore[attr-defined]


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


async def _require_dashboard_admin(request: Request) -> UserStore:
    user_id = _session_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active or user.role != "admin" or not user.can_login:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
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


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/alarm/status", response_model=AlarmStatusResponse)
async def alarm_status(request: Request) -> AlarmStatusResponse:
    state = await _alarm_store(request).get_state()
    return AlarmStatusResponse(
        is_active=state.is_active,
        message=state.message,
        activated_at=state.activated_at,
        activated_by_user_id=state.activated_by_user_id,
        deactivated_at=state.deactivated_at,
        deactivated_by_user_id=state.deactivated_by_user_id,
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

    apns_devices = await _registry(request).list_by_provider("apns")
    apns_tokens = [device.token for device in apns_devices]
    sms_numbers = await users.list_sms_targets()
    plan = BroadcastPlan(apns_tokens=apns_tokens, sms_numbers=sms_numbers)
    background_tasks.add_task(_broadcaster(request).broadcast_panic, alert_id=alert_id, message=body.message, plan=plan)

    logger.warning(
        "ALARM ACTIVATED alert_id=%s by_user=%s devices=%s sms_targets=%s message=%r",
        alert_id,
        triggered_by_user_id,
        len(apns_tokens),
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


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard(request: Request) -> HTMLResponse:
    if _session_user_id(request) is None:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    await _require_dashboard_admin(request)
    devices = await _registry(request).list_devices()
    alerts = await _alert_log(request).list_recent(limit=20)
    users = await _users(request).list_users()
    alarm_state = await _alarm_store(request).get_state()
    flash_message, flash_error = _pop_flash(request)
    html = render_admin_page(
        current_user=request.state.admin_user,  # type: ignore[attr-defined]
        alerts=alerts,
        devices=devices,
        users=users,
        alarm_state=alarm_state,
        apns_configured=_apns(request).is_configured(),
        twilio_configured=_broadcaster(request).twilio_configured(),
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
        )
    )


@router.post("/admin/setup", include_in_schema=False)
async def admin_setup(
    request: Request,
    name: str = Form(...),
    login_name: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    if await _users(request).count_dashboard_admins() > 0:
        _set_flash(request, error="An admin login already exists. Sign in instead.")
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    if not name.strip() or not login_name.strip() or not password.strip():
        _set_flash(request, error="Name, username, and password are required.")
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
    _set_flash(request, message=f"Welcome back, {user.name}.")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/logout", include_in_schema=False)
async def admin_logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/users/create", include_in_schema=False)
async def admin_create_user(
    request: Request,
    name: str = Form(...),
    role: str = Form(...),
    phone_e164: str = Form(default=""),
    login_name: str = Form(default=""),
    password: str = Form(default=""),
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

    apns_devices = await _registry(request).list_by_provider("apns")
    provider_counts = await _registry(request).provider_counts()
    device_count = await _registry(request).count()
    apns_tokens = [device.token for device in apns_devices]
    sms_numbers = await _users(request).list_sms_targets()

    logger.warning(
        "PANIC alert_id=%s devices=%s providers=%s sms_targets=%s message=%r",
        alert_id,
        device_count,
        provider_counts,
        len(sms_numbers),
        body.message,
    )

    plan = BroadcastPlan(apns_tokens=apns_tokens, sms_numbers=sms_numbers)
    background_tasks.add_task(_broadcaster(request).broadcast_panic, alert_id=alert_id, message=body.message, plan=plan)

    return PanicResponse(
        alert_id=alert_id,
        device_count=device_count,
        attempted=len(apns_tokens),
        succeeded=0,
        failed=0,
        apns_configured=_apns(request).is_configured(),
        provider_attempts={"apns": len(apns_tokens), "fcm": 0},
        sms_queued=len(sms_numbers),
        twilio_configured=_broadcaster(request).twilio_configured(),
    )
