import SwiftUI
import LocalAuthentication
import UIKit
import QuartzCore
import AVFoundation
import Foundation
import Combine
import MediaPlayer

private let appBg = DSColor.background
private let appBgDeep = DSColor.backgroundDeep
private let surfaceMain = DSColor.card
private let textPrimary = DSColor.textPrimary
private let textMuted = DSColor.textSecondary
private let bluePrimary = DSColor.primary
private let fieldDarkBg = DSColor.inputBackground
private let fieldDarkBorder = DSColor.border
private let placeholderMuted = DSColor.textSecondary.opacity(0.78)

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

private enum HoldActivationState {
    case idle
    case holding
    case triggered
    case canceled
}

@MainActor
private final class AlertController: ObservableObject {
    @Published var holdProgress: Double = 0
    @Published var holdState: HoldActivationState = .idle

    private var holdTask: Task<Void, Never>?
    private var hapticTask: Task<Void, Never>?
    private var didTrigger = false
    private var isTouchDown = false
    private static var audioPlayer: AVAudioPlayer?
    private static var volumeObserver: NSKeyValueObservation?
    private static weak var volumeSlider: UISlider?
    private static var volumeView: MPVolumeView?
    private static var isVolumeLockActive = false
    private static var isAdjustingVolume = false

    func beginHold(duration: Double = 3.0) {
        guard holdState != .holding, !didTrigger else { return }
        print("Press detected")
        print("Hold started")
        isTouchDown = true
        holdState = .holding
        holdProgress = 0
        didTrigger = false
        fireTouchDownHaptic()
        startHapticLoop()
        holdTask?.cancel()
        holdTask = Task {
            let start = CACurrentMediaTime()
            var lastLoggedStep = -1
            while !Task.isCancelled, !didTrigger, isTouchDown {
                let elapsed = CACurrentMediaTime() - start
                let progress = min(1.0, elapsed / duration)
                holdProgress = progress
                let progressStep = Int(progress * 10)
                if progressStep != lastLoggedStep {
                    lastLoggedStep = progressStep
                    print("Progress value: \(String(format: "%.2f", progress))")
                }
                try? await Task.sleep(nanoseconds: 16_666_667)
            }
        }
    }

    func completeHold(onActivate: @escaping () -> Void) {
        guard holdState == .holding, !didTrigger, isTouchDown else { return }
        didTrigger = true
        isTouchDown = false
        holdProgress = 1.0
        holdState = .triggered
        holdTask?.cancel()
        holdTask = nil
        stopHapticLoop()
        fireCompletionHaptic()
        print("Hold completed; triggering alert")
        onActivate()
        Task {
            try? await Task.sleep(nanoseconds: 240_000_000)
            withAnimation(.easeOut(duration: 0.18)) {
                holdProgress = 0
            }
            holdState = .idle
            didTrigger = false
        }
    }

    func cancelHold() {
        isTouchDown = false
        guard holdState == .holding, !didTrigger else { return }
        holdTask?.cancel()
        holdTask = nil
        stopHapticLoop()
        fireCancelHaptic()
        print("Hold cancelled")
        holdState = .canceled
        withAnimation(.easeOut(duration: 0.18)) {
            holdProgress = 0
        }
        Task {
            try? await Task.sleep(nanoseconds: 180_000_000)
            if !didTrigger {
                holdState = .idle
            }
        }
    }

    func resetHoldState() {
        holdTask?.cancel()
        holdTask = nil
        stopHapticLoop()
        holdProgress = 0
        didTrigger = false
        isTouchDown = false
        holdState = .idle
    }

