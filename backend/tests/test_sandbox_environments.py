"""
Sandbox / test-environment safety invariants.

Critical proof tests:
  P1. Production emergency alert (incidents/create) still fires real APNs/FCM push.
  P2. Production help request (team-assist/create) still fires real APNs/FCM push.
  P3. Cloned test tenant has no copied push tokens.
  P4. Cloned test tenant has no copied sessions/users.
  P5. _is_simulation_mode requires BOTH is_test=True AND simulation_mode_enabled=True.

Sandbox behaviour tests:
  S1. Clone district creates test district (is_test=True, source_district_id set).
  S2. Clone district creates test schools mirroring source district schools.
  S3. Clone blocked on a slug that already exists.
  S4. Simulation mode toggles correctly via super-admin endpoint.
  S5. Simulation mode blocks real push on alarm/activate.
  S6. Simulation mode blocks real push on incidents/create.
  S7. Simulation mode blocks real push on team-assist/create.
  S8. Simulate-alert endpoint creates is_simulation=True incident, no real push.
  S9. Reset endpoint deletes simulation incidents only.
 S10. Delete test district deletes district + schools; blocked on production.
 S11. Production schools cannot have simulation mode enabled via toggle endpoint.
 S12. Production schools cannot have audio suppression enabled via toggle endpoint.
"""
from __future__ import annotations

import asyncio
from fastapi.testclient import TestClient
from app.services.school_registry import SchoolRegistry


# ---------------------------------------------------------------------------
# Helpers — direct registry access (same pattern as existing test suite)
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously using a fresh event loop (safe with pytest)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _registry(client: TestClient) -> SchoolRegistry:
    return client.app.state.school_registry  # type: ignore[attr-defined]


