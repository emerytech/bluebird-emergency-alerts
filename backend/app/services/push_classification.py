"""
Shared push notification classification logic.

Single source of truth for:
  - Which event types are non-critical (soft sound, normal priority)
  - Which event types are help-request (distinct sound, time-sensitive)
  - All others are treated as critical alarms

Also provides SoundConfig — a plain value object that carries per-tenant
non-critical sound preferences through the push dispatch chain without
polluting extra_data or the APNs/FCM payload.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Alert type classification
# ---------------------------------------------------------------------------

NON_CRITICAL_TYPES: frozenset[str] = frozenset({
    "quiet_period_update",
    "quiet_request",
    "admin_message",
    "onboarding",
    "info",
    "access_code",
    "account",
})

_CLASSIFICATION_CRITICAL = "critical"
_CLASSIFICATION_HELP_REQUEST = "help_request"
_CLASSIFICATION_NON_CRITICAL = "non_critical"


def classify_alert_type(extra_data: dict | None) -> str:
    """
    Return the classification string for a push event.

    Possible values: 'critical', 'help_request', 'non_critical'.

    Critical is the safe default — if the type is unknown or missing, the
    push is treated as an emergency alert so it is never silenced by mistake.
    """
    alert_type = str((extra_data or {}).get("type", "")).strip()
    if alert_type == "help_request":
        return _CLASSIFICATION_HELP_REQUEST
    if alert_type in NON_CRITICAL_TYPES:
        return _CLASSIFICATION_NON_CRITICAL
    return _CLASSIFICATION_CRITICAL


def is_critical(extra_data: dict | None) -> bool:
    return classify_alert_type(extra_data) == _CLASSIFICATION_CRITICAL


def is_non_critical(extra_data: dict | None) -> bool:
    return classify_alert_type(extra_data) == _CLASSIFICATION_NON_CRITICAL


# ---------------------------------------------------------------------------
# Sound configuration value object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SoundConfig:
    """
    Tenant-level non-critical notification sound preferences.

    Passed through the push dispatch chain so APNs and FCM clients can
    apply the correct sound without needing to query the settings DB.
    """
    non_critical_sound_enabled: bool = True
    non_critical_sound_name: str = "notification_soft"

    @classmethod
    def default(cls) -> "SoundConfig":
        return cls()

    @classmethod
    def from_notification_settings(cls, settings: object) -> "SoundConfig":
        """Build from a NotificationSettings (or any duck-typed equivalent)."""
        return cls(
            non_critical_sound_enabled=bool(
                getattr(settings, "non_critical_sound_enabled", True)
            ),
            non_critical_sound_name=str(
                getattr(settings, "non_critical_sound_name", "notification_soft")
            ),
        )

    # APNs helpers -----------------------------------------------------------

    def apns_sound(self, classification: str) -> str:
        """Return the APNs aps.sound value for the given classification."""
        if classification == _CLASSIFICATION_NON_CRITICAL:
            if not self.non_critical_sound_enabled:
                return "default"  # iOS respects system silent mode for "default"
            return f"{self.non_critical_sound_name}.caf"
        if classification == _CLASSIFICATION_HELP_REQUEST:
            return "help_request_alert.caf"
        return "bluebird_alarm.caf"

    def apns_interruption_level(self, classification: str) -> str:
        if classification == _CLASSIFICATION_NON_CRITICAL:
            return "active"
        return "time-sensitive"

    def apns_priority(self, classification: str) -> str:
        if classification == _CLASSIFICATION_NON_CRITICAL:
            return "5"
        return "10"

    # FCM helpers ------------------------------------------------------------

    def fcm_channel_id(self, classification: str) -> str:
        if classification == _CLASSIFICATION_NON_CRITICAL:
            return "non_critical_notifications"
        return "bluebird_alerts"

    def fcm_sound(self, classification: str) -> str | None:
        if classification == _CLASSIFICATION_NON_CRITICAL:
            if not self.non_critical_sound_enabled:
                return None  # Let the Android channel default handle it
            return self.non_critical_sound_name
        if classification == _CLASSIFICATION_HELP_REQUEST:
            return "bluebird_alarm"  # help_request shares the alarm channel
        return "bluebird_alarm"
