from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import anyio


@dataclass(frozen=True)
class AlertRecord:
    id: int
    created_at: str
    message: str
    triggered_by_user_id: Optional[int] = None


@dataclass(frozen=True)
class AlertDeliveryRecord:
    """
    Delivery audit record. This is intentionally append-only for forensics.
    """

    id: int
    alert_id: int
    created_at: str
    channel: str
    provider: str
    target: str
    ok: bool
    status_code: Optional[int] = None
    error: Optional[str] = None


class AlertLog:
    """
    Minimal SQLite alert log.

    Stores: created_at (UTC ISO-8601), message, optional triggered_by_user_id.

    Safety-critical note:
      - We treat the alerts table as an immutable log (append-only) and record delivery results separately.
      - This helps post-incident review and avoids "losing" data due to updates.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=30, isolation_level=None)

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    message TEXT NOT NULL,
                    triggered_by_user_id INTEGER NULL,
                    trigger_ip TEXT NULL,
                    trigger_user_agent TEXT NULL
                );
                """
            )
            # Older local DBs may have been created before we added attribution fields.
            self._migrate_alerts_table(conn)

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    target TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    status_code INTEGER NULL,
                    error TEXT NULL,
                    FOREIGN KEY(alert_id) REFERENCES alerts(id)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_deliveries_alert_id ON alert_deliveries(alert_id);"
            )

    def _migrate_alerts_table(self, conn: sqlite3.Connection) -> None:
        """
        Minimal forward-only migration for SQLite.

        We avoid a full migration framework for MVP, but we still want schema evolution to be safe.
        """

        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(alerts);").fetchall()}
        if "triggered_by_user_id" not in cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN triggered_by_user_id INTEGER NULL;")
        if "trigger_ip" not in cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN trigger_ip TEXT NULL;")
        if "trigger_user_agent" not in cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN trigger_user_agent TEXT NULL;")

    def _log_alert_sync(
        self,
        created_at: str,
        message: str,
        triggered_by_user_id: Optional[int],
        trigger_ip: Optional[str],
        trigger_user_agent: Optional[str],
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO alerts (created_at, message, triggered_by_user_id, trigger_ip, trigger_user_agent)
                VALUES (?, ?, ?, ?, ?);
                """,
                (created_at, message, triggered_by_user_id, trigger_ip, trigger_user_agent),
            )
            return int(cur.lastrowid)

    async def log_alert(
        self,
        message: str,
        *,
        triggered_by_user_id: Optional[int] = None,
        trigger_ip: Optional[str] = None,
        trigger_user_agent: Optional[str] = None,
    ) -> int:
        """
        Records the panic event quickly and durably before attempting any outbound delivery.

        The DB write is run in a worker thread to avoid blocking the asyncio event loop.
        """

        created_at = datetime.now(timezone.utc).isoformat()
        return await anyio.to_thread.run_sync(
            self._log_alert_sync,
            created_at,
            message,
            triggered_by_user_id,
            trigger_ip,
            trigger_user_agent,
        )

    def _list_recent_sync(self, limit: int) -> List[AlertRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, message, triggered_by_user_id
                FROM alerts
                ORDER BY id DESC
                LIMIT ?;
                """,
                (max(1, limit),),
            ).fetchall()

        return [
            AlertRecord(
                id=int(row[0]),
                created_at=str(row[1]),
                message=str(row[2]),
                triggered_by_user_id=int(row[3]) if row[3] is not None else None,
            )
            for row in rows
        ]

    async def list_recent(self, limit: int = 20) -> List[AlertRecord]:
        """
        Returns most recent alerts for operator UI or audits.
        """

        return await anyio.to_thread.run_sync(self._list_recent_sync, int(limit))

    def _log_delivery_sync(
        self,
        alert_id: int,
        created_at: str,
        channel: str,
        provider: str,
        target: str,
        ok: bool,
        status_code: Optional[int],
        error: Optional[str],
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO alert_deliveries
                    (alert_id, created_at, channel, provider, target, ok, status_code, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    int(alert_id),
                    created_at,
                    channel,
                    provider,
                    target,
                    1 if ok else 0,
                    int(status_code) if status_code is not None else None,
                    error,
                ),
            )
            return int(cur.lastrowid)

    async def log_delivery(
        self,
        *,
        alert_id: int,
        channel: str,
        provider: str,
        target: str,
        ok: bool,
        status_code: Optional[int] = None,
        error: Optional[str] = None,
    ) -> int:
        """
        Records an outbound delivery attempt/result for a specific alert.
        """

        created_at = datetime.now(timezone.utc).isoformat()
        return await anyio.to_thread.run_sync(
            self._log_delivery_sync,
            int(alert_id),
            created_at,
            channel,
            provider,
            target,
            bool(ok),
            status_code,
            error[:500] if error else None,
        )
