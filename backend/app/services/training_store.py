from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import anyio

_ALL_GUIDE_IDS = {
    "initiate_emergency",
    "view_messages",
    "team_assist",
    "account_for_yourself",
    "account_for_students",
    "reunification",
}

_VALID_EVENTS = {
    "guide_started",
    "step_completed",
    "guide_completed",
    "walkthrough_started",
    "walkthrough_completed",
}


@dataclass(frozen=True)
class TrainingEvent:
    id: int
    user_id: int
    tenant_slug: str
    event_type: str
    guide_id: Optional[str]
    step: Optional[int]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "tenant_slug": self.tenant_slug,
            "event_type": self.event_type,
            "guide_id": self.guide_id,
            "step": self.step,
            "created_at": self.created_at,
        }


@dataclass
class UserTrainingProgress:
    user_id: int
    tenant_slug: str
    completed_guides: list[str] = field(default_factory=list)
    last_activity: Optional[str] = None

    @property
    def completion_percentage(self) -> float:
        if not _ALL_GUIDE_IDS:
            return 0.0
        return round(len(self.completed_guides) / len(_ALL_GUIDE_IDS) * 100, 1)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "tenant_slug": self.tenant_slug,
            "completed_guides": self.completed_guides,
            "completion_percentage": self.completion_percentage,
            "guides_completed": len(self.completed_guides),
            "guides_total": len(_ALL_GUIDE_IDS),
            "last_activity": self.last_activity,
        }


class TrainingStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS platform_training_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    tenant_slug TEXT    NOT NULL,
                    event_type  TEXT    NOT NULL,
                    guide_id    TEXT,
                    step        INTEGER,
                    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_training_user ON platform_training_events(user_id, tenant_slug)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_training_tenant ON platform_training_events(tenant_slug, created_at DESC)"
            )

    def _record_event_sync(
        self,
        user_id: int,
        tenant_slug: str,
        event_type: str,
        guide_id: Optional[str],
        step: Optional[int],
    ) -> bool:
        if event_type not in _VALID_EVENTS:
            return False
        if guide_id is not None and guide_id not in _ALL_GUIDE_IDS:
            return False
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO platform_training_events
                    (user_id, tenant_slug, event_type, guide_id, step, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    tenant_slug,
                    event_type,
                    guide_id,
                    step,
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                ),
            )
        return True

    def _get_user_progress_sync(self, user_id: int, tenant_slug: str) -> UserTrainingProgress:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT guide_id, MAX(created_at) AS last_at
                FROM platform_training_events
                WHERE user_id=? AND tenant_slug=? AND event_type='guide_completed' AND guide_id IS NOT NULL
                GROUP BY guide_id
                """,
                (user_id, tenant_slug),
            ).fetchall()

            last_row = conn.execute(
                """
                SELECT created_at FROM platform_training_events
                WHERE user_id=? AND tenant_slug=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, tenant_slug),
            ).fetchone()

        completed = [r["guide_id"] for r in rows]
        last_activity = last_row["created_at"] if last_row else None
        return UserTrainingProgress(
            user_id=user_id,
            tenant_slug=tenant_slug,
            completed_guides=completed,
            last_activity=last_activity,
        )

    def _list_tenant_progress_sync(self, tenant_slug: str) -> list[UserTrainingProgress]:
        with self._lock, self._connect() as conn:
            user_rows = conn.execute(
                "SELECT DISTINCT user_id FROM platform_training_events WHERE tenant_slug=?",
                (tenant_slug,),
            ).fetchall()

        return [
            self._get_user_progress_sync(r["user_id"], tenant_slug)
            for r in user_rows
        ]

    # ── Async wrappers ────────────────────────────────────────────────────────

    async def record_event(
        self,
        user_id: int,
        tenant_slug: str,
        event_type: str,
        guide_id: Optional[str] = None,
        step: Optional[int] = None,
    ) -> bool:
        return await anyio.to_thread.run_sync(
            lambda: self._record_event_sync(user_id, tenant_slug, event_type, guide_id, step)
        )

    async def get_user_progress(self, user_id: int, tenant_slug: str) -> UserTrainingProgress:
        return await anyio.to_thread.run_sync(
            lambda: self._get_user_progress_sync(user_id, tenant_slug)
        )

    async def list_tenant_progress(self, tenant_slug: str) -> list[UserTrainingProgress]:
        return await anyio.to_thread.run_sync(
            lambda: self._list_tenant_progress_sync(tenant_slug)
        )
