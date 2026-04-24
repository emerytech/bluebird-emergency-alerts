from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import socket
import sys
import time
from datetime import datetime, timezone
from html import escape
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import require_api_key
from app.constants.labels import FEATURE_LABELS, get_feature_label
from app.models.schemas import (
    AdminMessageInboxItem,
    AdminMessageInboxResponse,
    AdminMessageReplyRequest,
    AdminMessageRequest,
    AdminSendMessageRequest,
    AdminSendMessageResponse,
    AdminMessageResponse,
    AlarmActivateRequest,
    AlarmDeactivateRequest,
    AlarmStatusResponse,
    AdminBroadcastRequest,
    AlertsResponse,
    AlertSummary,
    IncidentCreateRequest,
    IncidentListResponse,
    IncidentSummary,
    TeamAssistCreateRequest,
    TeamAssistActionRequest,
    TeamAssistCancelConfirmRequest,
    TeamAssistListResponse,
    TeamAssistSummary,
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
    QuietPeriodAdminActionRequest,
    QuietPeriodAdminItem,
    QuietPeriodAdminListResponse,
    QuietPeriodDeleteRequest,
    QuietPeriodStatusResponse,
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
from app.services.incident_store import IncidentStore
from app.services.quiet_period_store import QuietPeriodStore
from app.services.report_store import AdminMessageRecord, ReportStore
from app.services.platform_admin_store import PlatformAdminStore
from app.services.school_registry import SchoolRegistry
from app.services.totp import generate_secret as generate_totp_secret, otpauth_uri, verify_code as verify_totp_code
from app.services.user_store import UserStore
from app.web.admin_views import (
    render_admin_page,
    render_change_password_page,
    render_login_page,
    render_super_admin_login_page,
    render_super_admin_page,
    render_totp_page,
)


router = APIRouter()
logger = logging.getLogger("bluebird.routes")
TRUST_DEVICE_TTL_SECONDS = 14 * 24 * 60 * 60
ADMIN_TRUST_COOKIE = "bluebird_admin_trusted_device"
SUPER_ADMIN_TRUST_COOKIE = "bluebird_super_admin_trusted_device"


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


def _incident_store(req: Request) -> IncidentStore:
    return req.state.tenant.incident_store  # type: ignore[attr-defined]


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


def _pending_admin_user_id(request: Request) -> Optional[int]:
    value = request.session.get("pending_admin_user_id")
    return int(value) if isinstance(value, int) or isinstance(value, str) and str(value).isdigit() else None


def _super_admin_id(request: Request) -> Optional[int]:
    value = request.session.get("super_admin_id")
    return int(value) if isinstance(value, int) or isinstance(value, str) and str(value).isdigit() else None


def _pending_super_admin_id(request: Request) -> Optional[int]:
    value = request.session.get("pending_super_admin_id")
    return int(value) if isinstance(value, int) or isinstance(value, str) and str(value).isdigit() else None


def _clear_pending_admin(request: Request) -> None:
    request.session.pop("pending_admin_user_id", None)


def _clear_pending_super_admin(request: Request) -> None:
    request.session.pop("pending_super_admin_id", None)


def _super_admin_school_slug(request: Request) -> Optional[str]:
    value = request.session.get("super_admin_school_slug")
    return str(value).strip() if isinstance(value, str) and str(value).strip() else None


def _clear_super_admin_school_scope(request: Request) -> None:
    request.session.pop("super_admin_school_slug", None)


def _set_flash(request: Request, *, message: Optional[str] = None, error: Optional[str] = None) -> None:
    request.session["admin_flash_message"] = message or ""
    request.session["admin_flash_error"] = error or ""


def _pop_flash(request: Request) -> tuple[Optional[str], Optional[str]]:
    message = str(request.session.pop("admin_flash_message", "") or "") or None
    error = str(request.session.pop("admin_flash_error", "") or "") or None
    return message, error


def _admin_section(value: Optional[str]) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"dashboard", "user-management", "quiet-periods", "audit-logs", "settings"}:
        return normalized
    return "dashboard"


def _super_admin_section(value: Optional[str]) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"schools", "platform-audit", "create-school", "security", "server-tools"}:
        return normalized
    return "schools"


def _super_admin_url(section: str, anchor: Optional[str] = None) -> str:
    resolved = _super_admin_section(section)
    suffix = anchor or resolved
    return f"/super-admin?section={resolved}#{suffix}"


def _quiet_hidden_ids(request: Request) -> set[int]:
    raw = request.session.get("admin_quiet_period_hidden_ids", [])
    if not isinstance(raw, list):
        return set()
    return {int(item) for item in raw if isinstance(item, (int, str)) and str(item).isdigit()}


def _set_quiet_hidden_ids(request: Request, ids: set[int]) -> None:
    request.session["admin_quiet_period_hidden_ids"] = sorted({int(item) for item in ids if int(item) > 0})


def _super_admin_ok(request: Request) -> bool:
    return bool(request.session.get("super_admin_id"))


def _require_super_admin(request: Request) -> None:
    if not _super_admin_ok(request):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/super-admin/login"})


def _school_prefix(request: Request) -> str:
    return str(getattr(request.state, "school_path_prefix", "") or "")


def _school_url(request: Request, suffix: str) -> str:
    normalized_suffix = suffix if suffix.startswith("/") else f"/{suffix}"
    return f"{_school_prefix(request)}{normalized_suffix}"


def _school_theme(school) -> dict[str, str]:
    return {
        "accent": getattr(school, "accent", None) or "",
        "accent_strong": getattr(school, "accent_strong", None) or "",
        "sidebar_start": getattr(school, "sidebar_start", None) or "",
        "sidebar_end": getattr(school, "sidebar_end", None) or "",
    }


def _super_admin_school_access_here(request: Request) -> bool:
    return _super_admin_ok(request) and _super_admin_school_slug(request) == str(getattr(request.state.school, "slug", "") or "")


def _current_school_actor_label(request: Request) -> Optional[str]:
    if _super_admin_school_access_here(request):
        actor = getattr(request.state, "super_admin_actor", None)
        login_name = getattr(actor, "login_name", None)
        return f"Platform Super Admin ({login_name})" if login_name else "Platform Super Admin"
    admin_user = getattr(request.state, "admin_user", None)
    if admin_user is None:
        return None
    login_name = getattr(admin_user, "login_name", None)
    name = getattr(admin_user, "name", None)
    if login_name:
        return str(login_name)
    if name:
        return str(name)
    return None


def _is_platform_actor_label(label: Optional[str]) -> bool:
    return bool(label and label.strip().lower().startswith("platform super admin"))


def _quiet_period_action_label(status: str) -> str:
    normalized = (status or "").strip().lower()
    if normalized == "approved":
        return "Quiet period approved"
    if normalized == "cleared":
        return "Quiet period removed"
    if normalized == "denied":
        return "Quiet period denied"
    if normalized == "expired":
        return "Quiet period expired"
    return f"Quiet period {normalized or 'updated'}"


async def _platform_activity_feed(
    request: Request,
    *,
    limit: int = 80,
) -> list[dict[str, str]]:
    schools = await _schools(request).list_schools()
    feed: list[dict[str, str]] = []
    for school in schools:
        tenant = request.app.state.tenant_manager.get(school)  # type: ignore[attr-defined]
        school_label = school.name or school.slug

        alerts = await tenant.alert_log.list_recent(limit=30)
        for alert in alerts:
            if not _is_platform_actor_label(alert.triggered_by_label):
                continue
            feed.append(
                {
                    "created_at": alert.created_at,
                    "school": school_label,
                    "action": "Alarm/Broadcast push",
                    "actor": alert.triggered_by_label or "Platform Super Admin",
                    "details": alert.message,
                }
            )

        broadcasts = await tenant.report_store.list_broadcast_updates(limit=30)
        for item in broadcasts:
            if not _is_platform_actor_label(item.admin_label):
                continue
            feed.append(
                {
                    "created_at": item.created_at,
                    "school": school_label,
                    "action": "Broadcast update",
                    "actor": item.admin_label or "Platform Super Admin",
                    "details": item.message,
                }
            )

        quiet_periods = await tenant.quiet_period_store.list_recent(limit=30)
        for item in quiet_periods:
            if not _is_platform_actor_label(item.approved_by_label):
                continue
            user = await tenant.user_store.get_user(item.user_id)
            user_label = user.name if user is not None else f"User #{item.user_id}"
            reason = f" ({item.reason})" if item.reason else ""
            feed.append(
                {
                    "created_at": item.approved_at or item.requested_at,
                    "school": school_label,
                    "action": _quiet_period_action_label(item.status),
                    "actor": item.approved_by_label or "Platform Super Admin",
                    "details": f"{user_label}{reason}",
                }
            )

        alarm_state = await tenant.alarm_store.get_state()
        if _is_platform_actor_label(alarm_state.activated_by_label) and alarm_state.activated_at:
            feed.append(
                {
                    "created_at": alarm_state.activated_at,
                    "school": school_label,
                    "action": "Alarm activated",
                    "actor": alarm_state.activated_by_label or "Platform Super Admin",
                    "details": alarm_state.message or "No message",
                }
            )
        if _is_platform_actor_label(alarm_state.deactivated_by_label) and alarm_state.deactivated_at:
            feed.append(
                {
                    "created_at": alarm_state.deactivated_at,
                    "school": school_label,
                    "action": "Alarm deactivated",
                    "actor": alarm_state.deactivated_by_label or "Platform Super Admin",
                    "details": alarm_state.message or "Alarm cleared",
                }
            )

    feed.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return feed[:max(1, int(limit))]


