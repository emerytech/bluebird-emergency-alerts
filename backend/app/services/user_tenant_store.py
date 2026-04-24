from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

import anyio


@dataclass(frozen=True)
class UserTenantAssignmentRecord:
    id: int
    created_at: str
    user_id: int
    home_tenant_id: int
    tenant_id: int
    role_for_tenant: Optional[str]


class UserTenantStore:
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
                CREATE TABLE IF NOT EXISTS user_tenants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    home_tenant_id INTEGER NOT NULL,
                    tenant_id INTEGER NOT NULL,
                    role_for_tenant TEXT NULL,
                    UNIQUE(user_id, home_tenant_id, tenant_id)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_tenants_user_home ON user_tenants(user_id, home_tenant_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_tenants_tenant_id ON user_tenants(tenant_id);"
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row | tuple) -> UserTenantAssignmentRecord:
        return UserTenantAssignmentRecord(
            id=int(row[0]),
            created_at=str(row[1]),
            user_id=int(row[2]),
            home_tenant_id=int(row[3]),
            tenant_id=int(row[4]),
            role_for_tenant=str(row[5]) if row[5] is not None else None,
        )

    def _list_assignments_sync(self, *, user_id: int, home_tenant_id: int) -> list[UserTenantAssignmentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, user_id, home_tenant_id, tenant_id, role_for_tenant
                FROM user_tenants
                WHERE user_id = ? AND home_tenant_id = ?
                ORDER BY tenant_id ASC;
                """,
                (int(user_id), int(home_tenant_id)),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    async def list_assignments(self, *, user_id: int, home_tenant_id: int) -> list[UserTenantAssignmentRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._list_assignments_sync(
                user_id=int(user_id),
                home_tenant_id=int(home_tenant_id),
            )
        )

    def _list_assignments_for_users_sync(
        self,
        *,
        home_tenant_id: int,
        user_ids: list[int],
    ) -> list[UserTenantAssignmentRecord]:
        if not user_ids:
            return []
        placeholders = ",".join(["?"] * len(user_ids))
        params: tuple[object, ...] = (int(home_tenant_id),) + tuple(int(user_id) for user_id in user_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, created_at, user_id, home_tenant_id, tenant_id, role_for_tenant
                FROM user_tenants
                WHERE home_tenant_id = ?
                  AND user_id IN ({placeholders})
                ORDER BY user_id ASC, tenant_id ASC;
                """,
                params,
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    async def list_assignments_for_users(
        self,
        *,
        home_tenant_id: int,
        user_ids: Iterable[int],
    ) -> list[UserTenantAssignmentRecord]:
        normalized_ids = sorted({int(user_id) for user_id in user_ids if int(user_id) > 0})
        return await anyio.to_thread.run_sync(
            lambda: self._list_assignments_for_users_sync(
                home_tenant_id=int(home_tenant_id),
                user_ids=normalized_ids,
            )
        )

    def _list_assignments_for_tenant_user_sync(
        self,
        *,
        tenant_id: int,
        user_id: int,
    ) -> list[UserTenantAssignmentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, user_id, home_tenant_id, tenant_id, role_for_tenant
                FROM user_tenants
                WHERE tenant_id = ? AND user_id = ?
                ORDER BY id ASC;
                """,
                (int(tenant_id), int(user_id)),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    async def list_assignments_for_tenant_user(
        self,
        *,
        tenant_id: int,
        user_id: int,
    ) -> list[UserTenantAssignmentRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._list_assignments_for_tenant_user_sync(
                tenant_id=int(tenant_id),
                user_id=int(user_id),
            )
        )

    def _replace_assignments_sync(
        self,
        *,
        user_id: int,
        home_tenant_id: int,
        tenant_ids: list[int],
        role_for_tenant: Optional[str],
    ) -> None:
        normalized_tenant_ids = sorted({int(tenant_id) for tenant_id in tenant_ids if int(tenant_id) > 0})
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            if normalized_tenant_ids:
                placeholders = ",".join(["?"] * len(normalized_tenant_ids))
                conn.execute(
                    f"""
                    DELETE FROM user_tenants
                    WHERE user_id = ?
                      AND home_tenant_id = ?
                      AND tenant_id NOT IN ({placeholders});
                    """,
                    (int(user_id), int(home_tenant_id), *normalized_tenant_ids),
                )
            else:
                conn.execute(
                    "DELETE FROM user_tenants WHERE user_id = ? AND home_tenant_id = ?;",
                    (int(user_id), int(home_tenant_id)),
                )
            for tenant_id in normalized_tenant_ids:
                conn.execute(
                    """
                    INSERT INTO user_tenants (
                        created_at,
                        user_id,
                        home_tenant_id,
                        tenant_id,
                        role_for_tenant
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, home_tenant_id, tenant_id)
                    DO UPDATE SET role_for_tenant = excluded.role_for_tenant;
                    """,
                    (
                        created_at,
                        int(user_id),
                        int(home_tenant_id),
                        int(tenant_id),
                        role_for_tenant.strip().lower() if role_for_tenant else None,
                    ),
                )

    async def replace_assignments(
        self,
        *,
        user_id: int,
        home_tenant_id: int,
        tenant_ids: Iterable[int],
        role_for_tenant: Optional[str] = None,
    ) -> None:
        normalized_tenant_ids = sorted({int(tenant_id) for tenant_id in tenant_ids if int(tenant_id) > 0})
        await anyio.to_thread.run_sync(
            lambda: self._replace_assignments_sync(
                user_id=int(user_id),
                home_tenant_id=int(home_tenant_id),
                tenant_ids=normalized_tenant_ids,
                role_for_tenant=role_for_tenant,
            )
        )
