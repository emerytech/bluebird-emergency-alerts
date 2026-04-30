from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import anyio


# ── Records ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TenantBillingRecord:
    tenant_id: int
    tenant_slug: Optional[str]
    district_id: Optional[int]
    customer_name: Optional[str]
    customer_email: Optional[str]
    # Plan
    plan_id: Optional[str]       # legacy alias; prefer plan_type
    plan_type: str               # trial | basic | pro | enterprise
    # Status
    billing_status: str          # trial | active | past_due | expired | suspended | cancelled | manual_override
    # License
    license_key: Optional[str]
    # Dates
    starts_at: Optional[str]
    trial_start: Optional[str]   # legacy
    trial_end: Optional[str]     # legacy alias; prefer trial_ends_at
    trial_ends_at: Optional[str]
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    renewal_date: Optional[str]
    # Override
    is_free_override: bool       # legacy alias; prefer override_enabled
    free_reason: Optional[str]   # legacy alias; prefer override_reason
    override_enabled: bool
    override_reason: Optional[str]
    # Meta
    internal_notes: Optional[str]
    created_at: Optional[str]
    updated_at: str
    # Stripe (Phase 10 ready — not called yet)
    stripe_customer_id: Optional[str]
    stripe_subscription_id: Optional[str]
    stripe_price_id: Optional[str]
    stripe_checkout_session_id: Optional[str]
    # Archive (district billing only; defaults keep all existing code working)
    is_archived: bool = False
    archived_at: Optional[str] = None
    archived_by: Optional[str] = None


@dataclass(frozen=True)
class BillingAuditRecord:
    id: int
    district_id: int
    event_type: str   # license_created | license_archived | license_restored | license_deleted | status_changed | ...
    actor: str
    detail: Optional[str]
    created_at: str


@dataclass(frozen=True)
class PaymentRecord:
    id: int
    tenant_slug: str
    amount: float
    currency: str
    payment_date: str
    payment_method: str          # check | cash | card | ACH | manual | stripe_future
    reference_number: Optional[str]
    notes: Optional[str]
    recorded_by: str
    created_at: str


@dataclass(frozen=True)
class InvoiceRecord:
    id: int
    invoice_number: str
    tenant_slug: str
    amount_due: float
    due_date: str
    status: str                  # draft | sent | paid | overdue | void
    notes: Optional[str]
    created_at: str
    updated_at: str


# ── Column selects ─────────────────────────────────────────────────────────────

_BILLING_COLS = """
    tenant_id, tenant_slug, district_id, customer_name, customer_email,
    plan_id, plan_type, billing_status, license_key,
    starts_at, trial_start, trial_end, trial_ends_at,
    current_period_start, current_period_end, renewal_date,
    is_free_override, free_reason, override_enabled, override_reason,
    internal_notes, created_at, updated_at,
    stripe_customer_id, stripe_subscription_id, stripe_price_id, stripe_checkout_session_id
"""

_PAYMENT_COLS = "id, tenant_slug, amount, currency, payment_date, payment_method, reference_number, notes, recorded_by, created_at"

_INVOICE_COLS = "id, invoice_number, tenant_slug, amount_due, due_date, status, notes, created_at, updated_at"

# district_billing column list — district_id is PK; rows convert to TenantBillingRecord(tenant_id=0)
_DISTRICT_BILLING_COLS = """
    district_id, customer_name, customer_email,
    plan_id, plan_type, billing_status, license_key,
    starts_at, trial_start, trial_end, trial_ends_at,
    current_period_start, current_period_end, renewal_date,
    is_free_override, free_reason, override_enabled, override_reason,
    internal_notes, created_at, updated_at,
    stripe_customer_id, stripe_subscription_id, stripe_price_id, stripe_checkout_session_id,
    is_archived, archived_at, archived_by
"""

_BILLING_AUDIT_COLS = "id, district_id, event_type, actor, detail, created_at"


# ── Store ──────────────────────────────────────────────────────────────────────


class TenantBillingStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_billing (
                    tenant_id              INTEGER PRIMARY KEY,
                    tenant_slug            TEXT NULL,
                    district_id            INTEGER NULL,
                    customer_name          TEXT NULL,
                    customer_email         TEXT NULL,
                    plan_id                TEXT NULL,
                    plan_type              TEXT NOT NULL DEFAULT 'trial',
                    billing_status         TEXT NOT NULL DEFAULT 'trial',
                    license_key            TEXT NULL,
                    starts_at              TEXT NULL,
                    trial_start            TEXT NULL,
                    trial_end              TEXT NULL,
                    trial_ends_at          TEXT NULL,
                    current_period_start   TEXT NULL,
                    current_period_end     TEXT NULL,
                    renewal_date           TEXT NULL,
                    is_free_override       INTEGER NOT NULL DEFAULT 0,
                    free_reason            TEXT NULL,
                    override_enabled       INTEGER NOT NULL DEFAULT 0,
                    override_reason        TEXT NULL,
                    internal_notes         TEXT NULL,
                    created_at             TEXT NULL,
                    updated_at             TEXT NOT NULL,
                    stripe_customer_id     TEXT NULL,
                    stripe_subscription_id TEXT NULL,
                    stripe_price_id        TEXT NULL,
                    stripe_checkout_session_id TEXT NULL
                );
                """
            )
            self._migrate_billing_table(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS billing_payment_records (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_slug      TEXT NOT NULL,
                    amount           REAL NOT NULL DEFAULT 0,
                    currency         TEXT NOT NULL DEFAULT 'USD',
                    payment_date     TEXT NOT NULL,
                    payment_method   TEXT NOT NULL DEFAULT 'manual',
                    reference_number TEXT NULL,
                    notes            TEXT NULL,
                    recorded_by      TEXT NOT NULL DEFAULT '',
                    created_at       TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_billing_payments_slug
                    ON billing_payment_records(tenant_slug);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS billing_invoices (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number TEXT NOT NULL UNIQUE,
                    tenant_slug    TEXT NOT NULL,
                    amount_due     REAL NOT NULL DEFAULT 0,
                    due_date       TEXT NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'draft',
                    notes          TEXT NULL,
                    created_at     TEXT NOT NULL,
                    updated_at     TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_billing_invoices_slug
                    ON billing_invoices(tenant_slug);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS district_billing (
                    district_id            INTEGER PRIMARY KEY,
                    customer_name          TEXT NULL,
                    customer_email         TEXT NULL,
                    plan_id                TEXT NULL,
                    plan_type              TEXT NOT NULL DEFAULT 'trial',
                    billing_status         TEXT NOT NULL DEFAULT 'trial',
                    license_key            TEXT NULL,
                    starts_at              TEXT NULL,
                    trial_start            TEXT NULL,
                    trial_end              TEXT NULL,
                    trial_ends_at          TEXT NULL,
                    current_period_start   TEXT NULL,
                    current_period_end     TEXT NULL,
                    renewal_date           TEXT NULL,
                    is_free_override       INTEGER NOT NULL DEFAULT 0,
                    free_reason            TEXT NULL,
                    override_enabled       INTEGER NOT NULL DEFAULT 0,
                    override_reason        TEXT NULL,
                    internal_notes         TEXT NULL,
                    created_at             TEXT NULL,
                    updated_at             TEXT NOT NULL,
                    stripe_customer_id     TEXT NULL,
                    stripe_subscription_id TEXT NULL,
                    stripe_price_id        TEXT NULL,
                    stripe_checkout_session_id TEXT NULL,
                    is_archived            INTEGER NOT NULL DEFAULT 0,
                    archived_at            TEXT NULL,
                    archived_by            TEXT NULL
                );
                """
            )
            self._migrate_district_billing_table(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS district_billing_audit_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    district_id INTEGER NOT NULL,
                    event_type  TEXT NOT NULL,
                    actor       TEXT NOT NULL DEFAULT '',
                    detail      TEXT NULL,
                    created_at  TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_district_billing_audit_district
                    ON district_billing_audit_log(district_id);
                """
            )

    def _migrate_billing_table(self, conn: sqlite3.Connection) -> None:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(tenant_billing);").fetchall()}
        migrations = [
            ("tenant_slug",                "TEXT NULL"),
            ("district_id",                "INTEGER NULL"),
            ("customer_name",              "TEXT NULL"),
            ("customer_email",             "TEXT NULL"),
            ("plan_type",                  "TEXT NOT NULL DEFAULT 'trial'"),
            ("license_key",                "TEXT NULL"),
            ("starts_at",                  "TEXT NULL"),
            ("trial_ends_at",              "TEXT NULL"),
            ("current_period_start",       "TEXT NULL"),
            ("current_period_end",         "TEXT NULL"),
            ("override_enabled",           "INTEGER NOT NULL DEFAULT 0"),
            ("override_reason",            "TEXT NULL"),
            ("internal_notes",             "TEXT NULL"),
            ("created_at",                 "TEXT NULL"),
            ("stripe_price_id",            "TEXT NULL"),
            ("stripe_checkout_session_id", "TEXT NULL"),
        ]
        for col, defn in migrations:
            if col not in existing:
                conn.execute(f"ALTER TABLE tenant_billing ADD COLUMN {col} {defn};")

    def _migrate_district_billing_table(self, conn: sqlite3.Connection) -> None:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(district_billing);").fetchall()}
        migrations = [
            ("is_archived",          "INTEGER NOT NULL DEFAULT 0"),
            ("archived_at",          "TEXT NULL"),
            ("archived_by",          "TEXT NULL"),
            ("stripe_product_id",    "TEXT NULL"),
            ("cancel_at_period_end", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for col, defn in migrations:
            if col not in existing:
                conn.execute(f"ALTER TABLE district_billing ADD COLUMN {col} {defn};")

    # ── Row → record helpers ───────────────────────────────────────────────────

    @staticmethod
    def _billing_row_to_record(row: tuple) -> TenantBillingRecord:
        (
            tenant_id, tenant_slug, district_id, customer_name, customer_email,
            plan_id, plan_type, billing_status, license_key,
            starts_at, trial_start, trial_end, trial_ends_at,
            current_period_start, current_period_end, renewal_date,
            is_free_override, free_reason, override_enabled, override_reason,
            internal_notes, created_at, updated_at,
            stripe_customer_id, stripe_subscription_id, stripe_price_id,
            stripe_checkout_session_id,
        ) = row
        return TenantBillingRecord(
            tenant_id=int(tenant_id),
            tenant_slug=str(tenant_slug) if tenant_slug is not None else None,
            district_id=int(district_id) if district_id is not None else None,
            customer_name=str(customer_name) if customer_name is not None else None,
            customer_email=str(customer_email) if customer_email is not None else None,
            plan_id=str(plan_id) if plan_id is not None else None,
            plan_type=str(plan_type or "trial"),
            billing_status=str(billing_status or "trial"),
            license_key=str(license_key) if license_key is not None else None,
            starts_at=str(starts_at) if starts_at is not None else None,
            trial_start=str(trial_start) if trial_start is not None else None,
            trial_end=str(trial_end) if trial_end is not None else None,
            trial_ends_at=str(trial_ends_at) if trial_ends_at is not None else None,
            current_period_start=str(current_period_start) if current_period_start is not None else None,
            current_period_end=str(current_period_end) if current_period_end is not None else None,
            renewal_date=str(renewal_date) if renewal_date is not None else None,
            is_free_override=bool(int(is_free_override or 0)),
            free_reason=str(free_reason) if free_reason is not None else None,
            override_enabled=bool(int(override_enabled or 0)),
            override_reason=str(override_reason) if override_reason is not None else None,
            internal_notes=str(internal_notes) if internal_notes is not None else None,
            created_at=str(created_at) if created_at is not None else None,
            updated_at=str(updated_at),
            stripe_customer_id=str(stripe_customer_id) if stripe_customer_id is not None else None,
            stripe_subscription_id=str(stripe_subscription_id) if stripe_subscription_id is not None else None,
            stripe_price_id=str(stripe_price_id) if stripe_price_id is not None else None,
            stripe_checkout_session_id=str(stripe_checkout_session_id) if stripe_checkout_session_id is not None else None,
        )

    @staticmethod
    def _payment_row_to_record(row: tuple) -> PaymentRecord:
        id_, tenant_slug, amount, currency, payment_date, payment_method, reference_number, notes, recorded_by, created_at = row
        return PaymentRecord(
            id=int(id_),
            tenant_slug=str(tenant_slug),
            amount=float(amount),
            currency=str(currency),
            payment_date=str(payment_date),
            payment_method=str(payment_method),
            reference_number=str(reference_number) if reference_number is not None else None,
            notes=str(notes) if notes is not None else None,
            recorded_by=str(recorded_by),
            created_at=str(created_at),
        )

    @staticmethod
    def _invoice_row_to_record(row: tuple) -> InvoiceRecord:
        id_, invoice_number, tenant_slug, amount_due, due_date, status, notes, created_at, updated_at = row
        return InvoiceRecord(
            id=int(id_),
            invoice_number=str(invoice_number),
            tenant_slug=str(tenant_slug),
            amount_due=float(amount_due),
            due_date=str(due_date),
            status=str(status),
            notes=str(notes) if notes is not None else None,
            created_at=str(created_at),
            updated_at=str(updated_at),
        )

    # ── Ensure / Get / List ────────────────────────────────────────────────────

    def _ensure_tenant_billing_sync(self, tenant_id: int) -> TenantBillingRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tenant_billing (tenant_id, billing_status, plan_type, updated_at, created_at) "
                "VALUES (?, 'trial', 'trial', ?, ?) ON CONFLICT(tenant_id) DO NOTHING;",
                (int(tenant_id), now, now),
            )
            row = conn.execute(
                f"SELECT {_BILLING_COLS} FROM tenant_billing WHERE tenant_id = ? LIMIT 1;",
                (int(tenant_id),),
            ).fetchone()
        assert row is not None
        return self._billing_row_to_record(row)

    async def ensure_tenant_billing(self, *, tenant_id: int) -> TenantBillingRecord:
        return await anyio.to_thread.run_sync(self._ensure_tenant_billing_sync, int(tenant_id))

    def _get_tenant_billing_sync(self, tenant_id: int) -> Optional[TenantBillingRecord]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_BILLING_COLS} FROM tenant_billing WHERE tenant_id = ? LIMIT 1;",
                (int(tenant_id),),
            ).fetchone()
        return self._billing_row_to_record(row) if row is not None else None

    async def get_tenant_billing(self, *, tenant_id: int) -> Optional[TenantBillingRecord]:
        return await anyio.to_thread.run_sync(self._get_tenant_billing_sync, int(tenant_id))

    def _get_by_slug_sync(self, tenant_slug: str) -> Optional[TenantBillingRecord]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_BILLING_COLS} FROM tenant_billing WHERE tenant_slug = ? LIMIT 1;",
                (str(tenant_slug),),
            ).fetchone()
        return self._billing_row_to_record(row) if row is not None else None

    async def get_by_slug(self, *, tenant_slug: str) -> Optional[TenantBillingRecord]:
        return await anyio.to_thread.run_sync(self._get_by_slug_sync, str(tenant_slug))

    def _list_all_sync(self) -> List[TenantBillingRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_BILLING_COLS} FROM tenant_billing ORDER BY updated_at DESC;"
            ).fetchall()
        return [self._billing_row_to_record(r) for r in rows]

    async def list_all(self) -> List[TenantBillingRecord]:
        return await anyio.to_thread.run_sync(self._list_all_sync)

    # ── Upsert (legacy-compat signature) ──────────────────────────────────────

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
                f"""
                INSERT INTO tenant_billing (
                    tenant_id, plan_id, plan_type, billing_status, trial_start, trial_end,
                    is_free_override, free_reason, override_enabled, override_reason,
                    stripe_customer_id, stripe_subscription_id, renewal_date,
                    updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    plan_id                = excluded.plan_id,
                    plan_type              = COALESCE(plan_type, excluded.plan_type),
                    billing_status         = excluded.billing_status,
                    trial_start            = excluded.trial_start,
                    trial_end              = excluded.trial_end,
                    is_free_override       = excluded.is_free_override,
                    free_reason            = excluded.free_reason,
                    override_enabled       = excluded.override_enabled,
                    override_reason        = excluded.override_reason,
                    stripe_customer_id     = excluded.stripe_customer_id,
                    stripe_subscription_id = excluded.stripe_subscription_id,
                    renewal_date           = excluded.renewal_date,
                    updated_at             = excluded.updated_at;
                """,
                (
                    int(tenant_id),
                    plan_id,
                    plan_id or "trial",
                    billing_status.strip().lower(),
                    trial_start,
                    trial_end,
                    1 if is_free_override else 0,
                    free_reason,
                    1 if is_free_override else 0,
                    free_reason,
                    stripe_customer_id,
                    stripe_subscription_id,
                    renewal_date,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                f"SELECT {_BILLING_COLS} FROM tenant_billing WHERE tenant_id = ? LIMIT 1;",
                (int(tenant_id),),
            ).fetchone()
        assert row is not None
        return self._billing_row_to_record(row)

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

    # ── Full update (new comprehensive method) ─────────────────────────────────

    def _update_billing_full_sync(
        self,
        *,
        tenant_id: int,
        tenant_slug: Optional[str] = None,
        district_id: Optional[int] = None,
        customer_name: Optional[str] = None,
        customer_email: Optional[str] = None,
        plan_type: Optional[str] = None,
        billing_status: Optional[str] = None,
        license_key: Optional[str] = None,
        starts_at: Optional[str] = None,
        trial_ends_at: Optional[str] = None,
        current_period_start: Optional[str] = None,
        current_period_end: Optional[str] = None,
        renewal_date: Optional[str] = None,
        override_enabled: Optional[bool] = None,
        override_reason: Optional[str] = None,
        internal_notes: Optional[str] = None,
    ) -> TenantBillingRecord:
        now = datetime.now(timezone.utc).isoformat()
        fields: list[str] = []
        params: list[object] = []

        def _set(col: str, val: object) -> None:
            fields.append(f"{col} = ?")
            params.append(val)

        if tenant_slug is not None:
            _set("tenant_slug", tenant_slug)
        if district_id is not None:
            _set("district_id", int(district_id))
        if customer_name is not None:
            _set("customer_name", customer_name)
        if customer_email is not None:
            _set("customer_email", customer_email)
        if plan_type is not None:
            _set("plan_type", plan_type.strip().lower())
            _set("plan_id", plan_type.strip().lower())
        if billing_status is not None:
            _set("billing_status", billing_status.strip().lower())
        if license_key is not None:
            _set("license_key", license_key)
        if starts_at is not None:
            _set("starts_at", starts_at)
        if trial_ends_at is not None:
            _set("trial_ends_at", trial_ends_at)
            _set("trial_end", trial_ends_at)
        if current_period_start is not None:
            _set("current_period_start", current_period_start)
        if current_period_end is not None:
            _set("current_period_end", current_period_end)
            _set("renewal_date", current_period_end)
        if renewal_date is not None:
            _set("renewal_date", renewal_date)
        if override_enabled is not None:
            v = 1 if override_enabled else 0
            _set("override_enabled", v)
            _set("is_free_override", v)
        if override_reason is not None:
            _set("override_reason", override_reason)
            _set("free_reason", override_reason)
        if internal_notes is not None:
            _set("internal_notes", internal_notes)

        fields.append("updated_at = ?")
        params.append(now)
        params.append(int(tenant_id))

        with self._connect() as conn:
            # Ensure row exists first
            conn.execute(
                "INSERT INTO tenant_billing (tenant_id, billing_status, plan_type, updated_at, created_at) "
                "VALUES (?, 'trial', 'trial', ?, ?) ON CONFLICT(tenant_id) DO NOTHING;",
                (int(tenant_id), now, now),
            )
            if fields:
                conn.execute(
                    f"UPDATE tenant_billing SET {', '.join(fields)} WHERE tenant_id = ?;",
                    params,
                )
            row = conn.execute(
                f"SELECT {_BILLING_COLS} FROM tenant_billing WHERE tenant_id = ? LIMIT 1;",
                (int(tenant_id),),
            ).fetchone()
        assert row is not None
        return self._billing_row_to_record(row)

    async def update_billing_full(
        self,
        *,
        tenant_id: int,
        tenant_slug: Optional[str] = None,
        district_id: Optional[int] = None,
        customer_name: Optional[str] = None,
        customer_email: Optional[str] = None,
        plan_type: Optional[str] = None,
        billing_status: Optional[str] = None,
        license_key: Optional[str] = None,
        starts_at: Optional[str] = None,
        trial_ends_at: Optional[str] = None,
        current_period_start: Optional[str] = None,
        current_period_end: Optional[str] = None,
        renewal_date: Optional[str] = None,
        override_enabled: Optional[bool] = None,
        override_reason: Optional[str] = None,
        internal_notes: Optional[str] = None,
    ) -> TenantBillingRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._update_billing_full_sync(
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                district_id=district_id,
                customer_name=customer_name,
                customer_email=customer_email,
                plan_type=plan_type,
                billing_status=billing_status,
                license_key=license_key,
                starts_at=starts_at,
                trial_ends_at=trial_ends_at,
                current_period_start=current_period_start,
                current_period_end=current_period_end,
                renewal_date=renewal_date,
                override_enabled=override_enabled,
                override_reason=override_reason,
                internal_notes=internal_notes,
            )
        )

    # ── Payments ───────────────────────────────────────────────────────────────

    def _add_payment_sync(
        self,
        *,
        tenant_slug: str,
        amount: float,
        currency: str,
        payment_date: str,
        payment_method: str,
        reference_number: Optional[str],
        notes: Optional[str],
        recorded_by: str,
    ) -> PaymentRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO billing_payment_records
                    (tenant_slug, amount, currency, payment_date, payment_method,
                     reference_number, notes, recorded_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (tenant_slug, amount, currency, payment_date, payment_method,
                 reference_number, notes, recorded_by, now),
            )
            row = conn.execute(
                f"SELECT {_PAYMENT_COLS} FROM billing_payment_records WHERE id = ?;",
                (cur.lastrowid,),
            ).fetchone()
        assert row is not None
        return self._payment_row_to_record(row)

    async def add_payment(
        self,
        *,
        tenant_slug: str,
        amount: float,
        currency: str = "USD",
        payment_date: str,
        payment_method: str,
        reference_number: Optional[str] = None,
        notes: Optional[str] = None,
        recorded_by: str,
    ) -> PaymentRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._add_payment_sync(
                tenant_slug=tenant_slug,
                amount=float(amount),
                currency=currency,
                payment_date=payment_date,
                payment_method=payment_method,
                reference_number=reference_number,
                notes=notes,
                recorded_by=recorded_by,
            )
        )

    def _list_payments_sync(self, tenant_slug: str, limit: int) -> List[PaymentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_PAYMENT_COLS} FROM billing_payment_records "
                f"WHERE tenant_slug = ? ORDER BY payment_date DESC LIMIT ?;",
                (tenant_slug, int(limit)),
            ).fetchall()
        return [self._payment_row_to_record(r) for r in rows]

    async def list_payments(self, *, tenant_slug: str, limit: int = 50) -> List[PaymentRecord]:
        return await anyio.to_thread.run_sync(lambda: self._list_payments_sync(tenant_slug, limit))

    # ── Invoices ───────────────────────────────────────────────────────────────

    def _create_invoice_sync(
        self,
        *,
        invoice_number: str,
        tenant_slug: str,
        amount_due: float,
        due_date: str,
        notes: Optional[str],
    ) -> InvoiceRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO billing_invoices
                    (invoice_number, tenant_slug, amount_due, due_date, status, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'draft', ?, ?, ?);
                """,
                (invoice_number, tenant_slug, float(amount_due), due_date, notes, now, now),
            )
            row = conn.execute(
                f"SELECT {_INVOICE_COLS} FROM billing_invoices WHERE id = ?;",
                (cur.lastrowid,),
            ).fetchone()
        assert row is not None
        return self._invoice_row_to_record(row)

    async def create_invoice(
        self,
        *,
        invoice_number: str,
        tenant_slug: str,
        amount_due: float,
        due_date: str,
        notes: Optional[str] = None,
    ) -> InvoiceRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._create_invoice_sync(
                invoice_number=invoice_number,
                tenant_slug=tenant_slug,
                amount_due=float(amount_due),
                due_date=due_date,
                notes=notes,
            )
        )

    def _update_invoice_status_sync(self, invoice_id: int, new_status: str) -> Optional[InvoiceRecord]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE billing_invoices SET status = ?, updated_at = ? WHERE id = ?;",
                (new_status.strip().lower(), now, int(invoice_id)),
            )
            row = conn.execute(
                f"SELECT {_INVOICE_COLS} FROM billing_invoices WHERE id = ?;",
                (int(invoice_id),),
            ).fetchone()
        return self._invoice_row_to_record(row) if row is not None else None

    async def update_invoice_status(self, *, invoice_id: int, new_status: str) -> Optional[InvoiceRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._update_invoice_status_sync(int(invoice_id), new_status)
        )

    def _list_invoices_sync(self, tenant_slug: str, limit: int) -> List[InvoiceRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_INVOICE_COLS} FROM billing_invoices "
                f"WHERE tenant_slug = ? ORDER BY created_at DESC LIMIT ?;",
                (tenant_slug, int(limit)),
            ).fetchall()
        return [self._invoice_row_to_record(r) for r in rows]

    async def list_invoices(self, *, tenant_slug: str, limit: int = 50) -> List[InvoiceRecord]:
        return await anyio.to_thread.run_sync(lambda: self._list_invoices_sync(tenant_slug, limit))

    # ── Legacy row-to-record (kept for any callers using old positional form) ──

    @staticmethod
    def _row_to_record(row: tuple) -> TenantBillingRecord:
        return TenantBillingStore._billing_row_to_record(row)  # type: ignore[arg-type]

    # ── District billing ───────────────────────────────────────────────────────
    # Returns TenantBillingRecord with tenant_id=0 so all enforcement functions
    # work without modification. Callers that need the real tenant_id must
    # supply it themselves (e.g. wrap the result in a replace call).

    @staticmethod
    def _district_row_to_record(row: tuple) -> TenantBillingRecord:
        (
            district_id, customer_name, customer_email,
            plan_id, plan_type, billing_status, license_key,
            starts_at, trial_start, trial_end, trial_ends_at,
            current_period_start, current_period_end, renewal_date,
            is_free_override, free_reason, override_enabled, override_reason,
            internal_notes, created_at, updated_at,
            stripe_customer_id, stripe_subscription_id, stripe_price_id,
            stripe_checkout_session_id,
            is_archived, archived_at, archived_by,
        ) = row
        return TenantBillingRecord(
            tenant_id=0,
            tenant_slug=None,
            district_id=int(district_id),
            customer_name=str(customer_name) if customer_name is not None else None,
            customer_email=str(customer_email) if customer_email is not None else None,
            plan_id=str(plan_id) if plan_id is not None else None,
            plan_type=str(plan_type or "trial"),
            billing_status=str(billing_status or "trial"),
            license_key=str(license_key) if license_key is not None else None,
            starts_at=str(starts_at) if starts_at is not None else None,
            trial_start=str(trial_start) if trial_start is not None else None,
            trial_end=str(trial_end) if trial_end is not None else None,
            trial_ends_at=str(trial_ends_at) if trial_ends_at is not None else None,
            current_period_start=str(current_period_start) if current_period_start is not None else None,
            current_period_end=str(current_period_end) if current_period_end is not None else None,
            renewal_date=str(renewal_date) if renewal_date is not None else None,
            is_free_override=bool(int(is_free_override or 0)),
            free_reason=str(free_reason) if free_reason is not None else None,
            override_enabled=bool(int(override_enabled or 0)),
            override_reason=str(override_reason) if override_reason is not None else None,
            internal_notes=str(internal_notes) if internal_notes is not None else None,
            created_at=str(created_at) if created_at is not None else None,
            updated_at=str(updated_at),
            stripe_customer_id=str(stripe_customer_id) if stripe_customer_id is not None else None,
            stripe_subscription_id=str(stripe_subscription_id) if stripe_subscription_id is not None else None,
            stripe_price_id=str(stripe_price_id) if stripe_price_id is not None else None,
            stripe_checkout_session_id=str(stripe_checkout_session_id) if stripe_checkout_session_id is not None else None,
            is_archived=bool(int(is_archived or 0)),
            archived_at=str(archived_at) if archived_at is not None else None,
            archived_by=str(archived_by) if archived_by is not None else None,
        )

    @staticmethod
    def _billing_audit_row_to_record(row: tuple) -> "BillingAuditRecord":
        id_, district_id, event_type, actor, detail, created_at = row
        return BillingAuditRecord(
            id=int(id_),
            district_id=int(district_id),
            event_type=str(event_type),
            actor=str(actor),
            detail=str(detail) if detail is not None else None,
            created_at=str(created_at),
        )

    def _ensure_district_billing_sync(self, district_id: int) -> TenantBillingRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO district_billing (district_id, billing_status, plan_type, updated_at, created_at) "
                "VALUES (?, 'trial', 'trial', ?, ?) ON CONFLICT(district_id) DO NOTHING;",
                (int(district_id), now, now),
            )
            row = conn.execute(
                f"SELECT {_DISTRICT_BILLING_COLS} FROM district_billing WHERE district_id = ? LIMIT 1;",
                (int(district_id),),
            ).fetchone()
        assert row is not None
        return self._district_row_to_record(row)

    async def ensure_district_billing(self, *, district_id: int) -> TenantBillingRecord:
        return await anyio.to_thread.run_sync(self._ensure_district_billing_sync, int(district_id))

    def _get_district_billing_sync(self, district_id: int, include_archived: bool) -> Optional[TenantBillingRecord]:
        where = "district_id = ?" if include_archived else "district_id = ? AND is_archived = 0"
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_DISTRICT_BILLING_COLS} FROM district_billing WHERE {where} LIMIT 1;",
                (int(district_id),),
            ).fetchone()
        return self._district_row_to_record(row) if row is not None else None

    async def get_district_billing(self, *, district_id: int, include_archived: bool = False) -> Optional[TenantBillingRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._get_district_billing_sync(int(district_id), include_archived)
        )

    def _list_all_district_billing_sync(self, include_archived: bool) -> List[TenantBillingRecord]:
        where = "" if include_archived else "WHERE is_archived = 0"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_DISTRICT_BILLING_COLS} FROM district_billing {where} ORDER BY updated_at DESC;"
            ).fetchall()
        return [self._district_row_to_record(r) for r in rows]

    async def list_all_district_billing(self, *, include_archived: bool = False) -> List[TenantBillingRecord]:
        return await anyio.to_thread.run_sync(lambda: self._list_all_district_billing_sync(include_archived))

    # ── Archive / Restore / Delete ──────────────────────────────────────────────

    def _archive_district_billing_sync(self, district_id: int, archived_by: str) -> TenantBillingRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE district_billing SET is_archived = 1, archived_at = ?, archived_by = ?, updated_at = ? "
                "WHERE district_id = ?;",
                (now, archived_by, now, int(district_id)),
            )
            row = conn.execute(
                f"SELECT {_DISTRICT_BILLING_COLS} FROM district_billing WHERE district_id = ? LIMIT 1;",
                (int(district_id),),
            ).fetchone()
        assert row is not None, f"district_billing row not found for district_id={district_id}"
        return self._district_row_to_record(row)

    async def archive_district_billing(self, *, district_id: int, archived_by: str) -> TenantBillingRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._archive_district_billing_sync(int(district_id), archived_by)
        )

    def _restore_district_billing_sync(self, district_id: int) -> TenantBillingRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE district_billing SET is_archived = 0, archived_at = NULL, archived_by = NULL, updated_at = ? "
                "WHERE district_id = ?;",
                (now, int(district_id)),
            )
            row = conn.execute(
                f"SELECT {_DISTRICT_BILLING_COLS} FROM district_billing WHERE district_id = ? LIMIT 1;",
                (int(district_id),),
            ).fetchone()
        assert row is not None, f"district_billing row not found for district_id={district_id}"
        return self._district_row_to_record(row)

    async def restore_district_billing(self, *, district_id: int) -> TenantBillingRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._restore_district_billing_sync(int(district_id))
        )

    def _delete_district_billing_sync(self, district_id: int) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT billing_status, is_archived FROM district_billing WHERE district_id = ? LIMIT 1;",
                (int(district_id),),
            ).fetchone()
            if row is None:
                return
            billing_status, is_archived = str(row[0] or "trial"), bool(int(row[1] or 0))
            active_statuses = {"active", "manual_override", "trial", "past_due"}
            if not is_archived and billing_status in active_statuses:
                raise ValueError(
                    f"Cannot delete an active district license (status={billing_status}). "
                    "Archive or let the license expire first."
                )
            conn.execute("DELETE FROM district_billing WHERE district_id = ?;", (int(district_id),))

    async def delete_district_billing(self, *, district_id: int) -> None:
        """Hard-delete the district billing record. Only allowed if archived OR status is expired/cancelled/suspended."""
        await anyio.to_thread.run_sync(lambda: self._delete_district_billing_sync(int(district_id)))

    # ── Billing Audit Log ──────────────────────────────────────────────────────

    def _log_billing_audit_sync(self, district_id: int, event_type: str, actor: str, detail: Optional[str]) -> BillingAuditRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO district_billing_audit_log (district_id, event_type, actor, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?);",
                (int(district_id), str(event_type), str(actor), detail, now),
            )
            row = conn.execute(
                f"SELECT {_BILLING_AUDIT_COLS} FROM district_billing_audit_log WHERE id = ?;",
                (cur.lastrowid,),
            ).fetchone()
        assert row is not None
        return self._billing_audit_row_to_record(row)

    async def log_billing_audit(
        self,
        *,
        district_id: int,
        event_type: str,
        actor: str,
        detail: Optional[str] = None,
    ) -> BillingAuditRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._log_billing_audit_sync(int(district_id), event_type, actor, detail)
        )

    def _list_billing_audit_sync(self, district_id: Optional[int], limit: int) -> List[BillingAuditRecord]:
        with self._connect() as conn:
            if district_id is not None:
                rows = conn.execute(
                    f"SELECT {_BILLING_AUDIT_COLS} FROM district_billing_audit_log "
                    f"WHERE district_id = ? ORDER BY created_at DESC LIMIT ?;",
                    (int(district_id), int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {_BILLING_AUDIT_COLS} FROM district_billing_audit_log "
                    f"ORDER BY created_at DESC LIMIT ?;",
                    (int(limit),),
                ).fetchall()
        return [self._billing_audit_row_to_record(r) for r in rows]

    async def list_billing_audit(
        self,
        *,
        district_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[BillingAuditRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._list_billing_audit_sync(district_id, limit)
        )

    def _update_district_billing_full_sync(
        self,
        *,
        district_id: int,
        customer_name: Optional[str] = None,
        customer_email: Optional[str] = None,
        plan_type: Optional[str] = None,
        billing_status: Optional[str] = None,
        license_key: Optional[str] = None,
        starts_at: Optional[str] = None,
        trial_ends_at: Optional[str] = None,
        current_period_start: Optional[str] = None,
        current_period_end: Optional[str] = None,
        renewal_date: Optional[str] = None,
        override_enabled: Optional[bool] = None,
        override_reason: Optional[str] = None,
        internal_notes: Optional[str] = None,
        stripe_customer_id: Optional[str] = None,
        stripe_subscription_id: Optional[str] = None,
        stripe_price_id: Optional[str] = None,
        stripe_product_id: Optional[str] = None,
        cancel_at_period_end: Optional[bool] = None,
    ) -> TenantBillingRecord:
        now = datetime.now(timezone.utc).isoformat()
        fields: list[str] = []
        params: list[object] = []

        def _set(col: str, val: object) -> None:
            fields.append(f"{col} = ?")
            params.append(val)

        if customer_name is not None:
            _set("customer_name", customer_name)
        if customer_email is not None:
            _set("customer_email", customer_email)
        if plan_type is not None:
            _set("plan_type", plan_type.strip().lower())
            _set("plan_id", plan_type.strip().lower())
        if billing_status is not None:
            _set("billing_status", billing_status.strip().lower())
        if license_key is not None:
            _set("license_key", license_key)
        if starts_at is not None:
            _set("starts_at", starts_at)
        if trial_ends_at is not None:
            _set("trial_ends_at", trial_ends_at)
            _set("trial_end", trial_ends_at)
        if current_period_start is not None:
            _set("current_period_start", current_period_start)
        if current_period_end is not None:
            _set("current_period_end", current_period_end)
            _set("renewal_date", current_period_end)
        if renewal_date is not None:
            _set("renewal_date", renewal_date)
        if override_enabled is not None:
            v = 1 if override_enabled else 0
            _set("override_enabled", v)
            _set("is_free_override", v)
        if override_reason is not None:
            _set("override_reason", override_reason)
            _set("free_reason", override_reason)
        if internal_notes is not None:
            _set("internal_notes", internal_notes)
        if stripe_customer_id is not None:
            _set("stripe_customer_id", stripe_customer_id)
        if stripe_subscription_id is not None:
            _set("stripe_subscription_id", stripe_subscription_id)
        if stripe_price_id is not None:
            _set("stripe_price_id", stripe_price_id)
        if stripe_product_id is not None:
            _set("stripe_product_id", stripe_product_id)
        if cancel_at_period_end is not None:
            _set("cancel_at_period_end", 1 if cancel_at_period_end else 0)

        fields.append("updated_at = ?")
        params.append(now)
        params.append(int(district_id))

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO district_billing (district_id, billing_status, plan_type, updated_at, created_at) "
                "VALUES (?, 'trial', 'trial', ?, ?) ON CONFLICT(district_id) DO NOTHING;",
                (int(district_id), now, now),
            )
            if fields:
                conn.execute(
                    f"UPDATE district_billing SET {', '.join(fields)} WHERE district_id = ?;",
                    params,
                )
            row = conn.execute(
                f"SELECT {_DISTRICT_BILLING_COLS} FROM district_billing WHERE district_id = ? LIMIT 1;",
                (int(district_id),),
            ).fetchone()
        assert row is not None
        return self._district_row_to_record(row)

    async def update_district_billing_full(
        self,
        *,
        district_id: int,
        customer_name: Optional[str] = None,
        customer_email: Optional[str] = None,
        plan_type: Optional[str] = None,
        billing_status: Optional[str] = None,
        license_key: Optional[str] = None,
        starts_at: Optional[str] = None,
        trial_ends_at: Optional[str] = None,
        current_period_start: Optional[str] = None,
        current_period_end: Optional[str] = None,
        renewal_date: Optional[str] = None,
        override_enabled: Optional[bool] = None,
        override_reason: Optional[str] = None,
        internal_notes: Optional[str] = None,
        stripe_customer_id: Optional[str] = None,
        stripe_subscription_id: Optional[str] = None,
        stripe_price_id: Optional[str] = None,
        stripe_product_id: Optional[str] = None,
        cancel_at_period_end: Optional[bool] = None,
    ) -> TenantBillingRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._update_district_billing_full_sync(
                district_id=district_id,
                customer_name=customer_name,
                customer_email=customer_email,
                plan_type=plan_type,
                billing_status=billing_status,
                license_key=license_key,
                starts_at=starts_at,
                trial_ends_at=trial_ends_at,
                current_period_start=current_period_start,
                current_period_end=current_period_end,
                renewal_date=renewal_date,
                override_enabled=override_enabled,
                override_reason=override_reason,
                internal_notes=internal_notes,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription_id,
                stripe_price_id=stripe_price_id,
                stripe_product_id=stripe_product_id,
                cancel_at_period_end=cancel_at_period_end,
            )
        )
