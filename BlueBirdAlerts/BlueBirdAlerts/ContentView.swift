import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var appState: AppState
    @State private var message = "Emergency alert. Please follow school procedures."
    @State private var showConfirm = false
    @State private var isSending = false
    @State private var isTestingBackend = false
    @State private var isRegistering = false
    @State private var isLoadingDebugData = false

    private let api = APIClient(baseURL: Config.backendBaseURL)

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    VStack(spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .font(.system(size: 48))
                            .foregroundStyle(.red)

                        Text("BlueBird Alerts")
                            .font(.largeTitle)
                            .fontWeight(.bold)
                    }

                    VStack(spacing: 8) {
                        row("Backend", Config.backendBaseURL.absoluteString)
                        row("Backend status", backendStatus)
                        row("Notifications", notificationStatus)
                        tokenStatus
                        if !appState.providerCounts.isEmpty {
                            row("Providers", providerSummary)
                        }

                        if let status = appState.lastStatus {
                            Text(status)
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }

                    VStack(spacing: 10) {
                        Button {
                            Task { await testBackend() }
                        } label: {
                            Label(isTestingBackend ? "Testing..." : "Test Backend", systemImage: "network")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .disabled(isTestingBackend)

                        Button {
                            Task { await loadDebugData() }
                        } label: {
                            Label(isLoadingDebugData ? "Refreshing..." : "Load Debug Data", systemImage: "arrow.clockwise")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .disabled(isLoadingDebugData)

                        if appState.deviceToken != nil {
                            Button {
                                Task { await retryRegisterDevice() }
                            } label: {
                                Label(isRegistering ? "Registering..." : "Register Device", systemImage: "iphone.gen3.radiowaves.left.and.right")
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.bordered)
                            .disabled(isRegistering)
                        }

                        Button {
                            Task { await useLocalTestDevice() }
                        } label: {
                            Label(
                                isRegistering ? "Registering..." : localTestButtonTitle,
                                systemImage: localTestButtonIcon
                            )
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .disabled(isRegistering)
                    }

                    TextField("Alert message", text: $message, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(2...4)

                    Button {
                        showConfirm = true
                    } label: {
                        Text(isSending ? "Sending..." : "PANIC")
                            .font(.system(size: 34, weight: .heavy))
                            .frame(maxWidth: .infinity, minHeight: 128)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.red)
                    .disabled(isSending || message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .alert("Send emergency alert?", isPresented: $showConfirm) {
                        Button("Cancel", role: .cancel) {}
                        Button("Send", role: .destructive) {
                            Task { await sendPanic() }
                        }
                    } message: {
                        Text(message)
                    }

                    if let error = appState.lastError {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    if !appState.recentAlerts.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Recent Alerts")
                                .font(.headline)
                            ForEach(appState.recentAlerts, id: \.self) { alert in
                                Text(alert)
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding()
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .deviceTokenUpdated)) { note in
            guard let token = note.userInfo?["token"] as? String else { return }
            appState.deviceToken = token
            appState.usingLocalTestToken = false
            Task { await registerDevice(token: token) }
        }
        .onReceive(NotificationCenter.default.publisher(for: .deviceTokenUpdateFailed)) { note in
            appState.lastError = note.userInfo?["error"] as? String
        }
    }

    private var backendStatus: String {
        if appState.backendReachable == nil { return "not tested" }
        return appState.backendReachable == true ? "reachable" : "unreachable"
    }

    private var notificationStatus: String {
        if appState.notificationPermissionGranted == nil { return "requesting" }
        return appState.notificationPermissionGranted == true ? "allowed" : "denied"
    }

    private var providerSummary: String {
        appState.providerCounts
            .sorted { $0.key < $1.key }
            .map { "\($0.key): \($0.value)" }
            .joined(separator: ", ")
    }

    private var localTestToken: String {
        "feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface"
    }

    private var localTestButtonTitle: String {
        #if targetEnvironment(simulator)
        return "Use Simulator Token"
        #else
        return "Use Local Test Device"
        #endif
    }

    private var localTestButtonIcon: String {
        #if targetEnvironment(simulator)
        return "desktopcomputer"
        #else
        return "iphone"
        #endif
    }

    @ViewBuilder
    private var tokenStatus: some View {
        if let token = appState.deviceToken {
            row("Device token", "...\(token.suffix(8))")
            row("Token source", appState.usingLocalTestToken ? "local test" : "apns")
            row("Registration", appState.deviceRegistered ? "registered" : "not registered")
            if appState.registeredDeviceCount > 0 {
                row("Registered devices", "\(appState.registeredDeviceCount)")
            }
        } else {
            row("Device token", "waiting")
        }
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
                .foregroundStyle(.secondary)
            Spacer(minLength: 12)
            Text(value)
                .multilineTextAlignment(.trailing)
        }
        .font(.subheadline)
    }

    private func registerDevice(token: String) async {
        isRegistering = true
        defer { isRegistering = false }

        do {
            let response = try await api.registerDevice(token: token)
            appState.deviceRegistered = response.deviceCount > 0
            appState.registeredDeviceCount = response.deviceCount
            appState.providerCounts = response.providerCounts
            appState.lastStatus = "Registered with backend. Devices: \(response.deviceCount)"
            appState.lastError = nil
        } catch {
            appState.deviceRegistered = false
            appState.lastError = "Register device failed: \(error.localizedDescription)"
        }
    }

    private func retryRegisterDevice() async {
        guard let token = appState.deviceToken else {
            appState.lastError = "No APNs device token yet. Run on a real iPhone and allow notifications."
            return
        }
        appState.usingLocalTestToken = (token == localTestToken)
        await registerDevice(token: token)
    }

    private func useLocalTestDevice() async {
        appState.deviceToken = localTestToken
        appState.usingLocalTestToken = true
        await registerDevice(token: localTestToken)
    }

    private func testBackend() async {
        isTestingBackend = true
        defer { isTestingBackend = false }

        do {
            let response = try await api.health()
            appState.backendReachable = response.ok
            appState.lastStatus = response.ok ? "Backend reachable." : "Backend returned an unhealthy response."
            appState.lastError = nil
        } catch {
            appState.backendReachable = false
            appState.lastError = "Backend test failed: \(error.localizedDescription)"
        }
    }

    private func loadDebugData() async {
        isLoadingDebugData = true
        defer { isLoadingDebugData = false }

        do {
            async let devices = api.devices()
            async let alerts = api.alerts(limit: 5)
            let (deviceResponse, alertsResponse) = try await (devices, alerts)

            appState.registeredDeviceCount = deviceResponse.deviceCount
            appState.providerCounts = deviceResponse.providerCounts
            appState.recentAlerts = alertsResponse.alerts.map { "#\($0.alertId) \($0.message)" }
            appState.lastStatus = "Loaded backend debug data."
            appState.lastError = nil
        } catch {
            appState.lastError = "Load debug data failed: \(error.localizedDescription)"
        }
    }

    private func sendPanic() async {
        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        isSending = true
        defer { isSending = false }

        do {
            let response = try await api.panic(message: trimmed)
            appState.registeredDeviceCount = response.deviceCount
            appState.lastStatus = "Alert #\(response.alertId): attempted \(response.attempted), ok \(response.succeeded), failed \(response.failed)"
            appState.lastError = response.apnsConfigured ? nil : "Backend accepted the alert, but APNs is not configured yet."
            await loadDebugData()
        } catch {
            appState.lastError = "Panic failed: \(error.localizedDescription)"
        }
    }
}
