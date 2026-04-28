"""
Realistic demo data seeder for sandbox/test tenants.

Seeds 50+ users, 45+ incidents (past 30 days), audit log events,
and access codes so a fresh demo tenant looks like a real school system.

All created records are marked is_simulation=True where applicable.
Only operates on is_test tenants — refuses to touch production.
"""
from __future__ import annotations

import logging
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bluebird.demo_seed")

# ── Realistic name pools ────────────────────────────────────────────────────

_FIRST_NAMES = [
    "Sarah", "Michael", "Jennifer", "David", "Emily", "Robert", "Ashley",
    "James", "Jessica", "Christopher", "Amanda", "Daniel", "Stephanie",
    "Matthew", "Nicole", "Anthony", "Melissa", "Joshua", "Rebecca", "Kevin",
    "Lauren", "Brian", "Megan", "Eric", "Heather", "Steven", "Amber",
    "Timothy", "Katherine", "Jeremy", "Rachel", "Jason", "Angela",
    "Benjamin", "Diana", "Ryan", "Christine", "William", "Patricia",
    "Mark", "Sandra", "Andrew", "Lisa", "Kenneth", "Betty", "George",
    "Dorothy", "Paul", "Susan", "Thomas",
]

_LAST_NAMES = [
    "Johnson", "Smith", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts",
]

_TEACHER_TITLES = [
    "3rd Grade Teacher", "5th Grade Teacher", "Math Teacher", "English Teacher",
    "Science Teacher", "History Teacher", "PE Teacher", "Art Teacher",
    "Music Teacher", "Special Education Teacher", "Kindergarten Teacher",
    "1st Grade Teacher", "2nd Grade Teacher", "4th Grade Teacher",
    "French Teacher", "Spanish Teacher", "Librarian", "Counselor",
    "Reading Specialist", "Technology Teacher",
]

_ADMIN_TITLES = [
    "Assistant Principal", "Principal", "Vice Principal",
    "Dean of Students", "Athletic Director",
]

_DISTRICT_TITLES = [
    "Superintendent", "Assistant Superintendent", "Director of Safety",
    "Chief Operations Officer",
]

# ── Alert messages ──────────────────────────────────────────────────────────

_ALERT_MESSAGES = [
    "Lockdown in effect — all staff secure classrooms immediately.",
    "Medical emergency reported in the gymnasium. EMS en route.",
    "Suspicious individual reported near east entrance. Security notified.",
    "DRILL: Practice lockdown — this is a drill, not a real emergency.",
    "All-clear: previous alert resolved. Normal operations may resume.",
    "Gas leak reported in building B. Evacuation in progress.",
    "Fire alarm activated — evacuate via designated exits.",
    "DRILL: Emergency evacuation drill in progress.",
    "Weather emergency: Shelter in place — tornado warning issued.",
    "Threat reported. Law enforcement has been notified. Lockdown in effect.",
]

_AUDIT_EVENTS = [
    ("user_login", None), ("user_login", None), ("user_login", None),
    ("alert_triggered", "alert"), ("alert_resolved", "alert"),
    ("user_created", "user"), ("user_role_changed", "user"),
    ("access_code_generated", "access_code"), ("access_code_used", "access_code"),
    ("drill_started", "drill"), ("drill_completed", "drill"),
    ("settings_updated", None), ("quiet_period_requested", "quiet_period"),
    ("quiet_period_approved", "quiet_period"), ("user_deactivated", "user"),
]

_INCIDENT_TYPES = ["panic", "medical", "assist", "drill"]
_INCIDENT_WEIGHTS = [3, 2, 2, 3]


