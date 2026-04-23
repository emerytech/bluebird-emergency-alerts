from __future__ import annotations

import re
from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field, field_validator, model_validator


_APNS_TOKEN_RE = re.compile(r"^[0-9a-f]+$")


class Platform(str, Enum):
    ios = "ios"
    android = "android"


class PushProvider(str, Enum):
    apns = "apns"
    fcm = "fcm"


class RegisterDeviceRequest(BaseModel):
    device_token: str = Field(..., min_length=1, max_length=4096, description="Push provider device token.")
    platform: Platform = Field(default=Platform.ios, description="Client platform.")
    push_provider: PushProvider = Field(default=PushProvider.apns, description="Push notification provider.")

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
    token_suffix: str


class DevicesResponse(BaseModel):
    device_count: int
    platform_counts: Dict[str, int]
    provider_counts: Dict[str, int]
    devices: List[DeviceSummary]


class PanicRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=240, description="Alert message to broadcast.")


class PanicResponse(BaseModel):
    alert_id: int
    device_count: int
    attempted: int
    succeeded: int
    failed: int
    apns_configured: bool
    provider_attempts: Dict[str, int]


class AlertSummary(BaseModel):
    alert_id: int
    created_at: str
    message: str


class AlertsResponse(BaseModel):
    alerts: List[AlertSummary]
