import SwiftUI

/// Trip → Places: everything on the trip by kind, the trip's edits, and shortcuts to bookings and packing.
struct TripPlaces: View {
    let trip: TripDetail
    @Binding var librarySheet: LibrarySheet?
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router

    var body: some View {
        let suggested = trip.places.filter(\.suggested)
        let mine = trip.places.filter { !$0.suggested }
        List {
            if !trip.isLocal {
                Section {
                    shortcut("ticket.fill", Theme.blue, "Bookings",
                             trip.bookings.isEmpty ? "Flights, stays and tables" : Fmt.plural(trip.bookings.count, "booking"),
                             "#/trip/\(trip.id)/bookings")
                    shortcut("suitcase.fill", Theme.teal, "Packing list", "Made for the weather and your plans", "#/packing/\(trip.id)")
                    shortcut("music.mic", Category.event.color, "What's on", "Events while you're there", "#/events/\(trip.id)")
                }
                EditsRail(trip: trip)
            }
            Section {
                Button { router.addRequest = Router.AddRequest(tripId: trip.id) } label: { Label("Search for a place to add", systemImage: "magnifyingglass") }
                Button { addFromSaved() } label: { Label("Add from saved", systemImage: "plus.circle.fill") }
            }
            if trip.places.isEmpty {
                EmptyState(symbol: "mappin.slash", title: "No places on this trip yet",
                           text: "Add places from everything you've saved, or from one of your folders.")
                    .listRowBackground(Color.clear)
            }
            if !suggested.isEmpty {
                Section {
                    ForEach(suggested) { place in
                        HStack {
                            NavigationLink(value: Route.place(id: place.id, tripId: trip.id)) {
                                VStack(alignment: .leading, spacing: 4) {
                                    PlaceRow(place: place, showDay: true)
                                    if let note = place.suggestionNote {
                                        Text(note).font(.footnote).italic().foregroundStyle(Theme.secondary)
                                    }
                                }
                            }
                        }
                        .swipeActions(edge: .leading) {
                            Button {
                                Task {
                                    await store.tripCall("POST", "/v1/trips/\(trip.id)/places/\(place.id)/keep")
                                    await store.reloadPlaces()
                                    store.show("Kept, and added to your saved places")
                                }
                            } label: { Label("Keep", systemImage: "bookmark.fill") }
                            .tint(Theme.gold)
                        }
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                Task { await store.removeFromTrip(trip.id, place.id); store.show("Suggestion removed") }
                            } label: { Label("Remove", systemImage: "xmark") }
                        }
                    }
                } header: {
                    Label("Suggested for quiet days · \(suggested.count)", systemImage: "sparkles")
                } footer: {
                    Text("Swipe right to keep one; it joins your saved places too.")
                }
            }
            ForEach(Category.allCases) { category in
                let list = mine.filter { Category($0.category) == category }
                    .sorted { $0.mustDo != $1.mustDo ? $0.mustDo : $0.mentionCount > $1.mentionCount }
                if !list.isEmpty {
                    Section {
                        ForEach(list) { place in
                            NavigationLink(value: Route.place(id: place.id, tripId: trip.id)) {
                                PlaceRow(place: place, showCategory: false, showDay: true)
                            }
                            .swipeActions(edge: .leading) {
                                Button { Task { await store.toggleStar(place) } } label: {
                                    Label(place.mustDo ? "Unstar" : "Star", systemImage: place.mustDo ? "star.slash" : "star.fill")
                                }
                                .tint(Theme.gold)
                            }
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    Task { await store.removeFromTrip(trip.id, place.id); store.show("Removed from the trip. It's still saved.") }
                                } label: { Label("Remove", systemImage: "minus.circle") }
                            }
                        }
                    } header: {
                        HStack(spacing: 8) {
                            CategoryTile(category: category, size: 22)
                            Text(category.label).font(Theme.serif(20)).foregroundStyle(Theme.label).textCase(nil)
                            Text("\(list.count)").foregroundStyle(Theme.secondary)
                        }
                    }
                }
            }
            if !trip.reels.isEmpty {
                Section("Saved from") {
                    ForEach(trip.reels) { reel in
                        Button { Links.open(URL(string: reel.url)) } label: {
                            HStack(spacing: 12) {
                                SymbolTile(symbol: JobRow.symbol(for: reel.url), color: Theme.indigo)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(reel.title).foregroundStyle(Theme.label).lineLimit(2)
                                    Text([reel.creator.map { "@\($0)" }, Fmt.plural(reel.placeCount, "place")].compactMap { $0 }.joined(separator: " · "))
                                        .font(.caption).foregroundStyle(Theme.secondary)
                                }
                            }
                        }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .tripBackground()
    }

    private func shortcut(_ symbol: String, _ color: Color, _ title: String, _ subtitle: String, _ hash: String) -> some View {
        Button { router.push(.web(hash: hash)) } label: {
            HStack(spacing: 12) {
                SymbolTile(symbol: symbol, color: color)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).foregroundStyle(Theme.label)
                    Text(subtitle).font(.caption).foregroundStyle(Theme.secondary)
                }
                Spacer()
                Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.tertiary)
            }
        }
    }

    private func addFromSaved() {
        let tripId = trip.id
        librarySheet = .pick(title: "Add to \(trip.name)", exclude: Set(trip.places.map(\.id)), confirm: "Add", onDone: { ids in
            await store.addToTrip(tripId, ids)
            store.show("Added \(Fmt.plural(ids.count, "place"))")
        })
    }
}

