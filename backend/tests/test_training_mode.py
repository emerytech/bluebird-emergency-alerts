from __future__ import annotations

from fastapi.testclient import TestClient
from app.api import routes


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


def test_training_panic_skips_live_broadcast_and_marks_alarm_state(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Training School", slug="training-school")
    admin_id = _create_user(client, "training-school", name="Training Admin", role="admin")
    user_id = _create_user(client, "training-school", name="Teacher", role="teacher")
    _register_fcm(client, "training-school", token="training-token-1", user_id=user_id)

    response = client.post(
        "/training-school/panic",
        headers={"X-API-Key": "test-api-key"},
        json={
            "message": "Training drill",
            "user_id": admin_id,
            "is_training": True,
            "training_label": "This is a drill",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["attempted"] == 0
    assert payload["provider_attempts"]["apns"] == 0
    assert payload["provider_attempts"]["fcm"] == 0
    assert payload["sms_queued"] == 0

    status = client.get(
        "/training-school/alarm/status",
        headers={"X-API-Key": "test-api-key"},
    )
    assert status.status_code == 200, status.text
    state = status.json()
    assert state["is_active"] is True
    assert state["is_training"] is True
    assert state["training_label"] == "This is a drill"
    assert state["silent_audio"] is False


def test_training_panic_can_run_with_silent_alarm_audio(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Silent Training", slug="silent-training")
    admin_id = _create_user(client, "silent-training", name="Silent Admin", role="admin")

    response = client.post(
        "/silent-training/panic",
        headers={"X-API-Key": "test-api-key"},
        json={
            "message": "Silent training drill",
            "user_id": admin_id,
            "is_training": True,
            "training_label": "Quiet house test",
            "silent_audio": True,
        },
    )
    assert response.status_code == 200, response.text

    status = client.get(
        "/silent-training/alarm/status",
        headers={"X-API-Key": "test-api-key"},
    )
    assert status.status_code == 200, status.text
    state = status.json()
    assert state["is_active"] is True
    assert state["is_training"] is True
    assert state["silent_audio"] is True


def test_live_alarm_ignores_silent_audio_flag(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Live Silent Guard", slug="live-silent-guard")
    admin_id = _create_user(client, "live-silent-guard", name="Live Admin", role="admin")

    response = client.post(
        "/live-silent-guard/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={
            "message": "Live alarm should still use audio",
            "user_id": admin_id,
            "is_training": False,
            "silent_audio": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["silent_audio"] is False


def test_training_alert_requires_admin_role(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Training Guard", slug="training-guard")
    teacher_id = _create_user(client, "training-guard", name="Teacher", role="teacher")

    response = client.post(
        "/training-guard/panic",
        headers={"X-API-Key": "test-api-key"},
        json={
            "message": "Teacher training test",
            "user_id": teacher_id,
            "is_training": True,
        },
    )
    assert response.status_code == 403


def test_alert_feed_marks_training_metadata(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Training Feed", slug="training-feed")
    admin_id = _create_user(client, "training-feed", name="Feed Admin", role="admin")

    activate = client.post(
        "/training-feed/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={
            "message": "Alarm training mode",
            "user_id": admin_id,
            "is_training": True,
            "training_label": "Safety drill",
        },
    )
    assert activate.status_code == 200, activate.text
    assert activate.json()["is_training"] is True

    alerts = client.get(
        "/training-feed/alerts?limit=1",
        headers={"X-API-Key": "test-api-key"},
    )
    assert alerts.status_code == 200, alerts.text
    item = alerts.json()["alerts"][0]
    assert item["is_training"] is True
    assert item["training_label"] == "Safety drill"
    assert item["created_by_user_id"] == admin_id


def test_alarm_status_handles_legacy_state_without_is_training(
    client: TestClient,
    login_super_admin,
    monkeypatch,
) -> None:
    class LegacyAlarmState:
        is_active = True
        message = "Legacy alarm"
        training_label = None
        activated_at = None
        activated_by_user_id = None
        activated_by_label = None
        deactivated_at = None
        deactivated_by_user_id = None
        deactivated_by_label = None

    class FakeAlarmStore:
        async def get_state(self):
            return LegacyAlarmState()

    login_super_admin()
    _create_school(client, name="Legacy Alarm", slug="legacy-alarm")
    monkeypatch.setattr(routes, "_alarm_store", lambda _request: FakeAlarmStore())

    response = client.get(
        "/legacy-alarm/alarm/status",
        headers={"X-API-Key": "test-api-key"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["is_active"] is True
    assert payload["message"] == "Legacy alarm"
    assert payload["is_training"] is False
