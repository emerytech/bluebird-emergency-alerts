import SwiftUI
import UserNotifications

@main
struct BlueBirdAlertsApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var appState = AppState()
    @AppStorage(DSThemePreference.storageKey) private var themeModeRaw = DSThemeMode.system.rawValue

    var body: some Scene {
        WindowGroup {
            Group {
                if appState.setupDone {
                    ContentView()
                } else {
                    LoginView()
                }
            }
                .environmentObject(appState)
                .preferredColorScheme(DSThemeMode(rawValue: themeModeRaw)?.colorScheme)
                .task {
                    DSTokenStore.shared.loadIfNeeded()
                    await requestNotificationsAndRegister()
                }
        }
    }

    private func requestNotificationsAndRegister() async {
        do {
            let center = UNUserNotificationCenter.current()
            let granted = try await center.requestAuthorization(options: [.alert, .sound, .badge])

            await MainActor.run {
                appState.notificationPermissionGranted = granted
                UIApplication.shared.registerForRemoteNotifications()
            }
        } catch {
            await MainActor.run {
                appState.lastError = "Notification permission error: \(error.localizedDescription)"
            }
        }
    }
}
