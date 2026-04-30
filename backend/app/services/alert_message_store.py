from __future__ import annotations

import functools
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import anyio


@dataclass(frozen=True)
class AlertMessageRecord:
    id: int
    alert_id: int
    tenant_slug: str
    sender_id: int
    sender_role: str
    sender_label: Optional[str]
    recipient_id: Optional[int]
    message: str
    is_broadcast: bool
    timestamp: str


class AlertMessageStore:
    """
    Per-tenant SQLite store for alert-scoped messages.

    Schema:
        alert_messages(id, alert_id, tenant_slug, sender_id, sender_role,
                       sender_label, recipient_id, message, is_broadcast, timestamp)

    Visibility rules (enforced in get_messages):
        - Admins see every message for the alert.
        - Regular users see: broadcasts + messages they sent + admin replies to them.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_messages (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id     INTEGER NOT NULL,
                    tenant_slug  TEXT    NOT NULL DEFAULT '',
                    sender_id    INTEGER NOT NULL,
                    sender_role  TEXT    NOT NULL DEFAULT '',
                    sender_label TEXT,
                    recipient_id INTEGER,
                    message      TEXT    NOT NULL,
                    is_broadcast INTEGER NOT NULL DEFAULT 0,
                    timestamp    TEXT    NOT NULL
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_messages_alert "
                "ON alert_messages(alert_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_messages_sender "
                "ON alert_messages(sender_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_messages_recipient "
                "ON alert_messages(recipient_id);"
            )

    # ── write ─────────────────────────────────────────────────────────────────

    def _send_sync(
        self,
        alert_id: int,
        tenant_slug: str,
        sender_id: int,
        sender_role: str,
        sender_label: Optional[str],
        recipient_id: Optional[int],
        message: str,
        is_broadcast: bool,
    ) -> AlertMessageRecord:
        ts = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO alert_messages
                    (alert_id, tenant_slug, sender_id, sender_role, sender_label,
                     recipient_id, message, is_broadcast, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    alert_id, tenant_slug, sender_id, sender_role, sender_label,
                    recipient_id, message, 1 if is_broadcast else 0, ts,
                ),
            )
            row = conn.execute(
                "SELECT id, alert_id, tenant_slug, sender_id, sender_role, "
                "sender_label, recipient_id, message, is_broadcast, timestamp "
                "FROM alert_messages WHERE id = ?;",
                (cur.lastrowid,),
            ).fetchone()
        return _row(row)

    async def send_message(
        self,
        alert_id: int,
        tenant_slug: str,
        sender_id: int,
        sender_role: str,
        sender_label: Optional[str],
        recipient_id: Optional[int],
        message: str,
        is_broadcast: bool = False,
    ) -> AlertMessageRecord:
        return await anyio.to_thread.run_sync(
            functools.partial(
                self._send_sync,
                int(alert_id), tenant_slug, int(sender_id), sender_role,
                sender_label,
                int(recipient_id) if recipient_id is not None else None,
                message, is_broadcast,
            )
        )

    # ── read ──────────────────────────────────────────────────────────────────

    def _get_messages_sync(
        self, alert_id: int, user_id: Optional[int], is_admin: bool
    ) -> List[AlertMessageRecord]:
        with self._connect() as conn:
            if is_admin:
                rows = conn.execute(
                    "SELECT id, alert_id, tenant_slug, sender_id, sender_role, "
                    "sender_label, recipient_id, message, is_broadcast, timestamp "
                    "FROM alert_messages WHERE alert_id = ? "
                    "ORDER BY timestamp ASC;",
                    (int(alert_id),),
                ).fetchall()
            else:
                uid = int(user_id or 0)
                rows = conn.execute(
                    "SELECT id, alert_id, tenant_slug, sender_id, sender_role, "
                    "sender_label, recipient_id, message, is_broadcast, timestamp "
                    "FROM alert_messages "
                    "WHERE alert_id = ? "
                    "  AND (is_broadcast = 1 OR sender_id = ? OR recipient_id = ?) "
                    "ORDER BY timestamp ASC;",
                    (int(alert_id), uid, uid),
                ).fetchall()
        return [_row(r) for r in rows]

    async def get_messages(
        self,
        alert_id: int,
        user_id: Optional[int] = None,
        is_admin: bool = False,
    ) -> List[AlertMessageRecord]:
        return await anyio.to_thread.run_sync(
            functools.partial(
                self._get_messages_sync, int(alert_id), user_id, is_admin
            )
        )

    def _count_sent_since_sync(self, alert_id: int, sender_id: int, since_ts: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM alert_messages "
                "WHERE alert_id = ? AND sender_id = ? AND timestamp >= ?;",
                (int(alert_id), int(sender_id), since_ts),
            ).fetchone()
        return int(row[0]) if row else 0

    async def count_sent_since(self, alert_id: int, sender_id: int, since_ts: str) -> int:
        """Used for rate-limiting: count messages from sender since a given ISO timestamp."""
        return await anyio.to_thread.run_sync(
            functools.partial(
                self._count_sent_since_sync, int(alert_id), int(sender_id), since_ts
            )
        )


def _row(row: tuple) -> AlertMessageRecord:
    return AlertMessageRecord(
        id=int(row[0]),
        alert_id=int(row[1]),
        tenant_slug=str(row[2]) if row[2] else "",
        sender_id=int(row[3]),
        sender_role=str(row[4]) if row[4] else "",
        sender_label=str(row[5]) if row[5] is not None else None,
        recipient_id=int(row[6]) if row[6] is not None else None,
        message=str(row[7]),
        is_broadcast=bool(row[8]),
        timestamp=str(row[9]),
    )
