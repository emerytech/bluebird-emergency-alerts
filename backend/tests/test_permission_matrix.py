"""
Phase 4 + 5 tests — Permission matrix and context-aware helpers.

Tests cover:
Phase 4 — Matrix correctness:
1.  Teacher/staff have standard user permissions
2.  Teacher/staff cannot manage users, approve quiet, access codes
3.  Law enforcement: alerts and reports only, no admin permissions
4.  Building admin has all expected granular permissions
5.  Building admin cannot manage district admins
6.  Building admin cannot edit settings (read-only)
7.  District admin has all building_admin permissions
8.  District admin can edit all settings categories
9.  District admin can manage district admins
10. Super admin granted everything via full_access
11. All legacy PERM_ constants still work correctly
12. super_admin is NOT a valid tenant role
13. Unknown role denied all permissions
14. All non-critical PERM_ constants have dot-notation values

Phase 5 — Context-aware helpers:
15. can_view_user: building_admin yes, teacher no
16. can_modify_user: building_admin can modify teacher, not district_admin
17. can_modify_user: district_admin can modify building_admin, not super_admin
18. can_delete_user: requires delete_archived permission + hierarchy
19. can_manage_access_code: building_admin yes, teacher no
20. can_review_quiet_request: building_admin yes, law_enforcement no
21. can_approve_quiet_request: blocks self-approval (same ID)
22. can_approve_quiet_request: allows cross-user approval for building_admin
23. can_approve_quiet_request: district_admin can approve across scope
24. can_edit_settings: district_admin yes for all categories
25. can_edit_settings: building_admin no for all edit categories
26. can_edit_settings: unknown category returns False
27. can_view_settings: building_admin yes, teacher no
28. assert_not_self_approval: raises on same user_id
29. assert_not_self_approval: passes on different user_ids
30. assert_not_last_district_admin: raises when count=1 and target is district_admin
31. assert_not_last_district_admin: passes when count=2
32. assert_not_last_district_admin: passes for non-district_admin target
33. PermissionDeniedError is importable and is an Exception subclass
"""
from __future__ import annotations

import pytest

