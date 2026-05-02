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


def test_super_admin_billing_panel_and_controls(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Billing Academy", slug="billing-academy")

    billing_page = client.get("/super-admin?section=billing", follow_redirects=False)
    assert billing_page.status_code == 200
    assert "Licensing" in billing_page.text
    assert "Generate License" in billing_page.text
    assert "Billing Academy" in billing_page.text

    start_trial = client.post(
        "/super-admin/schools/billing-academy/billing/start-trial",
        data={"duration_days": "30"},
        follow_redirects=False,
    )
    assert start_trial.status_code == 303
    assert start_trial.headers.get("location") == "/super-admin?section=billing#billing"

    grant_free = client.post(
        "/super-admin/schools/billing-academy/billing/grant-free",
        data={"free_reason": "Pilot campus"},
        follow_redirects=False,
    )
    assert grant_free.status_code == 303
    assert grant_free.headers.get("location") == "/super-admin?section=billing#billing"

    school = client.app.state.tenant_manager.school_for_slug("billing-academy")
    assert school is not None
    billing = asyncio.run(client.app.state.tenant_billing_store.get_tenant_billing(tenant_id=school.id))
    assert billing is not None
    assert billing.billing_status == "trial"
    assert billing.trial_end is not None
    assert billing.is_free_override is True
    assert billing.free_reason == "Pilot campus"

    remove_free = client.post(
        "/super-admin/schools/billing-academy/billing/remove-free",
        follow_redirects=False,
    )
    assert remove_free.status_code == 303
    assert remove_free.headers.get("location") == "/super-admin?section=billing#billing"

    updated = asyncio.run(client.app.state.tenant_billing_store.get_tenant_billing(tenant_id=school.id))
    assert updated is not None
    assert updated.is_free_override is False
    assert updated.free_reason is None


def test_super_admin_can_save_smtp_configuration(client: TestClient, login_super_admin) -> None:
    login_super_admin()

    page = client.get("/super-admin?section=configuration", follow_redirects=False)
    assert page.status_code == 200
    assert "Google Workspace SMTP" in page.text
    assert "smtp.gmail.com" in page.text

    response = client.post(
        "/super-admin/configuration/smtp",
        data={
            "smtp_host": "smtp.gmail.com",
            "smtp_port": "587",
            "smtp_username": "alerts@example.org",
            "smtp_password": "app-password-123",
            "smtp_from": "alerts@example.org",
            "smtp_use_tls": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers.get("location") == "/super-admin?section=configuration#configuration"

    smtp_config = client.app.state.email_service.smtp_config()
    assert smtp_config.configured is True
    assert smtp_config.host == "smtp.gmail.com"
    assert smtp_config.port == 587
    assert smtp_config.username == "alerts@example.org"
    assert smtp_config.from_address == "alerts@example.org"
    assert smtp_config.use_tls is True
    assert smtp_config.password_set is True


def test_super_admin_school_enter_and_exit_scope(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Oak Ridge", slug="oak-ridge")
    _enter_school(client, "oak-ridge")

    response = client.get("/oak-ridge/admin", follow_redirects=False)
    assert response.status_code == 200
    assert "Return to Super Admin" in response.text
    assert "operating inside" in response.text
    assert "<strong>Oak Ridge</strong>" in response.text

    response = client.post("/oak-ridge/admin/super-admin/exit", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/super-admin"

    response = client.get("/oak-ridge/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/oak-ridge/admin/login"


def test_super_admin_school_access_can_activate_alarm_without_tenant_user_id(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Signal Creek", slug="signal-creek")
    _enter_school(client, "signal-creek")

    activate = client.post(
        "/signal-creek/admin/alarm/activate",
        data={"message": "Platform-triggered alarm"},
        follow_redirects=False,
    )
    assert activate.status_code == 303
    assert activate.headers.get("location") == "/signal-creek/admin"

    status = client.get(
        "/signal-creek/alarm/status",
        headers={"X-API-Key": "test-api-key"},
    )
    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["is_active"] is True
    assert payload["message"] == "Platform-triggered alarm"


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
    assert response.headers.get("location") == "/river-valley/admin?section=quiet-periods#quiet-periods"

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
    assert response.headers.get("location") == "/north-point/admin?section=user-management#users"

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
    assert response.headers.get("location") == "/north-point/admin?section=quiet-periods#quiet-periods"

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
            "role": "law_enforcement",
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


def test_admin_can_send_message_to_single_user_or_all_users(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Pine Hill", slug="pine-hill")
    _enter_school(client, "pine-hill")

    for name in ("Admin One", "Teacher One", "Teacher Two"):
        role = "admin" if "Admin" in name else "teacher"
        login_name = "admin.one" if role == "admin" else ""
        password = "Password@123" if role == "admin" else ""
        created = client.post(
            "/pine-hill/admin/users/create",
            data={
                "name": name,
                "role": role,
                "phone_e164": "",
                "login_name": login_name,
                "password": password,
            },
            follow_redirects=False,
        )
        assert created.status_code == 303

    school = client.app.state.tenant_manager.school_for_slug("pine-hill")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)
    users = asyncio.run(tenant.user_store.list_users())
    admin = next(u for u in users if u.name == "Admin One")
    teacher_one = next(u for u in users if u.name == "Teacher One")
    teacher_two = next(u for u in users if u.name == "Teacher Two")

    single = client.post(
        "/pine-hill/messages/send",
        json={
            "admin_user_id": admin.id,
            "message": "Single recipient note",
            "recipient_user_id": teacher_one.id,
            "send_to_all": False,
        },
        headers={"X-API-Key": "test-api-key"},
    )
    assert single.status_code == 200
    assert single.json()["sent_count"] == 1

    inbox_one = client.get(
        f"/pine-hill/messages/inbox?user_id={teacher_one.id}&limit=20",
        headers={"X-API-Key": "test-api-key"},
    )
    assert inbox_one.status_code == 200
    assert any(item["message"] == "Single recipient note" for item in inbox_one.json()["messages"])

    inbox_two = client.get(
        f"/pine-hill/messages/inbox?user_id={teacher_two.id}&limit=20",
        headers={"X-API-Key": "test-api-key"},
    )
    assert inbox_two.status_code == 200
    assert not any(item["message"] == "Single recipient note" for item in inbox_two.json()["messages"])

    all_msg = client.post(
        "/pine-hill/messages/send",
        json={
            "admin_user_id": admin.id,
            "message": "All users note",
            "send_to_all": True,
        },
        headers={"X-API-Key": "test-api-key"},
    )
    assert all_msg.status_code == 200
    assert all_msg.json()["sent_count"] >= 2

    inbox_one_after = client.get(
        f"/pine-hill/messages/inbox?user_id={teacher_one.id}&limit=20",
        headers={"X-API-Key": "test-api-key"},
    )
    inbox_two_after = client.get(
        f"/pine-hill/messages/inbox?user_id={teacher_two.id}&limit=20",
        headers={"X-API-Key": "test-api-key"},
    )
    assert any(item["message"] == "All users note" for item in inbox_one_after.json()["messages"])
    assert any(item["message"] == "All users note" for item in inbox_two_after.json()["messages"])


def test_admin_console_can_clear_request_help_without_dual_consent(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Request Help Console", slug="request-help-console")
    _enter_school(client, "request-help-console")

    create_teacher = client.post(
        "/request-help-console/admin/users/create",
        data={
            "name": "Jordan Teacher",
            "role": "teacher",
            "phone_e164": "",
            "login_name": "",
            "password": "",
        },
        follow_redirects=False,
    )
    assert create_teacher.status_code == 303

    school = client.app.state.tenant_manager.school_for_slug("request-help-console")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)
    users = asyncio.run(tenant.user_store.list_users())
    teacher = next(u for u in users if u.name == "Jordan Teacher")

    created = client.post(
        "/request-help-console/team-assist/create",
        json={"type": "medical", "user_id": teacher.id, "assigned_team_ids": []},
        headers={"X-API-Key": "test-api-key"},
    )
    assert created.status_code == 200
    request_help_id = int(created.json()["id"])

    active_before = client.get("/request-help-console/team-assist/active", headers={"X-API-Key": "test-api-key"})
    assert active_before.status_code == 200
    assert any(item["id"] == request_help_id for item in active_before.json()["team_assists"])

    cleared = client.post(f"/request-help-console/admin/request-help/{request_help_id}/clear", follow_redirects=False)
    assert cleared.status_code == 303
    assert cleared.headers.get("location") == "/request-help-console/admin#request-help"

    active_after = client.get("/request-help-console/team-assist/active", headers={"X-API-Key": "test-api-key"})
    assert active_after.status_code == 200
    assert all(item["id"] != request_help_id for item in active_after.json()["team_assists"])
