import SwiftUI
import UserNotifications

@main
struct BlueBirdAlertsApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .task {
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
