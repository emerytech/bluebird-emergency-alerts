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


def has_tenant_access(
    tenant_billing: Optional[TenantBillingRecord],
    *,
    now: Optional[datetime] = None,
) -> bool:
    """
    Returns True when the tenant has any valid access (platform-level gate).
    Emergency alerts use a separate path that never consults billing — this
    function is for admin/management access, not for push or alert delivery.

    Statuses that grant access:
      - active
      - manual_override (or legacy is_free_override)
      - trial — only while trial period has not expired
      - past_due — still accessible; management will be restricted separately
    """
    if tenant_billing is None:
        return False

    if bool(tenant_billing.override_enabled) or bool(tenant_billing.is_free_override):
        return True

    status = str(tenant_billing.billing_status or "").strip().lower()

    if status == "active":
        return True

    if status == "past_due":
        return True

    if status == "manual_override":
        return True

    if status == "trial":
        check_now = (
            now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
        )
        trial_end = _parse_iso8601(
            tenant_billing.trial_ends_at or tenant_billing.trial_end
        )
        if trial_end is None:
            return False
        return check_now < trial_end

    # expired | suspended | cancelled — deny
    return False


# Keep camelCase alias for backward compatibility
def hasTenantAccess(
    tenantBilling: Optional[TenantBillingRecord],
    *,
    now: Optional[datetime] = None,
) -> bool:
    return has_tenant_access(tenantBilling, now=now)
