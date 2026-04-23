from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List


@dataclass(frozen=True)
class AlertRecord:
    id: int
    created_at: str
    message: str


class AlertLog:
    """
    Minimal SQLite alert log.

    Stores: created_at (UTC ISO-8601), message
    """

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
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    message TEXT NOT NULL
                );
                """
            )

    def log_alert(self, message: str) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO alerts (created_at, message) VALUES (?, ?);",
                (created_at, message),
            )
            return int(cur.lastrowid)

    def list_recent(self, limit: int = 20) -> List[AlertRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, message
                FROM alerts
                ORDER BY id DESC
                LIMIT ?;
                """,
                (max(1, limit),),
            ).fetchall()

        return [
            AlertRecord(
                id=int(row[0]),
                created_at=str(row[1]),
                message=str(row[2]),
            )
            for row in rows
        ]
