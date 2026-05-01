import SwiftUI

private let gradeOptions = ["PreK", "K"] + (1...12).map { "\($0)" } + ["Other"]
private let claimStatusOptions = ["present_with_me", "absent", "missing", "injured", "released", "unknown"]

private func statusLabel(_ s: String) -> String {
    s.split(separator: "_").map { $0.capitalized }.joined(separator: " ")
}

private func statusColor(_ s: String?) -> Color {
    switch s {
    case "present_with_me": return Color(red: 0.29, green: 0.86, blue: 0.50)
    case "missing":         return Color(red: 0.94, green: 0.27, blue: 0.27)
    case "injured":         return Color(red: 0.98, green: 0.60, blue: 0.09)
    case "released":        return Color(red: 0.38, green: 0.65, blue: 0.98)
    case "absent":          return Color(red: 0.98, green: 0.75, blue: 0.14)
    default:                return Color(red: 0.58, green: 0.64, blue: 0.72)
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
    @State private var showAddSheet = false
    @State private var conflictInfo: ConflictInfo?

    struct ConflictInfo {
        let message: String
        let row: RosterIncidentRow
        let status: String
    }

    var filtered: [RosterIncidentRow] {
        guard let students = roster?.students else { return [] }
        guard !searchQuery.isEmpty else { return students }
        return students.filter {
            $0.fullName.localizedCaseInsensitiveContains(searchQuery) ||
            $0.gradeLevel.localizedCaseInsensitiveContains(searchQuery)
        }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let summary = roster?.summary {
                    summaryBar(summary)
                }

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
                .padding(.horizontal, 16)
                .padding(.vertical, 10)

                if isLoading && roster == nil {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else if filtered.isEmpty {
                    Spacer()
                    Text(searchQuery.isEmpty ? "No students in roster." : "No results for \"\(searchQuery)\".")
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
                    }
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
            SummaryChip(label: "Total",    count: s.total,         color: Color(red: 0.80, green: 0.84, blue: 0.89))
            SummaryChip(label: "With Me",  count: s.presentWithMe, color: statusColor("present_with_me"))
            SummaryChip(label: "Missing",  count: s.missing,       color: statusColor("missing"))
            SummaryChip(label: "Unclaimed",count: s.unclaimed,     color: Color(red: 0.58, green: 0.64, blue: 0.72))
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(Color(red: 0.12, green: 0.16, blue: 0.23))
    }

    // MARK: - Actions

    private func loadRoster() async {
        isLoading = true
        defer { isLoading = false }
        do { roster = try await api.fetchIncidentRoster(alertId: alertId, userID: userID) }
        catch { }
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
        } catch { }
    }

    private func handleRelease(claimId: Int) async {
        do {
            try await api.releaseRosterClaim(alertId: alertId, claimId: claimId, userID: userID)
            await loadRoster()
        } catch { }
    }

    private func handleAddStudent(firstName: String, lastName: String, gradeLevel: String, note: String?) async {
        do {
            _ = try await api.addIncidentStudent(alertId: alertId, userID: userID, firstName: firstName, lastName: lastName, gradeLevel: gradeLevel, note: note)
            await loadRoster()
        } catch { }
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
                .foregroundStyle(Color(red: 0.58, green: 0.64, blue: 0.72))
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
                                    .foregroundStyle(Color(red: 0.98, green: 0.75, blue: 0.14))
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
                                .foregroundStyle(Color(red: 0.94, green: 0.27, blue: 0.27))
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
