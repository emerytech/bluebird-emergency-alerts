from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import Settings
from app.core.logging import configure_logging
from app.services.apns import APNsClient
from app.services.alert_log import AlertLog
from app.services.device_registry import DeviceRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load environment/config first so logging uses the intended level.
    settings = Settings()
    configure_logging(settings.LOG_LEVEL)

    # Core services (simple + explicit for reliability).
    device_registry = DeviceRegistry(settings.DB_PATH)
    alert_log = AlertLog(settings.DB_PATH)
    apns_client = APNsClient(settings)
    await apns_client.start()

    app.state.settings = settings
    app.state.device_registry = device_registry
    app.state.alert_log = alert_log
    app.state.apns_client = apns_client

    yield

    await apns_client.stop()


app = FastAPI(
    title="BlueBird Alerts API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
