from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.billing_access import has_tenant_access
from app.services.tenant_billing_store import TenantBillingRecord


def _record(
    *,
    billing_status: str,
    is_free_override: bool = False,
    trial_end: str | None = None,
) -> TenantBillingRecord:
    now = datetime.now(timezone.utc).isoformat()
    return TenantBillingRecord(
        tenant_id=1,
        plan_id="starter",
        billing_status=billing_status,
        trial_start=None,
        trial_end=trial_end,
        is_free_override=is_free_override,
        free_reason="manual override" if is_free_override else None,
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_123",
        renewal_date=None,
        updated_at=now,
    )


def test_active_access_allowed() -> None:
    record = _record(billing_status="active")
    assert has_tenant_access(record)


def test_valid_trial_access_allowed() -> None:
    trial_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    record = _record(billing_status="trial", trial_end=trial_end)
    assert has_tenant_access(record)


def test_expired_trial_access_denied() -> None:
    trial_end = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    record = _record(billing_status="trial", trial_end=trial_end)
    assert not has_tenant_access(record)


def test_free_override_always_allowed() -> None:
    trial_end = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    record = _record(
        billing_status="canceled",
        is_free_override=True,
        trial_end=trial_end,
    )
    assert has_tenant_access(record)

