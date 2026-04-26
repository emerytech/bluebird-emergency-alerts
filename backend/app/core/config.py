from __future__ import annotations

from typing import List, Optional

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

    SUPERADMIN_USERNAME: str = "temery"
    SUPERADMIN_PASSWORD: str = "Password@123"

    # Cloudflare DNS automation
    CLOUDFLARE_API_TOKEN: Optional[str] = None
    CLOUDFLARE_ZONE_ID: Optional[str] = None
    CLOUDFLARE_DNS_BASE_HOSTNAME: Optional[str] = None
    CLOUDFLARE_TUNNEL_CNAME_TARGET: Optional[str] = None
    CLOUDFLARE_DNS_PROXIED: bool = True

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
    SERVER_GIT_PULL_COMMAND: Optional[str] = None

    # SMTP (admin communication — separate from alert delivery)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True

    # Platform admin contacts (comma-separated emails for health alerts)
    PLATFORM_ADMIN_EMAILS: str = ""

    # Background health monitor
    HEALTH_CHECK_INTERVAL: int = 60
    HEALTH_EMAIL_COOLDOWN_MINUTES: int = 30

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

    def smtp_is_configured(self) -> bool:
        return bool(self.SMTP_HOST and self.SMTP_FROM)

    @property
    def platform_admin_email_list(self) -> List[str]:
        return [e.strip() for e in self.PLATFORM_ADMIN_EMAILS.split(",") if e.strip()]

    def cloudflare_dns_is_configured(self) -> bool:
        return all(
            [
                self.CLOUDFLARE_API_TOKEN,
                self.CLOUDFLARE_ZONE_ID,
                self.CLOUDFLARE_TUNNEL_CNAME_TARGET,
            ]
        )

    @property
    def cloudflare_dns_base_hostname(self) -> str:
        return (self.CLOUDFLARE_DNS_BASE_HOSTNAME or self.BASE_DOMAIN).strip().lower()
