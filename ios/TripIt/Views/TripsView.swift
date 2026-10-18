import SwiftData
import SwiftUI

struct TripsView: View {
    @Environment(\.modelContext) private var context
    @Environment(ImportCoordinator.self) private var importer
    @Query(sort: \Trip.createdAt, order: .reverse) private var trips: [Trip]
    @State private var showingAddLink = false
    @State private var path: [Trip] = []

    var body: some View {
        NavigationStack(path: $path) {
            List {
                let inFlight = importer.pending.filter { $0.state != .failed }
                if !inFlight.isEmpty {
                    Section {
                        ForEach(inFlight) { item in
                            HStack(spacing: 12) {
                                ProgressView()
                                VStack(alignment: .leading) {
                                    Text(importer.statusByID[item.id] ?? "Waiting to process…").font(.subheadline)
                                    Text(item.url).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                }
                            }
                        }
                    }
                }

                ForEach(trips) { trip in
                    NavigationLink(value: trip) { TripRow(trip: trip) }
                }
                .onDelete { offsets in
                    offsets.map { trips[$0] }.forEach(context.delete)
                }
            }
            .overlay {
                if trips.isEmpty && importer.pending.isEmpty {
                    ContentUnavailableView {
                        Label("No trips yet", systemImage: "airplane.departure")
                    } description: {
                        Text("In TikTok or Instagram, tap Share on a travel reel and choose TripIt. The places land here and on your map.")
                    } actions: {
                        Button("Paste a link") { showingAddLink = true }.buttonStyle(.borderedProminent)
                    }
                }
            }
            .navigationTitle("Trips")
            .navigationDestination(for: Trip.self) { TripDetailView(trip: $0) }
            .toolbar {
                Button { showingAddLink = true } label: { Image(systemName: "plus") }
            }
            .sheet(isPresented: $showingAddLink) { AddLinkSheet() }
            .onChange(of: importer.lastImportedTrip) { _, trip in
                if let trip, path.isEmpty { path = [trip] }
            }
        }
    }
}

private struct TripRow: View {
    let trip: Trip

    var body: some View {
        let places = trip.allPlaces
        VStack(alignment: .leading, spacing: 4) {
            Text(trip.name).font(.headline)
            HStack(spacing: 8) {
                Text("\(places.count) place\(places.count == 1 ? "" : "s")")
                if trip.hasItinerary { Text("· \(trip.dayCount)-day plan") }
                if !trip.country.isEmpty { Text("· \(trip.country)") }
            }
            .font(.subheadline)
            .foregroundStyle(.secondary)
            HStack(spacing: 4) {
                ForEach(Array(Set(places.map(\.category))).sorted { $0.rawValue < $1.rawValue }) { category in
                    Image(systemName: category.symbol)
                        .font(.caption2)
                        .foregroundStyle(category.color)
                }
            }
        }
        .padding(.vertical, 4)
    }
}

struct AddLinkSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(ImportCoordinator.self) private var importer
    @State private var text = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://www.tiktok.com/…", text: $text, axis: .vertical)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button("Paste from clipboard") {
                        text = UIPasteboard.general.string ?? text
                    }
                } footer: {
                    Text("Paste a TikTok, Instagram Reel or YouTube Shorts link. Sharing straight from the app works too.")
                }
            }
            .navigationTitle("Add a reel")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") {
                        importer.addLink(text)
                        dismiss()
                    }
                    .disabled(LinkExtractor.firstURL(in: text) == nil)
                }
            }
        }
        .presentationDetents([.medium])
    }
}
