import Foundation

struct APIClient {
    let baseURL: URL
    let apiKey: String

    init(baseURL: URL, apiKey: String = "") {
        self.baseURL = baseURL
        self.apiKey = apiKey
    }

    private func withAPIKey(_ request: inout URLRequest) {
        let key = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        if !key.isEmpty {
            request.setValue(key, forHTTPHeaderField: "X-API-Key")
        }
    }

    func health() async throws -> HealthResponse {
        let url = baseURL.appendingPathComponent("health")
        let (data, response) = try await URLSession.shared.data(from: url)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(HealthResponse.self, from: data)
    }

    func registerDevice(token: String) async throws -> RegisterDeviceResponse {
        let url = baseURL.appendingPathComponent("register-device")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(RegisterDeviceRequest(deviceToken: token))

        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(RegisterDeviceResponse.self, from: data)
    }

    func panic(userID: Int, message: String, isTraining: Bool = false, trainingLabel: String? = nil, silentAudio: Bool = false) async throws -> PanicResponse {
        let url = baseURL.appendingPathComponent("panic")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        withAPIKey(&request)
        request.httpBody = try JSONEncoder().encode(
            PanicRequest(
                userID: userID,
                message: message,
                isTraining: isTraining,
                trainingLabel: trainingLabel?.trimmingCharacters(in: .whitespacesAndNewlines),
                silentAudio: silentAudio
            )
        )

        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(PanicResponse.self, from: data)
    }

    func devices() async throws -> DevicesResponse {
        let url = baseURL.appendingPathComponent("devices")
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(DevicesResponse.self, from: data)
    }

    func alerts(limit: Int = 5) async throws -> AlertsResponse {
        var components = URLComponents(url: baseURL.appendingPathComponent("alerts"), resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "limit", value: String(limit))]
        guard let url = components?.url else {
            throw NSError(domain: "BlueBird.API", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid alerts URL"])
        }
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(AlertsResponse.self, from: data)
    }

    func activeIncidents() async throws -> IncidentListResponse {
        let url = baseURL.appendingPathComponent("incidents/active")
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(IncidentListResponse.self, from: data)
    }

    func alarmStatus() async throws -> AlarmStatusResponse {
        let url = baseURL.appendingPathComponent("alarm/status")
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(AlarmStatusResponse.self, from: data)
    }

    func deactivateAlarm(adminUserID: Int) async throws -> AlarmStatusResponse {
        let url = baseURL.appendingPathComponent("alarm/deactivate")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        withAPIKey(&request)
        request.httpBody = try JSONEncoder().encode(AlarmDeactivateRequest(userID: adminUserID))
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(AlarmStatusResponse.self, from: data)
    }

    func activeRequestHelp() async throws -> TeamAssistListResponse {
        let url = baseURL.appendingPathComponent("team-assist/active")
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(TeamAssistListResponse.self, from: data)
    }

    func activeTeamAssists() async throws -> TeamAssistListResponse {
        try await activeRequestHelp()
    }

    func configLabels() async throws -> [String: String] {
        let url = baseURL.appendingPathComponent("config/labels")
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode([String: String].self, from: data)
    }

    func createRequestHelp(userID: Int, type: String) async throws -> TeamAssistSummary {
        let url = baseURL.appendingPathComponent("team-assist/create")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        withAPIKey(&request)
        request.httpBody = try JSONEncoder().encode(TeamAssistCreateRequest(userID: userID, type: type))
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(TeamAssistSummary.self, from: data)
    }

    func createTeamAssist(userID: Int, type: String) async throws -> TeamAssistSummary {
        try await createRequestHelp(userID: userID, type: type)
    }

