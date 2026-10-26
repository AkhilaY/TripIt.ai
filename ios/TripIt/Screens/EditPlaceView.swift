import MapKit
import SwiftUI

/// A place from an edit that isn't in your library yet (a publication's pick): its photo, why it's in the edit,
/// the article it came from, directions, and Save. Once saved it becomes the full place page.
struct EditPlaceView: View {
    let tripId: String
    let editId: String
    let entryId: String
    @Environment(Store.self) private var store
    @State private var item: EditItem?
    @State private var editTitle = ""
    @State private var tripCity = ""
    @State private var error: String?
    @State private var savedPlaceId: String?
    @State private var saving = false

    var body: some View {
        Group {
            if let savedPlaceId {
                PlaceView(placeId: savedPlaceId, tripId: nil)
            } else if let item {
                content(item)
            } else if let error {
                EmptyState(symbol: "sparkles", title: "Couldn't open this place", text: error)
                    .frame(maxHeight: .infinity)
            } else {
                SkeletonRows(count: 3).padding(20).frame(maxHeight: .infinity, alignment: .top)
            }
        }
        .background(Theme.background.ignoresSafeArea())
        .task { await load() }
    }

    private func load() async {
        do {
            let edits: TripEdits = try await API.shared.get("/v1/trips/\(tripId)/edits")
            guard let edit = edits.edits.first(where: { $0.id == editId }),
                  let entry = edit.entries.first(where: { $0.id == entryId }) else {
                error = "This edit was refreshed. Open the trip to see the latest ones."
                return
            }
            editTitle = edit.title
            tripCity = store.trips.first { $0.id == tripId }?.city ?? ""
            if entry.saved, let placeId = entry.placeId { savedPlaceId = placeId } else { item = entry }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func save() async {
        saving = true
        do {
            let place: Place = try await API.shared.post("/v1/trips/\(tripId)/edits/\(editId)/entries/\(entryId)/save")
            await store.reloadPlaces()
            store.show("Saved \(place.name) to your library")
            withAnimation { savedPlaceId = place.id }
        } catch {
            store.fail(error)
        }
        saving = false
    }

    @ViewBuilder private func content(_ it: EditItem) -> some View {
        let category = Category(it.category)
        let city = it.city ?? tripCity
        let query = [it.name, it.neighborhood, city].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ")
        List {
            Section {
                if let photo = it.photo {
                    Color.clear
                        .frame(maxWidth: .infinity)
                        .frame(height: 300)
                        .overlay { RemoteImage(url: photo.url(width: 1000)) { Theme.fill } }
                        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                        .padding(.horizontal, 16)
                        .listRowInsets(EdgeInsets())
                        .listRowBackground(Color.clear)
                }
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        CategoryTile(category: category, size: 22)
                        Text(category.label.uppercased()).font(.caption.weight(.bold)).foregroundStyle(category.color).kerning(0.6)
                    }
                    Text(it.name).font(Theme.serif(32))
                    let loc = [it.neighborhood, city.isEmpty ? nil : city].compactMap { $0 }.joined(separator: " · ")
                    if !loc.isEmpty { Text(loc).font(.subheadline).foregroundStyle(Theme.secondary) }
                    if let rating = it.rating {
                        Label(String(format: "%.1f", rating) + (it.ratingCount.map { " · \(Fmt.count($0)) reviews" } ?? ""), systemImage: "star.fill")
                            .font(.subheadline).foregroundStyle(Theme.gold)
                    }
                    Label("New to you: from \(editTitle)", systemImage: "sparkles")
                        .font(.footnote).foregroundStyle(Theme.gold)
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets(top: 8, leading: 20, bottom: 4, trailing: 20))
                Button { Task { await save() } } label: {
                    if saving { ProgressView().tint(Theme.accentInk) } else { Label("Save to your library", systemImage: "bookmark.fill") }
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(saving)
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                HStack(spacing: 10) {
                    DirectionsButton(apple: Maps.appleDirections(latitude: it.latitude, longitude: it.longitude, query: query),
                                     google: Maps.googleDirections(latitude: it.latitude, longitude: it.longitude, query: query))
                    if let maps = it.mapsUrl.flatMap({ URL(string: $0) }) {
                        QuickButton(symbol: "globe", color: Theme.blue, title: "Google Maps") { Links.open(maps) }
                    }
                    if let url = it.source?.url.flatMap({ URL(string: $0) }) {
                        QuickButton(symbol: "book.fill", color: Theme.indigo, title: "Article") { Links.open(url) }
                    }
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 8, trailing: 16))
            }
            .listSectionSeparator(.hidden)

            if !it.note.isEmpty {
                Section("Why it's in \(editTitle)") {
                    Text(it.note)
                }
            }
            if let source = it.source {
                Section("Recommended by") {
                    Button { Links.open(source.url.flatMap { URL(string: $0) }) } label: {
                        HStack(spacing: 12) {
                            SymbolTile(symbol: "book.fill", color: Theme.indigo)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(source.name).foregroundStyle(Theme.label)
                                if let title = source.title { Text(title).font(.caption).foregroundStyle(Theme.secondary).lineLimit(2) }
                            }
                            Spacer()
                            if source.url != nil { Image(systemName: "arrow.up.right").font(.footnote).foregroundStyle(Theme.tertiary) }
                        }
                    }
                    .disabled(source.url == nil)
                }
            }
            if let lat = it.latitude, let lon = it.longitude {
                Section {
                    let coordinate = CLLocationCoordinate2D(latitude: lat, longitude: lon)
                    Map(initialPosition: .region(MKCoordinateRegion(center: coordinate, latitudinalMeters: 800, longitudinalMeters: 800))) {
                        Marker(it.name, systemImage: category.symbol, coordinate: coordinate).tint(category.color)
                    }
                    .allowsHitTesting(false)
                    .frame(height: 200)
                    .listRowInsets(EdgeInsets())
                } footer: {
                    Text("Save it to see opening hours and the menu, and to add it to folders and trips.")
                }
            }
        }
        .listStyle(.insetGrouped)
        .tripBackground()
        .navigationTitle(it.name)
        .navigationBarTitleDisplayMode(.inline)
    }
}
