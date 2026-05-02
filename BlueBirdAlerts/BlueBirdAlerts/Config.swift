import Foundation

enum Config {
    static let backendBaseURL: URL = {
        if let value = Bundle.main.object(forInfoDictionaryKey: "BACKEND_BASE_URL") as? String,
           let url = URL(string: value) {
            return url
        }
        return URL(string: "https://bluebird-alerts.com")!
    }()

    static let backendApiKey: String = {
        if let value = Bundle.main.object(forInfoDictionaryKey: "BACKEND_API_KEY") as? String,
           !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           !value.contains("$(") {
            return value.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if let value = ProcessInfo.processInfo.environment["BACKEND_API_KEY"],
           !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return value.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return ""
    }()
}
