from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Legacy permission constants (preserved — used throughout routes.py)
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Phase 4 — Granular permission constants
# ---------------------------------------------------------------------------

# User management
PERM_USERS_VIEW: Final[str] = "users.view"
PERM_USERS_CREATE: Final[str] = "users.create"
PERM_USERS_EDIT: Final[str] = "users.edit"
PERM_USERS_ARCHIVE: Final[str] = "users.archive"
PERM_USERS_RESTORE: Final[str] = "users.restore"
PERM_USERS_DELETE_ARCHIVED: Final[str] = "users.delete_archived"
PERM_USERS_MANAGE_DISTRICT_ADMIN: Final[str] = "users.manage_district_admin"

# Access codes
PERM_ACCESS_CODES_VIEW: Final[str] = "access_codes.view"
PERM_ACCESS_CODES_CREATE: Final[str] = "access_codes.create"
PERM_ACCESS_CODES_REVOKE: Final[str] = "access_codes.revoke"
PERM_ACCESS_CODES_ARCHIVE: Final[str] = "access_codes.archive"
PERM_ACCESS_CODES_DELETE_ARCHIVED: Final[str] = "access_codes.delete_archived"
PERM_ACCESS_CODES_BULK_GENERATE: Final[str] = "access_codes.bulk_generate"
PERM_ACCESS_CODES_PRINT_QR: Final[str] = "access_codes.print_qr"

# Quiet periods
PERM_QUIET_PERIODS_REQUEST: Final[str] = "quiet_periods.request"
PERM_QUIET_PERIODS_REVIEW: Final[str] = "quiet_periods.review"
PERM_QUIET_PERIODS_APPROVE: Final[str] = "quiet_periods.approve"
PERM_QUIET_PERIODS_DENY: Final[str] = "quiet_periods.deny"
PERM_QUIET_PERIODS_CANCEL_OWN: Final[str] = "quiet_periods.cancel_own"
PERM_QUIET_PERIODS_CANCEL_ANY: Final[str] = "quiet_periods.cancel_any"
PERM_QUIET_PERIODS_SCHEDULE: Final[str] = "quiet_periods.schedule"

# Alerts
PERM_ALERTS_TRIGGER_SECURE_PERIMETER: Final[str] = "alerts.trigger_secure_perimeter"
PERM_ALERTS_TRIGGER_LOCKDOWN: Final[str] = "alerts.trigger_lockdown"
PERM_ALERTS_DISABLE: Final[str] = "alerts.disable"
PERM_ALERTS_VIEW_STATUS: Final[str] = "alerts.view_status"
PERM_ALERTS_VIEW_HISTORY: Final[str] = "alerts.view_history"

# Devices
PERM_DEVICES_VIEW: Final[str] = "devices.view"
PERM_DEVICES_ARCHIVE: Final[str] = "devices.archive"
PERM_DEVICES_VIEW_STATUS: Final[str] = "devices.view_status"

# Reports
PERM_REPORTS_VIEW_BUILDING: Final[str] = "reports.view_building"
PERM_REPORTS_VIEW_DISTRICT: Final[str] = "reports.view_district"
PERM_REPORTS_EXPORT: Final[str] = "reports.export"

# Roster
PERM_ROSTER_VIEW: Final[str] = "roster.view"          # any authenticated user during active alert
PERM_ROSTER_CLAIM: Final[str] = "roster.claim"        # claim / update student status
PERM_ROSTER_MANAGE: Final[str] = "roster.manage"      # master student list CRUD + CSV import

# Settings
PERM_SETTINGS_VIEW: Final[str] = "settings.view"
PERM_SETTINGS_EDIT_NOTIFICATIONS: Final[str] = "settings.edit_notification_settings"
PERM_SETTINGS_EDIT_QUIET_PERIODS: Final[str] = "settings.edit_quiet_period_settings"
PERM_SETTINGS_EDIT_ALERTS: Final[str] = "settings.edit_alert_settings"
PERM_SETTINGS_EDIT_ACCESS_CODES: Final[str] = "settings.edit_access_code_settings"
PERM_SETTINGS_EDIT_DEVICES: Final[str] = "settings.edit_device_settings"


