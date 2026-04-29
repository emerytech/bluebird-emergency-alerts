"""
Quiet period scheduling and unified model tests.

Invariants under test:
  1.  Immediate request: status is pending then approved after approval.
  2.  Immediate approved request: expires_at = approved_at + 24h (no scheduled_end_at).
  3.  Scheduled 1-hour request: expires_at ≈ scheduled_end_at, NOT approved_at + 24h.
  4.  Scheduled 4-hour request: expires_at ≈ scheduled_end_at, NOT approved_at + 24h.
  5.  scheduled_end_at overrides 24h default even when start is in the past (immediate branch).
  6.  Building admin does NOT see own request in admin review queue.
  7.  Self-approval returns 403.
  8.  countdown_target_at = scheduled_start_at when status = scheduled.
  9.  countdown_target_at = expires_at when status = approved/active.
  10. denied_at is populated on denial; approved_at is NOT set.
  11. cancelled_at is populated on cancellation.
  12. Approval of request with future start → status = scheduled, not approved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_future(minutes: int = 60) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _iso_past(minutes: int = 5) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


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


def _request_quiet(
    client: TestClient,
    slug: str,
    *,
    user_id: int,
    scheduled_start_at: str | None = None,
    scheduled_end_at: str | None = None,
) -> dict:
    body: dict = {"user_id": user_id, "reason": "test"}
    if scheduled_start_at:
        body["scheduled_start_at"] = scheduled_start_at
    if scheduled_end_at:
        body["scheduled_end_at"] = scheduled_end_at
    resp = client.post(
        f"/{slug}/quiet-periods/request",
        headers={"X-API-Key": "test-api-key"},
        json=body,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


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


def _admin_queue(client: TestClient, slug: str, *, admin_id: int) -> list[dict]:
    resp = client.get(
        f"/{slug}/quiet-periods/admin/requests",
        headers={"X-API-Key": "test-api-key"},
        params={"admin_user_id": admin_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["requests"]


# ---------------------------------------------------------------------------
# 1. Immediate request lifecycle
# ---------------------------------------------------------------------------

def test_immediate_request_pending_then_approved(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Cedar School", slug="cedar")
    requester = _create_user(client, "cedar", name="Alice", role="teacher")
    admin = _create_user(client, "cedar", name="Bob", role="admin")

    req = _request_quiet(client, "cedar", user_id=requester)
    assert req["status"] == "pending"
    request_id = req["request_id"]

    result = _approve(client, "cedar", request_id=request_id, admin_id=admin)
    assert result["status"] == "approved"
    assert result["approved_at"] is not None
    assert result["expires_at"] is not None


# ---------------------------------------------------------------------------
# 2. Immediate approval: expires_at = approved_at + 24h (no scheduled_end_at)
# ---------------------------------------------------------------------------

def test_immediate_approval_default_24h(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Maple School", slug="maple")
    requester = _create_user(client, "maple", name="Carol", role="teacher")
    admin = _create_user(client, "maple", name="Dave", role="admin")

    req = _request_quiet(client, "maple", user_id=requester)
    result = _approve(client, "maple", request_id=req["request_id"], admin_id=admin)

    approved_at = datetime.fromisoformat(result["approved_at"])
    expires_at = datetime.fromisoformat(result["expires_at"])
    delta = expires_at - approved_at
    assert timedelta(hours=23, minutes=59) <= delta <= timedelta(hours=24, minutes=1)


# ---------------------------------------------------------------------------
# 3. Scheduled 1-hour request keeps 1-hour duration
# ---------------------------------------------------------------------------

def test_scheduled_1hour_keeps_duration(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Oak School", slug="oak")
    requester = _create_user(client, "oak", name="Eve", role="teacher")
    admin = _create_user(client, "oak", name="Frank", role="admin")

    start = _iso_future(minutes=60)
    end = _iso_future(minutes=120)  # 1 hour window

    req = _request_quiet(client, "oak", user_id=requester, scheduled_start_at=start, scheduled_end_at=end)
    assert req["status"] == "pending"

    result = _approve(client, "oak", request_id=req["request_id"], admin_id=admin)
    assert result["status"] == "scheduled"
    assert result["expires_at"] is not None

    # expires_at should match scheduled_end_at, not approved_at + 24h
    expires_at = datetime.fromisoformat(result["expires_at"])
    end_dt = datetime.fromisoformat(end)
    assert abs((expires_at - end_dt).total_seconds()) < 5


# ---------------------------------------------------------------------------
# 4. Scheduled 4-hour request keeps 4-hour duration
# ---------------------------------------------------------------------------

def test_scheduled_4hour_keeps_duration(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Pine School", slug="pine")
    requester = _create_user(client, "pine", name="Grace", role="teacher")
    admin = _create_user(client, "pine", name="Heidi", role="admin")

    start = _iso_future(minutes=60)
    end = _iso_future(minutes=300)  # 4 hours from start

    req = _request_quiet(client, "pine", user_id=requester, scheduled_start_at=start, scheduled_end_at=end)
    result = _approve(client, "pine", request_id=req["request_id"], admin_id=admin)
    assert result["status"] == "scheduled"

    expires_at = datetime.fromisoformat(result["expires_at"])
    end_dt = datetime.fromisoformat(end)
    assert abs((expires_at - end_dt).total_seconds()) < 5


# ---------------------------------------------------------------------------
# 5. scheduled_end_at overrides 24h when start is in the past (immediate branch)
# ---------------------------------------------------------------------------

def test_immediate_approval_respects_scheduled_end_at(client: TestClient, login_super_admin) -> None:
    """
    A request submitted with scheduled_start_at already in the past is approved
    immediately (status=approved), but expires_at must still honor scheduled_end_at
    rather than defaulting to approved_at + 24h.
    """
    login_super_admin()
    _create_school(client, name="Birch School", slug="birch")
    # Can't send a past start_at via the create endpoint (validator blocks it).
    # Test the store directly instead.
    from app.services.quiet_period_store import QuietPeriodStore
    import tempfile, os

    with tempfile.TemporaryDirectory() as tmp:
        store = QuietPeriodStore(os.path.join(tmp, "qp.db"))
        import asyncio

        # Insert record manually with a past start time and a 2-hour window.
        start = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

        record = asyncio.get_event_loop().run_until_complete(
            store.request_quiet_period(user_id=1, reason="test")
        )
        # Patch scheduled fields directly via SQL.
        import sqlite3
        with sqlite3.connect(os.path.join(tmp, "qp.db"), isolation_level=None) as conn:
            conn.execute(
                "UPDATE quiet_period_requests SET scheduled_start_at=?, scheduled_end_at=? WHERE id=?",
                (start, end, record.id),
            )

        result = asyncio.get_event_loop().run_until_complete(
            store.approve_request(request_id=record.id, admin_user_id=99)
        )
        assert result is not None
        assert result.status == "approved"  # start was in the past → immediate
        assert result.expires_at is not None
        expires_at = datetime.fromisoformat(result.expires_at)
        end_dt = datetime.fromisoformat(end)
        assert abs((expires_at - end_dt).total_seconds()) < 5, (
            f"expires_at {expires_at} should match scheduled_end_at {end_dt}, not approved_at + 24h"
        )


# ---------------------------------------------------------------------------
# 6. Building admin does NOT see own request in admin review queue
# ---------------------------------------------------------------------------

def test_admin_does_not_see_own_request_in_queue(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Elm School", slug="elm")
    admin = _create_user(client, "elm", name="Ivan", role="admin")
    other = _create_user(client, "elm", name="Judy", role="teacher")

    _request_quiet(client, "elm", user_id=admin)
    _request_quiet(client, "elm", user_id=other)

    queue = _admin_queue(client, "elm", admin_id=admin)
    user_ids_in_queue = {item["user_id"] for item in queue}
    assert admin not in user_ids_in_queue, "Admin must not see own request in review queue"
    assert other in user_ids_in_queue


# ---------------------------------------------------------------------------
# 7. Self-approval returns 403
# ---------------------------------------------------------------------------

def test_self_approval_blocked(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Walnut School", slug="walnut")
    admin = _create_user(client, "walnut", name="Kai", role="admin")

    req = _request_quiet(client, "walnut", user_id=admin)
    resp = client.post(
        f"/walnut/quiet-periods/{req['request_id']}/approve",
        headers={"X-API-Key": "test-api-key"},
        json={"admin_user_id": admin},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 8. countdown_target_at = scheduled_start_at when status = scheduled
# ---------------------------------------------------------------------------

def test_countdown_target_for_scheduled(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Spruce School", slug="spruce")
    requester = _create_user(client, "spruce", name="Lena", role="teacher")
    admin = _create_user(client, "spruce", name="Max", role="admin")

    start = _iso_future(minutes=90)
    end = _iso_future(minutes=150)

    req = _request_quiet(client, "spruce", user_id=requester, scheduled_start_at=start, scheduled_end_at=end)
    result = _approve(client, "spruce", request_id=req["request_id"], admin_id=admin)

    assert result["status"] == "scheduled"
    assert result["countdown_target_at"] is not None
    assert result["countdown_mode"] == "starts_in"
    # countdown_target_at should equal scheduled_start_at
    target = datetime.fromisoformat(result["countdown_target_at"])
    start_dt = datetime.fromisoformat(start)
    assert abs((target - start_dt).total_seconds()) < 5


# ---------------------------------------------------------------------------
# 9. countdown_target_at = expires_at when status = approved
# ---------------------------------------------------------------------------

def test_countdown_target_for_active(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Cedar2 School", slug="cedar2")
    requester = _create_user(client, "cedar2", name="Nina", role="teacher")
    admin = _create_user(client, "cedar2", name="Oscar", role="admin")

    req = _request_quiet(client, "cedar2", user_id=requester)
    result = _approve(client, "cedar2", request_id=req["request_id"], admin_id=admin)

    assert result["status"] == "approved"
    assert result["countdown_mode"] == "ends_in"
    assert result["countdown_target_at"] == result["expires_at"]


# ---------------------------------------------------------------------------
# 10. denied_at is populated on denial; approved_at is NOT set
# ---------------------------------------------------------------------------

def test_denial_sets_denied_at(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Fir School", slug="fir")
    requester = _create_user(client, "fir", name="Pat", role="teacher")
    admin = _create_user(client, "fir", name="Quinn", role="admin")

    req = _request_quiet(client, "fir", user_id=requester)
    result = _deny(client, "fir", request_id=req["request_id"], admin_id=admin)

    assert result["status"] == "denied"
    assert result["denied_at"] is not None
    # approved_at should remain None for a denied request
    assert result["approved_at"] is None


# ---------------------------------------------------------------------------
# 11 + 12. cancelled_at on cancellation AND future-start → scheduled
#          Uses the store layer directly to avoid the 10-test superadmin limit.
# ---------------------------------------------------------------------------

def test_cancel_and_future_scheduled() -> None:
    """Tests 11+12 via the store layer (no HTTP) to avoid superadmin-reload limits."""
    from app.services.quiet_period_store import QuietPeriodStore
    import asyncio
    import os
    import tempfile

    loop = asyncio.get_event_loop()

    with tempfile.TemporaryDirectory() as tmp:
        store = QuietPeriodStore(os.path.join(tmp, "qp.db"))

        # 11: cancelled_at set on cancellation
        rec = loop.run_until_complete(store.request_quiet_period(user_id=1, reason="test"))
        cancelled = loop.run_until_complete(store.cancel_for_user(request_id=rec.id, user_id=1))
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        assert cancelled.cancelled_at is not None

        # 12: future-start approval → status = scheduled
        start = _iso_future(minutes=120)
        end = _iso_future(minutes=180)

        rec2 = loop.run_until_complete(store.request_quiet_period(user_id=2, reason="sched"))
        import sqlite3
        with sqlite3.connect(os.path.join(tmp, "qp.db"), isolation_level=None) as conn:
            conn.execute(
                "UPDATE quiet_period_requests SET scheduled_start_at=?, scheduled_end_at=? WHERE id=?",
                (start, end, rec2.id),
            )
        result2 = loop.run_until_complete(store.approve_request(request_id=rec2.id, admin_user_id=99))
        assert result2 is not None
        assert result2.status == "scheduled"
        assert result2.scheduled_start_at is not None
        assert result2.scheduled_end_at is not None
