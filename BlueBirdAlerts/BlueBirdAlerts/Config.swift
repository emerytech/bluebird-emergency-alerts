import Foundation

enum Config {
    static var backendBaseURL: URL {
        if let value = Bundle.main.object(forInfoDictionaryKey: "BACKEND_BASE_URL") as? String,
           let url = URL(string: value) {
            return url
        }

        return URL(string: "http://10.7.0.171:8000")!
    }
}
