from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import anyio


@dataclass(frozen=True)
class HeartbeatRecord:
    id: int
    timestamp: str
    status: str
    response_time_ms: float
    db_ok: bool
    ws_connections: int
    apns_configured: bool
    fcm_configured: bool
    error_note: Optional[str]


@dataclass(frozen=True)
class UptimeStats:
    window_hours: int
    uptime_pct: float
    total_checks: int
    ok_checks: int
    downtime_events: int
    last_outage_at: Optional[str]


@dataclass(frozen=True)
class HealthStatus:
    overall: str  # "ok" | "degraded" | "error" | "unknown"
    last_heartbeat_at: Optional[str]
    seconds_since_heartbeat: Optional[float]
    is_stale: bool
    db_ok: bool
    ws_connections: int
    apns_configured: bool
    fcm_configured: bool
    response_time_ms: float
    error_note: Optional[str]
    uptime_24h: Optional[float]
    uptime_7d: Optional[float]


class HealthMonitor:
    STALE_THRESHOLD_SECONDS = 300  # 5 min — alert if heartbeat stops

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=30, isolation_level=None)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_health_events (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp        TEXT    NOT NULL,
                    status           TEXT    NOT NULL,
                    response_time_ms REAL    NOT NULL DEFAULT 0,
                    db_ok            INTEGER NOT NULL DEFAULT 1,
                    ws_connections   INTEGER NOT NULL DEFAULT 0,
                    apns_configured  INTEGER NOT NULL DEFAULT 0,
                    fcm_configured   INTEGER NOT NULL DEFAULT 0,
                    error_note       TEXT    NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_health_ts ON platform_health_events(timestamp);"
            )

    # ── Write ──────────────────────────────────────────────────────────────────

    def _insert_sync(
        self,
        timestamp: str,
        status: str,
        response_time_ms: float,
        db_ok: bool,
        ws_connections: int,
        apns_configured: bool,
        fcm_configured: bool,
        error_note: Optional[str],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO platform_health_events
                    (timestamp, status, response_time_ms, db_ok, ws_connections,
                     apns_configured, fcm_configured, error_note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    timestamp, status, response_time_ms,
                    1 if db_ok else 0, ws_connections,
                    1 if apns_configured else 0,
                    1 if fcm_configured else 0,
                    error_note,
                ),
            )
            # Keep platform DB lean — retain last 1 000 heartbeats (~17h at 60s interval)
            conn.execute(
                """DELETE FROM platform_health_events WHERE id NOT IN (
                    SELECT id FROM platform_health_events ORDER BY id DESC LIMIT 1000
                );"""
            )

    async def record_heartbeat(
        self,
        *,
        status: str,
        response_time_ms: float,
        db_ok: bool,
        ws_connections: int,
        apns_configured: bool,
        fcm_configured: bool,
        error_note: Optional[str] = None,
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            await anyio.to_thread.run_sync(
                self._insert_sync,
                timestamp, status, response_time_ms,
                db_ok, ws_connections, apns_configured, fcm_configured, error_note,
            )
        except Exception:
            pass  # never crash the background task

    # ── Read ───────────────────────────────────────────────────────────────────

    def _list_recent_sync(self, limit: int) -> List[HeartbeatRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, status, response_time_ms, db_ok,
                       ws_connections, apns_configured, fcm_configured, error_note
                FROM platform_health_events
                ORDER BY id DESC LIMIT ?;
                """,
                (limit,),
            ).fetchall()
        return [
            HeartbeatRecord(
                id=int(r[0]),
                timestamp=str(r[1]),
                status=str(r[2]),
                response_time_ms=float(r[3]),
                db_ok=bool(int(r[4])),
                ws_connections=int(r[5]),
                apns_configured=bool(int(r[6])),
                fcm_configured=bool(int(r[7])),
                error_note=str(r[8]) if r[8] else None,
            )
            for r in rows
        ]

    async def recent_heartbeats(self, limit: int = 20) -> List[HeartbeatRecord]:
        return await anyio.to_thread.run_sync(self._list_recent_sync, int(limit))

    def _uptime_sync(self, since_iso: str) -> Tuple[int, int, int, Optional[str]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*),
                    SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END),
                    MIN(CASE WHEN status = 'error' THEN timestamp ELSE NULL END)
                FROM platform_health_events
                WHERE timestamp >= ?;
                """,
                (since_iso,),
            ).fetchone()
        if not row or not row[0]:
            return 0, 0, 0, None
        return (
            int(row[0]),
            int(row[1] or 0),
            int(row[2] or 0),
            str(row[3]) if row[3] else None,
        )

    async def uptime_stats(self, window_hours: int = 24) -> UptimeStats:
        since = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
        total, ok, errors, last_outage = await anyio.to_thread.run_sync(self._uptime_sync, since)
        pct = round((ok / total * 100) if total > 0 else 100.0, 1)
        return UptimeStats(
            window_hours=window_hours,
            uptime_pct=pct,
            total_checks=total,
            ok_checks=ok,
            downtime_events=errors,
            last_outage_at=last_outage,
        )

    async def current_status(self) -> HealthStatus:
        recent = await self.recent_heartbeats(limit=1)
        stats_24h = await self.uptime_stats(24)
        stats_7d = await self.uptime_stats(168)
        if not recent:
            return HealthStatus(
                overall="unknown",
                last_heartbeat_at=None,
                seconds_since_heartbeat=None,
                is_stale=True,
                db_ok=False,
                ws_connections=0,
                apns_configured=False,
                fcm_configured=False,
                response_time_ms=0.0,
                error_note="No heartbeat recorded yet — monitor starting up",
                uptime_24h=None,
                uptime_7d=None,
            )
        latest = recent[0]
        try:
            last_dt = datetime.fromisoformat(latest.timestamp)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            seconds_ago: Optional[float] = (datetime.now(timezone.utc) - last_dt).total_seconds()
        except (ValueError, TypeError):
            seconds_ago = None
        is_stale = seconds_ago is None or seconds_ago > self.STALE_THRESHOLD_SECONDS
        return HealthStatus(
            overall="error" if is_stale else latest.status,
            last_heartbeat_at=latest.timestamp,
            seconds_since_heartbeat=seconds_ago,
            is_stale=is_stale,
            db_ok=latest.db_ok,
            ws_connections=latest.ws_connections,
            apns_configured=latest.apns_configured,
            fcm_configured=latest.fcm_configured,
            response_time_ms=latest.response_time_ms,
            error_note="Heartbeat stale — background monitor may be down" if is_stale else latest.error_note,
            uptime_24h=stats_24h.uptime_pct if stats_24h.total_checks > 0 else None,
            uptime_7d=stats_7d.uptime_pct if stats_7d.total_checks > 0 else None,
        )

    # ── Health checks (read-only, never modifies alert system) ─────────────────

    @staticmethod
    async def run_checks(app_state: object) -> Dict[str, Any]:
        """
        Read-only health probes against app state.
        Does NOT write to any alert table, trigger any notification,
        or affect WebSocket delivery in any way.
        """
        result: Dict[str, Any] = {
            "db_ok": False,
            "ws_connections": 0,
            "apns_configured": False,
            "fcm_configured": False,
            "response_time_ms": 0.0,
            "status": "error",
            "error_note": None,
        }
        errors: List[str] = []

        # DB ping — measures platform DB round-trip latency
        t0 = time.monotonic()
        try:
            settings = getattr(app_state, "settings", None)
            if settings:
                db_path = str(settings.PLATFORM_DB_PATH)

                def _ping(path: str) -> None:
                    c = sqlite3.connect(path, timeout=5)
                    c.execute("SELECT 1;")
                    c.close()

                await anyio.to_thread.run_sync(_ping, db_path)
                result["db_ok"] = True
        except Exception as exc:
            errors.append(f"DB: {exc}")
        result["response_time_ms"] = round((time.monotonic() - t0) * 1000, 1)

        # WS connection count — read-only property access
        try:
            hub = getattr(app_state, "alert_hub", None)
            if hub is not None:
                slugs = hub.connected_slugs()
                result["ws_connections"] = sum(hub.connection_count(s) for s in slugs)
        except Exception:
            pass

        # Push provider configuration — reads settings flags only
        try:
            settings = getattr(app_state, "settings", None)
            if settings:
                result["apns_configured"] = bool(settings.apns_is_configured())
                result["fcm_configured"] = bool(settings.fcm_is_configured())
        except Exception:
            pass

        if not result["db_ok"]:
            result["status"] = "error"
            result["error_note"] = "; ".join(errors) or "Platform DB unreachable"
        elif errors:
            result["status"] = "degraded"
            result["error_note"] = "; ".join(errors)
        else:
            result["status"] = "ok"

        return result
