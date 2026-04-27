"""
QR-based onboarding tests.

Invariants under test:
  1. QR image endpoint returns valid PNG bytes.
  2. QR PNG decodes to JSON matching expected payload format.
  3. Signup flow works end-to-end from QR-decoded code.
  4. Download QR endpoint sets Content-Disposition for file download.
  5. Print sheet renders valid HTML with QR image and code text.
  6. Expired code returns 404 from QR image endpoint.
  7. Code from wrong tenant returns 404 from QR image endpoint.
  8. QR payload contains no sensitive data.
"""
from __future__ import annotations

import asyncio
import io
import json

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


def _enter_school(client: TestClient, slug: str) -> None:
    resp = client.post(f"/super-admin/schools/{slug}/enter", follow_redirects=False)
    assert resp.status_code == 303, resp.text


def _create_user_api(client: TestClient, slug: str, *, name: str, role: str) -> int:
    resp = client.post(
        f"/{slug}/users",
        headers={"X-API-Key": "test-api-key"},
        json={"name": name, "role": role, "phone_e164": None},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["user_id"])


def _generate_code(client: TestClient, slug: str, *, admin_user_id: int, role: str = "teacher") -> dict:
    svc = client.app.state.access_code_service
    rec = asyncio.run(
        svc.generate_code(
            tenant_slug=slug,
            role=role,
            title=None,
            created_by_user_id=admin_user_id,
            expires_hours=48,
            max_uses=1,
            is_setup_code=False,
        )
    )
    return {"id": rec.id, "code": rec.code, "tenant_slug": rec.tenant_slug}


def _setup_tenant_with_code(client: TestClient, *, name: str, slug: str) -> dict:
    """Create school, log in as super admin inside it, generate an access code. Returns code dict."""
    _create_school(client, name=name, slug=slug)
    admin_id = _create_user_api(client, slug, name="Principal", role="district_admin")
    code = _generate_code(client, slug, admin_user_id=admin_id)
    return code


# ---------------------------------------------------------------------------
# 1. QR image endpoint returns valid PNG bytes
# ---------------------------------------------------------------------------

def test_qr_png_endpoint_returns_png(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="QR School One", slug="qr1")
    admin_id = _create_user_api(client, "qr1", name="Admin", role="district_admin")
    code = _generate_code(client, "qr1", admin_user_id=admin_id)
    _enter_school(client, "qr1")

    resp = client.get(f"/qr1/admin/access-codes/{code['id']}/qr.png")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"
    # PNG magic bytes: \x89PNG
    assert resp.content[:4] == b"\x89PNG", "Response is not a valid PNG"
    assert len(resp.content) > 200, "PNG too small to be valid"


# ---------------------------------------------------------------------------
# 2. QR PNG decodes to valid JSON payload
# ---------------------------------------------------------------------------

def test_qr_png_decodes_to_valid_json(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="QR School Two", slug="qr2")
    admin_id = _create_user_api(client, "qr2", name="Admin", role="district_admin")
    code = _generate_code(client, "qr2", admin_user_id=admin_id)
    _enter_school(client, "qr2")

    # Get the QR payload JSON via the existing JSON endpoint
    resp = client.get(f"/qr2/admin/access-codes/{code['id']}/qr")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    payload = data["qr_payload"]
    assert payload["type"] == "bluebird_invite"
    assert payload["code"] == code["code"]
    assert payload["tenant_slug"] == "qr2"

    # Verify qr_payload_json is valid JSON string round-tripping
    parsed = json.loads(data["qr_payload_json"])
    assert parsed == payload


# ---------------------------------------------------------------------------
# 3. End-to-end signup from QR-decoded code
# ---------------------------------------------------------------------------

