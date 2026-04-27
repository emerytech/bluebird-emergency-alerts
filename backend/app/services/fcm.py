from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import anyio
import firebase_admin
from firebase_admin import credentials, exceptions as firebase_exceptions, messaging

from app.core.config import Settings


@dataclass(frozen=True)
class FCMSendResult:
    token: str
    ok: bool
    status_code: Optional[int]
    reason: Optional[str]


class FCMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = logging.getLogger("bluebird.fcm")
        self._app: Optional[firebase_admin.App] = None

    async def start(self) -> None:
        if not self.is_configured():
            self._logger.info("FCM disabled: FCM_SERVICE_ACCOUNT_JSON not set")
            return
        await anyio.to_thread.run_sync(self._start_sync)

    def _start_sync(self) -> None:
        if self._app is not None:
            return
        cred_path = self._settings.FCM_SERVICE_ACCOUNT_JSON
        if not cred_path:
            return
        cred = credentials.Certificate(cred_path)
        self._app = firebase_admin.initialize_app(cred, name="bluebird-fcm")
        self._logger.info("FCM initialized")

    async def stop(self) -> None:
        if self._app is None:
            return
        await anyio.to_thread.run_sync(self._stop_sync)

    def _stop_sync(self) -> None:
        if self._app is None:
            return
        firebase_admin.delete_app(self._app)
        self._app = None

    def is_configured(self) -> bool:
        return self._settings.fcm_is_configured()

    async def send_bulk(self, tokens: List[str], message: str, extra_data: Optional[dict] = None) -> List[FCMSendResult]:
        if not tokens:
            return []
        if not self._app:
            return [FCMSendResult(token=t, ok=False, status_code=None, reason="fcm_not_configured") for t in tokens]
        return await anyio.to_thread.run_sync(self._send_bulk_sync, tokens, message, extra_data or {})

    async def send_with_data(
        self,
        tokens: List[str],
        title: str,
        body: str,
        extra_data: Optional[dict] = None,
    ) -> List[FCMSendResult]:
        if not tokens:
            return []
        if not self._app:
            return [FCMSendResult(token=t, ok=False, status_code=None, reason="fcm_not_configured") for t in tokens]
        return await anyio.to_thread.run_sync(
            self._send_with_data_sync, tokens, title, body, extra_data or {}
        )

    def _send_with_data_sync(
        self,
        tokens: List[str],
        title: str,
        body: str,
        extra_data: dict,
    ) -> List[FCMSendResult]:
        assert self._app is not None
        data: dict = {
            "title": title,
            "body": body,
            "message": body,
            "channel_id": "bluebird_alerts",
        }
        data.update({str(k): str(v) for k, v in extra_data.items()})
        messages = [
            messaging.Message(
                token=token,
                data=data,
                android=messaging.AndroidConfig(priority="high"),
            )
            for token in tokens
        ]
        try:
            batch = messaging.send_each(messages, app=self._app)
        except firebase_exceptions.FirebaseError as exc:
            self._logger.exception("FCM send_with_data batch failed")
            return [
                FCMSendResult(token=token, ok=False, status_code=None, reason=str(exc))
                for token in tokens
            ]
        results: List[FCMSendResult] = []
        for token, response in zip(tokens, batch.responses):
            if response.success:
                results.append(FCMSendResult(token=token, ok=True, status_code=200, reason=None))
                continue
            exc = response.exception
            results.append(
                FCMSendResult(
                    token=token,
                    ok=False,
                    status_code=getattr(exc, "http_response", None).status_code if getattr(exc, "http_response", None) else None,
                    reason=str(exc) if exc else "fcm_send_failed",
                )
            )
        return results

    def _send_bulk_sync(self, tokens: List[str], message: str, extra_data: dict = {}) -> List[FCMSendResult]:
        assert self._app is not None
        data: dict = {
            "title": "BlueBird Alert",
            "body": message,
            "message": message,
            "sound": "bluebird_alarm",
            "channel_id": "bluebird_alerts",
            "full_screen": "1",
            "open_alarm": "1",
            "category": "alarm",
        }
        data.update({str(k): str(v) for k, v in extra_data.items()})
        messages = [
            messaging.Message(
                token=token,
                data=data,
                android=messaging.AndroidConfig(
                    priority="high",
                ),
            )
            for token in tokens
        ]
        try:
            batch = messaging.send_each(messages, app=self._app)
        except firebase_exceptions.FirebaseError as exc:
            self._logger.exception("FCM batch send failed")
            return [
                FCMSendResult(
                    token=token,
                    ok=False,
                    status_code=None,
                    reason=str(exc),
                )
                for token in tokens
            ]

        results: List[FCMSendResult] = []
        for token, response in zip(tokens, batch.responses):
            if response.success:
                results.append(FCMSendResult(token=token, ok=True, status_code=200, reason=None))
                continue
            exc = response.exception
            results.append(
                FCMSendResult(
                    token=token,
                    ok=False,
                    status_code=getattr(exc, "http_response", None).status_code if getattr(exc, "http_response", None) else None,
                    reason=str(exc) if exc else "fcm_send_failed",
                )
            )
        return results
