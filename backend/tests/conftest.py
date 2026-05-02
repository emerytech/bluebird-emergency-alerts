from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Ensure the backend root is on sys.path so `app.*` imports work when any
# subset of tests is run in isolation (not just the full suite).
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """
    Build an isolated app instance backed by per-test SQLite files.
    """

    monkeypatch.chdir(BACKEND_ROOT)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "tenant-default.db"))
    monkeypatch.setenv("PLATFORM_DB_PATH", str(tmp_path / "platform.db"))
    monkeypatch.setenv("BASE_DOMAIN", "bluebird.test")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("SUPERADMIN_USERNAME", "superadmin")
    monkeypatch.setenv("SUPERADMIN_PASSWORD", "super-password-123")
    monkeypatch.setenv("API_KEY", "test-api-key")
    monkeypatch.setenv("FCM_SERVICE_ACCOUNT_JSON", "")
    monkeypatch.setenv("SMS_ENABLED", "false")
    monkeypatch.setenv("APNS_TEAM_ID", "")
    monkeypatch.setenv("APNS_KEY_ID", "")
    monkeypatch.setenv("APNS_P8_PATH", "")
    monkeypatch.setenv("APNS_BUNDLE_ID", "")

    # Force a fresh app/main import so Settings() re-reads per-test env values.
    sys.modules.pop("app.main", None)
    app_main = importlib.import_module("app.main")
    app_main = importlib.reload(app_main)

    # Reset module-level in-memory rate-limiter stores so tests don't bleed into each other.
    routes_mod = sys.modules.get("app.api.routes")
    if routes_mod is not None:
        for store_name in ("_alarm_rate_store", "_code_rate_store", "_login_rate_store"):
            store = getattr(routes_mod, store_name, None)
            if isinstance(store, dict):
                store.clear()

    with TestClient(app_main.app) as test_client:
        yield test_client

    # Defensive cleanup in case imports mutate process cwd in future changes.
    os.chdir(BACKEND_ROOT)


@pytest.fixture()
def login_super_admin(client: TestClient):
    def _login() -> None:
        response = client.post(
            "/super-admin/login",
            data={"login_name": "superadmin", "password": "super-password-123"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers.get("location")
        assert location in {"/super-admin", "/super-admin/change-password"}
        if location == "/super-admin/change-password":
            response = client.post(
                "/super-admin/change-password",
                data={
                    "new_password": "super-password-123",
                    "confirm_password": "super-password-123",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers.get("location") == "/super-admin"

    return _login