def _client_fingerprint(request: Request) -> str:
    user_agent = request.headers.get("user-agent", "").strip()
    return hashlib.sha256(user_agent.encode("utf-8")).hexdigest()


def _sign_trust_payload(request: Request, payload: dict[str, object]) -> str:
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(
        request.app.state.settings.SESSION_SECRET.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).digest()
    return (
        base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
        + "."
        + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    )


def _decode_trust_token(request: Request, token: str) -> Optional[dict[str, object]]:
    try:
        payload_b64, signature_b64 = token.split(".", 1)
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4))
        signature = base64.urlsafe_b64decode(signature_b64 + "=" * (-len(signature_b64) % 4))
    except Exception:
        return None
    expected_signature = hmac.new(
        request.app.state.settings.SESSION_SECRET.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature, expected_signature):
        return None
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or expires_at < int(time.time()):
        return None
    if payload.get("fp") != _client_fingerprint(request):
        return None
    return payload


def _issue_admin_trust_token(request: Request, *, user_id: int) -> str:
    school_slug = str(request.state.school.slug)
    return _sign_trust_payload(
        request,
        {
            "scope": "school-admin",
            "uid": user_id,
            "school": school_slug,
            "fp": _client_fingerprint(request),
            "exp": int(time.time()) + TRUST_DEVICE_TTL_SECONDS,
        },
    )


def _issue_super_admin_trust_token(request: Request, *, admin_id: int) -> str:
    return _sign_trust_payload(
        request,
        {
            "scope": "super-admin",
            "uid": admin_id,
            "fp": _client_fingerprint(request),
            "exp": int(time.time()) + TRUST_DEVICE_TTL_SECONDS,
        },
    )


def _is_admin_device_trusted(request: Request, *, user_id: int) -> bool:
    token = str(request.cookies.get(ADMIN_TRUST_COOKIE, "") or "").strip()
    if not token:
        return False
    payload = _decode_trust_token(request, token)
    return bool(
        payload
        and payload.get("scope") == "school-admin"
        and payload.get("uid") == user_id
        and payload.get("school") == str(request.state.school.slug)
    )


def _is_super_admin_device_trusted(request: Request, *, admin_id: int) -> bool:
    token = str(request.cookies.get(SUPER_ADMIN_TRUST_COOKIE, "") or "").strip()
    if not token:
        return False
    payload = _decode_trust_token(request, token)
    return bool(payload and payload.get("scope") == "super-admin" and payload.get("uid") == admin_id)


def _apply_admin_trust_cookie(request: Request, response: RedirectResponse, *, user_id: int) -> None:
    response.set_cookie(
        ADMIN_TRUST_COOKIE,
        _issue_admin_trust_token(request, user_id=user_id),
        max_age=TRUST_DEVICE_TTL_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path=_school_prefix(request) or "/",
    )


def _clear_admin_trust_cookie(request: Request, response: RedirectResponse) -> None:
    response.delete_cookie(
        ADMIN_TRUST_COOKIE,
        path=_school_prefix(request) or "/",
        secure=request.url.scheme == "https",
        samesite="lax",
    )


def _apply_super_admin_trust_cookie(request: Request, response: RedirectResponse, *, admin_id: int) -> None:
    response.set_cookie(
        SUPER_ADMIN_TRUST_COOKIE,
        _issue_super_admin_trust_token(request, admin_id=admin_id),
        max_age=TRUST_DEVICE_TTL_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/super-admin",
    )


def _clear_super_admin_trust_cookie(request: Request, response: RedirectResponse) -> None:
    response.delete_cookie(
        SUPER_ADMIN_TRUST_COOKIE,
        path="/super-admin",
        secure=request.url.scheme == "https",
        samesite="lax",
    )


async def _require_dashboard_admin(request: Request) -> UserStore:
    active_super_admin_id = _super_admin_id(request)
    active_super_admin_school_slug = _super_admin_school_slug(request)
    current_school_slug = str(getattr(request.state.school, "slug", "") or "")
    if active_super_admin_id is not None and active_super_admin_school_slug == current_school_slug:
        platform_admin = await _platform_admins(request).get_by_id(active_super_admin_id)
        if platform_admin is None:
            request.session.pop("super_admin_id", None)
            _clear_super_admin_school_scope(request)
            raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/super-admin/login"})
        request.state.super_admin_school_access = True
        request.state.super_admin_actor = platform_admin
        request.state.admin_user = SimpleNamespace(
            name=f"{platform_admin.login_name} (Super Admin)",
            login_name=platform_admin.login_name,
            role="super_admin",
        )
        return _users(request)
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
    request.state.super_admin_school_access = False
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


async def _require_dashboard_admin_id(users: UserStore, user_id: int) -> int:
    user = await users.get_user(int(user_id))
    if user is None or not user.is_active or user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only active admin users can perform this action")
    return user.id


