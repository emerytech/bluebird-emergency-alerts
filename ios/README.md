# BlueBird Alerts — iOS (SwiftUI) (Phase 1)

This app:
- Requests notification permission on launch
- Registers for remote notifications (APNs)
- Prints the device token and POSTs it to the backend (`/register-device`)
- Shows a large red panic button that POSTs to the backend (`/panic`)

## Create the Xcode project

1. Open Xcode → **File → New → Project…**
2. Choose **iOS → App**
3. Product Name: **BlueBirdAlerts**
4. Interface: **SwiftUI**
5. Language: **Swift**
6. Bundle Identifier: set to your real identifier (example: `com.yourschool.bluebirdalerts`)

Then replace the generated Swift files with the ones in:
- `BlueBird-Alerts/ios/BlueBirdAlerts/Sources/`

Also add these supporting files into your Xcode project:
- `BlueBird-Alerts/ios/BlueBirdAlerts/Supporting/Info.plist` (or merge keys into your existing Info.plist)
- `BlueBird-Alerts/ios/BlueBirdAlerts/Supporting/BlueBirdAlerts.entitlements`

## Enable Push Notifications in Xcode

In your project target:
1. **Signing & Capabilities**
2. Add capability **Push Notifications**
3. Add capability **Background Modes** and check **Remote notifications** (recommended)

Then ensure your target uses the provided entitlements:
- Build Settings → **Code Signing Entitlements** = `BlueBirdAlerts/Supporting/BlueBirdAlerts.entitlements`

You also need an **APNs key (.p8)** configured on the backend, and the iOS app must use the same Bundle ID (APNs topic).

## Backend URL configuration

The app reads the backend base URL from `Info.plist` key `BACKEND_BASE_URL`.

For a real iPhone, **do not** use `127.0.0.1` — set it to your Mac’s LAN IP, for example:
`http://192.168.1.50:8000`

### App Transport Security (ATS) for local HTTP

If you use `http://` during development, add an ATS exception in `Info.plist`.
Simplest dev-only option:

```xml
<key>NSAppTransportSecurity</key>
<dict>
  <key>NSAllowsArbitraryLoads</key>
  <true/>
</dict>
```

For production, use HTTPS and remove arbitrary loads.

## Test checklist (real device required for APNs token)

1. Run backend: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
2. Install/run iOS app on a real iPhone
3. Accept notification permission prompt
4. Confirm Xcode console prints `APNs device token: ...`
5. Backend logs should show `/register-device` success
6. Press panic → backend `/panic` returns success counts
