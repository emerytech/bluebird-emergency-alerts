from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.services.tenant_billing_store import TenantBillingRecord


def _parse_iso8601(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def has_tenant_access(tenant_billing: Optional[TenantBillingRecord], *, now: Optional[datetime] = None) -> bool:
    if tenant_billing is None:
        return False
    if bool(tenant_billing.is_free_override):
        return True

    status = str(tenant_billing.billing_status or "").strip().lower()
    if status == "active":
        return True
    if status != "trial":
        return False

    check_now = now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
    trial_end = _parse_iso8601(tenant_billing.trial_end)
    if trial_end is None:
        return False
    return check_now < trial_end


# Keep camelCase alias to match product requirement wording while maintaining Pythonic API.
def hasTenantAccess(tenantBilling: Optional[TenantBillingRecord], *, now: Optional[datetime] = None) -> bool:
    return has_tenant_access(tenantBilling, now=now)