# ---------------------------------------------------------------------------
# Role hierarchy (numeric levels for comparison)
# ---------------------------------------------------------------------------

ROLE_HIERARCHY: Final[dict[str, int]] = {
    ROLE_TEACHER: 1,
    ROLE_STAFF: 1,
    ROLE_LAW_ENFORCEMENT: 2,
    ROLE_ADMIN: 3,
    ROLE_BUILDING_ADMIN: 3,
    ROLE_DISTRICT_ADMIN: 4,
    ROLE_SUPER_ADMIN: 5,
}


# ---------------------------------------------------------------------------
# Permission matrix
# ---------------------------------------------------------------------------

# Permissions shared by teacher and staff
_STANDARD_USER_PERMS: Final[set[str]] = {
    PERM_REQUEST_HELP,
    PERM_VIEW_OWN_TENANT_INCIDENTS,
    PERM_SUBMIT_QUIET_REQUEST,
    # Phase 4 granular
    PERM_QUIET_PERIODS_REQUEST,
    PERM_QUIET_PERIODS_CANCEL_OWN,
    PERM_QUIET_PERIODS_SCHEDULE,
    PERM_ALERTS_VIEW_STATUS,
    # Roster
    PERM_ROSTER_VIEW,
    PERM_ROSTER_CLAIM,
}

# Permissions shared by building_admin and legacy admin alias
_BUILDING_ADMIN_PERMS: Final[set[str]] = {
    # Legacy — kept so existing route checks continue to work
    PERM_MANAGE_OWN_TENANT_USERS,
    PERM_TRIGGER_OWN_TENANT_ALERTS,
    PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS,
    PERM_SUBMIT_QUIET_REQUEST,
    PERM_GENERATE_ACCESS_CODES,
    # Phase 4 — user management
    PERM_USERS_VIEW,
    PERM_USERS_CREATE,
    PERM_USERS_EDIT,
    PERM_USERS_ARCHIVE,
    PERM_USERS_RESTORE,
    PERM_USERS_DELETE_ARCHIVED,
    # Phase 4 — access codes
    PERM_ACCESS_CODES_VIEW,
    PERM_ACCESS_CODES_CREATE,
    PERM_ACCESS_CODES_REVOKE,
    PERM_ACCESS_CODES_ARCHIVE,
    PERM_ACCESS_CODES_DELETE_ARCHIVED,
    PERM_ACCESS_CODES_BULK_GENERATE,
    PERM_ACCESS_CODES_PRINT_QR,
    # Phase 4 — quiet periods
    PERM_QUIET_PERIODS_REQUEST,
    PERM_QUIET_PERIODS_REVIEW,
    PERM_QUIET_PERIODS_APPROVE,
    PERM_QUIET_PERIODS_DENY,
    PERM_QUIET_PERIODS_CANCEL_OWN,
    PERM_QUIET_PERIODS_CANCEL_ANY,
    PERM_QUIET_PERIODS_SCHEDULE,
    # Phase 4 — alerts
    PERM_ALERTS_TRIGGER_SECURE_PERIMETER,
    PERM_ALERTS_TRIGGER_LOCKDOWN,
    PERM_ALERTS_DISABLE,
    PERM_ALERTS_VIEW_STATUS,
    PERM_ALERTS_VIEW_HISTORY,
    # Phase 4 — devices
    PERM_DEVICES_VIEW,
    PERM_DEVICES_ARCHIVE,
    PERM_DEVICES_VIEW_STATUS,
    # Phase 4 — reports
    PERM_REPORTS_VIEW_BUILDING,
    # Phase 4 — settings (read-only for building admin)
    PERM_SETTINGS_VIEW,
    # Roster
    PERM_ROSTER_VIEW,
    PERM_ROSTER_CLAIM,
    PERM_ROSTER_MANAGE,
}

