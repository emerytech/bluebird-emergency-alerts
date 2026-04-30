from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import anyio


_COLS = (
    "id, name, email, organization, role, school_count, message, "
    "phone, preferred_time, status, created_at, updated_at, notes"
)

VALID_STATUSES = {"new", "contacted", "converted", "closed"}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class DemoRequestRecord:
    id: int
    name: str
    email: str
    organization: str
    role: str
    school_count: Optional[int]
    message: str
    phone: str
    preferred_time: str
    status: str     # new | contacted | converted | closed
    created_at: str
    updated_at: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "organization": self.organization,
            "role": self.role,
            "school_count": self.school_count,
            "message": self.message,
            "phone": self.phone,
            "preferred_time": self.preferred_time,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
        }


class DemoRequestStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_demo_requests (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT    NOT NULL,
                    email           TEXT    NOT NULL,
                    organization    TEXT    NOT NULL,
                    role            TEXT    NOT NULL DEFAULT '',
                    school_count    INTEGER NULL,
                    message         TEXT    NOT NULL DEFAULT '',
                    phone           TEXT    NOT NULL DEFAULT '',
                    preferred_time  TEXT    NOT NULL DEFAULT '',
                    status          TEXT    NOT NULL DEFAULT 'new',
                    created_at      TEXT    NOT NULL,
                    updated_at      TEXT    NOT NULL,
                    notes           TEXT    NOT NULL DEFAULT ''
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_demo_requests_created "
                "ON platform_demo_requests(created_at DESC);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_demo_requests_status "
                "ON platform_demo_requests(status);"
            )

    @staticmethod
    def _row(row: tuple) -> DemoRequestRecord:
        return DemoRequestRecord(
            id=int(row[0]),
            name=str(row[1]),
            email=str(row[2]),
            organization=str(row[3]),
            role=str(row[4]),
            school_count=int(row[5]) if row[5] is not None else None,
            message=str(row[6]),
            phone=str(row[7]),
            preferred_time=str(row[8]),
            status=str(row[9]),
            created_at=str(row[10]),
            updated_at=str(row[11]),
            notes=str(row[12]) if len(row) > 12 and row[12] is not None else "",
        )

    def _create_sync(
        self,
        name: str,
        email: str,
        organization: str,
        role: str,
        school_count: Optional[int],
        message: str,
        phone: str,
        preferred_time: str,
    ) -> DemoRequestRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO platform_demo_requests
                    (name, email, organization, role, school_count, message,
                     phone, preferred_time, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?);
                """,
                (
                    name[:255],
                    email[:255],
                    organization[:255],
                    role[:100],
                    school_count,
                    message[:4000],
                    phone[:50],
                    preferred_time[:255],
                    now,
                    now,
                ),
            )
            row = conn.execute(
                f"SELECT {_COLS} FROM platform_demo_requests WHERE id = ?;",
                (cur.lastrowid,),
            ).fetchone()
        assert row is not None
        return self._row(row)

    async def create_demo_request(
        self,
        *,
        name: str,
        email: str,
        organization: str,
        role: str = "",
        school_count: Optional[int] = None,
        message: str = "",
        phone: str = "",
        preferred_time: str = "",
    ) -> DemoRequestRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._create_sync(
                name=name.strip(),
                email=email.strip().lower(),
                organization=organization.strip(),
                role=role.strip(),
                school_count=school_count,
                message=message.strip(),
                phone=phone.strip(),
                preferred_time=preferred_time.strip(),
            )
        )

    def _list_sync(self, status: Optional[str], limit: int) -> List[DemoRequestRecord]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    f"SELECT {_COLS} FROM platform_demo_requests "
                    f"WHERE status = ? ORDER BY created_at DESC LIMIT ?;",
                    (status, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {_COLS} FROM platform_demo_requests "
                    f"ORDER BY created_at DESC LIMIT ?;",
                    (int(limit),),
                ).fetchall()
        return [self._row(r) for r in rows]

    async def list_demo_requests(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[DemoRequestRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._list_sync(status, limit)
        )

    def _get_sync(self, req_id: int) -> Optional[DemoRequestRecord]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM platform_demo_requests WHERE id = ? LIMIT 1;",
                (int(req_id),),
            ).fetchone()
        return self._row(row) if row else None

    async def get_demo_request(self, req_id: int) -> Optional[DemoRequestRecord]:
        return await anyio.to_thread.run_sync(lambda: self._get_sync(int(req_id)))

    def _update_status_sync(self, req_id: int, new_status: str) -> Optional[DemoRequestRecord]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE platform_demo_requests SET status = ?, updated_at = ? WHERE id = ?;",
                (new_status, now, int(req_id)),
            )
            row = conn.execute(
                f"SELECT {_COLS} FROM platform_demo_requests WHERE id = ? LIMIT 1;",
                (int(req_id),),
            ).fetchone()
        return self._row(row) if row else None

    async def update_status(self, *, req_id: int, new_status: str) -> Optional[DemoRequestRecord]:
        if new_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {new_status!r}")
        return await anyio.to_thread.run_sync(
            lambda: self._update_status_sync(int(req_id), new_status)
        )

    def _update_notes_sync(self, req_id: int, notes: str) -> Optional[DemoRequestRecord]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE platform_demo_requests SET notes = ?, updated_at = ? WHERE id = ?;",
                (notes[:8000], now, int(req_id)),
            )
            row = conn.execute(
                f"SELECT {_COLS} FROM platform_demo_requests WHERE id = ? LIMIT 1;",
                (int(req_id),),
            ).fetchone()
        return self._row(row) if row else None

    async def update_notes(self, *, req_id: int, notes: str) -> Optional[DemoRequestRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._update_notes_sync(int(req_id), str(notes))
        )

    def _delete_sync(self, req_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM platform_demo_requests WHERE id = ?;",
                (int(req_id),),
            )
        return (cur.rowcount or 0) > 0

    async def delete_demo_request(self, req_id: int) -> bool:
        return await anyio.to_thread.run_sync(lambda: self._delete_sync(int(req_id)))
