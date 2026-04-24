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
    admin_label: Optional[str]
    message: str


@dataclass(frozen=True)
class AdminMessageRecord:
    id: int
    created_at: str
    sender_user_id: Optional[int]
    recipient_user_id: Optional[int]
    sender_label: Optional[str]
    direction: str
    message: str
    status: str
    response_message: Optional[str]
    response_created_at: Optional[str]
    response_by_user_id: Optional[int]
    response_by_label: Optional[str]


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
                    admin_label TEXT NULL,
                    message TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    sender_user_id INTEGER NULL,
                    recipient_user_id INTEGER NULL,
                    sender_label TEXT NULL,
                    direction TEXT NOT NULL DEFAULT 'user_to_admin',
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    response_message TEXT NULL,
                    response_created_at TEXT NULL,
                    response_by_user_id INTEGER NULL,
                    response_by_label TEXT NULL
                );
                """
            )
            self._migrate_broadcast_updates_table(conn)
            self._migrate_admin_messages_table(conn)

    def _migrate_broadcast_updates_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(broadcast_updates);").fetchall()}
        if "admin_label" not in cols:
            conn.execute("ALTER TABLE broadcast_updates ADD COLUMN admin_label TEXT NULL;")

    def _migrate_admin_messages_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(admin_messages);").fetchall()}
        if "recipient_user_id" not in cols:
            conn.execute("ALTER TABLE admin_messages ADD COLUMN recipient_user_id INTEGER NULL;")
        if "direction" not in cols:
            conn.execute("ALTER TABLE admin_messages ADD COLUMN direction TEXT NOT NULL DEFAULT 'user_to_admin';")

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

    def _create_broadcast_update_sync(self, created_at: str, admin_user_id: Optional[int], admin_label: Optional[str], message: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO broadcast_updates (created_at, admin_user_id, admin_label, message)
                VALUES (?, ?, ?, ?);
                """,
                (created_at, admin_user_id, admin_label, message),
            )
            return int(cur.lastrowid)

    async def create_broadcast_update(self, *, admin_user_id: Optional[int], message: str, admin_label: Optional[str] = None) -> int:
        return await anyio.to_thread.run_sync(
            self._create_broadcast_update_sync,
            datetime.now(timezone.utc).isoformat(),
            admin_user_id,
            admin_label,
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
                SELECT id, created_at, admin_user_id, admin_label, message
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
                admin_label=str(row[3]) if row[3] is not None else None,
                message=str(row[4]),
            )
            for row in rows
        ]

    async def list_broadcast_updates(self, *, limit: int = 5) -> List[BroadcastUpdateRecord]:
        return await anyio.to_thread.run_sync(self._list_broadcast_updates_sync, int(limit))

    def _create_admin_message_sync(
        self,
        created_at: str,
        sender_user_id: Optional[int],
        recipient_user_id: Optional[int],
        sender_label: Optional[str],
        direction: str,
        message: str,
        status: str,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO admin_messages (
                    created_at, sender_user_id, recipient_user_id, sender_label, direction, message, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (created_at, sender_user_id, recipient_user_id, sender_label, direction, message, status),
            )
            return int(cur.lastrowid)

    async def create_admin_message(
        self,
        *,
        sender_user_id: Optional[int],
        recipient_user_id: Optional[int],
        sender_label: Optional[str],
        direction: str,
        message: str,
        status: str = "open",
    ) -> int:
        return await anyio.to_thread.run_sync(
            self._create_admin_message_sync,
            datetime.now(timezone.utc).isoformat(),
            sender_user_id,
            recipient_user_id,
            sender_label,
            direction,
            message,
            status,
        )

    def _reply_admin_message_sync(
        self,
        message_id: int,
        response_message: str,
        response_by_user_id: Optional[int],
        response_by_label: Optional[str],
    ) -> Optional[AdminMessageRecord]:
        response_created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE admin_messages
                SET status = 'answered',
                    response_message = ?,
                    response_created_at = ?,
                    response_by_user_id = ?,
                    response_by_label = ?
                WHERE id = ?;
                """,
                (
                    response_message,
                    response_created_at,
                    response_by_user_id,
                    response_by_label,
                    int(message_id),
                ),
            )
            row = conn.execute(
                """
                SELECT id, created_at, sender_user_id, sender_label, message, status,
                       response_message, response_created_at, response_by_user_id, response_by_label,
                       recipient_user_id, direction
                FROM admin_messages
                WHERE id = ?
                LIMIT 1;
                """,
                (int(message_id),),
            ).fetchone()
        if row is None:
            return None
        return AdminMessageRecord(
            id=int(row[0]),
            created_at=str(row[1]),
            sender_user_id=int(row[2]) if row[2] is not None else None,
            sender_label=str(row[3]) if row[3] is not None else None,
            message=str(row[4]),
            status=str(row[5]),
            response_message=str(row[6]) if row[6] is not None else None,
            response_created_at=str(row[7]) if row[7] is not None else None,
            response_by_user_id=int(row[8]) if row[8] is not None else None,
            response_by_label=str(row[9]) if row[9] is not None else None,
            recipient_user_id=int(row[10]) if row[10] is not None else None,
            direction=str(row[11]) if row[11] is not None else "user_to_admin",
        )

    async def reply_admin_message(
        self,
        *,
        message_id: int,
        response_message: str,
        response_by_user_id: Optional[int],
        response_by_label: Optional[str],
    ) -> Optional[AdminMessageRecord]:
        return await anyio.to_thread.run_sync(
            self._reply_admin_message_sync,
            int(message_id),
            response_message,
            response_by_user_id,
            response_by_label,
        )

    def _list_admin_messages_sync(self, limit: int) -> List[AdminMessageRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, sender_user_id, sender_label, message, status,
                       response_message, response_created_at, response_by_user_id, response_by_label,
                       recipient_user_id, direction
                FROM admin_messages
                WHERE direction = 'user_to_admin'
                ORDER BY id DESC
                LIMIT ?;
                """,
                (int(limit),),
            ).fetchall()
        return [
            AdminMessageRecord(
                id=int(row[0]),
                created_at=str(row[1]),
                sender_user_id=int(row[2]) if row[2] is not None else None,
                sender_label=str(row[3]) if row[3] is not None else None,
                message=str(row[4]),
                status=str(row[5]),
                response_message=str(row[6]) if row[6] is not None else None,
                response_created_at=str(row[7]) if row[7] is not None else None,
                response_by_user_id=int(row[8]) if row[8] is not None else None,
                response_by_label=str(row[9]) if row[9] is not None else None,
                recipient_user_id=int(row[10]) if row[10] is not None else None,
                direction=str(row[11]) if row[11] is not None else "user_to_admin",
            )
            for row in rows
        ]

    async def list_admin_messages(self, *, limit: int = 50) -> List[AdminMessageRecord]:
        return await anyio.to_thread.run_sync(self._list_admin_messages_sync, int(limit))

    def _list_messages_for_user_sync(self, user_id: int, limit: int) -> List[AdminMessageRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, sender_user_id, sender_label, message, status,
                       response_message, response_created_at, response_by_user_id, response_by_label,
                       recipient_user_id, direction
                FROM admin_messages
                WHERE (
                    direction = 'user_to_admin' AND sender_user_id = ?
                ) OR (
                    direction = 'admin_to_user' AND recipient_user_id = ?
                )
                ORDER BY id DESC
                LIMIT ?;
                """,
                (int(user_id), int(user_id), int(limit)),
            ).fetchall()
        return [
            AdminMessageRecord(
                id=int(row[0]),
                created_at=str(row[1]),
                sender_user_id=int(row[2]) if row[2] is not None else None,
                sender_label=str(row[3]) if row[3] is not None else None,
                message=str(row[4]),
                status=str(row[5]),
                response_message=str(row[6]) if row[6] is not None else None,
                response_created_at=str(row[7]) if row[7] is not None else None,
                response_by_user_id=int(row[8]) if row[8] is not None else None,
                response_by_label=str(row[9]) if row[9] is not None else None,
                recipient_user_id=int(row[10]) if row[10] is not None else None,
                direction=str(row[11]) if row[11] is not None else "user_to_admin",
            )
            for row in rows
        ]

    async def list_admin_messages_for_user(self, *, user_id: int, limit: int = 50) -> List[AdminMessageRecord]:
        return await anyio.to_thread.run_sync(self._list_messages_for_user_sync, int(user_id), int(limit))