_ROLE_PERMISSIONS: Final[dict[str, set[str]]] = {
    ROLE_TEACHER: _STANDARD_USER_PERMS,
    ROLE_STAFF: _STANDARD_USER_PERMS,
    ROLE_LAW_ENFORCEMENT: {
        PERM_REQUEST_HELP,
        PERM_SUBMIT_QUIET_REQUEST,
        PERM_VIEW_ASSIGNED_TENANT_INCIDENTS,
        PERM_RECEIVE_ASSIGNED_TENANT_ALERTS,
        # Phase 4
        PERM_QUIET_PERIODS_REQUEST,
        PERM_QUIET_PERIODS_CANCEL_OWN,
        PERM_ALERTS_VIEW_STATUS,
        PERM_ALERTS_VIEW_HISTORY,
        PERM_REPORTS_VIEW_BUILDING,
        PERM_DEVICES_VIEW_STATUS,
    },
    ROLE_ADMIN: _BUILDING_ADMIN_PERMS,           # legacy alias
    ROLE_BUILDING_ADMIN: _BUILDING_ADMIN_PERMS,
    ROLE_DISTRICT_ADMIN: _BUILDING_ADMIN_PERMS | {
        # Legacy — kept for backward compat with existing tenant-local routes
        PERM_MANAGE_ASSIGNED_TENANTS,
        PERM_MANAGE_ASSIGNED_TENANT_USERS,
        PERM_MANAGE_ASSIGNED_TENANT_INCIDENTS,
        PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS,
        PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS,
        # Phase 4 — district-only
        PERM_USERS_MANAGE_DISTRICT_ADMIN,
        PERM_REPORTS_VIEW_DISTRICT,
        PERM_REPORTS_EXPORT,
        PERM_SETTINGS_EDIT_NOTIFICATIONS,
        PERM_SETTINGS_EDIT_QUIET_PERIODS,
        PERM_SETTINGS_EDIT_ALERTS,
        PERM_SETTINGS_EDIT_ACCESS_CODES,
        PERM_SETTINGS_EDIT_DEVICES,
    },
    ROLE_SUPER_ADMIN: {
        PERM_FULL_ACCESS,
    },
}


# ---------------------------------------------------------------------------
# Core permission predicates (stable API — do not change signatures)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Static role sets used for alarm / access-code / report guards
# ---------------------------------------------------------------------------

# Roles permitted to trigger a school-wide emergency alarm.
# Any authenticated, active tenant user may activate — teachers and staff
# are on the front line and must not be blocked from calling for help.
ALARM_TRIGGER_ROLES: Final[set[str]] = ALL_ROLES

CODEGEN_ALLOWED_ROLES: Final[set[str]] = {
    ROLE_BUILDING_ADMIN,
    ROLE_TEACHER,
    ROLE_STAFF,
    ROLE_LAW_ENFORCEMENT,
}


# ---------------------------------------------------------------------------
# Legacy convenience helpers (preserved — used throughout routes.py)
# ---------------------------------------------------------------------------

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

    Rules:
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
        ROLE_ADMIN: "Building Admin",
        ROLE_BUILDING_ADMIN: "Building Admin",
        ROLE_DISTRICT_ADMIN: "District Admin",
        ROLE_SUPER_ADMIN: "Super Admin",
    }
    return _labels.get(normalize_role(role), str(role or "").capitalize())


# ---------------------------------------------------------------------------
# Phase 5 — Context-aware permission helpers
# ---------------------------------------------------------------------------

class PermissionDeniedError(Exception):
    """Raised by assert_* helpers when a permission rule is violated."""


def can_view_user(actor_role: str | None) -> bool:
    """Any dashboard admin can view users in their scope."""
    return can(actor_role, PERM_USERS_VIEW)


def can_modify_user(actor_role: str | None, target_role: str | None) -> bool:
    """
    Actor can edit target if they have users.edit AND target is strictly
    below them in the hierarchy.

    Building admin cannot edit district admin or super admin.
    District admin cannot edit super admin.
    """
    if not can(actor_role, PERM_USERS_EDIT):
        return False
    actor_level = ROLE_HIERARCHY.get(normalize_role(actor_role), 0)
    target_level = ROLE_HIERARCHY.get(normalize_role(target_role), 0)
    return actor_level > target_level


def can_delete_user(actor_role: str | None, target_role: str | None) -> bool:
    """
    Stricter than archive — requires both users.delete_archived permission
    and the same hierarchy constraint as archive.
    """
    return can(actor_role, PERM_USERS_DELETE_ARCHIVED) and can_archive_user(actor_role, target_role)


