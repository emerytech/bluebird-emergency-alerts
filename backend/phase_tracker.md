# BlueBird Alerts — Phase Tracker

## Current Phase

### Phase 14 — iOS Feature Parity (pending)

---

## Completed Phases

### Phase 13 — Production Deployment

- `backend/Dockerfile` — multi-stage Python 3.11-slim build; non-root `bluebird` user; volumes for `/app/data` and `/app/secrets`
- `backend/.dockerignore` — excludes `.env`, `data/`, `secrets/`, `__pycache__`, tests from image
- `docker-compose.prod.yml` — `backend` + `nginx` + `certbot` (profile-gated) services; named volume for SQLite data; `secrets/` bind-mounted read-only; backend health-checked before nginx starts
- `deploy/nginx/bluebird.conf` — HTTP→HTTPS redirect; Let's Encrypt TLS; WebSocket upgrade for `/ws/` routes; per-zone rate limiting (general, alarm, auth); HSTS + security headers; ACME webroot challenge passthrough
- `tests/test_smoke.py` — live-server smoke suite (`-m smoke`) covering health, schools list, alarm status, super-admin login, API key enforcement, static assets, security headers; excluded from default `pytest` run via `pytest.ini addopts = -m "not smoke"`
- `pytest.ini` — registered `smoke` marker; `addopts = -m "not smoke"` keeps the 269-test unit suite clean

---

## Completed Phases

### Phase 12 — Push Reliability + Observability

- WS reconnect loop: tracks `closeCode` via `AtomicInteger`; breaks on 4xxx (server rejection); fast-reconnects on 1001/1012 (server restart) — both alarm WS and district WS in `MainActivity.kt`
- `alert_log.py` `_delivery_stats_sync`: added per-provider GROUP BY query; returns `by_provider` dict with `total`/`ok`/`failed`/`last_error` per provider
- `schemas.py`: added `ProviderDeliveryStats` model; `PushDeliveryStatsResponse` gains `by_provider: Dict[str, ProviderDeliveryStats]`
- `routes.py` `/alarm/push-stats`: maps `stats["by_provider"]` through `ProviderDeliveryStats(**v)` into response
- `admin_views.py` push delivery panel: replaced single-row table with provider-breakdown table (Total row + per-provider APNs/FCM rows); error rows shown inline
- Android: added `ProviderDeliveryStats` data class; `PushDeliveryStats` gains `byProvider: Map<String, ProviderDeliveryStats>`; `BackendClient.alarmPushStats` parses `by_provider` JSON; `PushDeliveryStatsCard` shows per-provider ok/failed rows
- `routes.py` `GET /district/audit-log`: aggregates audit events across all accessible schools, merges `tenant_slug` into metadata, sorts by timestamp descending
- Android: `UiState.districtAuditLog`; `loadDistrictAuditLog` ViewModel method; `BackendClient.listDistrictAuditLog`; `DistrictOverviewScreen` shows district audit log card with last 20 events

---

### Phase 11 — District Multi-School Admin

- Backend `schemas.py`: `DistrictQuietPeriodItem`, `DistrictQuietPeriodsResponse`, `DistrictQuietActionRequest`
- Backend `routes.py`: `GET /district/quiet-periods` — aggregates pending requests across assigned schools; `POST /district/quiet-periods/{id}/approve|deny` — tenant-scoped approval with assignment verification
- Android: `district_admin` added to `isAdmin` for role-gated views
- Android: `DistrictOverviewScreen` — pending quiet period queue with per-row Approve/Deny buttons and confirmation dialog
- Android: `DistrictQuietPeriodItem` data class + `districtQuietRequests` in `UiState`
- Android: ViewModel `loadDistrictQuietPeriods`, `approveDistrictQuietRequest`, `denyDistrictQuietRequest`
- Android: `BackendClient` — `listDistrictQuietPeriods`, `approveDistrictQuietPeriod`, `denyDistrictQuietPeriod`
- Android: District WebSocket (`/ws/district/alerts`) auto-connects on init for district/super_admin sessions; real-time alarm events fan into existing `districtTenants` state

---

## Completed Phases

### Phase 10 — Onboarding + User Management

- `access_code_service.py` — platform-level setup + access code CRUD
- `email_service.py` — transactional email scaffolding
- `health_monitor.py` — background health-check service
- `schemas.py` — `building_admin`, `staff` roles; access code schemas
- `permissions.py` — role matrix expanded; `PERM_SUBMIT_QUIET_REQUEST` unrestricted; self-approval blocked
- `routes.py` — onboarding endpoints (`/onboard/validate-code`, `/onboard/create-account`), access code admin endpoints, quiet period self-approval 403 guard + audit logging
- `admin_views.py` — Access Codes panel, Setup Codes panel
- iOS `OnboardingView.swift` — full multi-step onboarding (code entry → account creation → success)
- iOS `APIClient.swift` — onboarding API methods, role-aware helpers
- iOS `LoginView.swift` — "Get Started" entry point
- iOS `ContentView.swift` — quiet period inline feedback, admin list refresh on success
- Android `build.gradle.kts` — ZXing + CameraX dependencies
- Android `MainActivity.kt` — onboarding flow, role-gated UI (`building_admin`/`staff`), role capability descriptions, username pre-fill after account creation, quiet period Dialog/DialogProperties modal
- `test_onboarding.py` — full onboarding flow end-to-end (265 lines)
- `test_permissions_foundation.py` — updated: any active user can submit quiet request; admin cannot approve own request

### Phase 7 — Android Stabilization
- WebSocket lifecycle: auto-reconnect with exponential backoff, cleanup on tenant switch
- Push cross-tenant safety: suppress notifications for non-active tenant
- Settings screen polish: LazyColumn cards, typography hierarchy, back arrow, sign-out

### Phase 7.2 — iOS Settings Screen Polish
- Card-based layout, typography hierarchy matching Android

### Phase 7.4 — Design System Dark Mode
- iOS: `DSThemeMode`, `DSThemePreference`, adaptive fallback tokens, `DSBranding`
- Android: `isSystemInDarkTheme()` detection, `DSTokenStore.isDarkMode`, conditional color schemes in `BlueBirdTheme`

### Phase 7.5 — Mobile Admin Actions
- Quiet Request management: approve/deny with confirmation dialogs (iOS + Android)
- Messaging: inbox feed + send from admin
- Real-time WS events: `quiet_request_created`, `quiet_request_updated`, `message_received`
- Event deduplication: `processedEventIDs` bounded at 200

### Phase 7.5.1 — Help Request Lifecycle Fix
- Lifecycle corrected: `open → acknowledged → resolved`
- Backend: schemas + routes updated; WS events per transition
- iOS + Android: status-aware action buttons

### Phase 7.6 — Alarm Confirmation Tracking
- `acknowledgement_count` + `current_user_acknowledged` surfaced in iOS + Android alarm banners

### Phase 8 — Production Hardening
- Rate limiting on alarm + code endpoints (`_alarm_rate_store`, `_code_rate_store`)
- Push delivery stats endpoint + `PushDeliveryStatsCard` (iOS + Android)
- Audit log: structured `_fire_audit()` helper; all sensitive operations logged

### Phase 8.1 — Web Admin UI Polish
- Consistent `.data-table` across all tables
- `.table-search` + `.count-badge` CSS components
- Client-side search on users, devices, audit events, drill reports, schools
- `makeSearchFilter()` JS wired to all searchable tables

### Phase 9 — Backend Services + Test Coverage
- `email_service.py`, `health_monitor.py` scaffolded
- `test_permissions_foundation.py` expanded
- `test_onboarding.py` created

