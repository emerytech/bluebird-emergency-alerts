# BlueBird Alerts — Phase Tracker

## Completed Phases

### Phase 7 — Android Stabilization
- WebSocket lifecycle: auto-reconnect with exponential backoff, cleanup on tenant switch
- Push cross-tenant safety: suppress notifications for non-active tenant
- Settings screen polish: LazyColumn cards, typography hierarchy, back arrow, sign-out

### Phase 7.2 — iOS Settings Screen Polish
- Card-based layout, typography hierarchy matching Android

### Phase 7.4 — Design System Dark Mode
- iOS: `DSThemeMode`, `DSThemePreference`, adaptive fallback tokens, `DSBranding`
- Android: `isSystemInDarkTheme()` detection before token load, `DSTokenStore.isDarkMode`, conditional `darkColorScheme`/`lightColorScheme` in `BlueBirdTheme`
- Token lookup supports `dark`/`light` keyed JSON objects

### Phase 7.5 — Mobile Admin Actions
- Quiet Request management: approve/deny with confirmation dialogs (iOS + Android)
- Messaging: inbox feed + send from admin
- Real-time WS events: `quiet_request_created`, `quiet_request_updated`, `message_received`
- Event deduplication: `processedEventIDs` (iOS `Set<String>`, Android `LinkedHashSet`) bounded at 200, keyed by `event_id`
- `_publish_simple_event` helper in routes.py for lightweight WS payloads

### Phase 7.5.1 — Help Request Lifecycle Fix
- **Bug fixed**: `team_assist_action` endpoint hardcoded `next_status = "resolved"` for all actions
- **New lifecycle**: `open → acknowledged → resolved`
- Backend: `schemas.py` added "resolve" to valid actions; `routes.py` routes acknowledge/responding → "acknowledged", resolve → "resolved"; guard against acting on already-resolved items
- Backend: WS events `help_request_acknowledged` / `help_request_resolved` published after each action
- iOS: `teamAssistFeedRow` shows Acknowledge (open/active only), Resolve, Forward buttons based on status; `AdminRequestHelpPromptSheet` now has Acknowledge + Resolve
- Android: `TeamAssistRow` shows status-aware chips; admin prompt dialog updated to Acknowledge/Resolve; WS handlers refresh team assist list

### Phase 7.6 — Alarm Confirmation Tracking
- `AlarmStatusResponse` iOS model now decodes `acknowledgement_count` + `current_user_acknowledged`
- iOS ContentView: `alarmAcknowledgementCount` + `alarmCurrentUserAcknowledged` state vars; populated from `refreshIncidentFeed()`; banner shows "✓ N acknowledged" when count > 0
- Android `AlarmStatus` data class: added `acknowledgementCount` + `currentUserAcknowledged`; both `alarmStatus()` and `parseAlarm()` parse new fields; `AlarmBanner` shows ack count line

### Phase 8.1 — Web Admin UI Polish
- Consistent `.data-table` class across all tables (schools, billing, audit, messages, requests, reports, devices, quiet periods, alerts)
- `.data-table th` — uppercase headers, highlighted background, `text-transform: uppercase`
- `.data-table tbody tr:hover` — subtle row hover state
- `.table-wrap` — horizontal scroll wrapper for wide tables (billing, messages, devices)
- `.table-search` + `.count-badge` — new CSS components
- Client-side search inputs on: users, devices, audit events, drill reports, schools (super admin)
- JS `makeSearchFilter()` function wired to all searchable tables/grids
- Messages section: replaced 🔔 emoji in h2 with `<span class="count-badge">` for unread count

---

## Current Phase

### Phase 8 — Production Hardening

---

## Upcoming Phases

### Phase 8 — Production Hardening (remaining)
- APNS/FCM error surfacing in admin UI
- Audit log viewer for district admins
- Graceful backend restart (WS reconnect on 1001/1012 close codes)
