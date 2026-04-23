# BlueBird Alerts Android

Minimal Android app for local backend testing while Apple developer approval is pending.

## What it does

- Connects to the BlueBird backend over local HTTP
- Tests backend reachability
- Registers a local Android test device with `/register-device`
- Sends panic alerts with `/panic`
- Loads `/devices` and `/alerts` debug data

## Open in Android Studio

1. Open Android Studio
2. Choose **Open**
3. Select:

   `/Users/temery/Documents/BlueBird Alerts/BlueBird-Alerts/android`

4. Let Gradle sync

## Backend URL

The app currently points to:

`http://10.7.0.171:8000`

This is set in:

- `app/build.gradle.kts` via `BuildConfig.BACKEND_BASE_URL`

## Build a debug APK

Once Android Studio finishes syncing:

1. Select an Android device or emulator
2. Click **Run**

Or build the APK from Android Studio:

**Build > Build Bundle(s) / APK(s) > Build APK(s)**

## Note

This machine does not currently have a Java runtime / Gradle / Android SDK configured for command-line APK builds, so the project was scaffolded but not compiled locally from the shell.
