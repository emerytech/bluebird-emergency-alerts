from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import anyio

from app.services.passwords import hash_password, verify_password


@dataclass(frozen=True)
class PlatformAdminRecord:
    id: int
    created_at: str
    login_name: str
    last_login_at: Optional[str]
    must_change_password: bool
    totp_enabled: bool


class PlatformAdminStore:
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
                CREATE TABLE IF NOT EXISTS platform_admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    login_name TEXT NOT NULL UNIQUE,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    last_login_at TEXT NULL,
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    totp_secret TEXT NULL
                );
                """
            )
            self._migrate_platform_admins_table(conn)

    def _migrate_platform_admins_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(platform_admins);").fetchall()}
        if "totp_secret" not in cols:
            conn.execute("ALTER TABLE platform_admins ADD COLUMN totp_secret TEXT NULL;")

    def _row_to_record(self, row: sqlite3.Row | tuple) -> PlatformAdminRecord:
        return PlatformAdminRecord(
            id=int(row[0]),
            created_at=str(row[1]),
            login_name=str(row[2]),
            last_login_at=str(row[3]) if row[3] is not None else None,
            must_change_password=bool(int(row[4])),
            totp_enabled=bool(row[5]) if len(row) > 5 else False,
        )

    def _ensure_bootstrap_sync(self, login_name: str, password: str) -> PlatformAdminRecord:
        normalized = login_name.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, login_name, last_login_at, must_change_password, totp_secret
                FROM platform_admins
                WHERE login_name = ?
                LIMIT 1;
                """,
                (normalized,),
            ).fetchone()
            if row is not None:
                return self._row_to_record(row)

            salt_hex, digest_hex = hash_password(password)
            cur = conn.execute(
                """
                INSERT INTO platform_admins
                    (created_at, login_name, password_salt, password_hash, last_login_at, must_change_password)
                VALUES (?, ?, ?, ?, NULL, 1);
                """,
                (datetime.now(timezone.utc).isoformat(), normalized, salt_hex, digest_hex),
            )
            row = conn.execute(
                """
                SELECT id, created_at, login_name, last_login_at, must_change_password, totp_secret
                FROM platform_admins
                WHERE id = ?;
                """,
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    async def ensure_bootstrap(self, *, login_name: str, password: str) -> PlatformAdminRecord:
        return await anyio.to_thread.run_sync(self._ensure_bootstrap_sync, login_name, password)

    def _authenticate_sync(self, login_name: str, password: str) -> Optional[PlatformAdminRecord]:
        normalized = login_name.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, login_name, password_salt, password_hash, last_login_at, must_change_password, totp_secret
                FROM platform_admins
                WHERE login_name = ?
                LIMIT 1;
                """,
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        salt_hex = str(row[3])
        digest_hex = str(row[4])
        if not verify_password(password, salt_hex=salt_hex, digest_hex=digest_hex):
            return None
        return PlatformAdminRecord(
            id=int(row[0]),
            created_at=str(row[1]),
            login_name=str(row[2]),
            last_login_at=str(row[5]) if row[5] is not None else None,
            must_change_password=bool(int(row[6])),
            totp_enabled=bool(row[7]),
        )

    async def authenticate(self, login_name: str, password: str) -> Optional[PlatformAdminRecord]:
        return await anyio.to_thread.run_sync(self._authenticate_sync, login_name, password)

    def _get_by_id_sync(self, admin_id: int) -> Optional[PlatformAdminRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, login_name, last_login_at, must_change_password, totp_secret
                FROM platform_admins
                WHERE id = ?
                LIMIT 1;
                """,
                (int(admin_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def get_by_id(self, admin_id: int) -> Optional[PlatformAdminRecord]:
        return await anyio.to_thread.run_sync(self._get_by_id_sync, int(admin_id))

    def _mark_login_sync(self, admin_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE platform_admins SET last_login_at = ? WHERE id = ?;",
                (datetime.now(timezone.utc).isoformat(), int(admin_id)),
            )

    async def mark_login(self, admin_id: int) -> None:
        await anyio.to_thread.run_sync(self._mark_login_sync, int(admin_id))

    def _change_password_sync(self, admin_id: int, password: str) -> None:
        salt_hex, digest_hex = hash_password(password)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE platform_admins
                SET password_salt = ?, password_hash = ?, must_change_password = 0
                WHERE id = ?;
                """,
                (salt_hex, digest_hex, int(admin_id)),
            )

    async def change_password(self, admin_id: int, new_password: str) -> None:
        await anyio.to_thread.run_sync(self._change_password_sync, int(admin_id), new_password)

    def _get_totp_secret_sync(self, admin_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT totp_secret FROM platform_admins WHERE id = ? LIMIT 1;",
                (int(admin_id),),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return str(row[0])

    async def get_totp_secret(self, admin_id: int) -> Optional[str]:
        return await anyio.to_thread.run_sync(self._get_totp_secret_sync, int(admin_id))

    def _set_totp_secret_sync(self, admin_id: int, secret: Optional[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE platform_admins SET totp_secret = ? WHERE id = ?;",
                (secret, int(admin_id)),
            )

    async def set_totp_secret(self, admin_id: int, secret: Optional[str]) -> None:
        await anyio.to_thread.run_sync(self._set_totp_secret_sync, int(admin_id), secret)

    def _verify_current_password_sync(self, admin_id: int, password: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_salt, password_hash FROM platform_admins WHERE id = ? LIMIT 1;",
                (int(admin_id),),
            ).fetchone()
        if row is None:
            return False
        return verify_password(password, salt_hex=str(row[0]), digest_hex=str(row[1]))

    async def verify_current_password(self, admin_id: int, password: str) -> bool:
        return await anyio.to_thread.run_sync(self._verify_current_password_sync, int(admin_id), password)
