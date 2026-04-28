"""
Auto-activity engine for sandbox/demo tenants.

Generates realistic fake activity (incidents, etc.) on a randomized timer.
All generated records carry is_simulation=True and are scoped exclusively
to tenants where is_test=True. Never touches production tenants.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bluebird.demo_engine")

_INCIDENT_TYPES = ["panic", "medical", "assist", "drill"]
_INCIDENT_WEIGHTS = [3, 2, 2, 1]

_DEMO_REPORTERS = [
    "Ms. Johnson", "Mr. Smith", "Principal Davis",
    "Coach Roberts", "Ms. Chen", "Mr. Williams",
    "Staff Member", "Security Officer", "Front Office",
]

_RESOLUTION_NOTES = [
    "Situation resolved. All clear.",
    "Emergency services confirmed departure. All clear.",
    "False alarm — drill completed successfully.",
    "Situation contained. No injuries reported.",
    "All personnel accounted for. Normal operations resumed.",
    "Matter resolved. Thank you for your prompt response.",
]


class DemoLiveEngine:
    """
    Manages per-slug background demo activity tasks.
    State is in-memory only — not persisted across restarts (by design).
    """

    def __init__(self, tenant_manager: Any) -> None:
        self._tm = tenant_manager
        self._tasks: Dict[str, asyncio.Task] = {}
        self._active: set = set()
        # per-slug ring buffer of simulated push payloads (latest 50 per tenant)
        self._push_feeds: Dict[str, List[dict]] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def is_active(self, slug: str) -> bool:
        return slug in self._active

    def push_feed(self, slug: str, limit: int = 20) -> List[dict]:
        return list(self._push_feeds.get(slug, []))[-limit:]

    async def enable(self, slug: str) -> None:
        if slug in self._active:
            return
        # Safety guard — only activate for is_test tenants
        school = self._tm.school_for_slug(slug)
        if school is None or not getattr(school, "is_test", False):
            logger.warning("demo_live_engine: refused to enable for non-test slug=%s", slug)
            return
        self._active.add(slug)
        task = asyncio.create_task(self._run_loop(slug), name=f"demo_live_{slug}")
        self._tasks[slug] = task
        logger.info("demo_live_engine: enabled slug=%s", slug)

    async def disable(self, slug: str) -> None:
        self._active.discard(slug)
        task = self._tasks.pop(slug, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("demo_live_engine: disabled slug=%s", slug)

    async def disable_all(self) -> None:
        for slug in list(self._active):
            await self.disable(slug)

    # ── Internal loop ──────────────────────────────────────────────────────────

    async def _run_loop(self, slug: str) -> None:
        while slug in self._active:
            try:
                delay = random.uniform(30, 120)
                await asyncio.sleep(delay)
                if slug not in self._active:
                    break
                await self._generate_event(slug)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("demo_live_engine error slug=%s: %s", slug, exc)
                await asyncio.sleep(15)

    async def _generate_event(self, slug: str) -> None:
        school = self._tm.school_for_slug(slug)
        if school is None or not getattr(school, "is_test", False):
            self._active.discard(slug)
            return
        tenant = self._tm.get(school)
        if tenant is None:
            return

        reporter = random.choice(_DEMO_REPORTERS)
        inc_type = random.choices(_INCIDENT_TYPES, weights=_INCIDENT_WEIGHTS, k=1)[0]

        try:
            incident = await tenant.incident_store.create_incident(
                type_value=inc_type,
                status="active",
                created_by=0,
                school_id=slug,
                target_scope="ALL",
                metadata={"demo": True, "reported_by": reporter},
                is_simulation=True,
            )
            self._record_push(slug, {
                "type": "demo_incident",
                "incident_type": inc_type,
                "reported_by": reporter,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": f"{inc_type.replace('_', ' ').title()} reported — Demo Mode",
            })
            resolve_delay = random.uniform(60, 300)
            asyncio.create_task(
                self._auto_resolve(tenant, incident.id, resolve_delay, slug),
                name=f"demo_resolve_{slug}_{incident.id}",
            )
            logger.debug("demo_live_engine: created %s id=%s slug=%s", inc_type, incident.id, slug)
        except Exception as exc:
            logger.warning("demo_live_engine: event create failed slug=%s: %s", slug, exc)

    async def _auto_resolve(self, tenant: Any, incident_id: int, delay: float, slug: str) -> None:
        await asyncio.sleep(delay)
        try:
            note = random.choice(_RESOLUTION_NOTES)
            await tenant.incident_store.resolve_incident(incident_id, notes=note)
            logger.debug("demo_live_engine: auto-resolved id=%s slug=%s", incident_id, slug)
        except Exception as exc:
            logger.warning("demo_live_engine: auto-resolve failed id=%s: %s", incident_id, exc)

    def _record_push(self, slug: str, payload: dict) -> None:
        feed = self._push_feeds.setdefault(slug, [])
        feed.append(payload)
        if len(feed) > 50:
            self._push_feeds[slug] = feed[-50:]
