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
    acted_by_user_id: Optional[int]
    acted_by_label: Optional[str]
    forward_to_user_id: Optional[int]
    forward_to_label: Optional[str]
    cancel_requester_confirmed_at: Optional[str]
    cancel_admin_confirmed_at: Optional[str]
    cancel_admin_user_id: Optional[int]
    cancel_admin_label: Optional[str]
    # requester-initiated cancel fields
    cancelled_by_user_id: Optional[int] = None
    cancelled_at: Optional[str] = None
    cancel_reason_text: Optional[str] = None
    cancel_reason_category: Optional[str] = None


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
            self._migrate_incidents_table(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_incidents_school_id ON incidents(school_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_incidents_created_at ON incidents(created_at);"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS team_assists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    created_by INTEGER NOT NULL,
                    assigned_team_ids_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    acted_by_user_id INTEGER NULL,
                    acted_by_label TEXT NULL,
                    forward_to_user_id INTEGER NULL,
                    forward_to_label TEXT NULL,
                    cancel_requester_confirmed_at TEXT NULL,
                    cancel_admin_confirmed_at TEXT NULL,
                    cancel_admin_user_id INTEGER NULL,
                    cancel_admin_label TEXT NULL
                );
                """
            )
            self._migrate_team_assists_table(conn)
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

    def _migrate_incidents_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(incidents);").fetchall()}
        if "target_scope" not in cols:
            conn.execute("ALTER TABLE incidents ADD COLUMN target_scope TEXT NULL;")
            conn.execute("UPDATE incidents SET target_scope = 'ALL' WHERE target_scope IS NULL OR trim(target_scope) = '';")
        if "metadata_json" not in cols:
            conn.execute("ALTER TABLE incidents ADD COLUMN metadata_json TEXT NULL;")
            conn.execute("UPDATE incidents SET metadata_json = '{}' WHERE metadata_json IS NULL OR trim(metadata_json) = '';")

    def _migrate_team_assists_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(team_assists);").fetchall()}
        if "acted_by_user_id" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN acted_by_user_id INTEGER NULL;")
        if "acted_by_label" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN acted_by_label TEXT NULL;")
        if "forward_to_user_id" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN forward_to_user_id INTEGER NULL;")
        if "forward_to_label" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN forward_to_label TEXT NULL;")
        if "cancel_requester_confirmed_at" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN cancel_requester_confirmed_at TEXT NULL;")
        if "cancel_admin_confirmed_at" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN cancel_admin_confirmed_at TEXT NULL;")
        if "cancel_admin_user_id" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN cancel_admin_user_id INTEGER NULL;")
        if "cancel_admin_label" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN cancel_admin_label TEXT NULL;")
        if "cancelled_by_user_id" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN cancelled_by_user_id INTEGER NULL;")
        if "cancelled_at" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN cancelled_at TEXT NULL;")
        if "cancel_reason_text" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN cancel_reason_text TEXT NULL;")
        if "cancel_reason_category" not in cols:
            conn.execute("ALTER TABLE team_assists ADD COLUMN cancel_reason_category TEXT NULL;")

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
        incidents: list[IncidentRecord] = []
        for row in rows:
            metadata_raw = str(row[7]) if row[7] is not None else "{}"
            try:
                metadata = json.loads(metadata_raw)
            except Exception:
                metadata = {}
            incidents.append(
                IncidentRecord(
                    id=int(row[0]),
                    type=str(row[1]),
                    status=str(row[2]),
                    created_by=int(row[3]) if row[3] is not None else 0,
                    school_id=str(row[4]),
                    created_at=str(row[5]),
                    target_scope=str(row[6] or "ALL"),
                    metadata=metadata if isinstance(metadata, dict) else {},
                )
            )
        return incidents

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
                SELECT
                    id,
                    type,
                    created_by,
                    assigned_team_ids_json,
                    status,
                    created_at,
                    acted_by_user_id,
                    acted_by_label,
                    forward_to_user_id,
                    forward_to_label,
                    cancel_requester_confirmed_at,
                    cancel_admin_confirmed_at,
                    cancel_admin_user_id,
                    cancel_admin_label,
                    cancelled_by_user_id,
                    cancelled_at,
                    cancel_reason_text,
                    cancel_reason_category
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
            acted_by_user_id=int(row[6]) if row[6] is not None else None,
            acted_by_label=str(row[7]) if row[7] is not None else None,
            forward_to_user_id=int(row[8]) if row[8] is not None else None,
            forward_to_label=str(row[9]) if row[9] is not None else None,
            cancel_requester_confirmed_at=str(row[10]) if row[10] is not None else None,
            cancel_admin_confirmed_at=str(row[11]) if row[11] is not None else None,
            cancel_admin_user_id=int(row[12]) if row[12] is not None else None,
            cancel_admin_label=str(row[13]) if row[13] is not None else None,
            cancelled_by_user_id=int(row[14]) if row[14] is not None else None,
            cancelled_at=str(row[15]) if row[15] is not None else None,
            cancel_reason_text=str(row[16]) if row[16] is not None else None,
            cancel_reason_category=str(row[17]) if row[17] is not None else None,
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
                SELECT
                    id,
                    type,
                    created_by,
                    assigned_team_ids_json,
                    status,
                    created_at,
                    acted_by_user_id,
                    acted_by_label,
                    forward_to_user_id,
                    forward_to_label,
                    cancel_requester_confirmed_at,
                    cancel_admin_confirmed_at,
                    cancel_admin_user_id,
                    cancel_admin_label,
                    cancelled_by_user_id,
                    cancelled_at,
                    cancel_reason_text,
                    cancel_reason_category
                FROM team_assists
                WHERE status NOT IN ('cancelled', 'resolved')
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
                acted_by_user_id=int(row[6]) if row[6] is not None else None,
                acted_by_label=str(row[7]) if row[7] is not None else None,
                forward_to_user_id=int(row[8]) if row[8] is not None else None,
                forward_to_label=str(row[9]) if row[9] is not None else None,
                cancel_requester_confirmed_at=str(row[10]) if row[10] is not None else None,
                cancel_admin_confirmed_at=str(row[11]) if row[11] is not None else None,
                cancel_admin_user_id=int(row[12]) if row[12] is not None else None,
                cancel_admin_label=str(row[13]) if row[13] is not None else None,
                cancelled_by_user_id=int(row[14]) if row[14] is not None else None,
                cancelled_at=str(row[15]) if row[15] is not None else None,
                cancel_reason_text=str(row[16]) if row[16] is not None else None,
                cancel_reason_category=str(row[17]) if row[17] is not None else None,
            )
            for row in rows
        ]

    async def list_active_team_assists(self, *, limit: int = 50) -> List[TeamAssistRecord]:
        return await anyio.to_thread.run_sync(self._list_active_team_assists_sync, int(limit))

    def _team_assist_from_row(self, row: tuple[Any, ...]) -> TeamAssistRecord:
        return TeamAssistRecord(
            id=int(row[0]),
            type=str(row[1]),
            created_by=int(row[2]),
            assigned_team_ids=[int(item) for item in json.loads(str(row[3]) or "[]")],
            status=str(row[4]),
            created_at=str(row[5]),
            acted_by_user_id=int(row[6]) if row[6] is not None else None,
            acted_by_label=str(row[7]) if row[7] is not None else None,
            forward_to_user_id=int(row[8]) if row[8] is not None else None,
            forward_to_label=str(row[9]) if row[9] is not None else None,
            cancel_requester_confirmed_at=str(row[10]) if row[10] is not None else None,
            cancel_admin_confirmed_at=str(row[11]) if row[11] is not None else None,
            cancel_admin_user_id=int(row[12]) if row[12] is not None else None,
            cancel_admin_label=str(row[13]) if row[13] is not None else None,
            cancelled_by_user_id=int(row[14]) if row[14] is not None else None,
            cancelled_at=str(row[15]) if row[15] is not None else None,
            cancel_reason_text=str(row[16]) if row[16] is not None else None,
            cancel_reason_category=str(row[17]) if row[17] is not None else None,
        )

    def _get_team_assist_sync(self, team_assist_id: int) -> Optional[TeamAssistRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id,
                    type,
                    created_by,
                    assigned_team_ids_json,
                    status,
                    created_at,
                    acted_by_user_id,
                    acted_by_label,
                    forward_to_user_id,
                    forward_to_label,
                    cancel_requester_confirmed_at,
                    cancel_admin_confirmed_at,
                    cancel_admin_user_id,
                    cancel_admin_label,
                    cancelled_by_user_id,
                    cancelled_at,
                    cancel_reason_text,
                    cancel_reason_category
                FROM team_assists
                WHERE id = ?
                LIMIT 1;
                """,
                (int(team_assist_id),),
            ).fetchone()
        if row is None:
            return None
        return self._team_assist_from_row(row)

    async def get_team_assist(self, team_assist_id: int) -> Optional[TeamAssistRecord]:
        return await anyio.to_thread.run_sync(self._get_team_assist_sync, int(team_assist_id))

    def _update_team_assist_action_sync(
        self,
        *,
        team_assist_id: int,
        status: str,
        acted_by_user_id: int,
        acted_by_label: str,
        forward_to_user_id: Optional[int],
        forward_to_label: Optional[str],
    ) -> Optional[TeamAssistRecord]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE team_assists
                SET
                    status = ?,
                    acted_by_user_id = ?,
                    acted_by_label = ?,
                    forward_to_user_id = ?,
                    forward_to_label = ?
                WHERE id = ?;
                """,
                (
                    status,
                    int(acted_by_user_id),
                    acted_by_label,
                    int(forward_to_user_id) if forward_to_user_id is not None else None,
                    forward_to_label,
                    int(team_assist_id),
                ),
            )
            if cur.rowcount <= 0:
                return None
            row = conn.execute(
                """
                SELECT
                    id,
                    type,
                    created_by,
                    assigned_team_ids_json,
                    status,
                    created_at,
                    acted_by_user_id,
                    acted_by_label,
                    forward_to_user_id,
                    forward_to_label,
                    cancel_requester_confirmed_at,
                    cancel_admin_confirmed_at,
                    cancel_admin_user_id,
                    cancel_admin_label,
                    cancelled_by_user_id,
                    cancelled_at,
                    cancel_reason_text,
                    cancel_reason_category
                FROM team_assists
                WHERE id = ?
                LIMIT 1;
                """,
                (int(team_assist_id),),
            ).fetchone()
        if row is None:
            return None
        return self._team_assist_from_row(row)

    async def update_team_assist_action(
        self,
        *,
        team_assist_id: int,
        status: str,
        acted_by_user_id: int,
        acted_by_label: str,
        forward_to_user_id: Optional[int],
        forward_to_label: Optional[str],
    ) -> Optional[TeamAssistRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._update_team_assist_action_sync(
                team_assist_id=int(team_assist_id),
                status=status,
                acted_by_user_id=int(acted_by_user_id),
                acted_by_label=acted_by_label,
                forward_to_user_id=int(forward_to_user_id) if forward_to_user_id is not None else None,
                forward_to_label=forward_to_label,
            )
        )

    def _confirm_team_assist_cancel_sync(
        self,
        *,
        team_assist_id: int,
        actor_user_id: int,
        actor_role: str,
        actor_label: str,
    ) -> Optional[TeamAssistRecord]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id,
                    type,
                    created_by,
                    assigned_team_ids_json,
                    status,
                    created_at,
                    acted_by_user_id,
                    acted_by_label,
                    forward_to_user_id,
                    forward_to_label,
                    cancel_requester_confirmed_at,
                    cancel_admin_confirmed_at,
                    cancel_admin_user_id,
                    cancel_admin_label,
                    cancelled_by_user_id,
                    cancelled_at,
                    cancel_reason_text,
                    cancel_reason_category
                FROM team_assists
                WHERE id = ?
                LIMIT 1;
                """,
                (int(team_assist_id),),
            ).fetchone()
            if row is None:
                return None
            current = self._team_assist_from_row(row)
            requester_confirmed_at = current.cancel_requester_confirmed_at
            admin_confirmed_at = current.cancel_admin_confirmed_at
            admin_user_id = current.cancel_admin_user_id
            admin_label = current.cancel_admin_label

            if int(actor_user_id) == int(current.created_by):
                requester_confirmed_at = requester_confirmed_at or now
            if actor_role.lower() == "admin" and int(actor_user_id) != int(current.created_by):
                admin_confirmed_at = admin_confirmed_at or now
                admin_user_id = int(actor_user_id)
                admin_label = actor_label

            next_status = "cancelled" if requester_confirmed_at and admin_confirmed_at else "cancel_pending"
            conn.execute(
                """
                UPDATE team_assists
                SET
                    status = ?,
                    cancel_requester_confirmed_at = ?,
                    cancel_admin_confirmed_at = ?,
                    cancel_admin_user_id = ?,
                    cancel_admin_label = ?,
                    acted_by_user_id = ?,
                    acted_by_label = ?
                WHERE id = ?;
                """,
                (
                    next_status,
                    requester_confirmed_at,
                    admin_confirmed_at,
                    int(admin_user_id) if admin_user_id is not None else None,
                    admin_label,
                    int(actor_user_id),
                    actor_label,
                    int(team_assist_id),
                ),
            )
            updated_row = conn.execute(
                """
                SELECT
                    id,
                    type,
                    created_by,
                    assigned_team_ids_json,
                    status,
                    created_at,
                    acted_by_user_id,
                    acted_by_label,
                    forward_to_user_id,
                    forward_to_label,
                    cancel_requester_confirmed_at,
                    cancel_admin_confirmed_at,
                    cancel_admin_user_id,
                    cancel_admin_label,
                    cancelled_by_user_id,
                    cancelled_at,
                    cancel_reason_text,
                    cancel_reason_category
                FROM team_assists
                WHERE id = ?
                LIMIT 1;
                """,
                (int(team_assist_id),),
            ).fetchone()
        if updated_row is None:
            return None
        return self._team_assist_from_row(updated_row)

    async def confirm_team_assist_cancel(
        self,
        *,
        team_assist_id: int,
        actor_user_id: int,
        actor_role: str,
        actor_label: str,
    ) -> Optional[TeamAssistRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._confirm_team_assist_cancel_sync(
                team_assist_id=int(team_assist_id),
                actor_user_id=int(actor_user_id),
                actor_role=actor_role,
                actor_label=actor_label,
            )
        )

    def _cancel_team_assist_sync(
        self,
        *,
        team_assist_id: int,
        cancelled_by_user_id: int,
        cancel_reason_text: str,
        cancel_reason_category: str,
    ) -> Optional[TeamAssistRecord]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE team_assists
                SET
                    status = 'cancelled',
                    cancelled_by_user_id = ?,
                    cancelled_at = ?,
                    cancel_reason_text = ?,
                    cancel_reason_category = ?,
                    acted_by_user_id = ?,
                    acted_by_label = NULL
                WHERE id = ? AND status NOT IN ('cancelled', 'resolved');
                """,
                (
                    int(cancelled_by_user_id),
                    now,
                    cancel_reason_text,
                    cancel_reason_category,
                    int(cancelled_by_user_id),
                    int(team_assist_id),
                ),
            )
            if cur.rowcount <= 0:
                return None
            row = conn.execute(
                """
                SELECT
                    id,
                    type,
                    created_by,
                    assigned_team_ids_json,
                    status,
                    created_at,
                    acted_by_user_id,
                    acted_by_label,
                    forward_to_user_id,
                    forward_to_label,
                    cancel_requester_confirmed_at,
                    cancel_admin_confirmed_at,
                    cancel_admin_user_id,
                    cancel_admin_label,
                    cancelled_by_user_id,
                    cancelled_at,
                    cancel_reason_text,
                    cancel_reason_category
                FROM team_assists
                WHERE id = ?
                LIMIT 1;
                """,
                (int(team_assist_id),),
            ).fetchone()
        return self._team_assist_from_row(row) if row is not None else None

    async def cancel_team_assist(
        self,
        *,
        team_assist_id: int,
        cancelled_by_user_id: int,
        cancel_reason_text: str,
        cancel_reason_category: str,
    ) -> Optional[TeamAssistRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._cancel_team_assist_sync(
                team_assist_id=int(team_assist_id),
                cancelled_by_user_id=int(cancelled_by_user_id),
                cancel_reason_text=cancel_reason_text,
                cancel_reason_category=cancel_reason_category,
            )
        )

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
