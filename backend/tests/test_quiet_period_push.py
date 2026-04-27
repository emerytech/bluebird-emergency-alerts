"""
Quiet period push notification and expiry tests.

Invariants under test:
  1. Approving a request fires FCM send_with_data with "Quiet Period Approved" title.
  2. Denying a request fires FCM send_with_data with "Quiet Period Denied" title.
  3. Approve publishes a `quiet_period_approved` WebSocket event (not `quiet_request_updated`).
  4. Deny publishes a `quiet_period_denied` WebSocket event.
  5. Approving a request fires APNs send_with_data with "Quiet Period Approved" title.
  6. expire_and_return marks overdue approved records expired and returns them.
  7. Approve succeeds (200) when the requester has no registered device.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

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


def _request_quiet_period(client: TestClient, slug: str, *, user_id: int) -> int:
    resp = client.post(
        f"/{slug}/quiet-periods/request",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": user_id, "reason": "Test reason"},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["request_id"])


def _approve(client: TestClient, slug: str, *, request_id: int, admin_id: int) -> dict:
    resp = client.post(
        f"/{slug}/quiet-periods/{request_id}/approve",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": admin_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _deny(client: TestClient, slug: str, *, request_id: int, admin_id: int) -> dict:
    resp = client.post(
        f"/{slug}/quiet-periods/{request_id}/deny",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": admin_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _tenant_ctx(client: TestClient, slug: str):
    school = client.app.state.tenant_manager.school_for_slug(slug)
    return client.app.state.tenant_manager.get(school)


# ---------------------------------------------------------------------------
# 1. Approve fires FCM send_with_data with correct title
# ---------------------------------------------------------------------------

def test_approve_fires_fcm_push_with_correct_title(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    _create_school(client, name="QP Push Approve FCM", slug="qp-fcm-approve")
    requester_id = _create_user(client, "qp-fcm-approve", name="Officer A", role="law_enforcement")
    admin_id = _create_user(client, "qp-fcm-approve", name="Admin A", role="admin")
    _register_device(client, "qp-fcm-approve", token="fcm-token-requester", user_id=requester_id)

    sent_calls: list[tuple[list[str], str, str]] = []

    async def _fake_send_with_data(tokens, title, body, extra_data=None):
        sent_calls.append((list(tokens), title, body))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_with_data", _fake_send_with_data)

    request_id = _request_quiet_period(client, "qp-fcm-approve", user_id=requester_id)
    _approve(client, "qp-fcm-approve", request_id=request_id, admin_id=admin_id)

    assert any(
        "fcm-token-requester" in tokens and title == "Quiet Period Approved"
        for tokens, title, _ in sent_calls
    ), f"Expected FCM send_with_data with 'Quiet Period Approved', got: {sent_calls}"


# ---------------------------------------------------------------------------
# 2. Deny fires FCM send_with_data with correct title
# ---------------------------------------------------------------------------

def test_deny_fires_fcm_push_with_correct_title(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    _create_school(client, name="QP Push Deny FCM", slug="qp-fcm-deny")
    requester_id = _create_user(client, "qp-fcm-deny", name="Officer D", role="law_enforcement")
    admin_id = _create_user(client, "qp-fcm-deny", name="Admin D", role="admin")
    _register_device(client, "qp-fcm-deny", token="fcm-token-deny-req", user_id=requester_id)

    sent_calls: list[tuple[list[str], str, str]] = []

    async def _fake_send_with_data(tokens, title, body, extra_data=None):
        sent_calls.append((list(tokens), title, body))
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_with_data", _fake_send_with_data)

    request_id = _request_quiet_period(client, "qp-fcm-deny", user_id=requester_id)
    _deny(client, "qp-fcm-deny", request_id=request_id, admin_id=admin_id)

    assert any(
        "fcm-token-deny-req" in tokens and title == "Quiet Period Denied"
        for tokens, title, _ in sent_calls
    ), f"Expected FCM send_with_data with 'Quiet Period Denied', got: {sent_calls}"


# ---------------------------------------------------------------------------
# 3. Approve publishes quiet_period_approved WS event
# ---------------------------------------------------------------------------

def test_approve_publishes_quiet_period_approved_ws_event(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    _create_school(client, name="QP WS Approve", slug="qp-ws-approve")
    requester_id = _create_user(client, "qp-ws-approve", name="Officer WS", role="law_enforcement")
    admin_id = _create_user(client, "qp-ws-approve", name="Admin WS", role="admin")

    published: list[tuple[str, dict]] = []

    async def _fake_publish(slug: str, payload: dict) -> None:
        published.append((slug, dict(payload)))

    monkeypatch.setattr(client.app.state.alert_hub, "publish", _fake_publish)

    request_id = _request_quiet_period(client, "qp-ws-approve", user_id=requester_id)
    _approve(client, "qp-ws-approve", request_id=request_id, admin_id=admin_id)

    assert any(
        payload.get("event") == "quiet_period_approved"
        for _, payload in published
    ), f"Expected quiet_period_approved WS event, published: {published}"


# ---------------------------------------------------------------------------
# 4. Deny publishes quiet_period_denied WS event
# ---------------------------------------------------------------------------

def test_deny_publishes_quiet_period_denied_ws_event(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    _create_school(client, name="QP WS Deny", slug="qp-ws-deny")
    requester_id = _create_user(client, "qp-ws-deny", name="Officer WS2", role="law_enforcement")
    admin_id = _create_user(client, "qp-ws-deny", name="Admin WS2", role="admin")

    published: list[tuple[str, dict]] = []

    async def _fake_publish(slug: str, payload: dict) -> None:
        published.append((slug, dict(payload)))

    monkeypatch.setattr(client.app.state.alert_hub, "publish", _fake_publish)

    request_id = _request_quiet_period(client, "qp-ws-deny", user_id=requester_id)
    _deny(client, "qp-ws-deny", request_id=request_id, admin_id=admin_id)

    assert any(
        payload.get("event") == "quiet_period_denied"
        for _, payload in published
    ), f"Expected quiet_period_denied WS event, published: {published}"


# ---------------------------------------------------------------------------
# 5. Approve fires APNs send_with_data with correct title
# ---------------------------------------------------------------------------

def test_approve_fires_apns_push_with_correct_title(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    _create_school(client, name="QP Push Approve APNs", slug="qp-apns-approve")
    requester_id = _create_user(client, "qp-apns-approve", name="Officer APNs", role="law_enforcement")
    admin_id = _create_user(client, "qp-apns-approve", name="Admin APNs", role="admin")
    _register_device(
        client, "qp-apns-approve",
        token="a" * 64, user_id=requester_id,
        platform="ios", push_provider="apns",
    )

    sent_calls: list[tuple[list[str], str, str]] = []

    async def _fake_send_with_data(tokens, title, body, extra_data=None):
        sent_calls.append((list(tokens), title, body))
        return []

    monkeypatch.setattr(client.app.state.apns_client, "send_with_data", _fake_send_with_data)

    request_id = _request_quiet_period(client, "qp-apns-approve", user_id=requester_id)
    _approve(client, "qp-apns-approve", request_id=request_id, admin_id=admin_id)

    assert any(
        ("a" * 64) in tokens and title == "Quiet Period Approved"
        for tokens, title, _ in sent_calls
    ), f"Expected APNs send_with_data with 'Quiet Period Approved', got: {sent_calls}"


# ---------------------------------------------------------------------------
# 6. expire_and_return marks overdue records expired and returns them
# ---------------------------------------------------------------------------

def test_expire_and_return_marks_expired_records(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone
    from app.services.quiet_period_store import QuietPeriodStore

    db = str(tmp_path / "qp_test.db")
    store = QuietPeriodStore(db)

    # Insert an already-expired approved record directly via the grant flow,
    # then backdate expires_at to the past.
    import sqlite3
    conn = sqlite3.connect(db, isolation_level=None)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute(
        """
        INSERT INTO quiet_period_requests
            (user_id, reason, status, requested_at, approved_at, approved_by_user_id, expires_at)
        VALUES (42, 'test', 'approved', ?, ?, 1, ?);
        """,
        (past, past, past),
    )
    conn.close()

    expired = asyncio.run(store.expire_and_return())

    assert len(expired) == 1
    assert expired[0].user_id == 42
    assert expired[0].status == "approved"  # status at read time (before update is reflected in row)

    # Verify DB now shows status = expired
    conn2 = sqlite3.connect(db)
    row = conn2.execute("SELECT status FROM quiet_period_requests WHERE user_id = 42;").fetchone()
    conn2.close()
    assert row is not None and row[0] == "expired"


# ---------------------------------------------------------------------------
# 7. Approve succeeds when requester has no registered device
# ---------------------------------------------------------------------------

def test_approve_succeeds_when_user_has_no_device(client: TestClient, login_super_admin, monkeypatch) -> None:
    login_super_admin()
    _create_school(client, name="QP No Device", slug="qp-no-device")
    requester_id = _create_user(client, "qp-no-device", name="Officer No Dev", role="law_enforcement")
    admin_id = _create_user(client, "qp-no-device", name="Admin No Dev", role="admin")
    # No device registered for requester_id

    sent_calls: list = []

    async def _fake_send_with_data(tokens, title, body, extra_data=None):
        sent_calls.append(tokens)
        return []

    monkeypatch.setattr(client.app.state.fcm_client, "send_with_data", _fake_send_with_data)
    monkeypatch.setattr(client.app.state.apns_client, "send_with_data", _fake_send_with_data)

    request_id = _request_quiet_period(client, "qp-no-device", user_id=requester_id)
    result = _approve(client, "qp-no-device", request_id=request_id, admin_id=admin_id)

    assert result["status"] == "approved"
    # send_with_data should not have been called (no device tokens)
    assert not any(tokens for tokens in sent_calls)
