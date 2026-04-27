from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass
from typing import List, Optional

import httpx
import jwt

from app.core.config import Settings


@dataclass(frozen=True)
class APNsSendResult:
    token: str
    ok: bool
    status_code: Optional[int] = None
    reason: Optional[str] = None


class APNsClient:
    """
    APNs HTTP/2 client using token-based auth (.p8).

    Apple docs (conceptually):
      - Create a JWT signed with ES256 using your .p8 private key.
      - POST to /3/device/<token> with `authorization: bearer <jwt>` and `apns-topic`.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = logging.getLogger("bluebird.apns")
        self._client: Optional[httpx.AsyncClient] = None

        self._p8_private_key: Optional[str] = None
        self._jwt_cached: Optional[str] = None
        self._jwt_cached_at: Optional[float] = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(self._settings.APNS_TIMEOUT_SECONDS),
        )

        if not self._settings.apns_is_configured():
            self._logger.warning("APNs not configured; pushes will fail until env vars are set.")
            return

        p8_path = self._settings.APNS_P8_PATH or ""
        try:
            with open(p8_path, "r", encoding="utf-8") as f:
                self._p8_private_key = f.read()
        except OSError as e:
            self._logger.error("Failed to read APNS_P8_PATH=%s (%s)", p8_path, e)
            self._p8_private_key = None

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def is_configured(self) -> bool:
        return self._settings.apns_is_configured() and bool(self._p8_private_key)

    def _get_or_create_jwt(self) -> str:
        """
        Apple recommends reusing the same JWT for up to 60 minutes.
        We refresh a bit early (50 minutes) to avoid edge cases.
        """

        now = time.time()
        if self._jwt_cached and self._jwt_cached_at and (now - self._jwt_cached_at) < (50 * 60):
            return self._jwt_cached

        if not self._p8_private_key:
            raise RuntimeError("APNs private key not loaded")
        if not self._settings.APNS_TEAM_ID or not self._settings.APNS_KEY_ID:
            raise RuntimeError("APNs TEAM_ID / KEY_ID not configured")

        headers = {"alg": "ES256", "kid": self._settings.APNS_KEY_ID}
        payload = {"iss": self._settings.APNS_TEAM_ID, "iat": int(now)}

        token = jwt.encode(payload, self._p8_private_key, algorithm="ES256", headers=headers)
        self._jwt_cached = token
        self._jwt_cached_at = now
        return token

    async def send_bulk(self, tokens: List[str], message: str, extra_data: Optional[dict] = None) -> List[APNsSendResult]:
        if not tokens:
            return []

        if not self.is_configured():
            return [APNsSendResult(token=t, ok=False, reason="apns_not_configured") for t in tokens]

        sem = asyncio.Semaphore(max(1, int(self._settings.APNS_CONCURRENCY)))

        async def _guarded_send(t: str) -> APNsSendResult:
            async with sem:
                return await self._send_one_with_retries(t, message, extra_data)

        return await asyncio.gather(*(_guarded_send(t) for t in tokens))

    async def _send_one_with_retries(self, token: str, message: str, extra_data: Optional[dict] = None) -> APNsSendResult:
        max_retries = max(0, int(self._settings.APNS_MAX_RETRIES))
        last_error: Optional[APNsSendResult] = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                # Exponential backoff with small jitter.
                delay = (2 ** (attempt - 1)) * 0.4 + random.random() * 0.2
                await asyncio.sleep(delay)

            try:
                result = await self._send_one(token, message, extra_data)
                if result.ok:
                    return result

                # Retry on transient APNs/server responses.
                if result.status_code in (429, 500, 502, 503, 504):
                    last_error = result
                    continue

                return result
            except (httpx.HTTPError, RuntimeError) as e:
                last_error = APNsSendResult(token=token, ok=False, reason=str(e))

        return last_error or APNsSendResult(token=token, ok=False, reason="unknown_error")

    async def send_with_data(
        self,
        tokens: List[str],
        title: str,
        body: str,
        extra_data: Optional[dict] = None,
    ) -> List[APNsSendResult]:
        if not tokens:
            return []
        if not self.is_configured():
            return [APNsSendResult(token=t, ok=False, reason="apns_not_configured") for t in tokens]
        sem = asyncio.Semaphore(max(1, int(self._settings.APNS_CONCURRENCY)))

        async def _guarded(t: str) -> APNsSendResult:
            async with sem:
                return await self._send_one_custom(t, title, body, extra_data)

        return list(await asyncio.gather(*(_guarded(t) for t in tokens)))

    async def _send_one_custom(
        self,
        token: str,
        title: str,
        body: str,
        extra_data: Optional[dict] = None,
    ) -> APNsSendResult:
        if not self._client:
            raise RuntimeError("APNs client not started")
        jwt_token = self._get_or_create_jwt()
        url = f"https://{self._settings.apns_host}/3/device/{token}"
        headers = {
            "authorization": f"bearer {jwt_token}",
            "apns-topic": self._settings.APNS_BUNDLE_ID or "",
            "apns-push-type": "alert",
            "apns-priority": "10",
        }
        payload: dict = {
            "aps": {
                "alert": {"title": title, "body": body},
                "sound": "default",
                "badge": 1,
            }
        }
        if extra_data:
            payload.update(extra_data)
        resp = await self._client.post(url, headers=headers, json=payload)
        if resp.status_code == 200:
            return APNsSendResult(token=token, ok=True, status_code=200)
        reason = None
        try:
            data = resp.json()
            reason = data.get("reason")
        except json.JSONDecodeError:
            reason = resp.text[:200] if resp.text else None
        self._logger.warning("APNs custom failed token=%s status=%s reason=%s", token[-8:], resp.status_code, reason)
        return APNsSendResult(token=token, ok=False, status_code=resp.status_code, reason=reason)

    async def _send_one(self, token: str, message: str, extra_data: Optional[dict] = None) -> APNsSendResult:
        if not self._client:
            raise RuntimeError("APNs client not started")

        jwt_token = self._get_or_create_jwt()

        url = f"https://{self._settings.apns_host}/3/device/{token}"
        headers = {
            "authorization": f"bearer {jwt_token}",
            "apns-topic": self._settings.APNS_BUNDLE_ID or "",
            "apns-push-type": "alert",
            "apns-priority": "10",
        }

        payload: dict = {
            "aps": {
                "alert": {"title": "BlueBird Alert", "body": message},
                "sound": "bluebird_alarm.caf",
                "badge": 1,
                "interruption-level": "time-sensitive",
            }
        }
        if extra_data:
            payload.update({str(k): str(v) for k, v in extra_data.items()})

        resp = await self._client.post(url, headers=headers, json=payload)
        if resp.status_code == 200:
            return APNsSendResult(token=token, ok=True, status_code=200)

        reason = None
        try:
            data = resp.json()
            reason = data.get("reason")
        except json.JSONDecodeError:
            reason = resp.text[:200] if resp.text else None

        self._logger.warning("APNs failed token=%s status=%s reason=%s", token[-8:], resp.status_code, reason)
        return APNsSendResult(token=token, ok=False, status_code=resp.status_code, reason=reason)
