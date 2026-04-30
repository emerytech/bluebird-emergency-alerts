"""
AI Insights service — Ollama/llama3 local AI analysis for super admin dashboard.

Confidence scoring combines three independent signals so that the system never
relies solely on the LLM's self-reported confidence:

  final_confidence = 0.4 * rule_score + 0.3 * data_quality + 0.3 * llm_confidence

  ≥ 80  → shown normally (HIGH)
  60–79 → shown with "Needs Review" warning
  < 60  → filtered out, not stored

Tenant isolation: each call is scoped to exactly one tenant. Stats passed to the
model are aggregate counts only — never raw logs, messages, or PII.

Global toggle: AI_INSIGHTS_GLOBAL_ENABLED env var (default false).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import anyio

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("AI_INSIGHTS_MODEL", "llama3")
OLLAMA_TIMEOUT = float(os.getenv("AI_INSIGHTS_TIMEOUT_S", "10"))
AI_INSIGHTS_GLOBAL_ENABLED = os.getenv("AI_INSIGHTS_GLOBAL_ENABLED", "false").lower() in ("1", "true", "yes")

# Confidence thresholds
CONFIDENCE_HIGH = 80
CONFIDENCE_NEEDS_REVIEW = 60   # below this → filtered out


@dataclass(frozen=True)
class AiInsightRecord:
    id: int
    tenant_slug: str
    timestamp: str
    severity: str
    summary: str
    recommendations: list
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


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def compute_rule_score(stats: dict) -> int:
    """
    Rule-based signal score (0-100). Measures how much notable activity
    exists in the data — more signal gives the AI more to analyze reliably.
    """
    score = 40  # baseline

    ack_rate = int(stats.get("ack_rate_pct", 100))
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

    drill_count = int(stats.get("drill_count", 0))
    if drill_count >= 2:
        score += 5

    return min(100, max(0, score))


def compute_data_quality(stats: dict) -> int:
    """
    Data quality score (0-100). Penalizes small samples, stale data,
    and tenants with very low activity where AI analysis is unreliable.
    """
    score = 80  # start high, deduct for quality problems

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

    alert_count = int(stats.get("alert_count", 0))
    drill_count = int(stats.get("drill_count", 0))
    if alert_count == 0 and drill_count == 0:
        score -= 20

    return min(100, max(0, score))


def compute_final_confidence(rule_score: int, data_quality: int, llm_confidence: int) -> int:
    """Weighted combination of the three independent signals."""
    raw = 0.4 * rule_score + 0.3 * data_quality + 0.3 * llm_confidence
    return int(round(min(100, max(0, raw))))


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class AiInsightsStore:
    """SQLite-backed storage for AI insight records (platform DB, cross-tenant)."""

    _SELECT = (
        "SELECT id, tenant_slug, timestamp, severity, summary, recommendations, "
        "llm_confidence, final_confidence, rule_score, data_quality_score, "
        "debug_prompt, debug_response, debug_latency_ms, debug_error "
        "FROM ai_insights"
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_insights (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_slug       TEXT    NOT NULL,
                    timestamp         TEXT    NOT NULL,
                    severity          TEXT    NOT NULL DEFAULT 'info',
                    summary           TEXT    NOT NULL DEFAULT '',
                    recommendations   TEXT    NOT NULL DEFAULT '[]',
                    llm_confidence    INTEGER NOT NULL DEFAULT 50,
                    final_confidence  INTEGER NOT NULL DEFAULT 50,
                    rule_score        INTEGER NOT NULL DEFAULT 50,
                    data_quality_score INTEGER NOT NULL DEFAULT 50,
                    debug_prompt      TEXT    NULL,
                    debug_response    TEXT    NULL,
                    debug_latency_ms  INTEGER NULL,
                    debug_error       TEXT    NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_insights_tenant "
                "ON ai_insights(tenant_slug, timestamp DESC);"
            )
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(ai_insights);").fetchall()}
        for col, defn in [
            ("debug_prompt", "TEXT NULL"),
            ("debug_response", "TEXT NULL"),
            ("debug_latency_ms", "INTEGER NULL"),
            ("debug_error", "TEXT NULL"),
            ("llm_confidence", "INTEGER NOT NULL DEFAULT 50"),
            ("final_confidence", "INTEGER NOT NULL DEFAULT 50"),
            ("rule_score", "INTEGER NOT NULL DEFAULT 50"),
            ("data_quality_score", "INTEGER NOT NULL DEFAULT 50"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE ai_insights ADD COLUMN {col} {defn};")

    def _row_to_record(self, row: tuple) -> AiInsightRecord:
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
            llm_confidence=int(row[6]) if row[6] is not None else 50,
            final_confidence=int(row[7]) if row[7] is not None else 50,
            rule_score=int(row[8]) if row[8] is not None else 50,
            data_quality_score=int(row[9]) if row[9] is not None else 50,
            debug_prompt=str(row[10]) if len(row) > 10 and row[10] else None,
            debug_response=str(row[11]) if len(row) > 11 and row[11] else None,
            debug_latency_ms=int(row[12]) if len(row) > 12 and row[12] is not None else None,
            debug_error=str(row[13]) if len(row) > 13 and row[13] else None,
        )

    def _save_insight_sync(
        self,
        tenant_slug: str,
        severity: str,
        summary: str,
        recommendations: list,
        *,
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
                     llm_confidence, final_confidence, rule_score, data_quality_score,
                     debug_prompt, debug_response, debug_latency_ms, debug_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    tenant_slug, ts, severity, summary, json.dumps(recommendations),
                    int(llm_confidence), int(final_confidence),
                    int(rule_score), int(data_quality_score),
                    debug_prompt, debug_response, debug_latency_ms, debug_error,
                ),
            )
            row = conn.execute(
                self._SELECT + " WHERE id = ?;",
                (int(cur.lastrowid),),
            ).fetchone()
        assert row is not None
        return self._row_to_record(row)

    async def save_insight(
        self,
        tenant_slug: str,
        severity: str,
        summary: str,
        recommendations: list,
        **kwargs: Any,
    ) -> AiInsightRecord:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(
                self._save_insight_sync,
                tenant_slug, severity, summary, recommendations, **kwargs,
            )
        )

    def _list_insights_sync(
        self, tenant_slug: str, limit: int = 20, min_confidence: int = CONFIDENCE_NEEDS_REVIEW
    ) -> list[AiInsightRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                self._SELECT + " WHERE tenant_slug = ? AND final_confidence >= ? "
                "ORDER BY timestamp DESC LIMIT ?;",
                (tenant_slug, int(min_confidence), int(limit)),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    async def list_insights(
        self, tenant_slug: str, limit: int = 20, min_confidence: int = CONFIDENCE_NEEDS_REVIEW
    ) -> list[AiInsightRecord]:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._list_insights_sync, tenant_slug, int(limit), int(min_confidence))
        )

    def _list_debug_sync(self, tenant_slug: str, limit: int = 10) -> list[AiInsightRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                self._SELECT + " WHERE tenant_slug = ? AND debug_prompt IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT ?;",
                (tenant_slug, int(limit)),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    async def list_debug(self, tenant_slug: str, limit: int = 10) -> list[AiInsightRecord]:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._list_debug_sync, tenant_slug, int(limit))
        )


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

def _check_ollama_available() -> tuple[bool, str]:
    """Return (available, reason). Best-effort sync check — no extra deps."""
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
    """Call Ollama generate. Returns (response_text, latency_ms). Raises on failure."""
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


def _build_prompt(tenant_slug: str, stats: dict) -> str:
    return (
        "You are a school safety analytics assistant.\n"
        "Analyze the following anonymized statistics for a school and provide:\n"
        "- A brief insight (2-3 sentences)\n"
        "- 2-3 actionable recommendations\n"
        "- Your confidence in this analysis (0-100), where 100 means very strong signal\n\n"
        "Statistics (last 7 days):\n"
        f"- Active users: {stats.get('active_users', 0)}\n"
        f"- Registered devices: {stats.get('device_count', 0)}\n"
        f"- Alerts triggered: {stats.get('alert_count', 0)}\n"
        f"- Avg acknowledgement rate: {stats.get('ack_rate_pct', 0)}%\n"
        f"- Drills completed: {stats.get('drill_count', 0)}\n"
        f"- Quiet period requests: {stats.get('quiet_period_count', 0)}\n\n"
        "Respond ONLY with a JSON object in this exact structure:\n"
        '{"severity": "info|warning|critical", "summary": "...", '
        '"recommendations": ["...", "..."], "confidence": 0-100}\n'
        "Output only the JSON. No markdown, no extra text."
    )


def _parse_llm_response(text: str) -> tuple[str, str, list, int]:
    """Parse LLM JSON. Returns (severity, summary, recommendations, llm_confidence 0-100)."""
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
            raw_conf = data.get("confidence", 50)
            try:
                llm_conf = max(0, min(100, int(float(raw_conf))))
            except (ValueError, TypeError):
                llm_conf = 50
            return severity, summary, [str(r) for r in recs[:5]], llm_conf
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return "info", text[:300] if text else "No response", [], 30


# ---------------------------------------------------------------------------
# Analysis runner
# ---------------------------------------------------------------------------

async def run_tenant_analysis(
    tenant_slug: str,
    stats: dict,
    store: AiInsightsStore,
    *,
    debug_mode: bool = False,
) -> Optional[AiInsightRecord]:
    """
    Run AI analysis for one tenant. Computes confidence, filters low-confidence
    results, and saves to store. Returns saved record or None.

    Never raises — all failures are handled gracefully.
    """
    prompt = _build_prompt(tenant_slug, stats)
    debug_prompt = prompt if debug_mode else None
    debug_response: Optional[str] = None
    debug_latency_ms: Optional[int] = None
    debug_error: Optional[str] = None

    # Rule-based and data quality scores are computed independently of the LLM
    rs = compute_rule_score(stats)
    dq = compute_data_quality(stats)

    try:
        response_text, latency_ms = await anyio.to_thread.run_sync(
            lambda: _call_ollama_sync(prompt)
        )
        if debug_mode:
            debug_response = response_text
            debug_latency_ms = latency_ms
        severity, summary, recommendations, llm_conf = _parse_llm_response(response_text)
    except Exception as exc:
        debug_error = str(exc) if debug_mode else None
        severity, summary, recommendations, llm_conf = "info", f"AI analysis unavailable: {exc}", [], 0

    final_conf = compute_final_confidence(rs, dq, llm_conf)

    # Filter out low-confidence insights entirely — don't store noise
    if final_conf < CONFIDENCE_NEEDS_REVIEW and not debug_mode:
        return None

    try:
        return await store.save_insight(
            tenant_slug=tenant_slug,
            severity=severity,
            summary=summary,
            recommendations=recommendations,
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