async def _require_active_user_with_roles(users: UserStore, user_id: int, *, roles: set[str]) -> int:
    user = await users.get_user(int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active user is required")
    if user.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User does not have permission for this action")
    return user.id


async def _team_assist_target_user_ids(users: UserStore, assigned_team_ids: list[int]) -> list[int]:
    all_users = await users.list_users()
    active_users = [u for u in all_users if u.is_active]
    if assigned_team_ids:
        selected = set(int(item) for item in assigned_team_ids if int(item) > 0)
        return [u.id for u in active_users if u.id in selected]
    # Stage 2 baseline: fallback target is active admin responders.
    return [u.id for u in active_users if u.role == "admin"]


def _to_team_assist_summary(item) -> TeamAssistSummary:
    return TeamAssistSummary(
        id=item.id,
        type=item.type,
        created_by=item.created_by,
        assigned_team_ids=item.assigned_team_ids,
        status=item.status,
        created_at=item.created_at,
        acted_by_user_id=item.acted_by_user_id,
        acted_by_label=item.acted_by_label,
        forward_to_user_id=item.forward_to_user_id,
        forward_to_label=item.forward_to_label,
        cancel_requester_confirmed=bool(item.cancel_requester_confirmed_at),
        cancel_admin_confirmed=bool(item.cancel_admin_confirmed_at),
        cancel_admin_label=item.cancel_admin_label,
    )


def _to_quiet_period_summary(record) -> QuietPeriodSummary:
    return QuietPeriodSummary(
        request_id=record.id,
        user_id=record.user_id,
        reason=record.reason,
        status=record.status,
        requested_at=record.requested_at,
        approved_at=record.approved_at,
        approved_by_user_id=record.approved_by_user_id,
        approved_by_label=record.approved_by_label,
        expires_at=record.expires_at,
    )


async def _push_tokens_for_scope(
    request: Request,
    *,
    target_user_ids: Optional[set[int]] = None,
) -> tuple[list[str], list[str]]:
    paused_user_ids = set(await _quiet_periods(request).active_user_ids())
    apns_devices = await _registry(request).list_by_provider("apns")
    fcm_devices = await _registry(request).list_by_provider("fcm")

    def _allow_user(user_id: Optional[int]) -> bool:
        if user_id is not None and user_id in paused_user_ids:
            return False
        if target_user_ids is None:
            return user_id is None or user_id > 0
        if user_id is None:
            return False
        return user_id in target_user_ids

    apns_tokens = [device.token for device in apns_devices if _allow_user(device.user_id)]
    fcm_tokens = [device.token for device in fcm_devices if _allow_user(device.user_id)]
    return list(dict.fromkeys(apns_tokens)), list(dict.fromkeys(fcm_tokens))


async def _send_basic_push(
    request: Request,
    *,
    message: str,
    target_user_ids: Optional[set[int]] = None,
) -> None:
    apns_tokens, fcm_tokens = await _push_tokens_for_scope(request, target_user_ids=target_user_ids)
    if apns_tokens:
        await _apns(request).send_bulk(apns_tokens, message)
    if fcm_tokens:
        await _fcm(request).send_bulk(fcm_tokens, message)


def _to_admin_inbox_item(item: AdminMessageRecord) -> AdminMessageInboxItem:
    return AdminMessageInboxItem(
        message_id=item.id,
        created_at=item.created_at,
        sender_user_id=item.sender_user_id,
        sender_label=item.sender_label,
        message=item.message,
        status=item.status,
        response_message=item.response_message,
        response_created_at=item.response_created_at,
        response_by_user_id=item.response_by_user_id,
        response_by_label=item.response_by_label,
    )


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


@router.get("/config/labels")
async def config_labels(_: None = Depends(require_api_key)) -> dict[str, str]:
    return FEATURE_LABELS


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
        activated_by_label=state.activated_by_label,
        deactivated_at=state.deactivated_at,
        deactivated_by_user_id=state.deactivated_by_user_id,
        deactivated_by_label=state.deactivated_by_label,
        broadcasts=[
            BroadcastUpdateSummary(
                update_id=item.id,
                created_at=item.created_at,
                admin_user_id=item.admin_user_id,
                admin_label=item.admin_label,
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
        triggered_by_label=_current_school_actor_label(request),
        trigger_ip=trigger_ip,
        trigger_user_agent=trigger_user_agent,
    )
    state = await _alarm_store(request).activate(
        message=body.message,
        activated_by_user_id=triggered_by_user_id,
        activated_by_label=_current_school_actor_label(request),
    )

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
        activated_by_label=state.activated_by_label,
        deactivated_at=state.deactivated_at,
        deactivated_by_user_id=state.deactivated_by_user_id,
        deactivated_by_label=state.deactivated_by_label,
    )


@router.post("/alarm/deactivate", response_model=AlarmStatusResponse)
async def deactivate_alarm(
    body: AlarmDeactivateRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> AlarmStatusResponse:
    admin_user_id = await _require_admin_user(_users(request), body.user_id)
    state = await _alarm_store(request).deactivate(
        deactivated_by_user_id=admin_user_id,
        deactivated_by_label=_current_school_actor_label(request),
    )
    logger.warning("ALARM DEACTIVATED by_user=%s", admin_user_id)
    return AlarmStatusResponse(
        is_active=state.is_active,
        message=state.message,
        activated_at=state.activated_at,
        activated_by_user_id=state.activated_by_user_id,
        activated_by_label=state.activated_by_label,
        deactivated_at=state.deactivated_at,
        deactivated_by_user_id=state.deactivated_by_user_id,
        deactivated_by_label=state.deactivated_by_label,
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
async def admin_dashboard(
    request: Request,
    section: str = Query(default="dashboard"),
) -> HTMLResponse:
    if _session_user_id(request) is None and not _super_admin_school_access_here(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    await _require_dashboard_admin(request)
    devices = await _registry(request).list_devices()
    alerts = await _alert_log(request).list_recent(limit=20)
    users = await _users(request).list_users()
    alarm_state = await _alarm_store(request).get_state()
    reports = await _reports(request).list_reports(limit=25)
    broadcasts = await _reports(request).list_broadcast_updates(limit=10)
    admin_messages = await _reports(request).list_admin_messages(limit=40)
    unread_admin_messages = sum(1 for item in admin_messages if item.status == "open")
    quiet_periods_all = await _quiet_periods(request).list_recent(limit=200)
    hidden_ids = _quiet_hidden_ids(request)
    quiet_periods_active = [
        item for item in quiet_periods_all if item.status in {"pending", "approved"} and item.id not in hidden_ids
    ]
    quiet_periods_history = [item for item in quiet_periods_all if item.status not in {"pending", "approved"}]
    selected_section = _admin_section(section)
    flash_message, flash_error = _pop_flash(request)
    html = render_admin_page(
        school_name=request.state.school.name,
        school_slug=request.state.school.slug,
        school_path_prefix=_school_prefix(request),
        theme=_school_theme(request.state.school),
        current_user=request.state.admin_user,  # type: ignore[attr-defined]
        alerts=alerts,
        devices=devices,
        users=users,
        alarm_state=alarm_state,
        reports=reports,
        broadcasts=broadcasts,
        admin_messages=admin_messages,
        unread_admin_messages=unread_admin_messages,
        quiet_periods_active=quiet_periods_active,
        quiet_periods_history=quiet_periods_history,
        quiet_periods_hidden_count=len(hidden_ids),
        apns_configured=_apns(request).is_configured(),
        twilio_configured=_broadcaster(request).twilio_configured(),
        server_info=_build_server_info(request),
        totp_enabled=bool(getattr(request.state.admin_user, "totp_enabled", False)),  # type: ignore[attr-defined]
        totp_setup_secret=str(request.session.get("admin_totp_setup_secret", "") or "") or None,
        totp_setup_uri=(
            otpauth_uri(
                str(request.session.get("admin_totp_setup_secret", "") or "").strip(),
                request.state.admin_user.login_name or request.state.admin_user.name,  # type: ignore[attr-defined]
                issuer=f"BlueBird Alerts ({request.state.school.slug})",
            )
            if str(request.session.get("admin_totp_setup_secret", "") or "").strip()
            else None
        ),
        flash_message=flash_message,
        flash_error=flash_error,
        super_admin_mode=bool(getattr(request.state, "super_admin_school_access", False)),
        super_admin_actor_name=(
            getattr(getattr(request.state, "super_admin_actor", None), "login_name", None)
            if getattr(request.state, "super_admin_school_access", False)
            else None
        ),
        active_section=selected_section,
    )
    return HTMLResponse(content=html)


@router.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
async def admin_login_page(request: Request) -> HTMLResponse:
    if _super_admin_school_access_here(request):
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
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
            theme=_school_theme(request.state.school),
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
    if user.totp_enabled:
        if _is_admin_device_trusted(request, user_id=user.id):
            request.session["admin_user_id"] = user.id
            _clear_pending_admin(request)
            await _users(request).mark_login(user.id)
            response = RedirectResponse(
                url=_school_url(request, "/admin/change-password") if user.must_change_password else _school_url(request, "/admin"),
                status_code=status.HTTP_303_SEE_OTHER,
            )
            _set_flash(request, message="Trusted device recognized. Two-factor verification skipped for this device.")
            return response
        request.session["pending_admin_user_id"] = user.id
        return RedirectResponse(url="/admin/totp", status_code=status.HTTP_303_SEE_OTHER)
    request.session["admin_user_id"] = user.id
    _clear_pending_admin(request)
    await _users(request).mark_login(user.id)
    if user.must_change_password:
        return RedirectResponse(url="/admin/change-password", status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message=f"Welcome back, {user.name}.")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/totp", response_class=HTMLResponse, include_in_schema=False)
async def admin_totp_page(request: Request) -> HTMLResponse:
    pending_user_id = _pending_admin_user_id(request)
    if pending_user_id is None:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    user = await _users(request).get_user(pending_user_id)
    if user is None or not user.is_active or user.role != "admin" or not user.totp_enabled:
        _clear_pending_admin(request)
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    flash_message, flash_error = _pop_flash(request)
    return HTMLResponse(
        render_totp_page(
            action=_school_url(request, "/admin/totp"),
            cancel_action=_school_url(request, "/admin/login"),
            title="BlueBird Admin 2FA",
            eyebrow="School Safety Command Deck",
            heading="Two-factor verification",
            helper="Open your authenticator app and enter the current 6-digit code to finish signing in.",
            user_label=user.login_name or user.name,
            message=flash_message,
            error=flash_error,
            theme=_school_theme(request.state.school),
            allow_trust_device=True,
        )
    )


@router.post("/admin/totp", include_in_schema=False)
async def admin_totp_submit(
    request: Request,
    code: str = Form(...),
    trust_device: Optional[str] = Form(default=None),
) -> RedirectResponse:
    pending_user_id = _pending_admin_user_id(request)
    if pending_user_id is None:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    user = await _users(request).get_user(pending_user_id)
    secret = await _users(request).get_totp_secret(pending_user_id)
    if user is None or secret is None or not verify_totp_code(secret, code):
        _set_flash(request, error="Invalid authenticator code.")
        return RedirectResponse(url="/admin/totp", status_code=status.HTTP_303_SEE_OTHER)
    request.session["admin_user_id"] = user.id
    _clear_pending_admin(request)
    await _users(request).mark_login(user.id)
    response = RedirectResponse(
        url=_school_url(request, "/admin/change-password") if user.must_change_password else _school_url(request, "/admin"),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    if trust_device == "1":
        _apply_admin_trust_cookie(request, response, user_id=user.id)
        _set_flash(request, message=f"Welcome back, {user.name}. This device is trusted for 14 days.")
    else:
        _clear_admin_trust_cookie(request, response)
        _set_flash(request, message=f"Welcome back, {user.name}.")
    if user.must_change_password:
        return response
    return response


@router.post("/admin/logout", include_in_schema=False)
async def admin_logout(request: Request) -> RedirectResponse:
    request.session.clear()
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    _clear_admin_trust_cookie(request, response)
    return response


@router.get("/admin/totp/status")
async def admin_totp_status(request: Request) -> dict[str, object]:
    if _super_admin_school_access_here(request):
        return {"ok": False, "error": "School-admin 2FA settings are not available during super admin access."}
    await _require_dashboard_admin(request)
    user = request.state.admin_user  # type: ignore[attr-defined]
    return {"ok": True, "enabled": bool(getattr(user, "totp_enabled", False))}


@router.post("/admin/totp/setup")
async def admin_totp_setup(request: Request) -> dict[str, object]:
    if _super_admin_school_access_here(request):
        return {"ok": False, "error": "School-admin 2FA settings are not available during super admin access."}
    await _require_dashboard_admin(request)
    user = request.state.admin_user  # type: ignore[attr-defined]
    if bool(getattr(user, "totp_enabled", False)):
        return {"ok": False, "error": "Two-factor authentication is already enabled."}
    secret = generate_totp_secret()
    request.session["admin_totp_setup_secret"] = secret
    label = user.login_name or user.name
    issuer = f"BlueBird Alerts ({request.state.school.slug})"
    return {"ok": True, "secret": secret, "otpauth_uri": otpauth_uri(secret, label, issuer=issuer)}


@router.post("/admin/totp/setup-form", include_in_schema=False)
async def admin_totp_setup_form(request: Request) -> RedirectResponse:
    if _super_admin_school_access_here(request):
        _set_flash(request, error="School-admin 2FA settings are not available during super admin access.")
        return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
    await _require_dashboard_admin(request)
    user = request.state.admin_user  # type: ignore[attr-defined]
    if bool(getattr(user, "totp_enabled", False)):
        _set_flash(request, error="Two-factor authentication is already enabled.")
        return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
    request.session["admin_totp_setup_secret"] = generate_totp_secret()
    _set_flash(request, message="Authenticator setup secret generated. Add it to your app, then confirm with a 6-digit code.")
    return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/totp/enable")
async def admin_totp_enable(
    request: Request,
    code: str = Form(...),
) -> dict[str, object]:
    if _super_admin_school_access_here(request):
        return {"ok": False, "error": "School-admin 2FA settings are not available during super admin access."}
    await _require_dashboard_admin(request)
    user = request.state.admin_user  # type: ignore[attr-defined]
    secret = str(request.session.get("admin_totp_setup_secret", "") or "").strip()
    if not secret:
        return {"ok": False, "error": "Start TOTP setup first."}
    if not verify_totp_code(secret, code):
        return {"ok": False, "error": "Invalid authenticator code."}
    await _users(request).set_totp_secret(user.id, secret)
    request.session.pop("admin_totp_setup_secret", None)
    return {"ok": True, "enabled": True}


@router.post("/admin/totp/enable-form", include_in_schema=False)
async def admin_totp_enable_form(
    request: Request,
    code: str = Form(default=""),
) -> RedirectResponse:
    if _super_admin_school_access_here(request):
        _set_flash(request, error="School-admin 2FA settings are not available during super admin access.")
        return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
    await _require_dashboard_admin(request)
    user = request.state.admin_user  # type: ignore[attr-defined]
    secret = str(request.session.get("admin_totp_setup_secret", "") or "").strip()
    if not secret:
        _set_flash(request, error="Start TOTP setup first.")
        return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
    if not code.strip():
        _set_flash(request, error="Enter the 6-digit authenticator code.")
        return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
    if not verify_totp_code(secret, code):
        _set_flash(request, error="Invalid authenticator code.")
        return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
    await _users(request).set_totp_secret(user.id, secret)
    request.session.pop("admin_totp_setup_secret", None)
    _set_flash(request, message="Two-factor authentication is now enabled for your admin account.")
    return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/totp/disable")
async def admin_totp_disable(
    request: Request,
    current_password: str = Form(...),
) -> dict[str, object]:
    if _super_admin_school_access_here(request):
        return {"ok": False, "error": "School-admin 2FA settings are not available during super admin access."}
    await _require_dashboard_admin(request)
    user = request.state.admin_user  # type: ignore[attr-defined]
    if not await _users(request).verify_current_password(user.id, current_password):
        return {"ok": False, "error": "Current password is incorrect."}
    await _users(request).set_totp_secret(user.id, None)
    request.session.pop("admin_totp_setup_secret", None)
    return {"ok": True, "enabled": False}


@router.post("/admin/totp/disable-form", include_in_schema=False)
async def admin_totp_disable_form(
    request: Request,
    current_password: str = Form(default=""),
) -> RedirectResponse:
    if _super_admin_school_access_here(request):
        _set_flash(request, error="School-admin 2FA settings are not available during super admin access.")
        return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
    await _require_dashboard_admin(request)
    user = request.state.admin_user  # type: ignore[attr-defined]
    if not current_password.strip():
        _set_flash(request, error="Enter your current password to disable 2FA.")
        return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
    if not await _users(request).verify_current_password(user.id, current_password):
        _set_flash(request, error="Current password is incorrect.")
        return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
    await _users(request).set_totp_secret(user.id, None)
    request.session.pop("admin_totp_setup_secret", None)
    _set_flash(request, message="Two-factor authentication has been disabled for your admin account.")
    response = RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
    _clear_admin_trust_cookie(request, response)
    return response


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
    if admin.totp_enabled:
        if _is_super_admin_device_trusted(request, admin_id=admin.id):
            request.session["super_admin_id"] = admin.id
            _clear_pending_super_admin(request)
            await _platform_admins(request).mark_login(admin.id)
            response = RedirectResponse(
                url="/super-admin/change-password" if admin.must_change_password else "/super-admin",
                status_code=status.HTTP_303_SEE_OTHER,
            )
            _set_flash(request, message="Trusted device recognized. Two-factor verification skipped for this device.")
            return response
        request.session["pending_super_admin_id"] = admin.id
        return RedirectResponse(url="/super-admin/totp", status_code=status.HTTP_303_SEE_OTHER)
    request.session["super_admin_id"] = admin.id
    _clear_pending_super_admin(request)
    await _platform_admins(request).mark_login(admin.id)
    if admin.must_change_password:
        _set_flash(request, message="Please change your temporary super admin password before continuing.")
        return RedirectResponse(url="/super-admin/change-password", status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message="Signed in to super admin.")
    return RedirectResponse(url="/super-admin", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/super-admin/totp", response_class=HTMLResponse, include_in_schema=False)
async def super_admin_totp_page(request: Request) -> HTMLResponse:
    pending_admin_id = _pending_super_admin_id(request)
    if pending_admin_id is None:
        return RedirectResponse(url="/super-admin/login", status_code=status.HTTP_303_SEE_OTHER)
    admin = await _platform_admins(request).get_by_id(pending_admin_id)
    if admin is None or not admin.totp_enabled:
        _clear_pending_super_admin(request)
        return RedirectResponse(url="/super-admin/login", status_code=status.HTTP_303_SEE_OTHER)
    flash_message, flash_error = _pop_flash(request)
    return HTMLResponse(
        render_totp_page(
            action="/super-admin/totp",
            cancel_action="/super-admin/login",
            title="BlueBird Super Admin 2FA",
            eyebrow="Platform Control",
            heading="Two-factor verification",
            helper="Open your authenticator app and enter the current 6-digit code to finish signing in.",
            user_label=admin.login_name,
            message=flash_message,
            error=flash_error,
            allow_trust_device=True,
        )
    )


@router.post("/super-admin/totp", include_in_schema=False)
async def super_admin_totp_submit(
    request: Request,
    code: str = Form(...),
    trust_device: Optional[str] = Form(default=None),
) -> RedirectResponse:
    pending_admin_id = _pending_super_admin_id(request)
    if pending_admin_id is None:
        return RedirectResponse(url="/super-admin/login", status_code=status.HTTP_303_SEE_OTHER)
    admin = await _platform_admins(request).get_by_id(pending_admin_id)
    secret = await _platform_admins(request).get_totp_secret(pending_admin_id)
    if admin is None or secret is None or not verify_totp_code(secret, code):
        _set_flash(request, error="Invalid authenticator code.")
        return RedirectResponse(url="/super-admin/totp", status_code=status.HTTP_303_SEE_OTHER)
    request.session["super_admin_id"] = admin.id
    _clear_pending_super_admin(request)
    await _platform_admins(request).mark_login(admin.id)
    response = RedirectResponse(
        url="/super-admin/change-password" if admin.must_change_password else "/super-admin",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    if trust_device == "1":
        _apply_super_admin_trust_cookie(request, response, admin_id=admin.id)
        _set_flash(request, message="Signed in to super admin. This device is trusted for 14 days.")
    else:
        _clear_super_admin_trust_cookie(request, response)
        _set_flash(request, message="Signed in to super admin.")
    if admin.must_change_password:
        return response
    return response


@router.post("/super-admin/logout", include_in_schema=False)
async def super_admin_logout(request: Request) -> RedirectResponse:
    request.session.pop("super_admin_id", None)
    _clear_pending_super_admin(request)
    _clear_super_admin_school_scope(request)
    response = RedirectResponse(url="/super-admin/login", status_code=status.HTTP_303_SEE_OTHER)
    _clear_super_admin_trust_cookie(request, response)
    return response


@router.get("/super-admin/totp/status")
async def super_admin_totp_status(request: Request) -> dict[str, object]:
    _require_super_admin(request)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    return {"ok": True, "enabled": bool(admin.totp_enabled) if admin else False}


@router.post("/super-admin/totp/setup")
async def super_admin_totp_setup(request: Request) -> dict[str, object]:
    _require_super_admin(request)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    if admin is None:
        return {"ok": False, "error": "Super admin account not found."}
    if admin.totp_enabled:
        return {"ok": False, "error": "Two-factor authentication is already enabled."}
    secret = generate_totp_secret()
    request.session["super_admin_totp_setup_secret"] = secret
    return {"ok": True, "secret": secret, "otpauth_uri": otpauth_uri(secret, admin.login_name, issuer="BlueBird Alerts")}


@router.post("/super-admin/totp/setup-form", include_in_schema=False)
async def super_admin_totp_setup_form(request: Request) -> RedirectResponse:
    _require_super_admin(request)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    if admin is None:
        _set_flash(request, error="Super admin account not found.")
        return RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)
    if admin.totp_enabled:
        _set_flash(request, error="Two-factor authentication is already enabled.")
        return RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)
    request.session["super_admin_totp_setup_secret"] = generate_totp_secret()
    _set_flash(request, message="Authenticator setup secret generated. Add it to your app, then confirm with a 6-digit code.")
    return RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/totp/enable")
async def super_admin_totp_enable(
    request: Request,
    code: str = Form(...),
) -> dict[str, object]:
    _require_super_admin(request)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    if admin is None:
        return {"ok": False, "error": "Super admin account not found."}
    secret = str(request.session.get("super_admin_totp_setup_secret", "") or "").strip()
    if not secret:
        return {"ok": False, "error": "Start TOTP setup first."}
    if not verify_totp_code(secret, code):
        return {"ok": False, "error": "Invalid authenticator code."}
    await _platform_admins(request).set_totp_secret(admin.id, secret)
    request.session.pop("super_admin_totp_setup_secret", None)
    return {"ok": True, "enabled": True}


@router.post("/super-admin/totp/enable-form", include_in_schema=False)
async def super_admin_totp_enable_form(
    request: Request,
    code: str = Form(default=""),
) -> RedirectResponse:
    _require_super_admin(request)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    if admin is None:
        _set_flash(request, error="Super admin account not found.")
        return RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)
    secret = str(request.session.get("super_admin_totp_setup_secret", "") or "").strip()
    if not secret:
        _set_flash(request, error="Start TOTP setup first.")
        return RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)
    if not code.strip():
        _set_flash(request, error="Enter the 6-digit authenticator code.")
        return RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)
    if not verify_totp_code(secret, code):
        _set_flash(request, error="Invalid authenticator code.")
        return RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)
    await _platform_admins(request).set_totp_secret(admin.id, secret)
    request.session.pop("super_admin_totp_setup_secret", None)
    _set_flash(request, message="Two-factor authentication is now enabled for the super admin account.")
    return RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/totp/disable")
async def super_admin_totp_disable(
    request: Request,
    current_password: str = Form(...),
) -> dict[str, object]:
    _require_super_admin(request)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    if admin is None:
        return {"ok": False, "error": "Super admin account not found."}
    if not await _platform_admins(request).verify_current_password(admin.id, current_password):
        return {"ok": False, "error": "Current password is incorrect."}
    await _platform_admins(request).set_totp_secret(admin.id, None)
    request.session.pop("super_admin_totp_setup_secret", None)
    return {"ok": True, "enabled": False}


@router.post("/super-admin/totp/disable-form", include_in_schema=False)
async def super_admin_totp_disable_form(
    request: Request,
    current_password: str = Form(default=""),
) -> RedirectResponse:
    _require_super_admin(request)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    if admin is None:
        _set_flash(request, error="Super admin account not found.")
        return RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)
    if not current_password.strip():
        _set_flash(request, error="Enter your current password to disable 2FA.")
        return RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)
    if not await _platform_admins(request).verify_current_password(admin.id, current_password):
        _set_flash(request, error="Current password is incorrect.")
        return RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)
    await _platform_admins(request).set_totp_secret(admin.id, None)
    request.session.pop("super_admin_totp_setup_secret", None)
    _set_flash(request, message="Two-factor authentication has been disabled for the super admin account.")
    response = RedirectResponse(url=_super_admin_url("security"), status_code=status.HTTP_303_SEE_OTHER)
    _clear_super_admin_trust_cookie(request, response)
    return response


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
    response = RedirectResponse(url="/super-admin", status_code=status.HTTP_303_SEE_OTHER)
    _clear_super_admin_trust_cookie(request, response)
    return response