def can_manage_access_code(actor_role: str | None) -> bool:
    """Actor can create/revoke access codes."""
    return can_any(actor_role, {PERM_ACCESS_CODES_CREATE, PERM_GENERATE_ACCESS_CODES})


def can_review_quiet_request(actor_role: str | None) -> bool:
    """Actor can see the queue of pending quiet period requests."""
    return can_any(actor_role, {
        PERM_QUIET_PERIODS_REVIEW,
        PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS,
        PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS,
    })


def can_approve_quiet_request(
    actor_role: str | None,
    *,
    actor_user_id: int,
    requester_user_id: int,
) -> bool:
    """
    Actor can approve/deny a quiet period request if:
    1. They have an approval permission, AND
    2. They are not the requester (no self-approval).
    """
    if actor_user_id == requester_user_id:
        return False
    return can_any(actor_role, {
        PERM_QUIET_PERIODS_APPROVE,
        PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS,
        PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS,
    })


# Mapping from settings category name → required edit permission
_SETTINGS_CATEGORY_PERM: Final[dict[str, str]] = {
    "notifications": PERM_SETTINGS_EDIT_NOTIFICATIONS,
    "quiet_periods": PERM_SETTINGS_EDIT_QUIET_PERIODS,
    "alerts": PERM_SETTINGS_EDIT_ALERTS,
    "access_codes": PERM_SETTINGS_EDIT_ACCESS_CODES,
    "devices": PERM_SETTINGS_EDIT_DEVICES,
}

# ---------------------------------------------------------------------------
# District-level settings definitions
# ---------------------------------------------------------------------------

# Settings categories completely invisible to building_admin in the UI and
# filtered from GET /admin/settings/effective responses.
DISTRICT_ONLY_SETTINGS_CATEGORIES: Final[frozenset[str]] = frozenset({
    "alerts",
    "ai_insights",
})

# Within mixed-access categories, fields that only district_admin+ may see.
DISTRICT_ONLY_SETTINGS_FIELDS: Final[dict[str, frozenset[str]]] = {
    "quiet_periods": frozenset({
        "district_admin_can_approve_all",
        "building_admin_scope",
        "allow_self_approval",
    }),
}


def is_district_admin_or_higher(role: str | None) -> bool:
    """Return True if role grants district-level settings access."""
    return normalize_role(role) in {ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN}


def filter_settings_for_role(settings: dict, role: str) -> dict:
    """
    Remove district-only settings from a serialized settings dict for
    building_admin and below.  district_admin and super_admin receive
    the full dict unmodified.
    """
    if is_district_admin_or_higher(role):
        return settings
    result: dict = {}
    for cat, val in settings.items():
        if cat in DISTRICT_ONLY_SETTINGS_CATEGORIES:
            continue
        if cat in DISTRICT_ONLY_SETTINGS_FIELDS and isinstance(val, dict):
            restricted = DISTRICT_ONLY_SETTINGS_FIELDS[cat]
            result[cat] = {k: v for k, v in val.items() if k not in restricted}
        else:
            result[cat] = val
    return result


def can_edit_settings(actor_role: str | None, category: str) -> bool:
    """Return True if actor_role may edit the given settings category."""
    perm = _SETTINGS_CATEGORY_PERM.get(category)
    if perm is None:
        return False
    return can(actor_role, perm)


def can_view_settings(actor_role: str | None) -> bool:
    return can(actor_role, PERM_SETTINGS_VIEW)


def assert_not_self_approval(actor_user_id: int, requester_user_id: int) -> None:
    """Raise PermissionDeniedError if actor and requester are the same user."""
    if actor_user_id == requester_user_id:
        raise PermissionDeniedError("Cannot approve or deny your own request")


def assert_not_last_district_admin(
    target_role: str | None,
    district_admin_count: int,
) -> None:
    """
    Raise PermissionDeniedError if archiving/deleting target would leave the
    tenant with zero district admins.
    """
    if (
        normalize_role(target_role) == ROLE_DISTRICT_ADMIN
        and district_admin_count <= 1
    ):
        raise PermissionDeniedError(
            "Cannot remove the last district admin — at least one must remain active"
        )


# ---------------------------------------------------------------------------
# Dataclass kept for backward compat (used in some test/audit code)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PermissionCheck:
    role: str
    permission: str
    allowed: bool
