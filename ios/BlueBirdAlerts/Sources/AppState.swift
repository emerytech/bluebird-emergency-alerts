import Foundation

@MainActor
final class AppState: ObservableObject {
    @Published var notificationPermissionGranted: Bool? = nil
    @Published var deviceToken: String? = nil
    @Published var deviceRegistered: Bool = false
    @Published var lastStatus: String? = nil
    @Published var lastError: String? = nil
}
