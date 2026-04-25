"""
Acknowledgement tenant isolation tests.

Invariants under test:
  - A user in tenant A can acknowledge tenant A's alert.
  - That acknowledgement is NOT visible to tenant B (count stays at 0 for B).
  - Tenant B's alarm status does not reflect tenant A's acknowledgement count.
  - A user cannot acknowledge an alert from a tenant they do not belong to
    (the alert doesn't exist in the wrong tenant's DB → 404).
  - Acknowledgement is idempotent: a second POST returns already_acknowledged=True
    and does not double-count.
  - The tenant_slug field on AlertAcknowledgementRecord is set correctly.
  - Ack without a resolved tenant returns 400.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
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


def _activate(client: TestClient, slug: str, *, user_id: int, message: str = "Lockdown") -> int:
    resp = client.post(
        f"/{slug}/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": message, "user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["current_alert_id"])


def _ack(client: TestClient, slug: str, *, alert_id: int, user_id: int) -> dict:
    resp = client.post(
        f"/{slug}/alerts/{alert_id}/ack",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": user_id},
    )
    return resp


def _alarm_status(client: TestClient, slug: str, *, user_id: int | None = None) -> dict:
    url = f"/{slug}/alarm/status"
    if user_id is not None:
        url += f"?user_id={user_id}"
    resp = client.get(url, headers={"X-API-Key": "test-api-key"})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Core isolation: ack in A does not appear in B
# ---------------------------------------------------------------------------

def test_ack_in_tenant_a_not_visible_to_tenant_b(
    client: TestClient, login_super_admin
) -> None:
    """An acknowledgement recorded in tenant A must not affect tenant B's count."""
    login_super_admin()
    _create_school(client, name="Ack School A", slug="ack-a")
    _create_school(client, name="Ack School B", slug="ack-b")

    admin_a = _create_user(client, "ack-a", name="Admin A", role="admin")
    admin_b = _create_user(client, "ack-b", name="Admin B", role="admin")

    # Activate alarm in both tenants.
    alert_id_a = _activate(client, "ack-a", user_id=admin_a, message="Lockdown A")
    _activate(client, "ack-b", user_id=admin_b, message="Lockdown B")

    # Tenant A admin acknowledges tenant A's alert.
    resp = _ack(client, "ack-a", alert_id=alert_id_a, user_id=admin_a)
    assert resp.status_code == 200
    ack_data = resp.json()
    assert ack_data["acknowledgement_count"] == 1

    # Tenant B's alarm status must still show 0 acknowledgements.
    status_b = _alarm_status(client, "ack-b", user_id=admin_b)
    assert status_b["acknowledgement_count"] == 0, (
        "ISOLATION FAILURE: tenant A's ack bled into tenant B's acknowledgement count"
    )


def test_ack_in_tenant_a_reflected_only_in_a_status(
    client: TestClient, login_super_admin
) -> None:
    """AlarmStatusResponse.acknowledgement_count must be tenant-scoped."""
    login_super_admin()
    _create_school(client, name="Count School A", slug="count-a")
    _create_school(client, name="Count School B", slug="count-b")

    admin_a = _create_user(client, "count-a", name="Admin A", role="admin")
    teacher_a = _create_user(client, "count-a", name="Teacher A", role="teacher")
    admin_b = _create_user(client, "count-b", name="Admin B", role="admin")

    alert_id_a = _activate(client, "count-a", user_id=admin_a, message="Count A lockdown")
    _activate(client, "count-b", user_id=admin_b, message="Count B lockdown")

    # Both users in A acknowledge.
    _ack(client, "count-a", alert_id=alert_id_a, user_id=admin_a)
    _ack(client, "count-a", alert_id=alert_id_a, user_id=teacher_a)

    status_a = _alarm_status(client, "count-a", user_id=admin_a)
    status_b = _alarm_status(client, "count-b", user_id=admin_b)

    assert status_a["acknowledgement_count"] == 2
    assert status_b["acknowledgement_count"] == 0, (
        "ISOLATION FAILURE: tenant B sees acknowledgements from tenant A"
    )


# ---------------------------------------------------------------------------
# Cross-tenant ack attempt → 404
# ---------------------------------------------------------------------------

