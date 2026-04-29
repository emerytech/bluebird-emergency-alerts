from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import anyio

_SELECT_COLS = (
    "id, user_id, reason, status, requested_at, approved_at, "
    "approved_by_user_id, approved_by_label, expires_at, "
    "scheduled_start_at, scheduled_end_at, denied_at, cancelled_at"
)


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
    scheduled_start_at: Optional[str] = None
    scheduled_end_at: Optional[str] = None
    denied_at: Optional[str] = None
    cancelled_at: Optional[str] = None


def compute_countdown(record: QuietPeriodRecord) -> tuple[Optional[str], Optional[str]]:
    """Return (countdown_target_at, countdown_mode) for a record.

    countdown_mode is 'starts_in' for scheduled, 'ends_in' for approved/active, else None.
    """
    if record.status == "scheduled" and record.scheduled_start_at:
        return record.scheduled_start_at, "starts_in"
    if record.status == "approved" and record.expires_at:
        return record.expires_at, "ends_in"
    return None, None


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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_qpr_user_id ON quiet_period_requests(user_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_qpr_status ON quiet_period_requests(status);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_qpr_user_status ON quiet_period_requests(user_id, status);"
            )

    def _migrate_quiet_periods_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(quiet_period_requests);").fetchall()}
        if "approved_by_label" not in cols:
            conn.execute("ALTER TABLE quiet_period_requests ADD COLUMN approved_by_label TEXT NULL;")
        if "expires_at" not in cols:
            conn.execute("ALTER TABLE quiet_period_requests ADD COLUMN expires_at TEXT NULL;")
        if "scheduled_start_at" not in cols:
            conn.execute("ALTER TABLE quiet_period_requests ADD COLUMN scheduled_start_at TEXT NULL;")
        if "scheduled_end_at" not in cols:
            conn.execute("ALTER TABLE quiet_period_requests ADD COLUMN scheduled_end_at TEXT NULL;")
        if "denied_at" not in cols:
            conn.execute("ALTER TABLE quiet_period_requests ADD COLUMN denied_at TEXT NULL;")
        if "cancelled_at" not in cols:
            conn.execute("ALTER TABLE quiet_period_requests ADD COLUMN cancelled_at TEXT NULL;")

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
            scheduled_start_at=str(row[9]) if len(row) > 9 and row[9] is not None else None,
            scheduled_end_at=str(row[10]) if len(row) > 10 and row[10] is not None else None,
            denied_at=str(row[11]) if len(row) > 11 and row[11] is not None else None,
            cancelled_at=str(row[12]) if len(row) > 12 and row[12] is not None else None,
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
            # Activate scheduled requests whose start time has arrived.
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'approved'
                WHERE status = 'scheduled'
                  AND scheduled_start_at IS NOT NULL
                  AND scheduled_start_at <= ?;
                """,
                (now,),
            )

    async def expire_old(self) -> None:
        await anyio.to_thread.run_sync(self._expire_old_sync)

    def _expire_and_return_sync(self) -> List[QuietPeriodRecord]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {_SELECT_COLS}
                FROM quiet_period_requests
                WHERE status = 'approved'
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?;
                """,
                (now,),
            ).fetchall()
            if not rows:
                return []
            ids = [int(row[0]) for row in rows]
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE quiet_period_requests SET status = 'expired' WHERE id IN ({placeholders});",
                ids,
            )
        return [self._row_to_record(row) for row in rows]

    async def expire_and_return(self) -> List[QuietPeriodRecord]:
        return await anyio.to_thread.run_sync(self._expire_and_return_sync)

    def _request_sync(
        self,
        user_id: int,
        reason: Optional[str],
        scheduled_start_at: Optional[str] = None,
        scheduled_end_at: Optional[str] = None,
    ) -> QuietPeriodRecord:
        self._expire_old_sync()
        requested_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'superseded'
                WHERE user_id = ?
                  AND status IN ('pending', 'approved', 'scheduled');
                """,
                (int(user_id),),
            )
            cur = conn.execute(
                """
                INSERT INTO quiet_period_requests (
                    user_id, reason, status, requested_at, approved_at, approved_by_user_id, expires_at,
                    scheduled_start_at, scheduled_end_at
                )
                VALUES (?, ?, 'pending', ?, NULL, NULL, NULL, ?, ?);
                """,
                (int(user_id), reason, requested_at, scheduled_start_at, scheduled_end_at),
            )
            row = conn.execute(
                f"""
                SELECT {_SELECT_COLS}
                FROM quiet_period_requests
                WHERE id = ?;
                """,
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    async def request_quiet_period(
        self,
        *,
        user_id: int,
        reason: Optional[str],
        scheduled_start_at: Optional[str] = None,
        scheduled_end_at: Optional[str] = None,
    ) -> QuietPeriodRecord:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(
                self._request_sync,
                int(user_id),
                reason,
                scheduled_start_at,
                scheduled_end_at,
            )
        )

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
                f"""
                SELECT {_SELECT_COLS}
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
        with self._connect() as conn:
            # Read scheduled times before updating to determine status.
            rec = conn.execute(
                "SELECT scheduled_start_at, scheduled_end_at FROM quiet_period_requests WHERE id = ? AND status = 'pending';",
                (int(request_id),),
            ).fetchone()
            if rec is None:
                return None
            sched_start_raw = rec[0]
            sched_end_raw = rec[1]

            # Determine if this is a future-scheduled approval.
            new_status = "approved"
            if sched_start_raw:
                try:
                    start_dt = datetime.fromisoformat(str(sched_start_raw))
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                    if start_dt > approved_at:
                        new_status = "scheduled"
                except ValueError:
                    pass

            if new_status == "scheduled":
                if sched_end_raw:
                    expires_at = str(sched_end_raw)
                else:
                    start_dt = datetime.fromisoformat(str(sched_start_raw))
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                    expires_at = (start_dt + timedelta(hours=24)).isoformat()
            else:
                if sched_end_raw:
                    expires_at = str(sched_end_raw)
                else:
                    expires_at = (approved_at + timedelta(hours=24)).isoformat()

            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = ?,
                    approved_at = ?,
                    approved_by_user_id = ?,
                    approved_by_label = ?,
                    expires_at = ?
                WHERE id = ?
                  AND status = 'pending';
                """,
                (new_status, approved_at.isoformat(), int(admin_user_id), admin_label, expires_at, int(request_id)),
            )
            row = conn.execute(
                f"""
                SELECT {_SELECT_COLS}
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
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'denied',
                    denied_at = ?,
                    approved_by_user_id = ?,
                    approved_by_label = ?,
                    expires_at = NULL
                WHERE id = ?
                  AND status = 'pending';
                """,
                (now, int(admin_user_id), admin_label, int(request_id)),
            )
            row = conn.execute(
                f"""
                SELECT {_SELECT_COLS}
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
                f"""
                SELECT {_SELECT_COLS}
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
                f"""
                SELECT {_SELECT_COLS}
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
                f"""
                SELECT {_SELECT_COLS}
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

    def _pending_for_user_sync(self, user_id: int) -> Optional[QuietPeriodRecord]:
        self._expire_old_sync()
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_SELECT_COLS}
                FROM quiet_period_requests
                WHERE user_id = ?
                  AND status IN ('pending', 'scheduled')
                ORDER BY id DESC
                LIMIT 1;
                """,
                (int(user_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def pending_for_user(self, *, user_id: int) -> Optional[QuietPeriodRecord]:
        return await anyio.to_thread.run_sync(self._pending_for_user_sync, int(user_id))

    def _get_request_sync(self, request_id: int) -> Optional[QuietPeriodRecord]:
        self._expire_old_sync()
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_SELECT_COLS}
                FROM quiet_period_requests
                WHERE id = ?
                LIMIT 1;
                """,
                (int(request_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def get_request(self, *, request_id: int) -> Optional[QuietPeriodRecord]:
        return await anyio.to_thread.run_sync(self._get_request_sync, int(request_id))

    def _clear_quiet_period_sync(self, request_id: int, admin_user_id: int, admin_label: Optional[str]) -> Optional[QuietPeriodRecord]:
        self._expire_old_sync()
        now = datetime.now(timezone.utc).isoformat()
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
                (now, int(admin_user_id), admin_label, int(request_id)),
            )
            row = conn.execute(
                f"""
                SELECT {_SELECT_COLS}
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
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'cancelled',
                    cancelled_at = ?,
                    expires_at = NULL
                WHERE id = ?
                  AND user_id = ?
                  AND status IN ('pending', 'approved', 'scheduled');
                """,
                (now, int(request_id), int(user_id)),
            )
            row = conn.execute(
                f"""
                SELECT {_SELECT_COLS}
                FROM quiet_period_requests
                WHERE id = ?;
                """,
                (int(request_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def cancel_for_user(self, *, request_id: int, user_id: int) -> Optional[QuietPeriodRecord]:
        return await anyio.to_thread.run_sync(self._cancel_for_user_sync, int(request_id), int(user_id))

    def _cancel_active_for_user_sync(self, user_id: int) -> Optional[QuietPeriodRecord]:
        """Find and cancel the most recent active quiet period for a user by user_id.
        Does not require a request_id — safe to call when the client has a stale or unknown ID."""
        self._expire_old_sync()
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            active_row = conn.execute(
                """
                SELECT id FROM quiet_period_requests
                WHERE user_id = ?
                  AND status IN ('pending', 'approved', 'scheduled')
                ORDER BY id DESC
                LIMIT 1;
                """,
                (int(user_id),),
            ).fetchone()
            if active_row is None:
                return None
            request_id = int(active_row[0])
            conn.execute(
                """
                UPDATE quiet_period_requests
                SET status = 'cancelled', cancelled_at = ?, expires_at = NULL
                WHERE id = ? AND user_id = ? AND status IN ('pending', 'approved', 'scheduled');
                """,
                (now, request_id, int(user_id)),
            )
            row = conn.execute(
                f"""
                SELECT {_SELECT_COLS}
                FROM quiet_period_requests
                WHERE id = ?;
                """,
                (request_id,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def cancel_active_for_user(self, *, user_id: int) -> Optional[QuietPeriodRecord]:
        """Cancel the active quiet period for a user by user_id only (no request_id needed)."""
        return await anyio.to_thread.run_sync(self._cancel_active_for_user_sync, int(user_id))
