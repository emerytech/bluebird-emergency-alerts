from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import anyio

from app.services.passwords import hash_password, verify_password
from app.services.permissions import is_dashboard_role


@dataclass(frozen=True)
class UserRecord:
    id: int
    created_at: str
    name: str
    role: str
    phone_e164: Optional[str]
    is_active: bool
    login_name: Optional[str]
    can_login: bool
    last_login_at: Optional[str]
    must_change_password: bool = False
    totp_enabled: bool = False
    title: Optional[str] = None


class UserStore:
    """
    Minimal user store for MVP.

    This is used for:
      - Attribution (who triggered an alert)
      - SMS delivery targets (phone numbers)
      - Future role-based alerting
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
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    phone_e164 TEXT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    login_name TEXT NULL,
                    password_salt TEXT NULL,
                    password_hash TEXT NULL,
                    last_login_at TEXT NULL
                );
                """
            )
            self._migrate_users_table(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login_name ON users(login_name);")

    def _migrate_users_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(users);").fetchall()}
        if "login_name" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN login_name TEXT NULL;")
        if "password_salt" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN password_salt TEXT NULL;")
        if "password_hash" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT NULL;")
        if "last_login_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT NULL;")
        if "must_change_password" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0;")
        if "totp_secret" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT NULL;")
        if "title" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN title TEXT NULL;")

    def _create_user_sync(
        self,
        created_at: str,
        name: str,
        role: str,
        phone_e164: Optional[str],
        login_name: Optional[str],
        password_salt: Optional[str],
        password_hash: Optional[str],
        must_change_password: bool,
        title: Optional[str],
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (created_at, name, role, phone_e164, is_active, login_name, password_salt, password_hash, must_change_password, title)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?);
                """,
                (created_at, name, role, phone_e164, login_name, password_salt, password_hash, 1 if must_change_password else 0, title),
            )
            return int(cur.lastrowid)

    async def create_user(
        self,
        *,
        name: str,
        role: str,
        phone_e164: Optional[str],
        login_name: Optional[str] = None,
        password: Optional[str] = None,
        must_change_password: bool = False,
        title: Optional[str] = None,
    ) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        normalized_login = login_name.strip().lower() if login_name else None
        password_salt = None
        password_hash = None
        if normalized_login and password:
            password_salt, password_hash = hash_password(password)
        normalized_title = title.strip() if title else None
        return await anyio.to_thread.run_sync(
            self._create_user_sync,
            created_at,
            name,
            role,
            phone_e164,
            normalized_login,
            password_salt,
            password_hash,
            must_change_password,
            normalized_title,
        )

    def _list_users_sync(self) -> List[UserRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, name, role, phone_e164, is_active, login_name, password_hash, last_login_at, must_change_password, totp_secret, title
                FROM users
                ORDER BY id ASC;
                """
            ).fetchall()

        return [
            UserRecord(
                id=int(row[0]),
                created_at=str(row[1]),
                name=str(row[2]),
                role=str(row[3]),
                phone_e164=str(row[4]) if row[4] is not None else None,
                is_active=bool(int(row[5])),
                login_name=str(row[6]) if row[6] is not None else None,
                can_login=bool(row[6]) and bool(row[7]),
                last_login_at=str(row[8]) if row[8] is not None else None,
                must_change_password=bool(int(row[9])) if row[9] is not None else False,
                totp_enabled=bool(row[10]),
                title=str(row[11]) if row[11] is not None else None,
            )
            for row in rows
        ]

    async def list_users(self) -> List[UserRecord]:
        return await anyio.to_thread.run_sync(self._list_users_sync)

    def _list_sms_targets_sync(self, roles: Optional[List[str]], excluded_user_ids: Optional[List[int]]) -> List[str]:
        roles = roles or []
        excluded_user_ids = excluded_user_ids or []
        with self._connect() as conn:
            if roles:
                placeholders = ",".join(["?"] * len(roles))
                excluded_clause = ""
                excluded_params: tuple[object, ...] = ()
                if excluded_user_ids:
                    excluded_placeholders = ",".join(["?"] * len(excluded_user_ids))
                    excluded_clause = f" AND id NOT IN ({excluded_placeholders})"
                    excluded_params = tuple(int(v) for v in excluded_user_ids)
                rows = conn.execute(
                    f"""
                    SELECT phone_e164
                    FROM users
                    WHERE is_active = 1
                      AND phone_e164 IS NOT NULL
                      AND role IN ({placeholders})
                      {excluded_clause}
                    ORDER BY id ASC;
                    """,
                    tuple(roles) + excluded_params,
                ).fetchall()
            else:
                excluded_clause = ""
                excluded_params = ()
                if excluded_user_ids:
                    excluded_placeholders = ",".join(["?"] * len(excluded_user_ids))
                    excluded_clause = f" AND id NOT IN ({excluded_placeholders})"
                    excluded_params = tuple(int(v) for v in excluded_user_ids)
                rows = conn.execute(
                    f"""
                    SELECT phone_e164
                    FROM users
                    WHERE is_active = 1
                      AND phone_e164 IS NOT NULL
                      {excluded_clause}
                    ORDER BY id ASC;
                    """,
                    excluded_params,
                ).fetchall()

        return [str(row[0]) for row in rows if row and row[0]]

    async def list_sms_targets(self, *, roles: Optional[List[str]] = None, excluded_user_ids: Optional[List[int]] = None) -> List[str]:
        """
        Returns phone numbers for outbound SMS.
        """

        return await anyio.to_thread.run_sync(self._list_sms_targets_sync, roles, excluded_user_ids)

    def _exists_sync(self, user_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM users WHERE id = ? LIMIT 1;", (int(user_id),)).fetchone()
        return row is not None

    async def exists(self, user_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._exists_sync, int(user_id))

    def _get_user_sync(self, user_id: int) -> Optional[UserRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, name, role, phone_e164, is_active, login_name, password_hash, last_login_at, must_change_password, totp_secret, title
                FROM users
                WHERE id = ?
                LIMIT 1;
                """,
                (int(user_id),),
            ).fetchone()
        if row is None:
            return None
        return UserRecord(
            id=int(row[0]),
            created_at=str(row[1]),
            name=str(row[2]),
            role=str(row[3]),
            phone_e164=str(row[4]) if row[4] is not None else None,
            is_active=bool(int(row[5])),
            login_name=str(row[6]) if row[6] is not None else None,
            can_login=bool(row[6]) and bool(row[7]),
            last_login_at=str(row[8]) if row[8] is not None else None,
            must_change_password=bool(int(row[9])) if row[9] is not None else False,
            totp_enabled=bool(row[10]),
            title=str(row[11]) if row[11] is not None else None,
        )

    async def get_user(self, user_id: int) -> Optional[UserRecord]:
        return await anyio.to_thread.run_sync(self._get_user_sync, int(user_id))

    def _update_user_sync(
        self,
        user_id: int,
        name: str,
        role: str,
        phone_e164: Optional[str],
        is_active: bool,
        login_name: Optional[str],
        password_salt: Optional[str],
        password_hash: Optional[str],
        clear_login: bool,
        title: Optional[str],
    ) -> None:
        with self._connect() as conn:
            if clear_login:
                conn.execute(
                    """
                    UPDATE users
                    SET name = ?, role = ?, phone_e164 = ?, is_active = ?, login_name = NULL, password_salt = NULL, password_hash = NULL, title = ?
                    WHERE id = ?;
                    """,
                    (name, role, phone_e164, 1 if is_active else 0, title, int(user_id)),
                )
                return

            if password_hash is not None and password_salt is not None:
                conn.execute(
                    """
                    UPDATE users
                    SET name = ?, role = ?, phone_e164 = ?, is_active = ?, login_name = ?, password_salt = ?, password_hash = ?, title = ?
                    WHERE id = ?;
                    """,
                    (
                        name,
                        role,
                        phone_e164,
                        1 if is_active else 0,
                        login_name,
                        password_salt,
                        password_hash,
                        title,
                        int(user_id),
                    ),
                )
                return

            conn.execute(
                """
                UPDATE users
                SET name = ?, role = ?, phone_e164 = ?, is_active = ?, login_name = ?, title = ?
                WHERE id = ?;
                """,
                (name, role, phone_e164, 1 if is_active else 0, login_name, title, int(user_id)),
            )

    async def update_user(
        self,
        *,
        user_id: int,
        name: str,
        role: str,
        phone_e164: Optional[str],
        is_active: bool,
        login_name: Optional[str],
        password: Optional[str],
        clear_login: bool,
        title: Optional[str] = None,
    ) -> None:
        normalized_login = login_name.strip().lower() if login_name else None
        password_salt = None
        password_hash = None
        if normalized_login and password:
            password_salt, password_hash = hash_password(password)
        normalized_title = title.strip() if title else None
        await anyio.to_thread.run_sync(
            self._update_user_sync,
            int(user_id),
            name,
            role,
            phone_e164,
            bool(is_active),
            normalized_login,
            password_salt,
            password_hash,
            bool(clear_login),
            normalized_title,
        )

    def _count_dashboard_admins_sync(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE role IN ('admin', 'district_admin')
                  AND is_active = 1
                  AND login_name IS NOT NULL
                  AND password_hash IS NOT NULL
                  AND password_salt IS NOT NULL;
                """
            ).fetchone()
        return int(row[0]) if row else 0

    async def count_dashboard_admins(self) -> int:
        return await anyio.to_thread.run_sync(self._count_dashboard_admins_sync)

    def _count_other_dashboard_admins_sync(self, excluded_user_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE id != ?
                  AND role IN ('admin', 'district_admin')
                  AND is_active = 1
                  AND login_name IS NOT NULL
                  AND password_hash IS NOT NULL
                  AND password_salt IS NOT NULL;
                """,
                (int(excluded_user_id),),
            ).fetchone()
        return int(row[0]) if row else 0

    async def count_other_dashboard_admins(self, excluded_user_id: int) -> int:
        return await anyio.to_thread.run_sync(self._count_other_dashboard_admins_sync, int(excluded_user_id))

    def _authenticate_user_sync(self, login_name: str, password: str) -> Optional[UserRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, name, role, phone_e164, is_active, login_name, password_salt, password_hash, last_login_at, must_change_password, totp_secret, title
                FROM users
                WHERE login_name = ?
                LIMIT 1;
                """,
                (login_name.strip().lower(),),
            ).fetchone()
        if row is None:
            return None
        if not bool(int(row[5])):
            return None
        password_salt = str(row[7]) if row[7] is not None else ""
        password_hash = str(row[8]) if row[8] is not None else ""
        if not password_salt or not password_hash:
            return None
        if not verify_password(password, salt_hex=password_salt, digest_hex=password_hash):
            return None
        return UserRecord(
            id=int(row[0]),
            created_at=str(row[1]),
            name=str(row[2]),
            role=str(row[3]),
            phone_e164=str(row[4]) if row[4] is not None else None,
            is_active=bool(int(row[5])),
            login_name=str(row[6]) if row[6] is not None else None,
            can_login=True,
            last_login_at=str(row[9]) if row[9] is not None else None,
            must_change_password=bool(int(row[10])) if row[10] is not None else False,
            totp_enabled=bool(row[11]),
            title=str(row[12]) if row[12] is not None else None,
        )

    async def authenticate_user(self, login_name: str, password: str) -> Optional[UserRecord]:
        return await anyio.to_thread.run_sync(self._authenticate_user_sync, login_name, password)

    def _authenticate_admin_sync(self, login_name: str, password: str) -> Optional[UserRecord]:
        user = self._authenticate_user_sync(login_name, password)
        if user is None or not is_dashboard_role(user.role):
            return None
        return user

    async def authenticate_admin(self, login_name: str, password: str) -> Optional[UserRecord]:
        return await anyio.to_thread.run_sync(self._authenticate_admin_sync, login_name, password)

    def _mark_login_sync(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?;",
                (datetime.now(timezone.utc).isoformat(), int(user_id)),
            )

    async def mark_login(self, user_id: int) -> None:
        await anyio.to_thread.run_sync(self._mark_login_sync, int(user_id))

    def _delete_user_sync(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?;", (int(user_id),))

    async def delete_user(self, user_id: int) -> None:
        await anyio.to_thread.run_sync(self._delete_user_sync, int(user_id))

    def _change_password_sync(self, user_id: int, password_salt: str, password_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_salt = ?, password_hash = ?, must_change_password = 0 WHERE id = ?;",
                (password_salt, password_hash, int(user_id)),
            )

    async def change_password(self, user_id: int, new_password: str) -> None:
        password_salt, password_hash = hash_password(new_password)
        await anyio.to_thread.run_sync(self._change_password_sync, int(user_id), password_salt, password_hash)

    def _get_totp_secret_sync(self, user_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT totp_secret FROM users WHERE id = ? LIMIT 1;",
                (int(user_id),),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return str(row[0])

    async def get_totp_secret(self, user_id: int) -> Optional[str]:
        return await anyio.to_thread.run_sync(self._get_totp_secret_sync, int(user_id))

    def _set_totp_secret_sync(self, user_id: int, secret: Optional[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET totp_secret = ? WHERE id = ?;",
                (secret, int(user_id)),
            )

    async def set_totp_secret(self, user_id: int, secret: Optional[str]) -> None:
        await anyio.to_thread.run_sync(self._set_totp_secret_sync, int(user_id), secret)

    def _verify_current_password_sync(self, user_id: int, password: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_salt, password_hash FROM users WHERE id = ? LIMIT 1;",
                (int(user_id),),
            ).fetchone()
        if row is None:
            return False
        password_salt = str(row[0]) if row[0] is not None else ""
        password_hash = str(row[1]) if row[1] is not None else ""
        if not password_salt or not password_hash:
            return False
        return verify_password(password, salt_hex=password_salt, digest_hex=password_hash)

    async def verify_current_password(self, user_id: int, password: str) -> bool:
        return await anyio.to_thread.run_sync(self._verify_current_password_sync, int(user_id), password)
