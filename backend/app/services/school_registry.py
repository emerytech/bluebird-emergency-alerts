from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import anyio


@dataclass(frozen=True)
class SchoolRecord:
    id: int
    created_at: str
    slug: str
    name: str
    is_active: bool

    @property
    def subdomain(self) -> str:
        return self.slug


class SchoolRegistry:
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
                CREATE TABLE IF NOT EXISTS schools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                );
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_schools_slug ON schools(slug);")

    def _row_to_record(self, row: sqlite3.Row | tuple) -> SchoolRecord:
        return SchoolRecord(
            id=int(row[0]),
            created_at=str(row[1]),
            slug=str(row[2]),
            name=str(row[3]),
            is_active=bool(int(row[4])),
        )

    def _ensure_school_sync(self, slug: str, name: str) -> SchoolRecord:
        normalized_slug = slug.strip().lower()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO schools (created_at, slug, name, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(slug) DO UPDATE SET name = schools.name;
                """,
                (datetime.now(timezone.utc).isoformat(), normalized_slug, name.strip()),
            )
            row = conn.execute(
                """
                SELECT id, created_at, slug, name, is_active
                FROM schools
                WHERE slug = ?
                LIMIT 1;
                """,
                (normalized_slug,),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    async def ensure_school(self, *, slug: str, name: str) -> SchoolRecord:
        return await anyio.to_thread.run_sync(self._ensure_school_sync, slug, name)

    def _create_school_sync(self, slug: str, name: str) -> SchoolRecord:
        created_at = datetime.now(timezone.utc).isoformat()
        normalized_slug = slug.strip().lower()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO schools (created_at, slug, name, is_active)
                VALUES (?, ?, ?, 1);
                """,
                (created_at, normalized_slug, name.strip()),
            )
            row = conn.execute(
                """
                SELECT id, created_at, slug, name, is_active
                FROM schools
                WHERE id = ?;
                """,
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    async def create_school(self, *, slug: str, name: str) -> SchoolRecord:
        return await anyio.to_thread.run_sync(self._create_school_sync, slug, name)

    def _get_by_slug_sync(self, slug: str) -> Optional[SchoolRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, slug, name, is_active
                FROM schools
                WHERE slug = ?
                LIMIT 1;
                """,
                (slug.strip().lower(),),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def get_by_slug(self, slug: str) -> Optional[SchoolRecord]:
        return await anyio.to_thread.run_sync(self._get_by_slug_sync, slug)

    def _list_schools_sync(self) -> List[SchoolRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, slug, name, is_active
                FROM schools
                ORDER BY name ASC, slug ASC;
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    async def list_schools(self) -> List[SchoolRecord]:
        return await anyio.to_thread.run_sync(self._list_schools_sync)