    func updateRequestHelp(
        teamAssistID: Int,
        actorUserID: Int,
        action: String,
        forwardToUserID: Int? = nil
    ) async throws -> TeamAssistSummary {
        let url = baseURL.appendingPathComponent("team-assist/\(teamAssistID)/action")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        withAPIKey(&request)
        request.httpBody = try JSONEncoder().encode(
            TeamAssistActionPayload(userID: actorUserID, action: action, forwardToUserID: forwardToUserID)
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(TeamAssistSummary.self, from: data)
    }

    func updateTeamAssist(
        teamAssistID: Int,
        actorUserID: Int,
        action: String,
        forwardToUserID: Int? = nil
    ) async throws -> TeamAssistSummary {
        try await updateRequestHelp(
            teamAssistID: teamAssistID,
            actorUserID: actorUserID,
            action: action,
            forwardToUserID: forwardToUserID
        )
    }

    func confirmRequestHelpCancel(teamAssistID: Int, actorUserID: Int) async throws -> TeamAssistSummary {
        let url = baseURL.appendingPathComponent("team-assist/\(teamAssistID)/cancel-confirm")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        withAPIKey(&request)
        request.httpBody = try JSONEncoder().encode(TeamAssistCancelConfirmPayload(userID: actorUserID))
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(TeamAssistSummary.self, from: data)
    }

    func confirmTeamAssistCancel(teamAssistID: Int, actorUserID: Int) async throws -> TeamAssistSummary {
        try await confirmRequestHelpCancel(teamAssistID: teamAssistID, actorUserID: actorUserID)
    }

    func requestQuietPeriod(userID: Int, reason: String?) async throws -> QuietPeriodRequestResponse {
        let url = baseURL.appendingPathComponent("quiet-periods/request")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        withAPIKey(&request)
        request.httpBody = try JSONEncoder().encode(QuietPeriodRequestPayload(userID: userID, reason: reason))
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(QuietPeriodRequestResponse.self, from: data)
    }

    func adminQuietPeriodRequests(adminUserID: Int, limit: Int = 120) async throws -> QuietPeriodAdminListResponse {
        var components = URLComponents(url: baseURL.appendingPathComponent("quiet-periods/admin/requests"), resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "admin_user_id", value: String(adminUserID)),
            URLQueryItem(name: "limit", value: String(limit)),
        ]
        guard let url = components?.url else {
            throw NSError(domain: "BlueBird.API", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid quiet period admin requests URL"])
        }
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(QuietPeriodAdminListResponse.self, from: data)
    }

    func approveQuietPeriodRequest(requestID: Int, adminUserID: Int) async throws -> QuietPeriodRequestResponse {
        let url = baseURL.appendingPathComponent("quiet-periods/\(requestID)/approve")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        withAPIKey(&request)
        request.httpBody = try JSONEncoder().encode(QuietPeriodAdminActionPayload(adminUserID: adminUserID))
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(QuietPeriodRequestResponse.self, from: data)
    }

    func denyQuietPeriodRequest(requestID: Int, adminUserID: Int) async throws -> QuietPeriodRequestResponse {
        let url = baseURL.appendingPathComponent("quiet-periods/\(requestID)/deny")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        withAPIKey(&request)
        request.httpBody = try JSONEncoder().encode(QuietPeriodAdminActionPayload(adminUserID: adminUserID))
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(QuietPeriodRequestResponse.self, from: data)
    }

    func myQuietRequest(userID: Int) async throws -> QuietPeriodRequestResponse {
        var components = URLComponents(url: baseURL.appendingPathComponent("quiet-periods/my-request"), resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "user_id", value: String(userID))]
        guard let url = components?.url else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(QuietPeriodRequestResponse.self, from: data)
    }

