from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import anyio


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SessionRecord:
    id: int
    user_id: int
    tenant_slug: str
    session_token: str
    client_type: str  # "mobile" | "web"
    is_active: bool
    created_at: str
    last_seen_at: str


class SessionStore:
    """Per-tenant session store.

    Stores one active session per (user_id, client_type).
    Mobile sessions survive web logins. Web logins replace previous web sessions.
    Existing API key flows are unaffected — this store is purely additive.
    """

    def __init__(self, db_path: str, tenant_slug: str) -> None:
        self._db_path = db_path
        self._tenant_slug = tenant_slug
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=30, isolation_level=None)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       INTEGER NOT NULL,
                    tenant_slug   TEXT    NOT NULL,
                    session_token TEXT    NOT NULL UNIQUE,
                    client_type   TEXT    NOT NULL DEFAULT 'mobile',
                    is_active     INTEGER NOT NULL DEFAULT 1,
                    created_at    TEXT    NOT NULL,
                    last_seen_at  TEXT    NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sess_token ON user_sessions(session_token);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sess_user_type ON user_sessions(user_id, client_type, is_active);"
            )

    # ── internal helpers ───────────────────────────────────────────────────

    def _row_to_record(self, row: tuple) -> SessionRecord:
        return SessionRecord(
            id=int(row[0]),
            user_id=int(row[1]),
            tenant_slug=str(row[2]),
            session_token=str(row[3]),
            client_type=str(row[4]),
            is_active=bool(row[5]),
            created_at=str(row[6]),
            last_seen_at=str(row[7]),
        )

    def _create_sync(self, user_id: int, client_type: str) -> SessionRecord:
        now = _now_utc()
        token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            # Invalidate existing sessions of the SAME client_type for this user.
            # Mobile sessions are NOT touched when client_type == "web" and vice versa.
            conn.execute("BEGIN;")
            conn.execute(
                """UPDATE user_sessions
                   SET is_active = 0
                   WHERE user_id = ? AND tenant_slug = ? AND client_type = ? AND is_active = 1;""",
                (user_id, self._tenant_slug, client_type),
            )
            conn.execute(
                """INSERT INTO user_sessions
                       (user_id, tenant_slug, session_token, client_type, is_active, created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?);""",
                (user_id, self._tenant_slug, token, client_type, now, now),
            )
            row = conn.execute(
                """SELECT id, user_id, tenant_slug, session_token, client_type,
                          is_active, created_at, last_seen_at
                   FROM user_sessions WHERE session_token = ?;""",
                (token,),
            ).fetchone()
            conn.execute("COMMIT;")
        return self._row_to_record(row)

    def _get_by_token_sync(self, token: str) -> Optional[SessionRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id, user_id, tenant_slug, session_token, client_type,
                          is_active, created_at, last_seen_at
                   FROM user_sessions
                   WHERE session_token = ? AND is_active = 1;""",
                (token,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def _touch_sync(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE user_sessions SET last_seen_at = ? WHERE session_token = ? AND is_active = 1;",
                (_now_utc(), token),
            )

    def _invalidate_sync(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE user_sessions SET is_active = 0 WHERE session_token = ?;",
                (token,),
            )

    def _list_active_sync(self, user_id: Optional[int] = None) -> list:
        with self._connect() as conn:
            if user_id is not None:
                rows = conn.execute(
                    """SELECT id, user_id, tenant_slug, session_token, client_type,
                              is_active, created_at, last_seen_at
                       FROM user_sessions
                       WHERE is_active = 1 AND tenant_slug = ? AND user_id = ?
                       ORDER BY last_seen_at DESC;""",
                    (self._tenant_slug, int(user_id)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, user_id, tenant_slug, session_token, client_type,
                              is_active, created_at, last_seen_at
                       FROM user_sessions
                       WHERE is_active = 1 AND tenant_slug = ?
                       ORDER BY last_seen_at DESC;""",
                    (self._tenant_slug,),
                ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def _invalidate_by_id_sync(self, session_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE user_sessions SET is_active = 0 WHERE id = ? AND tenant_slug = ? AND is_active = 1;",
                (int(session_id), self._tenant_slug),
            )
        return (cur.rowcount or 0) > 0

    # ── public async API ───────────────────────────────────────────────────

    async def create_session(self, *, user_id: int, client_type: str) -> SessionRecord:
        """Create a new session. Invalidates existing sessions of the same client_type only."""
        return await anyio.to_thread.run_sync(
            lambda: self._create_sync(user_id, client_type)
        )

    async def get_by_token(self, token: str) -> Optional[SessionRecord]:
        """Return the active session for this token, or None if not found/inactive."""
        return await anyio.to_thread.run_sync(lambda: self._get_by_token_sync(token))

    async def touch(self, token: str) -> None:
        """Update last_seen_at. Call as a background task — never block on this."""
        await anyio.to_thread.run_sync(lambda: self._touch_sync(token))

    async def invalidate(self, token: str) -> None:
        """Explicitly deactivate a session (logout)."""
        await anyio.to_thread.run_sync(lambda: self._invalidate_sync(token))

    async def list_active(self, *, user_id: Optional[int] = None) -> list:
        """List all active sessions for this tenant, ordered by last_seen_at desc."""
        return await anyio.to_thread.run_sync(lambda: self._list_active_sync(user_id))

    async def invalidate_by_id(self, session_id: int) -> bool:
        """Deactivate a session by its row ID. Returns True if a session was revoked."""
        return await anyio.to_thread.run_sync(lambda: self._invalidate_by_id_sync(session_id))
