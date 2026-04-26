from __future__ import annotations

import asyncio
import importlib

import pytest
from fastapi.testclient import TestClient


# ── Helpers ────────────────────────────────────────────────────────────────────

def _create_school(client: TestClient, *, name: str, slug: str) -> None:
    r = client.post(
        "/super-admin/schools/create",
        data={"name": name, "slug": slug, "setup_pin": ""},
        follow_redirects=False,
    )
    assert r.status_code == 303


def _login_super_admin_session(client: TestClient) -> None:
    r = client.post(
        "/super-admin/login",
        data={"login_name": "superadmin", "password": "super-password-123"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def _generate_setup_code(client: TestClient, slug: str) -> str:
    """Generate a setup code for a school and return the code string."""
    r = client.post(
        "/super-admin/setup-codes/generate",
        data={"tenant_slug": slug, "expires_hours": "48"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    app_main = importlib.import_module("app.main")
    svc = app_main.app.state.access_code_service
    codes = asyncio.run(svc.list_setup_codes(limit=10))
    assert codes, "Expected at least one setup code"
    return codes[0].code


def _generate_invite_code_via_api(
    client: TestClient,
    slug: str,
    role: str = "teacher",
) -> str:
    """Generate an invite code as a district_admin and return the code string."""
    app_main = importlib.import_module("app.main")
    svc = app_main.app.state.access_code_service
    rec = asyncio.run(
        svc.generate_code(
            tenant_slug=slug,
            role=role,
            title=None,
            created_by_user_id=0,
            expires_hours=48,
            max_uses=1,
            is_setup_code=False,
        )
    )
    return rec.code


# ── Setup code tests ────────────────────────────────────────────────────────────

def test_validate_setup_code_invalid(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Test School", slug="test-school")

    r = client.post(
        "/onboarding/validate-setup-code",
        json={"code": "BADCODE1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert body["error"]


def test_setup_code_full_flow(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Setup School", slug="setup-school")
    code = _generate_setup_code(client, "setup-school")
    assert len(code) == 8

    # Validate step
    r = client.post("/onboarding/validate-setup-code", json={"code": code})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["tenant_slug"] == "setup-school"

    # Create district admin
    r = client.post(
        "/onboarding/create-district-admin",
        json={
            "code": code,
            "name": "Jane Admin",
            "login_name": "janedmin",
            "password": "SecurePass1!",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["tenant_slug"] == "setup-school"

    # Code should now be consumed — second attempt fails
    r = client.post(
        "/onboarding/create-district-admin",
        json={
            "code": code,
            "name": "Another Admin",
            "login_name": "another",
            "password": "SecurePass1!",
        },
    )
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_setup_code_consumed_after_use(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Consume School", slug="consume-school")
    code = _generate_setup_code(client, "consume-school")

    client.post(
        "/onboarding/create-district-admin",
        json={"code": code, "name": "Admin", "login_name": "admn", "password": "Password1!"},
    )
    r = client.post("/onboarding/validate-setup-code", json={"code": code})
    assert r.json()["valid"] is False


# ── Invite code tests ───────────────────────────────────────────────────────────

def test_validate_invite_code_invalid(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Invite School", slug="invite-school")

    r = client.post(
        "/onboarding/validate-code",
        json={"code": "NOTVALID", "tenant_slug": "invite-school"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False


def test_invite_code_full_flow(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Invite School", slug="invite-school")
    code = _generate_invite_code_via_api(client, "invite-school", role="teacher")

    # Validate
    r = client.post(
        "/onboarding/validate-code",
        json={"code": code, "tenant_slug": "invite-school"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["role"] == "teacher"
    assert body["tenant_slug"] == "invite-school"

    # Create account
    r = client.post(
        "/onboarding/create-account",
        json={
            "code": code,
            "tenant_slug": "invite-school",
            "name": "Alice Teacher",
            "login_name": "alicet",
            "password": "Password1!",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True

    # Code consumed — second use fails
    r = client.post(
        "/onboarding/create-account",
        json={
            "code": code,
            "tenant_slug": "invite-school",
            "name": "Bob",
            "login_name": "bob",
            "password": "Password1!",
        },
    )
    assert r.json()["valid"] is False


def test_invite_code_wrong_tenant_rejected(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="School A", slug="school-a")
    _create_school(client, name="School B", slug="school-b")
    code = _generate_invite_code_via_api(client, "school-a", role="staff")

    # Validate with wrong tenant
    r = client.post(
        "/onboarding/validate-code",
        json={"code": code, "tenant_slug": "school-b"},
    )
    assert r.json()["valid"] is False


def test_invite_code_duplicate_username_rejected(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Dup School", slug="dup-school")
    code1 = _generate_invite_code_via_api(client, "dup-school", role="teacher")
    code2 = _generate_invite_code_via_api(client, "dup-school", role="teacher")

    client.post(
        "/onboarding/create-account",
        json={"code": code1, "tenant_slug": "dup-school", "name": "User", "login_name": "dupuser", "password": "Password1!"},
    )
    r = client.post(
        "/onboarding/create-account",
        json={"code": code2, "tenant_slug": "dup-school", "name": "User2", "login_name": "dupuser", "password": "Password1!"},
    )
    assert r.json()["valid"] is False


def test_rate_limit_hits_after_five_attempts(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Rate School", slug="rate-school")

    for _ in range(5):
        client.post(
            "/onboarding/validate-code",
            json={"code": "BADCODE1", "tenant_slug": "rate-school"},
        )

    r = client.post(
        "/onboarding/validate-code",
        json={"code": "BADCODE1", "tenant_slug": "rate-school"},
    )
    assert r.status_code == 429


def test_super_admin_setup_code_revoke(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Revoke School", slug="revoke-school")
    code = _generate_setup_code(client, "revoke-school")

    # Revoke via web form
    app_main = importlib.import_module("app.main")
    svc = app_main.app.state.access_code_service
    codes = asyncio.run(svc.list_setup_codes(limit=10))
    code_id = next(c.id for c in codes if c.code == code)

    r = client.post(
        f"/super-admin/setup-codes/{code_id}/revoke",
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Validate now fails
    r = client.post("/onboarding/validate-setup-code", json={"code": code})
    assert r.json()["valid"] is False
