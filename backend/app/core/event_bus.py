"""
In-process async event bus for tenant-scoped events.

Used by routes.py to publish lifecycle events (alert triggered, ack updated,
message sent, presence changes, etc.) so that subscribers — such as district
dashboards or analytics sinks — can react without polling.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    ALERT_TRIGGERED = "alert_triggered"
    ALERT_DEACTIVATED = "alert_deactivated"
    ALERT_ACKNOWLEDGED = "alert_acknowledged"
    MESSAGE_SENT = "message_sent"
    MESSAGE_READ = "message_read"
    MESSAGE_PINNED = "message_pinned"
    MESSAGE_PRIORITY = "message_priority"
    ADMIN_BROADCAST = "admin_broadcast"
    ADMIN_REPLY = "admin_reply"
    THREAD_REPLY = "thread_reply"
    USER_ONLINE = "user_online"
    USER_OFFLINE = "user_offline"
    ROSTER_UPDATED = "roster_updated"
    STUDENTS_ACCOUNTED = "students_accounted"
    GENERIC = "generic"


@dataclass
class Event:
    event_type: EventType
    tenant_slug: str
    payload: dict[str, Any] = field(default_factory=dict)
    user_id: Optional[int] = None


Subscriber = Callable[[Event], Awaitable[None]]


class EventBus:
    """Simple in-process fan-out event bus."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._lock = asyncio.Lock()

    async def subscribe(self, fn: Subscriber) -> None:
        async with self._lock:
            self._subscribers.append(fn)

    async def unsubscribe(self, fn: Subscriber) -> None:
        async with self._lock:
            self._subscribers = [s for s in self._subscribers if s is not fn]

    async def emit(self, event: Event) -> None:
        subscribers = list(self._subscribers)
        for fn in subscribers:
            try:
                await fn(event)
            except Exception:
                logger.exception("EventBus subscriber raised exception for event %s", event.event_type)
