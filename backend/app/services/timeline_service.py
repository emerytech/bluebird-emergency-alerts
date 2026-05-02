"""
Timeline service — builds a chronological event list for an alert incident.

Events are sourced from the audit log for the tenant.  Each event is
normalised into a TimelineEvent with a relative_ms offset from the
alert's trigger time so clients can render a horizontal timeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.alert_log import AlertLog
from app.services.audit_log_service import AuditLogService


@dataclass
class TimelineEvent:
    event_id: int
    event_type: str
    timestamp: str
    relative_ms: int
    actor: Optional[str]
    payload: dict[str, Any] = field(default_factory=dict)


class TimelineService:
    """Builds ordered event timelines for alert incidents."""

    def __init__(self, alert_log: AlertLog, audit_log_service: AuditLogService) -> None:
        self._alert_log = alert_log
        self._audit = audit_log_service

    async def build(self, alert_id: int) -> list[TimelineEvent]:
        """Return chronological TimelineEvent list for the given alert."""
        alert = await self._alert_log.get_alert(alert_id)
        if alert is None:
            return []

        # Use alert created_at as origin for relative timestamps.
        import datetime as _dt

        def _parse_iso(ts: str) -> Optional[_dt.datetime]:
            try:
                return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                return None

        origin_str = str(getattr(alert, "created_at", "") or "")
        origin = _parse_iso(origin_str)

        events: list[TimelineEvent] = []

        # Seed with the alert-triggered event.
        events.append(TimelineEvent(
            event_id=0,
            event_type="alert_triggered",
            timestamp=origin_str,
            relative_ms=0,
            actor=None,
            payload={"message": getattr(alert, "message", ""), "is_training": getattr(alert, "is_training", False)},
        ))

        # Pull audit log entries that reference this alert.
        try:
            entries = await self._audit.list_entries(limit=500, alert_id=alert_id)
        except Exception:
            entries = []

        for i, entry in enumerate(entries, start=1):
            ts_str = str(getattr(entry, "created_at", "") or "")
            ts = _parse_iso(ts_str)
            relative_ms = int((ts - origin).total_seconds() * 1000) if (ts and origin) else 0
            events.append(TimelineEvent(
                event_id=i,
                event_type=str(getattr(entry, "event_type", "audit_event") or "audit_event"),
                timestamp=ts_str,
                relative_ms=max(0, relative_ms),
                actor=str(getattr(entry, "actor_name", None) or getattr(entry, "actor_id", None) or ""),
                payload={
                    "details": str(getattr(entry, "details", "") or ""),
                    "target": str(getattr(entry, "target_name", "") or ""),
                },
            ))

        events.sort(key=lambda e: e.relative_ms)
        return events
