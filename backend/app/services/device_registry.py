from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

import anyio


@dataclass(frozen=True)
class RegisteredDevice:
    token: str
    platform: str
    push_provider: str
    device_name: str | None = None
    device_id: str | None = None
    user_id: int | None = None
    first_user_id: int | None = None
    last_seen_at: str | None = None
    is_valid: bool = True
    is_active: bool = True
    archived_at: str | None = None
    ws_connected: bool = False
    ws_last_seen_at: str | None = None
    last_push_success_at: str | None = None
    last_push_status: str = "unknown"  # success / failed / unknown
    last_push_error: str | None = None


class DeviceRegistry:
    """
    SQLite-backed device registry with a lock around writes/reads.

    Notes:
      - Registrations survive backend restarts.
      - Records are deduplicated by (push_provider, token).
      - device_id is a stable per-install identifier (UUID from the client).
      - Only one active (is_active=1, archived_at IS NULL) record is allowed
        per device_id — registering a different user on the same device_id
        archives the old record automatically.
      - Push targeting only reads active records (is_active=1 AND archived_at IS NULL).
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
                    last_seen_at TEXT NULL,
                    is_valid INTEGER NOT NULL DEFAULT 1,
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
                conn.execute("ALTER TABLE registered_devices ADD COLUMN last_seen_at TEXT NULL;")
            if "is_valid" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN is_valid INTEGER NOT NULL DEFAULT 1;")
            if "device_id" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN device_id TEXT NULL;")
            if "is_active" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;")
            if "archived_at" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN archived_at TEXT NULL;")
            if "ws_connected" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN ws_connected INTEGER NOT NULL DEFAULT 0;")
            if "ws_last_seen_at" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN ws_last_seen_at TEXT NULL;")
            if "last_push_success_at" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN last_push_success_at TEXT NULL;")
            if "last_push_status" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN last_push_status TEXT NOT NULL DEFAULT 'unknown';")
            if "last_push_error" not in cols:
                conn.execute("ALTER TABLE registered_devices ADD COLUMN last_push_error TEXT NULL;")

    def _register_sync(
        self,
        token: str,
        platform: str,
        push_provider: str,
        device_name: str | None,
        user_id: int | None,
        device_id: str | None = None,
    ) -> bool:
        with self._lock:
            with self._connect() as conn:
                # Step 1: If a stable device_id is provided, archive any active
                # record for the same device that belongs to a different user.
                # This enforces "one active record per device_id".
                if device_id is not None:
                    conn.execute(
                        """
                        UPDATE registered_devices
                        SET is_valid = 0, is_active = 0, archived_at = CURRENT_TIMESTAMP
                        WHERE device_id = ?
                          AND is_active = 1
                          AND archived_at IS NULL
                          AND (user_id IS NULL OR user_id != ?);
                        """,
                        (device_id, user_id if user_id is not None else -1),
                    )

                # Step 2: Check whether this (push_provider, token) pair exists.
                existing = conn.execute(
                    """
                    SELECT user_id, device_id, is_active, archived_at
                    FROM registered_devices
                    WHERE push_provider = ? AND token = ?
                    LIMIT 1;
                    """,
                    (push_provider, token),
                ).fetchone()

                is_new = existing is None

                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO registered_devices
                            (token, platform, push_provider, device_name, device_id, user_id,
                             first_user_id, last_seen_at, is_valid, is_active, archived_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 1, 1, NULL);
                        """,
                        (token, platform, push_provider, device_name, device_id, user_id, user_id),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE registered_devices SET
                            platform     = ?,
                            device_name  = ?,
                            device_id    = COALESCE(?, device_id),
                            user_id      = ?,
                            first_user_id = COALESCE(first_user_id, ?),
                            last_seen_at = CURRENT_TIMESTAMP,
                            is_valid     = 1,
                            is_active    = 1,
                            archived_at  = NULL
                        WHERE push_provider = ? AND token = ?;
                        """,
                        (platform, device_name, device_id, user_id, user_id, push_provider, token),
                    )

                return is_new

    async def register(
        self,
        token: str,
        platform: str,
        push_provider: str,
        device_name: str | None = None,
        user_id: int | None = None,
        device_id: str | None = None,
    ) -> bool:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(
                self._register_sync,
                token,
                platform,
                push_provider,
                device_name,
                user_id,
                device_id,
            )
        )

    async def list_tokens(self) -> List[str]:
        devices = await self.list_devices()
        return [device.token for device in devices]

    def _list_by_provider_sync(self, push_provider: str) -> List[RegisteredDevice]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT token, platform, push_provider, device_name, device_id,
                           user_id, first_user_id, last_seen_at, is_valid, is_active, archived_at,
                           ws_connected, ws_last_seen_at,
                           last_push_success_at, last_push_status, last_push_error
                    FROM registered_devices
                    WHERE push_provider = ?
                      AND is_valid = 1
                      AND is_active = 1
                      AND archived_at IS NULL
                    ORDER BY created_at ASC, rowid ASC;
                    """,
                    (push_provider,),
                ).fetchall()
        return [_row_to_device(row) for row in rows]

    async def list_by_provider(self, push_provider: str) -> List[RegisteredDevice]:
        return await anyio.to_thread.run_sync(self._list_by_provider_sync, push_provider)

    def _list_devices_sync(self, include_archived: bool = False) -> List[RegisteredDevice]:
        with self._lock:
            with self._connect() as conn:
                query = """
                    SELECT token, platform, push_provider, device_name, device_id,
                           user_id, first_user_id, last_seen_at, is_valid, is_active, archived_at,
                           ws_connected, ws_last_seen_at,
                           last_push_success_at, last_push_status, last_push_error
                    FROM registered_devices
                """
                if not include_archived:
                    query += " WHERE is_active = 1 AND archived_at IS NULL"
                query += " ORDER BY created_at ASC, rowid ASC;"
                rows = conn.execute(query).fetchall()
        return [_row_to_device(row) for row in rows]

    async def list_devices(self, include_archived: bool = False) -> List[RegisteredDevice]:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._list_devices_sync, include_archived)
        )

    def _count_sync(self) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM registered_devices WHERE is_active = 1 AND archived_at IS NULL;"
                ).fetchone()
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
                    WHERE is_active = 1 AND archived_at IS NULL
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
                    WHERE is_active = 1 AND archived_at IS NULL
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
                    "DELETE FROM registered_devices WHERE push_provider = ? AND token = ?;",
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

    def _mark_invalid_sync(self, token: str, push_provider: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE registered_devices SET is_valid = 0 WHERE token = ? AND push_provider = ?;",
                    (token, push_provider),
                )

    async def mark_invalid(self, token: str, push_provider: str) -> None:
        """Mark a specific token as invalid (e.g. after a push delivery failure)."""
        await anyio.to_thread.run_sync(self._mark_invalid_sync, token, push_provider)

    def _mark_invalid_by_user_sync(self, user_id: int) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE registered_devices SET is_valid = 0 WHERE user_id = ?;",
                    (user_id,),
                )

    async def mark_invalid_by_user(self, user_id: int) -> None:
        """Mark all tokens for a user as invalid (e.g. when the user is deactivated)."""
        await anyio.to_thread.run_sync(self._mark_invalid_by_user_sync, user_id)

    # ── Session lifecycle ──────────────────────────────────────────────────────

    def _archive_by_token_sync(self, token: str, push_provider: str) -> bool:
        """Archive a device record when a user logs out. Keeps the row for auditing."""
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    UPDATE registered_devices
                    SET is_active = 0, archived_at = CURRENT_TIMESTAMP
                    WHERE push_provider = ? AND token = ?
                      AND is_active = 1;
                    """,
                    (push_provider, token),
                )
        return int(cur.rowcount or 0) > 0

    async def archive_by_token(self, token: str, push_provider: str) -> bool:
        """Archive a device on logout by its push token. Returns True if a record was updated."""
        return await anyio.to_thread.run_sync(self._archive_by_token_sync, token, push_provider)

    def _archive_by_device_id_sync(self, device_id: str, user_id: Optional[int] = None) -> int:
        """Archive all active records for a device_id (optionally scoped to a user)."""
        with self._lock:
            with self._connect() as conn:
                if user_id is not None:
                    cur = conn.execute(
                        """
                        UPDATE registered_devices
                        SET is_active = 0, archived_at = CURRENT_TIMESTAMP
                        WHERE device_id = ? AND user_id = ? AND is_active = 1;
                        """,
                        (device_id, user_id),
                    )
                else:
                    cur = conn.execute(
                        """
                        UPDATE registered_devices
                        SET is_active = 0, archived_at = CURRENT_TIMESTAMP
                        WHERE device_id = ? AND is_active = 1;
                        """,
                        (device_id,),
                    )
        return int(cur.rowcount or 0)

    async def archive_by_device_id(self, device_id: str, user_id: Optional[int] = None) -> int:
        """Archive active records for a device_id. Returns count of archived rows."""
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._archive_by_device_id_sync, device_id, user_id)
        )

    # ── WebSocket presence ─────────────────────────────────────────────────────

    def _set_ws_presence_sync(
        self, *, device_id: Optional[str], user_id: Optional[int], connected: bool
    ) -> None:
        flag = 1 if connected else 0
        with self._lock:
            with self._connect() as conn:
                if device_id is not None:
                    conn.execute(
                        """
                        UPDATE registered_devices
                        SET ws_connected = ?,
                            ws_last_seen_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE ws_last_seen_at END
                        WHERE device_id = ? AND is_active = 1 AND archived_at IS NULL;
                        """,
                        (flag, flag, device_id),
                    )
                elif user_id is not None:
                    conn.execute(
                        """
                        UPDATE registered_devices
                        SET ws_connected = ?,
                            ws_last_seen_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE ws_last_seen_at END
                        WHERE user_id = ? AND is_active = 1 AND archived_at IS NULL;
                        """,
                        (flag, flag, user_id),
                    )

    async def set_ws_presence(
        self, *, device_id: Optional[str], user_id: Optional[int], connected: bool
    ) -> None:
        """Set ws_connected flag and optionally update ws_last_seen_at on connect."""
        import functools
        await anyio.to_thread.run_sync(
            functools.partial(
                self._set_ws_presence_sync,
                device_id=device_id,
                user_id=user_id,
                connected=connected,
            )
        )

    def _touch_ws_sync(self, *, device_id: Optional[str], user_id: Optional[int]) -> None:
        with self._lock:
            with self._connect() as conn:
                if device_id is not None:
                    conn.execute(
                        "UPDATE registered_devices SET ws_last_seen_at = CURRENT_TIMESTAMP "
                        "WHERE device_id = ? AND is_active = 1 AND archived_at IS NULL;",
                        (device_id,),
                    )
                elif user_id is not None:
                    conn.execute(
                        "UPDATE registered_devices SET ws_last_seen_at = CURRENT_TIMESTAMP "
                        "WHERE user_id = ? AND is_active = 1 AND archived_at IS NULL;",
                        (user_id,),
                    )

    async def touch_ws(self, *, device_id: Optional[str], user_id: Optional[int]) -> None:
        """Refresh ws_last_seen_at on incoming WS message/ping."""
        import functools
        await anyio.to_thread.run_sync(
            functools.partial(self._touch_ws_sync, device_id=device_id, user_id=user_id)
        )

    # ── Push delivery status ───────────────────────────────────────────────────

    def _update_push_status_sync(
        self, token: str, push_provider: str, ok: bool, error: Optional[str]
    ) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._connect() as conn:
                if ok:
                    conn.execute(
                        """UPDATE registered_devices
                           SET last_push_success_at = ?,
                               last_push_status = 'success',
                               last_push_error = NULL
                           WHERE token = ? AND push_provider = ?;""",
                        (now, token, push_provider),
                    )
                else:
                    conn.execute(
                        """UPDATE registered_devices
                           SET last_push_status = 'failed',
                               last_push_error = ?
                           WHERE token = ? AND push_provider = ?;""",
                        ((error or "unknown error")[:500], token, push_provider),
                    )

    async def update_push_status(
        self, token: str, push_provider: str, ok: bool, error: Optional[str] = None
    ) -> None:
        """Record push delivery outcome per device. Call after every FCM/APNs attempt."""
        import functools
        await anyio.to_thread.run_sync(
            functools.partial(self._update_push_status_sync, token, push_provider, ok, error)
        )

    def _get_by_token_sync(self, token: str, push_provider: str) -> Optional[RegisteredDevice]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """SELECT token, platform, push_provider, device_name, device_id,
                              user_id, first_user_id, last_seen_at, is_valid, is_active, archived_at,
                              ws_connected, ws_last_seen_at,
                              last_push_success_at, last_push_status, last_push_error
                       FROM registered_devices
                       WHERE token = ? AND push_provider = ?
                       LIMIT 1;""",
                    (token, push_provider),
                ).fetchone()
        return _row_to_device(row) if row else None

    async def get_by_token(self, token: str, push_provider: str) -> Optional[RegisteredDevice]:
        """Look up a single device by its push token and provider."""
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._get_by_token_sync, token, push_provider)
        )


def compute_device_status(device: RegisteredDevice) -> str:
    """
    Return 'online', 'idle', or 'offline' based on hybrid WS + heartbeat thresholds.

    Thresholds:
      - WS connected + ws_last_seen_at within 60 s  → online
      - last_seen_at (heartbeat) within  5 min       → online
      - last_seen_at (heartbeat) within 15 min       → idle
      - otherwise                                    → offline
    """
    from datetime import datetime, timedelta

    now = datetime.utcnow()

    if device.ws_connected and device.ws_last_seen_at:
        try:
            ws_ts = datetime.fromisoformat(device.ws_last_seen_at.replace("Z", ""))
            if (now - ws_ts).total_seconds() < 60:
                return "online"
        except ValueError:
            pass

    if device.last_seen_at:
        try:
            hb_ts = datetime.fromisoformat(device.last_seen_at.replace("Z", ""))
            age = (now - hb_ts).total_seconds()
            if age < 300:
                return "online"
            if age < 900:
                return "idle"
        except ValueError:
            pass

    return "offline"


def _row_to_device(row: tuple) -> RegisteredDevice:
    """Convert a DB row (11, 13, or 16 columns) to RegisteredDevice."""
    return RegisteredDevice(
        token=str(row[0]),
        platform=str(row[1]),
        push_provider=str(row[2]),
        device_name=str(row[3]) if row[3] is not None else None,
        device_id=str(row[4]) if row[4] is not None else None,
        user_id=int(row[5]) if row[5] is not None else None,
        first_user_id=int(row[6]) if row[6] is not None else None,
        last_seen_at=str(row[7]) if row[7] is not None else None,
        is_valid=bool(row[8]),
        is_active=bool(row[9]),
        archived_at=str(row[10]) if row[10] is not None else None,
        ws_connected=bool(row[11]) if len(row) > 11 else False,
        ws_last_seen_at=str(row[12]) if len(row) > 12 and row[12] is not None else None,
        last_push_success_at=str(row[13]) if len(row) > 13 and row[13] is not None else None,
        last_push_status=str(row[14]) if len(row) > 14 and row[14] is not None else "unknown",
        last_push_error=str(row[15]) if len(row) > 15 and row[15] is not None else None,
    )
