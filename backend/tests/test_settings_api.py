"""
Phase 6 — Tenant Settings API tests.

Tests the settings endpoints via the permission + store layer directly,
without needing a live HTTP server.  The route logic is thin (auth + store
delegation), so we test:
  1. The permission gate helpers (`can_view_settings`, `can_edit_settings`)
  2. The store round-trip (patch → read back → effective_settings_dict)
  3. Validation error propagation
  4. Reset behaviour
  5. History recording

We do NOT spin up FastAPI here; instead we call the store and permission
helpers directly, which is where the business logic lives.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from app.services.permissions import (
    can_edit_settings,
    can_view_settings,
    ROLE_TEACHER,
    ROLE_STAFF,
    ROLE_BUILDING_ADMIN,
    ROLE_DISTRICT_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN,
)
from app.services.tenant_settings import (
    TenantSettings,
    effective_settings_dict,
    settings_from_dict,
    validate_settings_patch,
)
from app.services.tenant_settings_store import TenantSettingsStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "tenant.db")


@pytest.fixture()
def store(db_path):
    return TenantSettingsStore(db_path)


# ---------------------------------------------------------------------------
# Permission gate — who may view settings
# ---------------------------------------------------------------------------

class TestCanViewSettings:
    def test_district_admin_can_view(self):
        assert can_view_settings(ROLE_DISTRICT_ADMIN) is True

    def test_building_admin_can_view(self):
        assert can_view_settings(ROLE_BUILDING_ADMIN) is True

    def test_legacy_admin_can_view(self):
        assert can_view_settings(ROLE_ADMIN) is True

    def test_super_admin_can_view(self):
        assert can_view_settings(ROLE_SUPER_ADMIN) is True

    def test_teacher_cannot_view(self):
        assert can_view_settings(ROLE_TEACHER) is False

    def test_staff_cannot_view(self):
        assert can_view_settings(ROLE_STAFF) is False

    def test_none_role_cannot_view(self):
        assert can_view_settings(None) is False

    def test_unknown_role_cannot_view(self):
        assert can_view_settings("janitor") is False


# ---------------------------------------------------------------------------
# Permission gate — who may edit each settings category
# ---------------------------------------------------------------------------

EDIT_CATEGORIES = ["notifications", "quiet_periods", "alerts", "devices", "access_codes"]


class TestCanEditSettings:
    @pytest.mark.parametrize("category", EDIT_CATEGORIES)
    def test_district_admin_can_edit_all(self, category):
        assert can_edit_settings(ROLE_DISTRICT_ADMIN, category) is True

    @pytest.mark.parametrize("category", EDIT_CATEGORIES)
    def test_super_admin_can_edit_all(self, category):
        assert can_edit_settings(ROLE_SUPER_ADMIN, category) is True

    @pytest.mark.parametrize("category", EDIT_CATEGORIES)
    def test_building_admin_cannot_edit_any(self, category):
        assert can_edit_settings(ROLE_BUILDING_ADMIN, category) is False

    @pytest.mark.parametrize("category", EDIT_CATEGORIES)
    def test_legacy_admin_cannot_edit_any(self, category):
        assert can_edit_settings(ROLE_ADMIN, category) is False

    @pytest.mark.parametrize("category", EDIT_CATEGORIES)
    def test_teacher_cannot_edit_any(self, category):
        assert can_edit_settings(ROLE_TEACHER, category) is False

    def test_unknown_category_returns_false_for_district_admin(self):
        assert can_edit_settings(ROLE_DISTRICT_ADMIN, "ui") is False

    def test_unknown_category_returns_false_for_any_role(self):
        assert can_edit_settings(ROLE_SUPER_ADMIN, "nonexistent_category") is False


# ---------------------------------------------------------------------------
# effective_settings_dict — critical_alert_sound_locked invariant
# ---------------------------------------------------------------------------

class TestEffectiveSettingsDict:
    def test_critical_alert_sound_locked_always_true(self):
        d = effective_settings_dict(TenantSettings())
        assert d["notifications"]["critical_alert_sound_locked"] is True

    def test_critical_alert_sound_locked_survives_patch(self):
        # Even if someone somehow patches it in the raw blob, it's always True
        from app.services.tenant_settings import settings_from_dict
        s = settings_from_dict({"notifications": {"critical_alert_sound_locked": False}})
        d = effective_settings_dict(s)
        assert d["notifications"]["critical_alert_sound_locked"] is True

    def test_default_non_critical_sound_name(self):
        d = effective_settings_dict(TenantSettings())
        assert d["notifications"]["non_critical_sound_name"] == "notification_soft"

    def test_default_non_critical_sound_enabled(self):
        d = effective_settings_dict(TenantSettings())
        assert d["notifications"]["non_critical_sound_enabled"] is True


# ---------------------------------------------------------------------------
# Validate settings patch — boundary and type checks
# ---------------------------------------------------------------------------

class TestValidateSettingsPatch:
    def test_valid_notification_patch(self):
        errors = validate_settings_patch({"notifications": {"non_critical_sound_enabled": False}})
        assert errors == []

    def test_valid_quiet_period_patch(self):
        errors = validate_settings_patch({"quiet_periods": {"max_duration_minutes": 480}})
        assert errors == []

    def test_invalid_sound_name_rejected(self):
        errors = validate_settings_patch({"notifications": {"non_critical_sound_name": "custom_alarm"}})
        assert any("non_critical_sound_name" in e for e in errors)

    def test_critical_alert_sound_locked_rejected_as_read_only(self):
        errors = validate_settings_patch({"notifications": {"critical_alert_sound_locked": True}})
        assert any("critical_alert_sound_locked" in e for e in errors)

    def test_max_duration_too_low_rejected(self):
        errors = validate_settings_patch({"quiet_periods": {"max_duration_minutes": 5}})
        assert any("max_duration_minutes" in e for e in errors)

    def test_max_duration_too_high_rejected(self):
        errors = validate_settings_patch({"quiet_periods": {"max_duration_minutes": 99999}})
        assert any("max_duration_minutes" in e for e in errors)

    def test_hold_seconds_too_low_rejected(self):
        errors = validate_settings_patch({"alerts": {"hold_seconds": 0}})
        assert any("hold_seconds" in e for e in errors)

    def test_hold_seconds_too_high_rejected(self):
        errors = validate_settings_patch({"alerts": {"hold_seconds": 100}})
        assert any("hold_seconds" in e for e in errors)

    def test_valid_hold_seconds(self):
        errors = validate_settings_patch({"alerts": {"hold_seconds": 3}})
        assert errors == []

    def test_expiration_days_too_low_rejected(self):
        errors = validate_settings_patch({"access_codes": {"default_expiration_days": 0}})
        assert any("default_expiration_days" in e for e in errors)

    def test_expiration_days_too_high_rejected(self):
        errors = validate_settings_patch({"access_codes": {"default_expiration_days": 999}})
        assert any("default_expiration_days" in e for e in errors)

    def test_theme_mode_invalid_rejected(self):
        errors = validate_settings_patch({"ui": {"theme_mode": "sepia"}})
        assert any("theme_mode" in e for e in errors)

    def test_theme_mode_valid(self):
        errors = validate_settings_patch({"ui": {"theme_mode": "dark"}})
        assert errors == []

    def test_wrong_type_bool_field_rejected(self):
        errors = validate_settings_patch({"notifications": {"non_critical_sound_enabled": "yes"}})
        assert any("non_critical_sound_enabled" in e for e in errors)

    def test_wrong_type_int_field_rejected(self):
        errors = validate_settings_patch({"quiet_periods": {"max_duration_minutes": "long"}})
        assert any("max_duration_minutes" in e for e in errors)

    def test_unknown_keys_in_known_category_are_ignored(self):
        errors = validate_settings_patch({"notifications": {"made_up_field": True}})
        assert errors == []

    def test_completely_unknown_category_is_ignored(self):
        errors = validate_settings_patch({"totally_new_category": {"key": "value"}})
        assert errors == []

    def test_empty_patch_is_valid(self):
        assert validate_settings_patch({}) == []


# ---------------------------------------------------------------------------
# Store — round-trip: patch → get_effective_settings
# ---------------------------------------------------------------------------

class TestStoreRoundTrip:
    @pytest.mark.anyio
    async def test_defaults_returned_when_empty(self, store):
        s = await store.get_effective_settings()
        assert isinstance(s, TenantSettings)
        assert s.notifications.non_critical_sound_name == "notification_soft"

    @pytest.mark.anyio
    async def test_patch_notifications_persists(self, store):
        new_s, errors = await store.update_settings(
            {"notifications": {"non_critical_sound_enabled": False}},
            actor_label="test_admin",
        )
        assert errors == []
        assert new_s.notifications.non_critical_sound_enabled is False
        # Read back
        fetched = await store.get_effective_settings()
        assert fetched.notifications.non_critical_sound_enabled is False

    @pytest.mark.anyio
    async def test_patch_quiet_periods_persists(self, store):
        new_s, errors = await store.update_settings(
            {"quiet_periods": {"max_duration_minutes": 240}},
            actor_label="test_admin",
        )
        assert errors == []
        assert new_s.quiet_periods.max_duration_minutes == 240
        fetched = await store.get_effective_settings()
        assert fetched.quiet_periods.max_duration_minutes == 240

    @pytest.mark.anyio
    async def test_invalid_patch_returns_errors_and_does_not_write(self, store):
        _, errors = await store.update_settings(
            {"notifications": {"non_critical_sound_name": "bad_sound"}},
            actor_label="test_admin",
        )
        assert errors
        # Settings must remain at default
        fetched = await store.get_effective_settings()
        assert fetched.notifications.non_critical_sound_name == "notification_soft"

    @pytest.mark.anyio
    async def test_partial_patch_does_not_clobber_other_fields(self, store):
        # Set two fields
        await store.update_settings(
            {"notifications": {"non_critical_sound_enabled": False, "admin_message_notifications_enabled": False}},
            actor_label="test_admin",
        )
        # Patch only one field
        await store.update_settings(
            {"notifications": {"non_critical_sound_enabled": True}},
            actor_label="test_admin",
        )
        fetched = await store.get_effective_settings()
        assert fetched.notifications.non_critical_sound_enabled is True
        # The other field must still be False
        assert fetched.notifications.admin_message_notifications_enabled is False

    @pytest.mark.anyio
    async def test_reset_restores_defaults(self, store):
        await store.update_settings(
            {"quiet_periods": {"max_duration_minutes": 360}},
            actor_label="test_admin",
        )
        defaults = await store.reset_to_defaults(actor_label="test_admin")
        assert defaults.quiet_periods.max_duration_minutes == 1440  # default
        fetched = await store.get_effective_settings()
        assert fetched.quiet_periods.max_duration_minutes == 1440


# ---------------------------------------------------------------------------
# Store — history recording
# ---------------------------------------------------------------------------

class TestStoreHistory:
    @pytest.mark.anyio
    async def test_update_records_history(self, store):
        await store.update_settings(
            {"notifications": {"non_critical_sound_enabled": False}},
            actor_label="admin@school.edu",
        )
        history = await store.get_history(limit=10)
        assert len(history) >= 1
        latest = history[0]
        assert latest.field == "settings.notifications"
        assert latest.changed_by_label == "admin@school.edu"
        assert latest.new_value.get("non_critical_sound_enabled") is False

    @pytest.mark.anyio
    async def test_reset_records_history(self, store):
        await store.update_settings(
            {"quiet_periods": {"max_duration_minutes": 120}},
            actor_label="admin",
        )
        await store.reset_to_defaults(actor_label="admin")
        history = await store.get_history(limit=10)
        reset_entries = [h for h in history if "reset" in h.field]
        assert reset_entries

    @pytest.mark.anyio
    async def test_history_limit_respected(self, store):
        for i in range(5):
            await store.update_settings(
                {"alerts": {"hold_seconds": i + 1}},
                actor_label=f"admin_{i}",
            )
        history = await store.get_history(limit=3)
        assert len(history) == 3

    @pytest.mark.anyio
    async def test_no_history_entry_when_value_unchanged_between_two_explicit_writes(self, store):
        # Write a value explicitly, then write the same value again.
        await store.update_settings(
            {"notifications": {"non_critical_sound_enabled": False}},
            actor_label="admin",
        )
        history_before = await store.get_history(limit=50)
        assert len(history_before) == 1

        # Write the same value again — raw blob value is unchanged, so no new entry.
        await store.update_settings(
            {"notifications": {"non_critical_sound_enabled": False}},
            actor_label="admin",
        )
        history_after = await store.get_history(limit=50)
        assert len(history_after) == 1  # no new entry added
