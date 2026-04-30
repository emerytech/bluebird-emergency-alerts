from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import anyio


_COLS = (
    "id, name, email, school_or_district, estimated_students, "
    "number_of_schools, message, size_tag, status, created_at, updated_at, notes"
)

VALID_STATUSES = {"new", "contacted", "quoted", "closed"}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _size_tag(estimated_students: Optional[int]) -> str:
    if estimated_students is None:
        return "unknown"
    if estimated_students < 300:
        return "small"
    if estimated_students < 800:
        return "medium"
    return "large"


@dataclass(frozen=True)
class InquiryRecord:
    id: int
    name: str
    email: str
    school_or_district: str
    estimated_students: Optional[int]
    number_of_schools: Optional[int]
    message: str
    size_tag: str   # small | medium | large | unknown
    status: str     # new | contacted | quoted | closed
    created_at: str
    updated_at: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "school_or_district": self.school_or_district,
            "estimated_students": self.estimated_students,
            "number_of_schools": self.number_of_schools,
            "message": self.message,
            "size_tag": self.size_tag,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
        }


class InquiryStore:
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
                CREATE TABLE IF NOT EXISTS platform_inquiries (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    name                TEXT    NOT NULL,
                    email               TEXT    NOT NULL,
                    school_or_district  TEXT    NOT NULL,
                    estimated_students  INTEGER NULL,
                    number_of_schools   INTEGER NULL,
                    message             TEXT    NOT NULL DEFAULT '',
                    size_tag            TEXT    NOT NULL DEFAULT 'unknown',
                    status              TEXT    NOT NULL DEFAULT 'new',
                    created_at          TEXT    NOT NULL,
                    updated_at          TEXT    NOT NULL,
                    notes               TEXT    NOT NULL DEFAULT ''
                );
                """
            )
            # Migrate existing tables that lack the notes column
            cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(platform_inquiries);").fetchall()}
            if "notes" not in cols:
                conn.execute("ALTER TABLE platform_inquiries ADD COLUMN notes TEXT NOT NULL DEFAULT '';")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_inquiries_created "
                "ON platform_inquiries(created_at DESC);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_inquiries_status "
                "ON platform_inquiries(status);"
            )

    @staticmethod
    def _row(row: tuple) -> InquiryRecord:
        return InquiryRecord(
            id=int(row[0]),
            name=str(row[1]),
            email=str(row[2]),
            school_or_district=str(row[3]),
            estimated_students=int(row[4]) if row[4] is not None else None,
            number_of_schools=int(row[5]) if row[5] is not None else None,
            message=str(row[6]),
            size_tag=str(row[7]),
            status=str(row[8]),
            created_at=str(row[9]),
            updated_at=str(row[10]),
            notes=str(row[11]) if len(row) > 11 and row[11] is not None else "",
        )

    def _create_sync(
        self,
        name: str,
        email: str,
        school_or_district: str,
        estimated_students: Optional[int],
        number_of_schools: Optional[int],
        message: str,
    ) -> InquiryRecord:
        now = datetime.now(timezone.utc).isoformat()
        tag = _size_tag(estimated_students)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO platform_inquiries
                    (name, email, school_or_district, estimated_students,
                     number_of_schools, message, size_tag, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, ?);
                """,
                (
                    name[:255],
                    email[:255],
                    school_or_district[:255],
                    estimated_students,
                    number_of_schools,
                    message[:4000],
                    tag,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                f"SELECT {_COLS} FROM platform_inquiries WHERE id = ?;",
                (cur.lastrowid,),
            ).fetchone()
        assert row is not None
        return self._row(row)

    async def create_inquiry(
        self,
        *,
        name: str,
        email: str,
        school_or_district: str,
        estimated_students: Optional[int] = None,
        number_of_schools: Optional[int] = None,
        message: str = "",
    ) -> InquiryRecord:
        return await anyio.to_thread.run_sync(
            lambda: self._create_sync(
                name=name.strip(),
                email=email.strip().lower(),
                school_or_district=school_or_district.strip(),
                estimated_students=estimated_students,
                number_of_schools=number_of_schools,
                message=message.strip(),
            )
        )

    def _list_sync(self, status: Optional[str], limit: int) -> List[InquiryRecord]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    f"SELECT {_COLS} FROM platform_inquiries "
                    f"WHERE status = ? ORDER BY created_at DESC LIMIT ?;",
                    (status, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {_COLS} FROM platform_inquiries "
                    f"ORDER BY created_at DESC LIMIT ?;",
                    (int(limit),),
                ).fetchall()
        return [self._row(r) for r in rows]

    async def list_inquiries(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[InquiryRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._list_sync(status, limit)
        )

    def _get_sync(self, inquiry_id: int) -> Optional[InquiryRecord]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM platform_inquiries WHERE id = ? LIMIT 1;",
                (int(inquiry_id),),
            ).fetchone()
        return self._row(row) if row else None

    async def get_inquiry(self, inquiry_id: int) -> Optional[InquiryRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._get_sync(int(inquiry_id))
        )

    def _update_status_sync(self, inquiry_id: int, new_status: str) -> Optional[InquiryRecord]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE platform_inquiries SET status = ?, updated_at = ? WHERE id = ?;",
                (new_status, now, int(inquiry_id)),
            )
            row = conn.execute(
                f"SELECT {_COLS} FROM platform_inquiries WHERE id = ? LIMIT 1;",
                (int(inquiry_id),),
            ).fetchone()
        return self._row(row) if row else None

    async def update_status(
        self,
        *,
        inquiry_id: int,
        new_status: str,
    ) -> Optional[InquiryRecord]:
        if new_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {new_status!r}")
        return await anyio.to_thread.run_sync(
            lambda: self._update_status_sync(int(inquiry_id), new_status)
        )

    def _update_notes_sync(self, inquiry_id: int, notes: str) -> Optional[InquiryRecord]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE platform_inquiries SET notes = ?, updated_at = ? WHERE id = ?;",
                (notes[:8000], now, int(inquiry_id)),
            )
            row = conn.execute(
                f"SELECT {_COLS} FROM platform_inquiries WHERE id = ? LIMIT 1;",
                (int(inquiry_id),),
            ).fetchone()
        return self._row(row) if row else None

    async def update_notes(self, *, inquiry_id: int, notes: str) -> Optional[InquiryRecord]:
        return await anyio.to_thread.run_sync(
            lambda: self._update_notes_sync(int(inquiry_id), str(notes))
        )
