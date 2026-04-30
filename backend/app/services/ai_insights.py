"""
AI Insights service — Ollama/llama3 local AI analysis for super admin dashboard.

Architecture:
  1. Rule-based pre-processing (category assignment, health score, trend detection)
  2. Metrics history recorded on every run (drives trend detection)
  3. LLM receives structured context (category + trend + health) → better summaries
  4. Confidence filter drops weak insights before storage

Tenant isolation: each call is strictly scoped to one tenant slug. No cross-tenant
data is ever aggregated or sent to the model.

Global toggle: AI_INSIGHTS_GLOBAL_ENABLED env var (default false).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import anyio

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("AI_INSIGHTS_MODEL", "llama3")
OLLAMA_TIMEOUT = float(os.getenv("AI_INSIGHTS_TIMEOUT_S", "10"))
AI_INSIGHTS_GLOBAL_ENABLED = os.getenv("AI_INSIGHTS_GLOBAL_ENABLED", "false").lower() in ("1", "true", "yes")

CONFIDENCE_HIGH = 80
CONFIDENCE_NEEDS_REVIEW = 60

TREND_IMPROVING = "improving"
TREND_STABLE = "stable"
TREND_WORSENING = "worsening"

CATEGORY_SECURITY = "security"
CATEGORY_PERFORMANCE = "performance"
CATEGORY_READINESS = "readiness"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AiInsightRecord:
    id: int
    tenant_slug: str
    timestamp: str
    severity: str
    summary: str
    recommendations: list
    category: str
    trend: str
    health_score: int
    llm_confidence: int
    final_confidence: int
    rule_score: int
    data_quality_score: int
    debug_prompt: Optional[str]
    debug_response: Optional[str]
    debug_latency_ms: Optional[int]
    debug_error: Optional[str]

    @property
    def confidence_label(self) -> str:
        if self.final_confidence >= CONFIDENCE_HIGH:
            return "High"
        if self.final_confidence >= CONFIDENCE_NEEDS_REVIEW:
            return "Needs Review"
        return "Low"

    @property
    def needs_review(self) -> bool:
        return self.final_confidence < CONFIDENCE_HIGH

    @property
    def trend_arrow(self) -> str:
        return {"improving": "↑", "worsening": "↓", "stable": "→"}.get(self.trend, "→")


@dataclass(frozen=True)
class MetricsHistoryRecord:
    id: int
    tenant_slug: str
    timestamp: str
    ack_rate: float
    avg_response_time: float
    offline_pct: float
    push_failure_rate: float
    active_users: int
    device_count: int
    alert_count: int
    health_score: int


@dataclass(frozen=True)
class WeeklyReportRecord:
    id: int
    tenant_slug: str
    week_start: str
    generated_at: str
    summary: str
    recommendations: list
    health_score: int
    trend: str


# ---------------------------------------------------------------------------
# Rule-based scoring
# ---------------------------------------------------------------------------

def compute_health_score(stats: dict) -> int:
    """
    System health score (0-100). Weighted composite:
      35% ack rate, 25% device online %, 20% push success, 10% device coverage, 10% drill activity
    """
    ack_rate = float(stats.get("ack_rate_pct", 100))
    offline_pct = float(stats.get("offline_pct", 0))
    push_failure_rate = float(stats.get("push_failure_rate", 0))
    active_users = int(stats.get("active_users", 0))
    device_count = int(stats.get("device_count", 0))
    drill_count = int(stats.get("drill_count", 0))

    ack_component = max(0.0, min(100.0, ack_rate))
    device_component = max(0.0, 100.0 - offline_pct * 2)
    push_component = max(0.0, 100.0 - push_failure_rate * 3)
    coverage_component = min(100.0, (device_count / max(1, active_users)) * 80) if active_users > 0 else 0.0
    drill_component = min(100.0, drill_count * 25.0)

    score = (
        0.35 * ack_component
        + 0.25 * device_component
        + 0.20 * push_component
        + 0.10 * coverage_component
        + 0.10 * drill_component
    )
    return int(round(min(100, max(0, score))))


def compute_rule_score(stats: dict) -> int:
    """Signal strength score (0-100). Higher = more notable activity for AI to analyze."""
    score = 40
    ack_rate = float(stats.get("ack_rate_pct", 100))
    if ack_rate < 50:
        score += 30
    elif ack_rate < 75:
        score += 15
    elif ack_rate < 90:
        score += 5

    alert_count = int(stats.get("alert_count", 0))
    if alert_count >= 5:
        score += 20
    elif alert_count >= 2:
        score += 12
    elif alert_count >= 1:
        score += 6

    offline_pct = float(stats.get("offline_pct", 0))
    if offline_pct > 30:
        score += 20
    elif offline_pct > 15:
        score += 10

    push_failure_rate = float(stats.get("push_failure_rate", 0))
    if push_failure_rate > 20:
        score += 15
    elif push_failure_rate > 10:
        score += 8

    if int(stats.get("drill_count", 0)) >= 2:
        score += 5

    return min(100, max(0, score))


def compute_data_quality(stats: dict) -> int:
    """Data quality score (0-100). Penalizes small samples and low activity."""
    score = 80
    active_users = int(stats.get("active_users", 0))
    if active_users < 2:
        score -= 50
    elif active_users < 5:
        score -= 30
    elif active_users < 10:
        score -= 15

    device_count = int(stats.get("device_count", 0))
    if device_count == 0:
        score -= 30
    elif device_count < 3:
        score -= 15

    if int(stats.get("alert_count", 0)) == 0 and int(stats.get("drill_count", 0)) == 0:
        score -= 20

    return min(100, max(0, score))


def compute_final_confidence(rule_score: int, data_quality: int, llm_confidence: int) -> int:
    raw = 0.4 * rule_score + 0.3 * data_quality + 0.3 * llm_confidence
    return int(round(min(100, max(0, raw))))


def detect_trend(history: list[MetricsHistoryRecord]) -> str:
    """
    Compare average health_score of the newest half vs the older half.
    Requires at least 4 data points; returns "stable" otherwise.
    """
    if len(history) < 4:
        return TREND_STABLE
    mid = len(history) // 2
    # history is ordered newest-first from the DB query
    newer = history[:mid]
    older = history[mid:]
    newer_avg = sum(r.health_score for r in newer) / len(newer)
    older_avg = sum(r.health_score for r in older) / len(older)
    delta = newer_avg - older_avg
    if delta > 5:
        return TREND_IMPROVING
    if delta < -5:
        return TREND_WORSENING
    return TREND_STABLE


def assign_category(stats: dict, trend: str) -> str:
    """
    Assign the primary insight category based on rule-based thresholds.
    Evaluated BEFORE the LLM call — no model dependency.
    """
    ack_rate = float(stats.get("ack_rate_pct", 100))
    push_failure_rate = float(stats.get("push_failure_rate", 0))
    alert_count = int(stats.get("alert_count", 0))
    offline_pct = float(stats.get("offline_pct", 0))

    # Security: response quality and alert activity issues
    if ack_rate < 60 or push_failure_rate > 20 or alert_count >= 5:
        return CATEGORY_SECURITY
    # Performance: infrastructure and device availability
    if offline_pct > 25 or push_failure_rate > 10:
        return CATEGORY_PERFORMANCE
    # Readiness: general preparedness (default)
    return CATEGORY_READINESS


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class AiInsightsStore:
    """
    SQLite store for AI insights, metrics history, and weekly reports.
    Stored in the platform DB — one store serves all tenants, queries are always
    tenant-slug-scoped.
    """

    _SELECT_INSIGHT = (
        "SELECT id, tenant_slug, timestamp, severity, summary, recommendations, "
        "category, trend, health_score, "
        "llm_confidence, final_confidence, rule_score, data_quality_score, "
        "debug_prompt, debug_response, debug_latency_ms, debug_error "
        "FROM ai_insights"
    )

    _SELECT_METRICS = (
        "SELECT id, tenant_slug, timestamp, ack_rate, avg_response_time, "
        "offline_pct, push_failure_rate, active_users, device_count, alert_count, health_score "
        "FROM tenant_metrics_history"
    )

    _SELECT_REPORT = (
        "SELECT id, tenant_slug, week_start, generated_at, summary, recommendations, "
        "health_score, trend "
        "FROM ai_weekly_reports"
    )

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=30, isolation_level=None)

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_insights (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_slug        TEXT    NOT NULL,
                    timestamp          TEXT    NOT NULL,
                    severity           TEXT    NOT NULL DEFAULT 'info',
                    summary            TEXT    NOT NULL DEFAULT '',
                    recommendations    TEXT    NOT NULL DEFAULT '[]',
                    category           TEXT    NOT NULL DEFAULT 'readiness',
                    trend              TEXT    NOT NULL DEFAULT 'stable',
                    health_score       INTEGER NOT NULL DEFAULT 50,
                    llm_confidence     INTEGER NOT NULL DEFAULT 50,
                    final_confidence   INTEGER NOT NULL DEFAULT 50,
                    rule_score         INTEGER NOT NULL DEFAULT 50,
                    data_quality_score INTEGER NOT NULL DEFAULT 50,
                    debug_prompt       TEXT    NULL,
                    debug_response     TEXT    NULL,
                    debug_latency_ms   INTEGER NULL,
                    debug_error        TEXT    NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tenant_metrics_history (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_slug       TEXT    NOT NULL,
                    timestamp         TEXT    NOT NULL,
                    ack_rate          REAL    NOT NULL DEFAULT 100.0,
                    avg_response_time REAL    NOT NULL DEFAULT 0.0,
                    offline_pct       REAL    NOT NULL DEFAULT 0.0,
                    push_failure_rate REAL    NOT NULL DEFAULT 0.0,
                    active_users      INTEGER NOT NULL DEFAULT 0,
                    device_count      INTEGER NOT NULL DEFAULT 0,
                    alert_count       INTEGER NOT NULL DEFAULT 0,
                    health_score      INTEGER NOT NULL DEFAULT 50
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_weekly_reports (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_slug     TEXT    NOT NULL,
                    week_start      TEXT    NOT NULL,
                    generated_at    TEXT    NOT NULL,
                    summary         TEXT    NOT NULL DEFAULT '',
                    recommendations TEXT    NOT NULL DEFAULT '[]',
                    health_score    INTEGER NOT NULL DEFAULT 50,
                    trend           TEXT    NOT NULL DEFAULT 'stable'
                );
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_insights_tenant "
                "ON ai_insights(tenant_slug, timestamp DESC);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_metrics_history_tenant "
                "ON tenant_metrics_history(tenant_slug, timestamp DESC);"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_weekly_reports_week "
                "ON ai_weekly_reports(tenant_slug, week_start);"
            )
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(ai_insights);").fetchall()}
        for col, defn in [
            ("debug_prompt", "TEXT NULL"),
            ("debug_response", "TEXT NULL"),
            ("debug_latency_ms", "INTEGER NULL"),
            ("debug_error", "TEXT NULL"),
            ("llm_confidence", "INTEGER NOT NULL DEFAULT 50"),
            ("final_confidence", "INTEGER NOT NULL DEFAULT 50"),
            ("rule_score", "INTEGER NOT NULL DEFAULT 50"),
            ("data_quality_score", "INTEGER NOT NULL DEFAULT 50"),
            ("category", "TEXT NOT NULL DEFAULT 'readiness'"),
            ("trend", "TEXT NOT NULL DEFAULT 'stable'"),
            ("health_score", "INTEGER NOT NULL DEFAULT 50"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE ai_insights ADD COLUMN {col} {defn};")

    # ── Insight record helpers ──────────────────────────────────────────────

    def _row_to_insight(self, row: tuple) -> AiInsightRecord:
        try:
            recs = json.loads(row[5]) if row[5] else []
        except (json.JSONDecodeError, TypeError):
            recs = []
        return AiInsightRecord(
            id=int(row[0]),
            tenant_slug=str(row[1]),
            timestamp=str(row[2]),
            severity=str(row[3]),
            summary=str(row[4]),
            recommendations=recs,
            category=str(row[6]) if row[6] else "readiness",
            trend=str(row[7]) if row[7] else "stable",
            health_score=int(row[8]) if row[8] is not None else 50,
            llm_confidence=int(row[9]) if row[9] is not None else 50,
            final_confidence=int(row[10]) if row[10] is not None else 50,
            rule_score=int(row[11]) if row[11] is not None else 50,
            data_quality_score=int(row[12]) if row[12] is not None else 50,
            debug_prompt=str(row[13]) if len(row) > 13 and row[13] else None,
            debug_response=str(row[14]) if len(row) > 14 and row[14] else None,
            debug_latency_ms=int(row[15]) if len(row) > 15 and row[15] is not None else None,
            debug_error=str(row[16]) if len(row) > 16 and row[16] else None,
        )

    def _save_insight_sync(
        self,
        tenant_slug: str,
        severity: str,
        summary: str,
        recommendations: list,
        *,
        category: str = "readiness",
        trend: str = "stable",
        health_score: int = 50,
        llm_confidence: int = 50,
        final_confidence: int = 50,
        rule_score: int = 50,
        data_quality_score: int = 50,
        debug_prompt: Optional[str] = None,
        debug_response: Optional[str] = None,
        debug_latency_ms: Optional[int] = None,
        debug_error: Optional[str] = None,
    ) -> AiInsightRecord:
        ts = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO ai_insights
                    (tenant_slug, timestamp, severity, summary, recommendations,
                     category, trend, health_score,
                     llm_confidence, final_confidence, rule_score, data_quality_score,
                     debug_prompt, debug_response, debug_latency_ms, debug_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    tenant_slug, ts, severity, summary, json.dumps(recommendations),
                    category, trend, int(health_score),
                    int(llm_confidence), int(final_confidence),
                    int(rule_score), int(data_quality_score),
                    debug_prompt, debug_response, debug_latency_ms, debug_error,
                ),
            )
            row = conn.execute(
                self._SELECT_INSIGHT + " WHERE id = ?;", (int(cur.lastrowid),)
            ).fetchone()
        assert row is not None
        return self._row_to_insight(row)

    async def save_insight(self, tenant_slug: str, severity: str, summary: str,
                           recommendations: list, **kwargs: Any) -> AiInsightRecord:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._save_insight_sync,
                              tenant_slug, severity, summary, recommendations, **kwargs)
        )

    def _list_insights_sync(
        self, tenant_slug: str, limit: int = 20,
        min_confidence: int = CONFIDENCE_NEEDS_REVIEW,
        category: Optional[str] = None,
    ) -> list[AiInsightRecord]:
        q = self._SELECT_INSIGHT + " WHERE tenant_slug = ? AND final_confidence >= ?"
        params: list = [tenant_slug, int(min_confidence)]
        if category:
            q += " AND category = ?"
            params.append(category)
        q += " ORDER BY timestamp DESC LIMIT ?;"
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(q, params).fetchall()
        return [self._row_to_insight(r) for r in rows]

    async def list_insights(self, tenant_slug: str, limit: int = 20,
                            min_confidence: int = CONFIDENCE_NEEDS_REVIEW,
                            category: Optional[str] = None) -> list[AiInsightRecord]:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._list_insights_sync, tenant_slug, int(limit),
                              int(min_confidence), category)
        )

    def _list_debug_sync(self, tenant_slug: str, limit: int = 10) -> list[AiInsightRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                self._SELECT_INSIGHT + " WHERE tenant_slug = ? AND debug_prompt IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT ?;",
                (tenant_slug, int(limit)),
            ).fetchall()
        return [self._row_to_insight(r) for r in rows]

    async def list_debug(self, tenant_slug: str, limit: int = 10) -> list[AiInsightRecord]:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._list_debug_sync, tenant_slug, int(limit))
        )

    # ── Metrics history helpers ─────────────────────────────────────────────

    def _row_to_metrics(self, row: tuple) -> MetricsHistoryRecord:
        return MetricsHistoryRecord(
            id=int(row[0]),
            tenant_slug=str(row[1]),
            timestamp=str(row[2]),
            ack_rate=float(row[3]),
            avg_response_time=float(row[4]),
            offline_pct=float(row[5]),
            push_failure_rate=float(row[6]),
            active_users=int(row[7]),
            device_count=int(row[8]),
            alert_count=int(row[9]),
            health_score=int(row[10]),
        )

    def _record_metrics_sync(
        self,
        tenant_slug: str,
        stats: dict,
        health_score: int,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tenant_metrics_history
                    (tenant_slug, timestamp, ack_rate, avg_response_time,
                     offline_pct, push_failure_rate, active_users, device_count,
                     alert_count, health_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    tenant_slug, ts,
                    float(stats.get("ack_rate_pct", 100)),
                    float(stats.get("avg_response_time", 0)),
                    float(stats.get("offline_pct", 0)),
                    float(stats.get("push_failure_rate", 0)),
                    int(stats.get("active_users", 0)),
                    int(stats.get("device_count", 0)),
                    int(stats.get("alert_count", 0)),
                    int(health_score),
                ),
            )

    async def record_metrics(self, tenant_slug: str, stats: dict, health_score: int) -> None:
        import functools
        await anyio.to_thread.run_sync(
            functools.partial(self._record_metrics_sync, tenant_slug, stats, health_score)
        )

    def _get_metrics_history_sync(
        self, tenant_slug: str, limit: int = 10
    ) -> list[MetricsHistoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                self._SELECT_METRICS
                + " WHERE tenant_slug = ? ORDER BY timestamp DESC LIMIT ?;",
                (tenant_slug, int(limit)),
            ).fetchall()
        return [self._row_to_metrics(r) for r in rows]

    async def get_metrics_history(
        self, tenant_slug: str, limit: int = 10
    ) -> list[MetricsHistoryRecord]:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._get_metrics_history_sync, tenant_slug, int(limit))
        )

    def _get_metrics_window_sync(
        self, tenant_slug: str, since_iso: str
    ) -> list[MetricsHistoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                self._SELECT_METRICS
                + " WHERE tenant_slug = ? AND timestamp >= ? ORDER BY timestamp ASC;",
                (tenant_slug, since_iso),
            ).fetchall()
        return [self._row_to_metrics(r) for r in rows]

    async def get_metrics_window(
        self, tenant_slug: str, since_iso: str
    ) -> list[MetricsHistoryRecord]:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._get_metrics_window_sync, tenant_slug, since_iso)
        )

    # ── Weekly report helpers ───────────────────────────────────────────────

    def _row_to_report(self, row: tuple) -> WeeklyReportRecord:
        try:
            recs = json.loads(row[5]) if row[5] else []
        except (json.JSONDecodeError, TypeError):
            recs = []
        return WeeklyReportRecord(
            id=int(row[0]),
            tenant_slug=str(row[1]),
            week_start=str(row[2]),
            generated_at=str(row[3]),
            summary=str(row[4]),
            recommendations=recs,
            health_score=int(row[6]) if row[6] is not None else 50,
            trend=str(row[7]) if row[7] else "stable",
        )

    def _week_report_exists_sync(self, tenant_slug: str, week_start: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM ai_weekly_reports WHERE tenant_slug = ? AND week_start = ? LIMIT 1;",
                (tenant_slug, week_start),
            ).fetchone()
        return row is not None

    async def week_report_exists(self, tenant_slug: str, week_start: str) -> bool:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._week_report_exists_sync, tenant_slug, week_start)
        )

    def _save_report_sync(
        self,
        tenant_slug: str,
        week_start: str,
        summary: str,
        recommendations: list,
        health_score: int,
        trend: str,
    ) -> WeeklyReportRecord:
        generated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT OR REPLACE INTO ai_weekly_reports
                    (tenant_slug, week_start, generated_at, summary, recommendations,
                     health_score, trend)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    tenant_slug, week_start, generated_at,
                    summary, json.dumps(recommendations),
                    int(health_score), trend,
                ),
            )
            row = conn.execute(
                self._SELECT_REPORT + " WHERE id = ?;", (int(cur.lastrowid),)
            ).fetchone()
        assert row is not None
        return self._row_to_report(row)

    async def save_report(
        self,
        tenant_slug: str,
        week_start: str,
        summary: str,
        recommendations: list,
        health_score: int,
        trend: str,
    ) -> WeeklyReportRecord:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(
                self._save_report_sync,
                tenant_slug, week_start, summary, recommendations, health_score, trend,
            )
        )

    def _list_reports_sync(self, tenant_slug: str, limit: int = 12) -> list[WeeklyReportRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                self._SELECT_REPORT
                + " WHERE tenant_slug = ? ORDER BY week_start DESC LIMIT ?;",
                (tenant_slug, int(limit)),
            ).fetchall()
        return [self._row_to_report(r) for r in rows]

    async def list_reports(self, tenant_slug: str, limit: int = 12) -> list[WeeklyReportRecord]:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._list_reports_sync, tenant_slug, int(limit))
        )

    def _get_latest_health_sync(self, tenant_slug: str) -> Optional[MetricsHistoryRecord]:
        with self._connect() as conn:
            row = conn.execute(
                self._SELECT_METRICS
                + " WHERE tenant_slug = ? ORDER BY timestamp DESC LIMIT 1;",
                (tenant_slug,),
            ).fetchone()
        return self._row_to_metrics(row) if row else None

    async def get_latest_health(self, tenant_slug: str) -> Optional[MetricsHistoryRecord]:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._get_latest_health_sync, tenant_slug)
        )


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

def compute_device_status_offline_pct(devices: list) -> float:
    """Compute % of devices that are offline. Accepts any list of RegisteredDevice."""
    if not devices:
        return 0.0
    try:
        from app.services.device_registry import compute_device_status
        offline = sum(1 for d in devices if compute_device_status(d) == "offline")
        return round(offline / len(devices) * 100, 1)
    except Exception:
        return 0.0


def _check_ollama_available() -> tuple[bool, str]:
    import urllib.request
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status != 200:
                return False, f"Ollama returned HTTP {resp.status}"
            data = json.loads(resp.read().decode())
            model_names = [m.get("name", "") for m in data.get("models", [])]
            if not any(OLLAMA_MODEL in name for name in model_names):
                return False, f"Model '{OLLAMA_MODEL}' not found. Available: {model_names or 'none'}"
            return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _call_ollama_sync(prompt: str) -> tuple[str, int]:
    import urllib.request
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 400},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
        latency_ms = int((time.monotonic() - t0) * 1000)
        raw = json.loads(resp.read().decode())
    return str(raw.get("response", "")).strip(), latency_ms


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_insight_prompt(tenant_slug: str, stats: dict, category: str, trend: str,
                           health_score: int) -> str:
    trend_desc = {"improving": "trending upward", "worsening": "trending downward",
                  "stable": "stable"}.get(trend, "stable")
    return (
        "You are a school safety analytics assistant.\n"
        f"Category: {category.upper()} | Trend: {trend_desc} | Health: {health_score}/100\n\n"
        "Analyze these anonymized statistics and provide a 2-3 sentence insight "
        "and 2-3 actionable recommendations. Focus on the " + category + " category.\n\n"
        "Statistics (last 7 days):\n"
        f"- Active users: {stats.get('active_users', 0)}\n"
        f"- Registered devices: {stats.get('device_count', 0)}\n"
        f"- Alerts triggered: {stats.get('alert_count', 0)}\n"
        f"- Ack rate: {stats.get('ack_rate_pct', 0)}%\n"
        f"- Offline devices: {stats.get('offline_pct', 0):.0f}%\n"
        f"- Push failure rate: {stats.get('push_failure_rate', 0):.0f}%\n"
        f"- Drills completed: {stats.get('drill_count', 0)}\n\n"
        "Respond ONLY with JSON:\n"
        '{"severity": "info|warning|critical", "summary": "...", '
        '"recommendations": ["...", "..."], "confidence": 0-100}\n'
        "No markdown. No extra text."
    )


def _build_weekly_prompt(tenant_slug: str, week_metrics: list[MetricsHistoryRecord],
                          trend: str, health_score: int) -> str:
    if week_metrics:
        avg_ack = sum(m.ack_rate for m in week_metrics) / len(week_metrics)
        avg_offline = sum(m.offline_pct for m in week_metrics) / len(week_metrics)
        avg_push_fail = sum(m.push_failure_rate for m in week_metrics) / len(week_metrics)
        total_alerts = sum(m.alert_count for m in week_metrics)
        avg_users = sum(m.active_users for m in week_metrics) / len(week_metrics)
        data_points = len(week_metrics)
    else:
        avg_ack = avg_offline = avg_push_fail = total_alerts = avg_users = 0.0
        data_points = 0

    trend_desc = {"improving": "improving", "worsening": "declining",
                  "stable": "stable"}.get(trend, "stable")
    return (
        "You are a school safety analytics assistant generating a weekly report.\n"
        f"System health this week: {health_score}/100 ({trend_desc} trend)\n"
        f"Data points collected: {data_points}\n\n"
        "Weekly averages:\n"
        f"- Avg ack rate: {avg_ack:.0f}%\n"
        f"- Avg offline devices: {avg_offline:.0f}%\n"
        f"- Avg push failure rate: {avg_push_fail:.0f}%\n"
        f"- Total alerts triggered: {int(total_alerts)}\n"
        f"- Avg active users: {avg_users:.0f}\n\n"
        "Write a concise weekly summary (3-4 sentences) covering overall safety readiness, "
        "notable trends, and top priorities for next week.\n"
        "Respond ONLY with JSON:\n"
        '{"summary": "...", "recommendations": ["...", "...", "..."]}\n'
        "No markdown. No extra text."
    )


def _parse_insight_response(text: str) -> tuple[str, str, list, int]:
    """Returns (severity, summary, recommendations, llm_confidence)."""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            severity = str(data.get("severity", "info")).lower()
            if severity not in ("info", "warning", "critical"):
                severity = "info"
            summary = str(data.get("summary", text[:200]))
            recs = data.get("recommendations", [])
            if not isinstance(recs, list):
                recs = []
            try:
                llm_conf = max(0, min(100, int(float(data.get("confidence", 50)))))
            except (ValueError, TypeError):
                llm_conf = 50
            return severity, summary, [str(r) for r in recs[:5]], llm_conf
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return "info", text[:300] if text else "No response", [], 30


def _parse_weekly_response(text: str) -> tuple[str, list]:
    """Returns (summary, recommendations)."""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            summary = str(data.get("summary", text[:300]))
            recs = data.get("recommendations", [])
            if not isinstance(recs, list):
                recs = []
            return summary, [str(r) for r in recs[:5]]
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return text[:300] if text else "Weekly report unavailable.", []


# ---------------------------------------------------------------------------
# Analysis runners
# ---------------------------------------------------------------------------

async def run_tenant_analysis(
    tenant_slug: str,
    stats: dict,
    store: AiInsightsStore,
    *,
    debug_mode: bool = False,
) -> Optional[AiInsightRecord]:
    """
    Full per-tenant analysis pipeline:
      1. Record metrics snapshot (always, drives trend detection)
      2. Compute health score + rule/data-quality scores
      3. Detect trend from history
      4. Assign category (rule-based, before LLM)
      5. Call LLM with structured context
      6. Filter by confidence — drop anything below 60
    """
    health_score = compute_health_score(stats)
    rs = compute_rule_score(stats)
    dq = compute_data_quality(stats)

    # Always record metrics — even if analysis is skipped, history drives trend detection
    try:
        await store.record_metrics(tenant_slug, stats, health_score)
    except Exception:
        pass

    history = await store.get_metrics_history(tenant_slug, limit=10)
    trend = detect_trend(history)
    category = assign_category(stats, trend)

    prompt = _build_insight_prompt(tenant_slug, stats, category, trend, health_score)
    debug_prompt = prompt if debug_mode else None
    debug_response: Optional[str] = None
    debug_latency_ms: Optional[int] = None
    debug_error: Optional[str] = None

    try:
        response_text, latency_ms = await anyio.to_thread.run_sync(
            lambda: _call_ollama_sync(prompt)
        )
        if debug_mode:
            debug_response = response_text
            debug_latency_ms = latency_ms
        severity, summary, recommendations, llm_conf = _parse_insight_response(response_text)
    except Exception as exc:
        debug_error = str(exc) if debug_mode else None
        severity, summary, recommendations, llm_conf = "info", f"AI analysis unavailable: {exc}", [], 0

    final_conf = compute_final_confidence(rs, dq, llm_conf)

    if final_conf < CONFIDENCE_NEEDS_REVIEW and not debug_mode:
        return None

    try:
        return await store.save_insight(
            tenant_slug=tenant_slug,
            severity=severity,
            summary=summary,
            recommendations=recommendations,
            category=category,
            trend=trend,
            health_score=health_score,
            llm_confidence=llm_conf,
            final_confidence=final_conf,
            rule_score=rs,
            data_quality_score=dq,
            debug_prompt=debug_prompt,
            debug_response=debug_response,
            debug_latency_ms=debug_latency_ms,
            debug_error=debug_error,
        )
    except Exception:
        return None


async def generate_weekly_report(
    tenant_slug: str,
    week_start: str,
    store: AiInsightsStore,
) -> Optional[WeeklyReportRecord]:
    """
    Generate a weekly AI report for one tenant.
    Aggregates the past 7 days of metrics history and sends a structured prompt.
    Returns the saved report record or None on failure.
    """
    since_dt = datetime.fromisoformat(week_start.replace("Z", ""))
    week_metrics = await store.get_metrics_window(tenant_slug, since_dt.isoformat())

    if not week_metrics:
        return None

    avg_health = int(round(sum(m.health_score for m in week_metrics) / len(week_metrics)))
    history = await store.get_metrics_history(tenant_slug, limit=14)
    trend = detect_trend(history)

    prompt = _build_weekly_prompt(tenant_slug, week_metrics, trend, avg_health)

    try:
        response_text, _ = await anyio.to_thread.run_sync(
            lambda: _call_ollama_sync(prompt)
        )
        summary, recommendations = _parse_weekly_response(response_text)
    except Exception as exc:
        summary = f"Weekly report generation failed: {exc}"
        recommendations = []

    try:
        return await store.save_report(
            tenant_slug=tenant_slug,
            week_start=week_start,
            summary=summary,
            recommendations=recommendations,
            health_score=avg_health,
            trend=trend,
        )
    except Exception:
        return None
