import SwiftUI

/// What's on: concerts, theatre and sport near where you'll be during a trip, the ones that suit you marked, with
/// tickets and a way to add one to its day.
struct EventsView: View {
    let tripId: String
    @Environment(Store.self) private var store
    @State private var events: TripEvents?
    @State private var error: String?
    @State private var filter = "all"
    @State private var adding: Set<String> = []

    struct Filter: Identifiable {
        let id: String
        let label: String
    }

    static let filters = [
        Filter(id: "all", label: "All"), Filter(id: "match", label: "For you"), Filter(id: "music", label: "Music"),
        Filter(id: "arts", label: "Arts & theatre"), Filter(id: "sports", label: "Sports"), Filter(id: "family", label: "Family"),
        Filter(id: "other", label: "More"),
    ]

    private var trip: TripDetail? { store.tripDetails[tripId] }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                content
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 40)
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle("What's on")
        .task { await load() }
        .refreshable { await load(refresh: true) }
    }

    @ViewBuilder private var content: some View {
        if let error {
            EmptyState(symbol: "exclamationmark.triangle", title: "Couldn't load events", text: error) {
                Button("Try again") { Task { await load(refresh: true) } }.buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 200)
            }
        } else if let events {
            switch events.status {
            case "disabled":
                EmptyState(symbol: "ticket", title: "Events aren't available yet",
                           text: "Concerts, theatre and sport during your trips aren't switched on for The Travel Edit right now.")
            case "no_dates":
                EmptyState(symbol: "ticket", color: Theme.pink, title: "Add dates to see what's on",
                           text: "Set a start date for this trip and The Travel Edit will look for events on those days.")
            case "no_location":
                EmptyState(symbol: "mappin.slash", title: "No places on the map yet",
                           text: "Save a few places so The Travel Edit knows where you'll be, then it can look for events nearby.")
            case "error":
                EmptyState(symbol: "exclamationmark.triangle", title: "Couldn't load events", text: "Try again in a moment.") {
                    Button("Try again") { Task { await load(refresh: true) } }.buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 200)
                }
            default:
                list(events.events)
            }
        } else {
            VStack(spacing: 10) {
                ProgressView()
                Text("Looking for events").font(Theme.serif(20))
                Text("Checking what's on near where you're staying.").font(.subheadline).foregroundStyle(Theme.secondary)
            }
            .frame(maxWidth: .infinity).padding(.top, 60)
        }
    }

    private func matches(_ e: EventItem, _ id: String) -> Bool {
        id == "all" || (id == "match" ? e.match : e.category == id)
    }

    @ViewBuilder private func list(_ all: [EventItem]) -> some View {
        let available = Self.filters.filter { f in all.contains { matches($0, f.id) } }
        let current = available.contains { $0.id == filter } ? filter : "all"
        let shown = all.filter { matches($0, current) }
            .sorted { $0.startAt != $1.startAt ? $0.startAt < $1.startAt : ($0.match && !$1.match) }
        let days = shown.map(\.date).reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }
        if let trip { Text([trip.name, trip.startDate.map(Fmt.shortDay)].compactMap { $0 }.joined(separator: " · ")).font(.subheadline).foregroundStyle(Theme.secondary).padding(.top, 4) }
        if !all.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(available) { f in FilterChip(label: f.label, isOn: current == f.id) { filter = f.id } }
                }
            }
            .padding(.top, 12)
        }
        if shown.isEmpty {
            EmptyState(symbol: "ticket", title: all.isEmpty ? "Nothing found for these dates" : "Nothing in this filter",
                       text: all.isEmpty ? "There are no listed events near where you'll be on these days. Coverage is best in North America and parts of Europe."
                           : "Try another filter.")
        }
        ForEach(days, id: \.self) { day in
            let first = shown.first { $0.date == day }
            Eyebrow(text: Fmt.shortDay(day) + (first?.day.map { " · Day \($0)" } ?? ""), color: Theme.secondary).padding(.top, 22)
            ForEach(shown.filter { $0.date == day }) { event in card(event).padding(.top, 8) }
        }
        VStack(alignment: .leading, spacing: 8) {
            Text("Events and ticket links from Ticketmaster, which sells the tickets. The Travel Edit doesn't sell or hold tickets, and prices and availability can change. Picked for you using your taste profile.")
                .font(.footnote).foregroundStyle(Theme.secondary)
            Button("Refresh") { Task { await load(refresh: true) } }.font(.footnote.weight(.semibold)).foregroundStyle(Theme.link)
        }
        .padding(.top, 20)
    }

    private func card(_ e: EventItem) -> some View {
        let onTrip = trip?.places.contains { $0.name.lowercased() == e.name.lowercased() } ?? false
        return Card {
            if let image = e.image, let url = URL(string: image) {
                RemoteImage(url: url) { Theme.raised }
                    .frame(height: 150)
                    .frame(maxWidth: .infinity)
                    .clipped()
            }
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Chip(text: e.genre ?? Self.categoryLabel(e.category))
                    if e.match { Chip(text: "For you", symbol: "sparkles", color: Theme.gold) }
                    if e.status == "postponed" || e.status == "rescheduled" { Chip(text: e.status.capitalized, color: Theme.warn) }
                }
                Text(e.name).font(Theme.serif(20)).foregroundStyle(Theme.label).fixedSize(horizontal: false, vertical: true)
                Text([e.time.map(Fmt.clock) ?? "Time to be confirmed", e.venue].compactMap { $0 }.joined(separator: " · "))
                    .font(.footnote).foregroundStyle(Theme.secondary)
                if let why = e.why { Text(why).font(.footnote).italic().foregroundStyle(Theme.secondary) }
                if let price = Self.price(e) { Text(price).font(.footnote).foregroundStyle(Theme.secondary) }
                HStack(spacing: 10) {
                    Button("Tickets") { Links.open(URL(string: e.url)) }
                        .buttonStyle(PrimaryButtonStyle(compact: true)).fixedSize()
                    if onTrip {
                        Label("On your trip", systemImage: "checkmark").font(.footnote.weight(.semibold)).foregroundStyle(Theme.ok)
                    } else if let day = e.day {
                        Button { Task { await add(e) } } label: {
                            if adding.contains(e.id) { ProgressView() } else { Text("Add to Day \(day)") }
                        }
                        .buttonStyle(PrimaryButtonStyle(tinted: true, compact: true)).fixedSize()
                        .disabled(adding.contains(e.id))
                    }
                }
                .padding(.top, 4)
            }
            .padding(14)
        }
    }

    static func categoryLabel(_ category: String) -> String {
        ["music": "Music", "arts": "Arts & theatre", "sports": "Sports", "family": "Family"][category] ?? "Event"
    }

    static func price(_ e: EventItem) -> String? {
        guard let low = e.priceMin else { return nil }
        let money = { (n: Double) in n.formatted(.currency(code: e.currency ?? "USD").precision(.fractionLength(0))) }
        if let high = e.priceMax, high > low { return "\(money(low)) – \(money(high))" }
        return "From \(money(low))"
    }

    private func load(refresh: Bool = false) async {
        if store.tripDetails[tripId] == nil { _ = try? await store.loadTrip(tripId) }
        do {
            if refresh {
                events = try await API.shared.post("/v1/trips/\(tripId)/events/refresh")
            } else {
                events = try await API.shared.get("/v1/trips/\(tripId)/events")
            }
            error = nil
        } catch is CancellationError {
        } catch { self.error = error.localizedDescription }
    }

    private func add(_ e: EventItem) async {
        adding.insert(e.id)
        defer { adding.remove(e.id) }
        if await store.tripCall("POST", "/v1/trips/\(tripId)/events/\(e.id)/add") != nil {
            await store.reloadPlaces()
            store.show("Added to Day \(e.day ?? 1)")
        }
    }
}
