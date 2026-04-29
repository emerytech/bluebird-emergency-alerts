"""
Phase 2 tests — Canonical tenant settings schema and store.

Tests cover:
1.  Default settings returned for a new tenant
2.  settings_from_dict merges with defaults (partial dict)
3.  settings_from_dict ignores unknown keys safely
4.  settings_from_dict handles type mismatches gracefully
5.  validate_settings_patch accepts valid partial patches
6.  validate_settings_patch rejects out-of-range integers
7.  validate_settings_patch rejects invalid choice values
8.  validate_settings_patch rejects wrong type (bool field given string)
9.  validate_settings_patch rejects attempt to set read-only computed field
10. validate_settings_patch ignores unknown categories and keys silently
11. get_effective_settings returns defaults for a new tenant DB
12. update_settings persists partial patch and merges with defaults
13. update_settings records to tenant_settings_history
14. update_settings returns validation errors without writing
15. reset_to_defaults clears stored settings and returns to defaults
16. critical_alert_sound_locked is always True in effective_settings_dict
17. Stored malformed JSON is recovered gracefully
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from app.services.tenant_settings import (
    TenantSettings,
    effective_settings_dict,
    settings_from_dict,
    settings_to_dict,
    validate_settings_patch,
)
from app.services.tenant_settings_store import TenantSettingsStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test_settings.db")
    return db_path


@pytest.fixture
def store(tmp_db):
    return TenantSettingsStore(tmp_db)


# ---------------------------------------------------------------------------
# Schema / serialization tests (no DB needed)
# ---------------------------------------------------------------------------

def test_default_settings_are_sane():
    s = TenantSettings()
    assert s.notifications.non_critical_sound_enabled is True
    assert s.notifications.non_critical_sound_name == "notification_soft"
    assert s.quiet_periods.enabled is True
    assert s.quiet_periods.requires_approval is True
    assert s.quiet_periods.max_duration_minutes == 1440
    assert s.alerts.law_enforcement_can_trigger is False
    assert s.alerts.hold_seconds == 3
    assert s.devices.exclude_inactive_devices_from_push is True
    assert s.access_codes.enabled is True
    assert s.ui.theme_mode == "system"


def test_settings_from_dict_partial_merge():
    stored = {"quiet_periods": {"max_duration_minutes": 120}}
    s = settings_from_dict(stored)
    assert s.quiet_periods.max_duration_minutes == 120
    assert s.quiet_periods.enabled is True            # default preserved
    assert s.quiet_periods.requires_approval is True  # default preserved
    assert s.notifications.non_critical_sound_enabled is True  # other cat default


def test_settings_from_dict_ignores_unknown_keys():
    stored = {
        "unknown_category": {"foo": "bar"},
        "quiet_periods": {"nonexistent_field": 999, "enabled": False},
    }
    s = settings_from_dict(stored)
    assert s.quiet_periods.enabled is False   # known field applied
    # nonexistent_field is silently dropped; check all known fields are defaults
    assert s.quiet_periods.max_duration_minutes == 1440


def test_settings_from_dict_handles_none():
    s = settings_from_dict(None)
    assert s == TenantSettings()


def test_settings_from_dict_handles_empty_dict():
    s = settings_from_dict({})
    assert s == TenantSettings()


def test_settings_from_dict_type_mismatch_falls_back_to_default():
    stored = {"quiet_periods": {"enabled": "yes_please", "max_duration_minutes": "not_a_number"}}
    s = settings_from_dict(stored)
    assert s.quiet_periods.enabled is True          # bool mismatch → default (True)
    assert s.quiet_periods.max_duration_minutes == 1440  # int mismatch → default


def test_settings_from_dict_int_coerces_bool():
    # Bool fields given int 0/1 should coerce
    stored = {"alerts": {"require_hold_to_activate": 0}}
    s = settings_from_dict(stored)
    assert s.alerts.require_hold_to_activate is False


def test_settings_to_dict_round_trip():
    s = TenantSettings()
    d = settings_to_dict(s)
    s2 = settings_from_dict(d)
    assert s == s2


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

def test_validate_valid_patch_no_errors():
    patch = {
        "notifications": {"non_critical_sound_enabled": False},
        "quiet_periods": {"max_duration_minutes": 240, "enabled": True},
        "alerts": {"hold_seconds": 5},
    }
    assert validate_settings_patch(patch) == []


def test_validate_out_of_range_int_min():
    patch = {"quiet_periods": {"max_duration_minutes": 5}}  # min is 15
    errors = validate_settings_patch(patch)
    assert any("minimum" in e for e in errors)


def test_validate_out_of_range_int_max():
    patch = {"alerts": {"hold_seconds": 99}}  # max is 10
    errors = validate_settings_patch(patch)
    assert any("maximum" in e for e in errors)


def test_validate_invalid_choice():
    patch = {"ui": {"theme_mode": "purple"}}
    errors = validate_settings_patch(patch)
    assert any("theme_mode" in e for e in errors)


def test_validate_valid_choice():
    for mode in ("system", "light", "dark"):
        assert validate_settings_patch({"ui": {"theme_mode": mode}}) == []


def test_validate_wrong_type_bool_field():
    patch = {"alerts": {"require_hold_to_activate": "yes"}}
    errors = validate_settings_patch(patch)
    assert any("require_hold_to_activate" in e for e in errors)


def test_validate_read_only_field_rejected():
    patch = {"notifications": {"critical_alert_sound_locked": False}}
    errors = validate_settings_patch(patch)
    assert any("read-only" in e for e in errors)


def test_validate_unknown_category_ignored():
    patch = {"totally_unknown": {"key": "value"}}
    assert validate_settings_patch(patch) == []


def test_validate_unknown_field_within_known_category_ignored():
    patch = {"alerts": {"nonexistent_field": True}}
    assert validate_settings_patch(patch) == []


def test_validate_not_a_dict():
    errors = validate_settings_patch("not a dict")
    assert len(errors) == 1
    assert "JSON object" in errors[0]


def test_validate_category_not_a_dict():
    patch = {"notifications": "not_a_dict"}
    errors = validate_settings_patch(patch)
    assert any("notifications" in e for e in errors)


# ---------------------------------------------------------------------------
# Store tests (require tmp DB)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_effective_settings_new_tenant_returns_defaults(store):
    s = await store.get_effective_settings()
    assert s == TenantSettings()


@pytest.mark.anyio
async def test_update_settings_persists_patch(store):
    patch = {"quiet_periods": {"max_duration_minutes": 90}}
    new_s, errors = await store.update_settings(patch, actor_label="admin@test.com")
    assert errors == []
    assert new_s.quiet_periods.max_duration_minutes == 90
    # Reload from DB
    loaded = await store.get_effective_settings()
    assert loaded.quiet_periods.max_duration_minutes == 90
    assert loaded.quiet_periods.enabled is True  # other defaults preserved


@pytest.mark.anyio
async def test_update_settings_records_history(store):
    patch = {"notifications": {"non_critical_sound_enabled": False}}
    await store.update_settings(patch, actor_label="district_admin")
    history = await store.get_history(limit=10)
    # Should have exactly one settings.notifications entry
    settings_entries = [h for h in history if h.field.startswith("settings.")]
    assert len(settings_entries) == 1
    assert settings_entries[0].field == "settings.notifications"
    assert settings_entries[0].changed_by_label == "district_admin"
    # new_value should contain the changed key
    assert "non_critical_sound_enabled" in settings_entries[0].new_value


@pytest.mark.anyio
async def test_update_settings_returns_errors_without_writing(store):
    patch = {"alerts": {"hold_seconds": 99}}  # invalid
    _, errors = await store.update_settings(patch)
    assert errors  # validation failed
    # DB should be unchanged
    s = await store.get_effective_settings()
    assert s.alerts.hold_seconds == 3  # default


@pytest.mark.anyio
async def test_update_settings_multiple_patches_accumulate(store):
    await store.update_settings({"quiet_periods": {"max_duration_minutes": 120}})
    await store.update_settings({"quiet_periods": {"enabled": False}})
    s = await store.get_effective_settings()
    assert s.quiet_periods.max_duration_minutes == 120
    assert s.quiet_periods.enabled is False


@pytest.mark.anyio
async def test_reset_to_defaults_clears_stored(store):
    await store.update_settings({"quiet_periods": {"max_duration_minutes": 120}})
    result = await store.reset_to_defaults(actor_label="admin")
    assert result == TenantSettings()
    # Reload confirms defaults
    s = await store.get_effective_settings()
    assert s.quiet_periods.max_duration_minutes == 1440


@pytest.mark.anyio
async def test_reset_to_defaults_records_history(store):
    await store.update_settings({"ui": {"theme_mode": "dark"}})
    await store.reset_to_defaults(actor_label="district_admin")
    history = await store.get_history(limit=10)
    reset_entries = [h for h in history if "reset" in h.field]
    assert len(reset_entries) == 1


@pytest.mark.anyio
async def test_get_effective_settings_handles_malformed_db(tmp_db):
    """If the stored JSON is corrupt, return defaults without crashing."""
    # Write garbage to the DB directly
    store = TenantSettingsStore(tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tenant_settings (key, value) VALUES ('settings', ?)",
            ("not valid json {{{{",),
        )
    s = await store.get_effective_settings()
    assert s == TenantSettings()


# ---------------------------------------------------------------------------
# effective_settings_dict tests
# ---------------------------------------------------------------------------

def test_effective_settings_dict_always_locks_critical_sound():
    s = TenantSettings()
    d = effective_settings_dict(s)
    assert d["notifications"]["critical_alert_sound_locked"] is True


def test_effective_settings_dict_cannot_be_unlocked_via_patch():
    # Even if someone stores the flag as False, reading back locks it
    stored = {"notifications": {"critical_alert_sound_locked": False}}
    s = settings_from_dict(stored)
    d = effective_settings_dict(s)
    assert d["notifications"]["critical_alert_sound_locked"] is True
