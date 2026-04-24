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
