from __future__ import annotations

import re
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.constants.labels import normalize_feature_key

_APNS_TOKEN_RE = re.compile(r"^[0-9a-f]+$")
_E164_RE = re.compile(r"^[+][1-9][0-9]{1,14}$")


class Platform(str, Enum):
    ios = "ios"
    android = "android"


class PushProvider(str, Enum):
    apns = "apns"
    fcm = "fcm"

class UserRole(str, Enum):
    teacher = "teacher"
    staff = "staff"
    law_enforcement = "law_enforcement"
    admin = "admin"                      # legacy alias — kept for backward compat
    building_admin = "building_admin"
    district_admin = "district_admin"
    super_admin = "super_admin"


class ReportCategory(str, Enum):
    safe = "safe"
    need_help = "need_help"
    suspicious_person = "suspicious_person"
    medical_emergency = "medical_emergency"


class RegisterDeviceRequest(BaseModel):
    device_token: str = Field(..., min_length=1, max_length=4096, description="Push provider device token.")
    platform: Platform = Field(default=Platform.ios, description="Client platform.")
    push_provider: PushProvider = Field(default=PushProvider.apns, description="Push notification provider.")
    device_name: Optional[str] = Field(default=None, max_length=120)
    user_id: Optional[int] = None

    @field_validator("device_token")
    @classmethod
    def normalize_and_validate(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("device_token cannot be empty")
        return normalized

    @field_validator("device_token")
    @classmethod
    def normalize_apns_debug_tokens(cls, v: str) -> str:
        # Common iOS debug prints include spaces and angle brackets: "<abcd ...>"
        maybe_apns = v.lower().replace(" ", "").replace("<", "").replace(">", "")
        if _APNS_TOKEN_RE.match(maybe_apns) and len(maybe_apns) >= 32:
            return maybe_apns
        return v

    @model_validator(mode="after")
    def validate_platform_provider_pair(self) -> "RegisterDeviceRequest":
        if self.platform == Platform.ios and self.push_provider != PushProvider.apns:
            raise ValueError("iOS devices must use push_provider=apns")
        if self.platform == Platform.android and self.push_provider != PushProvider.fcm:
            raise ValueError("Android devices must use push_provider=fcm")
        if self.push_provider == PushProvider.apns:
            token_length = len(self.device_token)
            if not _APNS_TOKEN_RE.match(self.device_token) or token_length < 32 or token_length > 4096:
                raise ValueError("APNs device_token must be a hex string between 32 and 4096 characters")
        return self


class RegisterDeviceResponse(BaseModel):
    registered: bool
    device_count: int
    platform_counts: Dict[str, int]
    provider_counts: Dict[str, int]


class DeviceSummary(BaseModel):
    platform: str
    push_provider: str
    device_name: Optional[str] = None
    user_id: Optional[int] = None
    first_user_id: Optional[int] = None
    token_suffix: str


class DevicesResponse(BaseModel):
    device_count: int
    platform_counts: Dict[str, int]
    provider_counts: Dict[str, int]
    devices: List[DeviceSummary]

class CreateUserRequest(BaseModel):
    """
    Creates a user record used for alert targeting (SMS) and attribution (who triggered an alert).
    """

    name: str = Field(..., min_length=1, max_length=120, description="Display name for the user.")
    role: UserRole = Field(..., description="Role used for later role-based alerting.")
    title: Optional[str] = Field(default=None, max_length=120, description="Optional job title, e.g. Principal.")
    phone_e164: Optional[str] = Field(
        default=None,
        description="Optional E.164 phone number for SMS delivery, e.g. +15551234567.",
    )

    @field_validator("phone_e164")
    @classmethod
    def validate_phone_e164(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = v.strip()
        if not normalized:
            return None
        if not _E164_RE.match(normalized):
            raise ValueError("phone_e164 must be E.164 formatted like +15551234567")
        return normalized


class UserSummary(BaseModel):
    user_id: int
    created_at: str
    name: str
    role: str
    phone_e164: Optional[str] = None
    is_active: bool
    title: Optional[str] = None


class UsersResponse(BaseModel):
    users: List[UserSummary]


class MobileLoginRequest(BaseModel):
    login_name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=240)
    client_type: str = "mobile"

    @field_validator("login_name")
    @classmethod
    def normalize_login_name(cls, v: str) -> str:
        normalized = v.strip().lower()
        if not normalized:
            raise ValueError("login_name is required")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("password is required")
        return v


class MobileLoginResponse(BaseModel):
    user_id: int
    name: str
    role: str
    login_name: str
    title: Optional[str] = None
    must_change_password: bool = False
    can_deactivate_alarm: bool = False
    quiet_period_expires_at: Optional[str] = None
    quiet_mode_active: bool = False
    session_token: Optional[str] = None


class PublicSchoolSummary(BaseModel):
    name: str
    slug: str
    path: str
    api_base_url: Optional[str] = None
    admin_url: Optional[str] = None


class SchoolsCatalogResponse(BaseModel):
    schools: List[PublicSchoolSummary]


class BroadcastUpdateSummary(BaseModel):
    update_id: int
    created_at: str
    admin_user_id: Optional[int] = None
    admin_label: Optional[str] = None
    message: str


class ReportRequest(BaseModel):
    user_id: Optional[int] = None
    category: ReportCategory
    note: Optional[str] = Field(default=None, max_length=240)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = v.strip()
        return normalized or None


class ReportResponse(BaseModel):
    report_id: int
    created_at: str
    user_id: Optional[int] = None
    category: str
    note: Optional[str] = None


class AdminMessageRequest(BaseModel):
    user_id: Optional[int] = None
    message: str = Field(..., min_length=1, max_length=240)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("message is required")
        return normalized


class AdminSendMessageRequest(BaseModel):
    admin_user_id: int
    message: str = Field(..., min_length=1, max_length=240)
    recipient_user_id: Optional[int] = None
    recipient_user_ids: List[int] = Field(default_factory=list)
    send_to_all: bool = False

    @field_validator("message")
    @classmethod
    def normalize_admin_message(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("message is required")
        return normalized

    @model_validator(mode="after")
    def validate_recipient_scope(self) -> "AdminSendMessageRequest":
        if self.send_to_all:
            return self
        has_single = self.recipient_user_id is not None
        has_multi = bool(self.recipient_user_ids)
        if not has_single and not has_multi:
            raise ValueError("recipient_user_id or recipient_user_ids is required when send_to_all is false")
        return self


class AdminMessageResponse(BaseModel):
    message_id: int
    created_at: str
    user_id: Optional[int] = None
    message: str


class AdminSendMessageResponse(BaseModel):
    sent_count: int
    recipient_scope: str


class AdminMessageInboxItem(BaseModel):
    message_id: int
    created_at: str
    sender_user_id: Optional[int] = None
    sender_label: Optional[str] = None
    message: str
    status: str
    response_message: Optional[str] = None
    response_created_at: Optional[str] = None
    response_by_user_id: Optional[int] = None
    response_by_label: Optional[str] = None


class AdminMessageInboxResponse(BaseModel):
    unread_count: int
    messages: List[AdminMessageInboxItem]


class AdminMessageReplyRequest(BaseModel):
    admin_user_id: int
    message_id: int
    message: str = Field(..., min_length=1, max_length=240)

    @field_validator("message")
    @classmethod
    def normalize_reply_message(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("message is required")
        return normalized


class QuietPeriodRequestCreate(BaseModel):
    user_id: int
    reason: Optional[str] = Field(default=None, max_length=240)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = v.strip()
        return normalized or None


class QuietPeriodSummary(BaseModel):
    request_id: int
    user_id: int
    reason: Optional[str] = None
    status: str
    requested_at: str
    approved_at: Optional[str] = None
    approved_by_user_id: Optional[int] = None
    approved_by_label: Optional[str] = None
    expires_at: Optional[str] = None


class QuietPeriodStatusResponse(BaseModel):
    request_id: Optional[int] = None
    user_id: int
    status: Optional[str] = None
    reason: Optional[str] = None
    requested_at: Optional[str] = None
    approved_at: Optional[str] = None
    approved_by_label: Optional[str] = None
    expires_at: Optional[str] = None
    quiet_mode_active: bool = False


class QuietPeriodDeleteRequest(BaseModel):
    user_id: int


class QuietPeriodAdminActionRequest(BaseModel):
    admin_user_id: int
    admin_home_tenant_id: Optional[int] = None


class QuietPeriodAdminItem(BaseModel):
    request_id: int
    user_id: int
    user_name: Optional[str] = None
    user_role: Optional[str] = None
    reason: Optional[str] = None
    status: str
    requested_at: str
    approved_at: Optional[str] = None
    approved_by_user_id: Optional[int] = None
    approved_by_label: Optional[str] = None
    expires_at: Optional[str] = None


class QuietPeriodAdminListResponse(BaseModel):
    requests: List[QuietPeriodAdminItem]


class DistrictQuietPeriodItem(QuietPeriodAdminItem):
    tenant_slug: str
    tenant_name: str


class DistrictQuietPeriodsResponse(BaseModel):
    requests: List[DistrictQuietPeriodItem]


class DistrictQuietActionRequest(BaseModel):
    admin_user_id: int
    tenant_slug: str = Field(..., min_length=1, max_length=80)


class AdminBroadcastRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=240)


class PanicRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=240, description="Alert message to broadcast.")
    user_id: Optional[int] = Field(default=None, description="Optional user_id attribution (who triggered).")
    is_training: bool = Field(default=False)
    training_label: Optional[str] = Field(default=None, max_length=120)
    silent_audio: bool = Field(default=False)


class AlarmStatusResponse(BaseModel):
    is_active: bool
    message: Optional[str] = None
    is_training: bool = False
    training_label: Optional[str] = None
    silent_audio: bool = False
    current_alert_id: Optional[int] = None
    acknowledgement_count: int = 0
    current_user_acknowledged: bool = False
    activated_at: Optional[str] = None
    activated_by_user_id: Optional[int] = None
    activated_by_label: Optional[str] = None
    deactivated_at: Optional[str] = None
    deactivated_by_user_id: Optional[int] = None
    deactivated_by_label: Optional[str] = None
    broadcasts: List[BroadcastUpdateSummary] = []
    triggered_by_user_id: Optional[int] = None
    silent_for_sender: bool = True


class AlarmActivateRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=240)
    user_id: Optional[int] = Field(default=None)
    is_training: bool = Field(default=False)
    training_label: Optional[str] = Field(default=None, max_length=120)
    silent_audio: bool = Field(default=False)


