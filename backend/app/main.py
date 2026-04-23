from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import router
from app.core.config import Settings
from app.core.logging import configure_logging
from app.services.alert_broadcaster import AlertBroadcaster
from app.services.apns import APNsClient
from app.services.alert_log import AlertLog
from app.services.alarm_store import AlarmStore
from app.services.device_registry import DeviceRegistry
from app.services.fcm import FCMClient
from app.services.twilio_sms import TwilioSMSClient
from app.services.user_store import UserStore


settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.started_at = datetime.now(timezone.utc)

    # Load environment/config first so logging uses the intended level.
    configure_logging(settings.LOG_LEVEL)

    # Core services (simple + explicit for reliability).
    device_registry = DeviceRegistry(settings.DB_PATH)
    alert_log = AlertLog(settings.DB_PATH)
    alarm_store = AlarmStore(settings.DB_PATH)
    apns_client = APNsClient(settings)
    await apns_client.start()
    fcm_client = FCMClient(settings)
    await fcm_client.start()
    user_store = UserStore(settings.DB_PATH)
    twilio_sms = TwilioSMSClient(settings)
    await twilio_sms.start()
    broadcaster = AlertBroadcaster(apns=apns_client, fcm=fcm_client, twilio=twilio_sms, alert_log=alert_log)

    app.state.settings = settings
    app.state.device_registry = device_registry
    app.state.alert_log = alert_log
    app.state.alarm_store = alarm_store
    app.state.apns_client = apns_client
    app.state.fcm_client = fcm_client
    app.state.user_store = user_store
    app.state.twilio_sms = twilio_sms
    app.state.broadcaster = broadcaster

    yield

    await apns_client.stop()
    await fcm_client.stop()
    await twilio_sms.stop()


app = FastAPI(
    title="BlueBird Alerts API",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET, same_site="lax", https_only=False)
app.include_router(router)