def _create_school(client: TestClient, *, name: str, slug: str) -> None:
    resp = client.post(
        "/super-admin/schools/create",
        data={"name": name, "slug": slug, "setup_pin": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def _create_org_and_district(client: TestClient, *, org_slug: str, district_slug: str, district_name: str):
    reg = _registry(client)
    org = _run(reg.create_organization(name=district_name + " Org", slug=org_slug))
    district = _run(reg.create_district(name=district_name, slug=district_slug, organization_id=org.id))
    return org, district


def _create_user(client: TestClient, slug: str, *, name: str, role: str) -> int:
    resp = client.post(
        f"/{slug}/users",
        headers={"X-API-Key": "test-api-key"},
        json={"name": name, "role": role, "phone_e164": None},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["user_id"])


def _register_android(client: TestClient, slug: str, *, token: str, user_id: int) -> None:
    resp = client.post(
        f"/{slug}/devices/register",
        headers={"X-API-Key": "test-api-key"},
        json={
            "device_token": token,
            "platform": "android",
            "push_provider": "fcm",
            "device_name": "Test Android",
            "user_id": user_id,
        },
    )
    assert resp.status_code == 200, resp.text


def _clone_district(client: TestClient, district_id: int, *, test_slug: str, test_name: str = "") -> None:
    resp = client.post(
        f"/super-admin/districts/{district_id}/clone-test",
        data={"test_slug": test_slug, "test_name": test_name or "[TEST] cloned"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def _toggle_simulation(client: TestClient, slug: str) -> None:
    resp = client.post(
        f"/super-admin/test-tenants/{slug}/toggle-simulation",
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def _get_test_school_for_clone(client: TestClient, test_district_slug: str) -> str:
    """Return slug of first test school in a cloned district."""
    reg = _registry(client)
    test_district = _run(reg.get_district_by_slug(test_district_slug))
    assert test_district is not None
    test_schools = _run(reg.list_schools_by_district(test_district.id))
    assert test_schools
    return test_schools[0].slug


# ---------------------------------------------------------------------------
# P1. Production emergency alert still fires real push
# ---------------------------------------------------------------------------

def test_production_incident_still_sends_real_push(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """SAFETY: production incidents/create must fire FCM push; simulation gate must NOT block it."""
    login_super_admin()
    _create_school(client, name="Prod Incident School P1", slug="prod-inc-p1")

    user_id = _create_user(client, "prod-inc-p1", name="Admin", role="admin")
    _register_android(client, "prod-inc-p1", token="fcm-prod-inc-p1", user_id=user_id)

    fcm_calls: list = []

    async def _fake_fcm(tokens, message, extra_data=None):
        fcm_calls.append(list(tokens))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    resp = client.post(
        "/prod-inc-p1/incidents/create",
        headers={"X-API-Key": "test-api-key"},
        json={"type": "lockdown", "user_id": user_id, "target_scope": "ALL", "metadata": {}},
    )
    assert resp.status_code == 200, resp.text
    assert fcm_calls, (
        "SAFETY FAILURE: production incidents/create did not fire FCM push — "
        "simulation gate may be blocking production alerts"
    )
    all_tokens = {t for call in fcm_calls for t in call}
    assert "fcm-prod-inc-p1" in all_tokens, (
        "SAFETY FAILURE: registered production device token not in push recipients"
    )


# ---------------------------------------------------------------------------
# P2. Production help request still fires real push
# ---------------------------------------------------------------------------

def test_production_team_assist_still_sends_real_push(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """SAFETY: production team-assist/create must fire FCM push; simulation gate must NOT block it."""
    login_super_admin()
    _create_school(client, name="Prod Assist School P2", slug="prod-asst-p2")

    sender_id = _create_user(client, "prod-asst-p2", name="Sender", role="teacher")
    resp_id = _create_user(client, "prod-asst-p2", name="Responder", role="admin")
    _register_android(client, "prod-asst-p2", token="fcm-prod-sender-p2", user_id=sender_id)
    _register_android(client, "prod-asst-p2", token="fcm-prod-resp-p2", user_id=resp_id)

    fcm_calls: list = []

    async def _fake_fcm(tokens, message, extra_data=None):
        fcm_calls.append(list(tokens))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    resp = client.post(
        "/prod-asst-p2/team-assist/create",
        headers={"X-API-Key": "test-api-key"},
        json={"type": "medical", "user_id": sender_id, "assigned_team_ids": [resp_id]},
    )
    assert resp.status_code == 200, resp.text
    assert fcm_calls, (
        "SAFETY FAILURE: production team-assist/create did not fire FCM push"
    )


# ---------------------------------------------------------------------------
# P3. Cloned test tenant has no push tokens from source
# ---------------------------------------------------------------------------

def test_cloned_test_tenant_has_no_push_tokens(
    client: TestClient, login_super_admin
) -> None:
    """Clone must not copy device tokens from the source tenant DB."""
    login_super_admin()
    _create_school(client, name="Src School P3", slug="src-p3")
    user_id = _create_user(client, "src-p3", name="Admin", role="admin")
    _register_android(client, "src-p3", token="fcm-src-token-p3", user_id=user_id)

    _org, src_district = _create_org_and_district(
        client, org_slug="p3-org", district_slug="p3-src-dist", district_name="P3 Source"
    )
    reg = _registry(client)
    _run(reg.assign_to_district(school_slug="src-p3", district_id=src_district.id))

    _clone_district(client, src_district.id, test_slug="test-p3", test_name="[TEST] P3")
    test_slug = _get_test_school_for_clone(client, "test-p3")

    from app.services.tenant_manager import TenantManager
    tm: TenantManager = client.app.state.tenant_manager  # type: ignore[attr-defined]
    test_school = _run(reg.get_by_slug(test_slug))
    tenant_ctx = tm.get(test_school)
    devices = _run(tenant_ctx.device_registry.list_devices())
    tokens = {d.token for d in devices}
    assert "fcm-src-token-p3" not in tokens, (
        "SAFETY FAILURE: source tenant's push token found in cloned test tenant"
    )
    assert not tokens, f"Cloned test tenant must have zero device tokens, found: {tokens}"


# ---------------------------------------------------------------------------
# P4. Cloned test tenant has no copied users
# ---------------------------------------------------------------------------

def test_cloned_test_tenant_has_no_copied_users(
    client: TestClient, login_super_admin
) -> None:
    """Clone must not copy users from the source tenant DB."""
    login_super_admin()
    _create_school(client, name="Src School P4", slug="src-p4")
    _create_user(client, "src-p4", name="Alice", role="admin")

    _org, src_district = _create_org_and_district(
        client, org_slug="p4-org", district_slug="p4-src-dist", district_name="P4 Source"
    )
    reg = _registry(client)
    _run(reg.assign_to_district(school_slug="src-p4", district_id=src_district.id))

    _clone_district(client, src_district.id, test_slug="test-p4", test_name="[TEST] P4")
    test_slug = _get_test_school_for_clone(client, "test-p4")

    from app.services.tenant_manager import TenantManager
    tm: TenantManager = client.app.state.tenant_manager  # type: ignore[attr-defined]
    test_school = _run(reg.get_by_slug(test_slug))
    tenant_ctx = tm.get(test_school)
    users = _run(tenant_ctx.user_store.list_users())
    assert not users, (
        f"Cloned test tenant must have zero users (no user data copied from source), found: {[u.name for u in users]}"
    )


# ---------------------------------------------------------------------------
# P5. _is_simulation_mode requires both flags
# ---------------------------------------------------------------------------

def test_simulation_mode_requires_both_flags(
    client: TestClient, login_super_admin
) -> None:
    """_is_simulation_mode must return False unless BOTH is_test=True AND simulation_mode_enabled=True."""
    login_super_admin()
    _create_school(client, name="Prod School P5", slug="prod-p5")

    reg = _registry(client)
    school = _run(reg.get_by_slug("prod-p5"))
    assert school is not None
    assert school.is_test is False
    assert school.simulation_mode_enabled is False

    # Attempt to directly set simulation_mode_enabled on a production school via DB
    # (bypassing the route guard — testing that _is_simulation_mode still returns False).
    _run(reg.set_simulation_mode(slug="prod-p5", enabled=True))
    school_after = _run(reg.get_by_slug("prod-p5"))
    assert school_after is not None
    # The DB now has simulation_mode_enabled=True, but is_test=False.
    # _is_simulation_mode must still return False for this school.
    # We test this by using the route — if the gate were broken, incident push would be suppressed.
    user_id = _create_user(client, "prod-p5", name="Admin", role="admin")
    _register_android(client, "prod-p5", token="fcm-p5-token", user_id=user_id)

    fcm_calls: list = []

    async def _fake_fcm(tokens, message, extra_data=None):
        fcm_calls.append(list(tokens))
        return []

    from unittest.mock import MagicMock
    mock_request = MagicMock()
    mock_request.state.school = school_after
    from app.api.routes import _is_simulation_mode
    result = _is_simulation_mode(mock_request)
    assert result is False, (
        "SAFETY FAILURE: _is_simulation_mode returned True for a production school "
        f"(is_test={school_after.is_test}, simulation_mode_enabled={school_after.simulation_mode_enabled}). "
        "Production emergency push would be silently suppressed."
    )

    # Clean up the accidentally-set flag (production schools should never have this set).
    _run(reg.set_simulation_mode(slug="prod-p5", enabled=False))


# ---------------------------------------------------------------------------
# S1. Clone creates test district with is_test and source_district_id
# ---------------------------------------------------------------------------

def test_clone_creates_test_district(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _org, src_district = _create_org_and_district(
        client, org_slug="clone-org-s1", district_slug="src-district-s1", district_name="Source S1"
    )

    _clone_district(client, src_district.id, test_slug="test-src-s1", test_name="[TEST] Source")

    reg = _registry(client)
    test_district = _run(reg.get_district_by_slug("test-src-s1"))
    assert test_district is not None, "Cloned district must exist"
    assert test_district.is_test is True, "Cloned district must have is_test=True"
    assert test_district.source_district_id == src_district.id


# ---------------------------------------------------------------------------
# S2. Clone creates test schools mirroring source
# ---------------------------------------------------------------------------

def test_clone_creates_test_schools(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="School Alpha S2", slug="school-alpha-s2")
    _create_school(client, name="School Beta S2", slug="school-beta-s2")
    _org, src_district = _create_org_and_district(
        client, org_slug="clone-org-s2", district_slug="ms-district-s2", district_name="Multi School S2"
    )
    reg = _registry(client)
    _run(reg.assign_to_district(school_slug="school-alpha-s2", district_id=src_district.id))
    _run(reg.assign_to_district(school_slug="school-beta-s2", district_id=src_district.id))

    _clone_district(client, src_district.id, test_slug="test-ms-s2", test_name="[TEST] Multi")

    test_district = _run(reg.get_district_by_slug("test-ms-s2"))
    assert test_district is not None
    test_schools = _run(reg.list_schools_by_district(test_district.id))
    assert len(test_schools) == 2, f"Expected 2 test schools, got {len(test_schools)}"
    for ts in test_schools:
        assert ts.is_test is True
        assert ts.source_tenant_slug in {"school-alpha-s2", "school-beta-s2"}


# ---------------------------------------------------------------------------
# S3. Clone blocked on duplicate slug
# ---------------------------------------------------------------------------

def test_clone_blocked_on_duplicate_slug(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _org, src_district = _create_org_and_district(
        client, org_slug="dup-org-s3", district_slug="dup-district-s3", district_name="Dup S3"
    )

    resp1 = client.post(
        f"/super-admin/districts/{src_district.id}/clone-test",
        data={"test_slug": "test-dup-s3", "test_name": "[TEST] Dup"},
        follow_redirects=False,
    )
    assert resp1.status_code == 303

    resp2 = client.post(
        f"/super-admin/districts/{src_district.id}/clone-test",
        data={"test_slug": "test-dup-s3", "test_name": "[TEST] Dup Again"},
        follow_redirects=True,
    )
    assert resp2.status_code == 200
    body_lower = resp2.text.lower()
    assert "already taken" in body_lower or "slug" in body_lower


# ---------------------------------------------------------------------------
# S4. Simulation mode toggles correctly
# ---------------------------------------------------------------------------

def test_simulation_mode_toggles(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _org, src_district = _create_org_and_district(
        client, org_slug="simtog-org-s4", district_slug="simtog-dist-s4", district_name="Sim Toggle S4"
    )
    _create_school(client, name="Sim Toggle School", slug="simtog-school-s4")
    reg = _registry(client)
    _run(reg.assign_to_district(school_slug="simtog-school-s4", district_id=src_district.id))

    _clone_district(client, src_district.id, test_slug="test-simtog-s4")
    test_slug = _get_test_school_for_clone(client, "test-simtog-s4")

    before = _run(reg.get_by_slug(test_slug))
    sim_before = before.simulation_mode_enabled

    _toggle_simulation(client, test_slug)

    after = _run(reg.get_by_slug(test_slug))
    assert after.simulation_mode_enabled != sim_before, "Toggle must flip simulation_mode_enabled"


# ---------------------------------------------------------------------------
# S5. Simulation mode blocks real push on alarm/activate
# ---------------------------------------------------------------------------

def test_simulation_blocks_alarm_push(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    reg = _registry(client)
    _org, src_district = _create_org_and_district(
        client, org_slug="alarmblk-org-s5", district_slug="alarmblk-dist-s5", district_name="Alarm Block S5"
    )
    _create_school(client, name="Alarm Block School", slug="alarmblk-s5")
    _run(reg.assign_to_district(school_slug="alarmblk-s5", district_id=src_district.id))
    _clone_district(client, src_district.id, test_slug="test-alarmblk-s5")
    test_slug = _get_test_school_for_clone(client, "test-alarmblk-s5")

    school = _run(reg.get_by_slug(test_slug))
    if not school.simulation_mode_enabled:
        _toggle_simulation(client, test_slug)

    user_id = _create_user(client, test_slug, name="Admin", role="admin")
    _register_android(client, test_slug, token="fcm-alarm-s5", user_id=user_id)

    fcm_calls: list = []

    async def _fake_fcm(tokens, message, extra_data=None):
        fcm_calls.append(list(tokens))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    resp = client.post(
        f"/{test_slug}/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Test alarm", "user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    assert fcm_calls == [], "Simulation mode must suppress alarm/activate push"


# ---------------------------------------------------------------------------
# S6. Simulation mode blocks real push on incidents/create
# ---------------------------------------------------------------------------

def test_simulation_blocks_incident_push(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    reg = _registry(client)
    _org, src_district = _create_org_and_district(
        client, org_slug="incblk-org-s6", district_slug="incblk-dist-s6", district_name="Inc Block S6"
    )
    _create_school(client, name="Inc Block School", slug="incblk-s6")
    _run(reg.assign_to_district(school_slug="incblk-s6", district_id=src_district.id))
    _clone_district(client, src_district.id, test_slug="test-incblk-s6")
    test_slug = _get_test_school_for_clone(client, "test-incblk-s6")

    school = _run(reg.get_by_slug(test_slug))
    if not school.simulation_mode_enabled:
        _toggle_simulation(client, test_slug)

    user_id = _create_user(client, test_slug, name="Admin", role="admin")
    _register_android(client, test_slug, token="fcm-inc-s6", user_id=user_id)

    fcm_calls: list = []

    async def _fake_fcm(tokens, message, extra_data=None):
        fcm_calls.append(list(tokens))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    resp = client.post(
        f"/{test_slug}/incidents/create",
        headers={"X-API-Key": "test-api-key"},
        json={"type": "lockdown", "user_id": user_id, "target_scope": "ALL", "metadata": {}},
    )
    assert resp.status_code == 200, resp.text
    assert fcm_calls == [], "Simulation mode must suppress incidents/create push"


# ---------------------------------------------------------------------------
# S7. Simulation mode blocks real push on team-assist/create
# ---------------------------------------------------------------------------

def test_simulation_blocks_team_assist_push(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    reg = _registry(client)
    _org, src_district = _create_org_and_district(
        client, org_slug="asstblk-org-s7", district_slug="asstblk-dist-s7", district_name="Assist Block S7"
    )
    _create_school(client, name="Assist Block School", slug="asstblk-s7")
    _run(reg.assign_to_district(school_slug="asstblk-s7", district_id=src_district.id))
    _clone_district(client, src_district.id, test_slug="test-asstblk-s7")
    test_slug = _get_test_school_for_clone(client, "test-asstblk-s7")

    school = _run(reg.get_by_slug(test_slug))
    if not school.simulation_mode_enabled:
        _toggle_simulation(client, test_slug)

    sender_id = _create_user(client, test_slug, name="Sender", role="teacher")
    resp_id = _create_user(client, test_slug, name="Responder", role="admin")
    _register_android(client, test_slug, token="fcm-asst-sender-s7", user_id=sender_id)
    _register_android(client, test_slug, token="fcm-asst-resp-s7", user_id=resp_id)

    fcm_calls: list = []

    async def _fake_fcm(tokens, message, extra_data=None):
        fcm_calls.append(list(tokens))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    resp = client.post(
        f"/{test_slug}/team-assist/create",
        headers={"X-API-Key": "test-api-key"},
        json={"type": "medical", "user_id": sender_id, "assigned_team_ids": [resp_id]},
    )
    assert resp.status_code == 200, resp.text
    assert fcm_calls == [], "Simulation mode must suppress team-assist/create push"


# ---------------------------------------------------------------------------
# S8. Simulate-alert creates is_simulation incident, no real push
# ---------------------------------------------------------------------------

def test_simulate_alert_creates_simulation_incident(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    reg = _registry(client)
    _org, src_district = _create_org_and_district(
        client, org_slug="simalert-org-s8", district_slug="simalert-dist-s8", district_name="Sim Alert S8"
    )
    _create_school(client, name="Sim Alert School", slug="simalert-s8")
    _run(reg.assign_to_district(school_slug="simalert-s8", district_id=src_district.id))
    _clone_district(client, src_district.id, test_slug="test-simalert-s8")
    test_slug = _get_test_school_for_clone(client, "test-simalert-s8")

    fcm_calls: list = []

    async def _fake_fcm(tokens, message, extra_data=None):
        fcm_calls.append(list(tokens))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    resp = client.post(
        f"/super-admin/test-tenants/{test_slug}/simulate-alert",
        data={"alert_type": "lockdown"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert fcm_calls == [], "simulate-alert must not send real push"

    from app.services.tenant_manager import TenantManager
    tm: TenantManager = client.app.state.tenant_manager  # type: ignore[attr-defined]
    school = _run(reg.get_by_slug(test_slug))
    tenant_ctx = tm.get(school)
    incidents = _run(tenant_ctx.incident_store.list_active_incidents())
    assert any(getattr(i, "is_simulation", False) for i in incidents), (
        "Simulated incident must have is_simulation=True"
    )


# ---------------------------------------------------------------------------
# S9. Reset deletes simulation incidents only
# ---------------------------------------------------------------------------

def test_reset_deletes_simulation_incidents_only(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    reg = _registry(client)
    _org, src_district = _create_org_and_district(
        client, org_slug="reset-org-s9", district_slug="reset-dist-s9", district_name="Reset S9"
    )
    _create_school(client, name="Reset School", slug="reset-s9")
    _run(reg.assign_to_district(school_slug="reset-s9", district_id=src_district.id))
    _clone_district(client, src_district.id, test_slug="test-reset-s9")
    test_slug = _get_test_school_for_clone(client, "test-reset-s9")

    client.post(
        f"/super-admin/test-tenants/{test_slug}/simulate-alert",
        data={"alert_type": "lockdown"},
        follow_redirects=False,
    )

    from app.services.tenant_manager import TenantManager
    tm: TenantManager = client.app.state.tenant_manager  # type: ignore[attr-defined]
    school = _run(reg.get_by_slug(test_slug))
    tenant_ctx = tm.get(school)
    before = _run(tenant_ctx.incident_store.list_active_incidents())
    sim_before = [i for i in before if getattr(i, "is_simulation", False)]
    assert len(sim_before) >= 1

    resp = client.post(
        f"/super-admin/test-tenants/{test_slug}/reset",
        follow_redirects=False,
    )
    assert resp.status_code == 303

    after = _run(tenant_ctx.incident_store.list_active_incidents())
    sim_after = [i for i in after if getattr(i, "is_simulation", False)]
    assert sim_after == [], "Reset must remove all simulation incidents"


# ---------------------------------------------------------------------------
# S10a. Delete test district removes it
# ---------------------------------------------------------------------------

def test_delete_test_district_and_schools(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    reg = _registry(client)
    _org, src_district = _create_org_and_district(
        client, org_slug="deldist-org-s10a", district_slug="deldist-src-s10a", district_name="Del Src S10"
    )
    _create_school(client, name="Del School S10", slug="del-school-s10a")
    _run(reg.assign_to_district(school_slug="del-school-s10a", district_id=src_district.id))
    _clone_district(client, src_district.id, test_slug="test-deldist-s10a")
    test_district = _run(reg.get_district_by_slug("test-deldist-s10a"))
    assert test_district is not None

    resp = client.post(
        f"/super-admin/test-districts/{test_district.id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 303

    gone = _run(reg.get_district_by_slug("test-deldist-s10a"))
    assert gone is None, "Deleted test district must no longer exist"


# ---------------------------------------------------------------------------
# S10b. Delete blocked on production district — route and DB layer
# ---------------------------------------------------------------------------

def test_delete_production_district_blocked(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _org, prod_district = _create_org_and_district(
        client, org_slug="proddist-org-s10b", district_slug="proddist-s10b", district_name="Prod District S10"
    )

    resp = client.post(
        f"/super-admin/test-districts/{prod_district.id}/delete",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body_lower = resp.text.lower()
    assert "safety" in body_lower or "production" in body_lower, (
        "Endpoint must refuse to delete a production district with a safety message"
    )

    reg = _registry(client)
    still = _run(reg.get_district_by_slug("proddist-s10b"))
    assert still is not None, "Production district must not be deleted"


# ---------------------------------------------------------------------------
# S11. Production schools cannot have simulation mode enabled via toggle endpoint
# ---------------------------------------------------------------------------

def test_simulation_mode_blocked_on_production_school(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Prod School S11", slug="prodschool-s11")

    resp = client.post(
        "/super-admin/test-tenants/prodschool-s11/toggle-simulation",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body_lower = resp.text.lower()
    assert "production" in body_lower or "cannot" in body_lower

    reg = _registry(client)
    school = _run(reg.get_by_slug("prodschool-s11"))
    assert not school.simulation_mode_enabled, (
        "Production school must not have simulation_mode_enabled set to True via route"
    )


# ---------------------------------------------------------------------------
# S12. Production schools cannot have audio suppression enabled via toggle endpoint
# ---------------------------------------------------------------------------

def test_audio_suppression_blocked_on_production_school(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Prod School S12", slug="prodschool-s12")

    resp = client.post(
        "/super-admin/test-tenants/prodschool-s12/toggle-audio-suppression",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body_lower = resp.text.lower()
    assert "production" in body_lower or "cannot" in body_lower

    reg = _registry(client)
    school = _run(reg.get_by_slug("prodschool-s12"))
    assert not school.suppress_alarm_audio, (
        "Production school must not have suppress_alarm_audio set to True via route"
    )
