from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("bluebird.alert_hub")


class AlertHub:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        # District connections — keyed by slug, value is set of WebSockets watching that slug.
        self._district_slug_index: dict[str, set[WebSocket]] = defaultdict(set)
        # Reverse index: id(ws) → frozenset of slugs, for O(1) cleanup on disconnect.
        self._district_ws_slugs: dict[int, frozenset[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, tenant_slug: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[tenant_slug].add(websocket)
        logger.debug("WebSocket connected: tenant=%s total=%d", tenant_slug, self.connection_count(tenant_slug))

    async def disconnect(self, tenant_slug: str, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(tenant_slug)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(tenant_slug, None)
        logger.debug("WebSocket disconnected: tenant=%s total=%d", tenant_slug, self.connection_count(tenant_slug))

    async def connect_district(self, websocket: WebSocket, subscribed_slugs: frozenset[str]) -> None:
        """Register a district-level WebSocket that fans out events for multiple tenant slugs."""
        await websocket.accept()
        async with self._lock:
            for slug in subscribed_slugs:
                self._district_slug_index[slug].add(websocket)
            self._district_ws_slugs[id(websocket)] = subscribed_slugs
        logger.debug(
            "District WebSocket connected: slugs=%s total_district=%d",
            sorted(subscribed_slugs),
            self.district_connection_count(),
        )

    async def disconnect_district(self, websocket: WebSocket) -> None:
        """Remove a district WebSocket from all slug subscriptions."""
        async with self._lock:
            slugs = self._district_ws_slugs.pop(id(websocket), frozenset())
            for slug in slugs:
                bucket = self._district_slug_index.get(slug)
                if bucket:
                    bucket.discard(websocket)
                    if not bucket:
                        self._district_slug_index.pop(slug, None)
        logger.debug(
            "District WebSocket disconnected: slugs=%s total_district=%d",
            sorted(slugs),
            self.district_connection_count(),
        )

    async def publish(self, tenant_slug: str, payload: dict[str, Any]) -> None:
        slug = str(tenant_slug or "").strip()
        if not slug:
            logger.error(
                "AlertHub.publish called with empty tenant_slug — payload dropped to prevent cross-tenant broadcast. payload=%r",
                payload,
            )
            return
        encoded = json.dumps(payload, separators=(",", ":"), default=str)
        async with self._lock:
            sockets = list(self._connections.get(slug, set()))
            district_sockets = list(self._district_slug_index.get(slug, set()))
        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_text(encoded)
            except Exception:
                stale.append(websocket)
        if stale:
            async with self._lock:
                bucket = self._connections.get(slug)
                if bucket:
                    for websocket in stale:
                        bucket.discard(websocket)
                    if not bucket:
                        self._connections.pop(slug, None)
        district_stale: list[WebSocket] = []
        for websocket in district_sockets:
            try:
                await websocket.send_text(encoded)
            except Exception:
                district_stale.append(websocket)
        if district_stale:
            async with self._lock:
                for websocket in district_stale:
                    slugs = self._district_ws_slugs.pop(id(websocket), frozenset())
                    for s in slugs:
                        bucket = self._district_slug_index.get(s)
                        if bucket:
                            bucket.discard(websocket)
                            if not bucket:
                                self._district_slug_index.pop(s, None)

    def connection_count(self, tenant_slug: str) -> int:
        """Return the number of active WebSocket connections for a tenant."""
        return len(self._connections.get(tenant_slug, set()))

    def district_connection_count(self) -> int:
        """Return the number of active district WebSocket connections."""
        return len(self._district_ws_slugs)

    def connected_slugs(self) -> list[str]:
        """Return slugs that currently have at least one active connection."""
        return [slug for slug, sockets in self._connections.items() if sockets]