/// The trip's edits: magazine-style picks mixing your saved places with ones publications recommend.
struct EditsRail: View {
    let trip: TripDetail
    @Environment(Router.self) private var router
    @Environment(Store.self) private var store
    @State private var edits: TripEdits?
    @State private var refreshing = false

    var body: some View {
        Section {
            if let edits, !edits.edits.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 12) {
                        ForEach(edits.edits) { edit in
                            Button { router.push(.web(hash: "#/edit/\(trip.id)/\(edit.id)")) } label: { EditCard(edit: edit) }
                                .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 16)
                }
                .listRowInsets(EdgeInsets(top: 4, leading: 0, bottom: 4, trailing: 0))
                .listRowBackground(Color.clear)
            } else if refreshing {
                HStack { ProgressView(); Text("Curating edits for \(trip.city)…").foregroundStyle(Theme.secondary) }
            } else {
                Text(trip.places.count < 3 ? "Save at least three places here for edits." : "No edits yet.")
                    .foregroundStyle(Theme.secondary)
            }
        } header: {
            HStack {
                Text("The edits").font(Theme.serif(20)).foregroundStyle(Theme.label).textCase(nil)
                Spacer()
                if refreshing { ProgressView().controlSize(.small) }
                else if trip.places.count >= 3 {
                    Button("New edits") { Task { await curate() } }.font(.subheadline.weight(.semibold)).textCase(nil)
                }
            }
        }
        .task(id: trip.id) { await load() }
    }

    private func load() async {
        guard let fresh: TripEdits = try? await API.shared.get("/v1/trips/\(trip.id)/edits") else { return }
        edits = fresh
        refreshing = fresh.refreshing
        if (fresh.edits.isEmpty || fresh.stale) && !fresh.refreshing && trip.places.count >= 3 { await curate(quiet: true) }
        else if fresh.refreshing { await poll() }
    }

    private func curate(quiet: Bool = false) async {
        do {
            let fresh: TripEdits = try await API.shared.post("/v1/trips/\(trip.id)/edits")
            edits = fresh.edits.isEmpty ? edits : fresh
            refreshing = true
            await poll()
            if !quiet { store.show("New edits are ready") }
        } catch {
            refreshing = false
            if !quiet { store.fail(error) }
        }
    }

    private func poll() async {
        refreshing = true
        for _ in 0..<40 {
            try? await Task.sleep(for: .seconds(4))
            if Task.isCancelled { return }
            guard let fresh: TripEdits = try? await API.shared.get("/v1/trips/\(trip.id)/edits") else { continue }
            if !fresh.refreshing {
                edits = fresh
                break
            }
        }
        refreshing = false
    }
}

private struct EditCard: View {
    let edit: TripEdit

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ZStack(alignment: .topLeading) {
                RemoteImage(url: (edit.coverPhoto ?? edit.entries.first?.photo)?.url(width: 600)) {
                    LinearGradient(colors: [Theme.gold, Theme.accent], startPoint: .topLeading, endPoint: .bottomTrailing)
                }
                .frame(width: 220, height: 140)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                if edit.newCount > 0 {
                    Text("\(edit.newCount) new").font(.caption.weight(.bold)).foregroundStyle(.white)
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(.black.opacity(0.45), in: Capsule())
                        .padding(8)
                }
            }
            Text(edit.title).font(Theme.serif(18)).foregroundStyle(Theme.label).lineLimit(2)
            Text(edit.dek).font(.caption).foregroundStyle(Theme.secondary).lineLimit(2)
        }
        .frame(width: 220, alignment: .leading)
    }
}
