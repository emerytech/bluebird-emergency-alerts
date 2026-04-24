import SwiftUI
import LocalAuthentication

private let appBg = Color(red: 0.93, green: 0.96, blue: 1.0)
private let appBgDeep = Color(red: 0.86, green: 0.91, blue: 1.0)
private let surfaceMain = Color.white
private let textPrimary = Color(red: 0.06, green: 0.13, blue: 0.25)
private let textMuted = Color(red: 0.27, green: 0.34, blue: 0.48)
private let bluePrimary = Color(red: 0.11, green: 0.37, blue: 0.89)

private struct SafetyActionItem: Identifiable {
    let id: String
    let title: String
    let icon: String
    let color: Color
    let message: String
}

private let safetyActions: [SafetyActionItem] = [
    .init(id: "secure", title: "SECURE", icon: "hand.raised.fill", color: Color(red: 0.23, green: 0.66, blue: 0.95), message: "SECURE emergency initiated. Follow school secure procedures."),
    .init(id: "lockdown", title: "LOCKDOWN", icon: "lock.fill", color: Color(red: 0.94, green: 0.27, blue: 0.27), message: "LOCKDOWN emergency initiated. Follow lockdown procedures immediately."),
    .init(id: "evacuate", title: "EVACUATE", icon: "figure.walk.motion", color: Color(red: 0.52, green: 0.80, blue: 0.09), message: "EVACUATE emergency initiated. Move to evacuation locations now."),
    .init(id: "shelter", title: "SHELTER", icon: "house.fill", color: Color(red: 0.96, green: 0.62, blue: 0.12), message: "SHELTER emergency initiated. Move into shelter protocol."),
    .init(id: "hold", title: "HOLD", icon: "pause.fill", color: Color(red: 0.58, green: 0.20, blue: 0.92), message: "HOLD emergency initiated. Keep current position until cleared.")
]

struct ContentView: View {
    @EnvironmentObject private var appState: AppState
    @State private var message = "Emergency alert. Please follow school procedures."
    @State private var isSending = false
    @State private var isRegistering = false
    @State private var showSettings = false
    @State private var activeIncidents: [IncidentSummary] = []
    @State private var activeTeamAssists: [TeamAssistSummary] = []
    @State private var isRefreshingIncidentFeed = false
    @State private var pendingAction: SafetyActionItem?
    @State private var slideValue: Double = 0
    @State private var adminOutboundMessage = ""
    @State private var adminRecipients: [MessageRecipient] = []
    @State private var selectedRecipientID: Int?
    @State private var isSendingAdminMessage = false

    private var api: APIClient {
        APIClient(baseURL: appState.serverURL, apiKey: Config.backendApiKey)
    }

