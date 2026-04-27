"""
Tenant isolation regression tests.

Guards against the cross-tenant alert bug (and regressions of the fixes made
in Phases 3–5) by verifying six hard invariants:

  1. Alarm status  — activating A does not make B appear active.
  2. Alert history — alerts logged in A do not appear in B's /alerts feed.
  3. WebSocket     — events published to A are not delivered to B's connections.
  4. Push tokens   — alarm in A sends only A's FCM tokens, never B's.
  5. Ack count     — acknowledging an alert in A does not change B's count.
  6. Training      — training alert in A does not appear in B's history or status.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.services.alert_hub import AlertHub


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _school(client: TestClient, *, name: str, slug: str) -> None:
    r = client.post(
        "/super-admin/schools/create",
        data={"name": name, "slug": slug, "setup_pin": ""},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text


def _user(client: TestClient, slug: str, *, name: str, role: str) -> int:
    r = client.post(
        f"/{slug}/users",
        headers={"X-API-Key": "test-api-key"},
        json={"name": name, "role": role, "phone_e164": None},
    )
    assert r.status_code == 200, r.text
    return int(r.json()["user_id"])


def _activate(
    client: TestClient,
    slug: str,
    *,
    user_id: int,
    message: str = "Lockdown",
    is_training: bool = False,
    training_label: str | None = None,
) -> dict:
    body: dict = {"message": message, "user_id": user_id, "is_training": is_training}
    if training_label is not None:
        body["training_label"] = training_label
    r = client.post(
        f"/{slug}/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json=body,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _alarm_status(client: TestClient, slug: str) -> dict:
    r = client.get(f"/{slug}/alarm/status", headers={"X-API-Key": "test-api-key"})
    assert r.status_code == 200, r.text
    return r.json()


def _alerts(client: TestClient, slug: str, *, limit: int = 10) -> list[dict]:
    r = client.get(f"/{slug}/alerts?limit={limit}", headers={"X-API-Key": "test-api-key"})
    assert r.status_code == 200, r.text
    return r.json()["alerts"]


def _ack(client: TestClient, slug: str, *, alert_id: int, user_id: int):
    return client.post(
        f"/{slug}/alerts/{alert_id}/ack",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": user_id},
    )


def _register_android(client: TestClient, slug: str, *, token: str, user_id: int) -> None:
    r = client.post(
        f"/{slug}/devices/register",
        headers={"X-API-Key": "test-api-key"},
        json={
            "device_token": token,
            "platform": "android",
            "push_provider": "fcm",
            "device_name": "test-device",
            "user_id": user_id,
        },
    )
    assert r.status_code == 200, r.text


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# 1. Alarm status isolation
# ---------------------------------------------------------------------------

def test_alarm_status_isolation(client: TestClient, login_super_admin) -> None:
    """Triggering A's alarm must not make B appear active."""
    login_super_admin()
    _school(client, name="Reg Status A", slug="reg-status-a")
    _school(client, name="Reg Status B", slug="reg-status-b")

    uid_a = _user(client, "reg-status-a", name="Admin A", role="admin")
    _activate(client, "reg-status-a", user_id=uid_a, message="Reg lockdown A")

    assert _alarm_status(client, "reg-status-a")["is_active"] is True
    assert _alarm_status(client, "reg-status-b")["is_active"] is False, (
        "REGRESSION: reg-status-b reports active after reg-status-a was triggered"
    )


def test_alarm_status_isolation_bidirectional(client: TestClient, login_super_admin) -> None:
    """Triggering B's alarm must not make A appear active."""
    login_super_admin()
    _school(client, name="Reg Status Bidir A", slug="reg-bidir-a")
    _school(client, name="Reg Status Bidir B", slug="reg-bidir-b")

    uid_b = _user(client, "reg-bidir-b", name="Admin B", role="admin")
    _activate(client, "reg-bidir-b", user_id=uid_b, message="Reg lockdown B")

    assert _alarm_status(client, "reg-bidir-b")["is_active"] is True
    assert _alarm_status(client, "reg-bidir-a")["is_active"] is False, (
        "REGRESSION: reg-bidir-a reports active after reg-bidir-b was triggered"
    )


# ---------------------------------------------------------------------------
# 2. Alert history isolation
# ---------------------------------------------------------------------------

def test_alert_history_isolation(client: TestClient, login_super_admin) -> None:
    """/alerts in B must not include alerts logged in A, and vice-versa."""
    login_super_admin()
    _school(client, name="Reg Hist A", slug="reg-hist-a")
    _school(client, name="Reg Hist B", slug="reg-hist-b")

    uid_a = _user(client, "reg-hist-a", name="Admin A", role="admin")
    uid_b = _user(client, "reg-hist-b", name="Admin B", role="admin")

    _activate(client, "reg-hist-a", user_id=uid_a, message="Tenant A alert")
    _activate(client, "reg-hist-b", user_id=uid_b, message="Tenant B alert")

    msgs_a = {item["message"] for item in _alerts(client, "reg-hist-a")}
    msgs_b = {item["message"] for item in _alerts(client, "reg-hist-b")}

    assert "Tenant A alert" in msgs_a
    assert "Tenant B alert" not in msgs_a, (
        "REGRESSION: B's alert appears in A's /alerts history"
    )
    assert "Tenant B alert" in msgs_b
    assert "Tenant A alert" not in msgs_b, (
        "REGRESSION: A's alert appears in B's /alerts history"
    )


