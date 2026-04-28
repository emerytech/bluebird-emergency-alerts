from __future__ import annotations

from dataclasses import dataclass
from typing import Final


ROLE_TEACHER: Final[str] = "teacher"
ROLE_LAW_ENFORCEMENT: Final[str] = "law_enforcement"
ROLE_STAFF: Final[str] = "staff"
ROLE_ADMIN: Final[str] = "admin"              # legacy alias — kept for backward compat
ROLE_BUILDING_ADMIN: Final[str] = "building_admin"
ROLE_DISTRICT_ADMIN: Final[str] = "district_admin"
ROLE_SUPER_ADMIN: Final[str] = "super_admin"

ALL_ROLES: Final[set[str]] = {
    ROLE_TEACHER,
    ROLE_LAW_ENFORCEMENT,
    ROLE_STAFF,
    ROLE_ADMIN,
    ROLE_BUILDING_ADMIN,
    ROLE_DISTRICT_ADMIN,
    ROLE_SUPER_ADMIN,
}

# Roles that may log in to the web admin dashboard
DASHBOARD_ROLES: Final[set[str]] = {
    ROLE_ADMIN,
    ROLE_BUILDING_ADMIN,
    ROLE_DISTRICT_ADMIN,
}

PERM_REQUEST_HELP: Final[str] = "request_help"
PERM_VIEW_OWN_TENANT_INCIDENTS: Final[str] = "view_own_tenant_incidents"
PERM_VIEW_ASSIGNED_TENANT_INCIDENTS: Final[str] = "view_assigned_tenant_incidents"
PERM_RECEIVE_ASSIGNED_TENANT_ALERTS: Final[str] = "receive_assigned_tenant_alerts"
PERM_SUBMIT_QUIET_REQUEST: Final[str] = "submit_quiet_request"
PERM_MANAGE_OWN_TENANT_USERS: Final[str] = "manage_own_tenant_users"
PERM_TRIGGER_OWN_TENANT_ALERTS: Final[str] = "trigger_own_tenant_alerts"
PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS: Final[str] = "approve_own_tenant_quiet_requests"
PERM_MANAGE_ASSIGNED_TENANTS: Final[str] = "manage_assigned_tenants"
PERM_MANAGE_ASSIGNED_TENANT_USERS: Final[str] = "manage_assigned_tenant_users"
PERM_MANAGE_ASSIGNED_TENANT_INCIDENTS: Final[str] = "manage_assigned_tenant_incidents"
PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS: Final[str] = "approve_assigned_tenant_quiet_requests"
PERM_GENERATE_ACCESS_CODES: Final[str] = "generate_access_codes"
PERM_FULL_ACCESS: Final[str] = "full_access"


ROLE_HIERARCHY: Final[dict[str, int]] = {
    ROLE_TEACHER: 1,
    ROLE_STAFF: 1,
    ROLE_LAW_ENFORCEMENT: 2,
    ROLE_ADMIN: 3,
    ROLE_BUILDING_ADMIN: 3,
    ROLE_DISTRICT_ADMIN: 4,
    ROLE_SUPER_ADMIN: 5,
}


_ROLE_PERMISSIONS: Final[dict[str, set[str]]] = {
    ROLE_TEACHER: {
        PERM_REQUEST_HELP,
        PERM_VIEW_OWN_TENANT_INCIDENTS,
        PERM_SUBMIT_QUIET_REQUEST,
    },
    ROLE_STAFF: {
        PERM_REQUEST_HELP,
        PERM_VIEW_OWN_TENANT_INCIDENTS,
        PERM_SUBMIT_QUIET_REQUEST,
    },
    ROLE_LAW_ENFORCEMENT: {
        PERM_REQUEST_HELP,
        PERM_SUBMIT_QUIET_REQUEST,
        PERM_VIEW_ASSIGNED_TENANT_INCIDENTS,
        PERM_RECEIVE_ASSIGNED_TENANT_ALERTS,
    },
    ROLE_ADMIN: {
        PERM_MANAGE_OWN_TENANT_USERS,
        PERM_TRIGGER_OWN_TENANT_ALERTS,
        PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS,
        PERM_SUBMIT_QUIET_REQUEST,
        PERM_GENERATE_ACCESS_CODES,
    },
    ROLE_BUILDING_ADMIN: {
        PERM_MANAGE_OWN_TENANT_USERS,
        PERM_TRIGGER_OWN_TENANT_ALERTS,
        PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS,
        PERM_SUBMIT_QUIET_REQUEST,
        PERM_GENERATE_ACCESS_CODES,
    },
    ROLE_DISTRICT_ADMIN: {
        PERM_MANAGE_ASSIGNED_TENANTS,
        PERM_MANAGE_ASSIGNED_TENANT_USERS,
        PERM_MANAGE_ASSIGNED_TENANT_INCIDENTS,
        PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS,
        PERM_GENERATE_ACCESS_CODES,
        # Keep district admin compatible with existing tenant-local admin routes.
        PERM_MANAGE_OWN_TENANT_USERS,
        PERM_TRIGGER_OWN_TENANT_ALERTS,
        PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS,
        PERM_SUBMIT_QUIET_REQUEST,
    },
    ROLE_SUPER_ADMIN: {
        PERM_FULL_ACCESS,
    },
}


