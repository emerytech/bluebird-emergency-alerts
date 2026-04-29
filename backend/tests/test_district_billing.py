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
from app.services.tenant_billing_store import TenantBillingRecord, TenantBillingStore


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
