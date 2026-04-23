from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class RegisteredDevice:
    token: str
    platform: str
    push_provider: str


class DeviceRegistry:
    """
    SQLite-backed device registry with an async lock around writes/reads.

    Notes:
      - Registrations survive backend restarts.
      - Records are deduplicated by (push_provider, token).
      - SQLite is sufficient for the current single-node phase.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=30, isolation_level=None)

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS registered_devices (
                    token TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    push_provider TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (push_provider, token)
                );
                """
            )

    async def register(self, token: str, platform: str, push_provider: str) -> bool:
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT 1
                    FROM registered_devices
                    WHERE push_provider = ? AND token = ?
                    LIMIT 1;
                    """,
                    (push_provider, token),
                ).fetchone()
                is_new = row is None
                conn.execute(
                    """
                    INSERT INTO registered_devices (token, platform, push_provider)
                    VALUES (?, ?, ?)
                    ON CONFLICT(push_provider, token)
                    DO UPDATE SET
                        platform = excluded.platform,
                        push_provider = excluded.push_provider;
                    """,
                    (token, platform, push_provider),
                )
                return is_new

    async def list_tokens(self) -> List[str]:
        devices = await self.list_devices()
        return [device.token for device in devices]

    async def list_by_provider(self, push_provider: str) -> List[RegisteredDevice]:
        async with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT token, platform, push_provider
                    FROM registered_devices
                    WHERE push_provider = ?
                    ORDER BY created_at ASC, rowid ASC;
                    """,
                    (push_provider,),
                ).fetchall()
        return [
            RegisteredDevice(
                token=str(row[0]),
                platform=str(row[1]),
                push_provider=str(row[2]),
            )
            for row in rows
        ]

    async def list_devices(self) -> List[RegisteredDevice]:
        async with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT token, platform, push_provider
                    FROM registered_devices
                    ORDER BY created_at ASC, rowid ASC;
                    """
                ).fetchall()
        return [
            RegisteredDevice(
                token=str(row[0]),
                platform=str(row[1]),
                push_provider=str(row[2]),
            )
            for row in rows
        ]

    async def count(self) -> int:
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) FROM registered_devices;").fetchone()
        return int(row[0]) if row else 0

    async def platform_counts(self) -> Dict[str, int]:
        async with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT platform, COUNT(*)
                    FROM registered_devices
                    GROUP BY platform;
                    """
                ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    async def provider_counts(self) -> Dict[str, int]:
        async with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT push_provider, COUNT(*)
                    FROM registered_devices
                    GROUP BY push_provider;
                    """
                ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}