from app.services.permissions import (
    # Roles
    ROLE_ADMIN,
    ROLE_BUILDING_ADMIN,
    ROLE_DISTRICT_ADMIN,
    ROLE_LAW_ENFORCEMENT,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN,
    ROLE_TEACHER,
    # Legacy permissions
    PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS,
    PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS,
    PERM_FULL_ACCESS,
    PERM_GENERATE_ACCESS_CODES,
    PERM_MANAGE_ASSIGNED_TENANT_INCIDENTS,
    PERM_MANAGE_ASSIGNED_TENANT_USERS,
    PERM_MANAGE_ASSIGNED_TENANTS,
    PERM_MANAGE_OWN_TENANT_USERS,
    PERM_REQUEST_HELP,
    PERM_SUBMIT_QUIET_REQUEST,
    PERM_TRIGGER_OWN_TENANT_ALERTS,
    # Phase 4 — User management
    PERM_USERS_VIEW,
    PERM_USERS_CREATE,
    PERM_USERS_EDIT,
    PERM_USERS_ARCHIVE,
    PERM_USERS_RESTORE,
    PERM_USERS_DELETE_ARCHIVED,
    PERM_USERS_MANAGE_DISTRICT_ADMIN,
    # Phase 4 — Access codes
    PERM_ACCESS_CODES_VIEW,
    PERM_ACCESS_CODES_CREATE,
    PERM_ACCESS_CODES_REVOKE,
    PERM_ACCESS_CODES_ARCHIVE,
    PERM_ACCESS_CODES_DELETE_ARCHIVED,
    PERM_ACCESS_CODES_BULK_GENERATE,
    PERM_ACCESS_CODES_PRINT_QR,
    # Phase 4 — Quiet periods
    PERM_QUIET_PERIODS_REQUEST,
    PERM_QUIET_PERIODS_REVIEW,
    PERM_QUIET_PERIODS_APPROVE,
    PERM_QUIET_PERIODS_DENY,
    PERM_QUIET_PERIODS_CANCEL_OWN,
    PERM_QUIET_PERIODS_CANCEL_ANY,
    PERM_QUIET_PERIODS_SCHEDULE,
    # Phase 4 — Alerts
    PERM_ALERTS_TRIGGER_SECURE_PERIMETER,
    PERM_ALERTS_TRIGGER_LOCKDOWN,
    PERM_ALERTS_DISABLE,
    PERM_ALERTS_VIEW_STATUS,
    PERM_ALERTS_VIEW_HISTORY,
    # Phase 4 — Devices
    PERM_DEVICES_VIEW,
    PERM_DEVICES_ARCHIVE,
    PERM_DEVICES_VIEW_STATUS,
    # Phase 4 — Reports
    PERM_REPORTS_VIEW_BUILDING,
    PERM_REPORTS_VIEW_DISTRICT,
    PERM_REPORTS_EXPORT,
    # Phase 4 — Settings
    PERM_SETTINGS_VIEW,
    PERM_SETTINGS_EDIT_NOTIFICATIONS,
    PERM_SETTINGS_EDIT_QUIET_PERIODS,
    PERM_SETTINGS_EDIT_ALERTS,
    PERM_SETTINGS_EDIT_ACCESS_CODES,
    PERM_SETTINGS_EDIT_DEVICES,
    # Core helpers
    can,
    can_any,
    valid_tenant_roles,
    # Phase 5 context-aware helpers
    PermissionDeniedError,
    assert_not_last_district_admin,
    assert_not_self_approval,
    can_approve_quiet_request,
    can_delete_user,
    can_edit_settings,
    can_manage_access_code,
    can_modify_user,
    can_review_quiet_request,
    can_view_settings,
    can_view_user,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has(role: str, perm: str) -> bool:
    return can(role, perm)

def _lacks(role: str, perm: str) -> bool:
    return not can(role, perm)


# ---------------------------------------------------------------------------
# Phase 4 — Matrix tests
# ---------------------------------------------------------------------------

class TestStandardUserPermissions:
    def test_teacher_has_quiet_request(self):
        assert _has(ROLE_TEACHER, PERM_QUIET_PERIODS_REQUEST)
        assert _has(ROLE_TEACHER, PERM_SUBMIT_QUIET_REQUEST)

    def test_teacher_has_cancel_own(self):
        assert _has(ROLE_TEACHER, PERM_QUIET_PERIODS_CANCEL_OWN)

    def test_teacher_has_schedule(self):
        assert _has(ROLE_TEACHER, PERM_QUIET_PERIODS_SCHEDULE)

    def test_teacher_has_alerts_view_status(self):
        assert _has(ROLE_TEACHER, PERM_ALERTS_VIEW_STATUS)

    def test_teacher_lacks_user_management(self):
        for perm in (PERM_USERS_VIEW, PERM_USERS_CREATE, PERM_USERS_EDIT,
                     PERM_MANAGE_OWN_TENANT_USERS):
            assert _lacks(ROLE_TEACHER, perm), f"teacher should not have {perm}"

    def test_teacher_lacks_quiet_approval(self):
        assert _lacks(ROLE_TEACHER, PERM_QUIET_PERIODS_APPROVE)
        assert _lacks(ROLE_TEACHER, PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS)

    def test_teacher_lacks_access_code_create(self):
        assert _lacks(ROLE_TEACHER, PERM_ACCESS_CODES_CREATE)
        assert _lacks(ROLE_TEACHER, PERM_GENERATE_ACCESS_CODES)

    def test_teacher_lacks_settings(self):
        assert _lacks(ROLE_TEACHER, PERM_SETTINGS_VIEW)

    def test_staff_mirrors_teacher(self):
        staff_perms = [
            PERM_QUIET_PERIODS_REQUEST, PERM_QUIET_PERIODS_CANCEL_OWN,
            PERM_ALERTS_VIEW_STATUS, PERM_REQUEST_HELP,
        ]
        for perm in staff_perms:
            assert _has(ROLE_STAFF, perm), f"staff should have {perm}"


class TestLawEnforcementPermissions:
    def test_has_view_status_and_history(self):
        assert _has(ROLE_LAW_ENFORCEMENT, PERM_ALERTS_VIEW_STATUS)
        assert _has(ROLE_LAW_ENFORCEMENT, PERM_ALERTS_VIEW_HISTORY)

    def test_has_building_report(self):
        assert _has(ROLE_LAW_ENFORCEMENT, PERM_REPORTS_VIEW_BUILDING)

    def test_has_device_view_status(self):
        assert _has(ROLE_LAW_ENFORCEMENT, PERM_DEVICES_VIEW_STATUS)

    def test_has_quiet_request_and_cancel_own(self):
        assert _has(ROLE_LAW_ENFORCEMENT, PERM_QUIET_PERIODS_REQUEST)
        assert _has(ROLE_LAW_ENFORCEMENT, PERM_QUIET_PERIODS_CANCEL_OWN)

    def test_lacks_user_management(self):
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_USERS_VIEW)
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_MANAGE_OWN_TENANT_USERS)

    def test_lacks_quiet_approval(self):
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_QUIET_PERIODS_APPROVE)
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS)

    def test_lacks_alert_trigger(self):
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_ALERTS_TRIGGER_LOCKDOWN)
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_TRIGGER_OWN_TENANT_ALERTS)

    def test_lacks_access_codes(self):
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_ACCESS_CODES_CREATE)
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_GENERATE_ACCESS_CODES)

    def test_lacks_settings(self):
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_SETTINGS_VIEW)
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_SETTINGS_EDIT_NOTIFICATIONS)

    def test_lacks_district_report_and_export(self):
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_REPORTS_VIEW_DISTRICT)
        assert _lacks(ROLE_LAW_ENFORCEMENT, PERM_REPORTS_EXPORT)


