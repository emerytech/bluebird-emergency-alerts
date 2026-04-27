from __future__ import annotations

import base64
import hashlib
import smtplib
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from threading import Lock
from typing import Dict, List, Optional, Sequence

import anyio
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings


# ── Password encryption helpers ────────────────────────────────────────────────

def _fernet_from_secret(secret: str) -> Fernet:
    """Derive a stable Fernet key from the platform secret. Never changes per installation."""
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str, secret: str) -> str:
    """Encrypt a credential string. Returns a base64 token safe for DB storage."""
    return _fernet_from_secret(secret).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str, secret: str) -> str:
    """Decrypt a previously encrypted credential. Returns empty string on failure."""
    if not token:
        return ""
    try:
        return _fernet_from_secret(secret).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, Exception):
        return ""


# ── Message templates ──────────────────────────────────────────────────────────

TEMPLATES: Dict[str, Dict[str, str]] = {
    "outage_alert": {
        "subject": "BlueBird Alerts — Service Disruption Notice",
        "body": (
            "This is an automated notification from the BlueBird Alerts platform.\n\n"
            "We are currently experiencing a service disruption. "
            "Emergency alert delivery may be affected.\n\n"
            "Our team has been notified and is actively working to restore service.\n\n"
            "A recovery notification will be sent when full service is restored.\n\n"
            "— BlueBird Alerts Platform"
        ),
    },
    "maintenance_notice": {
        "subject": "BlueBird Alerts — Scheduled Maintenance",
        "body": (
            "This is a scheduled maintenance notice from BlueBird Alerts.\n\n"
            "Planned maintenance is scheduled. Service may be briefly unavailable "
            "during the maintenance window.\n\n"
            "Emergency alert delivery will be restored promptly after maintenance completes.\n\n"
            "— BlueBird Alerts Platform"
        ),
    },
    "upgrade_notice": {
        "subject": "BlueBird Alerts — System Upgrade",
        "body": (
            "BlueBird Alerts has been updated to the latest version.\n\n"
            "Your school's alert system is now running the newest release. "
            "No action is required on your part.\n\n"
            "— BlueBird Alerts Platform"
        ),
    },
    "recovery": {
        "subject": "BlueBird Alerts — Service Restored",
        "body": (
            "BlueBird Alerts service has been fully restored.\n\n"
            "All systems are operational and emergency alert delivery is "
            "functioning normally.\n\n"
            "Thank you for your patience.\n\n"
            "— BlueBird Alerts Platform"
        ),
    },
}

TEMPLATE_KEYS = list(TEMPLATES.keys())


# ── Record type ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EmailLogRecord:
    id: int
    timestamp: str
    event_type: str
    to_address: str
    subject: str
    ok: bool
    error: Optional[str]


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    username: str
    from_address: str
    use_tls: bool
    password_set: bool

    @property
    def configured(self) -> bool:
        return bool(self.host and self.from_address)


@dataclass(frozen=True)
class GmailSettings:
    gmail_address: str   # used as both username and from address
    from_name: str
    password_set: bool
    updated_at: Optional[str]
    updated_by: Optional[str]

    @property
    def configured(self) -> bool:
        return bool(self.gmail_address) and self.password_set


# ── Service ────────────────────────────────────────────────────────────────────

