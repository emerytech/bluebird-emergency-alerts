from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import anyio


@dataclass(frozen=True)
class TenantBillingRecord:
    tenant_id: int
    plan_id: Optional[str]
    billing_status: str
    trial_start: Optional[str]
    trial_end: Optional[str]
    is_free_override: bool
    free_reason: Optional[str]
    stripe_customer_id: Optional[str]
    stripe_subscription_id: Optional[str]
    renewal_date: Optional[str]
    updated_at: str


class TenantBillingStore:
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
                CREATE TABLE IF NOT EXISTS tenant_billing (
                    tenant_id INTEGER PRIMARY KEY,
                    plan_id TEXT NULL,
                    billing_status TEXT NOT NULL DEFAULT 'trial',
                    trial_start TEXT NULL,
                    trial_end TEXT NULL,
                    is_free_override INTEGER NOT NULL DEFAULT 0,
                    free_reason TEXT NULL,
                    stripe_customer_id TEXT NULL,
                    stripe_subscription_id TEXT NULL,
                    renewal_date TEXT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row | tuple) -> TenantBillingRecord:
        return TenantBillingRecord(
            tenant_id=int(row[0]),
            plan_id=str(row[1]) if row[1] is not None else None,
            billing_status=str(row[2]),
            trial_start=str(row[3]) if row[3] is not None else None,
            trial_end=str(row[4]) if row[4] is not None else None,
            is_free_override=bool(int(row[5])),
            free_reason=str(row[6]) if row[6] is not None else None,
            stripe_customer_id=str(row[7]) if row[7] is not None else None,
            stripe_subscription_id=str(row[8]) if row[8] is not None else None,
            renewal_date=str(row[9]) if row[9] is not None else None,
            updated_at=str(row[10]),
        )

    def _ensure_tenant_billing_sync(self, tenant_id: int) -> TenantBillingRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tenant_billing (
                    tenant_id,
                    billing_status,
                    updated_at
                )
                VALUES (?, 'trial', ?)
                ON CONFLICT(tenant_id) DO NOTHING;
                """,
                (int(tenant_id), now),
            )
            row = conn.execute(
                """
                SELECT
                    tenant_id,
                    plan_id,
                    billing_status,
                    trial_start,
                    trial_end,
                    is_free_override,
                    free_reason,
                    stripe_customer_id,
                    stripe_subscription_id,
                    renewal_date,
                    updated_at
                FROM tenant_billing
                WHERE tenant_id = ?
                LIMIT 1;
                """,
                (int(tenant_id),),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    async def ensure_tenant_billing(self, *, tenant_id: int) -> TenantBillingRecord:
        return await anyio.to_thread.run_sync(self._ensure_tenant_billing_sync, int(tenant_id))

    def _get_tenant_billing_sync(self, tenant_id: int) -> Optional[TenantBillingRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    tenant_id,
                    plan_id,
                    billing_status,
                    trial_start,
                    trial_end,
                    is_free_override,
                    free_reason,
                    stripe_customer_id,
                    stripe_subscription_id,
                    renewal_date,
                    updated_at
                FROM tenant_billing
                WHERE tenant_id = ?
                LIMIT 1;
                """,
                (int(tenant_id),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def get_tenant_billing(self, *, tenant_id: int) -> Optional[TenantBillingRecord]:
        return await anyio.to_thread.run_sync(self._get_tenant_billing_sync, int(tenant_id))

    def _upsert_tenant_billing_sync(
        self,
        *,
        tenant_id: int,
        plan_id: Optional[str],
        billing_status: str,
        trial_start: Optional[str],
        trial_end: Optional[str],
        is_free_override: bool,
        free_reason: Optional[str],
        stripe_customer_id: Optional[str],
        stripe_subscription_id: Optional[str],
        renewal_date: Optional[str],
    ) -> TenantBillingRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tenant_billing (
                    tenant_id,
                    plan_id,
                    billing_status,
                    trial_start,
                    trial_end,
                    is_free_override,
                    free_reason,
                    stripe_customer_id,
                    stripe_subscription_id,
                    renewal_date,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    plan_id = excluded.plan_id,
                    billing_status = excluded.billing_status,
                    trial_start = excluded.trial_start,
                    trial_end = excluded.trial_end,
                    is_free_override = excluded.is_free_override,
                    free_reason = excluded.free_reason,
                    stripe_customer_id = excluded.stripe_customer_id,
                    stripe_subscription_id = excluded.stripe_subscription_id,
                    renewal_date = excluded.renewal_date,
                    updated_at = excluded.updated_at;
                """,
                (
                    int(tenant_id),
                    plan_id,
                    billing_status.strip().lower(),
                    trial_start,
                    trial_end,
                    1 if is_free_override else 0,
                    free_reason,
                    stripe_customer_id,
                    stripe_subscription_id,
                    renewal_date,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT
                    tenant_id,
                    plan_id,
                    billing_status,
                    trial_start,
                    trial_end,
                    is_free_override,
                    free_reason,
                    stripe_customer_id,
                    stripe_subscription_id,
                    renewal_date,
                    updated_at
                FROM tenant_billing
                WHERE tenant_id = ?
                LIMIT 1;
                """,
                (int(tenant_id),),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    async def upsert_tenant_billing(
        self,
        *,
        tenant_id: int,
        plan_id: Optional[str],
        billing_status: str,
        trial_start: Optional[str],
        trial_end: Optional[str],
        is_free_override: bool,
        free_reason: Optional[str],
        stripe_customer_id: Optional[str],
        stripe_subscription_id: Optional[str],
        renewal_date: Optional[str],
    ) -> TenantBillingRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._upsert_tenant_billing_sync(
                tenant_id=int(tenant_id),
                plan_id=plan_id,
                billing_status=billing_status,
                trial_start=trial_start,
                trial_end=trial_end,
                is_free_override=bool(is_free_override),
                free_reason=free_reason,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription_id,
                renewal_date=renewal_date,
            )
        )

