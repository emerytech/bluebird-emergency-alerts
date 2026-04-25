from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


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


def test_alarm_deactivate_permission_matrix(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Alarm Role Matrix", slug="alarm-role-matrix")

    teacher_id = _create_user(client, "alarm-role-matrix", name="Teacher", role="teacher")
    officer_id = _create_user(client, "alarm-role-matrix", name="Officer", role="law_enforcement")
    admin_id = _create_user(client, "alarm-role-matrix", name="Admin", role="admin")
    district_admin_id = _create_user(client, "alarm-role-matrix", name="District", role="district_admin")

    activate = client.post(
        "/alarm-role-matrix/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Test alarm", "user_id": admin_id},
    )
    assert activate.status_code == 200, activate.text
    assert activate.json()["is_active"] is True

    teacher_attempt = client.post(
        "/alarm-role-matrix/alarm/deactivate",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": teacher_id},
    )
    assert teacher_attempt.status_code == 403

    officer_attempt = client.post(
        "/alarm-role-matrix/alarm/deactivate",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": officer_id},
    )
    assert officer_attempt.status_code == 403

    district_attempt = client.post(
        "/alarm-role-matrix/alarm/deactivate",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": district_admin_id},
    )
    assert district_attempt.status_code == 200, district_attempt.text
    assert district_attempt.json()["is_active"] is False

    activate_again = client.post(
        "/alarm-role-matrix/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Test alarm 2", "user_id": admin_id},
    )
    assert activate_again.status_code == 200, activate_again.text
    assert activate_again.json()["is_active"] is True

    admin_attempt = client.post(
        "/alarm-role-matrix/alarm/deactivate",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": admin_id},
    )
    assert admin_attempt.status_code == 200, admin_attempt.text
    assert admin_attempt.json()["is_active"] is False

    status = client.get(
        "/alarm-role-matrix/alarm/status",
        headers={"X-API-Key": "test-api-key"},
    )
    assert status.status_code == 200, status.text
    assert status.json()["is_active"] is False


def test_alarm_activate_allows_any_active_user_role(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Alarm Trigger Matrix", slug="alarm-trigger-matrix")

    teacher_id = _create_user(client, "alarm-trigger-matrix", name="Teacher", role="teacher")
    officer_id = _create_user(client, "alarm-trigger-matrix", name="Officer", role="law_enforcement")
    admin_id = _create_user(client, "alarm-trigger-matrix", name="Admin", role="admin")

    teacher_activate = client.post(
        "/alarm-trigger-matrix/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Teacher alarm", "user_id": teacher_id},
    )
    assert teacher_activate.status_code == 200, teacher_activate.text
    assert teacher_activate.json()["is_active"] is True

    teacher_disable_attempt = client.post(
        "/alarm-trigger-matrix/alarm/deactivate",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": teacher_id},
    )
    assert teacher_disable_attempt.status_code == 403

    clear_after_teacher = client.post(
        "/alarm-trigger-matrix/alarm/deactivate",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": admin_id},
    )
    assert clear_after_teacher.status_code == 200, clear_after_teacher.text
    assert clear_after_teacher.json()["is_active"] is False

    officer_activate = client.post(
        "/alarm-trigger-matrix/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Officer alarm", "user_id": officer_id},
    )
    assert officer_activate.status_code == 200, officer_activate.text
    assert officer_activate.json()["is_active"] is True


def test_alarm_activate_rejects_user_not_in_current_tenant(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Member Home", slug="member-home")
    _create_school(client, name="Member Other", slug="member-other")

    home_teacher_id = _create_user(client, "member-home", name="Home Teacher", role="teacher")

    cross_tenant_attempt = client.post(
        "/member-other/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Cross tenant trigger", "user_id": home_teacher_id},
    )
    assert cross_tenant_attempt.status_code == 403
    assert "this tenant" in cross_tenant_attempt.text
