"""
Per-device push routing invariants for help_request alerts.

Backend must send different payloads to sender vs responder devices so that
the sender is silent even when the app is backgrounded or closed (APNs plays
aps.sound before any app code can run).

Invariants under test:
  1. Sender iOS token is routed to send_silent_for_sender (no aps.sound path).
  2. Responder iOS token is routed to send_bulk (aps.sound = help_request_alert.caf path).
  3. Sender iOS token never appears in send_bulk.
  4. Responder iOS token never appears in send_silent_for_sender.
  5. Sender Android token receives push with silent_for_sender="true".
  6. Responder Android token receives push with silent_for_sender="false".
  7. Emergency (incident) push is unchanged — uses send_bulk only.
  8. No cross-tenant token delivery.
"""
from __future__ import annotations

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


def _register_ios(client: TestClient, slug: str, *, token: str, user_id: int) -> None:
    resp = client.post(
        f"/{slug}/devices/register",
        headers={"X-API-Key": "test-api-key"},
        json={
            "device_token": token,
            "platform": "ios",
            "push_provider": "apns",
            "device_name": "Test iPhone",
            "user_id": user_id,
        },
    )
    assert resp.status_code == 200, resp.text


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


def _create_help_request(
    client: TestClient,
    slug: str,
    *,
    sender_id: int,
    responder_ids: list[int],
) -> dict:
    resp = client.post(
        f"/{slug}/team-assist/create",
        headers={"X-API-Key": "test-api-key"},
        json={"type": "medical", "user_id": sender_id, "assigned_team_ids": responder_ids},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_incident(client: TestClient, slug: str, *, user_id: int) -> dict:
    resp = client.post(
        f"/{slug}/incidents/create",
        headers={"X-API-Key": "test-api-key"},
        json={"type": "lockdown", "user_id": user_id, "target_scope": "ALL", "metadata": {}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 1–4. APNs routing: sender → send_silent_for_sender, responder → send_bulk
# ---------------------------------------------------------------------------

_APNS_SENDER_1 = "a" * 64
_APNS_RESP_1   = "b" * 64
_APNS_SENDER_2 = "c" * 64
_APNS_RESP_2   = "d" * 64
_APNS_EMERG    = "e" * 64


def test_help_request_sender_ios_routed_to_silent_path(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """Sender's iOS token must be delivered via send_silent_for_sender, never via send_bulk."""
    login_super_admin()
    _create_school(client, name="HR APNs Sender", slug="hr-apns-sender")

    sender_id = _create_user(client, "hr-apns-sender", name="Sender", role="teacher")
    responder_id = _create_user(client, "hr-apns-sender", name="Responder", role="admin")

    _register_ios(client, "hr-apns-sender", token=_APNS_SENDER_1, user_id=sender_id)
    _register_ios(client, "hr-apns-sender", token=_APNS_RESP_1, user_id=responder_id)

    bulk_calls: list[tuple[list[str], str, dict]] = []
    silent_calls: list[tuple[list[str], str, str, dict]] = []

    async def _fake_bulk(tokens: list[str], message: str, extra_data=None):
        bulk_calls.append((list(tokens), message, extra_data or {}))
        return []

    async def _fake_silent(tokens: list[str], title: str, body: str, extra_data=None):
        silent_calls.append((list(tokens), title, body, extra_data or {}))
        return []

    monkeypatch.setattr(client.app.state.apns_client, "send_bulk", _fake_bulk)
    monkeypatch.setattr(client.app.state.apns_client, "send_silent_for_sender", _fake_silent)

    _create_help_request(client, "hr-apns-sender", sender_id=sender_id, responder_ids=[responder_id])

    bulk_tokens = {t for (tokens, _, _d) in bulk_calls for t in tokens}
    silent_tokens = {t for (tokens, _, _b, _d) in silent_calls for t in tokens}

    assert _APNS_SENDER_1 in silent_tokens, (
        "Sender's iOS token must be delivered via send_silent_for_sender"
    )
    assert _APNS_SENDER_1 not in bulk_tokens, (
        "SAFETY FAILURE: sender's iOS token appeared in send_bulk (would play alarm sound)"
    )


def test_help_request_responder_ios_routed_to_sound_path(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """Responder's iOS token must be delivered via send_bulk (sound path), not silent path."""
    login_super_admin()
    _create_school(client, name="HR APNs Responder", slug="hr-apns-resp")

    sender_id = _create_user(client, "hr-apns-resp", name="Sender", role="teacher")
    responder_id = _create_user(client, "hr-apns-resp", name="Responder", role="admin")

    _register_ios(client, "hr-apns-resp", token=_APNS_SENDER_2, user_id=sender_id)
    _register_ios(client, "hr-apns-resp", token=_APNS_RESP_2, user_id=responder_id)

    bulk_calls: list[tuple[list[str], str, dict]] = []
    silent_calls: list[tuple[list[str], str, str, dict]] = []

    async def _fake_bulk(tokens: list[str], message: str, extra_data=None):
        bulk_calls.append((list(tokens), message, extra_data or {}))
        return []

    async def _fake_silent(tokens: list[str], title: str, body: str, extra_data=None):
        silent_calls.append((list(tokens), title, body, extra_data or {}))
        return []

    monkeypatch.setattr(client.app.state.apns_client, "send_bulk", _fake_bulk)
    monkeypatch.setattr(client.app.state.apns_client, "send_silent_for_sender", _fake_silent)

    _create_help_request(client, "hr-apns-resp", sender_id=sender_id, responder_ids=[responder_id])

    bulk_tokens = {t for (tokens, _, _d) in bulk_calls for t in tokens}
    silent_tokens = {t for (tokens, _, _b, _d) in silent_calls for t in tokens}

    assert _APNS_RESP_2 in bulk_tokens, (
        "Responder's iOS token must be delivered via send_bulk (sound path)"
    )
    assert _APNS_RESP_2 not in silent_tokens, (
        "Responder's iOS token must not be silenced"
    )


# ---------------------------------------------------------------------------
# 5–6. FCM routing: extra_data["silent_for_sender"] differentiates paths
# ---------------------------------------------------------------------------

def test_help_request_sender_android_receives_silent_flag(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """Sender's Android token must be called with silent_for_sender='true' in extra_data."""
    login_super_admin()
    _create_school(client, name="HR FCM Sender", slug="hr-fcm-sender")

    sender_id = _create_user(client, "hr-fcm-sender", name="Sender", role="teacher")
    responder_id = _create_user(client, "hr-fcm-sender", name="Responder", role="admin")

    _register_android(client, "hr-fcm-sender", token="fcm-sender-tok", user_id=sender_id)
    _register_android(client, "hr-fcm-sender", token="fcm-responder-tok", user_id=responder_id)

    fcm_calls: list[tuple[list[str], str, dict]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message, extra_data or {}))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    _create_help_request(client, "hr-fcm-sender", sender_id=sender_id, responder_ids=[responder_id])

    sender_calls = [
        (tokens, data) for (tokens, _, data) in fcm_calls
        if "fcm-sender-tok" in tokens
    ]
    assert sender_calls, "Sender's Android token must receive a push"
    for _, data in sender_calls:
        assert data.get("silent_for_sender") == "true", (
            f"SAFETY FAILURE: sender's FCM push missing silent_for_sender='true', got {data}"
        )


def test_help_request_responder_android_receives_non_silent_flag(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """Responder's Android token must be called with silent_for_sender='false' in extra_data."""
    login_super_admin()
    _create_school(client, name="HR FCM Responder", slug="hr-fcm-resp")

    sender_id = _create_user(client, "hr-fcm-resp", name="Sender", role="teacher")
    responder_id = _create_user(client, "hr-fcm-resp", name="Responder", role="admin")

    _register_android(client, "hr-fcm-resp", token="fcm-resp-sender", user_id=sender_id)
    _register_android(client, "hr-fcm-resp", token="fcm-resp-responder", user_id=responder_id)

    fcm_calls: list[tuple[list[str], str, dict]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message, extra_data or {}))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    _create_help_request(client, "hr-fcm-resp", sender_id=sender_id, responder_ids=[responder_id])

    responder_calls = [
        (tokens, data) for (tokens, _, data) in fcm_calls
        if "fcm-resp-responder" in tokens
    ]
    assert responder_calls, "Responder's Android token must receive a push"
    for _, data in responder_calls:
        assert data.get("silent_for_sender") != "true", (
            f"Responder's FCM push must not have silent_for_sender='true', got {data}"
        )


# ---------------------------------------------------------------------------
# 7. Emergency (incident) push unchanged — send_bulk only, no silent path
# ---------------------------------------------------------------------------

def test_emergency_incident_push_unchanged(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """Emergency incident push must use send_bulk only; send_silent_for_sender must not be called."""
    login_super_admin()
    _create_school(client, name="HR Emergency", slug="hr-emergency")

    admin_id = _create_user(client, "hr-emergency", name="Admin", role="admin")
    _register_ios(client, "hr-emergency", token=_APNS_EMERG, user_id=admin_id)
    _register_android(client, "hr-emergency", token="fcm-emerg-tok", user_id=admin_id)

    bulk_calls: list = []
    silent_calls: list = []

    async def _fake_bulk(tokens: list[str], message: str, extra_data=None):
        bulk_calls.append(list(tokens))
        return []

    async def _fake_silent(tokens: list[str], title: str, body: str, extra_data=None):
        silent_calls.append(list(tokens))
        return []

    monkeypatch.setattr(client.app.state.apns_client, "send_bulk", _fake_bulk)
    monkeypatch.setattr(client.app.state.apns_client, "send_silent_for_sender", _fake_silent)

    _create_incident(client, "hr-emergency", user_id=admin_id)

    assert bulk_calls, "Emergency incident must trigger send_bulk"
    assert silent_calls == [], (
        "REGRESSION: send_silent_for_sender was called for an emergency incident — must not be"
    )


# ---------------------------------------------------------------------------
# 8. Cross-tenant isolation — no tokens from other tenants
# ---------------------------------------------------------------------------

def test_help_request_cross_tenant_isolation(
    client: TestClient, login_super_admin, monkeypatch
) -> None:
    """Tenant B's devices must never receive tenant A's help_request push."""
    login_super_admin()
    _create_school(client, name="HR Tenant A", slug="hr-tenant-a")
    _create_school(client, name="HR Tenant B", slug="hr-tenant-b")

    sender_a = _create_user(client, "hr-tenant-a", name="Sender A", role="teacher")
    responder_a = _create_user(client, "hr-tenant-a", name="Responder A", role="admin")
    user_b = _create_user(client, "hr-tenant-b", name="User B", role="admin")

    _register_android(client, "hr-tenant-a", token="fcm-a-sender", user_id=sender_a)
    _register_android(client, "hr-tenant-a", token="fcm-a-responder", user_id=responder_a)
    _register_android(client, "hr-tenant-b", token="fcm-b-user", user_id=user_b)

    fcm_calls: list[tuple[list[str], str, dict]] = []

    async def _fake_fcm(tokens: list[str], message: str, extra_data=None):
        fcm_calls.append((list(tokens), message, extra_data or {}))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_bulk", _fake_fcm)

    _create_help_request(client, "hr-tenant-a", sender_id=sender_a, responder_ids=[responder_a])

    all_tokens = {t for (tokens, _, _d) in fcm_calls for t in tokens}
    assert "fcm-b-user" not in all_tokens, (
        "ISOLATION FAILURE: tenant B's token appeared in tenant A's help_request push"
    )
