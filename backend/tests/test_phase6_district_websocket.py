"""
Phase 6 — District WebSocket tests.

Covers:
  - AlertHub.connect_district / disconnect_district / district publish fan-out (unit)
  - /ws/district/alerts endpoint: auth, role gates, slug subscription scoping (integration)
  - Existing per-tenant /ws/{slug}/alerts still works alongside district connections
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
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


def _create_school(client: TestClient, *, name: str, slug: str) -> None:
    r = client.post(
        "/super-admin/schools/create",
        data={"name": name, "slug": slug},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text


def _create_user(client: TestClient, slug: str, *, name: str, role: str) -> int:
    r = client.post(
        f"/{slug}/users",
        headers={"X-API-Key": "test-api-key"},
        json={"name": name, "role": role},
    )
    assert r.status_code == 200, r.text
    return int(r.json()["user_id"])


def _get_school(client: TestClient, slug: str):
    return client.app.state.tenant_manager.school_for_slug(slug)


def _assign_tenant(client: TestClient, *, user_id: int, home_tenant_id: int, tenant_ids: list[int]) -> None:
    asyncio.run(
        client.app.state.user_tenant_store.replace_assignments(
            user_id=user_id,
            home_tenant_id=home_tenant_id,
            tenant_ids=tenant_ids,
        )
    )


# ---------------------------------------------------------------------------
# AlertHub district unit tests
# ---------------------------------------------------------------------------

class TestAlertHubDistrict:

    def test_connect_district_receives_subscribed_slug_events(self) -> None:
        async def _run():
            hub = AlertHub()
            ws = _make_mock_websocket()
            await hub.connect_district(ws, frozenset({"school-a", "school-b"}))

            payload = {"event": "alert_triggered", "tenant_slug": "school-a"}
            await hub.publish("school-a", payload)

            encoded = json.dumps(payload, separators=(",", ":"), default=str)
            ws.send_text.assert_awaited_once_with(encoded)

        asyncio.run(_run())

    def test_connect_district_does_not_receive_unsubscribed_slug(self) -> None:
        async def _run():
            hub = AlertHub()
            ws = _make_mock_websocket()
            await hub.connect_district(ws, frozenset({"school-a"}))

            await hub.publish("school-b", {"event": "alert_triggered", "tenant_slug": "school-b"})

            ws.send_text.assert_not_awaited()

        asyncio.run(_run())

    def test_disconnect_district_stops_delivery(self) -> None:
        async def _run():
            hub = AlertHub()
            ws = _make_mock_websocket()
            await hub.connect_district(ws, frozenset({"school-a"}))
            await hub.disconnect_district(ws)

            await hub.publish("school-a", {"event": "alert_triggered", "tenant_slug": "school-a"})

            ws.send_text.assert_not_awaited()

        asyncio.run(_run())

    def test_district_connection_count_helper(self) -> None:
        async def _run():
            hub = AlertHub()
            assert hub.district_connection_count() == 0

            ws1 = _make_mock_websocket()
            ws2 = _make_mock_websocket()
            await hub.connect_district(ws1, frozenset({"school-a"}))
            assert hub.district_connection_count() == 1
            await hub.connect_district(ws2, frozenset({"school-a", "school-b"}))
            assert hub.district_connection_count() == 2

            await hub.disconnect_district(ws1)
            assert hub.district_connection_count() == 1

        asyncio.run(_run())

    def test_publish_reaches_both_per_tenant_and_district_connections(self) -> None:
        async def _run():
            hub = AlertHub()
            ws_tenant = _make_mock_websocket()
            ws_district = _make_mock_websocket()

            await hub.connect("school-a", ws_tenant)
            await hub.connect_district(ws_district, frozenset({"school-a"}))

            payload = {"event": "alert_triggered", "tenant_slug": "school-a"}
            await hub.publish("school-a", payload)

            encoded = json.dumps(payload, separators=(",", ":"), default=str)
            ws_tenant.send_text.assert_awaited_once_with(encoded)
            ws_district.send_text.assert_awaited_once_with(encoded)

        asyncio.run(_run())

    def test_district_stale_connection_pruned_on_send_error(self) -> None:
        async def _run():
            hub = AlertHub()
            ws_stale = _make_mock_websocket()
            ws_stale.send_text = AsyncMock(side_effect=RuntimeError("disconnected"))
            ws_good = _make_mock_websocket()

            await hub.connect_district(ws_stale, frozenset({"school-a"}))
            await hub.connect_district(ws_good, frozenset({"school-a"}))

            await hub.publish("school-a", {"event": "alert_triggered"})

            assert hub.district_connection_count() == 1
            ws_good.send_text.assert_awaited_once()

        asyncio.run(_run())

    def test_disconnect_district_cleans_all_slug_subscriptions(self) -> None:
        async def _run():
            hub = AlertHub()
            ws = _make_mock_websocket()
            await hub.connect_district(ws, frozenset({"school-a", "school-b", "school-c"}))
            await hub.disconnect_district(ws)

            for slug in ("school-a", "school-b", "school-c"):
                await hub.publish(slug, {"event": "test", "tenant_slug": slug})

            ws.send_text.assert_not_awaited()
            assert hub.district_connection_count() == 0

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Integration tests — /ws/district/alerts endpoint
# ---------------------------------------------------------------------------

def test_district_ws_rejects_missing_api_key(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="District Key School", slug="dist-key")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/district/alerts?home_tenant=dist-key&user_id=1"
        ) as ws:
            ws.receive_json()
    assert exc_info.value.code == 4401


def test_district_ws_rejects_wrong_api_key(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="District BadKey School", slug="dist-badkey")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/district/alerts?home_tenant=dist-badkey&user_id=1&api_key=wrong"
        ) as ws:
            ws.receive_json()
    assert exc_info.value.code == 4401


def test_district_ws_rejects_missing_home_tenant(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/district/alerts?user_id=1&api_key=test-api-key"
        ) as ws:
            ws.receive_json()
    assert exc_info.value.code == 4400


def test_district_ws_rejects_unknown_home_tenant(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/district/alerts?home_tenant=no-such-slug&user_id=1&api_key=test-api-key"
        ) as ws:
            ws.receive_json()
    assert exc_info.value.code == 4404


def test_district_ws_teacher_rejected_4403(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Teacher WS School", slug="teacher-ws")
    teacher_id = _create_user(client, "teacher-ws", name="Ms. Smith", role="teacher")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            f"/ws/district/alerts?home_tenant=teacher-ws&user_id={teacher_id}&api_key=test-api-key"
        ) as ws:
            ws.receive_json()
    assert exc_info.value.code == 4403


def test_district_ws_admin_rejected_4403(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Admin WS School", slug="admin-ws")
    admin_id = _create_user(client, "admin-ws", name="Admin", role="admin")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            f"/ws/district/alerts?home_tenant=admin-ws&user_id={admin_id}&api_key=test-api-key"
        ) as ws:
            ws.receive_json()
    assert exc_info.value.code == 4403


def test_district_ws_district_admin_receives_assigned_slug(client: TestClient, login_super_admin) -> None:
    """district_admin receives events for their home school and assigned schools."""
    login_super_admin()
    _create_school(client, name="Home School DA", slug="home-da")
    _create_school(client, name="Assigned School DA", slug="assigned-da")
    district_admin_id = _create_user(client, "home-da", name="DA User", role="district_admin")
    home_school = _get_school(client, "home-da")
    assigned_school = _get_school(client, "assigned-da")
    _assign_tenant(client, user_id=district_admin_id, home_tenant_id=home_school.id, tenant_ids=[assigned_school.id])

    received: list[dict] = []
    done = threading.Event()

    def _reader(ws_conn):
        try:
            received.append(ws_conn.receive_json())
        except Exception:
            pass
        finally:
            done.set()

    with client.websocket_connect(
        f"/ws/district/alerts?home_tenant=home-da&user_id={district_admin_id}&api_key=test-api-key"
    ) as ws:
        t = threading.Thread(target=_reader, args=(ws,), daemon=True)
        t.start()

        hub = client.app.state.alert_hub
        asyncio.run(hub.publish("assigned-da", {"event": "alert_triggered", "tenant_slug": "assigned-da"}))
        done.wait(timeout=2.0)

    assert received, "district_admin WS did not receive event for assigned tenant"
    assert received[0]["tenant_slug"] == "assigned-da"


def test_district_ws_district_admin_does_not_receive_unassigned_slug(client: TestClient, login_super_admin) -> None:
    """district_admin must not receive events for schools they are not assigned to."""
    login_super_admin()
    _create_school(client, name="Home DA NR", slug="home-da-nr")
    _create_school(client, name="Unassigned School", slug="unassigned-da-nr")
    district_admin_id = _create_user(client, "home-da-nr", name="DA No-Recv", role="district_admin")
    # Intentionally NOT assigning unassigned-da-nr to this user.

    received: list[dict] = []
    done = threading.Event()

    def _reader(ws_conn):
        try:
            received.append(ws_conn.receive_json())
        except Exception:
            pass
        finally:
            done.set()

    with client.websocket_connect(
        f"/ws/district/alerts?home_tenant=home-da-nr&user_id={district_admin_id}&api_key=test-api-key"
    ) as ws:
        t = threading.Thread(target=_reader, args=(ws,), daemon=True)
        t.start()

        hub = client.app.state.alert_hub
        asyncio.run(hub.publish("unassigned-da-nr", {"event": "alert_triggered", "tenant_slug": "unassigned-da-nr"}))
        done.wait(timeout=0.5)

    assert received == [], f"ISOLATION FAILURE: district_admin received event for unassigned tenant: {received}"


def test_district_ws_super_admin_receives_all_slugs(client: TestClient, login_super_admin) -> None:
    """super_admin district WS receives events for any active tenant."""
    login_super_admin()
    _create_school(client, name="SA School X", slug="sa-school-x")
    _create_school(client, name="SA School Y", slug="sa-school-y")
    _create_school(client, name="SA Home", slug="sa-home")
    super_admin_id = _create_user(client, "sa-home", name="Super", role="super_admin")

    received: list[dict] = []
    done = threading.Event()

    def _reader(ws_conn):
        try:
            received.append(ws_conn.receive_json())
        except Exception:
            pass
        finally:
            done.set()

    with client.websocket_connect(
        f"/ws/district/alerts?home_tenant=sa-home&user_id={super_admin_id}&api_key=test-api-key"
    ) as ws:
        t = threading.Thread(target=_reader, args=(ws,), daemon=True)
        t.start()

        hub = client.app.state.alert_hub
        asyncio.run(hub.publish("sa-school-x", {"event": "alert_triggered", "tenant_slug": "sa-school-x"}))
        done.wait(timeout=2.0)

    assert received, "super_admin WS did not receive event for any tenant"
    assert received[0]["tenant_slug"] == "sa-school-x"


def test_per_tenant_ws_still_works_alongside_district_ws(client: TestClient, login_super_admin) -> None:
    """Existing /ws/{slug}/alerts must still deliver independently of district connections."""
    login_super_admin()
    _create_school(client, name="Coexist School", slug="coexist")

    received_tenant: list[dict] = []
    done = threading.Event()

    def _reader(ws_conn):
        try:
            received_tenant.append(ws_conn.receive_json())
        except Exception:
            pass
        finally:
            done.set()

    with client.websocket_connect(
        "/ws/coexist/alerts",
        headers={"X-API-Key": "test-api-key"},
    ) as ws:
        t = threading.Thread(target=_reader, args=(ws,), daemon=True)
        t.start()

        hub = client.app.state.alert_hub
        asyncio.run(hub.publish("coexist", {"event": "alert_triggered", "tenant_slug": "coexist"}))
        done.wait(timeout=2.0)

    assert received_tenant, "Per-tenant WS stopped working after district endpoint added"
    assert received_tenant[0]["tenant_slug"] == "coexist"
