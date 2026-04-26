#!/usr/bin/env python3
"""
One-time migration: rename the "default" tenant slug to "nen".

Run ONCE before or immediately after deploying the config change.
Safe to re-run — all updates are idempotent (WHERE clauses filter by old value).

Usage:
    python3 scripts/migrate_default_to_nen.py [--dry-run]

Dry-run prints what would change without writing anything.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

OLD_SLUG = "default"
NEW_SLUG = "nen"
NEW_NAME = "Northeast Nodaway RV School District"

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

# Paths — override with env vars if needed.
PLATFORM_DB = Path(os.environ.get("PLATFORM_DB_PATH", str(BACKEND_ROOT / "data" / "platform.db")))
TENANT_DB = Path(os.environ.get("DB_PATH", str(BACKEND_ROOT / "data" / "bluebird.db")))


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def backup(path: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = path.with_suffix(f".pre_nen_migration_{ts}.db")
    shutil.copy2(path, dest)
    print(f"  Backed up {path.name} → {dest.name}")
    return dest


def table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table});").fetchall()}
    return column in cols


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table,)
    ).fetchone()
    return row is not None


def migrate_platform_db(dry_run: bool) -> None:
    print(f"\n{'[DRY RUN] ' if dry_run else ''}=== platform.db ({PLATFORM_DB}) ===")

    if not PLATFORM_DB.exists():
        print("  platform.db does not exist — will be created fresh with 'nen' on first startup.")
        return

    if not dry_run:
        backup(PLATFORM_DB)

    conn = connect(PLATFORM_DB)

    # schools table: update slug and name.
    if table_exists(conn, "schools"):
        row = conn.execute(
            "SELECT id, slug, name FROM schools WHERE slug = ?;", (OLD_SLUG,)
        ).fetchone()
        if row:
            print(f"  schools: found id={row[0]} slug='{row[1]}' name='{row[2]}'")
            if not dry_run:
                conn.execute(
                    "UPDATE schools SET slug = ?, name = ? WHERE slug = ?;",
                    (NEW_SLUG, NEW_NAME, OLD_SLUG),
                )
                print(f"  schools: updated slug '{OLD_SLUG}' → '{NEW_SLUG}', name → '{NEW_NAME}'")
            else:
                print(f"  [DRY RUN] schools: would update slug '{OLD_SLUG}' → '{NEW_SLUG}', name → '{NEW_NAME}'")
        else:
            already = conn.execute("SELECT id, slug, name FROM schools WHERE slug = ?;", (NEW_SLUG,)).fetchone()
            if already:
                print(f"  schools: slug '{NEW_SLUG}' already exists (id={already[0]}) — no action needed.")
            else:
                print(f"  schools: no row with slug '{OLD_SLUG}' found — nothing to migrate.")

    # access_codes table: tenant_slug column.
    if table_exists(conn, "access_codes") and table_has_column(conn, "access_codes", "tenant_slug"):
        count = conn.execute(
            "SELECT COUNT(*) FROM access_codes WHERE tenant_slug = ?;", (OLD_SLUG,)
        ).fetchone()[0]
        print(f"  access_codes: {count} rows with tenant_slug='{OLD_SLUG}'")
        if count > 0:
            if not dry_run:
                conn.execute(
                    "UPDATE access_codes SET tenant_slug = ? WHERE tenant_slug = ?;",
                    (NEW_SLUG, OLD_SLUG),
                )
                print(f"  access_codes: updated {count} rows.")
            else:
                print(f"  [DRY RUN] access_codes: would update {count} rows.")

    # tenant_slug_aliases: ensure old_slug → new_slug is recorded.
    if table_exists(conn, "tenant_slug_aliases"):
        existing = conn.execute(
            "SELECT new_slug FROM tenant_slug_aliases WHERE old_slug = ?;", (OLD_SLUG,)
        ).fetchone()
        if not existing:
            if not dry_run:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO tenant_slug_aliases (old_slug, new_slug, created_at, reason)
                    VALUES (?, ?, ?, ?);
                    """,
                    (OLD_SLUG, NEW_SLUG, datetime.now(timezone.utc).isoformat(),
                     "tenant_slug_migrated: default → nen (Northeast Nodaway RV School District)"),
                )
                print(f"  tenant_slug_aliases: registered '{OLD_SLUG}' → '{NEW_SLUG}'.")
            else:
                print(f"  [DRY RUN] tenant_slug_aliases: would register '{OLD_SLUG}' → '{NEW_SLUG}'.")
        else:
            print(f"  tenant_slug_aliases: alias '{OLD_SLUG}' → '{existing[0]}' already present.")

    conn.close()


def migrate_tenant_db(dry_run: bool) -> None:
    print(f"\n{'[DRY RUN] ' if dry_run else ''}=== tenant db ({TENANT_DB}) ===")

    if not TENANT_DB.exists():
        print("  tenant db does not exist — nothing to migrate.")
        return

    if not dry_run:
        backup(TENANT_DB)

    conn = connect(TENANT_DB)

    # Tables that store tenant_slug (added by migration on first startup).
    tenant_slug_tables = ["alarm_state", "alert_acknowledgements", "audit_log"]

    for tbl in tenant_slug_tables:
        if not table_exists(conn, tbl):
            print(f"  {tbl}: table does not exist yet — skipping.")
            continue
        if not table_has_column(conn, tbl, "tenant_slug"):
            print(f"  {tbl}: no tenant_slug column yet — will be set to '' by migration, then 'nen' by next write.")
            continue

        # Update both '' (migration default) and 'default' (explicit old value).
        for old_val in ("", OLD_SLUG):
            count = conn.execute(
                f"SELECT COUNT(*) FROM {tbl} WHERE tenant_slug = ?;", (old_val,)
            ).fetchone()[0]
            if count > 0:
                print(f"  {tbl}: {count} rows with tenant_slug='{old_val}'")
                if not dry_run:
                    conn.execute(
                        f"UPDATE {tbl} SET tenant_slug = ? WHERE tenant_slug = ?;",
                        (NEW_SLUG, old_val),
                    )
                    print(f"  {tbl}: updated {count} rows → '{NEW_SLUG}'.")
                else:
                    print(f"  [DRY RUN] {tbl}: would update {count} rows → '{NEW_SLUG}'.")

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate 'default' tenant slug to 'nen'.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing.")
    args = parser.parse_args()

    print(f"BlueBird Tenant Slug Migration: '{OLD_SLUG}' → '{NEW_SLUG}'")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    if args.dry_run:
        print("MODE: DRY RUN — no changes will be written.")

    migrate_platform_db(args.dry_run)
    migrate_tenant_db(args.dry_run)

    print("\nMigration complete." if not args.dry_run else "\nDry run complete — re-run without --dry-run to apply.")


if __name__ == "__main__":
    main()
