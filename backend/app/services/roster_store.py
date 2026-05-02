from __future__ import annotations

import csv
import io
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import anyio

from app.core.db import optimized_connect

ALLOWED_GRADES = frozenset(
    ["PreK", "K"] + [str(i) for i in range(1, 13)] + ["Other"]
)

ALLOWED_CLAIM_STATUSES = frozenset(
    ["present_with_me", "absent", "missing", "injured", "released", "unknown"]
)

TAKEOVER_WINDOW_SECONDS = 30

_ACCOUNTED_STATUSES = frozenset({"present_with_me", "absent", "injured", "released"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Data records
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StudentRecord:
    id: int
    created_at: str
    updated_at: str
    first_name: str
    last_name: str
    grade_level: str
    student_ref: Optional[str]
    is_archived: bool
    archived_at: Optional[str]


@dataclass(frozen=True)
class RosterClaimRecord:
    id: int
    alert_id: int
    student_id: Optional[int]
    addition_id: Optional[int]
    claimed_by_user_id: int
    claimed_by_label: str
    status: str
    claimed_at: str
    last_updated_at: str
    last_updated_by_user_id: int


@dataclass(frozen=True)
class RosterAdditionRecord:
    id: int
    alert_id: int
    first_name: str
    last_name: str
    grade_level: str
    note: Optional[str]
    added_by_user_id: int
    added_by_label: str
    created_at: str


@dataclass(frozen=True)
class RosterClaimHistoryRecord:
    id: int
    alert_id: int
    student_id: Optional[int]
    addition_id: Optional[int]
    previous_claimed_by_user_id: Optional[int]
    previous_claimed_by_label: Optional[str]
    new_claimed_by_user_id: Optional[int]
    new_claimed_by_label: Optional[str]
    previous_status: Optional[str]
    new_status: str
    changed_by_user_id: int
    changed_by_label: str
    changed_at: str
    change_type: str
    note: Optional[str]


@dataclass(frozen=True)
class ClaimConflict:
    """Returned when a claim hits the takeover-confirmation window."""
    was_claimed_by_user_id: int
    was_claimed_by_label: str
    claimed_seconds_ago: float
    requires_confirmation: bool = True


@dataclass(frozen=True)
class ClaimResult:
    claim: RosterClaimRecord
    conflict: Optional[ClaimConflict]
    history_id: int


@dataclass
class ImportPreviewRow:
    line: int
    first_name: str
    last_name: str
    grade_level: str
    student_ref: Optional[str]


@dataclass
class ImportErrorRow:
    line: int
    error: str
    raw: str


@dataclass
class ImportPreview:
    session_token: str
    valid_rows: list[ImportPreviewRow]
    error_rows: list[ImportErrorRow]
    duplicate_refs: list[dict]


@dataclass
class ImportResult:
    inserted: int
    skipped_duplicates: int
    error_count: int


# ─────────────────────────────────────────────────────────────────────────────
# RosterStore
# ─────────────────────────────────────────────────────────────────────────────

class RosterStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._import_sessions: dict[str, list[ImportPreviewRow]] = {}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return optimized_connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS students (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at  TEXT    NOT NULL,
                    updated_at  TEXT    NOT NULL,
                    first_name  TEXT    NOT NULL,
                    last_name   TEXT    NOT NULL,
                    grade_level TEXT    NOT NULL,
                    student_ref TEXT    NULL,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    archived_at TEXT    NULL
                );
                CREATE INDEX IF NOT EXISTS idx_students_grade
                    ON students(grade_level) WHERE is_archived = 0;
                CREATE INDEX IF NOT EXISTS idx_students_name
                    ON students(last_name, first_name) WHERE is_archived = 0;
                CREATE INDEX IF NOT EXISTS idx_students_ref
                    ON students(student_ref) WHERE student_ref IS NOT NULL;

                CREATE TABLE IF NOT EXISTS roster_additions (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id         INTEGER NOT NULL,
                    first_name       TEXT    NOT NULL,
                    last_name        TEXT    NOT NULL,
                    grade_level      TEXT    NOT NULL,
                    note             TEXT    NULL,
                    added_by_user_id INTEGER NOT NULL,
                    added_by_label   TEXT    NOT NULL,
                    created_at       TEXT    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ra_alert ON roster_additions(alert_id);

                CREATE TABLE IF NOT EXISTS roster_claims (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id                INTEGER NOT NULL,
                    student_id              INTEGER NULL,
                    addition_id             INTEGER NULL,
                    claimed_by_user_id      INTEGER NOT NULL,
                    claimed_by_label        TEXT    NOT NULL,
                    status                  TEXT    NOT NULL DEFAULT 'present_with_me',
                    claimed_at              TEXT    NOT NULL,
                    last_updated_at         TEXT    NOT NULL,
                    last_updated_by_user_id INTEGER NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uix_roster_claim_student
                    ON roster_claims(alert_id, student_id)
                    WHERE student_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS uix_roster_claim_addition
                    ON roster_claims(alert_id, addition_id)
                    WHERE addition_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS roster_claim_history (
                    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id                    INTEGER NOT NULL,
                    student_id                  INTEGER NULL,
                    addition_id                 INTEGER NULL,
                    previous_claimed_by_user_id INTEGER NULL,
                    previous_claimed_by_label   TEXT    NULL,
                    new_claimed_by_user_id      INTEGER NULL,
                    new_claimed_by_label        TEXT    NULL,
                    previous_status             TEXT    NULL,
                    new_status                  TEXT    NOT NULL,
                    changed_by_user_id          INTEGER NOT NULL,
                    changed_by_label            TEXT    NOT NULL,
                    changed_at                  TEXT    NOT NULL,
                    change_type                 TEXT    NOT NULL,
                    note                        TEXT    NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rch_alert
                    ON roster_claim_history(alert_id);
                CREATE INDEX IF NOT EXISTS idx_rch_student
                    ON roster_claim_history(student_id) WHERE student_id IS NOT NULL;
                """
            )

    # ── Students ──────────────────────────────────────────────────────────────

    def list_students_sync(
        self,
        *,
        grade: Optional[str] = None,
        q: Optional[str] = None,
        include_archived: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[StudentRecord]:
        conditions = []
        params: list = []
        if not include_archived:
            conditions.append("is_archived = 0")
        if grade:
            conditions.append("grade_level = ?")
            params.append(grade)
        if q:
            like = f"%{q}%"
            conditions.append("(first_name LIKE ? OR last_name LIKE ? OR student_ref LIKE ?)")
            params.extend([like, like, like])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = (
            f"SELECT id, created_at, updated_at, first_name, last_name, "
            f"grade_level, student_ref, is_archived, archived_at "
            f"FROM students {where} ORDER BY last_name, first_name"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_student(r) for r in rows]

    def count_students_sync(
        self,
        *,
        grade: Optional[str] = None,
        q: Optional[str] = None,
        include_archived: bool = False,
    ) -> int:
        conditions = []
        params: list = []
        if not include_archived:
            conditions.append("is_archived = 0")
        if grade:
            conditions.append("grade_level = ?")
            params.append(grade)
        if q:
            like = f"%{q}%"
            conditions.append("(first_name LIKE ? OR last_name LIKE ? OR student_ref LIKE ?)")
            params.extend([like, like, like])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) FROM students {where}", params).fetchone()
        return row[0] if row else 0

    def get_student_sync(self, student_id: int) -> Optional[StudentRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, created_at, updated_at, first_name, last_name, "
                "grade_level, student_ref, is_archived, archived_at "
                "FROM students WHERE id = ?",
                (student_id,),
            ).fetchone()
        return self._row_to_student(row) if row else None

    def create_student_sync(
        self,
        *,
        first_name: str,
        last_name: str,
        grade_level: str,
        student_ref: Optional[str] = None,
    ) -> StudentRecord:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO students (created_at, updated_at, first_name, last_name, "
                "grade_level, student_ref) VALUES (?, ?, ?, ?, ?, ?)",
                (now, now, first_name.strip(), last_name.strip(), grade_level, student_ref),
            )
            student_id = cur.lastrowid
        return self.get_student_sync(student_id)  # type: ignore[return-value]

    def update_student_sync(
        self,
        student_id: int,
        *,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        grade_level: Optional[str] = None,
        student_ref: Optional[str] = None,
    ) -> Optional[StudentRecord]:
        now = _now()
        fields, params = ["updated_at = ?"], [now]
        if first_name is not None:
            fields.append("first_name = ?"); params.append(first_name.strip())
        if last_name is not None:
            fields.append("last_name = ?"); params.append(last_name.strip())
        if grade_level is not None:
            fields.append("grade_level = ?"); params.append(grade_level)
        if student_ref is not None:
            fields.append("student_ref = ?"); params.append(student_ref)
        params.append(student_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE students SET {', '.join(fields)} WHERE id = ?", params
            )
        return self.get_student_sync(student_id)

    def archive_student_sync(self, student_id: int) -> bool:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE students SET is_archived = 1, archived_at = ? WHERE id = ? AND is_archived = 0",
                (now, student_id),
            )
        return cur.rowcount > 0

    # ── CSV import ────────────────────────────────────────────────────────────

    def parse_csv_preview_sync(self, csv_bytes: bytes) -> ImportPreview:
        token = str(uuid.uuid4())
        valid: list[ImportPreviewRow] = []
        errors: list[ImportErrorRow] = []

        text = csv_bytes.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        required = {"first_name", "last_name", "grade_level"}
        headers = set(reader.fieldnames or [])
        missing = required - headers
        if missing:
            errors.append(ImportErrorRow(
                line=1,
                error=f"Missing required columns: {', '.join(sorted(missing))}",
                raw="(header row)",
            ))
            return ImportPreview(
                session_token=token, valid_rows=[], error_rows=errors, duplicate_refs=[]
            )

        for i, row in enumerate(reader, start=2):
            fn = (row.get("first_name") or "").strip()
            ln = (row.get("last_name") or "").strip()
            gl = (row.get("grade_level") or "").strip()
            ref = (row.get("student_ref") or "").strip() or None
            raw = ",".join(str(v) for v in row.values())
            row_errors = []
            if not fn:
                row_errors.append("first_name is required")
            if not ln:
                row_errors.append("last_name is required")
            if gl not in ALLOWED_GRADES:
                row_errors.append(f"grade_level '{gl}' not in allowed set")
            if row_errors:
                errors.append(ImportErrorRow(line=i, error="; ".join(row_errors), raw=raw))
            else:
                valid.append(ImportPreviewRow(line=i, first_name=fn, last_name=ln,
                                              grade_level=gl, student_ref=ref))

        # Duplicate ref detection
        refs = [r.student_ref for r in valid if r.student_ref]
        dup_refs: list[dict] = []
        if refs:
            with self._connect() as conn:
                placeholders = ",".join("?" * len(refs))
                rows = conn.execute(
                    f"SELECT student_ref, id, first_name, last_name FROM students "
                    f"WHERE student_ref IN ({placeholders}) AND is_archived = 0",
                    refs,
                ).fetchall()
                for r in rows:
                    dup_refs.append({
                        "student_ref": r[0],
                        "existing_id": r[1],
                        "existing_name": f"{r[2]} {r[3]}",
                    })

        self._import_sessions[token] = valid
        return ImportPreview(session_token=token, valid_rows=valid, error_rows=errors,
                             duplicate_refs=dup_refs)

    def commit_import_sync(
        self,
        session_token: str,
        *,
        conflict_strategy: str = "skip",  # "skip" | "overwrite"
    ) -> ImportResult:
        rows = self._import_sessions.pop(session_token, None)
        if rows is None:
            raise ValueError("Invalid or expired import session token")
        inserted = 0
        skipped = 0
        now = _now()
        with self._connect() as conn:
            for row in rows:
                if row.student_ref:
                    existing = conn.execute(
                        "SELECT id FROM students WHERE student_ref = ? AND is_archived = 0",
                        (row.student_ref,),
                    ).fetchone()
                    if existing:
                        if conflict_strategy == "overwrite":
                            conn.execute(
                                "UPDATE students SET first_name=?, last_name=?, grade_level=?, "
                                "updated_at=? WHERE id=?",
                                (row.first_name, row.last_name, row.grade_level, now, existing[0]),
                            )
                            inserted += 1
                        else:
                            skipped += 1
                        continue
                conn.execute(
                    "INSERT INTO students (created_at, updated_at, first_name, last_name, "
                    "grade_level, student_ref) VALUES (?,?,?,?,?,?)",
                    (now, now, row.first_name, row.last_name, row.grade_level, row.student_ref),
                )
                inserted += 1
        return ImportResult(inserted=inserted, skipped_duplicates=skipped, error_count=0)

    # ── Incident roster ───────────────────────────────────────────────────────

    def list_incident_roster_sync(self, alert_id: int) -> dict:
        with self._connect() as conn:
            students = conn.execute(
                "SELECT id, first_name, last_name, grade_level, student_ref "
                "FROM students WHERE is_archived = 0 ORDER BY last_name, first_name"
            ).fetchall()
            additions = conn.execute(
                "SELECT id, first_name, last_name, grade_level, note, "
                "added_by_user_id, added_by_label, created_at "
                "FROM roster_additions WHERE alert_id = ? ORDER BY last_name, first_name",
                (alert_id,),
            ).fetchall()
            claims = conn.execute(
                "SELECT id, alert_id, student_id, addition_id, claimed_by_user_id, "
                "claimed_by_label, status, claimed_at, last_updated_at, last_updated_by_user_id "
                "FROM roster_claims WHERE alert_id = ?",
                (alert_id,),
            ).fetchall()

        claim_by_student: dict[int, RosterClaimRecord] = {}
        claim_by_addition: dict[int, RosterClaimRecord] = {}
        for c in claims:
            rec = self._row_to_claim(c)
            if rec.student_id is not None:
                claim_by_student[rec.student_id] = rec
            elif rec.addition_id is not None:
                claim_by_addition[rec.addition_id] = rec

        entries = []
        for s in students:
            claim = claim_by_student.get(s[0])
            entries.append({
                "student_id": s[0],
                "addition_id": None,
                "first_name": s[1],
                "last_name": s[2],
                "grade_level": s[3],
                "student_ref": s[4],
                "source": "master",
                "note": None,
                "added_by_label": None,
                "claim": self._claim_to_dict(claim),
            })
        for a in additions:
            claim = claim_by_addition.get(a[0])
            entries.append({
                "student_id": None,
                "addition_id": a[0],
                "first_name": a[1],
                "last_name": a[2],
                "grade_level": a[3],
                "student_ref": None,
                "source": "incident_addition",
                "note": a[4],
                "added_by_label": a[6],
                "claim": self._claim_to_dict(claim),
            })

        all_claims = list(claim_by_student.values()) + list(claim_by_addition.values())
        summary = {
            "total": len(entries),
            "unclaimed": sum(1 for e in entries if e["claim"] is None),
            "present_with_me": sum(
                1 for c in all_claims if c.status == "present_with_me"
            ),
            "absent": sum(1 for c in all_claims if c.status == "absent"),
            "missing": sum(1 for c in all_claims if c.status == "missing"),
            "injured": sum(1 for c in all_claims if c.status == "injured"),
            "released": sum(1 for c in all_claims if c.status == "released"),
        }

        return {"alert_id": alert_id, "students": entries, "summary": summary}

    # ── Claims ────────────────────────────────────────────────────────────────

    def upsert_claim_sync(
        self,
        alert_id: int,
        *,
        student_id: Optional[int] = None,
        addition_id: Optional[int] = None,
        status: str,
        claimant_user_id: int,
        claimant_label: str,
        takeover_confirmed: bool = False,
        note: Optional[str] = None,
    ) -> ClaimResult:
        now = _now()
        conflict: Optional[ClaimConflict] = None

        with self._connect() as conn:
            # Fetch existing claim
            if student_id is not None:
                existing_row = conn.execute(
                    "SELECT id, claimed_by_user_id, claimed_by_label, status, claimed_at "
                    "FROM roster_claims WHERE alert_id = ? AND student_id = ?",
                    (alert_id, student_id),
                ).fetchone()
            else:
                existing_row = conn.execute(
                    "SELECT id, claimed_by_user_id, claimed_by_label, status, claimed_at "
                    "FROM roster_claims WHERE alert_id = ? AND addition_id = ?",
                    (alert_id, addition_id),
                ).fetchone()

            if existing_row:
                existing_owner = existing_row[1]
                existing_label = existing_row[2]
                existing_status = existing_row[3]
                existing_time_str = existing_row[4]

                try:
                    existing_time = datetime.fromisoformat(existing_time_str)
                    now_dt = datetime.now(timezone.utc)
                    age_secs = (now_dt - existing_time).total_seconds()
                except Exception:
                    age_secs = 9999

                is_same_claimer = existing_owner == claimant_user_id
                is_within_window = age_secs <= TAKEOVER_WINDOW_SECONDS
                is_takeover = not is_same_claimer

                if is_takeover and is_within_window and not takeover_confirmed:
                    # Return conflict — do not write
                    conflict = ClaimConflict(
                        was_claimed_by_user_id=existing_owner,
                        was_claimed_by_label=existing_label,
                        claimed_seconds_ago=age_secs,
                    )
                    # Still need to return a claim record — return existing
                    claim_rec = self._row_to_claim(conn.execute(
                        "SELECT id, alert_id, student_id, addition_id, claimed_by_user_id, "
                        "claimed_by_label, status, claimed_at, last_updated_at, "
                        "last_updated_by_user_id FROM roster_claims WHERE id = ?",
                        (existing_row[0],),
                    ).fetchone())
                    return ClaimResult(claim=claim_rec, conflict=conflict, history_id=-1)

                # Determine change type
                if is_takeover:
                    change_type = "takeover"
                elif existing_status != status:
                    change_type = "status_change"
                else:
                    change_type = "claim"

                # Write history
                hist_cur = conn.execute(
                    "INSERT INTO roster_claim_history "
                    "(alert_id, student_id, addition_id, previous_claimed_by_user_id, "
                    "previous_claimed_by_label, new_claimed_by_user_id, new_claimed_by_label, "
                    "previous_status, new_status, changed_by_user_id, changed_by_label, "
                    "changed_at, change_type, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        alert_id, student_id, addition_id,
                        existing_owner, existing_label,
                        claimant_user_id, claimant_label,
                        existing_status, status,
                        claimant_user_id, claimant_label,
                        now, change_type, note,
                    ),
                )
                history_id = hist_cur.lastrowid

                # Update existing claim
                conn.execute(
                    "UPDATE roster_claims SET claimed_by_user_id=?, claimed_by_label=?, "
                    "status=?, last_updated_at=?, last_updated_by_user_id=? WHERE id=?",
                    (claimant_user_id, claimant_label, status, now, claimant_user_id, existing_row[0]),
                )
                claim_rec = self._row_to_claim(conn.execute(
                    "SELECT id, alert_id, student_id, addition_id, claimed_by_user_id, "
                    "claimed_by_label, status, claimed_at, last_updated_at, "
                    "last_updated_by_user_id FROM roster_claims WHERE id = ?",
                    (existing_row[0],),
                ).fetchone())

            else:
                # New claim
                hist_cur = conn.execute(
                    "INSERT INTO roster_claim_history "
                    "(alert_id, student_id, addition_id, previous_claimed_by_user_id, "
                    "previous_claimed_by_label, new_claimed_by_user_id, new_claimed_by_label, "
                    "previous_status, new_status, changed_by_user_id, changed_by_label, "
                    "changed_at, change_type, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        alert_id, student_id, addition_id,
                        None, None,
                        claimant_user_id, claimant_label,
                        None, status,
                        claimant_user_id, claimant_label,
                        now, "claim", note,
                    ),
                )
                history_id = hist_cur.lastrowid

                claim_cur = conn.execute(
                    "INSERT INTO roster_claims "
                    "(alert_id, student_id, addition_id, claimed_by_user_id, claimed_by_label, "
                    "status, claimed_at, last_updated_at, last_updated_by_user_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (alert_id, student_id, addition_id,
                     claimant_user_id, claimant_label, status, now, now, claimant_user_id),
                )
                claim_rec = self._row_to_claim(conn.execute(
                    "SELECT id, alert_id, student_id, addition_id, claimed_by_user_id, "
                    "claimed_by_label, status, claimed_at, last_updated_at, "
                    "last_updated_by_user_id FROM roster_claims WHERE id = ?",
                    (claim_cur.lastrowid,),
                ).fetchone())

        return ClaimResult(claim=claim_rec, conflict=conflict, history_id=history_id)

    def release_claim_sync(
        self,
        alert_id: int,
        claim_id: int,
        *,
        released_by_user_id: int,
        released_by_label: str,
        note: Optional[str] = None,
    ) -> bool:
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, student_id, addition_id, claimed_by_user_id, "
                "claimed_by_label, status FROM roster_claims WHERE id = ? AND alert_id = ?",
                (claim_id, alert_id),
            ).fetchone()
            if not row:
                return False
            conn.execute(
                "INSERT INTO roster_claim_history "
                "(alert_id, student_id, addition_id, previous_claimed_by_user_id, "
                "previous_claimed_by_label, new_claimed_by_user_id, new_claimed_by_label, "
                "previous_status, new_status, changed_by_user_id, changed_by_label, "
                "changed_at, change_type, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    alert_id, row[1], row[2],
                    row[3], row[4],
                    None, None,
                    row[5], "released",
                    released_by_user_id, released_by_label,
                    now, "release", note,
                ),
            )
            conn.execute("DELETE FROM roster_claims WHERE id = ?", (claim_id,))
        return True

    # ── Incident-only additions ───────────────────────────────────────────────

    def add_incident_student_sync(
        self,
        alert_id: int,
        *,
        first_name: str,
        last_name: str,
        grade_level: str,
        note: Optional[str],
        added_by_user_id: int,
        added_by_label: str,
    ) -> tuple[RosterAdditionRecord, RosterClaimRecord]:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO roster_additions "
                "(alert_id, first_name, last_name, grade_level, note, "
                "added_by_user_id, added_by_label, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (alert_id, first_name.strip(), last_name.strip(), grade_level, note,
                 added_by_user_id, added_by_label, now),
            )
            addition_id = cur.lastrowid

        addition = RosterAdditionRecord(
            id=addition_id, alert_id=alert_id,
            first_name=first_name.strip(), last_name=last_name.strip(),
            grade_level=grade_level, note=note,
            added_by_user_id=added_by_user_id, added_by_label=added_by_label,
            created_at=now,
        )

        result = self.upsert_claim_sync(
            alert_id,
            addition_id=addition_id,
            status="present_with_me",
            claimant_user_id=added_by_user_id,
            claimant_label=added_by_label,
        )
        return addition, result.claim

    # ── History ───────────────────────────────────────────────────────────────

    def list_claim_history_sync(self, alert_id: int) -> list[RosterClaimHistoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, alert_id, student_id, addition_id, "
                "previous_claimed_by_user_id, previous_claimed_by_label, "
                "new_claimed_by_user_id, new_claimed_by_label, "
                "previous_status, new_status, changed_by_user_id, changed_by_label, "
                "changed_at, change_type, note "
                "FROM roster_claim_history WHERE alert_id = ? ORDER BY changed_at",
                (alert_id,),
            ).fetchall()
        return [self._row_to_history(r) for r in rows]

    # ── Version ───────────────────────────────────────────────────────────────

    def get_roster_version_sync(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(updated_at) FROM students WHERE is_archived = 0"
            ).fetchone()
        return row[0] if row and row[0] else "0"

    # ── Accountability ─────────────────────────────────────────────────────────

    def get_accountability_rollup_sync(self, alert_id: int) -> dict:
        with self._connect() as conn:
            students = conn.execute(
                "SELECT id, grade_level FROM students WHERE is_archived = 0"
            ).fetchall()
            additions = conn.execute(
                "SELECT id, grade_level FROM roster_additions WHERE alert_id = ?",
                (alert_id,),
            ).fetchall()
            claims = conn.execute(
                "SELECT student_id, addition_id, claimed_by_label, status "
                "FROM roster_claims WHERE alert_id = ?",
                (alert_id,),
            ).fetchall()

        claim_by_student: dict[int, dict] = {}
        claim_by_addition: dict[int, dict] = {}
        for c in claims:
            rec = {"label": c[2], "status": c[3]}
            if c[0] is not None:
                claim_by_student[c[0]] = rec
            elif c[1] is not None:
                claim_by_addition[c[1]] = rec

        entries = []
        for s in students:
            sid, grade = s[0], s[1]
            claim = claim_by_student.get(sid)
            entries.append({
                "grade": grade,
                "status": claim["status"] if claim else "unknown",
                "label": claim["label"] if claim else None,
            })
        for a in additions:
            aid, grade = a[0], a[1]
            claim = claim_by_addition.get(aid)
            entries.append({
                "grade": grade,
                "status": claim["status"] if claim else "unknown",
                "label": claim["label"] if claim else None,
            })

        total = len(entries)
        accounted = sum(1 for e in entries if e["status"] in _ACCOUNTED_STATUSES)
        missing = sum(1 for e in entries if e["status"] == "missing")
        unknown = total - accounted - missing
        percentage = round(accounted / total * 100, 1) if total else 0.0

        grade_map: dict[str, dict] = {}
        for e in entries:
            g = e["grade"]
            if g not in grade_map:
                grade_map[g] = {"grade_level": g, "total": 0, "accounted": 0, "missing": 0, "unknown": 0}
            grade_map[g]["total"] += 1
            if e["status"] in _ACCOUNTED_STATUSES:
                grade_map[g]["accounted"] += 1
            elif e["status"] == "missing":
                grade_map[g]["missing"] += 1
            else:
                grade_map[g]["unknown"] += 1

        staff_map: dict[str, dict] = {}
        for e in entries:
            if e["label"] is None:
                continue
            lbl = e["label"]
            if lbl not in staff_map:
                staff_map[lbl] = {"staff_label": lbl, "claimed": 0, "accounted": 0, "missing": 0, "unknown": 0}
            staff_map[lbl]["claimed"] += 1
            if e["status"] in _ACCOUNTED_STATUSES:
                staff_map[lbl]["accounted"] += 1
            elif e["status"] == "missing":
                staff_map[lbl]["missing"] += 1
            else:
                staff_map[lbl]["unknown"] += 1

        return {
            "alert_id": alert_id,
            "total_students": total,
            "accounted": accounted,
            "missing": missing,
            "unknown": unknown,
            "percentage_accounted": percentage,
            "by_grade": list(grade_map.values()),
            "by_staff": list(staff_map.values()),
        }

    def list_missing_students_sync(
        self,
        alert_id: int,
        *,
        grade: Optional[str] = None,
        q: Optional[str] = None,
        include_unknown: bool = True,
    ) -> list[dict]:
        with self._connect() as conn:
            students = conn.execute(
                "SELECT id, first_name, last_name, grade_level, student_ref "
                "FROM students WHERE is_archived = 0"
            ).fetchall()
            claims = conn.execute(
                "SELECT student_id, claimed_by_label, status, last_updated_at "
                "FROM roster_claims WHERE alert_id = ? AND student_id IS NOT NULL",
                (alert_id,),
            ).fetchall()

        claim_map = {
            c[0]: {"claimed_by_label": c[1], "status": c[2], "last_updated_at": c[3]}
            for c in claims
        }

        result = []
        for s in students:
            sid, fn, ln, gl, ref = s
            claim = claim_map.get(sid)
            status = claim["status"] if claim else "unknown"

            if status == "missing":
                pass
            elif status == "unknown" and include_unknown:
                pass
            else:
                continue

            if grade and gl != grade:
                continue
            if q:
                ql = q.lower()
                if (ql not in fn.lower() and ql not in ln.lower()
                        and (not ref or ql not in ref.lower())):
                    continue

            result.append({
                "student_id": sid,
                "first_name": fn,
                "last_name": ln,
                "grade_level": gl,
                "student_ref": ref,
                "status": status,
                "claimed_by_label": claim["claimed_by_label"] if claim else None,
                "last_updated_at": claim["last_updated_at"] if claim else None,
            })
        return result

    def batch_upsert_claims_sync(
        self,
        alert_id: int,
        *,
        student_ids_present: list[int],
        student_ids_missing: list[int],
        claimant_user_id: int,
        claimant_label: str,
        note: Optional[str] = None,
    ) -> dict:
        all_pairs = (
            [(sid, "present_with_me") for sid in student_ids_present]
            + [(sid, "missing") for sid in student_ids_missing]
        )
        if not all_pairs:
            return {"inserted": 0, "updated": 0, "total": 0}

        with self._connect() as conn:
            existing = set(
                r[0]
                for r in conn.execute(
                    "SELECT student_id FROM roster_claims "
                    "WHERE alert_id = ? AND student_id IS NOT NULL",
                    (alert_id,),
                ).fetchall()
            )

        inserted = 0
        updated = 0
        for student_id, status in all_pairs:
            is_new = student_id not in existing
            self.upsert_claim_sync(
                alert_id,
                student_id=student_id,
                status=status,
                claimant_user_id=claimant_user_id,
                claimant_label=claimant_label,
                takeover_confirmed=True,
                note=note,
            )
            if is_new:
                inserted += 1
                existing.add(student_id)
            else:
                updated += 1

        return {"inserted": inserted, "updated": updated, "total": len(all_pairs)}

    # ── Async wrappers ────────────────────────────────────────────────────────

    async def list_students(self, **kw) -> list[StudentRecord]:
        return await anyio.to_thread.run_sync(lambda: self.list_students_sync(**kw))

    async def count_students(self, **kw) -> int:
        return await anyio.to_thread.run_sync(lambda: self.count_students_sync(**kw))

    async def get_student(self, student_id: int) -> Optional[StudentRecord]:
        return await anyio.to_thread.run_sync(lambda: self.get_student_sync(student_id))

    async def create_student(self, **kw) -> StudentRecord:
        return await anyio.to_thread.run_sync(lambda: self.create_student_sync(**kw))

    async def update_student(self, student_id: int, **kw) -> Optional[StudentRecord]:
        return await anyio.to_thread.run_sync(lambda: self.update_student_sync(student_id, **kw))

    async def archive_student(self, student_id: int) -> bool:
        return await anyio.to_thread.run_sync(lambda: self.archive_student_sync(student_id))

    async def parse_csv_preview(self, csv_bytes: bytes) -> ImportPreview:
        return await anyio.to_thread.run_sync(lambda: self.parse_csv_preview_sync(csv_bytes))

    async def commit_import(self, session_token: str, *, conflict_strategy: str = "skip") -> ImportResult:
        return await anyio.to_thread.run_sync(
            lambda: self.commit_import_sync(session_token, conflict_strategy=conflict_strategy)
        )

    async def list_incident_roster(self, alert_id: int) -> dict:
        return await anyio.to_thread.run_sync(lambda: self.list_incident_roster_sync(alert_id))

    async def upsert_claim(self, alert_id: int, **kw) -> ClaimResult:
        return await anyio.to_thread.run_sync(lambda: self.upsert_claim_sync(alert_id, **kw))

    async def release_claim(self, alert_id: int, claim_id: int, **kw) -> bool:
        return await anyio.to_thread.run_sync(
            lambda: self.release_claim_sync(alert_id, claim_id, **kw)
        )

    async def add_incident_student(self, alert_id: int, **kw):
        return await anyio.to_thread.run_sync(
            lambda: self.add_incident_student_sync(alert_id, **kw)
        )

    async def list_claim_history(self, alert_id: int) -> list[RosterClaimHistoryRecord]:
        return await anyio.to_thread.run_sync(lambda: self.list_claim_history_sync(alert_id))

    async def get_roster_version(self) -> str:
        return await anyio.to_thread.run_sync(self.get_roster_version_sync)

    async def get_accountability_rollup(self, alert_id: int) -> dict:
        return await anyio.to_thread.run_sync(lambda: self.get_accountability_rollup_sync(alert_id))

    async def list_missing_students(self, alert_id: int, **kw) -> list[dict]:
        return await anyio.to_thread.run_sync(lambda: self.list_missing_students_sync(alert_id, **kw))

    async def batch_upsert_claims(self, alert_id: int, **kw) -> dict:
        return await anyio.to_thread.run_sync(lambda: self.batch_upsert_claims_sync(alert_id, **kw))

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_student(row) -> StudentRecord:
        return StudentRecord(
            id=row[0], created_at=row[1], updated_at=row[2],
            first_name=row[3], last_name=row[4], grade_level=row[5],
            student_ref=row[6], is_archived=bool(row[7]), archived_at=row[8],
        )

    @staticmethod
    def _row_to_claim(row) -> RosterClaimRecord:
        return RosterClaimRecord(
            id=row[0], alert_id=row[1], student_id=row[2], addition_id=row[3],
            claimed_by_user_id=row[4], claimed_by_label=row[5], status=row[6],
            claimed_at=row[7], last_updated_at=row[8], last_updated_by_user_id=row[9],
        )

    @staticmethod
    def _row_to_history(row) -> RosterClaimHistoryRecord:
        return RosterClaimHistoryRecord(
            id=row[0], alert_id=row[1], student_id=row[2], addition_id=row[3],
            previous_claimed_by_user_id=row[4], previous_claimed_by_label=row[5],
            new_claimed_by_user_id=row[6], new_claimed_by_label=row[7],
            previous_status=row[8], new_status=row[9],
            changed_by_user_id=row[10], changed_by_label=row[11],
            changed_at=row[12], change_type=row[13], note=row[14],
        )

    @staticmethod
    def _claim_to_dict(claim: Optional[RosterClaimRecord]) -> Optional[dict]:
        if claim is None:
            return None
        return {
            "id": claim.id,
            "claimed_by_user_id": claim.claimed_by_user_id,
            "claimed_by_label": claim.claimed_by_label,
            "status": claim.status,
            "claimed_at": claim.claimed_at,
            "last_updated_at": claim.last_updated_at,
        }
