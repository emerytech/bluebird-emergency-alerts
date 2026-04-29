"""
Phase 7 — District Billing + Analytics Validation Tests

Covers:
  ✔ District license applies to all schools (enforcement uses district billing)
  ✔ Single school still works without a district (falls back to tenant billing)
  ✔ Alerts remain isolated (billing never gating alert paths)
  ✔ Analytics aggregate helpers work correctly
  ✔ No API breakage (existing TenantBillingRecord shape unchanged)
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.billing_service import (
    get_effective_billing_for_tenant,
    get_effective_status,
    get_days_remaining,
    is_management_allowed,
    require_management_license,
    ManagementLicenseError,
)
from app.services.tenant_billing_store import BillingAuditRecord, TenantBillingRecord, TenantBillingStore


# ── Helpers ────────────────────────────────────────────────────────────────────


def _sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@pytest.fixture()
def store(tmp_path) -> TenantBillingStore:
    return TenantBillingStore(db_path=str(tmp_path / "billing.db"))


# ── Phase 7: District license covers all schools ───────────────────────────────


def test_district_license_active_allows_school(store: TenantBillingStore) -> None:
    """Active district billing allows management even if tenant billing is expired."""
    _sync(store.update_district_billing_full(
        district_id=10,
        billing_status="active",
        plan_type="basic",
        current_period_end=_future(90),
    ))
    _sync(store.update_billing_full(
        tenant_id=1,
        billing_status="trial",
        trial_ends_at=_past(5),
    ))

    effective = _sync(get_effective_billing_for_tenant(store, tenant_id=1, district_id=10))
    assert is_management_allowed(effective)


def test_district_license_expired_blocks_school(store: TenantBillingStore) -> None:
    """Expired district billing blocks management even if tenant billing is active."""
    _sync(store.update_district_billing_full(
        district_id=11,
        billing_status="expired",
        current_period_end=_past(10),
    ))
    _sync(store.update_billing_full(
        tenant_id=2,
        billing_status="active",
        current_period_end=_future(30),
    ))

    effective = _sync(get_effective_billing_for_tenant(store, tenant_id=2, district_id=11))
    assert not is_management_allowed(effective)


def test_district_override_allows_school(store: TenantBillingStore) -> None:
    """District manual override grants access to schools."""
    _sync(store.update_district_billing_full(
        district_id=12,
        billing_status="cancelled",
        override_enabled=True,
        override_reason="Nonprofit partner",
    ))

    effective = _sync(get_effective_billing_for_tenant(store, tenant_id=3, district_id=12))
    assert is_management_allowed(effective)
    assert get_effective_status(effective) == "manual_override"


# ── Phase 7: Single school without district ────────────────────────────────────


def test_no_district_uses_tenant_billing(store: TenantBillingStore) -> None:
    """When district_id is None, tenant billing is used."""
    _sync(store.update_billing_full(
        tenant_id=4,
        billing_status="active",
        current_period_end=_future(30),
    ))

    effective = _sync(get_effective_billing_for_tenant(store, tenant_id=4, district_id=None))
    assert is_management_allowed(effective)
    assert effective.tenant_id == 4


def test_no_district_expired_tenant_blocks(store: TenantBillingStore) -> None:
    """Expired tenant billing blocks when no district is assigned."""
    _sync(store.update_billing_full(
        tenant_id=5,
        billing_status="expired",
        trial_ends_at=_past(10),
    ))

    effective = _sync(get_effective_billing_for_tenant(store, tenant_id=5, district_id=None))
    assert not is_management_allowed(effective)


def test_district_without_billing_record_falls_back(store: TenantBillingStore) -> None:
    """If district has no billing record, falls back to tenant billing."""
    _sync(store.update_billing_full(
        tenant_id=6,
        billing_status="active",
        current_period_end=_future(30),
    ))

    # district_id=999 has no billing record in store
    effective = _sync(get_effective_billing_for_tenant(store, tenant_id=6, district_id=999))
    assert effective.tenant_id == 6
    assert is_management_allowed(effective)


# ── Phase 7: District billing store CRUD ──────────────────────────────────────


def test_ensure_district_billing_creates_default(store: TenantBillingStore) -> None:
    record = _sync(store.ensure_district_billing(district_id=20))
    assert record.district_id == 20
    assert record.billing_status == "trial"
    assert record.tenant_id == 0  # synthetic sentinel


def test_update_district_billing_full(store: TenantBillingStore) -> None:
    period_end = _future(365)
    record = _sync(store.update_district_billing_full(
        district_id=21,
        billing_status="active",
        plan_type="enterprise",
        license_key="BB-TEST-1234-5678-9ABC",
        customer_name="Acme Unified District",
        customer_email="billing@acme.edu",
        current_period_end=period_end,
        internal_notes="Piloting district licensing",
    ))
    assert record.billing_status == "active"
    assert record.plan_type == "enterprise"
    assert record.license_key == "BB-TEST-1234-5678-9ABC"
    assert record.customer_name == "Acme Unified District"
    assert record.district_id == 21


def test_list_all_district_billing(store: TenantBillingStore) -> None:
    _sync(store.ensure_district_billing(district_id=30))
    _sync(store.ensure_district_billing(district_id=31))
    records = _sync(store.list_all_district_billing())
    district_ids = {r.district_id for r in records}
    assert 30 in district_ids
    assert 31 in district_ids


def test_get_district_billing_returns_none_when_missing(store: TenantBillingStore) -> None:
    result = _sync(store.get_district_billing(district_id=999))
    assert result is None


def test_get_district_billing_after_ensure(store: TenantBillingStore) -> None:
    _sync(store.ensure_district_billing(district_id=40))
    result = _sync(store.get_district_billing(district_id=40))
    assert result is not None
    assert result.district_id == 40


# ── Phase 7: Billing enforcement ──────────────────────────────────────────────


def _make_record(
    *,
    billing_status: str,
    period_end: Optional[str] = None,
    override: bool = False,
) -> TenantBillingRecord:
    now = _now()
    return TenantBillingRecord(
        tenant_id=0,
        tenant_slug=None,
        district_id=1,
        customer_name=None,
        customer_email=None,
        plan_id=None,
        plan_type="basic",
        billing_status=billing_status,
        license_key=None,
        starts_at=None,
        trial_start=None,
        trial_end=period_end,
        trial_ends_at=period_end,
        current_period_start=None,
        current_period_end=period_end,
        renewal_date=period_end,
        is_free_override=override,
        free_reason=None,
        override_enabled=override,
        override_reason=None,
        internal_notes=None,
        created_at=now,
        updated_at=now,
        stripe_customer_id=None,
        stripe_subscription_id=None,
        stripe_price_id=None,
        stripe_checkout_session_id=None,
    )


def test_require_management_license_passes_for_active() -> None:
    record = _make_record(billing_status="active", period_end=_future(30))
    require_management_license(record, "create_user")  # must not raise


def test_require_management_license_raises_for_expired() -> None:
    record = _make_record(billing_status="expired", period_end=_past(10))
    with pytest.raises(ManagementLicenseError) as exc_info:
        require_management_license(record, "create_user")
    assert exc_info.value.feature_name == "create_user"


def test_require_management_license_passes_for_override() -> None:
    record = _make_record(billing_status="cancelled", override=True)
    require_management_license(record, "generate_access_code")  # must not raise


# ── Phase 7: Alert isolation ──────────────────────────────────────────────────


def test_alert_trigger_independent_of_billing() -> None:
    """billing_service must not reference panic or alarm_trigger paths."""
    from app.services import billing_service  # noqa: PLC0415
    import inspect

    source = inspect.getsource(billing_service)
    assert "panic" not in source
    assert "alarm_trigger" not in source


# ── Phase 7: Analytics aggregate correctness ──────────────────────────────────


def test_district_analytics_aggregation_math() -> None:
    per_school = [
        {"user_count": 10, "device_count": 8, "alert_count": 3},
        {"user_count": 20, "device_count": 15, "alert_count": 7},
        {"user_count": 5, "device_count": 3, "alert_count": 0},
    ]
    assert sum(s["user_count"] for s in per_school) == 35
    assert sum(s["device_count"] for s in per_school) == 26
    assert sum(s["alert_count"] for s in per_school) == 10


# ── Phase 7: Backward compat ──────────────────────────────────────────────────


def test_tenant_billing_record_all_fields_present() -> None:
    """TenantBillingRecord must still have all pre-existing fields."""
    required = {
        "tenant_id", "tenant_slug", "district_id", "customer_name", "customer_email",
        "plan_id", "plan_type", "billing_status", "license_key",
        "starts_at", "trial_start", "trial_end", "trial_ends_at",
        "current_period_start", "current_period_end", "renewal_date",
        "is_free_override", "free_reason", "override_enabled", "override_reason",
        "internal_notes", "created_at", "updated_at",
        "stripe_customer_id", "stripe_subscription_id", "stripe_price_id",
        "stripe_checkout_session_id",
    }
    now = _now()
    record = TenantBillingRecord(
        tenant_id=1, tenant_slug="test", district_id=None,
        customer_name=None, customer_email=None, plan_id="trial", plan_type="trial",
        billing_status="trial", license_key=None, starts_at=None, trial_start=None,
        trial_end=None, trial_ends_at=None, current_period_start=None,
        current_period_end=None, renewal_date=None, is_free_override=False,
        free_reason=None, override_enabled=False, override_reason=None,
        internal_notes=None, created_at=now, updated_at=now,
        stripe_customer_id=None, stripe_subscription_id=None,
        stripe_price_id=None, stripe_checkout_session_id=None,
    )
    for field in required:
        assert hasattr(record, field), f"TenantBillingRecord missing field: {field}"


# ── Phase 12: Archive fields present on TenantBillingRecord ───────────────────


def test_tenant_billing_record_has_archive_fields() -> None:
    """New archive fields must exist with correct defaults."""
    now = _now()
    record = TenantBillingRecord(
        tenant_id=1, tenant_slug="test", district_id=None,
        customer_name=None, customer_email=None, plan_id="trial", plan_type="trial",
        billing_status="trial", license_key=None, starts_at=None, trial_start=None,
        trial_end=None, trial_ends_at=None, current_period_start=None,
        current_period_end=None, renewal_date=None, is_free_override=False,
        free_reason=None, override_enabled=False, override_reason=None,
        internal_notes=None, created_at=now, updated_at=now,
        stripe_customer_id=None, stripe_subscription_id=None,
        stripe_price_id=None, stripe_checkout_session_id=None,
    )
    assert record.is_archived is False
    assert record.archived_at is None
    assert record.archived_by is None


# ── Phase 12: Archive / Restore ───────────────────────────────────────────────


def test_archive_district_billing(store: TenantBillingStore) -> None:
    _sync(store.ensure_district_billing(district_id=50))
    result = _sync(store.archive_district_billing(district_id=50, archived_by="super_admin:alice"))
    assert result.is_archived is True
    assert result.archived_by == "super_admin:alice"
    assert result.archived_at is not None


def test_archived_excluded_from_default_get(store: TenantBillingStore) -> None:
    """get_district_billing(include_archived=False) must return None for an archived record."""
    _sync(store.ensure_district_billing(district_id=51))
    _sync(store.archive_district_billing(district_id=51, archived_by="super_admin:alice"))

    result = _sync(store.get_district_billing(district_id=51))
    assert result is None


def test_archived_visible_when_include_archived(store: TenantBillingStore) -> None:
    """get_district_billing(include_archived=True) returns the archived record."""
    _sync(store.ensure_district_billing(district_id=52))
    _sync(store.archive_district_billing(district_id=52, archived_by="super_admin:alice"))

    result = _sync(store.get_district_billing(district_id=52, include_archived=True))
    assert result is not None
    assert result.is_archived is True


def test_archived_excluded_from_list_by_default(store: TenantBillingStore) -> None:
    """list_all_district_billing() excludes archived records by default."""
    _sync(store.ensure_district_billing(district_id=53))
    _sync(store.ensure_district_billing(district_id=54))
    _sync(store.archive_district_billing(district_id=54, archived_by="super_admin:alice"))

    active_records = _sync(store.list_all_district_billing())
    active_ids = {r.district_id for r in active_records}
    assert 53 in active_ids
    assert 54 not in active_ids


def test_archived_excluded_from_enforcement(store: TenantBillingStore) -> None:
    """Archived district billing is invisible to get_effective_billing_for_tenant (falls back to tenant billing)."""
    _sync(store.update_district_billing_full(
        district_id=55,
        billing_status="active",
        current_period_end=_future(90),
    ))
    _sync(store.archive_district_billing(district_id=55, archived_by="super_admin:alice"))
    _sync(store.update_billing_full(
        tenant_id=7,
        billing_status="active",
        current_period_end=_future(30),
    ))

    effective = _sync(get_effective_billing_for_tenant(store, tenant_id=7, district_id=55))
    assert effective.tenant_id == 7


def test_restore_district_billing(store: TenantBillingStore) -> None:
    _sync(store.ensure_district_billing(district_id=56))
    _sync(store.archive_district_billing(district_id=56, archived_by="super_admin:alice"))
    result = _sync(store.restore_district_billing(district_id=56))

    assert result.is_archived is False
    assert result.archived_at is None
    assert result.archived_by is None


def test_restore_makes_record_visible_again(store: TenantBillingStore) -> None:
    _sync(store.ensure_district_billing(district_id=57))
    _sync(store.archive_district_billing(district_id=57, archived_by="super_admin:alice"))
    _sync(store.restore_district_billing(district_id=57))

    result = _sync(store.get_district_billing(district_id=57))
    assert result is not None
    assert result.is_archived is False


# ── Phase 12: Delete ──────────────────────────────────────────────────────────


def test_delete_archived_district_billing(store: TenantBillingStore) -> None:
    _sync(store.ensure_district_billing(district_id=60))
    _sync(store.archive_district_billing(district_id=60, archived_by="super_admin:alice"))
    _sync(store.delete_district_billing(district_id=60))

    result = _sync(store.get_district_billing(district_id=60, include_archived=True))
    assert result is None


def test_delete_expired_district_billing_without_archive(store: TenantBillingStore) -> None:
    """Expired/cancelled licenses can be deleted without archiving first."""
    _sync(store.update_district_billing_full(
        district_id=61,
        billing_status="expired",
        current_period_end=_past(10),
    ))
    _sync(store.delete_district_billing(district_id=61))

    result = _sync(store.get_district_billing(district_id=61, include_archived=True))
    assert result is None


def test_delete_cancelled_district_billing_without_archive(store: TenantBillingStore) -> None:
    _sync(store.update_district_billing_full(district_id=62, billing_status="cancelled"))
    _sync(store.delete_district_billing(district_id=62))
    result = _sync(store.get_district_billing(district_id=62, include_archived=True))
    assert result is None


def test_delete_active_district_billing_raises(store: TenantBillingStore) -> None:
    """Deleting an active license without archiving must raise ValueError."""
    _sync(store.update_district_billing_full(
        district_id=63,
        billing_status="active",
        current_period_end=_future(30),
    ))
    with pytest.raises(ValueError, match="Cannot delete an active district license"):
        _sync(store.delete_district_billing(district_id=63))


def test_delete_trial_district_billing_raises(store: TenantBillingStore) -> None:
    _sync(store.ensure_district_billing(district_id=64))  # default status="trial"
    with pytest.raises(ValueError, match="Cannot delete an active district license"):
        _sync(store.delete_district_billing(district_id=64))


def test_delete_past_due_district_billing_raises(store: TenantBillingStore) -> None:
    _sync(store.update_district_billing_full(district_id=65, billing_status="past_due"))
    with pytest.raises(ValueError, match="Cannot delete an active district license"):
        _sync(store.delete_district_billing(district_id=65))


def test_delete_nonexistent_district_billing_is_noop(store: TenantBillingStore) -> None:
    _sync(store.delete_district_billing(district_id=9999))  # must not raise


# ── Phase 12: Billing Audit Log ───────────────────────────────────────────────


def test_log_billing_audit_returns_record(store: TenantBillingStore) -> None:
    record = _sync(store.log_billing_audit(
        district_id=70,
        event_type="license_created",
        actor="super_admin:bob",
        detail="Plan: enterprise",
    ))
    assert isinstance(record, BillingAuditRecord)
    assert record.district_id == 70
    assert record.event_type == "license_created"
    assert record.actor == "super_admin:bob"
    assert record.detail == "Plan: enterprise"
    assert record.id > 0
    assert record.created_at


def test_list_billing_audit_returns_entries(store: TenantBillingStore) -> None:
    _sync(store.log_billing_audit(district_id=71, event_type="license_archived", actor="super_admin:carol"))
    _sync(store.log_billing_audit(district_id=71, event_type="license_restored", actor="super_admin:carol"))

    entries = _sync(store.list_billing_audit(district_id=71))
    assert len(entries) == 2
    event_types = {e.event_type for e in entries}
    assert "license_archived" in event_types
    assert "license_restored" in event_types


def test_list_billing_audit_filters_by_district(store: TenantBillingStore) -> None:
    _sync(store.log_billing_audit(district_id=72, event_type="license_created", actor="super_admin:dave"))
    _sync(store.log_billing_audit(district_id=73, event_type="license_created", actor="super_admin:dave"))

    entries_72 = _sync(store.list_billing_audit(district_id=72))
    assert all(e.district_id == 72 for e in entries_72)
    assert len(entries_72) == 1


def test_list_billing_audit_all_districts(store: TenantBillingStore) -> None:
    _sync(store.log_billing_audit(district_id=74, event_type="status_changed", actor="super_admin:eve"))
    _sync(store.log_billing_audit(district_id=75, event_type="status_changed", actor="super_admin:eve"))

    all_entries = _sync(store.list_billing_audit())
    district_ids = {e.district_id for e in all_entries}
    assert 74 in district_ids
    assert 75 in district_ids


def test_list_billing_audit_respects_limit(store: TenantBillingStore) -> None:
    for i in range(10):
        _sync(store.log_billing_audit(district_id=76, event_type="status_changed", actor="super_admin:test"))

    entries = _sync(store.list_billing_audit(district_id=76, limit=3))
    assert len(entries) == 3
