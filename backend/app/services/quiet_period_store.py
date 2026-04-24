from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import anyio


@dataclass(frozen=True)
class QuietPeriodRecord:
    id: int
    user_id: int
    reason: Optional[str]
    status: str
    requested_at: str
    approved_at: Optional[str]
    approved_by_user_id: Optional[int]
    approved_by_label: Optional[str]
    expires_at: Optional[str]


class QuietPeriodStore:
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
                CREATE TABLE IF NOT EXISTS quiet_period_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    reason TEXT NULL,
                    status TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    approved_at TEXT NULL,
                    approved_by_user_id INTEGER NULL,
                    approved_by_label TEXT NULL,
                    expires_at TEXT NULL
                );
                """
            )
            self._migrate_quiet_periods_table(conn)

    def _migrate_quiet_periods_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(quiet_period_requests);").fetchall()}
        if "approved_by_label" not in cols:
            conn.execute("ALTER TABLE quiet_period_requests ADD COLUMN approved_by_label TEXT NULL;")
        if "expires_at" not in cols:
            conn.execute("ALTER TABLE quiet_period_requests ADD COLUMN expires_at TEXT NULL;")

    def _row_to_record(self, row: sqlite3.Row | tuple) -> QuietPeriodRecord:
        return QuietPeriodRecord(
            id=int(row[0]),
            user_id=int(row[1]),
            reason=str(row[2]) if row[2] is not None else None,
            status=str(row[3]),
            requested_at=str(row[4]),
            approved_at=str(row[5]) if row[5] is not None else None,
            approved_by_user_id=int(row[6]) if row[6] is not None else None,
            approved_by_label=str(row[7]) if row[7] is not None else None,
            expires_at=str(row[8]) if row[8] is not None else None,
        )

    def _expire_old_sync(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'expired'
                WHERE status = 'approved'
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?;
                """,
                (now,),
            )

    async def expire_old(self) -> None:
        await anyio.to_thread.run_sync(self._expire_old_sync)

    def _request_sync(self, user_id: int, reason: Optional[str]) -> QuietPeriodRecord:
        self._expire_old_sync()
        requested_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'superseded'
                WHERE user_id = ?
                  AND status IN ('pending', 'approved');
                """,
                (int(user_id),),
            )
            cur = conn.execute(
                """
                INSERT INTO quiet_period_requests (
                    user_id, reason, status, requested_at, approved_at, approved_by_user_id, expires_at
                )
                VALUES (?, ?, 'pending', ?, NULL, NULL, NULL);
                """,
                (int(user_id), reason, requested_at),
            )
            row = conn.execute(
                """
                SELECT id, user_id, reason, status, requested_at, approved_at, approved_by_user_id, approved_by_label, expires_at
                FROM quiet_period_requests
                WHERE id = ?;
                """,
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    async def request_quiet_period(self, *, user_id: int, reason: Optional[str]) -> QuietPeriodRecord:
        return await anyio.to_thread.run_sync(self._request_sync, int(user_id), reason)

    def _grant_sync(self, user_id: int, reason: Optional[str], admin_user_id: int, admin_label: Optional[str]) -> QuietPeriodRecord:
        self._expire_old_sync()
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=24)).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'superseded'
                WHERE user_id = ?
                  AND status IN ('pending', 'approved');
                """,
                (int(user_id),),
            )
            cur = conn.execute(
                """
                INSERT INTO quiet_period_requests (
                    user_id, reason, status, requested_at, approved_at, approved_by_user_id, approved_by_label, expires_at
                )
                VALUES (?, ?, 'approved', ?, ?, ?, ?, ?);
                """,
                (int(user_id), reason, now.isoformat(), now.isoformat(), int(admin_user_id), admin_label, expires_at),
            )
            row = conn.execute(
                """
                SELECT id, user_id, reason, status, requested_at, approved_at, approved_by_user_id, approved_by_label, expires_at
                FROM quiet_period_requests
                WHERE id = ?;
                """,
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    async def grant_quiet_period(self, *, user_id: int, reason: Optional[str], admin_user_id: int, admin_label: Optional[str] = None) -> QuietPeriodRecord:
        return await anyio.to_thread.run_sync(self._grant_sync, int(user_id), reason, int(admin_user_id), admin_label)

    def _approve_sync(self, request_id: int, admin_user_id: int, admin_label: Optional[str]) -> Optional[QuietPeriodRecord]:
        self._expire_old_sync()
        approved_at = datetime.now(timezone.utc)
        expires_at = (approved_at + timedelta(hours=24)).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'approved',
                    approved_at = ?,
                    approved_by_user_id = ?,
                    approved_by_label = ?,
                    expires_at = ?
                WHERE id = ?
                  AND status = 'pending';
                """,
                (approved_at.isoformat(), int(admin_user_id), admin_label, expires_at, int(request_id)),
            )
            row = conn.execute(
                """
                SELECT id, user_id, reason, status, requested_at, approved_at, approved_by_user_id, approved_by_label, expires_at
                FROM quiet_period_requests
                WHERE id = ?;
                """,
                (int(request_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def approve_request(self, *, request_id: int, admin_user_id: int, admin_label: Optional[str] = None) -> Optional[QuietPeriodRecord]:
        return await anyio.to_thread.run_sync(self._approve_sync, int(request_id), int(admin_user_id), admin_label)

    def _deny_sync(self, request_id: int, admin_user_id: int, admin_label: Optional[str]) -> Optional[QuietPeriodRecord]:
        self._expire_old_sync()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'denied',
                    approved_at = ?,
                    approved_by_user_id = ?,
                    approved_by_label = ?,
                    expires_at = NULL
                WHERE id = ?
                  AND status = 'pending';
                """,
                (datetime.now(timezone.utc).isoformat(), int(admin_user_id), admin_label, int(request_id)),
            )
            row = conn.execute(
                """
                SELECT id, user_id, reason, status, requested_at, approved_at, approved_by_user_id, approved_by_label, expires_at
                FROM quiet_period_requests
                WHERE id = ?;
                """,
                (int(request_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def deny_request(self, *, request_id: int, admin_user_id: int, admin_label: Optional[str] = None) -> Optional[QuietPeriodRecord]:
        return await anyio.to_thread.run_sync(self._deny_sync, int(request_id), int(admin_user_id), admin_label)

    def _list_recent_sync(self, limit: int) -> List[QuietPeriodRecord]:
        self._expire_old_sync()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, reason, status, requested_at, approved_at, approved_by_user_id, approved_by_label, expires_at
                FROM quiet_period_requests
                ORDER BY id DESC
                LIMIT ?;
                """,
                (int(limit),),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    async def list_recent(self, *, limit: int = 25) -> List[QuietPeriodRecord]:
        return await anyio.to_thread.run_sync(self._list_recent_sync, int(limit))

    def _active_for_user_sync(self, user_id: int) -> Optional[QuietPeriodRecord]:
        self._expire_old_sync()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, reason, status, requested_at, approved_at, approved_by_user_id, approved_by_label, expires_at
                FROM quiet_period_requests
                WHERE user_id = ?
                  AND status = 'approved'
                ORDER BY id DESC
                LIMIT 1;
                """,
                (int(user_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def active_for_user(self, *, user_id: int) -> Optional[QuietPeriodRecord]:
        return await anyio.to_thread.run_sync(self._active_for_user_sync, int(user_id))

    def _active_user_ids_sync(self) -> List[int]:
        self._expire_old_sync()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT user_id
                FROM quiet_period_requests
                WHERE status = 'approved'
                  AND expires_at IS NOT NULL;
                """
            ).fetchall()
        return [int(row[0]) for row in rows if row and row[0] is not None]

    async def active_user_ids(self) -> List[int]:
        return await anyio.to_thread.run_sync(self._active_user_ids_sync)

    def _latest_for_user_sync(self, user_id: int) -> Optional[QuietPeriodRecord]:
        self._expire_old_sync()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, reason, status, requested_at, approved_at, approved_by_user_id, approved_by_label, expires_at
                FROM quiet_period_requests
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 1;
                """,
                (int(user_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def latest_for_user(self, *, user_id: int) -> Optional[QuietPeriodRecord]:
        return await anyio.to_thread.run_sync(self._latest_for_user_sync, int(user_id))

    def _clear_quiet_period_sync(self, request_id: int, admin_user_id: int, admin_label: Optional[str]) -> Optional[QuietPeriodRecord]:
        self._expire_old_sync()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'cleared',
                    approved_at = ?,
                    approved_by_user_id = ?,
                    approved_by_label = ?,
                    expires_at = NULL
                WHERE id = ?
                  AND status = 'approved';
                """,
                (datetime.now(timezone.utc).isoformat(), int(admin_user_id), admin_label, int(request_id)),
            )
            row = conn.execute(
                """
                SELECT id, user_id, reason, status, requested_at, approved_at, approved_by_user_id, approved_by_label, expires_at
                FROM quiet_period_requests
                WHERE id = ?;
                """,
                (int(request_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def clear_quiet_period(self, *, request_id: int, admin_user_id: int, admin_label: Optional[str] = None) -> Optional[QuietPeriodRecord]:
        return await anyio.to_thread.run_sync(self._clear_quiet_period_sync, int(request_id), int(admin_user_id), admin_label)

    def _cancel_for_user_sync(self, request_id: int, user_id: int) -> Optional[QuietPeriodRecord]:
        self._expire_old_sync()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'cancelled',
                    expires_at = NULL
                WHERE id = ?
                  AND user_id = ?
                  AND status IN ('pending', 'approved');
                """,
                (int(request_id), int(user_id)),
            )
            row = conn.execute(
                """
                SELECT id, user_id, reason, status, requested_at, approved_at, approved_by_user_id, approved_by_label, expires_at
                FROM quiet_period_requests
                WHERE id = ?;
                """,
                (int(request_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def cancel_for_user(self, *, request_id: int, user_id: int) -> Optional[QuietPeriodRecord]:
        return await anyio.to_thread.run_sync(self._cancel_for_user_sync, int(request_id), int(user_id))
