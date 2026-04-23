import UIKit
import UserNotifications

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        // Ensure notifications can be shown while app is in the foreground (useful for drills/tests).
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        let token = deviceToken.map { String(format: "%02.2hhx", $0) }.joined()
        print("APNs device token: \(token)")

        NotificationCenter.default.post(
            name: .deviceTokenUpdated,
            object: nil,
            userInfo: ["token": token]
        )
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        print("APNs registration failed: \(error)")

        NotificationCenter.default.post(
            name: .deviceTokenUpdateFailed,
            object: nil,
            userInfo: ["error": error.localizedDescription]
        )
    }

    // Present alerts even when the app is open.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        return [.banner, .sound]
    }
}

extension Notification.Name {
    static let deviceTokenUpdated = Notification.Name("BlueBird.deviceTokenUpdated")
    static let deviceTokenUpdateFailed = Notification.Name("BlueBird.deviceTokenUpdateFailed")
}
