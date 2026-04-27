from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import Dict, List

import anyio


@dataclass(frozen=True)
class RegisteredDevice:
    token: str
    platform: str
    push_provider: str
    device_name: str | None = None
    user_id: int | None = None
    first_user_id: int | None = None
    last_seen_at: str | None = None


class DeviceRegistry:
    """
    SQLite-backed device registry with a lock around writes/reads.

    Notes:
      - Registrations survive backend restarts.
      - Records are deduplicated by (push_provider, token).
      - SQLite is sufficient for the current single-node phase.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
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
                    device_name TEXT NULL,
                    user_id INTEGER NULL,
                    first_user_id INTEGER NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (push_provider, token)
                );
                """
            )
            cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(registered_devices);").fetchall()}
            if "device_name" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN device_name TEXT NULL;")
            if "user_id" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN user_id INTEGER NULL;")
            if "first_user_id" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN first_user_id INTEGER NULL;")
            if "last_seen_at" not in cols:
                conn.execute(
                    "ALTER TABLE registered_devices ADD COLUMN last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP;"
                )

    def _register_sync(
        self,
        token: str,
        platform: str,
        push_provider: str,
        device_name: str | None,
        user_id: int | None,
    ) -> bool:
        with self._lock:
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
                    INSERT INTO registered_devices
                        (token, platform, push_provider, device_name, user_id, first_user_id, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(push_provider, token)
                    DO UPDATE SET
                        platform = excluded.platform,
                        push_provider = excluded.push_provider,
                        device_name = excluded.device_name,
                        user_id = excluded.user_id,
                        first_user_id = COALESCE(registered_devices.first_user_id, excluded.first_user_id),
                        last_seen_at = CURRENT_TIMESTAMP;
                    """,
                    (token, platform, push_provider, device_name, user_id, user_id),
                )
                return is_new

    async def register(
        self,
        token: str,
        platform: str,
        push_provider: str,
        device_name: str | None = None,
        user_id: int | None = None,
    ) -> bool:
        # Run in a worker thread to avoid blocking the asyncio loop on SQLite I/O.
        return await anyio.to_thread.run_sync(
            self._register_sync,
            token,
            platform,
            push_provider,
            device_name,
            user_id,
        )

    async def list_tokens(self) -> List[str]:
        devices = await self.list_devices()
        return [device.token for device in devices]

    def _list_by_provider_sync(self, push_provider: str) -> List[RegisteredDevice]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT token, platform, push_provider, device_name, user_id, first_user_id, last_seen_at
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
                device_name=str(row[3]) if row[3] is not None else None,
                user_id=int(row[4]) if row[4] is not None else None,
                first_user_id=int(row[5]) if row[5] is not None else None,
                last_seen_at=str(row[6]) if row[6] is not None else None,
            )
            for row in rows
        ]

    async def list_by_provider(self, push_provider: str) -> List[RegisteredDevice]:
        return await anyio.to_thread.run_sync(self._list_by_provider_sync, push_provider)

    def _list_devices_sync(self) -> List[RegisteredDevice]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT token, platform, push_provider, device_name, user_id, first_user_id, last_seen_at
                    FROM registered_devices
                    ORDER BY created_at ASC, rowid ASC;
                    """
                ).fetchall()
        return [
            RegisteredDevice(
                token=str(row[0]),
                platform=str(row[1]),
                push_provider=str(row[2]),
                device_name=str(row[3]) if row[3] is not None else None,
                user_id=int(row[4]) if row[4] is not None else None,
                first_user_id=int(row[5]) if row[5] is not None else None,
                last_seen_at=str(row[6]) if row[6] is not None else None,
            )
            for row in rows
        ]

    async def list_devices(self) -> List[RegisteredDevice]:
        return await anyio.to_thread.run_sync(self._list_devices_sync)

    def _count_sync(self) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) FROM registered_devices;").fetchone()
        return int(row[0]) if row else 0

    async def count(self) -> int:
        return await anyio.to_thread.run_sync(self._count_sync)

    def _platform_counts_sync(self) -> Dict[str, int]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT platform, COUNT(*)
                    FROM registered_devices
                    GROUP BY platform;
                    """
                ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    async def platform_counts(self) -> Dict[str, int]:
        return await anyio.to_thread.run_sync(self._platform_counts_sync)

    def _provider_counts_sync(self) -> Dict[str, int]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT push_provider, COUNT(*)
                    FROM registered_devices
                    GROUP BY push_provider;
                    """
                ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    async def provider_counts(self) -> Dict[str, int]:
        return await anyio.to_thread.run_sync(self._provider_counts_sync)

    def _delete_sync(self, token: str, push_provider: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    DELETE FROM registered_devices
                    WHERE push_provider = ? AND token = ?;
                    """,
                    (push_provider, token),
                )
        return int(cur.rowcount or 0) > 0

    async def delete(self, token: str, push_provider: str) -> bool:
        return await anyio.to_thread.run_sync(self._delete_sync, token, push_provider)

    def _touch_sync(self, token: str, push_provider: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE registered_devices SET last_seen_at = CURRENT_TIMESTAMP WHERE token = ? AND push_provider = ?;",
                    (token, push_provider),
                )

    async def touch(self, token: str, push_provider: str) -> None:
        """Refresh last_seen_at without changing any other fields. Safe to fire as a background task."""
        await anyio.to_thread.run_sync(self._touch_sync, token, push_provider)
