from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import anyio
from app.services.passwords import hash_password, verify_password


@dataclass(frozen=True)
class SlugAliasRecord:
    old_slug: str
    new_slug: str
    created_at: str
    reason: Optional[str]


@dataclass(frozen=True)
class OrganizationRecord:
    id: int
    created_at: str
    name: str
    slug: str
    is_active: bool


@dataclass(frozen=True)
class DistrictRecord:
    id: int
    created_at: str
    name: str
    slug: str
    organization_id: int
    is_active: bool
    accent: Optional[str] = None
    accent_strong: Optional[str] = None
    sidebar_start: Optional[str] = None
    sidebar_end: Optional[str] = None
    logo_path: Optional[str] = None


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
    district_id: Optional[int] = None
    logo_path: Optional[str] = None
    sort_order: int = 0

    @property
    def subdomain(self) -> str:
        return self.slug


# SQL fragment shared by every districts SELECT to keep column ordering consistent.
_DISTRICT_COLS = """
    id, created_at, name, slug, organization_id, is_active,
    accent, accent_strong, sidebar_start, sidebar_end, logo_path
"""

# SQL fragment shared by every schools SELECT to keep column ordering consistent.
_SCHOOL_COLS = """
    id, created_at, slug, name, is_active,
    accent, accent_strong, sidebar_start, sidebar_end,
    setup_pin_salt, setup_pin_hash,
    district_id, logo_path, sort_order
"""


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
            conn.execute("PRAGMA foreign_keys=ON;")

            # Organizations must be created before districts (FK dependency).
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS organizations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT    NOT NULL,
                    name       TEXT    NOT NULL,
                    slug       TEXT    NOT NULL UNIQUE,
                    is_active  INTEGER NOT NULL DEFAULT 1
                );
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_slug ON organizations(slug);"
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS districts (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at      TEXT    NOT NULL,
                    name            TEXT    NOT NULL,
                    slug            TEXT    NOT NULL UNIQUE,
                    organization_id INTEGER NOT NULL REFERENCES organizations(id),
                    is_active       INTEGER NOT NULL DEFAULT 1
                );
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_districts_slug ON districts(slug);"
            )
            self._migrate_districts_table(conn)

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schools (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at      TEXT    NOT NULL,
                    slug            TEXT    NOT NULL UNIQUE,
                    name            TEXT    NOT NULL,
                    is_active       INTEGER NOT NULL DEFAULT 1,
                    accent          TEXT    NULL,
                    accent_strong   TEXT    NULL,
                    sidebar_start   TEXT    NULL,
                    sidebar_end     TEXT    NULL,
                    setup_pin_salt  TEXT    NULL,
                    setup_pin_hash  TEXT    NULL,
                    district_id     INTEGER NULL REFERENCES districts(id)
                );
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_schools_slug ON schools(slug);")
            self._migrate_schools_table(conn)

            # Backward-compat slug aliases: maps old_slug → new_slug for routing.
            # Rows here are checked when a direct slug lookup fails.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_slug_aliases (
                    old_slug   TEXT NOT NULL PRIMARY KEY,
                    new_slug   TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reason     TEXT NULL
                );
                """
            )

            # Theme presets: saved color combinations per tenant (or NULL for global).
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_theme_presets (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at    TEXT    NOT NULL,
                    tenant_slug   TEXT    NULL,
                    name          TEXT    NOT NULL,
                    accent        TEXT    NOT NULL DEFAULT '',
                    accent_strong TEXT    NOT NULL DEFAULT '',
                    sidebar_start TEXT    NOT NULL DEFAULT '',
                    sidebar_end   TEXT    NOT NULL DEFAULT '',
                    created_by    TEXT    NOT NULL DEFAULT ''
                );
                """
            )

            # Operator notes: super-admin-only internal notes per district/school.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS operator_notes (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at  TEXT    NOT NULL,
                    tenant_slug TEXT    NOT NULL,
                    note_text   TEXT    NOT NULL,
                    created_by  TEXT    NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_operator_notes_slug ON operator_notes(tenant_slug);"
            )

    def _migrate_districts_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(districts);").fetchall()}
        for col, ddl in [
            ("accent",        "ALTER TABLE districts ADD COLUMN accent TEXT NULL;"),
            ("accent_strong", "ALTER TABLE districts ADD COLUMN accent_strong TEXT NULL;"),
            ("sidebar_start", "ALTER TABLE districts ADD COLUMN sidebar_start TEXT NULL;"),
            ("sidebar_end",   "ALTER TABLE districts ADD COLUMN sidebar_end TEXT NULL;"),
            ("logo_path",     "ALTER TABLE districts ADD COLUMN logo_path TEXT NULL;"),
        ]:
            if col not in cols:
                conn.execute(ddl)

    def _migrate_schools_table(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(schools);").fetchall()}
        for col, ddl in [
            ("accent",        "ALTER TABLE schools ADD COLUMN accent TEXT NULL;"),
            ("accent_strong", "ALTER TABLE schools ADD COLUMN accent_strong TEXT NULL;"),
            ("sidebar_start", "ALTER TABLE schools ADD COLUMN sidebar_start TEXT NULL;"),
            ("sidebar_end",   "ALTER TABLE schools ADD COLUMN sidebar_end TEXT NULL;"),
            ("setup_pin_salt","ALTER TABLE schools ADD COLUMN setup_pin_salt TEXT NULL;"),
            ("setup_pin_hash","ALTER TABLE schools ADD COLUMN setup_pin_hash TEXT NULL;"),
            # Safe: existing rows get NULL — they continue to work without a district.
            ("district_id",   "ALTER TABLE schools ADD COLUMN district_id INTEGER NULL REFERENCES districts(id);"),
            ("logo_path",     "ALTER TABLE schools ADD COLUMN logo_path TEXT NULL;"),
            ("sort_order",    "ALTER TABLE schools ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;"),
        ]:
            if col not in cols:
                conn.execute(ddl)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _school_from_row(row: sqlite3.Row | tuple) -> SchoolRecord:
        # Column order matches _SCHOOL_COLS:
        # 0=id, 1=created_at, 2=slug, 3=name, 4=is_active,
        # 5=accent, 6=accent_strong, 7=sidebar_start, 8=sidebar_end,
        # 9=setup_pin_salt, 10=setup_pin_hash, 11=district_id, 12=logo_path, 13=sort_order
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
            district_id=int(row[11]) if len(row) > 11 and row[11] is not None else None,
            logo_path=str(row[12]) if len(row) > 12 and row[12] is not None else None,
            sort_order=int(row[13]) if len(row) > 13 and row[13] is not None else 0,
        )

    # Kept for backward compatibility — external callers use this name.
    def _row_to_record(self, row: sqlite3.Row | tuple) -> SchoolRecord:
        return self._school_from_row(row)

    @staticmethod
    def _org_from_row(row: sqlite3.Row | tuple) -> OrganizationRecord:
        return OrganizationRecord(
            id=int(row[0]),
            created_at=str(row[1]),
            name=str(row[2]),
            slug=str(row[3]),
            is_active=bool(int(row[4])),
        )

    @staticmethod
    def _district_from_row(row: sqlite3.Row | tuple) -> DistrictRecord:
        # 0=id, 1=created_at, 2=name, 3=slug, 4=organization_id, 5=is_active,
        # 6=accent, 7=accent_strong, 8=sidebar_start, 9=sidebar_end, 10=logo_path
        return DistrictRecord(
            id=int(row[0]),
            created_at=str(row[1]),
            name=str(row[2]),
            slug=str(row[3]),
            organization_id=int(row[4]),
            is_active=bool(int(row[5])),
            accent=str(row[6]) if len(row) > 6 and row[6] is not None else None,
            accent_strong=str(row[7]) if len(row) > 7 and row[7] is not None else None,
            sidebar_start=str(row[8]) if len(row) > 8 and row[8] is not None else None,
            sidebar_end=str(row[9]) if len(row) > 9 and row[9] is not None else None,
            logo_path=str(row[10]) if len(row) > 10 and row[10] is not None else None,
        )

    # ── Schools ───────────────────────────────────────────────────────────────

    def _ensure_school_sync(self, slug: str, name: str) -> SchoolRecord:
        normalized_slug = slug.strip().lower()
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO schools (
                    created_at, slug, name, is_active,
                    accent, accent_strong, sidebar_start, sidebar_end,
                    setup_pin_salt, setup_pin_hash, district_id
                )
                VALUES (?, ?, ?, 1, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                ON CONFLICT(slug) DO UPDATE SET name = schools.name;
                """,
                (datetime.now(timezone.utc).isoformat(), normalized_slug, name.strip()),
            )
            row = conn.execute(
                f"SELECT {_SCHOOL_COLS} FROM schools WHERE slug = ? LIMIT 1;",
                (normalized_slug,),
            ).fetchone()
        assert row is not None
        return self._school_from_row(row)

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
                    setup_pin_salt, setup_pin_hash, district_id
                )
                VALUES (?, ?, ?, 1, NULL, NULL, NULL, NULL, ?, ?, NULL);
                """,
                (created_at, normalized_slug, name.strip(), pin_salt, pin_hash),
            )
            row = conn.execute(
                f"SELECT {_SCHOOL_COLS} FROM schools WHERE id = ? LIMIT 1;",
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._school_from_row(row)

    async def create_school(self, *, slug: str, name: str, setup_pin: Optional[str] = None) -> SchoolRecord:
        normalized_pin = setup_pin.strip() if setup_pin else None
        return await anyio.to_thread.run_sync(self._create_school_sync, slug, name, normalized_pin or None)

    def _get_by_slug_sync(self, slug: str) -> Optional[SchoolRecord]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_SCHOOL_COLS} FROM schools WHERE slug = ? LIMIT 1;",
                (slug.strip().lower(),),
            ).fetchone()
        return self._school_from_row(row) if row is not None else None

    async def get_by_slug(self, slug: str) -> Optional[SchoolRecord]:
        return await anyio.to_thread.run_sync(self._get_by_slug_sync, slug)

    def _list_schools_sync(self) -> List[SchoolRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_SCHOOL_COLS} FROM schools ORDER BY name ASC, slug ASC;"
            ).fetchall()
        return [self._school_from_row(row) for row in rows]

    async def list_schools(self) -> List[SchoolRecord]:
        return await anyio.to_thread.run_sync(self._list_schools_sync)

    def _verify_setup_pin_sync(self, slug: str, setup_pin: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT setup_pin_salt, setup_pin_hash FROM schools WHERE slug = ? LIMIT 1;",
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
                "UPDATE schools SET setup_pin_salt = ?, setup_pin_hash = ? WHERE slug = ?;",
                (pin_salt, pin_hash, normalized_slug),
            )
            row = conn.execute(
                f"SELECT {_SCHOOL_COLS} FROM schools WHERE slug = ? LIMIT 1;",
                (normalized_slug,),
            ).fetchone()
        return self._school_from_row(row) if row is not None else None

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
                f"SELECT {_SCHOOL_COLS} FROM schools WHERE slug = ? LIMIT 1;",
                (normalized_slug,),
            ).fetchone()
        return self._school_from_row(row) if row is not None else None

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

    def _update_name_sync(self, slug: str, name: str) -> Optional[SchoolRecord]:
        normalized_slug = slug.strip().lower()
        with self._connect() as conn:
            conn.execute(
                "UPDATE schools SET name = ? WHERE slug = ?;",
                (name.strip(), normalized_slug),
            )
            row = conn.execute(
                f"SELECT {_SCHOOL_COLS} FROM schools WHERE slug = ? LIMIT 1;",
                (normalized_slug,),
            ).fetchone()
        return self._school_from_row(row) if row is not None else None

    async def update_name(self, *, slug: str, name: str) -> Optional[SchoolRecord]:
        return await anyio.to_thread.run_sync(self._update_name_sync, slug, name)

    def _update_logo_path_sync(self, slug: str, logo_path: Optional[str]) -> Optional[SchoolRecord]:
        normalized_slug = slug.strip().lower()
        with self._connect() as conn:
            conn.execute(
                "UPDATE schools SET logo_path = ? WHERE slug = ?;",
                (logo_path, normalized_slug),
            )
            row = conn.execute(
                f"SELECT {_SCHOOL_COLS} FROM schools WHERE slug = ? LIMIT 1;",
                (normalized_slug,),
            ).fetchone()
        return self._school_from_row(row) if row is not None else None

    async def update_logo_path(self, *, slug: str, logo_path: Optional[str]) -> Optional[SchoolRecord]:
        return await anyio.to_thread.run_sync(self._update_logo_path_sync, slug, logo_path)

    def _assign_to_district_sync(self, school_slug: str, district_id: Optional[int]) -> Optional[SchoolRecord]:
        """Set or clear the district_id on a school. Slug never changes."""
        normalized_slug = school_slug.strip().lower()
        with self._connect() as conn:
            conn.execute(
                "UPDATE schools SET district_id = ? WHERE slug = ?;",
                (district_id, normalized_slug),
            )
            row = conn.execute(
                f"SELECT {_SCHOOL_COLS} FROM schools WHERE slug = ? LIMIT 1;",
                (normalized_slug,),
            ).fetchone()
        return self._school_from_row(row) if row is not None else None

    async def assign_to_district(self, *, school_slug: str, district_id: Optional[int]) -> Optional[SchoolRecord]:
        """Assign a school to a district (or clear with district_id=None). Slug is not modified."""
        return await anyio.to_thread.run_sync(self._assign_to_district_sync, school_slug, district_id)

    def _list_schools_by_district_sync(self, district_id: int) -> List[SchoolRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_SCHOOL_COLS} FROM schools WHERE district_id = ? ORDER BY sort_order ASC, name ASC;",
                (int(district_id),),
            ).fetchall()
        return [self._school_from_row(row) for row in rows]

    async def list_schools_by_district(self, district_id: int) -> List[SchoolRecord]:
        return await anyio.to_thread.run_sync(self._list_schools_by_district_sync, int(district_id))

    def _reorder_schools_in_district_sync(
        self, district_id: int, ordered_slugs: List[str]
    ) -> None:
        """Set sort_order for each slug. Validates all slugs belong to district_id first."""
        normalized = [s.strip().lower() for s in ordered_slugs if s.strip()]
        if not normalized:
            return
        placeholders = ",".join("?" * len(normalized))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT slug, district_id FROM schools WHERE slug IN ({placeholders});",
                normalized,
            ).fetchall()
            found = {str(r[0]): r[1] for r in rows}
            for slug in normalized:
                if slug not in found:
                    raise ValueError(f"School not found: {slug!r}")
                school_district = found[slug]
                if school_district is None or int(school_district) != int(district_id):
                    raise ValueError(
                        f"School {slug!r} does not belong to district {district_id}"
                    )
            for order_idx, slug in enumerate(normalized):
                conn.execute(
                    "UPDATE schools SET sort_order = ? WHERE slug = ?;",
                    (order_idx, slug),
                )

    async def reorder_schools_in_district(
        self, *, district_id: int, ordered_slugs: List[str]
    ) -> None:
        """Reorder schools within a district. Raises ValueError for cross-district slugs."""
        await anyio.to_thread.run_sync(
            self._reorder_schools_in_district_sync, int(district_id), list(ordered_slugs)
        )

    # ── Organizations ─────────────────────────────────────────────────────────

    def _create_organization_sync(self, name: str, slug: str) -> OrganizationRecord:
        normalized_slug = slug.strip().lower()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO organizations (created_at, name, slug, is_active)
                VALUES (?, ?, ?, 1);
                """,
                (datetime.now(timezone.utc).isoformat(), name.strip(), normalized_slug),
            )
            row = conn.execute(
                "SELECT id, created_at, name, slug, is_active FROM organizations WHERE id = ? LIMIT 1;",
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._org_from_row(row)

    async def create_organization(self, *, name: str, slug: str) -> OrganizationRecord:
        return await anyio.to_thread.run_sync(self._create_organization_sync, name, slug)

    def _get_organization_sync(self, org_id: int) -> Optional[OrganizationRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, created_at, name, slug, is_active FROM organizations WHERE id = ? LIMIT 1;",
                (int(org_id),),
            ).fetchone()
        return self._org_from_row(row) if row is not None else None

    async def get_organization(self, org_id: int) -> Optional[OrganizationRecord]:
        return await anyio.to_thread.run_sync(self._get_organization_sync, int(org_id))

    def _get_organization_by_slug_sync(self, slug: str) -> Optional[OrganizationRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, created_at, name, slug, is_active FROM organizations WHERE slug = ? LIMIT 1;",
                (slug.strip().lower(),),
            ).fetchone()
        return self._org_from_row(row) if row is not None else None

    async def get_organization_by_slug(self, slug: str) -> Optional[OrganizationRecord]:
        return await anyio.to_thread.run_sync(self._get_organization_by_slug_sync, slug)

    def _list_organizations_sync(self) -> List[OrganizationRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, name, slug, is_active FROM organizations ORDER BY name ASC;"
            ).fetchall()
        return [self._org_from_row(row) for row in rows]

    async def list_organizations(self) -> List[OrganizationRecord]:
        return await anyio.to_thread.run_sync(self._list_organizations_sync)

    # ── Districts ─────────────────────────────────────────────────────────────

    def _create_district_sync(self, name: str, slug: str, organization_id: int) -> DistrictRecord:
        normalized_slug = slug.strip().lower()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO districts (created_at, name, slug, organization_id, is_active)
                VALUES (?, ?, ?, ?, 1);
                """,
                (datetime.now(timezone.utc).isoformat(), name.strip(), normalized_slug, int(organization_id)),
            )
            row = conn.execute(
                f"SELECT {_DISTRICT_COLS} FROM districts WHERE id = ? LIMIT 1;",
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._district_from_row(row)

    async def create_district(self, *, name: str, slug: str, organization_id: int) -> DistrictRecord:
        return await anyio.to_thread.run_sync(self._create_district_sync, name, slug, int(organization_id))

    def _get_district_sync(self, district_id: int) -> Optional[DistrictRecord]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_DISTRICT_COLS} FROM districts WHERE id = ? LIMIT 1;",
                (int(district_id),),
            ).fetchone()
        return self._district_from_row(row) if row is not None else None

    async def get_district(self, district_id: int) -> Optional[DistrictRecord]:
        return await anyio.to_thread.run_sync(self._get_district_sync, int(district_id))

    def _get_district_by_slug_sync(self, slug: str) -> Optional[DistrictRecord]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_DISTRICT_COLS} FROM districts WHERE slug = ? LIMIT 1;",
                (slug.strip().lower(),),
            ).fetchone()
        return self._district_from_row(row) if row is not None else None

    async def get_district_by_slug(self, slug: str) -> Optional[DistrictRecord]:
        return await anyio.to_thread.run_sync(self._get_district_by_slug_sync, slug)

    def _list_districts_sync(self, organization_id: Optional[int] = None) -> List[DistrictRecord]:
        with self._connect() as conn:
            if organization_id is not None:
                rows = conn.execute(
                    f"SELECT {_DISTRICT_COLS} FROM districts WHERE organization_id = ? ORDER BY name ASC;",
                    (int(organization_id),),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {_DISTRICT_COLS} FROM districts ORDER BY name ASC;"
                ).fetchall()
        return [self._district_from_row(row) for row in rows]

    async def list_districts(self, *, organization_id: Optional[int] = None) -> List[DistrictRecord]:
        return await anyio.to_thread.run_sync(self._list_districts_sync, organization_id)

    def _update_district_theme_sync(
        self,
        district_id: int,
        accent: Optional[str],
        accent_strong: Optional[str],
        sidebar_start: Optional[str],
        sidebar_end: Optional[str],
    ) -> Optional[DistrictRecord]:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE districts
                SET accent = ?, accent_strong = ?, sidebar_start = ?, sidebar_end = ?
                WHERE id = ?;
                """,
                (
                    accent.strip() if accent else None,
                    accent_strong.strip() if accent_strong else None,
                    sidebar_start.strip() if sidebar_start else None,
                    sidebar_end.strip() if sidebar_end else None,
                    int(district_id),
                ),
            )
            row = conn.execute(
                f"SELECT {_DISTRICT_COLS} FROM districts WHERE id = ? LIMIT 1;",
                (int(district_id),),
            ).fetchone()
        return self._district_from_row(row) if row is not None else None

    async def update_district_theme(
        self,
        *,
        district_id: int,
        accent: Optional[str],
        accent_strong: Optional[str],
        sidebar_start: Optional[str],
        sidebar_end: Optional[str],
    ) -> Optional[DistrictRecord]:
        return await anyio.to_thread.run_sync(
            self._update_district_theme_sync,
            int(district_id), accent, accent_strong, sidebar_start, sidebar_end,
        )

    def _update_district_logo_path_sync(self, district_id: int, logo_path: Optional[str]) -> Optional[DistrictRecord]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE districts SET logo_path = ? WHERE id = ?;",
                (logo_path, int(district_id)),
            )
            row = conn.execute(
                f"SELECT {_DISTRICT_COLS} FROM districts WHERE id = ? LIMIT 1;",
                (int(district_id),),
            ).fetchone()
        return self._district_from_row(row) if row is not None else None

    async def update_district_logo_path(self, *, district_id: int, logo_path: Optional[str]) -> Optional[DistrictRecord]:
        return await anyio.to_thread.run_sync(self._update_district_logo_path_sync, int(district_id), logo_path)

    # ── Theme presets ─────────────────────────────────────────────────────────

    def _add_theme_preset_sync(
        self, tenant_slug: str, name: str,
        accent: str, accent_strong: str, sidebar_start: str, sidebar_end: str,
        created_by: str,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO tenant_theme_presets
                   (created_at, tenant_slug, name, accent, accent_strong, sidebar_start, sidebar_end, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
                (now, tenant_slug.strip().lower(), name.strip(),
                 (accent or "").strip(), (accent_strong or "").strip(),
                 (sidebar_start or "").strip(), (sidebar_end or "").strip(),
                 created_by.strip()),
            )
            pid = cur.lastrowid
        return {"id": pid, "created_at": now, "tenant_slug": tenant_slug,
                "name": name, "accent": accent, "accent_strong": accent_strong,
                "sidebar_start": sidebar_start, "sidebar_end": sidebar_end,
                "created_by": created_by, "is_global": False}

    async def add_theme_preset(
        self, *, tenant_slug: str, name: str,
        accent: str, accent_strong: str, sidebar_start: str, sidebar_end: str,
        created_by: str,
    ) -> dict:
        return await anyio.to_thread.run_sync(
            self._add_theme_preset_sync,
            tenant_slug, name, accent, accent_strong, sidebar_start, sidebar_end, created_by,
        )

    def _list_theme_presets_sync(self, tenant_slug: str) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, created_at, tenant_slug, name, accent, accent_strong,
                          sidebar_start, sidebar_end, created_by
                   FROM tenant_theme_presets
                   WHERE tenant_slug = ? OR tenant_slug IS NULL
                   ORDER BY (tenant_slug IS NULL) DESC, name ASC;""",
                (tenant_slug.strip().lower(),),
            ).fetchall()
        return [
            {"id": r[0], "created_at": r[1], "tenant_slug": r[2], "name": r[3],
             "accent": r[4] or "", "accent_strong": r[5] or "",
             "sidebar_start": r[6] or "", "sidebar_end": r[7] or "",
             "created_by": r[8] or "", "is_global": r[2] is None}
            for r in rows
        ]

    async def list_theme_presets(self, tenant_slug: str) -> list:
        return await anyio.to_thread.run_sync(self._list_theme_presets_sync, tenant_slug)

    def _delete_theme_preset_sync(self, preset_id: int, tenant_slug: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM tenant_theme_presets WHERE id = ? AND tenant_slug = ?;",
                (int(preset_id), tenant_slug.strip().lower()),
            )
        return (cur.rowcount or 0) > 0

    async def delete_theme_preset(self, preset_id: int, tenant_slug: str) -> bool:
        return await anyio.to_thread.run_sync(self._delete_theme_preset_sync, int(preset_id), tenant_slug)

    # ── Operator notes ────────────────────────────────────────────────────────
    # Super-admin-only internal notes per district or school. Never exposed to tenants.

    def _add_note_sync(self, tenant_slug: str, note_text: str, created_by: str) -> dict[str, object]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO operator_notes (created_at, tenant_slug, note_text, created_by) VALUES (?, ?, ?, ?);",
                (now, tenant_slug.strip().lower(), note_text.strip(), created_by.strip()),
            )
            note_id = cur.lastrowid
        return {"id": note_id, "created_at": now, "tenant_slug": tenant_slug, "note_text": note_text, "created_by": created_by}

    async def add_operator_note(self, *, tenant_slug: str, note_text: str, created_by: str) -> dict[str, object]:
        return await anyio.to_thread.run_sync(self._add_note_sync, tenant_slug, note_text, created_by)

    def _list_notes_sync(self, tenant_slug: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, tenant_slug, note_text, created_by FROM operator_notes WHERE tenant_slug = ? ORDER BY created_at DESC;",
                (tenant_slug.strip().lower(),),
            ).fetchall()
        return [{"id": r[0], "created_at": r[1], "tenant_slug": r[2], "note_text": r[3], "created_by": r[4]} for r in rows]

    async def list_operator_notes(self, tenant_slug: str) -> list[dict[str, object]]:
        return await anyio.to_thread.run_sync(self._list_notes_sync, tenant_slug)

    def _delete_note_sync(self, note_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM operator_notes WHERE id = ?;", (int(note_id),))
        return (cur.rowcount or 0) > 0

    async def delete_operator_note(self, note_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._delete_note_sync, int(note_id))

    # ── Slug aliases ─────────────────────────────────────────────────────────
    # Maps old slugs to canonical ones so old API clients keep working.

    def _register_alias_sync(self, old_slug: str, new_slug: str, reason: Optional[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tenant_slug_aliases (old_slug, new_slug, created_at, reason)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(old_slug) DO UPDATE SET new_slug = excluded.new_slug, reason = excluded.reason;
                """,
                (old_slug.strip().lower(), new_slug.strip().lower(),
                 datetime.now(timezone.utc).isoformat(), reason),
            )

    async def register_alias(self, old_slug: str, new_slug: str, *, reason: Optional[str] = None) -> None:
        """Register old_slug as an alias for new_slug. Idempotent."""
        await anyio.to_thread.run_sync(self._register_alias_sync, old_slug, new_slug, reason)

    def resolve_alias_sync(self, slug: str) -> Optional[str]:
        """Return the canonical slug for old_slug, or None if no alias exists."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT new_slug FROM tenant_slug_aliases WHERE old_slug = ? LIMIT 1;",
                (slug.strip().lower(),),
            ).fetchone()
        return str(row[0]) if row is not None else None

    async def resolve_alias(self, slug: str) -> Optional[str]:
        return await anyio.to_thread.run_sync(self.resolve_alias_sync, slug)

    def _list_aliases_sync(self) -> List[SlugAliasRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT old_slug, new_slug, created_at, reason FROM tenant_slug_aliases ORDER BY old_slug ASC;"
            ).fetchall()
        return [
            SlugAliasRecord(old_slug=str(r[0]), new_slug=str(r[1]), created_at=str(r[2]),
                            reason=str(r[3]) if r[3] is not None else None)
            for r in rows
        ]

    async def list_aliases(self) -> List[SlugAliasRecord]:
        return await anyio.to_thread.run_sync(self._list_aliases_sync)
