"""
Silent alarm tests.

Invariants under test:
  1. Alarm push includes triggered_by_user_id and silent_for_sender=1 in FCM extra_data.
  2. Alarm push includes triggered_by_user_id and silent_for_sender=1 in APNs extra_data.
  3. All registered tokens receive the push — the sender is not excluded.
  4. Sender with multiple devices: all their tokens receive silent_for_sender=1 metadata.
  5. alert_triggered WS event includes triggered_by_user_id and silent_for_sender fields.
  6. AlarmStatusResponse includes triggered_by_user_id and silent_for_sender=True.
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


def _register_device(
    client: TestClient,
    slug: str,
    *,
    token: str,
    user_id: int,
    platform: str = "android",
    push_provider: str = "fcm",
) -> None:
    resp = client.post(
        f"/{slug}/devices/register",
        headers={"X-API-Key": "test-api-key"},
        json={
            "device_token": token,
            "platform": platform,
            "push_provider": push_provider,
            "device_name": "Test Device",
            "user_id": user_id,
        },
    )
    assert resp.status_code == 200, resp.text


def _activate_alarm(client: TestClient, slug: str, *, user_id: int, message: str = "Lockdown") -> dict:
    resp = client.post(
        f"/{slug}/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": message, "user_id": user_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 1. FCM extra_data contains triggered_by_user_id and silent_for_sender
# ---------------------------------------------------------------------------

def test_fcm_push_includes_silent_alarm_metadata(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    _create_school(client, name="Silent FCM", slug="silent-fcm")
    sender_uid = _create_user(client, "silent-fcm", name="Sender", role="teacher")
    _register_device(client, "silent-fcm", token="fcm-sender-token", user_id=sender_uid)

    fcm_calls: list[tuple[list[str], str, dict]] = []

    async def _fake_send_bulk(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message, dict(extra_data or {})))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_send_bulk)
    _activate_alarm(client, "silent-fcm", user_id=sender_uid)

    assert fcm_calls, "FCM send_bulk was not called"
    _, _, extra = fcm_calls[0]
    assert extra.get("triggered_by_user_id") == str(sender_uid), (
        f"Expected triggered_by_user_id={sender_uid!r}, got extra={extra!r}"
    )
    assert extra.get("silent_for_sender") == "1", (
        f"Expected silent_for_sender='1', got extra={extra!r}"
    )


# ---------------------------------------------------------------------------
# 2. APNs extra_data contains triggered_by_user_id and silent_for_sender
# ---------------------------------------------------------------------------

def test_apns_push_includes_silent_alarm_metadata(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    _create_school(client, name="Silent APNs", slug="silent-apns")
    sender_uid = _create_user(client, "silent-apns", name="Sender iOS", role="teacher")

    # APNs tokens must be hex strings.
    apns_token = "b" * 64
    _register_device(
        client, "silent-apns",
        token=apns_token, user_id=sender_uid,
        platform="ios", push_provider="apns",
    )

    apns_calls: list[tuple[list[str], str, dict]] = []

    async def _fake_send_bulk(tokens: list[str], message: str, extra_data=None):
        apns_calls.append((list(tokens), message, dict(extra_data or {})))
        return []

    monkeypatch.setattr(client.app.state.apns_client, "send_bulk", _fake_send_bulk)
    _activate_alarm(client, "silent-apns", user_id=sender_uid)

    assert apns_calls, "APNs send_bulk was not called"
    _, _, extra = apns_calls[0]
    assert extra.get("triggered_by_user_id") == str(sender_uid), (
        f"Expected triggered_by_user_id={sender_uid!r}, got extra={extra!r}"
    )
    assert extra.get("silent_for_sender") == "1", (
        f"Expected silent_for_sender='1', got extra={extra!r}"
    )


# ---------------------------------------------------------------------------
# 3. Sender's token is NOT excluded — all tokens receive the push
# ---------------------------------------------------------------------------

def test_sender_token_is_not_excluded_from_push(client: TestClient, login_super_admin, monkeypatch) -> None:
    """
    Silent alarm: the sender receives the push but their client suppresses
    audio/vibration. The sender's token must still be delivered.
    """
    login_super_admin()
    _create_school(client, name="Silent Sender Incl", slug="silent-sender-incl")
    sender_uid = _create_user(client, "silent-sender-incl", name="Sender", role="teacher")
    other_uid = _create_user(client, "silent-sender-incl", name="Other", role="teacher")
    _register_device(client, "silent-sender-incl", token="fcm-sender-s", user_id=sender_uid)
    _register_device(client, "silent-sender-incl", token="fcm-other-s", user_id=other_uid)

    all_tokens: set[str] = set()

    async def _fake_send_bulk(tokens: list[str], message: str, extra_data=None):
        all_tokens.update(tokens)
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_send_bulk)
    _activate_alarm(client, "silent-sender-incl", user_id=sender_uid)

    assert "fcm-sender-s" in all_tokens, (
        "REGRESSION: sender's token was excluded from the push — "
        "silent mode is client-side only; all tokens must be delivered"
    )
    assert "fcm-other-s" in all_tokens, "Other user must also receive push"


# ---------------------------------------------------------------------------
# 4. Multi-device sender: all their tokens carry silent_for_sender=1
# ---------------------------------------------------------------------------

def test_multi_device_sender_all_tokens_carry_silent_metadata(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    login_super_admin()
    _create_school(client, name="Silent Multi Device", slug="silent-multi-dev")
    sender_uid = _create_user(client, "silent-multi-dev", name="Sender Multi", role="teacher")
    _register_device(client, "silent-multi-dev", token="fcm-dev-1", user_id=sender_uid)
    _register_device(client, "silent-multi-dev", token="fcm-dev-2", user_id=sender_uid)

    captured_extra: list[dict] = []
    captured_tokens: list[str] = []

    async def _fake_send_bulk(tokens: list[str], message: str, extra_data=None):
        captured_tokens.extend(tokens)
        captured_extra.append(dict(extra_data or {}))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_send_bulk)
    _activate_alarm(client, "silent-multi-dev", user_id=sender_uid)

    assert "fcm-dev-1" in captured_tokens, "First device must receive push"
    assert "fcm-dev-2" in captured_tokens, "Second device must receive push"
    for extra in captured_extra:
        assert extra.get("silent_for_sender") == "1", (
            f"All FCM calls must carry silent_for_sender=1, got: {extra!r}"
        )


# ---------------------------------------------------------------------------
# 5. alert_triggered WS event includes triggered_by_user_id and silent_for_sender
# ---------------------------------------------------------------------------

def test_alert_triggered_ws_event_includes_silent_fields(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    login_super_admin()
    _create_school(client, name="Silent WS", slug="silent-ws")
    sender_uid = _create_user(client, "silent-ws", name="Sender WS", role="teacher")

    published: list[tuple[str, dict]] = []

    async def _fake_publish(slug: str, payload: dict) -> None:
        published.append((slug, dict(payload)))

    monkeypatch.setattr(client.app.state.alert_hub, "publish", _fake_publish)
    _activate_alarm(client, "silent-ws", user_id=sender_uid)

    alert_events = [p for _, p in published if p.get("event") == "alert_triggered"]
    assert alert_events, f"No alert_triggered WS event found in: {published}"

    event = alert_events[0]
    alarm = event.get("alarm", {})
    assert alarm.get("triggered_by_user_id") == sender_uid, (
        f"Expected triggered_by_user_id={sender_uid}, got alarm={alarm!r}"
    )
    assert alarm.get("silent_for_sender") is True, (
        f"Expected silent_for_sender=True, got alarm={alarm!r}"
    )


# ---------------------------------------------------------------------------
# 6. AlarmStatusResponse includes triggered_by_user_id and silent_for_sender
# ---------------------------------------------------------------------------

def test_activate_response_includes_silent_alarm_fields(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    login_super_admin()
    _create_school(client, name="Silent Response", slug="silent-resp")
    sender_uid = _create_user(client, "silent-resp", name="Sender Resp", role="teacher")

    async def _fake_send_bulk(tokens, message, extra_data=None):
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_send_bulk)
    monkeypatch.setattr(client.app.state.apns_client, "send_bulk", _fake_send_bulk)

    resp = client.post(
        "/silent-resp/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"message": "Lockdown", "user_id": sender_uid},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data.get("triggered_by_user_id") == sender_uid, (
        f"Expected triggered_by_user_id={sender_uid}, got: {data!r}"
    )
    assert data.get("silent_for_sender") is True, (
        f"Expected silent_for_sender=True, got: {data!r}"
    )