class TestBuildingAdminPermissions:
    def test_has_all_user_management_except_district(self):
        for perm in (PERM_USERS_VIEW, PERM_USERS_CREATE, PERM_USERS_EDIT,
                     PERM_USERS_ARCHIVE, PERM_USERS_RESTORE, PERM_USERS_DELETE_ARCHIVED):
            assert _has(ROLE_BUILDING_ADMIN, perm), f"building_admin should have {perm}"

    def test_lacks_manage_district_admin(self):
        assert _lacks(ROLE_BUILDING_ADMIN, PERM_USERS_MANAGE_DISTRICT_ADMIN)

    def test_has_all_access_code_permissions(self):
        for perm in (PERM_ACCESS_CODES_VIEW, PERM_ACCESS_CODES_CREATE,
                     PERM_ACCESS_CODES_REVOKE, PERM_ACCESS_CODES_ARCHIVE,
                     PERM_ACCESS_CODES_DELETE_ARCHIVED, PERM_ACCESS_CODES_BULK_GENERATE,
                     PERM_ACCESS_CODES_PRINT_QR):
            assert _has(ROLE_BUILDING_ADMIN, perm), f"building_admin should have {perm}"

    def test_has_all_quiet_period_permissions(self):
        for perm in (PERM_QUIET_PERIODS_REQUEST, PERM_QUIET_PERIODS_REVIEW,
                     PERM_QUIET_PERIODS_APPROVE, PERM_QUIET_PERIODS_DENY,
                     PERM_QUIET_PERIODS_CANCEL_OWN, PERM_QUIET_PERIODS_CANCEL_ANY,
                     PERM_QUIET_PERIODS_SCHEDULE):
            assert _has(ROLE_BUILDING_ADMIN, perm), f"building_admin should have {perm}"

    def test_has_all_alert_permissions(self):
        for perm in (PERM_ALERTS_TRIGGER_SECURE_PERIMETER, PERM_ALERTS_TRIGGER_LOCKDOWN,
                     PERM_ALERTS_DISABLE, PERM_ALERTS_VIEW_STATUS, PERM_ALERTS_VIEW_HISTORY):
            assert _has(ROLE_BUILDING_ADMIN, perm), f"building_admin should have {perm}"

    def test_has_device_and_report_permissions(self):
        assert _has(ROLE_BUILDING_ADMIN, PERM_DEVICES_VIEW)
        assert _has(ROLE_BUILDING_ADMIN, PERM_DEVICES_ARCHIVE)
        assert _has(ROLE_BUILDING_ADMIN, PERM_REPORTS_VIEW_BUILDING)
        assert _has(ROLE_BUILDING_ADMIN, PERM_SETTINGS_VIEW)

    def test_lacks_settings_edit_permissions(self):
        for perm in (PERM_SETTINGS_EDIT_NOTIFICATIONS, PERM_SETTINGS_EDIT_QUIET_PERIODS,
                     PERM_SETTINGS_EDIT_ALERTS, PERM_SETTINGS_EDIT_ACCESS_CODES,
                     PERM_SETTINGS_EDIT_DEVICES):
            assert _lacks(ROLE_BUILDING_ADMIN, perm), f"building_admin should NOT have {perm}"

    def test_lacks_district_report_and_export(self):
        assert _lacks(ROLE_BUILDING_ADMIN, PERM_REPORTS_VIEW_DISTRICT)
        assert _lacks(ROLE_BUILDING_ADMIN, PERM_REPORTS_EXPORT)

    def test_legacy_admin_alias_mirrors_building_admin(self):
        """Legacy 'admin' role must have same permissions as building_admin."""
        building_perms = [
            PERM_USERS_VIEW, PERM_ACCESS_CODES_CREATE, PERM_QUIET_PERIODS_APPROVE,
            PERM_ALERTS_DISABLE, PERM_SETTINGS_VIEW,
        ]
        for perm in building_perms:
            assert can(ROLE_ADMIN, perm) == can(ROLE_BUILDING_ADMIN, perm), \
                f"admin and building_admin should agree on {perm}"


