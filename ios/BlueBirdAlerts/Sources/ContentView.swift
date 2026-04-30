import SwiftUI
import UIKit

// MARK: - Alert Type

private enum AlertType: String, CaseIterable, Identifiable {
    case lockdown  = "LOCKDOWN"
    case secure    = "SECURE"
    case evacuate  = "EVACUATE"
    case shelter   = "SHELTER"
    case hold      = "HOLD"

    var id: String { rawValue }

    var title: String { rawValue.capitalized }

    var description: String {
        switch self {
        case .lockdown:  return "External threat — lock all doors, stay inside."
        case .secure:    return "External threat — secure perimeter, continue inside."
        case .evacuate:  return "Leave the building via designated routes."
        case .shelter:   return "Shelter in place — move away from windows and doors."
        case .hold:      return "Stay in classrooms — do not enter hallways."
        }
    }

    var color: Color {
        switch self {
        case .lockdown:  return .red
        case .secure:    return .orange
        case .evacuate:  return Color(red: 0.1, green: 0.45, blue: 0.9)
        case .shelter:   return Color(red: 0.5, green: 0.2, blue: 0.8)
        case .hold:      return Color(red: 0.15, green: 0.55, blue: 0.3)
        }
    }

    var message: String {
        "\(rawValue): \(description)"
    }
}

// MARK: - ContentView

struct ContentView: View {
    @EnvironmentObject private var appState: AppState
    @State private var selectedAlertType: AlertType? = nil
    @State private var showAlertTypeSheet: Bool = false
    @State private var showConfirm: Bool = false
    @State private var isSending: Bool = false
    @State private var showSettings: Bool = false
    @State private var showMessageAdminSheet: Bool = false
    @State private var adminMessage: String = ""
    @State private var isSendingAdminMessage: Bool = false

    private let api = APIClient(baseURL: Config.backendBaseURL)

