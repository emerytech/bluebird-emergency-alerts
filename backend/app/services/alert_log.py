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
    is_training: bool = False
    training_label: Optional[str] = None
    created_by_user_id: Optional[int] = None
    triggered_by_user_id: Optional[int] = None
    triggered_by_label: Optional[str] = None


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


@dataclass(frozen=True)
class AlertAcknowledgementRecord:
    id: int
    alert_id: int
    user_id: int
    acknowledged_at: str
    user_label: Optional[str] = None
    tenant_slug: str = ""


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
                    is_training INTEGER NOT NULL DEFAULT 0,
                    training_label TEXT NULL,
                    created_by_user_id INTEGER NULL,
                    triggered_by_user_id INTEGER NULL,
                    triggered_by_label TEXT NULL,
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_acknowledgements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    acknowledged_at TEXT NOT NULL,
                    user_label TEXT NULL,
                    tenant_slug TEXT NOT NULL DEFAULT '',
                    UNIQUE(alert_id, user_id),
                    FOREIGN KEY(alert_id) REFERENCES alerts(id)
                );
                """
            )
            self._migrate_acknowledgements_table(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_acknowledgements_alert_id ON alert_acknowledgements(alert_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_acknowledgements_user_id ON alert_acknowledgements(user_id);"
            )

    def _migrate_alerts_table(self, conn: sqlite3.Connection) -> None:
        """
        Minimal forward-only migration for SQLite.

        We avoid a full migration framework for MVP, but we still want schema evolution to be safe.
        """

        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(alerts);").fetchall()}
        if "triggered_by_user_id" not in cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN triggered_by_user_id INTEGER NULL;")
        if "is_training" not in cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN is_training INTEGER NOT NULL DEFAULT 0;")
        if "training_label" not in cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN training_label TEXT NULL;")
        if "created_by_user_id" not in cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN created_by_user_id INTEGER NULL;")
        if "triggered_by_label" not in cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN triggered_by_label TEXT NULL;")
        if "trigger_ip" not in cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN trigger_ip TEXT NULL;")
        if "trigger_user_agent" not in cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN trigger_user_agent TEXT NULL;")

    def _migrate_acknowledgements_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(alert_acknowledgements);").fetchall()}
        if "tenant_slug" not in cols:
            conn.execute("ALTER TABLE alert_acknowledgements ADD COLUMN tenant_slug TEXT NOT NULL DEFAULT '';")

    def _log_alert_sync(
        self,
        created_at: str,
        message: str,
        is_training: bool,
        training_label: Optional[str],
        created_by_user_id: Optional[int],
        triggered_by_user_id: Optional[int],
        triggered_by_label: Optional[str],
        trigger_ip: Optional[str],
        trigger_user_agent: Optional[str],
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO alerts (
                    created_at,
                    message,
                    is_training,
                    training_label,
                    created_by_user_id,
                    triggered_by_user_id,
                    triggered_by_label,
                    trigger_ip,
                    trigger_user_agent
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    created_at,
                    message,
                    1 if is_training else 0,
                    training_label,
                    created_by_user_id,
                    triggered_by_user_id,
                    triggered_by_label,
                    trigger_ip,
                    trigger_user_agent,
                ),
            )
            return int(cur.lastrowid)

    async def log_alert(
        self,
        message: str,
        *,
        is_training: bool = False,
        training_label: Optional[str] = None,
        created_by_user_id: Optional[int] = None,
        triggered_by_user_id: Optional[int] = None,
        triggered_by_label: Optional[str] = None,
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
            bool(is_training),
            training_label.strip() if training_label else None,
            created_by_user_id,
            triggered_by_user_id,
            triggered_by_label,
            trigger_ip,
            trigger_user_agent,
        )

    def _list_recent_sync(self, limit: int) -> List[AlertRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    message,
                    is_training,
                    training_label,
                    created_by_user_id,
                    triggered_by_user_id,
                    triggered_by_label
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
                is_training=bool(int(row[3])),
                training_label=str(row[4]) if row[4] is not None else None,
                created_by_user_id=int(row[5]) if row[5] is not None else None,
                triggered_by_user_id=int(row[6]) if row[6] is not None else None,
                triggered_by_label=str(row[7]) if row[7] is not None else None,
            )
            for row in rows
        ]

    async def list_recent(self, limit: int = 20) -> List[AlertRecord]:
        """
        Returns most recent alerts for operator UI or audits.
        """

        return await anyio.to_thread.run_sync(self._list_recent_sync, int(limit))

    def _get_alert_sync(self, alert_id: int) -> Optional[AlertRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    message,
                    is_training,
                    training_label,
                    created_by_user_id,
                    triggered_by_user_id,
                    triggered_by_label
                FROM alerts
                WHERE id = ?;
                """,
                (int(alert_id),),
            ).fetchone()
        if row is None:
            return None
        return AlertRecord(
            id=int(row[0]),
            created_at=str(row[1]),
            message=str(row[2]),
            is_training=bool(int(row[3])),
            training_label=str(row[4]) if row[4] is not None else None,
            created_by_user_id=int(row[5]) if row[5] is not None else None,
            triggered_by_user_id=int(row[6]) if row[6] is not None else None,
            triggered_by_label=str(row[7]) if row[7] is not None else None,
        )

    async def get_alert(self, alert_id: int) -> Optional[AlertRecord]:
        return await anyio.to_thread.run_sync(self._get_alert_sync, int(alert_id))

    async def latest_alert(self) -> Optional[AlertRecord]:
        items = await self.list_recent(limit=1)
        return items[0] if items else None

    def _acknowledge_sync(self, alert_id: int, user_id: int, user_label: Optional[str], tenant_slug: str) -> AlertAcknowledgementRecord:
        acknowledged_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO alert_acknowledgements (
                    alert_id,
                    user_id,
                    acknowledged_at,
                    user_label,
                    tenant_slug
                )
                VALUES (?, ?, ?, ?, ?);
                """,
                (int(alert_id), int(user_id), acknowledged_at, user_label, tenant_slug),
            )
            row = conn.execute(
                """
                SELECT id, alert_id, user_id, acknowledged_at, user_label, tenant_slug
                FROM alert_acknowledgements
                WHERE alert_id = ? AND user_id = ?;
                """,
                (int(alert_id), int(user_id)),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to read alert acknowledgement after insert")
        return AlertAcknowledgementRecord(
            id=int(row[0]),
            alert_id=int(row[1]),
            user_id=int(row[2]),
            acknowledged_at=str(row[3]),
            user_label=str(row[4]) if row[4] is not None else None,
            tenant_slug=str(row[5]) if row[5] is not None else "",
        )

    async def acknowledge(
        self,
        *,
        alert_id: int,
        user_id: int,
        user_label: Optional[str] = None,
        tenant_slug: str = "",
    ) -> AlertAcknowledgementRecord:
        slug = str(tenant_slug).strip().lower()
        return await anyio.to_thread.run_sync(
            lambda: self._acknowledge_sync(int(alert_id), int(user_id), user_label, slug)
        )

    def _ack_count_sync(self, alert_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM alert_acknowledgements WHERE alert_id = ?;",
                (int(alert_id),),
            ).fetchone()
        return int(row[0]) if row else 0

    async def acknowledgement_count(self, alert_id: int) -> int:
        return await anyio.to_thread.run_sync(self._ack_count_sync, int(alert_id))

    def _has_ack_sync(self, alert_id: int, user_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM alert_acknowledgements WHERE alert_id = ? AND user_id = ? LIMIT 1;",
                (int(alert_id), int(user_id)),
            ).fetchone()
        return row is not None

    async def has_acknowledged(self, *, alert_id: int, user_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._has_ack_sync, int(alert_id), int(user_id))

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