class TestDistrictAdminPermissions:
    def test_inherits_all_building_admin_permissions(self):
        building_admin_perms = [
            PERM_USERS_VIEW, PERM_USERS_CREATE, PERM_USERS_EDIT, PERM_USERS_ARCHIVE,
            PERM_ACCESS_CODES_VIEW, PERM_ACCESS_CODES_CREATE, PERM_ACCESS_CODES_BULK_GENERATE,
            PERM_QUIET_PERIODS_REVIEW, PERM_QUIET_PERIODS_APPROVE, PERM_QUIET_PERIODS_DENY,
            PERM_ALERTS_TRIGGER_LOCKDOWN, PERM_ALERTS_DISABLE, PERM_ALERTS_VIEW_HISTORY,
            PERM_DEVICES_VIEW, PERM_REPORTS_VIEW_BUILDING, PERM_SETTINGS_VIEW,
        ]
        for perm in building_admin_perms:
            assert _has(ROLE_DISTRICT_ADMIN, perm), f"district_admin should inherit {perm}"

    def test_has_manage_district_admin(self):
        assert _has(ROLE_DISTRICT_ADMIN, PERM_USERS_MANAGE_DISTRICT_ADMIN)

    def test_has_district_reports_and_export(self):
        assert _has(ROLE_DISTRICT_ADMIN, PERM_REPORTS_VIEW_DISTRICT)
        assert _has(ROLE_DISTRICT_ADMIN, PERM_REPORTS_EXPORT)

    def test_has_all_settings_edit_permissions(self):
        for perm in (PERM_SETTINGS_EDIT_NOTIFICATIONS, PERM_SETTINGS_EDIT_QUIET_PERIODS,
                     PERM_SETTINGS_EDIT_ALERTS, PERM_SETTINGS_EDIT_ACCESS_CODES,
                     PERM_SETTINGS_EDIT_DEVICES):
            assert _has(ROLE_DISTRICT_ADMIN, perm), f"district_admin should have {perm}"

    def test_has_legacy_assigned_tenant_permissions(self):
        assert _has(ROLE_DISTRICT_ADMIN, PERM_MANAGE_ASSIGNED_TENANTS)
        assert _has(ROLE_DISTRICT_ADMIN, PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS)