    private var holdSeconds: Double {
        Double(appState.tenantSettings.alerts.holdSeconds).clamped(to: 1...30)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
              VStack(spacing: 20) {
                if let alarm = appState.alarmState, alarm.isActive {
                    alarmBanner(alarm)
                }

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

                CircularEmergencyButton(
                    holdSeconds: holdSeconds,
                    enabled: !isSending,
                    onHoldComplete: {
                        let gen = UIImpactFeedbackGenerator(style: .heavy)
                        gen.impactOccurred()
                        showAlertTypeSheet = true
                    }
                )

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

                Spacer(minLength: 40)
              }
              .padding()
            }
            .navigationTitle("BlueBird Alerts")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Settings") { showSettings = true }
                }
            }
            .navigationDestination(isPresented: $showSettings) {
                SettingsView()
            }
            .sheet(isPresented: $showAlertTypeSheet) {
                AlertTypeSelectionSheet(onSelect: { type in
                    selectedAlertType = type
                    showAlertTypeSheet = false
                    showConfirm = true
                }, onCancel: {
                    showAlertTypeSheet = false
                })
            }
            .alert("Confirm \(selectedAlertType?.title ?? "Alert")", isPresented: $showConfirm) {
                Button("Cancel", role: .cancel) { selectedAlertType = nil }
                Button("Activate", role: .destructive) {
                    Task { await sendEmergency() }
                }
            } message: {
                if let type = selectedAlertType {
                    Text("Send a \(type.title) alert?\n\n\(type.description)\n\nThis will notify all registered devices immediately.")
                } else {
                    Text("Send emergency alert?")
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
                            Button("Cancel") { showMessageAdminSheet = false }
                        }
                    }
                }
            }
            .onAppear {
                Task { await appState.refreshAlarmState(client: api) }
            }
            .onReceive(NotificationCenter.default.publisher(for: .deviceTokenUpdated)) { note in
                guard let token = note.userInfo?["token"] as? String else { return }
                appState.deviceToken = token
                Task { await registerDevice(token: token) }
            }
            .onReceive(NotificationCenter.default.publisher(for: .deviceTokenUpdateFailed)) { note in
                appState.lastError = note.userInfo?["error"] as? String
            }
            .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)) { _ in
                Task { await appState.refreshAlarmState(client: api) }
            }
        }
    }

    @ViewBuilder
    private func alarmBanner(_ alarm: AlarmStatusResponse) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Text("⚠️")
                    .font(.title2)
                Text(alarm.isTraining ? "TRAINING DRILL" : "ALARM ACTIVE")
                    .font(.headline)
                    .fontWeight(.heavy)
                    .foregroundStyle(.white)
            }
            let triggeredBy = alarm.activatedByLabel ?? "Unknown"
            Text("Triggered by: \(triggeredBy)")
                .font(.subheadline)
                .fontWeight(.medium)
                .foregroundStyle(Color(red: 1, green: 0.8, blue: 0.8))
            if let at = alarm.activatedAt {
                Text(at)
                    .font(.caption)
                    .foregroundStyle(Color(red: 1, green: 0.75, blue: 0.75))
            }
            if let msg = alarm.message, !msg.isEmpty {
                Text(msg)
                    .font(.subheadline)
                    .foregroundStyle(.white)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(alarm.isTraining ? Color.orange : Color.red)
        .clipShape(RoundedRectangle(cornerRadius: 16))
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
        let message = selectedAlertType?.message ?? "EMERGENCY ALERT initiated. All users are being notified immediately."
        isSending = true
        defer {
            isSending = false
            selectedAlertType = nil
        }
        do {
            let resp = try await api.panic(message: message)
            appState.lastStatus = "Alert #\(resp.alertId) sent. ok=\(resp.succeeded) failed=\(resp.failed)"
            appState.lastError = nil
            let gen = UINotificationFeedbackGenerator()
            gen.notificationOccurred(.success)
        } catch {
            appState.lastError = "Alert failed: \(error.localizedDescription)"
            let gen = UINotificationFeedbackGenerator()
            gen.notificationOccurred(.error)
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

// MARK: - Alert Type Selection Sheet

private struct AlertTypeSelectionSheet: View {
    let onSelect: (AlertType) -> Void
    let onCancel: () -> Void

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Text("Select Alert Type")
                    .font(.title3)
                    .fontWeight(.bold)
                    .padding(.top, 8)
                    .padding(.bottom, 16)

                Text("Choose the type of emergency before activating.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 24)
                    .padding(.bottom, 20)

                VStack(spacing: 10) {
                    ForEach(AlertType.allCases) { type in
                        Button {
                            let gen = UIImpactFeedbackGenerator(style: .medium)
                            gen.impactOccurred()
                            onSelect(type)
                        } label: {
                            HStack(spacing: 14) {
                                Circle()
                                    .fill(type.color)
                                    .frame(width: 10, height: 10)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(type.title)
                                        .font(.headline)
                                        .foregroundStyle(.primary)
                                    Text(type.description)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(2)
                                }
                                Spacer()
                                Image(systemName: "chevron.right")
                                    .font(.caption)
                                    .foregroundStyle(.tertiary)
                            }
                            .padding(.horizontal, 18)
                            .padding(.vertical, 14)
                            .background(
                                RoundedRectangle(cornerRadius: 12)
                                    .fill(type.color.opacity(0.07))
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 12)
                                            .strokeBorder(type.color.opacity(0.25), lineWidth: 1)
                                    )
                            )
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 20)

                Spacer()
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel", role: .cancel) { onCancel() }
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}

// MARK: - Circular Hold Button

private struct CircularEmergencyButton: View {
    let holdSeconds: Double
    let enabled: Bool
    let onHoldComplete: () -> Void

    @State private var holdProgress: Double = 0
    @State private var holdTask: Task<Void, Never>? = nil
    @State private var buttonScale: CGFloat = 1.0
    @State private var isPressed: Bool = false

    private var ringColor: Color {
        holdProgress >= 0.8 ? .red : .white.opacity(0.9)
    }

    private var holdLabel: String {
        if holdProgress <= 0 || !isPressed { return "Hold to Activate" }
        if holdProgress >= 1.0 { return "Activating…" }
        if holdProgress >= 0.8 { return "Almost There…" }
        return "Keep Holding…"
    }

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                // Track ring
                Circle()
                    .stroke(Color.red.opacity(0.18), lineWidth: 8)
                    .frame(width: 144, height: 144)

                // Progress ring
                Circle()
                    .trim(from: 0, to: holdProgress)
                    .stroke(
                        ringColor,
                        style: StrokeStyle(lineWidth: 8, lineCap: .round)
                    )
                    .frame(width: 144, height: 144)
                    .rotationEffect(.degrees(-90))

                // Core button
                Circle()
                    .fill(Color.red)
                    .frame(width: 126, height: 126)
                    .shadow(color: .red.opacity(0.5), radius: 8 + holdProgress * 16)
                    .scaleEffect(buttonScale)
                    .overlay(
                        Text("🚨").font(.system(size: 44))
                    )
            }
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        guard enabled else { return }
                        if holdTask == nil { startHold() }
                    }
                    .onEnded { _ in
                        cancelHold()
                    }
            )
            .opacity(enabled ? 1.0 : 0.5)
            .allowsHitTesting(enabled)

            Text(holdLabel)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(.secondary)
        }
    }

    private func startHold() {
        isPressed = true
        withAnimation(.spring(duration: 0.15)) { buttonScale = 0.97 }
        holdTask = Task { @MainActor in
            let startTime = Date()
            while !Task.isCancelled {
                let elapsed = Date().timeIntervalSince(startTime)
                let progress = min(elapsed / holdSeconds, 1.0)
                holdProgress = progress
                if progress >= 1.0 {
                    withAnimation(.spring(duration: 0.2)) { buttonScale = 1.10 }
                    onHoldComplete()
                    return
                }
                try? await Task.sleep(nanoseconds: 16_000_000)
            }
            resetState()
        }
    }

    private func cancelHold() {
        holdTask?.cancel()
        holdTask = nil
        resetState()
    }

    private func resetState() {
        isPressed = false
        withAnimation(.spring(duration: 0.2)) {
            holdProgress = 0
            buttonScale = 1.0
        }
    }
}

// MARK: - Settings View

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

// MARK: - Comparable clamped helper

private extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self {
        min(max(self, range.lowerBound), range.upperBound)
    }
}
