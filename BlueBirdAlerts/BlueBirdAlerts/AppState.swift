import Foundation
import Combine

@MainActor
final class AppState: ObservableObject {
    @Published var notificationPermissionGranted: Bool?
    @Published var deviceToken: String?
    @Published var usingLocalTestToken = false
    @Published var deviceRegistered = false
    @Published var backendReachable: Bool?
    @Published var registeredDeviceCount = 0
    @Published var providerCounts: [String: Int] = [:]
    @Published var recentAlerts: [String] = []
    @Published var lastStatus: String?
    @Published var lastError: String?
}
