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
    assert response.headers.get("location") == "/super-admin#schools"


def _enter_school(client: TestClient, slug: str) -> None:
    response = client.post(f"/super-admin/schools/{slug}/enter", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == f"/{slug}/admin"


def test_super_admin_guard_blocks_unauthenticated_requests(client: TestClient) -> None:
    response = client.get("/super-admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/super-admin/login"

    response = client.post("/super-admin/schools/create", data={"name": "A", "slug": "a"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/super-admin/login"


def test_super_admin_session_allows_dashboard_access(client: TestClient, login_super_admin) -> None:
    login_super_admin()

    response = client.get("/super-admin", follow_redirects=False)
    assert response.status_code == 200
    assert "BlueBird Super Admin" in response.text
    assert "Platform super-admin activity" in response.text


def test_super_admin_school_enter_and_exit_scope(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Oak Ridge", slug="oak-ridge")
    _enter_school(client, "oak-ridge")

    response = client.get("/oak-ridge/admin", follow_redirects=False)
    assert response.status_code == 200
    assert "Return to Super Admin" in response.text
    assert "operating inside <strong>Oak Ridge</strong>" in response.text

    response = client.post("/oak-ridge/admin/super-admin/exit", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/super-admin"

    response = client.get("/oak-ridge/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/oak-ridge/admin/login"


def test_quiet_period_removal_clears_active_pause_state(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="River Valley", slug="river-valley")
    _enter_school(client, "river-valley")

    response = client.post(
        "/river-valley/admin/users/create",
        data={
            "name": "Teacher One",
            "role": "teacher",
            "phone_e164": "",
            "login_name": "",
            "password": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    school = client.app.state.tenant_manager.school_for_slug("river-valley")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)
    users = asyncio.run(tenant.user_store.list_users())
    teacher = next(u for u in users if u.name == "Teacher One")

    response = client.post(
        "/river-valley/admin/quiet-periods/grant",
        data={"user_id": str(teacher.id), "reason": "Testing quiet period"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    active_before = set(asyncio.run(tenant.quiet_period_store.active_user_ids()))
    assert teacher.id in active_before

    recent = asyncio.run(tenant.quiet_period_store.list_recent(limit=10))
    approved = next(item for item in recent if item.user_id == teacher.id and item.status == "approved")

    response = client.post(f"/river-valley/admin/quiet-periods/{approved.id}/clear", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/river-valley/admin#quiet-periods"

    active_after = set(asyncio.run(tenant.quiet_period_store.active_user_ids()))
    assert teacher.id not in active_after

    updated = asyncio.run(tenant.quiet_period_store.list_recent(limit=10))
    cleared = next(item for item in updated if item.id == approved.id)
    assert cleared.status == "cleared"


def test_platform_audit_feed_endpoint_returns_labeled_human_readable_rows(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="North Point", slug="north-point")
    _enter_school(client, "north-point")

    response = client.post(
        "/north-point/admin/users/create",
        data={
            "name": "Avery Lane",
            "role": "teacher",
            "phone_e164": "",
            "login_name": "",
            "password": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers.get("location") == "/north-point/admin"

    school = client.app.state.tenant_manager.school_for_slug("north-point")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)
    users = asyncio.run(tenant.user_store.list_users())
    teacher = next(u for u in users if u.name == "Avery Lane")

    response = client.post(
        "/north-point/admin/quiet-periods/grant",
        data={"user_id": str(teacher.id), "reason": "Needs focus"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers.get("location") == "/north-point/admin#quiet-periods"

    response = client.get("/super-admin/audit-feed", follow_redirects=False)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    assert payload["count"] >= 1
    assert isinstance(payload["items"], list)
    row = next(item for item in payload["items"] if item["school"] == "North Point" and item["action"] == "Quiet period approved")
    assert set(row.keys()) == {"created_at", "school", "action", "actor", "details"}
    assert row["actor"] == "Platform Super Admin (superadmin)"
    assert "Avery Lane" in row["details"]
    assert "User #" not in row["details"]


def test_admin_message_inbox_and_reply_flow(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Cedar High", slug="cedar-high")
    _enter_school(client, "cedar-high")

    create_teacher = client.post(
        "/cedar-high/admin/users/create",
        data={
            "name": "Taylor Teacher",
            "role": "teacher",
            "phone_e164": "",
            "login_name": "",
            "password": "",
        },
        follow_redirects=False,
    )
    assert create_teacher.status_code == 303

    create_admin = client.post(
        "/cedar-high/admin/users/create",
        data={
            "name": "Alex Admin",
            "role": "admin",
            "phone_e164": "",
            "login_name": "alex.admin",
            "password": "Password@123",
        },
        follow_redirects=False,
    )
    assert create_admin.status_code == 303

    school = client.app.state.tenant_manager.school_for_slug("cedar-high")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)
    users = asyncio.run(tenant.user_store.list_users())
    teacher = next(u for u in users if u.name == "Taylor Teacher")
    admin = next(u for u in users if u.name == "Alex Admin")

    created = client.post(
        "/cedar-high/message-admin",
        json={"user_id": teacher.id, "message": "Need help by room 12"},
        headers={"X-API-Key": "test-api-key"},
    )
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["message"] == "Need help by room 12"
    message_id = int(created_body["message_id"])

    admin_inbox = client.get(
        f"/cedar-high/messages/inbox?user_id={admin.id}&limit=20",
        headers={"X-API-Key": "test-api-key"},
    )
    assert admin_inbox.status_code == 200
    admin_payload = admin_inbox.json()
    assert admin_payload["unread_count"] >= 1
    item = next(row for row in admin_payload["messages"] if int(row["message_id"]) == message_id)
    assert item["sender_label"] == "Taylor Teacher"
    assert item["status"] == "open"

    replied = client.post(
        "/cedar-high/messages/reply",
        json={
            "admin_user_id": admin.id,
            "message_id": message_id,
            "message": "Received. Help is on the way.",
        },
        headers={"X-API-Key": "test-api-key"},
    )
    assert replied.status_code == 200

    teacher_inbox = client.get(
        f"/cedar-high/messages/inbox?user_id={teacher.id}&limit=20",
        headers={"X-API-Key": "test-api-key"},
    )
    assert teacher_inbox.status_code == 200
    teacher_payload = teacher_inbox.json()
    teacher_item = next(row for row in teacher_payload["messages"] if int(row["message_id"]) == message_id)
    assert teacher_item["status"] == "answered"
    assert teacher_item["response_message"] == "Received. Help is on the way."


def test_user_can_delete_own_quiet_period_request(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Westfield", slug="westfield")
    _enter_school(client, "westfield")

    create_teacher = client.post(
        "/westfield/admin/users/create",
        data={
            "name": "Jamie Teacher",
            "role": "teacher",
            "phone_e164": "",
            "login_name": "",
            "password": "",
        },
        follow_redirects=False,
    )
    assert create_teacher.status_code == 303

    school = client.app.state.tenant_manager.school_for_slug("westfield")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)
    users = asyncio.run(tenant.user_store.list_users())
    teacher = next(u for u in users if u.name == "Jamie Teacher")

    requested = client.post(
        "/westfield/quiet-periods/request",
        json={"user_id": teacher.id, "reason": "Wedding day"},
        headers={"X-API-Key": "test-api-key"},
    )
    assert requested.status_code == 200
    request_id = int(requested.json()["request_id"])

    deleted = client.post(
        f"/westfield/quiet-periods/{request_id}/delete",
        json={"user_id": teacher.id},
        headers={"X-API-Key": "test-api-key"},
    )
    assert deleted.status_code == 200
    payload = deleted.json()
    assert payload["status"] == "cancelled"

    status_resp = client.get(
        f"/westfield/quiet-periods/status?user_id={teacher.id}",
        headers={"X-API-Key": "test-api-key"},
    )
    assert status_resp.status_code == 200
    status_body = status_resp.json()
    assert status_body["status"] == "cancelled"
