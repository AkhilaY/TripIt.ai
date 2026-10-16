import SwiftData
import SwiftUI

struct ImportsView: View {
    @Environment(\.modelContext) private var context
    @Environment(ImportCoordinator.self) private var importer
    @Query(sort: \ReelSource.importedAt, order: .reverse) private var sources: [ReelSource]
    @State private var showingAddLink = false

    var body: some View {
        NavigationStack {
            List {
                if !importer.pending.isEmpty {
                    Section("In progress") {
                        ForEach(importer.pending) { item in
                            PendingRow(item: item, status: importer.statusByID[item.id])
                                .swipeActions {
                                    Button("Remove", role: .destructive) { importer.remove(item) }
                                    if item.state == .failed {
                                        Button("Retry") { importer.retry(item) }.tint(.blue)
                                    }
                                }
                        }
                    }
                }

                Section("Saved reels") {
                    ForEach(sources) { source in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(source.title).font(.headline)
                            Text("\(source.platformName) · \((source.places ?? []).count) places · \(source.importedAt.formatted(date: .abbreviated, time: .omitted))")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            if !source.summary.isEmpty {
                                Text(source.summary).font(.subheadline).lineLimit(2)
                            }
                            if let url = URL(string: source.url) {
                                Link("Open original", destination: url).font(.caption)
                            }
                        }
                    }
                    .onDelete { offsets in
                        // Deleting a reel keeps its places; they just lose the link back to it.
                        offsets.map { sources[$0] }.forEach(context.delete)
                    }
                }
            }
            .overlay {
                if sources.isEmpty && importer.pending.isEmpty {
                    ContentUnavailableView("Nothing imported yet", systemImage: "square.and.arrow.down",
                                           description: Text("Share a reel to TripIt from TikTok or Instagram."))
                }
            }
            .refreshable { importer.start() }
            .navigationTitle("Imports")
            .toolbar {
                Button { showingAddLink = true } label: { Image(systemName: "plus") }
            }
            .sheet(isPresented: $showingAddLink) { AddLinkSheet() }
        }
    }
}

private struct PendingRow: View {
    let item: PendingImport
    let status: String?

    var body: some View {
        HStack(spacing: 12) {
            if item.state == .failed {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            } else {
                ProgressView()
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(item.state == .failed ? (item.message ?? "Failed") : (status ?? "Waiting to process…"))
                    .font(.subheadline)
                Text(item.url).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                if item.state != .failed, let message = item.message {
                    Text(message).font(.caption2).foregroundStyle(.orange)
                }
            }
        }
    }
}
