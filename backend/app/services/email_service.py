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
from typing import Any, Dict, List, Optional, Sequence

import anyio
import httpx
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

DEFAULT_AUTO_REPLY_SUBJECT = "Thanks for your interest in BlueBird Alerts"
DEFAULT_AUTO_REPLY_BODY = (
    "Hi {{name}},\n\n"
    "Thanks for reaching out about BlueBird Alerts. I received your request for "
    "{{school_or_district}} and will review the details soon.\n\n"
    "BlueBird Alerts is designed to help schools quickly notify staff, coordinate "
    "responses, and improve visibility during active situations.\n\n"
    "I'll follow up with more information and a custom quote.\n\n"
    "Thanks,\n"
    "Taylor\n"
    "Emery Tech Solutions"
)

DEFAULT_INQUIRY_NOTIFY_EMAIL = "taylor@emerytechsolutions.com"


# ── Record types ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EmailMessage:
    id: int
    provider_message_id: str
    thread_id: Optional[str]
    direction: str          # inbound | outbound
    from_email: str
    from_name: str
    to_email: str
    subject: str
    body_text: str
    body_html: str
    received_at: Optional[str]
    sent_at: Optional[str]
    is_read: bool
    status: str             # new | read | replied | archived
    linked_inquiry_id: Optional[int]
    linked_customer_id: Optional[int]
    linked_district_id: Optional[int]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider_message_id": self.provider_message_id,
            "thread_id": self.thread_id,
            "direction": self.direction,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "to_email": self.to_email,
            "subject": self.subject,
            "body_text": self.body_text[:500],
            "body_html": "",
            "received_at": self.received_at,
            "sent_at": self.sent_at,
            "is_read": self.is_read,
            "status": self.status,
            "linked_inquiry_id": self.linked_inquiry_id,
            "linked_customer_id": self.linked_customer_id,
            "linked_district_id": self.linked_district_id,
            "created_at": self.created_at,
        }

    def to_full_dict(self) -> dict:
        d = self.to_dict()
        d["body_text"] = self.body_text
        d["body_html"] = self.body_html
        return d


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_stripe_settings (
                    id                      INTEGER PRIMARY KEY DEFAULT 1,
                    mode                    TEXT    NOT NULL DEFAULT 'test',
                    publishable_key         TEXT    NOT NULL DEFAULT '',
                    secret_key_encrypted    TEXT    NOT NULL DEFAULT '',
                    webhook_secret_encrypted TEXT   NOT NULL DEFAULT '',
                    updated_at              TEXT    NOT NULL DEFAULT ''
                );
                """
            )
            # Ensure the singleton row exists
            conn.execute(
                "INSERT OR IGNORE INTO platform_stripe_settings (id) VALUES (1);"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stripe_events (
                    event_id     TEXT    PRIMARY KEY,
                    event_type   TEXT    NOT NULL,
                    district_id  INTEGER NULL,
                    processed_at TEXT    NOT NULL,
                    payload_json TEXT    NOT NULL DEFAULT '{}'
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_stripe_events_ts "
                "ON stripe_events(processed_at DESC);"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS billing_plans (
                    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_type            TEXT    NOT NULL UNIQUE,
                    display_name         TEXT    NOT NULL,
                    stripe_price_id_test TEXT    NULL,
                    stripe_price_id_live TEXT    NULL,
                    max_schools          INTEGER NULL,
                    max_users            INTEGER NULL,
                    features_json        TEXT    NULL,
                    internal_notes       TEXT    NULL,
                    is_active            INTEGER NOT NULL DEFAULT 1,
                    created_at           TEXT    NOT NULL,
                    updated_at           TEXT    NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_messages (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_message_id TEXT    NOT NULL UNIQUE,
                    thread_id           TEXT    NULL,
                    direction           TEXT    NOT NULL DEFAULT 'inbound',
                    from_email          TEXT    NOT NULL DEFAULT '',
                    from_name           TEXT    NOT NULL DEFAULT '',
                    to_email            TEXT    NOT NULL DEFAULT '',
                    subject             TEXT    NOT NULL DEFAULT '',
                    body_text           TEXT    NOT NULL DEFAULT '',
                    body_html           TEXT    NOT NULL DEFAULT '',
                    received_at         TEXT    NULL,
                    sent_at             TEXT    NULL,
                    is_read             INTEGER NOT NULL DEFAULT 0,
                    status              TEXT    NOT NULL DEFAULT 'new',
                    linked_inquiry_id   INTEGER NULL,
                    linked_customer_id  INTEGER NULL,
                    linked_district_id  INTEGER NULL,
                    created_at          TEXT    NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_email_msg_created "
                "ON email_messages(created_at DESC);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_email_msg_direction "
                "ON email_messages(direction, is_read);"
            )
            # Migrations for existing databases.
            for col, typedef in (
                ("linked_customer_id", "INTEGER NULL"),
                ("linked_district_id", "INTEGER NULL"),
            ):
                try:
                    conn.execute(f"ALTER TABLE email_messages ADD COLUMN {col} {typedef};")
                except Exception:
                    pass  # column already exists

            # Seed default plans if table is empty
            now = datetime.now(timezone.utc).isoformat()
            for pt, dn in (
                ("trial", "Trial"),
                ("basic", "Basic"),
                ("pro", "Pro"),
                ("enterprise", "Enterprise"),
            ):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO billing_plans
                        (plan_type, display_name, is_active, created_at, updated_at)
                    VALUES (?, ?, 1, ?, ?);
                    """,
                    (pt, dn, now, now),
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

    def _send_html_sync(self, to_address: str, subject: str, body_text: str, body_html: str) -> None:
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
            "1", "true", "yes", "on",
        }
        if not host or not from_address:
            raise RuntimeError("SMTP is not configured")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_address
        msg["To"] = to_address
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
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

    async def send_html_email(
        self,
        *,
        to_address: str,
        subject: str,
        body_text: str,
        body_html: str,
        event_type: str = "invite",
    ) -> bool:
        timestamp = datetime.now(timezone.utc).isoformat()
        ok = False
        error: Optional[str] = None
        try:
            await anyio.to_thread.run_sync(
                self._send_html_sync, to_address, subject, body_text, body_html
            )
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

    # ── Extended email delivery settings ────────────────────────────────────

    def _get_delivery_settings_sync(self) -> Dict[str, str]:
        return self._settings_map_sync()

    async def get_delivery_settings(self) -> Dict[str, str]:
        """Return all platform_email_settings as a dict (secrets masked)."""
        raw = await anyio.to_thread.run_sync(self._get_delivery_settings_sync)
        masked: Dict[str, str] = {}
        for k, v in raw.items():
            if "ENCRYPTED" in k or k == "SMTP_PASSWORD":
                masked[k] = "••••••••" if v else ""
            else:
                masked[k] = v
        return masked

    def _save_settings_sync(self, updates: Dict[str, str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            for key, value in updates.items():
                conn.execute(
                    """
                    INSERT INTO platform_email_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value, updated_at = excluded.updated_at;
                    """,
                    (key, value, now),
                )

    async def save_delivery_settings(
        self,
        *,
        provider: str,
        from_email: str,
        from_name: str,
        reply_to_email: str = "",
        inquiry_notify_email: str = "",
        inbox_filter_to: str = "",
        sendgrid_api_key: Optional[str] = None,
    ) -> None:
        """Save provider-level and general email delivery settings."""
        valid_providers = {"smtp", "sendgrid", "disabled"}
        if provider not in valid_providers:
            raise ValueError(f"Invalid provider: {provider!r}")
        updates: Dict[str, str] = {
            "PROVIDER": provider,
            "FROM_EMAIL": from_email.strip().lower(),
            "FROM_NAME": from_name.strip() or "BlueBird Alerts",
            "REPLY_TO_EMAIL": reply_to_email.strip(),
            "INQUIRY_NOTIFY_EMAIL": (
                inquiry_notify_email.strip() or DEFAULT_INQUIRY_NOTIFY_EMAIL
            ),
            "INBOX_FILTER_TO": inbox_filter_to.strip().lower(),
        }
        if sendgrid_api_key and sendgrid_api_key.strip():
            updates["SENDGRID_API_KEY_ENCRYPTED"] = encrypt_secret(
                sendgrid_api_key.strip(), self._encryption_secret
            )
        await anyio.to_thread.run_sync(self._save_settings_sync, updates)

    async def save_auto_reply_settings(
        self,
        *,
        enabled: bool,
        subject: str,
        body: str,
    ) -> None:
        updates: Dict[str, str] = {
            "AUTO_REPLY_ENABLED": "1" if enabled else "0",
            "AUTO_REPLY_SUBJECT": subject.strip() or DEFAULT_AUTO_REPLY_SUBJECT,
            "AUTO_REPLY_BODY": body.strip() or DEFAULT_AUTO_REPLY_BODY,
        }
        await anyio.to_thread.run_sync(self._save_settings_sync, updates)

    def _get_auto_reply_sync(self) -> Dict[str, str]:
        values = self._settings_map_sync()
        return {
            "enabled": values.get("AUTO_REPLY_ENABLED", "0"),
            "subject": values.get("AUTO_REPLY_SUBJECT", DEFAULT_AUTO_REPLY_SUBJECT),
            "body": values.get("AUTO_REPLY_BODY", DEFAULT_AUTO_REPLY_BODY),
        }

    async def get_auto_reply_settings(self) -> Dict[str, str]:
        return await anyio.to_thread.run_sync(self._get_auto_reply_sync)

    # ── SendGrid ────────────────────────────────────────────────────────────

    async def _send_via_sendgrid(
        self,
        *,
        to_address: str,
        subject: str,
        body_text: str,
        from_address: str,
        from_name: str,
        reply_to: Optional[str] = None,
        api_key: str,
    ) -> None:
        payload: Dict[str, Any] = {
            "personalizations": [{"to": [{"email": to_address}]}],
            "from": {"email": from_address, "name": from_name},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body_text}],
        }
        if reply_to:
            payload["reply_to"] = {"email": reply_to}
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if r.status_code not in (200, 202):
                raise RuntimeError(
                    f"SendGrid error {r.status_code}: {r.text[:200]}"
                )

    # ── Unified send (routes through active provider) ────────────────────────

    async def send_via_provider(
        self,
        *,
        to_address: str,
        subject: str,
        body: str,
        event_type: str = "manual",
        reply_to: Optional[str] = None,
    ) -> bool:
        """
        Send through whichever provider is configured.
        Returns True on success. Never raises — logs and returns False on failure.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        ok = False
        error: Optional[str] = None
        try:
            values = await anyio.to_thread.run_sync(self._settings_map_sync)
            provider = values.get("PROVIDER", "smtp").lower()

            if provider == "disabled":
                return True  # silently drop

            if provider == "sendgrid":
                api_key_enc = values.get("SENDGRID_API_KEY_ENCRYPTED", "")
                api_key = (
                    decrypt_secret(api_key_enc, self._encryption_secret)
                    if api_key_enc
                    else ""
                )
                if not api_key:
                    raise RuntimeError("SendGrid API key not configured")
                from_email = (
                    values.get("FROM_EMAIL")
                    or values.get("SMTP_FROM")
                    or self._settings.SMTP_FROM
                    or ""
                ).strip()
                from_name = (values.get("FROM_NAME") or values.get("SMTP_FROM_NAME") or "BlueBird Alerts").strip()
                rt = reply_to or values.get("REPLY_TO_EMAIL", "")
                await self._send_via_sendgrid(
                    to_address=to_address,
                    subject=subject,
                    body_text=body,
                    from_address=from_email,
                    from_name=from_name,
                    reply_to=rt or None,
                    api_key=api_key,
                )
                ok = True
            else:
                # SMTP path (existing logic)
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

    # ── Inquiry emails ───────────────────────────────────────────────────────

    @staticmethod
    def render_template(template: str, vars: Dict[str, str]) -> str:
        """Replace {{var}} placeholders in template with values dict."""
        result = template
        for key, val in vars.items():
            result = result.replace("{{" + key + "}}", str(val))
        return result

    async def send_inquiry_notification(self, inquiry: Any) -> bool:
        """Send admin notification email for a new inquiry. Never raises."""
        try:
            values = await anyio.to_thread.run_sync(self._settings_map_sync)
            notify_email = (
                values.get("INQUIRY_NOTIFY_EMAIL") or DEFAULT_INQUIRY_NOTIFY_EMAIL
            ).strip()
            if not notify_email:
                return False

            students = str(getattr(inquiry, "estimated_students", "N/A") or "N/A")
            schools = str(getattr(inquiry, "number_of_schools", "N/A") or "N/A")
            tag = str(getattr(inquiry, "size_tag", "")).upper()
            body = (
                f"New BlueBird Alerts Inquiry [{tag}]\n\n"
                f"Name: {getattr(inquiry, 'name', '')}\n"
                f"Email: {getattr(inquiry, 'email', '')}\n"
                f"School/District: {getattr(inquiry, 'school_or_district', '')}\n"
                f"Estimated Students: {students}\n"
                f"Number of Schools: {schools}\n"
                f"Submitted: {getattr(inquiry, 'created_at', '')}\n\n"
                f"Message:\n{getattr(inquiry, 'message', '')}\n\n"
                f"--\nView in Super Admin: /super-admin?section=inquiries"
            )
            return await self.send_via_provider(
                to_address=notify_email,
                subject=f"[BlueBird Inquiry] {getattr(inquiry, 'name', 'New inquiry')} — {getattr(inquiry, 'school_or_district', '')}",
                body=body,
                event_type="inquiry_notification",
            )
        except Exception:
            return False

    async def send_inquiry_auto_reply(self, inquiry: Any) -> bool:
        """Send auto-reply to inquiry submitter if enabled. Never raises."""
        try:
            ar = await self.get_auto_reply_settings()
            if ar.get("enabled", "0") != "1":
                return False

            vars: Dict[str, str] = {
                "name": str(getattr(inquiry, "name", "")),
                "email": str(getattr(inquiry, "email", "")),
                "school_or_district": str(getattr(inquiry, "school_or_district", "")),
                "estimated_students": str(getattr(inquiry, "estimated_students", "") or ""),
                "number_of_schools": str(getattr(inquiry, "number_of_schools", "") or ""),
            }
            subject = self.render_template(ar["subject"], vars)
            body = self.render_template(ar["body"], vars)

            return await self.send_via_provider(
                to_address=str(getattr(inquiry, "email", "")),
                subject=subject,
                body=body,
                event_type="inquiry_auto_reply",
            )
        except Exception:
            return False

    # ── Demo request emails ──────────────────────────────────────────────────

    async def send_demo_request_notification(self, req: Any) -> bool:
        """Send admin notification email for a new demo request. Never raises."""
        try:
            values = await anyio.to_thread.run_sync(self._settings_map_sync)
            notify_email = (
                values.get("INQUIRY_NOTIFY_EMAIL") or DEFAULT_INQUIRY_NOTIFY_EMAIL
            ).strip()
            if not notify_email:
                return False

            role = str(getattr(req, "role", "") or "")
            school_count = str(getattr(req, "school_count", "N/A") or "N/A")
            phone = str(getattr(req, "phone", "") or "")
            preferred_time = str(getattr(req, "preferred_time", "") or "")
            body = (
                f"New BlueBird Alerts Demo Request\n\n"
                f"Name: {getattr(req, 'name', '')}\n"
                f"Email: {getattr(req, 'email', '')}\n"
                f"Organization: {getattr(req, 'organization', '')}\n"
                f"Role: {role}\n"
                f"Number of Schools: {school_count}\n"
                f"Phone: {phone or 'N/A'}\n"
                f"Preferred Demo Time: {preferred_time or 'N/A'}\n"
                f"Submitted: {getattr(req, 'created_at', '')}\n\n"
                f"Message:\n{getattr(req, 'message', '')}\n\n"
                f"--\nView in Super Admin: /super-admin?section=demo-requests"
            )
            return await self.send_via_provider(
                to_address=notify_email,
                subject=f"New Demo Request — {getattr(req, 'organization', 'New request')}",
                body=body,
                event_type="demo_request_notification",
            )
        except Exception:
            return False

    async def send_demo_request_auto_reply(self, req: Any) -> bool:
        """Send auto-reply to demo request submitter if auto-reply is enabled. Never raises."""
        try:
            ar = await self.get_auto_reply_settings()
            if ar.get("enabled", "0") != "1":
                return False

            vars: Dict[str, str] = {
                "name": str(getattr(req, "name", "")),
                "email": str(getattr(req, "email", "")),
                "organization": str(getattr(req, "organization", "")),
                "school_or_district": str(getattr(req, "organization", "")),
                "role": str(getattr(req, "role", "") or ""),
                "school_count": str(getattr(req, "school_count", "") or ""),
            }
            subject = self.render_template(ar["subject"], vars)
            body = self.render_template(ar["body"], vars)

            return await self.send_via_provider(
                to_address=str(getattr(req, "email", "")),
                subject=subject,
                body=body,
                event_type="demo_request_auto_reply",
            )
        except Exception:
            return False

    # ── Stripe settings ──────────────────────────────────────────────────────

    def _get_stripe_settings_sync(self) -> Dict[str, str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT mode, publishable_key, secret_key_encrypted, "
                "webhook_secret_encrypted, updated_at "
                "FROM platform_stripe_settings WHERE id = 1;"
            ).fetchone()
        if row is None:
            return {
                "mode": "test",
                "publishable_key": "",
                "secret_key_set": "0",
                "webhook_secret_set": "0",
                "updated_at": "",
            }
        return {
            "mode": str(row[0] or "test"),
            "publishable_key": str(row[1] or ""),
            "secret_key_set": "1" if row[2] else "0",
            "webhook_secret_set": "1" if row[3] else "0",
            "updated_at": str(row[4] or ""),
        }

    async def get_stripe_settings(self) -> Dict[str, str]:
        return await anyio.to_thread.run_sync(self._get_stripe_settings_sync)

    def _get_stripe_secret_sync(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT secret_key_encrypted FROM platform_stripe_settings WHERE id = 1;"
            ).fetchone()
        if not row or not row[0]:
            return ""
        return decrypt_secret(str(row[0]), self._encryption_secret)

    async def get_stripe_secret_key(self) -> str:
        """Return the decrypted Stripe secret key. Do not log or return to frontend."""
        return await anyio.to_thread.run_sync(self._get_stripe_secret_sync)

    def _get_stripe_webhook_secret_sync(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT webhook_secret_encrypted FROM platform_stripe_settings WHERE id = 1;"
            ).fetchone()
        if not row or not row[0]:
            return ""
        return decrypt_secret(str(row[0]), self._encryption_secret)

    async def get_stripe_webhook_secret(self) -> str:
        return await anyio.to_thread.run_sync(self._get_stripe_webhook_secret_sync)

    def _get_stripe_mode_sync(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT mode FROM platform_stripe_settings WHERE id = 1;"
            ).fetchone()
        return str(row[0] or "test") if row else "test"

    async def get_stripe_mode(self) -> str:
        return await anyio.to_thread.run_sync(self._get_stripe_mode_sync)

    def _save_stripe_settings_sync(
        self,
        mode: str,
        publishable_key: str,
        secret_key: Optional[str],
        webhook_secret: Optional[str],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT secret_key_encrypted, webhook_secret_encrypted "
                "FROM platform_stripe_settings WHERE id = 1;"
            ).fetchone()
            existing_sk = str(row[0] or "") if row else ""
            existing_wh = str(row[1] or "") if row else ""

            new_sk = (
                encrypt_secret(secret_key.strip(), self._encryption_secret)
                if secret_key and secret_key.strip()
                else existing_sk
            )
            new_wh = (
                encrypt_secret(webhook_secret.strip(), self._encryption_secret)
                if webhook_secret and webhook_secret.strip()
                else existing_wh
            )
            conn.execute(
                """
                INSERT INTO platform_stripe_settings
                    (id, mode, publishable_key, secret_key_encrypted,
                     webhook_secret_encrypted, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    mode                     = excluded.mode,
                    publishable_key          = excluded.publishable_key,
                    secret_key_encrypted     = excluded.secret_key_encrypted,
                    webhook_secret_encrypted = excluded.webhook_secret_encrypted,
                    updated_at               = excluded.updated_at;
                """,
                (mode, publishable_key, new_sk, new_wh, now),
            )

    async def save_stripe_settings(
        self,
        *,
        mode: str,
        publishable_key: str,
        secret_key: Optional[str] = None,
        webhook_secret: Optional[str] = None,
    ) -> Dict[str, str]:
        if mode not in ("test", "live"):
            raise ValueError("Stripe mode must be 'test' or 'live'")
        await anyio.to_thread.run_sync(
            self._save_stripe_settings_sync,
            mode,
            publishable_key.strip(),
            secret_key,
            webhook_secret,
        )
        return await self.get_stripe_settings()

    # ── Stripe event idempotency ─────────────────────────────────────────────

    def _mark_stripe_event_sync(
        self, event_id: str, event_type: str, district_id: Optional[int], payload_json: str
    ) -> bool:
        """Returns True if the event was freshly inserted, False if already processed."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO stripe_events (event_id, event_type, district_id, processed_at, payload_json)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (event_id, event_type, district_id, now, payload_json[:65535]),
                )
                return True
            except Exception:
                return False

    async def mark_stripe_event(
        self,
        *,
        event_id: str,
        event_type: str,
        district_id: Optional[int] = None,
        payload_json: str = "{}",
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._mark_stripe_event_sync, event_id, event_type, district_id, payload_json
        )

    # ── Billing plans ────────────────────────────────────────────────────────

    def _list_billing_plans_sync(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, plan_type, display_name, stripe_price_id_test,
                       stripe_price_id_live, max_schools, max_users,
                       features_json, internal_notes, is_active
                FROM billing_plans ORDER BY id;
                """
            ).fetchall()
        return [
            {
                "id": int(r[0]),
                "plan_type": str(r[1]),
                "display_name": str(r[2]),
                "stripe_price_id_test": r[3],
                "stripe_price_id_live": r[4],
                "max_schools": r[5],
                "max_users": r[6],
                "features_json": r[7],
                "internal_notes": r[8],
                "is_active": bool(r[9]),
            }
            for r in rows
        ]

    async def list_billing_plans(self) -> List[Dict[str, Any]]:
        return await anyio.to_thread.run_sync(self._list_billing_plans_sync)

    def _save_billing_plan_sync(
        self,
        plan_type: str,
        display_name: str,
        stripe_price_id_test: Optional[str],
        stripe_price_id_live: Optional[str],
        max_schools: Optional[int],
        max_users: Optional[int],
        internal_notes: Optional[str],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO billing_plans
                    (plan_type, display_name, stripe_price_id_test, stripe_price_id_live,
                     max_schools, max_users, internal_notes, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(plan_type) DO UPDATE SET
                    display_name         = excluded.display_name,
                    stripe_price_id_test = excluded.stripe_price_id_test,
                    stripe_price_id_live = excluded.stripe_price_id_live,
                    max_schools          = excluded.max_schools,
                    max_users            = excluded.max_users,
                    internal_notes       = excluded.internal_notes,
                    updated_at           = excluded.updated_at;
                """,
                (
                    plan_type,
                    display_name,
                    stripe_price_id_test or None,
                    stripe_price_id_live or None,
                    max_schools,
                    max_users,
                    internal_notes or None,
                    now,
                    now,
                ),
            )

    async def save_billing_plan(
        self,
        *,
        plan_type: str,
        display_name: str,
        stripe_price_id_test: Optional[str] = None,
        stripe_price_id_live: Optional[str] = None,
        max_schools: Optional[int] = None,
        max_users: Optional[int] = None,
        internal_notes: Optional[str] = None,
    ) -> None:
        await anyio.to_thread.run_sync(
            self._save_billing_plan_sync,
            plan_type,
            display_name,
            stripe_price_id_test,
            stripe_price_id_live,
            max_schools,
            max_users,
            internal_notes,
        )

    # ── IMAP credentials ─────────────────────────────────────────────────────

    def get_imap_credentials_sync(self) -> Dict[str, str]:
        """Return IMAP connection params. Empty strings if not configured."""
        values = self._settings_map_sync()
        encrypted_pw = values.get("SMTP_PASSWORD_ENCRYPTED", "")
        password = decrypt_secret(encrypted_pw, self._encryption_secret) if encrypted_pw else ""
        username = (values.get("SMTP_USERNAME") or "").strip()
        imap_host = (values.get("IMAP_HOST") or "imap.gmail.com").strip()
        imap_port = int(values.get("IMAP_PORT") or 993)
        inbox_filter_to = (values.get("INBOX_FILTER_TO") or "").strip().lower()
        return {
            "host": imap_host,
            "port": str(imap_port),
            "username": username,
            "password": password,
            "filter_to": inbox_filter_to,
        }

    async def get_imap_credentials(self) -> Dict[str, str]:
        return await anyio.to_thread.run_sync(self.get_imap_credentials_sync)

    # ── email_messages CRUD ──────────────────────────────────────────────────

    @staticmethod
    def _msg_row(row: tuple) -> "EmailMessage":
        return EmailMessage(
            id=int(row[0]),
            provider_message_id=str(row[1]),
            thread_id=str(row[2]) if row[2] else None,
            direction=str(row[3]),
            from_email=str(row[4]),
            from_name=str(row[5]),
            to_email=str(row[6]),
            subject=str(row[7]),
            body_text=str(row[8]),
            body_html=str(row[9]),
            received_at=str(row[10]) if row[10] else None,
            sent_at=str(row[11]) if row[11] else None,
            is_read=bool(int(row[12])),
            status=str(row[13]),
            linked_inquiry_id=int(row[14]) if row[14] is not None else None,
            linked_customer_id=int(row[15]) if row[15] is not None else None,
            linked_district_id=int(row[16]) if row[16] is not None else None,
            created_at=str(row[17]),
        )

    _MSG_COLS = (
        "id, provider_message_id, thread_id, direction, from_email, from_name, "
        "to_email, subject, body_text, body_html, received_at, sent_at, "
        "is_read, status, linked_inquiry_id, linked_customer_id, linked_district_id, created_at"
    )

    def store_message_sync(
        self,
        *,
        provider_message_id: str,
        thread_id: Optional[str],
        direction: str,
        from_email: str,
        from_name: str,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str,
        received_at: Optional[str],
        sent_at: Optional[str],
        is_read: bool = False,
        status: str = "new",
        linked_inquiry_id: Optional[int] = None,
        linked_customer_id: Optional[int] = None,
        linked_district_id: Optional[int] = None,
    ) -> Optional["EmailMessage"]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    f"""
                    INSERT INTO email_messages
                        (provider_message_id, thread_id, direction, from_email, from_name,
                         to_email, subject, body_text, body_html, received_at, sent_at,
                         is_read, status, linked_inquiry_id, linked_customer_id,
                         linked_district_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        provider_message_id[:2048], thread_id, direction,
                        from_email[:512], from_name[:255], to_email[:512],
                        subject[:512], body_text[:65535], body_html[:131072],
                        received_at, sent_at, 1 if is_read else 0,
                        status, linked_inquiry_id, linked_customer_id,
                        linked_district_id, now,
                    ),
                )
                row = conn.execute(
                    f"SELECT {self._MSG_COLS} FROM email_messages WHERE id = ?;",
                    (cur.lastrowid,),
                ).fetchone()
            except Exception:
                return None
        return self._msg_row(row) if row else None

    async def store_message(self, **kwargs) -> Optional["EmailMessage"]:
        return await anyio.to_thread.run_sync(lambda: self.store_message_sync(**kwargs))

    def list_messages_sync(
        self,
        *,
        direction: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 100,
    ) -> List["EmailMessage"]:
        clauses: list = []
        params: list = []
        if direction:
            clauses.append("direction = ?")
            params.append(direction)
        if unread_only:
            clauses.append("is_read = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._MSG_COLS} FROM email_messages "
                f"{where} ORDER BY created_at DESC LIMIT ?;",
                (*params, int(limit)),
            ).fetchall()
        return [self._msg_row(r) for r in rows]

    async def list_messages(self, **kwargs) -> List["EmailMessage"]:
        return await anyio.to_thread.run_sync(lambda: self.list_messages_sync(**kwargs))

    def get_message_sync(self, message_id: int) -> Optional["EmailMessage"]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._MSG_COLS} FROM email_messages WHERE id = ? LIMIT 1;",
                (int(message_id),),
            ).fetchone()
        return self._msg_row(row) if row else None

    async def get_message(self, message_id: int) -> Optional["EmailMessage"]:
        return await anyio.to_thread.run_sync(lambda: self.get_message_sync(int(message_id)))

    def mark_read_sync(self, message_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE email_messages SET is_read = 1, status = CASE "
                "WHEN status = 'new' THEN 'read' ELSE status END "
                "WHERE id = ?;",
                (int(message_id),),
            )

    async def mark_read(self, message_id: int) -> None:
        await anyio.to_thread.run_sync(lambda: self.mark_read_sync(int(message_id)))

    def link_inquiry_sync(self, message_id: int, inquiry_id: Optional[int]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE email_messages SET linked_inquiry_id = ? WHERE id = ?;",
                (inquiry_id, int(message_id)),
            )

    async def link_inquiry(self, message_id: int, inquiry_id: Optional[int]) -> None:
        await anyio.to_thread.run_sync(lambda: self.link_inquiry_sync(int(message_id), inquiry_id))

    def link_customer_sync(self, message_id: int, customer_id: Optional[int]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE email_messages SET linked_customer_id = ? WHERE id = ?;",
                (customer_id, int(message_id)),
            )

    async def link_customer(self, message_id: int, customer_id: Optional[int]) -> None:
        await anyio.to_thread.run_sync(lambda: self.link_customer_sync(int(message_id), customer_id))

    def link_district_sync(self, message_id: int, district_id: Optional[int]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE email_messages SET linked_district_id = ? WHERE id = ?;",
                (district_id, int(message_id)),
            )

    async def link_district(self, message_id: int, district_id: Optional[int]) -> None:
        await anyio.to_thread.run_sync(lambda: self.link_district_sync(int(message_id), district_id))

    def _list_messages_by_customer_sync(self, customer_id: int, limit: int = 50) -> List[EmailMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._MSG_COLS} FROM email_messages "
                f"WHERE linked_customer_id = ? ORDER BY created_at DESC LIMIT ?;",
                (int(customer_id), limit),
            ).fetchall()
        return [self._msg_row(r) for r in rows]

    async def list_messages_by_customer(self, customer_id: int, limit: int = 50) -> List[EmailMessage]:
        return await anyio.to_thread.run_sync(
            lambda: self._list_messages_by_customer_sync(customer_id, limit)
        )

    def mark_replied_sync(self, message_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE email_messages SET status = 'replied' WHERE id = ?;",
                (int(message_id),),
            )

    async def mark_replied(self, message_id: int) -> None:
        await anyio.to_thread.run_sync(lambda: self.mark_replied_sync(int(message_id)))

    def message_id_exists_sync(self, provider_message_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM email_messages WHERE provider_message_id = ? LIMIT 1;",
                (str(provider_message_id)[:2048],),
            ).fetchone()
        return row is not None

    async def message_id_exists(self, provider_message_id: str) -> bool:
        return await anyio.to_thread.run_sync(
            lambda: self.message_id_exists_sync(provider_message_id)
        )

    def unread_count_sync(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM email_messages WHERE direction = 'inbound' AND is_read = 0;"
            ).fetchone()
        return int(row[0]) if row else 0

    async def unread_count(self) -> int:
        return await anyio.to_thread.run_sync(self.unread_count_sync)
