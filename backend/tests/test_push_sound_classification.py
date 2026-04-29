"""
Phase 3 tests — Push notification sound classification system.

Tests cover:
1.  classify_alert_type: emergency → critical
2.  classify_alert_type: unknown/missing type → critical (safe default)
3.  classify_alert_type: quiet_period_update → non_critical
4.  classify_alert_type: admin_message → non_critical
5.  classify_alert_type: onboarding → non_critical
6.  classify_alert_type: help_request → help_request
7.  SoundConfig.default() values are safe
8.  SoundConfig.from_notification_settings() reads fields correctly
9.  APNs critical → bluebird_alarm.caf, time-sensitive, priority 10
10. APNs non_critical (enabled) → notification_soft.caf, active, priority 5
11. APNs non_critical (disabled) → "default", active, priority 5
12. APNs help_request → help_request_alert.caf, time-sensitive, priority 10
13. FCM critical → bluebird_alerts channel, bluebird_alarm sound, full_screen flag
14. FCM non_critical (enabled) → non_critical_notifications channel, notification_soft sound
15. FCM non_critical (disabled) → non_critical_notifications channel, no sound field
16. FCM help_request → bluebird_alerts channel, bluebird_alarm sound
17. APNs _send_one uses named non-critical sound (not "default")
18. FCM _send_bulk_sync does NOT inject bluebird_alarm for non-critical events
19. FCM _send_bulk_sync DOES inject bluebird_alarm for emergency
20. FCM _send_with_data_sync uses correct channel per event type
21. Disabling non-critical sound does not affect emergency behavior
22. SoundConfig from_notification_settings: disabled setting propagates
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.push_classification import (
    NON_CRITICAL_TYPES,
    SoundConfig,
    classify_alert_type,
    is_critical,
    is_non_critical,
)


# ---------------------------------------------------------------------------
# classify_alert_type tests
# ---------------------------------------------------------------------------

def test_classify_emergency_is_critical():
    assert classify_alert_type({"type": "emergency"}) == "critical"


def test_classify_missing_type_is_critical():
    assert classify_alert_type({}) == "critical"
    assert classify_alert_type(None) == "critical"


def test_classify_unknown_type_is_critical():
    assert classify_alert_type({"type": "totally_unknown"}) == "critical"


def test_classify_quiet_period_update_is_non_critical():
    assert classify_alert_type({"type": "quiet_period_update"}) == "non_critical"


def test_classify_admin_message_is_non_critical():
    assert classify_alert_type({"type": "admin_message"}) == "non_critical"


def test_classify_onboarding_is_non_critical():
    assert classify_alert_type({"type": "onboarding"}) == "non_critical"


def test_classify_quiet_request_is_non_critical():
    assert classify_alert_type({"type": "quiet_request"}) == "non_critical"


def test_classify_access_code_is_non_critical():
    assert classify_alert_type({"type": "access_code"}) == "non_critical"


def test_classify_help_request_is_help_request():
    assert classify_alert_type({"type": "help_request"}) == "help_request"


def test_is_critical_and_is_non_critical_helpers():
    assert is_critical({"type": "emergency"}) is True
    assert is_critical({"type": "quiet_period_update"}) is False
    assert is_non_critical({"type": "quiet_period_update"}) is True
    assert is_non_critical({"type": "emergency"}) is False


def test_all_non_critical_types_classified_correctly():
    for t in NON_CRITICAL_TYPES:
        assert classify_alert_type({"type": t}) == "non_critical", f"Expected non_critical for type={t}"


# ---------------------------------------------------------------------------
# SoundConfig tests
# ---------------------------------------------------------------------------

def test_sound_config_default_values():
    cfg = SoundConfig.default()
    assert cfg.non_critical_sound_enabled is True
    assert cfg.non_critical_sound_name == "notification_soft"


def test_sound_config_from_notification_settings():
    mock_settings = MagicMock()
    mock_settings.non_critical_sound_enabled = False
    mock_settings.non_critical_sound_name = "notification_soft"
    cfg = SoundConfig.from_notification_settings(mock_settings)
    assert cfg.non_critical_sound_enabled is False
    assert cfg.non_critical_sound_name == "notification_soft"


def test_sound_config_from_notification_settings_missing_attrs():
    cfg = SoundConfig.from_notification_settings(object())  # no attrs
    assert cfg.non_critical_sound_enabled is True  # safe default
    assert cfg.non_critical_sound_name == "notification_soft"


# ---------------------------------------------------------------------------
# SoundConfig APNs helper tests
# ---------------------------------------------------------------------------

def test_apns_sound_critical():
    cfg = SoundConfig.default()
    assert cfg.apns_sound("critical") == "bluebird_alarm.caf"
    assert cfg.apns_interruption_level("critical") == "time-sensitive"
    assert cfg.apns_priority("critical") == "10"


def test_apns_sound_non_critical_enabled():
    cfg = SoundConfig(non_critical_sound_enabled=True, non_critical_sound_name="notification_soft")
    assert cfg.apns_sound("non_critical") == "notification_soft.caf"
    assert cfg.apns_interruption_level("non_critical") == "active"
    assert cfg.apns_priority("non_critical") == "5"


def test_apns_sound_non_critical_disabled():
    cfg = SoundConfig(non_critical_sound_enabled=False)
    assert cfg.apns_sound("non_critical") == "default"
    assert cfg.apns_interruption_level("non_critical") == "active"
    assert cfg.apns_priority("non_critical") == "5"


def test_apns_sound_help_request():
    cfg = SoundConfig.default()
    assert cfg.apns_sound("help_request") == "help_request_alert.caf"
    assert cfg.apns_interruption_level("help_request") == "time-sensitive"
    assert cfg.apns_priority("help_request") == "10"


# ---------------------------------------------------------------------------
# SoundConfig FCM helper tests
# ---------------------------------------------------------------------------

def test_fcm_channel_critical():
    cfg = SoundConfig.default()
    assert cfg.fcm_channel_id("critical") == "bluebird_alerts"
    assert cfg.fcm_sound("critical") == "bluebird_alarm"


def test_fcm_channel_non_critical_enabled():
    cfg = SoundConfig(non_critical_sound_enabled=True, non_critical_sound_name="notification_soft")
    assert cfg.fcm_channel_id("non_critical") == "non_critical_notifications"
    assert cfg.fcm_sound("non_critical") == "notification_soft"


def test_fcm_channel_non_critical_disabled():
    cfg = SoundConfig(non_critical_sound_enabled=False)
    assert cfg.fcm_channel_id("non_critical") == "non_critical_notifications"
    assert cfg.fcm_sound("non_critical") is None  # no sound field → channel default


def test_fcm_channel_help_request():
    cfg = SoundConfig.default()
    assert cfg.fcm_channel_id("help_request") == "bluebird_alerts"
    assert cfg.fcm_sound("help_request") == "bluebird_alarm"


# ---------------------------------------------------------------------------
# APNs _send_one payload inspection (mock HTTP client)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_apns_send_one_non_critical_uses_named_sound():
    """_send_one for a non-critical type must use notification_soft.caf, not 'default'."""
    from app.services.apns import APNsClient
    from app.core.config import Settings

    settings = MagicMock(spec=Settings)
    settings.apns_host = "api.sandbox.push.apple.com"
    settings.APNS_BUNDLE_ID = "com.test.app"
    settings.APNS_TEAM_ID = "TEAMID1234"
    settings.APNS_KEY_ID = "KEYID12345"
    settings.APNS_TIMEOUT_SECONDS = 10.0
    settings.APNS_CONCURRENCY = 10
    settings.APNS_MAX_RETRIES = 0
    settings.apns_is_configured.return_value = True

    client = APNsClient(settings)
    client._p8_private_key = "fake_key"

    captured_payloads = []

    async def _fake_post(url, headers, json):
        captured_payloads.append(json)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    fake_http = MagicMock()
    fake_http.post = _fake_post
    client._client = fake_http

    with patch.object(client, "_get_or_create_jwt", return_value="fake.jwt.token"):
        cfg = SoundConfig(non_critical_sound_enabled=True, non_critical_sound_name="notification_soft")
        await client._send_one(
            "fake_token",
            "You have a notification",
            extra_data={"type": "quiet_period_update"},
            sound_config=cfg,
        )

    assert len(captured_payloads) == 1
    aps = captured_payloads[0]["aps"]
    assert aps["sound"] == "notification_soft.caf"
    assert aps["interruption-level"] == "active"


@pytest.mark.anyio
async def test_apns_send_one_critical_uses_alarm_sound():
    from app.services.apns import APNsClient
    from app.core.config import Settings

    settings = MagicMock(spec=Settings)
    settings.apns_host = "api.sandbox.push.apple.com"
    settings.APNS_BUNDLE_ID = "com.test.app"
    settings.APNS_TEAM_ID = "TEAMID1234"
    settings.APNS_KEY_ID = "KEYID12345"
    settings.APNS_TIMEOUT_SECONDS = 10.0
    settings.APNS_CONCURRENCY = 10
    settings.APNS_MAX_RETRIES = 0
    settings.apns_is_configured.return_value = True

    client = APNsClient(settings)
    client._p8_private_key = "fake_key"

    captured_payloads = []

    async def _fake_post(url, headers, json):
        captured_payloads.append(json)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    fake_http = MagicMock()
    fake_http.post = _fake_post
    client._client = fake_http

    with patch.object(client, "_get_or_create_jwt", return_value="fake.jwt.token"):
        await client._send_one(
            "fake_token",
            "LOCKDOWN",
            extra_data={"type": "emergency"},
        )

    assert len(captured_payloads) == 1
    aps = captured_payloads[0]["aps"]
    assert aps["sound"] == "bluebird_alarm.caf"
    assert aps["interruption-level"] == "time-sensitive"


@pytest.mark.anyio
async def test_apns_send_one_non_critical_disabled_uses_default():
    from app.services.apns import APNsClient
    from app.core.config import Settings

    settings = MagicMock(spec=Settings)
    settings.apns_host = "api.sandbox.push.apple.com"
    settings.APNS_BUNDLE_ID = "com.test.app"
    settings.APNS_TEAM_ID = "TEAMID1234"
    settings.APNS_KEY_ID = "KEYID12345"
    settings.APNS_TIMEOUT_SECONDS = 10.0
    settings.APNS_CONCURRENCY = 10
    settings.APNS_MAX_RETRIES = 0
    settings.apns_is_configured.return_value = True

    client = APNsClient(settings)
    client._p8_private_key = "fake_key"
    captured_payloads = []

    async def _fake_post(url, headers, json):
        captured_payloads.append(json)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    fake_http = MagicMock()
    fake_http.post = _fake_post
    client._client = fake_http

    with patch.object(client, "_get_or_create_jwt", return_value="fake.jwt.token"):
        cfg = SoundConfig(non_critical_sound_enabled=False)
        await client._send_one(
            "fake_token",
            "Admin message",
            extra_data={"type": "admin_message"},
            sound_config=cfg,
        )

    aps = captured_payloads[0]["aps"]
    assert aps["sound"] == "default"


# ---------------------------------------------------------------------------
# FCM _send_bulk_sync payload inspection (mocked firebase)
# ---------------------------------------------------------------------------

def _make_fcm_client():
    """Return an FCMClient with a mocked firebase app."""
    from app.services.fcm import FCMClient
    from app.core.config import Settings

    settings = MagicMock(spec=Settings)
    settings.fcm_is_configured.return_value = True

    client = FCMClient(settings)
    client._app = MagicMock()  # pretend initialized
    return client


def test_fcm_send_bulk_non_critical_correct_channel_and_sound():
    """Non-critical events must NOT use bluebird_alarm or bluebird_alerts channel."""
    client = _make_fcm_client()

    captured_messages = []

    def _fake_send_each(messages, app):
        captured_messages.extend(messages)
        batch = MagicMock()
        batch.responses = [MagicMock(success=True) for _ in messages]
        return batch

    with patch("firebase_admin.messaging.send_each", side_effect=_fake_send_each):
        cfg = SoundConfig(non_critical_sound_enabled=True, non_critical_sound_name="notification_soft")
        results = client._send_bulk_sync(
            ["token1"],
            "Your quiet period was approved",
            extra_data={"type": "quiet_period_update"},
            sound_config=cfg,
        )

    assert results[0].ok is True
    data = captured_messages[0].data
    assert data["channel_id"] == "non_critical_notifications"
    assert data["sound"] == "notification_soft"
    assert "full_screen" not in data
    assert "open_alarm" not in data
    assert data.get("sound_profile") == "non_critical"


def test_fcm_send_bulk_critical_uses_alarm_channel_and_sound():
    """Emergency events must use bluebird_alarm and bluebird_alerts channel."""
    client = _make_fcm_client()

    captured_messages = []

    def _fake_send_each(messages, app):
        captured_messages.extend(messages)
        batch = MagicMock()
        batch.responses = [MagicMock(success=True) for _ in messages]
        return batch

    with patch("firebase_admin.messaging.send_each", side_effect=_fake_send_each):
        results = client._send_bulk_sync(
            ["token1"],
            "LOCKDOWN",
            extra_data={"type": "emergency"},
        )

    assert results[0].ok is True
    data = captured_messages[0].data
    assert data["channel_id"] == "bluebird_alerts"
    assert data["sound"] == "bluebird_alarm"
    assert data["full_screen"] == "1"
    assert data["open_alarm"] == "1"


def test_fcm_send_bulk_non_critical_disabled_no_sound_field():
    """When non-critical sound is disabled, FCM data should have no 'sound' key."""
    client = _make_fcm_client()
    captured_messages = []

    def _fake_send_each(messages, app):
        captured_messages.extend(messages)
        batch = MagicMock()
        batch.responses = [MagicMock(success=True) for _ in messages]
        return batch

    with patch("firebase_admin.messaging.send_each", side_effect=_fake_send_each):
        cfg = SoundConfig(non_critical_sound_enabled=False)
        client._send_bulk_sync(
            ["token1"],
            "Notification",
            extra_data={"type": "admin_message"},
            sound_config=cfg,
        )

    data = captured_messages[0].data
    assert data["channel_id"] == "non_critical_notifications"
    assert "sound" not in data


def test_fcm_send_with_data_non_critical_correct_channel():
    """send_with_data for quiet period update must use non_critical_notifications channel."""
    client = _make_fcm_client()
    captured_messages = []

    def _fake_send_each(messages, app):
        captured_messages.extend(messages)
        batch = MagicMock()
        batch.responses = [MagicMock(success=True) for _ in messages]
        return batch

    with patch("firebase_admin.messaging.send_each", side_effect=_fake_send_each):
        cfg = SoundConfig.default()
        client._send_with_data_sync(
            ["token1"],
            "Quiet Period Approved",
            "Your quiet period request has been approved.",
            extra_data={"type": "quiet_period_update"},
            sound_config=cfg,
        )

    data = captured_messages[0].data
    assert data["channel_id"] == "non_critical_notifications"
    assert data.get("sound") == "notification_soft"


def test_fcm_send_with_data_critical_uses_bluebird_alerts_channel():
    """send_with_data for an emergency must use bluebird_alerts channel."""
    client = _make_fcm_client()
    captured_messages = []

    def _fake_send_each(messages, app):
        captured_messages.extend(messages)
        batch = MagicMock()
        batch.responses = [MagicMock(success=True) for _ in messages]
        return batch

    with patch("firebase_admin.messaging.send_each", side_effect=_fake_send_each):
        client._send_with_data_sync(
            ["token1"],
            "Emergency",
            "Lockdown in progress.",
            extra_data={"type": "emergency"},
        )

    data = captured_messages[0].data
    assert data["channel_id"] == "bluebird_alerts"


def test_disabling_non_critical_sound_does_not_affect_emergency():
    """Disabling non-critical sound must never silence emergency alerts."""
    client = _make_fcm_client()
    captured_messages = []

    def _fake_send_each(messages, app):
        captured_messages.extend(messages)
        batch = MagicMock()
        batch.responses = [MagicMock(success=True) for _ in messages]
        return batch

    with patch("firebase_admin.messaging.send_each", side_effect=_fake_send_each):
        cfg = SoundConfig(non_critical_sound_enabled=False)
        client._send_bulk_sync(
            ["token1"],
            "LOCKDOWN",
            extra_data={"type": "emergency"},
            sound_config=cfg,
        )

    data = captured_messages[0].data
    # Emergency is unaffected by non_critical_sound_enabled=False
    assert data["channel_id"] == "bluebird_alerts"
    assert data["sound"] == "bluebird_alarm"
    assert data["full_screen"] == "1"
