from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import anyio


@dataclass(frozen=True)
class SettingsChangeRecord:
    id: int
    field: str
    old_value: Dict[str, Any]
    new_value: Dict[str, Any]
    changed_at: str
    changed_by_label: Optional[str]
    is_undone: bool


class TenantSettingsStore:
    """
    Per-tenant settings change history in the tenant DB.
    Supports undo: each write records before/after snapshots so any change can be rolled back.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=30, isolation_level=None)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_settings_history (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    field            TEXT    NOT NULL,
                    old_value        TEXT    NOT NULL DEFAULT '{}',
                    new_value        TEXT    NOT NULL DEFAULT '{}',
                    changed_at       TEXT    NOT NULL,
                    changed_by_label TEXT    NULL,
                    is_undone        INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_settings_history_field ON tenant_settings_history(field);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_settings_history_changed_at ON tenant_settings_history(changed_at);"
            )

    @staticmethod
    def _row_to_record(row: tuple) -> SettingsChangeRecord:
        try:
            old = json.loads(row[2]) if row[2] else {}
        except (ValueError, TypeError):
            old = {}
        try:
            new = json.loads(row[3]) if row[3] else {}
        except (ValueError, TypeError):
            new = {}
        return SettingsChangeRecord(
            id=int(row[0]),
            field=str(row[1]),
            old_value=old,
            new_value=new,
            changed_at=str(row[4]),
            changed_by_label=str(row[5]) if row[5] is not None else None,
            is_undone=bool(int(row[6])),
        )

    def _record_change_sync(
        self,
        field: str,
        old_value: Dict[str, Any],
        new_value: Dict[str, Any],
        changed_by_label: Optional[str],
    ) -> int:
        changed_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO tenant_settings_history
                    (field, old_value, new_value, changed_at, changed_by_label, is_undone)
                VALUES (?, ?, ?, ?, ?, 0);
                """,
                (
                    field,
                    json.dumps(old_value),
                    json.dumps(new_value),
                    changed_at,
                    changed_by_label,
                ),
            )
            return int(cur.lastrowid)

    async def record_change(
        self,
        *,
        field: str,
        old_value: Dict[str, Any],
        new_value: Dict[str, Any],
        changed_by_label: Optional[str] = None,
    ) -> int:
        return await anyio.to_thread.run_sync(
            self._record_change_sync, field, old_value, new_value, changed_by_label
        )

    def _get_history_sync(self, limit: int) -> List[SettingsChangeRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, field, old_value, new_value, changed_at, changed_by_label, is_undone
                FROM tenant_settings_history
                ORDER BY id DESC LIMIT ?;
                """,
                (max(1, limit),),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    async def get_history(self, limit: int = 50) -> List[SettingsChangeRecord]:
        return await anyio.to_thread.run_sync(self._get_history_sync, int(limit))

    def _get_last_undoable_sync(self, field: str) -> Optional[SettingsChangeRecord]:
        """Return the most recent non-undone change for the given field."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, field, old_value, new_value, changed_at, changed_by_label, is_undone
                FROM tenant_settings_history
                WHERE field = ? AND is_undone = 0
                ORDER BY id DESC LIMIT 1;
                """,
                (field,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def get_last_undoable(self, field: str) -> Optional[SettingsChangeRecord]:
        return await anyio.to_thread.run_sync(self._get_last_undoable_sync, field)

    def _get_by_id_sync(self, change_id: int) -> Optional[SettingsChangeRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, field, old_value, new_value, changed_at, changed_by_label, is_undone
                FROM tenant_settings_history WHERE id = ? LIMIT 1;
                """,
                (int(change_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def get_by_id(self, change_id: int) -> Optional[SettingsChangeRecord]:
        return await anyio.to_thread.run_sync(self._get_by_id_sync, int(change_id))

    def _mark_undone_sync(self, change_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE tenant_settings_history SET is_undone = 1 WHERE id = ? AND is_undone = 0;",
                (int(change_id),),
            )
            return cur.rowcount > 0

    async def mark_undone(self, change_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._mark_undone_sync, int(change_id))
