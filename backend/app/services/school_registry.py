from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import anyio
from app.services.passwords import hash_password, verify_password


@dataclass(frozen=True)
class SchoolRecord:
    id: int
    created_at: str
    slug: str
    name: str
    is_active: bool
    setup_pin_required: bool = False
    accent: Optional[str] = None
    accent_strong: Optional[str] = None
    sidebar_start: Optional[str] = None
    sidebar_end: Optional[str] = None

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
                    is_active INTEGER NOT NULL DEFAULT 1,
                    accent TEXT NULL,
                    accent_strong TEXT NULL,
                    sidebar_start TEXT NULL,
                    sidebar_end TEXT NULL,
                    setup_pin_salt TEXT NULL,
                    setup_pin_hash TEXT NULL
                );
                """
            )
            self._migrate_schools_table(conn)
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_schools_slug ON schools(slug);")

    def _migrate_schools_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(schools);").fetchall()}
        if "accent" not in cols:
            conn.execute("ALTER TABLE schools ADD COLUMN accent TEXT NULL;")
        if "accent_strong" not in cols:
            conn.execute("ALTER TABLE schools ADD COLUMN accent_strong TEXT NULL;")
        if "sidebar_start" not in cols:
            conn.execute("ALTER TABLE schools ADD COLUMN sidebar_start TEXT NULL;")
        if "sidebar_end" not in cols:
            conn.execute("ALTER TABLE schools ADD COLUMN sidebar_end TEXT NULL;")
        if "setup_pin_salt" not in cols:
            conn.execute("ALTER TABLE schools ADD COLUMN setup_pin_salt TEXT NULL;")
        if "setup_pin_hash" not in cols:
            conn.execute("ALTER TABLE schools ADD COLUMN setup_pin_hash TEXT NULL;")

    def _row_to_record(self, row: sqlite3.Row | tuple) -> SchoolRecord:
        return SchoolRecord(
            id=int(row[0]),
            created_at=str(row[1]),
            slug=str(row[2]),
            name=str(row[3]),
            is_active=bool(int(row[4])),
            accent=str(row[5]) if row[5] is not None else None,
            accent_strong=str(row[6]) if row[6] is not None else None,
            sidebar_start=str(row[7]) if row[7] is not None else None,
            sidebar_end=str(row[8]) if row[8] is not None else None,
            setup_pin_required=bool(row[9] and row[10]),
        )

    def _ensure_school_sync(self, slug: str, name: str) -> SchoolRecord:
        normalized_slug = slug.strip().lower()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO schools (
                    created_at, slug, name, is_active,
                    accent, accent_strong, sidebar_start, sidebar_end,
                    setup_pin_salt, setup_pin_hash
                )
                VALUES (?, ?, ?, 1, NULL, NULL, NULL, NULL, NULL, NULL)
                ON CONFLICT(slug) DO UPDATE SET name = schools.name;
                """,
                (datetime.now(timezone.utc).isoformat(), normalized_slug, name.strip()),
            )
            row = conn.execute(
                """
                SELECT id, created_at, slug, name, is_active,
                       accent, accent_strong, sidebar_start, sidebar_end,
                       setup_pin_salt, setup_pin_hash
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

    def _create_school_sync(self, slug: str, name: str, setup_pin: Optional[str]) -> SchoolRecord:
        created_at = datetime.now(timezone.utc).isoformat()
        normalized_slug = slug.strip().lower()
        pin_salt = None
        pin_hash = None
        if setup_pin:
            pin_salt, pin_hash = hash_password(setup_pin)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO schools (
                    created_at, slug, name, is_active,
                    accent, accent_strong, sidebar_start, sidebar_end,
                    setup_pin_salt, setup_pin_hash
                )
                VALUES (?, ?, ?, 1, NULL, NULL, NULL, NULL, ?, ?);
                """,
                (created_at, normalized_slug, name.strip(), pin_salt, pin_hash),
            )
            row = conn.execute(
                """
                SELECT id, created_at, slug, name, is_active,
                       accent, accent_strong, sidebar_start, sidebar_end,
                       setup_pin_salt, setup_pin_hash
                FROM schools
                WHERE id = ?;
                """,
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    async def create_school(self, *, slug: str, name: str, setup_pin: Optional[str] = None) -> SchoolRecord:
        normalized_pin = setup_pin.strip() if setup_pin else None
        return await anyio.to_thread.run_sync(self._create_school_sync, slug, name, normalized_pin or None)

    def _get_by_slug_sync(self, slug: str) -> Optional[SchoolRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, slug, name, is_active,
                       accent, accent_strong, sidebar_start, sidebar_end,
                       setup_pin_salt, setup_pin_hash
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
                SELECT id, created_at, slug, name, is_active,
                       accent, accent_strong, sidebar_start, sidebar_end,
                       setup_pin_salt, setup_pin_hash
                FROM schools
                ORDER BY name ASC, slug ASC;
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    async def list_schools(self) -> List[SchoolRecord]:
        return await anyio.to_thread.run_sync(self._list_schools_sync)

    def _verify_setup_pin_sync(self, slug: str, setup_pin: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT setup_pin_salt, setup_pin_hash
                FROM schools
                WHERE slug = ?
                LIMIT 1;
                """,
                (slug.strip().lower(),),
            ).fetchone()
        if row is None:
            return False
        salt = str(row[0]) if row[0] is not None else ""
        digest = str(row[1]) if row[1] is not None else ""
        if not salt or not digest:
            return True
        return verify_password(setup_pin.strip(), salt_hex=salt, digest_hex=digest)

    async def verify_setup_pin(self, *, slug: str, setup_pin: str) -> bool:
        return await anyio.to_thread.run_sync(self._verify_setup_pin_sync, slug, setup_pin)

    def _set_setup_pin_sync(self, slug: str, setup_pin: Optional[str]) -> Optional[SchoolRecord]:
        normalized_slug = slug.strip().lower()
        pin_salt = None
        pin_hash = None
        if setup_pin:
            pin_salt, pin_hash = hash_password(setup_pin.strip())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE schools
                SET setup_pin_salt = ?, setup_pin_hash = ?
                WHERE slug = ?;
                """,
                (pin_salt, pin_hash, normalized_slug),
            )
            row = conn.execute(
                """
                SELECT id, created_at, slug, name, is_active,
                       accent, accent_strong, sidebar_start, sidebar_end,
                       setup_pin_salt, setup_pin_hash
                FROM schools
                WHERE slug = ?
                LIMIT 1;
                """,
                (normalized_slug,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def set_setup_pin(self, *, slug: str, setup_pin: Optional[str]) -> Optional[SchoolRecord]:
        normalized_pin = setup_pin.strip() if setup_pin else None
        return await anyio.to_thread.run_sync(self._set_setup_pin_sync, slug, normalized_pin or None)

    def _update_theme_sync(
        self,
        slug: str,
        accent: Optional[str],
        accent_strong: Optional[str],
        sidebar_start: Optional[str],
        sidebar_end: Optional[str],
    ) -> Optional[SchoolRecord]:
        normalized_slug = slug.strip().lower()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE schools
                SET accent = ?, accent_strong = ?, sidebar_start = ?, sidebar_end = ?
                WHERE slug = ?;
                """,
                (
                    accent.strip() if accent else None,
                    accent_strong.strip() if accent_strong else None,
                    sidebar_start.strip() if sidebar_start else None,
                    sidebar_end.strip() if sidebar_end else None,
                    normalized_slug,
                ),
            )
            row = conn.execute(
                """
                SELECT id, created_at, slug, name, is_active,
                       accent, accent_strong, sidebar_start, sidebar_end,
                       setup_pin_salt, setup_pin_hash
                FROM schools
                WHERE slug = ?
                LIMIT 1;
                """,
                (normalized_slug,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    async def update_theme(
        self,
        *,
        slug: str,
        accent: Optional[str],
        accent_strong: Optional[str],
        sidebar_start: Optional[str],
        sidebar_end: Optional[str],
    ) -> Optional[SchoolRecord]:
        return await anyio.to_thread.run_sync(
            self._update_theme_sync,
            slug,
            accent,
            accent_strong,
            sidebar_start,
            sidebar_end,
        )
