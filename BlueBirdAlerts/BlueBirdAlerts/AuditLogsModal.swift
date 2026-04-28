import SwiftUI

struct AuditLogsModal: View {
    let api: APIClient
    let userID: Int

    @Environment(\.dismiss) private var dismiss
    @State private var entries: [AuditLogEntry] = []
    @State private var isLoading = false
    @State private var loadError: String? = nil
    @State private var searchText = ""
    @State private var selectedEventType: String? = nil
    @State private var availableEventTypes: [String] = []
    @State private var offset = 0
    @State private var hasMore = true
    @State private var expandedEntryID: Int? = nil
    @State private var debounceTask: Task<Void, Never>? = nil

    private let pageSize = 25

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                searchBar
                filterChips
                Divider()
                    .padding(.top, 4)
                contentBody
            }
            .navigationTitle("Audit Logs")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .fontWeight(.semibold)
                }
            }
        }
        .task { await initialLoad() }
    }

    // MARK: – Search bar

    private var searchBar: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(.secondary)
            TextField("Search by action or user…", text: $searchText)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .onChange(of: searchText) { _ in scheduleSearch() }
            if !searchText.isEmpty {
                Button { searchText = ""; scheduleSearch() } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
        .padding(.horizontal, 16)
        .padding(.top, 12)
        .padding(.bottom, 8)
    }

    // MARK: – Filter chips

    private var filterChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                chip(label: "All", isSelected: selectedEventType == nil) {
                    selectedEventType = nil
                    reload()
                }
                ForEach(availableEventTypes, id: \.self) { type in
                    chip(label: type.replacingOccurrences(of: "_", with: " ").capitalized,
                         isSelected: selectedEventType == type) {
                        selectedEventType = (selectedEventType == type) ? nil : type
                        reload()
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 8)
        }
    }

    @ViewBuilder
    private func chip(label: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.caption.weight(.semibold))
                .foregroundStyle(isSelected ? .white : .primary)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(isSelected ? Color.accentColor : Color(.systemFill), in: Capsule())
        }
    }

    // MARK: – Content

    @ViewBuilder
    private var contentBody: some View {
        if isLoading && entries.isEmpty {
            Spacer()
            ProgressView("Loading…")
                .frame(maxWidth: .infinity)
            Spacer()
        } else if let error = loadError, entries.isEmpty {
            Spacer()
            VStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.largeTitle)
                    .foregroundStyle(.orange)
                Text(error)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                Button("Retry") { reload() }
                    .buttonStyle(.bordered)
            }
            .padding()
            Spacer()
        } else if entries.isEmpty {
            Spacer()
            VStack(spacing: 8) {
                Image(systemName: "doc.text.magnifyingglass")
                    .font(.largeTitle)
                    .foregroundStyle(.secondary)
                Text("No audit logs found")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        } else {
            List {
                ForEach(entries) { entry in
                    entryRow(entry)
                        .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 6, trailing: 16))
                        .listRowSeparator(.hidden)
                        .listRowBackground(Color.clear)
                }
                if hasMore {
                    HStack {
                        Spacer()
                        if isLoading {
                            ProgressView()
                        } else {
                            Button("Load More") { Task { await loadMore() } }
                                .buttonStyle(.bordered)
                        }
                        Spacer()
                    }
                    .listRowInsets(EdgeInsets(top: 8, leading: 0, bottom: 16, trailing: 0))
                    .listRowSeparator(.hidden)
                    .listRowBackground(Color.clear)
                }
            }
            .listStyle(.plain)
        }
    }

    // MARK: – Log row

    @ViewBuilder
    private func entryRow(_ entry: AuditLogEntry) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) {
                    expandedEntryID = (expandedEntryID == entry.id) ? nil : entry.id
                }
            } label: {
                HStack(alignment: .top, spacing: 12) {
                    Circle()
                        .fill(eventTypeColor(entry.eventType))
                        .frame(width: 8, height: 8)
                        .padding(.top, 5)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(entry.eventType.replacingOccurrences(of: "_", with: " ").capitalized)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.primary)
                        HStack(spacing: 6) {
                            if let label = entry.actorLabel {
                                Text(label)
                                    .foregroundStyle(.primary)
                                Text("•")
                                    .foregroundStyle(.secondary)
                            }
                            Text(formatTimestamp(entry.timestamp))
                                .foregroundStyle(.secondary)
                        }
                        .font(.caption)
                    }
                    Spacer()
                    Image(systemName: expandedEntryID == entry.id ? "chevron.up" : "chevron.down")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(.vertical, 10)
            .padding(.horizontal, 12)

            if expandedEntryID == entry.id {
                expandedDetail(entry)
                    .padding(.horizontal, 12)
                    .padding(.bottom, 10)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.06), radius: 4, x: 0, y: 2)
    }

    @ViewBuilder
    private func expandedDetail(_ entry: AuditLogEntry) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Divider()
            detailRow(label: "Event ID", value: String(entry.id))
            detailRow(label: "Timestamp", value: entry.timestamp)
            if let targetType = entry.targetType {
                detailRow(label: "Target", value: targetType)
            }
            if let targetId = entry.targetId {
                detailRow(label: "Target ID", value: targetId)
            }
        }
    }

    private func detailRow(label: String, value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label + ":")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 80, alignment: .leading)
            Text(value)
                .font(.caption)
                .foregroundStyle(.primary)
            Spacer()
        }
    }

    // MARK: – Helpers

    private func eventTypeColor(_ type: String) -> Color {
        switch type {
        case let t where t.contains("alarm") || t.contains("alert"): return .red
        case let t where t.contains("login"): return .blue
        case let t where t.contains("user"): return .purple
        case let t where t.contains("quiet"): return .teal
        default: return .gray
        }
    }

    private func formatTimestamp(_ raw: String) -> String {
        let prefix = String(raw.prefix(16))
        return prefix.replacingOccurrences(of: "T", with: " ")
    }

    // MARK: – Data loading

    private func scheduleSearch() {
        debounceTask?.cancel()
        debounceTask = Task {
            try? await Task.sleep(nanoseconds: 350_000_000)
            if !Task.isCancelled { reload() }
        }
    }

    private func reload() {
        offset = 0
        hasMore = true
        entries = []
        Task { await initialLoad() }
    }

    private func initialLoad() async {
        guard !isLoading else { return }
        isLoading = true
        loadError = nil
        defer { isLoading = false }
        do {
            let response = try await api.auditLog(
                userID: userID,
                limit: pageSize,
                offset: 0,
                search: searchText.isEmpty ? nil : searchText,
                eventType: selectedEventType
            )
            entries = response.events
            hasMore = response.events.count == pageSize
            offset = response.events.count
            if availableEventTypes.isEmpty {
                let types = Set(response.events.map { $0.eventType }).sorted()
                if !types.isEmpty { availableEventTypes = types }
            }
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func loadMore() async {
        guard !isLoading, hasMore else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await api.auditLog(
                userID: userID,
                limit: pageSize,
                offset: offset,
                search: searchText.isEmpty ? nil : searchText,
                eventType: selectedEventType
            )
            entries.append(contentsOf: response.events)
            hasMore = response.events.count == pageSize
            offset += response.events.count
        } catch {
            // Silently fail on load-more; user can retry
        }
    }
}
