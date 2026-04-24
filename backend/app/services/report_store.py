from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import anyio


@dataclass(frozen=True)
class ReportRecord:
    id: int
    created_at: str
    user_id: Optional[int]
    category: str
    note: Optional[str]


@dataclass(frozen=True)
class BroadcastUpdateRecord:
    id: int
    created_at: str
    admin_user_id: Optional[int]
    message: str


class ReportStore:
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
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    user_id INTEGER NULL,
                    category TEXT NOT NULL,
                    note TEXT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS broadcast_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    admin_user_id INTEGER NULL,
                    message TEXT NOT NULL
                );
                """
            )

    def _create_report_sync(self, created_at: str, user_id: Optional[int], category: str, note: Optional[str]) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO reports (created_at, user_id, category, note)
                VALUES (?, ?, ?, ?);
                """,
                (created_at, user_id, category, note),
            )
            return int(cur.lastrowid)

    async def create_report(self, *, user_id: Optional[int], category: str, note: Optional[str]) -> int:
        return await anyio.to_thread.run_sync(
            self._create_report_sync,
            datetime.now(timezone.utc).isoformat(),
            user_id,
            category,
            note,
        )

    def _create_broadcast_update_sync(self, created_at: str, admin_user_id: Optional[int], message: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO broadcast_updates (created_at, admin_user_id, message)
                VALUES (?, ?, ?);
                """,
                (created_at, admin_user_id, message),
            )
            return int(cur.lastrowid)

    async def create_broadcast_update(self, *, admin_user_id: Optional[int], message: str) -> int:
        return await anyio.to_thread.run_sync(
            self._create_broadcast_update_sync,
            datetime.now(timezone.utc).isoformat(),
            admin_user_id,
            message,
        )

    def _list_reports_sync(self, limit: int) -> List[ReportRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, user_id, category, note
                FROM reports
                ORDER BY id DESC
                LIMIT ?;
                """,
                (int(limit),),
            ).fetchall()
        return [
            ReportRecord(
                id=int(row[0]),
                created_at=str(row[1]),
                user_id=int(row[2]) if row[2] is not None else None,
                category=str(row[3]),
                note=str(row[4]) if row[4] is not None else None,
            )
            for row in rows
        ]

    async def list_reports(self, *, limit: int = 20) -> List[ReportRecord]:
        return await anyio.to_thread.run_sync(self._list_reports_sync, int(limit))

    def _list_broadcast_updates_sync(self, limit: int) -> List[BroadcastUpdateRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, admin_user_id, message
                FROM broadcast_updates
                ORDER BY id DESC
                LIMIT ?;
                """,
                (int(limit),),
            ).fetchall()
        return [
            BroadcastUpdateRecord(
                id=int(row[0]),
                created_at=str(row[1]),
                admin_user_id=int(row[2]) if row[2] is not None else None,
                message=str(row[3]),
            )
            for row in rows
        ]

    async def list_broadcast_updates(self, *, limit: int = 5) -> List[BroadcastUpdateRecord]:
        return await anyio.to_thread.run_sync(self._list_broadcast_updates_sync, int(limit))
