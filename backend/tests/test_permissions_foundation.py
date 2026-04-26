from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.permissions import (
    PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS,
    PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS,
    PERM_REQUEST_HELP,
    PERM_SUBMIT_QUIET_REQUEST,
    PERM_TRIGGER_OWN_TENANT_ALERTS,
    can,
)


def _create_school(client: TestClient, *, name: str, slug: str) -> None:
    response = client.post(
        "/super-admin/schools/create",
        data={"name": name, "slug": slug},
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


def test_permissions_matrix_foundation_flags() -> None:
    assert can("teacher", PERM_REQUEST_HELP)
    assert not can("teacher", PERM_SUBMIT_QUIET_REQUEST)

    assert can("law_enforcement", PERM_REQUEST_HELP)
    assert can("law_enforcement", PERM_SUBMIT_QUIET_REQUEST)
    assert not can("law_enforcement", PERM_APPROVE_OWN_TENANT_QUIET_REQUESTS)

    assert can("admin", PERM_TRIGGER_OWN_TENANT_ALERTS)
    assert can("district_admin", PERM_TRIGGER_OWN_TENANT_ALERTS)
    assert can("district_admin", PERM_APPROVE_ASSIGNED_TENANT_QUIET_REQUESTS)


def test_law_enforcement_can_request_help_and_submit_quiet_request(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Law Support", slug="law-support")
    officer_id = _create_user(client, "law-support", name="Officer One", role="law_enforcement")

    help_response = client.post(
        "/law-support/request-help/create",
        headers={"X-API-Key": "test-api-key"},
        json={"type": "medical_assistance", "user_id": officer_id, "assigned_team_ids": []},
    )
    assert help_response.status_code == 200, help_response.text

    quiet_response = client.post(
        "/law-support/quiet-periods/request",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": officer_id, "reason": "Sensitive on-scene operation"},
    )
    assert quiet_response.status_code == 200, quiet_response.text
    assert quiet_response.json()["status"] == "pending"


def test_any_active_user_can_submit_quiet_request(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Teacher Quiet Guard", slug="teacher-quiet-guard")
    teacher_id = _create_user(client, "teacher-quiet-guard", name="Teacher One", role="teacher")
    staff_id = _create_user(client, "teacher-quiet-guard", name="Staff One", role="staff")

    for user_id in (teacher_id, staff_id):
        r = client.post(
            "/teacher-quiet-guard/quiet-periods/request",
            headers={"X-API-Key": "test-api-key"},
            json={"user_id": user_id, "reason": "Optional reason"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending"


def test_admin_cannot_approve_own_quiet_request(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Self Approve Guard", slug="self-approve-guard")
    admin_id = _create_user(client, "self-approve-guard", name="Admin One", role="admin")

    request_response = client.post(
        "/self-approve-guard/quiet-periods/request",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": admin_id, "reason": "Admin requesting own quiet"},
    )
    assert request_response.status_code == 200, request_response.text
    request_id = int(request_response.json()["request_id"])

    approve_response = client.post(
        f"/self-approve-guard/quiet-periods/{request_id}/approve",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": admin_id},
    )
    assert approve_response.status_code == 403

    deny_response = client.post(
        f"/self-approve-guard/quiet-periods/{request_id}/deny",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": admin_id},
    )
    assert deny_response.status_code == 403


def test_district_admin_can_manage_incidents_and_quiet_approval(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="District Ops", slug="district-ops")
    district_admin_id = _create_user(client, "district-ops", name="District Admin", role="district_admin")
    officer_id = _create_user(client, "district-ops", name="Officer Two", role="law_enforcement")

    request_response = client.post(
        "/district-ops/quiet-periods/request",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": officer_id, "reason": "Investigation in progress"},
    )
    assert request_response.status_code == 200, request_response.text
    request_id = int(request_response.json()["request_id"])

    approve_response = client.post(
        f"/district-ops/quiet-periods/{request_id}/approve",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": district_admin_id},
    )
    assert approve_response.status_code == 200, approve_response.text
    assert approve_response.json()["status"] == "approved"

    incident_response = client.post(
        "/district-ops/incidents/create",
        headers={"X-API-Key": "test-api-key"},
        json={"type": "lockdown", "user_id": district_admin_id, "target_scope": "ALL", "metadata": {}},
    )
    assert incident_response.status_code == 200, incident_response.text


def test_law_enforcement_cannot_approve_quiet_requests(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Law Approval Guard", slug="law-approval-guard")
    officer_id = _create_user(client, "law-approval-guard", name="Officer Three", role="law_enforcement")
    district_admin_id = _create_user(client, "law-approval-guard", name="District Admin Two", role="district_admin")

    request_response = client.post(
        "/law-approval-guard/quiet-periods/request",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": officer_id, "reason": "Need quiet mode"},
    )
    assert request_response.status_code == 200, request_response.text
    request_id = int(request_response.json()["request_id"])

    deny_response = client.post(
        f"/law-approval-guard/quiet-periods/{request_id}/deny",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": officer_id},
    )
    assert deny_response.status_code == 403

    approve_response = client.post(
        f"/law-approval-guard/quiet-periods/{request_id}/approve",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": district_admin_id},
    )
    assert approve_response.status_code == 200, approve_response.text
