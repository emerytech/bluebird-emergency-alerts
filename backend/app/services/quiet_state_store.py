from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import anyio


@dataclass(frozen=True)
class QuietStateRecord:
    id: int
    user_id: int
    home_tenant_id: int
    active: bool
    activated_at: Optional[str]
    source_request_id: Optional[int]
    approved_by_user_id: Optional[int]


class QuietStateStore:
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
                CREATE TABLE IF NOT EXISTS quiet_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    home_tenant_id INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    activated_at TEXT NULL,
                    source_request_id INTEGER NULL,
                    approved_by_user_id INTEGER NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, home_tenant_id)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quiet_states_active ON quiet_states(active, home_tenant_id, user_id);"
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row | tuple) -> QuietStateRecord:
        return QuietStateRecord(
            id=int(row[0]),
            user_id=int(row[1]),
            home_tenant_id=int(row[2]),
            active=bool(int(row[3])),
            activated_at=str(row[4]) if row[4] is not None else None,
            source_request_id=int(row[5]) if row[5] is not None else None,
            approved_by_user_id=int(row[6]) if row[6] is not None else None,
        )

    def _upsert_active_sync(
        self,
        *,
        user_id: int,
        home_tenant_id: int,
        source_request_id: Optional[int],
        approved_by_user_id: Optional[int],
    ) -> QuietStateRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO quiet_states (
                    user_id, home_tenant_id, active, activated_at, source_request_id, approved_by_user_id, updated_at
                )
                VALUES (?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(user_id, home_tenant_id)
                DO UPDATE SET
                    active = 1,
                    activated_at = excluded.activated_at,
                    source_request_id = excluded.source_request_id,
                    approved_by_user_id = excluded.approved_by_user_id,
                    updated_at = excluded.updated_at;
                """,
                (
                    int(user_id),
                    int(home_tenant_id),
                    now,
                    int(source_request_id) if source_request_id is not None else None,
                    int(approved_by_user_id) if approved_by_user_id is not None else None,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT id, user_id, home_tenant_id, active, activated_at, source_request_id, approved_by_user_id
                FROM quiet_states
                WHERE user_id = ? AND home_tenant_id = ?
                LIMIT 1;
                """,
                (int(user_id), int(home_tenant_id)),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    async def upsert_active(
        self,
        *,
        user_id: int,
        home_tenant_id: int,
        source_request_id: Optional[int],
        approved_by_user_id: Optional[int],
    ) -> QuietStateRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._upsert_active_sync(
                user_id=int(user_id),
                home_tenant_id=int(home_tenant_id),
                source_request_id=int(source_request_id) if source_request_id is not None else None,
                approved_by_user_id=int(approved_by_user_id) if approved_by_user_id is not None else None,
            )
        )

    def _deactivate_sync(self, *, user_id: int, home_tenant_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiet_states
                SET active = 0,
                    updated_at = ?
                WHERE user_id = ? AND home_tenant_id = ?;
                """,
                (datetime.now(timezone.utc).isoformat(), int(user_id), int(home_tenant_id)),
            )

    async def deactivate(self, *, user_id: int, home_tenant_id: int) -> None:
        await anyio.to_thread.run_sync(
            lambda: self._deactivate_sync(user_id=int(user_id), home_tenant_id=int(home_tenant_id))
        )

    def _get_sync(self, *, user_id: int, home_tenant_id: int) -> Optional[QuietStateRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, home_tenant_id, active, activated_at, source_request_id, approved_by_user_id
                FROM quiet_states
                WHERE user_id = ? AND home_tenant_id = ?
                LIMIT 1;
                """,
                (int(user_id), int(home_tenant_id)),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def get(self, *, user_id: int, home_tenant_id: int) -> Optional[QuietStateRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._get_sync(user_id=int(user_id), home_tenant_id=int(home_tenant_id))
        )

    async def is_active(self, *, user_id: int, home_tenant_id: int) -> bool:
        record = await self.get(user_id=int(user_id), home_tenant_id=int(home_tenant_id))
        return bool(record and record.active)

