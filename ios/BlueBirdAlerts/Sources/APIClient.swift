import Foundation

struct APIClient {
    let baseURL: URL

    func health() async throws -> HealthResponse {
        let url = baseURL.appendingPathComponent("health")
        let (data, resp) = try await URLSession.shared.data(from: url)
        try require2xx(resp: resp, data: data)
        return try JSONDecoder().decode(HealthResponse.self, from: data)
    }

    func registerDevice(token: String) async throws -> RegisterDeviceResponse {
        let url = baseURL.appendingPathComponent("register-device")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = RegisterDeviceRequest(deviceToken: token)
        req.httpBody = try JSONEncoder().encode(body)

        let (data, resp) = try await URLSession.shared.data(for: req)
        try require2xx(resp: resp, data: data)
        return try JSONDecoder().decode(RegisterDeviceResponse.self, from: data)
    }

    func panic(message: String) async throws -> PanicResponse {
        let url = baseURL.appendingPathComponent("panic")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = PanicRequest(message: message)
        req.httpBody = try JSONEncoder().encode(body)

        let (data, resp) = try await URLSession.shared.data(for: req)
        try require2xx(resp: resp, data: data)
        return try JSONDecoder().decode(PanicResponse.self, from: data)
    }

    func messageAdmin(message: String, userId: Int? = nil) async throws -> AdminMessageResponse {
        let url = baseURL.appendingPathComponent("message-admin")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = AdminMessageRequest(userId: userId, message: message)
        req.httpBody = try JSONEncoder().encode(body)

        let (data, resp) = try await URLSession.shared.data(for: req)
        try require2xx(resp: resp, data: data)
        return try JSONDecoder().decode(AdminMessageResponse.self, from: data)
    }

    func devices() async throws -> DevicesResponse {
        let url = baseURL.appendingPathComponent("devices")
        let (data, resp) = try await URLSession.shared.data(from: url)
        try require2xx(resp: resp, data: data)
        return try JSONDecoder().decode(DevicesResponse.self, from: data)
    }

    func alerts(limit: Int = 5) async throws -> AlertsResponse {
        var components = URLComponents(url: baseURL.appendingPathComponent("alerts"), resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "limit", value: String(limit))]
        guard let url = components?.url else {
            throw NSError(domain: "BlueBird.API", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid alerts URL"])
        }

        let (data, resp) = try await URLSession.shared.data(from: url)
        try require2xx(resp: resp, data: data)
        return try JSONDecoder().decode(AlertsResponse.self, from: data)
    }

    func fetchTenantSettings() async throws -> TenantSettings {
        let url = baseURL.appendingPathComponent("tenant-settings")
        let (data, resp) = try await URLSession.shared.data(from: url)
        try require2xx(resp: resp, data: data)
        return try JSONDecoder().decode(TenantSettings.self, from: data)
    }

    private func require2xx(resp: URLResponse, data: Data) throws {
        guard let http = resp as? HTTPURLResponse else { return }
        guard (200..<300).contains(http.statusCode) else {
            let body = parseAPIError(data: data)
            throw NSError(
                domain: "BlueBird.API",
                code: http.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "HTTP \(http.statusCode): \(body)"]
            )
        }
    }

    private func parseAPIError(data: Data) -> String {
        if let error = try? JSONDecoder().decode(FastAPIError.self, from: data) {
            return error.message
        }
        return String(data: data, encoding: .utf8) ?? "<non-utf8>"
    }
}

// MARK: - Models

struct HealthResponse: Decodable {
    let ok: Bool
}

private struct FastAPIError: Decodable {
    let detail: [ValidationErrorDetail]?

    var message: String {
        guard let first = detail?.first else { return "Request failed." }
        return first.msg
    }
}

private struct ValidationErrorDetail: Decodable {
    let msg: String
}

private struct RegisterDeviceRequest: Encodable {
    let deviceToken: String
    let platform = "ios"
    let pushProvider = "apns"

    enum CodingKeys: String, CodingKey {
        case deviceToken = "device_token"
        case platform
        case pushProvider = "push_provider"
    }
}

struct RegisterDeviceResponse: Decodable {
    let registered: Bool
    let deviceCount: Int
    let providerCounts: [String: Int]

    enum CodingKeys: String, CodingKey {
        case registered
        case deviceCount = "device_count"
        case providerCounts = "provider_counts"
    }
}

struct DevicesResponse: Decodable {
    let deviceCount: Int
    let providerCounts: [String: Int]
    let devices: [DeviceSummary]

    enum CodingKeys: String, CodingKey {
        case deviceCount = "device_count"
        case providerCounts = "provider_counts"
        case devices
    }
}

struct DeviceSummary: Decodable, Identifiable {
    let platform: String
    let pushProvider: String
    let tokenSuffix: String

