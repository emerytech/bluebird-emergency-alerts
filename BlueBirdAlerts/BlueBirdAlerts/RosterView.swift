import SwiftUI

private let gradeOptions = ["PreK", "K"] + (1...12).map { "\($0)" } + ["Other"]
private let claimStatusOptions = ["present_with_me", "absent", "missing", "injured", "released", "unknown"]

private func statusLabel(_ s: String) -> String {
    s.split(separator: "_").map { $0.capitalized }.joined(separator: " ")
}

private func statusColor(_ s: String?) -> Color {
    switch s {
    case "present_with_me": return DSColor.success
    case "missing":         return DSColor.danger
    case "injured":         return DSColor.warning
    case "released":        return DSColor.info
    case "absent":          return DSColor.warning
    default:                return DSColor.offline
    }
}

// MARK: - Main View

struct RosterView: View {
    let alertId: Int
    let userID: Int
    let api: APIClient

    @Environment(\.dismiss) private var dismiss
    @State private var roster: IncidentRoster?
    @State private var isLoading = false
    @State private var searchQuery = ""
    @State private var gradeFilter = ""   // "" = all grades
    @State private var showAddSheet = false
    @State private var conflictInfo: ConflictInfo?
    @State private var accountabilityMode = false
    @State private var markedPresent: Set<Int> = []
    @State private var markedMissing: Set<Int> = []
    @State private var isSubmittingAccountability = false

    struct ConflictInfo {
        let message: String
        let row: RosterIncidentRow
        let status: String
    }

    private var accountabilityStudents: [RosterIncidentRow] {
        (roster?.students ?? []).filter { !$0.isAddition }
    }

    private var filteredForAccountability: [RosterIncidentRow] {
        accountabilityStudents.filter {
            let matchesSearch = searchQuery.isEmpty || $0.fullName.localizedCaseInsensitiveContains(searchQuery)
            let matchesGrade = gradeFilter.isEmpty || $0.gradeLevel == gradeFilter
            return matchesSearch && matchesGrade
        }
    }

    var availableGrades: [String] {
        let all = roster?.students.map { $0.gradeLevel } ?? []
        let unique = Array(Set(all))
        return unique.sorted {
            let li = gradeOptions.firstIndex(of: $0) ?? Int.max
            let ri = gradeOptions.firstIndex(of: $1) ?? Int.max
            return li < ri
        }
    }

