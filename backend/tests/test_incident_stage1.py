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