    var id: String { "\(platform)-\(pushProvider)-\(tokenSuffix)" }

    enum CodingKeys: String, CodingKey {
        case platform
        case pushProvider = "push_provider"
        case tokenSuffix = "token_suffix"
    }
}

private struct PanicRequest: Encodable {
    let message: String
}

private struct AdminMessageRequest: Encodable {
    let userId: Int?
    let message: String

    enum CodingKeys: String, CodingKey {
        case userId = "user_id"
        case message
    }
}

struct PanicResponse: Decodable {
    let alertId: Int
    let deviceCount: Int
    let attempted: Int
    let succeeded: Int
    let failed: Int
    let apnsConfigured: Bool

    enum CodingKeys: String, CodingKey {
        case alertId = "alert_id"
        case deviceCount = "device_count"
        case attempted
        case succeeded
        case failed
        case apnsConfigured = "apns_configured"
    }
}

struct AdminMessageResponse: Decodable {
    let messageId: Int
    let createdAt: String
    let userId: Int?
    let message: String

    enum CodingKeys: String, CodingKey {
        case messageId = "message_id"
        case createdAt = "created_at"
        case userId = "user_id"
        case message
    }
}

struct AlertsResponse: Decodable {
    let alerts: [AlertSummary]
}

struct AlertSummary: Decodable, Identifiable {
    let alertId: Int
    let createdAt: String
    let message: String

    var id: Int { alertId }

    enum CodingKeys: String, CodingKey {
        case alertId = "alert_id"
        case createdAt = "created_at"
        case message
    }
}

// MARK: - Tenant Settings

struct TenantSettings: Decodable {
    let notifications: TenantNotificationSettings
    let quietPeriods: TenantQuietPeriodSettings
    let alerts: TenantAlertSettings
    let devices: TenantDeviceSettings
    let accessCodes: TenantAccessCodeSettings

    static let defaults = TenantSettings(
        notifications: .init(),
        quietPeriods: .init(),
        alerts: .init(),
        devices: .init(),
        accessCodes: .init()
    )

    enum CodingKeys: String, CodingKey {
        case notifications
        case quietPeriods  = "quiet_periods"
        case alerts
        case devices
        case accessCodes   = "access_codes"
    }
}

struct TenantNotificationSettings: Decodable {
    let nonCriticalSoundName: String
    let nonCriticalSoundEnabled: Bool
    let quietPeriodNotificationsEnabled: Bool
    let adminMessageNotificationsEnabled: Bool
    let accessCodeNotificationsEnabled: Bool
    let auditNotificationsEnabled: Bool
    let criticalAlertSoundLocked: Bool

    init(
        nonCriticalSoundName: String = "notification_soft",
        nonCriticalSoundEnabled: Bool = true,
        quietPeriodNotificationsEnabled: Bool = true,
        adminMessageNotificationsEnabled: Bool = true,
        accessCodeNotificationsEnabled: Bool = true,
        auditNotificationsEnabled: Bool = false,
        criticalAlertSoundLocked: Bool = true
    ) {
        self.nonCriticalSoundName = nonCriticalSoundName
        self.nonCriticalSoundEnabled = nonCriticalSoundEnabled
        self.quietPeriodNotificationsEnabled = quietPeriodNotificationsEnabled
        self.adminMessageNotificationsEnabled = adminMessageNotificationsEnabled
        self.accessCodeNotificationsEnabled = accessCodeNotificationsEnabled
        self.auditNotificationsEnabled = auditNotificationsEnabled
        self.criticalAlertSoundLocked = criticalAlertSoundLocked
    }

    enum CodingKeys: String, CodingKey {
        case nonCriticalSoundName                  = "non_critical_sound_name"
        case nonCriticalSoundEnabled               = "non_critical_sound_enabled"
        case quietPeriodNotificationsEnabled       = "quiet_period_notifications_enabled"
        case adminMessageNotificationsEnabled      = "admin_message_notifications_enabled"
        case accessCodeNotificationsEnabled        = "access_code_notifications_enabled"
        case auditNotificationsEnabled             = "audit_notifications_enabled"
        case criticalAlertSoundLocked              = "critical_alert_sound_locked"
    }
}

struct TenantQuietPeriodSettings: Decodable {
    let enabled: Bool
    let requiresApproval: Bool
    let allowScheduling: Bool
    let maxDurationMinutes: Int
    let defaultDurationMinutes: Int
    let allowSelfApproval: Bool
    let districtAdminCanApproveAll: Bool
    let buildingAdminScope: String