    var filtered: [RosterIncidentRow] {
        guard let students = roster?.students else { return [] }
        return students.filter {
            let matchesSearch = searchQuery.isEmpty || $0.fullName.localizedCaseInsensitiveContains(searchQuery)
            let matchesGrade = gradeFilter.isEmpty || $0.gradeLevel == gradeFilter
            return matchesSearch && matchesGrade
        }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let summary = roster?.summary {
                    summaryBar(summary)
                }

                VStack(spacing: 8) {
                    HStack(spacing: 10) {
                        HStack {
                            Image(systemName: "magnifyingglass")
                                .foregroundStyle(.secondary)
                            TextField("Search students…", text: $searchQuery)
                                .autocorrectionDisabled()
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)
                        .background(Color(.systemFill))
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

                        Button { showAddSheet = true } label: {
                            Text("+ Add")
                                .font(.subheadline.weight(.semibold))
                                .padding(.horizontal, 14)
                                .padding(.vertical, 9)
                                .background(Color.accentColor)
                                .foregroundStyle(.white)
                                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        }
                    }

                    if !availableGrades.isEmpty {
                        Picker("Grade", selection: $gradeFilter) {
                            Text("All Grades").tag("")
                            ForEach(availableGrades, id: \.self) { g in
                                Text("Grade \(g)").tag(g)
                            }
                        }
                        .pickerStyle(.segmented)
                        .frame(maxWidth: .infinity)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)

                if isLoading && roster == nil {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else if accountabilityMode {
                    List(filteredForAccountability) { row in
                        if let sid = row.studentId {
                            AccountabilityRowCard(
                                row: row,
                                isPresent: markedPresent.contains(sid),
                                isMissing: markedMissing.contains(sid),
                                onMarkPresent: {
                                    markedPresent.insert(sid)
                                    markedMissing.remove(sid)
                                },
                                onMarkMissing: {
                                    markedMissing.insert(sid)
                                    markedPresent.remove(sid)
                                },
                                onClear: {
                                    markedPresent.remove(sid)
                                    markedMissing.remove(sid)
                                }
                            )
                            .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 6, trailing: 16))
                            .listRowSeparator(.hidden)
                            .listRowBackground(Color.clear)
                        }
                    }
                    .listStyle(.plain)
                } else if filtered.isEmpty {
                    Spacer()
                    Text({
                        if !searchQuery.isEmpty && !gradeFilter.isEmpty { return "No results for \"\(searchQuery)\" in Grade \(gradeFilter)." }
                        if !searchQuery.isEmpty { return "No results for \"\(searchQuery)\"." }
                        if !gradeFilter.isEmpty { return "No students in Grade \(gradeFilter)." }
                        return "No students in roster."
                    }())
                        .foregroundStyle(.secondary)
                        .padding()
                    Spacer()
                } else {
                    List(filtered) { row in
                        RosterRowCard(row: row) { status in
                            Task { await handleClaim(row: row, status: status) }
                        } onRelease: { claimId in
                            Task { await handleRelease(claimId: claimId) }
                        }
                        .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 6, trailing: 16))
                        .listRowSeparator(.hidden)
                        .listRowBackground(Color.clear)
                    }
                    .listStyle(.plain)
                }
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Student Roster")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
                ToolbarItem(placement: .primaryAction) {
                    if isLoading {
                        ProgressView().scaleEffect(0.8)
                    } else {
                        Button(accountabilityMode ? "Exit Roll Call" : "Roll Call") {
                            accountabilityMode.toggle()
                            if !accountabilityMode {
                                markedPresent = []
                                markedMissing = []
                            }
                        }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(accountabilityMode ? DSColor.danger : DSColor.primary)
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                if accountabilityMode {
                    accountabilityBottomBar
                }
            }
        }
        .task { await loadRoster() }
        .sheet(isPresented: $showAddSheet) {
            AddIncidentStudentSheet { firstName, lastName, gradeLevel, note in
                Task { await handleAddStudent(firstName: firstName, lastName: lastName, gradeLevel: gradeLevel, note: note) }
            }
        }
        .alert("Claim Conflict", isPresented: Binding(
            get: { conflictInfo != nil },
            set: { if !$0 { conflictInfo = nil } }
        )) {
            if let info = conflictInfo {
                Button("Confirm Takeover", role: .destructive) {
                    Task { await claimStudent(row: info.row, status: info.status, takeover: true) }
                    conflictInfo = nil
                }
                Button("Cancel", role: .cancel) { conflictInfo = nil }
            }
        } message: {
            if let info = conflictInfo { Text(info.message) }
        }
    }

    @ViewBuilder
    private func summaryBar(_ s: IncidentRosterSummary) -> some View {
        HStack(spacing: 24) {
            SummaryChip(label: "Total",    count: s.total,         color: DSColor.textSecondary)
            SummaryChip(label: "With Me",  count: s.presentWithMe, color: statusColor("present_with_me"))
            SummaryChip(label: "Missing",  count: s.missing,       color: statusColor("missing"))
            SummaryChip(label: "Unclaimed",count: s.unclaimed,     color: DSColor.offline)
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(DSColor.backgroundDeep)
    }

    // MARK: - Accountability bottom bar

    @ViewBuilder
    private var accountabilityBottomBar: some View {
        let presentCount = markedPresent.count
        let missingCount = markedMissing.count
        let unmarkedCount = accountabilityStudents.count - presentCount - missingCount
        VStack(spacing: 0) {
            Divider()
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(presentCount) present · \(missingCount) missing · \(unmarkedCount) unmarked")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.primary)
                    Text("Tap Submit to record batch accountability")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if isSubmittingAccountability {
                    ProgressView().scaleEffect(0.8).frame(width: 80, height: 36)
                } else {
                    Button {
                        Task { await submitAccountability() }
                    } label: {
                        Text("Submit")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.white)
                            .padding(.horizontal, 20).padding(.vertical, 8)
                            .background(DSColor.primary)
                            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                    .disabled(markedPresent.isEmpty && markedMissing.isEmpty)
                }
            }
            .padding(.horizontal, 16).padding(.vertical, 10)
            .background(.ultraThinMaterial)
        }
    }

    // MARK: - Actions

    private func loadRoster() async {
        isLoading = true
        defer { isLoading = false }
        do { roster = try await api.fetchIncidentRoster(alertId: alertId, userID: userID) }
        catch {
            #if DEBUG
            print("[RosterView] loadRoster failed: \(error)")
            #endif
        }
    }

    private func handleClaim(row: RosterIncidentRow, status: String) async {
        await claimStudent(row: row, status: status, takeover: false)
    }

    private func claimStudent(row: RosterIncidentRow, status: String, takeover: Bool) async {
        do {
            let result: RosterClaimResult
            if let sid = row.studentId {
                result = try await api.claimStudent(alertId: alertId, studentId: sid, userID: userID, status: status, takeoverConfirmed: takeover)
            } else if let aid = row.additionId {
                result = try await api.claimAddition(alertId: alertId, additionId: aid, userID: userID, status: status, takeoverConfirmed: takeover)
            } else { return }

            if result.conflict {
                let label = result.conflictClaimedByLabel ?? "another teacher"
                let secs = result.conflictClaimedSecondsAgo.map { Int($0) } ?? 0
                conflictInfo = ConflictInfo(
                    message: "\(label) claimed this student \(secs)s ago. Take over?",
                    row: row, status: status
                )
            } else {
                await loadRoster()
            }
        } catch {
            #if DEBUG
            print("[RosterView] claimStudent failed: \(error)")
            #endif
        }
    }

    private func handleRelease(claimId: Int) async {
        do {
            try await api.releaseRosterClaim(alertId: alertId, claimId: claimId, userID: userID)
            await loadRoster()
        } catch {
            #if DEBUG
            print("[RosterView] handleRelease failed: \(error)")
            #endif
        }
    }

    private func handleAddStudent(firstName: String, lastName: String, gradeLevel: String, note: String?) async {
        do {
            _ = try await api.addIncidentStudent(alertId: alertId, userID: userID, firstName: firstName, lastName: lastName, gradeLevel: gradeLevel, note: note)
            await loadRoster()
        } catch {
            #if DEBUG
            print("[RosterView] handleAddStudent failed: \(error)")
            #endif
        }
    }

    private func submitAccountability() async {
        isSubmittingAccountability = true
        defer { isSubmittingAccountability = false }
        do {
            _ = try await api.submitAccountability(
                alertId: alertId,
                userID: userID,
                studentsPresent: Array(markedPresent),
                studentsMissing: Array(markedMissing)
            )
            accountabilityMode = false
            markedPresent = []
            markedMissing = []
            await loadRoster()
        } catch {
            #if DEBUG
            print("[RosterView] submitAccountability failed: \(error)")
            #endif
        }
    }
}

