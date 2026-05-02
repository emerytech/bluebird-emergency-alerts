import SwiftUI
import Combine

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Data Model
// ─────────────────────────────────────────────────────────────────────────────

enum LCGuideID: String, CaseIterable {
    case initiateEmergency  = "initiate_emergency"
    case viewMessages       = "view_messages"
    case teamAssist         = "team_assist"
    case accountForYourself = "account_for_yourself"
    case accountForStudents = "account_for_students"
    case reunification      = "reunification"

    var title: String {
        switch self {
        case .initiateEmergency:  return "Initiate an Emergency"
        case .viewMessages:       return "View Messages"
        case .teamAssist:         return "Team Assist"
        case .accountForYourself: return "Account for Yourself"
        case .accountForStudents: return "Account for Students"
        case .reunification:      return "Reunification"
        }
    }

    var introDescription: String {
        switch self {
        case .initiateEmergency:
            return "Learn how to initiate an emergency alert and manage an active incident safely."
        case .viewMessages:
            return "Learn how to send and receive messages during and outside of emergencies."
        case .teamAssist:
            return "Learn how to request team assistance for non-emergency situations."
        case .accountForYourself:
            return "Learn how to mark yourself safe during an emergency."
        case .accountForStudents:
            return "Learn how to account for students in your care during an emergency."
        case .reunification:
            return "Learn how to manage the reunification process after an emergency."
        }
    }

    var icon: String {
        switch self {
        case .initiateEmergency:  return "exclamationmark.triangle.fill"
        case .viewMessages:       return "message.fill"
        case .teamAssist:         return "person.2.fill"
        case .accountForYourself: return "checkmark.circle.fill"
        case .accountForStudents: return "list.bullet.clipboard.fill"
        case .reunification:      return "figure.walk"
        }
    }

    var color: Color {
        switch self {
        case .initiateEmergency:  return DSColor.danger
        case .viewMessages:       return DSColor.primary
        case .teamAssist:         return DSColor.warning
        case .accountForYourself: return DSColor.success
        case .accountForStudents: return DSColor.info
        case .reunification:      return DSColor.primary
        }
    }
}

enum LCStepKind {
    case info(imageName: String? = nil)
    case iconGrid(items: [(icon: String, label: String, color: Color)])
    case slideToConfirm(label: String, iconName: String)
    case holdButton(emergencyType: String, color: Color)
    case alarmTakeover(emergencyType: String)
    case acknowledgeButton
    case mockNotification(appName: String, title: String, body: String)
    case visualCopy(placeholder: String)
}

struct LCStep {
    let title: String
    let description: String
    let kind: LCStepKind
}

struct LCGuide: Identifiable, Hashable {
    let id: LCGuideID
    let steps: [LCStep]
    var title: String { id.title }
    var introDescription: String { id.introDescription }

