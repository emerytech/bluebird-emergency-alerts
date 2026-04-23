from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request

from app.models.schemas import (
    AlertsResponse,
    AlertSummary,
    DevicesResponse,
    DeviceSummary,
    PanicRequest,
    PanicResponse,
    RegisterDeviceRequest,
    RegisterDeviceResponse,
)
from app.services.apns import APNsClient
from app.services.alert_log import AlertLog
from app.services.device_registry import DeviceRegistry


router = APIRouter()
logger = logging.getLogger("bluebird.routes")


def _registry(req: Request) -> DeviceRegistry:
    return req.app.state.device_registry  # type: ignore[attr-defined]


def _apns(req: Request) -> APNsClient:
    return req.app.state.apns_client  # type: ignore[attr-defined]


def _alert_log(req: Request) -> AlertLog:
    return req.app.state.alert_log  # type: ignore[attr-defined]


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/devices", response_model=DevicesResponse)
async def devices(request: Request) -> DevicesResponse:
    registry = _registry(request)
    all_devices = await registry.list_devices()
    platform_counts = await registry.platform_counts()
    provider_counts = await registry.provider_counts()

    return DevicesResponse(
        device_count=len(all_devices),
        platform_counts=platform_counts,
        provider_counts=provider_counts,
        devices=[
            DeviceSummary(
                platform=device.platform,
                push_provider=device.push_provider,
                token_suffix=device.token[-8:],
            )
            for device in all_devices
        ],
    )


@router.get("/alerts", response_model=AlertsResponse)
async def alerts(request: Request, limit: int = Query(default=10, ge=1, le=100)) -> AlertsResponse:
    recent_alerts = _alert_log(request).list_recent(limit=limit)
    return AlertsResponse(
        alerts=[
            AlertSummary(
                alert_id=alert.id,
                created_at=alert.created_at,
                message=alert.message,
            )
            for alert in recent_alerts
        ]
    )


@router.post("/register-device", response_model=RegisterDeviceResponse)
async def register_device(body: RegisterDeviceRequest, request: Request) -> RegisterDeviceResponse:
    """
    Registers a device token for future push notifications.
    """

    registered = await _registry(request).register(
        token=body.device_token,
        platform=body.platform.value,
        push_provider=body.push_provider.value,
    )
    device_count = await _registry(request).count()
    platform_counts = await _registry(request).platform_counts()
    provider_counts = await _registry(request).provider_counts()
    logger.info(
        "Device registered=%s platform=%s provider=%s count=%s token_suffix=%s",
        registered,
        body.platform.value,
        body.push_provider.value,
        device_count,
        body.device_token[-8:],
    )
    return RegisterDeviceResponse(
        registered=registered,
        device_count=device_count,
        platform_counts=platform_counts,
        provider_counts=provider_counts,
    )


@router.post("/panic", response_model=PanicResponse)
async def panic(body: PanicRequest, request: Request) -> PanicResponse:
    """
    Broadcasts an emergency alert to all registered devices (push notifications only).
    """

    alert_id = _alert_log(request).log_alert(body.message)
    apns_devices = await _registry(request).list_by_provider("apns")
    provider_counts = await _registry(request).provider_counts()
    device_count = await _registry(request).count()
    apns_tokens = [device.token for device in apns_devices]

    logger.warning(
        "PANIC alert_id=%s devices=%s providers=%s message=%r",
        alert_id,
        device_count,
        provider_counts,
        body.message,
    )

    results = await _apns(request).send_bulk(apns_tokens, body.message)
    succeeded = sum(1 for r in results if r.ok)
    failed = len(results) - succeeded

    return PanicResponse(
        alert_id=alert_id,
        device_count=device_count,
        attempted=len(results),
        succeeded=succeeded,
        failed=failed,
        apns_configured=_apns(request).is_configured(),
        provider_attempts={"apns": len(results), "fcm": 0},
    )
