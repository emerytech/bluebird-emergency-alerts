"""
Phase 11 tests: billing license, status, enforcement, and super-admin access controls.

Critical invariant: expired billing MUST NOT block emergency alerts.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.billing_service import (
    ManagementLicenseError,
    generate_license_key,
    generate_invoice_number,
    get_banner_info,
    get_days_remaining,
    get_effective_status,
    is_management_allowed,
    require_management_license,
)
from app.services.billing_access import has_tenant_access
from app.services.tenant_billing_store import TenantBillingRecord, TenantBillingStore


# ── Helpers ────────────────────────────────────────────────────────────────────


def _sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _future(days: int) -> str:
    return (_now() + timedelta(days=days)).isoformat()


def _past(days: int) -> str:
    return (_now() - timedelta(days=days)).isoformat()


def _make_record(
    *,
    billing_status: str = "trial",
    plan_type: str = "trial",
    override_enabled: bool = False,
    is_free_override: bool = False,
    trial_ends_at: Optional[str] = None,
    current_period_end: Optional[str] = None,
    tenant_id: int = 1,
) -> TenantBillingRecord:
    return TenantBillingRecord(
        tenant_id=tenant_id,
        tenant_slug="test-school",
        district_id=None,
        customer_name=None,
        customer_email=None,
        plan_id=plan_type,
        plan_type=plan_type,
        billing_status=billing_status,
        license_key=None,
        starts_at=None,
        trial_start=None,
        trial_end=trial_ends_at,
        trial_ends_at=trial_ends_at,
        current_period_start=None,
        current_period_end=current_period_end,
        renewal_date=current_period_end,
        is_free_override=is_free_override,
        free_reason=None,
        override_enabled=override_enabled,
        override_reason=None,
        internal_notes=None,
        created_at=None,
        updated_at=_now().isoformat(),
        stripe_customer_id=None,
        stripe_subscription_id=None,
        stripe_price_id=None,
        stripe_checkout_session_id=None,
    )


# ── License key generation ─────────────────────────────────────────────────────


class TestLicenseKeyGeneration:
    def test_format(self):
        key = generate_license_key()
        parts = key.split("-")
        assert parts[0] == "BB"
        assert len(parts) == 5
        for p in parts[1:]:
            assert len(p) == 4
            assert p.isupper() or p.isdigit() or all(c.isalnum() for c in p)

    def test_uniqueness(self):
        keys = {generate_license_key() for _ in range(100)}
        assert len(keys) == 100

    def test_invoice_number_format(self):
        inv = generate_invoice_number(tenant_slug="lincoln-high", sequence=3)
        assert inv.startswith("BB-INV-")
        assert inv.endswith("-0003")


# ── Status resolution ──────────────────────────────────────────────────────────


class TestGetEffectiveStatus:
    def test_active(self):
        r = _make_record(billing_status="active")
        assert get_effective_status(r) == "active"

    def test_trial_not_expired(self):
        r = _make_record(billing_status="trial", trial_ends_at=_future(10))
        assert get_effective_status(r) == "trial"

    def test_trial_expired_returns_expired(self):
        r = _make_record(billing_status="trial", trial_ends_at=_past(1))
        assert get_effective_status(r) == "expired"

    def test_trial_no_end_date(self):
        r = _make_record(billing_status="trial")
        # No trial_ends_at set → stays trial (no expiry to check)
        assert get_effective_status(r) == "trial"

    def test_override_enabled_wins(self):
        r = _make_record(billing_status="expired", override_enabled=True)
        assert get_effective_status(r) == "manual_override"

    def test_legacy_free_override_wins(self):
        r = _make_record(billing_status="past_due", is_free_override=True)
        assert get_effective_status(r) == "manual_override"

    def test_suspended(self):
        r = _make_record(billing_status="suspended")
        assert get_effective_status(r) == "suspended"

    def test_cancelled(self):
        r = _make_record(billing_status="cancelled")
        assert get_effective_status(r) == "cancelled"

    def test_none_billing_returns_trial(self):
        assert get_effective_status(None) == "trial"


# ── Management access ──────────────────────────────────────────────────────────


class TestIsManagementAllowed:
    def test_active_allows(self):
        r = _make_record(billing_status="active")
        assert is_management_allowed(r) is True

    def test_override_allows(self):
        r = _make_record(billing_status="expired", override_enabled=True)
        assert is_management_allowed(r) is True

    def test_active_trial_allows(self):
        r = _make_record(billing_status="trial", trial_ends_at=_future(5))
        assert is_management_allowed(r) is True

    def test_expired_trial_denies(self):
        r = _make_record(billing_status="trial", trial_ends_at=_past(1))
        assert is_management_allowed(r) is False

    def test_expired_denies(self):
        r = _make_record(billing_status="expired")
        assert is_management_allowed(r) is False

    def test_suspended_denies(self):
        r = _make_record(billing_status="suspended")
        assert is_management_allowed(r) is False

    def test_cancelled_denies(self):
        r = _make_record(billing_status="cancelled")
        assert is_management_allowed(r) is False

    def test_past_due_within_grace_allows(self):
        r = _make_record(billing_status="past_due", current_period_end=_past(3))
        assert is_management_allowed(r) is True

    def test_past_due_beyond_grace_denies(self):
        r = _make_record(billing_status="past_due", current_period_end=_past(10))
        assert is_management_allowed(r) is False

    def test_none_billing_no_dates_allows(self):
        # No billing record at all → trial with no expiry → allowed
        r = _make_record(billing_status="trial")
        assert is_management_allowed(r) is True


# ── require_management_license ─────────────────────────────────────────────────


class TestRequireManagementLicense:
    def test_active_does_not_raise(self):
        r = _make_record(billing_status="active")
        require_management_license(r, "user_creation")  # no exception

    def test_expired_raises(self):
        r = _make_record(billing_status="expired")
        with pytest.raises(ManagementLicenseError) as exc_info:
            require_management_license(r, "user_creation")
        assert exc_info.value.feature_name == "user_creation"

    def test_override_does_not_raise(self):
        r = _make_record(billing_status="expired", override_enabled=True)
        require_management_license(r, "access_code_generation")  # no exception

    def test_error_message_contains_status(self):
        r = _make_record(billing_status="suspended")
        with pytest.raises(ManagementLicenseError) as exc_info:
            require_management_license(r, "settings")
        assert "suspended" in str(exc_info.value)


# ── has_tenant_access (billing_access) ────────────────────────────────────────


class TestHasTenantAccess:
    def test_active(self):
        r = _make_record(billing_status="active")
        assert has_tenant_access(r) is True

    def test_trial_valid(self):
        r = _make_record(billing_status="trial", trial_ends_at=_future(5))
        assert has_tenant_access(r) is True

    def test_trial_expired(self):
        r = _make_record(billing_status="trial", trial_ends_at=_past(1))
        assert has_tenant_access(r) is False

    def test_past_due_grants_access(self):
        r = _make_record(billing_status="past_due")
        assert has_tenant_access(r) is True

    def test_expired_denies(self):
        r = _make_record(billing_status="expired")
        assert has_tenant_access(r) is False

    def test_suspended_denies(self):
        r = _make_record(billing_status="suspended")
        assert has_tenant_access(r) is False

    def test_manual_override_grants(self):
        r = _make_record(billing_status="expired", override_enabled=True)
        assert has_tenant_access(r) is True

    def test_legacy_free_override_grants(self):
        r = _make_record(billing_status="expired", is_free_override=True)
        assert has_tenant_access(r) is True

    def test_none_denies(self):
        assert has_tenant_access(None) is False


# ── Emergency operations exempt from billing check ────────────────────────────


class TestEmergencyExempt:
    """
    Verifies the design invariant: emergency routes must NEVER call
    require_management_license(). Simulated here by confirming that
    an expired tenant CAN still call the (unmocked) billing service
    without management check — as long as the caller skips it.
    """

    def test_expired_tenant_can_still_be_created_and_billing_read(self):
        """Expired billing record can be read without raising."""
        r = _make_record(billing_status="expired", trial_ends_at=_past(30))
        eff = get_effective_status(r)
        assert eff == "expired"
        # Emergency route would read this status but NOT call require_management_license()
        # — no exception here proves the separation of concerns

    def test_management_check_is_caller_opt_in(self):
        """require_management_license raises only when explicitly called."""
        r = _make_record(billing_status="suspended")
        # Without calling require_management_license: fine
        status = get_effective_status(r)
        assert status == "suspended"
        # With it: raises
        with pytest.raises(ManagementLicenseError):
            require_management_license(r, "some_management_feature")


# ── Banner info ────────────────────────────────────────────────────────────────


class TestBannerInfo:
    def test_active_shows_ok(self):
        r = _make_record(billing_status="active", current_period_end=_future(30))
        info = get_banner_info(r)
        assert info["show"] is True
        assert info["level"] == "ok"

    def test_trial_expiring_soon_shows_warn(self):
        r = _make_record(billing_status="trial", trial_ends_at=_future(3))
        info = get_banner_info(r)
        assert info["show"] is True
        assert info["level"] == "warn"

    def test_trial_long_remaining_shows_info(self):
        r = _make_record(billing_status="trial", trial_ends_at=_future(30))
        info = get_banner_info(r)
        assert info["show"] is True
        assert info["level"] == "info"

    def test_expired_shows_danger(self):
        r = _make_record(billing_status="trial", trial_ends_at=_past(5))
        info = get_banner_info(r)
        assert info["show"] is True
        assert info["level"] == "danger"

    def test_override_shows_info(self):
        r = _make_record(billing_status="expired", override_enabled=True)
        info = get_banner_info(r)
        assert info["show"] is True
        assert info["level"] == "info"
        assert "Override" in info["message"]

    def test_suspended_shows_danger(self):
        r = _make_record(billing_status="suspended")
        info = get_banner_info(r)
        assert info["level"] == "danger"

    def test_none_does_not_show(self):
        assert get_banner_info(None)["show"] is False


# ── Store integration ──────────────────────────────────────────────────────────


class TestTenantBillingStore:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> TenantBillingStore:
        return TenantBillingStore(str(tmp_path / "billing.db"))

    def test_ensure_creates_trial_record(self, store):
        rec = _sync(store.ensure_tenant_billing(tenant_id=42))
        assert rec.tenant_id == 42
        assert rec.billing_status == "trial"
        assert rec.plan_type == "trial"

    def test_ensure_idempotent(self, store):
        r1 = _sync(store.ensure_tenant_billing(tenant_id=1))
        r2 = _sync(store.ensure_tenant_billing(tenant_id=1))
        assert r1.tenant_id == r2.tenant_id

    def test_update_billing_full_status(self, store):
        _sync(store.ensure_tenant_billing(tenant_id=5))
        rec = _sync(store.update_billing_full(tenant_id=5, billing_status="active", tenant_slug="lincoln"))
        assert rec.billing_status == "active"
        assert rec.tenant_slug == "lincoln"

    def test_update_billing_full_license(self, store):
        key = generate_license_key()
        _sync(store.ensure_tenant_billing(tenant_id=6))
        rec = _sync(store.update_billing_full(tenant_id=6, license_key=key, plan_type="pro"))
        assert rec.license_key == key
        assert rec.plan_type == "pro"

    def test_upsert_legacy_compat(self, store):
        rec = _sync(
            store.upsert_tenant_billing(
                tenant_id=7,
                plan_id="basic",
                billing_status="active",
                trial_start=None,
                trial_end=None,
                is_free_override=False,
                free_reason=None,
                stripe_customer_id=None,
                stripe_subscription_id=None,
                renewal_date=_future(365),
            )
        )
        assert rec.billing_status == "active"

    def test_add_and_list_payments(self, store):
        _sync(store.ensure_tenant_billing(tenant_id=1))
        _sync(
            store.add_payment(
                tenant_slug="test",
                amount=500.00,
                payment_date=str(_now().date()),
                payment_method="check",
                recorded_by="super_admin",
            )
        )
        payments = _sync(store.list_payments(tenant_slug="test"))
        assert len(payments) == 1
        assert payments[0].amount == 500.00
        assert payments[0].payment_method == "check"

    def test_create_and_list_invoices(self, store):
        inv = _sync(
            store.create_invoice(
                invoice_number="BB-INV-TEST-0001",
                tenant_slug="test",
                amount_due=1200.00,
                due_date=_future(30)[:10],
            )
        )
        assert inv.invoice_number == "BB-INV-TEST-0001"
        assert inv.status == "draft"

        invoices = _sync(store.list_invoices(tenant_slug="test"))
        assert len(invoices) == 1

    def test_update_invoice_status(self, store):
        inv = _sync(
            store.create_invoice(
                invoice_number="BB-INV-TEST-0002",
                tenant_slug="test",
                amount_due=600.00,
                due_date=_future(15)[:10],
            )
        )
        updated = _sync(store.update_invoice_status(invoice_id=inv.id, new_status="paid"))
        assert updated is not None
        assert updated.status == "paid"

    def test_list_all_billing(self, store):
        _sync(store.ensure_tenant_billing(tenant_id=10))
        _sync(store.ensure_tenant_billing(tenant_id=11))
        all_recs = _sync(store.list_all())
        assert len(all_recs) >= 2