    static func == (lhs: LCGuide, rhs: LCGuide) -> Bool {
        lhs.id == rhs.id
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Guide Definitions
// ─────────────────────────────────────────────────────────────────────────────

let LC_ALL_GUIDES: [LCGuide] = [

    // ── GUIDE 1 — FULLY IMPLEMENTED ─────────────────────────────────────────
    LCGuide(id: .initiateEmergency, steps: [
        LCStep(
            title: "Emergency Types",
            description: "The main screen shows emergency types for your school — Lockdown, Evacuation, Shelter, Secure, or Hold. Each represents a specific protocol. Tap any to learn more during a real emergency.",
            kind: .iconGrid(items: [
                ("lock.fill",           "LOCKDOWN",  DSColor.danger),
                ("figure.walk.motion",  "EVACUATE",  DSColor.success),
                ("house.fill",          "SHELTER",   DSColor.warning),
                ("hand.raised.fill",    "SECURE",    DSColor.info),
                ("pause.fill",          "HOLD",      Color(red: 0.56, green: 0.23, blue: 0.92)),
            ])
        ),
        LCStep(
            title: "Hold to Activate",
            description: "Hold the circular button for your school's configured duration (typically 3 seconds). The ring fills as you hold. All staff receive an immediate alert the moment you release.",
            kind: .holdButton(emergencyType: "LOCKDOWN", color: DSColor.danger)
        ),
        LCStep(
            title: "Active Alert Screen",
            description: "When an emergency activates, every staff device shows a full-screen takeover. The acknowledgement counter updates in real time as staff tap the button below.",
            kind: .alarmTakeover(emergencyType: "LOCKDOWN")
        ),
        LCStep(
            title: "Acknowledge the Alert",
            description: "Tap Acknowledge to mark yourself safe. The counter above updates instantly. Administrators see who has and hasn't responded in real time.",
            kind: .acknowledgeButton
        ),
        LCStep(
            title: "Push Notification",
            description: "Every staff member receives a push notification the instant an emergency activates. The app opens automatically and locks to the alert screen until the emergency is cleared.",
            kind: .mockNotification(
                appName: "BlueBird Alerts",
                title: "🚨 LOCKDOWN — Lincoln Elementary",
                body: "Emergency alert activated. Open the app and follow procedures immediately."
            )
        ),
        LCStep(
            title: "You're Ready",
            description: "You now know how to initiate an emergency and what staff will experience. In a real emergency: stay calm, hold the correct button, and follow your school's established protocols.",
            kind: .info(imageName: nil)
        ),
    ]),

    // ── GUIDES 2–6 — SCAFFOLDED ──────────────────────────────────────────────
    LCGuide(id: .viewMessages, steps: [
        LCStep(
            title: "Messages Overview",
            description: "BlueBird Alerts includes a secure messaging system for communicating with staff before, during, and after emergencies. More training steps coming soon.",
            kind: .info(imageName: nil)
        ),
    ]),
    LCGuide(id: .teamAssist, steps: [
        LCStep(
            title: "Team Assist Overview",
            description: "Team Assist lets you silently request help from a colleague for non-emergency situations — a medical concern, an irate visitor, or a student issue. More steps coming soon.",
            kind: .info(imageName: nil)
        ),
    ]),
    LCGuide(id: .accountForYourself, steps: [
        LCStep(
            title: "Account for Yourself",
            description: "During an active emergency, tap Acknowledge on the alert screen to mark yourself safe. Administrators see real-time counts of who has and hasn't responded. More steps coming soon.",
            kind: .info(imageName: nil)
        ),
    ]),
    LCGuide(id: .accountForStudents, steps: [
        LCStep(
            title: "Student Accountability",
            description: "Administrators can track student status during an emergency using built-in roster tools. More steps coming soon.",
            kind: .info(imageName: nil)
        ),
    ]),
    LCGuide(id: .reunification, steps: [
        LCStep(
            title: "Reunification Overview",
            description: "After an emergency, BlueBird Alerts supports the reunification process with tracking and communication tools. More steps coming soon.",
            kind: .info(imageName: nil)
        ),
    ]),
]

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Persistence
// ─────────────────────────────────────────────────────────────────────────────

final class LearningCenterStore: ObservableObject {
    static let shared = LearningCenterStore()

    private let completedKey = "lc_completed_guides_v1"
    private let lastStepKey  = "lc_last_step_v1"

    @Published var completedGuides: Set<String> = []
    @Published var lastSteps: [String: Int] = [:]

    private init() {
        let completed = UserDefaults.standard.stringArray(forKey: completedKey) ?? []
        completedGuides = Set(completed)
        lastSteps = (UserDefaults.standard.dictionary(forKey: lastStepKey) as? [String: Int]) ?? [:]
    }

    func markComplete(_ id: LCGuideID) {
        completedGuides.insert(id.rawValue)
        UserDefaults.standard.set(Array(completedGuides), forKey: completedKey)
    }

    func saveProgress(id: LCGuideID, step: Int) {
        lastSteps[id.rawValue] = step
        UserDefaults.standard.set(lastSteps, forKey: lastStepKey)
    }

    func lastStep(for id: LCGuideID) -> Int { lastSteps[id.rawValue] ?? 0 }
    func isComplete(_ id: LCGuideID) -> Bool { completedGuides.contains(id.rawValue) }

    func reset(_ id: LCGuideID) {
        completedGuides.remove(id.rawValue)
        lastSteps.removeValue(forKey: id.rawValue)
        UserDefaults.standard.set(Array(completedGuides), forKey: completedKey)
        UserDefaults.standard.set(lastSteps, forKey: lastStepKey)
    }

    func resetAll() {
        completedGuides = []
        lastSteps = [:]
        UserDefaults.standard.removeObject(forKey: completedKey)
        UserDefaults.standard.removeObject(forKey: lastStepKey)
    }

    var completionPercentage: Double {
        guard !LC_ALL_GUIDES.isEmpty else { return 0 }
        return Double(completedGuides.count) / Double(LC_ALL_GUIDES.count)
    }

    var completedCount: Int { completedGuides.count }
    var totalCount: Int { LC_ALL_GUIDES.count }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Analytics
// ─────────────────────────────────────────────────────────────────────────────

enum LCAnalytics {
    private static let isoFormatter = ISO8601DateFormatter()

    static func track(_ event: String, guideID: String? = nil, step: Int? = nil) {
        var info: [String: Any] = [
            "event": event,
            "timestamp": isoFormatter.string(from: .now),
        ]
        if let g = guideID { info["guide_id"] = g }
        if let s = step    { info["step"] = s }
        // Events are buffered locally; the app may POST them to /{tenant}/api/training/event
        // when a network session is available.
        print("[LCAnalytics]", info)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Simulation State
// ─────────────────────────────────────────────────────────────────────────────

final class LCSimulationState: ObservableObject {
    @Published var isActivated   = false
    @Published var acknowledged  = false
    @Published var ackCount      = 2

    func reset() {
        isActivated  = false
        acknowledged = false
        ackCount     = 2
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Learning Center Menu
// ─────────────────────────────────────────────────────────────────────────────

struct LearningCenterMenuView: View {
    @Environment(\.dismiss)       private var dismiss
    @EnvironmentObject             private var appState: AppState
    @StateObject                   private var store = LearningCenterStore.shared
    @State                         private var selectedGuide: LCGuide?

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(
                    colors: [DSColor.background, DSColor.backgroundDeep],
                    startPoint: .top, endPoint: .bottom
                ).ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 0) {
                        // ── Header ────────────────────────────────────────
                        VStack(spacing: 8) {
                            Image(systemName: "graduationcap.fill")
                                .font(.system(size: 44))
                                .foregroundStyle(DSColor.primary)
                                .padding(.top, 36)
                            Text("Learning Center")
                                .font(.title.weight(.bold))
                                .foregroundStyle(DSColor.textPrimary)
                            Text("Become more familiar with BlueBird Alerts")
                                .font(.subheadline)
                                .foregroundStyle(DSColor.textSecondary)
                                .multilineTextAlignment(.center)
                        }
                        .padding(.bottom, 24)

                        // ── Progress ──────────────────────────────────────
                        VStack(spacing: 8) {
                            HStack {
                                Text("Your Progress")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(DSColor.textSecondary)
                                Spacer()
                                Text("\(store.completedCount) of \(store.totalCount) completed")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(DSColor.textSecondary)
                            }
                            ProgressView(value: store.completionPercentage)
                                .tint(DSColor.primary)
                        }
                        .padding(.horizontal, 20)
                        .padding(.bottom, 20)

                        // ── Guide list ────────────────────────────────────
                        VStack(spacing: 10) {
                            ForEach(LC_ALL_GUIDES) { guide in
                                LCGuideRow(guide: guide, store: store)
                                    .onTapGesture { selectedGuide = guide }
                            }
                        }
                        .padding(.horizontal, 16)
                        .padding(.bottom, 40)
                    }
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Close") { dismiss() }
                        .foregroundStyle(DSColor.primary)
                }
            }
            .navigationDestination(item: $selectedGuide) { guide in
                LCGuideIntroView(guide: guide)
            }
            .onChange(of: appState.alarmIsActive) { _, active in
                if active { dismiss() }
            }
        }
    }
}

private struct LCGuideRow: View {
    let guide: LCGuide
    @ObservedObject var store: LearningCenterStore

    private var isComplete: Bool  { store.isComplete(guide.id) }
    private var lastStep: Int     { store.lastStep(for: guide.id) }
    private var hasStarted: Bool  { lastStep > 0 && !isComplete }

    var body: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(guide.id.color.opacity(0.14))
                    .frame(width: 50, height: 50)
                Image(systemName: guide.id.icon)
                    .foregroundStyle(guide.id.color)
                    .font(.system(size: 20, weight: .semibold))
            }

            VStack(alignment: .leading, spacing: 3) {
                Text(guide.title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(DSColor.textPrimary)
                Text(guide.introDescription)
                    .font(.caption)
                    .foregroundStyle(DSColor.textSecondary)
                    .lineLimit(2)
            }

            Spacer()

            Group {
                if isComplete {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(DSColor.success)
                        .font(.title3)
                } else if hasStarted {
                    VStack(spacing: 2) {
                        Image(systemName: "play.circle.fill")
                            .foregroundStyle(DSColor.primary)
                            .font(.title3)
                        Text("Step \(lastStep + 1)")
                            .font(.caption2)
                            .foregroundStyle(DSColor.textSecondary)
                    }
                } else {
                    Image(systemName: "chevron.right")
                        .foregroundStyle(DSColor.textSecondary)
                        .font(.caption.weight(.semibold))
                }
            }
        }
        .padding(14)
        .background(DSColor.card, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(DSColor.border, lineWidth: 1))
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Guide Intro
// ─────────────────────────────────────────────────────────────────────────────

struct LCGuideIntroView: View {
    let guide: LCGuide
    @StateObject private var store = LearningCenterStore.shared
    @State private var showSteps = false
    @State private var startingStep = 0

    private var isComplete: Bool { store.isComplete(guide.id) }
    private var hasStarted: Bool { store.lastStep(for: guide.id) > 0 && !isComplete }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [DSColor.background, DSColor.backgroundDeep],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            VStack(spacing: 0) {
                Spacer()

                VStack(spacing: 22) {
                    ZStack {
                        Circle()
                            .fill(guide.id.color.opacity(0.12))
                            .frame(width: 100, height: 100)
                        Image(systemName: guide.id.icon)
                            .font(.system(size: 44, weight: .semibold))
                            .foregroundStyle(guide.id.color)
                    }

                    VStack(spacing: 10) {
                        Text(guide.title)
                            .font(.title.weight(.bold))
                            .foregroundStyle(DSColor.textPrimary)
                            .multilineTextAlignment(.center)
                        Text(guide.introDescription)
                            .font(.body)
                            .foregroundStyle(DSColor.textSecondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 8)
                    }

                    if isComplete {
                        Label("Completed", systemImage: "checkmark.circle.fill")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(DSColor.success)
                    }

                    Text("\(guide.steps.count) steps · ~\(guide.steps.count * 30) seconds")
                        .font(.caption)
                        .foregroundStyle(DSColor.textSecondary)
                }
                .padding(.horizontal, 24)

                Spacer()

                VStack(spacing: 12) {
                    Button {
                        startingStep = hasStarted ? store.lastStep(for: guide.id) : 0
                        LCAnalytics.track("guide_started", guideID: guide.id.rawValue)
                        showSteps = true
                    } label: {
                        Text(hasStarted ? "Resume" : isComplete ? "Retake" : "Start")
                            .font(.headline)
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 16)
                            .background(guide.id.color, in: RoundedRectangle(cornerRadius: 14))
                    }

                    if hasStarted || isComplete {
                        Button("Start Over") {
                            store.reset(guide.id)
                            startingStep = 0
                            showSteps = true
                        }
                        .font(.subheadline)
                        .foregroundStyle(DSColor.textSecondary)
                    }
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 44)
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(isPresented: $showSteps) {
            LCGuideStepView(guide: guide, startStep: startingStep)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Guide Step View
// ─────────────────────────────────────────────────────────────────────────────

struct LCGuideStepView: View {
    let guide: LCGuide

    @Environment(\.dismiss)       private var dismiss
    @EnvironmentObject             private var appState: AppState
    @StateObject                   private var store = LearningCenterStore.shared
    @StateObject                   private var simState = LCSimulationState()
    @State                         private var currentStep: Int
    @State                         private var interactionDone = false

    init(guide: LCGuide, startStep: Int = 0) {
        self.guide = guide
        _currentStep = State(initialValue: startStep)
    }

    private var step: LCStep       { guide.steps[currentStep] }
    private var isFirst: Bool      { currentStep == 0 }
    private var isLast: Bool       { currentStep == guide.steps.count - 1 }
    private var needsInteraction: Bool {
        switch step.kind {
        case .slideToConfirm, .holdButton, .acknowledgeButton: return true
        default: return false
        }
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [DSColor.background, DSColor.backgroundDeep],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            VStack(spacing: 0) {
                ScrollView {
                    VStack(spacing: 24) {
                        lcStepContent
                            .padding(.horizontal, 20)
                            .padding(.top, 28)

                        VStack(spacing: 10) {
                            Text(step.title)
                                .font(.title2.weight(.bold))
                                .foregroundStyle(DSColor.textPrimary)
                                .multilineTextAlignment(.center)
                            Text(step.description)
                                .font(.body)
                                .foregroundStyle(DSColor.textSecondary)
                                .multilineTextAlignment(.center)
                        }
                        .padding(.horizontal, 24)
                        .padding(.bottom, 24)
                    }
                }

                // ── Nav controls ─────────────────────────────────────────
                VStack(spacing: 14) {
                    HStack(spacing: 8) {
                        ForEach(0..<guide.steps.count, id: \.self) { i in
                            Capsule()
                                .fill(i == currentStep ? DSColor.primary : DSColor.border)
                                .frame(width: i == currentStep ? 20 : 8, height: 8)
                                .animation(.easeInOut(duration: 0.2), value: currentStep)
                        }
                    }

                    HStack(spacing: 10) {
                        Button {
                            withAnimation(.easeInOut(duration: 0.2)) { currentStep -= 1 }
                            interactionDone = false
                            simState.reset()
                        } label: {
                            Label("Back", systemImage: "chevron.left")
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(DSColor.textSecondary)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(DSColor.card, in: RoundedRectangle(cornerRadius: 12))
                                .overlay(RoundedRectangle(cornerRadius: 12).stroke(DSColor.border, lineWidth: 1))
                        }
                        .disabled(isFirst)
                        .opacity(isFirst ? 0.35 : 1)

                        Button {
                            if isLast {
                                store.markComplete(guide.id)
                                store.saveProgress(id: guide.id, step: 0)
                                LCAnalytics.track("guide_completed", guideID: guide.id.rawValue, step: currentStep)
                                dismiss()
                            } else {
                                LCAnalytics.track("step_completed", guideID: guide.id.rawValue, step: currentStep)
                                store.saveProgress(id: guide.id, step: currentStep + 1)
                                withAnimation(.easeInOut(duration: 0.2)) { currentStep += 1 }
                                interactionDone = false
                                simState.reset()
                            }
                        } label: {
                            Label(isLast ? "Finish" : "Next",
                                  systemImage: isLast ? "checkmark" : "chevron.right")
                                .labelStyle(ReversedLabelStyle())
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(.white)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(
                                    (needsInteraction && !interactionDone)
                                        ? DSColor.primary.opacity(0.4)
                                        : DSColor.primary,
                                    in: RoundedRectangle(cornerRadius: 12)
                                )
                        }
                        .disabled(needsInteraction && !interactionDone)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 34)
                .background(.ultraThinMaterial)
            }
        }
        .navigationTitle("Step \(currentStep + 1) of \(guide.steps.count)")
        .navigationBarTitleDisplayMode(.inline)
        .onChange(of: appState.alarmIsActive) { _, active in
            if active { dismiss() }
        }
    }

    @ViewBuilder
    private var lcStepContent: some View {
        switch step.kind {
        case .info(let img):
            LCInfoStepView(imageName: img, icon: guide.id.icon, color: guide.id.color)
        case .iconGrid(let items):
            LCIconGridView(items: items)
        case .slideToConfirm(let label, let icon):
            LCSlideToConfirmView(label: label, iconName: icon) { interactionDone = true }
        case .holdButton(let emergencyType, let color):
            LCHoldButtonView(emergencyType: emergencyType, color: color, simState: simState) {
                simState.isActivated = true
                interactionDone = true
            }
        case .alarmTakeover(let emergencyType):
            LCAlarmTakeoverView(emergencyType: emergencyType, simState: simState)
        case .acknowledgeButton:
            LCAcknowledgeStepView(simState: simState) {
                interactionDone = true
            }
        case .mockNotification(let app, let title, let body):
            LCMockNotificationView(appName: app, title: title, body: body)
        case .visualCopy(let placeholder):
            LCVisualCopyView(placeholder: placeholder)
        }
    }
}

private struct ReversedLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) {
            configuration.title
            configuration.icon
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Step Renderers
// ─────────────────────────────────────────────────────────────────────────────

private struct LCInfoStepView: View {
    let imageName: String?
    let icon: String
    let color: Color

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 20)
                .fill(color.opacity(0.08))
                .overlay(RoundedRectangle(cornerRadius: 20).stroke(color.opacity(0.18), lineWidth: 1))
                .frame(height: 200)
            Image(systemName: icon)
                .font(.system(size: 72, weight: .thin))
                .foregroundStyle(color.opacity(0.6))
        }
    }
}

private struct LCIconGridView: View {
    let items: [(icon: String, label: String, color: Color)]
    private let cols = [GridItem(.adaptive(minimum: 88), spacing: 10)]

