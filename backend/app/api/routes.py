from __future__ import annotations

import asyncio
import base64
import csv
import anyio
import hashlib
import hmac
import io
import json
import logging
import os
import socket
import sys
import time
import zipfile
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from threading import Lock
from types import SimpleNamespace
from typing import Optional, cast

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse

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
    AlertAcknowledgeRequest,
    AlertAcknowledgeResponse,
    AdminBroadcastRequest,
    AlertsResponse,
    AlertSummary,
    DistrictOverviewResponse,
    DistrictQuietPeriodItem,
    DistrictQuietPeriodsResponse,
    DistrictQuietActionRequest,
    IncidentCreateRequest,
    IncidentListResponse,
    IncidentSummary,
    MeResponse,
    SelectTenantRequest,
    SelectTenantResponse,
    TeamAssistCreateRequest,
    TeamAssistActionRequest,
    TeamAssistCancelRequest,
    TeamAssistListResponse,
    TeamAssistSummary,
    TenantOverviewItem,
    TenantSummaryForUser,
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
    PushDeliveryStatsResponse,
    ProviderDeliveryStats,
    AuditLogEntry,
    AuditLogResponse,
    GenerateAccessCodeRequest,
    AccessCodeResponse,
    AccessCodeListResponse,
    ValidateCodeRequest,
    ValidateCodeResponse,
    CreateAccountFromCodeRequest,
    ValidateSetupCodeRequest,
    ValidateSetupCodeResponse,
    CreateDistrictAdminRequest,
    SendInviteEmailRequest,
    GmailSettingsResponse,
    GmailSettingsUpdateRequest,
    CustomerMessageRequest,
    HelpRequestCancellationAnalyticsResponse,
    HelpRequestCancellationCategoryBreakdown,
)
from app.services.access_code_service import AccessCodeService
from app.services.alert_broadcaster import BroadcastPlan, AlertBroadcaster
from app.services.alarm_store import AlarmStateRecord, AlarmStore
from app.services.apns import APNsClient
from app.services.email_service import EmailService, TEMPLATE_KEYS as EMAIL_TEMPLATE_KEYS
from app.services.health_monitor import HealthMonitor
from app.services.alert_log import AlertLog
from app.services.audit_log_service import AuditLogService, AuditEventRecord
from app.services.drill_report_service import DrillReportService
from app.services.drill_report_pdf import generate_pdf
from app.services.onboarding_pdf import generate_packet_pdf, generate_bulk_packets_pdf
from app.services.device_registry import DeviceRegistry
from app.services.fcm import FCMClient
from app.services.incident_store import IncidentStore
from app.services.permissions import (
    CODEGEN_ALLOWED_ROLES,
    PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS,
    PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS,
    PERM_FULL_ACCESS,
    PERM_GENERATE_ACCESS_CODES,
    PERM_MANAGE_ASSIGNED_TENANT_INCIDENTS,
    PERM_MANAGE_ASSIGNED_TENANT_USERS,
    PERM_MANAGE_ASSIGNED_TENANTS,
    PERM_MANAGE_OWN_TENANT_USERS,
    PERM_REQUEST_HELP,
    PERM_SUBMIT_QUIET_REQUEST,
    PERM_TRIGGER_OWN_TENANT_ALERTS,
    ROLE_ADMIN,
    ROLE_BUILDING_ADMIN,
    ROLE_DISTRICT_ADMIN,
    ROLE_SUPER_ADMIN,
    can,
    can_any,
    can_deactivate_alarm as _can_deactivate_alarm,
    can_archive_user,
    can_generate_codes,
    is_dashboard_role,
    role_display_label,
    valid_tenant_roles,
)
from app.services.quiet_period_store import QuietPeriodStore
from app.services.report_store import AdminMessageRecord, ReportStore
from app.services.platform_admin_store import PlatformAdminStore
from app.services.quiet_state_store import QuietStateStore
from app.services.school_registry import SchoolRegistry
from app.services.tenant_billing_store import TenantBillingStore
from app.services.totp import generate_secret as generate_totp_secret, otpauth_uri, verify_code as verify_totp_code
from app.services.user_store import UserStore
from app.services.user_tenant_store import UserTenantStore
from app.web.admin_views import (
    render_admin_page,
    render_change_password_page,
    render_login_page,
    render_super_admin_login_page,
    render_super_admin_page,
    render_totp_page,
)
import qrcode
import qrcode.constants


router = APIRouter()
logger = logging.getLogger("bluebird.routes")

# ── Alarm activation rate limiter (per-tenant, in-memory) ─────────────────────
_alarm_rate_store: dict[str, deque] = {}
_alarm_rate_lock = Lock()

def _check_alarm_rate_limit(slug: str, *, max_activations: int = 5, window_seconds: int = 60) -> bool:
    """Returns True if within limit. Allows up to max_activations per window per tenant."""
    now = time.monotonic()
    with _alarm_rate_lock:
        if slug not in _alarm_rate_store:
            _alarm_rate_store[slug] = deque()
        dq = _alarm_rate_store[slug]
        while dq and now - dq[0] > window_seconds:
            dq.popleft()
        if len(dq) >= max_activations:
            return False
        dq.append(now)
        return True


# ── Onboarding code-validation rate limiter (per-IP, in-memory) ───────────────
_code_rate_store: dict[str, deque] = {}
_code_rate_lock = Lock()


def _check_code_rate_limit(ip: str, *, max_attempts: int = 5, window_seconds: int = 60) -> bool:
    """Returns True if within limit. Protects /onboarding/validate-* endpoints."""
    now = time.monotonic()
    with _code_rate_lock:
        if ip not in _code_rate_store:
            _code_rate_store[ip] = deque()
        dq = _code_rate_store[ip]
        while dq and now - dq[0] > window_seconds:
            dq.popleft()
        if len(dq) >= max_attempts:
            return False
        dq.append(now)
        return True


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


TRUST_DEVICE_TTL_SECONDS = 14 * 24 * 60 * 60
ADMIN_TRUST_COOKIE = "bluebird_admin_trusted_device"
SUPER_ADMIN_TRUST_COOKIE = "bluebird_super_admin_trusted_device"


def _state_field(state: object, field: str, default: object = None) -> object:
    """
    Backward-compatible alarm-state accessor.
    Some legacy records may not have newer fields (e.g. is_training); this
    keeps runtime endpoints stable while still logging upstream read failures.
    """
    return getattr(state, field, default)


def _websocket_api_key_valid(websocket: WebSocket) -> bool:
    required = getattr(websocket.app.state.settings, "API_KEY", None)  # type: ignore[attr-defined]
    if not required:
        return True
    # Accept key from header (native clients) or query param (browser clients that can't set headers).
    presented = str(websocket.headers.get("X-API-Key", "") or "")
    if not presented:
        presented = str(websocket.query_params.get("api_key", "") or "")
    return bool(presented) and hmac.compare_digest(presented, required)


def _registry(req: Request) -> DeviceRegistry:
    return _tenant(req).device_registry  # type: ignore[attr-defined]


def _apns(req: Request) -> APNsClient:
    return req.app.state.apns_client  # type: ignore[attr-defined]

def _alarm_store(req: Request) -> AlarmStore:
    return _tenant(req).alarm_store  # type: ignore[attr-defined]


def _fcm(req: Request) -> FCMClient:
    return req.app.state.fcm_client  # type: ignore[attr-defined]


def _reports(req: Request) -> ReportStore:
    return _tenant(req).report_store  # type: ignore[attr-defined]


def _incident_store(req: Request) -> IncidentStore:
    return _tenant(req).incident_store  # type: ignore[attr-defined]


def _quiet_periods(req: Request) -> QuietPeriodStore:
    return _tenant(req).quiet_period_store  # type: ignore[attr-defined]


def _alert_log(req: Request) -> AlertLog:
    return _tenant(req).alert_log  # type: ignore[attr-defined]

def _audit_log_svc(req: Request) -> AuditLogService:
    return _tenant(req).audit_log_service  # type: ignore[attr-defined]

def _drill_report_svc(req: Request) -> DrillReportService:
    return _tenant(req).drill_report_service  # type: ignore[attr-defined]

def _users(req: Request) -> UserStore:
    return _tenant(req).user_store  # type: ignore[attr-defined]


def _sessions(req: Request):
    return _tenant(req).session_store  # type: ignore[attr-defined]


def _broadcaster(req: Request) -> AlertBroadcaster:
    return _tenant(req).broadcaster  # type: ignore[attr-defined]


def _schools(req: Request) -> SchoolRegistry:
    return req.app.state.school_registry  # type: ignore[attr-defined]


def _user_tenants(req: Request) -> UserTenantStore:
    return req.app.state.user_tenant_store  # type: ignore[attr-defined]


def _platform_admins(req: Request) -> PlatformAdminStore:
    return req.app.state.platform_admin_store  # type: ignore[attr-defined]


def _tenant_billing(req: Request) -> TenantBillingStore:
    return req.app.state.tenant_billing_store  # type: ignore[attr-defined]


def _quiet_states(req: Request) -> QuietStateStore:
    return req.app.state.quiet_state_store


def _health_monitor(req: Request) -> HealthMonitor:
    return req.app.state.health_monitor  # type: ignore[attr-defined]


def _email_service(req: Request) -> EmailService:
    return req.app.state.email_service  # type: ignore[attr-defined]


def _access_codes(req: Request) -> AccessCodeService:
    return req.app.state.access_code_service  # type: ignore[attr-defined]


def _settings_store(req: Request):
    from app.services.tenant_settings_store import TenantSettingsStore
    return _tenant(req).settings_store  # type: ignore[attr-defined]


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
    if normalized in {"dashboard", "user-management", "access-codes", "quiet-periods", "audit-logs", "settings", "drill-reports", "district", "devices", "analytics", "district-reports"}:
        return normalized
    return "dashboard"


def _super_admin_section(value: Optional[str]) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"districts", "schools", "billing", "platform-audit", "create-school", "security", "configuration", "server-tools", "health", "email-tool", "setup-codes", "noc", "msp", "platform-control", "sandbox"}:
        return normalized
    return "districts"


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


def _selected_tenant_slug_session_key(request: Request) -> str:
    school_slug = str(getattr(request.state.school, "slug", "") or "").strip().lower()
    return f"admin_selected_tenant_slug:{school_slug}"


def _get_selected_tenant_slug(request: Request) -> Optional[str]:
    value = request.session.get(_selected_tenant_slug_session_key(request))
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _set_selected_tenant_slug(request: Request, slug: str) -> None:
    request.session[_selected_tenant_slug_session_key(request)] = slug.strip().lower()


def _tenant(req: Request):
    selected = getattr(req.state, "admin_effective_tenant", None)
    return selected or req.state.tenant  # type: ignore[attr-defined]


@dataclass(frozen=True)
class _AdminTenantScope:
    available_schools: list
    selected_school: object


async def _resolve_admin_tenant_scope(
    request: Request,
    *,
    admin_user,
    selected_slug_hint: Optional[str] = None,
) -> _AdminTenantScope:
    current_school = request.state.school
    if bool(getattr(request.state, "super_admin_school_access", False)):
        return _AdminTenantScope(
            available_schools=[current_school],
            selected_school=current_school,
        )

    available_by_slug: dict[str, object] = {str(current_school.slug): current_school}
    if str(getattr(admin_user, "role", "")).strip().lower() == "district_admin":
        assignments = await _user_tenants(request).list_assignments(
            user_id=int(admin_user.id),
            home_tenant_id=int(current_school.id),
        )
        assigned_ids = {int(item.tenant_id) for item in assignments if int(item.tenant_id) > 0}
        if assigned_ids:
            all_schools = await _schools(request).list_schools()
            for school in all_schools:
                if int(school.id) in assigned_ids:
                    available_by_slug[str(school.slug)] = school

    available_schools = sorted(
        available_by_slug.values(),
        key=lambda school: str(getattr(school, "name", "")).lower(),
    )
    selected_slug = (selected_slug_hint or "").strip().lower()
    if not selected_slug:
        selected_slug = _get_selected_tenant_slug(request) or str(current_school.slug)
    elif selected_slug not in available_by_slug:
        _set_flash(request, error="Requested tenant is not in your assignment scope. Showing your current school.")
    selected_school = available_by_slug.get(selected_slug, current_school)
    _set_selected_tenant_slug(request, str(getattr(selected_school, "slug", current_school.slug)))
    return _AdminTenantScope(
        available_schools=available_schools,
        selected_school=selected_school,
    )


def _tenant_school_id(request: Request) -> int:
    active_tenant = _tenant(request)
    school = getattr(active_tenant, "school", None)
    return int(getattr(school, "id", 0) or 0)


async def _quiet_state_is_currently_valid(
    request: Request,
    *,
    home_tenant_id: int,
    user_id: int,
) -> bool:
    state = await _quiet_states(request).get(user_id=int(user_id), home_tenant_id=int(home_tenant_id))
    if state is None or not state.active:
        return False
    if state.source_request_id is None:
        return True

    schools = await _schools(request).list_schools()
    home_school = next((item for item in schools if int(item.id) == int(home_tenant_id)), None)
    if home_school is None:
        await _quiet_states(request).deactivate(user_id=int(user_id), home_tenant_id=int(home_tenant_id))
        return False

    home_tenant = request.app.state.tenant_manager.get(home_school)  # type: ignore[attr-defined]
    source_request = await home_tenant.quiet_period_store.get_request(request_id=int(state.source_request_id))
    if source_request is None or source_request.status != "approved":
        await _quiet_states(request).deactivate(user_id=int(user_id), home_tenant_id=int(home_tenant_id))
        return False
    return True


async def _is_effective_quiet_user(request: Request, *, user_id: int) -> bool:
    if int(user_id) <= 0:
        return False
    tenant_id = _tenant_school_id(request)
    local_quiet = set(await _quiet_periods(request).active_user_ids())
    if int(user_id) in local_quiet:
        return True

    if await _quiet_state_is_currently_valid(
        request,
        home_tenant_id=int(tenant_id),
        user_id=int(user_id),
    ):
        return True

    assignments = await _user_tenants(request).list_assignments_for_tenant_user(
        tenant_id=int(tenant_id),
        user_id=int(user_id),
    )
    for assignment in assignments:
        if await _quiet_state_is_currently_valid(
            request,
            home_tenant_id=int(assignment.home_tenant_id),
            user_id=int(assignment.user_id),
        ):
            return True
    return False


async def _quiet_suppressed_user_ids(
    request: Request,
    *,
    candidate_user_ids: set[int],
) -> set[int]:
    if not candidate_user_ids:
        return set()
    valid_ids = sorted({int(item) for item in candidate_user_ids if int(item) > 0})
    results = await asyncio.gather(*[
        _is_effective_quiet_user(request, user_id=uid) for uid in valid_ids
    ])
    return {uid for uid, is_quiet in zip(valid_ids, results) if is_quiet}


async def _apply_law_enforcement_quiet_state_for_request(
    request: Request,
    *,
    request_user_id: int,
    source_request_id: int,
    approved_by_user_id: Optional[int],
) -> None:
    user = await _users(request).get_user(int(request_user_id))
    if user is None or str(user.role).strip().lower() != "law_enforcement":
        return
    await _quiet_states(request).upsert_active(
        user_id=int(request_user_id),
        home_tenant_id=_tenant_school_id(request),
        source_request_id=int(source_request_id),
        approved_by_user_id=int(approved_by_user_id) if approved_by_user_id is not None else None,
    )


async def _deactivate_law_enforcement_quiet_state_for_user(
    request: Request,
    *,
    user_id: int,
) -> None:
    user = await _users(request).get_user(int(user_id))
    if user is None or str(user.role).strip().lower() != "law_enforcement":
        return
    await _quiet_states(request).deactivate(
        user_id=int(user_id),
        home_tenant_id=_tenant_school_id(request),
    )


def _super_admin_school_access_here(request: Request) -> bool:
    return _super_admin_ok(request) and _super_admin_school_slug(request) == str(getattr(request.state.school, "slug", "") or "")


def _fire_audit(
    request: Request,
    event_type: str,
    *,
    actor_user_id: Optional[int] = None,
    actor_label: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Fire-and-forget audit event. Never raises, never blocks the response."""
    svc = _audit_log_svc(request)
    slug = _tenant(request).slug

    async def _task() -> None:
        try:
            await svc.log_event(
                tenant_slug=slug,
                event_type=event_type,
                actor_user_id=actor_user_id,
                actor_label=actor_label,
                target_type=target_type,
                target_id=target_id,
                metadata=metadata,
            )
        except Exception:
            logger.debug("Audit log write failed event_type=%s tenant=%s", event_type, slug, exc_info=True)

    try:
        asyncio.create_task(_task())
    except RuntimeError:
        pass


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
    title = getattr(admin_user, "title", None)
    base = str(login_name) if login_name else (str(name) if name else None)
    if base and title:
        return f"{base} ({title})"
    return base


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


def _alert_hub(request: Request):
    return request.app.state.alert_hub  # type: ignore[attr-defined]


def _assert_tenant_resolved(request: Request) -> None:
    """
    Belt-and-suspenders guard: raise 400 if tenant context was not bound by the
    school middleware.  The middleware already rejects unresolvable tenants, so
    this check should never fire for normal HTTP traffic — it protects against
    middleware bypass or future mis-wiring.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not isinstance(tenant_id, int) or tenant_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant could not be resolved for this request.",
        )


async def _active_alert_metadata(request: Request, *, user_id: Optional[int] = None) -> tuple[Optional[int], int, bool]:
    state = await _alarm_store(request).get_state()
    if not bool(_state_field(state, "is_active", False)):
        return None, 0, False
    latest = await _alert_log(request).latest_alert()
    if latest is None:
        return None, 0, False
    ack_count = await _alert_log(request).acknowledgement_count(latest.id)
    user_ack = False
    if user_id is not None and int(user_id) > 0:
        user_ack = await _alert_log(request).has_acknowledged(alert_id=latest.id, user_id=int(user_id))
    return latest.id, ack_count, user_ack


async def _publish_alert_event(
    request: Request,
    *,
    event: str,
    alert_id: Optional[int] = None,
    extra: Optional[dict[str, object]] = None,
) -> None:
    state = await _alarm_store(request).get_state()
    active_alert_id, acknowledgement_count, _ = await _active_alert_metadata(request)
    # Use the effective tenant's slug so that district-admin operations on a
    # different school publish to the correct WebSocket channel, not the
    # routing-school's channel.
    effective_slug = _tenant(request).slug
    payload: dict[str, object] = {
        "event": event,
        "tenant_slug": effective_slug,
        "alarm": {
            "is_active": bool(_state_field(state, "is_active", False)),
            "message": cast(Optional[str], _state_field(state, "message", None)),
            "is_training": bool(_state_field(state, "is_training", False)),
            "training_label": cast(Optional[str], _state_field(state, "training_label", None)),
            "silent_audio": bool(_state_field(state, "silent_audio", False)),
            "current_alert_id": active_alert_id,
            "acknowledgement_count": acknowledgement_count,
            "activated_at": cast(Optional[str], _state_field(state, "activated_at", None)),
            "activated_by_label": cast(Optional[str], _state_field(state, "activated_by_label", None)),
            "deactivated_at": cast(Optional[str], _state_field(state, "deactivated_at", None)),
            "deactivated_by_label": cast(Optional[str], _state_field(state, "deactivated_by_label", None)),
            "triggered_by_user_id": cast(Optional[int], _state_field(state, "activated_by_user_id", None)),
            "silent_for_sender": True,
        },
    }
    if alert_id is not None:
        payload["alert_id"] = int(alert_id)
    if extra:
        payload.update(extra)
    await _alert_hub(request).publish(effective_slug, payload)


async def _publish_simple_event(
    request: Request,
    *,
    event: str,
    extra: Optional[dict[str, object]] = None,
) -> None:
    """Publish a lightweight non-alarm WebSocket event to the tenant channel."""
    effective_slug = _tenant(request).slug
    payload: dict[str, object] = {
        "event": event,
        "tenant_slug": effective_slug,
    }
    if extra:
        payload.update(extra)
    await _alert_hub(request).publish(effective_slug, payload)


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