class TestSuperAdminPermissions:
    def test_super_admin_granted_every_permission(self):
        all_new_perms = [
            PERM_USERS_VIEW, PERM_USERS_MANAGE_DISTRICT_ADMIN,
            PERM_ACCESS_CODES_CREATE, PERM_ACCESS_CODES_BULK_GENERATE,
            PERM_QUIET_PERIODS_APPROVE, PERM_QUIET_PERIODS_CANCEL_ANY,
            PERM_ALERTS_TRIGGER_LOCKDOWN, PERM_ALERTS_DISABLE,
            PERM_DEVICES_VIEW, PERM_DEVICES_ARCHIVE,
            PERM_REPORTS_VIEW_DISTRICT, PERM_REPORTS_EXPORT,
            PERM_SETTINGS_EDIT_NOTIFICATIONS, PERM_SETTINGS_EDIT_ALERTS,
        ]
        for perm in all_new_perms:
            assert _has(ROLE_SUPER_ADMIN, perm), f"super_admin should have {perm}"

    def test_super_admin_not_a_tenant_role(self):
        assert ROLE_SUPER_ADMIN not in valid_tenant_roles()

    def test_unknown_role_denied_all_permissions(self):
        for perm in (PERM_USERS_VIEW, PERM_QUIET_PERIODS_APPROVE, PERM_ALERTS_TRIGGER_LOCKDOWN,
                     PERM_SETTINGS_EDIT_NOTIFICATIONS, PERM_FULL_ACCESS):
            assert _lacks("unknown_role", perm)
            assert _lacks(None, perm)


class TestLegacyPermissionsUnchanged:
    """All previously-existing PERM_ constants must still work as before."""

    def test_legacy_perm_values_unchanged(self):
        assert PERM_REQUEST_HELP == "request_help"
        assert PERM_SUBMIT_QUIET_REQUEST == "submit_quiet_request"
        assert PERM_TRIGGER_OWN_TENANT_ALERTS == "trigger_own_tenant_alerts"
        assert PERM_GENERATE_ACCESS_CODES == "generate_access_codes"
        assert PERM_FULL_ACCESS == "full_access"
        assert PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS == "approve_own_tenant_quiet_requests"
        assert PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS == "approve_assigned_tenant_quiet_requests"

    def test_existing_teacher_legacy_perms(self):
        assert can(ROLE_TEACHER, PERM_REQUEST_HELP)
        assert can(ROLE_TEACHER, PERM_SUBMIT_QUIET_REQUEST)
        assert not can(ROLE_TEACHER, PERM_TRIGGER_OWN_TENANT_ALERTS)

    def test_existing_building_admin_legacy_perms(self):
        assert can(ROLE_BUILDING_ADMIN, PERM_MANAGE_OWN_TENANT_USERS)
        assert can(ROLE_BUILDING_ADMIN, PERM_TRIGGER_OWN_TENANT_ALERTS)
        assert can(ROLE_BUILDING_ADMIN, PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS)
        assert can(ROLE_BUILDING_ADMIN, PERM_GENERATE_ACCESS_CODES)

    def test_existing_district_admin_legacy_perms(self):
        assert can(ROLE_DISTRICT_ADMIN, PERM_MANAGE_ASSIGNED_TENANTS)
        assert can(ROLE_DISTRICT_ADMIN, PERM_MANAGE_ASSIGNED_TENANT_USERS)
        assert can(ROLE_DISTRICT_ADMIN, PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS)


class TestPermissionConstantNaming:
    """Phase 4 granular permissions use dot-notation values."""

    def test_user_perm_dot_notation(self):
        assert "." in PERM_USERS_VIEW
        assert PERM_USERS_VIEW.startswith("users.")

    def test_quiet_period_perm_dot_notation(self):
        assert PERM_QUIET_PERIODS_APPROVE.startswith("quiet_periods.")

    def test_settings_perm_dot_notation(self):
        assert PERM_SETTINGS_EDIT_NOTIFICATIONS.startswith("settings.")

    def test_alert_perm_dot_notation(self):
        assert PERM_ALERTS_TRIGGER_LOCKDOWN.startswith("alerts.")


