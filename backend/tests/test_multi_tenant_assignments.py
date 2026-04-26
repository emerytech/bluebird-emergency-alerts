from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient


def _create_school(client: TestClient, *, name: str, slug: str) -> None:
    response = client.post(
        "/super-admin/schools/create",
        data={"name": name, "slug": slug, "setup_pin": ""},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _enter_school(client: TestClient, slug: str) -> None:
    response = client.post(f"/super-admin/schools/{slug}/enter", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == f"/{slug}/admin"


def _create_admin_console_user(
    client: TestClient,
    slug: str,
    *,
    name: str,
    role: str,
    login_name: str = "",
    password: str = "",
) -> None:
    response = client.post(
        f"/{slug}/admin/users/create",
        data={
            "name": name,
            "role": role,
            "phone_e164": "",
            "login_name": login_name,
            "password": password,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def _login_building_admin(client: TestClient, slug: str, *, login_name: str, password: str) -> None:
    response = client.post(
        f"/{slug}/admin/login",
        data={"login_name": login_name, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers.get("location") in {f"/{slug}/admin", f"/{slug}/admin/change-password"}


def test_district_admin_tenant_filter_respects_assignments(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Alpha School", slug="alpha-school")
    _create_school(client, name="Beta School", slug="beta-school")
    _create_school(client, name="Gamma School", slug="gamma-school")

    _enter_school(client, "alpha-school")
    _create_admin_console_user(
        client,
        "alpha-school",
        name="District Lead",
        role="district_admin",
        login_name="district.lead",
        password="Password@123",
    )
    _create_admin_console_user(client, "alpha-school", name="Alpha Teacher", role="teacher")

    _enter_school(client, "beta-school")
    _create_admin_console_user(client, "beta-school", name="Beta Teacher", role="teacher")

    _enter_school(client, "gamma-school")
    _create_admin_console_user(client, "gamma-school", name="Gamma Teacher", role="teacher")

    school_alpha = client.app.state.tenant_manager.school_for_slug("alpha-school")
    school_beta = client.app.state.tenant_manager.school_for_slug("beta-school")
    assert school_alpha is not None
    assert school_beta is not None
    tenant_alpha = client.app.state.tenant_manager.get(school_alpha)
    alpha_users = asyncio.run(tenant_alpha.user_store.list_users())
    district_user = next(item for item in alpha_users if item.login_name == "district.lead")

    asyncio.run(
        client.app.state.user_tenant_store.replace_assignments(
            user_id=district_user.id,
            home_tenant_id=school_alpha.id,
            tenant_ids=[school_beta.id],
        )
    )

    logout = client.post("/super-admin/logout", follow_redirects=False)
    assert logout.status_code == 303

    _login_building_admin(client, "alpha-school", login_name="district.lead", password="Password@123")

    assigned_view = client.get(
        "/alpha-school/admin?section=user-management&tenant=beta-school",
        follow_redirects=False,
    )
    assert assigned_view.status_code == 200
    assert "Viewing tenant: <strong>Beta School</strong>" in assigned_view.text
    assert "Beta Teacher" in assigned_view.text
    assert "Gamma Teacher" not in assigned_view.text

    blocked_view = client.get(
        "/alpha-school/admin?section=user-management&tenant=gamma-school",
        follow_redirects=False,
    )
    assert blocked_view.status_code == 200
    assert "Requested tenant is not in your assignment scope" in blocked_view.text
    assert "Viewing tenant: <strong>Alpha School</strong>" in blocked_view.text
    assert "Gamma Teacher" not in blocked_view.text


def test_district_admin_assignment_update_filters_unassigned_tenants(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Home School", slug="home-school")
    _create_school(client, name="Assigned School", slug="assigned-school")
    _create_school(client, name="Outside School", slug="outside-school")

    _enter_school(client, "home-school")
    _create_admin_console_user(
        client,
        "home-school",
        name="District One",
        role="district_admin",
        login_name="district.one",
        password="Password@123",
    )
    _create_admin_console_user(client, "home-school", name="Officer One", role="law_enforcement")

    school_home = client.app.state.tenant_manager.school_for_slug("home-school")
    school_assigned = client.app.state.tenant_manager.school_for_slug("assigned-school")
    school_outside = client.app.state.tenant_manager.school_for_slug("outside-school")
    assert school_home is not None
    assert school_assigned is not None
    assert school_outside is not None
    tenant_home = client.app.state.tenant_manager.get(school_home)
    home_users = asyncio.run(tenant_home.user_store.list_users())
    district_user = next(item for item in home_users if item.login_name == "district.one")
    officer_user = next(item for item in home_users if item.name == "Officer One")

    asyncio.run(
        client.app.state.user_tenant_store.replace_assignments(
            user_id=district_user.id,
            home_tenant_id=school_home.id,
            tenant_ids=[school_assigned.id],
        )
    )

    logout = client.post("/super-admin/logout", follow_redirects=False)
    assert logout.status_code == 303
    _login_building_admin(client, "home-school", login_name="district.one", password="Password@123")

    update = client.post(
        f"/home-school/admin/users/{officer_user.id}/tenant-assignments",
        data={
            "tenant_ids": [str(school_assigned.id), str(school_outside.id)],
        },
        follow_redirects=False,
    )
    assert update.status_code == 303
    assert update.headers.get("location") == "/home-school/admin?section=user-management#users"

    assignments = asyncio.run(
        client.app.state.user_tenant_store.list_assignments(
            user_id=officer_user.id,
            home_tenant_id=school_home.id,
        )
    )
    assigned_ids = sorted(item.tenant_id for item in assignments)
    assert assigned_ids == [school_assigned.id]

