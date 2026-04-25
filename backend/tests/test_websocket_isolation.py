"""
WebSocket tenant isolation tests for AlertHub and the /ws/{tenant_slug}/alerts endpoint.

Invariants under test:
  - AlertHub.publish delivers only to the target tenant's connections.
  - AlertHub.publish with an empty/blank slug is dropped; no connection receives it.
  - AlertHub.connect/disconnect are scoped: connecting under slug-a does not create
    an entry for slug-b, and disconnecting slug-a does not remove slug-b connections.
  - The WebSocket endpoint rejects unknown tenant slugs with close code 4404.
  - The WebSocket endpoint rejects missing/invalid API keys with close code 4401.
  - A live WebSocket connected to tenant A receives events published for A.
  - A live WebSocket connected to tenant B does NOT receive events published for A.
"""
from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.services.alert_hub import AlertHub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_websocket() -> MagicMock:
    """Return a minimal mock that satisfies AlertHub's usage of WebSocket."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# AlertHub unit tests (pure asyncio, no HTTP stack needed)
# ---------------------------------------------------------------------------

class TestAlertHubIsolation:
    """Unit tests that exercise AlertHub in isolation using mock WebSockets."""

    def test_publish_reaches_only_target_tenant(self) -> None:
        async def _run() -> None:
            hub = AlertHub()
            ws_a = _make_mock_websocket()
            ws_b = _make_mock_websocket()

            # Connect ws_a to "school-a" and ws_b to "school-b".
            await hub.connect("school-a", ws_a)
            await hub.connect("school-b", ws_b)

            payload = {"event": "alert_triggered", "tenant_slug": "school-a"}
            await hub.publish("school-a", payload)

            encoded = json.dumps(payload, separators=(",", ":"), default=str)
            ws_a.send_text.assert_awaited_once_with(encoded)
            ws_b.send_text.assert_not_awaited()

        asyncio.run(_run())

    def test_publish_empty_slug_is_dropped(self) -> None:
        async def _run() -> None:
            hub = AlertHub()
            ws_a = _make_mock_websocket()
            await hub.connect("school-a", ws_a)

            # Neither "" nor "   " should reach any connection.
            await hub.publish("", {"event": "alert_triggered"})
            await hub.publish("   ", {"event": "alert_triggered"})

            ws_a.send_text.assert_not_awaited()

        asyncio.run(_run())

    def test_publish_none_slug_is_dropped(self) -> None:
        async def _run() -> None:
            hub = AlertHub()
            ws_a = _make_mock_websocket()
            await hub.connect("school-a", ws_a)

            # Passing None should be coerced to "" and dropped.
            await hub.publish(None, {"event": "alert_triggered"})  # type: ignore[arg-type]

            ws_a.send_text.assert_not_awaited()

        asyncio.run(_run())

    def test_disconnect_does_not_remove_other_tenant_connections(self) -> None:
        async def _run() -> None:
            hub = AlertHub()
            ws_a = _make_mock_websocket()
            ws_b = _make_mock_websocket()

            await hub.connect("school-a", ws_a)
            await hub.connect("school-b", ws_b)

            await hub.disconnect("school-a", ws_a)

            # school-b must still be reachable.
            payload = {"event": "admin_update", "tenant_slug": "school-b"}
            await hub.publish("school-b", payload)

            encoded = json.dumps(payload, separators=(",", ":"), default=str)
            ws_b.send_text.assert_awaited_once_with(encoded)

        asyncio.run(_run())

    def test_multiple_connections_per_tenant(self) -> None:
        async def _run() -> None:
            hub = AlertHub()
            ws1 = _make_mock_websocket()
            ws2 = _make_mock_websocket()
            ws_other = _make_mock_websocket()

            await hub.connect("school-a", ws1)
            await hub.connect("school-a", ws2)
            await hub.connect("school-b", ws_other)

            payload = {"event": "alert_triggered", "tenant_slug": "school-a"}
            await hub.publish("school-a", payload)

            encoded = json.dumps(payload, separators=(",", ":"), default=str)
            ws1.send_text.assert_awaited_once_with(encoded)
            ws2.send_text.assert_awaited_once_with(encoded)
            ws_other.send_text.assert_not_awaited()

        asyncio.run(_run())

    def test_connection_count_helper(self) -> None:
        async def _run() -> None:
            hub = AlertHub()
            assert hub.connection_count("school-a") == 0

            ws1 = _make_mock_websocket()
            ws2 = _make_mock_websocket()
            await hub.connect("school-a", ws1)
            assert hub.connection_count("school-a") == 1

            await hub.connect("school-a", ws2)
            assert hub.connection_count("school-a") == 2

            await hub.disconnect("school-a", ws1)
            assert hub.connection_count("school-a") == 1

        asyncio.run(_run())

    def test_connected_slugs_helper(self) -> None:
        async def _run() -> None:
            hub = AlertHub()
            assert hub.connected_slugs() == []

            ws_a = _make_mock_websocket()
            ws_b = _make_mock_websocket()
            await hub.connect("school-a", ws_a)
            await hub.connect("school-b", ws_b)

            slugs = set(hub.connected_slugs())
            assert slugs == {"school-a", "school-b"}

            await hub.disconnect("school-a", ws_a)
            assert hub.connected_slugs() == ["school-b"]

        asyncio.run(_run())

    def test_stale_connection_pruned_on_send_error(self) -> None:
        async def _run() -> None:
            hub = AlertHub()
            ws_stale = _make_mock_websocket()
            ws_good = _make_mock_websocket()
            ws_stale.send_text = AsyncMock(side_effect=RuntimeError("disconnected"))

            await hub.connect("school-a", ws_stale)
            await hub.connect("school-a", ws_good)

            payload = {"event": "alert_triggered"}
            await hub.publish("school-a", payload)

            # ws_stale should be removed; ws_good should have received the message.
            assert hub.connection_count("school-a") == 1
            ws_good.send_text.assert_awaited_once()

        asyncio.run(_run())

    def test_publish_b_does_not_affect_a(self) -> None:
        """Bidirectional: publishing to B must not reach A's connection."""
        async def _run() -> None:
            hub = AlertHub()
            ws_a = _make_mock_websocket()
            ws_b = _make_mock_websocket()

            await hub.connect("school-a", ws_a)
            await hub.connect("school-b", ws_b)

            await hub.publish("school-b", {"event": "alert_triggered", "tenant_slug": "school-b"})

            ws_a.send_text.assert_not_awaited()
            ws_b.send_text.assert_awaited_once()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# WebSocket endpoint tests (TestClient — HTTP upgrade path)
