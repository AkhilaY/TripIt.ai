import MapKit
import SwiftUI

/// One place: photos, what the reel said, hours, how to get there, its folders and trips, and your notes.
/// Opened from a trip it also shows that trip's day and time for it.
struct PlaceView: View {
    let placeId: String
    let tripId: String?
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var detail: PlaceDetail?
    @State private var loadError: String?
    @State private var notes = ""
    @State private var notesLoaded = false
    @State private var sheet: LibrarySheet?
    @State private var confirmDelete = false
    @State private var locating = false
    @State private var locateQuery = ""
    @State private var showDirections = false

    private var trip: TripDetail? { tripId.flatMap { store.tripDetails[$0] } }

    private var place: Place? {
        if let trip, let p = trip.places.first(where: { $0.id == placeId }) { return p }
        return store.places.first { $0.id == placeId } ?? detail?.place
    }

    var body: some View {
        Group {
            if let place {
                content(place)
            } else if let loadError {
                EmptyState(symbol: "mappin.slash", title: "Couldn't open this place", text: loadError)
                    .frame(maxHeight: .infinity)
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Theme.background.ignoresSafeArea())
        .task { await load() }
    }

    private func load() async {
        do {
            if let tripId, store.tripDetails[tripId] == nil { _ = try await store.loadTrip(tripId) }
            let fresh: PlaceDetail = try await API.shared.get("/v1/places/\(placeId)")
            detail = fresh
            if !notesLoaded { notes = fresh.place.userNotes; notesLoaded = true }
            await findReserveLink(fresh.place)
        } catch {
            loadError = error.localizedDescription
        }
    }

    /// Looks once, in the background, for the restaurant's Resy, OpenTable, Tock or SevenRooms page.
    private func findReserveLink(_ p: Place) async {
        guard Category(p.category).hasMenu, p.website != nil, p.reserveCheckedAt == nil else { return }
        if let fresh: Place = try? await API.shared.post("/v1/places/\(p.id)/reserve-link") {
            store.update(fresh)
            detail?.place = fresh
        }
    }

    @ViewBuilder private func content(_ p: Place) -> some View {
        let category = Category(p.category)
        List {
            Section {
                Hero(place: p)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                header(p, category)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets(top: 8, leading: 20, bottom: 4, trailing: 20))
                if !p.summary.isEmpty {
                    Text(p.summary).font(.body).foregroundStyle(Theme.label)
                        .listRowBackground(Color.clear)
                        .listRowInsets(EdgeInsets(top: 4, leading: 20, bottom: 4, trailing: 20))
                }
                quickActions(p, category)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
            }
            .listSectionSeparator(.hidden)

            librarySection(p)
            if category == .event { eventSection(p) }
            if let trip, trip.dayCount > 0, !trip.isLocal { planSection(p, trip) }
            if !p.isLocated { locateSection(p) }
            hoursSection(p)
            if !p.recommendedItems.isEmpty || p.tips != nil || p.priceHint != nil { reelSection(p) }
            detailsSection(p, category)
            notesSection(p)
            if let reels = detail?.reels, !reels.isEmpty { savedFrom(reels) }
            Section {
                Button("Delete place", role: .destructive) { confirmDelete = true }
                    .frame(maxWidth: .infinity)
            }
        }
        .listStyle(.insetGrouped)
        .tripBackground()
        .navigationTitle(p.name)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            Button { Task { await store.toggleStar(p) } } label: {
                Image(systemName: p.mustDo ? "star.fill" : "star")
            }
            .tint(p.mustDo ? Theme.gold : Theme.accent)
            .accessibilityLabel(p.mustDo ? "Remove the star" : "Star this place")
            ShareLink(item: p.googleMapsURL ?? AppConfig.baseURL, subject: Text(p.name), message: Text(p.name))
        }
        .sheet(item: $sheet) { $0.view.environment(store).environment(router) }
        .confirmationDialog("Delete this place everywhere? It leaves your saved places, folders and trips.",
                            isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete place", role: .destructive) {
                Task { if await store.delete(p) { dismiss() } }
            }
        }
        .confirmationDialog("Directions to \(p.name)", isPresented: $showDirections, titleVisibility: .visible) {
            Button("Apple Maps") { Links.open(p.directionsURL) }
            Button("Google Maps") {
                var c = URLComponents(string: "https://www.google.com/maps/dir/")!
                c.queryItems = [.init(name: "api", value: "1"),
                                .init(name: "destination", value: p.coordinate.map { "\($0.latitude),\($0.longitude)" } ?? "\(p.name), \(p.city)")]
                Links.open(c.url)
            }
        }
        .alert("Find on the map", isPresented: $locating) {
            TextField("Search, e.g. \(p.name), \(p.city)", text: $locateQuery)
            Button("Cancel", role: .cancel) {}
            Button("Find") { Task { await locate(p) } }
        } message: {
            Text("Add a street or neighbourhood if the first search didn't find it.")
        }
        .onDisappear { saveNotes(p) }
    }

    // MARK: Header

    private func header(_ p: Place, _ category: Category) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                CategoryTile(category: category, size: 22)
                Text(category.label.uppercased()).font(.caption.weight(.bold)).foregroundStyle(category.color).kerning(0.6)
            }
            Text(p.name).font(Theme.serif(32))
            let loc = [p.neighborhood, p.city.isEmpty ? nil : p.city].compactMap { $0 }.joined(separator: " · ")
            if !loc.isEmpty { Text(loc).font(.subheadline).foregroundStyle(Theme.secondary) }
            if p.mustDo {
                Label("Starred: first in your lists, and the planner always fits it in", systemImage: "star.fill")
                    .font(.footnote).foregroundStyle(Theme.gold)
            }
            if let need = needText(p) {
                Label(need, systemImage: "calendar.badge.exclamationmark")
                    .font(.footnote).foregroundStyle(Theme.warn)
            }
            if p.mentionCount >= 2 {
                Label("Recommended in \(p.mentionCount) of your saved reels", systemImage: "flame.fill")
                    .font(.footnote).foregroundStyle(Theme.orange)
            }
            if let status = Hours.status(p.openingHours) {
                Text(status.label).font(.subheadline.weight(.semibold)).foregroundStyle(status.isOpen ? Theme.ok : Theme.danger)
            }
            if let resolved = p.resolvedName, resolved != p.name {
                Text("On maps as \(resolved)").font(.footnote).foregroundStyle(Theme.secondary)
            }
            if p.confidence == "low" {
                Text("The name was hard to make out in the reel; double-check it.").font(.footnote).foregroundStyle(Theme.warn)
            }
        }
    }

    private func needText(_ p: Place) -> String? {
        guard let need = p.bookingNeed else { return nil }
        let required = need == "required"
        let text: String
        if p.bookingKind == "tickets" { text = required ? "Tickets needed" : "Tickets recommended" }
        else { text = required ? "Book ahead" : "Booking recommended" }
        if let note = p.bookingNote { return text + ". " + note }
        return text
    }

    private func quickActions(_ p: Place, _ category: Category) -> some View {
        let booked = trip?.bookings.contains { $0.placeId == p.id && $0.kind == "reservation" } ?? false
        let reserve: URL? = booked ? nil : p.reserveUrl.flatMap { URL(string: $0) }
        return HStack(spacing: 10) {
            if let reserve {
                QuickButton(symbol: "calendar.badge.plus", color: Theme.gold, title: "Reserve") { Links.open(reserve) }
            }
            QuickButton(symbol: "map.fill", color: Theme.green, title: "Apple Maps") { Links.open(p.appleMapsURL) }
            QuickButton(symbol: "globe", color: Theme.blue, title: "Google") { Links.open(p.googleMapsURL) }
            QuickButton(symbol: "arrow.triangle.turn.up.right.diamond.fill", color: Theme.orange, title: "Directions") { showDirections = true }
            if category.hasMenu {
                QuickButton(symbol: "menucard.fill", color: Theme.pink, title: "Menu") { router.push(.web(hash: "#/place/\(p.id)/menu")) }
            }
        }
    }

    // MARK: Sections

    @ViewBuilder private func librarySection(_ p: Place) -> some View {
        if p.suggested, let trip {
            Section {
                HStack {
                    SymbolTile(symbol: "sparkles", color: Theme.gold)
                    VStack(alignment: .leading) {
                        Text("Suggested for this trip")
                        Text(p.suggestionNote ?? "Added by AI to fill a quiet day").font(.caption).foregroundStyle(Theme.secondary)
                    }
                    Spacer()
                    Button("Keep") {
                        Task {
                            await store.tripCall("POST", "/v1/trips/\(trip.id)/places/\(p.id)/keep")
                            await store.reloadPlaces()
                            store.show("Kept, and added to your saved places")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                }
            }
        } else {
            let folders = store.folders.filter { p.folderIds.contains($0.id) }.map(\.name)
            let trips = store.trips.filter { p.tripIds.contains($0.id) }.map(\.name)
            Section("In your library") {
                Button { sheet = .folders([p.id]) } label: {
                    row(symbol: "folder.fill", color: Theme.gold, title: "Folders",
                        value: folders.isEmpty ? "Not in a folder" : folders.joined(separator: ", "), chevron: true)
                }
                Button { sheet = .trips([p.id]) } label: {
                    row(symbol: "airplane", color: Theme.blue, title: "Trips",
                        value: trips.isEmpty ? "Not in a trip yet" : trips.joined(separator: ", "), chevron: true)
                }
                if let trip {
                    Button {
                        Task {
                            await store.removeFromTrip(trip.id, p.id)
                            store.show("Removed from the trip. It's still saved.")
                            dismiss()
                        }
                    } label: {
                        row(symbol: "xmark", color: Theme.gray, title: "Remove from \(trip.name)", value: "It stays in your saved places")
                    }
                }
            }
        }
    }

    private func eventSection(_ p: Place) -> some View {
        Section {
            if let date = p.eventDate.flatMap(Fmt.day) {
                DatePicker("Date", selection: Binding(get: { date }, set: { new in
                    Task { await store.patch(p, ["event_date": Fmt.iso(new)]) }
                }), displayedComponents: .date)
                Button("Clear date", role: .destructive) { Task { await store.patch(p, ["clear_event_date": true]) } }
            } else {
                Button { Task { await store.patch(p, ["event_date": Fmt.iso(Date())]) } } label: {
                    row(symbol: "calendar.badge.plus", color: Category.event.color, title: "Add the date", value: "So it shows on your calendar")
                }
            }
            if let venue = p.venue { row(symbol: "mappin", color: Theme.gray, title: "Where", value: venue) }
        } header: {
            Text("When")
        } footer: {
            if let end = p.eventEndDate { Text("Runs until \(Fmt.shortDay(end)).") }
        }
    }

    private func planSection(_ p: Place, _ trip: TripDetail) -> some View {
        Section("On this trip") {
            Picker(selection: Binding(get: { p.dayNumber ?? 0 }, set: { day in
                Task { await store.patch(p, ["day_number": day], tripId: trip.id) }
            })) {
                Text("Not scheduled").tag(0)
                ForEach(1...trip.dayCount, id: \.self) { d in
                    Text(Fmt.tripDay(start: trip.startDate, day: d).map { "Day \(d) · \($0)" } ?? "Day \(d)").tag(d)
                }
            } label: { Label("Day", systemImage: "calendar") }
            Picker(selection: Binding(get: { p.timeOfDay ?? "" }, set: { value in
                Task { await store.patch(p, value.isEmpty ? ["clear_time_of_day": true] : ["time_of_day": value], tripId: trip.id) }
            })) {
                Text("Any time").tag("")
                ForEach(Fmt.timesOfDay, id: \.self) { Text($0.capitalized).tag($0) }
            } label: { Label("Time of day", systemImage: "clock") }
            if let start = p.startTime, let date = clockDate(start) {
                HStack {
                    DatePicker(selection: Binding(get: { date }, set: { new in
                        Task { await store.patch(p, ["start_time": hhmm(new)], tripId: trip.id) }
                    }), displayedComponents: .hourAndMinute) { Label("Exact time", systemImage: "alarm") }
                    Button("Clear") { Task { await store.patch(p, ["clear_start_time": true], tripId: trip.id) } }
                        .buttonStyle(.borderless)
                }
            } else {
                Button { Task { await store.patch(p, ["start_time": "19:00"], tripId: trip.id) } } label: {
                    Label("Set an exact time (a reservation or tour)", systemImage: "alarm")
                }
            }
        }
    }

    private func locateSection(_ p: Place) -> some View {
        Section {
            Button {
                locateQuery = [p.name, p.neighborhood, p.city].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ")
                locating = true
            } label: {
                row(symbol: "mappin.and.ellipse", color: Theme.warn, title: "Not on the map yet", value: "Search for it to add the pin", chevron: true)
            }
        }
    }

    private func locate(_ p: Place) async {
        do {
            let fresh: Place = try await API.shared.post("/v1/places/\(p.id)/locate", ["query": locateQuery])
            store.update(fresh)
            detail?.place = fresh
            if let tripId { _ = try? await store.loadTrip(tripId) }
            store.show("Found it")
        } catch { store.fail(error) }
    }

    @ViewBuilder private func hoursSection(_ p: Place) -> some View {
        Section {
            if let hours = p.openingHours, !hours.text.isEmpty {
                let today = Hours.mondayIndex()
                ForEach(Array(hours.text.enumerated()), id: \.offset) { i, line in
                    Text(line)
                        .font(.subheadline.weight(hours.weekly != nil && i == today ? .semibold : .regular))
                        .foregroundStyle(hours.weekly != nil && i == today ? Theme.label : Theme.secondary)
                }
            } else {
                Text("No opening hours found for this place. Check Google Maps before you go.")
                    .font(.subheadline).foregroundStyle(Theme.secondary)
            }
        } header: {
            Text("Hours")
        } footer: {
            if let hours = p.openingHours, !hours.text.isEmpty {
                Text("From \(hours.source == "google" ? "Google" : "OpenStreetMap"). Hours change, so check before you go.")
            }
        }
    }

    private func reelSection(_ p: Place) -> some View {
        Section("From the reel") {
            ForEach(p.recommendedItems, id: \.self) { item in
                Label { Text(item) } icon: { Image(systemName: "star.fill").foregroundStyle(Theme.gold) }
            }
            if let price = p.priceHint { row(symbol: "tag.fill", color: Theme.green, title: "Price", value: price) }
            if let tips = p.tips { row(symbol: "sparkles", color: Theme.pink, title: "Tip", value: tips) }
        }
    }

    private func detailsSection(_ p: Place, _ category: Category) -> some View {
        Section("Details") {
            if let rating = p.rating {
                Button { Links.open(p.googleMapsURL) } label: {
                    row(symbol: "star.fill", color: Theme.gold, title: "Google rating",
                        value: String(format: "%.1f", rating) + (p.ratingCount.map { " · \($0.formatted()) reviews" } ?? " out of 5"), chevron: true)
                }
            }
            if let site = p.website, let url = URL(string: site) {
                Button { Links.open(url) } label: {
                    row(symbol: "globe", color: Theme.blue, title: "Website",
                        value: (url.host ?? site).replacingOccurrences(of: "www.", with: ""), chevron: true)
                }
            }
            if let phone = p.phone {
                Button { Links.open(URL(string: "tel:" + phone.filter { $0.isNumber || $0 == "+" })) } label: {
                    row(symbol: "phone.fill", color: Theme.green, title: "Phone", value: phone, chevron: true)
                }
            }
            if let address = p.address {
                row(symbol: "mappin", color: Theme.gray, title: "Address", value: address)
                    .contextMenu { Button { UIPasteboard.general.string = address } label: { Label("Copy address", systemImage: "doc.on.doc") } }
            }
            Toggle(isOn: Binding(get: { p.visited }, set: { v in Task { await store.patch(p, ["visited": v]) } })) {
                Label("Visited", systemImage: "checkmark.circle")
            }
            Picker(selection: Binding(get: { category }, set: { c in Task { await store.patch(p, ["category": c.rawValue]) } })) {
                ForEach(Category.allCases) { Label($0.label, systemImage: $0.symbol).tag($0) }
            } label: { Label("Category", systemImage: category.symbol) }
            if p.isLocated {
                Button {
                    locateQuery = [p.name, p.neighborhood, p.city].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ")
                    locating = true
                } label: { Label("Wrong pin? Search again", systemImage: "location.magnifyingglass") }
            }
        }
    }

    private func notesSection(_ p: Place) -> some View {
        Section("My notes") {
            TextField("Add a note", text: $notes, axis: .vertical)
                .lineLimit(3...12)
                .onChange(of: notes) { _, _ in scheduleNotesSave(p) }
        }
    }

    private func savedFrom(_ reels: [Reel]) -> some View {
        Section("Saved from") {
            ForEach(reels) { reel in
                Button { Links.open(URL(string: reel.url)) } label: {
                    HStack(spacing: 12) {
                        SymbolTile(symbol: JobRow.symbol(for: reel.url), color: Theme.indigo)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(reel.title).foregroundStyle(Theme.label).lineLimit(2)
                            Text([reel.platform.capitalized, reel.creator.map { "@\($0)" }].compactMap { $0 }.joined(separator: " · "))
                                .font(.caption).foregroundStyle(Theme.secondary)
                        }
                        Spacer()
                        Image(systemName: "arrow.up.right").font(.footnote).foregroundStyle(Theme.tertiary)
                    }
                }
            }
        }
    }

    private func row(symbol: String, color: Color, title: String, value: String, chevron: Bool = false) -> some View {
        HStack(spacing: 12) {
            SymbolTile(symbol: symbol, color: color)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).foregroundStyle(Theme.label)
                Text(value).font(.subheadline).foregroundStyle(Theme.secondary)
            }
            Spacer(minLength: 0)
            if chevron { Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.tertiary) }
        }
    }

    // MARK: Notes and times

    @State private var notesTask: Task<Void, Never>?

    private func scheduleNotesSave(_ p: Place) {
        guard notesLoaded else { return }
        notesTask?.cancel()
        notesTask = Task {
            try? await Task.sleep(for: .seconds(1.2))
            if !Task.isCancelled { saveNotes(p) }
        }
    }

    private func saveNotes(_ p: Place) {
        guard notesLoaded, notes != (place?.userNotes ?? p.userNotes) else { return }
        let text = notes
        Task { await store.patch(p, ["user_notes": text]) }
    }

    private func clockDate(_ hhmm: String) -> Date? {
        let parts = hhmm.split(separator: ":").compactMap { Int($0) }
        guard parts.count == 2 else { return nil }
        return Calendar.current.date(bySettingHour: parts[0], minute: parts[1], second: 0, of: Date())
    }

    private func hhmm(_ date: Date) -> String {
        let c = Calendar.current.dateComponents([.hour, .minute], from: date)
        return String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0)
    }
}

