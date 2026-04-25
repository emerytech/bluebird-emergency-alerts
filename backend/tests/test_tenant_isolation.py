"""
Tenant isolation tests for alarm state, alert history, and incident lists.

Invariants under test:
  - Activating an alarm in tenant A does NOT affect tenant B's alarm state.
  - Deactivating tenant A's alarm does NOT affect tenant B.
  - /alerts history is scoped to the requesting tenant.
  - /incidents/active is scoped to the requesting tenant.
  - alarm_state rows store the correct tenant_slug.
  - The _assert_tenant_resolved guard rejects requests with no resolved tenant.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _create_school(client: TestClient, *, name: str, slug: str) -> None:
    resp = client.post(
        "/super-admin/schools/create",
        data={"name": name, "slug": slug, "setup_pin": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def _create_user(client: TestClient, slug: str, *, name: str, role: str) -> int:
    resp = client.post(
        f"/{slug}/users",
        headers={"X-API-Key": "test-api-key"},
        json={"name": name, "role": role, "phone_e164": None},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["user_id"])


def _alarm_status(client: TestClient, slug: str) -> dict:
    resp = client.get(
        f"/{slug}/alarm/status",
        headers={"X-API-Key": "test-api-key"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _activate(client: TestClient, slug: str, *, user_id: int, message: str = "Lockdown") -> dict:
    resp = client.post(
        f"/{slug}/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": message, "user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _deactivate(client: TestClient, slug: str, *, user_id: int) -> dict:
    resp = client.post(
        f"/{slug}/alarm/deactivate",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _alerts(client: TestClient, slug: str, *, limit: int = 10) -> list[dict]:
    resp = client.get(
        f"/{slug}/alerts?limit={limit}",
        headers={"X-API-Key": "test-api-key"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["alerts"]


def _create_incident(client: TestClient, slug: str, *, user_id: int, incident_type: str = "medical") -> dict:
    resp = client.post(
        f"/{slug}/incidents/create",
        headers={"X-API-Key": "test-api-key"},
        json={"type": incident_type, "user_id": user_id, "target_scope": "ALL", "metadata": {}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _active_incidents(client: TestClient, slug: str) -> list[dict]:
    resp = client.get(
        f"/{slug}/incidents/active",
        headers={"X-API-Key": "test-api-key"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["incidents"]


# ---------------------------------------------------------------------------
# Core isolation test: alarm state
# ---------------------------------------------------------------------------

def test_alarm_activation_does_not_bleed_into_other_tenant(
    client: TestClient, login_super_admin
) -> None:
    """Activating school-a's alarm must leave school-b's alarm state untouched."""
    login_super_admin()
    _create_school(client, name="School Alpha", slug="alpha")
    _create_school(client, name="School Beta", slug="beta")

    admin_a = _create_user(client, "alpha", name="Alpha Admin", role="admin")
    admin_b = _create_user(client, "beta", name="Beta Admin", role="admin")

    # Both start inactive.
    assert _alarm_status(client, "alpha")["is_active"] is False
    assert _alarm_status(client, "beta")["is_active"] is False

    # Activate alpha.
    result = _activate(client, "alpha", user_id=admin_a, message="Lockdown alpha")
    assert result["is_active"] is True
    assert result["message"] == "Lockdown alpha"

    # Alpha is active.
    assert _alarm_status(client, "alpha")["is_active"] is True

    # Beta is still inactive — no cross-tenant bleed.
    beta_status = _alarm_status(client, "beta")
    assert beta_status["is_active"] is False, (
        "ISOLATION FAILURE: activating alpha's alarm leaked into beta"
    )


def test_alarm_deactivation_does_not_affect_other_tenant(
    client: TestClient, login_super_admin
) -> None:
    """Deactivating school-a must not clear or disturb school-b's alarm."""
    login_super_admin()
    _create_school(client, name="Gamma School", slug="gamma")
    _create_school(client, name="Delta School", slug="delta")

    admin_g = _create_user(client, "gamma", name="Gamma Admin", role="admin")
    admin_d = _create_user(client, "delta", name="Delta Admin", role="admin")

    # Activate both independently.
    _activate(client, "gamma", user_id=admin_g, message="Gamma lockdown")
    _activate(client, "delta", user_id=admin_d, message="Delta lockdown")

    assert _alarm_status(client, "gamma")["is_active"] is True
    assert _alarm_status(client, "delta")["is_active"] is True

    # Deactivate gamma only.
    _deactivate(client, "gamma", user_id=admin_g)

    assert _alarm_status(client, "gamma")["is_active"] is False

    # Delta must still be active.
    delta_status = _alarm_status(client, "delta")
    assert delta_status["is_active"] is True, (
        "ISOLATION FAILURE: deactivating gamma's alarm also cleared delta"
    )


