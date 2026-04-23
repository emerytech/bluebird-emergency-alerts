# BlueBird Alerts (Phase 1) — FastAPI Backend (Push + SMS)

This backend accepts a panic request, persists it (audit trail), and broadcasts it redundantly:

- Push: APNs to registered iOS devices
- SMS: Twilio (optional; enabled via env vars)

Device registration is already platform-aware so Android/FCM can be added without redesigning the API.

## Project layout

- `app/main.py`: FastAPI app + lifespan wiring
- `app/api/routes.py`: `/register-device` + `/panic`
- `app/services/apns.py`: APNs HTTP/2 client (token-based auth, `.p8`)
- `app/services/device_registry.py`: SQLite-backed platform/provider-aware device registry
- `app/services/alert_log.py`: SQLite alert log (timestamp, message)
- `app/services/user_store.py`: SQLite user store (role, phone) for SMS + attribution
- `app/services/twilio_sms.py`: Twilio REST SMS client (optional)
- `app/services/alert_broadcaster.py`: Broadcast orchestration + delivery logging
- `.env.example`: environment variables template

## Quick start

```bash
cd BlueBird-Alerts/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env to point to your .p8 and identifiers

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```bash
curl -s http://127.0.0.1:8000/health
```

Open the local operator dashboard:

```text
http://127.0.0.1:8000/admin
```

The admin dashboard can now:
- create local test users (`teacher` and `admin`)
- activate an alarm
- deactivate an alarm using an admin user id

Android clients can poll `/alarm/status` and keep sounding a local alarm until the backend marks the alarm inactive.

## Security (MVP)

If you set `API_KEY` in `.env`, all endpoints except `/health` require:

```bash
-H "X-API-Key: <your key>"
```

## API usage

Register an iOS/APNs device token:

```bash
curl -s -X POST http://127.0.0.1:8000/register-device \
  -H "X-API-Key: <your key (optional)>" \
  -H "Content-Type: application/json" \
  -d '{"device_token":"<64-hex-token>","platform":"ios","push_provider":"apns"}'
```

Future Android/FCM registration will use the same route:

```bash
curl -s -X POST http://127.0.0.1:8000/register-device \
  -H "X-API-Key: <your key (optional)>" \
  -H "Content-Type: application/json" \
  -d '{"device_token":"<fcm-token>","platform":"android","push_provider":"fcm"}'
```

Create a user (for SMS + attribution):

```bash
curl -s -X POST http://127.0.0.1:8000/users \
  -H "X-API-Key: <your key (optional)>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Front Office","role":"admin","phone_e164":"+15551234567"}'
```

Trigger a panic alert:

```bash
curl -s -X POST http://127.0.0.1:8000/panic \
  -H "X-API-Key: <your key (optional)>" \
  -H "Content-Type: application/json" \
  -d '{"message":"Lockdown drill. Please follow procedures."}'
```

Trigger a panic alert with attribution:

```bash
curl -s -X POST http://127.0.0.1:8000/panic \
  -H "X-API-Key: <your key (optional)>" \
  -H "Content-Type: application/json" \
  -d '{"message":"Lockdown drill. Please follow procedures.","user_id":1}'
```

List recent alerts:

```bash
curl -s http://127.0.0.1:8000/alerts -H "X-API-Key: <your key (optional)>"
```

## APNs configuration notes (required for real pushes)

1. **Apple Developer Key (.p8)**: Create an APNs Auth Key in the Apple Developer portal and download the `.p8`.
2. **Team ID / Key ID**: Copy `APNS_TEAM_ID` and `APNS_KEY_ID` from Apple Developer.
3. **Bundle ID / Topic**: Set `APNS_BUNDLE_ID` to your iOS app's bundle identifier.
4. **Sandbox vs Production**
   - Development build + sandbox device token: `APNS_USE_SANDBOX=true`
   - TestFlight/App Store + production device token: `APNS_USE_SANDBOX=false`

## Important limitations (Phase 1)

- Device tokens are stored in SQLite and survive backend restarts on the same machine.
- SQLite is still a single-node local database, so this is not yet a multi-instance shared registry.
- Android/FCM tokens can register now, but `/panic` only sends APNs pushes until the FCM sender is added.
- SMS delivery is optional and requires Twilio configuration (`SMS_ENABLED=true` + Twilio env vars).
- For production reliability, replace in-process background tasks with a durable job queue (outbox pattern).
- The `/admin` dashboard is read-only and local-operator focused for now; real user login and role enforcement are the next step.
