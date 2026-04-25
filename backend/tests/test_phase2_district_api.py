from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# ── Shared helpers ────────────────────────────────────────────────────────────

def _create_school(client: TestClient, *, name: str, slug: str) -> None:
    r = client.post(
        "/super-admin/schools/create",
        data={"name": name, "slug": slug},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text


def _create_user(client: TestClient, slug: str, *, name: str, role: str) -> int:
    r = client.post(
        f"/{slug}/users",
        headers={"X-API-Key": "test-api-key"},
        json={"name": name, "role": role, "phone_e164": None},
    )
    assert r.status_code == 200, r.text
    return int(r.json()["user_id"])


def _get_school(client: TestClient, slug: str):
    return client.app.state.tenant_manager.school_for_slug(slug)


def _assign_tenant(client: TestClient, *, user_id: int, home_tenant_id: int, tenant_ids: list[int]) -> None:
    asyncio.run(
        client.app.state.user_tenant_store.replace_assignments(
            user_id=user_id,
            home_tenant_id=home_tenant_id,
            tenant_ids=tenant_ids,
        )
    )


def _me(client: TestClient, slug: str, user_id: int) -> dict:
    return client.get(
        f"/{slug}/me",
        headers={"X-API-Key": "test-api-key"},
        params={"user_id": user_id},
    )


def _select_tenant(client: TestClient, slug: str, user_id: int, target_slug: str):
    return client.post(
        f"/{slug}/me/selected-tenant",
        headers={"X-API-Key": "test-api-key"},
        params={"user_id": user_id},
        json={"tenant_slug": target_slug},
    )


def _overview(client: TestClient, slug: str, user_id: int):
    return client.get(
        f"/{slug}/district/overview",
        headers={"X-API-Key": "test-api-key"},
        params={"user_id": user_id},
    )


# ── GET /me tests ─────────────────────────────────────────────────────────────

def test_me_single_tenant_user(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Me School Single", slug="me-single")
    teacher_id = _create_user(client, "me-single", name="Ms. Jones", role="teacher")

    r = _me(client, "me-single", teacher_id)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user_id"] == teacher_id
    assert data["role"] == "teacher"
    assert data["can_deactivate_alarm"] is False
    assert data["selected_tenant"] == "me-single"
    assert len(data["tenants"]) == 1
    assert data["tenants"][0]["tenant_slug"] == "me-single"
    assert data["tenants"][0]["role"] == "teacher"


def test_me_admin_can_deactivate_flag(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Me Admin School", slug="me-admin")
    admin_id = _create_user(client, "me-admin", name="Admin User", role="admin")

    r = _me(client, "me-admin", admin_id)
    assert r.status_code == 200, r.text
    assert r.json()["can_deactivate_alarm"] is True


def test_me_district_admin_sees_assigned_tenants(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Me Home School", slug="me-home")
    _create_school(client, name="Me Assigned School", slug="me-assigned")
    _create_school(client, name="Me Unassigned School", slug="me-unassigned")

    district_id = _create_user(client, "me-home", name="District Lead", role="district_admin")

    school_home = _get_school(client, "me-home")
    school_assigned = _get_school(client, "me-assigned")
    assert school_home is not None
    assert school_assigned is not None

    _assign_tenant(client, user_id=district_id, home_tenant_id=school_home.id, tenant_ids=[school_assigned.id])

    r = _me(client, "me-home", district_id)
    assert r.status_code == 200, r.text
    data = r.json()
    tenant_slugs = {t["tenant_slug"] for t in data["tenants"]}
    assert "me-home" in tenant_slugs
    assert "me-assigned" in tenant_slugs
    assert "me-unassigned" not in tenant_slugs
    assert len(data["tenants"]) == 2


def test_me_super_admin_user_sees_all_active_schools(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="SA School Alpha", slug="sa-alpha")
    _create_school(client, name="SA School Beta", slug="sa-beta")
    super_id = _create_user(client, "sa-alpha", name="Super User", role="super_admin")

    r = _me(client, "sa-alpha", super_id)
    assert r.status_code == 200, r.text
    data = r.json()
    tenant_slugs = {t["tenant_slug"] for t in data["tenants"]}
    assert "sa-alpha" in tenant_slugs
    assert "sa-beta" in tenant_slugs


def test_me_requires_api_key(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Me Auth School", slug="me-auth")
    user_id = _create_user(client, "me-auth", name="Teacher", role="teacher")

    r = client.get(f"/me-auth/me", params={"user_id": user_id})
    # require_api_key returns 401 when key is absent
    assert r.status_code in {401, 403}


def test_me_unknown_user_rejected(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Me Unknown School", slug="me-unknown")

    r = _me(client, "me-unknown", 99999)
    assert r.status_code == 403


def test_me_title_included_in_response(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Me Title School", slug="me-title")
    r = client.post(
        "/me-title/users",
        headers={"X-API-Key": "test-api-key"},
        json={"name": "Principal User", "role": "admin", "phone_e164": None, "title": "Principal"},
    )
    assert r.status_code == 200
    user_id = r.json()["user_id"]

    r = _me(client, "me-title", user_id)
    assert r.status_code == 200
    assert r.json()["title"] == "Principal"


# ── POST /me/selected-tenant tests ───────────────────────────────────────────

def test_select_tenant_home_school_succeeds(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Select Home School", slug="sel-home")
    teacher_id = _create_user(client, "sel-home", name="Teacher", role="teacher")

    r = _select_tenant(client, "sel-home", teacher_id, "sel-home")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tenant_slug"] == "sel-home"
    assert data["role"] == "teacher"


def test_select_tenant_assigned_succeeds_for_district_admin(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Select DA Home", slug="selda-home")
    _create_school(client, name="Select DA Assigned", slug="selda-assigned")

    district_id = _create_user(client, "selda-home", name="District Admin", role="district_admin")
    school_home = _get_school(client, "selda-home")
    school_assigned = _get_school(client, "selda-assigned")
    _assign_tenant(client, user_id=district_id, home_tenant_id=school_home.id, tenant_ids=[school_assigned.id])

    r = _select_tenant(client, "selda-home", district_id, "selda-assigned")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tenant_slug"] == "selda-assigned"


def test_select_tenant_unassigned_returns_403(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Select Unassigned Home", slug="selu-home")
    _create_school(client, name="Select Unassigned Other", slug="selu-other")

    teacher_id = _create_user(client, "selu-home", name="Teacher", role="teacher")
    r = _select_tenant(client, "selu-home", teacher_id, "selu-other")
    assert r.status_code == 403


def test_select_tenant_district_admin_blocked_from_unassigned(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="DA Blocked Home", slug="dab-home")
    _create_school(client, name="DA Blocked Assigned", slug="dab-assigned")
    _create_school(client, name="DA Blocked Other", slug="dab-other")

    district_id = _create_user(client, "dab-home", name="District Admin", role="district_admin")
    school_home = _get_school(client, "dab-home")
    school_assigned = _get_school(client, "dab-assigned")
    _assign_tenant(client, user_id=district_id, home_tenant_id=school_home.id, tenant_ids=[school_assigned.id])

    r = _select_tenant(client, "dab-home", district_id, "dab-other")
    assert r.status_code == 403


def test_select_tenant_not_found_returns_404(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Select 404 School", slug="sel-404")
    admin_id = _create_user(client, "sel-404", name="Admin", role="admin")

    r = _select_tenant(client, "sel-404", admin_id, "nonexistent-tenant")
    assert r.status_code == 404


def test_select_tenant_super_admin_user_can_access_any_tenant(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Super Select Home", slug="supsel-home")
    _create_school(client, name="Super Select Remote", slug="supsel-remote")
    super_id = _create_user(client, "supsel-home", name="Super User", role="super_admin")

    r = _select_tenant(client, "supsel-home", super_id, "supsel-remote")
    assert r.status_code == 200, r.text
    assert r.json()["tenant_slug"] == "supsel-remote"
    assert r.json()["role"] == "super_admin"


# ── GET /district/overview tests ─────────────────────────────────────────────

def test_district_overview_403_for_teacher(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Overview Teacher School", slug="ov-teacher")
    teacher_id = _create_user(client, "ov-teacher", name="Teacher", role="teacher")

    r = _overview(client, "ov-teacher", teacher_id)
    assert r.status_code == 403


def test_district_overview_403_for_admin(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Overview Admin School", slug="ov-admin")
    admin_id = _create_user(client, "ov-admin", name="Admin", role="admin")

    r = _overview(client, "ov-admin", admin_id)
    assert r.status_code == 403


def test_district_overview_district_admin_sees_only_assigned(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="OV DA Home", slug="ovda-home")
    _create_school(client, name="OV DA Assigned", slug="ovda-assigned")
    _create_school(client, name="OV DA Outside", slug="ovda-outside")

    district_id = _create_user(client, "ovda-home", name="District Admin", role="district_admin")
    school_home = _get_school(client, "ovda-home")
    school_assigned = _get_school(client, "ovda-assigned")
    _assign_tenant(client, user_id=district_id, home_tenant_id=school_home.id, tenant_ids=[school_assigned.id])

    r = _overview(client, "ovda-home", district_id)
    assert r.status_code == 200, r.text
    data = r.json()
    slugs = {t["tenant_slug"] for t in data["tenants"]}
    assert "ovda-home" in slugs
    assert "ovda-assigned" in slugs
    assert "ovda-outside" not in slugs
    assert data["tenant_count"] == 2


def test_district_overview_super_admin_sees_all_active(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="OV SA Alpha", slug="ovsa-alpha")
    _create_school(client, name="OV SA Beta", slug="ovsa-beta")
    super_id = _create_user(client, "ovsa-alpha", name="Super User", role="super_admin")

    r = _overview(client, "ovsa-alpha", super_id)
    assert r.status_code == 200, r.text
    data = r.json()
    slugs = {t["tenant_slug"] for t in data["tenants"]}
    assert "ovsa-alpha" in slugs
    assert "ovsa-beta" in slugs


def test_district_overview_alarm_status_is_tenant_scoped(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="OV Alarm Home", slug="oval-home")
    _create_school(client, name="OV Alarm Remote", slug="oval-remote")

    district_id = _create_user(client, "oval-home", name="District Admin", role="district_admin")
    admin_home_id = _create_user(client, "oval-home", name="Admin Home", role="admin")
    _create_user(client, "oval-remote", name="Admin Remote", role="admin")

    school_home = _get_school(client, "oval-home")
    school_remote = _get_school(client, "oval-remote")
    _assign_tenant(client, user_id=district_id, home_tenant_id=school_home.id, tenant_ids=[school_remote.id])

    # Activate alarm in home school only
    r = client.post(
        "/oval-home/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Emergency!", "user_id": admin_home_id},
    )
    assert r.status_code == 200

    r = _overview(client, "oval-home", district_id)
    assert r.status_code == 200, r.text
    data = r.json()
    by_slug = {t["tenant_slug"]: t for t in data["tenants"]}
    assert by_slug["oval-home"]["alarm_is_active"] is True
    assert by_slug["oval-remote"]["alarm_is_active"] is False