// MARK: - Summary Chip

private struct SummaryChip: View {
    let label: String
    let count: Int
    let color: Color

    var body: some View {
        VStack(spacing: 2) {
            Text("\(count)")
                .font(.title3.weight(.bold))
                .foregroundStyle(color)
            Text(label)
                .font(.caption2)
                .foregroundStyle(DSColor.offline)
        }
    }
}

// MARK: - Roster Row Card

private struct RosterRowCard: View {
    let row: RosterIncidentRow
    let onClaim: (String) -> Void
    let onRelease: (Int) -> Void

    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button { withAnimation(.easeInOut(duration: 0.2)) { expanded.toggle() } } label: {
                HStack {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Text(row.fullName)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(.primary)
                            if row.isAddition {
                                Text("added")
                                    .font(.caption2.weight(.medium))
                                    .foregroundStyle(DSColor.warning)
                                    .padding(.horizontal, 5).padding(.vertical, 2)
                                    .background(Color(red: 0.57, green: 0.25, blue: 0.06))
                                    .clipShape(RoundedRectangle(cornerRadius: 4, style: .continuous))
                            }
                        }
                        Text("Grade \(row.gradeLevel)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if let claim = row.claim {
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(statusLabel(claim.status))
                                .font(.caption.weight(.medium))
                                .foregroundStyle(statusColor(claim.status))
                            Text(claim.claimedByLabel)
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                    } else {
                        Text("Unclaimed")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                    Image(systemName: expanded ? "chevron.up" : "chevron.down")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .padding(.leading, 6)
                }
                .padding(12)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if expanded {
                Divider().padding(.horizontal, 12)
                VStack(alignment: .leading, spacing: 10) {
                    Text("Set status:")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    FlowLayout(spacing: 6) {
                        ForEach(claimStatusOptions, id: \.self) { status in
                            let isActive = row.claim?.status == status
                            Button {
                                if !isActive { onClaim(status) }
                            } label: {
                                Text(statusLabel(status))
                                    .font(.caption.weight(.medium))
                                    .padding(.horizontal, 10).padding(.vertical, 5)
                                    .foregroundStyle(isActive ? statusColor(status) : Color.secondary)
                                    .background(isActive ? statusColor(status).opacity(0.18) : Color(.systemFill))
                                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                                            .stroke(isActive ? statusColor(status) : Color.clear, lineWidth: 1)
                                    )
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    if let claim = row.claim {
                        Button {
                            onRelease(claim.id)
                        } label: {
                            Text("Release claim")
                                .font(.caption.weight(.medium))
                                .foregroundStyle(DSColor.danger)
                        }
                        .buttonStyle(.plain)
                    }
                    if let note = row.note {
                        Text("Note: \(note)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.bottom, 12)
                .padding(.top, 8)
            }
        }
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

// MARK: - Accountability Row Card

private struct AccountabilityRowCard: View {
    let row: RosterIncidentRow
    let isPresent: Bool
    let isMissing: Bool
    let onMarkPresent: () -> Void
    let onMarkMissing: () -> Void
    let onClear: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(row.fullName)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                Text("Grade \(row.gradeLevel)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            HStack(spacing: 6) {
                accountabilityButton(
                    label: "Present",
                    systemImage: "checkmark.circle.fill",
                    isActive: isPresent,
                    activeColor: DSColor.success
                ) {
                    if isPresent { onClear() } else { onMarkPresent() }
                }
                accountabilityButton(
                    label: "Missing",
                    systemImage: "xmark.circle.fill",
                    isActive: isMissing,
                    activeColor: DSColor.danger
                ) {
                    if isMissing { onClear() } else { onMarkMissing() }
                }
            }
        }
        .padding(12)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    @ViewBuilder
    private func accountabilityButton(label: String, systemImage: String, isActive: Bool, activeColor: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 3) {
                Image(systemName: systemImage)
                    .font(.system(size: 22))
                    .foregroundStyle(isActive ? activeColor : Color(.tertiaryLabel))
                Text(label)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(isActive ? activeColor : Color(.tertiaryLabel))
            }
            .frame(width: 58, height: 44)
            .background(isActive ? activeColor.opacity(0.12) : Color(.tertiarySystemFill))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Flow Layout

private struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 0
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowH: CGFloat = 0
        for sv in subviews {
            let size = sv.sizeThatFits(.unspecified)
            if x + size.width > width && x > 0 {
                y += rowH + spacing
                x = 0
                rowH = 0
            }
            rowH = max(rowH, size.height)
            x += size.width + spacing
        }
        y += rowH
        return CGSize(width: width, height: y)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var rowH: CGFloat = 0
        for sv in subviews {
            let size = sv.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX && x > bounds.minX {
                y += rowH + spacing
                x = bounds.minX
                rowH = 0
            }
            sv.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            rowH = max(rowH, size.height)
            x += size.width + spacing
        }
    }
}

// MARK: - Add Student Sheet

private struct AddIncidentStudentSheet: View {
    let onAdd: (String, String, String, String?) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var firstName = ""
    @State private var lastName = ""
    @State private var gradeLevel = "K"
    @State private var note = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Student Info") {
                    TextField("First name", text: $firstName)
                        .textInputAutocapitalization(.words)
                    TextField("Last name", text: $lastName)
                        .textInputAutocapitalization(.words)
                    Picker("Grade", selection: $gradeLevel) {
                        ForEach(gradeOptions, id: \.self) { Text($0) }
                    }
                }
                Section("Note (optional)") {
                    TextField("Note", text: $note, axis: .vertical)
                        .lineLimit(2...4)
                }
            }
            .navigationTitle("Add Student")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") {
                        onAdd(firstName.trimmingCharacters(in: .whitespaces),
                              lastName.trimmingCharacters(in: .whitespaces),
                              gradeLevel,
                              note.trimmingCharacters(in: .whitespaces).isEmpty ? nil : note.trimmingCharacters(in: .whitespaces))
                        dismiss()
                    }
                    .disabled(firstName.trimmingCharacters(in: .whitespaces).isEmpty ||
                              lastName.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }
}
