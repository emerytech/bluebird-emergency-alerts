# BlueBird Alerts — Session & Authentication Architecture

Last updated: 2026-04-27  
Covers: `backend/app/api/deps.py`, `backend/app/api/routes.py`, `backend/app/services/session_store.py`, `backend/app/services/permissions.py`

---

## 1. Current Authentication Methods

There are three distinct authentication mechanisms running in parallel. They serve different surfaces and do not interfere with each other.

| Mechanism | Used By | Transport |
|---|---|---|
| API Key (`X-API-Key`) | Mobile clients, all REST API callers | HTTP request header |
| Server-side cookie session | Web admin dashboard | Signed cookie (Starlette SessionMiddleware) |
| Session token (`X-Session-Token`) | Mobile clients (new, layered on top of API key) | HTTP request header |

None of these use JWT. No OIDC or SAML is in use. This is intentional — the system was designed for controlled school deployments where a shared API key per tenant is acceptable at the current scale.

---

## 2. API Key Authentication

### How it works

Every mobile API endpoint declares `_: None = Depends(require_api_key)` in its signature. The `require_api_key` dependency (in `deps.py`) checks the `X-API-Key` header against the `API_KEY` value in the tenant's environment config.

The comparison uses `hmac.compare_digest` to prevent timing attacks.

If `API_KEY` is not configured in the environment, the check is a no-op — all requests pass. This is intentional for local development.

### Key properties

- A single shared key per deployment (not per user).
- The key proves the caller is a BlueBird client, not which user is acting. User identity is established separately via `user_id` query parameters that callers pass explicitly on each request.
- There is no key rotation mechanism today. Rotating the key requires restarting the server with a new env value.
- API key auth is not logged in the audit trail. User-level actions are audited by `user_id`.

### What it does not do

The API key does not identify a specific user session, does not expire, and cannot be revoked per-user. It is a shared secret for the deployment.

---

## 3. JWTs

JWTs are **not used** in this system for session management.

The trusted-device cookie (described in Section 7) uses a custom HMAC-signed payload format that superficially resembles a JWT (base64 payload + base64 signature, dot-separated) but is not a standard JWT. It uses `HS256` via `hmac.new(..., hashlib.sha256)` with the `SESSION_SECRET` as the key. There is no `alg` header and no standard JWT library is involved.

Do not assume JWT tooling or middleware will parse these tokens.

---

## 4. Session Table Design

The `user_sessions` table lives in each tenant's SQLite database (same file as users, alerts, etc.). It is created automatically on first use by `SessionStore._init_db()`.

```
user_sessions
─────────────────────────────────────────────────
id              INTEGER  PRIMARY KEY AUTOINCREMENT
user_id         INTEGER  NOT NULL
tenant_slug     TEXT     NOT NULL
session_token   TEXT     NOT NULL UNIQUE
client_type     TEXT     NOT NULL  DEFAULT 'mobile'
is_active       INTEGER  NOT NULL  DEFAULT 1
created_at      TEXT     NOT NULL  (ISO-8601 UTC)
last_seen_at    TEXT     NOT NULL  (ISO-8601 UTC)

Indexes:
  idx_sess_token          ON (session_token)
  idx_sess_user_type      ON (user_id, client_type, is_active)
```

### Design decisions

