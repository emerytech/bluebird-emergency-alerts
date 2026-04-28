from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import anyio

logger = logging.getLogger("bluebird.audit")


@dataclass(frozen=True)
class AuditEventRecord:
    id: int
    tenant_slug: str
    timestamp: str
    event_type: str
    actor_user_id: Optional[int]
    actor_label: Optional[str]
    target_type: Optional[str]
    target_id: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


class AuditLogService:
    """
    Append-only per-tenant audit log. Shares the same SQLite DB file as other
    tenant services. All writes run in a thread executor and are fail-safe —
    a write failure never surfaces to the caller.
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
                CREATE TABLE IF NOT EXISTS audit_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_slug TEXT    NOT NULL,
                    timestamp   TEXT    NOT NULL,
                    event_type  TEXT    NOT NULL,
                    actor_user_id INTEGER NULL,
                    actor_label TEXT    NULL,
                    target_type TEXT    NULL,
                    target_id   TEXT    NULL,
                    metadata    TEXT    NOT NULL DEFAULT '{}'
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp  ON audit_log(timestamp);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_slug ON audit_log(tenant_slug);"
            )

    def _log_event_sync(
        self,
        tenant_slug: str,
        timestamp: str,
        event_type: str,
        actor_user_id: Optional[int],
        actor_label: Optional[str],
        target_type: Optional[str],
        target_id: Optional[str],
        metadata_json: str,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO audit_log
                    (tenant_slug, timestamp, event_type, actor_user_id, actor_label,
                     target_type, target_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    tenant_slug,
                    timestamp,
                    event_type,
                    actor_user_id,
                    actor_label,
                    target_type,
                    target_id,
                    metadata_json,
                ),
            )
            return int(cur.lastrowid)

    async def log_event(
        self,
        *,
        tenant_slug: str,
        event_type: str,
        actor_user_id: Optional[int] = None,
        actor_label: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        timestamp = datetime.now(timezone.utc).isoformat()
        safe_metadata: Dict[str, Any] = {}
        if metadata:
            for k, v in metadata.items():
                try:
                    json.dumps(v)
                    safe_metadata[k] = v
                except (TypeError, ValueError):
                    safe_metadata[k] = str(v)
        metadata_json = json.dumps(safe_metadata)
        return await anyio.to_thread.run_sync(
            self._log_event_sync,
            str(tenant_slug),
            timestamp,
            str(event_type),
            actor_user_id,
            actor_label,
            target_type,
            target_id,
            metadata_json,
        )

    def _list_recent_sync(self, limit: int, event_type: Optional[str]) -> List[AuditEventRecord]:
        with self._connect() as conn:
            if event_type:
                rows = conn.execute(
                    """
                    SELECT id, tenant_slug, timestamp, event_type, actor_user_id,
                           actor_label, target_type, target_id, metadata
                    FROM audit_log
                    WHERE event_type = ?
                    ORDER BY id DESC LIMIT ?;
                    """,
                    (event_type, max(1, limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, tenant_slug, timestamp, event_type, actor_user_id,
                           actor_label, target_type, target_id, metadata
                    FROM audit_log
                    ORDER BY id DESC LIMIT ?;
                    """,
                    (max(1, limit),),
                ).fetchall()
        records = []
        for row in rows:
            try:
                meta = json.loads(row[8]) if row[8] else {}
            except (ValueError, TypeError):
                meta = {}
            records.append(
                AuditEventRecord(
                    id=int(row[0]),
                    tenant_slug=str(row[1]),
                    timestamp=str(row[2]),
                    event_type=str(row[3]),
                    actor_user_id=int(row[4]) if row[4] is not None else None,
                    actor_label=str(row[5]) if row[5] is not None else None,
                    target_type=str(row[6]) if row[6] is not None else None,
                    target_id=str(row[7]) if row[7] is not None else None,
                    metadata=meta,
                )
            )
        return records

    async def list_recent(
        self,
        limit: int = 100,
        event_type: Optional[str] = None,
    ) -> List[AuditEventRecord]:
        return await anyio.to_thread.run_sync(
            self._list_recent_sync, int(limit), event_type or None
        )

    def _list_by_user_id_sync(self, user_id: int, limit: int) -> List[AuditEventRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, tenant_slug, timestamp, event_type, actor_user_id,
                       actor_label, target_type, target_id, metadata
                FROM audit_log
                WHERE (target_type = 'user' AND target_id = ?)
                   OR actor_user_id = ?
                ORDER BY id DESC LIMIT ?;
                """,
                (str(user_id), int(user_id), max(1, limit)),
            ).fetchall()
        records = []
        for row in rows:
            try:
                meta = json.loads(row[8]) if row[8] else {}
            except (ValueError, TypeError):
                meta = {}
            records.append(
                AuditEventRecord(
                    id=int(row[0]),
                    tenant_slug=str(row[1]),
                    timestamp=str(row[2]),
                    event_type=str(row[3]),
                    actor_user_id=int(row[4]) if row[4] is not None else None,
                    actor_label=str(row[5]) if row[5] is not None else None,
                    target_type=str(row[6]) if row[6] is not None else None,
                    target_id=str(row[7]) if row[7] is not None else None,
                    metadata=meta,
                )
            )
        return records

    async def list_by_user_id(self, user_id: int, limit: int = 50) -> List[AuditEventRecord]:
        return await anyio.to_thread.run_sync(
            self._list_by_user_id_sync, int(user_id), int(limit)
        )

    async def distinct_event_types(self) -> List[str]:
        def _sync() -> List[str]:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT event_type FROM audit_log ORDER BY event_type;"
                ).fetchall()
            return [str(row[0]) for row in rows]
        return await anyio.to_thread.run_sync(_sync)