    init(
        enabled: Bool = true,
        requiresApproval: Bool = true,
        allowScheduling: Bool = true,
        maxDurationMinutes: Int = 1440,
        defaultDurationMinutes: Int = 60,
        allowSelfApproval: Bool = false,
        districtAdminCanApproveAll: Bool = true,
        buildingAdminScope: String = "building"
    ) {
        self.enabled = enabled
        self.requiresApproval = requiresApproval
        self.allowScheduling = allowScheduling
        self.maxDurationMinutes = maxDurationMinutes
        self.defaultDurationMinutes = defaultDurationMinutes
        self.allowSelfApproval = allowSelfApproval
        self.districtAdminCanApproveAll = districtAdminCanApproveAll
        self.buildingAdminScope = buildingAdminScope
    }

    enum CodingKeys: String, CodingKey {
        case enabled
        case requiresApproval              = "requires_approval"
        case allowScheduling               = "allow_scheduling"
        case maxDurationMinutes            = "max_duration_minutes"
        case defaultDurationMinutes        = "default_duration_minutes"
        case allowSelfApproval             = "allow_self_approval"
        case districtAdminCanApproveAll    = "district_admin_can_approve_all"
        case buildingAdminScope            = "building_admin_scope"
    }
}

struct TenantAlertSettings: Decodable {
    let teachersCanTriggerSecurePerimeter: Bool
    let teachersCanTriggerLockdown: Bool
    let lawEnforcementCanTrigger: Bool
    let requireHoldToActivate: Bool
    let holdSeconds: Int
    let disableRequiresAdmin: Bool

    init(
        teachersCanTriggerSecurePerimeter: Bool = true,
        teachersCanTriggerLockdown: Bool = true,
        lawEnforcementCanTrigger: Bool = false,
        requireHoldToActivate: Bool = true,
        holdSeconds: Int = 3,
        disableRequiresAdmin: Bool = true
    ) {
        self.teachersCanTriggerSecurePerimeter = teachersCanTriggerSecurePerimeter
        self.teachersCanTriggerLockdown = teachersCanTriggerLockdown
        self.lawEnforcementCanTrigger = lawEnforcementCanTrigger
        self.requireHoldToActivate = requireHoldToActivate
        self.holdSeconds = holdSeconds
        self.disableRequiresAdmin = disableRequiresAdmin
    }

    enum CodingKeys: String, CodingKey {
        case teachersCanTriggerSecurePerimeter = "teachers_can_trigger_secure_perimeter"
        case teachersCanTriggerLockdown        = "teachers_can_trigger_lockdown"
        case lawEnforcementCanTrigger          = "law_enforcement_can_trigger"
        case requireHoldToActivate             = "require_hold_to_activate"
        case holdSeconds                       = "hold_seconds"
        case disableRequiresAdmin              = "disable_requires_admin"
    }
}

struct TenantDeviceSettings: Decodable {
    let deviceStatusReportingEnabled: Bool
    let markDeviceStaleAfterMinutes: Int
    let excludeInactiveDevicesFromPush: Bool

    init(
        deviceStatusReportingEnabled: Bool = true,
        markDeviceStaleAfterMinutes: Int = 30,
        excludeInactiveDevicesFromPush: Bool = true
    ) {
        self.deviceStatusReportingEnabled = deviceStatusReportingEnabled
        self.markDeviceStaleAfterMinutes = markDeviceStaleAfterMinutes
        self.excludeInactiveDevicesFromPush = excludeInactiveDevicesFromPush
    }

    enum CodingKeys: String, CodingKey {
        case deviceStatusReportingEnabled      = "device_status_reporting_enabled"
        case markDeviceStaleAfterMinutes       = "mark_device_stale_after_minutes"
        case excludeInactiveDevicesFromPush    = "exclude_inactive_devices_from_push"
    }
}

struct TenantAccessCodeSettings: Decodable {
    let enabled: Bool
    let autoExpireEnabled: Bool
    let defaultExpirationDays: Int
    let autoArchiveRevokedEnabled: Bool
    let autoArchiveRevokedAfterDays: Int

    init(
        enabled: Bool = true,
        autoExpireEnabled: Bool = true,
        defaultExpirationDays: Int = 14,
        autoArchiveRevokedEnabled: Bool = false,
        autoArchiveRevokedAfterDays: Int = 7
    ) {
        self.enabled = enabled
        self.autoExpireEnabled = autoExpireEnabled
        self.defaultExpirationDays = defaultExpirationDays
        self.autoArchiveRevokedEnabled = autoArchiveRevokedEnabled
        self.autoArchiveRevokedAfterDays = autoArchiveRevokedAfterDays
    }

    enum CodingKeys: String, CodingKey {
        case enabled
        case autoExpireEnabled             = "auto_expire_enabled"
        case defaultExpirationDays         = "default_expiration_days"
        case autoArchiveRevokedEnabled     = "auto_archive_revoked_enabled"
        case autoArchiveRevokedAfterDays   = "auto_archive_revoked_after_days"
    }
}