@router.get("/super-admin", response_class=HTMLResponse, include_in_schema=False)
async def super_admin_dashboard(
    request: Request,
    section: str = Query(default="schools"),
) -> HTMLResponse:
    _require_super_admin(request)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    if admin and admin.must_change_password:
        return RedirectResponse(url="/super-admin/change-password", status_code=status.HTTP_303_SEE_OTHER)
    flash_message, flash_error = _pop_flash(request)
    schools = await _schools(request).list_schools()
    platform_activity_rows = await _platform_activity_feed(request, limit=120)
    base_domain = str(request.app.state.settings.BASE_DOMAIN).strip().lower()  # type: ignore[attr-defined]
    school_rows: list[dict[str, object]] = []
    for school in schools:
        school_prefix = f"/{school.slug}"
        admin_count = await request.app.state.tenant_manager.get(school).user_store.count_dashboard_admins()  # type: ignore[attr-defined]
        admin_url = f"https://{base_domain}{school_prefix}/admin"
        access_controls_html = f"""
            <form method="post" action="/super-admin/schools/{school.slug}/enter" style="margin-top:10px;">
              <div class="button-row">
                <button class="button button-primary" type="submit">Open Admin as Super Admin</button>
              </div>
            </form>
        """
        pin_controls_html = (
            f"""
            <form method="post" action="/super-admin/schools/{school.slug}/setup-pin" class="stack" style="margin-top:10px;">
              <div class="field">
                <label>Update setup PIN</label>
                <input name="setup_pin" type="password" placeholder="New PIN" />
              </div>
              <div class="button-row">
                <button class="button button-secondary" type="submit">Save PIN</button>
              </div>
            </form>
            <form method="post" action="/super-admin/schools/{school.slug}/setup-pin/clear" style="margin-top:10px;" onsubmit="return confirm('Clear the setup PIN for {school.name}?');">
              <div class="button-row">
                <button class="button button-danger-outline" type="submit">Clear PIN</button>
              </div>
            </form>
            """
        )
        theme_controls_html = f"""
            <form method="post" action="/super-admin/schools/{school.slug}/theme" class="stack" style="margin-top:10px;">
              <div class="form-grid">
                <div class="field">
                  <label>Accent</label>
                  <input name="accent" value="{escape(school.accent or '')}" placeholder="#1b5fe4" />
                </div>
                <div class="field">
                  <label>Accent strong</label>
                  <input name="accent_strong" value="{escape(school.accent_strong or '')}" placeholder="#2f84ff" />
                </div>
                <div class="field">
                  <label>Sidebar start</label>
                  <input name="sidebar_start" value="{escape(school.sidebar_start or '')}" placeholder="#092054" />
                </div>
                <div class="field">
                  <label>Sidebar end</label>
                  <input name="sidebar_end" value="{escape(school.sidebar_end or '')}" placeholder="#071536" />
                </div>
              </div>
              <div class="button-row">
                <button class="button button-secondary" type="submit">Save Theme</button>
              </div>
            </form>
        """
        school_rows.append(
            {
                "name": school.name,
                "slug": school.slug,
                "admin_url": admin_url,
                "admin_url_label": f"{base_domain}{school_prefix}/admin",
                "api_base_label": f"{base_domain}{school_prefix}",
                "access_controls_html": access_controls_html,
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
                "pin_controls_html": pin_controls_html,
                "theme_controls_html": theme_controls_html,
                "is_active": school.is_active,
            }
        )
    return HTMLResponse(
        render_super_admin_page(
            base_domain=request.app.state.settings.BASE_DOMAIN,  # type: ignore[attr-defined]
            school_rows=school_rows,
            platform_activity_rows=platform_activity_rows,
            git_pull_configured=bool(request.app.state.settings.SERVER_GIT_PULL_COMMAND),  # type: ignore[attr-defined]
            server_info=_build_server_info(request),
            super_admin_login_name=admin.login_name if admin else "superadmin",
            totp_enabled=bool(admin.totp_enabled) if admin else False,
            totp_setup_secret=str(request.session.get("super_admin_totp_setup_secret", "") or "") or None,
            totp_setup_uri=(
                otpauth_uri(
                    str(request.session.get("super_admin_totp_setup_secret", "") or "").strip(),
                    admin.login_name,
                    issuer="BlueBird Alerts",
                )
                if admin and str(request.session.get("super_admin_totp_setup_secret", "") or "").strip()
                else None
            ),
            flash_message=flash_message,
            flash_error=flash_error,
            active_section=_super_admin_section(section),
        )
    )