# ---------------------------------------------------------------------------

def _create_school(client: TestClient, *, name: str, slug: str) -> None:
    resp = client.post(
        "/super-admin/schools/create",
        data={"name": name, "slug": slug, "setup_pin": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text


def test_websocket_unknown_tenant_closes_4404(client: TestClient) -> None:
    """A slug that resolves to no school must close with code 4404."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/nonexistent-xyz/alerts",
            headers={"X-API-Key": "test-api-key"},
        ) as ws:
            ws.receive_json()
    assert exc_info.value.code == 4404


def test_websocket_invalid_api_key_closes_4401(client: TestClient, login_super_admin) -> None:
    """A valid tenant slug with a wrong API key must close with code 4401."""
    login_super_admin()
    _create_school(client, name="API Key School", slug="apikey-school")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/apikey-school/alerts",
            headers={"X-API-Key": "wrong-key"},
        ) as ws:
            ws.receive_json()
    assert exc_info.value.code == 4401


def test_websocket_accepts_valid_tenant_and_key(client: TestClient, login_super_admin) -> None:
    """A valid slug + correct API key must produce an accepted WebSocket connection."""
    login_super_admin()
    _create_school(client, name="Valid School", slug="valid-school")

    # If the server closes, receive_json() will raise — so we just verify we can connect.
    received: list[dict] = []
    done = threading.Event()

    def _reader(ws_conn):
        try:
            data = ws_conn.receive_json()
            received.append(data)
        except Exception:
            pass
        finally:
            done.set()

    with client.websocket_connect(
        "/ws/valid-school/alerts",
        headers={"X-API-Key": "test-api-key"},
    ) as ws:
        t = threading.Thread(target=_reader, args=(ws,), daemon=True)
        t.start()
        # Publish a payload directly into the hub to verify the connection is live.
        hub = client.app.state.alert_hub
        asyncio.run(hub.publish("valid-school", {"event": "admin_update", "tenant_slug": "valid-school"}))
        done.wait(timeout=2.0)

    assert received, "Expected at least one message from hub publish to valid-school"
    assert received[0]["event"] == "admin_update"


# ---------------------------------------------------------------------------
# Cross-tenant live isolation test
# ---------------------------------------------------------------------------

def test_cross_tenant_websocket_isolation(client: TestClient, login_super_admin) -> None:
    """
    Connect a WebSocket to school-ws-a and another to school-ws-b.
    Publish an event exclusively to school-ws-a.
    Assert school-ws-a's socket receives it; school-ws-b's socket receives nothing.
    """
    login_super_admin()
    _create_school(client, name="WS School A", slug="ws-school-a")
    _create_school(client, name="WS School B", slug="ws-school-b")

    received_a: list[dict] = []
    received_b: list[dict] = []

    with (
        client.websocket_connect(
            "/ws/ws-school-a/alerts",
            headers={"X-API-Key": "test-api-key"},
        ) as ws_a,
        client.websocket_connect(
            "/ws/ws-school-b/alerts",
            headers={"X-API-Key": "test-api-key"},
        ) as ws_b,
    ):
        done_a = threading.Event()
        done_b = threading.Event()

        def _reader_a():
            try:
                received_a.append(ws_a.receive_json())
            except Exception:
                pass
            finally:
                done_a.set()

        def _reader_b():
            try:
                received_b.append(ws_b.receive_json())
            except Exception:
                pass
            finally:
                done_b.set()

        t_a = threading.Thread(target=_reader_a, daemon=True)
        t_b = threading.Thread(target=_reader_b, daemon=True)
        t_a.start()
        t_b.start()

        hub = client.app.state.alert_hub
        payload = {"event": "alert_triggered", "tenant_slug": "ws-school-a"}
        asyncio.run(hub.publish("ws-school-a", payload))

        # Give ws_a time to receive; ws_b should NOT receive within the window.
        done_a.wait(timeout=2.0)
        done_b.wait(timeout=0.5)  # Short wait — we expect nothing here.

    assert received_a, "ISOLATION FAILURE: ws-school-a did not receive its own alert event"
    assert received_a[0]["event"] == "alert_triggered"

    assert received_b == [], (
        f"ISOLATION FAILURE: ws-school-b received an event intended for ws-school-a: {received_b}"
    )
