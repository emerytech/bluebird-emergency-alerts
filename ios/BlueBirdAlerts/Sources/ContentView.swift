import SwiftUI

private enum EmergencyType: String, CaseIterable, Identifiable {
    case secure, lockdown, evacuate, shelter, hold

    var id: String { rawValue }

    var title: String {
        switch self {
        case .secure:   return "Secure"
        case .lockdown: return "Lockdown"
        case .evacuate: return "Evacuate"
        case .shelter:  return "Shelter in Place"
        case .hold:     return "Hold"
        }
    }

    var symbol: String {
        switch self {
        case .secure:   return "🔐"
        case .lockdown: return "🔒"
        case .evacuate: return "🚶"
        case .shelter:  return "🏠"
        case .hold:     return "⏸"
        }
    }

    var message: String {
        switch self {
        case .secure:   return "SECURE emergency initiated. Follow school secure procedures."
        case .lockdown: return "LOCKDOWN emergency initiated. Follow lockdown procedures immediately."
        case .evacuate: return "EVACUATE emergency initiated. Move to evacuation locations now."
        case .shelter:  return "SHELTER emergency initiated. Move into shelter protocol."
        case .hold:     return "HOLD emergency initiated. Keep current position until cleared."
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var appState: AppState
    @State private var showEmergencyTypeSheet: Bool = false
    @State private var pendingEmergencyMessage: String = ""
    @State private var showConfirm: Bool = false
    @State private var isSending: Bool = false
    @State private var showSettings: Bool = false
    @State private var showMessageAdminSheet: Bool = false
    @State private var adminMessage: String = ""
    @State private var isSendingAdminMessage: Bool = false

    private let api = APIClient(baseURL: Config.backendBaseURL)
    // TODO(iOS parity): Add "Request Quiet Period" flow matching Android:
    // large button -> dark slide-to-confirm overlay -> reason/context text input below slider.

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

                Button {
                    showEmergencyTypeSheet = true
                } label: {
                    Label(isSending ? "Sending…" : "Activate Emergency", systemImage: "exclamationmark.triangle.fill")
                        .font(.system(size: 22, weight: .heavy))
                        .frame(maxWidth: .infinity, minHeight: 100)
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
                .disabled(isSending)
                .alert("Send emergency alert?", isPresented: $showConfirm) {
                    Button("Cancel", role: .cancel) {}
                    Button("Send", role: .destructive) {
                        Task { await sendEmergency() }
                    }
                } message: {
                    Text(pendingEmergencyMessage)
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
            .sheet(isPresented: $showEmergencyTypeSheet) {
                NavigationStack {
                    List {
                        Section {
                            ForEach(EmergencyType.allCases) { type in
                                Button {
                                    pendingEmergencyMessage = type.message
                                    showEmergencyTypeSheet = false
                                    showConfirm = true
                                } label: {
                                    HStack(spacing: 16) {
                                        Text(type.symbol)
                                            .font(.title2)
                                        Text(type.title)
                                            .font(.headline)
                                            .foregroundStyle(.primary)
                                    }
                                    .padding(.vertical, 4)
                                }
                                .tint(.primary)
                            }
                        } header: {
                            Text("Select Emergency Type")
                        }
                    }
                    .navigationTitle("Activate Emergency")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .topBarLeading) {
                            Button("Cancel") {
                                showEmergencyTypeSheet = false
                            }
                        }
                    }
                }
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

    private func sendEmergency() async {
        guard !pendingEmergencyMessage.isEmpty else { return }
        isSending = true
        defer { isSending = false }

        do {
            let resp = try await api.panic(message: pendingEmergencyMessage)
            appState.lastStatus = "Alert #\(resp.alertId) sent. ok=\(resp.succeeded) failed=\(resp.failed)"
            appState.lastError = nil
        } catch {
            appState.lastError = "Alert failed: \(error.localizedDescription)"
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