class EmailService:
    """
    SMTP email sender for platform-level admin communication.

    Completely separate from the alert delivery system — shares no code path
    with APNs/FCM/Twilio and never touches tenant alert tables.
    """

    def __init__(self, settings: Settings, db_path: str) -> None:
        self._settings = settings
        self._db_path = db_path
        self._encryption_secret = settings.SESSION_SECRET or "bluebird-default-dev"
        self._cooldown_lock = Lock()
        self._last_sent: Dict[str, float] = {}
        self._init_db()

    def is_configured(self) -> bool:
        return self.smtp_config().configured

    def smtp_config(self) -> SMTPConfig:
        return self._smtp_config_sync()

    # ── DB ──────────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=30, isolation_level=None)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_email_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL,
                    event_type  TEXT    NOT NULL,
                    to_address  TEXT    NOT NULL,
                    subject     TEXT    NOT NULL,
                    ok          INTEGER NOT NULL DEFAULT 0,
                    error       TEXT    NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_email_log_ts ON platform_email_log(timestamp);"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_email_settings (
                    key         TEXT PRIMARY KEY,
                    value       TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );
                """
            )

    def _log_sync(
        self,
        timestamp: str,
        event_type: str,
        to_address: str,
        subject: str,
        ok: bool,
        error: Optional[str],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO platform_email_log
                    (timestamp, event_type, to_address, subject, ok, error)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (timestamp, event_type, to_address, subject, 1 if ok else 0, error),
            )
            conn.execute(
                """DELETE FROM platform_email_log WHERE id NOT IN (
                    SELECT id FROM platform_email_log ORDER BY id DESC LIMIT 500
                );"""
            )

    # ── SMTP ────────────────────────────────────────────────────────────────

    def _settings_map_sync(self) -> Dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM platform_email_settings;"
            ).fetchall()
        return {str(key): str(value) for key, value in rows}

    def _smtp_config_sync(self) -> SMTPConfig:
        values = self._settings_map_sync()
        # Support both encrypted (new) and plaintext (legacy) password keys.
        encrypted_pw = values.get("SMTP_PASSWORD_ENCRYPTED", "")
        plaintext_pw = values.get("SMTP_PASSWORD") or self._settings.SMTP_PASSWORD or ""
        password = decrypt_secret(encrypted_pw, self._encryption_secret) if encrypted_pw else plaintext_pw
        return SMTPConfig(
            host=(values.get("SMTP_HOST") or self._settings.SMTP_HOST or "").strip(),
            port=int(values.get("SMTP_PORT") or self._settings.SMTP_PORT or 587),
            username=(values.get("SMTP_USERNAME") or self._settings.SMTP_USERNAME or "").strip(),
            from_address=(values.get("SMTP_FROM") or self._settings.SMTP_FROM or "").strip(),
            use_tls=(values.get("SMTP_USE_TLS") or str(self._settings.SMTP_USE_TLS)).strip().lower()
            in {"1", "true", "yes", "on"},
            password_set=bool(password),
        )

    # ── Gmail-specific settings ────────────────────────────────────────────────

    def _gmail_settings_sync(self) -> GmailSettings:
        values = self._settings_map_sync()
        encrypted_pw = values.get("SMTP_PASSWORD_ENCRYPTED", "")
        gmail_address = (values.get("SMTP_USERNAME") or "").strip()
        return GmailSettings(
            gmail_address=gmail_address,
            from_name=(values.get("SMTP_FROM_NAME") or "BlueBird Alerts").strip(),
            password_set=bool(encrypted_pw),
            updated_at=values.get("GMAIL_UPDATED_AT"),
            updated_by=values.get("GMAIL_UPDATED_BY"),
        )

    async def get_gmail_settings(self) -> GmailSettings:
        return await anyio.to_thread.run_sync(self._gmail_settings_sync)

    def _save_gmail_settings_sync(
        self,
        gmail_address: str,
        from_name: str,
        app_password: Optional[str],
        updated_by: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        values: Dict[str, str] = {
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": gmail_address,
            "SMTP_FROM": gmail_address,
            "SMTP_FROM_NAME": from_name,
            "SMTP_USE_TLS": "true",
            "GMAIL_UPDATED_AT": now,
            "GMAIL_UPDATED_BY": updated_by,
        }
        if app_password and app_password.strip():
            values["SMTP_PASSWORD_ENCRYPTED"] = encrypt_secret(
                app_password.strip(), self._encryption_secret
            )
        with self._connect() as conn:
            for key, value in values.items():
                conn.execute(
                    """
                    INSERT INTO platform_email_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
                    """,
                    (key, value, now),
                )

    async def save_gmail_settings(
        self,
        *,
        gmail_address: str,
        from_name: str,
        app_password: Optional[str] = None,
        updated_by: str = "super_admin",
    ) -> GmailSettings:
        await anyio.to_thread.run_sync(
            self._save_gmail_settings_sync,
            gmail_address.strip().lower(),
            from_name.strip() or "BlueBird Alerts",
            app_password,
            updated_by,
        )
        return await self.get_gmail_settings()

    async def save_smtp_config(
        self,
        *,
        host: str,
        port: int,
        username: str,
        from_address: str,
        use_tls: bool,
        password: Optional[str] = None,
        clear_password: bool = False,
    ) -> SMTPConfig:
        if port < 1 or port > 65535:
            raise ValueError("SMTP port must be between 1 and 65535.")
        await anyio.to_thread.run_sync(
            self._save_smtp_config_sync,
            host.strip(),
            int(port),
            username.strip(),
            from_address.strip(),
            bool(use_tls),
            password,
            bool(clear_password),
        )
        return self.smtp_config()

    def _save_smtp_config_sync(
        self,
        host: str,
        port: int,
        username: str,
        from_address: str,
        use_tls: bool,
        password: Optional[str],
        clear_password: bool,
    ) -> None:
        values = {
            "SMTP_HOST": host,
            "SMTP_PORT": str(port),
            "SMTP_USERNAME": username,
            "SMTP_FROM": from_address,
            "SMTP_USE_TLS": "true" if use_tls else "false",
        }
        if clear_password:
            values["SMTP_PASSWORD"] = ""
        elif password is not None and password.strip():
            values["SMTP_PASSWORD"] = password.strip()
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            for key, value in values.items():
                conn.execute(
                    """
                    INSERT INTO platform_email_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at;
                    """,
                    (key, value, timestamp),
                )

    def _send_sync(self, to_address: str, subject: str, body: str) -> None:
        values = self._settings_map_sync()
        host = (values.get("SMTP_HOST") or self._settings.SMTP_HOST or "").strip()
        port = int(values.get("SMTP_PORT") or self._settings.SMTP_PORT or 587)
        user = (values.get("SMTP_USERNAME") or self._settings.SMTP_USERNAME or "").strip()
        encrypted_pw = values.get("SMTP_PASSWORD_ENCRYPTED", "")
        if encrypted_pw:
            pw = decrypt_secret(encrypted_pw, self._encryption_secret)
        else:
            pw = values.get("SMTP_PASSWORD")
            if pw is None:
                pw = self._settings.SMTP_PASSWORD or ""
        from_address = (values.get("SMTP_FROM") or self._settings.SMTP_FROM or "").strip()
        use_tls = (values.get("SMTP_USE_TLS") or str(self._settings.SMTP_USE_TLS)).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not host or not from_address:
            raise RuntimeError("SMTP is not configured")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_address
        msg["To"] = to_address
        msg.attach(MIMEText(body, "plain", "utf-8"))

        if use_tls and port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10) as smtp:
                if user and pw:
                    smtp.login(user, pw)
                smtp.sendmail(from_address, [to_address], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                if use_tls:
                    smtp.starttls()
                if user and pw:
                    smtp.login(user, pw)
                smtp.sendmail(from_address, [to_address], msg.as_string())

    # ── Public API ──────────────────────────────────────────────────────────

    async def send_email(
        self,
        *,
        to_address: str,
        subject: str,
        body: str,
        event_type: str = "manual",
    ) -> bool:
        timestamp = datetime.now(timezone.utc).isoformat()
        ok = False
        error: Optional[str] = None
        try:
            await anyio.to_thread.run_sync(self._send_sync, to_address, subject, body)
            ok = True
        except Exception as exc:
            error = str(exc)[:500]
        try:
            await anyio.to_thread.run_sync(
                self._log_sync, timestamp, event_type, to_address, subject, ok, error
            )
        except Exception:
            pass
        return ok

    async def send_to_addresses(
        self,
        addresses: Sequence[str],
        *,
        subject: str,
        body: str,
        event_type: str = "bulk",
    ) -> int:
        """Send to multiple addresses; returns count of successes."""
        count = 0
        for addr in addresses:
            if await self.send_email(
                to_address=addr, subject=subject, body=body, event_type=event_type
            ):
                count += 1
        return count

    def check_cooldown(self, event_type: str, cooldown_minutes: int = 30) -> bool:
        """Returns True if sending is allowed. Thread-safe. Updates last-sent timestamp."""
        with self._cooldown_lock:
            last = self._last_sent.get(event_type)
            now = time.monotonic()
            if last is None or (now - last) >= (cooldown_minutes * 60):
                self._last_sent[event_type] = now
                return True
            return False

    def _list_log_sync(self, limit: int) -> List[EmailLogRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, event_type, to_address, subject, ok, error
                FROM platform_email_log
                ORDER BY id DESC LIMIT ?;
                """,
                (limit,),
            ).fetchall()
        return [
            EmailLogRecord(
                id=int(r[0]),
                timestamp=str(r[1]),
                event_type=str(r[2]),
                to_address=str(r[3]),
                subject=str(r[4]),
                ok=bool(int(r[5])),
                error=str(r[6]) if r[6] else None,
            )
            for r in rows
        ]

    async def recent_email_log(self, limit: int = 50) -> List[EmailLogRecord]:
        return await anyio.to_thread.run_sync(self._list_log_sync, int(limit))

    @classmethod
    def get_template(cls, key: str) -> Dict[str, str]:
        return dict(TEMPLATES.get(key, TEMPLATES["maintenance_notice"]))