def test_alert_history_empty_for_silent_tenant(client: TestClient, login_super_admin) -> None:
    """A tenant that never triggered an alarm must return an empty /alerts list."""
    login_super_admin()
    _school(client, name="Reg Silent", slug="reg-silent")
    _school(client, name="Reg Noisy", slug="reg-noisy")

    uid = _user(client, "reg-noisy", name="Admin", role="admin")
    _activate(client, "reg-noisy", user_id=uid, message="Noisy alarm")

    assert _alerts(client, "reg-silent") == [], (
        "REGRESSION: reg-silent's /alerts is non-empty despite no alarms"
    )


# ---------------------------------------------------------------------------
# 3. WebSocket isolation
# ---------------------------------------------------------------------------

def test_websocket_publish_reaches_only_target_tenant() -> None:
    """Publishing to A must deliver only to A's connected sockets."""
    async def _run() -> None:
        hub = AlertHub()
        ws_a = _mock_ws()
        ws_b = _mock_ws()
        await hub.connect("reg-ws-a", ws_a)
        await hub.connect("reg-ws-b", ws_b)

        payload = {"event": "alert_triggered", "tenant_slug": "reg-ws-a"}
        await hub.publish("reg-ws-a", payload)

        encoded = json.dumps(payload, separators=(",", ":"), default=str)
        ws_a.send_text.assert_awaited_once_with(encoded)
        ws_b.send_text.assert_not_awaited()

    asyncio.run(_run())


def test_websocket_publish_b_does_not_reach_a() -> None:
    """Publishing to B must not deliver to A's connected socket."""
    async def _run() -> None:
        hub = AlertHub()
        ws_a = _mock_ws()
        ws_b = _mock_ws()
        await hub.connect("reg-ws-a2", ws_a)
        await hub.connect("reg-ws-b2", ws_b)

        await hub.publish("reg-ws-b2", {"event": "alert_triggered", "tenant_slug": "reg-ws-b2"})

        ws_a.send_text.assert_not_awaited()
        ws_b.send_text.assert_awaited_once()

    asyncio.run(_run())


def test_websocket_blank_slug_not_delivered() -> None:
    """Publishing with a blank or whitespace slug must not reach any socket."""
    async def _run() -> None:
        hub = AlertHub()
        ws = _mock_ws()
        await hub.connect("reg-ws-guard", ws)

        await hub.publish("", {"event": "test"})
        await hub.publish("   ", {"event": "test"})
        await hub.publish(None, {"event": "test"})  # type: ignore[arg-type]

        ws.send_text.assert_not_awaited()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 4. Push token selection isolation
# ---------------------------------------------------------------------------

def test_push_fcm_isolation(client: TestClient, login_super_admin, monkeypatch) -> None:
    """FCM tokens registered in B must never be included in A's alarm push."""
    login_super_admin()
    _school(client, name="Reg Push A", slug="reg-push-a")
    _school(client, name="Reg Push B", slug="reg-push-b")

    uid_a = _user(client, "reg-push-a", name="Admin A", role="admin")
    uid_b = _user(client, "reg-push-b", name="Admin B", role="admin")
    _register_android(client, "reg-push-a", token="reg-fcm-a", user_id=uid_a)
    _register_android(client, "reg-push-b", token="reg-fcm-b", user_id=uid_b)

    sent: list[tuple[list, str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None) -> list:
        sent.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)
    _activate(client, "reg-push-a", user_id=uid_a, message="Reg push lockdown A")

    all_tokens = {t for tokens, _ in sent for t in tokens}
    assert "reg-fcm-a" in all_tokens, "REGRESSION: A's FCM token was not sent"
    assert "reg-fcm-b" not in all_tokens, (
        "REGRESSION: B's FCM token included in A's alarm delivery"
    )


def test_push_fcm_isolation_reverse(client: TestClient, login_super_admin, monkeypatch) -> None:
    """B's alarm must not deliver to A's registered FCM tokens."""
    login_super_admin()
    _school(client, name="Reg Push Rev A", slug="reg-push-rev-a")
    _school(client, name="Reg Push Rev B", slug="reg-push-rev-b")

    uid_a = _user(client, "reg-push-rev-a", name="Admin A", role="admin")
    uid_b = _user(client, "reg-push-rev-b", name="Admin B", role="admin")
    _register_android(client, "reg-push-rev-a", token="reg-fcm-rev-a", user_id=uid_a)
    _register_android(client, "reg-push-rev-b", token="reg-fcm-rev-b", user_id=uid_b)

    sent: list[tuple[list, str]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None) -> list:
        sent.append((list(tokens), message))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)
    _activate(client, "reg-push-rev-b", user_id=uid_b, message="Reg push lockdown B")

    all_tokens = {t for tokens, _ in sent for t in tokens}
    assert "reg-fcm-rev-b" in all_tokens, "REGRESSION: B's FCM token was not sent"
    assert "reg-fcm-rev-a" not in all_tokens, (
        "REGRESSION: A's FCM token included in B's alarm delivery"
    )


