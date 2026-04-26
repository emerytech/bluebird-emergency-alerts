"""
Tests for the Organization → District → Tenant hierarchy.

Critical invariant: tenant slug is never modified by any org/district operation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.school_registry import SchoolRegistry


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def registry(tmp_path: Path) -> SchoolRegistry:
    return SchoolRegistry(str(tmp_path / "platform.db"))


# ── Organization tests ────────────────────────────────────────────────────────


def test_create_and_retrieve_organization(registry: SchoolRegistry) -> None:
    import anyio

    org = anyio.from_thread.run_sync(
        lambda: anyio.run(registry.create_organization, name="Springfield USD", slug="springfield-usd")
    ) if False else _sync(registry.create_organization(name="Springfield USD", slug="springfield-usd"))

    assert org.name == "Springfield USD"
    assert org.slug == "springfield-usd"
    assert org.is_active is True
    assert org.id > 0


def test_list_organizations_empty(registry: SchoolRegistry) -> None:
    orgs = _sync(registry.list_organizations())
    assert orgs == []


def test_list_organizations(registry: SchoolRegistry) -> None:
    _sync(registry.create_organization(name="Org A", slug="org-a"))
    _sync(registry.create_organization(name="Org B", slug="org-b"))
    orgs = _sync(registry.list_organizations())
    assert len(orgs) == 2
    assert [o.slug for o in orgs] == ["org-a", "org-b"]


def test_get_organization_by_slug(registry: SchoolRegistry) -> None:
    _sync(registry.create_organization(name="Acme District", slug="acme"))
    org = _sync(registry.get_organization_by_slug("acme"))
    assert org is not None
    assert org.name == "Acme District"


def test_get_organization_missing_returns_none(registry: SchoolRegistry) -> None:
    result = _sync(registry.get_organization(9999))
    assert result is None


def test_organization_slug_uniqueness(registry: SchoolRegistry) -> None:
    _sync(registry.create_organization(name="First", slug="dup-org"))
    with pytest.raises(Exception):
        _sync(registry.create_organization(name="Second", slug="dup-org"))


# ── District tests ────────────────────────────────────────────────────────────


def test_create_district_under_organization(registry: SchoolRegistry) -> None:
    org = _sync(registry.create_organization(name="Metro USD", slug="metro-usd"))
    district = _sync(registry.create_district(name="North District", slug="north", organization_id=org.id))

    assert district.name == "North District"
    assert district.slug == "north"
    assert district.organization_id == org.id
    assert district.is_active is True


def test_list_districts_by_organization(registry: SchoolRegistry) -> None:
    org1 = _sync(registry.create_organization(name="Org 1", slug="org-1"))
    org2 = _sync(registry.create_organization(name="Org 2", slug="org-2"))

    _sync(registry.create_district(name="D1", slug="d1", organization_id=org1.id))
    _sync(registry.create_district(name="D2", slug="d2", organization_id=org1.id))
    _sync(registry.create_district(name="D3", slug="d3", organization_id=org2.id))

    d_org1 = _sync(registry.list_districts(organization_id=org1.id))
    d_org2 = _sync(registry.list_districts(organization_id=org2.id))
    d_all = _sync(registry.list_districts())

    assert len(d_org1) == 2
    assert len(d_org2) == 1
    assert len(d_all) == 3


def test_get_district_by_slug(registry: SchoolRegistry) -> None:
    org = _sync(registry.create_organization(name="Riverdale", slug="riverdale"))
    _sync(registry.create_district(name="South District", slug="south", organization_id=org.id))
    district = _sync(registry.get_district_by_slug("south"))
    assert district is not None
    assert district.organization_id == org.id


def test_get_district_missing_returns_none(registry: SchoolRegistry) -> None:
    result = _sync(registry.get_district(9999))
    assert result is None


def test_district_slug_uniqueness(registry: SchoolRegistry) -> None:
    org = _sync(registry.create_organization(name="Dup Org", slug="dup-org2"))
    _sync(registry.create_district(name="D1", slug="dup-district", organization_id=org.id))
    with pytest.raises(Exception):
        _sync(registry.create_district(name="D2", slug="dup-district", organization_id=org.id))


# ── Tenant ↔ District assignment tests ───────────────────────────────────────


def test_new_school_has_no_district(registry: SchoolRegistry) -> None:
    school = _sync(registry.create_school(slug="lone-school", name="Lone School"))
    assert school.district_id is None
    assert school.slug == "lone-school"  # slug unchanged


def test_assign_school_to_district(registry: SchoolRegistry) -> None:
    org = _sync(registry.create_organization(name="Assign Org", slug="assign-org"))
    district = _sync(registry.create_district(name="Assign District", slug="assign-dist", organization_id=org.id))
    school = _sync(registry.create_school(slug="assign-school", name="Assign School"))

    assert school.district_id is None

    updated = _sync(registry.assign_to_district(school_slug="assign-school", district_id=district.id))
    assert updated is not None
    assert updated.district_id == district.id
    # Slug is immutable — must not change.
    assert updated.slug == "assign-school"


def test_slug_unchanged_after_district_assignment(registry: SchoolRegistry) -> None:
    org = _sync(registry.create_organization(name="Slug Guard Org", slug="slug-guard-org"))
    district = _sync(registry.create_district(name="Slug Guard District", slug="slug-guard-dist", organization_id=org.id))
    original_slug = "slug-critical"
    _sync(registry.create_school(slug=original_slug, name="Slug-Critical School"))

    _sync(registry.assign_to_district(school_slug=original_slug, district_id=district.id))

    fetched = _sync(registry.get_by_slug(original_slug))
    assert fetched is not None, "School must still be retrievable by original slug"
    assert fetched.slug == original_slug
    assert fetched.district_id == district.id


def test_remove_school_from_district(registry: SchoolRegistry) -> None:
    org = _sync(registry.create_organization(name="Remove Org", slug="remove-org"))
    district = _sync(registry.create_district(name="Remove District", slug="remove-dist", organization_id=org.id))
    _sync(registry.create_school(slug="remove-school", name="Remove School"))
    _sync(registry.assign_to_district(school_slug="remove-school", district_id=district.id))

    cleared = _sync(registry.assign_to_district(school_slug="remove-school", district_id=None))
    assert cleared is not None
    assert cleared.district_id is None
    assert cleared.slug == "remove-school"


def test_list_schools_by_district(registry: SchoolRegistry) -> None:
    org = _sync(registry.create_organization(name="List Org", slug="list-org"))
    d1 = _sync(registry.create_district(name="District 1", slug="list-d1", organization_id=org.id))
    d2 = _sync(registry.create_district(name="District 2", slug="list-d2", organization_id=org.id))

    _sync(registry.create_school(slug="school-a", name="School A"))
    _sync(registry.create_school(slug="school-b", name="School B"))
    _sync(registry.create_school(slug="school-c", name="School C"))

    _sync(registry.assign_to_district(school_slug="school-a", district_id=d1.id))
    _sync(registry.assign_to_district(school_slug="school-b", district_id=d1.id))
    _sync(registry.assign_to_district(school_slug="school-c", district_id=d2.id))

    in_d1 = _sync(registry.list_schools_by_district(d1.id))
    in_d2 = _sync(registry.list_schools_by_district(d2.id))

    assert len(in_d1) == 2
    assert {s.slug for s in in_d1} == {"school-a", "school-b"}
    assert len(in_d2) == 1
    assert in_d2[0].slug == "school-c"


def test_existing_school_migration_safe(registry: SchoolRegistry) -> None:
    """Simulates an existing school (district_id=NULL) staying functional after schema migration."""
    school = _sync(registry.ensure_school(slug="legacy-school", name="Legacy School"))
    assert school.district_id is None
    assert school.slug == "legacy-school"

    # Verify it's still retrievable and usable with no district.
    fetched = _sync(registry.get_by_slug("legacy-school"))
    assert fetched is not None
    assert fetched.district_id is None


def test_multiple_schools_same_district(registry: SchoolRegistry) -> None:
    org = _sync(registry.create_organization(name="Multi Org", slug="multi-org"))
    district = _sync(registry.create_district(name="Multi District", slug="multi-dist", organization_id=org.id))

    for i in range(5):
        _sync(registry.create_school(slug=f"multi-school-{i}", name=f"School {i}"))
        _sync(registry.assign_to_district(school_slug=f"multi-school-{i}", district_id=district.id))

    schools = _sync(registry.list_schools_by_district(district.id))
    assert len(schools) == 5
    # All slugs intact.
    assert all(s.slug.startswith("multi-school-") for s in schools)


# ── Utility ───────────────────────────────────────────────────────────────────


def _sync(coro):
    """Run a coroutine synchronously in tests using a dedicated event loop."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