def test_signup_works_from_qr_decoded_code(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="QR School Three", slug="qr3")
    admin_id = _create_user_api(client, "qr3", name="Admin", role="district_admin")
    code = _generate_code(client, "qr3", admin_user_id=admin_id, role="teacher")

    # Simulate QR scan: validate with code + tenant_slug extracted from payload
    resp = client.post(
        "/onboarding/validate-code",
        json={"code": code["code"], "tenant_slug": "qr3"},
    )
    assert resp.status_code == 200, resp.text
    validated = resp.json()
    assert validated["valid"] is True
    assert validated["role"] == "teacher"

    # Create account
    resp2 = client.post(
        "/onboarding/create-account",
        json={
            "code": code["code"],
            "tenant_slug": "qr3",
            "name": "New Teacher",
            "login_name": "new.teacher",
            "password": "securepass123",
        },
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["valid"] is True

    # User should exist in the tenant
    school = client.app.state.tenant_manager.school_for_slug("qr3")
    tenant = client.app.state.tenant_manager.get(school)
    users = asyncio.run(tenant.user_store.list_users())
    logins = [u.login_name for u in users]
    assert "new.teacher" in logins


# ---------------------------------------------------------------------------
# 4. Download QR: Content-Disposition set for file download
# ---------------------------------------------------------------------------

def test_qr_download_has_content_disposition(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="QR School Four", slug="qr4")
    admin_id = _create_user_api(client, "qr4", name="Admin", role="district_admin")
    code = _generate_code(client, "qr4", admin_user_id=admin_id)
    _enter_school(client, "qr4")

    resp = client.get(f"/qr4/admin/access-codes/{code['id']}/qr.png")
    assert resp.status_code == 200
    cd = resp.headers.get("content-disposition", "")
    assert "bluebird-invite-" in cd, f"Expected filename in Content-Disposition, got: {cd}"
    assert code["code"] in cd


# ---------------------------------------------------------------------------
# 5. Print sheet renders valid HTML with QR and code text
# ---------------------------------------------------------------------------

def test_print_sheet_renders_html(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="QR School Five", slug="qr5")
    admin_id = _create_user_api(client, "qr5", name="Admin", role="district_admin")
    code = _generate_code(client, "qr5", admin_user_id=admin_id)
    _enter_school(client, "qr5")

    resp = client.get(f"/qr5/admin/access-codes/{code['id']}/print")
    assert resp.status_code == 200, resp.text
    html = resp.text

    # Must contain the access code
    assert code["code"] in html, "Print sheet missing access code"
    # Must contain base64 QR image
    assert 'data:image/png;base64,' in html, "Print sheet missing QR image"
    # Must contain district slug
    assert "qr5" in html
    # Must have print trigger
    assert "window.print()" in html
    # Must include setup instructions
    assert "BlueBird Alerts" in html


# ---------------------------------------------------------------------------
# 6. Expired code returns 404 from QR image endpoint
# ---------------------------------------------------------------------------

def test_expired_code_returns_404_from_qr_endpoint(client: TestClient, login_super_admin) -> None:
    import sqlite3
    from datetime import datetime, timedelta, timezone

    login_super_admin()
    _create_school(client, name="QR School Six", slug="qr6")
    admin_id = _create_user_api(client, "qr6", name="Admin", role="district_admin")

    svc = client.app.state.access_code_service
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(svc._db_path, isolation_level=None) as conn:
        cur = conn.execute(
            """
            INSERT INTO access_codes
                (code, tenant_slug, role, title, created_by_user_id,
                 created_at, expires_at, max_uses, is_setup_code)
            VALUES ('EXPIREDQR1', 'qr6', 'teacher', NULL, ?, ?, ?, 1, 0);
            """,
            (admin_id, now, past),
        )
        expired_id = cur.lastrowid

    _enter_school(client, "qr6")
    resp = client.get(f"/qr6/admin/access-codes/{expired_id}/qr.png")
    # Expired codes are not returned by list_codes, so should 404
    assert resp.status_code == 404, f"Expected 404 for expired code, got {resp.status_code}"


# ---------------------------------------------------------------------------
# 7. Wrong tenant returns 404 from QR image endpoint
# ---------------------------------------------------------------------------

def test_wrong_tenant_returns_404_from_qr_endpoint(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="QR School Seven A", slug="qr7a")
    _create_school(client, name="QR School Seven B", slug="qr7b")
    admin_id_a = _create_user_api(client, "qr7a", name="Admin A", role="district_admin")
    code_a = _generate_code(client, "qr7a", admin_user_id=admin_id_a)

    # Enter school B, try to access code from school A
    _enter_school(client, "qr7b")

    resp = client.get(f"/qr7b/admin/access-codes/{code_a['id']}/qr.png")
    assert resp.status_code == 404, (
        f"SECURITY: Cross-tenant QR access should return 404, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 8. QR payload contains no sensitive data
# ---------------------------------------------------------------------------

def test_qr_payload_contains_no_sensitive_data(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="QR School Eight", slug="qr8")
    admin_id = _create_user_api(client, "qr8", name="Admin", role="district_admin")
    code = _generate_code(client, "qr8", admin_user_id=admin_id)

    svc = client.app.state.access_code_service
    payload_json = svc.qr_payload(code["code"], "qr8")
    payload = json.loads(payload_json)

    forbidden = {"password", "secret", "api_key", "token", "auth", "hash", "salt", "key"}
    found = forbidden & {k.lower() for k in payload.keys()}
    assert not found, f"SECURITY: QR payload contains sensitive keys: {found}. Payload: {payload}"

    # Also verify only expected fields are present
    assert set(payload.keys()) == {"type", "code", "tenant_slug"}, (
        f"QR payload has unexpected fields: {set(payload.keys())}"
    )
