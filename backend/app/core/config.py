from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized configuration via environment variables.

    For local development:
      - copy `.env.example` to `.env`
      - fill in APNs values
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Optional shared-secret API key. If set, write endpoints require `X-API-Key`.
    API_KEY: Optional[str] = None
    SESSION_SECRET: str = "bluebird-local-dev-session-secret"

    # SQLite (used for alert logging)
    DB_PATH: str = "./data/bluebird.db"
    PLATFORM_DB_PATH: str = "./data/platform.db"
    BASE_DOMAIN: str = "bluebird.ets3d.com"
    DEFAULT_SCHOOL_SLUG: str = "default"
    DEFAULT_SCHOOL_NAME: str = "Default School"

    SUPERADMIN_USERNAME: str = "superadmin"
    SUPERADMIN_PASSWORD: str = "change-me-now"

    # APNs
    APNS_USE_SANDBOX: bool = True
    APNS_TEAM_ID: Optional[str] = None
    APNS_KEY_ID: Optional[str] = None
    APNS_P8_PATH: Optional[str] = None
    APNS_BUNDLE_ID: Optional[str] = None

    # Reliability tuning
    APNS_TIMEOUT_SECONDS: float = 10.0
    APNS_CONCURRENCY: int = 50
    APNS_MAX_RETRIES: int = 2

    # SMS (Twilio)
    SMS_ENABLED: bool = False
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_FROM_NUMBER: Optional[str] = None
    TWILIO_TIMEOUT_SECONDS: float = 5.0
    TWILIO_CONCURRENCY: int = 20

    # Firebase Cloud Messaging (Android)
    FCM_SERVICE_ACCOUNT_JSON: Optional[str] = None

    # Server management
    SERVER_RESTART_COMMAND: Optional[str] = None

    @property
    def apns_host(self) -> str:
        return "api.sandbox.push.apple.com" if self.APNS_USE_SANDBOX else "api.push.apple.com"

    def apns_is_configured(self) -> bool:
        return all(
            [
                self.APNS_TEAM_ID,
                self.APNS_KEY_ID,
                self.APNS_P8_PATH,
                self.APNS_BUNDLE_ID,
            ]
        )

    def twilio_is_configured(self) -> bool:
        # SMS can be disabled explicitly for environments without Twilio.
        if not self.SMS_ENABLED:
            return False
        return all([self.TWILIO_ACCOUNT_SID, self.TWILIO_AUTH_TOKEN, self.TWILIO_FROM_NUMBER])

    def fcm_is_configured(self) -> bool:
        return bool(self.FCM_SERVICE_ACCOUNT_JSON)