def test_inactive_tenant_unaffected_when_other_activates_and_deactivates(
    client: TestClient, login_super_admin
) -> None:
    """Full round-trip: activate A → deactivate A → verify B was never touched."""
    login_super_admin()
    _create_school(client, name="Epsilon School", slug="epsilon")
    _create_school(client, name="Zeta School", slug="zeta")

    admin_e = _create_user(client, "epsilon", name="Epsilon Admin", role="admin")

    # Zeta never activates. Epsilon activates then deactivates.
    _activate(client, "epsilon", user_id=admin_e, message="Epsilon lockdown")
    assert _alarm_status(client, "epsilon")["is_active"] is True
    assert _alarm_status(client, "zeta")["is_active"] is False

    _deactivate(client, "epsilon", user_id=admin_e)
    assert _alarm_status(client, "epsilon")["is_active"] is False
    assert _alarm_status(client, "zeta")["is_active"] is False, (
        "ISOLATION FAILURE: zeta alarm state changed when epsilon cycled"
    )


# ---------------------------------------------------------------------------
# Alarm state stores the correct tenant_slug
# ---------------------------------------------------------------------------

def test_alarm_state_records_correct_tenant_slug(
    client: TestClient, login_super_admin
) -> None:
    """After activation, alarm_state.tenant_slug must match the school's slug."""
    login_super_admin()
    _create_school(client, name="Slug School", slug="slug-school")
    admin_id = _create_user(client, "slug-school", name="Slug Admin", role="admin")

    _activate(client, "slug-school", user_id=admin_id, message="Slug check")

    school = client.app.state.tenant_manager.school_for_slug("slug-school")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)
    state = asyncio.run(tenant.alarm_store.get_state())

    assert state.is_active is True
    assert state.tenant_slug == "slug-school", (
        f"Expected tenant_slug='slug-school', got {state.tenant_slug!r}"
    )


def test_alarm_state_tenant_slug_cleared_on_deactivate(
    client: TestClient, login_super_admin
) -> None:
    """After deactivation, tenant_slug remains set to the correct school."""
    login_super_admin()
    _create_school(client, name="Deactivate Slug School", slug="deact-slug")
    admin_id = _create_user(client, "deact-slug", name="Admin", role="admin")

    _activate(client, "deact-slug", user_id=admin_id, message="Pre-deact")
    _deactivate(client, "deact-slug", user_id=admin_id)

    school = client.app.state.tenant_manager.school_for_slug("deact-slug")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)
    state = asyncio.run(tenant.alarm_store.get_state())

    assert state.is_active is False
    assert state.tenant_slug == "deact-slug", (
        f"Expected tenant_slug='deact-slug' after deactivation, got {state.tenant_slug!r}"
    )


# ---------------------------------------------------------------------------
# Alert history (/alerts) isolation
# ---------------------------------------------------------------------------

def test_alert_history_is_scoped_to_tenant(
    client: TestClient, login_super_admin
) -> None:
    """Alerts logged in tenant A must not appear in tenant B's /alerts response."""
    login_super_admin()
    _create_school(client, name="Alert School A", slug="alert-a")
    _create_school(client, name="Alert School B", slug="alert-b")

    admin_a = _create_user(client, "alert-a", name="Admin A", role="admin")
    admin_b = _create_user(client, "alert-b", name="Admin B", role="admin")

    # alert-a fires an alarm.
    _activate(client, "alert-a", user_id=admin_a, message="Alert A lockdown")
    _deactivate(client, "alert-a", user_id=admin_a)

    # alert-b fires a different alarm.
    _activate(client, "alert-b", user_id=admin_b, message="Alert B lockdown")
    _deactivate(client, "alert-b", user_id=admin_b)

    alerts_a = _alerts(client, "alert-a")
    alerts_b = _alerts(client, "alert-b")

    # Each tenant sees exactly its own alerts.
    messages_a = {item["message"] for item in alerts_a}
    messages_b = {item["message"] for item in alerts_b}

    assert "Alert A lockdown" in messages_a
    assert "Alert B lockdown" not in messages_a, (
        "ISOLATION FAILURE: alert-b's alert appears in alert-a's history"
    )
    assert "Alert B lockdown" in messages_b
    assert "Alert A lockdown" not in messages_b, (
        "ISOLATION FAILURE: alert-a's alert appears in alert-b's history"
    )


