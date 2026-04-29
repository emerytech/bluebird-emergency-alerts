from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import anyio

from app.services.tenant_settings import (
    TenantSettings,
    settings_from_dict,
    settings_to_dict,
    validate_settings_patch,
)


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
            # Canonical settings document — single row, key='settings'.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '{}'
                );
                """
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

    # -----------------------------------------------------------------------
    # Canonical settings document
    # -----------------------------------------------------------------------

    _SETTINGS_KEY = "settings"

    def _read_raw_settings_sync(self) -> dict:
        """Read the raw JSON blob from tenant_settings, or return {} if absent."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM tenant_settings WHERE key = ? LIMIT 1;",
                (self._SETTINGS_KEY,),
            ).fetchone()
        if row is None:
            return {}
        try:
            return json.loads(row[0]) or {}
        except (ValueError, TypeError):
            return {}

    def _write_raw_settings_sync(self, blob: dict) -> None:
        """Upsert the settings blob."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tenant_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value;
                """,
                (self._SETTINGS_KEY, json.dumps(blob)),
            )

    def _get_effective_settings_sync(self) -> TenantSettings:
        return settings_from_dict(self._read_raw_settings_sync())

    async def get_effective_settings(self) -> TenantSettings:
        """Return stored settings merged with defaults. Safe for all tenants."""
        return await anyio.to_thread.run_sync(self._get_effective_settings_sync)

    def _update_settings_sync(
        self,
        patch: dict,
        actor_label: Optional[str],
    ) -> tuple[TenantSettings, list[str]]:
        """
        Deep-merge `patch` into stored settings, write back, record history.

        Returns (new_effective_settings, validation_errors).
        If validation_errors is non-empty, nothing is written.
        """
        errors = validate_settings_patch(patch)
        if errors:
            return settings_from_dict(self._read_raw_settings_sync()), errors

        old_raw = self._read_raw_settings_sync()
        new_raw = _deep_merge(old_raw, patch)
        self._write_raw_settings_sync(new_raw)

        # Record to audit history (one entry per updated category)
        changed_at = datetime.now(timezone.utc).isoformat()
        for category, values in patch.items():
            if not isinstance(values, dict):
                continue
            old_cat = old_raw.get(category, {})
            new_cat = new_raw.get(category, {})
            changed_keys = {k for k in values if old_cat.get(k) != new_cat.get(k)}
            if not changed_keys:
                continue
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO tenant_settings_history
                        (field, old_value, new_value, changed_at, changed_by_label, is_undone)
                    VALUES (?, ?, ?, ?, ?, 0);
                    """,
                    (
                        f"settings.{category}",
                        json.dumps({k: old_cat.get(k) for k in changed_keys}),
                        json.dumps({k: new_cat.get(k) for k in changed_keys}),
                        changed_at,
                        actor_label,
                    ),
                )

        return settings_from_dict(new_raw), []

    async def update_settings(
        self,
        patch: dict,
        actor_label: Optional[str] = None,
    ) -> tuple[TenantSettings, list[str]]:
        """
        Apply a partial settings patch.

        Returns (effective_settings, errors).  If errors is non-empty the
        settings were not changed.
        """
        return await anyio.to_thread.run_sync(
            self._update_settings_sync, patch, actor_label
        )

    def _reset_to_defaults_sync(self, actor_label: Optional[str]) -> TenantSettings:
        old_raw = self._read_raw_settings_sync()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM tenant_settings WHERE key = ?;",
                (self._SETTINGS_KEY,),
            )
        if old_raw:
            changed_at = datetime.now(timezone.utc).isoformat()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO tenant_settings_history
                        (field, old_value, new_value, changed_at, changed_by_label, is_undone)
                    VALUES (?, ?, ?, ?, ?, 0);
                    """,
                    (
                        "settings.reset_to_defaults",
                        json.dumps(old_raw),
                        json.dumps({}),
                        changed_at,
                        actor_label,
                    ),
                )
        return TenantSettings()

    async def reset_to_defaults(self, actor_label: Optional[str] = None) -> TenantSettings:
        """Erase all stored settings and return to factory defaults."""
        return await anyio.to_thread.run_sync(self._reset_to_defaults_sync, actor_label)


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, patch: dict) -> dict:
    """
    Recursively merge `patch` into a copy of `base`.  Only known-category
    top-level keys are merged; others are preserved in `base` untouched.
    """
    result = dict(base)
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