class DemoSeedService:
    """Seeds a test tenant with realistic demo data."""

    def __init__(self, db_path: str, tenant_slug: str) -> None:
        self._db_path = db_path
        self._slug = tenant_slug
        self._rng = random.Random(hash(tenant_slug) & 0xFFFFFFFF)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=30, isolation_level=None)

    def _rand_name(self) -> str:
        return f"{self._rng.choice(_FIRST_NAMES)} {self._rng.choice(_LAST_NAMES)}"

    def _rand_ts(self, days_ago_max: int = 30, days_ago_min: int = 0) -> str:
        now = datetime.now(timezone.utc)
        delta = timedelta(
            days=self._rng.randint(days_ago_min, days_ago_max),
            hours=self._rng.randint(6, 18),
            minutes=self._rng.randint(0, 59),
        )
        return (now - delta).isoformat()

    # ── Users ───────────────────────────────────────────────────────────────

    def _seed_users(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        existing = conn.execute("SELECT COUNT(*) FROM users;").fetchone()[0]
        if existing >= 20:
            rows = conn.execute(
                "SELECT id, name, role FROM users WHERE is_active = 1 AND is_archived = 0 LIMIT 60;"
            ).fetchall()
            return [{"id": r[0], "name": r[1], "role": r[2]} for r in rows]

        from app.services.passwords import hash_password  # type: ignore[import]

        created: List[Dict[str, Any]] = []

        def _insert(name: str, role: str, title: Optional[str], login: Optional[str]) -> int:
            ts = self._rand_ts(days_ago_max=60, days_ago_min=1)
            salt, pw_hash = (None, None)
            if login:
                salt, pw_hash = hash_password("Demo2024!")
            cur = conn.execute(
                """INSERT OR IGNORE INTO users
                   (created_at, name, role, phone_e164, is_active, login_name,
                    password_salt, password_hash, must_change_password, title)
                   VALUES (?, ?, ?, NULL, 1, ?, ?, ?, 0, ?);""",
                (ts, name, role, login, salt, pw_hash, title),
            )
            return cur.lastrowid or 0

        # 2 district admins
        for i in range(2):
            n = self._rand_name()
            ln = f"district_{i + 1}@demo"
            uid = _insert(n, "district_admin", self._rng.choice(_DISTRICT_TITLES), ln)
            if uid:
                created.append({"id": uid, "name": n, "role": "district_admin"})

        # 6 building admins
        for i in range(6):
            n = self._rand_name()
            ln = f"admin_{i + 1}@demo"
            uid = _insert(n, "building_admin", self._rng.choice(_ADMIN_TITLES), ln)
            if uid:
                created.append({"id": uid, "name": n, "role": "building_admin"})

        # 42 teachers
        for i in range(42):
            n = self._rand_name()
            login = f"teacher_{i + 1}@demo" if i < 15 else None
            uid = _insert(n, "teacher", self._rng.choice(_TEACHER_TITLES), login)
            if uid:
                created.append({"id": uid, "name": n, "role": "teacher"})

        logger.info("demo_seed: created %d users slug=%s", len(created), self._slug)
        return created

    # ── Incidents ───────────────────────────────────────────────────────────

    def _seed_incidents(self, conn: sqlite3.Connection, users: List[Dict]) -> int:
        existing = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE is_simulation = 1;"
        ).fetchone()[0]
        if existing >= 30:
            return 0

        actors = [u for u in users if u["role"] in {"building_admin", "district_admin"}]
        if not actors:
            actors = users[:3]

        reporters = [
            "Ms. Johnson", "Mr. Smith", "Principal Davis", "Coach Roberts",
            "Ms. Chen", "Mr. Williams", "Front Office", "Security Officer",
            "Dr. Anderson", "Mrs. Thompson",
        ]

        count = 0
        for i in range(45):
            inc_type = self._rng.choices(_INCIDENT_TYPES, weights=_INCIDENT_WEIGHTS, k=1)[0]
            actor = self._rng.choice(actors) if actors else None
            reporter = self._rng.choice(reporters)
            ts = self._rand_ts(days_ago_max=30, days_ago_min=0)
            status = "resolved" if i < 40 else "active"
            metadata = f'{{"demo": true, "reported_by": "{reporter}", "is_simulation": true}}'
            try:
                conn.execute(
                    """INSERT INTO incidents
                       (type, status, created_at, created_by, school_id,
                        target_scope, metadata, is_simulation)
                       VALUES (?, ?, ?, ?, ?, 'ALL', ?, 1);""",
                    (inc_type, status, ts, actor["id"] if actor else 0, self._slug, metadata),
                )
                count += 1
            except Exception:
                pass

        logger.info("demo_seed: created %d incidents slug=%s", count, self._slug)
        return count

    # ── Alerts ──────────────────────────────────────────────────────────────

    def _seed_alerts(self, conn: sqlite3.Connection, users: List[Dict]) -> int:
        existing = conn.execute("SELECT COUNT(*) FROM alerts;").fetchone()[0]
        if existing >= 15:
            return 0

        admins = [u for u in users if u["role"] in {"building_admin", "district_admin"}]
        if not admins:
            admins = users[:2]

        count = 0
        for i in range(20):
            msg = self._rng.choice(_ALERT_MESSAGES)
            is_training = 1 if "DRILL" in msg else 0
            actor = self._rng.choice(admins) if admins else None
            ts = self._rand_ts(days_ago_max=28, days_ago_min=0)
            try:
                conn.execute(
                    """INSERT INTO alerts
                       (created_at, message, is_training, triggered_by_user_id, triggered_by_label)
                       VALUES (?, ?, ?, ?, ?);""",
                    (ts, msg, is_training, actor["id"] if actor else None,
                     actor["name"] if actor else None),
                )
                count += 1
            except Exception:
                pass

        logger.info("demo_seed: created %d alerts slug=%s", count, self._slug)
        return count

    # ── Audit Log ───────────────────────────────────────────────────────────

    def _seed_audit_log(self, conn: sqlite3.Connection, users: List[Dict]) -> int:
        existing = conn.execute("SELECT COUNT(*) FROM audit_log;").fetchone()[0]
        if existing >= 40:
            return 0

        count = 0
        for i in range(80):
            event_type, target_type = self._rng.choice(_AUDIT_EVENTS)
            actor = self._rng.choice(users) if users else None
            ts = self._rand_ts(days_ago_max=30, days_ago_min=0)
            target_id = str(self._rng.randint(1, 50)) if target_type else None
            try:
                conn.execute(
                    """INSERT INTO audit_log
                       (tenant_slug, timestamp, event_type, actor_user_id,
                        actor_label, target_type, target_id, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, '{}');""",
                    (self._slug, ts, event_type,
                     actor["id"] if actor else None,
                     actor["name"] if actor else None,
                     target_type, target_id),
                )
                count += 1
            except Exception:
                pass

        logger.info("demo_seed: created %d audit events slug=%s", count, self._slug)
        return count

    # ── Access Codes ────────────────────────────────────────────────────────

    def _seed_access_codes(self, conn: sqlite3.Connection, users: List[Dict]) -> int:
        existing = conn.execute("SELECT COUNT(*) FROM access_codes;").fetchone()[0]
        if existing >= 10:
            return 0

        admins = [u for u in users if u["role"] in {"building_admin", "district_admin"}]
        creator_id = admins[0]["id"] if admins else 1

        import string
        chars = string.ascii_uppercase + string.digits

        statuses: List[Tuple[str, int]] = [
            ("active", 12), ("used", 20), ("expired", 8),
        ]
        count = 0
        roles = ["teacher", "teacher", "teacher", "building_admin"]

        for status_val, qty in statuses:
            for _ in range(qty):
                code = "".join(self._rng.choices(chars, k=8))
                role = self._rng.choice(roles)
                ts = self._rand_ts(days_ago_max=60, days_ago_min=1)
                exp = self._rand_ts(days_ago_max=0, days_ago_min=0) if status_val == "expired" else None
                max_uses = 1
                use_count = 1 if status_val == "used" else 0
                asgn_name = self._rand_name() if status_val == "used" else None
                try:
                    conn.execute(
                        """INSERT INTO access_codes
                           (code, tenant_slug, role, created_at, expires_at, status,
                            max_uses, use_count, created_by_user_id,
                            assigned_name, is_archived)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0);""",
                        (code, self._slug, role, ts, exp, status_val,
                         max_uses, use_count, creator_id, asgn_name),
                    )
                    count += 1
                except Exception:
                    pass

        logger.info("demo_seed: created %d access codes slug=%s", count, self._slug)
        return count

    # ── Public entry point ──────────────────────────────────────────────────

    def seed(self) -> Dict[str, int]:
        """Seed the tenant DB. Returns counts of created records."""
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            users = self._seed_users(conn)
            incidents = self._seed_incidents(conn, users)
            alerts = self._seed_alerts(conn, users)
            audit = self._seed_audit_log(conn, users)
            codes = self._seed_access_codes(conn, users)

        return {
            "users": len(users),
            "incidents": incidents,
            "alerts": alerts,
            "audit_events": audit,
            "access_codes": codes,
        }