def normalize_role(role: str | None) -> str:
    return str(role or "").strip().lower()


def is_known_role(role: str | None) -> bool:
    return normalize_role(role) in ALL_ROLES


def is_dashboard_role(role: str | None) -> bool:
    return normalize_role(role) in DASHBOARD_ROLES


def can(role: str | None, permission: str) -> bool:
    normalized_role = normalize_role(role)
    if normalized_role == ROLE_SUPER_ADMIN:
        return True
    if normalized_role not in _ROLE_PERMISSIONS:
        return False
    return permission in _ROLE_PERMISSIONS[normalized_role]


def can_any(role: str | None, permissions: set[str]) -> bool:
    return any(can(role, permission) for permission in permissions)


def valid_tenant_roles() -> set[str]:
    # Platform super admin is intentionally not created as a tenant-local user role.
    return {
        ROLE_TEACHER,
        ROLE_STAFF,
        ROLE_LAW_ENFORCEMENT,
        ROLE_ADMIN,
        ROLE_BUILDING_ADMIN,
        ROLE_DISTRICT_ADMIN,
    }


# Roles that a district_admin may create via access code.
# Never includes district_admin or super_admin.
CODEGEN_ALLOWED_ROLES: Final[set[str]] = {
    ROLE_BUILDING_ADMIN,
    ROLE_TEACHER,
    ROLE_STAFF,
    ROLE_LAW_ENFORCEMENT,
}


# Roles permitted to trigger a school-wide emergency alarm.
# Intentionally excludes teacher, staff, and law_enforcement — those roles
# can send help requests (team-assist) but not activate the full alarm.
ALARM_TRIGGER_ROLES: Final[set[str]] = {
    ROLE_ADMIN,           # legacy alias for building_admin
    ROLE_BUILDING_ADMIN,
    ROLE_DISTRICT_ADMIN,
}


def can_trigger_alarm(role: str | None) -> bool:
    return normalize_role(role) in ALARM_TRIGGER_ROLES


def can_deactivate_alarm(role: str | None) -> bool:
    return can_any(role, {PERM_TRIGGER_OWN_TENANT_ALERTS, PERM_MANAGE_ASSIGNED_TENANT_INCIDENTS})


def can_manage_users(role: str | None) -> bool:
    return can_any(role, {PERM_MANAGE_OWN_TENANT_USERS, PERM_MANAGE_ASSIGNED_TENANT_USERS, PERM_FULL_ACCESS})


def can_generate_codes(role: str | None) -> bool:
    return can_any(role, {PERM_GENERATE_ACCESS_CODES, PERM_FULL_ACCESS})


def can_view_reports(role: str | None) -> bool:
    return is_dashboard_role(role) or normalize_role(role) == ROLE_SUPER_ADMIN


def can_archive_user(actor_role: str | None, target_role: str | None) -> bool:
    """Return True if actor_role is permitted to archive/restore/delete a user with target_role.

    Rules (from spec):
    - super_admin and district_admin can archive/restore/delete anyone.
    - building_admin (and legacy admin) can archive/restore/delete staff-level users
      but NOT district_admin users.
    - Anyone below building_admin cannot archive users.
    """
    actor = normalize_role(actor_role)
    target = normalize_role(target_role)
    if actor in {ROLE_SUPER_ADMIN, ROLE_DISTRICT_ADMIN}:
        return True
    if actor in {ROLE_ADMIN, ROLE_BUILDING_ADMIN}:
        return target not in {ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN}
    return False


def role_display_label(role: str | None) -> str:
    """Human-readable label for a role value."""
    _labels: dict[str, str] = {
        ROLE_TEACHER: "Teacher",
        ROLE_STAFF: "Staff",
        ROLE_LAW_ENFORCEMENT: "Law Enforcement",
        ROLE_ADMIN: "Building Admin",        # legacy alias displays as Building Admin
        ROLE_BUILDING_ADMIN: "Building Admin",
        ROLE_DISTRICT_ADMIN: "District Admin",
        ROLE_SUPER_ADMIN: "Super Admin",
    }
    return _labels.get(normalize_role(role), str(role or "").capitalize())


@dataclass(frozen=True)
class PermissionCheck:
    role: str
    permission: str
    allowed: bool