# ---------------------------------------------------------------------------
# Phase 5 — Context-aware helper tests
# ---------------------------------------------------------------------------

class TestCanViewUser:
    def test_building_admin_can_view(self):
        assert can_view_user(ROLE_BUILDING_ADMIN) is True

    def test_district_admin_can_view(self):
        assert can_view_user(ROLE_DISTRICT_ADMIN) is True

    def test_teacher_cannot_view(self):
        assert can_view_user(ROLE_TEACHER) is False

    def test_law_enforcement_cannot_view(self):
        assert can_view_user(ROLE_LAW_ENFORCEMENT) is False


class TestCanModifyUser:
    def test_building_admin_can_modify_teacher(self):
        assert can_modify_user(ROLE_BUILDING_ADMIN, ROLE_TEACHER) is True

    def test_building_admin_can_modify_staff(self):
        assert can_modify_user(ROLE_BUILDING_ADMIN, ROLE_STAFF) is True

    def test_building_admin_cannot_modify_district_admin(self):
        assert can_modify_user(ROLE_BUILDING_ADMIN, ROLE_DISTRICT_ADMIN) is False

    def test_building_admin_cannot_modify_super_admin(self):
        assert can_modify_user(ROLE_BUILDING_ADMIN, ROLE_SUPER_ADMIN) is False

    def test_district_admin_can_modify_building_admin(self):
        assert can_modify_user(ROLE_DISTRICT_ADMIN, ROLE_BUILDING_ADMIN) is True

    def test_district_admin_cannot_modify_super_admin(self):
        assert can_modify_user(ROLE_DISTRICT_ADMIN, ROLE_SUPER_ADMIN) is False

    def test_teacher_cannot_modify_anyone(self):
        assert can_modify_user(ROLE_TEACHER, ROLE_TEACHER) is False
        assert can_modify_user(ROLE_TEACHER, ROLE_STAFF) is False


class TestCanDeleteUser:
    def test_building_admin_can_delete_teacher(self):
        assert can_delete_user(ROLE_BUILDING_ADMIN, ROLE_TEACHER) is True

    def test_building_admin_cannot_delete_district_admin(self):
        assert can_delete_user(ROLE_BUILDING_ADMIN, ROLE_DISTRICT_ADMIN) is False

    def test_district_admin_can_delete_building_admin(self):
        assert can_delete_user(ROLE_DISTRICT_ADMIN, ROLE_BUILDING_ADMIN) is True

    def test_teacher_cannot_delete(self):
        assert can_delete_user(ROLE_TEACHER, ROLE_TEACHER) is False


class TestCanManageAccessCode:
    def test_building_admin_can_manage(self):
        assert can_manage_access_code(ROLE_BUILDING_ADMIN) is True

    def test_district_admin_can_manage(self):
        assert can_manage_access_code(ROLE_DISTRICT_ADMIN) is True

    def test_teacher_cannot_manage(self):
        assert can_manage_access_code(ROLE_TEACHER) is False

    def test_law_enforcement_cannot_manage(self):
        assert can_manage_access_code(ROLE_LAW_ENFORCEMENT) is False


class TestCanReviewQuietRequest:
    def test_building_admin_can_review(self):
        assert can_review_quiet_request(ROLE_BUILDING_ADMIN) is True

    def test_district_admin_can_review(self):
        assert can_review_quiet_request(ROLE_DISTRICT_ADMIN) is True

    def test_teacher_cannot_review(self):
        assert can_review_quiet_request(ROLE_TEACHER) is False

    def test_law_enforcement_cannot_review(self):
        assert can_review_quiet_request(ROLE_LAW_ENFORCEMENT) is False