    func startAlarmAudio() {
        if Self.audioPlayer?.isPlaying == true {
            print("Audio already playing")
            Self.enableVolumeLock()
            return
        }
        guard let fileURL = Bundle.main.url(forResource: "bluebird-alarm-asset", withExtension: "mp3") else {
            print("Audio failed: bluebird-alarm-asset.mp3 not found in app bundle")
            return
        }
        print("Alarm file URL: \(fileURL)")
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: [.duckOthers])
            try session.setActive(true)
            let player = try AVAudioPlayer(contentsOf: fileURL)
            player.numberOfLoops = -1
            player.volume = 1.0
            player.prepareToPlay()
            if player.play() {
                Self.audioPlayer = player
                Self.enableVolumeLock()
                print("Audio started")
            } else {
                print("Audio failed: AVAudioPlayer returned play() == false")
            }
        } catch {
            print("Audio failed: \(error.localizedDescription)")
        }
    }

    func stopAlarmAudio() {
        Self.disableVolumeLock()
        if let player = Self.audioPlayer {
            if player.isPlaying {
                player.stop()
            }
            player.currentTime = 0
            print("Audio stopped")
        }
        Self.audioPlayer = nil
        do {
            try AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
        } catch {
            print("Audio session deactivate error: \(error.localizedDescription)")
        }
    }

    private static func enableVolumeLock() {
        guard !isVolumeLockActive else {
            setSystemVolumeToMax()
            return
        }
        isVolumeLockActive = true
        ensureSystemVolumeSlider()
        setSystemVolumeToMax()

        volumeObserver = AVAudioSession.sharedInstance().observe(\.outputVolume, options: [.new]) { _, change in
            guard let newValue = change.newValue else { return }
            Task { @MainActor in
                guard Self.isVolumeLockActive else { return }
                if newValue < 0.995 {
                    Self.setSystemVolumeToMax()
                }
            }
        }
    }

    private static func disableVolumeLock() {
        isVolumeLockActive = false
        volumeObserver?.invalidate()
        volumeObserver = nil
    }

    private static func ensureSystemVolumeSlider() {
        guard volumeSlider == nil else { return }
        guard
            let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
            let window = windowScene.windows.first
        else {
            print("Volume lock: no window available for MPVolumeView")
            return
        }

        let mpView = MPVolumeView(frame: CGRect(x: -1000, y: -1000, width: 1, height: 1))
        mpView.isHidden = true
        window.addSubview(mpView)
        volumeView = mpView
        volumeSlider = mpView.subviews.compactMap { $0 as? UISlider }.first
        if volumeSlider == nil {
            print("Volume lock: could not find MPVolumeView slider")
        }
    }

    private static func setSystemVolumeToMax() {
        guard !isAdjustingVolume else { return }
        isAdjustingVolume = true
        DispatchQueue.main.async {
            ensureSystemVolumeSlider()
            volumeSlider?.value = 1.0
            volumeSlider?.sendActions(for: .valueChanged)
            isAdjustingVolume = false
        }
    }

    private func startHapticLoop() {
        hapticTask?.cancel()
        hapticTask = Task {
            while !Task.isCancelled, !didTrigger, holdState == .holding {
                let isNearComplete = holdProgress >= 0.8
                fireProgressHaptic(strong: isNearComplete)
                print("Haptics firing (strong=\(isNearComplete))")
                try? await Task.sleep(nanoseconds: 800_000_000)
            }
        }
    }

    private func stopHapticLoop() {
        hapticTask?.cancel()
        hapticTask = nil
    }

    private func fireTouchDownHaptic() {
        let generator = UIImpactFeedbackGenerator(style: .light)
        generator.prepare()
        generator.impactOccurred(intensity: 0.5)
    }

    private func fireProgressHaptic(strong: Bool) {
        let generator = UIImpactFeedbackGenerator(style: strong ? .medium : .soft)
        generator.prepare()
        generator.impactOccurred(intensity: strong ? 0.78 : 0.5)
    }

    private func fireCompletionHaptic() {
        let generator = UINotificationFeedbackGenerator()
        generator.prepare()
        generator.notificationOccurred(.success)
    }

    private func fireCancelHaptic() {
        let generator = UIImpactFeedbackGenerator(style: .soft)
        generator.prepare()
        generator.impactOccurred(intensity: 0.42)
    }
}

private struct SafetyHoldButton: View {
    let action: SafetyActionItem
    let titleColor: Color
    let isEnabled: Bool
    let onHoldVisual: (Bool, Double, Color) -> Void
    let onActivate: () -> Void

    @StateObject private var controller = AlertController()

    private var holdText: String {
        switch holdState {
        case .idle:
            return "Hold to Activate"
        case .holding:
            return "Keep Holding…"
        case .triggered:
            return "Activating…"
        case .canceled:
            return "Release to Cancel"
        }
    }

    private var holdScale: CGFloat {
        switch holdState {
        case .idle, .canceled:
            return 1.0
        case .triggered:
            return 1.12
        case .holding:
            return CGFloat(0.97 + holdProgress * 0.11)
        }
    }

    private var holdProgress: Double { controller.holdProgress }
    private var holdState: HoldActivationState { controller.holdState }