private struct QuickButton: View {
    let symbol: String
    let color: Color
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 6) {
                SymbolTile(symbol: symbol, color: color, size: 34)
                Text(title).font(.caption.weight(.medium)).foregroundStyle(Theme.label).lineLimit(1).minimumScaleFactor(0.8)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(Theme.cell, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

/// Swipe through the place's photos, with its spot on the map as the last page.
private struct Hero: View {
    let place: Place
    @State private var page = 0

    var body: some View {
        let photos = place.photos
        let pages = photos.count + (place.isLocated ? 1 : 0)
        if pages > 0 {
            TabView(selection: $page) {
                ForEach(Array(photos.enumerated()), id: \.offset) { i, photo in
                    RemoteImage(url: photo.url(width: 1000)) { Theme.fill }
                        .frame(maxWidth: .infinity)
                        .frame(height: 300)
                        .clipped()
                        .overlay(alignment: .bottomLeading) {
                            if let credit = photo.attribution ?? (photo.source == "reel" ? "From the reel" : nil) {
                                Text(credit).font(.caption2).foregroundStyle(.white.opacity(0.9))
                                    .padding(.horizontal, 8).padding(.vertical, 4)
                                    .background(.black.opacity(0.35), in: Capsule())
                                    .padding(10)
                            }
                        }
                        .tag(i)
                }
                if let coordinate = place.coordinate {
                    Map(initialPosition: .region(MKCoordinateRegion(center: coordinate, latitudinalMeters: 700, longitudinalMeters: 700))) {
                        Marker(place.name, systemImage: Category(place.category).symbol, coordinate: coordinate)
                            .tint(Category(place.category).color)
                    }
                    .allowsHitTesting(false)
                    .frame(height: 300)
                    .tag(photos.count)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: pages > 1 ? .always : .never))
            .frame(height: 300)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .padding(.horizontal, 16)
        }
    }
}