    var body: some View {
        LazyVGrid(columns: cols, spacing: 10) {
            ForEach(Array(items.enumerated()), id: \.0) { _, item in
                VStack(spacing: 8) {
                    ZStack {
                        Circle()
                            .fill(item.color.opacity(0.14))
                            .frame(width: 54, height: 54)
                        Image(systemName: item.icon)
                            .font(.system(size: 22, weight: .semibold))
                            .foregroundStyle(item.color)
                    }
                    Text(item.label)
                        .font(.caption.weight(.bold))
                        .foregroundStyle(DSColor.textPrimary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(DSColor.card, in: RoundedRectangle(cornerRadius: 12))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(item.color.opacity(0.2), lineWidth: 1))
            }
        }
    }
}

private struct LCSlideToConfirmView: View {
    let label: String
    let iconName: String
    let onComplete: () -> Void

    @State private var dragOffset: CGFloat = 0
    @State private var completed = false

    private let trackH: CGFloat  = 68
    private let thumbSz: CGFloat = 56

    var body: some View {
        VStack(spacing: 16) {
            HStack(spacing: 6) {
                Image(systemName: "shield.fill")
                Text("SIMULATION — no real alert sent")
                    .font(.caption.weight(.bold))
            }
            .foregroundStyle(DSColor.warning)
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(DSColor.warning.opacity(0.12), in: Capsule())

            GeometryReader { geo in
                let maxDrag = geo.size.width - thumbSz - 8

                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: trackH / 2)
                        .fill(completed ? DSColor.success.opacity(0.15) : DSColor.danger.opacity(0.10))
                        .overlay(
                            RoundedRectangle(cornerRadius: trackH / 2)
                                .stroke(
                                    completed ? DSColor.success.opacity(0.4) : DSColor.danger.opacity(0.28),
                                    lineWidth: 1.5
                                )
                        )

                    RoundedRectangle(cornerRadius: trackH / 2)
                        .fill(completed ? DSColor.success.opacity(0.25) : DSColor.danger.opacity(0.18))
                        .frame(width: max(thumbSz, dragOffset + thumbSz))
                        .animation(.easeOut(duration: 0.12), value: dragOffset)

                    Text(completed ? "Simulated ✓" : label)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(completed ? DSColor.success : DSColor.danger.opacity(0.7))
                        .frame(maxWidth: .infinity, alignment: .center)
                        .offset(x: thumbSz * 0.4)

                    Circle()
                        .fill(completed ? DSColor.success : DSColor.danger)
                        .frame(width: thumbSz, height: thumbSz)
                        .overlay(
                            Image(systemName: completed ? "checkmark" : iconName)
                                .foregroundStyle(.white)
                                .font(.system(size: 22, weight: .bold))
                        )
                        .shadow(color: (completed ? DSColor.success : DSColor.danger).opacity(0.4), radius: 10)
                        .offset(x: 4 + dragOffset)
                        .gesture(
                            DragGesture()
                                .onChanged { v in
                                    guard !completed else { return }
                                    dragOffset = min(max(0, v.translation.width), maxDrag)
                                    if dragOffset >= maxDrag {
                                        withAnimation(.spring(response: 0.3)) {
                                            completed = true
                                            dragOffset = maxDrag
                                        }
                                        onComplete()
                                    }
                                }
                                .onEnded { _ in
                                    if !completed {
                                        withAnimation(.spring(response: 0.4)) { dragOffset = 0 }
                                    }
                                }
                        )
                }
            }
            .frame(height: trackH)
        }
    }
}

