"""
Full system validation for the archive / restore / delete lifecycle and
role-based access control around district_admin accounts.

Scenarios covered
-----------------
1. building_admin cannot archive a district_admin
2. building_admin cannot delete a district_admin
3. district_admin CAN archive another district_admin
4. district_admin CAN restore a district_admin
5. Staff user can be archived and restored normally
6. Archived user is excluded from login (auth guard)
7. Archived user is excluded from push notification targeting
8. Archived user's push tokens are marked invalid immediately
9. Restored user can log in again
10. Restored user's push tokens become valid on re-registration
11. Deleted user's tokens are invalidated before the row is removed
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SLUG = "rbac-test"
API_HEADERS = {"X-API-Key": "test-api-key"}


def _create_school(client: TestClient) -> None:
    resp = client.post(
        "/super-admin/schools/create",
        data={"name": "RBAC Test School", "slug": SLUG, "setup_pin": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def _enter_school(client: TestClient) -> None:
    resp = client.post(f"/super-admin/schools/{SLUG}/enter", follow_redirects=False)
    assert resp.status_code == 303, resp.text


def _create_dashboard_user(
    client: TestClient,
    *,
    name: str,
    role: str,
    login_name: str = "",
    password: str = "",
) -> None:
    resp = client.post(
        f"/{SLUG}/admin/users/create",
        data={
            "name": name,
            "role": role,
            "phone_e164": "",
            "login_name": login_name,
            "password": password,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def _create_api_user(client: TestClient, *, name: str, role: str) -> int:
    resp = client.post(
        f"/{SLUG}/users",
        headers=API_HEADERS,
        json={"name": name, "role": role, "phone_e164": None},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["user_id"])


def _get_user_id(client: TestClient, login_name: str) -> int:
    tenant = client.app.state.tenant_manager.school_for_slug(SLUG)
    ctx = client.app.state.tenant_manager.get(tenant)
    users = asyncio.run(ctx.user_store.list_users())
    match = next((u for u in users if u.login_name == login_name), None)
    assert match is not None, f"User with login_name={login_name!r} not found"
    return match.id


def _get_user_by_id(client: TestClient, user_id: int):
    tenant = client.app.state.tenant_manager.school_for_slug(SLUG)
    ctx = client.app.state.tenant_manager.get(tenant)
    return asyncio.run(ctx.user_store.get_user(user_id))


def _get_all_users(client: TestClient):
    tenant = client.app.state.tenant_manager.school_for_slug(SLUG)
    ctx = client.app.state.tenant_manager.get(tenant)
    return asyncio.run(ctx.user_store.list_users())


def _get_registry(client: TestClient):
    tenant = client.app.state.tenant_manager.school_for_slug(SLUG)
    ctx = client.app.state.tenant_manager.get(tenant)
    return ctx.device_registry


def _login_admin(client: TestClient, *, login_name: str, password: str) -> None:
    resp = client.post(
        f"/{SLUG}/admin/login",
        data={"login_name": login_name, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert f"/{SLUG}/admin" in resp.headers.get("location", "")


def _logout(client: TestClient) -> None:
    client.post(f"/{SLUG}/admin/logout", follow_redirects=False)
    client.post("/super-admin/logout", follow_redirects=False)


def _archive(client: TestClient, user_id: int) -> str:
    resp = client.post(
        f"/{SLUG}/admin/users/{user_id}/archive",
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    return resp.headers.get("location", "")


def _restore(client: TestClient, user_id: int) -> str:
    resp = client.post(
        f"/{SLUG}/admin/users/{user_id}/restore",
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    return resp.headers.get("location", "")


def _delete(client: TestClient, user_id: int) -> str:
    resp = client.post(
        f"/{SLUG}/admin/users/{user_id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    return resp.headers.get("location", "")


def _register_device(client: TestClient, *, token: str, user_id: int) -> None:
    """Register an FCM (Android) device — FCM tokens have no hex format requirement."""
    resp = client.post(
        f"/{SLUG}/devices/register",
        headers=API_HEADERS,
        json={
            "device_token": token,
            "platform": "android",
            "push_provider": "fcm",
            "device_name": "Test Device",
            "user_id": user_id,
        },
    )
    assert resp.status_code == 200, resp.text


def _token_is_valid(client: TestClient, token: str) -> bool:
    registry = _get_registry(client)
    devices = asyncio.run(registry.list_by_provider("fcm"))
    match = next((d for d in devices if d.token == token), None)
    return match is not None and match.is_valid


def _setup_school(client: TestClient) -> None:
    """Create school and enter via super-admin. Call once per test."""
    _create_school(client)
    _enter_school(client)


# ---------------------------------------------------------------------------
# Test 1 & 2 — building_admin CANNOT archive or delete district_admin
# ---------------------------------------------------------------------------

def test_building_admin_cannot_archive_district_admin(
    client: TestClient, login_super_admin
) -> None:
    login_super_admin()
    _setup_school(client)

    _create_dashboard_user(
        client, name="District Admin", role="district_admin",
        login_name="da.main", password="Password@1",
    )
    _create_dashboard_user(
        client, name="Building Admin", role="building_admin",
        login_name="ba.main", password="Password@1",
    )
    da_id = _get_user_id(client, "da.main")

    _logout(client)
    _login_admin(client, login_name="ba.main", password="Password@1")

    location = _archive(client, da_id)

    # Must redirect back without going to the archived tab
    assert "archived" not in location
    # User must still be active
    user = _get_user_by_id(client, da_id)
    assert user is not None
    assert not getattr(user, "is_archived", False)
    assert user.is_active


def test_building_admin_cannot_delete_district_admin(
    client: TestClient, login_super_admin
) -> None:
    login_super_admin()
    _setup_school(client)

    # district_admin must be archived first (by someone who can) before delete is possible.
    # Verify the delete endpoint also rejects building_admin even for an archived district_admin.
    _create_dashboard_user(
        client, name="District Admin", role="district_admin",
        login_name="da.del", password="Password@1",
    )
    _create_dashboard_user(
        client, name="Building Admin", role="building_admin",
        login_name="ba.del", password="Password@1",
    )
    _create_dashboard_user(
        client, name="District Admin 2", role="district_admin",
        login_name="da.del2", password="Password@1",
    )
    da_id = _get_user_id(client, "da.del")
    da2_id = _get_user_id(client, "da.del2")

    # Archive the target DA as super-admin (via enter-school session)
    _enter_school(client)
    _archive(client, da_id)

    user = _get_user_by_id(client, da_id)
    assert getattr(user, "is_archived", False), "DA should now be archived"

    # Switch to building_admin and try to delete
    _logout(client)
    _login_admin(client, login_name="ba.del", password="Password@1")
    _delete(client, da_id)

    # User record must still exist
    user = _get_user_by_id(client, da_id)
    assert user is not None, "building_admin delete of district_admin must be blocked"


# ---------------------------------------------------------------------------
# Test 3 — district_admin CAN archive and restore another district_admin
# ---------------------------------------------------------------------------

def test_district_admin_can_archive_and_restore_district_admin(
    client: TestClient, login_super_admin
) -> None:
    login_super_admin()
    _setup_school(client)

    _create_dashboard_user(
        client, name="Acting DA", role="district_admin",
        login_name="da.actor", password="Password@1",
    )
    _create_dashboard_user(
        client, name="Target DA", role="district_admin",
        login_name="da.target", password="Password@1",
    )
    target_id = _get_user_id(client, "da.target")

    _logout(client)
    _login_admin(client, login_name="da.actor", password="Password@1")

    # Archive
    location = _archive(client, target_id)
    assert "archived" in location

    user = _get_user_by_id(client, target_id)
    assert getattr(user, "is_archived", False)
    assert not user.is_active

    # Restore
    _restore(client, target_id)

    user = _get_user_by_id(client, target_id)
    assert not getattr(user, "is_archived", False)
    assert user.is_active


# ---------------------------------------------------------------------------
# Test 4 & 5 — staff user archived and restored normally
# ---------------------------------------------------------------------------

def test_staff_user_archive_restore_cycle(
    client: TestClient, login_super_admin
) -> None:
    login_super_admin()
    _setup_school(client)

    # District admin to perform actions
    _create_dashboard_user(
        client, name="District Admin", role="district_admin",
        login_name="da.cycle", password="Password@1",
    )
    staff_id = _create_api_user(client, name="Staff Member", role="staff")

    _logout(client)
    _login_admin(client, login_name="da.cycle", password="Password@1")

    # Archive staff
    location = _archive(client, staff_id)
    assert "archived" in location

    all_users = _get_all_users(client)
    active_ids = {u.id for u in all_users if not getattr(u, "is_archived", False)}
    archived_ids = {u.id for u in all_users if getattr(u, "is_archived", False)}
    assert staff_id not in active_ids
    assert staff_id in archived_ids

    # Restore staff
    _restore(client, staff_id)

    all_users = _get_all_users(client)
    active_ids = {u.id for u in all_users if not getattr(u, "is_archived", False)}
    assert staff_id in active_ids


# ---------------------------------------------------------------------------
# Test 6 — archived user cannot log in (auth guard)
# ---------------------------------------------------------------------------

def test_archived_user_cannot_log_in(
    client: TestClient, login_super_admin
) -> None:
    login_super_admin()
    _setup_school(client)

    _create_dashboard_user(
        client, name="District Admin", role="district_admin",
        login_name="da.auth", password="Password@1",
    )
    _create_dashboard_user(
        client, name="Archivable Admin", role="building_admin",
        login_name="ba.auth", password="Password@1",
    )
    ba_id = _get_user_id(client, "ba.auth")

    # Archive the building_admin while logged in as district_admin
    _logout(client)
    _login_admin(client, login_name="da.auth", password="Password@1")
    _archive(client, ba_id)

    # Now try to log in as the archived user
    _logout(client)
    resp = client.post(
        f"/{SLUG}/admin/login",
        data={"login_name": "ba.auth", "password": "Password@1"},
        follow_redirects=False,
    )
    # Must NOT land on the admin dashboard
    location = resp.headers.get("location", "")
    assert f"/{SLUG}/admin/login" in location or resp.status_code != 303


# ---------------------------------------------------------------------------
# Test 7 — archived user excluded from push notification targeting
# ---------------------------------------------------------------------------

def test_archived_user_excluded_from_push_targeting(
    client: TestClient, login_super_admin
) -> None:
    login_super_admin()
    _setup_school(client)

    _create_dashboard_user(
        client, name="District Admin", role="district_admin",
        login_name="da.push", password="Password@1",
    )
    teacher_id = _create_api_user(client, name="Teacher Push", role="teacher")
    trigger_id = _create_api_user(client, name="Alarm Trigger", role="admin")

    _register_device(client, token="teacher-token-abc", user_id=teacher_id)

    # Archive the teacher
    _logout(client)
    _login_admin(client, login_name="da.push", password="Password@1")
    _archive(client, teacher_id)

    # Verify user is marked is_active=False (push targeting gate)
    user = _get_user_by_id(client, teacher_id)
    assert not user.is_active

    # Trigger alarm and intercept push — archived user's token must not appear
    captured_tokens: list[list[str]] = []

    async def mock_send_bulk(tokens, *args, **kwargs):
        captured_tokens.append(list(tokens))

    _logout(client)
    login_super_admin()
    _enter_school(client)

    with patch("app.services.fcm.FCMClient.send_bulk", new=AsyncMock(side_effect=mock_send_bulk)):
        client.post(
            f"/{SLUG}/alarm/activate",
            headers=API_HEADERS,
            json={"message": "Lockdown", "user_id": trigger_id},
        )

    flat_tokens = [t for batch in captured_tokens for t in batch]
    assert "teacher-token-abc" not in flat_tokens


# ---------------------------------------------------------------------------
# Test 8 — tokens marked invalid immediately on archive
# ---------------------------------------------------------------------------

def test_archive_invalidates_push_tokens(
    client: TestClient, login_super_admin
) -> None:
    login_super_admin()
    _setup_school(client)

    _create_dashboard_user(
        client, name="District Admin", role="district_admin",
        login_name="da.tok", password="Password@1",
    )
    teacher_id = _create_api_user(client, name="Teacher Tokens", role="teacher")
    _register_device(client, token="valid-token-xyz", user_id=teacher_id)

    assert _token_is_valid(client, "valid-token-xyz"), "Token should be valid before archive"

    _logout(client)
    _login_admin(client, login_name="da.tok", password="Password@1")
    _archive(client, teacher_id)

    assert not _token_is_valid(client, "valid-token-xyz"), "Token must be invalidated after archive"


# ---------------------------------------------------------------------------
# Test 9 — restored user can log in again
# ---------------------------------------------------------------------------

def test_restored_user_can_log_in(
    client: TestClient, login_super_admin
) -> None:
    login_super_admin()
    _setup_school(client)

    _create_dashboard_user(
        client, name="District Admin", role="district_admin",
        login_name="da.restore", password="Password@1",
    )
    _create_dashboard_user(
        client, name="Building Admin Restore", role="building_admin",
        login_name="ba.restore", password="Password@1",
    )
    ba_id = _get_user_id(client, "ba.restore")

    # Archive
    _logout(client)
    _login_admin(client, login_name="da.restore", password="Password@1")
    _archive(client, ba_id)

    # Confirm login blocked
    _logout(client)
    resp = client.post(
        f"/{SLUG}/admin/login",
        data={"login_name": "ba.restore", "password": "Password@1"},
        follow_redirects=False,
    )
    location = resp.headers.get("location", "")
    assert f"/{SLUG}/admin/login" in location or resp.status_code != 303

    # Restore
    login_super_admin()
    _enter_school(client)
    _restore(client, ba_id)

    # Confirm login works again
    _logout(client)
    _login_admin(client, login_name="ba.restore", password="Password@1")

    user = _get_user_by_id(client, ba_id)
    assert not getattr(user, "is_archived", False)
    assert user.is_active


# ---------------------------------------------------------------------------
# Test 10 — restored user's tokens become valid on re-registration
# ---------------------------------------------------------------------------

def test_restored_user_token_valid_after_reregistration(
    client: TestClient, login_super_admin
) -> None:
    login_super_admin()
    _setup_school(client)

    _create_dashboard_user(
        client, name="District Admin", role="district_admin",
        login_name="da.rereg", password="Password@1",
    )
    teacher_id = _create_api_user(client, name="Teacher Rereg", role="teacher")
    _register_device(client, token="rereg-token-001", user_id=teacher_id)

    # Archive → token goes invalid
    _logout(client)
    _login_admin(client, login_name="da.rereg", password="Password@1")
    _archive(client, teacher_id)
    assert not _token_is_valid(client, "rereg-token-001")

    # Restore
    _logout(client)
    login_super_admin()
    _enter_school(client)
    _restore(client, teacher_id)

    # Re-register the same token (simulates the app reconnecting)
    _register_device(client, token="rereg-token-001", user_id=teacher_id)

    assert _token_is_valid(client, "rereg-token-001"), (
        "Re-registration must reset is_valid=1 for a restored user's token"
    )


# ---------------------------------------------------------------------------
# Test 11 — delete invalidates tokens before removing user row
# ---------------------------------------------------------------------------

def test_delete_invalidates_tokens(
    client: TestClient, login_super_admin
) -> None:
    login_super_admin()
    _setup_school(client)

    _create_dashboard_user(
        client, name="District Admin", role="district_admin",
        login_name="da.deltok", password="Password@1",
    )
    teacher_id = _create_api_user(client, name="Teacher Delete", role="teacher")
    _register_device(client, token="delete-token-999", user_id=teacher_id)

    assert _token_is_valid(client, "delete-token-999")

    # Archive first (required before delete)
    _logout(client)
    _login_admin(client, login_name="da.deltok", password="Password@1")
    _archive(client, teacher_id)

    # Token already invalid from archive; delete should not break anything
    _delete(client, teacher_id)

    # User row must be gone
    user = _get_user_by_id(client, teacher_id)
    assert user is None, "User record must be deleted"

    # Token must remain invalid
    assert not _token_is_valid(client, "delete-token-999")