@router.get("/super-admin/audit-feed", include_in_schema=False)
async def super_admin_audit_feed(
    request: Request,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict[str, object]:
    _require_super_admin(request)
    items = await _platform_activity_feed(request, limit=limit)
    return {"count": len(items), "items": items}


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
        return RedirectResponse(url=_super_admin_url("create-school"), status_code=status.HTTP_303_SEE_OTHER)
    if not normalized_slug:
        _set_flash(request, error="School slug is required.")
        return RedirectResponse(url=_super_admin_url("create-school"), status_code=status.HTTP_303_SEE_OTHER)
    normalized_pin = setup_pin.strip()
    if normalized_pin and len(normalized_pin) < 4:
        _set_flash(request, error="Setup PIN must be at least 4 characters.")
        return RedirectResponse(url=_super_admin_url("create-school"), status_code=status.HTTP_303_SEE_OTHER)
    try:
        school = await _schools(request).create_school(
            slug=normalized_slug,
            name=normalized_name,
            setup_pin=normalized_pin or None,
        )
    except Exception as exc:
        _set_flash(request, error=f"Could not create school: {exc}")
        return RedirectResponse(url=_super_admin_url("create-school"), status_code=status.HTTP_303_SEE_OTHER)
    base_domain = str(request.app.state.settings.BASE_DOMAIN).strip().lower()  # type: ignore[attr-defined]
    admin_url = f"https://{base_domain}/{school.slug}/admin"
    _set_flash(
        request,
        message=(
            f"Created school {school.name}. School admin URL: {admin_url}."
            + (" A setup PIN was saved for first-admin creation." if school.setup_pin_required else "")
        ),
    )
    return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/schools/{slug}/setup-pin", include_in_schema=False)
async def super_admin_update_setup_pin(
    request: Request,
    slug: str,
    setup_pin: str = Form(...),
) -> RedirectResponse:
    _require_super_admin(request)
    from app.services.tenant_manager import normalize_school_slug

    normalized_slug = normalize_school_slug(slug)
    normalized_pin = setup_pin.strip()
    if not normalized_pin:
        _set_flash(request, error="Enter a setup PIN to save, or use Clear PIN instead.")
        return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)
    if len(normalized_pin) < 4:
        _set_flash(request, error="Setup PIN must be at least 4 characters.")
        return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)
    school = await _schools(request).set_setup_pin(slug=normalized_slug, setup_pin=normalized_pin)
    if school is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message=f"Updated the setup PIN for {school.name}.")
    return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/schools/{slug}/setup-pin/clear", include_in_schema=False)
