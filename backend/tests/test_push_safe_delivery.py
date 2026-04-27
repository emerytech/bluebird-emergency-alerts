"""
Phase 3: Push safe delivery invariants.

Invariants under test:
  - Active user with a valid token receives the alert push.
  - Inactive (deactivated) user's token is excluded from the push, even if the token is valid.
  - A token marked is_valid=0 is excluded from the push.
  - A user whose session was revoked STILL receives the push (sessions and push are decoupled).
  - A user who logged out STILL receives the push (logout invalidates session, not token).
  - A token registered under a different tenant slug never appears in another tenant's push.
  - After a push failure with an invalidating reason, the token is marked is_valid=0.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers (mirrors test_push_isolation.py patterns)
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


def _register_device(
    client: TestClient,
    slug: str,
    *,
    token: str,
    user_id: int,
    platform: str = "android",
    push_provider: str = "fcm",
) -> None:
    resp = client.post(
        f"/{slug}/devices/register",
        headers={"X-API-Key": "test-api-key"},
        json={
            "device_token": token,
            "platform": platform,
            "push_provider": push_provider,
            "device_name": "Test Device",
            "user_id": user_id,
        },
    )
    assert resp.status_code == 200, resp.text


def _activate_alarm(client: TestClient, slug: str, *, user_id: int, message: str = "Lockdown") -> None:
    resp = client.post(
        f"/{slug}/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": message, "user_id": user_id},
    )
    assert resp.status_code == 200, resp.text


def _mobile_login(client: TestClient, slug: str, *, login_name: str, password: str) -> str:
    resp = client.post(
        f"/{slug}/auth/login",
        headers={"X-API-Key": "test-api-key"},
        json={"login_name": login_name, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json().get("session_token", ""))


def _all_tokens(calls: list) -> set[str]:
    return {token for (tokens, _msg) in calls for token in tokens}


def _tenant_ctx(client: TestClient, slug: str):
    school = client.app.state.tenant_manager.school_for_slug(slug)
    return client.app.state.tenant_manager.get(school)


# ---------------------------------------------------------------------------
# 1. Active user + valid token → receives alert
# ---------------------------------------------------------------------------

def test_active_user_receives_push(client: TestClient, login_super_admin, monkeypatch) -> None:
    """An active user with a registered token must receive the push."""
    login_super_admin()
    _create_school(client, name="Safe Delivery A", slug="safe-a")
    uid = _create_user(client, "safe-a", name="Active User", role="teacher")
    _register_device(client, "safe-a", token="fcm-active-token", user_id=uid)

    fcm_calls: list[tuple[list[str], str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)
    _activate_alarm(client, "safe-a", user_id=uid, message="Test lockdown")

    assert "fcm-active-token" in _all_tokens(fcm_calls), (
        "Active user's token must be included in push delivery"
    )


# ---------------------------------------------------------------------------
# 2. Inactive (deactivated) user → token excluded
# ---------------------------------------------------------------------------

def test_inactive_user_token_excluded_from_push(client: TestClient, login_super_admin, monkeypatch) -> None:
    """A deactivated user's device token must never receive an alert push."""
    login_super_admin()
    _create_school(client, name="Safe Delivery B", slug="safe-b")

    active_uid = _create_user(client, "safe-b", name="Active User", role="teacher")
    inactive_uid = _create_user(client, "safe-b", name="Inactive User", role="teacher")

    _register_device(client, "safe-b", token="fcm-active-token-b", user_id=active_uid)
    _register_device(client, "safe-b", token="fcm-inactive-token-b", user_id=inactive_uid)

    # Deactivate inactive_uid directly via UserStore
    tenant = _tenant_ctx(client,"safe-b")
    existing = asyncio.run(tenant.user_store.get_user(inactive_uid))
    assert existing is not None
    asyncio.run(tenant.user_store.update_user(
        user_id=inactive_uid,
        name=existing.name,
        role=existing.role,
        phone_e164=existing.phone_e164,
        is_active=False,
        login_name=existing.login_name,
        password=None,
        clear_login=False,
        title=existing.title,
    ))

    fcm_calls: list[tuple[list[str], str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)
    _activate_alarm(client, "safe-b", user_id=active_uid, message="Lockdown inactive test")

    sent = _all_tokens(fcm_calls)
    assert "fcm-active-token-b" in sent, "Active user must still receive push"
    assert "fcm-inactive-token-b" not in sent, (
        "ISOLATION FAILURE: deactivated user's token was included in the alarm push"
    )


# ---------------------------------------------------------------------------
# 3. is_valid=0 token → excluded from push
# ---------------------------------------------------------------------------

def test_invalid_token_excluded_from_push(client: TestClient, login_super_admin, monkeypatch) -> None:
    """A token marked is_valid=0 must not appear in any push delivery."""
    login_super_admin()
    _create_school(client, name="Safe Delivery C", slug="safe-c")

    uid = _create_user(client, "safe-c", name="User C", role="teacher")
    uid2 = _create_user(client, "safe-c", name="User C2", role="teacher")
    _register_device(client, "safe-c", token="fcm-invalid-token-c", user_id=uid)
    _register_device(client, "safe-c", token="fcm-valid-token-c", user_id=uid2)

    tenant = _tenant_ctx(client,"safe-c")
    asyncio.run(tenant.device_registry.mark_invalid("fcm-invalid-token-c", "fcm"))

    fcm_calls: list[tuple[list[str], str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)
    _activate_alarm(client, "safe-c", user_id=uid2, message="Invalid token test")

    sent = _all_tokens(fcm_calls)
    assert "fcm-valid-token-c" in sent, "Valid token must still be delivered"
    assert "fcm-invalid-token-c" not in sent, (
        "ISOLATION FAILURE: is_valid=0 token was included in the push"
    )


# ---------------------------------------------------------------------------
# 4. Logged-out user (session invalidated) STILL receives push
# ---------------------------------------------------------------------------

def test_logged_out_user_still_receives_push(client: TestClient, login_super_admin, monkeypatch) -> None:
    """Revoking a session must NOT affect push delivery — tokens and sessions are decoupled."""
    login_super_admin()
    _create_school(client, name="Safe Delivery D", slug="safe-d")

    uid = _create_user(client, "safe-d", name="User D", role="teacher")
    uid2 = _create_user(client, "safe-d", name="Alarm Trigger D", role="admin")
    _register_device(client, "safe-d", token="fcm-logged-out-d", user_id=uid)

    # Invalidate the user's session (simulating logout)
    tenant = _tenant_ctx(client,"safe-d")
    sessions = asyncio.run(tenant.session_store.list_active(user_id=uid))
    for s in sessions:
        asyncio.run(tenant.session_store.invalidate(s.session_token))

    fcm_calls: list[tuple[list[str], str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)
    _activate_alarm(client, "safe-d", user_id=uid2, message="Logout push decoupling test")

    assert "fcm-logged-out-d" in _all_tokens(fcm_calls), (
        "REGRESSION: logged-out user's token was excluded — sessions must not gate push delivery"
    )


# ---------------------------------------------------------------------------
# 5. Session revoked by admin STILL receives push
# ---------------------------------------------------------------------------

def test_revoked_session_user_still_receives_push(client: TestClient, login_super_admin, monkeypatch) -> None:
    """Force-revoking a session (admin action) must not suppress push delivery."""
    login_super_admin()
    _create_school(client, name="Safe Delivery E", slug="safe-e")

    uid = _create_user(client, "safe-e", name="User E", role="teacher")
    uid2 = _create_user(client, "safe-e", name="Trigger E", role="admin")
    _register_device(client, "safe-e", token="fcm-revoked-e", user_id=uid)

    tenant = _tenant_ctx(client,"safe-e")
    # Create and then immediately revoke a session by ID
    session = asyncio.run(tenant.session_store.create_session(user_id=uid, client_type="mobile"))
    asyncio.run(tenant.session_store.invalidate_by_id(session.id))

    fcm_calls: list[tuple[list[str], str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)
    _activate_alarm(client, "safe-e", user_id=uid2, message="Revoke push decoupling test")

    assert "fcm-revoked-e" in _all_tokens(fcm_calls), (
        "REGRESSION: session-revoked user's token was excluded — session state must not gate push"
    )


# ---------------------------------------------------------------------------
# 6. Wrong tenant → token never appears in another tenant's push
# ---------------------------------------------------------------------------

def test_cross_tenant_tokens_never_included(client: TestClient, login_super_admin, monkeypatch) -> None:
    """Tokens registered in tenant X must never be delivered for tenant Y's alarm."""
    login_super_admin()
    _create_school(client, name="Safe Tenant X", slug="safe-x")
    _create_school(client, name="Safe Tenant Y", slug="safe-y")

    uid_x = _create_user(client, "safe-x", name="User X", role="teacher")
    uid_y = _create_user(client, "safe-y", name="User Y", role="teacher")
    _register_device(client, "safe-x", token="fcm-tenant-x-token", user_id=uid_x)
    _register_device(client, "safe-y", token="fcm-tenant-y-token", user_id=uid_y)

    fcm_calls: list[tuple[list[str], str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)
    _activate_alarm(client, "safe-y", user_id=uid_y, message="Cross-tenant isolation test")

    sent = _all_tokens(fcm_calls)
    assert "fcm-tenant-y-token" in sent, "Tenant Y's token must be delivered"
    assert "fcm-tenant-x-token" not in sent, (
        "ISOLATION FAILURE: tenant X's token appeared in tenant Y's push delivery"
    )


# ---------------------------------------------------------------------------
# 7. APNs push failure with invalidating reason → token marked is_valid=0
# ---------------------------------------------------------------------------

def test_apns_failure_marks_token_invalid(client: TestClient, login_super_admin, monkeypatch) -> None:
    """After an APNs push returns BadDeviceToken, the registry must mark the token is_valid=0."""
    from app.services.apns import APNsSendResult

    login_super_admin()
    _create_school(client, name="Safe Delivery F", slug="safe-f")

    uid = _create_user(client, "safe-f", name="User F", role="teacher")

    # APNs token validation requires a hex string; register directly to bypass API validation.
    bad_apns_token = "a" * 64
    tenant = _tenant_ctx(client, "safe-f")
    asyncio.run(tenant.device_registry.register(
        token=bad_apns_token,
        platform="ios",
        push_provider="apns",
        device_name="Test iPhone",
        user_id=uid,
    ))

    bad_result = APNsSendResult(
        token=bad_apns_token,
        ok=False,
        status_code=400,
        reason="BadDeviceToken",
    )

    async def _fake_apns(tokens: list[str], message: str, extra_data=None):
        return [bad_result]

    monkeypatch.setattr(client.app.state.apns_client, "send_bulk", _fake_apns)

    # Trigger an alarm so the broadcaster fires
    _activate_alarm(client, "safe-f", user_id=uid, message="APNs failure test")

    # After broadcast, the token should be marked invalid — list_by_provider filters is_valid=1
    valid_devices = asyncio.run(tenant.device_registry.list_by_provider("apns"))
    valid_tokens = {d.token for d in valid_devices}
    assert bad_apns_token not in valid_tokens, (
        "Token with BadDeviceToken APNs failure must be marked is_valid=0 in the registry"
    )