class TestCanApproveQuietRequest:
    def test_building_admin_can_approve_other_user(self):
        assert can_approve_quiet_request(
            ROLE_BUILDING_ADMIN, actor_user_id=10, requester_user_id=20
        ) is True

    def test_self_approval_blocked_for_building_admin(self):
        assert can_approve_quiet_request(
            ROLE_BUILDING_ADMIN, actor_user_id=10, requester_user_id=10
        ) is False

    def test_district_admin_can_approve_other(self):
        assert can_approve_quiet_request(
            ROLE_DISTRICT_ADMIN, actor_user_id=1, requester_user_id=2
        ) is True

    def test_self_approval_blocked_for_district_admin(self):
        assert can_approve_quiet_request(
            ROLE_DISTRICT_ADMIN, actor_user_id=5, requester_user_id=5
        ) is False

    def test_teacher_cannot_approve_anyone(self):
        assert can_approve_quiet_request(
            ROLE_TEACHER, actor_user_id=1, requester_user_id=2
        ) is False

    def test_law_enforcement_cannot_approve(self):
        assert can_approve_quiet_request(
            ROLE_LAW_ENFORCEMENT, actor_user_id=1, requester_user_id=2
        ) is False


class TestCanEditSettings:
    _all_categories = [
        "notifications", "quiet_periods", "alerts", "access_codes", "devices"
    ]

    def test_district_admin_can_edit_all_categories(self):
        for cat in self._all_categories:
            assert can_edit_settings(ROLE_DISTRICT_ADMIN, cat) is True, \
                f"district_admin should be able to edit {cat}"

    def test_building_admin_cannot_edit_any_category(self):
        for cat in self._all_categories:
            assert can_edit_settings(ROLE_BUILDING_ADMIN, cat) is False, \
                f"building_admin should NOT be able to edit {cat}"

    def test_teacher_cannot_edit_any_category(self):
        for cat in self._all_categories:
            assert can_edit_settings(ROLE_TEACHER, cat) is False

    def test_unknown_category_returns_false(self):
        assert can_edit_settings(ROLE_DISTRICT_ADMIN, "nonexistent_category") is False

    def test_super_admin_can_edit_all_categories(self):
        for cat in self._all_categories:
            assert can_edit_settings(ROLE_SUPER_ADMIN, cat) is True


class TestCanViewSettings:
    def test_building_admin_can_view(self):
        assert can_view_settings(ROLE_BUILDING_ADMIN) is True

    def test_district_admin_can_view(self):
        assert can_view_settings(ROLE_DISTRICT_ADMIN) is True

    def test_teacher_cannot_view(self):
        assert can_view_settings(ROLE_TEACHER) is False

    def test_law_enforcement_cannot_view(self):
        assert can_view_settings(ROLE_LAW_ENFORCEMENT) is False


class TestAssertNotSelfApproval:
    def test_raises_when_same_id(self):
        with pytest.raises(PermissionDeniedError):
            assert_not_self_approval(42, 42)

    def test_passes_when_different_ids(self):
        assert_not_self_approval(1, 2)  # should not raise

    def test_error_is_exception(self):
        assert issubclass(PermissionDeniedError, Exception)


class TestAssertNotLastDistrictAdmin:
    def test_raises_when_last_district_admin(self):
        with pytest.raises(PermissionDeniedError):
            assert_not_last_district_admin(ROLE_DISTRICT_ADMIN, district_admin_count=1)

    def test_passes_when_multiple_district_admins(self):
        assert_not_last_district_admin(ROLE_DISTRICT_ADMIN, district_admin_count=2)

    def test_passes_for_non_district_admin_role(self):
        assert_not_last_district_admin(ROLE_TEACHER, district_admin_count=1)
        assert_not_last_district_admin(ROLE_BUILDING_ADMIN, district_admin_count=1)

    def test_raises_with_count_zero(self):
        with pytest.raises(PermissionDeniedError):
            assert_not_last_district_admin(ROLE_DISTRICT_ADMIN, district_admin_count=0)

    def test_passes_with_count_three(self):
        assert_not_last_district_admin(ROLE_DISTRICT_ADMIN, district_admin_count=3)
