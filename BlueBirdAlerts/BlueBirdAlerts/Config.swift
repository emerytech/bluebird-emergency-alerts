import Foundation

enum Config {
    static var backendBaseURL: URL {
        if let value = Bundle.main.object(forInfoDictionaryKey: "BACKEND_BASE_URL") as? String,
           let url = URL(string: value) {
            return url
        }

        return URL(string: "https://bluebird.ets3d.com")!
    }

    static var backendApiKey: String {
        if let value = Bundle.main.object(forInfoDictionaryKey: "BACKEND_API_KEY") as? String {
            return value
        }
        return ""
    }
}