async def super_admin_clear_setup_pin(
    request: Request,
    slug: str,
) -> RedirectResponse:
    _require_super_admin(request)
    from app.services.tenant_manager import normalize_school_slug

    normalized_slug = normalize_school_slug(slug)
    school = await _schools(request).set_setup_pin(slug=normalized_slug, setup_pin=None)
    if school is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message=f"Cleared the setup PIN for {school.name}.")
    return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/schools/{slug}/theme", include_in_schema=False)
async def super_admin_update_school_theme(
    request: Request,
    slug: str,
    accent: str = Form(default=""),
    accent_strong: str = Form(default=""),
    sidebar_start: str = Form(default=""),
    sidebar_end: str = Form(default=""),
) -> RedirectResponse:
    _require_super_admin(request)
    from app.services.tenant_manager import normalize_school_slug

    normalized_slug = normalize_school_slug(slug)
    school = await _schools(request).update_theme(
        slug=normalized_slug,
        accent=accent.strip() or None,
        accent_strong=accent_strong.strip() or None,
        sidebar_start=sidebar_start.strip() or None,
        sidebar_end=sidebar_end.strip() or None,
    )
    if school is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message=f"Updated the theme for {school.name}.")
    return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/schools/{slug}/enter", include_in_schema=False)
async def super_admin_enter_school(
    request: Request,
    slug: str,
) -> RedirectResponse:
    _require_super_admin(request)
    from app.services.tenant_manager import normalize_school_slug

    normalized_slug = normalize_school_slug(slug)
    school = await _schools(request).get_by_slug(normalized_slug)
    if school is None or not school.is_active:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)
    request.session["super_admin_school_slug"] = school.slug
    request.session.pop("admin_user_id", None)
    request.session.pop("pending_admin_user_id", None)
    request.session.pop("admin_totp_setup_secret", None)
    _set_flash(request, message=f"Entered {school.name} as super admin.")
    return RedirectResponse(url=f"/{school.slug}/admin", status_code=status.HTTP_303_SEE_OTHER)


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
        return RedirectResponse(url=_super_admin_url("server-tools"), status_code=status.HTTP_303_SEE_OTHER)
    background_tasks.add_task(_run_server_command, command)
    _set_flash(request, message="Server git pull started in the background.")
    return RedirectResponse(url=_super_admin_url("server-tools"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/server/restart", include_in_schema=False)
async def super_admin_restart(
    request: Request,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    _require_super_admin(request)
    command = request.app.state.settings.SERVER_RESTART_COMMAND
    background_tasks.add_task(_do_restart, command)
    _set_flash(request, message="Restart initiated. The service will be back in a few seconds.")
    return RedirectResponse(url=_super_admin_url("server-tools"), status_code=status.HTTP_303_SEE_OTHER)


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


@router.post("/admin/super-admin/exit", include_in_schema=False)
async def admin_exit_super_admin_access(request: Request) -> RedirectResponse:
    if _super_admin_ok(request):
        _clear_super_admin_school_scope(request)
    request.session.pop("admin_user_id", None)
    request.session.pop("pending_admin_user_id", None)
    request.session.pop("admin_totp_setup_secret", None)
    _set_flash(request, message="Returned to the super admin console.")
    return RedirectResponse(url="/super-admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/server/restart", include_in_schema=False)
async def server_restart(request: Request, background_tasks: BackgroundTasks) -> RedirectResponse:
    await _require_dashboard_admin(request)
    command = request.app.state.settings.SERVER_RESTART_COMMAND
    background_tasks.add_task(_do_restart, command)
    _set_flash(request, message="Restart initiated. The service will be back in a few seconds.")
    return RedirectResponse(url="/admin#server", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/change-password", response_class=HTMLResponse, include_in_schema=False)
async def change_password_page(request: Request) -> HTMLResponse:
    if _super_admin_school_access_here(request):
        _set_flash(request, error="School-admin password changes are not available during super admin access.")
        return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
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
            theme=_school_theme(request.state.school),
        )
    )


@router.post("/admin/change-password", include_in_schema=False)
async def change_password_submit(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> RedirectResponse:
    if _super_admin_school_access_here(request):
        _set_flash(request, error="School-admin password changes are not available during super admin access.")
        return RedirectResponse(url=_school_url(request, "/admin#security"), status_code=status.HTTP_303_SEE_OTHER)
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
    response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    _clear_admin_trust_cookie(request, response)
    return response


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
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    if normalized_role not in {"admin", "teacher"}:
        _set_flash(request, error="Role must be admin or teacher.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    if bool(login_name.strip()) != bool(password.strip()):
        _set_flash(request, error="Provide both username and password to enable login for a user.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
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
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message=f"Created user {normalized_name}.")
    return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)


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
    if bool(getattr(request.state, "super_admin_school_access", False)):
        await _alarm_store(request).deactivate(
            deactivated_by_user_id=None,
            deactivated_by_label=_current_school_actor_label(request),
        )
    else:
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
        admin_label=_current_school_actor_label(request),
        message=normalized_message,
    )
    if send_push == "1":
        admin_user_id = _session_user_id(request)
        trigger_ip = request.client.host if request.client else None
        trigger_user_agent = request.headers.get("user-agent")
        alert_id = await _alert_log(request).log_alert(
            normalized_message,
            triggered_by_user_id=admin_user_id,
            triggered_by_label=_current_school_actor_label(request),
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


@router.post("/admin/messages/{message_id}/reply", include_in_schema=False)
async def admin_reply_message(
    request: Request,
    message_id: int,
    message: str = Form(...),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    reply_text = message.strip()
    if not reply_text:
        _set_flash(request, error="Reply message cannot be empty.")
        return RedirectResponse(url="/admin#messages", status_code=status.HTTP_303_SEE_OTHER)
    admin_id = _session_user_id(request)
    reply = await _reports(request).reply_admin_message(
        message_id=message_id,
        response_message=reply_text,
        response_by_user_id=admin_id,
        response_by_label=_current_school_actor_label(request),
    )
    if reply is None:
        _set_flash(request, error="Message was not found.")
        return RedirectResponse(url="/admin#messages", status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message="Reply sent to user message.")
    return RedirectResponse(url="/admin#messages", status_code=status.HTTP_303_SEE_OTHER)


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
        return RedirectResponse(url="/admin?section=quiet-periods#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)
    await _quiet_periods(request).grant_quiet_period(
        user_id=user_id,
        reason=reason.strip() or None,
        admin_user_id=_session_user_id(request) or 0,
        admin_label=_current_school_actor_label(request),
    )
    _set_flash(request, message=f"Quiet period granted for {user.name} for 24 hours.")
    return RedirectResponse(url="/admin?section=quiet-periods#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/quiet-periods/{request_id}/approve", include_in_schema=False)
async def admin_approve_quiet_period(
    request: Request,
    request_id: int,
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    record = await _quiet_periods(request).approve_request(
        request_id=request_id,
        admin_user_id=_session_user_id(request) or 0,
        admin_label=_current_school_actor_label(request),
    )
    if record is None or record.status != "approved":
        _set_flash(request, error="Quiet period request was not found or is no longer pending.")
        return RedirectResponse(url="/admin?section=quiet-periods#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)
    user = await _users(request).get_user(record.user_id)
    label = user.name if user else f"User #{record.user_id}"
    _set_flash(request, message=f"Approved quiet period request for {label}.")
    return RedirectResponse(url="/admin?section=quiet-periods#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/quiet-periods/{request_id}/deny", include_in_schema=False)
async def admin_deny_quiet_period(
    request: Request,
    request_id: int,
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    record = await _quiet_periods(request).deny_request(
        request_id=request_id,
        admin_user_id=_session_user_id(request) or 0,
        admin_label=_current_school_actor_label(request),
    )
    if record is None or record.status != "denied":
        _set_flash(request, error="Quiet period request was not found or is no longer pending.")
        return RedirectResponse(url="/admin?section=quiet-periods#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)
    user = await _users(request).get_user(record.user_id)
    label = user.name if user else f"User #{record.user_id}"
    _set_flash(request, message=f"Denied quiet period request for {label}.")
    return RedirectResponse(url="/admin?section=quiet-periods#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/quiet-periods/{request_id}/clear", include_in_schema=False)
async def admin_clear_quiet_period(
    request: Request,
    request_id: int,
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    record = await _quiet_periods(request).clear_quiet_period(
        request_id=request_id,
        admin_user_id=_session_user_id(request) or 0,
        admin_label=_current_school_actor_label(request),
    )
    if record is None or record.status != "cleared":
        _set_flash(request, error="Active quiet period was not found.")
        return RedirectResponse(url="/admin?section=quiet-periods#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)
    user = await _users(request).get_user(record.user_id)
    label = user.name if user else f"User #{record.user_id}"
    _set_flash(request, message=f"Removed the quiet period for {label}.")
    return RedirectResponse(url="/admin?section=quiet-periods#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/quiet-periods/{request_id}/hide", include_in_schema=False)
async def admin_hide_quiet_period_from_main_view(
    request: Request,
    request_id: int,
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    hidden = _quiet_hidden_ids(request)
    hidden.add(int(request_id))
    _set_quiet_hidden_ids(request, hidden)
    _set_flash(request, message="Request hidden from the main quiet-period queue. History is still retained.")
    return RedirectResponse(url="/admin?section=quiet-periods#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/quiet-periods/show-all", include_in_schema=False)
async def admin_show_hidden_quiet_periods(
    request: Request,
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    _set_quiet_hidden_ids(request, set())
    _set_flash(request, message="Hidden quiet-period requests are visible again.")
    return RedirectResponse(url="/admin?section=quiet-periods#quiet-periods", status_code=status.HTTP_303_SEE_OTHER)


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
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    normalized_name = name.strip()
    normalized_role = role.strip().lower()
    if not normalized_name:
        _set_flash(request, error="User name cannot be empty.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    if normalized_role not in {"admin", "teacher"}:
        _set_flash(request, error="Role must be admin or teacher.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    if clear_login is None and bool(login_name.strip()) != bool(password.strip()) and bool(password.strip()):
        _set_flash(request, error="To change credentials, provide both username and password.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
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
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message=f"Updated user {normalized_name}.")
    return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)


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
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)

    if user.role == "admin" and user.can_login and user.is_active:
        other_admins = await _users(request).count_other_dashboard_admins(user.id)
        if other_admins <= 0:
            _set_flash(request, error="You cannot delete the last active admin with dashboard login access.")
            return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)

    await _users(request).delete_user(user_id)

    if current_admin_id is not None and current_admin_id == user_id:
        request.session.clear()
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    _set_flash(request, message=f"Deleted user {user.name}.")
    return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)


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
                triggered_by_label=alert.triggered_by_label,
            )
            for alert in recent_alerts
        ]
    )


@router.post("/incidents/create", response_model=IncidentSummary)
async def create_incident(
    body: IncidentCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_api_key),
) -> IncidentSummary:
    creator_id = await _require_active_user_with_roles(_users(request), body.user_id, roles={"admin"})
    incident = await _incident_store(request).create_incident(
        type_value=body.type,
        status="active",
        created_by=creator_id,
        school_id=str(request.state.school.slug),
        target_scope=body.target_scope.strip().upper() or "ALL",
        metadata=body.metadata or {},
    )
    await _incident_store(request).create_notification_log(
        user_id=creator_id,
        type_value="incident_created",
        payload={"incident_id": incident.id, "type": incident.type, "target_scope": incident.target_scope},
    )
    background_tasks.add_task(
        _send_basic_push,
        request,
        message=f"Incident active: {incident.type}",
    )
    return IncidentSummary(
        id=incident.id,
        type=incident.type,
        status=incident.status,
        created_by=incident.created_by,
        school_id=incident.school_id,
        created_at=incident.created_at,
        target_scope=incident.target_scope,
        metadata=incident.metadata,
    )


@router.get("/incidents/active", response_model=IncidentListResponse)
async def active_incidents(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_api_key),
) -> IncidentListResponse:
    incidents = await _incident_store(request).list_active_incidents(limit=limit)
    return IncidentListResponse(
        incidents=[
            IncidentSummary(
                id=item.id,
                type=item.type,
                status=item.status,
                created_by=item.created_by,
                school_id=item.school_id,
                created_at=item.created_at,
                target_scope=item.target_scope,
                metadata=item.metadata,
            )
            for item in incidents
        ]
    )


@router.post("/team-assist/create", response_model=TeamAssistSummary)
@router.post("/request-help/create", response_model=TeamAssistSummary)
async def create_team_assist(
    body: TeamAssistCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_api_key),
) -> TeamAssistSummary:
    creator_id = await _require_active_user_with_roles(_users(request), body.user_id, roles={"admin", "teacher"})
    team_assist = await _incident_store(request).create_team_assist(
        type_value=body.type,
        created_by=creator_id,
        assigned_team_ids=[int(item) for item in body.assigned_team_ids],
        status="active",
    )
    target_user_ids = await _team_assist_target_user_ids(_users(request), body.assigned_team_ids)
    for target_user_id in target_user_ids:
        await _incident_store(request).create_notification_log(
            user_id=target_user_id,
            type_value="team_assist_targeted",
            payload={
                "team_assist_id": team_assist.id,
                "type": team_assist.type,
                "created_by": team_assist.created_by,
                "school_id": str(request.state.school.slug),
            },
        )
    await _incident_store(request).create_notification_log(
        user_id=creator_id,
        type_value="team_assist_created",
        payload={
            "team_assist_id": team_assist.id,
            "type": team_assist.type,
            "target_user_ids": target_user_ids,
        },
    )
    background_tasks.add_task(
        _send_basic_push,
        request,
        message=f"{get_feature_label('request_help')}: {get_feature_label(team_assist.type)}",
        target_user_ids=set(target_user_ids),
    )
    return _to_team_assist_summary(team_assist)


@router.post("/team-assist/{team_assist_id}/action", response_model=TeamAssistSummary)
@router.post("/request-help/{team_assist_id}/action", response_model=TeamAssistSummary)
async def team_assist_action(
    team_assist_id: int,
    body: TeamAssistActionRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> TeamAssistSummary:
    users = _users(request)
    actor_id = await _require_active_user_with_roles(users, body.user_id, roles={"admin"})
    actor = await users.get_user(actor_id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acting user not found")

    existing = await _incident_store(request).get_team_assist(team_assist_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request help item not found")
    if existing.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request help item is already cancelled")

    # Admin response should immediately clear active request-help alarm state.
    # We keep the action type in logs/notifications for audit visibility.
    next_status = "resolved"
    forward_to_user_id: Optional[int] = None
    forward_to_label: Optional[str] = None
    if body.action == "forward":
        if body.forward_to_user_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="forward_to_user_id is required")
        forward_user = await users.get_user(int(body.forward_to_user_id))
        if forward_user is None or not forward_user.is_active:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Forward target user not found")
        forward_to_user_id = forward_user.id
        forward_to_label = forward_user.name

    updated = await _incident_store(request).update_team_assist_action(
        team_assist_id=team_assist_id,
        status=next_status,
        acted_by_user_id=actor_id,
        acted_by_label=actor.name,
        forward_to_user_id=forward_to_user_id,
        forward_to_label=forward_to_label,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request help item not found")

    await _incident_store(request).create_notification_log(
        user_id=updated.created_by,
        type_value="team_assist_action",
        payload={
            "team_assist_id": updated.id,
            "action": body.action,
            "status": updated.status,
            "acted_by_user_id": actor.id,
            "acted_by_label": actor.name,
            "forward_to_user_id": forward_to_user_id,
            "forward_to_label": forward_to_label,
        },
    )
    if forward_to_user_id is not None:
        await _incident_store(request).create_notification_log(
            user_id=forward_to_user_id,
            type_value="team_assist_forwarded",
            payload={
                "team_assist_id": updated.id,
                "type": updated.type,
                "forwarded_by_label": actor.name,
            },
        )
    return _to_team_assist_summary(updated)


@router.post("/team-assist/{team_assist_id}/cancel-confirm", response_model=TeamAssistSummary)
@router.post("/request-help/{team_assist_id}/cancel-confirm", response_model=TeamAssistSummary)
async def team_assist_cancel_confirm(
    team_assist_id: int,
    body: TeamAssistCancelConfirmRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> TeamAssistSummary:
    users = _users(request)
    actor_id = await _require_active_user_with_roles(users, body.user_id, roles={"admin", "teacher"})
    actor = await users.get_user(actor_id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acting user not found")

    existing = await _incident_store(request).get_team_assist(team_assist_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request help item not found")
    if existing.status == "cancelled":
        return _to_team_assist_summary(existing)
    if actor.role != "admin" and actor.id != existing.created_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin or the initiating requester can confirm cancellation",
        )

    updated = await _incident_store(request).confirm_team_assist_cancel(
        team_assist_id=team_assist_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        actor_label=actor.name,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request help item not found")

    await _incident_store(request).create_notification_log(
        user_id=updated.created_by,
        type_value="team_assist_cancel_confirmation",
        payload={
            "team_assist_id": updated.id,
            "status": updated.status,
            "confirmed_by_user_id": actor.id,
            "confirmed_by_label": actor.name,
            "requester_confirmed": bool(updated.cancel_requester_confirmed_at),
            "admin_confirmed": bool(updated.cancel_admin_confirmed_at),
        },
    )
    return _to_team_assist_summary(updated)


@router.get("/team-assist/active", response_model=TeamAssistListResponse)
@router.get("/request-help/active", response_model=TeamAssistListResponse)
async def active_team_assists(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_api_key),
) -> TeamAssistListResponse:
    assists = await _incident_store(request).list_active_team_assists(limit=limit)
    return TeamAssistListResponse(team_assists=[_to_team_assist_summary(item) for item in assists])


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
@router.post("/devices/register", response_model=RegisterDeviceResponse)
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


@router.post("/quiet-periods/request", response_model=QuietPeriodSummary)
async def request_quiet_period(
    body: QuietPeriodRequestCreate,
    request: Request,
    _: None = Depends(require_api_key),
) -> QuietPeriodSummary:
    user = await _users(request).get_user(body.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found or inactive")
    record = await _quiet_periods(request).request_quiet_period(
        user_id=body.user_id,
        reason=body.reason,
    )
    return _to_quiet_period_summary(record)


@router.get("/quiet-periods/admin/requests", response_model=QuietPeriodAdminListResponse)
async def admin_quiet_period_requests(
    request: Request,
    admin_user_id: int = Query(..., ge=1),
    limit: int = Query(default=100, ge=1, le=300),
    _: None = Depends(require_api_key),
) -> QuietPeriodAdminListResponse:
    await _require_active_user_with_roles(_users(request), admin_user_id, roles={"admin"})
    records = await _quiet_periods(request).list_recent(limit=limit)
    visible = [item for item in records if item.status in {"pending", "approved"}]
    all_users = await _users(request).list_users()
    users_by_id = {int(u.id): u for u in all_users}
    return QuietPeriodAdminListResponse(
        requests=[
            QuietPeriodAdminItem(
                request_id=item.id,
                user_id=item.user_id,
                user_name=users_by_id.get(int(item.user_id)).name if users_by_id.get(int(item.user_id)) is not None else None,
                user_role=users_by_id.get(int(item.user_id)).role if users_by_id.get(int(item.user_id)) is not None else None,
                reason=item.reason,
                status=item.status,
                requested_at=item.requested_at,
                approved_at=item.approved_at,
                approved_by_user_id=item.approved_by_user_id,
                approved_by_label=item.approved_by_label,
                expires_at=item.expires_at,
            )
            for item in visible
        ]
    )


@router.post("/quiet-periods/{request_id}/approve", response_model=QuietPeriodSummary)
async def approve_quiet_period_request_api(
    request_id: int,
    body: QuietPeriodAdminActionRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> QuietPeriodSummary:
    admin_id = await _require_active_user_with_roles(_users(request), body.admin_user_id, roles={"admin"})
    admin_user = await _users(request).get_user(admin_id)
    record = await _quiet_periods(request).approve_request(
        request_id=request_id,
        admin_user_id=admin_id,
        admin_label=admin_user.name if admin_user is not None else None,
    )
    if record is None or record.status != "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quiet period request is not pending")
    return _to_quiet_period_summary(record)


@router.post("/quiet-periods/{request_id}/deny", response_model=QuietPeriodSummary)
async def deny_quiet_period_request_api(
    request_id: int,
    body: QuietPeriodAdminActionRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> QuietPeriodSummary:
    admin_id = await _require_active_user_with_roles(_users(request), body.admin_user_id, roles={"admin"})
    admin_user = await _users(request).get_user(admin_id)
    record = await _quiet_periods(request).deny_request(
        request_id=request_id,
        admin_user_id=admin_id,
        admin_label=admin_user.name if admin_user is not None else None,
    )
    if record is None or record.status != "denied":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quiet period request is not pending")
    return _to_quiet_period_summary(record)


@router.get("/quiet-periods/status", response_model=QuietPeriodStatusResponse)
async def quiet_period_status(
    request: Request,
    user_id: int = Query(..., ge=1),
    _: None = Depends(require_api_key),
) -> QuietPeriodStatusResponse:
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found or inactive")
    record = await _quiet_periods(request).latest_for_user(user_id=user_id)
    if record is None:
        return QuietPeriodStatusResponse(user_id=user_id)
    return QuietPeriodStatusResponse(
        request_id=record.id,
        user_id=user_id,
        status=record.status,
        reason=record.reason,
        requested_at=record.requested_at,
        approved_at=record.approved_at,
        approved_by_label=record.approved_by_label,
        expires_at=record.expires_at,
    )


@router.post("/quiet-periods/{request_id}/delete", response_model=QuietPeriodSummary)
async def delete_quiet_period_request(
    request_id: int,
    body: QuietPeriodDeleteRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> QuietPeriodSummary:
    user = await _users(request).get_user(body.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found or inactive")
    record = await _quiet_periods(request).cancel_for_user(
        request_id=request_id,
        user_id=body.user_id,
    )
    if record is None or record.user_id != body.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiet period request not found")
    if record.status not in {"cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quiet period request is not deletable")
    return _to_quiet_period_summary(record)


@router.post("/message-admin", response_model=AdminMessageResponse)
async def message_admin(
    body: AdminMessageRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> AdminMessageResponse:
    user_id = await _validated_user_id(_users(request), body.user_id)
    sender_user = await _users(request).get_user(user_id) if user_id is not None else None
    sender_label = (
        sender_user.name
        if sender_user is not None
        else (f"User #{user_id}" if user_id is not None else "Unknown user")
    )
    message_id = await _reports(request).create_admin_message(
        sender_user_id=user_id,
        recipient_user_id=None,
        sender_label=sender_label,
        direction="user_to_admin",
        message=body.message,
        status="open",
    )
    messages = await _reports(request).list_admin_messages(limit=30)
    created = next((item for item in messages if item.id == message_id), None)
    if created is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not load created admin message")
    return AdminMessageResponse(
        message_id=created.id,
        created_at=created.created_at,
        user_id=created.sender_user_id,
        message=created.message,
    )


@router.post("/messages/send", response_model=AdminSendMessageResponse)
async def admin_send_message(
    body: AdminSendMessageRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> AdminSendMessageResponse:
    users = _users(request)
    admin_id = await _require_dashboard_admin_id(users, body.admin_user_id)
    admin_user = await users.get_user(admin_id)
    sender_label = (admin_user.login_name or admin_user.name) if admin_user else f"Admin #{admin_id}"

    recipients: list[int] = []
    if body.send_to_all:
        all_users = await users.list_users()
        recipients = [u.id for u in all_users if u.is_active and u.role != "admin"]
    else:
        requested_ids = set(int(item) for item in body.recipient_user_ids if int(item) > 0)
        if body.recipient_user_id is not None and int(body.recipient_user_id) > 0:
            requested_ids.add(int(body.recipient_user_id))
        if not requested_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No recipient users selected")
        for recipient_user_id in sorted(requested_ids):
            target = await users.get_user(recipient_user_id)
            if target is None or not target.is_active or target.role == "admin":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Recipient user #{recipient_user_id} not found")
            recipients.append(target.id)

    if not recipients:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active non-admin recipients found")

    for recipient_user_id in recipients:
        await _reports(request).create_admin_message(
            sender_user_id=admin_id,
            recipient_user_id=recipient_user_id,
            sender_label=sender_label,
            direction="admin_to_user",
            message=body.message,
            status="delivered",
        )
    return AdminSendMessageResponse(
        sent_count=len(recipients),
        recipient_scope="all" if body.send_to_all else "single",
    )


@router.get("/messages/inbox", response_model=AdminMessageInboxResponse)
async def message_inbox(
    request: Request,
    user_id: int = Query(..., ge=1),
    limit: int = Query(default=30, ge=1, le=100),
    _: None = Depends(require_api_key),
) -> AdminMessageInboxResponse:
    users = _users(request)
    user = await users.get_user(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active user is required")
    if user.role == "admin":
        messages = await _reports(request).list_admin_messages(limit=limit)
    else:
        messages = await _reports(request).list_admin_messages_for_user(user_id=user_id, limit=limit)
    unread = sum(1 for item in messages if item.status == "open")
    return AdminMessageInboxResponse(
        unread_count=unread,
        messages=[_to_admin_inbox_item(item) for item in messages],
    )


@router.post("/messages/reply", response_model=AdminMessageResponse)
async def message_reply(
    body: AdminMessageReplyRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> AdminMessageResponse:
    users = _users(request)
    admin_id = await _require_dashboard_admin_id(users, body.admin_user_id)
    admin_user = await users.get_user(admin_id)
    reply = await _reports(request).reply_admin_message(
        message_id=body.message_id,
        response_message=body.message,
        response_by_user_id=admin_id,
        response_by_label=(admin_user.login_name or admin_user.name) if admin_user else f"Admin #{admin_id}",
    )
    if reply is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return AdminMessageResponse(
        message_id=reply.id,
        created_at=reply.created_at,
        user_id=reply.sender_user_id,
        message=reply.response_message or "",
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
        triggered_by_label=_current_school_actor_label(request),
        trigger_ip=trigger_ip,
        trigger_user_agent=trigger_user_agent,
    )
    await _alarm_store(request).activate(
        message=body.message,
        activated_by_user_id=triggered_by_user_id,
        activated_by_label=_current_school_actor_label(request),
    )

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
