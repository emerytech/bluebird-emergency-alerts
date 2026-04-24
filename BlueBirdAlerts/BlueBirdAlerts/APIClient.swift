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

    func panic(message: String) async throws -> PanicResponse {
        let url = baseURL.appendingPathComponent("panic")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(PanicRequest(message: message))

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

    func activeTeamAssists() async throws -> TeamAssistListResponse {
        let url = baseURL.appendingPathComponent("team-assist/active")
        var request = URLRequest(url: url)
        withAPIKey(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try requireSuccess(response: response, data: data)
        return try JSONDecoder().decode(TeamAssistListResponse.self, from: data)
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
    let message: String
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

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case status
        case createdBy = "created_by"
        case createdAt = "created_at"
    }
}
