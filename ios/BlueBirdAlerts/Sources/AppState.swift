import Foundation

@MainActor
final class AppState: ObservableObject {
    @Published var notificationPermissionGranted: Bool? = nil
    @Published var deviceToken: String? = nil
    @Published var deviceRegistered: Bool = false
    @Published var lastStatus: String? = nil
    @Published var lastError: String? = nil

    /// Effective tenant settings, populated once at startup. Falls back to safe
    /// defaults until the first successful fetch so the UI always has values.
    @Published var tenantSettings: TenantSettings = .defaults

    /// Fetch settings from the backend and update tenantSettings.
    /// Silently ignores errors — defaults remain in place.
    func loadTenantSettings(client: APIClient) async {
        do {
            let settings = try await client.fetchTenantSettings()
            tenantSettings = settings
        } catch {
            // Non-fatal: safe defaults already set.
        }
    }
}
