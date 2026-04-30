"""
AI Insights service — Ollama/llama3 local AI analysis for super admin dashboard.

Tenant isolation: each call is scoped to exactly one tenant. No cross-tenant data
is ever aggregated or sent to the model. Data passed to the model is a summary
of aggregate statistics only (counts, rates) — never raw logs, messages, or PII.

Access control: the background job checks ai_insights.enabled per tenant and skips
disabled tenants. The API endpoints are gated by _require_super_admin().

Global toggle: AI_INSIGHTS_GLOBAL_ENABLED env var (default false). If false,
the background job exits immediately and endpoints return a 503.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

import anyio

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("AI_INSIGHTS_MODEL", "llama3")
OLLAMA_TIMEOUT = float(os.getenv("AI_INSIGHTS_TIMEOUT_S", "10"))
AI_INSIGHTS_GLOBAL_ENABLED = os.getenv("AI_INSIGHTS_GLOBAL_ENABLED", "false").lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class AiInsightRecord:
    id: int
    tenant_slug: str
    timestamp: str
    severity: str
    summary: str
    recommendations: list
    debug_prompt: Optional[str]
    debug_response: Optional[str]
    debug_latency_ms: Optional[int]
    debug_error: Optional[str]


class AiInsightsStore:
    """SQLite-backed storage for AI insight records. One DB shared across all tenants (platform DB)."""

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
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_slug      TEXT    NOT NULL,
                    timestamp        TEXT    NOT NULL,
                    severity         TEXT    NOT NULL DEFAULT 'info',
                    summary          TEXT    NOT NULL DEFAULT '',
                    recommendations  TEXT    NOT NULL DEFAULT '[]',
                    debug_prompt     TEXT    NULL,
                    debug_response   TEXT    NULL,
                    debug_latency_ms INTEGER NULL,
                    debug_error      TEXT    NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_insights_tenant ON ai_insights(tenant_slug, timestamp DESC);"
            )
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(ai_insights);").fetchall()}
        for col, defn in [
            ("debug_prompt", "TEXT NULL"),
            ("debug_response", "TEXT NULL"),
            ("debug_latency_ms", "INTEGER NULL"),
            ("debug_error", "TEXT NULL"),
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
            debug_prompt=str(row[6]) if len(row) > 6 and row[6] else None,
            debug_response=str(row[7]) if len(row) > 7 and row[7] else None,
            debug_latency_ms=int(row[8]) if len(row) > 8 and row[8] is not None else None,
            debug_error=str(row[9]) if len(row) > 9 and row[9] else None,
        )

    def _save_insight_sync(
        self,
        tenant_slug: str,
        severity: str,
        summary: str,
        recommendations: list,
        *,
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
                     debug_prompt, debug_response, debug_latency_ms, debug_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    tenant_slug, ts, severity, summary, json.dumps(recommendations),
                    debug_prompt, debug_response, debug_latency_ms, debug_error,
                ),
            )
            row = conn.execute(
                "SELECT id, tenant_slug, timestamp, severity, summary, recommendations, "
                "debug_prompt, debug_response, debug_latency_ms, debug_error "
                "FROM ai_insights WHERE id = ?;",
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
                tenant_slug, severity, summary, recommendations, **kwargs
            )
        )

    def _list_insights_sync(self, tenant_slug: str, limit: int = 20) -> list[AiInsightRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, tenant_slug, timestamp, severity, summary, recommendations, "
                "debug_prompt, debug_response, debug_latency_ms, debug_error "
                "FROM ai_insights WHERE tenant_slug = ? ORDER BY timestamp DESC LIMIT ?;",
                (tenant_slug, int(limit)),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    async def list_insights(self, tenant_slug: str, limit: int = 20) -> list[AiInsightRecord]:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._list_insights_sync, tenant_slug, int(limit))
        )

    def _list_debug_sync(self, tenant_slug: str, limit: int = 10) -> list[AiInsightRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, tenant_slug, timestamp, severity, summary, recommendations, "
                "debug_prompt, debug_response, debug_latency_ms, debug_error "
                "FROM ai_insights WHERE tenant_slug = ? AND debug_prompt IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT ?;",
                (tenant_slug, int(limit)),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    async def list_debug(self, tenant_slug: str, limit: int = 10) -> list[AiInsightRecord]:
        import functools
        return await anyio.to_thread.run_sync(
            functools.partial(self._list_debug_sync, tenant_slug, int(limit))
        )


def _check_ollama_available() -> tuple[bool, str]:
    """Return (available, reason). Best-effort sync check via urllib — no extra deps."""
    import urllib.request
    import urllib.error
    try:
        url = f"{OLLAMA_BASE_URL}/api/tags"
        req = urllib.request.Request(url, method="GET")
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
    """Call Ollama generate API. Returns (response_text, latency_ms). Raises on failure."""
    import urllib.request
    import urllib.error
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 300},
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
        f"You are a school safety analytics assistant.\n"
        f"Analyze the following anonymized statistics for school '{tenant_slug}' "
        f"and provide a brief insight (2-3 sentences) and 2-3 actionable recommendations.\n\n"
        f"Statistics (last 7 days):\n"
        f"- Active users: {stats.get('active_users', 0)}\n"
        f"- Registered devices: {stats.get('device_count', 0)}\n"
        f"- Alerts triggered: {stats.get('alert_count', 0)}\n"
        f"- Avg acknowledgement rate: {stats.get('ack_rate_pct', 0)}%\n"
        f"- Drills completed: {stats.get('drill_count', 0)}\n"
        f"- Quiet period requests: {stats.get('quiet_period_count', 0)}\n\n"
        f"Respond in JSON with this exact structure:\n"
        f'{{"severity": "info|warning|critical", "summary": "...", "recommendations": ["...", "..."]}}\n'
        f"Only output the JSON object. No extra text."
    )


def _parse_llm_response(text: str) -> tuple[str, str, list]:
    """Parse LLM JSON response. Returns (severity, summary, recommendations)."""
    try:
        # Find JSON object in response (model may wrap it in markdown)
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
            return severity, summary, [str(r) for r in recs[:5]]
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return "info", text[:300] if text else "No response", []


async def run_tenant_analysis(
    tenant_slug: str,
    stats: dict,
    store: AiInsightsStore,
    *,
    debug_mode: bool = False,
) -> Optional[AiInsightRecord]:
    """
    Run AI analysis for one tenant. Returns saved record or None on failure.
    Never raises — failures are logged and stored as debug_error when debug_mode is on.
    """
    prompt = _build_prompt(tenant_slug, stats)
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
        severity, summary, recommendations = _parse_llm_response(response_text)
    except Exception as exc:
        debug_error = str(exc) if debug_mode else None
        severity, summary, recommendations = "info", f"AI analysis unavailable: {exc}", []

    try:
        return await store.save_insight(
            tenant_slug=tenant_slug,
            severity=severity,
            summary=summary,
            recommendations=recommendations,
            debug_prompt=debug_prompt,
            debug_response=debug_response,
            debug_latency_ms=debug_latency_ms,
            debug_error=debug_error,
        )
    except Exception:
        return None