private struct LCMockNotificationView: View {
    let appName: String
    let title: String
    let message: String

    init(appName: String, title: String, body: String) {
        self.appName = appName
        self.title = title
        self.message = body
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 10)
                    .fill(DSColor.danger)
                    .frame(width: 44, height: 44)
                Image(systemName: "bell.badge.fill")
                    .foregroundStyle(.white)
                    .font(.system(size: 20, weight: .semibold))
            }

            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(appName)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(DSColor.textSecondary)
                    Spacer()
                    Text("now")
                        .font(.caption2)
                        .foregroundStyle(DSColor.textSecondary)
                }
                Text(title)
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(DSColor.textPrimary)
                Text(message)
                    .font(.caption)
                    .foregroundStyle(DSColor.textSecondary)
                    .lineLimit(3)
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 18)
                .fill(DSColor.card)
                .shadow(color: .black.opacity(0.18), radius: 12, x: 0, y: 4)
        )
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(DSColor.border, lineWidth: 1))
    }
}

private struct LCVisualCopyView: View {
    let placeholder: String

    var body: some View {
        // TODO(LearningCenter): replace with real EmergencyAlarmTakeover(tutorialMode: true)
        // when the component supports tutorialMode to disable all side effects and API calls.
        ZStack {
            RoundedRectangle(cornerRadius: 16)
                .fill(DSColor.danger.opacity(0.07))
                .overlay(RoundedRectangle(cornerRadius: 16).stroke(DSColor.danger.opacity(0.2), lineWidth: 1.5))

            VStack(spacing: 14) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 38))
                    .foregroundStyle(DSColor.danger)

