from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

from app.services.alert_log import AlertLog
from app.services.apns import APNsClient
from app.services.device_registry import DeviceRegistry
from app.services.fcm import FCMClient
from app.services.twilio_sms import TwilioSMSClient

_APNS_INVALID_REASONS = {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"}
_FCM_INVALID_ERRORS = {"registration-token-not-registered", "invalid-registration-token"}


@dataclass(frozen=True)
class BroadcastPlan:
    apns_tokens: List[str]
    fcm_tokens: List[str]
    sms_numbers: List[str]
    tenant_slug: str = ""
    triggered_by_user_id: Optional[int] = None
    silent_for_sender: bool = True


class AlertBroadcaster:
    """
    Broadcasts an alert across multiple channels and records delivery attempts.

    Safety-critical note:
      - The panic request handler should *not* block on external providers.
      - This class is designed to be run as a background task.
    """

    def __init__(self, *, apns: APNsClient, fcm: FCMClient, twilio: TwilioSMSClient, alert_log: AlertLog, registry: Optional[DeviceRegistry] = None) -> None:
        self._apns = apns
        self._fcm = fcm
        self._twilio = twilio
        self._alert_log = alert_log
        self._registry = registry
        self._logger = logging.getLogger("bluebird.broadcast")

    def twilio_configured(self) -> bool:
        return self._twilio.is_configured()

    def fcm_configured(self) -> bool:
        return self._fcm.is_configured()

    async def broadcast_panic(self, *, alert_id: int, message: str, plan: BroadcastPlan) -> None:
        """
        Sends APNs + FCM + SMS concurrently and logs per-target delivery outcomes.
        """
        self._logger.info(
            "broadcast_panic tenant=%s alert_id=%s apns=%d fcm=%d sms=%d",
            plan.tenant_slug, alert_id,
            len(plan.apns_tokens), len(plan.fcm_tokens), len(plan.sms_numbers),
        )
        sender_extra: Optional[dict] = None
        if plan.triggered_by_user_id is not None:
            sender_extra = {
                "triggered_by_user_id": str(plan.triggered_by_user_id),
                "silent_for_sender": "1" if plan.silent_for_sender else "0",
            }
        apns_task = asyncio.create_task(
            self._send_apns(alert_id=alert_id, message=message, tokens=plan.apns_tokens, tenant_slug=plan.tenant_slug, extra_data=sender_extra)
        )
        fcm_task = asyncio.create_task(
            self._send_fcm(alert_id=alert_id, message=message, tokens=plan.fcm_tokens, tenant_slug=plan.tenant_slug, extra_data=sender_extra)
        )
        sms_task = asyncio.create_task(
            self._send_sms(alert_id=alert_id, message=message, numbers=plan.sms_numbers, tenant_slug=plan.tenant_slug)
        )
        await asyncio.gather(apns_task, fcm_task, sms_task)

    async def _send_apns(self, *, alert_id: int, message: str, tokens: List[str], tenant_slug: str = "", extra_data: Optional[dict] = None) -> None:
        if not tokens:
            return

        results = await self._apns.send_bulk(tokens, message, extra_data=extra_data)
        for r in results:
            await self._alert_log.log_delivery(
                alert_id=alert_id,
                channel="push",
                provider="apns",
                target=r.token[-8:],  # avoid storing full token in audit log
                ok=r.ok,
                status_code=r.status_code,
                error=r.reason,
            )
            if not r.ok and r.reason in _APNS_INVALID_REASONS and self._registry is not None:
                await self._registry.mark_invalid(r.token, "apns")

        succeeded = sum(1 for r in results if r.ok)
        failed = len(results) - succeeded
        self._logger.info(
            "APNs delivered tenant=%s alert_id=%s ok=%s failed=%s", tenant_slug, alert_id, succeeded, failed
        )

    async def _send_fcm(self, *, alert_id: int, message: str, tokens: List[str], tenant_slug: str = "", extra_data: Optional[dict] = None) -> None:
        if not tokens:
            return

        results = await self._fcm.send_bulk(tokens, message, extra_data=extra_data)
        for r in results:
            await self._alert_log.log_delivery(
                alert_id=alert_id,
                channel="push",
                provider="fcm",
                target=r.token[-8:],
                ok=r.ok,
                status_code=r.status_code,
                error=r.reason,
            )
            if not r.ok and r.reason in _FCM_INVALID_ERRORS and self._registry is not None:
                await self._registry.mark_invalid(r.token, "fcm")

        succeeded = sum(1 for r in results if r.ok)
        failed = len(results) - succeeded
        self._logger.info(
            "FCM delivered tenant=%s alert_id=%s ok=%s failed=%s", tenant_slug, alert_id, succeeded, failed
        )

    async def _send_sms(self, *, alert_id: int, message: str, numbers: List[str], tenant_slug: str = "") -> None:
        if not numbers:
            return

        results = await self._twilio.send_bulk(to_numbers=numbers, body=message)
        for r in results:
            suffix = r.to[-4:] if len(r.to) >= 4 else r.to
            await self._alert_log.log_delivery(
                alert_id=alert_id,
                channel="sms",
                provider="twilio",
                target=f"***{suffix}",
                ok=r.ok,
                status_code=r.status_code,
                error=r.error,
            )

        succeeded = sum(1 for r in results if r.ok)
        failed = len(results) - succeeded
        self._logger.info(
            "SMS delivered tenant=%s alert_id=%s ok=%s failed=%s", tenant_slug, alert_id, succeeded, failed
        )