def test_alert_history_empty_for_tenant_with_no_alarms(
    client: TestClient, login_super_admin
) -> None:
    """A tenant that has never had an alarm must return an empty /alerts list."""
    login_super_admin()
    _create_school(client, name="Quiet School", slug="quiet-school")
    _create_school(client, name="Active School", slug="active-school")

    admin_active = _create_user(client, "active-school", name="Admin", role="admin")
    _activate(client, "active-school", user_id=admin_active, message="Active alarm")

    quiet_alerts = _alerts(client, "quiet-school")
    assert quiet_alerts == [], (
        f"ISOLATION FAILURE: quiet-school has no alarms but /alerts returned: {quiet_alerts}"
    )


# ---------------------------------------------------------------------------
# Incident isolation
# ---------------------------------------------------------------------------

def test_incidents_are_scoped_to_tenant(
    client: TestClient, login_super_admin
) -> None:
    """Incidents created in tenant A must not appear in tenant B's /incidents/active."""
    login_super_admin()
    _create_school(client, name="Incident School A", slug="incident-a")
    _create_school(client, name="Incident School B", slug="incident-b")

    # Teachers can create incidents (PERM_TRIGGER_OWN_TENANT_ALERTS or
    # PERM_MANAGE_ASSIGNED_TENANT_INCIDENTS).  Use admin role to be safe.
    user_a = _create_user(client, "incident-a", name="Admin A", role="admin")
    user_b = _create_user(client, "incident-b", name="Admin B", role="admin")

    _create_incident(client, "incident-a", user_id=user_a, incident_type="medical")
    _create_incident(client, "incident-b", user_id=user_b, incident_type="fire")

    incidents_a = _active_incidents(client, "incident-a")
    incidents_b = _active_incidents(client, "incident-b")

    types_a = {i["type"] for i in incidents_a}
    types_b = {i["type"] for i in incidents_b}

    assert "medical" in types_a
    assert "fire" not in types_a, (
        "ISOLATION FAILURE: incident-b's fire incident appeared in incident-a"
    )
    assert "fire" in types_b
    assert "medical" not in types_b, (
        "ISOLATION FAILURE: incident-a's medical incident appeared in incident-b"
    )


def test_incidents_empty_for_tenant_with_no_incidents(
    client: TestClient, login_super_admin
) -> None:
    """A tenant with no incidents must return an empty /incidents/active list."""
    login_super_admin()
    _create_school(client, name="No Incidents School", slug="no-incidents")
    _create_school(client, name="Has Incidents School", slug="has-incidents")

    user_hi = _create_user(client, "has-incidents", name="Admin", role="admin")
    _create_incident(client, "has-incidents", user_id=user_hi)

    assert _active_incidents(client, "no-incidents") == [], (
        "ISOLATION FAILURE: no-incidents tenant has incidents it should not see"
    )


# ---------------------------------------------------------------------------
# Bidirectional isolation: B does not affect A
# ---------------------------------------------------------------------------

def test_activating_b_does_not_affect_a(
    client: TestClient, login_super_admin
) -> None:
    """Activating tenant B's alarm does not bleed into tenant A."""
    login_super_admin()
    _create_school(client, name="Tenant P", slug="tenant-p")
    _create_school(client, name="Tenant Q", slug="tenant-q")

    admin_q = _create_user(client, "tenant-q", name="Q Admin", role="admin")

    # Only Q activates.
    _activate(client, "tenant-q", user_id=admin_q, message="Q alarm")

    status_p = _alarm_status(client, "tenant-p")
    assert status_p["is_active"] is False, (
        "ISOLATION FAILURE: activating tenant-q leaked into tenant-p"
    )
    assert _alarm_status(client, "tenant-q")["is_active"] is True


# ---------------------------------------------------------------------------
# Defensive guard: missing tenant context
# ---------------------------------------------------------------------------

def test_alarm_status_without_tenant_returns_400(client: TestClient) -> None:
    """Requests that cannot resolve a tenant must get 400, not a silent default."""
    resp = client.get("/alarm/status", headers={"X-API-Key": "test-api-key"})
    assert resp.status_code == 400
    assert "Tenant" in resp.text


def test_alarm_activate_without_tenant_returns_400(client: TestClient) -> None:
    resp = client.post(
        "/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Test", "user_id": 1},
    )
    assert resp.status_code == 400


def test_alarm_deactivate_without_tenant_returns_400(client: TestClient) -> None:
    resp = client.post(
        "/alarm/deactivate",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": 1},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Unknown tenant slug returns 400
# ---------------------------------------------------------------------------

def test_unknown_tenant_slug_returns_400(client: TestClient) -> None:
    """A slug that doesn't map to any school must be rejected by the middleware."""
    resp = client.get(
        "/nonexistent-school-xyz/alarm/status",
        headers={"X-API-Key": "test-api-key"},
    )
    assert resp.status_code == 400