                Text("🔒 LOCKDOWN")
                    .font(.title2.weight(.black))
                    .foregroundStyle(DSColor.danger)

                Text("Lincoln Elementary")
                    .font(.headline)
                    .foregroundStyle(DSColor.textPrimary)

                HStack(spacing: 24) {
                    VStack(spacing: 2) {
                        Text("12 / 28")
                            .font(.title3.weight(.bold))
                            .foregroundStyle(DSColor.textPrimary)
                        Text("Acknowledged")
                            .font(.caption)
                            .foregroundStyle(DSColor.textSecondary)
                    }
                    Divider().frame(height: 36)
                    VStack(spacing: 2) {
                        Text("ACTIVE")
                            .font(.caption.weight(.black))
                            .foregroundStyle(DSColor.danger)
                        Text("Alert Status")
                            .font(.caption)
                            .foregroundStyle(DSColor.textSecondary)
                    }
                }
            }
            .padding(24)
        }
        .frame(height: 220)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - LCHoldButtonView
// TODO(LearningCenter): replace with real SafetyHoldButton(tutorialMode: true)
// ─────────────────────────────────────────────────────────────────────────────

private final class LCHoldController: ObservableObject {
    @Published var holdProgress: Double = 0
    @Published var isHolding = false
    @Published var completed = false

