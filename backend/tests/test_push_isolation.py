"""
Push notification tenant isolation tests.

Invariants under test:
  - Triggering an alarm in tenant A sends APNs ONLY to devices registered in tenant A.
  - Triggering an alarm in tenant A sends FCM ONLY to devices registered in tenant A.
  - Devices registered in tenant B are never included in tenant A's push delivery.
  - Training alarms never trigger any push notification.
  - BroadcastPlan carries the correct tenant_slug.
  - A user in quiet mode has their tokens excluded without affecting other users.
  - The /panic endpoint follows the same tenant-scoped token selection.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared helpers
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


def _register_ios_device(client: TestClient, slug: str, *, token: str, user_id: int) -> None:
    resp = client.post(
        f"/{slug}/devices/register",
        headers={"X-API-Key": "test-api-key"},
        json={
            "device_token": token,
            "platform": "ios",
            "push_provider": "apns",
            "device_name": "Pytest iPhone",
            "user_id": user_id,
        },
    )
    assert resp.status_code == 200, resp.text


def _register_android_device(client: TestClient, slug: str, *, token: str, user_id: int) -> None:
    resp = client.post(
        f"/{slug}/devices/register",
        headers={"X-API-Key": "test-api-key"},
        json={
            "device_token": token,
            "platform": "android",
            "push_provider": "fcm",
            "device_name": "Pytest Android",
            "user_id": user_id,
        },
    )
    assert resp.status_code == 200, resp.text


def _activate(client: TestClient, slug: str, *, user_id: int, message: str = "Lockdown") -> dict:
    resp = client.post(
        f"/{slug}/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": message, "user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _panic(client: TestClient, slug: str, *, user_id: int, message: str = "Lockdown") -> dict:
    resp = client.post(
        f"/{slug}/panic",
        headers={"X-API-Key": "test-api-key"},
        json={"message": message, "user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _all_tokens(calls: list) -> set[str]:
    """Flatten all tokens from captured send_bulk call list."""
    return {token for (tokens, _msg) in calls for token in tokens}


# ---------------------------------------------------------------------------
# FCM isolation
# ---------------------------------------------------------------------------

def test_alarm_fcm_sends_only_tenant_a_tokens(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """FCM delivery must include only tenant A's registered devices."""
    login_super_admin()
    _create_school(client, name="FCM Tenant A", slug="fcm-a")
    _create_school(client, name="FCM Tenant B", slug="fcm-b")

    admin_a = _create_user(client, "fcm-a", name="FCM Admin A", role="admin")
    admin_b = _create_user(client, "fcm-b", name="FCM Admin B", role="admin")

    _register_android_device(client, "fcm-a", token="fcm-token-a", user_id=admin_a)
    _register_android_device(client, "fcm-b", token="fcm-token-b", user_id=admin_b)

    fcm_calls: list[tuple[list[str], str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    _activate(client, "fcm-a", user_id=admin_a, message="Lockdown FCM-A")

    sent = _all_tokens(fcm_calls)
    assert "fcm-token-a" in sent, "Tenant A's FCM token must be delivered"
    assert "fcm-token-b" not in sent, (
        "ISOLATION FAILURE: tenant B's FCM token was included in tenant A's alarm push"
    )


def test_alarm_fcm_tenant_b_tokens_not_sent_when_a_triggers(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """Bidirectional: triggering B's alarm must not send to A's devices."""
    login_super_admin()
    _create_school(client, name="FCM Bidirectional A", slug="fcm-bidir-a")
    _create_school(client, name="FCM Bidirectional B", slug="fcm-bidir-b")

    admin_a = _create_user(client, "fcm-bidir-a", name="Bidir Admin A", role="admin")
    admin_b = _create_user(client, "fcm-bidir-b", name="Bidir Admin B", role="admin")

    _register_android_device(client, "fcm-bidir-a", token="fcm-bidir-token-a", user_id=admin_a)
    _register_android_device(client, "fcm-bidir-b", token="fcm-bidir-token-b", user_id=admin_b)

    fcm_calls: list[tuple[list[str], str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    # Trigger B — A's token must not be hit.
    _activate(client, "fcm-bidir-b", user_id=admin_b, message="Lockdown FCM-B")

    sent = _all_tokens(fcm_calls)
    assert "fcm-bidir-token-b" in sent
    assert "fcm-bidir-token-a" not in sent, (
        "ISOLATION FAILURE: tenant A's FCM token was included in tenant B's alarm push"
    )


# ---------------------------------------------------------------------------
# APNs isolation
# ---------------------------------------------------------------------------

_APNS_TOKEN_A = "aa" * 32  # valid 64-char hex APNs token
_APNS_TOKEN_B = "bb" * 32


def test_alarm_apns_sends_only_tenant_a_tokens(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """APNs delivery must include only tenant A's registered iOS devices."""
    login_super_admin()
    _create_school(client, name="APNs Tenant A", slug="apns-a")
    _create_school(client, name="APNs Tenant B", slug="apns-b")

    admin_a = _create_user(client, "apns-a", name="APNs Admin A", role="admin")
    admin_b = _create_user(client, "apns-b", name="APNs Admin B", role="admin")

    _register_ios_device(client, "apns-a", token=_APNS_TOKEN_A, user_id=admin_a)
    _register_ios_device(client, "apns-b", token=_APNS_TOKEN_B, user_id=admin_b)

    apns_calls: list[tuple[list[str], str]] = []

    async def _fake_apns(tokens: list[str], message: str, extra_data=None):
        apns_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.apns_client, "send_bulk", _fake_apns)

    _activate(client, "apns-a", user_id=admin_a, message="Lockdown APNs-A")

    sent = _all_tokens(apns_calls)
    assert _APNS_TOKEN_A in sent, "Tenant A's APNs token must be delivered"
    assert _APNS_TOKEN_B not in sent, (
        "ISOLATION FAILURE: tenant B's APNs token was included in tenant A's alarm push"
    )


# ---------------------------------------------------------------------------
# Training mode
# ---------------------------------------------------------------------------

_APNS_TOKEN_TRAINING = "cc" * 32


def test_training_alarm_sends_no_push(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """Training alarms must never reach APNs or FCM."""
    login_super_admin()
    _create_school(client, name="Training Push School", slug="training-push")

    admin_id = _create_user(client, "training-push", name="Training Admin", role="admin")
    _register_ios_device(client, "training-push", token=_APNS_TOKEN_TRAINING, user_id=admin_id)
    _register_android_device(client, "training-push", token="fcm-training-token", user_id=admin_id)

    apns_calls: list = []
    fcm_calls: list = []

    async def _fake_apns(tokens: list[str], message: str, extra_data=None):
        apns_calls.append(list(tokens))
        return []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append(list(tokens))
        return []

    monkeypatch.setattr(client.app.state.apns_client, "send_bulk", _fake_apns)
    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    resp = client.post(
        "/training-push/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Training drill", "user_id": admin_id, "is_training": True},
    )
    assert resp.status_code == 200
    assert resp.json()["is_training"] is True

    assert apns_calls == [], "Training alarm must not trigger APNs"
    assert fcm_calls == [], "Training alarm must not trigger FCM"


# ---------------------------------------------------------------------------
# BroadcastPlan carries correct tenant_slug
# ---------------------------------------------------------------------------

def test_broadcast_plan_carries_tenant_slug(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """The BroadcastPlan passed to broadcast_panic must carry the triggering tenant's slug."""
    login_super_admin()
    _create_school(client, name="Plan Slug School", slug="plan-slug")
    admin_id = _create_user(client, "plan-slug", name="Plan Admin", role="admin")
    _register_android_device(client, "plan-slug", token="plan-fcm-token", user_id=admin_id)

    school = client.app.state.tenant_manager.school_for_slug("plan-slug")
    assert school is not None
    tenant = client.app.state.tenant_manager.get(school)

    captured_plans = []
    original = tenant.broadcaster.broadcast_panic

    async def _capture_plan(*, alert_id, message, plan):
        captured_plans.append(plan)

    tenant.broadcaster.broadcast_panic = _capture_plan

    _activate(client, "plan-slug", user_id=admin_id)

    assert captured_plans, "broadcast_panic was not called"
    assert captured_plans[0].tenant_slug == "plan-slug", (
        f"Expected tenant_slug='plan-slug', got {captured_plans[0].tenant_slug!r}"
    )


# ---------------------------------------------------------------------------
# Quiet mode: paused user's token excluded without affecting others
# ---------------------------------------------------------------------------

def test_quiet_user_token_excluded_from_alarm_push(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """A user in quiet mode must have their token excluded; other users still receive the push."""
    login_super_admin()
    _create_school(client, name="Quiet Push School", slug="quiet-push")

    quiet_user_id = _create_user(client, "quiet-push", name="Quiet User", role="admin")
    active_user_id = _create_user(client, "quiet-push", name="Active User", role="teacher")

    _register_android_device(client, "quiet-push", token="fcm-quiet-token", user_id=quiet_user_id)
    _register_android_device(client, "quiet-push", token="fcm-active-token", user_id=active_user_id)

    school = client.app.state.tenant_manager.school_for_slug("quiet-push")
    assert school is not None
    school_id = int(school.id)

    # Activate quiet mode for quiet_user_id with no source request (bypasses approval check).
    quiet_store = client.app.state.quiet_state_store
    asyncio.run(quiet_store.upsert_active(
        user_id=quiet_user_id,
        home_tenant_id=school_id,
        source_request_id=None,
        approved_by_user_id=None,
    ))

    fcm_calls: list[tuple[list[str], str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    _activate(client, "quiet-push", user_id=quiet_user_id, message="Lockdown quiet test")

    sent = _all_tokens(fcm_calls)
    assert "fcm-active-token" in sent, "Non-paused user must still receive the push"
    assert "fcm-quiet-token" not in sent, (
        "ISOLATION FAILURE: quiet user's FCM token was included in the alarm push"
    )


# ---------------------------------------------------------------------------
# /panic endpoint: same token selection isolation
# ---------------------------------------------------------------------------

def test_panic_endpoint_sends_only_triggered_tenant_fcm_tokens(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """The /panic endpoint must respect the same per-tenant token selection as /alarm/activate."""
    login_super_admin()
    _create_school(client, name="Panic Tenant A", slug="panic-a")
    _create_school(client, name="Panic Tenant B", slug="panic-b")

    admin_a = _create_user(client, "panic-a", name="Panic Admin A", role="admin")
    admin_b = _create_user(client, "panic-b", name="Panic Admin B", role="admin")

    _register_android_device(client, "panic-a", token="panic-fcm-a", user_id=admin_a)
    _register_android_device(client, "panic-b", token="panic-fcm-b", user_id=admin_b)

    fcm_calls: list[tuple[list[str], str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    _panic(client, "panic-a", user_id=admin_a, message="Panic A")

    sent = _all_tokens(fcm_calls)
    assert "panic-fcm-a" in sent, "Panic A's FCM token must be delivered"
    assert "panic-fcm-b" not in sent, (
        "ISOLATION FAILURE: panic-b's FCM token was included in panic-a's delivery"
    )


def test_panic_training_sends_no_push(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """Training /panic must not send any push notifications."""
    login_super_admin()
    _create_school(client, name="Panic Training School", slug="panic-training")
    admin_id = _create_user(client, "panic-training", name="Panic Admin", role="admin")
    _register_android_device(client, "panic-training", token="panic-train-fcm", user_id=admin_id)

    fcm_calls: list = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append(list(tokens))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    resp = client.post(
        "/panic-training/panic",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Training panic", "user_id": admin_id, "is_training": True},
    )
    assert resp.status_code == 200

    assert fcm_calls == [], "Training /panic must not trigger FCM"
