"""
Help-request cancel endpoint tests.

Invariants:
  1. Requester can cancel their own active request (immediate, no second confirmation).
  2. cancel_reason_text is required — empty string rejected.
  3. cancel_reason_category is required — empty string rejected.
  4. A different user cannot cancel someone else's request (403).
  5. Cannot cancel an already-closed (cancelled/resolved) request (409).
  6. Audit log entry created with correct fields.
  7. cancel-confirm legacy endpoint still works (no regression).
  8. cancel_reason_text/category appear in the response.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

API_KEY = {"X-API-Key": "test-api-key"}


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
        headers=API_KEY,
        json={"name": name, "role": role, "phone_e164": None},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["user_id"])


def _create_help_request(client: TestClient, slug: str, *, user_id: int) -> int:
    resp = client.post(
        f"/{slug}/request-help/create",
        headers=API_KEY,
        json={"user_id": user_id, "type": "medical", "assigned_team_ids": []},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _cancel(client: TestClient, slug: str, *, team_assist_id: int, user_id: int,
            reason_text: str = "No longer needed", reason_category: str = "false_alarm"):
    return client.post(
        f"/{slug}/request-help/{team_assist_id}/cancel",
        headers=API_KEY,
        json={
            "user_id": user_id,
            "cancel_reason_text": reason_text,
            "cancel_reason_category": reason_category,
        },
    )


def _setup(client: TestClient, login_super_admin, slug: str = "hc1"):
    login_super_admin()
    _create_school(client, name="Help Cancel School", slug=slug)
    requester_id = _create_user(client, slug, name="Requester", role="teacher")
    other_id = _create_user(client, slug, name="Other User", role="teacher")
    admin_id = _create_user(client, slug, name="Admin", role="district_admin")
    return requester_id, other_id, admin_id


# ---------------------------------------------------------------------------
# 1. Requester cancels their own request — succeeds immediately
# ---------------------------------------------------------------------------

def test_requester_can_cancel_own_request(client: TestClient, login_super_admin) -> None:
    requester_id, _, _ = _setup(client, login_super_admin, "hc1")
    ta_id = _create_help_request(client, "hc1", user_id=requester_id)

    resp = _cancel(client, "hc1", team_assist_id=ta_id, user_id=requester_id)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "cancelled"
    assert data["cancelled_by_user_id"] == requester_id
    assert data["cancelled_at"] is not None
    assert data["cancel_reason_text"] == "No longer needed"
    assert data["cancel_reason_category"] == "false_alarm"


# ---------------------------------------------------------------------------
# 2. cancel_reason_text required
# ---------------------------------------------------------------------------

def test_empty_reason_text_rejected(client: TestClient, login_super_admin) -> None:
    requester_id, _, _ = _setup(client, login_super_admin, "hc2")
    ta_id = _create_help_request(client, "hc2", user_id=requester_id)

    resp = _cancel(client, "hc2", team_assist_id=ta_id, user_id=requester_id,
                   reason_text="  ", reason_category="false_alarm")
    # Pydantic min_length=1 rejects blank strings
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 3. cancel_reason_category required
# ---------------------------------------------------------------------------

def test_empty_reason_category_rejected(client: TestClient, login_super_admin) -> None:
    requester_id, _, _ = _setup(client, login_super_admin, "hc3")
    ta_id = _create_help_request(client, "hc3", user_id=requester_id)

    resp = _cancel(client, "hc3", team_assist_id=ta_id, user_id=requester_id,
                   reason_text="Valid reason", reason_category="")
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 4. Different user cannot cancel someone else's request
# ---------------------------------------------------------------------------

def test_other_user_cannot_cancel(client: TestClient, login_super_admin) -> None:
    requester_id, other_id, _ = _setup(client, login_super_admin, "hc4")
    ta_id = _create_help_request(client, "hc4", user_id=requester_id)

    resp = _cancel(client, "hc4", team_assist_id=ta_id, user_id=other_id)
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 5. Cannot cancel an already-cancelled request
# ---------------------------------------------------------------------------

def test_cannot_cancel_already_cancelled(client: TestClient, login_super_admin) -> None:
    requester_id, _, _ = _setup(client, login_super_admin, "hc5")
    ta_id = _create_help_request(client, "hc5", user_id=requester_id)

    resp = _cancel(client, "hc5", team_assist_id=ta_id, user_id=requester_id)
    assert resp.status_code == 200

    resp2 = _cancel(client, "hc5", team_assist_id=ta_id, user_id=requester_id)
    assert resp2.status_code == 409, resp2.text


# ---------------------------------------------------------------------------
# 6. Audit log entry created
# ---------------------------------------------------------------------------

def test_audit_log_created_on_cancel(client: TestClient, login_super_admin) -> None:
    requester_id, _, _ = _setup(client, login_super_admin, "hc6")
    ta_id = _create_help_request(client, "hc6", user_id=requester_id)

    _cancel(client, "hc6", team_assist_id=ta_id, user_id=requester_id,
            reason_text="Test audit", reason_category="test")

    school = client.app.state.tenant_manager.school_for_slug("hc6")
    tenant = client.app.state.tenant_manager.get(school)
    entries = asyncio.run(tenant.audit_log_service.list_recent(limit=50))
    cancel_entries = [e for e in entries if e.event_type == "help_request_cancelled"]
    assert len(cancel_entries) == 1
    meta = cancel_entries[0].metadata or {}
    assert meta.get("request_id") == ta_id
    assert meta.get("cancelled_by") == requester_id
    assert meta.get("cancel_reason_text") == "Test audit"
    assert meta.get("cancel_reason_category") == "test"


# ---------------------------------------------------------------------------
# 7. Legacy cancel-confirm still works (no regression)
# ---------------------------------------------------------------------------

def test_legacy_cancel_confirm_still_works(client: TestClient, login_super_admin) -> None:
    requester_id, _, _ = _setup(client, login_super_admin, "hc7")
    ta_id = _create_help_request(client, "hc7", user_id=requester_id)

    resp = client.post(
        f"/hc7/request-help/{ta_id}/cancel-confirm",
        headers=API_KEY,
        json={"user_id": requester_id},
    )
    assert resp.status_code == 200, resp.text
    # Legacy flow sets cancel_pending until admin also confirms
    assert resp.json()["status"] in {"cancel_pending", "cancelled"}


# ---------------------------------------------------------------------------
# 8. No dual-confirmation required — single call cancels immediately
# ---------------------------------------------------------------------------

def test_single_call_cancels_immediately(client: TestClient, login_super_admin) -> None:
    requester_id, _, _ = _setup(client, login_super_admin, "hc8")
    ta_id = _create_help_request(client, "hc8", user_id=requester_id)

    resp = _cancel(client, "hc8", team_assist_id=ta_id, user_id=requester_id)
    assert resp.status_code == 200
    # Must be "cancelled" on the first call — no intermediate "cancel_pending"
    assert resp.json()["status"] == "cancelled"
