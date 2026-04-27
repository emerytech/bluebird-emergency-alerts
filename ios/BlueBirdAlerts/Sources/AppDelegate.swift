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

    // Present alerts even when the app is open, with type-appropriate audio.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        let userInfo = notification.request.content.userInfo
        let alertType = userInfo["type"] as? String ?? ""

        // Sender silence: suppress sound if this device belongs to the requester.
        // NOTE: iOS app does not persist user_id today — sender silence for background
        // pushes requires per-token APNs dispatch (future work).
        let silentForSender = (userInfo["silent_for_sender"] as? String) == "true"
        let triggeredByUid = (userInfo["triggered_by_user_id"] as? String).flatMap { Int($0) }
        let storedUid = UserDefaults.standard.string(forKey: "bluebird_user_id").flatMap { Int($0) }
        let isSender = silentForSender
            && triggeredByUid != nil
            && storedUid != nil
            && triggeredByUid == storedUid

        if isSender {
            return [.banner]
        }

        // Emergency alerts: full audio (unchanged).
        if alertType == "emergency" || alertType.isEmpty {
            return [.banner, .sound]
        }

        // Help requests: banner + sound (aps.sound = "help_request_alert.caf").
        return [.banner, .sound]
    }
}

extension Notification.Name {
    static let deviceTokenUpdated = Notification.Name("BlueBird.deviceTokenUpdated")
    static let deviceTokenUpdateFailed = Notification.Name("BlueBird.deviceTokenUpdateFailed")
}
