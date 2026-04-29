"""
Canonical tenant settings schema for BlueBird Alerts.

Every setting has a safe default.  The service layer merges stored values with
these defaults so missing keys never crash.  Unknown patch keys are silently
dropped.  Type mismatches in stored data fall back to defaults.

Usage::

    from app.services.tenant_settings import TenantSettings, settings_from_dict, validate_settings_patch

    # Get effective settings (stored merged with defaults):
    effective = settings_from_dict(stored_dict)

    # Validate a partial patch before writing:
    errors = validate_settings_patch(patch_dict)
    if errors:
        raise ValueError(errors)
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Sub-category dataclasses
# ---------------------------------------------------------------------------

@dataclass
class NotificationSettings:
    # critical_alert_sound_locked is always True — never stored, always computed.
    non_critical_sound_name: str = "notification_soft"
    non_critical_sound_enabled: bool = True
    quiet_period_notifications_enabled: bool = True
    admin_message_notifications_enabled: bool = True
    access_code_notifications_enabled: bool = True
    audit_notifications_enabled: bool = False


@dataclass
class QuietPeriodSettings:
    enabled: bool = True
    requires_approval: bool = True
    allow_scheduling: bool = True
    max_duration_minutes: int = 1440   # 24 hours
    default_duration_minutes: int = 60
    allow_self_approval: bool = False
    district_admin_can_approve_all: bool = True
    building_admin_scope: str = "building"  # "building" | "district"


@dataclass
class AlertSettings:
    teachers_can_trigger_secure_perimeter: bool = True
    teachers_can_trigger_lockdown: bool = True
    law_enforcement_can_trigger: bool = False
    require_hold_to_activate: bool = True
    hold_seconds: int = 3
    disable_requires_admin: bool = True


@dataclass
class DeviceSettings:
    device_status_reporting_enabled: bool = True
    mark_device_stale_after_minutes: int = 30
    exclude_inactive_devices_from_push: bool = True


@dataclass
class AccessCodeSettings:
    enabled: bool = True
    auto_expire_enabled: bool = True
    default_expiration_days: int = 14
    auto_archive_revoked_enabled: bool = False
    auto_archive_revoked_after_days: int = 7


@dataclass
class UiSettings:
    theme_mode: str = "system"   # "system" | "light" | "dark"
    show_guided_tour: bool = True


# ---------------------------------------------------------------------------
# Root settings object
# ---------------------------------------------------------------------------

@dataclass
class TenantSettings:
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    quiet_periods: QuietPeriodSettings = field(default_factory=QuietPeriodSettings)
    alerts: AlertSettings = field(default_factory=AlertSettings)
    devices: DeviceSettings = field(default_factory=DeviceSettings)
    access_codes: AccessCodeSettings = field(default_factory=AccessCodeSettings)
    ui: UiSettings = field(default_factory=UiSettings)


# Map category name → dataclass type (for generic merge / validate helpers)
_CATEGORY_CLASSES: dict[str, type] = {
    "notifications": NotificationSettings,
    "quiet_periods": QuietPeriodSettings,
    "alerts": AlertSettings,
    "devices": DeviceSettings,
    "access_codes": AccessCodeSettings,
    "ui": UiSettings,
}

# Per-field validation bounds and allowed values
_FIELD_CONSTRAINTS: dict[str, dict[str, Any]] = {
    "quiet_periods": {
        "max_duration_minutes": {"min": 15, "max": 10_080},    # 15 min – 7 days
        "default_duration_minutes": {"min": 15, "max": 1_440},
        "building_admin_scope": {"choices": {"building", "district"}},
    },
    "alerts": {
        "hold_seconds": {"min": 1, "max": 10},
    },
    "devices": {
        "mark_device_stale_after_minutes": {"min": 5, "max": 1_440},
    },
    "access_codes": {
        "default_expiration_days": {"min": 1, "max": 365},
        "auto_archive_revoked_after_days": {"min": 1, "max": 180},
    },
    "notifications": {
        "non_critical_sound_name": {"choices": {"notification_soft"}},
    },
    "ui": {
        "theme_mode": {"choices": {"system", "light", "dark"}},
    },
}

# Fields that are computed and must never be stored or modified externally
_COMPUTED_FIELDS: dict[str, set[str]] = {
    "notifications": {"critical_alert_sound_locked"},
}


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def settings_to_dict(s: TenantSettings) -> dict[str, Any]:
    """Convert a TenantSettings to a plain dict (for JSON storage)."""
    return dataclasses.asdict(s)


def _merge_category(cls: type, stored: Any) -> object:
    """
    Create an instance of `cls` by starting from its defaults and overlaying
    values from `stored`.  Unknown keys in `stored` are ignored.
    Type mismatches fall back to the field's default.
    """
    if not isinstance(stored, dict):
        return cls()
    defaults = cls()
    init_kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        stored_val = stored.get(f.name, dataclasses.MISSING)
        if stored_val is dataclasses.MISSING:
            init_kwargs[f.name] = getattr(defaults, f.name)
            continue
        # Type-safe coercion — fall back to default on mismatch.
        try:
            default_val = getattr(defaults, f.name)
            if isinstance(default_val, bool):
                if isinstance(stored_val, bool):
                    init_kwargs[f.name] = stored_val
                elif isinstance(stored_val, int):
                    init_kwargs[f.name] = bool(stored_val)
                else:
                    init_kwargs[f.name] = default_val
            elif isinstance(default_val, int):
                init_kwargs[f.name] = int(stored_val)
            elif isinstance(default_val, str):
                init_kwargs[f.name] = str(stored_val)
            else:
                init_kwargs[f.name] = stored_val
        except (ValueError, TypeError):
            init_kwargs[f.name] = getattr(defaults, f.name)
    return cls(**init_kwargs)


def settings_from_dict(d: Any) -> TenantSettings:
    """
    Build a TenantSettings from an arbitrary dict, merging with defaults.
    Safe to call with None, {}, or partially-populated dicts.
    """
    if not isinstance(d, dict):
        return TenantSettings()
    return TenantSettings(
        notifications=_merge_category(NotificationSettings, d.get("notifications")),  # type: ignore[arg-type]
        quiet_periods=_merge_category(QuietPeriodSettings, d.get("quiet_periods")),   # type: ignore[arg-type]
        alerts=_merge_category(AlertSettings, d.get("alerts")),                        # type: ignore[arg-type]
        devices=_merge_category(DeviceSettings, d.get("devices")),                     # type: ignore[arg-type]
        access_codes=_merge_category(AccessCodeSettings, d.get("access_codes")),       # type: ignore[arg-type]
        ui=_merge_category(UiSettings, d.get("ui")),                                   # type: ignore[arg-type]
    )


def effective_settings_dict(s: TenantSettings) -> dict[str, Any]:
    """
    Return a dict suitable for API responses.  Injects computed read-only
    fields (e.g., critical_alert_sound_locked) that are never stored.
    """
    d = settings_to_dict(s)
    d["notifications"]["critical_alert_sound_locked"] = True
    return d


# ---------------------------------------------------------------------------
# Patch validation
# ---------------------------------------------------------------------------

def validate_settings_patch(patch: Any) -> list[str]:
    """
    Validate a partial settings patch dict.

    Returns a list of human-readable error strings.
    An empty list means the patch is valid.
    Unknown top-level categories and unknown field names are silently ignored
    (they won't be written, so they can't do harm).
    """
    if not isinstance(patch, dict):
        return ["Patch must be a JSON object"]

    errors: list[str] = []

    for category, values in patch.items():
        if category not in _CATEGORY_CLASSES:
            continue  # unknown category → silently ignored
        if not isinstance(values, dict):
            errors.append(f"{category}: must be an object")
            continue

        cls = _CATEGORY_CLASSES[category]
        defaults = cls()
        constraints = _FIELD_CONSTRAINTS.get(category, {})
        computed = _COMPUTED_FIELDS.get(category, set())

        for key, val in values.items():
            if key in computed:
                errors.append(f"{category}.{key}: read-only field cannot be set")
                continue

            # Check if the field is known
            known_fields = {f.name for f in dataclasses.fields(cls)}
            if key not in known_fields:
                continue  # unknown field → silently ignored

            default_val = getattr(defaults, key)

            # Type check
            if isinstance(default_val, bool):
                if not isinstance(val, bool):
                    errors.append(f"{category}.{key}: must be true or false")
                    continue
            elif isinstance(default_val, int):
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    errors.append(f"{category}.{key}: must be an integer")
                    continue
                val = int(val)
            elif isinstance(default_val, str):
                if not isinstance(val, str):
                    errors.append(f"{category}.{key}: must be a string")
                    continue

            # Bounds / choices
            field_constraints = constraints.get(key, {})
            if "min" in field_constraints and val < field_constraints["min"]:
                errors.append(
                    f"{category}.{key}: minimum value is {field_constraints['min']}"
                )
            if "max" in field_constraints and val > field_constraints["max"]:
                errors.append(
                    f"{category}.{key}: maximum value is {field_constraints['max']}"
                )
            if "choices" in field_constraints and val not in field_constraints["choices"]:
                allowed = ", ".join(sorted(field_constraints["choices"]))
                errors.append(f"{category}.{key}: must be one of [{allowed}]")

    return errors