    private var timer: Timer?

    func beginHold(duration: Double, onComplete: @escaping () -> Void) {
        guard !completed else { return }
        isHolding = true
        let step = 0.05 / duration
        timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] t in
            guard let self else { t.invalidate(); return }
            self.holdProgress = min(self.holdProgress + step, 1.0)
            if self.holdProgress >= 1.0 {
                t.invalidate()
                self.completed = true
                self.isHolding = false
                onComplete()
            }
        }
    }

    func cancelHold() {
        timer?.invalidate()
        timer = nil
        isHolding = false
        withAnimation(.spring(response: 0.4)) { holdProgress = 0 }
    }

    func reset() {
        timer?.invalidate()
        timer = nil
        isHolding = false
        completed = false
        holdProgress = 0
    }
}

private struct LCHoldButtonView: View {
    let emergencyType: String
    let color: Color
    let simState: LCSimulationState
    let onComplete: () -> Void

    @StateObject private var controller = LCHoldController()

    private var ringColor: Color {
        controller.holdProgress < 0.55 ? .white
        : controller.holdProgress < 0.80 ? DSColor.warning
        : DSColor.danger
    }

    private var holdScale: CGFloat {
        controller.completed ? 1.12
        : controller.isHolding ? CGFloat(0.97 + controller.holdProgress * 0.11)
        : 1.0
    }

