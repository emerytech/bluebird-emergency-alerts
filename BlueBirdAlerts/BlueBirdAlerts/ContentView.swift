import SwiftUI
import LocalAuthentication
import UIKit

private let appBg = Color(red: 0.93, green: 0.96, blue: 1.0)
private let appBgDeep = Color(red: 0.86, green: 0.91, blue: 1.0)
private let surfaceMain = Color.white
private let textPrimary = Color(red: 0.06, green: 0.13, blue: 0.25)
private let textMuted = Color(red: 0.27, green: 0.34, blue: 0.48)
private let bluePrimary = Color(red: 0.11, green: 0.37, blue: 0.89)
private let fieldDarkBg = Color(red: 0.22, green: 0.25, blue: 0.31)
private let fieldDarkBorder = Color.white.opacity(0.12)
private let placeholderMuted = Color(red: 0.62, green: 0.67, blue: 0.76)

private struct PressableScaleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.985 : 1.0)
            .animation(.easeOut(duration: 0.14), value: configuration.isPressed)
    }
}

private struct SafetyActionItem: Identifiable {
    let id: String
    let title: String
    let icon: String
    let color: Color
    let message: String
}

private func buildSafetyActions(featureLabels: [String: String]) -> [SafetyActionItem] {
    [
        .init(id: "secure", title: AppLabels.labelForFeatureKey(AppLabels.keySecure, overrides: featureLabels).uppercased(), icon: "hand.raised.fill", color: Color(red: 0.23, green: 0.66, blue: 0.95), message: "SECURE emergency initiated. Follow school secure procedures."),
        .init(id: "lockdown", title: AppLabels.labelForFeatureKey(AppLabels.keyLockdown, overrides: featureLabels).uppercased(), icon: "lock.fill", color: Color(red: 0.94, green: 0.27, blue: 0.27), message: "LOCKDOWN emergency initiated. Follow lockdown procedures immediately."),
        .init(id: "evacuation", title: AppLabels.labelForFeatureKey(AppLabels.keyEvacuation, overrides: featureLabels).uppercased(), icon: "figure.walk.motion", color: Color(red: 0.52, green: 0.80, blue: 0.09), message: "EVACUATE emergency initiated. Move to evacuation locations now."),
        .init(id: "shelter", title: AppLabels.labelForFeatureKey(AppLabels.keyShelter, overrides: featureLabels).uppercased(), icon: "house.fill", color: Color(red: 0.96, green: 0.62, blue: 0.12), message: "SHELTER emergency initiated. Move into shelter protocol."),
        .init(id: "hold", title: "HOLD", icon: "pause.fill", color: Color(red: 0.58, green: 0.20, blue: 0.92), message: "HOLD emergency initiated. Keep current position until cleared."),
    ]
}
private let teamAssistTypes = [
    "Fight in Progress",
    "Irate Parent",
    "Medical Assistance",
    "Principal to Front Office",
    "Suspicious Activity",
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
    @State private var selectedRecipientIDs: Set<Int> = []
    @State private var showRecipientSheet = false
    @State private var isSendingAdminMessage = false
    @State private var userMessageToAdmin = ""
    @State private var isSendingUserMessage = false
    @State private var showTeamAssistPicker = false
    @State private var showMessagingCenter = false
    @State private var showQuietPeriodCenter = false
    @State private var quietPeriodReason = ""
    @State private var isSubmittingQuickAction = false
    @State private var teamAssistForwardRecipients: [MessageRecipient] = []
    @State private var forwardingTeamAssist: TeamAssistSummary?
    @State private var isUpdatingTeamAssist = false
    @State private var adminPromptRequestHelpID: Int?
    @State private var dismissedAdminPromptRequestHelpID: Int?
    @State private var adminQuietPeriodRequests: [QuietPeriodAdminRequest] = []
    @State private var isUpdatingQuietPeriodRequests = false
    @State private var featureLabels: [String: String] = AppLabels.defaultFeatureLabels

    private var api: APIClient {
        APIClient(baseURL: appState.serverURL, apiKey: Config.backendApiKey)
    }

    private var isAdminSession: Bool {
        let role = appState.userRole.lowercased()
        return role == "admin" || role == "super_admin" || role == "platform_super_admin"
    }

    private var safetyActions: [SafetyActionItem] {
        buildSafetyActions(featureLabels: featureLabels)
    }

    private var requestHelpLabel: String {
        AppLabels.labelForFeatureKey(AppLabels.keyRequestHelp, overrides: featureLabels)
    }

    private var activeRequestHelpLabel: String {
        if requestHelpLabel.caseInsensitiveCompare(AppLabels.requestHelp) == .orderedSame {
            return AppLabels.activeHelpRequests
        }
        return "Active \(requestHelpLabel)"
    }

    private var noActiveRequestHelpLabel: String {
        if requestHelpLabel.caseInsensitiveCompare(AppLabels.requestHelp) == .orderedSame {
            return AppLabels.noActiveHelpRequests
        }
        return "No active \(requestHelpLabel.lowercased())."
    }

    private var adminPromptRequestHelpItem: TeamAssistSummary? {
        guard let id = adminPromptRequestHelpID else { return nil }
        return activeTeamAssists.first(where: { $0.id == id })
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
                        dashboardTabsCard
                        customPanicCard
                        supportActionsCard
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 14)
                }
            }
            .simultaneousGesture(
                TapGesture().onEnded {
                    dismissKeyboard()
                }
            )
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
            .navigationDestination(isPresented: $showMessagingCenter) {
                messagingCenterPage
            }
            .navigationDestination(isPresented: $showQuietPeriodCenter) {
                quietPeriodCenterPage
            }
            .refreshable {
                await refreshIncidentFeed()
            }
            .task {
                await loadFeatureLabels()
                await refreshIncidentFeed()
                if isAdminSession {
                    await loadAdminRecipients()
                    await loadTeamAssistForwardRecipients()
                    await loadAdminQuietPeriodRequests()
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
                    if tick % 18 == 0 {
                        await loadFeatureLabels()
                    }
                    if isAdminSession && tick % 6 == 0 {
                        await loadAdminRecipients()
                        await loadTeamAssistForwardRecipients()
                        await loadAdminQuietPeriodRequests()
                    }
                }
            }
            .sheet(isPresented: $showRecipientSheet) {
                RecipientSelectionSheet(
                    recipients: adminRecipients,
                    selectedRecipientIDs: $selectedRecipientIDs
                )
            }
            .sheet(item: $forwardingTeamAssist) { teamAssist in
                TeamAssistForwardSheet(
                    teamAssist: teamAssist,
                    requestHelpLabel: requestHelpLabel,
                    recipients: teamAssistForwardRecipients.filter { $0.userID != appState.userID },
                    isBusy: isUpdatingTeamAssist,
                    onSelect: { recipient in
                        Task { await forwardTeamAssist(teamAssist, to: recipient) }
                    }
                )
            }
            .confirmationDialog(requestHelpLabel, isPresented: $showTeamAssistPicker, titleVisibility: .visible) {
                ForEach(teamAssistTypes, id: \.self) { type in
                    Button(type) {
                        Task { await submitTeamAssist(type: type) }
                    }
                }
                Button("Cancel", role: .cancel) {}
            }
            .sheet(
                isPresented: Binding(
                    get: { isAdminSession && adminPromptRequestHelpItem != nil },
                    set: { presented in
                        if !presented {
                            if let current = adminPromptRequestHelpID {
                                dismissedAdminPromptRequestHelpID = current
                            }
                            adminPromptRequestHelpID = nil
                        }
                    }
                )
            ) {
                if let promptItem = adminPromptRequestHelpItem {
                    AdminRequestHelpPromptSheet(
                        requestHelpLabel: requestHelpLabel,
                        item: promptItem,
                        isBusy: isUpdatingTeamAssist,
                        onAcknowledge: {
                            dismissedAdminPromptRequestHelpID = promptItem.id
                            adminPromptRequestHelpID = nil
                            Task { await applyTeamAssistAction(promptItem, action: "acknowledge") }
                        },
                        onResponding: {
                            dismissedAdminPromptRequestHelpID = promptItem.id
                            adminPromptRequestHelpID = nil
                            Task { await applyTeamAssistAction(promptItem, action: "responding") }
                        },
                        onLater: {
                            dismissedAdminPromptRequestHelpID = promptItem.id
                            adminPromptRequestHelpID = nil
                        }
                    )
                    .presentationDetents([.medium])
                    .presentationDragIndicator(.visible)
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

                Text(activeRequestHelpLabel)
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(Color(red: 0.06, green: 0.46, blue: 0.43))
                if activeTeamAssists.isEmpty {
                    Text(noActiveRequestHelpLabel)
                        .font(.subheadline)
                        .foregroundStyle(textMuted)
                } else {
                    ForEach(activeTeamAssists.prefix(6)) { item in
                        teamAssistFeedRow(item: item)
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

    private var dashboardTabsCard: some View {
        card {
            VStack(alignment: .leading, spacing: 10) {
                Text("Dashboard")
                    .font(.headline)
                    .foregroundStyle(textPrimary)
                HStack(spacing: 10) {
                    Button {
                        showMessagingCenter = true
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "message.fill")
                            Text("Messaging")
                        }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, minHeight: 46)
                        .background(bluePrimary)
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                    .shadow(color: bluePrimary.opacity(0.16), radius: 8, x: 0, y: 3)
                    .buttonStyle(PressableScaleButtonStyle())

                    Button {
                        showQuietPeriodCenter = true
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "moon.zzz.fill")
                            Text("Quiet Period")
                        }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, minHeight: 46)
                        .background(Color(red: 0.56, green: 0.23, blue: 0.92))
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                    .shadow(color: Color(red: 0.56, green: 0.23, blue: 0.92).opacity(0.16), radius: 8, x: 0, y: 3)
                    .buttonStyle(PressableScaleButtonStyle())
                }
            }
        }
    }

    private var adminMessageCard: some View {
        card {
            VStack(alignment: .leading, spacing: 14) {
                Text("Admin Messaging")
                    .font(.headline)
                    .foregroundStyle(textPrimary)

                TextField("", text: $adminOutboundMessage, prompt: Text("Message users...").foregroundStyle(placeholderMuted), axis: .vertical)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .background(fieldDarkBg)
                    .overlay(
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .stroke(fieldDarkBorder, lineWidth: 1)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .lineLimit(2...4)

                Button {
                    showRecipientSheet = true
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Recipients")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(textMuted)
                            Text(recipientLabel)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(textPrimary)
                        }
                        Spacer()
                        Image(systemName: "person.2.badge.gearshape")
                            .foregroundStyle(bluePrimary)
                        Image(systemName: "chevron.right")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(textPrimary)
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .background(Color.white)
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(Color.black.opacity(0.1), lineWidth: 1)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                .buttonStyle(.plain)

                VStack(alignment: .leading, spacing: 8) {
                    Text("Message Preview")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(textMuted)
                    Text(adminOutboundMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "Type a message to preview." : adminOutboundMessage)
                        .font(.subheadline)
                        .foregroundStyle(Color(red: 0.93, green: 0.95, blue: 0.98))
                        .lineSpacing(2)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 12)
                        .background(fieldDarkBg)
                        .overlay(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .stroke(fieldDarkBorder, lineWidth: 1)
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }

                Button {
                    Task { await sendAdminMessage() }
                } label: {
                    Text(isSendingAdminMessage ? "Sending..." : "Send Message")
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, minHeight: 46)
                        .background(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .fill(bluePrimary.opacity(canSendAdminMessage ? 1.0 : 0.55))
                        )
                }
                .buttonStyle(PressableScaleButtonStyle())
                .shadow(color: canSendAdminMessage ? bluePrimary.opacity(0.28) : .clear, radius: 8, x: 0, y: 3)
                .disabled(!canSendAdminMessage)
            }
        }
    }

    private var adminQuietPeriodRequestsCard: some View {
        card {
            VStack(alignment: .leading, spacing: 12) {
                Text("Quiet Period Requests")
                    .font(.headline)
                    .foregroundStyle(textPrimary)

                if adminQuietPeriodRequests.isEmpty {
                    Text("No pending quiet period requests.")
                        .font(.subheadline)
                        .foregroundStyle(textMuted)
                } else {
                    ForEach(adminQuietPeriodRequests.prefix(10)) { item in
                        VStack(alignment: .leading, spacing: 8) {
                            Text("\(item.userName ?? "User #\(item.userID)") • \((item.userRole ?? "user").capitalized)")
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(textPrimary)
                            Text("Requested: \(item.requestedAt)")
                                .font(.caption)
                                .foregroundStyle(textMuted)
                            if let reason = item.reason, !reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                Text("Reason: \(reason)")
                                    .font(.caption)
                                    .foregroundStyle(textMuted)
                            }
                            HStack(spacing: 10) {
                                Button {
                                    Task { await approveQuietPeriodRequest(item) }
                                } label: {
                                    Text("Approve")
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(.white)
                                        .padding(.horizontal, 12)
                                        .padding(.vertical, 8)
                                        .background(Color(red: 0.10, green: 0.40, blue: 0.20))
                                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                }
                                .disabled(isUpdatingQuietPeriodRequests || item.status.lowercased() != "pending")

                                Button {
                                    Task { await denyQuietPeriodRequest(item) }
                                } label: {
                                    Text("Deny")
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(.white)
                                        .padding(.horizontal, 12)
                                        .padding(.vertical, 8)
                                        .background(Color(red: 0.72, green: 0.11, blue: 0.11))
                                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                }
                                .disabled(isUpdatingQuietPeriodRequests || item.status.lowercased() != "pending")
                            }
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(red: 0.97, green: 0.98, blue: 1.0))
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                }
            }
        }
    }

    private var customPanicCard: some View {
        card {
            VStack(spacing: 14) {
                TextField("", text: $message, prompt: Text("Custom emergency message").foregroundStyle(placeholderMuted), axis: .vertical)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .background(fieldDarkBg)
                    .overlay(
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .stroke(fieldDarkBorder, lineWidth: 1)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .lineLimit(2...4)

                Button {
                    Task { await authenticateThenSendPanic() }
                } label: {
                    Text(isSending ? "Sending..." : "Send Custom Panic")
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, minHeight: 46)
                        .background(
                            LinearGradient(
                                colors: [Color(red: 0.93, green: 0.25, blue: 0.25), Color(red: 0.80, green: 0.13, blue: 0.13)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                .buttonStyle(PressableScaleButtonStyle())
                .shadow(color: Color.red.opacity(0.24), radius: 8, x: 0, y: 3)
                .disabled(isSending || message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }

    private var supportActionsCard: some View {
        card {
            VStack(spacing: DSSpacing.md) {
                PrimaryButton(
                    isSubmittingQuickAction ? "Submitting..." : requestHelpLabel,
                    isLoading: isSubmittingQuickAction,
                    isEnabled: !isSubmittingQuickAction
                ) {
                    showTeamAssistPicker = true
                }
            }
        }
    }

    private var messagingCenterPage: some View {
        ScrollView {
            VStack(spacing: 14) {
                if isAdminSession {
                    adminMessageCard
                } else {
                    userMessageCard
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
        }
        .background(
            LinearGradient(colors: [appBg, appBgDeep], startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
        )
        .navigationTitle("Messaging")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var quietPeriodCenterPage: some View {
        ScrollView {
            VStack(spacing: 14) {
                card {
                    SectionContainer("Request Quiet Period") {
                        Text("Share optional context for approvers.")
                            .font(.subheadline)
                            .foregroundStyle(DSColor.textSecondary)
                        TextInput(
                            text: $quietPeriodReason,
                            placeholder: "Reason (optional)",
                            axis: .vertical
                        )
                        PrimaryButton(
                            isSubmittingQuickAction ? "Submitting..." : "Submit Request",
                            isLoading: isSubmittingQuickAction,
                            isEnabled: !isSubmittingQuickAction
                        ) {
                            Task { await submitQuietPeriodRequest() }
                        }
                    }
                }
                if isAdminSession {
                    adminQuietPeriodRequestsCard
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
        }
        .background(
            LinearGradient(colors: [appBg, appBgDeep], startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
        )
        .navigationTitle("Quiet Period")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var userMessageCard: some View {
        card {
            VStack(alignment: .leading, spacing: 14) {
                Text("Message Admin")
                    .font(.headline)
                    .foregroundStyle(textPrimary)
                TextField("", text: $userMessageToAdmin, prompt: Text("Message admins...").foregroundStyle(placeholderMuted), axis: .vertical)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .background(fieldDarkBg)
                    .overlay(
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .stroke(fieldDarkBorder, lineWidth: 1)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .lineLimit(2...4)
                Button {
                    Task { await sendMessageToAdminFromUser() }
                } label: {
                    Text(isSendingUserMessage ? "Sending..." : "Send Message")
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, minHeight: 46)
                        .background(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .fill(bluePrimary.opacity(userMessageToAdmin.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.55 : 1.0))
                        )
                }
                .buttonStyle(PressableScaleButtonStyle())
                .disabled(isSendingUserMessage || userMessageToAdmin.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
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
                    slideToInitiateControl(action: action)
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

    private func slideToInitiateControl(action: SafetyActionItem) -> some View {
        GeometryReader { geo in
            let knobSize: CGFloat = 56
            let horizontalInset: CGFloat = 6
            let maxOffset = max(0, geo.size.width - knobSize - horizontalInset * 2)

            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.white.opacity(0.22))

                Text("Slide to Initiate")
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(.white.opacity(0.95))
                    .frame(maxWidth: .infinity)
                    .padding(.leading, 34)
                    .padding(.trailing, 12)

                Circle()
                    .fill(.white)
                    .overlay {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(Color(red: 0.86, green: 0.26, blue: 0.22))
                            .font(.system(size: 24, weight: .bold))
                    }
                    .frame(width: knobSize, height: knobSize)
                    .offset(x: horizontalInset + CGFloat(slideValue) * maxOffset)
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .onChanged { value in
                                let proposed = value.location.x - (knobSize / 2) - horizontalInset
                                let clamped = min(max(0, proposed), maxOffset)
                                guard maxOffset > 0 else {
                                    slideValue = 0
                                    return
                                }
                                slideValue = Double(clamped / maxOffset)
                            }
                            .onEnded { _ in
                                if slideValue >= 0.92 {
                                    Task { await initiateAction(action) }
                                } else {
                                    withAnimation(.easeOut(duration: 0.18)) {
                                        slideValue = 0
                                    }
                                }
                            }
                    )
            }
            .frame(height: 68)
        }
        .frame(height: 68)
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
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(surfaceMain)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
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

    private func teamAssistFeedRow(item: TeamAssistSummary) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            feedRow(title: AppLabels.featureDisplayName(for: item.type, overrides: featureLabels), subtitle: teamAssistSubtitle(for: item))
            if isAdminSession {
                HStack(spacing: 10) {
                    Menu {
                        Button("Acknowledge") {
                            Task { await applyTeamAssistAction(item, action: "acknowledge") }
                        }
                        Button("Responding") {
                            Task { await applyTeamAssistAction(item, action: "responding") }
                        }
                        Button("Forward…") {
                            forwardingTeamAssist = item
                        }
                    } label: {
                        Text("Update")
                            .font(.caption.weight(.semibold))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                            .background(bluePrimary.opacity(0.14))
                            .clipShape(Capsule())
                    }

                    if item.status != "cancelled" {
                        Button {
                            Task { await confirmTeamAssistCancel(item) }
                        } label: {
                            Text(item.cancelAdminConfirmed ? "Admin Confirmed" : "Confirm Cancel")
                                .font(.caption.weight(.semibold))
                                .padding(.horizontal, 12)
                                .padding(.vertical, 7)
                                .background(item.cancelAdminConfirmed ? Color.green.opacity(0.15) : Color.red.opacity(0.14))
                                .clipShape(Capsule())
                        }
                        .disabled(isUpdatingTeamAssist || item.cancelAdminConfirmed)
                    }
                }
            } else if appState.userID == item.createdBy && item.status != "cancelled" {
                Button {
                    Task { await confirmTeamAssistCancel(item) }
                } label: {
                    Text(item.cancelRequesterConfirmed ? "Requester Confirmed" : "Confirm Cancel")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 7)
                        .background(item.cancelRequesterConfirmed ? Color.green.opacity(0.15) : Color.orange.opacity(0.14))
                        .clipShape(Capsule())
                }
                .disabled(isUpdatingTeamAssist || item.cancelRequesterConfirmed)
            }
        }
        .padding(.vertical, 2)
    }

    private func teamAssistSubtitle(for item: TeamAssistSummary) -> String {
        var parts: [String] = ["by #\(item.createdBy)"]
        if let actor = item.actedByLabel, !actor.isEmpty {
            parts.append("\(item.status.capitalized) by \(actor)")
        } else {
            parts.append(item.status.capitalized)
        }
        if item.status == "forwarded", let forwardLabel = item.forwardToLabel, !forwardLabel.isEmpty {
            parts.append("to \(forwardLabel)")
        }
        if item.status == "cancel_pending" {
            let requester = item.cancelRequesterConfirmed ? "Requester ✓" : "Requester …"
            let admin = item.cancelAdminConfirmed ? "Admin ✓" : "Admin …"
            parts.append("\(requester), \(admin)")
        }
        return parts.joined(separator: " • ")
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
            async let teamAssistResponse = api.activeRequestHelp()
            let (incidents, teamAssists) = try await (incidentsResponse, teamAssistResponse)
            activeIncidents = incidents.incidents
            activeTeamAssists = teamAssists.teamAssists
            syncAdminRequestHelpPrompt()
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
        guard !adminRecipients.isEmpty else { return "All users" }
        if selectedRecipientIDs.count == adminRecipients.count {
            return "All users"
        }
        if selectedRecipientIDs.isEmpty {
            return "No users selected"
        }
        return "\(selectedRecipientIDs.count) users selected"
    }

    private var canSendAdminMessage: Bool {
        !isSendingAdminMessage &&
        !adminOutboundMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
        !adminRecipients.isEmpty &&
        !selectedRecipientIDs.isEmpty
    }

    private func loadAdminRecipients() async {
        guard isAdminSession else { return }
        do {
            let recipients = try await api.listMessageRecipients()
            adminRecipients = recipients
            if selectedRecipientIDs.isEmpty || selectedRecipientIDs.count > recipients.count {
                selectedRecipientIDs = Set(recipients.map(\.userID))
            } else {
                selectedRecipientIDs = selectedRecipientIDs.intersection(Set(recipients.map(\.userID)))
            }
        } catch {
            if adminRecipients.isEmpty {
                appState.lastError = "Could not load user recipients for admin messaging."
            }
        }
    }

    private func loadTeamAssistForwardRecipients() async {
        guard isAdminSession else { return }
        do {
            teamAssistForwardRecipients = try await api.listTeamAssistForwardRecipients()
        } catch {
            if teamAssistForwardRecipients.isEmpty {
                appState.lastError = "Could not load users for request-help forwarding."
            }
        }
    }

    private func loadAdminQuietPeriodRequests() async {
        guard isAdminSession, let adminUserID = appState.userID else { return }
        do {
            let response = try await api.adminQuietPeriodRequests(adminUserID: adminUserID)
            adminQuietPeriodRequests = response.requests
        } catch {
            if adminQuietPeriodRequests.isEmpty {
                appState.lastError = "Could not load quiet period requests."
            }
        }
    }

    private func loadFeatureLabels() async {
        do {
            let remote = try await api.configLabels()
            if remote.isEmpty { return }
            var merged = AppLabels.defaultFeatureLabels
            for (rawKey, rawValue) in remote {
                let key = AppLabels.normalizeFeatureKey(rawKey)
                let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
                if !value.isEmpty {
                    merged[key] = value
                }
            }
            featureLabels = merged
        } catch {
            if featureLabels.isEmpty {
                featureLabels = AppLabels.defaultFeatureLabels
            }
        }
    }

    private func syncAdminRequestHelpPrompt() {
        guard isAdminSession else {
            adminPromptRequestHelpID = nil
            dismissedAdminPromptRequestHelpID = nil
            return
        }
        let nextPendingID = activeTeamAssists.first {
            $0.status.lowercased() == "active" && $0.createdBy != appState.userID
        }?.id
        guard let nextPendingID else {
            adminPromptRequestHelpID = nil
            dismissedAdminPromptRequestHelpID = nil
            return
        }
        if adminPromptRequestHelpID == nil && dismissedAdminPromptRequestHelpID != nextPendingID {
            adminPromptRequestHelpID = nextPendingID
        }
        if let showingID = adminPromptRequestHelpID, activeTeamAssists.allSatisfy({ $0.id != showingID }) {
            adminPromptRequestHelpID = nil
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
            let allRecipientIDs = adminRecipients.map(\.userID)
            let recipientIDs = selectedRecipientIDs.isEmpty ? allRecipientIDs : Array(selectedRecipientIDs)
            let isAllSelected = Set(recipientIDs).count == Set(allRecipientIDs).count
            let response = try await api.sendMessageFromAdmin(
                adminUserID: adminUserID,
                message: trimmed,
                recipientUserIDs: recipientIDs,
                sendToAll: isAllSelected
            )
            adminOutboundMessage = ""
            appState.lastError = nil
            appState.lastStatus = "Message sent (\(response.sentCount)) to \(response.recipientScope)."
        } catch {
            appState.lastError = "Send message failed: \(error.localizedDescription)"
        }
    }

    private func sendMessageToAdminFromUser() async {
        let trimmed = userMessageToAdmin.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        isSendingUserMessage = true
        defer { isSendingUserMessage = false }
        do {
            _ = try await api.messageAdmin(userID: appState.userID, message: trimmed)
            userMessageToAdmin = ""
            appState.lastError = nil
            appState.lastStatus = "Message sent to admins."
        } catch {
            appState.lastError = "Send message failed: \(error.localizedDescription)"
        }
    }

    private func submitTeamAssist(type: String) async {
        guard let userID = appState.userID else {
            appState.lastError = "You must be signed in to request help."
            return
        }
        isSubmittingQuickAction = true
        defer { isSubmittingQuickAction = false }
        do {
            _ = try await api.createRequestHelp(userID: userID, type: type)
            appState.lastError = nil
            appState.lastStatus = "Request help sent."
            await refreshIncidentFeed()
        } catch {
            appState.lastError = "Request help failed: \(error.localizedDescription)"
        }
    }

    private func applyTeamAssistAction(_ item: TeamAssistSummary, action: String) async {
        guard let userID = appState.userID else {
            appState.lastError = "Admin sign-in is required."
            return
        }
        isUpdatingTeamAssist = true
        defer { isUpdatingTeamAssist = false }
        do {
            _ = try await api.updateRequestHelp(teamAssistID: item.id, actorUserID: userID, action: action)
            appState.lastError = nil
            appState.lastStatus = "Request help marked \(action) by \(appState.userName)."
            await refreshIncidentFeed()
        } catch {
            appState.lastError = "Request-help update failed: \(error.localizedDescription)"
        }
    }

    private func confirmTeamAssistCancel(_ item: TeamAssistSummary) async {
        guard let userID = appState.userID else {
            appState.lastError = "Sign-in is required."
            return
        }
        isUpdatingTeamAssist = true
        defer { isUpdatingTeamAssist = false }
        do {
            let updated = try await api.confirmRequestHelpCancel(teamAssistID: item.id, actorUserID: userID)
            appState.lastError = nil
            if updated.status == "cancelled" {
                appState.lastStatus = "Request help cancelled after dual confirmation."
            } else {
                appState.lastStatus = "Cancellation confirmation recorded. Waiting for second confirmation."
            }
            await refreshIncidentFeed()
        } catch {
            appState.lastError = "Request-help cancellation confirmation failed: \(error.localizedDescription)"
        }
    }

    private func forwardTeamAssist(_ item: TeamAssistSummary, to recipient: MessageRecipient) async {
        guard let userID = appState.userID else {
            appState.lastError = "Admin sign-in is required."
            return
        }
        isUpdatingTeamAssist = true
        defer { isUpdatingTeamAssist = false }
        do {
            _ = try await api.updateRequestHelp(
                teamAssistID: item.id,
                actorUserID: userID,
                action: "forward",
                forwardToUserID: recipient.userID
            )
            forwardingTeamAssist = nil
            appState.lastError = nil
            appState.lastStatus = "Request help forwarded to \(recipient.label)."
            await refreshIncidentFeed()
        } catch {
            appState.lastError = "Request-help forward failed: \(error.localizedDescription)"
        }
    }

    private func approveQuietPeriodRequest(_ item: QuietPeriodAdminRequest) async {
        guard let adminUserID = appState.userID else {
            appState.lastError = "Admin sign-in is required."
            return
        }
        isUpdatingQuietPeriodRequests = true
        defer { isUpdatingQuietPeriodRequests = false }
        do {
            _ = try await api.approveQuietPeriodRequest(requestID: item.requestID, adminUserID: adminUserID)
            appState.lastError = nil
            appState.lastStatus = "Quiet period request approved."
            await loadAdminQuietPeriodRequests()
        } catch {
            appState.lastError = "Approve failed: \(error.localizedDescription)"
        }
    }

    private func denyQuietPeriodRequest(_ item: QuietPeriodAdminRequest) async {
        guard let adminUserID = appState.userID else {
            appState.lastError = "Admin sign-in is required."
            return
        }
        isUpdatingQuietPeriodRequests = true
        defer { isUpdatingQuietPeriodRequests = false }
        do {
            _ = try await api.denyQuietPeriodRequest(requestID: item.requestID, adminUserID: adminUserID)
            appState.lastError = nil
            appState.lastStatus = "Quiet period request denied."
            await loadAdminQuietPeriodRequests()
        } catch {
            appState.lastError = "Deny failed: \(error.localizedDescription)"
        }
    }

    private func submitQuietPeriodRequest() async {
        guard let userID = appState.userID else {
            appState.lastError = "You must be signed in to request quiet period."
            return
        }
        isSubmittingQuickAction = true
        defer { isSubmittingQuickAction = false }
        do {
            let trimmed = quietPeriodReason.trimmingCharacters(in: .whitespacesAndNewlines)
            _ = try await api.requestQuietPeriod(
                userID: userID,
                reason: trimmed.isEmpty ? nil : trimmed
            )
            quietPeriodReason = ""
            appState.lastError = nil
            appState.lastStatus = "Quiet period request submitted."
        } catch {
            appState.lastError = "Quiet period request failed: \(error.localizedDescription)"
        }
    }

    private func dismissKeyboard() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
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

private struct RecipientSelectionSheet: View {
    let recipients: [MessageRecipient]
    @Binding var selectedRecipientIDs: Set<Int>
    @Environment(\.dismiss) private var dismiss
    @State private var searchText = ""

    private var filteredRecipients: [MessageRecipient] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        if query.isEmpty { return recipients }
        return recipients.filter { $0.label.localizedCaseInsensitiveContains(query) }
    }

    private var allSelected: Bool {
        !recipients.isEmpty && selectedRecipientIDs.count == recipients.count
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button {
                        if allSelected {
                            selectedRecipientIDs.removeAll()
                        } else {
                            selectedRecipientIDs = Set(recipients.map(\.userID))
                        }
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: allSelected ? "checkmark.square.fill" : "square")
                                .foregroundStyle(allSelected ? bluePrimary : textMuted)
                            Text("Select All Users")
                                .foregroundStyle(textPrimary)
                                .font(.body.weight(.semibold))
                        }
                    }
                    .buttonStyle(.plain)
                }

                Section {
                    ForEach(filteredRecipients) { recipient in
                        Button {
                            if selectedRecipientIDs.contains(recipient.userID) {
                                selectedRecipientIDs.remove(recipient.userID)
                            } else {
                                selectedRecipientIDs.insert(recipient.userID)
                            }
                        } label: {
                            HStack(spacing: 12) {
                                Image(systemName: selectedRecipientIDs.contains(recipient.userID) ? "checkmark.square.fill" : "square")
                                    .foregroundStyle(selectedRecipientIDs.contains(recipient.userID) ? bluePrimary : textMuted)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(parsedRecipientName(from: recipient.label))
                                        .foregroundStyle(textPrimary)
                                    if let role = parsedRecipientRole(from: recipient.label) {
                                        Text(role)
                                            .font(.caption)
                                            .foregroundStyle(textMuted)
                                    }
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .searchable(text: $searchText, prompt: "Search users")
            .navigationTitle("Select Recipients")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .fontWeight(.semibold)
                }
            }
        }
    }

    private func parsedRecipientName(from label: String) -> String {
        if let open = label.firstIndex(of: "(") {
            return label[..<open].trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return label
    }

    private func parsedRecipientRole(from label: String) -> String? {
        guard let open = label.firstIndex(of: "("), let close = label.lastIndex(of: ")"), open < close else {
            return nil
        }
        return String(label[label.index(after: open)..<close])
    }
}

private struct AdminRequestHelpPromptSheet: View {
    let requestHelpLabel: String
    let item: TeamAssistSummary
    let isBusy: Bool
    let onAcknowledge: () -> Void
    let onResponding: () -> Void
    let onLater: () -> Void

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 14) {
                Text("Incoming \(requestHelpLabel)")
                    .font(.title3.weight(.bold))
                    .foregroundStyle(textPrimary)
                Text("From #\(item.createdBy) • \(item.createdAt)")
                    .font(.subheadline)
                    .foregroundStyle(textMuted)
                Text("Take action now to clear this active request.")
                    .font(.subheadline)
                    .foregroundStyle(textPrimary)

                HStack(spacing: 10) {
                    Button("Acknowledge") { onAcknowledge() }
                        .buttonStyle(.bordered)
                        .tint(bluePrimary)
                        .disabled(isBusy)
                    Button("Responding") { onResponding() }
                        .buttonStyle(.borderedProminent)
                        .tint(Color(red: 0.06, green: 0.46, blue: 0.43))
                        .disabled(isBusy)
                }
                .padding(.top, 4)

                Spacer(minLength: 0)
            }
            .padding(20)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Later") { onLater() }
                        .disabled(isBusy)
                }
            }
        }
    }
}

private struct TeamAssistForwardSheet: View {
    let teamAssist: TeamAssistSummary
    let requestHelpLabel: String
    let recipients: [MessageRecipient]
    let isBusy: Bool
    let onSelect: (MessageRecipient) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if recipients.isEmpty {
                    Text("No active users available.")
                        .foregroundStyle(textMuted)
                } else {
                    ForEach(recipients) { recipient in
                        Button {
                            onSelect(recipient)
                        } label: {
                            HStack {
                                Text(recipient.label)
                                    .foregroundStyle(textPrimary)
                                Spacer()
                                Image(systemName: "arrowshape.turn.up.right.fill")
                                    .foregroundStyle(bluePrimary)
                            }
                            .padding(.vertical, 4)
                        }
                        .disabled(isBusy)
                    }
                }
            }
            .navigationTitle("Forward \(requestHelpLabel)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Text("#\(teamAssist.id)")
                        .font(.caption)
                        .foregroundStyle(textMuted)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Close") { dismiss() }
                }
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
