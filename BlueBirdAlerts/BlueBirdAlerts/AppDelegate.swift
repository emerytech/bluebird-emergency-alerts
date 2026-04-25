import UIKit
import UserNotifications

enum AlarmPushBridge {
    private static var pendingUserInfo: [AnyHashable: Any]?

    static func store(userInfo: [AnyHashable: Any]) {
        pendingUserInfo = userInfo
        DispatchQueue.main.async {
            NotificationCenter.default.post(name: .alarmPushReceived, object: nil, userInfo: userInfo)
        }
    }

    static func consumePendingUserInfo() -> [AnyHashable: Any]? {
        let payload = pendingUserInfo
        pendingUserInfo = nil
        return payload
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        if let remoteNotification = launchOptions?[.remoteNotification] as? [AnyHashable: Any] {
            AlarmPushBridge.store(userInfo: remoteNotification)
        }
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

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        AlarmPushBridge.store(userInfo: notification.request.content.userInfo)
        return [.banner, .sound, .badge, .list]
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse
    ) async {
        AlarmPushBridge.store(userInfo: response.notification.request.content.userInfo)
    }

    func application(
        _ application: UIApplication,
        didReceiveRemoteNotification userInfo: [AnyHashable: Any],
        fetchCompletionHandler completionHandler: @escaping (UIBackgroundFetchResult) -> Void
    ) {
        AlarmPushBridge.store(userInfo: userInfo)
        completionHandler(.newData)
    }
}

extension Notification.Name {
    static let deviceTokenUpdated = Notification.Name("BlueBird.deviceTokenUpdated")
    static let deviceTokenUpdateFailed = Notification.Name("BlueBird.deviceTokenUpdateFailed")
    static let alarmPushReceived = Notification.Name("BlueBird.alarmPushReceived")
}
