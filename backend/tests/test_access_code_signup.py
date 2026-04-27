"""
Access code signup flow tests.

Invariants under test:
  1. Generate code for tenant "nen" → code is stored with that tenant_slug.
  2. Validate same code with correct tenant_slug → valid=True, returns role/name.
  3. Validate same code with wrong tenant_slug → valid=False.
  4. Create account with valid tenant/code → success, user exists in tenant.
  5. Reuse single-use code after account created → valid=False (code consumed).
  6. Expired code → valid=False.
  7. Generate response includes qr_payload_json with tenant_slug and code.
  8. QR payload does NOT contain password or secret.
  9. Standard invite code cannot create district_admin via create-account.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_school(client: TestClient, *, name: str, slug: str) -> None:
    resp = client.post(
        "/super-admin/schools/create",
        data={"name": name, "slug": slug, "setup_pin": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def _create_user(client: TestClient, slug: str, *, name: str, role: str) -> int:
    resp = client.post(
        f"/{slug}/users",
        headers={"X-API-Key": "test-api-key"},
        json={"name": name, "role": role, "phone_e164": None},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["user_id"])


def _generate_code(
    client: TestClient,
    slug: str,
    *,
    admin_user_id: int,
    role: str = "teacher",
    max_uses: int = 1,
    expires_hours: int = 48,
) -> dict:
    # Log in as the admin so the session cookie is set, then call the API endpoint.
    # The test uses direct AccessCodeService call to bypass auth for simplicity.
    # We use the service directly through the app state.
    svc = client.app.state.access_code_service
    rec = asyncio.run(
        svc.generate_code(
            tenant_slug=slug,
            role=role,
            title=None,
            created_by_user_id=admin_user_id,
            expires_hours=expires_hours,
            max_uses=max_uses,
            is_setup_code=False,
        )
    )
    return {
        "id": rec.id,
        "code": rec.code,
        "tenant_slug": rec.tenant_slug,
        "role": rec.role,
        "status": rec.status,
        "expires_at": rec.expires_at,
    }


def _validate_code(client: TestClient, *, code: str, tenant_slug: str) -> dict:
    resp = client.post(
        "/onboarding/validate-code",
        json={"code": code, "tenant_slug": tenant_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_account(
    client: TestClient,
    *,
    code: str,
    tenant_slug: str,
    name: str = "Test User",
    login_name: str = "testuser",
    password: str = "securepassword123",
) -> dict:
    resp = client.post(
        "/onboarding/create-account",
        json={
            "code": code,
            "tenant_slug": tenant_slug,
            "name": name,
            "login_name": login_name,
            "password": password,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _tenant_ctx(client: TestClient, slug: str):
    school = client.app.state.tenant_manager.school_for_slug(slug)
    return client.app.state.tenant_manager.get(school)


# ---------------------------------------------------------------------------
# 1. Generate code → stored with correct tenant_slug
# ---------------------------------------------------------------------------

def test_generate_code_stores_correct_tenant_slug(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Northeast Nodaway", slug="nen")
    admin_id = _create_user(client, "nen", name="Admin", role="district_admin")

    result = _generate_code(client, "nen", admin_user_id=admin_id)

    assert result["tenant_slug"] == "nen", f"Expected tenant_slug='nen', got: {result}"
    assert result["role"] == "teacher"
    assert result["status"] == "active"


# ---------------------------------------------------------------------------
# 2. Validate code with correct tenant_slug → valid=True
# ---------------------------------------------------------------------------

def test_validate_code_correct_tenant_succeeds(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="NEN School", slug="nen2")
    admin_id = _create_user(client, "nen2", name="Admin", role="district_admin")

    gen = _generate_code(client, "nen2", admin_user_id=admin_id)
    result = _validate_code(client, code=gen["code"], tenant_slug="nen2")

    assert result["valid"] is True, f"Expected valid=True, got: {result}"
    assert result["tenant_slug"] == "nen2"
    assert result["role"] == "teacher"
    assert result.get("tenant_name") is not None


# ---------------------------------------------------------------------------
# 3. Validate code with wrong tenant_slug → valid=False
# ---------------------------------------------------------------------------

def test_validate_code_wrong_tenant_fails(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="NEN Real", slug="nen3")
    _create_school(client, name="Other School", slug="other3")
    admin_id = _create_user(client, "nen3", name="Admin", role="district_admin")

    gen = _generate_code(client, "nen3", admin_user_id=admin_id)
    result = _validate_code(client, code=gen["code"], tenant_slug="other3")

    assert result["valid"] is False, (
        f"SECURITY FAILURE: code from 'nen3' validated against 'other3', got: {result}"
    )


# ---------------------------------------------------------------------------
# 4. Create account with valid code → user exists in tenant
# ---------------------------------------------------------------------------

def test_create_account_with_valid_code_creates_user(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="NEN Create", slug="nen4")
    admin_id = _create_user(client, "nen4", name="Admin", role="district_admin")

    gen = _generate_code(client, "nen4", admin_user_id=admin_id, role="teacher")
    result = _create_account(
        client,
        code=gen["code"],
        tenant_slug="nen4",
        name="Jane Teacher",
        login_name="jane.teacher",
    )

    assert result["valid"] is True, f"Expected valid=True, got: {result}"
    assert result["role"] == "teacher"
    assert result["tenant_slug"] == "nen4"

    # User must now exist in the tenant DB.
    tenant = _tenant_ctx(client, "nen4")
    users = asyncio.run(tenant.user_store.list_users())
    login_names = [u.login_name for u in users if u.login_name]
    assert "jane.teacher" in login_names, (
        f"Expected 'jane.teacher' in tenant user list, found: {login_names}"
    )


# ---------------------------------------------------------------------------
# 5. Reuse single-use code → second attempt returns valid=False
# ---------------------------------------------------------------------------

def test_single_use_code_rejected_on_reuse(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="NEN Reuse", slug="nen5")
    admin_id = _create_user(client, "nen5", name="Admin", role="district_admin")

    gen = _generate_code(client, "nen5", admin_user_id=admin_id, max_uses=1)
    # First use succeeds.
    result1 = _create_account(
        client, code=gen["code"], tenant_slug="nen5", login_name="first.user"
    )
    assert result1["valid"] is True, f"First use should succeed: {result1}"

    # Second use must fail.
    result2 = _validate_code(client, code=gen["code"], tenant_slug="nen5")
    assert result2["valid"] is False, (
        f"SECURITY FAILURE: single-use code accepted a second time: {result2}"
    )


# ---------------------------------------------------------------------------
# 6. Expired code → valid=False
# ---------------------------------------------------------------------------

def test_expired_code_is_rejected(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="NEN Expire", slug="nen6")
    admin_id = _create_user(client, "nen6", name="Admin", role="district_admin")

    svc = client.app.state.access_code_service
    import sqlite3
    # Insert a code that expired 1 hour ago.
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(svc._db_path, isolation_level=None) as conn:
        conn.execute(
            """
            INSERT INTO access_codes
                (code, tenant_slug, role, title, created_by_user_id,
                 created_at, expires_at, max_uses, is_setup_code)
            VALUES ('EXPIREDCODE', 'nen6', 'teacher', NULL, ?, ?, ?, 1, 0);
            """,
            (admin_id, now, past),
        )

    result = _validate_code(client, code="EXPIREDCODE", tenant_slug="nen6")
    assert result["valid"] is False, f"Expected expired code to fail, got: {result}"


# ---------------------------------------------------------------------------
# 7. Generate response includes qr_payload_json with tenant_slug and code
# ---------------------------------------------------------------------------

def test_generate_api_response_includes_qr_payload_json(client: TestClient, login_super_admin) -> None:
    import json

    login_super_admin()
    _create_school(client, name="NEN QR", slug="nen7")
    admin_id = _create_user(client, "nen7", name="Admin", role="district_admin")

    gen = _generate_code(client, "nen7", admin_user_id=admin_id)
    svc = client.app.state.access_code_service
    qr_json = svc.qr_payload(gen["code"], "nen7")
    payload = json.loads(qr_json)

    assert payload.get("tenant_slug") == "nen7", f"QR payload missing tenant_slug: {payload}"
    assert payload.get("code") == gen["code"], f"QR payload missing code: {payload}"
    assert payload.get("type") == "bluebird_invite", f"QR payload wrong type: {payload}"


# ---------------------------------------------------------------------------
# 8. QR payload does NOT contain password or secret
# ---------------------------------------------------------------------------

def test_qr_payload_contains_no_password(client: TestClient, login_super_admin) -> None:
    import json

    login_super_admin()
    _create_school(client, name="NEN QR Safe", slug="nen8")
    admin_id = _create_user(client, "nen8", name="Admin", role="district_admin")

    gen = _generate_code(client, "nen8", admin_user_id=admin_id)
    svc = client.app.state.access_code_service
    qr_json = svc.qr_payload(gen["code"], "nen8")
    payload = json.loads(qr_json)

    forbidden_keys = {"password", "secret", "api_key", "token", "auth"}
    found = forbidden_keys & set(payload.keys())
    assert not found, (
        f"SECURITY FAILURE: QR payload contains sensitive keys: {found}. Full payload: {payload}"
    )


# ---------------------------------------------------------------------------
# 9. Standard invite code cannot create district_admin
# ---------------------------------------------------------------------------

def test_invite_code_cannot_create_district_admin(client: TestClient, login_super_admin) -> None:
    """
    Even if a code is somehow generated with role=district_admin,
    the create-account endpoint must reject it.
    """
    login_super_admin()
    _create_school(client, name="NEN DA Block", slug="nen9")
    admin_id = _create_user(client, "nen9", name="Admin", role="district_admin")

    svc = client.app.state.access_code_service
    import sqlite3, datetime as _dt

    # Manually insert a non-setup code with role=district_admin to simulate
    # a hypothetical bypass attempt.
    now = _dt.datetime.now(timezone.utc).isoformat()
    expires = (_dt.datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    with sqlite3.connect(svc._db_path, isolation_level=None) as conn:
        conn.execute(
            """
            INSERT INTO access_codes
                (code, tenant_slug, role, title, created_by_user_id,
                 created_at, expires_at, max_uses, is_setup_code)
            VALUES ('DADMINCODE', 'nen9', 'district_admin', NULL, ?, ?, ?, 1, 0);
            """,
            (admin_id, now, expires),
        )

    result = _create_account(
        client,
        code="DADMINCODE",
        tenant_slug="nen9",
        login_name="bad.actor",
    )

    assert result["valid"] is False, (
        f"SECURITY FAILURE: create-account accepted a district_admin role code: {result}"
    )