    var body: some View {
        VStack(spacing: 6) {
            ZStack {
                Circle()
                    .stroke(Color.white.opacity(0.24), lineWidth: 10)
                Circle()
                    .trim(from: 0, to: holdProgress)
                    .stroke(
                        holdProgress < 0.55 ? Color.white : (holdProgress < 0.8 ? DSColor.warning : DSColor.danger),
                        style: StrokeStyle(lineWidth: 10, lineCap: .round, lineJoin: .round)
                    )
                    .shadow(color: Color.white.opacity(0.5), radius: 4, x: 0, y: 0)
                    .rotationEffect(.degrees(-90))
                    .animation(.linear(duration: 0.05), value: holdProgress)

                Circle()
                    .fill(action.color)
                    .overlay {
                        Image(systemName: action.icon)
                            .foregroundStyle(.white)
                            .font(.system(size: 30, weight: .bold))
                    }
                    .scaleEffect(holdScale)
                    .shadow(color: action.color.opacity(0.1 + holdProgress * 0.24), radius: 18, x: 0, y: 0)
                    .animation(.easeOut(duration: 0.16), value: holdScale)
            }
            .frame(width: 122, height: 122)
            .contentShape(Circle())
            .onLongPressGesture(
                minimumDuration: 3.0,
                maximumDistance: 44,
                pressing: { pressing in
                    guard isEnabled else { return }
                    if pressing {
                        controller.beginHold(duration: 3.0)
                    } else {
                        controller.cancelHold()
                        onHoldVisual(false, 0, action.color)
                    }
                },
                perform: {
                    controller.completeHold {
                        onHoldVisual(false, 0, action.color)
                        onActivate()
                    }
                }
            )
            .opacity(isEnabled ? 1 : 0.5)

            Text(action.title)
                .font(.headline.weight(.bold))
                .foregroundStyle(titleColor)
                .multilineTextAlignment(.center)
            Text(holdText)
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.white.opacity(0.88))
            Text("~3s")
                .font(.caption2)
                .foregroundStyle(Color.white.opacity(0.62))
        }
        .frame(maxWidth: .infinity)
        .onChange(of: controller.holdProgress) { _, progress in
            onHoldVisual(holdState == .holding, progress, action.color)
        }
        .onDisappear {
            controller.resetHoldState()
            onHoldVisual(false, 0, action.color)
        }
    }
}

