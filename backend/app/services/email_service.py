from __future__ import annotations

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

from app.core.config import Settings


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
        self._cooldown_lock = Lock()
        self._last_sent: Dict[str, float] = {}
        self._init_db()

    def is_configured(self) -> bool:
        return bool(self._settings.SMTP_HOST and self._settings.SMTP_FROM)

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

    def _send_sync(self, to_address: str, subject: str, body: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._settings.SMTP_FROM
        msg["To"] = to_address
        msg.attach(MIMEText(body, "plain", "utf-8"))

        host = self._settings.SMTP_HOST
        port = int(self._settings.SMTP_PORT)
        user = self._settings.SMTP_USERNAME or ""
        pw = self._settings.SMTP_PASSWORD or ""

        if self._settings.SMTP_USE_TLS and port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10) as smtp:
                if user and pw:
                    smtp.login(user, pw)
                smtp.sendmail(self._settings.SMTP_FROM, [to_address], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                if self._settings.SMTP_USE_TLS:
                    smtp.starttls()
                if user and pw:
                    smtp.login(user, pw)
                smtp.sendmail(self._settings.SMTP_FROM, [to_address], msg.as_string())

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
