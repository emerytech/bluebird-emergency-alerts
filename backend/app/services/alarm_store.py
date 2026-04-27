from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import anyio


@dataclass(frozen=True)
class AlarmStateRecord:
    is_active: bool = False
    tenant_slug: str = ""
    message: Optional[str] = None
    is_training: bool = False
    training_label: Optional[str] = None
    silent_audio: bool = False
    activated_at: Optional[str] = None
    activated_by_user_id: Optional[int] = None
    activated_by_label: Optional[str] = None
    deactivated_at: Optional[str] = None
    deactivated_by_user_id: Optional[int] = None
    deactivated_by_label: Optional[str] = None


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
                    tenant_slug TEXT NOT NULL DEFAULT '',
                    message TEXT NULL,
                    is_training INTEGER NOT NULL DEFAULT 0,
                    training_label TEXT NULL,
                    silent_audio INTEGER NOT NULL DEFAULT 0,
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
                    id, is_active, tenant_slug, message, is_training, training_label, silent_audio,
                    activated_at, activated_by_user_id, activated_by_label,
                    deactivated_at, deactivated_by_user_id, deactivated_by_label
                )
                VALUES (1, 0, '', NULL, 0, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL)
                ON CONFLICT(id) DO NOTHING;
                """
            )

    def _migrate_alarm_state_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(alarm_state);").fetchall()}
        if "is_training" not in cols:
            conn.execute("ALTER TABLE alarm_state ADD COLUMN is_training INTEGER NOT NULL DEFAULT 0;")
        if "training_label" not in cols:
            conn.execute("ALTER TABLE alarm_state ADD COLUMN training_label TEXT NULL;")
        if "silent_audio" not in cols:
            conn.execute("ALTER TABLE alarm_state ADD COLUMN silent_audio INTEGER NOT NULL DEFAULT 0;")
        if "activated_by_label" not in cols:
            conn.execute("ALTER TABLE alarm_state ADD COLUMN activated_by_label TEXT NULL;")
        if "deactivated_by_label" not in cols:
            conn.execute("ALTER TABLE alarm_state ADD COLUMN deactivated_by_label TEXT NULL;")
        if "tenant_slug" not in cols:
            conn.execute("ALTER TABLE alarm_state ADD COLUMN tenant_slug TEXT NOT NULL DEFAULT '';")

    def _fetch_state_sync(self) -> AlarmStateRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT is_active, tenant_slug, message, is_training, training_label, silent_audio,
                       activated_at, activated_by_user_id, activated_by_label,
                       deactivated_at, deactivated_by_user_id, deactivated_by_label
                FROM alarm_state
                WHERE id = 1;
                """
            ).fetchone()
        if row is None:
            return AlarmStateRecord()
        return AlarmStateRecord(
            is_active=bool(int(row[0])),
            tenant_slug=str(row[1]) if row[1] is not None else "",
            message=str(row[2]) if row[2] is not None else None,
            is_training=bool(int(row[3])),
            training_label=str(row[4]) if row[4] is not None else None,
            silent_audio=bool(int(row[5])),
            activated_at=str(row[6]) if row[6] is not None else None,
            activated_by_user_id=int(row[7]) if row[7] is not None else None,
            activated_by_label=str(row[8]) if row[8] is not None else None,
            deactivated_at=str(row[9]) if row[9] is not None else None,
            deactivated_by_user_id=int(row[10]) if row[10] is not None else None,
            deactivated_by_label=str(row[11]) if row[11] is not None else None,
        )

    async def get_state(self) -> AlarmStateRecord:
        return await anyio.to_thread.run_sync(self._fetch_state_sync)

    def _activate_sync(
        self,
        message: str,
        activated_by_user_id: Optional[int],
        activated_by_label: Optional[str],
        is_training: bool,
        training_label: Optional[str],
        silent_audio: bool,
        tenant_slug: str,
    ) -> AlarmStateRecord:
        activated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE alarm_state
                SET is_active = 1,
                    tenant_slug = ?,
                    message = ?,
                    is_training = ?,
                    training_label = ?,
                    silent_audio = ?,
                    activated_at = ?,
                    activated_by_user_id = ?,
                    activated_by_label = ?,
                    deactivated_at = NULL,
                    deactivated_by_user_id = NULL,
                    deactivated_by_label = NULL
                WHERE id = 1;
                """,
                (
                    tenant_slug,
                    message,
                    1 if is_training else 0,
                    training_label,
                    1 if silent_audio else 0,
                    activated_at,
                    activated_by_user_id,
                    activated_by_label,
                ),
            )
        return self._fetch_state_sync()

    async def activate(
        self,
        *,
        tenant_slug: str,
        message: str,
        activated_by_user_id: Optional[int],
        activated_by_label: Optional[str] = None,
        is_training: bool = False,
        training_label: Optional[str] = None,
        silent_audio: bool = False,
    ) -> AlarmStateRecord:
        return await anyio.to_thread.run_sync(
            self._activate_sync,
            message,
            activated_by_user_id,
            activated_by_label,
            bool(is_training),
            training_label.strip() if training_label else None,
            bool(silent_audio),
            str(tenant_slug).strip().lower(),
        )

    def _deactivate_sync(
        self,
        deactivated_by_user_id: Optional[int],
        deactivated_by_label: Optional[str],
        tenant_slug: str,
    ) -> AlarmStateRecord:
        deactivated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE alarm_state
                SET is_active = 0,
                    tenant_slug = ?,
                    is_training = 0,
                    training_label = NULL,
                    silent_audio = 0,
                    deactivated_at = ?,
                    deactivated_by_user_id = ?,
                    deactivated_by_label = ?
                WHERE id = 1;
                """,
                (tenant_slug, deactivated_at, deactivated_by_user_id, deactivated_by_label),
            )
        return self._fetch_state_sync()

    async def deactivate(
        self,
        *,
        tenant_slug: str,
        deactivated_by_user_id: Optional[int],
        deactivated_by_label: Optional[str] = None,
    ) -> AlarmStateRecord:
        return await anyio.to_thread.run_sync(
            self._deactivate_sync,
            deactivated_by_user_id,
            deactivated_by_label,
            str(tenant_slug).strip().lower(),
        )
