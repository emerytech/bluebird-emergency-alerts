import SwiftUI

// MARK: - Local persistence

enum MasterRosterStore {
    private static let fileName = "master_roster.json"
    private static let syncDateKey = "master_roster_sync_date"
    private static let versionKey = "master_roster_version"
    private static let encoder = JSONEncoder()
    private static let decoder = JSONDecoder()

    private static var fileURL: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(fileName)
    }

    static func save(_ students: [MasterStudent], version: String? = nil) {
        guard let data = try? encoder.encode(students) else { return }
        try? data.write(to: fileURL, options: .atomic)
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: syncDateKey)
        if let v = version, !v.isEmpty {
            UserDefaults.standard.set(v, forKey: versionKey)
        }
    }

    static func load() -> [MasterStudent] {
        guard let data = try? Data(contentsOf: fileURL),
              let students = try? decoder.decode([MasterStudent].self, from: data)
        else { return [] }
        return students
    }

    static var lastSyncDate: Date? {
        let ts = UserDefaults.standard.double(forKey: syncDateKey)
        return ts > 0 ? Date(timeIntervalSince1970: ts) : nil
    }

    static var lastKnownVersion: String? {
        UserDefaults.standard.string(forKey: versionKey)
    }
}

// MARK: - View

private let gradeOrder = ["PreK", "K"] + (1...12).map { "\($0)" } + ["Other"]

struct MasterRosterView: View {
    let api: APIClient
    let userID: Int

    @Environment(\.dismiss) private var dismiss
    @State private var students: [MasterStudent] = []
    @State private var searchQuery = ""
    @State private var gradeFilter = ""
    @State private var isDownloading = false
    @State private var downloadError: String?
    @State private var lastSync: Date? = MasterRosterStore.lastSyncDate

    private var availableGrades: [String] {
        let raw = Set(students.map { $0.gradeLevel })
        return gradeOrder.filter { raw.contains($0) }
    }

    private var filtered: [MasterStudent] {
        students.filter {
            let matchSearch = searchQuery.isEmpty || $0.fullName.localizedCaseInsensitiveContains(searchQuery)
            let matchGrade = gradeFilter.isEmpty || $0.gradeLevel == gradeFilter
            return matchSearch && matchGrade
        }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Search + grade filter
                VStack(spacing: 8) {
                    HStack {
                        Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                        TextField("Search students…", text: $searchQuery)
                            .autocorrectionDisabled()
                    }
                    .padding(.horizontal, 10).padding(.vertical, 8)
                    .background(Color(.systemFill))
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

                    if !availableGrades.isEmpty {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 6) {
                                gradeChip("All", tag: "")
                                ForEach(availableGrades, id: \.self) { g in
                                    gradeChip("Gr \(g)", tag: g)
                                }
                            }
                            .padding(.horizontal, 2)
                        }
                    }
                }
                .padding(.horizontal, 16).padding(.vertical, 10)

                if students.isEmpty && !isDownloading {
                    emptyState
                } else if isDownloading && students.isEmpty {
                    Spacer()
                    ProgressView("Downloading…")
                    Spacer()
                } else {
                    List(filtered) { student in
                        MasterStudentRow(student: student)
                            .listRowInsets(EdgeInsets(top: 5, leading: 16, bottom: 5, trailing: 16))
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
                    Button {
                        Task { await downloadRoster() }
                    } label: {
                        if isDownloading {
                            ProgressView().scaleEffect(0.8)
                        } else {
                            Image(systemName: "arrow.clockwise")
                        }
                    }
                    .disabled(isDownloading)
                }
            }
            .safeAreaInset(edge: .bottom) {
                if let sync = lastSync {
                    Text("Synced \(sync.formatted(.relative(presentation: .named)))")
                        .font(.caption2)
                        .foregroundStyle(DSColor.textSecondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                        .background(.ultraThinMaterial)
                }
            }
            .alert("Download Failed", isPresented: Binding(
                get: { downloadError != nil },
                set: { if !$0 { downloadError = nil } }
            )) {
                Button("OK", role: .cancel) { downloadError = nil }
            } message: {
                if let err = downloadError { Text(err) }
            }
        }
        .onAppear {
            students = MasterRosterStore.load()
            lastSync = MasterRosterStore.lastSyncDate
            Task { await autoSyncIfStale() }
        }
    }

    // MARK: - Sub-views

    @ViewBuilder
    private func gradeChip(_ label: String, tag: String) -> some View {
        let selected = gradeFilter == tag
        Button { gradeFilter = tag } label: {
            Text(label)
                .font(.caption.weight(.semibold))
                .padding(.horizontal, 10).padding(.vertical, 5)
                .foregroundStyle(selected ? DSColor.primary : DSColor.textSecondary)
                .background(selected ? DSColor.primary.opacity(0.12) : Color(.systemFill))
                .clipShape(Capsule())
                .overlay(Capsule().stroke(selected ? DSColor.primary : Color.clear, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var emptyState: some View {
        Spacer()
        VStack(spacing: 14) {
            Image(systemName: "person.3.fill")
                .font(.system(size: 48))
                .foregroundStyle(DSColor.textSecondary.opacity(0.4))
            Text("No roster downloaded")
                .font(.headline)
                .foregroundStyle(DSColor.textPrimary)
            Text("Tap the sync button to download the student roster from your school's server.")
                .font(.subheadline)
                .foregroundStyle(DSColor.textSecondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
            Button {
                Task { await downloadRoster() }
            } label: {
                Label("Download Roster", systemImage: "arrow.clockwise")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 24).padding(.vertical, 12)
                    .background(DSColor.primary, in: RoundedRectangle(cornerRadius: 12))
            }
            .disabled(isDownloading)
        }
        Spacer()
    }

    // MARK: - Actions

    private func autoSyncIfStale() async {
        guard !students.isEmpty, !isDownloading else { return }
        guard let remoteVersion = try? await api.fetchRosterVersion(userID: userID) else { return }
        guard remoteVersion != MasterRosterStore.lastKnownVersion else { return }
        await downloadRoster()
    }

    private func downloadRoster() async {
        isDownloading = true
        defer { isDownloading = false }
        do {
            async let fetchedStudents = api.fetchMasterRoster(userID: userID)
            async let fetchedVersion = api.fetchRosterVersion(userID: userID)
            let (students, version) = try await (fetchedStudents, fetchedVersion)
            MasterRosterStore.save(students, version: version)
            self.students = students
            lastSync = MasterRosterStore.lastSyncDate
        } catch {
            downloadError = error.localizedDescription
            #if DEBUG
            print("[MasterRosterView] download failed: \(error)")
            #endif
        }
    }
}

// MARK: - Row

private struct MasterStudentRow: View {
    let student: MasterStudent

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(student.fullName)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                HStack(spacing: 6) {
                    Text("Grade \(student.gradeLevel)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if let ref = student.studentRef, !ref.isEmpty {
                        Text("· \(ref)")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
            Spacer()
        }
        .padding(12)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
