from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx

from app.core.config import Settings


@dataclass(frozen=True)
class SMSSendResult:
    to: str
    ok: bool
    status_code: Optional[int] = None
    message_sid: Optional[str] = None
    error: Optional[str] = None


class TwilioSMSClient:
    """
    Minimal Twilio SMS sender using Twilio's REST API.

    We implement this with `httpx` to keep dependencies small and behavior explicit.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = logging.getLogger("bluebird.twilio")
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        # Twilio is optional. If not configured, we still start the client so calls can return quickly.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._settings.TWILIO_TIMEOUT_SECONDS),
        )

        if self._settings.SMS_ENABLED and not self.is_configured():
            self._logger.warning("SMS_ENABLED=true but Twilio env vars are incomplete; SMS will be skipped.")

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def is_configured(self) -> bool:
        return self._settings.twilio_is_configured()

    async def send_bulk(self, *, to_numbers: List[str], body: str) -> List[SMSSendResult]:
        if not to_numbers:
            return []

        if not self.is_configured():
            return [SMSSendResult(to=n, ok=False, error="twilio_not_configured") for n in to_numbers]

        sem = asyncio.Semaphore(max(1, int(self._settings.TWILIO_CONCURRENCY)))

        async def _guarded_send(to_number: str) -> SMSSendResult:
            async with sem:
                return await self._send_one(to=to_number, body=body)

        return await asyncio.gather(*(_guarded_send(n) for n in to_numbers))

    async def _send_one(self, *, to: str, body: str) -> SMSSendResult:
        if not self._client:
            raise RuntimeError("Twilio client not started")

        account_sid = self._settings.TWILIO_ACCOUNT_SID or ""
        auth_token = self._settings.TWILIO_AUTH_TOKEN or ""
        from_number = self._settings.TWILIO_FROM_NUMBER or ""

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        data = {
            "From": from_number,
            "To": to,
            "Body": body,
        }

        try:
            resp = await self._client.post(url, data=data, auth=(account_sid, auth_token))
        except httpx.HTTPError as e:
            return SMSSendResult(to=to, ok=False, error=str(e))

        if 200 <= resp.status_code < 300:
            # Response is JSON with fields like "sid"; we avoid depending on full schema.
            sid = None
            try:
                sid = (resp.json() or {}).get("sid")
            except ValueError:
                sid = None
            return SMSSendResult(to=to, ok=True, status_code=resp.status_code, message_sid=sid)

        # Twilio returns JSON with a "message" field.
        err = None
        try:
            err = (resp.json() or {}).get("message")
        except ValueError:
            err = resp.text[:200] if resp.text else None

        suffix = to[-4:] if len(to) >= 4 else to
        self._logger.warning("Twilio SMS failed to=***%s status=%s error=%s", suffix, resp.status_code, err)
        return SMSSendResult(to=to, ok=False, status_code=resp.status_code, error=err)