# ---------------------------------------------------------------------------
# 5. Acknowledgement isolation
# ---------------------------------------------------------------------------

def test_ack_count_isolation(client: TestClient, login_super_admin) -> None:
    """Acknowledging an alert in A must not increment B's acknowledgement_count."""
    login_super_admin()
    _school(client, name="Reg Ack A", slug="reg-ack-a")
    _school(client, name="Reg Ack B", slug="reg-ack-b")

    uid_a = _user(client, "reg-ack-a", name="Admin A", role="admin")
    uid_b = _user(client, "reg-ack-b", name="Admin B", role="admin")

    result_a = _activate(client, "reg-ack-a", user_id=uid_a, message="Ack A lockdown")
    _activate(client, "reg-ack-b", user_id=uid_b, message="Ack B lockdown")
    alert_id_a = int(result_a["current_alert_id"])

    resp = _ack(client, "reg-ack-a", alert_id=alert_id_a, user_id=uid_a)
    assert resp.status_code == 200
    assert resp.json()["acknowledgement_count"] == 1

    status_b = _alarm_status(client, "reg-ack-b")
    assert status_b["acknowledgement_count"] == 0, (
        "REGRESSION: B's acknowledgement_count is non-zero after A's ack"
    )


def test_cross_tenant_ack_returns_404(client: TestClient, login_super_admin) -> None:
    """Acknowledging tenant A's alert_id via tenant B's URL must return 404."""
    login_super_admin()
    _school(client, name="Reg Cross Ack A", slug="reg-cross-ack-a")
    _school(client, name="Reg Cross Ack B", slug="reg-cross-ack-b")

    uid_a = _user(client, "reg-cross-ack-a", name="Admin A", role="admin")
    uid_b = _user(client, "reg-cross-ack-b", name="Admin B", role="admin")

    result_a = _activate(client, "reg-cross-ack-a", user_id=uid_a)
    alert_id_a = int(result_a["current_alert_id"])

    resp = _ack(client, "reg-cross-ack-b", alert_id=alert_id_a, user_id=uid_b)
    assert resp.status_code == 404, (
        f"REGRESSION: cross-tenant ack returned {resp.status_code} instead of 404"
    )


# ---------------------------------------------------------------------------
# 6. Training mode isolation
# ---------------------------------------------------------------------------

def test_training_alert_not_in_other_tenant_history(
    client: TestClient, login_super_admin
) -> None:
    """A training alert logged in A must not appear in B's /alerts history."""
    login_super_admin()
    _school(client, name="Reg Train A", slug="reg-train-a")
    _school(client, name="Reg Train B", slug="reg-train-b")

    uid_a = _user(client, "reg-train-a", name="Admin A", role="admin")
    _activate(
        client,
        "reg-train-a",
        user_id=uid_a,
        message="Training drill",
        is_training=True,
        training_label="Safety drill",
    )

    alerts_a = _alerts(client, "reg-train-a")
    assert any(a["message"] == "Training drill" and a["is_training"] for a in alerts_a), (
        "Expected training alert in reg-train-a's history"
    )

    alerts_b = _alerts(client, "reg-train-b")
    assert alerts_b == [], (
        f"REGRESSION: reg-train-b sees alerts from reg-train-a: {alerts_b}"
    )


def test_training_alarm_status_does_not_bleed(
    client: TestClient, login_super_admin
) -> None:
    """A training alarm active in A must not make B's alarm status show active."""
    login_super_admin()
    _school(client, name="Reg Train Status A", slug="reg-tstatus-a")
    _school(client, name="Reg Train Status B", slug="reg-tstatus-b")

    uid_a = _user(client, "reg-tstatus-a", name="Admin A", role="admin")
    _activate(
        client,
        "reg-tstatus-a",
        user_id=uid_a,
        message="Training status drill",
        is_training=True,
    )

    status_a = _alarm_status(client, "reg-tstatus-a")
    assert status_a["is_active"] is True
    assert status_a["is_training"] is True

    status_b = _alarm_status(client, "reg-tstatus-b")
    assert status_b["is_active"] is False, (
        "REGRESSION: B shows active after A's training alarm was triggered"
    )
    assert status_b["is_training"] is False, (
        "REGRESSION: B shows is_training=True from A's training alarm"
    )


def test_training_push_not_sent_to_any_tenant(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """A training alarm must not trigger any FCM push, even to A's own devices."""
    login_super_admin()
    _school(client, name="Reg Train Push", slug="reg-train-push")

    uid = _user(client, "reg-train-push", name="Admin", role="admin")
    _register_android(client, "reg-train-push", token="reg-train-fcm", user_id=uid)

    sent: list = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None) -> list:
        sent.append(list(tokens))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)
    result = _activate(
        client, "reg-train-push", user_id=uid, message="Training push drill", is_training=True
    )

    assert result["is_training"] is True
    assert sent == [], "REGRESSION: training alarm triggered FCM push delivery"
