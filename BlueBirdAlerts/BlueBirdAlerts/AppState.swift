import Foundation
import Combine

@MainActor
final class AppState: ObservableObject {
    private static let biometricsAllowedKey = "biometrics_allowed"
    private static let hapticAlertsEnabledKey = "haptic_alerts_enabled"
    private static let screenFlashAlertsEnabledKey = "screen_flash_alerts_enabled"
    private static let flashlightAlertsEnabledKey = "flashlight_alerts_enabled"
    private static let endAlertConfirmationEnabledKey = "end_alert_confirmation_enabled"
    private static let setupDoneKey = "setup_done"
    private static let serverURLKey = "server_url"
    private static let userIDKey = "user_id"
    private static let userNameKey = "user_name"
    private static let userRoleKey = "user_role"
    private static let loginNameKey = "login_name"
    private static let canDeactivateKey = "can_deactivate"
    private static let schoolNameKey = "school_name"
    private static let initialDeviceAuthUserIDKey = "initial_device_auth_user_id"
    private static let initialDeviceAuthUserNameKey = "initial_device_auth_user_name"

    @Published var notificationPermissionGranted: Bool?
    @Published var deviceToken: String?
    @Published var usingLocalTestToken = false
    @Published var deviceRegistered = false
    @Published var setupDone: Bool = UserDefaults.standard.bool(forKey: setupDoneKey)
    @Published var serverURLString: String = UserDefaults.standard.string(forKey: serverURLKey) ?? Config.backendBaseURL.absoluteString
    @Published var userID: Int?
    @Published var userName: String = UserDefaults.standard.string(forKey: userNameKey) ?? ""
    @Published var userRole: String = UserDefaults.standard.string(forKey: userRoleKey) ?? ""
    @Published var loginName: String = UserDefaults.standard.string(forKey: loginNameKey) ?? ""
    @Published var canDeactivateAlarm: Bool = UserDefaults.standard.bool(forKey: canDeactivateKey)
    @Published var schoolName: String = UserDefaults.standard.string(forKey: schoolNameKey) ?? ""
    @Published var initialDeviceAuthUserID: Int?
    @Published var initialDeviceAuthUserName: String = UserDefaults.standard.string(forKey: initialDeviceAuthUserNameKey) ?? ""
    @Published var backendReachable: Bool?
    @Published var registeredDeviceCount = 0
    @Published var providerCounts: [String: Int] = [:]
    @Published var recentAlerts: [String] = []
    @Published var lastStatus: String?
    @Published var lastError: String?
    @Published var biometricsAllowed: Bool = UserDefaults.standard.bool(forKey: biometricsAllowedKey) {
        didSet {
            UserDefaults.standard.set(biometricsAllowed, forKey: Self.biometricsAllowedKey)
        }
    }
    @Published var hapticAlertsEnabled: Bool = {
        if let stored = UserDefaults.standard.object(forKey: hapticAlertsEnabledKey) as? Bool {
            return stored
        }
        return true
    }() {
        didSet {
            UserDefaults.standard.set(hapticAlertsEnabled, forKey: Self.hapticAlertsEnabledKey)
        }
    }
    @Published var screenFlashAlertsEnabled: Bool = {
        if let stored = UserDefaults.standard.object(forKey: screenFlashAlertsEnabledKey) as? Bool {
            return stored
        }
        return true
    }() {
        didSet {
            UserDefaults.standard.set(screenFlashAlertsEnabled, forKey: Self.screenFlashAlertsEnabledKey)
        }
    }
    @Published var flashlightAlertsEnabled: Bool = {
        if let stored = UserDefaults.standard.object(forKey: flashlightAlertsEnabledKey) as? Bool {
            return stored
        }
        return true
    }() {
        didSet {
            UserDefaults.standard.set(flashlightAlertsEnabled, forKey: Self.flashlightAlertsEnabledKey)
        }
    }
    @Published var endAlertConfirmationEnabled: Bool = {
        if let stored = UserDefaults.standard.object(forKey: endAlertConfirmationEnabledKey) as? Bool {
            return stored
        }
        return true
    }() {
        didSet {
            UserDefaults.standard.set(endAlertConfirmationEnabled, forKey: Self.endAlertConfirmationEnabledKey)
        }
    }

