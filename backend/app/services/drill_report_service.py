from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import anyio


@dataclass(frozen=True)
class AckRecord:
    user_id: int
    user_label: Optional[str]
    acknowledged_at: str


@dataclass(frozen=True)
class TimelineEvent:
    timestamp: str
    event_type: str
    actor_label: Optional[str]
    detail: str


@dataclass(frozen=True)
class DrillReport:
    alert_id: int
    tenant_slug: str
    message: str
    is_training: bool
    training_label: Optional[str]
    created_at: str
    activated_by: Optional[str]
    deactivated_at: Optional[str]
    deactivated_by: Optional[str]
    # Acknowledgement stats
    total_users_expected: int
    total_acknowledged: int
    acknowledgement_rate: float
    first_ack_time: Optional[str]
    last_ack_time: Optional[str]
    acknowledgements: List[AckRecord]
    # Timeline
    timeline: List[TimelineEvent]
    # Delivery
    delivery_total: int
    delivery_ok: int
    delivery_failed: int

    def to_dict(self) -> Dict[str, Any]:
        rate_label = (
            "green" if self.acknowledgement_rate >= 90
            else "yellow" if self.acknowledgement_rate >= 60
            else "red"
        )
        return {
            "alert": {
                "alert_id": self.alert_id,
                "message": self.message,
                "is_training": self.is_training,
                "training_label": self.training_label,
                "created_at": self.created_at,
                "activated_by": self.activated_by,
                "deactivated_at": self.deactivated_at,
                "deactivated_by": self.deactivated_by,
            },
            "ack_stats": {
                "total_users_expected": self.total_users_expected,
                "total_acknowledged": self.total_acknowledged,
                "acknowledgement_rate": round(self.acknowledgement_rate, 1),
                "rate_label": rate_label,
                "first_ack_time": self.first_ack_time,
                "last_ack_time": self.last_ack_time,
            },
            "timeline": [
                {
                    "timestamp": e.timestamp,
                    "event_type": e.event_type,
                    "actor_label": e.actor_label,
                    "detail": e.detail,
                }
                for e in self.timeline
            ],
            "delivery": {
                "total": self.delivery_total,
                "ok": self.delivery_ok,
                "failed": self.delivery_failed,
            },
            "acknowledgements": [
                {
                    "user_id": a.user_id,
                    "user_label": a.user_label,
                    "acknowledged_at": a.acknowledged_at,
                }
                for a in self.acknowledgements
            ],
        }


