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
        guard let fileURL = Bundle.main.url(forResource: "bluebird_alarm", withExtension: "caf") else {
            print("Audio failed: bluebird_alarm.caf not found in app bundle")
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

@MainActor
private final class AlertFeedbackController: ObservableObject {
    @Published var screenFlashOpacity: Double = 0
    @Published var screenFlashColor: Color = DSColor.danger

    private var feedbackTask: Task<Void, Never>?
    private let impactGenerator = UIImpactFeedbackGenerator(style: .heavy)

    func start(isTraining: Bool, hapticsEnabled: Bool, flashlightEnabled: Bool, screenFlashEnabled: Bool) {
        stop()
        screenFlashColor = isTraining ? DSColor.warning : DSColor.danger
        impactGenerator.prepare()
        feedbackTask = Task { @MainActor in
            while !Task.isCancelled {
                if screenFlashEnabled {
                    withAnimation(.easeOut(duration: 0.12)) {
                        screenFlashOpacity = isTraining ? 0.12 : 0.18
                    }
                }
                if hapticsEnabled {
                    impactGenerator.impactOccurred(intensity: isTraining ? 0.6 : 1.0)
                    impactGenerator.prepare()
                }
                if flashlightEnabled {
                    Self.setTorch(enabled: true)
                }
                try? await Task.sleep(nanoseconds: 300_000_000)
                if screenFlashEnabled {
                    withAnimation(.easeOut(duration: 0.16)) {
                        screenFlashOpacity = 0
                    }
                } else {
                    screenFlashOpacity = 0
                }
                if flashlightEnabled {
                    Self.setTorch(enabled: false)
                }
                try? await Task.sleep(nanoseconds: 300_000_000)
            }
        }
    }

    func stop() {
        feedbackTask?.cancel()
        feedbackTask = nil
        screenFlashOpacity = 0
        Self.setTorch(enabled: false)
    }

    private static func setTorch(enabled: Bool) {
        guard let device = AVCaptureDevice.default(for: .video), device.hasTorch else { return }
        do {
            try device.lockForConfiguration()
            if enabled {
                let level = min(AVCaptureDevice.maxAvailableTorchLevel, 1.0)
                try device.setTorchModeOn(level: level)
            } else {
                device.torchMode = .off
            }
            device.unlockForConfiguration()
        } catch {
            #if DEBUG
            print("Torch update failed: \(error.localizedDescription)")
            #endif
        }
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
    @Environment(\.scenePhase) private var scenePhase
    @EnvironmentObject private var appState: AppState
    @StateObject private var alertController = AlertController()
    @StateObject private var alertFeedbackController = AlertFeedbackController()
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
    @State private var alarmSilentAudio = false
    @State private var alarmAcknowledgementCount = 0
    @State private var alarmCurrentUserAcknowledged = false
    @State private var showAlarmTakeover = false
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
    @State private var silentTrainingAudioEnabled = false
    @State private var trainingLabel = "This is a drill"
    @State private var isSubmittingQuickAction = false
    @State private var teamAssistForwardRecipients: [MessageRecipient] = []
    @State private var forwardingTeamAssist: TeamAssistSummary?
    @State private var isUpdatingTeamAssist = false
    @State private var adminPromptRequestHelpID: Int?
    @State private var dismissedAdminPromptRequestHelpID: Int?
    @State private var adminQuietPeriodRequests: [QuietPeriodAdminRequest] = []
    @State private var isUpdatingQuietPeriodRequests = false
    @State private var pendingQuietActionItem: QuietPeriodAdminRequest? = nil
    @State private var pendingQuietActionIsApprove: Bool = true
    @State private var quietPeriodLocalFeedback: String? = nil
    @State private var quietPeriodLocalIsError: Bool = false
    @State private var myQuietRequest: QuietPeriodRequestResponse? = nil
    @State private var isCancellingQuietRequest = false
    @State private var showCancelQuietRequestConfirm = false
    @State private var processedEventIDs: Set<String> = []
    @State private var pushDeliveryStats: PushDeliveryStatsResponse?
    @State private var showAuditLogModal = false
    @State private var featureLabels: [String: String] = AppLabels.defaultFeatureLabels
    @State private var holdFlashActive = false
    @State private var holdFlashProgress: Double = 0
    @State private var holdFlashColor: Color = DSColor.danger
    @State private var showDeactivateConfirmation = false
    @State private var pendingAlertAction: SafetyActionItem?
    @State private var showDistrictView = false
    @State private var districtTenants: [TenantOverviewItem] = []
    @State private var wsReconnectGeneration: Int = 0

    private var api: APIClient {
        APIClient(baseURL: appState.selectedTenantURL, apiKey: Config.backendApiKey)
    }

    private var isAdminSession: Bool {
        let role = appState.userRole.lowercased()
        return role == "admin" || role == "building_admin" || role == "super_admin" || role == "platform_super_admin"
    }

    private var isDistrictSession: Bool {
        let role = appState.userRole.lowercased()
        return role == "district_admin" || role == "super_admin" || role == "platform_super_admin"
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

    private var shouldRunAlertFeedback: Bool {
        alarmIsActive && scenePhase == .active
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
                            let school = appState.effectiveSchoolName
                            let prefix = school.isEmpty ? "TRAINING DRILL" : "TRAINING DRILL — \(school)"
                            flashBanner(
                                message: "\(prefix): \(trainingText)",
                                isError: false
                            )
                        }
                        incidentsCard
                        safetyGrid
                        dashboardTabsCard
                        customPanicCard
                        supportActionsCard
                        if isAdminSession {
                            trainingModeCard
                            adminPushStatsCard
                            auditLogButtonCard
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 14)
                }

                if holdFlashActive {
                    TimelineView(.animation(minimumInterval: 0.05)) { timeline in
                        let t: Double = timeline.date.timeIntervalSinceReferenceDate
                        let frequency: Double = 1.6
                        let twoPi: Double = Double.pi * 2
                        let angle: Double = t * twoPi * frequency
                        let sineValue: Double = sin(angle)
                        let wave: Double = (sineValue + 1.0) / 2.0
                        let base: Double = 0.035 + holdFlashProgress * 0.09
                        let pulse: Double = (0.03 + holdFlashProgress * 0.07) * wave
                        let countdown: Int = max(1, Int(ceil((1.0 - holdFlashProgress) * 3.0)))
                        ZStack {
                            Rectangle()
                                .fill(holdFlashColor)
                                .opacity(min(0.22, base + pulse))
                                .ignoresSafeArea()
                            Text("\(countdown)")
                                .font(.system(size: 118, weight: .black, design: .rounded))
                                .foregroundStyle(.white)
                                .shadow(color: .black.opacity(0.35), radius: 10, x: 0, y: 4)
                                .opacity(0.45 + pulse * 0.85)
                                .scaleEffect(0.9 + pulse * 0.2)
                        }
                    }
                    .allowsHitTesting(false)
                }

                if alertFeedbackController.screenFlashOpacity > 0 {
                    Rectangle()
                        .fill(alertFeedbackController.screenFlashColor)
                        .opacity(alertFeedbackController.screenFlashOpacity)
                        .ignoresSafeArea()
                        .allowsHitTesting(false)
                        .zIndex(18)
                }

                if alarmIsActive, showAlarmTakeover {
                    alarmTakeoverOverlay
                        .transition(.opacity.combined(with: .scale(scale: 1.02)))
                        .zIndex(20)
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
            .navigationDestination(isPresented: $showDistrictView) {
                districtOverviewPage
            }
            .refreshable {
                await refreshIncidentFeed()
            }
            .task(id: "\(appState.selectedTenantSlug)-\(wsReconnectGeneration)") {
                await connectAlarmWebSocket()
            }
            .task {
                await loadMeData()
                await loadFeatureLabels()
                await refreshIncidentFeed()
                if let pendingAlarmUserInfo = AlarmPushBridge.consumePendingUserInfo() {
                    handleIncomingAlarmNotification(pendingAlarmUserInfo)
                }
                if isAdminSession {
                    await loadAdminRecipients()
                    await loadTeamAssistForwardRecipients()
                    await loadAdminQuietPeriodRequests()
                    await loadPushDeliveryStats()
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
                        await loadPushDeliveryStats()
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
            .alert("End Active Alert?", isPresented: $showDeactivateConfirmation) {
                Button("Cancel", role: .cancel) {}
                Button("End Alert", role: .destructive) {
                    Task { await deactivateAlarm() }
                }
            } message: {
                Text("This will end the active emergency alert for all users.")
            }
            .alert(
                "Confirm Alert",
                isPresented: Binding(
                    get: { pendingAlertAction != nil },
                    set: { if !$0 { pendingAlertAction = nil } }
                ),
                presenting: pendingAlertAction
            ) { action in
                Button("Cancel", role: .cancel) { pendingAlertAction = nil }
                Button("Send \(action.title) Alert", role: .destructive) {
                    pendingAlertAction = nil
                    Task { await authenticateThenSendPanic() }
                }
            } message: { action in
                let school = appState.effectiveSchoolName
                Text("Send \(action.title) alert to \(school.isEmpty ? "your school" : school)?")
            }
            .alert(
                pendingQuietActionIsApprove ? "Approve Quiet Period?" : "Deny Quiet Period?",
                isPresented: Binding(
                    get: { pendingQuietActionItem != nil },
                    set: { if !$0 { pendingQuietActionItem = nil } }
                ),
                presenting: pendingQuietActionItem
            ) { item in
                Button("Cancel", role: .cancel) { pendingQuietActionItem = nil }
                Button(
                    pendingQuietActionIsApprove ? "Approve" : "Deny",
                    role: pendingQuietActionIsApprove ? .none : .destructive
                ) {
                    let captured = item
                    let isApprove = pendingQuietActionIsApprove
                    pendingQuietActionItem = nil
                    Task {
                        if isApprove {
                            await approveQuietPeriodRequest(captured)
                        } else {
                            await denyQuietPeriodRequest(captured)
                        }
                    }
                }
            } message: { item in
                let name = item.userName ?? "User #\(item.userID)"
                let reason = item.reason.map { "\nReason: \($0)" } ?? ""
                return Text("\(name)\(reason)")
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
                        onResolve: {
                            dismissedAdminPromptRequestHelpID = promptItem.id
                            adminPromptRequestHelpID = nil
                            Task { await applyTeamAssistAction(promptItem, action: "resolve") }
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
        .onReceive(NotificationCenter.default.publisher(for: .alarmPushReceived)) { note in
            handleIncomingAlarmNotification(note.userInfo)
        }
        .onChange(of: alarmIsActive) { _, isActive in
            UIApplication.shared.isIdleTimerDisabled = isActive
            if isActive {
                showAlarmTakeover = true
                syncAlarmAudio()
            } else {
                showAlarmTakeover = false
                syncAlarmAudio()
            }
            updateAlertFeedbackState()
        }
        .onChange(of: alarmSilentAudio) { _, _ in
            syncAlarmAudio()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                wsReconnectGeneration += 1
                if let pendingAlarmUserInfo = AlarmPushBridge.consumePendingUserInfo() {
                    handleIncomingAlarmNotification(pendingAlarmUserInfo)
                } else if alarmIsActive {
                    showAlarmTakeover = true
                    syncAlarmAudio()
                }
            }
            updateAlertFeedbackState()
        }
        .onChange(of: appState.hapticAlertsEnabled) { _, _ in
            updateAlertFeedbackState()
        }
        .onChange(of: appState.flashlightAlertsEnabled) { _, _ in
            updateAlertFeedbackState()
        }
        .onChange(of: appState.screenFlashAlertsEnabled) { _, _ in
            updateAlertFeedbackState()
        }
        .onChange(of: alarmIsTraining) { _, _ in
            updateAlertFeedbackState()
        }
        .onDisappear {
            UIApplication.shared.isIdleTimerDisabled = false
            alertController.stopAlarmAudio()
            alertFeedbackController.stop()
        }
    }

    private func syncAlarmAudio() {
        if alarmIsActive && !alarmSilentAudio {
            alertController.startAlarmAudio()
        } else {
            alertController.stopAlarmAudio()
        }
    }

    private func handleIncomingAlarmNotification(_ userInfo: [AnyHashable: Any]?) {
        let aps = userInfo?["aps"] as? [AnyHashable: Any]
        let alert = aps?["alert"] as? [AnyHashable: Any]
        let title = (alert?["title"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
        let body =
            (alert?["body"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            ?? (userInfo?["message"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            ?? (userInfo?["body"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)

        // Tenant slug safety: if the push payload carries a tenant_slug (current APNs payload
        // does not, but future versions may), guard against cross-tenant state contamination.
        let pushSlug = (userInfo?["tenant_slug"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
        let currentSlug: String = {
            if !appState.selectedTenantSlug.isEmpty { return appState.selectedTenantSlug }
            let parts = appState.serverURL.pathComponents.filter { !$0.isEmpty && $0 != "/" }
            return parts.first ?? ""
        }()
        if let slug = pushSlug, !slug.isEmpty, slug != currentSlug {
            // Push is from a different school. Show banner but do NOT activate alarm for wrong school.
            let schoolName = appState.tenants.first(where: { $0.tenantSlug == slug })?.tenantName ?? slug
            let displayBody = body ?? "Emergency alert"
            appState.lastStatus = "Alert at \(schoolName): \(displayBody)"
            #if DEBUG
            print("[Push] Cross-tenant push from '\(slug)' (active: '\(currentSlug)') — alarm state unchanged")
            #endif
            Task { await refreshIncidentFeed() }
            return
        }

        showSettings = false
        showMessagingCenter = false
        showQuietPeriodCenter = false
        if let title, !title.isEmpty {
            appState.lastStatus = title
        }
        if let body, !body.isEmpty {
            alarmMessage = body
        }
        if let silent = userInfo?["silent_audio"] as? Bool {
            alarmSilentAudio = silent
        }
        alarmIsActive = true
        showAlarmTakeover = true
        syncAlarmAudio()
        updateAlertFeedbackState()
        Task {
            await refreshIncidentFeed()
        }
    }

    private func updateAlertFeedbackState() {
        guard shouldRunAlertFeedback else {
            alertFeedbackController.stop()
            return
        }
        alertFeedbackController.start(
            isTraining: alarmIsTraining,
            hapticsEnabled: appState.hapticAlertsEnabled,
            flashlightEnabled: appState.flashlightAlertsEnabled,
            screenFlashEnabled: appState.screenFlashAlertsEnabled,
        )
    }

    private var alarmTakeoverOverlay: some View {
        let isTraining = alarmIsTraining
        let accent = isTraining ? DSColor.warning : DSColor.danger
        let title = isTraining ? "TRAINING DRILL" : "EMERGENCY ALERT"
        let schoolName = appState.effectiveSchoolName
        let subtitle = isTraining
            ? (alarmTrainingLabel ?? "This is a drill")
            : (schoolName.isEmpty ? "School alarm is active" : "\(schoolName) — alarm is active")
        let body = alarmMessage?.trimmingCharacters(in: .whitespacesAndNewlines)

        return ZStack {
            LinearGradient(
                colors: [accent, Color.black],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            VStack(spacing: 28) {
                Spacer(minLength: 20)

                ZStack {
                    Circle()
                        .stroke(Color.white.opacity(0.24), lineWidth: 10)
                        .frame(width: 154, height: 154)
                    Image(systemName: isTraining ? "exclamationmark.triangle.fill" : "bell.and.waves.left.and.right.fill")
                        .font(.system(size: 66, weight: .black))
                        .foregroundStyle(.white)
                }
                .shadow(color: .black.opacity(0.35), radius: 18, x: 0, y: 8)

                VStack(spacing: 12) {
                    Text(title)
                        .font(.system(size: 38, weight: .black, design: .rounded))
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.white)

                    Text(subtitle)
                        .font(.title3.weight(.bold))
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.white.opacity(0.88))

                    if let body, !body.isEmpty {
                        Text(body)
                            .font(.body.weight(.semibold))
                            .multilineTextAlignment(.center)
                            .foregroundStyle(.white.opacity(0.9))
                            .padding(.top, 4)
                            .padding(.horizontal, 12)
                    }
                }

                Spacer()

                VStack(spacing: 12) {
                    if appState.canDeactivateAlarm {
                        Button {
                            Task { await authenticateThenDeactivateAlarm() }
                        } label: {
                            Label(isUpdatingAlarm ? "Disabling Alarm..." : "Disable Alarm", systemImage: "bell.slash.fill")
                                .font(.headline.weight(.bold))
                                .foregroundStyle(accent)
                                .frame(maxWidth: .infinity, minHeight: 58)
                                .background(Color.white)
                                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                        }
                        .buttonStyle(PressableScaleButtonStyle())
                        .disabled(isUpdatingAlarm)
                    }

                    Button {
                        showAlarmTakeover = false
                    } label: {
                        Text("View Dashboard")
                            .font(.headline.weight(.bold))
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity, minHeight: 54)
                            .background(Color.white.opacity(0.18))
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                            .overlay(
                                RoundedRectangle(cornerRadius: 16, style: .continuous)
                                    .stroke(Color.white.opacity(0.32), lineWidth: 1)
                            )
                    }
                    .buttonStyle(PressableScaleButtonStyle())
                }
                .padding(.horizontal, 22)
                .padding(.bottom, 26)
            }
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

                VStack(alignment: .leading, spacing: 2) {
                    Text("BlueBird Alerts")
                        .font(.headline)
                        .foregroundStyle(textPrimary)
                    if !appState.effectiveSchoolName.isEmpty {
                        if appState.isMultiTenant {
                            Menu {
                                ForEach(appState.tenants) { tenant in
                                    Button(tenant.tenantName) {
                                        appState.switchTenant(slug: tenant.tenantSlug, name: tenant.tenantName)
                                    }
                                }
                            } label: {
                                HStack(spacing: 4) {
                                    Text(appState.effectiveSchoolName)
                                        .font(.subheadline.weight(.medium))
                                        .foregroundStyle(textPrimary.opacity(0.75))
                                    Image(systemName: "chevron.up.chevron.down")
                                        .font(.caption2)
                                        .foregroundStyle(textMuted)
                                }
                            }
                        } else {
                            Text(appState.effectiveSchoolName)
                                .font(.subheadline.weight(.medium))
                                .foregroundStyle(textPrimary.opacity(0.75))
                        }
                    }
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
                        if alarmAcknowledgementCount > 0 {
                            Text("✓ \(alarmAcknowledgementCount) acknowledged")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(DSColor.success)
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
                if isDistrictSession {
                    Button {
                        showDistrictView = true
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "building.2.fill")
                            Text("District Overview")
                        }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity, minHeight: 46)
                        .background(DSColor.info)
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                    .shadow(color: DSColor.info.opacity(0.16), radius: 8, x: 0, y: 3)
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
                                    pendingQuietActionItem = item
                                    pendingQuietActionIsApprove = true
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
                                    pendingQuietActionItem = item
                                    pendingQuietActionIsApprove = false
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

    private var trainingModeCard: some View {
        card {
            VStack(spacing: 14) {
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
                    HStack(spacing: 10) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Silent Alarm Audio")
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(textPrimary)
                            Text("Show the alarm flow without siren volume.")
                                .font(.caption)
                                .foregroundStyle(textMuted)
                        }
                        Spacer()
                        Toggle("", isOn: $silentTrainingAudioEnabled)
                            .labelsHidden()
                    }
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
                if myQuietRequest?.status?.lowercased() == "pending" {
                    card {
                        VStack(alignment: .leading, spacing: 12) {
                            HStack(alignment: .top) {
                                Text("Quiet Period Requested")
                                    .font(.headline)
                                    .foregroundStyle(DSColor.textPrimary)
                                Spacer()
                                Text("Pending Approval")
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                    .foregroundStyle(DSColor.info)
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 4)
                                    .background(DSColor.info.opacity(0.12))
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                                            .stroke(DSColor.info.opacity(0.35), lineWidth: 1)
                                    )
                                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                            if let requestedAt = myQuietRequest?.requestedAt {
                                Text("Requested: \(requestedAt)")
                                    .font(.subheadline)
                                    .foregroundStyle(DSColor.textSecondary)
                            }
                            if let reason = myQuietRequest?.reason, !reason.isEmpty {
                                Text("Reason: \(reason)")
                                    .font(.subheadline)
                                    .foregroundStyle(DSColor.textSecondary)
                            }
                            Button {
                                showCancelQuietRequestConfirm = true
                            } label: {
                                Text(isCancellingQuietRequest ? "Cancelling..." : "Cancel Request")
                                    .font(.body)
                                    .fontWeight(.semibold)
                                    .foregroundStyle(DSColor.danger)
                                    .frame(maxWidth: .infinity, minHeight: 44)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                                            .stroke(DSColor.danger.opacity(0.5), lineWidth: 1.5)
                                    )
                            }
                            .buttonStyle(PressableScaleButtonStyle())
                            .disabled(isCancellingQuietRequest)
                            if let feedback = quietPeriodLocalFeedback {
                                flashBanner(message: feedback, isError: quietPeriodLocalIsError)
                            }
                        }
                    }
                } else if myQuietRequest?.status?.lowercased() == "approved" {
                    card {
                        VStack(alignment: .leading, spacing: 12) {
                            HStack(alignment: .top) {
                                Text("Quiet Period Active")
                                    .font(.headline)
                                    .foregroundStyle(DSColor.textPrimary)
                                Spacer()
                                Text("Active")
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                    .foregroundStyle(DSColor.success)
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 4)
                                    .background(DSColor.success.opacity(0.12))
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                                            .stroke(DSColor.success.opacity(0.35), lineWidth: 1)
                                    )
                                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                            if let label = myQuietRequest?.approvedByLabel {
                                Text("Approved by: \(label)")
                                    .font(.subheadline)
                                    .foregroundStyle(DSColor.textSecondary)
                            }
                            if let expiresAt = myQuietRequest?.expiresAt {
                                Text("Expires: \(expiresAt)")
                                    .font(.subheadline)
                                    .foregroundStyle(DSColor.textSecondary)
                            }
                            Button {
                                showCancelQuietRequestConfirm = true
                            } label: {
                                Text(isCancellingQuietRequest ? "Ending..." : "End Quiet Period")
                                    .font(.body)
                                    .fontWeight(.semibold)
                                    .foregroundStyle(DSColor.danger)
                                    .frame(maxWidth: .infinity, minHeight: 44)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                                            .stroke(DSColor.danger.opacity(0.5), lineWidth: 1.5)
                                    )
                            }
                            .buttonStyle(PressableScaleButtonStyle())
                            .disabled(isCancellingQuietRequest)
                            if let feedback = quietPeriodLocalFeedback {
                                flashBanner(message: feedback, isError: quietPeriodLocalIsError)
                            }
                        }
                    }
                } else {
                    if myQuietRequest?.status?.lowercased() == "denied" {
                        card {
                            HStack(spacing: 10) {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundStyle(DSColor.danger)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Request Denied")
                                        .font(.subheadline)
                                        .fontWeight(.semibold)
                                        .foregroundStyle(DSColor.textPrimary)
                                    if let label = myQuietRequest?.approvedByLabel {
                                        Text("by \(label)")
                                            .font(.caption)
                                            .foregroundStyle(DSColor.textSecondary)
                                    }
                                }
                                Spacer()
                            }
                            .padding(.vertical, 2)
                        }
                    }
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
                            if let feedback = quietPeriodLocalFeedback {
                                flashBanner(message: feedback, isError: quietPeriodLocalIsError)
                            }
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
        .onAppear {
            Task { await loadMyQuietRequest() }
        }
        .confirmationDialog(
            myQuietRequest?.status?.lowercased() == "approved"
                ? "End your active quiet period?"
                : "Cancel this quiet period request?",
            isPresented: $showCancelQuietRequestConfirm,
            titleVisibility: .visible
        ) {
            Button(
                myQuietRequest?.status?.lowercased() == "approved" ? "End Quiet Period" : "Cancel Request",
                role: .destructive
            ) {
                Task { await cancelQuietPeriodRequest() }
            }
            Button(
                myQuietRequest?.status?.lowercased() == "approved" ? "Keep Quiet Period" : "Keep Request",
                role: .cancel
            ) {}
        } message: {
            Text(myQuietRequest?.status?.lowercased() == "approved"
                 ? "Push notifications will resume immediately."
                 : "This will cancel your pending quiet period request.")
        }
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
            pendingAlertAction = action
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

    private var adminPushStatsCard: some View {
        card {
            VStack(alignment: .leading, spacing: 8) {
                Text("Push Delivery")
                    .font(.headline)
                    .foregroundStyle(textPrimary)
                if let stats = pushDeliveryStats {
                    if stats.total == 0 {
                        Text("No deliveries recorded for current alert.")
                            .font(.subheadline)
                            .foregroundStyle(textMuted)
                    } else {
                        HStack(spacing: 16) {
                            Label("\(stats.ok) sent", systemImage: "checkmark.circle.fill")
                                .foregroundStyle(DSColor.success)
                            if stats.failed > 0 {
                                Label("\(stats.failed) failed", systemImage: "exclamationmark.triangle.fill")
                                    .foregroundStyle(DSColor.danger)
                            }
                        }
                        .font(.subheadline.weight(.semibold))
                        if let err = stats.lastError, !err.isEmpty {
                            Text("Last error: \(err)")
                                .font(.caption)
                                .foregroundStyle(DSColor.danger)
                                .lineLimit(2)
                        }
                    }
                } else {
                    Text("—")
                        .font(.subheadline)
                        .foregroundStyle(textMuted)
                }
            }
        }
    }

    private var auditLogButtonCard: some View {
        card {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Audit Log")
                        .font(.headline)
                        .foregroundStyle(textPrimary)
                    Text("View activity, logins, and user changes")
                        .font(.caption)
                        .foregroundStyle(textMuted)
                }
                Spacer()
                Button {
                    showAuditLogModal = true
                } label: {
                    HStack(spacing: 4) {
                        Text("View Logs")
                            .font(.caption.weight(.semibold))
                        Image(systemName: "chevron.right")
                            .font(.caption2)
                    }
                    .foregroundStyle(bluePrimary)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(bluePrimary.opacity(0.1))
                    .clipShape(Capsule())
                }
            }
        }
        .sheet(isPresented: $showAuditLogModal) {
            AuditLogsModal(api: api, userID: appState.userID ?? 0)
        }
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
                    if item.status == "open" || item.status == "active" {
                        Button {
                            Task { await applyTeamAssistAction(item, action: "acknowledge") }
                        } label: {
                            Text("Acknowledge")
                                .font(.caption.weight(.semibold))
                                .padding(.horizontal, 12)
                                .padding(.vertical, 7)
                                .background(bluePrimary.opacity(0.14))
                                .clipShape(Capsule())
                        }
                        .disabled(isUpdatingTeamAssist)
                    }
                    if item.status != "resolved" && item.status != "cancelled" {
                        Button {
                            Task { await applyTeamAssistAction(item, action: "resolve") }
                        } label: {
                            Text("Resolve")
                                .font(.caption.weight(.semibold))
                                .padding(.horizontal, 12)
                                .padding(.vertical, 7)
                                .background(DSColor.success.opacity(0.14))
                                .clipShape(Capsule())
                        }
                        .disabled(isUpdatingTeamAssist)
                        Button {
                            forwardingTeamAssist = item
                        } label: {
                            Text("Forward…")
                                .font(.caption.weight(.semibold))
                                .padding(.horizontal, 12)
                                .padding(.vertical, 7)
                                .background(DSColor.textSecondary.opacity(0.14))
                                .clipShape(Capsule())
                        }
                        .disabled(isUpdatingTeamAssist)
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
        var errors: [String] = []
        var anySuccess = false

        do {
            let incidents = try await api.activeIncidents()
            activeIncidents = incidents.incidents
            anySuccess = true
        } catch {
            errors.append("Incidents: \(error.localizedDescription)")
        }

        do {
            let teamAssists = try await api.activeRequestHelp()
            activeTeamAssists = teamAssists.teamAssists
            syncAdminRequestHelpPrompt()
            anySuccess = true
        } catch {
            errors.append("Request Help: \(error.localizedDescription)")
        }

        do {
            let alarm = try await api.alarmStatus()
            alarmIsActive = alarm.isActive
            alarmMessage = alarm.message
            alarmIsTraining = alarm.isTraining
            alarmTrainingLabel = alarm.trainingLabel
            alarmSilentAudio = alarm.silentAudio
            alarmAcknowledgementCount = alarm.acknowledgementCount
            alarmCurrentUserAcknowledged = alarm.currentUserAcknowledged
            anySuccess = true
        } catch {
            errors.append("Alarm status: \(error.localizedDescription)")
        }

        appState.backendReachable = anySuccess
        if errors.isEmpty {
            appState.lastError = nil
        } else {
            appState.lastError = "Incident feed refresh failed: \(errors.joined(separator: " | "))"
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
                trainingLabel: isAdminSession && trainingModeEnabled ? trainingLabel : nil,
                silentAudio: isAdminSession && trainingModeEnabled && silentTrainingAudioEnabled
            )
            alarmIsActive = true
            alarmMessage = trimmed
            alarmIsTraining = isAdminSession && trainingModeEnabled
            alarmTrainingLabel = alarmIsTraining ? trainingLabel : nil
            alarmSilentAudio = alarmIsTraining && silentTrainingAudioEnabled
            syncAlarmAudio()
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
        if appState.endAlertConfirmationEnabled && !alarmIsTraining {
            showDeactivateConfirmation = true
        } else {
            await deactivateAlarm()
        }
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
            alarmSilentAudio = response.silentAudio
            appState.lastStatus = response.isActive ? "Alarm remains active." : "Alarm disabled."
            appState.lastError = nil
            if !response.isActive {
                syncAlarmAudio()
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

    private func loadPushDeliveryStats() async {
        guard isAdminSession, let adminUserID = appState.userID else { return }
        pushDeliveryStats = try? await api.alarmPushStats(userID: adminUserID)
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
            quietPeriodLocalFeedback = "You must be signed in to request a quiet period."
            quietPeriodLocalIsError = true
            return
        }
        #if DEBUG
        print("[QuietPeriod] Submit tapped — userID: \(userID)")
        #endif
        isSubmittingQuickAction = true
        quietPeriodLocalFeedback = nil
        defer { isSubmittingQuickAction = false }
        do {
            let trimmed = quietPeriodReason.trimmingCharacters(in: .whitespacesAndNewlines)
            #if DEBUG
            print("[QuietPeriod] POST /quiet-periods/request — reason: \(trimmed.isEmpty ? "<none>" : trimmed)")
            #endif
            let result = try await api.requestQuietPeriod(
                userID: userID,
                reason: trimmed.isEmpty ? nil : trimmed
            )
            #if DEBUG
            print("[QuietPeriod] Request submitted successfully")
            #endif
            quietPeriodReason = ""
            myQuietRequest = result
            quietPeriodLocalFeedback = nil
            quietPeriodLocalIsError = false
            appState.lastError = nil
            appState.lastStatus = "Quiet period request submitted."
            if isAdminSession {
                await loadAdminQuietPeriodRequests()
            }
        } catch {
            #if DEBUG
            print("[QuietPeriod] Request failed: \(error)")
            #endif
            quietPeriodLocalFeedback = "Request failed: \(error.localizedDescription)"
            quietPeriodLocalIsError = true
            appState.lastError = "Quiet period request failed: \(error.localizedDescription)"
        }
    }

    private func loadMyQuietRequest() async {
        guard let userID = appState.userID else { return }
        do {
            let result = try await api.quietPeriodStatus(userID: userID)
            myQuietRequest = result.status != nil ? result : nil
        } catch {
            myQuietRequest = nil
        }
    }

    private func cancelQuietPeriodRequest() async {
        guard let userID = appState.userID,
              let requestID = myQuietRequest?.requestID else { return }
        isCancellingQuietRequest = true
        defer { isCancellingQuietRequest = false }
        do {
            _ = try await api.cancelQuietRequest(requestID: requestID, userID: userID)
            myQuietRequest = nil
            quietPeriodLocalFeedback = nil
        } catch {
            quietPeriodLocalFeedback = "Could not cancel request: \(error.localizedDescription)"
            quietPeriodLocalIsError = true
        }
    }

    private func dismissKeyboard() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }

    private func loadMeData() async {
        guard let userID = appState.userID else { return }
        let homeAPI = APIClient(baseURL: appState.serverURL, apiKey: Config.backendApiKey)
        do {
            let me = try await homeAPI.me(userID: userID)
            appState.updateTenants(
                me.tenants,
                selectedSlug: me.selectedTenant,
                selectedName: me.tenants.first(where: { $0.tenantSlug == me.selectedTenant })?.tenantName ?? ""
            )
            if let title = me.title, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                appState.updateUserTitle(title)
            }
        } catch {
            // Non-critical — app still works on single-tenant without /me data
        }
    }

    private func loadDistrictOverview() async {
        guard let userID = appState.userID else { return }
        do {
            let response = try await api.districtOverview(userID: userID)
            districtTenants = response.tenants
        } catch {
            appState.lastError = "District overview failed: \(error.localizedDescription)"
        }
    }

    private func connectAlarmWebSocket() async {
        guard let userID = appState.userID else { return }
        let slug: String = {
            if !appState.selectedTenantSlug.isEmpty { return appState.selectedTenantSlug }
            let parts = appState.serverURL.pathComponents.filter { !$0.isEmpty && $0 != "/" }
            return parts.first ?? "default"
        }()
        guard var components = URLComponents(url: appState.serverBaseURL, resolvingAgainstBaseURL: false) else { return }
        components.scheme = (components.scheme == "https") ? "wss" : "ws"
        components.path = "/ws/\(slug)/alerts"
        components.queryItems = [
            URLQueryItem(name: "user_id", value: String(userID)),
            URLQueryItem(name: "api_key", value: Config.backendApiKey),
        ]
        guard let wsURL = components.url else { return }

        var delay: UInt64 = 2_000_000_000
        let maxDelay: UInt64 = 15_000_000_000
        while !Task.isCancelled {
            #if DEBUG
            print("[WS] Connecting: \(slug)")
            #endif
            let wsTask = URLSession(configuration: .default).webSocketTask(with: wsURL)
            wsTask.resume()
            var connectedOnce = false
            receiveLoop: while !Task.isCancelled {
                do {
                    let msg = try await wsTask.receive()
                    if !connectedOnce {
                        connectedOnce = true
                        delay = 2_000_000_000  // reset backoff on successful connection
                        #if DEBUG
                        print("[WS] Connected: \(slug)")
                        #endif
                    }
                    if case .string(let text) = msg,
                       let data = text.data(using: .utf8),
                       let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                        #if DEBUG
                        print("[WS] Event: \(json["event"] as? String ?? "unknown")")
                        #endif
                        handleAlarmWebSocketEvent(json)
                    }
                } catch {
                    #if DEBUG
                    print("[WS] Disconnected: \(slug) — \(error.localizedDescription)")
                    #endif
                    break receiveLoop
                }
            }
            // Always close the task cleanly, even if Swift cancelled the outer Task.
            wsTask.cancel(with: .normalClosure, reason: nil)
            guard !Task.isCancelled else { return }
            #if DEBUG
            print("[WS] Reconnecting in \(delay / 1_000_000_000)s: \(slug)")
            #endif
            try? await Task.sleep(nanoseconds: delay)
            delay = min(delay * 2, maxDelay)
        }
    }

    private func handleAlarmWebSocketEvent(_ json: [String: Any]) {
        let event = json["event"] as? String ?? ""

        // Deduplication: ignore events already processed (bounded to 200 entries)
        if let eventID = json["event_id"] as? String, !eventID.isEmpty {
            guard !processedEventIDs.contains(eventID) else {
                #if DEBUG
                print("[WS] Dedup skip eventID=\(eventID) event=\(event)")
                #endif
                return
            }
            processedEventIDs.insert(eventID)
            if processedEventIDs.count > 200 { processedEventIDs.remove(processedEventIDs.first!) }
        }

        let eventSlug = (json["tenant_slug"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        // Alarm fields are nested inside the "alarm" key in every backend event.
        let alarm = json["alarm"] as? [String: Any]

        // Resolve current slug (selectedTenantSlug is empty before /me loads on first launch).
        let currentSlug: String = {
            if !appState.selectedTenantSlug.isEmpty { return appState.selectedTenantSlug }
            let parts = appState.serverURL.pathComponents.filter { !$0.isEmpty && $0 != "/" }
            return parts.first ?? ""
        }()
        let isCurrentTenant = eventSlug.isEmpty || eventSlug == currentSlug

        // Update district overview rows for any tenant without a full refetch.
        if !eventSlug.isEmpty {
            applyEventToDistrictTenant(slug: eventSlug, event: event, alarm: alarm)
        }

        // Guard: only update local alarm state when the event is for the active tenant.
        guard isCurrentTenant else {
            #if DEBUG
            print("[WS] Cross-tenant event '\(event)' for '\(eventSlug)' (active: '\(currentSlug)') — main state unchanged")
            #endif
            return
        }

        switch event {
        case "alarm_activated", "alert_triggered":
            let wasActive = alarmIsActive
            if let a = alarm {
                if let v = a["is_active"] as? Bool { alarmIsActive = v }
                if let v = a["message"] as? String { alarmMessage = v }
                if let v = a["is_training"] as? Bool { alarmIsTraining = v }
                alarmTrainingLabel = a["training_label"] as? String
                if let v = a["silent_audio"] as? Bool { alarmSilentAudio = v }
            }
            if alarmIsActive && !wasActive {
                showAlarmTakeover = true
                syncAlarmAudio()
                updateAlertFeedbackState()
            }
            Task { await refreshIncidentFeed() }

        case "alarm_deactivated", "tenant_alert_cleared":
            alarmIsActive = false
            alarmMessage = nil
            alarmIsTraining = false
            alarmTrainingLabel = nil
            alarmSilentAudio = false
            syncAlarmAudio()
            updateAlertFeedbackState()
            Task { await refreshIncidentFeed() }

        case "tenant_alert_updated":
            if let a = alarm {
                if let v = a["is_active"] as? Bool { alarmIsActive = v }
                if let v = a["message"] as? String { alarmMessage = v }
                if let v = a["is_training"] as? Bool { alarmIsTraining = v }
                alarmTrainingLabel = a["training_label"] as? String
                if let v = a["silent_audio"] as? Bool { alarmSilentAudio = v }
            }
            if !alarmIsActive {
                syncAlarmAudio()
                updateAlertFeedbackState()
            } else {
                syncAlarmAudio()
            }
            Task { await refreshIncidentFeed() }

        case "tenant_acknowledgement_updated":
            // Ack count is surfaced via refreshIncidentFeed / alarm status poll.
            // districtTenants already updated above via applyEventToDistrictTenant.
            break

        case "quiet_request_created", "quiet_request_updated":
            if isAdminSession { Task { await loadAdminQuietPeriodRequests() } }
            Task { await loadMyQuietRequest() }

        case "message_received":
            break

        case "help_request_acknowledged", "help_request_resolved":
            Task { await refreshIncidentFeed() }

        case "theme_updated":
            let themeAccent = json["accent"] as? String ?? ""
            let themeAccentStrong = json["accent_strong"] as? String ?? ""
            let themeSidebarStart = json["sidebar_start"] as? String ?? ""
            if !themeAccent.isEmpty || !themeSidebarStart.isEmpty {
                DSBranding.apply(
                    primary: themeSidebarStart.isEmpty ? themeAccent : themeSidebarStart,
                    accent: themeAccent.isEmpty ? themeAccentStrong : themeAccent
                )
            }

        default:
            #if DEBUG
            print("[WS] Unknown event type: '\(event)'")
            #endif
            break
        }
    }

    private func applyEventToDistrictTenant(slug: String, event: String, alarm: [String: Any]?) {
        guard let idx = districtTenants.firstIndex(where: { $0.tenantSlug == slug }) else { return }
        let old = districtTenants[idx]
        let updated: TenantOverviewItem
        switch event {
        case "alarm_activated", "alert_triggered", "tenant_alert_updated":
            guard let a = alarm else { return }
            updated = TenantOverviewItem(
                tenantSlug: old.tenantSlug,
                tenantName: old.tenantName,
                alarmIsActive: a["is_active"] as? Bool ?? old.alarmIsActive,
                alarmMessage: a["message"] as? String ?? old.alarmMessage,
                alarmIsTraining: a["is_training"] as? Bool ?? old.alarmIsTraining,
                lastAlertAt: a["activated_at"] as? String ?? old.lastAlertAt,
                acknowledgementCount: old.acknowledgementCount,
                expectedUserCount: old.expectedUserCount,
                acknowledgementRate: old.acknowledgementRate
            )
        case "alarm_deactivated", "tenant_alert_cleared":
            updated = TenantOverviewItem(
                tenantSlug: old.tenantSlug,
                tenantName: old.tenantName,
                alarmIsActive: false,
                alarmMessage: nil,
                alarmIsTraining: false,
                lastAlertAt: old.lastAlertAt,
                acknowledgementCount: old.acknowledgementCount,
                expectedUserCount: old.expectedUserCount,
                acknowledgementRate: old.acknowledgementRate
            )
        case "tenant_acknowledgement_updated":
            guard let a = alarm, let count = a["acknowledgement_count"] as? Int else { return }
            let rate: Double = old.expectedUserCount > 0
                ? Double(count) / Double(old.expectedUserCount)
                : old.acknowledgementRate
            updated = TenantOverviewItem(
                tenantSlug: old.tenantSlug,
                tenantName: old.tenantName,
                alarmIsActive: old.alarmIsActive,
                alarmMessage: old.alarmMessage,
                alarmIsTraining: old.alarmIsTraining,
                lastAlertAt: old.lastAlertAt,
                acknowledgementCount: count,
                expectedUserCount: old.expectedUserCount,
                acknowledgementRate: rate
            )
        default:
            return
        }
        districtTenants[idx] = updated
    }

    private var districtOverviewPage: some View {
        ScrollView {
            VStack(spacing: 14) {
                if districtTenants.isEmpty {
                    card {
                        Text("Loading district overview...")
                            .font(.subheadline)
                            .foregroundStyle(textMuted)
                            .frame(maxWidth: .infinity, alignment: .center)
                    }
                } else {
                    ForEach(districtTenants) { tenant in
                        card {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text(tenant.tenantName)
                                        .font(.headline)
                                        .foregroundStyle(textPrimary)
                                    Spacer()
                                    Circle()
                                        .fill(tenant.alarmIsActive
                                              ? (tenant.alarmIsTraining ? DSColor.warning : DSColor.danger)
                                              : DSColor.success)
                                        .frame(width: 10, height: 10)
                                }
                                if tenant.alarmIsActive {
                                    Text(tenant.alarmIsTraining ? "Training Drill Active" : "ALARM ACTIVE")
                                        .font(.subheadline.weight(.bold))
                                        .foregroundStyle(tenant.alarmIsTraining ? DSColor.warning : DSColor.danger)
                                    if let msg = tenant.alarmMessage, !msg.isEmpty {
                                        Text(msg)
                                            .font(.caption)
                                            .foregroundStyle(textMuted)
                                    }
                                } else {
                                    Text("No active alarm")
                                        .font(.subheadline)
                                        .foregroundStyle(textMuted)
                                }
                                if tenant.expectedUserCount > 0 {
                                    let rate = Int((tenant.acknowledgementRate * 100).rounded())
                                    Text("Ack: \(tenant.acknowledgementCount)/\(tenant.expectedUserCount) (\(rate)%)")
                                        .font(.caption)
                                        .foregroundStyle(textMuted)
                                }
                            }
                        }
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
        }
        .background(
            LinearGradient(colors: [appBg, appBgDeep], startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
        )
        .navigationTitle("District Overview")
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadDistrictOverview() }
        .refreshable { await loadDistrictOverview() }
    }

    private func authenticateIfNeeded(reason: String) async -> Bool {
        if !appState.biometricsAllowed { return true }
        let context = LAContext()
        context.localizedFallbackTitle = "Use Passcode"
        var error: NSError?
        let biometricPolicy: LAPolicy = .deviceOwnerAuthenticationWithBiometrics
        if context.canEvaluatePolicy(biometricPolicy, error: &error) {
            return await withCheckedContinuation { continuation in
                context.evaluatePolicy(biometricPolicy, localizedReason: reason) { success, _ in
                    continuation.resume(returning: success)
                }
            }
        }

        let fallbackPolicy: LAPolicy = .deviceOwnerAuthentication
        guard context.canEvaluatePolicy(fallbackPolicy, error: &error) else {
            return true
        }
        return await withCheckedContinuation { continuation in
            context.evaluatePolicy(fallbackPolicy, localizedReason: reason) { success, _ in
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
    let onResolve: () -> Void
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
                Text("Acknowledge to log receipt, or Resolve to close the request.")
                    .font(.subheadline)
                    .foregroundStyle(textPrimary)

                HStack(spacing: 10) {
                    Button("Acknowledge") { onAcknowledge() }
                        .buttonStyle(.bordered)
                        .tint(bluePrimary)
                        .disabled(isBusy)
                    Button("Resolve") { onResolve() }
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

            ScrollView {
                VStack(spacing: 16) {
                    // Account
                    settingsCard {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("ACCOUNT")
                                .font(.caption)
                                .fontWeight(.semibold)
                                .foregroundStyle(DSColor.textSecondary)
                                .tracking(0.8)
                            Text(appState.userName.isEmpty ? "BlueBird Alerts" : appState.userName)
                                .font(.title3)
                                .fontWeight(.bold)
                                .foregroundStyle(DSColor.textPrimary)
                            if !appState.loginName.isEmpty {
                                Text("@\(appState.loginName)")
                                    .font(.subheadline)
                                    .foregroundStyle(DSColor.primary)
                            }
                            Divider()
                            settingsInfoRow("Role", value: appState.userRole.capitalized)
                            settingsInfoRow("Server", value: appState.serverURL.absoluteString, small: true, muted: true)
                            if !appState.initialDeviceAuthUserName.isEmpty {
                                settingsInfoRow("Device Auth", value: appState.initialDeviceAuthUserName, small: true, muted: true)
                            }
                        }
                    }

                    // Appearance
                    settingsCard {
                        VStack(alignment: .leading, spacing: 14) {
                            Text("Appearance")
                                .font(.headline)
                                .foregroundStyle(DSColor.textPrimary)
                            Picker("Theme", selection: $themeModeRaw) {
                                ForEach(DSThemeMode.allCases, id: \.rawValue) { mode in
                                    Text(mode.rawValue.capitalized).tag(mode.rawValue)
                                }
                            }
                            .pickerStyle(.segmented)
                        }
                    }

                    // Security
                    settingsCard {
                        VStack(alignment: .leading, spacing: 14) {
                            Text("Security")
                                .font(.headline)
                                .foregroundStyle(DSColor.textPrimary)
                            settingsToggleRow(
                                title: "Require Biometrics",
                                description: "Require Face ID or Touch ID before sending emergency alerts.",
                                isOn: $appState.biometricsAllowed
                            )
                            Divider().opacity(0.5)
                            settingsToggleRow(
                                title: "Confirm Before Ending Alerts",
                                description: "Show a confirmation dialog before deactivating a live alarm. Training drills always skip confirmation.",
                                isOn: $appState.endAlertConfirmationEnabled
                            )
                        }
                    }

                    // Emergency Feedback
                    settingsCard {
                        VStack(alignment: .leading, spacing: 14) {
                            Text("Emergency Feedback")
                                .font(.headline)
                                .foregroundStyle(DSColor.textPrimary)
                            settingsToggleRow(title: "Haptic Alerts", description: "Pulse vibration during active emergencies.", isOn: $appState.hapticAlertsEnabled)
                            Divider().opacity(0.5)
                            settingsToggleRow(title: "Flashlight Alerts", description: "Flash the device torch while the alert screen is active.", isOn: $appState.flashlightAlertsEnabled)
                            Divider().opacity(0.5)
                            settingsToggleRow(title: "Screen Flash Alerts", description: "Pulse a full-screen warning overlay during emergencies.", isOn: $appState.screenFlashAlertsEnabled)
                            Text("Enable LED Flash Alerts in device settings for enhanced visibility.")
                                .font(.footnote)
                                .foregroundStyle(DSColor.textSecondary)
                        }
                    }

                    // Diagnostics
                    settingsCard {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Diagnostics")
                                .font(.headline)
                                .foregroundStyle(DSColor.textPrimary)
                            Button(isTestingBackend ? "Testing…" : "Test Backend") {
                                Task { await testBackend() }
                            }
                            .font(.subheadline)
                            .foregroundStyle(DSColor.primary)
                            .disabled(isTestingBackend)
                            Button(isLoadingDebugData ? "Refreshing…" : "Load Debug Data") {
                                Task { await loadDebugData() }
                            }
                            .font(.subheadline)
                            .foregroundStyle(DSColor.primary)
                            .disabled(isLoadingDebugData)
                            if appState.deviceToken != nil {
                                Button(isRegistering ? "Registering…" : "Register Device") {
                                    Task { await retryRegisterDevice() }
                                }
                                .font(.subheadline)
                                .foregroundStyle(DSColor.primary)
                                .disabled(isRegistering)
                            }
                            Button(isRegistering ? "Registering…" : localTestButtonTitle) {
                                Task { await useLocalTestDevice() }
                            }
                            .font(.subheadline)
                            .foregroundStyle(DSColor.primary)
                            .disabled(isRegistering)
                        }
                    }

                    // Sign Out
                    Button {
                        appState.logout()
                    } label: {
                        Text("Sign Out")
                            .font(.headline)
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                            .background(DSColor.danger, in: RoundedRectangle(cornerRadius: 14))
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 16)
                .padding(.bottom, 32)
            }
        }
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
    }

    @ViewBuilder
    private func settingsCard<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        content()
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(DSColor.card, in: RoundedRectangle(cornerRadius: 16))
            .shadow(color: .black.opacity(0.06), radius: 8, x: 0, y: 2)
    }

    @ViewBuilder
    private func settingsToggleRow(title: String, description: String, isOn: Binding<Bool>) -> some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.subheadline)
                    .fontWeight(.semibold)
                    .foregroundStyle(DSColor.textPrimary)
                Text(description)
                    .font(.caption)
                    .foregroundStyle(DSColor.textSecondary)
            }
            Spacer()
            Toggle("", isOn: isOn)
                .labelsHidden()
                .tint(DSColor.primary)
        }
    }

    private func settingsInfoRow(_ label: String, value: String, small: Bool = false, muted: Bool = false) -> some View {
        HStack(alignment: .top) {
            Text(label)
                .font(small ? .caption : .subheadline)
                .foregroundStyle(DSColor.textSecondary)
            Spacer()
            Text(value)
                .font(small ? .caption : .subheadline)
                .foregroundStyle(muted ? DSColor.textSecondary : DSColor.textPrimary)
                .multilineTextAlignment(.trailing)
        }
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
