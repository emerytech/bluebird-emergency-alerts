"""Tests for the smart suggestion engine."""
from __future__ import annotations

import pytest

from app.services.suggestion_engine import (
    RuleBasedProvider,
    Suggestion,
    SuggestionContext,
    SuggestionEngine,
    SuggestionProvider,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _healthy_ctx(**overrides) -> SuggestionContext:
    """Baseline context where the tenant is fully configured — no suggestions expected."""
    defaults = dict(
        role="building_admin",
        prefix="/bb/school-a",
        user_count=10,
        active_user_count=8,
        device_count=7,
        apns_configured=True,
        fcm_configured=False,
        totp_enabled=True,
        access_code_count=3,
        unread_messages=0,
        help_requests_active=0,
        alert_count_7d=2,
        district_admin_count=1,
        acknowledgement_rate=None,
        quiet_period_active=False,
    )
    defaults.update(overrides)
    return SuggestionContext(**defaults)


def _engine() -> SuggestionEngine:
    return SuggestionEngine()


def _ids(suggestions: list[Suggestion]) -> list[str]:
    return [s.id for s in suggestions]


# ── Core engine behaviour ─────────────────────────────────────────────────────


def test_healthy_tenant_produces_no_suggestions():
    result = _engine().evaluate(_healthy_ctx())
    assert result == []


def test_result_capped_at_four():
    # Trigger as many rules as possible simultaneously.
    ctx = _healthy_ctx(
        user_count=0,
        active_user_count=0,
        device_count=0,
        apns_configured=False,
        fcm_configured=False,
        totp_enabled=False,
        unread_messages=3,
        help_requests_active=2,
        access_code_count=0,
        alert_count_7d=0,
        district_admin_count=0,
        acknowledgement_rate=0.2,
    )
    result = _engine().evaluate(ctx)
    assert len(result) <= 4


def test_result_sorted_by_priority():
    ctx = _healthy_ctx(
        totp_enabled=False,           # medium
        help_requests_active=1,       # high
        alert_count_7d=0,             # medium (no_recent_drill)
    )
    result = _engine().evaluate(ctx)
    priorities = [s.priority for s in result]
    _PRIO = {"high": 0, "medium": 1, "low": 2}
    assert priorities == sorted(priorities, key=lambda p: _PRIO.get(p, 99))


def test_no_duplicate_ids():
    ctx = _healthy_ctx(help_requests_active=5)
    ids = _ids(_engine().evaluate(ctx))
    assert len(ids) == len(set(ids))


# ── Individual rules ──────────────────────────────────────────────────────────


def test_help_requests_active_fires():
    ctx = _healthy_ctx(help_requests_active=2)
    ids = _ids(_engine().evaluate(ctx))
    assert "help_requests_active" in ids


def test_help_requests_zero_no_fire():
    ctx = _healthy_ctx(help_requests_active=0)
    ids = _ids(_engine().evaluate(ctx))
    assert "help_requests_active" not in ids


def test_unread_messages_fires():
    ctx = _healthy_ctx(unread_messages=1)
    ids = _ids(_engine().evaluate(ctx))
    assert "unread_messages" in ids


def test_push_not_configured_fires_when_both_missing():
    ctx = _healthy_ctx(apns_configured=False, fcm_configured=False)
    ids = _ids(_engine().evaluate(ctx))
    assert "push_not_configured" in ids


def test_push_not_configured_suppressed_when_apns_ok():
    ctx = _healthy_ctx(apns_configured=True, fcm_configured=False)
    ids = _ids(_engine().evaluate(ctx))
    assert "push_not_configured" not in ids


def test_low_ack_rate_fires_below_70_pct():
    ctx = _healthy_ctx(acknowledgement_rate=0.50)
    ids = _ids(_engine().evaluate(ctx))
    assert "low_ack_rate" in ids


def test_low_ack_rate_suppressed_above_threshold():
    ctx = _healthy_ctx(acknowledgement_rate=0.75)
    ids = _ids(_engine().evaluate(ctx))
    assert "low_ack_rate" not in ids


def test_low_ack_rate_suppressed_when_none():
    ctx = _healthy_ctx(acknowledgement_rate=None)
    ids = _ids(_engine().evaluate(ctx))
    assert "low_ack_rate" not in ids


def test_no_users_fires():
    ctx = _healthy_ctx(user_count=0, active_user_count=0, device_count=0)
    ids = _ids(_engine().evaluate(ctx))
    assert "no_users" in ids


def test_no_devices_fires_when_users_exist():
    ctx = _healthy_ctx(device_count=0, active_user_count=5)
    ids = _ids(_engine().evaluate(ctx))
    assert "no_devices" in ids


def test_low_device_coverage_fires():
    ctx = _healthy_ctx(active_user_count=10, device_count=4)
    ids = _ids(_engine().evaluate(ctx))
    assert "low_device_coverage" in ids


def test_low_device_coverage_suppressed_when_coverage_ok():
    ctx = _healthy_ctx(active_user_count=10, device_count=6)
    ids = _ids(_engine().evaluate(ctx))
    assert "low_device_coverage" not in ids


def test_no_access_codes_fires():
    ctx = _healthy_ctx(access_code_count=0, active_user_count=3)
    ids = _ids(_engine().evaluate(ctx))
    assert "no_access_codes" in ids


def test_no_recent_drill_fires():
    ctx = _healthy_ctx(alert_count_7d=0)
    ids = _ids(_engine().evaluate(ctx))
    assert "no_recent_drill" in ids


def test_no_recent_drill_suppressed_when_no_users():
    ctx = _healthy_ctx(alert_count_7d=0, user_count=0, active_user_count=0)
    ids = _ids(_engine().evaluate(ctx))
    assert "no_recent_drill" not in ids


def test_no_2fa_fires_for_building_admin():
    ctx = _healthy_ctx(totp_enabled=False, role="building_admin")
    ids = _ids(_engine().evaluate(ctx))
    assert "no_2fa" in ids


def test_no_2fa_suppressed_for_staff_role():
    ctx = _healthy_ctx(totp_enabled=False, role="staff")
    ids = _ids(_engine().evaluate(ctx))
    assert "no_2fa" not in ids


def test_no_district_admin_fires():
    ctx = _healthy_ctx(district_admin_count=0, active_user_count=10)
    ids = _ids(_engine().evaluate(ctx))
    assert "no_district_admin" in ids


def test_no_district_admin_suppressed_when_few_users():
    ctx = _healthy_ctx(district_admin_count=0, active_user_count=3)
    ids = _ids(_engine().evaluate(ctx))
    assert "no_district_admin" not in ids


# ── Pluggable provider ────────────────────────────────────────────────────────


def test_suggestion_provider_protocol():
    """RuleBasedProvider satisfies the SuggestionProvider Protocol."""
    assert isinstance(RuleBasedProvider(), SuggestionProvider)


def test_custom_provider_merged():
    class AlwaysOnProvider:
        def evaluate(self, ctx: SuggestionContext) -> list[Suggestion]:
            return [
                Suggestion(
                    id="custom_test",
                    title="Custom suggestion",
                    description="Always fires.",
                    priority="low",
                )
            ]

    engine = SuggestionEngine(providers=[RuleBasedProvider(), AlwaysOnProvider()])
    result = engine.evaluate(_healthy_ctx())
    ids = _ids(result)
    assert "custom_test" in ids


def test_provider_deduplication():
    """If two providers return the same id, only the first occurrence is kept."""
    class DupeProvider:
        def evaluate(self, ctx: SuggestionContext) -> list[Suggestion]:
            return [
                Suggestion(id="dupe", title="A", description=".", priority="high"),
                Suggestion(id="dupe", title="B", description=".", priority="high"),
            ]

    engine = SuggestionEngine(providers=[DupeProvider()])
    result = engine.evaluate(_healthy_ctx())
    assert sum(1 for s in result if s.id == "dupe") == 1
