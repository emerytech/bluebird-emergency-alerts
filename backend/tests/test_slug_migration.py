"""
Tests for the "default" → "nen" tenant slug migration.

Verifies:
- New tenant comes up with slug "nen"
- API calls using "nen" work
- API calls still using "default" route correctly via alias
- No data loss — existing endpoints return expected results
- Alias is persisted and listable
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _create_user(client: TestClient, slug: str, *, name: str, role: str) -> int:
    r = client.post(
        f"/{slug}/users",
        headers={"X-API-Key": "test-api-key"},
        json={"name": name, "role": role, "phone_e164": None},
    )
    assert r.status_code == 200, r.text
    return int(r.json()["user_id"])


def _alarm_status(client: TestClient, *, tenant: str) -> dict:
    r = client.get(
        "/alarm/status",
        headers={"X-API-Key": "test-api-key", "X-Tenant-ID": tenant},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _trigger_alarm(client: TestClient, *, tenant: str, user_id: int) -> dict:
    r = client.post(
        f"/{tenant}/alarm/activate",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": user_id, "message": "Test alarm"},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── Tests: canonical "nen" slug ───────────────────────────────────────────────


def test_nen_tenant_is_created_on_startup(client: TestClient, login_super_admin) -> None:
    """The default school must come up with slug 'nen', not 'default'."""
    login_super_admin()
    r = client.get("/schools")
    assert r.status_code == 200, r.text
    slugs = [s["slug"] for s in r.json()["schools"]]
    assert "nen" in slugs, f"Expected 'nen' in schools, got: {slugs}"


def test_nen_slug_routes_correctly(client: TestClient) -> None:
    """Direct API calls with /nen/ prefix must resolve the tenant."""
    user_id = _create_user(client, "nen", name="Alice Teacher", role="teacher")
    assert user_id > 0


def test_nen_alarm_status_via_path(client: TestClient) -> None:
    r = client.get("/nen/alarm/status", headers={"X-API-Key": "test-api-key"})
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False


def test_nen_alarm_status_via_header(client: TestClient) -> None:
    status = _alarm_status(client, tenant="nen")
    assert status["is_active"] is False


# ── Tests: backward-compat "default" alias ────────────────────────────────────


def test_default_alias_resolves_to_nen(client: TestClient) -> None:
    """`X-Tenant-ID: default` must resolve to the nen tenant without error."""
    status = _alarm_status(client, tenant="default")
    assert status["is_active"] is False


def test_default_path_alias_resolves(client: TestClient) -> None:
    """/default/alarm/status must work via alias routing."""
    r = client.get("/default/alarm/status", headers={"X-API-Key": "test-api-key"})
    assert r.status_code == 200, r.text


def test_default_and_nen_see_same_tenant(client: TestClient) -> None:
    """Data written via 'nen' must be visible via 'default' header — same tenant."""
    user_id = _create_user(client, "nen", name="Shared User", role="admin")

    # List users via "nen"
    r_nen = client.get("/nen/users", headers={"X-API-Key": "test-api-key"})
    assert r_nen.status_code == 200
    nen_ids = [u["user_id"] for u in r_nen.json()["users"]]

    # List users via "default" header
    r_default = client.get(
        "/users",
        headers={"X-API-Key": "test-api-key", "X-Tenant-ID": "default"},
    )
    assert r_default.status_code == 200
    default_ids = [u["user_id"] for u in r_default.json()["users"]]

    assert user_id in nen_ids
    assert set(nen_ids) == set(default_ids), "Both slugs must return the same user list"


def test_default_slug_not_in_school_list(client: TestClient, login_super_admin) -> None:
    """The schools registry should show 'nen', not 'default', as the canonical slug."""
    login_super_admin()
    r = client.get("/schools")
    assert r.status_code == 200
    slugs = [s["slug"] for s in r.json()["schools"]]
    assert "default" not in slugs, f"'default' should not appear in schools list, got: {slugs}"
    assert "nen" in slugs


# ── Tests: no 404 regressions ────────────────────────────────────────────────


def test_unknown_slug_still_returns_400(client: TestClient) -> None:
    """A completely unknown slug must still return 400, not accidentally alias."""
    r = client.get(
        "/alarm/status",
        headers={"X-API-Key": "test-api-key", "X-Tenant-ID": "nonexistent-school"},
    )
    assert r.status_code in (400, 404), f"Expected 4xx, got {r.status_code}"


def test_alarm_roundtrip_under_nen(client: TestClient) -> None:
    """Activate and read alarm using the new 'nen' slug."""
    admin_id = _create_user(client, "nen", name="NEN Admin", role="admin")

    activate = _trigger_alarm(client, tenant="nen", user_id=admin_id)
    assert activate.get("is_active") is True

    status = _alarm_status(client, tenant="nen")
    assert status["is_active"] is True

    # Also visible via default alias
    legacy_status = _alarm_status(client, tenant="default")
    assert legacy_status["is_active"] is True


def test_alias_persisted_in_registry(client: TestClient) -> None:
    """The 'default' → 'nen' alias must be stored in the DB (verifiable via registry)."""
    import asyncio
    import importlib
    import os

    platform_db = os.environ.get("PLATFORM_DB_PATH", "")
    if not platform_db:
        pytest.skip("PLATFORM_DB_PATH not set in test environment")

    registry_mod = importlib.import_module("app.services.school_registry")
    SchoolRegistry = registry_mod.SchoolRegistry

    reg = SchoolRegistry(platform_db)
    loop = asyncio.new_event_loop()
    try:
        aliases = loop.run_until_complete(reg.list_aliases())
    finally:
        loop.close()

    alias_map = {a.old_slug: a.new_slug for a in aliases}
    assert "default" in alias_map, f"Expected 'default' alias, got: {alias_map}"
    assert alias_map["default"] == "nen"
