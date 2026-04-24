from __future__ import annotations

import re
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


_APNS_TOKEN_RE = re.compile(r"^[0-9a-f]+$")
_E164_RE = re.compile(r"^[+][1-9][0-9]{1,14}$")


class Platform(str, Enum):
    ios = "ios"
    android = "android"


class PushProvider(str, Enum):
    apns = "apns"
    fcm = "fcm"

class UserRole(str, Enum):
    """
    Roles are intentionally coarse for MVP.
    We can expand this into a proper RBAC model later.
    """

    teacher = "teacher"
    admin = "admin"


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


class UsersResponse(BaseModel):
    users: List[UserSummary]


class MobileLoginRequest(BaseModel):
    login_name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=240)

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
    must_change_password: bool = False
    can_deactivate_alarm: bool = False
    quiet_period_expires_at: Optional[str] = None


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


class AdminBroadcastRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=240)


class PanicRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=240, description="Alert message to broadcast.")
    user_id: Optional[int] = Field(default=None, description="Optional user_id attribution (who triggered).")


class AlarmStatusResponse(BaseModel):
    is_active: bool
    message: Optional[str] = None
    activated_at: Optional[str] = None
    activated_by_user_id: Optional[int] = None
    activated_by_label: Optional[str] = None
    deactivated_at: Optional[str] = None
    deactivated_by_user_id: Optional[int] = None
    deactivated_by_label: Optional[str] = None
    broadcasts: List[BroadcastUpdateSummary] = []


class AlarmActivateRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=240)
    user_id: Optional[int] = Field(default=None)


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
    triggered_by_user_id: Optional[int] = None
    triggered_by_label: Optional[str] = None


class AlertsResponse(BaseModel):
    alerts: List[AlertSummary]