    func quietPeriodStatus(userID: Int) async throws -> QuietPeriodRequestResponse {
        var components = URLComponents(url: baseURL.appendingPathComponent("quiet-periods/status"), resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "user_id", value: String(userID))]
        guard let url = components?.url else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(QuietPeriodRequestResponse.self, from: data)
    }

    func cancelQuietRequest(requestID: Int, userID: Int) async throws -> QuietPeriodRequestResponse {
        var components = URLComponents(url: baseURL.appendingPathComponent("quiet-periods/request/\(requestID)"), resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "user_id", value: String(userID))]
        guard let url = components?.url else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(QuietPeriodRequestResponse.self, from: data)
    }

    func alarmPushStats(userID: Int) async throws -> PushDeliveryStatsResponse {
        var components = URLComponents(url: baseURL.appendingPathComponent("alarm/push-stats"), resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "user_id", value: String(userID))]
        guard let url = components?.url else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(PushDeliveryStatsResponse.self, from: data)
    }

    func auditLog(
        userID: Int,
        limit: Int = 25,
        offset: Int = 0,
        search: String? = nil,
        eventType: String? = nil
    ) async throws -> AuditLogResponse {
        var components = URLComponents(url: baseURL.appendingPathComponent("audit-log"), resolvingAgainstBaseURL: false)
        var items = [
            URLQueryItem(name: "user_id", value: String(userID)),
            URLQueryItem(name: "limit", value: String(limit)),
            URLQueryItem(name: "offset", value: String(offset)),
        ]
        if let s = search, !s.isEmpty { items.append(URLQueryItem(name: "search", value: s)) }
        if let e = eventType, !e.isEmpty { items.append(URLQueryItem(name: "event_type", value: e)) }
        components?.queryItems = items
        guard let url = components?.url else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(AuditLogResponse.self, from: data)
    }

    func listSchools() async throws -> SchoolsCatalogResponse {
        let url = Config.backendBaseURL.appendingPathComponent("schools")
        let (data, response) = try await URLSession.shared.data(from: url)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(SchoolsCatalogResponse.self, from: data)
    }

    func me(userID: Int) async throws -> MeResponse {
        var components = URLComponents(url: baseURL.appendingPathComponent("me"), resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "user_id", value: String(userID))]
        guard let url = components?.url else {
            throw NSError(domain: "BlueBird.API", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid /me URL"])
        }
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(MeResponse.self, from: data)
    }

    func districtOverview(userID: Int) async throws -> DistrictOverviewResponse {
        var components = URLComponents(url: baseURL.appendingPathComponent("district/overview"), resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "user_id", value: String(userID))]
        guard let url = components?.url else {
            throw NSError(domain: "BlueBird.API", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid /district/overview URL"])
        }
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(DistrictOverviewResponse.self, from: data)
    }

    func login(username: String, password: String) async throws -> MobileLoginResponse {
        let url = baseURL.appendingPathComponent("auth/login")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(MobileLoginRequest(loginName: username, password: password))

        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(MobileLoginResponse.self, from: data)
    }

    func messageAdmin(userID: Int?, message: String) async throws -> AdminMessageResponse {
        let url = baseURL.appendingPathComponent("message-admin")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        withAPIKey(&request)
        request.httpBody = try JSONEncoder().encode(MessageAdminRequest(userID: userID, message: message))
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(AdminMessageResponse.self, from: data)
    }

    func listMessageRecipients() async throws -> [MessageRecipient] {
        let url = baseURL.appendingPathComponent("users")
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        let users = try JSONDecoder().decode(UsersResponse.self, from: data).users
        return users
            .filter { $0.isActive && $0.role.lowercased() != "admin" }
            .map { MessageRecipient(userID: $0.userID, label: "\($0.name) (\($0.role))") }
            .sorted { $0.label.localizedCaseInsensitiveCompare($1.label) == .orderedAscending }
    }

    func listTeamAssistForwardRecipients() async throws -> [MessageRecipient] {
        let url = baseURL.appendingPathComponent("users")
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        let users = try JSONDecoder().decode(UsersResponse.self, from: data).users
        return users
            .filter { $0.isActive }
            .map { MessageRecipient(userID: $0.userID, label: "\($0.name) (\($0.role))") }
            .sorted { $0.label.localizedCaseInsensitiveCompare($1.label) == .orderedAscending }
    }

    func sendMessageFromAdmin(
        adminUserID: Int,
        message: String,
        recipientUserIDs: [Int],
        sendToAll: Bool,
    ) async throws -> AdminSendMessageResponse {
        let url = baseURL.appendingPathComponent("messages/send")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        withAPIKey(&request)
        request.httpBody = try JSONEncoder().encode(
            AdminSendMessageRequest(
                adminUserID: adminUserID,
                message: message,
                recipientUserIDs: recipientUserIDs,
                sendToAll: sendToAll
            )
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(AdminSendMessageResponse.self, from: data)
    }

    private func requireSuccess(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
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
        return String(data: data, encoding: .utf8) ?? "<non-utf8 response>"
    }
}

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
    let userID: Int
    let message: String
    let isTraining: Bool
    let trainingLabel: String?
    let silentAudio: Bool

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case message
        case isTraining = "is_training"
        case trainingLabel = "training_label"
        case silentAudio = "silent_audio"
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

struct IncidentListResponse: Decodable {
    let incidents: [IncidentSummary]
}

struct IncidentSummary: Decodable, Identifiable {
    let id: Int
    let type: String
    let status: String
    let createdBy: Int
    let createdAt: String
    let targetScope: String

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case status
        case createdBy = "created_by"
        case createdAt = "created_at"
        case targetScope = "target_scope"
    }
}