    private var holdText: String {
        controller.completed ? "Activating…"
        : controller.isHolding ? "Keep Holding…"
        : "Hold to Activate"
    }

    var body: some View {
        VStack(spacing: 16) {
            HStack(spacing: 6) {
                Image(systemName: "shield.fill")
                Text("SIMULATION — no real alert sent")
                    .font(.caption.weight(.bold))
            }
            .foregroundStyle(DSColor.warning)
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(DSColor.warning.opacity(0.12), in: Capsule())

            VStack(spacing: 6) {
                ZStack {
                    Circle()
                        .stroke(Color.white.opacity(0.24), lineWidth: 10)
                    Circle()
                        .trim(from: 0, to: controller.holdProgress)
                        .stroke(ringColor, style: StrokeStyle(lineWidth: 10, lineCap: .round))
                        .shadow(color: Color.white.opacity(0.5), radius: 4)
                        .rotationEffect(.degrees(-90))
                        .animation(.linear(duration: 0.05), value: controller.holdProgress)

                    Circle()
                        .fill(color)
                        .overlay {
                            Image(systemName: "lock.fill")
                                .foregroundStyle(.white)
                                .font(.system(size: 30, weight: .bold))
                        }
                        .scaleEffect(holdScale)
                        .shadow(color: color.opacity(0.1 + controller.holdProgress * 0.24), radius: 18)
                        .animation(.easeOut(duration: 0.16), value: holdScale)
                }
                .frame(width: 122, height: 122)
                .contentShape(Circle())
                .onLongPressGesture(
                    minimumDuration: 3.0,
                    maximumDistance: 44,
                    pressing: { pressing in
                        if pressing {
                            controller.beginHold(duration: 3.0, onComplete: onComplete)
                        } else {
                            if !controller.completed { controller.cancelHold() }
                        }
                    },
                    perform: {}
                )

                Text(emergencyType)
                    .font(.headline.weight(.bold))
                    .foregroundStyle(color)
                Text(holdText)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color.white.opacity(0.88))
                Text("~3s")
                    .font(.caption2)
                    .foregroundStyle(Color.white.opacity(0.62))
            }
            .padding()
            .background(DSColor.backgroundDeep, in: RoundedRectangle(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(color.opacity(0.25), lineWidth: 1))
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - LCAlarmTakeoverView
// TODO(LearningCenter): replace with real EmergencyAlarmTakeover(tutorialMode: true)
// ─────────────────────────────────────────────────────────────────────────────

private struct LCAlarmTakeoverView: View {
    let emergencyType: String
    @ObservedObject var simState: LCSimulationState

    private let totalUsers = 14

    private var ackPct: Double {
        guard totalUsers > 0 else { return 0 }
        return Double(simState.ackCount) / Double(totalUsers) * 100
    }

    private var ackColor: Color {
        ackPct < 40 ? DSColor.danger : ackPct < 75 ? DSColor.warning : DSColor.success
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [DSColor.danger, Color(red: 0.04, green: 0.06, blue: 0.10)],
                startPoint: .topLeading, endPoint: .bottom
            )
            .clipShape(RoundedRectangle(cornerRadius: 20))

            VStack(spacing: 18) {
                HStack(spacing: 6) {
                    Image(systemName: "shield.fill")
                    Text("SIMULATION — no real alert sent")
                        .font(.caption.weight(.bold))
                }
                .foregroundStyle(DSColor.warning)
                .padding(.horizontal, 14)
                .padding(.vertical, 7)
                .background(DSColor.warning.opacity(0.15), in: Capsule())

                ZStack {
                    Circle()
                        .stroke(Color.white.opacity(0.22), lineWidth: 9)
                        .frame(width: 100, height: 100)
                    Circle()
                        .fill(Color.white.opacity(0.10))
                        .frame(width: 84, height: 84)
                    Image(systemName: "bell.and.waves.left.and.right.fill")
                        .font(.system(size: 38, weight: .black))
                        .foregroundStyle(.white)
                }

                VStack(spacing: 6) {
                    Text("EMERGENCY ALERT")
                        .font(.system(size: 22, weight: .black, design: .rounded))
                        .foregroundStyle(.white)
                        .tracking(1)
                    Text("🔒 \(emergencyType)")
                        .font(.title3.weight(.bold))
                        .foregroundStyle(.white.opacity(0.92))
                    Text("Lincoln Elementary")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.white.opacity(0.65))
                }

                Text("Follow school emergency procedures immediately.")
                    .font(.subheadline.weight(.semibold))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.white.opacity(0.94))
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .frame(maxWidth: .infinity)
                    .background(Color.white.opacity(0.13))
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

                VStack(spacing: 8) {
                    HStack {
                        Text("\(simState.ackCount) / \(totalUsers) acknowledged")
                            .font(.subheadline.weight(.bold))
                            .foregroundStyle(.white)
                        Spacer()
                        Text("\(Int(ackPct))%")
                            .font(.subheadline.weight(.black))
                            .foregroundStyle(ackColor)
                    }
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule().fill(Color.white.opacity(0.18)).frame(height: 8)
                            Capsule()
                                .fill(ackColor)
                                .frame(width: geo.size.width * CGFloat(ackPct / 100), height: 8)
                                .animation(.spring(response: 0.5, dampingFraction: 0.75), value: ackPct)
                        }
                    }
                    .frame(height: 8)
                }
            }
            .padding(20)
        }
        .onAppear {
            // Simulate two more staff acknowledging after a short delay
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
                withAnimation { simState.ackCount = min(simState.ackCount + 1, totalUsers - 1) }
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.4) {
                withAnimation { simState.ackCount = min(simState.ackCount + 1, totalUsers - 1) }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - LCAcknowledgeStepView
// ─────────────────────────────────────────────────────────────────────────────

private struct LCAcknowledgeStepView: View {
    @ObservedObject var simState: LCSimulationState
    let onComplete: () -> Void

    private let totalUsers = 14

    private var ackPct: Double {
        guard totalUsers > 0 else { return 0 }
        return Double(simState.ackCount) / Double(totalUsers) * 100
    }

    private var ackColor: Color {
        ackPct < 40 ? DSColor.danger : ackPct < 75 ? DSColor.warning : DSColor.success
    }

    var body: some View {
        VStack(spacing: 16) {
            VStack(spacing: 8) {
                HStack {
                    Text("\(simState.ackCount) / \(totalUsers) acknowledged")
                        .font(.subheadline.weight(.bold))
                        .foregroundStyle(DSColor.textPrimary)
                    Spacer()
                    Text("\(Int(ackPct))%")
                        .font(.subheadline.weight(.black))
                        .foregroundStyle(ackColor)
                }
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Capsule().fill(DSColor.border).frame(height: 8)
                        Capsule()
                            .fill(ackColor)
                            .frame(width: geo.size.width * CGFloat(ackPct / 100), height: 8)
                            .animation(.spring(response: 0.5, dampingFraction: 0.75), value: ackPct)
                    }
                }
                .frame(height: 8)
            }
            .padding(16)
            .background(DSColor.card, in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(DSColor.border, lineWidth: 1))

            Button {
                guard !simState.acknowledged else { return }
                withAnimation(.spring(response: 0.3)) {
                    simState.acknowledged = true
                    simState.ackCount = min(simState.ackCount + 1, totalUsers)
                }
                onComplete()
            } label: {
                HStack(spacing: 8) {
                    if simState.acknowledged {
                        Image(systemName: "checkmark.circle.fill")
                    }
                    Text(simState.acknowledged ? "Acknowledged" : "Acknowledge")
                        .font(.system(size: 17, weight: .black))
                }
                .foregroundStyle(simState.acknowledged
                    ? Color.white.opacity(0.70)
                    : Color(red: 0.02, green: 0.30, blue: 0.23))
                .frame(maxWidth: .infinity, minHeight: 58)
                .background(simState.acknowledged
                    ? Color.white.opacity(0.20)
                    : DSColor.success)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
            .disabled(simState.acknowledged)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - Guided Walkthrough Overlay (contextual, first-launch)
// ─────────────────────────────────────────────────────────────────────────────

struct GuidedWalkthroughOverlay: View {
    @Binding var isPresented: Bool
    @EnvironmentObject private var appState: AppState

    var body: some View {
        if isPresented {
            ZStack(alignment: .bottom) {
                Color.black.opacity(0.55)
                    .ignoresSafeArea()
                    .onTapGesture { withAnimation { isPresented = false } }

                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        Label("Quick Tour", systemImage: "sparkles")
                            .font(.headline.weight(.bold))
                            .foregroundStyle(DSColor.primary)
                        Spacer()
                        Button {
                            withAnimation { isPresented = false }
                            UserDefaults.standard.set(true, forKey: "lc_walkthrough_dismissed")
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(DSColor.textSecondary)
                                .font(.title3)
                        }
                    }

                    Text("Welcome to BlueBird Alerts! Tap any button to explore. For a full guided training experience, open **Settings → Learning Center**.")
                        .font(.subheadline)
                        .foregroundStyle(DSColor.textPrimary)

                    Button {
                        withAnimation { isPresented = false }
                        UserDefaults.standard.set(true, forKey: "lc_walkthrough_dismissed")
                        LCAnalytics.track("walkthrough_completed")
                    } label: {
                        Text("Got It")
                            .font(.headline)
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                            .background(DSColor.primary, in: RoundedRectangle(cornerRadius: 12))
                    }
                }
                .padding(24)
                .background(DSColor.card, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                .padding(.horizontal, 16)
                .padding(.bottom, 32)
            }
            .transition(.opacity.combined(with: .move(edge: .bottom)))
            .onChange(of: appState.alarmIsActive) { _, active in
                if active { isPresented = false }
            }
        }
    }
}
