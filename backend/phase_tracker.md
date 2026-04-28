# BlueBird Alerts — Phase Tracker

## Current Phase

### Phase 11 — District Multi-School Admin (active)

**In Progress**
- District admin UI: school list, cross-school quiet period approval queue
- District admin WebSocket scope (receive events from all assigned schools)
- `district_admin` role enforcement in mobile role-gated views

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

---

## Pending Phases

### Phase 12 — Push Reliability + Observability
- APNS/FCM error surfacing in web admin UI
- Audit log viewer for district admins
- Graceful backend restart (WS reconnect on 1001/1012 close codes)
- Health monitor admin panel integration

### Phase 13 — Production Deployment
- Docker Compose production config
- Secrets management (env-based, no hardcoded values)
- HTTPS termination + reverse proxy setup
- Smoke test suite against staging
