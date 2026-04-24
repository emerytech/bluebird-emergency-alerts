import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var appState: AppState
    @State private var message: String = "Emergency alert. Please follow school procedures."
    @State private var showConfirm: Bool = false
    @State private var isSending: Bool = false
    @State private var showSettings: Bool = false
    @State private var showMessageAdminSheet: Bool = false
    @State private var adminMessage: String = ""
    @State private var isSendingAdminMessage: Bool = false

    private let api = APIClient(baseURL: Config.backendBaseURL)

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                VStack(spacing: 8) {
                    statusLine
                    tokenLine
                    if let status = appState.lastStatus {
                        Text(status)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                TextField("Alert message", text: $message, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(2...4)

                Button {
                    showConfirm = true
                } label: {
                    Text(isSending ? "Sending…" : "PANIC")
                        .font(.system(size: 32, weight: .heavy))
                        .frame(maxWidth: .infinity, minHeight: 120)
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
                .disabled(isSending)
                .alert("Send emergency alert?", isPresented: $showConfirm) {
                    Button("Cancel", role: .cancel) {}
                    Button("Send", role: .destructive) {
                        Task { await sendPanic() }
                    }
                } message: {
                    Text(message)
                }

                Button {
                    showMessageAdminSheet = true
                } label: {
                    Text("Message Admin")
                        .font(.headline)
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.bordered)
                .disabled(isSendingAdminMessage)

                if let err = appState.lastError {
                    Text(err)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                Spacer()
            }
            .padding()
            .navigationTitle("BlueBird Alerts")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Settings") {
                        showSettings = true
                    }
                }
            }
            .navigationDestination(isPresented: $showSettings) {
                SettingsView()
            }
            .sheet(isPresented: $showMessageAdminSheet) {
                NavigationStack {
                    VStack(spacing: 16) {
                        Text("Send a short message to school admins.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)

                        TextField("Need help in room 204", text: $adminMessage, axis: .vertical)
                            .textFieldStyle(.roundedBorder)
                            .lineLimit(2...4)

                        Button {
                            Task { await sendAdminMessage() }
                        } label: {
                            Text(isSendingAdminMessage ? "Sending…" : "Send")
                                .frame(maxWidth: .infinity, minHeight: 44)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(isSendingAdminMessage || adminMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                        Spacer()
                    }
                    .padding()
                    .navigationTitle("Message Admin")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .topBarLeading) {
                            Button("Cancel") {
                                showMessageAdminSheet = false
                            }
                        }
                    }
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: .deviceTokenUpdated)) { note in
                guard let token = note.userInfo?["token"] as? String else { return }
                appState.deviceToken = token
                Task { await registerDevice(token: token) }
            }
            .onReceive(NotificationCenter.default.publisher(for: .deviceTokenUpdateFailed)) { note in
                appState.lastError = note.userInfo?["error"] as? String
            }
        }
    }

    @ViewBuilder
    private var statusLine: some View {
        let permission = appState.notificationPermissionGranted
        let permissionText: String
        if permission == nil { permissionText = "Notifications: requesting…" }
        else if permission == true { permissionText = "Notifications: allowed" }
        else { permissionText = "Notifications: denied" }

        Text(permissionText)
            .font(.subheadline)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var tokenLine: some View {
        if let token = appState.deviceToken {
            Text("Device token: …\(token.suffix(8))")
                .font(.subheadline)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(appState.deviceRegistered ? "Backend: registered" : "Backend: not registered yet")
                .font(.subheadline)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            Text("Device token: waiting (real device required)")
                .font(.subheadline)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func registerDevice(token: String) async {
        do {
            let resp = try await api.registerDevice(token: token)
            appState.deviceRegistered = resp.registered || resp.deviceCount > 0
            appState.lastStatus = "Registered. Devices: \(resp.deviceCount)"
            appState.lastError = nil
        } catch {
            appState.deviceRegistered = false
            appState.lastError = "Register device failed: \(error.localizedDescription)"
        }
    }

    private func sendPanic() async {
        guard !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        isSending = true
        defer { isSending = false }

        do {
            let resp = try await api.panic(message: message)
            appState.lastStatus = "Alert #\(resp.alertId) sent. ok=\(resp.succeeded) failed=\(resp.failed)"
            appState.lastError = nil
        } catch {
            appState.lastError = "Panic failed: \(error.localizedDescription)"
        }
    }

    private func sendAdminMessage() async {
        let trimmed = adminMessage.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        isSendingAdminMessage = true
        defer { isSendingAdminMessage = false }

        do {
            let response = try await api.messageAdmin(message: trimmed)
            appState.lastStatus = "Message sent to admins at \(response.createdAt)"
            appState.lastError = nil
            adminMessage = ""
            showMessageAdminSheet = false
        } catch {
            appState.lastError = "Message admin failed: \(error.localizedDescription)"
        }
    }
}

private struct SettingsView: View {
    var body: some View {
        List {
            Section("Account") {
                Text("BlueBird Alerts")
                Text("Server: \(Config.backendBaseURL.absoluteString)")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
    }
}
