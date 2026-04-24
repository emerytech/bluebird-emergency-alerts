from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import anyio


@dataclass(frozen=True)
class AlarmStateRecord:
    is_active: bool
    message: Optional[str]
    activated_at: Optional[str]
    activated_by_user_id: Optional[int]
    activated_by_label: Optional[str]
    deactivated_at: Optional[str]
    deactivated_by_user_id: Optional[int]
    deactivated_by_label: Optional[str]


class AlarmStore:
    """
    Persists the single current alarm state for the system.

    We keep one row keyed by `id = 1` so clients can quickly determine whether
    the school is in an active alarm state without reconstructing it from alerts.
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alarm_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    is_active INTEGER NOT NULL DEFAULT 0,
                    message TEXT NULL,
                    activated_at TEXT NULL,
                    activated_by_user_id INTEGER NULL,
                    activated_by_label TEXT NULL,
                    deactivated_at TEXT NULL,
                    deactivated_by_user_id INTEGER NULL,
                    deactivated_by_label TEXT NULL
                );
                """
            )
            self._migrate_alarm_state_table(conn)
            conn.execute(
                """
                INSERT INTO alarm_state (
                    id, is_active, message, activated_at, activated_by_user_id, activated_by_label, deactivated_at, deactivated_by_user_id, deactivated_by_label
                )
                VALUES (1, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                ON CONFLICT(id) DO NOTHING;
                """
            )

    def _migrate_alarm_state_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(alarm_state);").fetchall()}
        if "activated_by_label" not in cols:
            conn.execute("ALTER TABLE alarm_state ADD COLUMN activated_by_label TEXT NULL;")
        if "deactivated_by_label" not in cols:
            conn.execute("ALTER TABLE alarm_state ADD COLUMN deactivated_by_label TEXT NULL;")

    def _fetch_state_sync(self) -> AlarmStateRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT is_active, message, activated_at, activated_by_user_id, activated_by_label, deactivated_at, deactivated_by_user_id, deactivated_by_label
                FROM alarm_state
                WHERE id = 1;
                """
            ).fetchone()
        if row is None:
            return AlarmStateRecord(False, None, None, None, None, None, None, None)
        return AlarmStateRecord(
            is_active=bool(int(row[0])),
            message=str(row[1]) if row[1] is not None else None,
            activated_at=str(row[2]) if row[2] is not None else None,
            activated_by_user_id=int(row[3]) if row[3] is not None else None,
            activated_by_label=str(row[4]) if row[4] is not None else None,
            deactivated_at=str(row[5]) if row[5] is not None else None,
            deactivated_by_user_id=int(row[6]) if row[6] is not None else None,
            deactivated_by_label=str(row[7]) if row[7] is not None else None,
        )

    async def get_state(self) -> AlarmStateRecord:
        return await anyio.to_thread.run_sync(self._fetch_state_sync)

    def _activate_sync(self, message: str, activated_by_user_id: Optional[int], activated_by_label: Optional[str]) -> AlarmStateRecord:
        activated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE alarm_state
                SET is_active = 1,
                    message = ?,
                    activated_at = ?,
                    activated_by_user_id = ?,
                    activated_by_label = ?,
                    deactivated_at = NULL,
                    deactivated_by_user_id = NULL,
                    deactivated_by_label = NULL
                WHERE id = 1;
                """,
                (message, activated_at, activated_by_user_id, activated_by_label),
            )
        return self._fetch_state_sync()

    async def activate(self, *, message: str, activated_by_user_id: Optional[int], activated_by_label: Optional[str] = None) -> AlarmStateRecord:
        return await anyio.to_thread.run_sync(self._activate_sync, message, activated_by_user_id, activated_by_label)

    def _deactivate_sync(self, deactivated_by_user_id: Optional[int], deactivated_by_label: Optional[str]) -> AlarmStateRecord:
        deactivated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE alarm_state
                SET is_active = 0,
                    deactivated_at = ?,
                    deactivated_by_user_id = ?,
                    deactivated_by_label = ?
                WHERE id = 1;
                """,
                (deactivated_at, deactivated_by_user_id, deactivated_by_label),
            )
        return self._fetch_state_sync()

    async def deactivate(self, *, deactivated_by_user_id: Optional[int], deactivated_by_label: Optional[str] = None) -> AlarmStateRecord:
        return await anyio.to_thread.run_sync(self._deactivate_sync, deactivated_by_user_id, deactivated_by_label)
