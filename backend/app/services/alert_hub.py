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
        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_text(encoded)
            except Exception:
                stale.append(websocket)
        if stale:
            async with self._lock:
                sockets = self._connections.get(slug)
                if not sockets:
                    return
                for websocket in stale:
                    sockets.discard(websocket)
                if not sockets:
                    self._connections.pop(slug, None)

    def connection_count(self, tenant_slug: str) -> int:
        """Return the number of active WebSocket connections for a tenant."""
        return len(self._connections.get(tenant_slug, set()))

    def connected_slugs(self) -> list[str]:
        """Return slugs that currently have at least one active connection."""
        return [slug for slug, sockets in self._connections.items() if sockets]
