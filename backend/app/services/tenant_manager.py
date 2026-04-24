from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

from app.core.config import Settings
from app.services.alert_broadcaster import AlertBroadcaster
from app.services.alarm_store import AlarmStore
from app.services.alert_log import AlertLog
from app.services.device_registry import DeviceRegistry
from app.services.fcm import FCMClient
from app.services.quiet_period_store import QuietPeriodStore
from app.services.report_store import ReportStore
from app.services.school_registry import SchoolRecord, SchoolRegistry
from app.services.twilio_sms import TwilioSMSClient
from app.services.apns import APNsClient
from app.services.user_store import UserStore


_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def normalize_school_slug(value: str) -> str:
    cleaned = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return cleaned or "default"


def resolve_school_slug(host: str, settings: Settings) -> str:
    hostname = (host or "").split(":", 1)[0].strip().lower()
    if not hostname or hostname in {"localhost", "127.0.0.1"}:
        return settings.DEFAULT_SCHOOL_SLUG
    if hostname.replace(".", "").isdigit():
        return settings.DEFAULT_SCHOOL_SLUG

    base_domain = settings.BASE_DOMAIN.strip().lower()
    if base_domain and hostname == base_domain:
        return settings.DEFAULT_SCHOOL_SLUG
    if base_domain and hostname.endswith(f".{base_domain}"):
        prefix = hostname[: -(len(base_domain) + 1)]
        return normalize_school_slug(prefix)

    return settings.DEFAULT_SCHOOL_SLUG


@dataclass(frozen=True)
class TenantContext:
    school: SchoolRecord
    slug: str
    db_path: str
    device_registry: DeviceRegistry
    alert_log: AlertLog
    alarm_store: AlarmStore
    report_store: ReportStore
    quiet_period_store: QuietPeriodStore
    user_store: UserStore
    broadcaster: AlertBroadcaster


class TenantManager:
    def __init__(
        self,
        *,
        settings: Settings,
        school_registry: SchoolRegistry,
        apns: APNsClient,
        fcm: FCMClient,
        twilio: TwilioSMSClient,
    ) -> None:
        self._settings = settings
        self._school_registry = school_registry
        self._apns = apns
        self._fcm = fcm
        self._twilio = twilio
        self._lock = threading.Lock()
        self._cache: dict[str, TenantContext] = {}

    def db_path_for_slug(self, slug: str) -> str:
        normalized = normalize_school_slug(slug)
        if normalized == normalize_school_slug(self._settings.DEFAULT_SCHOOL_SLUG):
            return self._settings.DB_PATH

        default_abs = os.path.abspath(self._settings.DB_PATH)
        data_dir = os.path.dirname(default_abs)
        schools_dir = os.path.join(data_dir, "schools")
        os.makedirs(schools_dir, exist_ok=True)
        return os.path.join(schools_dir, f"{normalized}.db")

    def school_for_host(self, host: str) -> SchoolRecord | None:
        slug = resolve_school_slug(host, self._settings)
        school = self._school_registry._get_by_slug_sync(slug)
        if school is not None and school.is_active:
            return school
        if slug == normalize_school_slug(self._settings.DEFAULT_SCHOOL_SLUG):
            return self._school_registry._ensure_school_sync(
                slug=slug,
                name=self._settings.DEFAULT_SCHOOL_NAME,
            )
        return None

    def get(self, school: SchoolRecord) -> TenantContext:
        normalized = normalize_school_slug(school.slug)
        with self._lock:
            cached = self._cache.get(normalized)
            if cached is not None:
                return cached

            db_path = self.db_path_for_slug(normalized)
            alert_log = AlertLog(db_path)
            tenant = TenantContext(
                school=school,
                slug=normalized,
                db_path=db_path,
                device_registry=DeviceRegistry(db_path),
                alert_log=alert_log,
                alarm_store=AlarmStore(db_path),
                report_store=ReportStore(db_path),
                quiet_period_store=QuietPeriodStore(db_path),
                user_store=UserStore(db_path),
                broadcaster=AlertBroadcaster(
                    apns=self._apns,
                    fcm=self._fcm,
                    twilio=self._twilio,
                    alert_log=alert_log,
                ),
            )
            self._cache[normalized] = tenant
            return tenant
