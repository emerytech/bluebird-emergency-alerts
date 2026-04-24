import Foundation

enum AppLabels {
    static let keyLockdown = "lockdown"
    static let keyEvacuation = "evacuation"
    static let keyShelter = "shelter"
    static let keySecure = "secure"
    static let keyRequestHelp = "request_help"

    static let lockdown = "Lockdown"
    static let evacuation = "Evacuation"
    static let shelter = "Shelter"
    static let secure = "Secure Perimeter"
    static let requestHelp = "Request Help"

    static let activeHelpRequests = "Active Help Requests"
    static let noActiveHelpRequests = "No active help requests."
    static let forwardRequestHelp = "Forward Request Help"

    static let defaultFeatureLabels: [String: String] = [
        keyLockdown: lockdown,
        keyEvacuation: evacuation,
        keyShelter: shelter,
        keySecure: secure,
        keyRequestHelp: requestHelp,
    ]

    static func normalizeFeatureKey(_ value: String) -> String {
        let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        switch normalized {
        case "team_assist", "team assist", "request help":
            return keyRequestHelp
        default:
            return normalized
        }
    }

    static func labelForFeatureKey(_ key: String, overrides: [String: String] = defaultFeatureLabels) -> String {
        let normalized = normalizeFeatureKey(key)
        return overrides[normalized] ?? defaultFeatureLabels[normalized] ?? key
    }

    static func featureDisplayName(for rawValue: String, overrides: [String: String] = defaultFeatureLabels) -> String {
        let normalized = normalizeFeatureKey(rawValue)
        switch normalized {
        case keyLockdown, keyEvacuation, keyShelter, keySecure, keyRequestHelp:
            return labelForFeatureKey(normalized, overrides: overrides)
        default:
            return rawValue
        }
    }
}
