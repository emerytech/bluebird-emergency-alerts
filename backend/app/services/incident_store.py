from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional

import anyio


@dataclass(frozen=True)
class IncidentRecord:
    id: int
    type: str
    status: str
    created_by: int
    school_id: str
    created_at: str
    target_scope: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class TeamAssistRecord:
    id: int
    type: str
    created_by: int
    assigned_team_ids: list[int]
    status: str
    created_at: str


@dataclass(frozen=True)
class NotificationLogRecord:
    id: int
    user_id: Optional[int]
    type: str
    payload: dict[str, Any]
    timestamp: str


class IncidentStore:
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
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_by INTEGER NOT NULL,
                    school_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    target_scope TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS team_assists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    created_by INTEGER NOT NULL,
                    assigned_team_ids_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NULL,
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    timestamp TEXT NOT NULL
                );
                """
            )

    def _create_incident_sync(
        self,
        *,
        type_value: str,
        status: str,
        created_by: int,
        school_id: str,
        target_scope: str,
        metadata: dict[str, Any],
    ) -> IncidentRecord:
        created_at = datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {}, separators=(",", ":"), sort_keys=True)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO incidents (type, status, created_by, school_id, created_at, target_scope, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (type_value, status, int(created_by), school_id, created_at, target_scope, metadata_json),
            )
            row = conn.execute(
                """
                SELECT id, type, status, created_by, school_id, created_at, target_scope, metadata_json
                FROM incidents
                WHERE id = ?
                LIMIT 1;
                """,
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return IncidentRecord(
            id=int(row[0]),
            type=str(row[1]),
            status=str(row[2]),
            created_by=int(row[3]),
            school_id=str(row[4]),
            created_at=str(row[5]),
            target_scope=str(row[6]),
            metadata=json.loads(str(row[7]) or "{}"),
        )

    async def create_incident(
        self,
        *,
        type_value: str,
        status: str,
        created_by: int,
        school_id: str,
        target_scope: str,
        metadata: dict[str, Any],
    ) -> IncidentRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._create_incident_sync(
                type_value=type_value,
                status=status,
                created_by=int(created_by),
                school_id=school_id,
                target_scope=target_scope,
                metadata=metadata,
            )
        )

    def _list_active_incidents_sync(self, limit: int) -> List[IncidentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, type, status, created_by, school_id, created_at, target_scope, metadata_json
                FROM incidents
                WHERE status = 'active'
                ORDER BY id DESC
                LIMIT ?;
                """,
                (int(limit),),
            ).fetchall()
        return [
            IncidentRecord(
                id=int(row[0]),
                type=str(row[1]),
                status=str(row[2]),
                created_by=int(row[3]),
                school_id=str(row[4]),
                created_at=str(row[5]),
                target_scope=str(row[6]),
                metadata=json.loads(str(row[7]) or "{}"),
            )
            for row in rows
        ]

    async def list_active_incidents(self, *, limit: int = 50) -> List[IncidentRecord]:
        return await anyio.to_thread.run_sync(self._list_active_incidents_sync, int(limit))

    def _create_team_assist_sync(
        self,
        *,
        type_value: str,
        created_by: int,
        assigned_team_ids: list[int],
        status: str,
    ) -> TeamAssistRecord:
        created_at = datetime.now(timezone.utc).isoformat()
        assigned_json = json.dumps([int(item) for item in assigned_team_ids], separators=(",", ":"))
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO team_assists (type, created_by, assigned_team_ids_json, status, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (type_value, int(created_by), assigned_json, status, created_at),
            )
            row = conn.execute(
                """
                SELECT id, type, created_by, assigned_team_ids_json, status, created_at
                FROM team_assists
                WHERE id = ?
                LIMIT 1;
                """,
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return TeamAssistRecord(
            id=int(row[0]),
            type=str(row[1]),
            created_by=int(row[2]),
            assigned_team_ids=[int(item) for item in json.loads(str(row[3]) or "[]")],
            status=str(row[4]),
            created_at=str(row[5]),
        )

    async def create_team_assist(
        self,
        *,
        type_value: str,
        created_by: int,
        assigned_team_ids: list[int],
        status: str,
    ) -> TeamAssistRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._create_team_assist_sync(
                type_value=type_value,
                created_by=int(created_by),
                assigned_team_ids=assigned_team_ids,
                status=status,
            )
        )

    def _list_active_team_assists_sync(self, limit: int) -> List[TeamAssistRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, type, created_by, assigned_team_ids_json, status, created_at
                FROM team_assists
                WHERE status = 'active'
                ORDER BY id DESC
                LIMIT ?;
                """,
                (int(limit),),
            ).fetchall()
        return [
            TeamAssistRecord(
                id=int(row[0]),
                type=str(row[1]),
                created_by=int(row[2]),
                assigned_team_ids=[int(item) for item in json.loads(str(row[3]) or "[]")],
                status=str(row[4]),
                created_at=str(row[5]),
            )
            for row in rows
        ]

    async def list_active_team_assists(self, *, limit: int = 50) -> List[TeamAssistRecord]:
        return await anyio.to_thread.run_sync(self._list_active_team_assists_sync, int(limit))

    def _create_notification_log_sync(self, *, user_id: Optional[int], type_value: str, payload: dict[str, Any]) -> NotificationLogRecord:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload or {}, separators=(",", ":"), sort_keys=True)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO notification_logs (user_id, type, payload_json, timestamp)
                VALUES (?, ?, ?, ?);
                """,
                (int(user_id) if user_id is not None else None, type_value, payload_json, timestamp),
            )
            row = conn.execute(
                """
                SELECT id, user_id, type, payload_json, timestamp
                FROM notification_logs
                WHERE id = ?
                LIMIT 1;
                """,
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return NotificationLogRecord(
            id=int(row[0]),
            user_id=int(row[1]) if row[1] is not None else None,
            type=str(row[2]),
            payload=json.loads(str(row[3]) or "{}"),
            timestamp=str(row[4]),
        )

    async def create_notification_log(self, *, user_id: Optional[int], type_value: str, payload: dict[str, Any]) -> NotificationLogRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._create_notification_log_sync(
                user_id=int(user_id) if user_id is not None else None,
                type_value=type_value,
                payload=payload,
            )
        )

    def _list_notification_logs_sync(self, limit: int) -> List[NotificationLogRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, type, payload_json, timestamp
                FROM notification_logs
                ORDER BY id DESC
                LIMIT ?;
                """,
                (int(limit),),
            ).fetchall()
        return [
            NotificationLogRecord(
                id=int(row[0]),
                user_id=int(row[1]) if row[1] is not None else None,
                type=str(row[2]),
                payload=json.loads(str(row[3]) or "{}"),
                timestamp=str(row[4]),
            )
            for row in rows
        ]

    async def list_notification_logs(self, *, limit: int = 100) -> List[NotificationLogRecord]:
        return await anyio.to_thread.run_sync(self._list_notification_logs_sync, int(limit))
