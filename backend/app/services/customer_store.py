from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import anyio


VALID_STATUSES = {"lead", "active", "closed", "archived"}
VALID_SOURCES  = {"website", "email", "manual"}

_COLS = (
    "id, name, email, organization, phone, source, status, "
    "inquiry_id, district_id, notes, created_at, updated_at"
)


@dataclass(frozen=True)
class CustomerRecord:
    id: int
    name: str
    email: str
    organization: str
    phone: Optional[str]
    source: str      # website | email | manual
    status: str      # lead | active | closed | archived
    inquiry_id: Optional[int]
    district_id: Optional[int]
    notes: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "organization": self.organization,
            "phone": self.phone,
            "source": self.source,
            "status": self.status,
            "inquiry_id": self.inquiry_id,
            "district_id": self.district_id,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_record(row: sqlite3.Row) -> CustomerRecord:
    return CustomerRecord(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        organization=row["organization"] or "",
        phone=row["phone"],
        source=row["source"] or "manual",
        status=row["status"] or "lead",
        inquiry_id=row["inquiry_id"],
        district_id=row["district_id"],
        notes=row["notes"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class CustomerStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path
        self._ensure_schema()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._db) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("""
                CREATE TABLE IF NOT EXISTS platform_customers (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    name         TEXT    NOT NULL,
                    email        TEXT    NOT NULL,
                    organization TEXT    NOT NULL DEFAULT '',
                    phone        TEXT    NULL,
                    source       TEXT    NOT NULL DEFAULT 'manual',
                    status       TEXT    NOT NULL DEFAULT 'lead',
                    inquiry_id   INTEGER NULL,
                    district_id  INTEGER NULL,
                    notes        TEXT    NOT NULL DEFAULT '',
                    created_at   TEXT    NOT NULL,
                    updated_at   TEXT    NOT NULL
                )
            """)
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_customers_email  ON platform_customers(email)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_customers_status ON platform_customers(status)"
            )
            con.commit()

    # ── Sync helpers ──────────────────────────────────────────────────────────

    def _create_sync(
        self,
        name: str,
        email: str,
        organization: str = "",
        phone: Optional[str] = None,
        source: str = "manual",
        status: str = "lead",
        inquiry_id: Optional[int] = None,
        district_id: Optional[int] = None,
        notes: str = "",
    ) -> CustomerRecord:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db) as con:
            con.row_factory = sqlite3.Row
            cur = con.execute(
                """
                INSERT INTO platform_customers
                    (name, email, organization, phone, source, status,
                     inquiry_id, district_id, notes, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (name, email, organization, phone, source, status,
                 inquiry_id, district_id, notes, now, now),
            )
            con.commit()
            row = con.execute(
                f"SELECT {_COLS} FROM platform_customers WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        return _row_to_record(row)

    def _list_sync(
        self,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[CustomerRecord]:
        with sqlite3.connect(self._db) as con:
            con.row_factory = sqlite3.Row
            if status:
                rows = con.execute(
                    f"SELECT {_COLS} FROM platform_customers WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    f"SELECT {_COLS} FROM platform_customers ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [_row_to_record(r) for r in rows]

    def _get_sync(self, customer_id: int) -> Optional[CustomerRecord]:
        with sqlite3.connect(self._db) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                f"SELECT {_COLS} FROM platform_customers WHERE id=?", (customer_id,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def _get_by_inquiry_sync(self, inquiry_id: int) -> Optional[CustomerRecord]:
        with sqlite3.connect(self._db) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                f"SELECT {_COLS} FROM platform_customers WHERE inquiry_id=? LIMIT 1",
                (inquiry_id,),
            ).fetchone()
        return _row_to_record(row) if row else None

    def _update_sync(
        self,
        customer_id: int,
        *,
        name: Optional[str] = None,
        email: Optional[str] = None,
        organization: Optional[str] = None,
        phone: Optional[str] = None,
        source: Optional[str] = None,
        status: Optional[str] = None,
        district_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Optional[CustomerRecord]:
        now = datetime.now(timezone.utc).isoformat()
        fields, vals = ["updated_at=?"], [now]
        if name         is not None: fields.append("name=?");         vals.append(name)
        if email        is not None: fields.append("email=?");        vals.append(email)
        if organization is not None: fields.append("organization=?"); vals.append(organization)
        if phone        is not None: fields.append("phone=?");        vals.append(phone)
        if source       is not None: fields.append("source=?");       vals.append(source)
        if status       is not None: fields.append("status=?");       vals.append(status)
        if district_id  is not None: fields.append("district_id=?");  vals.append(district_id)
        if notes        is not None: fields.append("notes=?");        vals.append(notes)
        vals.append(customer_id)
        with sqlite3.connect(self._db) as con:
            con.execute(
                f"UPDATE platform_customers SET {', '.join(fields)} WHERE id=?", vals
            )
            con.commit()
        return self._get_sync(customer_id)

    def _delete_sync(self, customer_id: int) -> bool:
        with sqlite3.connect(self._db) as con:
            cur = con.execute("DELETE FROM platform_customers WHERE id=?", (customer_id,))
            con.commit()
        return cur.rowcount > 0

    # ── Public async API ──────────────────────────────────────────────────────

    async def create_customer(
        self,
        name: str,
        email: str,
        organization: str = "",
        phone: Optional[str] = None,
        source: str = "manual",
        status: str = "lead",
        inquiry_id: Optional[int] = None,
        district_id: Optional[int] = None,
        notes: str = "",
    ) -> CustomerRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._create_sync(
                name, email, organization, phone, source, status,
                inquiry_id, district_id, notes
            )
        )

    async def list_customers(
        self, status: Optional[str] = None, limit: int = 100
    ) -> List[CustomerRecord]:
        return await anyio.to_thread.run_sync(lambda: self._list_sync(status, limit))

    async def get_customer(self, customer_id: int) -> Optional[CustomerRecord]:
        return await anyio.to_thread.run_sync(lambda: self._get_sync(customer_id))

    async def get_by_inquiry(self, inquiry_id: int) -> Optional[CustomerRecord]:
        return await anyio.to_thread.run_sync(lambda: self._get_by_inquiry_sync(inquiry_id))

    async def update_customer(self, customer_id: int, **kwargs) -> Optional[CustomerRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._update_sync(customer_id, **kwargs)
        )

    async def delete_customer(self, customer_id: int) -> bool:
        return await anyio.to_thread.run_sync(lambda: self._delete_sync(customer_id))