    init() {
        let storedUserID = UserDefaults.standard.integer(forKey: Self.userIDKey)
        userID = storedUserID > 0 ? storedUserID : nil
        let storedInitialUserID = UserDefaults.standard.integer(forKey: Self.initialDeviceAuthUserIDKey)
        initialDeviceAuthUserID = storedInitialUserID > 0 ? storedInitialUserID : nil
        let normalizedServer = Self.normalizedServerURLString(serverURLString)
        if normalizedServer != serverURLString {
            serverURLString = normalizedServer
            UserDefaults.standard.set(normalizedServer, forKey: Self.serverURLKey)
        }
    }

    var serverURL: URL {
        URL(string: Self.normalizedServerURLString(serverURLString)) ?? Self.defaultTenantURL
    }

    func completeLogin(
        userID: Int,
        name: String,
        role: String,
        loginName: String,
        canDeactivateAlarm: Bool,
        serverURL: URL,
        schoolName: String = "",
    ) {
        self.userID = userID
        self.userName = name
        self.userRole = role
        self.loginName = loginName
        self.canDeactivateAlarm = canDeactivateAlarm
        self.schoolName = schoolName
        let normalizedServerURLString = Self.normalizedServerURLString(serverURL.absoluteString)
        self.serverURLString = normalizedServerURLString
        self.setupDone = true

        let defaults = UserDefaults.standard
        defaults.set(true, forKey: Self.setupDoneKey)
        defaults.set(userID, forKey: Self.userIDKey)
        defaults.set(name, forKey: Self.userNameKey)
        defaults.set(role, forKey: Self.userRoleKey)
        defaults.set(loginName, forKey: Self.loginNameKey)
        defaults.set(canDeactivateAlarm, forKey: Self.canDeactivateKey)
        defaults.set(schoolName, forKey: Self.schoolNameKey)
        defaults.set(normalizedServerURLString, forKey: Self.serverURLKey)
    }

    func logout() {
        let preservedServer = serverURLString
        let defaults = UserDefaults.standard
        defaults.removeObject(forKey: Self.setupDoneKey)
        defaults.removeObject(forKey: Self.userIDKey)
        defaults.removeObject(forKey: Self.userNameKey)
        defaults.removeObject(forKey: Self.userRoleKey)
        defaults.removeObject(forKey: Self.loginNameKey)
        defaults.removeObject(forKey: Self.canDeactivateKey)
        defaults.removeObject(forKey: Self.schoolNameKey)

        setupDone = false
        userID = nil
        userName = ""
        userRole = ""
        loginName = ""
        canDeactivateAlarm = false
        schoolName = ""
        deviceRegistered = false
        backendReachable = nil
        registeredDeviceCount = 0
        providerCounts = [:]
        recentAlerts = []
        lastStatus = nil
        lastError = nil

        serverURLString = preservedServer
        defaults.set(preservedServer, forKey: Self.serverURLKey)
    }

    func markInitialDeviceAuthUserIfNeeded(userID: Int, name: String) {
        guard initialDeviceAuthUserID == nil else { return }
        initialDeviceAuthUserID = userID
        initialDeviceAuthUserName = name
        let defaults = UserDefaults.standard
        defaults.set(userID, forKey: Self.initialDeviceAuthUserIDKey)
        defaults.set(name, forKey: Self.initialDeviceAuthUserNameKey)
    }

    private static var defaultTenantURL: URL {
        ensureTenantPath(on: Config.backendBaseURL)
    }

    private static func normalizedServerURLString(_ raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if let parsed = URL(string: trimmed) {
            return ensureTenantPath(on: parsed).absoluteString
        }
        return defaultTenantURL.absoluteString
    }

    private static func ensureTenantPath(on url: URL) -> URL {
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return url
        }
        let normalizedPath = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if normalizedPath.isEmpty {
            components.path = "/default"
        }
        return components.url ?? url
    }
}
