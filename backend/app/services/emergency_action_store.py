from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import anyio

from app.core.db import optimized_connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Records
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UserLocationRecord:
    id: int
    user_id: int
    incident_id: int
    latitude: float
    longitude: float
    accuracy: Optional[float]
    created_at: str


@dataclass(frozen=True)
class AnalyticsEventRecord:
    id: int
    user_id: Optional[int]
    incident_id: Optional[int]
    event_type: str
    metadata: Optional[str]
    created_at: str


# ─────────────────────────────────────────────────────────────────────────────
# Store
# ─────────────────────────────────────────────────────────────────────────────

class EmergencyActionStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = optimized_connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS user_locations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    incident_id INTEGER NOT NULL,
                    latitude    REAL    NOT NULL,
                    longitude   REAL    NOT NULL,
                    accuracy    REAL    NULL,
                    created_at  TEXT    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_user_locations_incident
                    ON user_locations(incident_id);
                CREATE INDEX IF NOT EXISTS idx_user_locations_user
                    ON user_locations(user_id, incident_id);

                CREATE TABLE IF NOT EXISTS analytics_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NULL,
                    incident_id INTEGER NULL,
                    event_type  TEXT    NOT NULL,
                    metadata    TEXT    NULL,
                    created_at  TEXT    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analytics_events_incident
                    ON analytics_events(incident_id);
                CREATE INDEX IF NOT EXISTS idx_analytics_events_type
                    ON analytics_events(event_type, created_at);
            """)

    # ── Locations ─────────────────────────────────────────────────────────────

    def _record_location_sync(
        self,
        user_id: int,
        incident_id: int,
        latitude: float,
        longitude: float,
        accuracy: Optional[float],
    ) -> UserLocationRecord:
        ts = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO user_locations (user_id, incident_id, latitude, longitude, accuracy, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?);",
                (user_id, incident_id, latitude, longitude, accuracy, ts),
            )
            row = conn.execute(
                "SELECT id, user_id, incident_id, latitude, longitude, accuracy, created_at "
                "FROM user_locations WHERE id = ?;",
                (int(cur.lastrowid),),
            ).fetchone()
        return UserLocationRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            incident_id=int(row["incident_id"]),
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            accuracy=float(row["accuracy"]) if row["accuracy"] is not None else None,
            created_at=str(row["created_at"]),
        )

    async def record_location(
        self,
        *,
        user_id: int,
        incident_id: int,
        latitude: float,
        longitude: float,
        accuracy: Optional[float] = None,
    ) -> UserLocationRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._record_location_sync(user_id, incident_id, latitude, longitude, accuracy)
        )

    def _list_locations_for_incident_sync(self, incident_id: int) -> list[UserLocationRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT l.id, l.user_id, l.incident_id, l.latitude, l.longitude, l.accuracy, l.created_at
                FROM user_locations l
                INNER JOIN (
                    SELECT user_id, MAX(id) AS max_id
                    FROM user_locations
                    WHERE incident_id = ?
                    GROUP BY user_id
                ) latest ON l.id = latest.max_id
                ORDER BY l.created_at DESC;
                """,
                (incident_id,),
            ).fetchall()
        return [
            UserLocationRecord(
                id=int(r["id"]),
                user_id=int(r["user_id"]),
                incident_id=int(r["incident_id"]),
                latitude=float(r["latitude"]),
                longitude=float(r["longitude"]),
                accuracy=float(r["accuracy"]) if r["accuracy"] is not None else None,
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]

    async def list_locations_for_incident(self, incident_id: int) -> list[UserLocationRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._list_locations_for_incident_sync(incident_id)
        )

    def _location_count_for_incident_sync(self, incident_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM user_locations WHERE incident_id = ?;",
                (incident_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    async def location_count_for_incident(self, incident_id: int) -> int:
        return await anyio.to_thread.run_sync(
            lambda: self._location_count_for_incident_sync(incident_id)
        )

    # ── Analytics Events ──────────────────────────────────────────────────────

    def _record_event_sync(
        self,
        event_type: str,
        user_id: Optional[int] = None,
        incident_id: Optional[int] = None,
        metadata: Optional[str] = None,
    ) -> AnalyticsEventRecord:
        ts = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO analytics_events (user_id, incident_id, event_type, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?);",
                (user_id, incident_id, event_type, metadata, ts),
            )
            row = conn.execute(
                "SELECT id, user_id, incident_id, event_type, metadata, created_at "
                "FROM analytics_events WHERE id = ?;",
                (int(cur.lastrowid),),
            ).fetchone()
        return AnalyticsEventRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]) if row["user_id"] is not None else None,
            incident_id=int(row["incident_id"]) if row["incident_id"] is not None else None,
            event_type=str(row["event_type"]),
            metadata=str(row["metadata"]) if row["metadata"] is not None else None,
            created_at=str(row["created_at"]),
        )

    async def record_event(
        self,
        *,
        event_type: str,
        user_id: Optional[int] = None,
        incident_id: Optional[int] = None,
        metadata: Optional[str] = None,
    ) -> AnalyticsEventRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._record_event_sync(event_type, user_id, incident_id, metadata)
        )

    def _events_for_incident_sync(self, incident_id: int) -> list[AnalyticsEventRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, user_id, incident_id, event_type, metadata, created_at "
                "FROM analytics_events WHERE incident_id = ? ORDER BY created_at ASC;",
                (incident_id,),
            ).fetchall()
        return [
            AnalyticsEventRecord(
                id=int(r["id"]),
                user_id=int(r["user_id"]) if r["user_id"] is not None else None,
                incident_id=int(r["incident_id"]) if r["incident_id"] is not None else None,
                event_type=str(r["event_type"]),
                metadata=str(r["metadata"]) if r["metadata"] is not None else None,
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]

    async def events_for_incident(self, incident_id: int) -> list[AnalyticsEventRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._events_for_incident_sync(incident_id)
        )

    def _event_summary_for_incident_sync(self, incident_id: int) -> dict:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_type, COUNT(*) as cnt FROM analytics_events "
                "WHERE incident_id = ? GROUP BY event_type;",
                (incident_id,),
            ).fetchall()
            loc_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM user_locations WHERE incident_id = ?;",
                (incident_id,),
            ).fetchone()
            loc_total = conn.execute(
                "SELECT COUNT(*) FROM user_locations WHERE incident_id = ?;",
                (incident_id,),
            ).fetchone()
            first_loc = conn.execute(
                "SELECT created_at FROM user_locations WHERE incident_id = ? ORDER BY id ASC LIMIT 1;",
                (incident_id,),
            ).fetchone()
        counts: dict[str, int] = {str(r["event_type"]): int(r["cnt"]) for r in rows}
        return {
            "location_shares_users": int(loc_users[0]) if loc_users else 0,
            "location_shares_total": int(loc_total[0]) if loc_total else 0,
            "first_location_at": str(first_loc["created_at"]) if first_loc else None,
            "call_911_initiated": counts.get("call_911_initiated", 0),
            "call_911_confirmed": counts.get("call_911_confirmed", 0),
            "call_911_cancelled": counts.get("call_911_cancelled", 0),
            "location_auto_shared": counts.get("location_auto_shared", 0),
        }

    async def event_summary_for_incident(self, incident_id: int) -> dict:
        return await anyio.to_thread.run_sync(
            lambda: self._event_summary_for_incident_sync(incident_id)
        )