private func buildSafetyActions(featureLabels: [String: String]) -> [SafetyActionItem] {
    [
        .init(id: "secure", title: AppLabels.labelForFeatureKey(AppLabels.keySecure, overrides: featureLabels).uppercased(), icon: "hand.raised.fill", color: DSColor.info, message: "SECURE emergency initiated. Follow school secure procedures."),
        .init(id: "lockdown", title: AppLabels.labelForFeatureKey(AppLabels.keyLockdown, overrides: featureLabels).uppercased(), icon: "lock.fill", color: DSColor.danger, message: "LOCKDOWN emergency initiated. Follow lockdown procedures immediately."),
        .init(id: "evacuation", title: AppLabels.labelForFeatureKey(AppLabels.keyEvacuation, overrides: featureLabels).uppercased(), icon: "figure.walk.motion", color: DSColor.success, message: "EVACUATE emergency initiated. Move to evacuation locations now."),
        .init(id: "shelter", title: AppLabels.labelForFeatureKey(AppLabels.keyShelter, overrides: featureLabels).uppercased(), icon: "house.fill", color: DSColor.warning, message: "SHELTER emergency initiated. Move into shelter protocol."),
        .init(id: "hold", title: "HOLD", icon: "pause.fill", color: DSColor.quietAccent, message: "HOLD emergency initiated. Keep current position until cleared."),
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
    @StateObject private var alertController = AlertController()
    @State private var message = "Emergency alert. Please follow school procedures."
    @State private var isSending = false
    @State private var isRegistering = false
    @State private var showSettings = false
    @State private var activeIncidents: [IncidentSummary] = []
    @State private var activeTeamAssists: [TeamAssistSummary] = []
    @State private var alarmIsActive = false
    @State private var alarmMessage: String?
    @State private var alarmIsTraining = false
    @State private var alarmTrainingLabel: String?
    @State private var isRefreshingIncidentFeed = false
    @State private var isUpdatingAlarm = false
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
    @State private var trainingModeEnabled = false
    @State private var trainingLabel = "This is a drill"
    @State private var isSubmittingQuickAction = false
    @State private var teamAssistForwardRecipients: [MessageRecipient] = []
    @State private var forwardingTeamAssist: TeamAssistSummary?
    @State private var isUpdatingTeamAssist = false
    @State private var adminPromptRequestHelpID: Int?
    @State private var dismissedAdminPromptRequestHelpID: Int?
    @State private var adminQuietPeriodRequests: [QuietPeriodAdminRequest] = []
    @State private var isUpdatingQuietPeriodRequests = false
    @State private var featureLabels: [String: String] = AppLabels.defaultFeatureLabels
    @State private var holdFlashActive = false
    @State private var holdFlashProgress: Double = 0
    @State private var holdFlashColor: Color = DSColor.danger

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
                        if alarmIsActive, alarmIsTraining {
                            let trainingBannerLabel = alarmTrainingLabel?.trimmingCharacters(in: .whitespacesAndNewlines)
                            let trainingText = (trainingBannerLabel?.isEmpty == false) ? (trainingBannerLabel ?? "This is a drill") : "This is a drill"
                            flashBanner(
                                message: "TRAINING DRILL: \(trainingText)",
                                isError: false
                            )
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

                if holdFlashActive {
                    TimelineView(.animation(minimumInterval: 0.05)) { timeline in
                        let t = timeline.date.timeIntervalSinceReferenceDate
                        let wave = (sin(t * Double.pi * 2 * 1.6) + 1) / 2
                        let base = 0.035 + holdFlashProgress * 0.09
                        let pulse = (0.03 + holdFlashProgress * 0.07) * wave
                        Rectangle()
                            .fill(holdFlashColor)
                            .opacity(min(0.22, base + pulse))
                            .ignoresSafeArea()
                    }
                    .allowsHitTesting(false)
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
        .onReceive(NotificationCenter.default.publisher(for: .deviceTokenUpdated)) { note in
            guard let token = note.userInfo?["token"] as? String else { return }
            appState.deviceToken = token
            appState.usingLocalTestToken = false
            Task { await registerDevice(token: token) }
        }
        .onReceive(NotificationCenter.default.publisher(for: .deviceTokenUpdateFailed)) { note in
            appState.lastError = note.userInfo?["error"] as? String
        }
        .onChange(of: alarmIsActive) { _, isActive in
            if isActive {
                alertController.startAlarmAudio()
            } else {
                alertController.stopAlarmAudio()
            }
        }
        .onDisappear {
            alertController.stopAlarmAudio()
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

                if appState.canDeactivateAlarm {
                    HStack(spacing: 8) {
                        Circle()
                            .fill(
                                alarmIsActive
                                    ? (alarmIsTraining ? DSColor.warning : DSColor.danger)
                                    : DSColor.textSecondary.opacity(0.6)
                            )
                            .frame(width: 9, height: 9)
                        Text(
                            alarmIsActive
                                ? (alarmIsTraining ? "Training Drill Active" : "Alarm Active")
                                : "No Active Alarm"
                        )
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(
                                alarmIsActive
                                    ? (alarmIsTraining ? DSColor.warning : DSColor.danger)
                                    : textMuted
                            )
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(
                        Capsule(style: .continuous)
                            .fill(alarmIsActive ? DSColor.danger.opacity(0.14) : DSColor.border.opacity(0.32))
                    )

                    Button {
                        Task { await authenticateThenDeactivateAlarm() }
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "bell.slash.fill")
                                .font(.subheadline.weight(.bold))
                            Text(isUpdatingAlarm ? "Disabling Alarm…" : (alarmIsTraining ? "End Training Alert" : "Disable Alarm"))
                                .font(.subheadline.weight(.bold))
                        }
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, minHeight: 50)
                        .background(
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .fill(alarmIsActive ? DSColor.danger : DSColor.textSecondary.opacity(0.5))
                        )
                    }
                    .buttonStyle(PressableScaleButtonStyle())
                    .shadow(color: alarmIsActive ? DSColor.danger.opacity(0.22) : .clear, radius: 8, x: 0, y: 3)
                    .disabled(isUpdatingAlarm || !alarmIsActive)

                    if alarmIsActive {
                        if let label = alarmTrainingLabel, alarmIsTraining, !label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            Text("Training: \(label)")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(DSColor.warning)
                        }
                        if let alarmMessage, !alarmMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            Text(alarmMessage)
                                .font(.caption)
                                .foregroundStyle(textMuted)
                                .lineLimit(2)
                        }
                    }
                    Divider()
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
                    .foregroundStyle(DSColor.success)
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
                        .background(DSColor.quietAccent)
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                    .shadow(color: DSColor.quietAccent.opacity(0.16), radius: 8, x: 0, y: 3)
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
                    .background(DSColor.card)
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(DSColor.border, lineWidth: 1)
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
                        .foregroundStyle(DSColor.background)
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
                                        .background(DSColor.success)
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
                                        .background(DSColor.danger)
                                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                }
                                .disabled(isUpdatingQuietPeriodRequests || item.status.lowercased() != "pending")
                            }
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(DSColor.background)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                }
            }
        }
    }

    private var customPanicCard: some View {
        card {
            VStack(spacing: 14) {
                if isAdminSession {
                    HStack(spacing: 10) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Training Mode")
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(textPrimary)
                            Text("Drill-only alert. No live push or SMS.")
                                .font(.caption)
                                .foregroundStyle(textMuted)
                        }
                        Spacer()
                        Toggle("", isOn: $trainingModeEnabled)
                            .labelsHidden()
                    }
                    if trainingModeEnabled {
                        TextField("", text: $trainingLabel, prompt: Text("Training label (e.g., This is a drill)").foregroundStyle(placeholderMuted))
                            .foregroundStyle(.white)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 10)
                            .background(fieldDarkBg)
                            .overlay(
                                RoundedRectangle(cornerRadius: 12, style: .continuous)
                                    .stroke(fieldDarkBorder, lineWidth: 1)
                            )
                            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                }
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
                    Text(
                        isSending
                            ? "Sending..."
                            : (trainingModeEnabled && isAdminSession ? "Start Training Alert" : "Send Custom Panic")
                    )
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, minHeight: 46)
                        .background(
                            LinearGradient(
                                colors: [DSColor.danger.opacity(0.86), DSColor.danger],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                .buttonStyle(PressableScaleButtonStyle())
                .shadow(color: DSColor.danger.opacity(0.24), radius: 8, x: 0, y: 3)
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
        SafetyHoldButton(
            action: action,
            titleColor: textPrimary,
            isEnabled: !isSending && !isUpdatingAlarm,
            onHoldVisual: updateHoldFlash
        ) {
            guard !isSending else { return }
            message = action.message
            Task { await authenticateThenSendPanic() }
        }
    }

    private func updateHoldFlash(isActive: Bool, progress: Double, color: Color) {
        holdFlashActive = isActive
        holdFlashProgress = max(0, min(1, progress))
        holdFlashColor = color
    }

    private func flashBanner(message: String, isError: Bool) -> some View {
        Text(message)
            .font(.subheadline)
            .foregroundStyle(isError ? DSColor.danger : DSColor.success)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(isError ? DSColor.danger.opacity(0.16) : DSColor.success.opacity(0.16))
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
                                .background(item.cancelAdminConfirmed ? DSColor.success.opacity(0.15) : DSColor.danger.opacity(0.14))
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
                        .background(item.cancelRequesterConfirmed ? DSColor.success.opacity(0.15) : DSColor.warning.opacity(0.14))
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
        if appState.backendReachable == true { return DSColor.success }
        if appState.backendReachable == false { return DSColor.danger }
        return DSColor.textSecondary
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
            async let alarmResponse = api.alarmStatus()
            let (incidents, teamAssists, alarm) = try await (incidentsResponse, teamAssistResponse, alarmResponse)
            activeIncidents = incidents.incidents
            activeTeamAssists = teamAssists.teamAssists
            alarmIsActive = alarm.isActive
            alarmMessage = alarm.message
            alarmIsTraining = alarm.isTraining
            alarmTrainingLabel = alarm.trainingLabel
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
        guard let userID = appState.userID else {
            appState.lastError = "No active signed-in user found."
            return
        }

        isSending = true
        defer { isSending = false }

        do {
            let response = try await api.panic(
                userID: userID,
                message: trimmed,
                isTraining: isAdminSession && trainingModeEnabled,
                trainingLabel: isAdminSession && trainingModeEnabled ? trainingLabel : nil
            )
            alarmIsActive = true
            alarmMessage = trimmed
            alarmIsTraining = isAdminSession && trainingModeEnabled
            alarmTrainingLabel = alarmIsTraining ? trainingLabel : nil
            appState.registeredDeviceCount = response.deviceCount
            if isAdminSession && trainingModeEnabled {
                appState.lastStatus = "Training alert #\(response.alertId) started. Local recipients: \(response.attempted)."
                appState.lastError = nil
            } else {
                appState.lastStatus = "Alert #\(response.alertId): attempted \(response.attempted), ok \(response.succeeded), failed \(response.failed)"
                appState.lastError = response.apnsConfigured ? nil : "Backend accepted the alert, but APNs is not configured yet."
            }
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

    private func authenticateThenDeactivateAlarm() async {
        guard await authenticateIfNeeded(reason: "Confirm alarm deactivation.") else {
            appState.lastError = "Biometric verification was canceled."
            return
        }
        await deactivateAlarm()
    }

    private func deactivateAlarm() async {
        guard appState.canDeactivateAlarm else {
            appState.lastError = "Your role does not have permission to disable alarms."
            return
        }
        guard alarmIsActive else {
            appState.lastStatus = "No active alarm to disable."
            return
        }
        guard let adminUserID = appState.userID else {
            appState.lastError = "No active admin session found."
            return
        }
        guard !isUpdatingAlarm else {
            appState.lastStatus = "Alarm update already in progress."
            return
        }

        isUpdatingAlarm = true
        defer { isUpdatingAlarm = false }
        appState.lastStatus = "Disabling alarm..."
        appState.lastError = nil

        do {
            let response = try await api.deactivateAlarm(adminUserID: adminUserID)
            alarmIsActive = response.isActive
            alarmMessage = response.message
            alarmIsTraining = response.isTraining
            alarmTrainingLabel = response.trainingLabel
            appState.lastStatus = response.isActive ? "Alarm remains active." : "Alarm disabled."
            appState.lastError = nil
            if !response.isActive {
                alertController.stopAlarmAudio()
            }
            await refreshIncidentFeed()
        } catch {
            appState.lastError = "Disable alarm failed: \(error.localizedDescription)"
        }
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
                        .tint(DSColor.success)
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
    @AppStorage(DSThemePreference.storageKey) private var themeModeRaw = DSThemeMode.system.rawValue

    private var api: APIClient {
        APIClient(baseURL: appState.serverURL, apiKey: Config.backendApiKey)
    }

    var body: some View {
        ZStack {
            LinearGradient(colors: [DSColor.background, DSColor.backgroundDeep], startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()

            List {
                Section("Account") {
                    Text("BlueBird Alerts")
                        .foregroundStyle(DSColor.textPrimary)
                    if !appState.loginName.isEmpty {
                        Text("Login: \(appState.loginName)")
                            .foregroundStyle(DSColor.textPrimary)
                    }
                    Text("Role: \(appState.userRole.capitalized)")
                        .foregroundStyle(DSColor.textPrimary)
                    Text("Server: \(appState.serverURL.absoluteString)")
                        .font(.footnote)
                        .foregroundStyle(DSColor.textSecondary)
                    if !appState.initialDeviceAuthUserName.isEmpty {
                        Text("Initial device auth: \(appState.initialDeviceAuthUserName)")
                            .font(.footnote)
                            .foregroundStyle(DSColor.textSecondary)
                    }
                }
                .listRowBackground(DSColor.card)

                Section("Appearance") {
                    Picker("Theme", selection: $themeModeRaw) {
                        ForEach(DSThemeMode.allCases, id: \.rawValue) { mode in
                            Text(mode.rawValue.capitalized).tag(mode.rawValue)
                        }
                    }
                    .tint(DSColor.primary)
                }
                .listRowBackground(DSColor.card)

                Section("Security") {
                    Toggle("Biometrics Allowed", isOn: $appState.biometricsAllowed)
                        .tint(DSColor.primary)
                    Text("Require Face ID / Touch ID before sending emergency alerts.")
                        .font(.footnote)
                        .foregroundStyle(DSColor.textSecondary)
                }
                .listRowBackground(DSColor.card)

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
                .listRowBackground(DSColor.card)

                Section {
                    Button("Log Out", role: .destructive) {
                        appState.logout()
                    }
                }
                .listRowBackground(DSColor.card)
            }
            .listStyle(.insetGrouped)
            .scrollContentBackground(.hidden)
            .tint(DSColor.primary)
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