struct AlarmStatusResponse: Decodable {
    let isActive: Bool
    let message: String?
    let isTraining: Bool
    let trainingLabel: String?
    let silentAudio: Bool
    let acknowledgementCount: Int
    let currentUserAcknowledged: Bool

    enum CodingKeys: String, CodingKey {
        case isActive = "is_active"
        case message
        case isTraining = "is_training"
        case trainingLabel = "training_label"
        case silentAudio = "silent_audio"
        case acknowledgementCount = "acknowledgement_count"
        case currentUserAcknowledged = "current_user_acknowledged"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        isActive = try container.decodeIfPresent(Bool.self, forKey: .isActive) ?? false
        message = try container.decodeIfPresent(String.self, forKey: .message)
        isTraining = try container.decodeIfPresent(Bool.self, forKey: .isTraining) ?? false
        silentAudio = try container.decodeIfPresent(Bool.self, forKey: .silentAudio) ?? false
        trainingLabel = try container.decodeIfPresent(String.self, forKey: .trainingLabel)
        acknowledgementCount = try container.decodeIfPresent(Int.self, forKey: .acknowledgementCount) ?? 0
        currentUserAcknowledged = try container.decodeIfPresent(Bool.self, forKey: .currentUserAcknowledged) ?? false
    }
}

struct TeamAssistListResponse: Decodable {
    let teamAssists: [TeamAssistSummary]

    enum CodingKeys: String, CodingKey {
        case teamAssists = "team_assists"
    }
}

struct TeamAssistSummary: Decodable, Identifiable {
    let id: Int
    let type: String
    let status: String
    let createdBy: Int
    let createdAt: String
    let actedByUserID: Int?
    let actedByLabel: String?
    let forwardToUserID: Int?
    let forwardToLabel: String?
    let cancelRequesterConfirmed: Bool?
    let cancelAdminConfirmed: Bool?
    let cancelAdminLabel: String?
    let cancelledByUserID: Int?
    let cancelReasonText: String?

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case status
        case createdBy = "created_by"
        case createdAt = "created_at"
        case actedByUserID = "acted_by_user_id"
        case actedByLabel = "acted_by_label"
        case forwardToUserID = "forward_to_user_id"
        case forwardToLabel = "forward_to_label"
        case cancelRequesterConfirmed = "cancel_requester_confirmed"
        case cancelAdminConfirmed = "cancel_admin_confirmed"
        case cancelAdminLabel = "cancel_admin_label"
        case cancelledByUserID = "cancelled_by_user_id"
        case cancelReasonText = "cancel_reason_text"
    }
}

struct SchoolsCatalogResponse: Decodable {
    let schools: [SchoolCatalogItem]
}

struct SchoolCatalogItem: Decodable, Identifiable {
    let name: String
    let slug: String
    let path: String

    var id: String { slug }
}

private struct MobileLoginRequest: Encodable {
    let loginName: String
    let password: String

    enum CodingKeys: String, CodingKey {
        case loginName = "login_name"
        case password
    }
}

struct MobileLoginResponse: Decodable {
    let userID: Int
    let name: String
    let role: String
    let loginName: String
    let canDeactivateAlarm: Bool
    let quietModeActive: Bool?
    let quietPeriodExpiresAt: String?

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case name
        case role
        case loginName = "login_name"
        case canDeactivateAlarm = "can_deactivate_alarm"
        case quietModeActive = "quiet_mode_active"
        case quietPeriodExpiresAt = "quiet_period_expires_at"
    }
}

private struct MessageAdminRequest: Encodable {
    let userID: Int?
    let message: String

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case message
    }
}

private struct AdminSendMessageRequest: Encodable {
    let adminUserID: Int
    let message: String
    let recipientUserIDs: [Int]
    let sendToAll: Bool

    enum CodingKeys: String, CodingKey {
        case adminUserID = "admin_user_id"
        case message
        case recipientUserIDs = "recipient_user_ids"
        case sendToAll = "send_to_all"
    }
}

private struct TeamAssistCreateRequest: Encodable {
    let userID: Int
    let type: String

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case type
    }
}

private struct TeamAssistActionPayload: Encodable {
    let userID: Int
    let action: String
    let forwardToUserID: Int?

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case action
        case forwardToUserID = "forward_to_user_id"
    }
}

