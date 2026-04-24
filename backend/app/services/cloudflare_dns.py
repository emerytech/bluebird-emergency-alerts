from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import Settings


class CloudflareDNSError(RuntimeError):
    pass


@dataclass(frozen=True)
class CloudflareDNSResult:
    hostname: str
    record_id: str
    created: bool


class CloudflareDNSClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://api.cloudflare.com/client/v4",
            timeout=15.0,
            headers={
                "Authorization": f"Bearer {self._settings.CLOUDFLARE_API_TOKEN}",
                "Content-Type": "application/json",
            },
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def is_configured(self) -> bool:
        return self._settings.cloudflare_dns_is_configured()

    def school_hostname(self, slug: str) -> str:
        return f"{slug.strip().lower()}.{self._settings.cloudflare_dns_base_hostname}"

    def _record_payload(self, hostname: str) -> dict[str, Any]:
        return {
            "type": "CNAME",
            "name": hostname,
            "content": str(self._settings.CLOUDFLARE_TUNNEL_CNAME_TARGET),
            "proxied": bool(self._settings.CLOUDFLARE_DNS_PROXIED),
            "ttl": 1,
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if self._client is None:
            raise CloudflareDNSError("Cloudflare DNS client is not started.")
        response = await self._client.request(method, path, **kwargs)
        try:
            data = response.json()
        except ValueError as exc:
            raise CloudflareDNSError(f"Cloudflare returned a non-JSON response ({response.status_code}).") from exc
        if response.status_code >= 400 or not data.get("success", False):
            errors = data.get("errors") or []
            detail = "; ".join(str(item.get("message", item)) for item in errors) or f"HTTP {response.status_code}"
            raise CloudflareDNSError(detail)
        return data

    async def create_or_update_school_dns(self, slug: str) -> CloudflareDNSResult:
        if not self.is_configured():
            raise CloudflareDNSError("Cloudflare DNS automation is not configured.")

        hostname = self.school_hostname(slug)
        zone_id = str(self._settings.CLOUDFLARE_ZONE_ID)
        payload = self._record_payload(hostname)

        lookup = await self._request(
            "GET",
            f"/zones/{zone_id}/dns_records",
            params={"name": hostname, "type": "CNAME"},
        )
        records = lookup.get("result") or []
        if records:
            record_id = str(records[0]["id"])
            updated = await self._request(
                "PUT",
                f"/zones/{zone_id}/dns_records/{record_id}",
                json=payload,
            )
            return CloudflareDNSResult(
                hostname=hostname,
                record_id=str(updated["result"]["id"]),
                created=False,
            )

        created = await self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            json=payload,
        )
        return CloudflareDNSResult(
            hostname=hostname,
            record_id=str(created["result"]["id"]),
            created=True,
        )