class DrillReportService:
    """
    Builds structured drill/alert reports from per-tenant SQLite.
    Shares the same DB file as AlertLog, AlarmStore, and AuditLogService.
    All reads are run in a thread executor.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=30, isolation_level=None)

    def _build_sync(self, alert_id: int, tenant_slug: str) -> Optional[DrillReport]:
        with self._connect() as conn:
            # 1. Alert metadata
            alert_row = conn.execute(
                """
                SELECT id, created_at, message, is_training, training_label,
                       triggered_by_label
                FROM alerts WHERE id = ?;
                """,
                (int(alert_id),),
            ).fetchone()
            if alert_row is None:
                return None

            # 2. Alarm state for deactivated_at / deactivated_by
            state_row = conn.execute(
                "SELECT activated_at, activated_by_label, deactivated_at, deactivated_by_label FROM alarm_state LIMIT 1;"
            ).fetchone()
            deactivated_at = str(state_row[2]) if state_row and state_row[2] else None
            deactivated_by = str(state_row[3]) if state_row and state_row[3] else None

            # 3. Acknowledgements
            ack_rows = conn.execute(
                """
                SELECT user_id, user_label, acknowledged_at
                FROM alert_acknowledgements
                WHERE alert_id = ?
                ORDER BY acknowledged_at ASC;
                """,
                (int(alert_id),),
            ).fetchall()

            # 4. Active user count
            user_count_row = conn.execute(
                "SELECT COUNT(*) FROM users WHERE is_active = 1;"
            ).fetchone()
            total_users = int(user_count_row[0]) if user_count_row else 0

            # 5. Delivery stats
            delivery_row = conn.execute(
                """
                SELECT COUNT(*),
                       SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END)
                FROM alert_deliveries WHERE alert_id = ?;
                """,
                (int(alert_id),),
            ).fetchone()
            delivery_total = int(delivery_row[0]) if delivery_row and delivery_row[0] else 0
            delivery_ok = int(delivery_row[1] or 0) if delivery_row else 0

            # 6. Audit timeline for this alert
            audit_rows = conn.execute(
                """
                SELECT timestamp, event_type, actor_label, metadata
                FROM audit_log
                WHERE event_type IN (
                    'alarm_activated','training_started',
                    'alarm_deactivated','training_ended',
                    'alert_acknowledged','user_login'
                )
                ORDER BY timestamp ASC
                LIMIT 500;
                """,
            ).fetchall()

        # Build ack records
        acks = [
            AckRecord(
                user_id=int(r[0]),
                user_label=str(r[1]) if r[1] else None,
                acknowledged_at=str(r[2]),
            )
            for r in ack_rows
        ]

        # Build timeline — filter audit events relevant to this alert
        timeline: List[TimelineEvent] = []
        for row in audit_rows:
            ts, etype, actor, meta_json = row
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except (ValueError, TypeError):
                meta = {}

            if etype in ("alarm_activated", "training_started"):
                if int(meta.get("alert_id", -1)) == int(alert_id):
                    mode = "Training drill" if meta.get("is_training") else "Live alarm"
                    apns = meta.get("apns_count", 0)
                    fcm = meta.get("fcm_count", 0)
                    timeline.append(TimelineEvent(
                        timestamp=str(ts),
                        event_type=etype,
                        actor_label=str(actor) if actor else None,
                        detail=f"{mode} activated. Push targets: APNs={apns}, FCM={fcm}.",
                    ))

            elif etype in ("alarm_deactivated", "training_ended"):
                # Match by proximity: if deactivated_at is set, check timestamp
                if deactivated_at and str(ts)[:16] == deactivated_at[:16]:
                    timeline.append(TimelineEvent(
                        timestamp=str(ts),
                        event_type=etype,
                        actor_label=str(actor) if actor else None,
                        detail="Alarm deactivated.",
                    ))

            elif etype == "alert_acknowledged":
                if int(meta.get("alert_id", -1)) == int(alert_id):
                    count = meta.get("total_acknowledgements", "")
                    timeline.append(TimelineEvent(
                        timestamp=str(ts),
                        event_type=etype,
                        actor_label=str(actor) if actor else None,
                        detail=f"Acknowledged. Total: {count}.",
                    ))

        # Ack stats
        total_acked = len(acks)
        rate = (total_acked / total_users * 100.0) if total_users > 0 else 0.0
        first_ack = acks[0].acknowledged_at if acks else None
        last_ack = acks[-1].acknowledged_at if acks else None

        return DrillReport(
            alert_id=int(alert_row[0]),
            tenant_slug=tenant_slug,
            message=str(alert_row[2]),
            is_training=bool(int(alert_row[3])),
            training_label=str(alert_row[4]) if alert_row[4] else None,
            created_at=str(alert_row[1]),
            activated_by=str(alert_row[5]) if alert_row[5] else None,
            deactivated_at=deactivated_at,
            deactivated_by=deactivated_by,
            total_users_expected=total_users,
            total_acknowledged=total_acked,
            acknowledgement_rate=round(rate, 1),
            first_ack_time=first_ack,
            last_ack_time=last_ack,
            acknowledgements=acks,
            timeline=sorted(timeline, key=lambda e: e.timestamp),
            delivery_total=delivery_total,
            delivery_ok=delivery_ok,
            delivery_failed=delivery_total - delivery_ok,
        )

    async def build_report(self, alert_id: int, tenant_slug: str) -> Optional[DrillReport]:
        """Build a complete drill/alert report. Returns None if alert_id not found."""
        return await anyio.to_thread.run_sync(self._build_sync, int(alert_id), str(tenant_slug))
