import Foundation
import Combine
import UIKit

// Tenant entry returned by /me
struct TenantSummaryItem: Codable, Identifiable, Equatable {
    var id: String { tenantSlug }
    let tenantSlug: String
    let tenantName: String
    let role: String?

    enum CodingKeys: String, CodingKey {
        case tenantSlug = "tenant_slug"
        case tenantName = "tenant_name"
        case role
    }
}

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
    // Multi-tenant
    private static let tenantsJSONKey = "tenants_json"
    private static let selectedTenantSlugKey = "selected_tenant_slug"
    private static let selectedTenantNameKey = "selected_tenant_name"
    private static let userTitleKey = "user_title"
    // Stable per-install device identifier
    private static let deviceIDKey = "bluebird_device_id"

    @Published var notificationPermissionGranted: Bool?
    @Published var deviceToken: String?
    @Published var usingLocalTestToken = false

    /// Stable per-install UUID. Uses identifierForVendor when available and
    /// falls back to a persisted UUID so it survives app restarts.
    var deviceID: String {
        let defaults = UserDefaults.standard
        if let stored = defaults.string(forKey: Self.deviceIDKey), !stored.isEmpty {
            return stored
        }
        let generated = UIDevice.current.identifierForVendor?.uuidString ?? UUID().uuidString
        defaults.set(generated, forKey: Self.deviceIDKey)
        return generated
    }
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
    // Multi-tenant state
    @Published var tenants: [TenantSummaryItem] = []
    @Published var selectedTenantSlug: String = UserDefaults.standard.string(forKey: selectedTenantSlugKey) ?? ""
    @Published var selectedTenantName: String = UserDefaults.standard.string(forKey: selectedTenantNameKey) ?? ""
    @Published var userTitle: String = UserDefaults.standard.string(forKey: userTitleKey) ?? ""

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

    // Synced from ContentView so Learning Center screens can dismiss on alarm.
    @Published var alarmIsActive: Bool = false

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
        // Load persisted tenant list
        if let data = UserDefaults.standard.data(forKey: Self.tenantsJSONKey),
           let decoded = try? JSONDecoder().decode([TenantSummaryItem].self, from: data) {
            tenants = decoded
        }
    }

    // The URL used for API calls in the currently-selected tenant.
    // Replaces the school slug in serverURL with selectedTenantSlug when a switch has occurred.
    var selectedTenantURL: URL {
        let slug = selectedTenantSlug.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !slug.isEmpty else { return serverURL }
        guard var components = URLComponents(url: serverURL, resolvingAgainstBaseURL: false) else {
            return serverURL
        }
        let pathSegments = components.path
            .split(separator: "/", omittingEmptySubsequences: true)
            .map(String.init)
        if pathSegments.isEmpty {
            components.path = "/\(slug)"
        } else {
            var segs = pathSegments
            segs[0] = slug
            components.path = "/" + segs.joined(separator: "/")
        }
        return components.url ?? serverURL
    }

    // The base server URL (scheme + host, no path) for building WebSocket URLs.
    var serverBaseURL: URL {
        guard var components = URLComponents(url: serverURL, resolvingAgainstBaseURL: false) else {
            return serverURL
        }
        components.path = ""
        components.queryItems = nil
        return components.url ?? serverURL
    }

    // True if the user has access to more than one school.
    var isMultiTenant: Bool { tenants.count > 1 }

    // Active school name: prefer the selected tenant name, fall back to login-time school name.
    var effectiveSchoolName: String {
        let selected = selectedTenantName.trimmingCharacters(in: .whitespacesAndNewlines)
        return selected.isEmpty ? schoolName : selected
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

    // Called after /me returns to persist the full tenant list.
    func updateTenants(_ newTenants: [TenantSummaryItem], selectedSlug: String, selectedName: String) {
        tenants = newTenants
        // Only update selection if no selection is stored yet or selection is not in the new list.
        let slugIsValid = newTenants.contains { $0.tenantSlug == selectedSlug }
        let currentSlugValid = newTenants.contains { $0.tenantSlug == selectedTenantSlug }
        if !currentSlugValid {
            selectedTenantSlug = slugIsValid ? selectedSlug : (newTenants.first?.tenantSlug ?? selectedSlug)
            selectedTenantName = newTenants.first(where: { $0.tenantSlug == selectedTenantSlug })?.tenantName ?? selectedName
            UserDefaults.standard.set(selectedTenantSlug, forKey: Self.selectedTenantSlugKey)
            UserDefaults.standard.set(selectedTenantName, forKey: Self.selectedTenantNameKey)
        }
        if let data = try? JSONEncoder().encode(newTenants) {
            UserDefaults.standard.set(data, forKey: Self.tenantsJSONKey)
        }
    }

    // Switch the active tenant. Restarts WebSocket connections in the calling view.
    func switchTenant(slug: String, name: String) {
        selectedTenantSlug = slug
        selectedTenantName = name
        UserDefaults.standard.set(slug, forKey: Self.selectedTenantSlugKey)
        UserDefaults.standard.set(name, forKey: Self.selectedTenantNameKey)
    }

    func updateUserTitle(_ title: String) {
        userTitle = title
        UserDefaults.standard.set(title, forKey: Self.userTitleKey)
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
        defaults.removeObject(forKey: Self.tenantsJSONKey)
        defaults.removeObject(forKey: Self.selectedTenantSlugKey)
        defaults.removeObject(forKey: Self.selectedTenantNameKey)
        defaults.removeObject(forKey: Self.userTitleKey)

        setupDone = false
        userID = nil
        userName = ""
        userRole = ""
        loginName = ""
        canDeactivateAlarm = false
        schoolName = ""
        tenants = []
        selectedTenantSlug = ""
        selectedTenantName = ""
        userTitle = ""
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
