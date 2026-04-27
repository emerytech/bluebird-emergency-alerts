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
    assert response.headers.get("location") == "/super-admin?section=schools#schools"


def _create_user(client: TestClient, slug: str, *, name: str, role: str) -> int:
    response = client.post(
        f"/{slug}/users",
        json={"name": name, "role": role, "phone_e164": None},
        headers={"X-API-Key": "test-api-key"},
    )
    assert response.status_code == 200
    return int(response.json()["user_id"])


def _register_android_device(client: TestClient, slug: str, *, token: str, user_id: int) -> None:
    response = client.post(
        f"/{slug}/devices/register",
        json={
            "device_token": token,
            "platform": "android",
            "push_provider": "fcm",
            "device_name": "Pytest Android",
            "user_id": user_id,
        },
        headers={"X-API-Key": "test-api-key"},
    )
    assert response.status_code == 200


def test_incident_routes_require_api_key(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Incident Guard", slug="incident-guard")
    admin_id = _create_user(client, "incident-guard", name="Guard Admin", role="admin")

    response = client.post(
        "/incident-guard/incidents/create",
        json={"type": "lockdown", "user_id": admin_id, "target_scope": "ALL", "metadata": {}},
    )
    assert response.status_code == 401


def test_create_incident_and_fetch_active_incidents(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Incident One", slug="incident-one")
    admin_id = _create_user(client, "incident-one", name="Admin One", role="admin")

    created = client.post(
        "/incident-one/incidents/create",
        json={
            "type": "lockdown",
            "user_id": admin_id,
            "target_scope": "ALL",
            "metadata": {"note": "Hallway event"},
        },
        headers={"X-API-Key": "test-api-key"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "active"
    assert body["type"] == "lockdown"
    assert body["school_id"] == "incident-one"

    active = client.get("/incident-one/incidents/active", headers={"X-API-Key": "test-api-key"})
    assert active.status_code == 200
    incidents = active.json()["incidents"]
    assert len(incidents) >= 1
    assert any(item["id"] == body["id"] for item in incidents)


def test_team_assist_create_and_active_fetch(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Assist One", slug="assist-one")
    teacher_id = _create_user(client, "assist-one", name="Teacher One", role="teacher")

    created = client.post(
        "/assist-one/team-assist/create",
        json={"type": "medical", "user_id": teacher_id, "assigned_team_ids": [101, 202]},
        headers={"X-API-Key": "test-api-key"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "active"
    assert body["assigned_team_ids"] == [101, 202]

    active = client.get("/assist-one/team-assist/active", headers={"X-API-Key": "test-api-key"})
    assert active.status_code == 200
    assists = active.json()["team_assists"]
    assert any(item["id"] == body["id"] for item in assists)


def test_request_help_alias_type_normalizes_from_team_assist(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Alias Help", slug="alias-help")
    teacher_id = _create_user(client, "alias-help", name="Alias Teacher", role="teacher")

    created = client.post(
        "/alias-help/team-assist/create",
        json={"type": "team_assist", "user_id": teacher_id, "assigned_team_ids": []},
        headers={"X-API-Key": "test-api-key"},
    )
    assert created.status_code == 200
    assert created.json()["type"] == "request_help"


def test_config_labels_endpoint_returns_feature_labels(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Labels School", slug="labels-school")
    response = client.get("/labels-school/config/labels", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    body = response.json()
    assert body["request_help"] == "Request Help"
    assert body["secure"] == "Secure Perimeter"


def test_admin_quiet_period_mobile_list_and_approve(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Quiet Mobile", slug="quiet-mobile")
    teacher_id = _create_user(client, "quiet-mobile", name="Quiet Officer", role="law_enforcement")
    admin_id = _create_user(client, "quiet-mobile", name="Quiet Admin", role="admin")

    created = client.post(
        "/quiet-mobile/quiet-periods/request",
        json={"user_id": teacher_id, "reason": "Taking an exam"},
        headers={"X-API-Key": "test-api-key"},
    )
    assert created.status_code == 200
    request_id = int(created.json()["request_id"])

    listing = client.get(
        f"/quiet-mobile/quiet-periods/admin/requests?admin_user_id={admin_id}",
        headers={"X-API-Key": "test-api-key"},
    )
    assert listing.status_code == 200
    rows = listing.json()["requests"]
    assert any(item["request_id"] == request_id and item["user_name"] == "Quiet Officer" for item in rows)

    approved = client.post(
        f"/quiet-mobile/quiet-periods/{request_id}/approve",
        json={"admin_user_id": admin_id},
        headers={"X-API-Key": "test-api-key"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_team_assist_admin_action_records_actor_label(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Assist Action", slug="assist-action")
    teacher_id = _create_user(client, "assist-action", name="Teacher Actor", role="teacher")
    admin_id = _create_user(client, "assist-action", name="Admin Actor", role="admin")

    created = client.post(
        "/assist-action/team-assist/create",
        json={"type": "medical", "user_id": teacher_id, "assigned_team_ids": [admin_id]},
        headers={"X-API-Key": "test-api-key"},
    )
    assert created.status_code == 200
    team_assist_id = int(created.json()["id"])

    action = client.post(
        f"/assist-action/team-assist/{team_assist_id}/action",
        json={"user_id": admin_id, "action": "resolve"},
        headers={"X-API-Key": "test-api-key"},
    )
    assert action.status_code == 200
    body = action.json()
    assert body["status"] == "resolved"
    assert body["acted_by_label"] == "Admin Actor"

    active_after = client.get("/assist-action/team-assist/active", headers={"X-API-Key": "test-api-key"})
    assert active_after.status_code == 200
    assert all(item["id"] != team_assist_id for item in active_after.json()["team_assists"])


def test_team_assist_requester_cancel_immediate(client: TestClient, login_super_admin) -> None:
    """Requester cancels their own request immediately — no dual confirmation required."""
    login_super_admin()
    _create_school(client, name="Assist Cancel", slug="assist-cancel")
    teacher_id = _create_user(client, "assist-cancel", name="Cancel Teacher", role="teacher")
    admin_id = _create_user(client, "assist-cancel", name="Cancel Admin", role="district_admin")

    created = client.post(
        "/assist-cancel/team-assist/create",
        json={"type": "fight", "user_id": teacher_id, "assigned_team_ids": [admin_id]},
        headers={"X-API-Key": "test-api-key"},
    )
    assert created.status_code == 200
    team_assist_id = int(created.json()["id"])

    # Single call by requester cancels immediately
    cancel_resp = client.post(
        f"/assist-cancel/team-assist/{team_assist_id}/cancel",
        json={"user_id": teacher_id, "cancel_reason_text": "Resolved on my own", "cancel_reason_category": "accidental"},
        headers={"X-API-Key": "test-api-key"},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"
    assert cancel_resp.json()["cancelled_by_user_id"] == teacher_id
    assert cancel_resp.json()["cancel_reason_text"] == "Resolved on my own"

    # Old dual-confirmation endpoint must be gone
    old_endpoint = client.post(
        f"/assist-cancel/team-assist/{team_assist_id}/cancel-confirm",
        json={"user_id": teacher_id},
        headers={"X-API-Key": "test-api-key"},
    )
    assert old_endpoint.status_code in {404, 405}, "cancel-confirm endpoint must no longer exist"


def test_incident_permission_guard_blocks_non_admin(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Guard Two", slug="guard-two")
    teacher_id = _create_user(client, "guard-two", name="Teacher Two", role="teacher")

    denied = client.post(
        "/guard-two/incidents/create",
        json={"type": "evacuate", "user_id": teacher_id, "target_scope": "ALL", "metadata": {}},
        headers={"X-API-Key": "test-api-key"},
    )
    assert denied.status_code == 403


def test_incident_creation_writes_notification_log(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Log School", slug="log-school")
    admin_id = _create_user(client, "log-school", name="Admin Log", role="admin")

    created = client.post(
        "/log-school/incidents/create",
        json={"type": "secure", "user_id": admin_id, "target_scope": "ALL", "metadata": {"source": "test"}},
        headers={"X-API-Key": "test-api-key"},
    )
    assert created.status_code == 200
    incident_id = int(created.json()["id"])

    school = client.app.state.tenant_manager.school_for_slug("log-school")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)
    logs = asyncio.run(tenant.incident_store.list_notification_logs(limit=20))
    assert any(log.type == "incident_created" and int(log.payload.get("incident_id", 0)) == incident_id for log in logs)


def test_team_assist_writes_targeted_notification_logs(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Assist Logs", slug="assist-logs")
    admin_id = _create_user(client, "assist-logs", name="Assist Admin", role="admin")
    teacher_id = _create_user(client, "assist-logs", name="Assist Teacher", role="teacher")

    created = client.post(
        "/assist-logs/team-assist/create",
        json={"type": "fight_in_progress", "user_id": teacher_id, "assigned_team_ids": [admin_id]},
        headers={"X-API-Key": "test-api-key"},
    )
    assert created.status_code == 200
    team_assist_id = int(created.json()["id"])

    school = client.app.state.tenant_manager.school_for_slug("assist-logs")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)
    logs = asyncio.run(tenant.incident_store.list_notification_logs(limit=50))
    assert any(
        log.type == "team_assist_targeted"
        and log.user_id == admin_id
        and int(log.payload.get("team_assist_id", 0)) == team_assist_id
        for log in logs
    )


def test_devices_register_alias_path(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Device Alias", slug="device-alias")
    admin_id = _create_user(client, "device-alias", name="Alias Admin", role="admin")

    response = client.post(
        "/device-alias/devices/register",
        json={
            "device_token": "device-token-123",
            "platform": "android",
            "push_provider": "fcm",
            "device_name": "Alias Device",
            "user_id": admin_id,
        },
        headers={"X-API-Key": "test-api-key"},
    )
    assert response.status_code == 200
    assert response.json()["registered"] is True


def test_incident_create_triggers_fcm_push(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    _create_school(client, name="Push Incident", slug="push-incident")
    admin_id = _create_user(client, "push-incident", name="Push Admin", role="admin")
    _register_android_device(client, "push-incident", token="fcm-incident-token", user_id=admin_id)

    push_calls: list[tuple[list[str], str]] = []

    async def _fake_send_bulk(tokens: list[str], message: str, extra_data: dict | None = None):
        push_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_send_bulk)

    response = client.post(
        "/push-incident/incidents/create",
        json={"type": "lockdown", "user_id": admin_id, "target_scope": "ALL", "metadata": {}},
        headers={"X-API-Key": "test-api-key"},
    )
    assert response.status_code == 200
    assert push_calls
    assert "fcm-incident-token" in push_calls[0][0]


def test_team_assist_push_targets_assigned_user_only(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    _create_school(client, name="Push Assist", slug="push-assist")
    teacher_id = _create_user(client, "push-assist", name="Assist Teacher", role="teacher")
    admin_id = _create_user(client, "push-assist", name="Assist Admin", role="admin")
    _register_android_device(client, "push-assist", token="fcm-teacher-token", user_id=teacher_id)
    _register_android_device(client, "push-assist", token="fcm-admin-token", user_id=admin_id)

    push_calls: list[tuple[list[str], str]] = []

    async def _fake_send_bulk(tokens: list[str], message: str, extra_data: dict | None = None):
        push_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_send_bulk)

    response = client.post(
        "/push-assist/team-assist/create",
        json={"type": "medical", "user_id": teacher_id, "assigned_team_ids": [admin_id]},
        headers={"X-API-Key": "test-api-key"},
    )
    assert response.status_code == 200
    assert push_calls
    sent_tokens = set(push_calls[0][0])
    assert "fcm-admin-token" in sent_tokens
    assert "fcm-teacher-token" not in sent_tokens
