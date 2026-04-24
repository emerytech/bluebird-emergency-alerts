import Foundation

enum AppLabels {
    static let lockdown = "Lockdown"
    static let evacuation = "Evacuation"
    static let shelter = "Shelter"
    static let secure = "Secure Perimeter"
    static let requestHelp = "Request Help"

    static let activeHelpRequests = "Active Help Requests"
    static let noActiveHelpRequests = "No active help requests."
    static let forwardRequestHelp = "Forward Request Help"

    static func featureDisplayName(for rawValue: String) -> String {
        let normalized = rawValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        switch normalized {
        case "lockdown":
            return lockdown
        case "evacuation":
            return evacuation
        case "shelter":
            return shelter
        case "secure":
            return secure
        case "request_help", "request help", "team_assist", "team assist":
            return requestHelp
        default:
            return rawValue
        }
    }
}