class AlarmDeactivateRequest(BaseModel):
    user_id: Optional[int] = Field(default=None)


class PanicResponse(BaseModel):
    alert_id: int
    device_count: int
    attempted: int
    succeeded: int
    failed: int
    apns_configured: bool
    provider_attempts: Dict[str, int]
    # SMS is queued so the panic endpoint returns quickly (<2s goal) even if Twilio is slow.
    sms_queued: int = 0
    twilio_configured: bool = False


class AlertSummary(BaseModel):
    alert_id: int
    created_at: str
    message: str
    is_training: bool = False
    training_label: Optional[str] = None
    created_by_user_id: Optional[int] = None
    triggered_by_user_id: Optional[int] = None
    triggered_by_label: Optional[str] = None


class AlertsResponse(BaseModel):
    alerts: List[AlertSummary]


class AlertAcknowledgeRequest(BaseModel):
    user_id: int


class AlertAcknowledgeResponse(BaseModel):
    alert_id: int
    user_id: int
    acknowledged_at: str
    already_acknowledged: bool = False
    acknowledgement_count: int = 0


class IncidentCreateRequest(BaseModel):
    type: str = Field(..., min_length=1, max_length=120)
    user_id: int
    target_scope: str = Field(default="ALL", min_length=1, max_length=40)
    metadata: Dict[str, object] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def normalize_incident_type(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("type is required")
        return normalized


class IncidentSummary(BaseModel):
    id: int
    type: str
    status: str
    created_by: int
    school_id: str
    created_at: str
    target_scope: str
    metadata: Dict[str, object] = Field(default_factory=dict)


class IncidentListResponse(BaseModel):
    incidents: List[IncidentSummary]


class TeamAssistCreateRequest(BaseModel):
    type: str = Field(..., min_length=1, max_length=120)
    user_id: int
    assigned_team_ids: List[int] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def normalize_team_assist_type(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("type is required")
        return normalize_feature_key(normalized)


class TeamAssistSummary(BaseModel):
    id: int
    type: str
    created_by: int
    assigned_team_ids: List[int] = Field(default_factory=list)
    status: str
    created_at: str
    acted_by_user_id: Optional[int] = None
    acted_by_label: Optional[str] = None
    forward_to_user_id: Optional[int] = None
    forward_to_label: Optional[str] = None
    # requester-initiated cancel fields
    cancelled_by_user_id: Optional[int] = None
    cancelled_at: Optional[str] = None
    cancel_reason_text: Optional[str] = None
    cancel_reason_category: Optional[str] = None


class TeamAssistListResponse(BaseModel):
    team_assists: List[TeamAssistSummary]


class TeamAssistActionRequest(BaseModel):
    user_id: int
    action: str = Field(..., min_length=1, max_length=40)
    forward_to_user_id: Optional[int] = None

    @field_validator("action")
    @classmethod
    def normalize_action(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in {"acknowledge", "responding", "forward", "resolve"}:
            raise ValueError("action must be acknowledge, responding, forward, or resolve")
        return normalized


CANCEL_REASON_CATEGORIES = {"accidental", "resolved", "test", "duplicate", "other"}


class TeamAssistCancelRequest(BaseModel):
    user_id: int
    cancel_reason_text: str = Field(..., max_length=500)
    cancel_reason_category: str = Field(..., max_length=100)

    @field_validator("cancel_reason_text")
    @classmethod
    def _require_non_blank_text(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("cancel_reason_text must not be blank")
        return v

    @field_validator("cancel_reason_category")
    @classmethod
    def _validate_category(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in CANCEL_REASON_CATEGORIES:
            raise ValueError(
                f"cancel_reason_category must be one of: {', '.join(sorted(CANCEL_REASON_CATEGORIES))}"
            )
        return normalized


# ── District / multi-school schemas ──────────────────────────────────────────

class TenantSummaryForUser(BaseModel):
    tenant_slug: str
    tenant_name: str
    role: Optional[str] = None


class MeResponse(BaseModel):
    user_id: int
    name: str
    login_name: str
    role: str
    title: Optional[str] = None
    can_deactivate_alarm: bool = False
    tenants: List[TenantSummaryForUser]
    selected_tenant: str


class SelectTenantRequest(BaseModel):
    tenant_slug: str = Field(..., min_length=1, max_length=120)


class SelectTenantResponse(BaseModel):
    tenant_slug: str
    tenant_name: str
    role: Optional[str] = None


class TenantOverviewItem(BaseModel):
    tenant_slug: str
    tenant_name: str
    alarm_is_active: bool
    alarm_message: Optional[str] = None
    alarm_is_training: bool = False
    last_alert_at: Optional[str] = None
    acknowledgement_count: int = 0
    expected_user_count: int = 0
    acknowledgement_rate: float = 0.0


class DistrictOverviewResponse(BaseModel):
    tenant_count: int
    tenants: List[TenantOverviewItem]


# ── Phase 8: Production hardening schemas ─────────────────────────────────────

class ProviderDeliveryStats(BaseModel):
    total: int = 0
    ok: int = 0
    failed: int = 0
    last_error: Optional[str] = None


class PushDeliveryStatsResponse(BaseModel):
    total: int = 0
    ok: int = 0
    failed: int = 0
    last_error: Optional[str] = None
    by_provider: Dict[str, ProviderDeliveryStats] = {}


class AuditLogEntry(BaseModel):
    id: int
    timestamp: str
    event_type: str
    actor_user_id: Optional[int] = None
    actor_label: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    metadata: Dict = {}


class AuditLogResponse(BaseModel):
    events: List[AuditLogEntry]


# ── Access code / onboarding schemas ──────────────────────────────────────────

class GenerateAccessCodeRequest(BaseModel):
    role: str = Field(..., description="Role the new user will receive.")
    title: Optional[str] = Field(default=None, max_length=120, description="Optional job title (metadata only).")
    tenant_slug: str = Field(..., min_length=1, max_length=80)
    max_uses: int = Field(default=1, ge=1, le=20)
    expires_hours: int = Field(default=48, ge=1, le=720)  # 1h–30d


class AccessCodeResponse(BaseModel):
    id: int
    code: str
    tenant_slug: str
    tenant_name: str
    role: str
    role_label: str
    title: Optional[str]
    created_at: str
    expires_at: str
    max_uses: int
    use_count: int
    status: str
    qr_payload: str       # JSON string ready for QR encoding (content for QR image)
    qr_payload_json: str  # same content, explicit field for mobile SDK consumers
    invite_url: str       # deep-link/web fallback URL pre-filled with code


class AccessCodeListResponse(BaseModel):
    codes: List[AccessCodeResponse]


class ValidateCodeRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=20)
    tenant_slug: str = Field(..., min_length=1, max_length=80)


class ValidateCodeResponse(BaseModel):
    valid: bool
    role: Optional[str] = None
    role_label: Optional[str] = None
    title: Optional[str] = None
    tenant_slug: Optional[str] = None
    tenant_name: Optional[str] = None
    error: Optional[str] = None


class CreateAccountFromCodeRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=20)
    tenant_slug: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=120)
    login_name: str = Field(..., min_length=2, max_length=80)
    password: str = Field(..., min_length=8, max_length=200)


class ValidateSetupCodeRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=20)


class ValidateSetupCodeResponse(BaseModel):
    valid: bool
    tenant_slug: Optional[str] = None
    tenant_name: Optional[str] = None
    error: Optional[str] = None


class CreateDistrictAdminRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=120)
    login_name: str = Field(..., min_length=2, max_length=80)
    password: str = Field(..., min_length=8, max_length=200)


class SendInviteEmailRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    code_id: int


class GmailSettingsResponse(BaseModel):
    gmail_address: str
    from_name: str
    password_set: bool
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    configured: bool


class GmailSettingsUpdateRequest(BaseModel):
    gmail_address: str = Field(..., min_length=3, max_length=254)
    from_name: str = Field(default="BlueBird Alerts", max_length=100)
    app_password: Optional[str] = Field(default=None, max_length=200)


class CustomerMessageRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=5000)


class HelpRequestCancellationCategoryBreakdown(BaseModel):
    category: str
    count: int


class HelpRequestCancellationAnalyticsResponse(BaseModel):
    total_requests: int
    cancelled: int
    cancellation_rate: float
    breakdown_by_category: List[HelpRequestCancellationCategoryBreakdown]