def test_cannot_ack_alert_from_wrong_tenant(
    client: TestClient, login_super_admin
) -> None:
    """Attempting to acknowledge an alert_id that doesn't exist in the target tenant
    must return 404, not silently create a phantom acknowledgement."""
    login_super_admin()
    _create_school(client, name="Cross Ack A", slug="cross-ack-a")
    _create_school(client, name="Cross Ack B", slug="cross-ack-b")

    admin_a = _create_user(client, "cross-ack-a", name="Admin A", role="admin")
    admin_b = _create_user(client, "cross-ack-b", name="Admin B", role="admin")

    # Only tenant A activates an alarm.
    alert_id_a = _activate(client, "cross-ack-a", user_id=admin_a)

    # Try to acknowledge tenant A's alert_id via tenant B's URL using tenant B's user.
    resp = _ack(client, "cross-ack-b", alert_id=alert_id_a, user_id=admin_b)
    assert resp.status_code == 404, (
        f"Expected 404 when acking cross-tenant alert, got {resp.status_code}: {resp.text}"
    )

    # Tenant A's ack count must remain 0 (the failed cross-tenant attempt had no effect).
    status_a = _alarm_status(client, "cross-ack-a", user_id=admin_a)
    assert status_a["acknowledgement_count"] == 0


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_ack_is_idempotent(client: TestClient, login_super_admin) -> None:
    """A second acknowledgement from the same user returns already_acknowledged=True
    and the count does not increase."""
    login_super_admin()
    _create_school(client, name="Idempotent Ack School", slug="idem-ack")

    admin_id = _create_user(client, "idem-ack", name="Admin", role="admin")
    alert_id = _activate(client, "idem-ack", user_id=admin_id)

    first = _ack(client, "idem-ack", alert_id=alert_id, user_id=admin_id)
    assert first.status_code == 200
    assert first.json()["already_acknowledged"] is False
    assert first.json()["acknowledgement_count"] == 1

    second = _ack(client, "idem-ack", alert_id=alert_id, user_id=admin_id)
    assert second.status_code == 200
    assert second.json()["already_acknowledged"] is True
    assert second.json()["acknowledgement_count"] == 1, (
        "Idempotency failure: double-ack incremented the count"
    )


# ---------------------------------------------------------------------------
# tenant_slug recorded correctly in AlertAcknowledgementRecord
# ---------------------------------------------------------------------------

def test_ack_record_carries_correct_tenant_slug(
    client: TestClient, login_super_admin
) -> None:
    """The AlertAcknowledgementRecord stored in the DB must have the correct tenant_slug."""
    login_super_admin()
    _create_school(client, name="Slug Ack School", slug="slug-ack")

    admin_id = _create_user(client, "slug-ack", name="Admin", role="admin")
    alert_id = _activate(client, "slug-ack", user_id=admin_id)

    resp = _ack(client, "slug-ack", alert_id=alert_id, user_id=admin_id)
    assert resp.status_code == 200

    school = client.app.state.tenant_manager.school_for_slug("slug-ack")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)

    record = asyncio.run(tenant.alert_log.has_acknowledged(alert_id=alert_id, user_id=admin_id))
    assert record is True

    ack_count = asyncio.run(tenant.alert_log.acknowledgement_count(alert_id))
    assert ack_count == 1

    # Directly inspect the stored record via the acknowledge method returning the record.
    # Re-acking returns the existing record with tenant_slug set.
    ack_record = asyncio.run(
        tenant.alert_log.acknowledge(alert_id=alert_id, user_id=admin_id, tenant_slug="slug-ack")
    )
    assert ack_record.tenant_slug == "slug-ack", (
        f"Expected tenant_slug='slug-ack', got {ack_record.tenant_slug!r}"
    )


# ---------------------------------------------------------------------------
# Defensive guard: ack without resolved tenant → 400
# ---------------------------------------------------------------------------

def test_ack_without_tenant_returns_400(client: TestClient) -> None:
    """A POST to /alerts/{id}/ack with no resolvable tenant must return 400."""
    resp = client.post(
        "/alerts/1/ack",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": 1},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# current_user_acknowledged is tenant-scoped
# ---------------------------------------------------------------------------

def test_current_user_acknowledged_is_tenant_scoped(
    client: TestClient, login_super_admin
) -> None:
    """AlarmStatusResponse.current_user_acknowledged must reflect only the queried tenant."""
    login_super_admin()
    _create_school(client, name="User Ack School A", slug="user-ack-a")
    _create_school(client, name="User Ack School B", slug="user-ack-b")

    # Use role=admin so the user has ack permissions in both tenants.
    admin_a = _create_user(client, "user-ack-a", name="Admin A", role="admin")
    admin_b = _create_user(client, "user-ack-b", name="Admin B", role="admin")

    alert_id_a = _activate(client, "user-ack-a", user_id=admin_a, message="User Ack A")
    _activate(client, "user-ack-b", user_id=admin_b, message="User Ack B")

    _ack(client, "user-ack-a", alert_id=alert_id_a, user_id=admin_a)

    # Tenant A's status for admin_a must show acknowledged.
    status_a = _alarm_status(client, "user-ack-a", user_id=admin_a)
    assert status_a["current_user_acknowledged"] is True

    # Tenant B's status for admin_b must show NOT acknowledged (different tenant, different alert).
    status_b = _alarm_status(client, "user-ack-b", user_id=admin_b)
    assert status_b["current_user_acknowledged"] is False, (
        "ISOLATION FAILURE: tenant B shows current_user_acknowledged=True "
        "based on tenant A's acknowledgement"
    )