private struct TeamAssistCancelConfirmPayload: Encodable {
    let userID: Int

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
    }
}

private struct QuietPeriodRequestPayload: Encodable {
    let userID: Int
    let reason: String?

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case reason
    }
}

private struct QuietPeriodAdminActionPayload: Encodable {
    let adminUserID: Int

    enum CodingKeys: String, CodingKey {
        case adminUserID = "admin_user_id"
    }
}

private struct AlarmDeactivateRequest: Encodable {
    let userID: Int

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
    }
}

struct AdminMessageResponse: Decodable {
    let messageID: Int
    let createdAt: String
    let message: String

    enum CodingKeys: String, CodingKey {
        case messageID = "message_id"
        case createdAt = "created_at"
        case message
    }
}

struct AdminSendMessageResponse: Decodable {
    let sentCount: Int
    let recipientScope: String

    enum CodingKeys: String, CodingKey {
        case sentCount = "sent_count"
        case recipientScope = "recipient_scope"
    }
}

struct QuietPeriodRequestResponse: Decodable {
    let requestID: Int?
    let userID: Int?
    let reason: String?
    let status: String?
    let requestedAt: String?
    let approvedAt: String?
    let approvedByLabel: String?
    let expiresAt: String?
    let quietModeActive: Bool?

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id"
        case userID = "user_id"
        case reason
        case status
        case requestedAt = "requested_at"
        case approvedAt = "approved_at"
        case approvedByLabel = "approved_by_label"
        case expiresAt = "expires_at"
        case quietModeActive = "quiet_mode_active"
    }
}

struct QuietPeriodAdminListResponse: Decodable {
    let requests: [QuietPeriodAdminRequest]
}

struct QuietPeriodAdminRequest: Decodable, Identifiable {
    let requestID: Int
    let userID: Int
    let userName: String?
    let userRole: String?
    let reason: String?
    let status: String
    let requestedAt: String
    let approvedAt: String?
    let approvedByLabel: String?
    let expiresAt: String?

    var id: Int { requestID }

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id"
        case userID = "user_id"
        case userName = "user_name"
        case userRole = "user_role"
        case reason
        case status
        case requestedAt = "requested_at"
        case approvedAt = "approved_at"
        case approvedByLabel = "approved_by_label"
        case expiresAt = "expires_at"
    }
}

private struct UsersResponse: Decodable {
    let users: [UserSummary]
}

private struct UserSummary: Decodable {
    let userID: Int
    let name: String
    let role: String
    let isActive: Bool

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case name
        case role
        case isActive = "is_active"
    }
}

struct MessageRecipient: Identifiable {
    let userID: Int
    let label: String
    var id: Int { userID }
}

// MARK: - Phase 7: Multi-tenant /me and /district/overview models

struct MeResponse: Decodable {
    let userID: Int
    let name: String
    let loginName: String
    let role: String
    let title: String?
    let canDeactivateAlarm: Bool
    let tenants: [TenantSummaryItem]
    let selectedTenant: String

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case name
        case loginName = "login_name"
        case role
        case title
        case canDeactivateAlarm = "can_deactivate_alarm"
        case tenants
        case selectedTenant = "selected_tenant"
    }
}

struct TenantOverviewItem: Decodable, Identifiable {
    let tenantSlug: String
    let tenantName: String
    let alarmIsActive: Bool
    let alarmMessage: String?
    let alarmIsTraining: Bool
    let lastAlertAt: String?
    let acknowledgementCount: Int
    let expectedUserCount: Int
    let acknowledgementRate: Double

    var id: String { tenantSlug }

    enum CodingKeys: String, CodingKey {
        case tenantSlug = "tenant_slug"
        case tenantName = "tenant_name"
        case alarmIsActive = "alarm_is_active"
        case alarmMessage = "alarm_message"
        case alarmIsTraining = "alarm_is_training"
        case lastAlertAt = "last_alert_at"
        case acknowledgementCount = "acknowledgement_count"
        case expectedUserCount = "expected_user_count"
        case acknowledgementRate = "acknowledgement_rate"
    }
}

struct DistrictOverviewResponse: Decodable {
    let tenantCount: Int
    let tenants: [TenantOverviewItem]

