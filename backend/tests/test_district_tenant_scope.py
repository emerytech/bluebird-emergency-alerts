"""
Phase 7 validation tests for district-level multi-building tenant scope resolution.

Tests verify that _resolve_admin_tenant_scope():
  - Automatically grants district_admin access to all buildings sharing a district_id
  - Is additive with explicit user_tenants assignments (union, not replace)
  - Does NOT expand access for non-district-admin roles
  - Does not call list_schools_by_district when district_id is None
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes import _resolve_admin_tenant_scope  # type: ignore[attr-defined]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_school(*, id: int, slug: str, name: str, district_id: Optional[int] = None):
    s = MagicMock()
    s.id = id
    s.slug = slug
    s.name = name
    s.district_id = district_id
    return s


def _make_admin_user(*, id: int, role: str):
    u = MagicMock()
    u.id = id
    u.role = role
    return u


def _make_assignment(*, tenant_id: int):
    a = MagicMock()
    a.tenant_id = tenant_id
    return a


def _make_request(
    *,
    school,
    school_registry_mock,
    user_tenant_store_mock,
    super_admin_school_access: bool = False,
    session: Optional[dict] = None,
):
    req = MagicMock()
    req.state.school = school
    req.state.super_admin_school_access = super_admin_school_access
    req.app.state.school_registry = school_registry_mock
    req.app.state.user_tenant_store = user_tenant_store_mock
    # _get_selected_tenant_slug / _set_selected_tenant_slug use request.session
    req.session = session or {}
    return req


async def _run(coro):
    import asyncio
    return await asyncio.get_event_loop().run_until_complete(coro) if False else await coro


def _sync(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestDistrictIdAutoResolution:
    """district_id FK on home school auto-expands scope for district_admin."""

    def test_district_admin_sees_all_district_buildings(self):
        home = _make_school(id=1, slug="lincoln", name="Lincoln HS", district_id=10)
        sister_a = _make_school(id=2, slug="washington", name="Washington MS", district_id=10)
        sister_b = _make_school(id=3, slug="jefferson", name="Jefferson ES", district_id=10)

        school_registry = MagicMock()
        school_registry.list_schools_by_district = AsyncMock(return_value=[home, sister_a, sister_b])
        school_registry.list_schools = AsyncMock(return_value=[])

        user_tenant_store = MagicMock()
        user_tenant_store.list_assignments = AsyncMock(return_value=[])

        req = _make_request(school=home, school_registry_mock=school_registry, user_tenant_store_mock=user_tenant_store)
        admin = _make_admin_user(id=42, role="district_admin")

        scope = _sync(_resolve_admin_tenant_scope(req, admin_user=admin))

        slugs = {str(getattr(s, "slug", "")) for s in scope.available_schools}
        assert "lincoln" in slugs
        assert "washington" in slugs
        assert "jefferson" in slugs
        assert len(slugs) == 3

        school_registry.list_schools_by_district.assert_called_once_with(10)

    def test_district_admin_with_no_district_id_uses_assignments_only(self):
        home = _make_school(id=1, slug="lone", name="Lone School", district_id=None)

        school_registry = MagicMock()
        school_registry.list_schools = AsyncMock(return_value=[])
        school_registry.list_schools_by_district = AsyncMock(return_value=[])

        user_tenant_store = MagicMock()
        user_tenant_store.list_assignments = AsyncMock(return_value=[])

        req = _make_request(school=home, school_registry_mock=school_registry, user_tenant_store_mock=user_tenant_store)
        admin = _make_admin_user(id=99, role="district_admin")

        scope = _sync(_resolve_admin_tenant_scope(req, admin_user=admin))

        slugs = {str(getattr(s, "slug", "")) for s in scope.available_schools}
        assert slugs == {"lone"}
        school_registry.list_schools_by_district.assert_not_called()

    def test_newly_added_school_visible_without_explicit_assignment(self):
        """School added to district after DA creation is immediately visible via district_id path."""
        home = _make_school(id=1, slug="home-school", name="Home School", district_id=7)
        new_school = _make_school(id=5, slug="new-building", name="New Building", district_id=7)

        school_registry = MagicMock()
        # district query returns both buildings — the new one has no explicit assignment
        school_registry.list_schools_by_district = AsyncMock(return_value=[home, new_school])
        school_registry.list_schools = AsyncMock(return_value=[])

        user_tenant_store = MagicMock()
        # no explicit assignments at all
        user_tenant_store.list_assignments = AsyncMock(return_value=[])

        req = _make_request(school=home, school_registry_mock=school_registry, user_tenant_store_mock=user_tenant_store)
        admin = _make_admin_user(id=10, role="district_admin")

        scope = _sync(_resolve_admin_tenant_scope(req, admin_user=admin))

        slugs = {str(getattr(s, "slug", "")) for s in scope.available_schools}
        assert "new-building" in slugs
        assert "home-school" in slugs


class TestDistrictAndAssignmentAreAdditive:
    """district_id expansion and explicit assignment grants form a union."""

    def test_union_of_district_and_assignment_sources(self):
        home = _make_school(id=1, slug="alpha", name="Alpha", district_id=20)
        district_school = _make_school(id=2, slug="beta", name="Beta", district_id=20)
        # gamma is in a different district but explicitly assigned
        assigned_school = _make_school(id=3, slug="gamma", name="Gamma", district_id=99)

        school_registry = MagicMock()
        school_registry.list_schools_by_district = AsyncMock(return_value=[home, district_school])
        school_registry.list_schools = AsyncMock(return_value=[home, district_school, assigned_school])

        user_tenant_store = MagicMock()
        user_tenant_store.list_assignments = AsyncMock(return_value=[_make_assignment(tenant_id=3)])

        req = _make_request(school=home, school_registry_mock=school_registry, user_tenant_store_mock=user_tenant_store)
        admin = _make_admin_user(id=11, role="district_admin")

        scope = _sync(_resolve_admin_tenant_scope(req, admin_user=admin))

        slugs = {str(getattr(s, "slug", "")) for s in scope.available_schools}
        assert "alpha" in slugs
        assert "beta" in slugs
        assert "gamma" in slugs

    def test_overlap_between_district_and_assignment_does_not_duplicate(self):
        home = _make_school(id=1, slug="alpha", name="Alpha", district_id=5)
        overlap = _make_school(id=2, slug="beta", name="Beta", district_id=5)

        school_registry = MagicMock()
        school_registry.list_schools_by_district = AsyncMock(return_value=[home, overlap])
        school_registry.list_schools = AsyncMock(return_value=[home, overlap])

        user_tenant_store = MagicMock()
        # beta is also explicitly assigned
        user_tenant_store.list_assignments = AsyncMock(return_value=[_make_assignment(tenant_id=2)])

        req = _make_request(school=home, school_registry_mock=school_registry, user_tenant_store_mock=user_tenant_store)
        admin = _make_admin_user(id=12, role="district_admin")

        scope = _sync(_resolve_admin_tenant_scope(req, admin_user=admin))

        slugs = [str(getattr(s, "slug", "")) for s in scope.available_schools]
        assert slugs.count("beta") == 1, "Overlapping school must not appear twice"


class TestNonDistrictAdminRoles:
    """Non-district-admin roles must NOT get district-based expansion."""

    @pytest.mark.parametrize("role", ["building_admin", "admin", "teacher", "staff"])
    def test_non_district_admin_sees_only_home_school(self, role: str):
        home = _make_school(id=1, slug="my-school", name="My School", district_id=10)
        sister = _make_school(id=2, slug="sister-school", name="Sister School", district_id=10)

        school_registry = MagicMock()
        school_registry.list_schools_by_district = AsyncMock(return_value=[home, sister])
        school_registry.list_schools = AsyncMock(return_value=[home, sister])

        user_tenant_store = MagicMock()
        user_tenant_store.list_assignments = AsyncMock(return_value=[])

        req = _make_request(school=home, school_registry_mock=school_registry, user_tenant_store_mock=user_tenant_store)
        admin = _make_admin_user(id=20, role=role)

        scope = _sync(_resolve_admin_tenant_scope(req, admin_user=admin))

        slugs = {str(getattr(s, "slug", "")) for s in scope.available_schools}
        assert slugs == {"my-school"}, f"{role} should only see home school, got {slugs}"
        school_registry.list_schools_by_district.assert_not_called()


class TestSuperAdminBypass:
    """super_admin_school_access short-circuits all district resolution."""

    def test_super_admin_flag_bypasses_district_resolution(self):
        home = _make_school(id=1, slug="any-school", name="Any School", district_id=10)

        school_registry = MagicMock()
        school_registry.list_schools_by_district = AsyncMock(return_value=[])

        user_tenant_store = MagicMock()
        user_tenant_store.list_assignments = AsyncMock(return_value=[])

        req = _make_request(
            school=home,
            school_registry_mock=school_registry,
            user_tenant_store_mock=user_tenant_store,
            super_admin_school_access=True,
        )
        admin = _make_admin_user(id=1, role="district_admin")

        scope = _sync(_resolve_admin_tenant_scope(req, admin_user=admin))

        # Returns exactly the current_school only (early return path)
        assert len(scope.available_schools) == 1
        school_registry.list_schools_by_district.assert_not_called()


class TestSelectedSchoolLogic:
    """selected_school respects slug hint when school is in scope."""

    def test_slug_hint_selects_district_school(self):
        home = _make_school(id=1, slug="home", name="Home", district_id=3)
        target = _make_school(id=2, slug="target", name="Target", district_id=3)

        school_registry = MagicMock()
        school_registry.list_schools_by_district = AsyncMock(return_value=[home, target])
        school_registry.list_schools = AsyncMock(return_value=[])

        user_tenant_store = MagicMock()
        user_tenant_store.list_assignments = AsyncMock(return_value=[])

        req = _make_request(school=home, school_registry_mock=school_registry, user_tenant_store_mock=user_tenant_store)
        admin = _make_admin_user(id=5, role="district_admin")

        scope = _sync(_resolve_admin_tenant_scope(req, admin_user=admin, selected_slug_hint="target"))

        assert str(getattr(scope.selected_school, "slug", "")) == "target"

    def test_out_of_scope_slug_hint_falls_back_to_home(self):
        home = _make_school(id=1, slug="home", name="Home", district_id=3)
        other = _make_school(id=9, slug="rogue", name="Rogue", district_id=99)

        school_registry = MagicMock()
        school_registry.list_schools_by_district = AsyncMock(return_value=[home])
        school_registry.list_schools = AsyncMock(return_value=[])

        user_tenant_store = MagicMock()
        user_tenant_store.list_assignments = AsyncMock(return_value=[])

        req = _make_request(school=home, school_registry_mock=school_registry, user_tenant_store_mock=user_tenant_store)
        admin = _make_admin_user(id=5, role="district_admin")

        scope = _sync(_resolve_admin_tenant_scope(req, admin_user=admin, selected_slug_hint="rogue"))

        assert str(getattr(scope.selected_school, "slug", "")) == "home"
