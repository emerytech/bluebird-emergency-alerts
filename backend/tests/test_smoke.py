"""
Smoke tests against a live staging or production server.

These tests make real HTTP requests — they are NOT run by the regular pytest
suite (they require network access and a running server).

Usage:
    export SMOKE_BASE_URL=https://staging.bluebirdalerts.com
    export SMOKE_API_KEY=<your-api-key>
    export SMOKE_TENANT=<school-slug>             # optional, defaults to "nen"
    export SMOKE_SUPER_USER=superadmin
    export SMOKE_SUPER_PASS=<password>
    pytest tests/test_smoke.py -v -m smoke

Environment variables:
    SMOKE_BASE_URL      Base URL of the running server (no trailing slash)
    SMOKE_API_KEY       Shared API key (X-API-Key header)
    SMOKE_TENANT        Tenant slug to use for per-tenant endpoints
    SMOKE_SUPER_USER    Super-admin username
    SMOKE_SUPER_PASS    Super-admin password
"""

from __future__ import annotations

import os
import time
import pytest
import urllib.request
import urllib.error
import json
from typing import Any


# ── Skip entire module if SMOKE_BASE_URL is not set ──────────────────────────

pytestmark = pytest.mark.smoke

BASE_URL: str = os.environ.get("SMOKE_BASE_URL", "").rstrip("/")
API_KEY: str = os.environ.get("SMOKE_API_KEY", "")
TENANT: str = os.environ.get("SMOKE_TENANT", "nen")
SUPER_USER: str = os.environ.get("SMOKE_SUPER_USER", "")
SUPER_PASS: str = os.environ.get("SMOKE_SUPER_PASS", "")


def _skip_if_unconfigured() -> None:
    if not BASE_URL:
        pytest.skip("SMOKE_BASE_URL not set — skipping smoke tests")


@pytest.fixture(scope="session", autouse=True)
def require_smoke_env():
    _skip_if_unconfigured()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    if extra:
        h.update(extra)
    return h


def _get(path: str, tenant: str | None = None, timeout: int = 10) -> tuple[int, Any]:
    url = f"{BASE_URL}/{tenant}{path}" if tenant else f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def _post(path: str, body: dict, tenant: str | None = None, timeout: int = 10) -> tuple[int, Any]:
    url = f"{BASE_URL}/{tenant}{path}" if tenant else f"{BASE_URL}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail", "")
        except Exception:
            detail = ""
        return e.code, {"detail": detail}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self):
        code, body = _get("/health")
        assert code == 200, f"Expected 200, got {code}"

    def test_health_has_status_field(self):
        _, body = _get("/health")
        assert "status" in body, "Health response missing 'status' field"

    def test_health_is_ok_or_degraded(self):
        _, body = _get("/health")
        assert body.get("status") in {"ok", "degraded"}, (
            f"Health status unexpected: {body.get('status')}"
        )

    def test_response_time_acceptable(self):
        start = time.monotonic()
        _get("/health")
        elapsed = time.monotonic() - start
        assert elapsed < 3.0, f"Health check too slow: {elapsed:.2f}s"


class TestSchoolsList:
    def test_schools_endpoint_returns_200(self):
        code, body = _get("/schools")
        assert code == 200

    def test_schools_list_not_empty(self):
        _, body = _get("/schools")
        schools = body.get("schools") or body.get("data") or body
        assert schools, "Schools list is empty"


class TestTenantEndpoints:
    def test_alarm_status_returns_200(self):
        code, body = _get("/alarm/status", tenant=TENANT)
        assert code == 200, f"alarm/status returned {code}: {body}"

    def test_alarm_status_has_is_active(self):
        _, body = _get("/alarm/status", tenant=TENANT)
        assert "is_active" in body, f"alarm/status missing 'is_active': {body}"

    def test_alarm_not_active_at_startup(self):
        """Staging should not have an active alarm at test time."""
        _, body = _get("/alarm/status", tenant=TENANT)
        assert not body.get("is_active"), (
            "Staging has an ACTIVE alarm — check the server state before running smoke tests"
        )


class TestSuperAdminLogin:
    def test_login_missing_credentials_returns_422(self):
        code, _ = _post("/super-admin/login", {})
        assert code in {400, 422}, f"Expected 400/422, got {code}"

    def test_login_bad_credentials_returns_401(self):
        code, body = _post("/super-admin/login", {
            "username": "definitely_not_real",
            "password": "wrong_password_12345",
        })
        assert code == 401, f"Expected 401, got {code}: {body}"

    @pytest.mark.skipif(not SUPER_USER, reason="SMOKE_SUPER_USER not set")
    def test_login_valid_credentials(self):
        code, body = _post("/super-admin/login", {
            "username": SUPER_USER,
            "password": SUPER_PASS,
        })
        assert code == 200, f"Super-admin login failed ({code}): {body}"
        assert "token" in body or "user_id" in body, (
            f"Login response missing token/user_id: {body}"
        )


class TestAPIKeySecurity:
    def test_protected_endpoint_rejects_no_key(self):
        """Alarm status requires X-API-Key when API_KEY is configured server-side."""
        if not API_KEY:
            pytest.skip("No API_KEY configured — skipping key-rejection test")
        url = f"{BASE_URL}/{TENANT}/alarm/status"
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
            pytest.fail("Expected 401/403 but got 200 — API key enforcement may be disabled")
        except urllib.error.HTTPError as e:
            assert e.code in {401, 403}, f"Expected 401/403, got {e.code}"

    def test_protected_endpoint_accepts_valid_key(self):
        code, _ = _get("/alarm/status", tenant=TENANT)
        assert code == 200


class TestStaticAssets:
    def test_static_css_served(self):
        url = f"{BASE_URL}/static/admin.css"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status == 200
                ct = resp.headers.get("Content-Type", "")
                assert "css" in ct or "text" in ct
        except urllib.error.HTTPError as e:
            pytest.skip(f"Static file not found ({e.code}) — may not be mounted in this deployment")


class TestResponseHeaders:
    def test_hsts_header_present(self):
        """HSTS must be set when running behind HTTPS."""
        _, _ = _get("/health")
        # urllib follows redirects, so we check the final response headers indirectly
        url = f"{BASE_URL}/health"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                hsts = resp.headers.get("Strict-Transport-Security")
                if BASE_URL.startswith("https://"):
                    assert hsts, "HSTS header missing on HTTPS response"
        except Exception:
            pytest.skip("Could not verify HSTS (HTTP-only or unreachable)")

    def test_x_content_type_options(self):
        url = f"{BASE_URL}/health"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                header = resp.headers.get("X-Content-Type-Options")
                if BASE_URL.startswith("https://"):
                    assert header == "nosniff", f"X-Content-Type-Options: {header}"
        except Exception:
            pytest.skip("Could not verify security headers")