async def _require_dashboard_admin(request: Request, *, selected_tenant_slug: Optional[str] = None) -> UserStore:
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
        request.state.admin_available_schools = [request.state.school]
        request.state.admin_effective_school = request.state.school
        request.state.admin_effective_tenant = request.state.tenant
        return _users(request)
    user_id = _session_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": _school_url(request, "/admin/login")})
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active or not is_dashboard_role(user.role) or not user.can_login:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": _school_url(request, "/admin/login")})
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": _school_url(request, "/admin/change-password")})
    request.state.admin_user = user
    request.state.super_admin_school_access = False
    scope = await _resolve_admin_tenant_scope(
        request,
        admin_user=user,
        selected_slug_hint=selected_tenant_slug,
    )
    request.state.admin_available_schools = scope.available_schools
    request.state.admin_effective_school = scope.selected_school
    request.state.admin_effective_tenant = request.app.state.tenant_manager.get(scope.selected_school)  # type: ignore[attr-defined]
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
    if user is None or not user.is_active or not can_any(
        user.role, {PERM_TRIGGER_OWN_TENANT_ALERTS, PERM_MANAGE_ASSIGNED_TENANT_INCIDENTS}
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only authorized active users can deactivate alarm")
    return user.id


async def _require_alarm_trigger_user(
    users: UserStore,
    user_id: Optional[int],
    *,
    allow_platform_super_admin: bool = False,
) -> Optional[int]:
    if user_id is None:
        if allow_platform_super_admin:
            return None
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authorized user_id is required to activate alarm")
    user = await users.get_user(int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only active users in this tenant can activate alarm",
        )
    return user.id


async def _ensure_no_active_alarm(request: Request) -> None:
    if (await _alarm_store(request).get_state()).is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An alarm is already active")


async def _require_dashboard_admin_id(users: UserStore, user_id: int) -> int:
    user = await users.get_user(int(user_id))
    if user is None or not user.is_active or not can_any(user.role, {PERM_MANAGE_OWN_TENANT_USERS, PERM_MANAGE_ASSIGNED_TENANT_USERS}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only active admin users can perform this action")
    return user.id


async def _require_active_user_with_permission(users: UserStore, user_id: int, *, permission: str) -> int:
    user = await users.get_user(int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active user is required")
    if not can(user.role, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User does not have permission for this action")
    return user.id


async def _require_active_user_with_any_permission(users: UserStore, user_id: int, *, permissions: set[str]) -> int:
    user = await users.get_user(int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active user is required")
    if not can_any(user.role, permissions):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User does not have permission for this action")
    return user.id


async def _require_active_user_with_roles(users: UserStore, user_id: int, *, roles: set[str]) -> int:
    user = await users.get_user(int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active user is required")
    if user.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User does not have permission for this action")
    return user.id


async def _require_active_user(users: UserStore, user_id: int) -> int:
    """Require any active user — no role or permission restriction."""
    user = await users.get_user(int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active user is required")
    return user.id


async def _team_assist_target_user_ids(users: UserStore, assigned_team_ids: list[int]) -> list[int]:
    all_users = await users.list_users()
    active_users = [u for u in all_users if u.is_active]
    if assigned_team_ids:
        selected = set(int(item) for item in assigned_team_ids if int(item) > 0)
        return [u.id for u in active_users if u.id in selected]
    # Stage 2 baseline: fallback target is active dashboard responders.
    return [u.id for u in active_users if is_dashboard_role(u.role)]


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
        cancelled_by_user_id=item.cancelled_by_user_id,
        cancelled_at=item.cancelled_at,
        cancel_reason_text=item.cancel_reason_text,
        cancel_reason_category=item.cancel_reason_category,
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
    tenant_slug = _tenant(request).slug
    apns_devices = await _registry(request).list_by_provider("apns")
    fcm_devices = await _registry(request).list_by_provider("fcm")
    candidate_user_ids = {
        int(device.user_id)
        for device in (*apns_devices, *fcm_devices)
        if device.user_id is not None and int(device.user_id) > 0
    }
    paused_user_ids = await _quiet_suppressed_user_ids(request, candidate_user_ids=candidate_user_ids)
    all_users = await _users(request).list_users()
    active_user_ids = {u.id for u in all_users if u.is_active}

    def _allow_user(user_id: Optional[int]) -> bool:
        if user_id is not None and user_id not in active_user_ids:
            return False
        if user_id is not None and user_id in paused_user_ids:
            return False
        if target_user_ids is None:
            return user_id is None or user_id > 0
        if user_id is None:
            return False
        return user_id in target_user_ids

    apns_tokens = [device.token for device in apns_devices if _allow_user(device.user_id)]
    fcm_tokens = [device.token for device in fcm_devices if _allow_user(device.user_id)]
    apns_tokens = list(dict.fromkeys(apns_tokens))
    fcm_tokens = list(dict.fromkeys(fcm_tokens))
    logger.debug(
        "push_tokens_for_scope tenant=%s apns=%d fcm=%d paused_users=%d active_users=%d",
        tenant_slug, len(apns_tokens), len(fcm_tokens), len(paused_user_ids), len(active_user_ids),
    )
    return apns_tokens, fcm_tokens


def _is_simulation_mode(request: Request) -> bool:
    """True ONLY when the current tenant is an is_test=True school with simulation_mode_enabled.

    Defense in depth: both flags must be set. simulation_mode_enabled alone is
    NOT sufficient — if somehow set on a production school (is_test=False), this
    returns False and real push continues normally.
    """
    school = getattr(request.state, "school", None)
    if school is None:
        return False
    if not getattr(school, "is_test", False):
        return False
    return bool(getattr(school, "simulation_mode_enabled", False))


async def _send_basic_push(
    request: Request,
    *,
    message: str,
    target_user_ids: Optional[set[int]] = None,
    extra_data: Optional[dict] = None,
) -> None:
    apns_tokens, fcm_tokens = await _push_tokens_for_scope(request, target_user_ids=target_user_ids)
    if apns_tokens:
        await _apns(request).send_bulk(apns_tokens, message, extra_data=extra_data)
    if fcm_tokens:
        await _fcm(request).send_bulk(fcm_tokens, message, extra_data=extra_data)


async def _send_help_request_push(
    request: Request,
    *,
    creator_id: int,
    responder_user_ids: set[int],
    message: str,
    extra_data: dict,
) -> None:
    """
    Per-device help_request push routing.

    Responders receive a normal sound push.  The sender's devices receive a
    silent banner (no aps.sound on iOS, silent_for_sender="true" on Android)
    so the alarm does not play on the device that originated the request,
    even when the app is backgrounded or closed.
    """
    apns_devices = await _registry(request).list_by_provider("apns")
    fcm_devices = await _registry(request).list_by_provider("fcm")

    candidate_ids = {
        int(d.user_id)
        for d in (*apns_devices, *fcm_devices)
        if d.user_id is not None and int(d.user_id) > 0
    }
    paused_ids = await _quiet_suppressed_user_ids(request, candidate_user_ids=candidate_ids)
    active_ids = {u.id for u in await _users(request).list_users() if u.is_active}

    # Sender is excluded from responder set in case of overlap.
    actual_responder_ids = responder_user_ids - {creator_id}

    def _eligible(uid: Optional[int]) -> bool:
        return uid is not None and int(uid) > 0 and int(uid) in active_ids and int(uid) not in paused_ids

    responder_apns = list(dict.fromkeys(
        d.token for d in apns_devices
        if _eligible(d.user_id) and int(d.user_id) in actual_responder_ids  # type: ignore[arg-type]
    ))
    responder_fcm = list(dict.fromkeys(
        d.token for d in fcm_devices
        if _eligible(d.user_id) and int(d.user_id) in actual_responder_ids  # type: ignore[arg-type]
    ))
    sender_apns = list(dict.fromkeys(
        d.token for d in apns_devices
        if _eligible(d.user_id) and int(d.user_id) == creator_id  # type: ignore[arg-type]
    ))
    sender_fcm = list(dict.fromkeys(
        d.token for d in fcm_devices
        if _eligible(d.user_id) and int(d.user_id) == creator_id  # type: ignore[arg-type]
    ))

    responder_data = {**extra_data, "silent_for_sender": "false"}
    sender_data = {**extra_data, "silent_for_sender": "true"}

    coros = []
    if responder_apns:
        coros.append(_apns(request).send_bulk(responder_apns, message, extra_data=responder_data))
    if sender_apns:
        coros.append(_apns(request).send_silent_for_sender(
            sender_apns,
            title="Help request sent",
            body="Your help request has been sent to your team.",
            extra_data=sender_data,
        ))
    if responder_fcm:
        coros.append(_fcm(request).send_bulk(responder_fcm, message, extra_data=responder_data))
    if sender_fcm:
        coros.append(_fcm(request).send_bulk(sender_fcm, message, extra_data=sender_data))
    if coros:
        await asyncio.gather(*coros)


async def _send_quiet_period_push_bg(
    apns: object,
    fcm: object,
    apns_tokens: list[str],
    fcm_tokens: list[str],
    title: str,
    message: str,
    extra_data: Optional[dict] = None,
) -> None:
    """Fire-and-forget push with custom title for quiet period status changes."""
    try:
        coros = []
        if apns_tokens:
            coros.append(apns.send_with_data(apns_tokens, title, message, extra_data=extra_data))  # type: ignore[union-attr]
        if fcm_tokens:
            coros.append(fcm.send_with_data(fcm_tokens, title, message, extra_data=extra_data or {}))  # type: ignore[union-attr]
        if coros:
            await asyncio.gather(*coros)
    except Exception:
        logger.debug("quiet_period_push_bg failed title=%s", title, exc_info=True)


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
async def health(request: Request) -> JSONResponse:
    checks = await HealthMonitor.run_checks(request.app.state)
    db_ok = bool(checks["db_ok"])
    ws_connections = int(checks["ws_connections"])
    ok = db_ok
    http_status = status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        content={"ok": ok, "db": db_ok, "ws_connections": ws_connections},
        status_code=http_status,
    )


@router.websocket("/ws/district/alerts")
async def district_alerts_websocket(websocket: WebSocket) -> None:
    """Real-time alert fan-out for district_admin / super_admin users across multiple tenants."""
    if not _websocket_api_key_valid(websocket):
        logger.warning("District WebSocket rejected: invalid API key")
        await websocket.close(code=4401)
        return

    raw_user_id = websocket.query_params.get("user_id")
    home_tenant_param = str(websocket.query_params.get("home_tenant", "") or "").strip().lower()

    if not home_tenant_param:
        logger.warning("District WebSocket rejected: missing home_tenant param")
        await websocket.close(code=4400)
        return
    if raw_user_id is None:
        logger.warning("District WebSocket rejected: missing user_id param")
        await websocket.close(code=4400)
        return
    try:
        ws_user_id = int(raw_user_id)
    except (ValueError, TypeError):
        logger.warning("District WebSocket rejected: invalid user_id=%r", raw_user_id)
        await websocket.close(code=4400)
        return

    home_school = websocket.app.state.tenant_manager.school_for_slug(home_tenant_param)  # type: ignore[attr-defined]
    if home_school is None:
        logger.warning("District WebSocket rejected: unknown home_tenant=%r", home_tenant_param)
        await websocket.close(code=4404)
        return

    home_ctx = websocket.app.state.tenant_manager.get(home_school)  # type: ignore[attr-defined]
    ws_user = await home_ctx.user_store.get_user(ws_user_id)
    if ws_user is None or not ws_user.is_active:
        logger.warning(
            "District WebSocket rejected: user_id=%d not active in tenant=%s", ws_user_id, home_tenant_param
        )
        await websocket.close(code=4403)
        return

    user_role = str(getattr(ws_user, "role", "") or "").strip().lower()
    if not can_any(user_role, {PERM_MANAGE_ASSIGNED_TENANTS, PERM_FULL_ACCESS}):
        logger.warning(
            "District WebSocket rejected: user_id=%d role=%r lacks district access in tenant=%s",
            ws_user_id, user_role, home_tenant_param,
        )
        await websocket.close(code=4403)
        return

    # Resolve which tenant slugs this user is subscribed to.
    school_registry: SchoolRegistry = websocket.app.state.school_registry  # type: ignore[attr-defined]
    user_tenant_store: UserTenantStore = websocket.app.state.user_tenant_store  # type: ignore[attr-defined]
    all_schools = await school_registry.list_schools()
    if user_role == "super_admin":
        subscribed_slugs = frozenset(str(s.slug) for s in all_schools if s.is_active)
    else:
        slugs: set[str] = {str(home_school.slug)}
        school_by_id = {int(s.id): s for s in all_schools}
        assignments = await user_tenant_store.list_assignments(
            user_id=ws_user_id,
            home_tenant_id=int(home_school.id),
        )
        for assignment in assignments:
            school = school_by_id.get(int(assignment.tenant_id))
            if school is not None and school.is_active:
                slugs.add(str(school.slug))
        subscribed_slugs = frozenset(slugs)

    hub = websocket.app.state.alert_hub  # type: ignore[attr-defined]
    await hub.connect_district(websocket, subscribed_slugs)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect_district(websocket)


@router.websocket("/ws/{tenant_slug}/alerts")
async def alerts_websocket(websocket: WebSocket, tenant_slug: str) -> None:
    tenant_candidate = str(tenant_slug or "").strip().lower()
    school = websocket.app.state.tenant_manager.school_for_slug(tenant_candidate)  # type: ignore[attr-defined]
    if school is None:
        logger.warning("WebSocket rejected: unknown tenant slug=%r", tenant_candidate)
        await websocket.close(code=4404)
        return
    if not _websocket_api_key_valid(websocket):
        logger.warning("WebSocket rejected: invalid API key for tenant=%s", tenant_candidate)
        await websocket.close(code=4401)
        return

    # Optional user identity — if provided, validate that the user exists and is active in this tenant.
    raw_user_id = websocket.query_params.get("user_id")
    if raw_user_id is not None:
        try:
            ws_user_id = int(raw_user_id)
        except (ValueError, TypeError):
            logger.warning("WebSocket rejected: invalid user_id=%r for tenant=%s", raw_user_id, tenant_candidate)
            await websocket.close(code=4400)
            return
        tenant_ctx = websocket.app.state.tenant_manager.get(school)  # type: ignore[attr-defined]
        ws_user = await tenant_ctx.user_store.get_user(ws_user_id)
        if ws_user is None or not ws_user.is_active:
            logger.warning("WebSocket rejected: user_id=%d not active in tenant=%s", ws_user_id, tenant_candidate)
            await websocket.close(code=4403)
            return

    hub = websocket.app.state.alert_hub  # type: ignore[attr-defined]
    await hub.connect(school.slug, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(school.slug, websocket)


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


_DEFAULT_BRANDING = {
    "accent": "#1b5fe4",
    "accent_strong": "#2f84ff",
    "sidebar_start": "#092054",
    "sidebar_end": "#071536",
}


@router.get("/{slug}/branding", include_in_schema=False)
async def get_school_branding(slug: str, request: Request) -> JSONResponse:
    """Public endpoint — returns fixed BlueBird defaults. Kept for mobile client compatibility."""
    from app.services.tenant_manager import TenantManager
    tenant_manager: TenantManager = request.app.state.tenant_manager  # type: ignore[attr-defined]
    school = tenant_manager.school_for_slug(slug)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found")
    return JSONResponse({
        "slug": school.slug,
        "name": school.name,
        **_DEFAULT_BRANDING,
        "logo_url": None,
        "has_custom_branding": False,
    })


@router.get("/{slug}/theme", include_in_schema=False)
async def get_school_theme(slug: str, request: Request) -> JSONResponse:
    """Public endpoint — returns fixed BlueBird defaults. Kept for mobile client compatibility."""
    from app.services.tenant_manager import TenantManager
    tenant_manager: TenantManager = request.app.state.tenant_manager  # type: ignore[attr-defined]
    school = tenant_manager.school_for_slug(slug)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found")
    return JSONResponse({
        "type": "theme_updated",
        "slug": school.slug,
        "name": school.name,
        **_DEFAULT_BRANDING,
        "logo_url": None,
        "brand_locked": False,
        "has_custom_branding": False,
    })


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
    _mobile_actor_label = (user.login_name or user.name) + (f" ({user.title})" if user.title else "")
    _fire_audit(
        request,
        "user_login",
        actor_user_id=user.id,
        actor_label=_mobile_actor_label,
        target_type="user",
        target_id=str(user.id),
        metadata={"login_name": body.login_name, "channel": "mobile"},
    )
    client_type = body.client_type if body.client_type in ("mobile", "web") else "mobile"
    session = await _sessions(request).create_session(user_id=user.id, client_type=client_type)
    quiet_period = await _quiet_periods(request).active_for_user(user_id=user.id)
    quiet_mode_active = await _is_effective_quiet_user(request, user_id=user.id)
    return MobileLoginResponse(
        user_id=user.id,
        name=user.name,
        role=user.role,
        login_name=user.login_name or body.login_name,
        title=user.title,
        must_change_password=user.must_change_password,
        can_deactivate_alarm=_can_deactivate_alarm(user.role),
        quiet_period_expires_at=quiet_period.expires_at if quiet_period else None,
        quiet_mode_active=quiet_mode_active,
        session_token=session.session_token,
    )


@router.get("/alarm/status", response_model=AlarmStatusResponse)
async def alarm_status(
    request: Request,
    user_id: Optional[int] = Query(default=None),
) -> AlarmStatusResponse:
    try:
        state = await _alarm_store(request).get_state()
    except Exception:
        logger.exception("alarm_status: failed to read alarm_state; returning safe default")
        state = AlarmStateRecord(
            is_active=False,
            message=None,
            is_training=False,
            training_label=None,
            silent_audio=False,
            activated_at=None,
            activated_by_user_id=None,
            activated_by_label=None,
            deactivated_at=None,
            deactivated_by_user_id=None,
            deactivated_by_label=None,
        )
    try:
        broadcasts = await _reports(request).list_broadcast_updates(limit=5)
    except Exception:
        logger.exception("alarm_status: failed to read broadcast updates; returning empty list")
        broadcasts = []
    current_alert_id, acknowledgement_count, current_user_acknowledged = await _active_alert_metadata(
        request,
        user_id=user_id,
    )
    return AlarmStatusResponse(
        is_active=bool(_state_field(state, "is_active", False)),
        message=cast(Optional[str], _state_field(state, "message", None)),
        is_training=bool(_state_field(state, "is_training", False)),
        training_label=cast(Optional[str], _state_field(state, "training_label", None)),
        silent_audio=bool(_state_field(state, "silent_audio", False)),
        current_alert_id=current_alert_id,
        acknowledgement_count=acknowledgement_count,
        current_user_acknowledged=current_user_acknowledged,
        activated_at=cast(Optional[str], _state_field(state, "activated_at", None)),
        activated_by_user_id=cast(Optional[int], _state_field(state, "activated_by_user_id", None)),
        activated_by_label=cast(Optional[str], _state_field(state, "activated_by_label", None)),
        deactivated_at=cast(Optional[str], _state_field(state, "deactivated_at", None)),
        deactivated_by_user_id=cast(Optional[int], _state_field(state, "deactivated_by_user_id", None)),
        deactivated_by_label=cast(Optional[str], _state_field(state, "deactivated_by_label", None)),
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


@router.get("/alarm/push-stats", response_model=PushDeliveryStatsResponse)
async def alarm_push_stats(
    request: Request,
    user_id: int = Query(...),
    _: None = Depends(require_api_key),
) -> PushDeliveryStatsResponse:
    users = _users(request)
    user = await users.get_user(user_id)
    if user is None or not user.is_active or not is_dashboard_role(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    latest = await _alert_log(request).latest_alert()
    if latest is None:
        return PushDeliveryStatsResponse()
    stats = await _alert_log(request).delivery_stats(latest.id)
    return PushDeliveryStatsResponse(
        total=stats.get("total", 0),
        ok=stats.get("ok", 0),
        failed=stats.get("failed", 0),
        last_error=stats.get("last_error"),
        by_provider={
            k: ProviderDeliveryStats(**v)
            for k, v in stats.get("by_provider", {}).items()
        },
    )


@router.get("/audit-log", response_model=AuditLogResponse)
async def get_audit_log(
    request: Request,
    user_id: int = Query(...),
    limit: int = Query(default=50, le=200),
    _: None = Depends(require_api_key),
) -> AuditLogResponse:
    users = _users(request)
    actor_id = await _require_active_user_with_any_permission(
        users,
        user_id,
        permissions={PERM_MANAGE_OWN_TENANT_USERS, PERM_MANAGE_ASSIGNED_TENANT_USERS},
    )
    _ = actor_id
    events = await _audit_log_svc(request).list_recent(limit=limit)
    return AuditLogResponse(
        events=[
            AuditLogEntry(
                id=e.id,
                timestamp=e.timestamp,
                event_type=e.event_type,
                actor_user_id=e.actor_user_id,
                actor_label=e.actor_label,
                target_type=e.target_type,
                target_id=e.target_id,
                metadata=e.metadata,
            )
            for e in events
        ]
    )


@router.post("/alarm/activate", response_model=AlarmStatusResponse)
async def activate_alarm(
    body: AlarmActivateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_api_key),
) -> AlarmStatusResponse:
    _assert_tenant_resolved(request)
    users = _users(request)
    allow_platform_super_admin = bool(getattr(request.state, "super_admin_school_access", False))
    triggered_by_user_id = await _require_alarm_trigger_user(
        users,
        body.user_id,
        allow_platform_super_admin=allow_platform_super_admin,
    )
    is_training = bool(body.is_training)
    training_label = body.training_label.strip() if body.training_label else None
    silent_audio = bool(body.silent_audio) and is_training
    if is_training and triggered_by_user_id is not None:
        await _require_dashboard_admin_id(users, triggered_by_user_id)

    await _ensure_no_active_alarm(request)

    effective_slug = _tenant(request).slug
    if not _check_alarm_rate_limit(effective_slug):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many alarm activations. Please wait before trying again.",
        )
    trigger_ip = request.client.host if request.client else None
    trigger_user_agent = request.headers.get("user-agent")
    alert_id = await _alert_log(request).log_alert(
        body.message,
        is_training=is_training,
        training_label=training_label,
        created_by_user_id=triggered_by_user_id,
        triggered_by_user_id=triggered_by_user_id,
        triggered_by_label=_current_school_actor_label(request),
        trigger_ip=trigger_ip,
        trigger_user_agent=trigger_user_agent,
    )
    state = await _alarm_store(request).activate(
        tenant_slug=effective_slug,
        message=body.message,
        activated_by_user_id=triggered_by_user_id,
        activated_by_label=_current_school_actor_label(request),
        is_training=is_training,
        training_label=training_label,
        silent_audio=silent_audio,
    )
    apns_tokens: list[str] = []
    fcm_tokens: list[str] = []
    sms_numbers: list[str] = []
    paused_user_ids: set[int] = set()
    if not is_training:
        apns_devices = await _registry(request).list_by_provider("apns")
        fcm_devices = await _registry(request).list_by_provider("fcm")
        all_users_list = await users.list_users()
        active_user_ids_set = {int(u.id) for u in all_users_list if u.is_active}
        candidate_user_ids = {
            int(device.user_id)
            for device in (*apns_devices, *fcm_devices)
            if device.user_id is not None and int(device.user_id) > 0
        }
        candidate_user_ids.update(int(user.id) for user in all_users_list if int(user.id) > 0)
        paused_user_ids = await _quiet_suppressed_user_ids(request, candidate_user_ids=candidate_user_ids)
        apns_tokens = list(
            dict.fromkeys(
                [
                    device.token
                    for device in apns_devices
                    if (device.user_id is None or device.user_id in active_user_ids_set)
                    and (device.user_id is None or device.user_id not in paused_user_ids)
                ]
            )
        )
        fcm_tokens = list(
            dict.fromkeys(
                [
                    device.token
                    for device in fcm_devices
                    if (device.user_id is None or device.user_id in active_user_ids_set)
                    and (device.user_id is None or device.user_id not in paused_user_ids)
                ]
            )
        )
        sms_numbers = await users.list_sms_targets(excluded_user_ids=sorted(paused_user_ids))
        plan = BroadcastPlan(
            apns_tokens=apns_tokens,
            fcm_tokens=fcm_tokens,
            sms_numbers=sms_numbers,
            tenant_slug=effective_slug,
            triggered_by_user_id=triggered_by_user_id,
            silent_for_sender=True,
        )
        if not _is_simulation_mode(request):
            background_tasks.add_task(_broadcaster(request).broadcast_panic, alert_id=alert_id, message=body.message, plan=plan)

    logger.warning(
        "ALARM ACTIVATED tenant=%s alert_id=%s by_user=%s training=%s label=%r apns=%s fcm=%s sms_targets=%s skipped_users=%s message=%r",
        effective_slug,
        alert_id,
        triggered_by_user_id,
        is_training,
        training_label,
        len(apns_tokens),
        len(fcm_tokens),
        len(sms_numbers),
        len(paused_user_ids),
        body.message,
    )
    _fire_audit(
        request,
        "training_started" if is_training else "alarm_activated",
        actor_user_id=triggered_by_user_id,
        actor_label=_current_school_actor_label(request),
        target_type="alert",
        target_id=str(alert_id),
        metadata={
            "alert_id": alert_id,
            "message": body.message,
            "is_training": is_training,
            "training_label": training_label,
            "silent_audio": silent_audio,
            "apns_count": len(apns_tokens),
            "fcm_count": len(fcm_tokens),
            "sms_count": len(sms_numbers),
        },
    )
    await _publish_alert_event(request, event="alert_triggered", alert_id=alert_id)

    return AlarmStatusResponse(
        is_active=bool(_state_field(state, "is_active", False)),
        message=cast(Optional[str], _state_field(state, "message", None)),
        is_training=bool(_state_field(state, "is_training", False)),
        training_label=cast(Optional[str], _state_field(state, "training_label", None)),
        silent_audio=bool(_state_field(state, "silent_audio", False)),
        current_alert_id=alert_id,
        acknowledgement_count=0,
        current_user_acknowledged=False,
        activated_at=cast(Optional[str], _state_field(state, "activated_at", None)),
        activated_by_user_id=cast(Optional[int], _state_field(state, "activated_by_user_id", None)),
        activated_by_label=cast(Optional[str], _state_field(state, "activated_by_label", None)),
        deactivated_at=cast(Optional[str], _state_field(state, "deactivated_at", None)),
        deactivated_by_user_id=cast(Optional[int], _state_field(state, "deactivated_by_user_id", None)),
        deactivated_by_label=cast(Optional[str], _state_field(state, "deactivated_by_label", None)),
        triggered_by_user_id=triggered_by_user_id,
        silent_for_sender=True,
    )


@router.post("/alarm/deactivate", response_model=AlarmStatusResponse)
async def deactivate_alarm(
    body: AlarmDeactivateRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> AlarmStatusResponse:
    _assert_tenant_resolved(request)
    admin_user_id = await _require_admin_user(_users(request), body.user_id)
    pre_state = await _alarm_store(request).get_state()
    state = await _alarm_store(request).deactivate(
        tenant_slug=_tenant(request).slug,
        deactivated_by_user_id=admin_user_id,
        deactivated_by_label=_current_school_actor_label(request),
    )
    logger.warning("ALARM DEACTIVATED by_user=%s", admin_user_id)
    _fire_audit(
        request,
        "training_ended" if pre_state.is_training else "alarm_deactivated",
        actor_user_id=admin_user_id,
        actor_label=_current_school_actor_label(request),
        target_type="alert",
        metadata={
            "message": pre_state.message,
            "is_training": pre_state.is_training,
            "training_label": pre_state.training_label,
        },
    )
    await _publish_alert_event(request, event="alert_cleared")
    return AlarmStatusResponse(
        is_active=bool(_state_field(state, "is_active", False)),
        message=cast(Optional[str], _state_field(state, "message", None)),
        is_training=bool(_state_field(state, "is_training", False)),
        training_label=cast(Optional[str], _state_field(state, "training_label", None)),
        silent_audio=bool(_state_field(state, "silent_audio", False)),
        current_alert_id=None,
        acknowledgement_count=0,
        current_user_acknowledged=False,
        activated_at=cast(Optional[str], _state_field(state, "activated_at", None)),
        activated_by_user_id=cast(Optional[int], _state_field(state, "activated_by_user_id", None)),
        activated_by_label=cast(Optional[str], _state_field(state, "activated_by_label", None)),
        deactivated_at=cast(Optional[str], _state_field(state, "deactivated_at", None)),
        deactivated_by_user_id=cast(Optional[int], _state_field(state, "deactivated_by_user_id", None)),
        deactivated_by_label=cast(Optional[str], _state_field(state, "deactivated_by_label", None)),
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


async def _fetch_school_status(school: object, tenant_ctx: object) -> dict:
    """Fetch all per-school data needed for district overview in two parallel batches."""
    alarm_state, latest_alert = await asyncio.gather(
        tenant_ctx.alarm_store.get_state(),
        tenant_ctx.alert_log.latest_alert(),
    )
    is_active = bool(getattr(alarm_state, "is_active", False))
    if latest_alert is not None and is_active:
        ack_count, school_users = await asyncio.gather(
            tenant_ctx.alert_log.acknowledgement_count(latest_alert.id),
            tenant_ctx.user_store.list_users(),
        )
    else:
        school_users = await tenant_ctx.user_store.list_users()
        ack_count = 0
    expected_users = sum(1 for u in school_users if u.is_active)
    ack_rate = round((ack_count / expected_users * 100.0) if expected_users > 0 else 0.0, 1)
    return {
        "tenant_slug": str(getattr(school, "slug", "")),
        "tenant_name": str(getattr(school, "name", "")),
        "alarm_is_active": is_active,
        "alarm_is_training": bool(getattr(alarm_state, "is_training", False)),
        "alarm_message": str(getattr(alarm_state, "message", "") or ""),
        "last_alert_at": latest_alert.created_at if latest_alert else None,
        "ack_count": ack_count,
        "expected_users": expected_users,
        "ack_rate": ack_rate,
    }


async def _build_district_overview_items(request: Request, *, admin_user) -> list[dict]:
    current_school = request.state.school
    all_schools = await _schools(request).list_schools()
    school_by_id = {int(s.id): s for s in all_schools}

    if str(getattr(admin_user, "role", "")).strip().lower() == "super_admin":
        accessible: dict[str, object] = {str(s.slug): s for s in all_schools if s.is_active}
    else:
        accessible = {str(current_school.slug): current_school}
        assignments = await _user_tenants(request).list_assignments(
            user_id=int(admin_user.id),
            home_tenant_id=int(current_school.id),
        )
        for assignment in assignments:
            school = school_by_id.get(int(assignment.tenant_id))
            if school is not None:
                slug = str(getattr(school, "slug", ""))
                if slug:
                    accessible[slug] = school

    school_list = sorted(accessible.values(), key=lambda s: str(getattr(s, "name", "")).lower())
    return list(await asyncio.gather(*[
        _fetch_school_status(school, request.app.state.tenant_manager.get(school))  # type: ignore[attr-defined]
        for school in school_list
    ]))


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard(
    request: Request,
    section: str = Query(default="dashboard"),
    tab: str = Query(default=""),
    tenant: Optional[str] = Query(default=None),
    audit_event_type: str = Query(default=""),
) -> HTMLResponse:
    if _session_user_id(request) is None and not _super_admin_school_access_here(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    await _require_dashboard_admin(request, selected_tenant_slug=tenant)
    effective_school = getattr(request.state, "admin_effective_school", request.state.school)
    available_schools = list(getattr(request.state, "admin_available_schools", [request.state.school]))
    devices = await _registry(request).list_devices()
    alerts = await _alert_log(request).list_recent(limit=20)
    users = await _users(request).list_users()
    alarm_state = await _alarm_store(request).get_state()
    _latest_alert = await _alert_log(request).latest_alert()
    _dashboard_ack_count = 0
    if alarm_state.is_active and _latest_alert is not None:
        _dashboard_ack_count = await _alert_log(request).acknowledgement_count(_latest_alert.id)
    fcm_configured = _fcm(request).is_configured()
    _dashboard_delivery_stats: dict = {}
    if _latest_alert is not None:
        _dashboard_delivery_stats = await _alert_log(request).delivery_stats(_latest_alert.id)
    _audit_event_type_filter = audit_event_type.strip()
    _audit_events = await _audit_log_svc(request).list_recent(
        limit=100,
        event_type=_audit_event_type_filter or None,
    )
    _audit_event_types = await _audit_log_svc(request).distinct_event_types()
    reports = await _reports(request).list_reports(limit=25)
    broadcasts = await _reports(request).list_broadcast_updates(limit=10)
    admin_messages = await _reports(request).list_admin_messages(limit=40)
    unread_admin_messages = sum(1 for item in admin_messages if item.status == "open")
    request_help_active = await _incident_store(request).list_active_team_assists(limit=50)
    quiet_periods_all = await _quiet_periods(request).list_recent(limit=200)
    hidden_ids = _quiet_hidden_ids(request)
    quiet_periods_active = [
        item for item in quiet_periods_all if item.status in {"pending", "approved"} and item.id not in hidden_ids
    ]
    quiet_periods_history = [item for item in quiet_periods_all if item.status not in {"pending", "approved"}]
    selected_section = _admin_section(section)
    _admin_role = str(getattr(request.state.admin_user, "role", "")).strip().lower()
    # Gate district and devices sections to district_admin and super_admin
    if selected_section in {"district", "devices"}:
        if _admin_role not in {"district_admin", "super_admin"}:
            selected_section = "dashboard"
    flash_message, flash_error = _pop_flash(request)
    assignments = await _user_tenants(request).list_assignments_for_users(
        home_tenant_id=int(effective_school.id),
        user_ids=[user.id for user in users],
    )
    schools_by_id = {int(item.id): item for item in await _schools(request).list_schools()}
    user_tenant_assignments: dict[int, list[str]] = {}
    for assignment in assignments:
        school_match = schools_by_id.get(int(assignment.tenant_id))
        if school_match is None:
            continue
        user_tenant_assignments.setdefault(int(assignment.user_id), []).append(str(school_match.name))
    for labels in user_tenant_assignments.values():
        labels.sort()

    _district_items: list[dict] = []
    if selected_section == "district":
        _district_items = await _build_district_overview_items(
            request, admin_user=request.state.admin_user
        )

    _active_sessions: list = []
    _sessions_users_by_id: dict = {}
    if selected_section == "devices":
        _active_sessions = await _sessions(request).list_active()
        _users_map = {u.id: u for u in users}
        _sessions_users_by_id = {s.user_id: _users_map[s.user_id] for s in _active_sessions if s.user_id in _users_map}

    _ws_api_key = str(getattr(request.app.state.settings, "API_KEY", "") or "")
    _ws_user_id = int(getattr(request.state.admin_user, "id", 0) or 0)
    _ws_home_tenant_slug = str(request.state.school.slug)

    _settings_history: list = []
    if selected_section == "settings":
        _settings_history = await _settings_store(request).get_history(limit=50)

    _admin_role = str(getattr(request.state.admin_user, "role", "")).strip().lower()
    _access_code_records: list = []
    if can_generate_codes(_admin_role) and selected_section == "access-codes":
        _access_code_records = await _access_codes(request).list_codes(str(request.state.school.slug), limit=200)
    _base_domain = str(getattr(request.app.state.settings, "BASE_DOMAIN", "") or "app.bluebirdalerts.com").strip()

    html = render_admin_page(
        school_name=request.state.school.name,
        school_slug=request.state.school.slug,
        school_path_prefix=_school_prefix(request),
        selected_tenant_slug=str(getattr(effective_school, "slug", request.state.school.slug)),
        selected_tenant_name=str(getattr(effective_school, "name", request.state.school.name)),
        tenant_options=[{"id": str(item.id), "slug": str(item.slug), "name": str(item.name)} for item in available_schools],
        current_user=request.state.admin_user,  # type: ignore[attr-defined]
        alerts=alerts,
        devices=devices,
        users=users,
        user_tenant_assignments=user_tenant_assignments,
        alarm_state=alarm_state,
        reports=reports,
        broadcasts=broadcasts,
        admin_messages=admin_messages,
        unread_admin_messages=unread_admin_messages,
        request_help_active=request_help_active,
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
        active_tab=tab.strip().lower(),
        acknowledgement_count=_dashboard_ack_count,
        fcm_configured=fcm_configured,
        delivery_stats=_dashboard_delivery_stats,
        audit_events=_audit_events,
        audit_event_types=_audit_event_types,
        audit_event_type_filter=_audit_event_type_filter,
        district_overview_items=_district_items,
        ws_api_key=_ws_api_key,
        current_user_id=_ws_user_id,
        home_tenant_slug=_ws_home_tenant_slug,
        access_code_records=_access_code_records,
        base_domain=_base_domain,
        settings_history=_settings_history,
        school_district_id=getattr(request.state.school, "district_id", None),
        active_sessions=_active_sessions,
        sessions_users_by_id=_sessions_users_by_id,
    )
    return HTMLResponse(content=html)


@router.post("/admin/settings/name", include_in_schema=False)
async def admin_settings_update_name(
    request: Request,
    name: str = Form(...),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    name = name.strip()
    if not name:
        _set_flash(request, error="School name cannot be empty.")
        return RedirectResponse(url=_school_url(request, "/admin?section=settings"), status_code=status.HTTP_303_SEE_OTHER)

    school = request.state.school
    old_name = str(school.name)
    if name == old_name:
        return RedirectResponse(url=_school_url(request, "/admin?section=settings"), status_code=status.HTTP_303_SEE_OTHER)

    updated = await _schools(request).update_name(slug=str(school.slug), name=name)
    if updated is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_school_url(request, "/admin?section=settings"), status_code=status.HTTP_303_SEE_OTHER)

    actor_label = str(getattr(request.state.admin_user, "name", "") or "")
    await _settings_store(request).record_change(
        field="name",
        old_value={"name": old_name},
        new_value={"name": name},
        changed_by_label=actor_label or None,
    )
    await _audit_log_svc(request).log_event(
        tenant_slug=str(school.slug),
        event_type="settings.name_updated",
        actor_label=actor_label or None,
        metadata={"old_name": old_name, "new_name": name},
    )
    _set_flash(request, message=f"School name updated to \"{name}\".")
    return RedirectResponse(url=_school_url(request, "/admin?section=settings"), status_code=status.HTTP_303_SEE_OTHER)


# ── Super-admin JSON info endpoints (used by tests and sandbox UI) ─────────────

@router.get("/super-admin/organizations", include_in_schema=False)
async def super_admin_list_organizations(request: Request) -> JSONResponse:
    _require_super_admin(request)
    orgs = await _schools(request).list_organizations()
    return JSONResponse({
        "organizations": [
            {"id": o.id, "name": o.name, "slug": o.slug, "is_active": o.is_active}
            for o in orgs
        ]
    })


@router.post("/super-admin/districts/create", include_in_schema=False)
async def super_admin_create_district(
    request: Request,
    name: str = Form(...),
    slug: str = Form(...),
    organization_id: int = Form(...),
) -> JSONResponse:
    _require_super_admin(request)
    district = await _schools(request).create_district(
        name=name.strip(), slug=slug.strip().lower(), organization_id=int(organization_id)
    )
    return JSONResponse({"ok": True, "id": district.id, "slug": district.slug, "name": district.name})


@router.get("/super-admin/districts/{slug}/info", include_in_schema=False)
async def super_admin_district_info(request: Request, slug: str) -> JSONResponse:
    _require_super_admin(request)
    district = await _schools(request).get_district_by_slug(slug.strip().lower())
    if district is None:
        raise HTTPException(status_code=404, detail="District not found")
    return JSONResponse({
        "id": district.id,
        "name": district.name,
        "slug": district.slug,
        "organization_id": district.organization_id,
        "is_active": district.is_active,
        "is_test": district.is_test,
        "source_district_id": district.source_district_id,
        "brand_lock_enabled": district.brand_lock_enabled,
    })


@router.get("/super-admin/districts/{slug}/schools", include_in_schema=False)
async def super_admin_district_schools(request: Request, slug: str) -> JSONResponse:
    _require_super_admin(request)
    district = await _schools(request).get_district_by_slug(slug.strip().lower())
    if district is None:
        raise HTTPException(status_code=404, detail="District not found")
    schools = await _schools(request).list_schools_by_district(district.id)
    return JSONResponse({
        "schools": [
            {
                "id": s.id,
                "slug": s.slug,
                "name": s.name,
                "is_active": s.is_active,
                "is_test": s.is_test,
                "source_tenant_slug": s.source_tenant_slug,
                "simulation_mode_enabled": s.simulation_mode_enabled,
                "suppress_alarm_audio": s.suppress_alarm_audio,
            }
            for s in schools
        ]
    })


@router.get("/super-admin/schools/{slug}/info", include_in_schema=False)
async def super_admin_school_info(request: Request, slug: str) -> JSONResponse:
    _require_super_admin(request)
    school = await _schools(request).get_by_slug(slug.strip().lower())
    if school is None:
        raise HTTPException(status_code=404, detail="School not found")
    return JSONResponse({
        "id": school.id,
        "slug": school.slug,
        "name": school.name,
        "is_active": school.is_active,
        "is_test": school.is_test,
        "source_tenant_slug": school.source_tenant_slug,
        "simulation_mode_enabled": school.simulation_mode_enabled,
        "suppress_alarm_audio": school.suppress_alarm_audio,
        "district_id": school.district_id,
    })


@router.post("/super-admin/schools/{slug}/assign-district", include_in_schema=False)
async def super_admin_assign_school_to_district(
    request: Request,
    slug: str,
    district_id: Optional[int] = Form(default=None),
) -> JSONResponse:
    _require_super_admin(request)
    school = await _schools(request).assign_to_district(
        school_slug=slug.strip().lower(),
        district_id=int(district_id) if district_id is not None else None,
    )
    if school is None:
        raise HTTPException(status_code=404, detail="School not found")
    return JSONResponse({"ok": True, "slug": school.slug, "district_id": school.district_id})


@router.post("/super-admin/districts/{district_id}/archive", include_in_schema=False)
async def super_admin_archive_district(request: Request, district_id: int) -> RedirectResponse:
    _require_super_admin(request)
    district = await _schools(request).get_district(district_id)
    if district is None:
        _set_flash(request, error="District not found.")
        return RedirectResponse(url=_super_admin_url("districts"), status_code=status.HTTP_303_SEE_OTHER)
    if district.is_archived:
        _set_flash(request, error="District is already archived.")
        return RedirectResponse(url=_super_admin_url("districts"), status_code=status.HTTP_303_SEE_OTHER)
    await _schools(request).archive_district(district_id)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    actor = admin.login_name if admin else "superadmin"
    _set_flash(request, message=f"District '{district.name}' archived.")
    return RedirectResponse(url=_super_admin_url("districts"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/districts/{district_id}/purge", include_in_schema=False)
async def super_admin_purge_district(
    request: Request,
    district_id: int,
    confirm_name: str = Form(default=""),
) -> RedirectResponse:
    _require_super_admin(request)
    district = await _schools(request).get_district(district_id)
    if district is None:
        _set_flash(request, error="District not found.")
        return RedirectResponse(url=_super_admin_url("districts"), status_code=status.HTTP_303_SEE_OTHER)
    if not district.is_archived:
        _set_flash(request, error="Only archived districts can be purged. Archive the district first.")
        return RedirectResponse(url=_super_admin_url("districts"), status_code=status.HTTP_303_SEE_OTHER)
    if confirm_name.strip().lower() != district.name.strip().lower():
        _set_flash(request, error=f"Confirmation name did not match. Type the district name exactly to confirm purge.")
        return RedirectResponse(url=_super_admin_url("districts"), status_code=status.HTTP_303_SEE_OTHER)
    # Get all schools before deletion so we can remove their DB files
    schools_to_purge = await _schools(request).list_schools_for_district(district_id)
    from app.services.tenant_manager import TenantManager, normalize_school_slug
    tenant_manager: TenantManager = request.app.state.tenant_manager  # type: ignore[attr-defined]
    # Evict from tenant cache and delete DB files
    for school in schools_to_purge:
        db_path = tenant_manager.db_path_for_slug(school.slug)
        with tenant_manager._lock:
            tenant_manager._cache.pop(normalize_school_slug(school.slug), None)
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
    # Delete from registry (schools + district)
    await _schools(request).delete_district(district_id)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    actor = admin.login_name if admin else "superadmin"
    _set_flash(request, message=f"District '{district.name}' and all associated data permanently deleted.")
    return RedirectResponse(url=_super_admin_url("districts"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/settings/undo/{change_id}", include_in_schema=False)
async def admin_settings_undo(
    request: Request,
    change_id: int,
) -> RedirectResponse:
    await _require_dashboard_admin(request)

    store = _settings_store(request)
    rec = await store.get_by_id(change_id)
    if rec is None or rec.is_undone:
        _set_flash(request, error="Change not found or already undone.")
        return RedirectResponse(url=_school_url(request, "/admin?section=settings"), status_code=status.HTTP_303_SEE_OTHER)

    school = request.state.school
    actor_label = str(getattr(request.state.admin_user, "name", "") or "")

    if rec.field == "name":
        restored_name = str(rec.old_value.get("name", "") or "")
        if restored_name:
            await _schools(request).update_name(slug=str(school.slug), name=restored_name)

    await store.mark_undone(change_id)
    await _audit_log_svc(request).log_event(
        tenant_slug=str(school.slug),
        event_type="settings.change_undone",
        actor_label=actor_label or None,
        metadata={"change_id": change_id, "field": rec.field},
    )
    _set_flash(request, message=f"Change to \"{rec.field}\" has been undone.")
    return RedirectResponse(url=_school_url(request, "/admin?section=settings"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/district/schools/reorder", include_in_schema=False)
async def admin_district_reorder_schools(request: Request) -> JSONResponse:
    """Reorder schools within a district. Accepts {ordered_slugs: [...]}. Same-district only."""
    if _session_user_id(request) is None and not _super_admin_school_access_here(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _admin_role = str(getattr(request.state.admin_user, "role", "")).strip().lower()
    if _admin_role not in {"district_admin", "super_admin"}:
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    school = request.state.school
    district_id = getattr(school, "district_id", None)
    if district_id is None:
        return JSONResponse({"error": "Current school has no district"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    ordered_slugs = [str(s).strip().lower() for s in body.get("ordered_slugs", []) if str(s).strip()]
    if not ordered_slugs:
        return JSONResponse({"error": "ordered_slugs must be a non-empty list"}, status_code=400)

    try:
        await _schools(request).reorder_schools_in_district(
            district_id=int(district_id),
            ordered_slugs=ordered_slugs,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    actor_label = str(getattr(request.state.admin_user, "name", "") or "")
    await _audit_log_svc(request).log_event(
        tenant_slug=str(school.slug),
        event_type="district.schools_reordered",
        actor_label=actor_label or None,
        metadata={"ordered_slugs": ordered_slugs},
    )
    return JSONResponse({"ok": True})


@router.get("/admin/reports/{alert_id}", include_in_schema=False)
async def admin_report_json(alert_id: int, request: Request) -> JSONResponse:
    await _require_dashboard_admin(request)
    report = await _drill_report_svc(request).build_report(
        alert_id=alert_id, tenant_slug=_tenant(request).slug
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return JSONResponse(content=report.to_dict())


@router.get("/admin/reports/{alert_id}/export.csv", include_in_schema=False)
async def admin_report_csv(alert_id: int, request: Request) -> StreamingResponse:
    await _require_dashboard_admin(request)
    report = await _drill_report_svc(request).build_report(
        alert_id=alert_id, tenant_slug=_tenant(request).slug
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["BlueBird Alerts — Alert Report"])
    writer.writerow(["School", request.state.school.name])
    writer.writerow(["Alert ID", report.alert_id])
    writer.writerow(["Type", "Training Drill" if report.is_training else "Live Alarm"])
    writer.writerow(["Message", report.message])
    writer.writerow(["Created at", report.created_at])
    writer.writerow(["Activated by", report.activated_by or ""])
    writer.writerow(["Deactivated at", report.deactivated_at or ""])
    writer.writerow(["Deactivated by", report.deactivated_by or ""])
    writer.writerow([])
    writer.writerow(["Acknowledgement Summary"])
    writer.writerow(["Users expected", report.total_users_expected])
    writer.writerow(["Users acknowledged", report.total_acknowledged])
    writer.writerow(["Acknowledgement rate", f"{report.acknowledgement_rate:.1f}%"])
    writer.writerow(["First acknowledgement", report.first_ack_time or ""])
    writer.writerow(["Last acknowledgement", report.last_ack_time or ""])
    writer.writerow([])
    writer.writerow(["Delivery Summary"])
    writer.writerow(["Push attempts", report.delivery_total])
    writer.writerow(["Delivered", report.delivery_ok])
    writer.writerow(["Failed", report.delivery_failed])
    writer.writerow([])
    writer.writerow(["Acknowledgements"])
    writer.writerow(["user_id", "user_name", "acknowledged_at"])
    for ack in report.acknowledgements:
        writer.writerow([ack.user_id, ack.user_label or "", ack.acknowledged_at])
    csv_bytes = buf.getvalue().encode("utf-8-sig")
    filename = f"bluebird-report-alert-{alert_id}.csv"
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/reports/{alert_id}/export.pdf", include_in_schema=False)
async def admin_report_pdf(alert_id: int, request: Request) -> StreamingResponse:
    await _require_dashboard_admin(request)
    report = await _drill_report_svc(request).build_report(
        alert_id=alert_id, tenant_slug=_tenant(request).slug
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    school_name = request.state.school.name
    pdf_bytes = await anyio.to_thread.run_sync(
        lambda: generate_pdf(report, school_name)
    )
    filename = f"bluebird-report-alert-{alert_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
async def admin_login_page(request: Request) -> HTMLResponse:
    if _super_admin_school_access_here(request):
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    user = None
    if _session_user_id(request) is not None:
        user = await _users(request).get_user(_session_user_id(request) or 0)
    if user and is_dashboard_role(user.role) and user.is_active and user.can_login:
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
    try:
        await _users(request).create_user(
            name=name.strip(),
            role="admin",
            phone_e164=None,
            login_name=login_name.strip(),
            password=password,
        )
    except Exception as exc:
        import sqlite3 as _sqlite3
        if isinstance(exc.__cause__, _sqlite3.IntegrityError) or isinstance(exc, _sqlite3.IntegrityError) or "UNIQUE" in str(exc):
            _set_flash(request, error="That username is already taken. Choose a different one.")
        else:
            _set_flash(request, error=f"Could not create admin account: {exc}")
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
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
            _fire_audit(
                request,
                "user_login",
                actor_user_id=user.id,
                actor_label=user.login_name or user.name,
                target_type="user",
                target_id=str(user.id),
                metadata={"login_name": login_name, "channel": "web_admin", "totp": "trusted_device"},
            )
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
    _fire_audit(
        request,
        "user_login",
        actor_user_id=user.id,
        actor_label=user.login_name or user.name,
        target_type="user",
        target_id=str(user.id),
        metadata={"login_name": login_name, "channel": "web_admin"},
    )
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
    if user is None or not user.is_active or not is_dashboard_role(user.role) or not user.totp_enabled:
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
    _fire_audit(
        request,
        "user_login",
        actor_user_id=user.id,
        actor_label=user.login_name or user.name,
        target_type="user",
        target_id=str(user.id),
        metadata={"channel": "web_admin", "totp": "verified"},
    )
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


@router.post("/admin/devices/{session_id}/revoke", include_in_schema=False)
async def admin_revoke_device_session(request: Request, session_id: int) -> RedirectResponse:
    await _require_dashboard_admin(request)
    _actor_role = str(getattr(request.state.admin_user, "role", "")).strip().lower()
    if _actor_role not in {"district_admin", "super_admin"}:
        _set_flash(request, error="Only district administrators can revoke device sessions.")
        return RedirectResponse(url=_school_url(request, "/admin?section=devices"), status_code=status.HTTP_303_SEE_OTHER)
    revoked = await _sessions(request).invalidate_by_id(session_id)
    if revoked:
        _fire_audit(
            request,
            "session_revoked",
            actor_user_id=int(getattr(request.state.admin_user, "id", 0) or 0),
            actor_label=str(getattr(request.state.admin_user, "name", "") or ""),
            target_type="session",
            target_id=str(session_id),
            metadata={"channel": "web_admin"},
        )
        _set_flash(request, message="Device session revoked.")
    else:
        _set_flash(request, error="Session not found or already inactive.")
    return RedirectResponse(url=_school_url(request, "/admin?section=devices"), status_code=status.HTTP_303_SEE_OTHER)


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
    section: str = Query(default="districts"),
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
    billing_rows: list[dict[str, object]] = []
    for school in schools:
        school_prefix = f"/{school.slug}"
        admin_count = await request.app.state.tenant_manager.get(school).user_store.count_dashboard_admins()  # type: ignore[attr-defined]
        admin_url = f"https://{base_domain}{school_prefix}/admin"
        billing = await _tenant_billing(request).ensure_tenant_billing(tenant_id=int(school.id))
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
        billing_status = str(billing.billing_status or "trial").strip().lower()
        billing_status_class = "ok" if billing_status in {"active", "trial", "free"} else "danger"
        free_override_class = "ok" if billing.is_free_override else "danger"
        billing_rows.append(
            {
                "name": school.name,
                "slug": school.slug,
                "plan_id": billing.plan_id or "—",
                "billing_status": billing_status,
                "billing_status_class": billing_status_class,
                "trial_end": billing.trial_end or "—",
                "renewal_date": billing.renewal_date or "—",
                "free_override_label": "Enabled" if billing.is_free_override else "Disabled",
                "free_override_class": free_override_class,
                "free_reason": billing.free_reason or "—",
                "stripe_customer_id": billing.stripe_customer_id or "—",
                "stripe_subscription_id": billing.stripe_subscription_id or "—",
                "start_trial_action": f"/super-admin/schools/{school.slug}/billing/start-trial",
                "grant_free_action": f"/super-admin/schools/{school.slug}/billing/grant-free",
                "remove_free_action": f"/super-admin/schools/{school.slug}/billing/remove-free",
            }
        )
    hm = _health_monitor(request)
    es = _email_service(request)
    _sa_section = _super_admin_section(section)
    health_status, health_heartbeats, email_log = await asyncio.gather(
        hm.current_status(),
        hm.recent_heartbeats(limit=20),
        es.recent_email_log(limit=50),
    )
    _setup_codes = await _access_codes(request).list_setup_codes(limit=200) if _sa_section == "setup-codes" else []
    _sa_schools_by_slug = {s.slug: s for s in await _schools(request).list_schools()} if _sa_section == "setup-codes" else {}
    # NOC initial data — gathered in parallel, only when the noc section is active
    # (or always, since it's cheap: one DB read per tenant for alarm state)
    _noc_tenant_data = await asyncio.gather(*[
        _fetch_tenant_noc_status(request, s) for s in schools
    ])
    started_at = getattr(request.app.state, "started_at", None)
    _noc_uptime = max(0, int((datetime.now(timezone.utc) - started_at).total_seconds())) if started_at else 0
    # ── MSP district groupings ─────────────────────────────────────────────────
    _all_districts = await _schools(request).list_districts()
    _noc_by_slug: dict[str, dict[str, object]] = {t["slug"]: t for t in _noc_tenant_data}  # type: ignore[index]
    _billing_by_slug: dict[str, dict[str, object]] = {b["slug"]: b for b in billing_rows}  # type: ignore[index]
    _district_school_map: dict[int, list[object]] = defaultdict(list)
    _ungrouped_schools: list[object] = []
    for _s in schools:
        if getattr(_s, "district_id", None) is not None:
            _district_school_map[int(_s.district_id)].append(_s)  # type: ignore[arg-type]
        else:
            _ungrouped_schools.append(_s)
    msp_districts: list[dict[str, object]] = []
    for _d in _all_districts:
        _ds = _district_school_map.get(_d.id, [])
        _ds_nocs = [_noc_by_slug.get(str(getattr(s, "slug", "")), {}) for s in _ds]
        _d_alarm = sum(1 for n in _ds_nocs if n.get("alarm_active"))
        _d_ws = sum(int(n.get("ws_connections") or 0) for n in _ds_nocs)
        _d_last = max((n.get("last_alert_at") or "" for n in _ds_nocs), default="")
        _d_status = "alarm" if _d_alarm > 0 else ("empty" if not _ds else "healthy")
        _d_bills = [str(_billing_by_slug.get(str(getattr(s, "slug", "")), {}).get("billing_status", "unknown") or "unknown") for s in _ds]
        _d_push_failed = sum(int(n.get("push_failed", 0)) for n in _ds_nocs)
        msp_districts.append({
            "id": _d.id, "name": _d.name, "slug": _d.slug, "is_active": _d.is_active,
            "is_archived": bool(getattr(_d, "is_archived", False)),
            "archived_at": str(getattr(_d, "archived_at", "") or ""),
            "is_district": True, "school_count": len(_ds),
            "schools": [{"slug": str(getattr(s, "slug", "")), "name": str(getattr(s, "name", ""))} for s in _ds],
            "alarm_count": _d_alarm, "ws_total": _d_ws, "last_activity": _d_last,
            "status": _d_status, "billing_ok": all(b in {"active", "trial", "free"} for b in _d_bills) if _d_bills else True,
            "brand_locked": bool(getattr(_d, "brand_lock_enabled", False)),
            "push_failed_total": _d_push_failed,
        })
    for _s in _ungrouped_schools:
        _s_noc = _noc_by_slug.get(str(getattr(_s, "slug", "")), {})
        _s_bill = str(_billing_by_slug.get(str(getattr(_s, "slug", "")), {}).get("billing_status", "unknown") or "unknown")
        msp_districts.append({
            "id": None, "name": str(getattr(_s, "name", "")), "slug": str(getattr(_s, "slug", "")),
            "is_active": bool(getattr(_s, "is_active", True)), "is_district": False, "school_count": 1,
            "schools": [{"slug": str(getattr(_s, "slug", "")), "name": str(getattr(_s, "name", ""))}],
            "alarm_count": 1 if _s_noc.get("alarm_active") else 0,
            "ws_total": int(_s_noc.get("ws_connections") or 0),
            "last_activity": _s_noc.get("last_alert_at") or "",
            "status": "alarm" if _s_noc.get("alarm_active") else ("healthy" if bool(getattr(_s, "is_active", True)) else "offline"),
            "billing_ok": _s_bill in {"active", "trial", "free"},
            "push_failed_total": int(_s_noc.get("push_failed", 0)),
        })
    # ── Platform Control stats ────────────────────────────────────────────────
    _branded_schools = sum(1 for s in schools if any([s.accent, s.accent_strong, s.sidebar_start, s.logo_path]))
    _locked_districts = sum(1 for d in _all_districts if getattr(d, "brand_lock_enabled", False))
    _active_schools = sum(1 for s in schools if s.is_active)
    _platform_stats: dict[str, object] = {
        "total_schools": len(schools),
        "active_schools": _active_schools,
        "branded_schools": _branded_schools,
        "branding_coverage_pct": round(100 * _branded_schools / max(len(schools), 1)),
        "total_districts": len(_all_districts),
        "locked_districts": _locked_districts,
        "alarm_schools": sum(1 for t in _noc_tenant_data if t.get("alarm_active")),
        "ws_connections": sum(int(t.get("ws_connections") or 0) for t in _noc_tenant_data),
    }
    # ── Sandbox district data ──────────────────────────────────────────────────
    _test_districts = await _schools(request).list_test_districts()
    _test_schools_all = await _schools(request).list_test_schools()
    _test_schools_by_district: dict[int, list[object]] = defaultdict(list)
    for _ts in _test_schools_all:
        if getattr(_ts, "district_id", None) is not None:
            _test_schools_by_district[int(_ts.district_id)].append(_ts)
    _sandbox_data: list[dict[str, object]] = []
    for _td in _test_districts:
        _td_schools = _test_schools_by_district.get(_td.id, [])
        _sandbox_data.append({
            "district_id": _td.id,
            "district_name": _td.name,
            "district_slug": _td.slug,
            "source_district_id": _td.source_district_id,
            "schools": [
                {
                    "slug": str(getattr(s, "slug", "")),
                    "name": str(getattr(s, "name", "")),
                    "simulation_mode_enabled": bool(getattr(s, "simulation_mode_enabled", False)),
                    "suppress_alarm_audio": bool(getattr(s, "suppress_alarm_audio", False)),
                    "source_tenant_slug": str(getattr(s, "source_tenant_slug", "") or ""),
                }
                for s in _td_schools
            ],
        })
    _prod_districts = [d for d in _all_districts if not getattr(d, "is_test", False)]
    return HTMLResponse(
        render_super_admin_page(
            base_domain=request.app.state.settings.BASE_DOMAIN,  # type: ignore[attr-defined]
            school_rows=school_rows,
            billing_rows=billing_rows,
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
            active_section=_sa_section,
            health_status=health_status,
            health_heartbeats=health_heartbeats,
            email_log=email_log,
            email_configured=es.is_configured(),
            smtp_config=es.smtp_config(),
            gmail_settings=await es.get_gmail_settings(),
            platform_admin_emails=request.app.state.settings.platform_admin_email_list,  # type: ignore[attr-defined]
            email_template_keys=EMAIL_TEMPLATE_KEYS,
            setup_codes=_setup_codes,
            schools_by_slug=_sa_schools_by_slug,
            noc_tenant_data=list(_noc_tenant_data),
            noc_uptime_seconds=_noc_uptime,
            msp_districts=msp_districts,
            platform_stats=_platform_stats,
            sandbox_data=_sandbox_data,
            prod_districts=_prod_districts,
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


# ── NOC / Operations Dashboard endpoints ──────────────────────────────────────


async def _fetch_tenant_noc_status(request: Request, school: object) -> dict[str, object]:
    """Per-tenant live status for the NOC grid. Two gather batches, never crashes."""
    tenant = request.app.state.tenant_manager.get(school)  # type: ignore[attr-defined]
    slug = str(getattr(school, "slug", ""))
    name = str(getattr(school, "name", slug))
    try:
        alarm_state, latest_alert = await asyncio.gather(
            tenant.alarm_store.get_state(),
            tenant.alert_log.latest_alert(),
        )
        is_active = bool(getattr(alarm_state, "is_active", False))
        ack_count: int = 0
        user_count: int = 0
        push_failed: int = 0
        if is_active and latest_alert is not None:
            ack_val, users = await asyncio.gather(
                tenant.alert_log.acknowledgement_count(latest_alert.id),
                tenant.user_store.list_users(),
            )
            ack_count = int(ack_val)
            user_count = sum(1 for u in users if getattr(u, "is_active", True))
        if latest_alert is not None:
            _ps = await tenant.alert_log.delivery_stats(latest_alert.id)
            push_failed = int(_ps.get("failed", 0))
        hub = getattr(request.app.state, "alert_hub", None)
        ws_count = 0
        if hub is not None:
            try:
                ws_count = int(hub.connection_count(slug))
            except Exception:
                pass
        return {
            "slug": slug,
            "name": name,
            "alarm_active": is_active,
            "alarm_message": str(getattr(alarm_state, "message", "") or "")[:120] if is_active else None,
            "last_alert_at": str(getattr(latest_alert, "created_at", "") or "") if latest_alert else None,
            "ws_connections": ws_count,
            "ack_count": ack_count,
            "user_count": user_count,
            "push_failed": push_failed,
        }
    except Exception as exc:
        logger.warning("NOC tenant status error for %s: %s", slug, exc)
        return {"slug": slug, "name": name, "alarm_active": False, "alarm_message": None,
                "last_alert_at": None, "ws_connections": 0, "ack_count": 0, "user_count": 0, "push_failed": 0}


@router.get("/super-admin/metrics", include_in_schema=False)
async def super_admin_metrics(request: Request) -> dict[str, object]:
    _require_super_admin(request)
    schools = await _schools(request).list_schools()
    hm = _health_monitor(request)
    hs = await hm.current_status()
    hub = getattr(request.app.state, "alert_hub", None)
    ws_total = 0
    if hub is not None:
        try:
            ws_total = sum(hub.connection_count(s) for s in hub.connected_slugs())
        except Exception:
            pass
    started_at = getattr(request.app.state, "started_at", None)
    uptime_seconds = 0
    if started_at is not None:
        from datetime import datetime, timezone
        uptime_seconds = max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))
    return {
        "status": hs.overall,
        "db": "ok" if hs.db_ok else "error",
        "ws_connections": ws_total,
        "active_tenants": len(schools),
        "uptime_seconds": uptime_seconds,
        "apns_configured": hs.apns_configured,
        "fcm_configured": hs.fcm_configured,
        "response_time_ms": hs.response_time_ms,
        "last_heartbeat_at": hs.last_heartbeat_at,
        "uptime_24h": hs.uptime_24h,
    }


@router.get("/super-admin/tenant-health", include_in_schema=False)
async def super_admin_tenant_health(request: Request) -> dict[str, object]:
    _require_super_admin(request)
    schools = await _schools(request).list_schools()
    results = await asyncio.gather(*[_fetch_tenant_noc_status(request, s) for s in schools])
    return {"tenants": list(results)}


@router.get("/super-admin/system-activity", include_in_schema=False)
async def super_admin_system_activity(
    request: Request,
    limit: int = Query(default=60, ge=1, le=200),
) -> dict[str, object]:
    _require_super_admin(request)
    schools = await _schools(request).list_schools()
    all_events: list[dict[str, str]] = []

    async def _tenant_events(school: object) -> list[dict[str, str]]:
        try:
            tenant = request.app.state.tenant_manager.get(school)  # type: ignore[attr-defined]
            svc = getattr(tenant, "audit_log_service", None)
            if svc is None:
                return []
            events = await svc.list_recent(limit=30)
            return [
                {
                    "timestamp": str(e.timestamp),
                    "school": str(getattr(school, "name", "")),
                    "slug": str(getattr(school, "slug", "")),
                    "event_type": str(e.event_type),
                    "actor": str(e.actor_label or ""),
                    "target": str(e.target_type or ""),
                }
                for e in events
            ]
        except Exception:
            return []

    batches = await asyncio.gather(*[_tenant_events(s) for s in schools])
    for batch in batches:
        all_events.extend(batch)
    all_events.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"events": all_events[:limit]}


@router.get("/super-admin/push-stats", include_in_schema=False)
async def super_admin_push_stats(request: Request) -> dict[str, object]:
    _require_super_admin(request)
    schools = await _schools(request).list_schools()

    async def _tenant_push(school: object) -> dict[str, object]:
        slug = str(getattr(school, "slug", ""))
        name = str(getattr(school, "name", slug))
        try:
            tenant = request.app.state.tenant_manager.get(school)  # type: ignore[attr-defined]
            latest = await tenant.alert_log.latest_alert()
            if latest is None:
                return {"slug": slug, "name": name, "total": 0, "ok": 0, "failed": 0,
                        "last_error": None, "last_alert_at": None}
            stats = await tenant.alert_log.delivery_stats(latest.id)
            return {
                "slug": slug, "name": name,
                "total": int(stats.get("total", 0)),
                "ok": int(stats.get("ok", 0)),
                "failed": int(stats.get("failed", 0)),
                "last_error": stats.get("last_error"),
                "last_alert_at": str(getattr(latest, "created_at", "") or ""),
            }
        except Exception:
            return {"slug": slug, "name": name, "total": 0, "ok": 0, "failed": 0,
                    "last_error": None, "last_alert_at": None}

    results = await asyncio.gather(*[_tenant_push(s) for s in schools])
    return {"tenants": list(results)}


# ── MSP / Customer Operations endpoints ───────────────────────────────────────

@router.get("/super-admin/msp/district/{slug}", include_in_schema=False)
async def super_admin_msp_district(request: Request, slug: str) -> dict[str, object]:
    """Full live detail for one district (or ungrouped school). Super-admin only."""
    _require_super_admin(request)
    school_registry = _schools(request)
    district = await school_registry.get_district_by_slug(slug)
    if district is not None:
        d_schools = await school_registry.list_schools_by_district(district.id)
        entity_name = district.name
    else:
        # Treat slug as a school slug (ungrouped school)
        d_schools = [s for s in await school_registry.list_schools() if s.slug == slug]
        entity_name = d_schools[0].name if d_schools else slug

    async def _school_ops_counts(school: object) -> dict[str, object]:
        _slug = str(getattr(school, "slug", ""))
        try:
            _tc = request.app.state.tenant_manager.get(school)  # type: ignore[attr-defined]
            _inc, _qp, _aud = await asyncio.gather(
                _tc.incident_store.list_active_incidents(limit=50),
                _tc.quiet_period_store.list_recent(limit=50),
                _tc.audit_log_service.list_recent(limit=5),
            )
            return {
                "slug": _slug,
                "incident_count": len(_inc),
                "pending_quiet": sum(1 for q in _qp if getattr(q, "status", "") == "pending"),
                "recent_audit": [
                    {
                        "created_at": str(getattr(e, "timestamp", "") or ""),
                        "event_type": str(getattr(e, "event_type", "")),
                        "actor": str(getattr(e, "actor_label", "") or "system"),
                    }
                    for e in _aud[:5]
                ],
            }
        except Exception:
            return {"slug": _slug, "incident_count": 0, "pending_quiet": 0, "recent_audit": []}

    noc_results, push_results, ops_results = await asyncio.gather(
        asyncio.gather(*[_fetch_tenant_noc_status(request, s) for s in d_schools]),
        asyncio.gather(*[_tenant_push_stat(request, s) for s in d_schools]),
        asyncio.gather(*[_school_ops_counts(s) for s in d_schools]),
    )
    notes = await school_registry.list_operator_notes(slug)
    _all_audit = sorted(
        [ev for o in ops_results for ev in o.get("recent_audit", [])],
        key=lambda e: str(e.get("created_at", "")),
        reverse=True,
    )[:10]
    return {
        "slug": slug,
        "name": entity_name,
        "is_district": district is not None,
        "schools": [
            {
                "slug": str(s.slug), "name": str(s.name), "is_active": bool(s.is_active),
                "admin_url": f"/{s.slug}/admin",
            }
            for s in d_schools
        ],
        "noc": list(noc_results),
        "push": list(push_results),
        "notes": notes,
        "incident_count": sum(int(o.get("incident_count", 0)) for o in ops_results),
        "pending_quiet": sum(int(o.get("pending_quiet", 0)) for o in ops_results),
        "recent_audit": _all_audit,
    }


async def _tenant_push_stat(request: Request, school: object) -> dict[str, object]:
    slug = str(getattr(school, "slug", ""))
    name = str(getattr(school, "name", slug))
    try:
        tenant = request.app.state.tenant_manager.get(school)  # type: ignore[attr-defined]
        latest = await tenant.alert_log.latest_alert()
        if latest is None:
            return {"slug": slug, "name": name, "total": 0, "ok": 0, "failed": 0, "last_alert_at": None}
        stats = await tenant.alert_log.delivery_stats(latest.id)
        return {
            "slug": slug, "name": name,
            "total": int(stats.get("total", 0)), "ok": int(stats.get("ok", 0)),
            "failed": int(stats.get("failed", 0)),
            "last_alert_at": str(getattr(latest, "created_at", "") or ""),
        }
    except Exception:
        return {"slug": slug, "name": name, "total": 0, "ok": 0, "failed": 0, "last_alert_at": None}


@router.get("/super-admin/msp/notes/{tenant_slug}", include_in_schema=False)
async def super_admin_msp_list_notes(request: Request, tenant_slug: str) -> dict[str, object]:
    _require_super_admin(request)
    notes = await _schools(request).list_operator_notes(tenant_slug)
    return {"notes": notes}


@router.post("/super-admin/msp/notes", include_in_schema=False)
async def super_admin_msp_add_note(request: Request) -> dict[str, object]:
    _require_super_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    tenant_slug = str(body.get("tenant_slug", "")).strip().lower()
    note_text = str(body.get("note_text", "")).strip()
    if not tenant_slug or not note_text:
        raise HTTPException(status_code=400, detail="tenant_slug and note_text are required")
    if len(note_text) > 2000:
        raise HTTPException(status_code=400, detail="Note must be under 2000 characters")
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    created_by = admin.login_name if admin else "super_admin"
    note = await _schools(request).add_operator_note(
        tenant_slug=tenant_slug, note_text=note_text, created_by=created_by
    )
    return {"note": note}


@router.delete("/super-admin/msp/notes/{note_id}", include_in_schema=False)
async def super_admin_msp_delete_note(request: Request, note_id: int) -> dict[str, object]:
    _require_super_admin(request)
    deleted = await _schools(request).delete_operator_note(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": True, "id": note_id}


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
        await _tenant_billing(request).ensure_tenant_billing(tenant_id=int(school.id))
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


@router.post("/super-admin/schools/{slug}/billing/start-trial", include_in_schema=False)
async def super_admin_start_tenant_trial(
    request: Request,
    slug: str,
    duration_days: int = Form(default=14),
) -> RedirectResponse:
    _require_super_admin(request)
    from app.services.tenant_manager import normalize_school_slug

    normalized_slug = normalize_school_slug(slug)
    school = await _schools(request).get_by_slug(normalized_slug)
    if school is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("billing"), status_code=status.HTTP_303_SEE_OTHER)
    if int(duration_days) < 1 or int(duration_days) > 365:
        _set_flash(request, error="Trial duration must be between 1 and 365 days.")
        return RedirectResponse(url=_super_admin_url("billing"), status_code=status.HTTP_303_SEE_OTHER)
    existing = await _tenant_billing(request).ensure_tenant_billing(tenant_id=int(school.id))
    now = datetime.now(timezone.utc)
    trial_start = now.isoformat()
    trial_end = (now + timedelta(days=int(duration_days))).isoformat()
    await _tenant_billing(request).upsert_tenant_billing(
        tenant_id=int(school.id),
        plan_id=existing.plan_id,
        billing_status="trial",
        trial_start=trial_start,
        trial_end=trial_end,
        is_free_override=existing.is_free_override,
        free_reason=existing.free_reason,
        stripe_customer_id=existing.stripe_customer_id,
        stripe_subscription_id=existing.stripe_subscription_id,
        renewal_date=existing.renewal_date,
    )
    _set_flash(request, message=f"Started {int(duration_days)}-day trial for {school.name}.")
    return RedirectResponse(url=_super_admin_url("billing"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/schools/{slug}/billing/grant-free", include_in_schema=False)
async def super_admin_grant_tenant_free_access(
    request: Request,
    slug: str,
    free_reason: str = Form(default=""),
) -> RedirectResponse:
    _require_super_admin(request)
    from app.services.tenant_manager import normalize_school_slug

    normalized_slug = normalize_school_slug(slug)
    school = await _schools(request).get_by_slug(normalized_slug)
    if school is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("billing"), status_code=status.HTTP_303_SEE_OTHER)
    existing = await _tenant_billing(request).ensure_tenant_billing(tenant_id=int(school.id))
    await _tenant_billing(request).upsert_tenant_billing(
        tenant_id=int(school.id),
        plan_id=existing.plan_id,
        billing_status=existing.billing_status,
        trial_start=existing.trial_start,
        trial_end=existing.trial_end,
        is_free_override=True,
        free_reason=free_reason.strip() or "Granted by super admin",
        stripe_customer_id=existing.stripe_customer_id,
        stripe_subscription_id=existing.stripe_subscription_id,
        renewal_date=existing.renewal_date,
    )
    _set_flash(request, message=f"Granted free access for {school.name}.")
    return RedirectResponse(url=_super_admin_url("billing"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/schools/{slug}/billing/remove-free", include_in_schema=False)
async def super_admin_remove_tenant_free_access(
    request: Request,
    slug: str,
) -> RedirectResponse:
    _require_super_admin(request)
    from app.services.tenant_manager import normalize_school_slug

    normalized_slug = normalize_school_slug(slug)
    school = await _schools(request).get_by_slug(normalized_slug)
    if school is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("billing"), status_code=status.HTTP_303_SEE_OTHER)
    existing = await _tenant_billing(request).ensure_tenant_billing(tenant_id=int(school.id))
    await _tenant_billing(request).upsert_tenant_billing(
        tenant_id=int(school.id),
        plan_id=existing.plan_id,
        billing_status=existing.billing_status,
        trial_start=existing.trial_start,
        trial_end=existing.trial_end,
        is_free_override=False,
        free_reason=None,
        stripe_customer_id=existing.stripe_customer_id,
        stripe_subscription_id=existing.stripe_subscription_id,
        renewal_date=existing.renewal_date,
    )
    _set_flash(request, message=f"Removed free-access override for {school.name}.")
    return RedirectResponse(url=_super_admin_url("billing"), status_code=status.HTTP_303_SEE_OTHER)


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


@router.post("/super-admin/health/email/send", include_in_schema=False)
async def super_admin_health_email_send(
    request: Request,
    to_addresses: str = Form(default=""),
    template_key: str = Form(default="maintenance_notice"),
    custom_subject: str = Form(default=""),
    custom_body: str = Form(default=""),
) -> RedirectResponse:
    _require_super_admin(request)
    es = _email_service(request)
    if not es.is_configured():
        _set_flash(request, error="SMTP is not configured. Set SMTP_HOST and SMTP_FROM in the backend environment.")
        return RedirectResponse(url=_super_admin_url("email-tool"), status_code=status.HTTP_303_SEE_OTHER)
    addresses = [a.strip() for a in to_addresses.replace("\n", ",").split(",") if a.strip()]
    if not addresses:
        _set_flash(request, error="No valid email addresses provided.")
        return RedirectResponse(url=_super_admin_url("email-tool"), status_code=status.HTTP_303_SEE_OTHER)
    tmpl = es.get_template(template_key)
    subject = custom_subject.strip() or tmpl["subject"]
    body = custom_body.strip() or tmpl["body"]
    count = await es.send_to_addresses(addresses, subject=subject, body=body, event_type=f"manual_{template_key}")
    _set_flash(request, message=f"Email sent to {count}/{len(addresses)} addresses.")
    return RedirectResponse(url=_super_admin_url("email-tool"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/health/email/test", include_in_schema=False)
async def super_admin_health_email_test(
    request: Request,
    test_email: str = Form(default=""),
) -> RedirectResponse:
    _require_super_admin(request)
    es = _email_service(request)
    if not es.is_configured():
        _set_flash(request, error="SMTP is not configured. Set SMTP_HOST and SMTP_FROM in the backend environment.")
        return RedirectResponse(url=_super_admin_url("email-tool"), status_code=status.HTTP_303_SEE_OTHER)
    addr = test_email.strip()
    if not addr or "@" not in addr:
        _set_flash(request, error="Enter a valid email address for the test.")
        return RedirectResponse(url=_super_admin_url("email-tool"), status_code=status.HTTP_303_SEE_OTHER)
    ok = await es.send_email(
        to_address=addr,
        subject="BlueBird Alerts — Test Email",
        body=(
            "This is a test email from the BlueBird Alerts platform admin console.\n\n"
            "If you received this, SMTP is configured correctly.\n\n"
            "— BlueBird Alerts Platform"
        ),
        event_type="test",
    )
    if ok:
        _set_flash(request, message=f"Test email sent successfully to {addr}.")
    else:
        _set_flash(request, error=f"Test email to {addr} failed. Check SMTP settings and the email log for details.")
    return RedirectResponse(url=_super_admin_url("email-tool"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/configuration/smtp", include_in_schema=False)
async def super_admin_save_smtp_configuration(
    request: Request,
    smtp_host: str = Form(default=""),
    smtp_port: int = Form(default=587),
    smtp_username: str = Form(default=""),
    smtp_password: str = Form(default=""),
    smtp_from: str = Form(default=""),
    smtp_use_tls: Optional[str] = Form(default=None),
    clear_smtp_password: Optional[str] = Form(default=None),
) -> RedirectResponse:
    _require_super_admin(request)
    host = smtp_host.strip()
    from_address = smtp_from.strip()
    username = smtp_username.strip()
    if not host:
        _set_flash(request, error="SMTP host is required.")
        return RedirectResponse(url=_super_admin_url("configuration"), status_code=status.HTTP_303_SEE_OTHER)
    if smtp_port < 1 or smtp_port > 65535:
        _set_flash(request, error="SMTP port must be between 1 and 65535.")
        return RedirectResponse(url=_super_admin_url("configuration"), status_code=status.HTTP_303_SEE_OTHER)
    if not from_address or "@" not in from_address:
        _set_flash(request, error="Enter a valid From email address.")
        return RedirectResponse(url=_super_admin_url("configuration"), status_code=status.HTTP_303_SEE_OTHER)
    try:
        await _email_service(request).save_smtp_config(
            host=host,
            port=int(smtp_port),
            username=username,
            from_address=from_address,
            use_tls=bool(smtp_use_tls),
            password=smtp_password,
            clear_password=bool(clear_smtp_password),
        )
    except Exception as exc:
        _set_flash(request, error=f"Could not save SMTP settings: {exc}")
        return RedirectResponse(url=_super_admin_url("configuration"), status_code=status.HTTP_303_SEE_OTHER)
    _set_flash(request, message="SMTP configuration saved. Use Email Tool to send a test message.")
    return RedirectResponse(url=_super_admin_url("configuration"), status_code=status.HTTP_303_SEE_OTHER)


# ── Gmail Settings ─────────────────────────────────────────────────────────────


@router.get("/super-admin/email-settings", include_in_schema=False)
async def super_admin_get_gmail_settings(request: Request) -> GmailSettingsResponse:
    _require_super_admin(request)
    gs = await _email_service(request).get_gmail_settings()
    return GmailSettingsResponse(
        gmail_address=gs.gmail_address,
        from_name=gs.from_name,
        password_set=gs.password_set,
        updated_at=gs.updated_at,
        updated_by=gs.updated_by,
        configured=gs.configured,
    )


@router.post("/super-admin/email-settings", include_in_schema=False)
async def super_admin_save_gmail_settings(
    request: Request,
    gmail_address: str = Form(default=""),
    from_name: str = Form(default="BlueBird Alerts"),
    app_password: str = Form(default=""),
) -> RedirectResponse:
    _require_super_admin(request)
    addr = gmail_address.strip().lower()
    if not addr or "@" not in addr:
        _set_flash(request, error="Enter a valid Gmail address.")
        return RedirectResponse(url=_super_admin_url("configuration"), status_code=status.HTTP_303_SEE_OTHER)
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    actor = admin.login_name if admin else "super_admin"
    await _email_service(request).save_gmail_settings(
        gmail_address=addr,
        from_name=from_name.strip() or "BlueBird Alerts",
        app_password=app_password.strip() or None,
        updated_by=actor,
    )
    logger.info("super_admin email_settings_updated actor=%s gmail=%s", actor, addr)
    _set_flash(request, message="Gmail settings saved.")
    return RedirectResponse(url=_super_admin_url("configuration"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/email-settings/test", include_in_schema=False)
async def super_admin_test_gmail_settings(
    request: Request,
    test_email: str = Form(default=""),
) -> RedirectResponse:
    _require_super_admin(request)
    addr = test_email.strip()
    if not addr or "@" not in addr:
        _set_flash(request, error="Enter a valid email address for the test.")
        return RedirectResponse(url=_super_admin_url("configuration"), status_code=status.HTTP_303_SEE_OTHER)
    es = _email_service(request)
    gs = await es.get_gmail_settings()
    if not gs.configured:
        _set_flash(request, error="Gmail is not configured. Save Gmail settings first.")
        return RedirectResponse(url=_super_admin_url("configuration"), status_code=status.HTTP_303_SEE_OTHER)
    ok = await es.send_email(
        to_address=addr,
        subject="BlueBird Alerts — Test Email",
        body=(
            "This is a test email from the BlueBird Alerts platform.\n\n"
            "If you received this, Gmail SMTP is working correctly.\n\n"
            "— BlueBird Alerts Platform"
        ),
        event_type="gmail_test",
    )
    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    actor = admin.login_name if admin else "super_admin"
    logger.info("super_admin test_email_sent actor=%s to=%s ok=%s", actor, addr, ok)
    if ok:
        _set_flash(request, message=f"Test email sent to {addr}.")
    else:
        _set_flash(request, error=f"Test email to {addr} failed. Check Gmail settings and email log.")
    return RedirectResponse(url=_super_admin_url("configuration"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/customers/{school_slug}/message", include_in_schema=False)
async def super_admin_send_customer_message(
    request: Request,
    school_slug: str,
    subject: str = Form(default=""),
    body: str = Form(default=""),
) -> RedirectResponse:
    _require_super_admin(request)
    subject = subject.strip()
    body = body.strip()
    if not subject or not body:
        _set_flash(request, error="Subject and message body are required.")
        return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)

    school = _tenant_manager(request).school_for_slug(school_slug)
    if school is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)

    tenant_ctx = _tenant_manager(request).get(school)
    email_addresses = await tenant_ctx.user_store.list_emails_by_role(["district_admin", "building_admin"])

    admin = await _platform_admins(request).get_by_id(_super_admin_id(request) or 0)
    actor = admin.login_name if admin else "super_admin"
    es = _email_service(request)

    if not es.is_configured():
        logger.info("super_admin customer_message NOT sent (unconfigured) actor=%s school=%s", actor, school_slug)
        _set_flash(request, error="Email is not configured. Message logged but not sent.")
        return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)

    if not email_addresses:
        _set_flash(request, error=f"No email addresses found for admins in {school.name}.")
        return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)

    count = await es.send_to_addresses(email_addresses, subject=subject, body=body, event_type="customer_message")
    logger.info("super_admin customer_message_sent actor=%s school=%s count=%d/%d", actor, school_slug, count, len(email_addresses))
    _set_flash(request, message=f"Message sent to {count}/{len(email_addresses)} admin(s) at {school.name}.")
    return RedirectResponse(url=_super_admin_url("schools"), status_code=status.HTTP_303_SEE_OTHER)


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
    title: str = Form(default=""),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    actor = request.state.admin_user
    actor_role = str(getattr(actor, "role", "")).strip().lower()
    normalized_name = name.strip()
    normalized_role = role.strip().lower()
    normalized_phone = phone_e164.strip() or None
    normalized_title = title.strip() or None
    if not normalized_name:
        _set_flash(request, error="Name is required.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    if normalized_role not in valid_tenant_roles():
        _set_flash(request, error="Role must be one of: building_admin, teacher, staff, law_enforcement, district_admin.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    if normalized_role == ROLE_DISTRICT_ADMIN and actor_role not in {ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN}:
        _set_flash(request, error="Only district admins can create district admin accounts.")
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
            title=normalized_title,
        )
    except Exception as exc:
        msg = "That username is already taken." if "UNIQUE" in str(exc) else f"Could not create user: {exc}"
        _set_flash(request, error=msg)
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    _fire_audit(
        request,
        "user_created",
        actor_user_id=_session_user_id(request),
        actor_label=_current_school_actor_label(request),
        target_type="user",
        metadata={"name": normalized_name, "role": normalized_role},
    )
    _set_flash(request, message=f"Created user {normalized_name}.")
    return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/alarm/activate", include_in_schema=False)
async def admin_activate_alarm(
    request: Request,
    background_tasks: BackgroundTasks,
    message: str = Form(...),
    is_training: Optional[str] = Form(default=None),
    training_label: str = Form(default=""),
    silent_audio: Optional[str] = Form(default=None),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    # When a district admin is managing a different school than the one they
    # authenticated against, the session user_id belongs to the routing school's
    # user store — not the effective tenant's.  Treat this the same way super-admin
    # access is treated: set the school-access flag so activate_alarm bypasses the
    # user-store lookup and relies on the actor label for attribution instead.
    effective_slug = _tenant(request).slug
    routing_slug = str(getattr(request.state, "school_slug", "") or "")
    is_cross_tenant = effective_slug != routing_slug
    if is_cross_tenant:
        request.state.super_admin_school_access = True
    await activate_alarm(
        AlarmActivateRequest(
            message=message.strip(),
            user_id=None if is_cross_tenant else _session_user_id(request),
            is_training=(is_training == "1"),
            training_label=training_label.strip() or None,
            silent_audio=(silent_audio == "1"),
        ),
        request,
        background_tasks,
    )
    _set_flash(request, message="Training alert activated." if is_training == "1" else "Alarm activated.")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/alarm/deactivate", include_in_schema=False)
async def admin_deactivate_alarm(
    request: Request,
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    effective_slug = _tenant(request).slug
    routing_slug = str(getattr(request.state, "school_slug", "") or "")
    is_cross_tenant = effective_slug != routing_slug
    # Super-admin school access OR district-admin managing a different school:
    # bypass user-store lookup and deactivate directly with actor label only.
    if bool(getattr(request.state, "super_admin_school_access", False)) or is_cross_tenant:
        await _alarm_store(request).deactivate(
            tenant_slug=effective_slug,
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
        apns_devices = await _registry(request).list_by_provider("apns")
        fcm_devices = await _registry(request).list_by_provider("fcm")
        candidate_user_ids = {
            int(device.user_id)
            for device in (*apns_devices, *fcm_devices)
            if device.user_id is not None and int(device.user_id) > 0
        }
        paused_user_ids = await _quiet_suppressed_user_ids(request, candidate_user_ids=candidate_user_ids)
        apns_tokens = list(
            dict.fromkeys(
                [device.token for device in apns_devices if device.user_id is None or device.user_id not in paused_user_ids]
            )
        )
        fcm_tokens = list(
            dict.fromkeys(
                [device.token for device in fcm_devices if device.user_id is None or device.user_id not in paused_user_ids]
            )
        )
        plan = BroadcastPlan(
            apns_tokens=apns_tokens,
            fcm_tokens=fcm_tokens,
            sms_numbers=[],
            tenant_slug=_tenant(request).slug,
        )
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


@router.post("/admin/request-help/{team_assist_id}/clear", include_in_schema=False)
async def admin_clear_request_help(
    request: Request,
    team_assist_id: int,
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    existing = await _incident_store(request).get_team_assist(team_assist_id)
    if existing is None:
        _set_flash(request, error="Help request was not found.")
        return RedirectResponse(url="/admin#request-help", status_code=status.HTTP_303_SEE_OTHER)
    if existing.status in {"resolved", "cancelled"}:
        _set_flash(request, message="Help request is already cleared.")
        return RedirectResponse(url="/admin#request-help", status_code=status.HTTP_303_SEE_OTHER)

    actor_user_id = _session_user_id(request) or 0
    actor_label = _current_school_actor_label(request)
    updated = await _incident_store(request).update_team_assist_action(
        team_assist_id=team_assist_id,
        status="resolved",
        acted_by_user_id=actor_user_id,
        acted_by_label=actor_label,
        forward_to_user_id=None,
        forward_to_label=None,
    )
    if updated is None:
        _set_flash(request, error="Help request was not found.")
        return RedirectResponse(url="/admin#request-help", status_code=status.HTTP_303_SEE_OTHER)

    await _incident_store(request).create_notification_log(
        user_id=updated.created_by,
        type_value="team_assist_action",
        payload={
            "team_assist_id": updated.id,
            "action": "admin_clear",
            "status": updated.status,
            "acted_by_user_id": actor_user_id,
            "acted_by_label": actor_label,
            "requires_two_person_cancel": False,
        },
    )
    _set_flash(request, message="Help request cleared by admin.")
    return RedirectResponse(url="/admin#request-help", status_code=status.HTTP_303_SEE_OTHER)


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
    latest = await _quiet_periods(request).active_for_user(user_id=user_id)
    if latest is not None:
        await _apply_law_enforcement_quiet_state_for_request(
            request,
            request_user_id=int(latest.user_id),
            source_request_id=int(latest.id),
            approved_by_user_id=(_session_user_id(request) or 0),
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
    await _apply_law_enforcement_quiet_state_for_request(
        request,
        request_user_id=int(record.user_id),
        source_request_id=int(record.id),
        approved_by_user_id=(_session_user_id(request) or 0),
    )
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
    await _deactivate_law_enforcement_quiet_state_for_user(request, user_id=int(record.user_id))
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
    await _deactivate_law_enforcement_quiet_state_for_user(request, user_id=int(record.user_id))
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
    title: str = Form(default=""),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    actor = request.state.admin_user
    actor_role = str(getattr(actor, "role", "")).strip().lower()
    actor_id = int(getattr(actor, "id", 0) or 0)
    existing_user = await _users(request).get_user(user_id)
    if existing_user is None:
        _set_flash(request, error=f"User #{user_id} was not found.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    if existing_user.role == ROLE_DISTRICT_ADMIN and actor_role not in {ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN}:
        _set_flash(request, error="Only district admins can modify district admin accounts.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    normalized_name = name.strip()
    normalized_role = role.strip().lower()
    normalized_title = title.strip() or None
    if not normalized_name:
        _set_flash(request, error="User name cannot be empty.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    if normalized_role not in valid_tenant_roles():
        _set_flash(request, error="Role must be one of: building_admin, teacher, staff, law_enforcement, district_admin.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    # Block self role modification
    if actor_id == user_id and normalized_role != existing_user.role:
        _set_flash(request, error="You cannot change your own role.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    # Only district_admin/super_admin may assign or remove the district_admin role
    role_is_changing = normalized_role != existing_user.role
    if role_is_changing and actor_role not in {ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN}:
        _set_flash(request, error="Only district admins can change user roles.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    # Protect last district admin — prevent demoting if they are the only one
    if existing_user.role == ROLE_DISTRICT_ADMIN and normalized_role != ROLE_DISTRICT_ADMIN:
        da_count = await _users(request).count_district_admins()
        if da_count <= 1:
            _set_flash(request, error="Cannot remove the last district admin account.")
            return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    if clear_login is None and bool(login_name.strip()) != bool(password.strip()) and bool(password.strip()):
        _set_flash(request, error="To change credentials, provide both username and password.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    being_deactivated = existing_user.is_active and (is_active is None)
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
            title=normalized_title,
        )
    except Exception as exc:
        _set_flash(request, error=f"Could not update user #{user_id}: {exc}")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    if being_deactivated:
        await _registry(request).mark_invalid_by_user(user_id)
    _fire_audit(
        request,
        "user_updated",
        actor_user_id=_session_user_id(request),
        actor_label=_current_school_actor_label(request),
        target_type="user",
        target_id=str(user_id),
        metadata={
            "name": normalized_name,
            "old_role": existing_user.role,
            "new_role": normalized_role,
            "role_changed": existing_user.role != normalized_role,
            "is_active": is_active is not None,
        },
    )
    if existing_user.role != normalized_role:
        _fire_audit(
            request,
            "user_role_changed",
            actor_user_id=_session_user_id(request),
            actor_label=_current_school_actor_label(request),
            target_type="user",
            target_id=str(user_id),
            metadata={
                "target_name": normalized_name,
                "old_role": existing_user.role,
                "new_role": normalized_role,
            },
        )
    _set_flash(request, message=f"Updated user {normalized_name}.")
    return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/users/{user_id}/tenant-assignments", include_in_schema=False)
async def admin_update_user_tenant_assignments(
    request: Request,
    user_id: int,
    tenant_ids: list[int] = Form(default=[]),
    role_for_tenant: str = Form(default=""),
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    actor = request.state.admin_user  # type: ignore[attr-defined]
    actor_role = str(getattr(actor, "role", "")).strip().lower()
    if not (
        bool(getattr(request.state, "super_admin_school_access", False))
        or actor_role == "district_admin"
        or can(actor_role, PERM_MANAGE_ASSIGNED_TENANTS)
    ):
        _set_flash(request, error="Only district admins can change cross-tenant assignments.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)

    target_user = await _users(request).get_user(int(user_id))
    if target_user is None:
        _set_flash(request, error=f"User #{int(user_id)} was not found.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)
    if target_user.role not in {"district_admin", "law_enforcement"}:
        _set_flash(request, error="Only district-admin and law-enforcement users support multi-tenant assignment.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)

    available_schools = list(getattr(request.state, "admin_available_schools", [request.state.school]))
    allowed_ids = {int(item.id) for item in available_schools}
    selected_ids = sorted({int(item) for item in tenant_ids if int(item) > 0 and int(item) in allowed_ids})
    await _user_tenants(request).replace_assignments(
        user_id=int(user_id),
        home_tenant_id=int(request.state.admin_effective_school.id),  # type: ignore[attr-defined]
        tenant_ids=selected_ids,
        role_for_tenant=role_for_tenant.strip().lower() or None,
    )
    _set_flash(request, message=f"Updated tenant assignments for {target_user.name}.")
    return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/users/bulk-archive", include_in_schema=False)
async def admin_bulk_archive_users(request: Request) -> JSONResponse:
    await _require_dashboard_admin(request)
    actor_role = str(getattr(getattr(request.state, "admin_user", None), "role", "") or "")
    try:
        body = await request.json()
        raw_ids = [int(x) for x in (body.get("user_ids") or [])]
    except Exception:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="user_ids must be a list of integers")

    success_count = 0
    skipped: list[str] = []
    for uid in raw_ids:
        user = await _users(request).get_user(uid)
        if user is None:
            skipped.append(f"#{uid}: not found")
            continue
        if getattr(user, "is_archived", False):
            skipped.append(f"#{uid}: already archived")
            continue
        if not can_archive_user(actor_role, user.role):
            skipped.append(f"#{uid}: insufficient permissions")
            continue
        if is_dashboard_role(user.role) and user.can_login and user.is_active:
            other_admins = await _users(request).count_other_dashboard_admins(uid)
            if other_admins <= 0:
                skipped.append(f"#{uid}: last active admin")
                continue
        _fire_audit(request, "user_archived", actor_user_id=_session_user_id(request),
                    actor_label=_current_school_actor_label(request),
                    target_type="user", target_id=str(uid),
                    metadata={"name": user.name, "role": user.role, "bulk": True})
        await _users(request).archive_user(uid)
        await _registry(request).mark_invalid_by_user(uid)
        success_count += 1

    return JSONResponse({"success_count": success_count, "skipped_count": len(skipped), "skipped": skipped})


@router.post("/admin/users/bulk-restore", include_in_schema=False)
async def admin_bulk_restore_users(request: Request) -> JSONResponse:
    await _require_dashboard_admin(request)
    actor_role = str(getattr(getattr(request.state, "admin_user", None), "role", "") or "")
    try:
        body = await request.json()
        raw_ids = [int(x) for x in (body.get("user_ids") or [])]
    except Exception:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="user_ids must be a list of integers")

    success_count = 0
    skipped: list[str] = []
    for uid in raw_ids:
        user = await _users(request).get_user(uid)
        if user is None:
            skipped.append(f"#{uid}: not found")
            continue
        if not getattr(user, "is_archived", False):
            skipped.append(f"#{uid}: not archived")
            continue
        if not can_archive_user(actor_role, user.role):
            skipped.append(f"#{uid}: insufficient permissions")
            continue
        _fire_audit(request, "user_restored", actor_user_id=_session_user_id(request),
                    actor_label=_current_school_actor_label(request),
                    target_type="user", target_id=str(uid),
                    metadata={"name": user.name, "role": user.role, "bulk": True})
        await _users(request).restore_user(uid)
        success_count += 1

    return JSONResponse({"success_count": success_count, "skipped_count": len(skipped), "skipped": skipped})


@router.get("/admin/users/{user_id}/audit", include_in_schema=False)
async def admin_user_audit_trail(user_id: int, request: Request) -> JSONResponse:
    await _require_dashboard_admin(request)
    actor_role = str(getattr(getattr(request.state, "admin_user", None), "role", "") or "")
    user = await _users(request).get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not can_archive_user(actor_role, user.role) and actor_role not in {ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    events = await _audit_log_svc(request).list_by_user_id(user_id, limit=50)
    return JSONResponse({
        "user_id": user_id,
        "user_name": user.name,
        "events": [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "event_type": e.event_type,
                "actor_label": e.actor_label,
                "metadata": e.metadata,
            }
            for e in events
        ],
    })


@router.get("/admin/users/{user_id}/view-as", include_in_schema=False)
async def admin_view_as_user(user_id: int, request: Request) -> JSONResponse:
    """9.1 — Read-only troubleshooting snapshot. Fires audit. Never allows actions."""
    await _require_dashboard_admin(request)
    actor = getattr(request.state, "admin_user", None)
    actor_role = str(getattr(actor, "role", "") or "").strip().lower()

    _view_as_roles = {ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN, ROLE_BUILDING_ADMIN, "admin"}
    if actor_role not in _view_as_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for view-as")

    user = await _users(request).get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # building_admin / admin cannot view DA or SA accounts
    if actor_role in {ROLE_BUILDING_ADMIN, "admin"} and user.role in {ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view users with higher privilege")

    alarm_state = await _alarm_store(request).get_state()
    recent_alerts = await _alert_log(request).list_recent(limit=5)
    quiet_status = await _quiet_periods(request).active_for_user(user_id=user.id)
    pending_quiet = await _quiet_periods(request).pending_for_user(user_id=user.id)
    active_assists = await _incident_store(request).list_active_team_assists(limit=50)

    _fire_audit(
        request,
        "user_view_as_opened",
        actor_user_id=_session_user_id(request),
        actor_label=_current_school_actor_label(request),
        target_type="user",
        target_id=str(user_id),
        metadata={"target_name": user.name, "target_role": user.role},
    )

    return JSONResponse({
        "user": {
            "id": user.id,
            "name": user.name,
            "role": user.role,
            "title": getattr(user, "title", "") or "",
            "login_name": user.login_name or "",
            "is_active": user.is_active,
            "phone": getattr(user, "phone_e164", "") or "",
            "last_login_at": str(getattr(user, "last_login_at", "") or ""),
        },
        "tenant_context": {
            "school_name": str(request.state.school.name),
            "school_slug": str(request.state.school.slug),
            "alarm_active": alarm_state.is_active,
            "alarm_is_training": alarm_state.is_training,
            "alarm_message": alarm_state.message or "",
        },
        "visible_alerts": [
            {
                "id": a.id,
                "message": a.message,
                "created_at": a.created_at,
                "is_training": a.is_training,
            }
            for a in recent_alerts
        ],
        "visible_help_requests": [
            {
                "id": a.id,
                "type": a.type,
                "status": a.status,
                "created_at": a.created_at,
                "is_own": a.created_by == user.id,
            }
            for a in active_assists
            if a.created_by == user.id
        ][:10],
        "quiet_period_status": {
            "active": quiet_status is not None,
            "expires_at": quiet_status.expires_at if quiet_status else None,
            "pending": pending_quiet is not None,
        },
    })


@router.get("/admin/analytics/buildings", include_in_schema=False)
async def admin_building_analytics(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
) -> JSONResponse:
    """9.2 — Per-building/tenant analytics. Lazy-loaded; not computed on every page load."""
    await _require_dashboard_admin(request)
    actor = getattr(request.state, "admin_user", None)
    actor_role = str(getattr(actor, "role", "") or "").strip().lower()

    if actor_role not in {ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN, ROLE_BUILDING_ADMIN, "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    cutoff_str = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    if actor_role in {ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN}:
        schools = await _district_accessible_schools(request, actor)
    else:
        schools = [getattr(request.state, "admin_effective_school", request.state.school)]

    buildings = []
    for school in schools:
        tenant = request.app.state.tenant_manager.get(school)  # type: ignore[attr-defined]
        if tenant is None:
            continue
        all_alerts = await tenant.alert_log.list_recent(limit=500)
        period_alerts = [a for a in all_alerts if str(a.created_at) >= cutoff_str]
        emergency_alerts = [a for a in period_alerts if not a.is_training]

        hr_data = await tenant.incident_store.help_request_cancellation_analytics()
        qp_all = await tenant.quiet_period_store.list_recent(limit=500)
        qp_period = sum(1 for q in qp_all if str(getattr(q, "created_at", "") or "") >= cutoff_str)

        avg_ack_s = None
        if emergency_alerts:
            most_recent = emergency_alerts[0]
            try:
                acks = await tenant.alert_log.list_acknowledgements(most_recent.id)
                alert_dt = datetime.fromisoformat(most_recent.created_at.replace("Z", "+00:00"))
                deltas = []
                for ack in acks:
                    ack_dt = datetime.fromisoformat(ack.acknowledged_at.replace("Z", "+00:00"))
                    delta = (ack_dt - alert_dt).total_seconds()
                    if 0 <= delta <= 3600:
                        deltas.append(delta)
                if deltas:
                    avg_ack_s = round(sum(deltas) / len(deltas), 1)
            except Exception:
                pass

        buildings.append({
            "building_id": str(getattr(school, "slug", "")),
            "building_name": str(getattr(school, "name", "")),
            "total_alerts": len(period_alerts),
            "emergency_alerts": len(emergency_alerts),
            "training_alerts": len(period_alerts) - len(emergency_alerts),
            "help_requests": int(hr_data.get("total", 0)),
            "cancelled_help_requests": int(hr_data.get("cancelled", 0)),
            "quiet_period_requests": qp_period,
            "avg_ack_time_seconds": avg_ack_s,
            "last_alert_at": period_alerts[0].created_at if period_alerts else None,
        })

    return JSONResponse({"buildings": buildings, "period_days": days})


@router.get("/admin/reports/district.csv", include_in_schema=False)
async def admin_district_csv_export(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
) -> StreamingResponse:
    """9.3 — District-scoped CSV export. Restricted to district_admin and super_admin."""
    await _require_dashboard_admin(request)
    actor = getattr(request.state, "admin_user", None)
    actor_role = str(getattr(actor, "role", "") or "").strip().lower()

    if actor_role not in {ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="District admin or super admin required")

    cutoff_str = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    schools = await _district_accessible_schools(request, actor)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "School", "Period (days)", "Total Alerts", "Emergency Alerts",
        "Training Alerts", "Total Help Requests", "Cancelled Help Requests",
        "Quiet Period Requests", "Last Alert (UTC)",
    ])
    for school in schools:
        tenant = request.app.state.tenant_manager.get(school)  # type: ignore[attr-defined]
        if tenant is None:
            continue
        all_alerts = await tenant.alert_log.list_recent(limit=500)
        period_alerts = [a for a in all_alerts if str(a.created_at) >= cutoff_str]
        emergency = sum(1 for a in period_alerts if not a.is_training)
        training = sum(1 for a in period_alerts if a.is_training)
        hr_data = await tenant.incident_store.help_request_cancellation_analytics()
        qp_all = await tenant.quiet_period_store.list_recent(limit=500)
        qp_period = sum(1 for q in qp_all if str(getattr(q, "created_at", "") or "") >= cutoff_str)
        last_alert = period_alerts[0].created_at[:16].replace("T", " ") if period_alerts else ""
        writer.writerow([
            str(getattr(school, "name", "")),
            days,
            len(period_alerts),
            emergency,
            training,
            int(hr_data.get("total", 0)),
            int(hr_data.get("cancelled", 0)),
            qp_period,
            last_alert,
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="district-report-{days}d.csv"'},
    )


@router.post("/admin/users/{user_id}/archive", include_in_schema=False)
async def admin_archive_user(
    user_id: int,
    request: Request,
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    user = await _users(request).get_user(user_id)
    if user is None:
        _set_flash(request, error=f"User #{user_id} was not found.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)

    if getattr(user, "is_archived", False):
        _set_flash(request, error=f"{user.name} is already archived.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)

    actor_role = str(getattr(getattr(request.state, "admin_user", None), "role", "") or "")
    if not can_archive_user(actor_role, user.role):
        if user.role == ROLE_DISTRICT_ADMIN:
            _set_flash(request, error="Only district admins can modify district admin accounts.")
        else:
            _set_flash(request, error=f"You do not have permission to archive {user.name}.")
        return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)

    if is_dashboard_role(user.role) and user.can_login and user.is_active:
        other_admins = await _users(request).count_other_dashboard_admins(user.id)
        if other_admins <= 0:
            _set_flash(request, error="You cannot archive the last active admin with dashboard login access.")
            return RedirectResponse(url="/admin?section=user-management#users", status_code=status.HTTP_303_SEE_OTHER)

    _fire_audit(
        request,
        "user_archived",
        actor_user_id=_session_user_id(request),
        actor_label=_current_school_actor_label(request),
        target_type="user",
        target_id=str(user_id),
        metadata={"name": user.name, "role": user.role},
    )
    await _users(request).archive_user(user_id)
    await _registry(request).mark_invalid_by_user(user_id)
    _set_flash(request, message=f"Archived {user.name}. You can permanently delete them from the archived users list.")
    return RedirectResponse(url="/admin?section=user-management&tab=archived", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/users/{user_id}/restore", include_in_schema=False)
async def admin_restore_user(
    user_id: int,
    request: Request,
) -> RedirectResponse:
    await _require_dashboard_admin(request)
    user = await _users(request).get_user(user_id)
    if user is None:
        _set_flash(request, error=f"User #{user_id} was not found.")
        return RedirectResponse(url="/admin?section=user-management&tab=archived", status_code=status.HTTP_303_SEE_OTHER)

    if not getattr(user, "is_archived", False):
        _set_flash(request, error=f"{user.name} is not archived.")
        return RedirectResponse(url="/admin?section=user-management&tab=archived", status_code=status.HTTP_303_SEE_OTHER)

    actor_role = str(getattr(getattr(request.state, "admin_user", None), "role", "") or "")
    if not can_archive_user(actor_role, user.role):
        if user.role == ROLE_DISTRICT_ADMIN:
            _set_flash(request, error="Only district admins can modify district admin accounts.")
        else:
            _set_flash(request, error=f"You do not have permission to restore {user.name}.")
        return RedirectResponse(url="/admin?section=user-management&tab=archived", status_code=status.HTTP_303_SEE_OTHER)

    _fire_audit(
        request,
        "user_restored",
        actor_user_id=_session_user_id(request),
        actor_label=_current_school_actor_label(request),
        target_type="user",
        target_id=str(user_id),
        metadata={"name": user.name, "role": user.role},
    )
    await _users(request).restore_user(user_id)
    _set_flash(request, message=f"Restored {user.name}. They can now log in and receive alerts.")
    return RedirectResponse(url="/admin?section=user-management", status_code=status.HTTP_303_SEE_OTHER)


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

    if not getattr(user, "is_archived", False):
        _set_flash(request, error=f"Archive {user.name} before permanently deleting them.")
        return RedirectResponse(url="/admin?section=user-management&tab=archived", status_code=status.HTTP_303_SEE_OTHER)

    actor_role = str(getattr(getattr(request.state, "admin_user", None), "role", "") or "")
    if not can_archive_user(actor_role, user.role):
        if user.role == ROLE_DISTRICT_ADMIN:
            _set_flash(request, error="Only district admins can modify district admin accounts.")
        else:
            _set_flash(request, error=f"You do not have permission to delete {user.name}.")
        return RedirectResponse(url="/admin?section=user-management&tab=archived", status_code=status.HTTP_303_SEE_OTHER)

    _fire_audit(
        request,
        "user_deleted",
        actor_user_id=_session_user_id(request),
        actor_label=_current_school_actor_label(request),
        target_type="user",
        target_id=str(user_id),
        metadata={"name": user.name, "role": user.role},
    )
    if user.role == ROLE_DISTRICT_ADMIN:
        da_total = await _users(request).count_all_district_admins()
        if da_total <= 1:
            _set_flash(request, error="Cannot delete the last district admin. At least one must remain.")
            return RedirectResponse(url="/admin?section=user-management&tab=archived", status_code=status.HTTP_303_SEE_OTHER)

    await _registry(request).mark_invalid_by_user(user_id)
    await _users(request).delete_user(user_id)

    if current_admin_id is not None and current_admin_id == user_id:
        request.session.clear()
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    _set_flash(request, message=f"Permanently deleted {user.name}.")
    return RedirectResponse(url="/admin?section=user-management&tab=archived", status_code=status.HTTP_303_SEE_OTHER)


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
                is_training=alert.is_training,
                training_label=alert.training_label,
                created_by_user_id=alert.created_by_user_id,
                triggered_by_user_id=alert.triggered_by_user_id,
                triggered_by_label=alert.triggered_by_label,
            )
            for alert in recent_alerts
        ]
    )


@router.post("/alerts/{alert_id}/ack", response_model=AlertAcknowledgeResponse)
async def acknowledge_alert(
    alert_id: int,
    body: AlertAcknowledgeRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> AlertAcknowledgeResponse:
    _assert_tenant_resolved(request)
    user_id = await _require_active_user_with_any_permission(
        _users(request),
        body.user_id,
        permissions={
            PERM_REQUEST_HELP,
            PERM_SUBMIT_QUIET_REQUEST,
            PERM_TRIGGER_OWN_TENANT_ALERTS,
            PERM_MANAGE_ASSIGNED_TENANT_INCIDENTS,
        },
    )
    alert = await _alert_log(request).get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    already_acknowledged = await _alert_log(request).has_acknowledged(alert_id=alert_id, user_id=user_id)
    user = await _users(request).get_user(user_id)
    tenant_slug = _tenant(request).slug
    record = await _alert_log(request).acknowledge(
        alert_id=alert_id,
        user_id=user_id,
        user_label=getattr(user, "login_name", None) or getattr(user, "name", None),
        tenant_slug=tenant_slug,
    )
    acknowledgement_count = await _alert_log(request).acknowledgement_count(alert_id)
    _fire_audit(
        request,
        "alert_acknowledged",
        actor_user_id=user_id,
        actor_label=record.user_label,
        target_type="alert",
        target_id=str(alert_id),
        metadata={
            "alert_id": alert_id,
            "already_acknowledged": already_acknowledged,
            "total_acknowledgements": acknowledgement_count,
        },
    )
    await _publish_alert_event(
        request,
        event="alert_acknowledged",
        alert_id=alert_id,
        extra={
            "acknowledgement": {
                "user_id": user_id,
                "user_label": record.user_label,
                "acknowledged_at": record.acknowledged_at,
                "acknowledgement_count": acknowledgement_count,
            }
        },
    )
    return AlertAcknowledgeResponse(
        alert_id=alert_id,
        user_id=user_id,
        acknowledged_at=record.acknowledged_at,
        already_acknowledged=already_acknowledged,
        acknowledgement_count=acknowledgement_count,
    )


@router.post("/incidents/create", response_model=IncidentSummary)
async def create_incident(
    body: IncidentCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_api_key),
) -> IncidentSummary:
    creator_id = await _require_active_user_with_any_permission(
        _users(request),
        body.user_id,
        permissions={PERM_TRIGGER_OWN_TENANT_ALERTS, PERM_MANAGE_ASSIGNED_TENANT_INCIDENTS},
    )
    is_sim = _is_simulation_mode(request)
    incident = await _incident_store(request).create_incident(
        type_value=body.type,
        status="active",
        created_by=creator_id,
        school_id=str(request.state.school.slug),
        target_scope=body.target_scope.strip().upper() or "ALL",
        metadata=body.metadata or {},
        is_simulation=is_sim,
    )
    await _incident_store(request).create_notification_log(
        user_id=creator_id,
        type_value="incident_created",
        payload={"incident_id": incident.id, "type": incident.type, "target_scope": incident.target_scope},
    )
    if not is_sim:
        background_tasks.add_task(
            _send_basic_push,
            request,
            message=f"Incident active: {incident.type}",
            extra_data={
                "type": "emergency",
                "triggered_by_user_id": str(creator_id),
                "silent_for_sender": "true",
            },
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
    creator_id = await _require_active_user(_users(request), body.user_id)
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
    if not _is_simulation_mode(request):
        background_tasks.add_task(
            _send_help_request_push,
            request,
            creator_id=creator_id,
            responder_user_ids=set(target_user_ids),
            message=f"{get_feature_label('request_help')}: {get_feature_label(team_assist.type)}",
            extra_data={
                "type": "help_request",
                "triggered_by_user_id": str(creator_id),
            },
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
    actor_id = await _require_active_user_with_any_permission(
        users,
        body.user_id,
        permissions={PERM_TRIGGER_OWN_TENANT_ALERTS, PERM_MANAGE_ASSIGNED_TENANT_INCIDENTS},
    )
    actor = await users.get_user(actor_id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acting user not found")

    existing = await _incident_store(request).get_team_assist(team_assist_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request help item not found")
    if existing.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request help item is already cancelled")

    if existing.status == "resolved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request help item is already resolved")

    if body.action in {"acknowledge", "responding"}:
        next_status = "acknowledged"
    elif body.action == "resolve":
        next_status = "resolved"
    else:
        next_status = body.action  # "forward" keeps its own status label
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

    ws_event = "help_request_resolved" if updated.status == "resolved" else "help_request_acknowledged"
    await _publish_simple_event(request, event=ws_event, extra={
        "event_id": f"hra_{updated.id}_{updated.status}",
        "team_assist_id": updated.id,
        "status": updated.status,
        "acted_by_label": actor.name,
    })

    return _to_team_assist_summary(updated)


@router.post("/team-assist/{team_assist_id}/cancel", response_model=TeamAssistSummary)
@router.post("/request-help/{team_assist_id}/cancel", response_model=TeamAssistSummary)
async def cancel_team_assist(
    team_assist_id: int,
    body: TeamAssistCancelRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> TeamAssistSummary:
    """Requester cancels their own help request immediately with a required reason."""
    users = _users(request)
    actor_id = await _require_active_user(users, body.user_id)
    actor = await users.get_user(actor_id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    existing = await _incident_store(request).get_team_assist(team_assist_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Help request not found")
    if existing.status in {"cancelled", "resolved"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Help request is already closed")
    if actor.id != existing.created_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the original requester can cancel their own help request",
        )

    updated = await _incident_store(request).cancel_team_assist(
        team_assist_id=team_assist_id,
        cancelled_by_user_id=actor.id,
        cancel_reason_text=body.cancel_reason_text.strip(),
        cancel_reason_category=body.cancel_reason_category.strip(),
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Help request could not be cancelled — it may have just been closed by another action",
        )

    _fire_audit(
        request,
        "help_request_cancelled",
        actor_user_id=actor.id,
        actor_label=actor.name,
        target_type="team_assist",
        target_id=str(team_assist_id),
        metadata={
            "request_id": team_assist_id,
            "created_by": existing.created_by,
            "cancelled_by": actor.id,
            "cancel_reason_text": body.cancel_reason_text.strip(),
            "cancel_reason_category": body.cancel_reason_category.strip(),
        },
    )
    await _incident_store(request).create_notification_log(
        user_id=actor.id,
        type_value="help_request_cancelled",
        payload={
            "team_assist_id": updated.id,
            "cancelled_by_user_id": actor.id,
            "cancelled_by_label": actor.name,
            "cancel_reason_text": body.cancel_reason_text.strip(),
            "cancel_reason_category": body.cancel_reason_category.strip(),
        },
    )
    return _to_team_assist_summary(updated)


@router.get("/admin/help-requests/analytics", response_model=HelpRequestCancellationAnalyticsResponse)
async def help_request_cancellation_analytics(
    request: Request,
    _: None = Depends(require_api_key),
) -> HelpRequestCancellationAnalyticsResponse:
    data = await _incident_store(request).help_request_cancellation_analytics()
    total = data["total"]
    cancelled = data["cancelled"]
    rate = round(cancelled / total, 4) if total > 0 else 0.0
    return HelpRequestCancellationAnalyticsResponse(
        total_requests=total,
        cancelled=cancelled,
        cancellation_rate=rate,
        breakdown_by_category=[
            HelpRequestCancellationCategoryBreakdown(category=cat, count=cnt)
            for cat, cnt in data["breakdown"]
        ],
    )


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
                title=u.title,
            )
            for u in all_users
        ]
    )


@router.post("/users", response_model=UserSummary)
async def create_user(body: CreateUserRequest, request: Request, _: None = Depends(require_api_key)) -> UserSummary:
    user_id = await _users(request).create_user(name=body.name, role=body.role.value, phone_e164=body.phone_e164, title=body.title)
    _fire_audit(
        request,
        "user_created",
        target_type="user",
        target_id=str(user_id),
        metadata={"name": body.name, "role": body.role.value, "channel": "api"},
    )
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
        title=created.title,
    )


@router.get("/me", response_model=MeResponse)
async def get_me(
    request: Request,
    user_id: int = Query(...),
    _: None = Depends(require_api_key),
) -> MeResponse:
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active user not found")

    current_school = request.state.school
    all_schools = await _schools(request).list_schools()
    school_by_id: dict[int, object] = {int(s.id): s for s in all_schools}

    tenants: list[TenantSummaryForUser] = []
    if str(user.role).strip().lower() == "super_admin":
        for school in all_schools:
            if school.is_active:
                tenants.append(TenantSummaryForUser(
                    tenant_slug=str(school.slug),
                    tenant_name=str(school.name),
                    role="super_admin",
                ))
    else:
        tenants.append(TenantSummaryForUser(
            tenant_slug=str(current_school.slug),
            tenant_name=str(current_school.name),
            role=str(user.role),
        ))
        if str(user.role).strip().lower() == "district_admin":
            assignments = await _user_tenants(request).list_assignments(
                user_id=int(user.id),
                home_tenant_id=int(current_school.id),
            )
            seen_slugs = {str(current_school.slug)}
            for assignment in assignments:
                school = school_by_id.get(int(assignment.tenant_id))
                if school is None:
                    continue
                slug = str(getattr(school, "slug", ""))
                if slug and slug not in seen_slugs:
                    seen_slugs.add(slug)
                    tenants.append(TenantSummaryForUser(
                        tenant_slug=slug,
                        tenant_name=str(getattr(school, "name", slug)),
                        role=str(assignment.role_for_tenant) if assignment.role_for_tenant else str(user.role),
                    ))

    tenants.sort(key=lambda t: t.tenant_name.lower())
    return MeResponse(
        user_id=user.id,
        name=user.name,
        login_name=user.login_name or "",
        role=user.role,
        title=user.title,
        can_deactivate_alarm=_can_deactivate_alarm(user.role),
        tenants=tenants,
        selected_tenant=str(current_school.slug),
    )


@router.post("/me/selected-tenant", response_model=SelectTenantResponse)
async def select_tenant(
    body: SelectTenantRequest,
    request: Request,
    user_id: int = Query(...),
    _: None = Depends(require_api_key),
) -> SelectTenantResponse:
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active user not found")

    target_slug = str(body.tenant_slug).strip().lower()
    all_schools = await _schools(request).list_schools()
    target_school = next(
        (s for s in all_schools if str(getattr(s, "slug", "")).strip().lower() == target_slug),
        None,
    )
    if target_school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    current_school = request.state.school
    role_for_tenant: Optional[str] = None

    if str(user.role).strip().lower() == "super_admin":
        role_for_tenant = "super_admin"
    elif str(getattr(target_school, "slug", "")) == str(current_school.slug):
        role_for_tenant = str(user.role)
    elif str(user.role).strip().lower() == "district_admin":
        assignments = await _user_tenants(request).list_assignments(
            user_id=int(user.id),
            home_tenant_id=int(current_school.id),
        )
        school_by_id: dict[int, object] = {int(s.id): s for s in all_schools}
        for assignment in assignments:
            school = school_by_id.get(int(assignment.tenant_id))
            if school is None:
                continue
            if str(getattr(school, "slug", "")).strip().lower() == target_slug:
                role_for_tenant = str(assignment.role_for_tenant) if assignment.role_for_tenant else str(user.role)
                break
        if role_for_tenant is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not assigned to requested tenant")
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not assigned to requested tenant")

    return SelectTenantResponse(
        tenant_slug=str(getattr(target_school, "slug", target_slug)),
        tenant_name=str(getattr(target_school, "name", target_slug)),
        role=role_for_tenant,
    )


@router.get("/district/overview", response_model=DistrictOverviewResponse)
async def district_overview(
    request: Request,
    user_id: int = Query(...),
    _: None = Depends(require_api_key),
) -> DistrictOverviewResponse:
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active user not found")
    if not can_any(user.role, {PERM_MANAGE_ASSIGNED_TENANTS, PERM_FULL_ACCESS}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only district or platform admins can access district overview")

    current_school = request.state.school
    all_schools = await _schools(request).list_schools()

    if str(user.role).strip().lower() == "super_admin":
        accessible_schools = [s for s in all_schools if s.is_active]
    else:
        school_by_id: dict[int, object] = {int(s.id): s for s in all_schools}
        accessible: dict[str, object] = {str(current_school.slug): current_school}
        assignments = await _user_tenants(request).list_assignments(
            user_id=int(user.id),
            home_tenant_id=int(current_school.id),
        )
        for assignment in assignments:
            school = school_by_id.get(int(assignment.tenant_id))
            if school is not None:
                slug = str(getattr(school, "slug", ""))
                if slug:
                    accessible[slug] = school
        accessible_schools = sorted(accessible.values(), key=lambda s: str(getattr(s, "name", "")).lower())

    raw_items = await asyncio.gather(*[
        _fetch_school_status(school, request.app.state.tenant_manager.get(school))  # type: ignore[attr-defined]
        for school in accessible_schools
    ])
    items = sorted(
        [
            TenantOverviewItem(
                tenant_slug=d["tenant_slug"],
                tenant_name=d["tenant_name"],
                alarm_is_active=d["alarm_is_active"],
                alarm_message=cast(Optional[str], d["alarm_message"] or None),
                alarm_is_training=d["alarm_is_training"],
                last_alert_at=d["last_alert_at"],
                acknowledgement_count=d["ack_count"],
                expected_user_count=d["expected_users"],
                acknowledgement_rate=d["ack_rate"],
            )
            for d in raw_items
        ],
        key=lambda i: i.tenant_name.lower(),
    )
    return DistrictOverviewResponse(tenant_count=len(items), tenants=items)


async def _district_accessible_schools(request: Request, user) -> list:
    """Return list of schools accessible to a district/super admin."""
    current_school = request.state.school
    all_schools = await _schools(request).list_schools()
    user_role = str(getattr(user, "role", "")).strip().lower()
    if user_role == "super_admin":
        return [s for s in all_schools if s.is_active]
    school_by_id: dict[int, object] = {int(s.id): s for s in all_schools}
    accessible: dict[str, object] = {str(current_school.slug): current_school}
    assignments = await _user_tenants(request).list_assignments(
        user_id=int(user.id),
        home_tenant_id=int(current_school.id),
    )
    for assignment in assignments:
        school = school_by_id.get(int(assignment.tenant_id))
        if school is not None and getattr(school, "is_active", True):
            slug = str(getattr(school, "slug", ""))
            if slug:
                accessible[slug] = school
    return list(accessible.values())


async def _district_verify_school_access(request: Request, user, tenant_slug: str) -> object:
    """Return the School object if user has access; raise 403/404 otherwise."""
    school = request.app.state.tenant_manager.school_for_slug(tenant_slug)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found")
    user_role = str(getattr(user, "role", "")).strip().lower()
    if user_role == "super_admin":
        return school
    current_school = request.state.school
    if str(school.slug) == str(current_school.slug):
        return school
    assignments = await _user_tenants(request).list_assignments(
        user_id=int(user.id),
        home_tenant_id=int(current_school.id),
    )
    assigned_ids = {int(a.tenant_id) for a in assignments}
    if int(school.id) not in assigned_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not assigned to this school")
    return school


@router.get("/district/quiet-periods", response_model=DistrictQuietPeriodsResponse)
async def district_quiet_periods(
    request: Request,
    user_id: int = Query(..., ge=1),
    _: None = Depends(require_api_key),
) -> DistrictQuietPeriodsResponse:
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active user not found")
    if not can_any(user.role, {PERM_MANAGE_ASSIGNED_TENANTS, PERM_FULL_ACCESS}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    accessible_schools = await _district_accessible_schools(request, user)
    items: list[DistrictQuietPeriodItem] = []
    for school in accessible_schools:
        tenant = request.app.state.tenant_manager.get(school)
        if tenant is None:
            continue
        records = await tenant.quiet_period_store.list_recent(limit=100)
        pending = [r for r in records if r.status == "pending"]
        all_users = await tenant.user_store.list_users()
        users_by_id = {int(u.id): u for u in all_users}
        for r in pending:
            u = users_by_id.get(int(r.user_id))
            items.append(DistrictQuietPeriodItem(
                request_id=r.id,
                user_id=r.user_id,
                user_name=u.name if u is not None else None,
                user_role=u.role if u is not None else None,
                reason=r.reason,
                status=r.status,
                requested_at=r.requested_at,
                approved_at=r.approved_at,
                approved_by_user_id=r.approved_by_user_id,
                approved_by_label=r.approved_by_label,
                expires_at=r.expires_at,
                tenant_slug=str(school.slug),
                tenant_name=str(school.name),
            ))
    items.sort(key=lambda x: x.requested_at, reverse=True)
    return DistrictQuietPeriodsResponse(requests=items)


@router.post("/district/quiet-periods/{request_id}/approve", response_model=QuietPeriodSummary)
async def district_approve_quiet_period(
    request_id: int,
    body: DistrictQuietActionRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> QuietPeriodSummary:
    admin = await _users(request).get_user(body.admin_user_id)
    if admin is None or not admin.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin not found or inactive")
    if not can_any(admin.role, {PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS, PERM_FULL_ACCESS}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    school = await _district_verify_school_access(request, admin, body.tenant_slug)
    tenant = request.app.state.tenant_manager.get(school)
    pending = await tenant.quiet_period_store.get_request(request_id=request_id)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if int(pending.user_id) == int(body.admin_user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot approve your own quiet period request")
    record = await tenant.quiet_period_store.approve_request(
        request_id=request_id,
        admin_user_id=int(body.admin_user_id),
        admin_label=admin.name,
    )
    if record is None or record.status != "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quiet period request is not pending")
    _fire_audit(
        request,
        "quiet_period_approved",
        actor_user_id=int(body.admin_user_id),
        actor_label=admin.name,
        target_type="quiet_period_request",
        target_id=str(record.id),
        metadata={"requester_user_id": int(record.user_id), "tenant_slug": body.tenant_slug},
    )
    return _to_quiet_period_summary(record)


@router.post("/district/quiet-periods/{request_id}/deny", response_model=QuietPeriodSummary)
async def district_deny_quiet_period(
    request_id: int,
    body: DistrictQuietActionRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> QuietPeriodSummary:
    admin = await _users(request).get_user(body.admin_user_id)
    if admin is None or not admin.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin not found or inactive")
    if not can_any(admin.role, {PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS, PERM_FULL_ACCESS}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    school = await _district_verify_school_access(request, admin, body.tenant_slug)
    tenant = request.app.state.tenant_manager.get(school)
    pending = await tenant.quiet_period_store.get_request(request_id=request_id)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if int(pending.user_id) == int(body.admin_user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot deny your own quiet period request")
    record = await tenant.quiet_period_store.deny_request(
        request_id=request_id,
        admin_user_id=int(body.admin_user_id),
        admin_label=admin.name,
    )
    if record is None or record.status != "denied":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quiet period request is not pending")
    _fire_audit(
        request,
        "quiet_period_denied",
        actor_user_id=int(body.admin_user_id),
        actor_label=admin.name,
        target_type="quiet_period_request",
        target_id=str(record.id),
        metadata={"requester_user_id": int(record.user_id), "tenant_slug": body.tenant_slug},
    )
    return _to_quiet_period_summary(record)


@router.get("/district/audit-log", response_model=AuditLogResponse)
async def district_audit_log(
    request: Request,
    user_id: int = Query(..., ge=1),
    limit: int = Query(default=50, le=200),
    _: None = Depends(require_api_key),
) -> AuditLogResponse:
    users = _users(request)
    admin = await users.get_user(user_id)
    if admin is None or not admin.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin not found or inactive")
    if not can_any(admin.role, {PERM_MANAGE_ASSIGNED_TENANT_USERS, PERM_FULL_ACCESS}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    schools = await _district_accessible_schools(request, admin)
    per_school_limit = max(limit, 20)
    all_events: list[AuditLogEntry] = []
    for school in schools:
        tenant = request.app.state.tenant_manager.get(school)
        raw = await tenant.audit_log_service.list_recent(limit=per_school_limit)
        slug = str(getattr(school, "slug", ""))
        for e in raw:
            all_events.append(
                AuditLogEntry(
                    id=e.id,
                    timestamp=e.timestamp,
                    event_type=e.event_type,
                    actor_user_id=e.actor_user_id,
                    actor_label=e.actor_label,
                    target_type=e.target_type,
                    target_id=e.target_id,
                    metadata={**(e.metadata or {}), "tenant_slug": slug},
                )
            )
    all_events.sort(key=lambda e: e.timestamp or "", reverse=True)
    return AuditLogResponse(events=all_events[:limit])


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
    _fire_audit(
        request,
        "device_registered",
        actor_user_id=body.user_id,
        target_type="device",
        metadata={
            "platform": body.platform.value,
            "provider": body.push_provider.value,
            "device_name": body.device_name,
            "registered": registered,
        },
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
    user_id = await _require_active_user(_users(request), body.user_id)
    user = await _users(request).get_user(user_id)
    record = await _quiet_periods(request).request_quiet_period(
        user_id=user_id,
        reason=body.reason,
    )
    _fire_audit(
        request,
        "quiet_period_requested",
        actor_user_id=user_id,
        actor_label=user.name if user else None,
        target_type="quiet_period_request",
        target_id=str(record.id),
        metadata={"reason": body.reason},
    )
    await _publish_simple_event(request, event="quiet_request_created", extra={
        "request_id": record.id,
        "user_id": record.user_id,
        "event_id": f"qrc_{record.id}",
    })
    return _to_quiet_period_summary(record)


@router.get("/quiet-periods/admin/requests", response_model=QuietPeriodAdminListResponse)
async def admin_quiet_period_requests(
    request: Request,
    admin_user_id: int = Query(..., ge=1),
    limit: int = Query(default=100, ge=1, le=300),
    _: None = Depends(require_api_key),
) -> QuietPeriodAdminListResponse:
    await _require_active_user_with_any_permission(
        _users(request),
        admin_user_id,
        permissions={PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS, PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS},
    )
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
    admin_id = await _require_active_user_with_any_permission(
        _users(request),
        body.admin_user_id,
        permissions={PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS, PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS},
    )
    pending = await _quiet_periods(request).get_request(request_id=request_id)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiet period request not found")
    if int(pending.user_id) == admin_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot approve your own quiet period request")
    admin_user = await _users(request).get_user(admin_id)
    record = await _quiet_periods(request).approve_request(
        request_id=request_id,
        admin_user_id=admin_id,
        admin_label=admin_user.name if admin_user is not None else None,
    )
    if record is None or record.status != "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quiet period request is not pending")
    await _apply_law_enforcement_quiet_state_for_request(
        request,
        request_user_id=int(record.user_id),
        source_request_id=int(record.id),
        approved_by_user_id=admin_id,
    )
    _fire_audit(
        request,
        "quiet_period_approved",
        actor_user_id=admin_id,
        actor_label=admin_user.name if admin_user else None,
        target_type="quiet_period_request",
        target_id=str(record.id),
        metadata={"requester_user_id": int(record.user_id)},
    )
    try:
        # Bypass quiet suppression: the recipient IS the user just granted quiet,
        # so _push_tokens_for_scope would filter them out. Query registry directly.
        _target_uid = int(record.user_id)
        _push_apns = [d.token for d in await _registry(request).list_by_provider("apns") if d.user_id == _target_uid and d.is_valid]
        _push_fcm = [d.token for d in await _registry(request).list_by_provider("fcm") if d.user_id == _target_uid and d.is_valid]
        await _send_quiet_period_push_bg(
            _apns(request), _fcm(request), _push_apns, _push_fcm,
            title="Quiet Period Approved",
            message="Your quiet period request has been approved.",
            extra_data={"type": "quiet_period_update", "status": "approved", "quiet_period_id": str(record.id)},
        )
    except Exception:
        logger.debug("quiet_period approve push failed user_id=%s", record.user_id, exc_info=True)
    await _publish_simple_event(request, event="quiet_period_approved", extra={
        "request_id": record.id,
        "user_id": record.user_id,
        "expires_at": record.expires_at,
        "event_id": f"qra_{record.id}",
    })
    return _to_quiet_period_summary(record)


@router.post("/quiet-periods/{request_id}/deny", response_model=QuietPeriodSummary)
async def deny_quiet_period_request_api(
    request_id: int,
    body: QuietPeriodAdminActionRequest,
    request: Request,
    _: None = Depends(require_api_key),
) -> QuietPeriodSummary:
    admin_id = await _require_active_user_with_any_permission(
        _users(request),
        body.admin_user_id,
        permissions={PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS, PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS},
    )
    pending = await _quiet_periods(request).get_request(request_id=request_id)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiet period request not found")
    if int(pending.user_id) == admin_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot deny your own quiet period request")
    admin_user = await _users(request).get_user(admin_id)
    record = await _quiet_periods(request).deny_request(
        request_id=request_id,
        admin_user_id=admin_id,
        admin_label=admin_user.name if admin_user is not None else None,
    )
    if record is None or record.status != "denied":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quiet period request is not pending")
    await _deactivate_law_enforcement_quiet_state_for_user(request, user_id=int(record.user_id))
    _fire_audit(
        request,
        "quiet_period_denied",
        actor_user_id=admin_id,
        actor_label=admin_user.name if admin_user else None,
        target_type="quiet_period_request",
        target_id=str(record.id),
        metadata={"requester_user_id": int(record.user_id)},
    )
    try:
        _target_uid = int(record.user_id)
        _push_apns = [d.token for d in await _registry(request).list_by_provider("apns") if d.user_id == _target_uid and d.is_valid]
        _push_fcm = [d.token for d in await _registry(request).list_by_provider("fcm") if d.user_id == _target_uid and d.is_valid]
        await _send_quiet_period_push_bg(
            _apns(request), _fcm(request), _push_apns, _push_fcm,
            title="Quiet Period Denied",
            message="Your quiet period request has been denied.",
            extra_data={"type": "quiet_period_update", "status": "denied", "quiet_period_id": str(record.id)},
        )
    except Exception:
        logger.debug("quiet_period deny push failed user_id=%s", record.user_id, exc_info=True)
    await _publish_simple_event(request, event="quiet_period_denied", extra={
        "request_id": record.id,
        "user_id": record.user_id,
        "event_id": f"qrd_{record.id}",
    })
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
        return QuietPeriodStatusResponse(
            user_id=user_id,
            quiet_mode_active=await _is_effective_quiet_user(request, user_id=user_id),
        )
    return QuietPeriodStatusResponse(
        request_id=record.id,
        user_id=user_id,
        status=record.status,
        reason=record.reason,
        requested_at=record.requested_at,
        approved_at=record.approved_at,
        approved_by_label=record.approved_by_label,
        expires_at=record.expires_at,
        quiet_mode_active=await _is_effective_quiet_user(request, user_id=user_id),
    )


@router.get("/quiet-periods/my-request", response_model=QuietPeriodSummary)
async def get_my_quiet_request(
    request: Request,
    user_id: int = Query(..., ge=1),
    _: None = Depends(require_api_key),
) -> QuietPeriodSummary:
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    record = await _quiet_periods(request).pending_for_user(user_id=user_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No pending quiet period request")
    return _to_quiet_period_summary(record)


@router.delete("/quiet-periods/active", response_model=QuietPeriodSummary)
async def cancel_active_quiet_period(
    request: Request,
    user_id: int = Query(..., ge=1),
    actor_user_id: Optional[int] = Query(None, ge=1),
    _: None = Depends(require_api_key),
) -> QuietPeriodSummary:
    """Cancel the active quiet period for a user by user_id only.
    The requester can cancel their own, or an admin/district_admin can cancel on behalf."""
    effective_actor_id = actor_user_id if actor_user_id is not None else user_id
    actor = await _users(request).get_user(effective_actor_id)
    if actor is None or not actor.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Actor user not found or inactive")
    if effective_actor_id != user_id:
        if actor.role not in {ROLE_DISTRICT_ADMIN, ROLE_ADMIN, ROLE_SUPER_ADMIN}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to cancel another user's quiet period")
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found or inactive")
    record = await _quiet_periods(request).cancel_active_for_user(user_id=user_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active quiet period found for this user")
    await _deactivate_law_enforcement_quiet_state_for_user(request, user_id=int(record.user_id))
    return _to_quiet_period_summary(record)


@router.delete("/quiet-periods/request/{request_id}", response_model=QuietPeriodSummary)
async def cancel_quiet_period_request(
    request_id: int,
    request: Request,
    user_id: int = Query(..., ge=1),
    _: None = Depends(require_api_key),
) -> QuietPeriodSummary:
    user = await _users(request).get_user(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found or inactive")
    record = await _quiet_periods(request).cancel_for_user(
        request_id=request_id,
        user_id=user_id,
    )
    if record is None or record.user_id != user_id:
        # Fallback: cancel by user_id only in case client has a stale request_id
        record = await _quiet_periods(request).cancel_active_for_user(user_id=user_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active quiet period found for this user")
    if record.status not in {"cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quiet period request is not cancellable")
    await _deactivate_law_enforcement_quiet_state_for_user(request, user_id=int(record.user_id))
    return _to_quiet_period_summary(record)


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
        # Fallback: cancel by user_id only in case client has a stale request_id
        record = await _quiet_periods(request).cancel_active_for_user(user_id=body.user_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active quiet period found for this user")
    if record.status not in {"cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quiet period request is not deletable")
    await _deactivate_law_enforcement_quiet_state_for_user(request, user_id=int(record.user_id))
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
    await _publish_simple_event(request, event="message_received", extra={
        "message_id": created.id,
        "direction": "user_to_admin",
        "event_id": f"msg_{created.id}",
    })
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
        recipients = [u.id for u in all_users if u.is_active and not is_dashboard_role(u.role)]
    else:
        requested_ids = set(int(item) for item in body.recipient_user_ids if int(item) > 0)
        if body.recipient_user_id is not None and int(body.recipient_user_id) > 0:
            requested_ids.add(int(body.recipient_user_id))
        if not requested_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No recipient users selected")
        for recipient_user_id in sorted(requested_ids):
            target = await users.get_user(recipient_user_id)
            if target is None or not target.is_active or is_dashboard_role(target.role):
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
    await _publish_simple_event(request, event="message_received", extra={
        "direction": "admin_to_user",
        "sent_count": len(recipients),
        "event_id": f"msgb_{admin_id}_{int(time.time() * 1000)}",
    })
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
    if is_dashboard_role(user.role):
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

    users = _users(request)
    triggered_by_user_id = await _require_alarm_trigger_user(users, body.user_id)
    is_training = bool(body.is_training)
    training_label = body.training_label.strip() if body.training_label else None
    silent_audio = bool(body.silent_audio) and is_training
    if is_training:
        await _require_dashboard_admin_id(users, triggered_by_user_id)

    await _ensure_no_active_alarm(request)

    trigger_ip = request.client.host if request.client else None
    trigger_user_agent = request.headers.get("user-agent")

    alert_id = await _alert_log(request).log_alert(
        body.message,
        is_training=is_training,
        training_label=training_label,
        created_by_user_id=triggered_by_user_id,
        triggered_by_user_id=triggered_by_user_id,
        triggered_by_label=_current_school_actor_label(request),
        trigger_ip=trigger_ip,
        trigger_user_agent=trigger_user_agent,
    )
    await _alarm_store(request).activate(
        tenant_slug=_tenant(request).slug,
        message=body.message,
        activated_by_user_id=triggered_by_user_id,
        activated_by_label=_current_school_actor_label(request),
        is_training=is_training,
        training_label=training_label,
        silent_audio=silent_audio,
    )

    apns_devices = [] if is_training else await _registry(request).list_by_provider("apns")
    fcm_devices = [] if is_training else await _registry(request).list_by_provider("fcm")
    provider_counts = await _registry(request).provider_counts()
    device_count = await _registry(request).count()
    candidate_user_ids = {
        int(device.user_id)
        for device in (*apns_devices, *fcm_devices)
        if device.user_id is not None and int(device.user_id) > 0
    }
    candidate_user_ids.update(int(user.id) for user in await users.list_users() if int(user.id) > 0)
    paused_user_ids = await _quiet_suppressed_user_ids(request, candidate_user_ids=candidate_user_ids)
    apns_tokens = list(
        dict.fromkeys(
            [
                device.token
                for device in apns_devices
                if device.user_id is None or device.user_id not in paused_user_ids
            ]
        )
    )
    fcm_tokens = list(
        dict.fromkeys(
            [
                device.token
                for device in fcm_devices
                if device.user_id is None or device.user_id not in paused_user_ids
            ]
        )
    )
    sms_numbers = [] if is_training else await users.list_sms_targets(excluded_user_ids=sorted(paused_user_ids))

    _panic_tenant_slug = _tenant(request).slug
    logger.warning(
        "PANIC tenant=%s alert_id=%s training=%s label=%r devices=%s apns=%s fcm=%s sms_targets=%s skipped_users=%s message=%r",
        _panic_tenant_slug,
        alert_id,
        is_training,
        training_label,
        device_count,
        len(apns_tokens),
        len(fcm_tokens),
        len(sms_numbers),
        len(paused_user_ids),
        body.message,
    )

    if not is_training:
        plan = BroadcastPlan(apns_tokens=apns_tokens, fcm_tokens=fcm_tokens, sms_numbers=sms_numbers, tenant_slug=_panic_tenant_slug)
        background_tasks.add_task(_broadcaster(request).broadcast_panic, alert_id=alert_id, message=body.message, plan=plan)

    await _publish_alert_event(request, event="alert_triggered", alert_id=alert_id)

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


# ── Onboarding — public endpoints (no tenant session required) ─────────────────

def _tenant_manager(req: Request):
    return req.app.state.tenant_manager


def _build_access_code_response(rec, school) -> AccessCodeResponse:
    base_domain = ""
    _qr = AccessCodeService.qr_payload(rec.code, rec.tenant_slug)
    return AccessCodeResponse(
        id=rec.id,
        code=rec.code,
        tenant_slug=rec.tenant_slug,
        tenant_name=school.name if school else rec.tenant_slug,
        role=rec.role,
        role_label=role_display_label(rec.role),
        title=rec.title,
        created_at=rec.created_at,
        expires_at=rec.expires_at,
        max_uses=rec.max_uses,
        use_count=rec.use_count,
        status=rec.status,
        qr_payload=_qr,
        qr_payload_json=_qr,
        invite_url=AccessCodeService.invite_url(rec.code, rec.tenant_slug, base_domain or "app.bluebirdalerts.com"),
    )


@router.post("/onboarding/validate-code", response_model=ValidateCodeResponse)
async def onboarding_validate_code(request: Request, body: ValidateCodeRequest) -> ValidateCodeResponse:
    ip = _client_ip(request)
    if not _check_code_rate_limit(ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many validation attempts. Try again in a minute.")
    rec = await _access_codes(request).validate_code(body.code, body.tenant_slug)
    if rec is None:
        return ValidateCodeResponse(valid=False, error="Code is invalid, expired, or already used.")
    school = _tenant_manager(request).school_for_slug(rec.tenant_slug)
    return ValidateCodeResponse(
        valid=True,
        role=rec.role,
        role_label=role_display_label(rec.role),
        title=rec.title,
        tenant_slug=rec.tenant_slug,
        tenant_name=school.name if school else rec.tenant_slug,
    )


@router.post("/onboarding/create-account", response_model=ValidateCodeResponse)
async def onboarding_create_account(request: Request, body: CreateAccountFromCodeRequest) -> ValidateCodeResponse:
    ip = _client_ip(request)
    if not _check_code_rate_limit(ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts. Try again in a minute.")
    rec = await _access_codes(request).validate_code(body.code, body.tenant_slug)
    if rec is None:
        return ValidateCodeResponse(valid=False, error="Code is invalid, expired, or already used.")
    # Enforce: public signup codes may not create elevated roles.
    if rec.role not in CODEGEN_ALLOWED_ROLES:
        return ValidateCodeResponse(valid=False, error="This code cannot be used for public signup.")
    school = _tenant_manager(request).school_for_slug(rec.tenant_slug)
    if school is None:
        return ValidateCodeResponse(valid=False, error="School not found.")
    tenant_ctx = _tenant_manager(request).get(school)
    user_store: UserStore = tenant_ctx.user_store
    try:
        await user_store.create_user(
            name=body.name.strip(),
            role=rec.role,
            phone_e164=None,
            login_name=body.login_name.strip().lower(),
            password=body.password,
            must_change_password=False,
            title=rec.title,
        )
    except Exception as exc:
        logger.warning("onboarding create_account failed tenant=%s: %s", rec.tenant_slug, exc)
        return ValidateCodeResponse(valid=False, error="Could not create account. The username may already be taken.")
    consumed = await _access_codes(request).consume_code(rec.id)
    if not consumed:
        logger.warning("onboarding consume_code failed code_id=%s — user already created", rec.id)
    logger.info("onboarding user created tenant=%s role=%s login=%s", rec.tenant_slug, rec.role, body.login_name)
    # Audit: both events fire asynchronously; failures must not block the response.
    _login = body.login_name.strip().lower()
    try:
        await tenant_ctx.audit_log_service.log_event(
            tenant_slug=rec.tenant_slug,
            event_type="access_code_used",
            actor_label=f"signup:{_login}",
            target_type="access_code",
            target_id=str(rec.id),
            metadata={"role": rec.role, "code_id": rec.id},
        )
        await tenant_ctx.audit_log_service.log_event(
            tenant_slug=rec.tenant_slug,
            event_type="user_created_from_code",
            actor_label=f"signup:{_login}",
            target_type="user",
            metadata={"role": rec.role, "code_id": rec.id},
        )
    except Exception:
        logger.debug("Audit log failed for onboarding create_account tenant=%s", rec.tenant_slug, exc_info=True)
    return ValidateCodeResponse(
        valid=True,
        role=rec.role,
        role_label=role_display_label(rec.role),
        title=rec.title,
        tenant_slug=rec.tenant_slug,
        tenant_name=school.name,
    )


@router.post("/onboarding/validate-setup-code", response_model=ValidateSetupCodeResponse)
async def onboarding_validate_setup_code(request: Request, body: ValidateSetupCodeRequest) -> ValidateSetupCodeResponse:
    ip = _client_ip(request)
    if not _check_code_rate_limit(ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many validation attempts. Try again in a minute.")
    # Setup codes embed the tenant_slug; scan the whole platform for matching active setup code
    # We don't know the tenant until we find the code, so we search with a sentinel slug.
    # Actually, the mobile app provides tenant_slug from QR payload. We accept it as a hint.
    # Try the code against all known schools.
    schools = await _schools(request).list_schools()
    rec = None
    matched_school = None
    for school in schools:
        candidate = await _access_codes(request).validate_setup_code(body.code, school.slug)
        if candidate is not None:
            rec = candidate
            matched_school = school
            break
    if rec is None:
        return ValidateSetupCodeResponse(valid=False, error="Setup code is invalid, expired, or already used.")
    return ValidateSetupCodeResponse(
        valid=True,
        tenant_slug=rec.tenant_slug,
        tenant_name=matched_school.name if matched_school else rec.tenant_slug,
    )


@router.post("/onboarding/create-district-admin", response_model=ValidateSetupCodeResponse)
async def onboarding_create_district_admin(request: Request, body: CreateDistrictAdminRequest) -> ValidateSetupCodeResponse:
    ip = _client_ip(request)
    if not _check_code_rate_limit(ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts. Try again in a minute.")
    schools = await _schools(request).list_schools()
    rec = None
    matched_school = None
    for school in schools:
        candidate = await _access_codes(request).validate_setup_code(body.code, school.slug)
        if candidate is not None:
            rec = candidate
            matched_school = school
            break
    if rec is None:
        return ValidateSetupCodeResponse(valid=False, error="Setup code is invalid, expired, or already used.")
    if matched_school is None:
        return ValidateSetupCodeResponse(valid=False, error="School not found.")
    from app.services.permissions import ROLE_DISTRICT_ADMIN
    user_store: UserStore = _tenant_manager(request).get(matched_school).user_store
    try:
        await user_store.create_user(
            name=body.name.strip(),
            role=ROLE_DISTRICT_ADMIN,
            phone_e164=None,
            login_name=body.login_name.strip().lower(),
            password=body.password,
            must_change_password=True,
        )
    except Exception as exc:
        logger.warning("onboarding create_district_admin failed tenant=%s: %s", rec.tenant_slug, exc)
        return ValidateSetupCodeResponse(valid=False, error="Could not create account. The username may already be taken.")
    consumed = await _access_codes(request).consume_code(rec.id)
    if not consumed:
        logger.warning("onboarding consume_setup_code failed code_id=%s", rec.id)
    logger.info("onboarding district_admin created tenant=%s login=%s", rec.tenant_slug, body.login_name)
    return ValidateSetupCodeResponse(
        valid=True,
        tenant_slug=rec.tenant_slug,
        tenant_name=matched_school.name,
    )


# ── Admin web form — access codes (redirect-based, for dashboard UI) ──────────

@router.post("/admin/access-codes/generate", include_in_schema=False)
async def admin_generate_access_code_form(
    request: Request,
    tenant_slug: str = Form(...),
    role: str = Form(...),
    title: str = Form(default=""),
    max_uses: int = Form(default=1),
    expires_hours: int = Form(default=48),
) -> RedirectResponse:
    users = await _require_dashboard_admin(request)
    user_id = _session_user_id(request) or 0
    user = await users.get_user(user_id)
    if user is None or not can_generate_codes(user.role):
        _set_flash(request, error="Only district admins may generate access codes.")
        return RedirectResponse(url="/admin?section=access-codes#access-codes", status_code=status.HTTP_303_SEE_OTHER)
    normalized_role = role.strip().lower()
    if normalized_role not in CODEGEN_ALLOWED_ROLES:
        _set_flash(request, error=f"Role '{normalized_role}' is not allowed for access codes.")
        return RedirectResponse(url="/admin?section=access-codes#access-codes", status_code=status.HTTP_303_SEE_OTHER)
    effective_slug = str(getattr(request.state, "school_slug", "") or tenant_slug).strip()
    rec = await _access_codes(request).generate_code(
        tenant_slug=effective_slug,
        role=normalized_role,
        title=title.strip() or None,
        created_by_user_id=user_id,
        expires_hours=max(1, min(720, expires_hours)),
        max_uses=max(1, min(20, max_uses)),
        is_setup_code=False,
    )
    _fire_audit(
        request,
        "access_code_generated",
        actor_user_id=user_id,
        actor_label=_current_school_actor_label(request),
        target_type="access_code",
        metadata={"code_id": rec.id, "role": normalized_role, "tenant": effective_slug},
    )
    _set_flash(request, message=f"Code {rec.code} generated for role '{normalized_role}'.")
    return RedirectResponse(url="/admin?section=access-codes#access-codes", status_code=status.HTTP_303_SEE_OTHER)


# ── Admin JSON API — access codes (tenant-scoped, requires dashboard admin) ────

@router.post("/admin/access-codes/generate-api", response_model=AccessCodeResponse)
async def admin_generate_access_code(request: Request, body: GenerateAccessCodeRequest) -> AccessCodeResponse:
    users = await _require_dashboard_admin(request)
    user_id = _session_user_id(request) or 0
    user = await users.get_user(user_id)
    if user is None or not can_generate_codes(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only district admins may generate access codes.")
    if body.role not in CODEGEN_ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot generate code for role '{body.role}'. Allowed: {sorted(CODEGEN_ALLOWED_ROLES)}",
        )
    tenant_slug = str(getattr(request.state, "school_slug", "") or body.tenant_slug).strip()
    rec = await _access_codes(request).generate_code(
        tenant_slug=tenant_slug,
        role=body.role,
        title=body.title,
        created_by_user_id=user_id,
        expires_hours=body.expires_hours,
        max_uses=body.max_uses,
        is_setup_code=False,
    )
    school = _tenant_manager(request).school_for_slug(tenant_slug)
    base_domain = str(request.app.state.settings.BASE_DOMAIN).strip()
    _qr = AccessCodeService.qr_payload(rec.code, rec.tenant_slug)
    return AccessCodeResponse(
        id=rec.id,
        code=rec.code,
        tenant_slug=rec.tenant_slug,
        tenant_name=school.name if school else rec.tenant_slug,
        role=rec.role,
        role_label=role_display_label(rec.role),
        title=rec.title,
        created_at=rec.created_at,
        expires_at=rec.expires_at,
        max_uses=rec.max_uses,
        use_count=rec.use_count,
        status=rec.status,
        qr_payload=_qr,
        qr_payload_json=_qr,
        invite_url=AccessCodeService.invite_url(rec.code, rec.tenant_slug, base_domain or "app.bluebirdalerts.com"),
    )


@router.get("/admin/access-codes", response_model=AccessCodeListResponse)
async def admin_list_access_codes(request: Request, limit: int = Query(default=200, ge=1, le=500)) -> AccessCodeListResponse:
    users = await _require_dashboard_admin(request)
    user_id = _session_user_id(request) or 0
    user = await users.get_user(user_id)
    if user is None or not can_generate_codes(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to view access codes.")
    tenant_slug = str(getattr(request.state, "school_slug", "")).strip()
    records = await _access_codes(request).list_codes(tenant_slug, limit=limit)
    school = _tenant_manager(request).school_for_slug(tenant_slug)
    base_domain = str(request.app.state.settings.BASE_DOMAIN).strip()
    codes = [
        AccessCodeResponse(
            id=r.id,
            code=r.code,
            tenant_slug=r.tenant_slug,
            tenant_name=school.name if school else r.tenant_slug,
            role=r.role,
            role_label=role_display_label(r.role),
            title=r.title,
            created_at=r.created_at,
            expires_at=r.expires_at,
            max_uses=r.max_uses,
            use_count=r.use_count,
            status=r.status,
            qr_payload=AccessCodeService.qr_payload(r.code, r.tenant_slug),
            qr_payload_json=AccessCodeService.qr_payload(r.code, r.tenant_slug),
            invite_url=AccessCodeService.invite_url(r.code, r.tenant_slug, base_domain or "app.bluebirdalerts.com"),
        )
        for r in records
    ]
    return AccessCodeListResponse(codes=codes)


@router.post("/admin/access-codes/bulk-generate", include_in_schema=False)
async def admin_bulk_generate_access_codes(request: Request) -> JSONResponse:
    users = await _require_dashboard_admin(request)
    user_id = _session_user_id(request) or 0
    user = await users.get_user(user_id)
    if user is None or not can_generate_codes(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
    body = await request.json()
    quantity = max(1, min(100, int(body.get("quantity", 1))))
    role = str(body.get("role", "teacher")).strip()
    if role not in CODEGEN_ALLOWED_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role: {role}")
    title = str(body.get("title", "")).strip() or None
    expires_hours = max(1, min(720, int(body.get("expires_hours", 48))))
    label = str(body.get("label", "")).strip() or None
    assignments = []
    for a in body.get("assignments", []):
        name = str(a.get("name", "")).strip() or None
        email = str(a.get("email", "")).strip() or None
        assignments.append((name, email))
    tenant_slug = str(getattr(request.state, "school_slug", "")).strip()
    records = await _access_codes(request).generate_codes_bulk(
        tenant_slug=tenant_slug,
        role=role,
        quantity=quantity,
        title=title,
        created_by_user_id=user_id,
        expires_hours=expires_hours,
        label=label,
        assignments=assignments or None,
    )
    _fire_audit(request, "access_codes_bulk_generated", actor_user_id=user_id,
                actor_label=user.name, target_type="access_code",
                metadata={"quantity": len(records), "role": role, "label": label})
    return JSONResponse({
        "created": len(records),
        "codes": [
            {
                "id": r.id,
                "code": r.code,
                "role": r.role,
                "assigned_name": r.assigned_name,
                "assigned_email": r.assigned_email,
                "expires_at": r.expires_at,
            }
            for r in records
        ],
    })


@router.get("/admin/access-codes/bulk-packets.pdf", include_in_schema=False)
async def admin_bulk_packets_pdf(request: Request, ids: str = Query(default="")) -> StreamingResponse:
    await _require_dashboard_admin(request)
    effective_role = str(getattr(getattr(request.state, "admin_user", None), "role", "")).strip()
    if not can_generate_codes(effective_role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
    code_ids = {int(x.strip()) for x in ids.split(",") if x.strip().isdigit()}
    if not code_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid ids provided.")
    tenant_slug = str(getattr(request.state, "school_slug", "")).strip()
    school = request.state.school
    school_name = str(getattr(school, "name", tenant_slug))
    records = await _access_codes(request).list_codes(tenant_slug, limit=500)
    selected = [r for r in records if r.id in code_ids]
    if not selected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching codes found.")
    packets = []
    for rec in selected:
        payload_json = AccessCodeService.qr_payload(rec.code, rec.tenant_slug)
        qr_bytes = await anyio.to_thread.run_sync(lambda p=payload_json: _qr_png_bytes(p, box_size=14, border=4))
        packets.append((
            rec.code,
            role_display_label(rec.role),
            qr_bytes,
            rec.expires_at,
            rec.label,
            rec.assigned_name,
            rec.assigned_email,
        ))
    pdf_bytes = await anyio.to_thread.run_sync(
        lambda: generate_bulk_packets_pdf(packets, school_name)
    )
    fname = f"bluebird-onboarding-packets-{tenant_slug}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/admin/access-codes/bulk.zip", include_in_schema=False)
async def admin_bulk_zip(request: Request, ids: str = Query(default="")) -> StreamingResponse:
    await _require_dashboard_admin(request)
    effective_role = str(getattr(getattr(request.state, "admin_user", None), "role", "")).strip()
    if not can_generate_codes(effective_role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
    code_ids = {int(x.strip()) for x in ids.split(",") if x.strip().isdigit()}
    if not code_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid ids provided.")
    tenant_slug = str(getattr(request.state, "school_slug", "")).strip()
    records = await _access_codes(request).list_codes(tenant_slug, limit=500)
    selected = [r for r in records if r.id in code_ids]
    if not selected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching codes found.")

    def _build_zip() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rec in selected:
                payload_json = AccessCodeService.qr_payload(rec.code, rec.tenant_slug)
                png = _qr_png_bytes(payload_json, box_size=14, border=4)
                zf.writestr(f"bluebird-qr-{rec.code}.png", png)
        return buf.getvalue()

    zip_bytes = await anyio.to_thread.run_sync(_build_zip)
    fname = f"bluebird-qr-codes-{tenant_slug}.zip"
    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/admin/access-codes/import-csv", include_in_schema=False)
async def admin_import_codes_csv(
    request: Request,
    file: UploadFile = File(...),
    role: str = Form(default="teacher"),
    expires_hours: int = Form(default=48),
    label: str = Form(default=""),
) -> JSONResponse:
    users = await _require_dashboard_admin(request)
    user_id = _session_user_id(request) or 0
    user = await users.get_user(user_id)
    if user is None or not can_generate_codes(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
    if role not in CODEGEN_ALLOWED_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role: {role}")
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    assignments = []
    errors: list = []
    for i, row in enumerate(reader, start=2):
        name = str(row.get("name", row.get("Name", ""))).strip() or None
        email = str(row.get("email", row.get("Email", ""))).strip() or None
        if not name and not email:
            errors.append(f"Row {i}: empty name and email — skipped")
            continue
        assignments.append((name, email))
    if not assignments:
        return JSONResponse({"created": 0, "skipped": 0, "errors": errors})
    tenant_slug = str(getattr(request.state, "school_slug", "")).strip()
    records = await _access_codes(request).generate_codes_bulk(
        tenant_slug=tenant_slug,
        role=role,
        quantity=len(assignments),
        created_by_user_id=user_id,
        expires_hours=max(1, min(720, expires_hours)),
        label=label.strip() or None,
        assignments=assignments,
    )
    _fire_audit(request, "access_codes_csv_imported", actor_user_id=user_id,
                actor_label=user.name, target_type="access_code",
                metadata={"created": len(records), "role": role, "label": label})
    return JSONResponse({"created": len(records), "skipped": len(errors), "errors": errors})


@router.get("/admin/access-codes/{code_id}/qr")
async def admin_get_access_code_qr(request: Request, code_id: int) -> JSONResponse:
    """Return the QR payload for a specific access code (JSON — front end renders the image)."""
    await _require_dashboard_admin(request)
    effective_role = str(getattr(getattr(request.state, "admin_user", None), "role", "")).strip()
    if not can_generate_codes(effective_role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to view access codes.")
    tenant_slug = str(getattr(request.state, "school_slug", "")).strip()
    records = await _access_codes(request).list_codes(tenant_slug, limit=500)
    rec = next((r for r in records if r.id == code_id), None)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found.")
    import json as _json
    payload_json = AccessCodeService.qr_payload(rec.code, rec.tenant_slug)
    return JSONResponse({
        "code_id": rec.id,
        "code": rec.code,
        "tenant_slug": rec.tenant_slug,
        "qr_payload": _json.loads(payload_json),
        "qr_payload_json": payload_json,
    })


def _qr_png_bytes(payload_json: str, box_size: int = 10, border: int = 4) -> bytes:
    """Generate a QR code PNG and return raw bytes using Pillow."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload_json)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@router.get("/admin/access-codes/{code_id}/qr.png", include_in_schema=False)
async def admin_get_access_code_qr_png(request: Request, code_id: int) -> StreamingResponse:
    """Return a QR code as a PNG image for the given access code."""
    await _require_dashboard_admin(request)
    effective_role = str(getattr(getattr(request.state, "admin_user", None), "role", "")).strip()
    if not can_generate_codes(effective_role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to view access codes.")
    tenant_slug = str(getattr(request.state, "school_slug", "")).strip()
    records = await _access_codes(request).list_codes(tenant_slug, limit=500)
    rec = next((r for r in records if r.id == code_id), None)
    if rec is None or rec.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found or not active.")
    payload_json = AccessCodeService.qr_payload(rec.code, rec.tenant_slug)
    png_bytes = await anyio.to_thread.run_sync(lambda: _qr_png_bytes(payload_json))
    return StreamingResponse(
        iter([png_bytes]),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="bluebird-invite-{rec.code}.png"'},
    )


@router.get("/admin/access-codes/{code_id}/print", include_in_schema=False)
async def admin_get_access_code_print(request: Request, code_id: int) -> HTMLResponse:
    """Return a printable HTML onboarding sheet for a single access code."""
    from html import escape as _esc
    import base64 as _b64
    await _require_dashboard_admin(request)
    effective_role = str(getattr(getattr(request.state, "admin_user", None), "role", "")).strip()
    if not can_generate_codes(effective_role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to view access codes.")
    tenant_slug = str(getattr(request.state, "school_slug", "")).strip()
    school = request.state.school
    school_name = _esc(str(getattr(school, "name", tenant_slug)))
    records = await _access_codes(request).list_codes(tenant_slug, limit=500)
    rec = next((r for r in records if r.id == code_id), None)
    if rec is None or rec.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found or not active.")
    payload_json = AccessCodeService.qr_payload(rec.code, rec.tenant_slug)
    png_bytes = await anyio.to_thread.run_sync(lambda: _qr_png_bytes(payload_json, box_size=14, border=4))
    qr_b64 = _b64.b64encode(png_bytes).decode("ascii")
    code_display = _esc(rec.code)
    slug_display = _esc(rec.tenant_slug)
    role_display = _esc(role_display_label(rec.role))
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BlueBird Alerts — Onboarding Sheet</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      background: #fff;
      color: #111;
      padding: 40px 48px;
      max-width: 680px;
      margin: 0 auto;
    }}
    .header {{
      display: flex;
      align-items: center;
      gap: 16px;
      border-bottom: 2px solid #1a3a5c;
      padding-bottom: 16px;
      margin-bottom: 28px;
    }}
    .header-logo {{ font-size: 2rem; }}
    .header-text h1 {{ font-size: 1.4rem; font-weight: 700; color: #1a3a5c; }}
    .header-text p {{ font-size: 0.9rem; color: #555; margin-top: 2px; }}
    .school-name {{
      font-size: 1.1rem;
      font-weight: 600;
      color: #1a3a5c;
      margin-bottom: 24px;
      text-align: center;
    }}
    .headline {{
      font-size: 1.35rem;
      font-weight: 700;
      text-align: center;
      margin-bottom: 28px;
      color: #111;
    }}
    .qr-block {{
      text-align: center;
      margin: 0 auto 28px;
    }}
    .qr-block img {{
      width: 240px;
      height: 240px;
      image-rendering: pixelated;
      border: 1px solid #ddd;
      padding: 8px;
      background: #fff;
    }}
    .code-fallback {{
      text-align: center;
      margin-bottom: 28px;
    }}
    .code-label {{ font-size: 0.8rem; color: #666; margin-bottom: 4px; }}
    .code-value {{
      font-family: "Courier New", monospace;
      font-size: 2rem;
      font-weight: 700;
      letter-spacing: 0.15em;
      color: #1a3a5c;
      border: 2px dashed #1a3a5c;
      display: inline-block;
      padding: 8px 24px;
      border-radius: 6px;
    }}
    .meta {{ text-align: center; font-size: 0.8rem; color: #888; margin-bottom: 28px; }}
    .instructions {{
      border-top: 1px solid #e0e0e0;
      padding-top: 20px;
    }}
    .instructions h2 {{ font-size: 1rem; font-weight: 700; margin-bottom: 12px; }}
    .instructions ol {{ padding-left: 20px; }}
    .instructions li {{
      font-size: 0.95rem;
      line-height: 1.7;
      color: #222;
    }}
    .footer {{
      margin-top: 32px;
      font-size: 0.75rem;
      color: #aaa;
      text-align: center;
      border-top: 1px solid #eee;
      padding-top: 12px;
    }}
    @media print {{
      body {{ padding: 20px 24px; }}
      @page {{ margin: 15mm; }}
    }}
  </style>
</head>
<body>
  <div class="header">
    <div class="header-logo">&#127284;</div>
    <div class="header-text">
      <h1>BlueBird Alerts</h1>
      <p>Emergency notification platform</p>
    </div>
  </div>

  <p class="school-name">{school_name}</p>

  <p class="headline">Scan to join BlueBird Alerts</p>

  <div class="qr-block">
    <img src="data:image/png;base64,{qr_b64}" alt="QR Code for {code_display}" />
  </div>

  <div class="code-fallback">
    <p class="code-label">Or enter this code manually</p>
    <span class="code-value">{code_display}</span>
  </div>

  <div class="meta">District code: {slug_display} &nbsp;&middot;&nbsp; Role: {role_display}</div>

  <div class="instructions">
    <h2>How to set up your account:</h2>
    <ol>
      <li>Download the <strong>BlueBird Alerts</strong> app from the App Store or Google Play</li>
      <li>Open the app and tap <strong>Get Started</strong></li>
      <li>Scan this QR code &mdash; or enter your district code and the code above manually</li>
      <li>Create your username and password</li>
      <li>You&rsquo;re ready to receive emergency alerts</li>
    </ol>
  </div>

  <div class="footer">
    Generated by BlueBird Alerts &nbsp;&middot;&nbsp; {school_name}
  </div>
</body>
<script>
  window.addEventListener("load", function() {{
    setTimeout(function() {{ window.print(); }}, 400);
  }});
</script>
</html>""")


@router.get("/admin/access-codes/{code_id}/packet.pdf", include_in_schema=False)
async def admin_get_access_code_packet_pdf(request: Request, code_id: int) -> StreamingResponse:
    """Return a PDF onboarding packet for a single access code."""
    await _require_dashboard_admin(request)
    effective_role = str(getattr(getattr(request.state, "admin_user", None), "role", "")).strip()
    if not can_generate_codes(effective_role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
    tenant_slug = str(getattr(request.state, "school_slug", "")).strip()
    school = request.state.school
    school_name = str(getattr(school, "name", tenant_slug))
    records = await _access_codes(request).list_codes(tenant_slug, limit=500)
    rec = next((r for r in records if r.id == code_id), None)
    if rec is None or rec.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found or not active.")
    payload_json = AccessCodeService.qr_payload(rec.code, rec.tenant_slug)
    qr_bytes = await anyio.to_thread.run_sync(lambda: _qr_png_bytes(payload_json, box_size=14, border=4))
    pdf_bytes = await anyio.to_thread.run_sync(
        lambda: generate_packet_pdf(
            school_name=school_name,
            code_text=rec.code,
            role_label=role_display_label(rec.role),
            qr_png_bytes=qr_bytes,
            expires_at=rec.expires_at,
            label=rec.label,
            assigned_name=rec.assigned_name,
            assigned_email=rec.assigned_email,
        )
    )
    fname = f"bluebird-onboarding-{rec.code}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/admin/access-codes/{code_id}/revoke", include_in_schema=False)
async def admin_revoke_access_code(request: Request, code_id: int):
    users = await _require_dashboard_admin(request)
    user_id = _session_user_id(request) or 0
    user = await users.get_user(user_id)
    _is_form = "application/x-www-form-urlencoded" in request.headers.get("content-type", "")
    if user is None or not can_generate_codes(user.role):
        if _is_form:
            _set_flash(request, error="Only district admins may revoke access codes.")
            return RedirectResponse(url="/admin?section=access-codes#access-codes", status_code=status.HTTP_303_SEE_OTHER)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only district admins may revoke access codes.")
    tenant_slug = str(getattr(request.state, "school_slug", "")).strip()
    ok = await _access_codes(request).revoke_code(code_id, tenant_slug)
    if _is_form:
        if ok:
            _set_flash(request, message="Code revoked.")
        else:
            _set_flash(request, error="Code not found or already revoked.")
        return RedirectResponse(url="/admin?section=access-codes#access-codes", status_code=status.HTTP_303_SEE_OTHER)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found or already revoked.")
    return JSONResponse({"revoked": True, "code_id": code_id})


@router.post("/admin/access-codes/{code_id}/send-invite", response_model=None)
async def admin_send_invite_email(request: Request, code_id: int, body: SendInviteEmailRequest) -> JSONResponse:
    users = await _require_dashboard_admin(request)
    user_id = _session_user_id(request) or 0
    user = await users.get_user(user_id)
    if user is None or not can_generate_codes(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only district admins may send invite emails.")
    tenant_slug = str(getattr(request.state, "school_slug", "")).strip()
    records = await _access_codes(request).list_codes(tenant_slug, limit=500)
    rec = next((r for r in records if r.id == code_id), None)
    if rec is None or rec.status not in ("active",):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active code not found.")
    email_svc = _email_service(request)
    if not email_svc.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email is not configured on this server.")
    base_domain = str(request.app.state.settings.BASE_DOMAIN).strip() or "app.bluebirdalerts.com"
    url = AccessCodeService.invite_url(rec.code, rec.tenant_slug, base_domain)
    school = _tenant_manager(request).school_for_slug(tenant_slug)
    school_name = school.name if school else tenant_slug
    subject = f"You've been invited to {school_name} on BlueBird Alerts"
    body_text = (
        f"Hi,\n\n"
        f"You've been invited to join {school_name} on BlueBird Alerts as a {role_display_label(rec.role)}.\n\n"
        f"Use your invite code to set up your account:\n\n"
        f"  Code: {rec.code}\n"
        f"  Direct link: {url}\n\n"
        f"This code expires at {rec.expires_at[:10]} UTC.\n\n"
        f"— BlueBird Alerts"
    )
    ok = await email_svc.send_email(
        to_address=body.email,
        subject=subject,
        body=body_text,
        event_type="invite_email",
    )
    await _access_codes(request).set_invite_email(code_id, tenant_slug, body.email)
    return JSONResponse({"sent": ok, "email": body.email})


# ── Super-admin — setup codes (district admin bootstrap) ───────────────────────

@router.post("/super-admin/setup-codes/generate", include_in_schema=False)
async def super_admin_generate_setup_code(
    request: Request,
    tenant_slug: str = Form(...),
    expires_hours: int = Form(default=168),
) -> RedirectResponse:
    _require_super_admin(request)
    school = await _schools(request).get_by_slug(tenant_slug.strip().lower())
    if school is None:
        _set_flash(request, error=f"School '{tenant_slug}' not found.")
        return RedirectResponse(url=_super_admin_url("setup-codes"), status_code=status.HTTP_303_SEE_OTHER)
    if expires_hours < 1 or expires_hours > 8760:
        _set_flash(request, error="Expiry must be between 1 and 8760 hours.")
        return RedirectResponse(url=_super_admin_url("setup-codes"), status_code=status.HTTP_303_SEE_OTHER)
    rec = await _access_codes(request).generate_code(
        tenant_slug=school.slug,
        role="district_admin",
        title="District Admin",
        created_by_user_id=0,
        expires_hours=expires_hours,
        max_uses=1,
        is_setup_code=True,
    )
    logger.info("super_admin generated setup code id=%s tenant=%s", rec.id, school.slug)
    _set_flash(request, message=f"Setup code {rec.code} created for {school.name}. Expires in {expires_hours}h.")
    return RedirectResponse(url=_super_admin_url("setup-codes"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/setup-codes/{code_id}/revoke", include_in_schema=False)
async def super_admin_revoke_setup_code(request: Request, code_id: int) -> RedirectResponse:
    _require_super_admin(request)
    # Setup codes have tenant_slug but revoke needs it — look it up first
    codes = await _access_codes(request).list_setup_codes(limit=500)
    rec = next((c for c in codes if c.id == code_id), None)
    if rec is None:
        _set_flash(request, error="Setup code not found.")
        return RedirectResponse(url=_super_admin_url("setup-codes"), status_code=status.HTTP_303_SEE_OTHER)
    ok = await _access_codes(request).revoke_code(code_id, rec.tenant_slug)
    if ok:
        _set_flash(request, message=f"Setup code {rec.code} revoked.")
    else:
        _set_flash(request, error="Could not revoke code.")
    return RedirectResponse(url=_super_admin_url("setup-codes"), status_code=status.HTTP_303_SEE_OTHER)


# ── Sandbox / test environment endpoints ──────────────────────────────────────
# All guarded by _require_super_admin.  Production districts/schools are
# protected at the DB layer (is_test=1 WHERE clause), but we also guard at the
# route layer for defense in depth.

@router.post("/super-admin/districts/{district_id}/clone-test", include_in_schema=False)
async def super_admin_clone_test_district(
    district_id: int,
    request: Request,
    test_slug: str = Form(...),
    test_name: str = Form(...),
) -> RedirectResponse:
    """Clone a production district into a test/sandbox district."""
    _require_super_admin(request)
    school_registry = _schools(request)
    source = await school_registry.get_district(district_id)
    if source is None:
        _set_flash(request, error="Source district not found.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)
    if source.is_test:
        _set_flash(request, error="Cannot clone a test district from another test district.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)

    slug = test_slug.strip().lower()
    name = test_name.strip() or f"[TEST] {source.name}"
    existing = await school_registry.get_district_by_slug(slug)
    if existing is not None:
        _set_flash(request, error=f"Slug '{slug}' already taken.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)

    test_district = await school_registry.create_test_district(
        name=name,
        slug=slug,
        organization_id=source.organization_id,
        source_district_id=district_id,
    )

    # Clone each school in the source district into test schools.
    source_schools = await school_registry.list_schools_by_district(district_id)
    for i, src_school in enumerate(source_schools):
        school_slug = f"{slug}-{src_school.slug}"
        existing_school = await school_registry.get_by_slug(school_slug)
        if existing_school is None:
            test_school = await school_registry.create_test_school(
                name=f"[TEST] {src_school.name}",
                slug=school_slug,
                district_id=test_district.id,
                source_tenant_slug=src_school.slug,
                accent=src_school.accent,
                accent_strong=src_school.accent_strong,
                sidebar_start=src_school.sidebar_start,
                sidebar_end=src_school.sidebar_end,
                logo_path=src_school.logo_path,
            )
            # Eagerly init the test tenant DB (empty — no users/data carried over).
            from app.services.tenant_manager import TenantManager
            tm: TenantManager = request.app.state.tenant_manager  # type: ignore[attr-defined]
            tm.get(test_school)

    logger.warning(
        "SANDBOX district_cloned actor=%s source_district_id=%s test_slug=%s schools=%s",
        request.session.get("super_admin_username", "super_admin"), district_id, slug, len(source_schools),
    )
    _set_flash(request, message=f"Test district '{name}' created with {len(source_schools)} school(s).")
    return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/test-tenants/{slug}/toggle-simulation", include_in_schema=False)
async def super_admin_toggle_simulation_mode(slug: str, request: Request) -> RedirectResponse:
    """Enable or disable simulation mode for a test school."""
    _require_super_admin(request)
    school_registry = _schools(request)
    school = await school_registry.get_by_slug(slug)
    if school is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)
    if not school.is_test:
        _set_flash(request, error="Cannot enable simulation mode on a production school.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)

    new_state = not school.simulation_mode_enabled
    await school_registry.set_simulation_mode(slug=slug, enabled=new_state)
    label = "enabled" if new_state else "disabled"
    logger.warning(
        "SANDBOX simulation_mode_toggled actor=%s slug=%s enabled=%s",
        request.session.get("super_admin_username", "super_admin"), slug, new_state,
    )
    _set_flash(request, message=f"Simulation mode {label} for '{slug}'.")
    return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/test-tenants/{slug}/toggle-audio-suppression", include_in_schema=False)
async def super_admin_toggle_audio_suppression(slug: str, request: Request) -> RedirectResponse:
    """Enable or disable alarm audio suppression for a test school."""
    _require_super_admin(request)
    school_registry = _schools(request)
    school = await school_registry.get_by_slug(slug)
    if school is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)
    if not school.is_test:
        _set_flash(request, error="Cannot modify audio suppression on a production school.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)

    new_state = not school.suppress_alarm_audio
    await school_registry.set_audio_suppression(slug=slug, enabled=new_state)
    label = "enabled" if new_state else "disabled"
    logger.warning(
        "SANDBOX audio_suppression_toggled actor=%s slug=%s enabled=%s",
        request.session.get("super_admin_username", "super_admin"), slug, new_state,
    )
    _set_flash(request, message=f"Audio suppression {label} for '{slug}'.")
    return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/test-tenants/{slug}/simulate-alert", include_in_schema=False)
async def super_admin_simulate_alert(slug: str, request: Request, alert_type: str = Form(default="lockdown")) -> RedirectResponse:
    """Trigger a simulated incident in a test school (no real push sent)."""
    _require_super_admin(request)
    school_registry = _schools(request)
    school = await school_registry.get_by_slug(slug)
    if school is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)
    if not school.is_test:
        _set_flash(request, error="Cannot trigger simulated alert on a production school.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)

    from app.services.tenant_manager import TenantManager
    tm: TenantManager = request.app.state.tenant_manager  # type: ignore[attr-defined]
    tenant_ctx = tm.get(school)
    incident = await tenant_ctx.incident_store.create_incident(
        type_value=alert_type.strip() or "lockdown",
        status="active",
        created_by=0,
        school_id=slug,
        target_scope="ALL",
        metadata={"simulated": True},
        is_simulation=True,
    )
    logger.warning(
        "SANDBOX alert_simulated actor=%s slug=%s alert_type=%s incident_id=%s",
        request.session.get("super_admin_username", "super_admin"), slug, alert_type, incident.id,
    )
    _set_flash(request, message=f"Simulated {alert_type} incident created in '{slug}'.")
    return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/test-tenants/{slug}/reset", include_in_schema=False)
async def super_admin_reset_test_tenant(slug: str, request: Request) -> RedirectResponse:
    """Delete all simulation incidents in a test school (reset to clean state)."""
    _require_super_admin(request)
    school_registry = _schools(request)
    school = await school_registry.get_by_slug(slug)
    if school is None:
        _set_flash(request, error="School not found.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)
    if not school.is_test:
        _set_flash(request, error="Cannot reset a production school.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)

    from app.services.tenant_manager import TenantManager
    tm: TenantManager = request.app.state.tenant_manager  # type: ignore[attr-defined]
    tenant_ctx = tm.get(school)
    deleted = await tenant_ctx.incident_store.delete_simulation_incidents()
    logger.warning(
        "SANDBOX tenant_reset actor=%s slug=%s incidents_deleted=%s",
        request.session.get("super_admin_username", "super_admin"), slug, deleted,
    )
    _set_flash(request, message=f"Reset '{slug}': {deleted} simulation incident(s) deleted.")
    return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/super-admin/test-districts/{district_id}/delete", include_in_schema=False)
async def super_admin_delete_test_district(district_id: int, request: Request) -> RedirectResponse:
    """Hard-delete a test district and all its test schools. Blocked on production districts."""
    _require_super_admin(request)
    school_registry = _schools(request)
    district = await school_registry.get_district(district_id)
    if district is None:
        _set_flash(request, error="District not found.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)
    if not district.is_test:
        _set_flash(request, error="SAFETY: cannot delete a production district via sandbox endpoint.")
        return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)

    test_schools = await school_registry.list_schools_by_district(district_id)
    deleted_schools = 0
    for school in test_schools:
        if school.is_test:
            ok = await school_registry.delete_school_record(school.id)
            if ok:
                deleted_schools += 1

    ok = await school_registry.delete_district_record(district_id)
    logger.warning(
        "SANDBOX district_deleted actor=%s district_id=%s district_name=%s schools_deleted=%s",
        request.session.get("super_admin_username", "super_admin"), district_id, district.name, deleted_schools,
    )
    if ok:
        _set_flash(request, message=f"Deleted test district '{district.name}' and {deleted_schools} school(s).")
    else:
        _set_flash(request, error="District delete failed (may already be removed).")
    return RedirectResponse(url=_super_admin_url("sandbox"), status_code=status.HTTP_303_SEE_OTHER)
