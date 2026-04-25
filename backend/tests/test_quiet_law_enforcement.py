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


def _create_user(client: TestClient, slug: str, *, name: str, role: str) -> int:
    response = client.post(
        f"/{slug}/users",
        headers={"X-API-Key": "test-api-key"},
        json={"name": name, "role": role, "phone_e164": None},
    )
    assert response.status_code == 200, response.text
    return int(response.json()["user_id"])


def _register_fcm(client: TestClient, slug: str, *, token: str, user_id: int) -> None:
    response = client.post(
        f"/{slug}/devices/register",
        headers={"X-API-Key": "test-api-key"},
        json={
            "device_token": token,
            "platform": "android",
            "push_provider": "fcm",
            "device_name": token,
            "user_id": user_id,
        },
    )
    assert response.status_code == 200, response.text


def test_law_enforcement_can_submit_quiet_request(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Law Quiet Submit", slug="law-quiet-submit")
    officer_id = _create_user(client, "law-quiet-submit", name="Officer Submit", role="law_enforcement")

    response = client.post(
        "/law-quiet-submit/quiet-periods/request",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": officer_id, "reason": "Sensitive operation"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"


def test_law_enforcement_cannot_approve_or_deny_quiet_requests(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Law Quiet Guard", slug="law-quiet-guard")
    officer_id = _create_user(client, "law-quiet-guard", name="Officer Guard", role="law_enforcement")
    admin_id = _create_user(client, "law-quiet-guard", name="Admin Guard", role="admin")

    request_response = client.post(
        "/law-quiet-guard/quiet-periods/request",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": officer_id, "reason": "Need quiet"},
    )
    assert request_response.status_code == 200, request_response.text
    request_id = int(request_response.json()["request_id"])

    deny_as_officer = client.post(
        f"/law-quiet-guard/quiet-periods/{request_id}/deny",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": officer_id},
    )
    assert deny_as_officer.status_code == 403

    approve_as_officer = client.post(
        f"/law-quiet-guard/quiet-periods/{request_id}/approve",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": officer_id},
    )
    assert approve_as_officer.status_code == 403

    approve_as_admin = client.post(
        f"/law-quiet-guard/quiet-periods/{request_id}/approve",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": admin_id},
    )
    assert approve_as_admin.status_code == 200, approve_as_admin.text


def test_admin_approval_sets_quiet_mode_active_state(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Law Quiet Active", slug="law-quiet-active")
    officer_id = _create_user(client, "law-quiet-active", name="Officer Active", role="law_enforcement")
    admin_id = _create_user(client, "law-quiet-active", name="Admin Active", role="admin")

    request_response = client.post(
        "/law-quiet-active/quiet-periods/request",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": officer_id, "reason": "Protect identity"},
    )
    assert request_response.status_code == 200, request_response.text
    request_id = int(request_response.json()["request_id"])

    approve = client.post(
        f"/law-quiet-active/quiet-periods/{request_id}/approve",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": admin_id},
    )
    assert approve.status_code == 200, approve.text

    status_response = client.get(
        f"/law-quiet-active/quiet-periods/status?user_id={officer_id}",
        headers={"X-API-Key": "test-api-key"},
    )
    assert status_response.status_code == 200, status_response.text
    body = status_response.json()
    assert body["status"] == "approved"
    assert body["quiet_mode_active"] is True


def test_quiet_mode_suppresses_assigned_tenant_alerts_for_user_only_without_duplicates(
    client: TestClient,
    login_super_admin,
) -> None:
    login_super_admin()
    _create_school(client, name="Quiet Home", slug="quiet-home")
    _create_school(client, name="Quiet Assigned", slug="quiet-assigned")

    # Home tenant users (quiet principal user_id will be 3).
    _create_user(client, "quiet-home", name="Home Filler 1", role="teacher")
    _create_user(client, "quiet-home", name="Home Filler 2", role="teacher")
    officer_id = _create_user(client, "quiet-home", name="Officer Quiet", role="law_enforcement")
    admin_id = _create_user(client, "quiet-home", name="Home Admin", role="admin")

    # Assigned tenant users; mirror user id=3 for the assigned officer context.
    _create_user(client, "quiet-assigned", name="Assigned Filler 1", role="teacher")
    _create_user(client, "quiet-assigned", name="Assigned Filler 2", role="teacher")
    mirrored_officer_id = _create_user(client, "quiet-assigned", name="Assigned Officer", role="teacher")
    other_user_id = _create_user(client, "quiet-assigned", name="Other User", role="teacher")
    assigned_admin_id = _create_user(client, "quiet-assigned", name="Assigned Admin", role="admin")
    assert mirrored_officer_id == officer_id

    home_school = client.app.state.tenant_manager.school_for_slug("quiet-home")
    assigned_school = client.app.state.tenant_manager.school_for_slug("quiet-assigned")
    assert home_school is not None
    assert assigned_school is not None
    asyncio.run(
        client.app.state.user_tenant_store.replace_assignments(
            user_id=officer_id,
            home_tenant_id=home_school.id,
            tenant_ids=[assigned_school.id],
        )
    )

    request_response = client.post(
        "/quiet-home/quiet-periods/request",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": officer_id, "reason": "Quiet across assignments"},
    )
    assert request_response.status_code == 200, request_response.text
    request_id = int(request_response.json()["request_id"])
    approve = client.post(
        f"/quiet-home/quiet-periods/{request_id}/approve",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": admin_id},
    )
    assert approve.status_code == 200, approve.text

    _register_fcm(client, "quiet-assigned", token="quiet-suppressed-token", user_id=mirrored_officer_id)
    _register_fcm(client, "quiet-assigned", token="other-user-token-1", user_id=other_user_id)
    _register_fcm(client, "quiet-assigned", token="other-user-token-2", user_id=other_user_id)

    panic = client.post(
        "/quiet-assigned/panic",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Assigned tenant alert", "user_id": assigned_admin_id},
    )
    assert panic.status_code == 200, panic.text
    payload = panic.json()
    assert payload["provider_attempts"]["fcm"] == 2
    assert payload["attempted"] == 2