    private var isAdminSession: Bool {
        let role = appState.userRole.lowercased()
        return role == "admin" || role == "super_admin" || role == "platform_super_admin"
    }

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(colors: [appBg, appBgDeep], startPoint: .top, endPoint: .bottom)
                    .ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 14) {
                        headerCard
                        if let status = appState.lastStatus, !status.isEmpty {
                            flashBanner(message: status, isError: false)
                        }
                        if let error = appState.lastError, !error.isEmpty {
                            flashBanner(message: error, isError: true)
                        }
                        incidentsCard
                        safetyGrid
                        if isAdminSession {
                            adminMessageCard
                        }
                        customPanicCard
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 14)
                }
            }
            .navigationTitle("BlueBird Alerts")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Settings") { showSettings = true }
                        .fontWeight(.semibold)
                }
            }
            .navigationDestination(isPresented: $showSettings) {
                SettingsView()
            }
            .refreshable {
                await refreshIncidentFeed()
            }
            .task {
                await refreshIncidentFeed()
                if isAdminSession {
                    await loadAdminRecipients()
                }
                if let token = appState.deviceToken, appState.initialDeviceAuthUserID == nil {
                    appState.usingLocalTestToken = (token == localTestToken)
                    await registerDevice(token: token)
                }
                var tick = 0
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 10_000_000_000)
                    await refreshIncidentFeed()
                    tick += 1
                    if isAdminSession && tick % 6 == 0 {
                        await loadAdminRecipients()
                    }
                }
            }
        }
        .overlay {
            if let action = pendingAction {
                actionConfirmOverlay(action: action)
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

    private var headerCard: some View {
        card {
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 14)
                        .fill(Color.white)
                        .shadow(color: .black.opacity(0.06), radius: 6, x: 0, y: 2)
                    Image("BlueBirdLogo")
                        .resizable()
                        .scaledToFit()
                        .padding(4)
                }
                .frame(width: 48, height: 48)

                VStack(alignment: .leading, spacing: 3) {
                    Text("BlueBird Alerts")
                        .font(.headline)
                        .foregroundStyle(textPrimary)
                    Text(appState.userName.isEmpty ? "School Safety" : "\(appState.userName) • \(appState.userRole.capitalized)")
                        .font(.caption)
                        .foregroundStyle(textMuted)
                }
                Spacer()
                Circle()
                    .fill(backendStatusColor)
                    .frame(width: 10, height: 10)
            }
        }
    }

    private var incidentsCard: some View {
        card {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("Active Feed")
                        .font(.headline)
                        .foregroundStyle(textPrimary)
                    Spacer()
                    Button(isRefreshingIncidentFeed ? "Refreshing…" : "Refresh") {
                        Task { await refreshIncidentFeed() }
                    }
                    .disabled(isRefreshingIncidentFeed)
                    .font(.subheadline.weight(.semibold))
                }

                Text("Emergencies")
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(bluePrimary)
                if activeIncidents.isEmpty {
                    Text("No active incidents.")
                        .font(.subheadline)
                        .foregroundStyle(textMuted)
                } else {
                    ForEach(activeIncidents.prefix(6)) { incident in
                        feedRow(title: incident.type.uppercased(), subtitle: "by #\(incident.createdBy)")
                    }
                }

                Divider()

                Text("Team Assists")
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(Color(red: 0.06, green: 0.46, blue: 0.43))
                if activeTeamAssists.isEmpty {
                    Text("No active team assists.")
                        .font(.subheadline)
                        .foregroundStyle(textMuted)
                } else {
                    ForEach(activeTeamAssists.prefix(6)) { item in
                        feedRow(title: item.type, subtitle: "by #\(item.createdBy)")
                    }
                }
            }
        }
    }

    private var safetyGrid: some View {
        card {
            VStack(spacing: 16) {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 18) {
                    ForEach(safetyActions.prefix(4)) { action in
                        safetyActionButton(action: action)
                    }
                }
                safetyActionButton(action: safetyActions[4])
                    .frame(maxWidth: .infinity)
            }
        }
    }

    private var adminMessageCard: some View {
        card {
            VStack(alignment: .leading, spacing: 10) {
                Text("Admin Messaging")
                    .font(.headline)
                    .foregroundStyle(textPrimary)

                TextField("Message users...", text: $adminOutboundMessage, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(2...4)

                Menu {
                    Button("All users") { selectedRecipientID = nil }
                    ForEach(adminRecipients) { recipient in
                        Button(recipient.label) { selectedRecipientID = recipient.userID }
                    }
                } label: {
                    HStack {
                        Text("Recipients: \(recipientLabel)")
                            .foregroundStyle(textPrimary)
                        Spacer()
                        Image(systemName: "chevron.up.chevron.down")
                            .foregroundStyle(textMuted)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(Color.white)
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(Color.black.opacity(0.1), lineWidth: 1)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                }

                Button {
                    Task { await sendAdminMessage() }
                } label: {
                    Text(isSendingAdminMessage ? "Sending..." : "Send Message")
                        .frame(maxWidth: .infinity, minHeight: 42)
                }
                .buttonStyle(.borderedProminent)
                .tint(bluePrimary)
                .disabled(isSendingAdminMessage || adminOutboundMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }

    private var customPanicCard: some View {
        card {
            VStack(spacing: 10) {
                TextField("Custom emergency message", text: $message, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(2...4)

                Button {
                    Task { await authenticateThenSendPanic() }
                } label: {
                    Text(isSending ? "Sending..." : "Send Custom Panic")
                        .frame(maxWidth: .infinity, minHeight: 42)
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
                .disabled(isSending || message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }

    private func safetyActionButton(action: SafetyActionItem) -> some View {
        Button {
            pendingAction = action
            slideValue = 0
        } label: {
            VStack(spacing: 8) {
                ZStack {
                    Circle().fill(action.color)
                    Image(systemName: action.icon)
                        .foregroundStyle(.white)
                        .font(.system(size: 30, weight: .bold))
                }
                .frame(width: 122, height: 122)
                Text(action.title)
                    .font(.headline.weight(.bold))
                    .foregroundStyle(textPrimary)
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
    }

    private func actionConfirmOverlay(action: SafetyActionItem) -> some View {
        ZStack {
            Color.black.opacity(0.68).ignoresSafeArea()
            VStack(spacing: 18) {
                Spacer()
                Circle()
                    .fill(action.color)
                    .frame(width: 92, height: 92)
                    .overlay {
                        Image(systemName: action.icon)
                            .foregroundStyle(.white)
                            .font(.system(size: 34, weight: .bold))
                    }
                Text("\(action.title) EMERGENCY")
                    .font(.title3.weight(.heavy))
                    .foregroundStyle(.white)

                VStack(spacing: 8) {
                    Text("Slide to Initiate →")
                        .font(.headline.weight(.semibold))
                        .foregroundStyle(.white)
                    Slider(value: $slideValue, in: 0...1, onEditingChanged: { isEditing in
                        if !isEditing && slideValue < 0.97 {
                            withAnimation(.easeOut(duration: 0.15)) {
                                slideValue = 0
                            }
                        }
                    })
                        .tint(.white)
                        .onChange(of: slideValue) { _, newValue in
                            if newValue >= 0.97 {
                                Task { await initiateAction(action) }
                            }
                        }
                }
                .padding(14)
                .background(Color.white.opacity(0.2))
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .padding(.horizontal, 18)

                Button {
                    pendingAction = nil
                    slideValue = 0
                } label: {
                    VStack(spacing: 4) {
                        ZStack {
                            Circle().fill(Color.white.opacity(0.25))
                            Image(systemName: "xmark")
                                .font(.title2.weight(.bold))
                                .foregroundStyle(.white)
                        }
                        .frame(width: 66, height: 66)
                        Text("Cancel")
                            .font(.subheadline)
                            .foregroundStyle(.white)
                    }
                }
                .buttonStyle(.plain)
                Spacer()
            }
            .padding(.horizontal, 22)
        }
    }

    private func initiateAction(_ action: SafetyActionItem) async {
        pendingAction = nil
        slideValue = 0
        message = action.message
        await authenticateThenSendPanic()
    }

    private func flashBanner(message: String, isError: Bool) -> some View {
        Text(message)
            .font(.subheadline)
            .foregroundStyle(isError ? Color(red: 0.72, green: 0.08, blue: 0.08) : Color(red: 0.09, green: 0.42, blue: 0.20))
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(isError ? Color(red: 1.0, green: 0.91, blue: 0.91) : Color(red: 0.92, green: 0.97, blue: 0.92))
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private func card<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        content()
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(surfaceMain)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .shadow(color: .black.opacity(0.06), radius: 8, x: 0, y: 3)
    }

    private func feedRow(title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(textPrimary)
            Text(subtitle)
                .font(.caption)
                .foregroundStyle(textMuted)
        }
        .padding(.vertical, 4)
    }

    private var backendStatusColor: Color {
        if appState.backendReachable == true { return .green }
        if appState.backendReachable == false { return .red }
        return .gray
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

    private func refreshIncidentFeed() async {
        if isRefreshingIncidentFeed { return }
        isRefreshingIncidentFeed = true
        defer { isRefreshingIncidentFeed = false }

        do {
            async let incidentsResponse = api.activeIncidents()
            async let teamAssistResponse = api.activeTeamAssists()
            let (incidents, teamAssists) = try await (incidentsResponse, teamAssistResponse)
            activeIncidents = incidents.incidents
            activeTeamAssists = teamAssists.teamAssists
            appState.lastError = nil
            appState.backendReachable = true
        } catch {
            appState.backendReachable = false
            appState.lastError = "Incident feed refresh failed: \(error.localizedDescription)"
        }
    }

    private func registerDevice(token: String) async {
        isRegistering = true
        defer { isRegistering = false }

        do {
            let response = try await api.registerDevice(token: token)
            appState.deviceRegistered = response.deviceCount > 0
            appState.registeredDeviceCount = response.deviceCount
            appState.providerCounts = response.providerCounts
            if let currentUserID = appState.userID, !appState.userName.isEmpty {
                appState.markInitialDeviceAuthUserIfNeeded(userID: currentUserID, name: appState.userName)
            }
            if appState.initialDeviceAuthUserName.isEmpty {
                appState.lastStatus = "Registered with backend. Devices: \(response.deviceCount)"
            } else {
                appState.lastStatus = "Registered with backend. Linked to initial auth user: \(appState.initialDeviceAuthUserName)."
            }
            appState.lastError = nil
        } catch {
            appState.deviceRegistered = false
            appState.lastError = "Register device failed: \(error.localizedDescription)"
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
        } catch {
            appState.lastError = "Panic failed: \(error.localizedDescription)"
        }
    }

    private func authenticateThenSendPanic() async {
        guard await authenticateIfNeeded(reason: "Confirm emergency alert action.") else {
            appState.lastError = "Biometric verification was canceled."
            return
        }
        await sendPanic()
    }

    private var recipientLabel: String {
        if let selectedRecipientID, let recipient = adminRecipients.first(where: { $0.userID == selectedRecipientID }) {
            return recipient.label
        }
        return "All users"
    }

    private func loadAdminRecipients() async {
        guard isAdminSession else { return }
        do {
            adminRecipients = try await api.listMessageRecipients()
        } catch {
            if adminRecipients.isEmpty {
                appState.lastError = "Could not load user recipients for admin messaging."
            }
        }
    }

    private func sendAdminMessage() async {
        guard let adminUserID = appState.userID else {
            appState.lastError = "No admin session is active."
            return
        }
        let trimmed = adminOutboundMessage.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        isSendingAdminMessage = true
        defer { isSendingAdminMessage = false }

        do {
            let recipientIDs = selectedRecipientID.map { [$0] } ?? []
            let response = try await api.sendMessageFromAdmin(
                adminUserID: adminUserID,
                message: trimmed,
                recipientUserIDs: recipientIDs,
                sendToAll: selectedRecipientID == nil
            )
            adminOutboundMessage = ""
            appState.lastError = nil
            appState.lastStatus = "Message sent (\(response.sentCount)) to \(response.recipientScope)."
        } catch {
            appState.lastError = "Send message failed: \(error.localizedDescription)"
        }
    }

    private func authenticateIfNeeded(reason: String) async -> Bool {
        if !appState.biometricsAllowed { return true }
        let context = LAContext()
        var error: NSError?
        let policy: LAPolicy = .deviceOwnerAuthentication
        guard context.canEvaluatePolicy(policy, error: &error) else {
            return true
        }
        return await withCheckedContinuation { continuation in
            context.evaluatePolicy(policy, localizedReason: reason) { success, _ in
                continuation.resume(returning: success)
            }
        }
    }
}

private struct SettingsView: View {
    @EnvironmentObject private var appState: AppState
    @State private var isTestingBackend = false
    @State private var isRegistering = false
    @State private var isLoadingDebugData = false

    private var api: APIClient {
        APIClient(baseURL: appState.serverURL, apiKey: Config.backendApiKey)
    }

    var body: some View {
        List {
            Section("Account") {
                Text("BlueBird Alerts")
                if !appState.loginName.isEmpty {
                    Text("Login: \(appState.loginName)")
                }
                Text("Role: \(appState.userRole.capitalized)")
                Text("Server: \(appState.serverURL.absoluteString)")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                if !appState.initialDeviceAuthUserName.isEmpty {
                    Text("Initial device auth: \(appState.initialDeviceAuthUserName)")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            Section("Security") {
                Toggle("Biometrics Allowed", isOn: $appState.biometricsAllowed)
                Text("Require Face ID / Touch ID before sending emergency alerts.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            Section("Diagnostics (Temporary)") {
                Button(isTestingBackend ? "Testing..." : "Test Backend") {
                    Task { await testBackend() }
                }
                .disabled(isTestingBackend)

                Button(isLoadingDebugData ? "Refreshing..." : "Load Debug Data") {
                    Task { await loadDebugData() }
                }
                .disabled(isLoadingDebugData)

                if appState.deviceToken != nil {
                    Button(isRegistering ? "Registering..." : "Register Device") {
                        Task { await retryRegisterDevice() }
                    }
                    .disabled(isRegistering)
                }

                Button(isRegistering ? "Registering..." : localTestButtonTitle) {
                    Task { await useLocalTestDevice() }
                }
                .disabled(isRegistering)
            }
            Section {
                Button("Log Out", role: .destructive) {
                    appState.logout()
                }
            }
        }
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
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

    private func registerDevice(token: String) async {
        isRegistering = true
        defer { isRegistering = false }
        do {
            let response = try await api.registerDevice(token: token)
            appState.deviceRegistered = response.deviceCount > 0
            appState.registeredDeviceCount = response.deviceCount
            appState.providerCounts = response.providerCounts
            if let currentUserID = appState.userID, !appState.userName.isEmpty {
                appState.markInitialDeviceAuthUserIfNeeded(userID: currentUserID, name: appState.userName)
            }
            appState.lastStatus = "Registered with backend. Devices: \(response.deviceCount)"
            appState.lastError = nil
        } catch {
            appState.deviceRegistered = false
            appState.lastError = "Register device failed: \(error.localizedDescription)"
        }
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
}
