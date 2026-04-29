"""
Billing service: license generation, status resolution, soft enforcement.

Emergency alert endpoints must NEVER call require_management_license().
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from app.services.tenant_billing_store import TenantBillingRecord, TenantBillingStore

# Days past_due is allowed before management is fully restricted
_GRACE_PERIOD_DAYS = 7

_LICENSE_ALPHABET = string.ascii_uppercase + string.digits

VALID_PLAN_TYPES = frozenset({"trial", "basic", "pro", "enterprise"})
VALID_BILLING_STATUSES = frozenset(
    {"trial", "active", "past_due", "expired", "suspended", "cancelled", "manual_override"}
)


# ── License generation ─────────────────────────────────────────────────────────


def generate_license_key() -> str:
    """Return a new BB-XXXX-XXXX-XXXX-XXXX license key (alphanumeric, uppercase)."""
    groups = ["".join(secrets.choice(_LICENSE_ALPHABET) for _ in range(4)) for _ in range(4)]
    return "BB-" + "-".join(groups)


# ── Date helpers ───────────────────────────────────────────────────────────────


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except Exception:
        return None


def get_days_remaining(
    billing: Optional[TenantBillingRecord],
    *,
    now: Optional[datetime] = None,
) -> Optional[int]:
    """
    Days until the billing period / trial ends.
    Returns negative for expired. None if no expiry date is set.
    """
    if billing is None:
        return None
    check_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    end_str = (
        billing.current_period_end
        or billing.trial_ends_at
        or billing.trial_end
        or billing.renewal_date
    )
    dt = _parse_iso(end_str)
    if dt is None:
        return None
    return (dt - check_now).days


# ── Status resolution ──────────────────────────────────────────────────────────


def get_effective_status(
    billing: Optional[TenantBillingRecord],
    *,
    now: Optional[datetime] = None,
) -> str:
    """
    Resolve the actual billing status, accounting for override and trial expiry.
    Always returns one of the VALID_BILLING_STATUSES values.
    """
    if billing is None:
        return "trial"

    if billing.override_enabled or billing.is_free_override:
        return "manual_override"

    status = str(billing.billing_status or "trial").strip().lower()

    if status == "trial":
        days = get_days_remaining(billing, now=now)
        if days is not None and days < 0:
            return "expired"

    return status if status in VALID_BILLING_STATUSES else "trial"


# ── Enforcement ────────────────────────────────────────────────────────────────


def is_management_allowed(
    billing: Optional[TenantBillingRecord],
    *,
    now: Optional[datetime] = None,
) -> bool:
    """
    Returns True when full management features are permitted.
    Emergency alert endpoints are EXEMPT — do not call this for them.
    """
    effective = get_effective_status(billing, now=now)

    if effective in {"active", "manual_override"}:
        return True

    if effective == "trial":
        days = get_days_remaining(billing, now=now)
        return days is None or days >= 0

    if effective == "past_due":
        days = get_days_remaining(billing, now=now)
        return days is None or days >= -_GRACE_PERIOD_DAYS

    return False


class ManagementLicenseError(Exception):
    """Raised when a management feature is blocked by license/billing status."""

    def __init__(self, feature_name: str, effective_status: str) -> None:
        self.feature_name = feature_name
        self.effective_status = effective_status
        super().__init__(
            f"Feature '{feature_name}' requires an active license "
            f"(current status: {effective_status})"
        )


def require_management_license(
    billing: Optional[TenantBillingRecord],
    feature_name: str,
    *,
    now: Optional[datetime] = None,
) -> None:
    """
    Raise ManagementLicenseError if the tenant's license does not allow management.

    IMPORTANT: Must NOT be called from emergency alert, push, or device endpoints.
    """
    if not is_management_allowed(billing, now=now):
        raise ManagementLicenseError(
            feature_name=feature_name,
            effective_status=get_effective_status(billing, now=now),
        )


# ── Banner ─────────────────────────────────────────────────────────────────────


def get_banner_info(
    billing: Optional[TenantBillingRecord],
    *,
    now: Optional[datetime] = None,
) -> dict:
    """
    Returns a dict describing the billing status banner for the admin console.

    Keys: show (bool), level (ok|info|warn|danger), message (str), css_class (str)
    """
    if billing is None:
        return {"show": False}

    effective = get_effective_status(billing, now=now)
    days = get_days_remaining(billing, now=now)

    if effective == "manual_override":
        return {
            "show": True,
            "level": "info",
            "message": "License: Active — Platform Override",
            "css_class": "billing-banner-info",
        }

    if effective == "active":
        end_str = billing.current_period_end or billing.renewal_date or ""
        date_part = f" — renews {end_str[:10]}" if end_str else ""
        return {
            "show": True,
            "level": "ok",
            "message": f"License: Active{date_part}",
            "css_class": "billing-banner-ok",
        }

    if effective == "trial":
        if days is not None:
            urgency = "warn" if days <= 7 else "info"
            label = f"{days} day{'s' if days != 1 else ''}"
            return {
                "show": True,
                "level": urgency,
                "message": f"Trial — expires in {label}",
                "css_class": f"billing-banner-{urgency}",
            }
        return {"show": True, "level": "info", "message": "Trial", "css_class": "billing-banner-info"}

    if effective == "past_due":
        return {
            "show": True,
            "level": "warn",
            "message": "Payment past due — management features will be restricted soon",
            "css_class": "billing-banner-warn",
        }

    if effective in {"expired", "cancelled"}:
        return {
            "show": True,
            "level": "danger",
            "message": "License expired — management restricted. Contact support to renew.",
            "css_class": "billing-banner-danger",
        }

    if effective == "suspended":
        return {
            "show": True,
            "level": "danger",
            "message": "Account suspended — contact support.",
            "css_class": "billing-banner-danger",
        }

    return {"show": False}


# ── District-aware billing resolution ─────────────────────────────────────────


async def get_effective_billing_for_tenant(
    billing_store: TenantBillingStore,
    *,
    tenant_id: int,
    district_id: Optional[int],
) -> TenantBillingRecord:
    """
    Return the billing record that governs enforcement for a tenant.

    Resolution order:
      1. If the tenant belongs to a district AND the district has a billing
         record, use the district record (district license covers all schools).
      2. Otherwise fall back to the tenant's own billing record.

    The returned record always has the correct billing fields for enforcement.
    Emergency alert endpoints MUST NOT call this — they bypass billing entirely.
    """
    if district_id is not None:
        district_billing = await billing_store.get_district_billing(district_id=int(district_id))
        if district_billing is not None:
            return district_billing
    return await billing_store.ensure_tenant_billing(tenant_id=int(tenant_id))


# ── Invoice number generation ──────────────────────────────────────────────────


def generate_invoice_number(*, tenant_slug: str, sequence: int) -> str:
    """BB-INV-{SLUG[:6].upper()}-{SEQUENCE:04d}"""
    slug_part = str(tenant_slug)[:6].upper().replace("-", "")
    return f"BB-INV-{slug_part}-{int(sequence):04d}"