    enum CodingKeys: String, CodingKey {
        case tenantCount = "tenant_count"
        case tenants
    }
}

// MARK: - Phase 8: Production hardening models

struct PushDeliveryStatsResponse: Decodable {
    let total: Int
    let ok: Int
    let failed: Int
    let lastError: String?

    enum CodingKeys: String, CodingKey {
        case total, ok, failed
        case lastError = "last_error"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        total = try c.decodeIfPresent(Int.self, forKey: .total) ?? 0
        ok = try c.decodeIfPresent(Int.self, forKey: .ok) ?? 0
        failed = try c.decodeIfPresent(Int.self, forKey: .failed) ?? 0
        lastError = try c.decodeIfPresent(String.self, forKey: .lastError)
    }
}

struct AuditLogEntry: Decodable, Identifiable {
    let id: Int
    let timestamp: String
    let eventType: String
    let actorUserID: Int?
    let actorLabel: String?
    let targetType: String?
    let targetId: String?

    enum CodingKeys: String, CodingKey {
        case id, timestamp
        case eventType = "event_type"
        case actorUserID = "actor_user_id"
        case actorLabel = "actor_label"
        case targetType = "target_type"
        case targetId = "target_id"
    }
}

struct AuditLogResponse: Decodable {
    let events: [AuditLogEntry]
}

// MARK: - Onboarding models

struct ValidateCodeRequest: Encodable {
    let code: String
    let tenantSlug: String
    enum CodingKeys: String, CodingKey {
        case code
        case tenantSlug = "tenant_slug"
    }
}

struct ValidateCodeResponse: Decodable {
    let valid: Bool
    let role: String?
    let roleLabel: String?
    let title: String?
    let tenantSlug: String?
    let tenantName: String?
    let error: String?
    enum CodingKeys: String, CodingKey {
        case valid, role, title, error
        case roleLabel = "role_label"
        case tenantSlug = "tenant_slug"
        case tenantName = "tenant_name"
    }
}

struct CreateAccountFromCodeRequest: Encodable {
    let code: String
    let tenantSlug: String
    let name: String
    let loginName: String
    let password: String
    enum CodingKeys: String, CodingKey {
        case code, name, password
        case tenantSlug = "tenant_slug"
        case loginName = "login_name"
    }
}

struct ValidateSetupCodeRequest: Encodable {
    let code: String
}

struct ValidateSetupCodeResponse: Decodable {
    let valid: Bool
    let tenantSlug: String?
    let tenantName: String?
    let error: String?
    enum CodingKeys: String, CodingKey {
        case valid, error
        case tenantSlug = "tenant_slug"
        case tenantName = "tenant_name"
    }
}

struct CreateDistrictAdminRequest: Encodable {
    let code: String
    let name: String
    let loginName: String
    let password: String
    enum CodingKeys: String, CodingKey {
        case code, name, password
        case loginName = "login_name"
    }
}

// MARK: - Onboarding API methods (platform-level — use Config.backendBaseURL as baseURL)

extension APIClient {
    func validateInviteCode(code: String, tenantSlug: String) async throws -> ValidateCodeResponse {
        let url = baseURL.appendingPathComponent("onboarding/validate-code")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(ValidateCodeRequest(code: code, tenantSlug: tenantSlug))
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(ValidateCodeResponse.self, from: data)
    }

    func createAccountFromCode(code: String, tenantSlug: String, name: String, loginName: String, password: String) async throws -> ValidateCodeResponse {
        let url = baseURL.appendingPathComponent("onboarding/create-account")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(
            CreateAccountFromCodeRequest(code: code, tenantSlug: tenantSlug, name: name, loginName: loginName, password: password)
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(ValidateCodeResponse.self, from: data)
    }

    func validateSetupCode(code: String) async throws -> ValidateSetupCodeResponse {
        let url = baseURL.appendingPathComponent("onboarding/validate-setup-code")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(ValidateSetupCodeRequest(code: code))
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(ValidateSetupCodeResponse.self, from: data)
    }

    func createDistrictAdmin(code: String, name: String, loginName: String, password: String) async throws -> ValidateSetupCodeResponse {
        let url = baseURL.appendingPathComponent("onboarding/create-district-admin")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(
            CreateDistrictAdminRequest(code: code, name: name, loginName: loginName, password: password)
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(ValidateSetupCodeResponse.self, from: data)
    }
}
