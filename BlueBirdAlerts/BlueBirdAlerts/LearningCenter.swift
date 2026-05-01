import SwiftUI

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
    case mockNotification(appName: String, title: String, body: String)
    case visualCopy(placeholder: String)
}

struct LCStep {
    let title: String
    let description: String
    let kind: LCStepKind
}

struct LCGuide: Identifiable {
    let id: LCGuideID
    let steps: [LCStep]
    var title: String { id.title }
    var introDescription: String { id.introDescription }
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
            description: "Hold the circular button for your school's configured duration (typically 3 seconds). The ring around the button fills as you hold. All staff receive an immediate alert the moment you release.",
            kind: .slideToConfirm(label: "Slide to Simulate", iconName: "exclamationmark.triangle.fill")
        ),
        LCStep(
            title: "Active Alert Screen",
            description: "When an emergency activates, every staff device shows a full-screen takeover. Admins can send broadcast updates, view acknowledgements, and deactivate when the emergency is resolved.",
            // TODO(LearningCenter): replace with real EmergencyAlarmTakeover(tutorialMode: true)
            kind: .visualCopy(placeholder: "emergency_takeover")
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
    static func track(_ event: String, guideID: String? = nil, step: Int? = nil) {
        var info: [String: Any] = [
            "event": event,
            "timestamp": ISO8601DateFormatter().string(from: .now),
        ]
        if let g = guideID { info["guide_id"] = g }
        if let s = step    { info["step"] = s }
        // Events are buffered locally; the app may POST them to /{tenant}/api/training/event
        // when a network session is available.
        print("[LCAnalytics]", info)
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
    let startStep: Int

    @Environment(\.dismiss)       private var dismiss
    @EnvironmentObject             private var appState: AppState
    @StateObject                   private var store = LearningCenterStore.shared
    @State                         private var currentStep: Int
    @State                         private var interactionDone = false

    init(guide: LCGuide, startStep: Int = 0) {
        self.guide = guide
        self.startStep = startStep
        _currentStep = State(initialValue: startStep)
    }

    private var step: LCStep       { guide.steps[currentStep] }
    private var isFirst: Bool      { currentStep == 0 }
    private var isLast: Bool       { currentStep == guide.steps.count - 1 }
    private var needsInteraction: Bool {
        if case .slideToConfirm = step.kind { return true }
        return false
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
                let progress = maxDrag > 0 ? min(dragOffset / maxDrag, 1.0) : 0

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
    let body: String

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
                Text(body)
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
