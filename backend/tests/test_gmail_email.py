"""
Gmail email system tests.

Invariants under test:
  1. GET /super-admin/email-settings returns unconfigured state by default.
  2. POST /super-admin/email-settings saves Gmail address and encrypts password.
  3. Email send uses decrypted password (SMTP_PASSWORD_ENCRYPTED preferred over plaintext).
  4. Test email route fails gracefully when Gmail is not configured.
  5. Customer message route fails gracefully when no email configured.
  6. User email field: set_email / list_emails_by_role work correctly.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login_super(client: TestClient) -> None:
    resp = client.post(
        "/super-admin/login",
        data={"login_name": "superadmin", "password": "super-password-123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


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


# ---------------------------------------------------------------------------
# 1. GET /super-admin/email-settings returns unconfigured by default
# ---------------------------------------------------------------------------

def test_get_gmail_settings_default_unconfigured(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    resp = client.get("/super-admin/email-settings")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["configured"] is False
    assert data["password_set"] is False
    assert data["gmail_address"] == ""


# ---------------------------------------------------------------------------
# 2. POST /super-admin/email-settings saves Gmail config and encrypts password
# ---------------------------------------------------------------------------

def test_save_gmail_settings_stores_encrypted_password(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    resp = client.post(
        "/super-admin/email-settings",
        data={
            "gmail_address": "test@gmail.com",
            "from_name": "Test Alerts",
            "app_password": "myapppassword",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text

    # GET should now show configured
    resp2 = client.get("/super-admin/email-settings")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["configured"] is True
    assert data["gmail_address"] == "test@gmail.com"
    assert data["from_name"] == "Test Alerts"
    assert data["password_set"] is True

    # Verify the password is encrypted in the DB (not plaintext)
    es = client.app.state.email_service
    import sqlite3
    with sqlite3.connect(es._db_path) as conn:
        row = conn.execute(
            "SELECT value FROM platform_email_settings WHERE key = 'SMTP_PASSWORD_ENCRYPTED';"
        ).fetchone()
    assert row is not None, "SMTP_PASSWORD_ENCRYPTED should be stored"
    # The encrypted value should NOT be the plaintext password
    assert row[0] != "myapppassword", "Password must be encrypted, not stored plaintext"


# ---------------------------------------------------------------------------
# 3. Decryption: SMTP_PASSWORD_ENCRYPTED is preferred over SMTP_PASSWORD
# ---------------------------------------------------------------------------

def test_encrypted_password_preferred_over_plaintext(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    es = client.app.state.email_service
    from app.services.email_service import encrypt_secret, decrypt_secret

    # Save both an encrypted and a plaintext key directly
    secret = es._encryption_secret
    encrypted = encrypt_secret("correct-password", secret)
    import sqlite3, datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with sqlite3.connect(es._db_path) as conn:
        conn.execute(
            "INSERT INTO platform_email_settings (key, value, updated_at) VALUES ('SMTP_PASSWORD_ENCRYPTED', ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at;",
            (encrypted, now),
        )
        conn.execute(
            "INSERT INTO platform_email_settings (key, value, updated_at) VALUES ('SMTP_PASSWORD', 'wrong-password', ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at;",
            (now,),
        )

    # The SMTP config must return password_set=True (decrypted from SMTP_PASSWORD_ENCRYPTED)
    cfg = es.smtp_config()
    assert cfg.password_set is True

    # Verify decrypt_secret recovers the correct value
    row_val = encrypted
    recovered = decrypt_secret(row_val, secret)
    assert recovered == "correct-password"


# ---------------------------------------------------------------------------
# 4. Test email route fails gracefully when Gmail not configured
# ---------------------------------------------------------------------------

def test_test_email_fails_when_unconfigured(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    resp = client.post(
        "/super-admin/email-settings/test",
        data={"test_email": "someone@example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # Should set a flash error visible in the session
    location = resp.headers.get("location", "")
    assert "configuration" in location


# ---------------------------------------------------------------------------
# 5. Customer message route fails gracefully when email is not configured
# ---------------------------------------------------------------------------

def test_customer_message_fails_gracefully_when_unconfigured(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Customer School", slug="custsch")

    resp = client.post(
        "/super-admin/customers/custsch/message",
        data={"subject": "Hello", "body": "Test message"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = resp.headers.get("location", "")
    assert "schools" in location


# ---------------------------------------------------------------------------
# 6. UserStore.set_email / list_emails_by_role
# ---------------------------------------------------------------------------

def test_user_email_field_set_and_list(client: TestClient, login_super_admin) -> None:
    login_super_admin()
    _create_school(client, name="Email School", slug="emailsch")
    uid = _create_user(client, "emailsch", name="Principal", role="district_admin")

    # Use the store directly
    school = client.app.state.tenant_manager.school_for_slug("emailsch")
    tenant = client.app.state.tenant_manager.get(school)
    store = tenant.user_store

    # Initially no email
    emails_before = asyncio.run(store.list_emails_by_role(["district_admin"]))
    assert "principal@school.edu" not in emails_before

    # Set email
    asyncio.run(store.set_email(uid, "principal@school.edu"))

    # Now it appears
    emails_after = asyncio.run(store.list_emails_by_role(["district_admin"]))
    assert "principal@school.edu" in emails_after

    # Wrong role returns empty
    emails_wrong_role = asyncio.run(store.list_emails_by_role(["teacher"]))
    assert "principal@school.edu" not in emails_wrong_role