- `client_type` is the isolation boundary. Only values `"mobile"` and `"web"` are meaningful today.
- `is_active = 0` is a soft-delete. Records are never physically removed, which preserves a complete history of issued tokens.
- `tenant_slug` is stored redundantly in the row (the table already lives in the tenant's own DB) to support potential future cross-tenant administrative queries without needing to open every tenant DB.
- There is no TTL or automatic expiry column. Expiry is not enforced by the database or any background job today (see Section 10).
- The UNIQUE constraint on `session_token` is enforced at the database level. `secrets.token_urlsafe(32)` generates 256 bits of randomness, making collision effectively impossible.

---

## 5. Mobile Login Flow

The login endpoint is `POST /auth/login` and accepts a JSON body of type `MobileLoginRequest`.

```
Request body:
  login_name   string   (normalized to lowercase)
  password     string
  client_type  string   default "mobile"  ("mobile" | "web")

Response body (MobileLoginResponse):
  user_id
  name
  role
  login_name
  title
  must_change_password
  can_deactivate_alarm
  quiet_period_expires_at
  quiet_mode_active
  session_token            ← newly issued token
```

### Step-by-step

1. `authenticate_user` checks credentials against the users table (bcrypt compare).
2. On success, `mark_login` records the timestamp.
3. An `user_login` audit event fires with `channel: "mobile"`.
4. `client_type` is validated — anything other than `"mobile"` or `"web"` falls back to `"mobile"`.
5. `SessionStore.create_session(user_id, client_type)` runs atomically:
   - All existing active sessions for this user with the same `client_type` are set `is_active = 0`.
   - A new row is inserted with a fresh `secrets.token_urlsafe(32)` token.
6. The `session_token` is returned in the login response.

The caller must store this token and send it as `X-Session-Token` on subsequent requests.

---

## 6. Mobile Session Behavior

Mobile sessions are scoped to `client_type = "mobile"`.

- A new mobile login invalidates all previous mobile sessions for that user. Only one active mobile session per user is maintained.
- A new web login does **not** touch mobile sessions. A user can have one active mobile session and one active web session simultaneously.
- The API key (`X-API-Key`) continues to work for all mobile requests regardless of whether a session token is present. The session token is additive — it provides per-user traceability and revocability that the shared API key cannot offer.
- `SessionStore.touch(token)` updates `last_seen_at` and is designed to be called as a background task (never awaited inline) to avoid adding latency to request handling.
- `SessionStore.invalidate(token)` sets `is_active = 0` for a specific token. This is the logout path.

---

## 7. Web / Admin Session Behavior

The web admin dashboard uses an entirely separate authentication path from the mobile API.

### Cookie-based session (Starlette SessionMiddleware)

Starlette's `SessionMiddleware` is mounted at application startup with `SESSION_SECRET` from config. It signs the session cookie with HMAC-SHA256. The cookie is `HttpOnly`, `SameSite=lax`.

The session stores these keys:

| Key | Purpose |
|---|---|
| `admin_user_id` | Authenticated school-level admin user ID |
| `pending_admin_user_id` | User who has passed password but not yet TOTP |
| `super_admin_id` | Authenticated platform-level super admin ID |
| `pending_super_admin_id` | Super admin pending TOTP |
| `super_admin_school_slug` | Which tenant a super admin is currently impersonating |
| `admin_flash_message` / `admin_flash_error` | One-shot UI flash messages |
| `admin_quiet_period_hidden_ids` | UI state — which quiet period rows are hidden |
| `admin_totp_setup_secret` | Temporary TOTP secret during setup flow |
| `extracted_theme_colors` | Temporary state during brand/theme upload flow |

Logout (`POST /admin/logout`) calls `request.session.clear()`.

### School admin login flow

1. `POST /admin/login` (form submit): `authenticate_admin` verifies credentials.
2. If TOTP is enabled:
   - Check for a trusted-device cookie. If valid, skip TOTP and set `admin_user_id` directly.
   - Otherwise set `pending_admin_user_id` and redirect to `/admin/totp`.
3. `POST /admin/totp`: verify TOTP code. On success, promote `pending_admin_user_id` → `admin_user_id`.
4. An `user_login` audit event fires with `channel: "web_admin"` (and `totp: "verified"` or `totp: "trusted_device"` if applicable).

Only roles in `DASHBOARD_ROLES` (`admin`, `building_admin`, `district_admin`) may log into the web admin dashboard. `teacher`, `staff`, `law_enforcement`, and `super_admin` cannot.

### Super admin login flow

Mirrors the school admin flow but uses `super_admin_id` / `pending_super_admin_id` session keys and a separate login page at `/platform/login`. Super admins authenticate against the `PlatformAdminStore`, not the per-tenant `UserStore`.

### Trusted-device cookie

When a TOTP-enabled admin successfully verifies their TOTP code and opts in to "trust this device", the server issues a `bluebird_admin_trusted_device` cookie (or `bluebird_super_admin_trusted_device` for super admins).

The cookie value is a custom HMAC-signed token: `base64url(payload).base64url(HMAC-SHA256(payload, SESSION_SECRET))`.

The payload contains:
- `scope`: `"school-admin"` or `"super-admin"`
- `uid`: the user's numeric ID
- `school`: the tenant slug (school admin only)
- `fp`: SHA-256 of the `User-Agent` header at the time of issuance
- `exp`: Unix timestamp 14 days from issuance

On subsequent logins, if the decoded token matches `scope`, `uid`, `school`, and `fp`, and has not expired, the TOTP step is skipped. The fingerprint (`fp`) ties the cookie to the browser/client that originally authenticated, providing a weak device-binding.

---

## 8. Token Validation Flow

### API key validation (every mobile API request)

```
Incoming request
  → require_api_key dependency
  → Read X-API-Key header
  → Compare against settings.API_KEY using hmac.compare_digest
  → 401 if mismatch; pass-through if API_KEY not configured
```

### Session token validation (optional, non-breaking)

```
Incoming request
  → optional_session_token dependency
  → Read X-Session-Token header
  → If absent: return None (caller decides what to do)
  → Resolve tenant from request.state.school
  → Call ctx.session_store.get_by_token(token)
  → SELECT ... WHERE session_token = ? AND is_active = 1
  → Return SessionRecord or None
```

The `optional_session_token` dependency never raises. It is the caller's responsibility to treat a `None` result as unauthenticated if their endpoint requires a valid session.

As of the current implementation, `optional_session_token` is defined and exported but not yet attached as a `Depends(...)` on any endpoint. It is available for endpoints to adopt incrementally.

### Web admin validation (every admin page request)

```
Incoming request
  → _get_admin_user_id(request) reads request.session["admin_user_id"]
  → If missing: redirect to /admin/login
  → Fetch user from UserStore by ID
  → If user is inactive or not a dashboard role: redirect to /admin/login
```

---

## 9. Compatibility Rules

These rules are load-bearing. Do not break them without intentional migration planning.

**Rule 1 — API key is the baseline.**  
All existing mobile clients authenticate with `X-API-Key`. The session token system is layered on top. Any endpoint that adds `optional_session_token` must continue to work for callers that send only `X-API-Key` and no `X-Session-Token`.

**Rule 2 — Mobile and web sessions never cross-contaminate.**  
Creating a session with `client_type = "web"` only invalidates previous `client_type = "web"` sessions. Mobile sessions are untouched. The reverse is also true. This is enforced at the SQL level in `_create_sync`.

**Rule 3 — Web admin dashboard has no awareness of the session token table.**  
The web admin is authenticated entirely via Starlette's cookie session (`request.session["admin_user_id"]`). It does not issue or validate `X-Session-Token` values and never will under the current design.

**Rule 4 — User identity in the mobile API is caller-supplied.**  
The API key proves the caller is a BlueBird client. The `user_id` query parameter on each request identifies which user is acting. `_require_active_user` and `_require_active_user_with_permission` functions validate that the supplied user_id exists, is active, and has the required permission — but they do not verify that the caller "owns" that user_id cryptographically. The session token is the path to closing this gap.

**Rule 5 — DASHBOARD_ROLES is not the same as ALL_ROLES.**  
`teacher`, `staff`, and `law_enforcement` can use the mobile API but cannot log into the web admin dashboard. `super_admin` also cannot use the web admin dashboard — super admins have a separate platform login. Do not conflate these sets.

**Rule 6 — The `admin` role is a legacy alias for `building_admin`.**  
Both have hierarchy level 3 and identical permissions. New code should prefer `building_admin`. The `admin` string is kept for backward compatibility with existing database rows.

---

## 10. Future Migration Notes

These are known gaps and the intended direction for each. None of these are active tickets — they are recorded here so future auth work starts from an accurate baseline.

### Session token adoption on endpoints

`optional_session_token` is defined but not wired to any endpoint. The next step is to choose which endpoints should require a valid session token in addition to (or instead of) the API key. The recommended path is to start with write operations (alarm trigger, quiet period requests, help requests) because those carry the highest risk if `user_id` is spoofed by a malicious client.

### Session expiry

There is no TTL enforcement today. `last_seen_at` is tracked and available for querying, but no background job expires idle sessions. A reasonable policy would be: expire mobile sessions inactive for 90 days; expire web sessions inactive for 30 days. This should be implemented as a scheduled cleanup job, not a database trigger, to keep the SQLite schema simple.

### Token rotation on use

Currently, a session token issued at login is valid until explicitly invalidated or a new login of the same `client_type` occurs. There is no rolling-window refresh. If rotation is desired (e.g., refresh every 24 hours of use), `touch` could be extended to return a new token when the current token is older than a threshold, with the old token invalidated atomically in the same `BEGIN/COMMIT` block.

### Per-user API keys

The shared `API_KEY` cannot be revoked per user. If a device is compromised, the only option is rotating the key for the entire deployment. Once session tokens are adopted on endpoints, the session token becomes the revocable per-user credential and the API key becomes a lighter-weight "is this a BlueBird client" gate. At that point, rotating the API key on compromise is acceptable because per-user sessions can still be invalidated individually via `SessionStore.invalidate`.

### TOTP trust cookie hardening

The trusted-device fingerprint is SHA-256 of the `User-Agent` string. This is a weak binding — any client that spoofs the same User-Agent can bypass TOTP on a stolen session cookie. A stronger binding would use a long-lived browser-local random value (stored in `localStorage` or a separate non-session cookie) included in the HMAC payload.

### Web admin session into the session table

The web admin currently uses Starlette's server-side cookie session (a signed cookie, not a database row). There is no server-side revocation — clearing `request.session` only works if the user makes a request. To support forcible logout of web admin users (e.g., after a role change), the web admin session should eventually be mirrored into the `user_sessions` table using `client_type = "web"`, allowing server-side invalidation.

### Multi-tenancy and session isolation

`tenant_slug` is stored in each session row, but `SessionStore` is instantiated per-tenant and always queries against the tenant's own DB. Cross-tenant session lookups are not currently possible and not needed. If a future feature requires a platform-level view of all active sessions across tenants, the `tenant_slug` column is the join key.
