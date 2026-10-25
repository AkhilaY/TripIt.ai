import SwiftUI

/// The Discover tab: well-rated places near home, near you, or around a trip, picked for your taste, with the edits
/// for that city above them. While you're travelling it looks around your trip unless you pick somewhere else.
struct DiscoverView: View {
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @State private var location = Location.shared
    @AppStorage("discover.kind") private var kind = "restaurants"
    @State private var area = "home"  // home, here or trip
    @State private var tripId: String?
    @State private var picked = false
    @State private var results: [String: DiscoverResult] = [:]
    @State private var errors: [String: String] = [:]
    @State private var loading: Set<String> = []
    @State private var saving: Set<String> = []
    @State private var allEdits: [TripEdits] = []

    struct Kind: Identifiable {
        let id: String
        let label: String
        let category: Category
    }

    static let kinds = [
        Kind(id: "restaurants", label: "Restaurants", category: .food), Kind(id: "coffee", label: "Coffee", category: .cafe),
        Kind(id: "bars", label: "Bars", category: .drinks), Kind(id: "dessert", label: "Dessert", category: .dessert),
        Kind(id: "things", label: "Things to do", category: .activity),
    ]

    /// An edit and the trip it belongs to.
    struct EditRef: Identifiable {
        let tripId: String
        let edit: TripEdit
        var id: String { "\(tripId)/\(edit.id)" }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                header
                edits
                content
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 40)
        }
        .background(Theme.background.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .refreshable { await load(force: true) }
        .task(id: "\(key)|\(store.loaded)") {
            settleArea()
            await load()
        }
        .task { await loadEdits() }
        .onChange(of: location.current) { _, _ in
            if area == "here", results[key] == nil { Task { await load() } }
        }
    }

    // MARK: Where and what

    private var tripsWithPlaces: [Trip] { store.realTrips.filter { $0.placeCount > 0 } }

    private var key: String { "\(area)|\(area == "trip" ? tripId ?? "" : "")|\(kind)" }

    /// While travelling Discover looks around the trip, unless you picked somewhere; without a home city, near you.
    private func settleArea() {
        if !picked, let active = store.activeTrip, active.trip.placeCount > 0 {
            area = "trip"
            tripId = active.trip.id
        }
        if area == "home", store.home == nil { area = "here" }
        if area == "trip", !tripsWithPlaces.contains(where: { $0.id == tripId }) { area = store.home == nil ? "here" : "home" }
    }

    private var trip: Trip? { area == "trip" ? tripsWithPlaces.first { $0.id == tripId } : nil }

    /// The city being looked at: home, or the trip's stop today (or its first city).
    private var cityName: String {
        if area == "home" { return store.home?.city ?? "" }
        guard let trip else { return "" }
        if let active = store.activeTrip, active.trip.id == trip.id,
           let stop = (trip.stops ?? []).first(where: { active.day >= $0.startDay && active.day <= $0.endDay }) {
            return stop.city
        }
        return trip.city
    }

    private var areaLabel: String {
        switch area {
        case "home": return "Near you · \(store.home?.city ?? "")"
        case "here": return "Near you"
        default: return [trip?.name ?? "Trip", cityName.isEmpty ? nil : cityName].compactMap { $0 }.joined(separator: " · ")
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Spacer()
                RoundIconButton(symbol: "plus", label: "Save a place") { router.addRequest = Router.AddRequest() }
                ProfileButton()
            }
            .padding(.top, 8)
            Text("Discover").font(Theme.serif(32)).foregroundStyle(Theme.label).padding(.top, 8)
            Menu {
                Button { choose("here", nil) } label: { check(area == "here", "My location") }
                if let home = store.home {
                    Button { choose("home", nil) } label: { check(area == "home", "\(home.city) (home)") }
                }
                ForEach(tripsWithPlaces) { t in
                    Button { choose("trip", t.id) } label: { check(area == "trip" && tripId == t.id, t.name) }
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "location.fill").font(.caption)
                    Text(areaLabel).font(.subheadline.weight(.semibold)).lineLimit(1)
                    Image(systemName: "chevron.down").font(.caption2.weight(.bold))
                }
                .foregroundStyle(Theme.label)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(Theme.cell, in: Capsule())
                .overlay(Capsule().strokeBorder(Theme.border))
            }
            .padding(.top, 10)
            Text("Switches to your trip city when you travel").font(.footnote).foregroundStyle(Theme.secondary).padding(.top, 6)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(Self.kinds) { k in
                        FilterChip(label: k.label, isOn: kind == k.id) { kind = k.id }
                    }
                }
            }
            .padding(.top, 12)
        }
    }

    @ViewBuilder private func check(_ on: Bool, _ title: String) -> some View {
        if on { Label(title, systemImage: "checkmark") } else { Text(title) }
    }

    private func choose(_ newArea: String, _ newTrip: String?) {
        picked = true
        area = newArea
        tripId = newTrip
        if newArea == "here" { location.request() }
    }

    // MARK: Edits for this city

    @ViewBuilder private var edits: some View {
        let cards = editCards
        if !cards.isEmpty {
            SectionHeading(title: "The edits\(cityName.isEmpty ? "" : " · \(cityName)")") {
                if cards.count > 1 { Text("\(cards.count) edits · swipe").font(.caption).foregroundStyle(Theme.secondary) }
            }
            .padding(.top, 22)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: 12) {
                    ForEach(cards) { card in
                        Button { router.push(.edit(tripId: card.tripId, editId: card.edit.id)) } label: { EditCard(edit: card.edit) }
                            .buttonStyle(.plain)
                    }
                }
            }
            .padding(.horizontal, -20)
            .contentMargins(.horizontal, 20, for: .scrollContent)
        }
    }

    private var editCards: [EditRef] {
        let matching = allEdits.filter { te in
            if let trip { return te.tripId == trip.id }
            guard !cityName.isEmpty, let t = store.trips.first(where: { $0.id == te.tripId }) else { return false }
            return t.cities.contains { Store.cityKey($0) == Store.cityKey(cityName) }
        }
        return Array(matching.flatMap { te in te.edits.map { EditRef(tripId: te.tripId, edit: $0) } }.prefix(6))
    }

    private func loadEdits() async {
        if let all: [TripEdits] = try? await API.shared.get("/v1/edits") { allEdits = all }
    }

    // MARK: Recommendations

    @ViewBuilder private var content: some View {
        let category = Self.kinds.first { $0.id == kind }?.category ?? .food
        if area == "here", location.current == nil {
            if location.denied {
                EmptyState(symbol: "location.slash", title: "Location is off",
                           text: "Allow location for The Travel Edit in Settings, or choose your home city or a trip above.")
            } else {
                ProgressView("Finding where you are…").frame(maxWidth: .infinity).padding(.top, 40)
                    .onAppear { location.request() }
            }
        } else if let message = errors[key] {
            EmptyState(symbol: "exclamationmark.triangle", title: "Couldn't load recommendations", text: message) {
                Button("Try again") { Task { await load(force: true) } }.buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 200)
            }
        } else if let result = results[key], !loading.contains(key) {
            switch result.status {
            case "disabled":
                EmptyState(symbol: "safari", title: "Discover isn't available yet",
                           text: "Recommendations aren't switched on for The Travel Edit right now. Your saved places and edits still work.")
            case "no_area":
                EmptyState(symbol: "mappin", title: "Where should we look?", text: "Set your home city in your profile, or choose Near you.") {
                    Button("Open your profile") { router.showProfile = true }.buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 220)
                }
            case "error":
                EmptyState(symbol: "exclamationmark.triangle", title: "Couldn't load recommendations", text: "Try again in a moment.") {
                    Button("Try again") { Task { await load(force: true) } }.buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 200)
                }
            default:
                if result.items.isEmpty {
                    EmptyState(symbol: "mappin.slash", title: "Nothing well-rated found here", text: "Try another kind of place or a wider area.")
                } else {
                    SectionHeading(title: "Popular near \(area == "trip" ? (cityName.isEmpty ? "your trip" : cityName) : "you")") {
                        Button("Refresh") { Task { await load(force: true) } }.font(.subheadline.weight(.semibold)).foregroundStyle(Theme.link)
                    }
                    .padding(.top, 22)
                    VStack(spacing: 0) {
                        ForEach(result.items) { item in
                            DiscoverRow(item: item, category: category, saving: saving.contains(item.id)) { Task { await save(item) } }
                            if item.id != result.items.last?.id { Divider().overlay(Theme.divider) }
                        }
                    }
                    Text("Well rated on Google and picked for your taste. Awards such as Michelin stars come from Claude's knowledge, not a live feed, so check before you go.")
                        .font(.footnote).foregroundStyle(Theme.secondary).padding(.top, 14)
                }
            }
        } else {
            VStack(spacing: 10) {
                ProgressView()
                Text("Finding the best nearby…").font(.subheadline).foregroundStyle(Theme.secondary)
            }
            .frame(maxWidth: .infinity).padding(.top, 50)
        }
    }

    private func load(force: Bool = false) async {
        let key = self.key
        guard force || (results[key] == nil && !loading.contains(key)) else { return }
        var query = [URLQueryItem(name: "kind", value: kind), URLQueryItem(name: "area", value: area)]
        if area == "trip", let tripId { query.append(URLQueryItem(name: "trip_id", value: tripId)) }
        if area == "here" {
            guard let here = location.current else { location.request(); return }
            query.append(URLQueryItem(name: "lat", value: String(here.coordinate.latitude)))
            query.append(URLQueryItem(name: "lon", value: String(here.coordinate.longitude)))
        }
        if force { query.append(URLQueryItem(name: "refresh", value: "true")) }
        var c = URLComponents()
        c.queryItems = query
        loading.insert(key)
        defer { loading.remove(key) }
        do {
            results[key] = try await API.shared.get("/v1/discover" + (c.string ?? ""))
            errors[key] = nil
        } catch is CancellationError {
        } catch {
            errors[key] = error.localizedDescription
        }
    }

    private func save(_ item: DiscoverItem) async {
        guard !item.saved, !saving.contains(item.id) else { return }
        saving.insert(item.id)
        defer { saving.remove(item.id) }
        do {
            let result: AddPlaceResult = try await API.shared.post("/v1/places", ["candidate_id": item.id, "trip_id": area == "trip" ? tripId : nil])
            if var r = results[key], let i = r.items.firstIndex(where: { $0.id == item.id }) {
                r.items[i].saved = true
                results[key] = r
            }
            await store.add(result)
        } catch { store.fail(error) }
    }
}

/// A recommendation: photo, name, the kind of place, price and distance, an award, why it suits you, and Save.
private struct DiscoverRow: View {
    let item: DiscoverItem
    let category: Category
    let saving: Bool
    let onSave: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            RemoteImage(url: item.photo.flatMap { API.shared.url($0) }) {
                ZStack {
                    category.color.opacity(0.14)
                    Image(systemName: category.symbol).font(.system(size: 20, weight: .semibold)).foregroundStyle(category.color)
                }
            }
            .frame(width: 56, height: 56)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .onTapGesture { openMaps() }
            VStack(alignment: .leading, spacing: 3) {
                Text(item.name).font(.body.weight(.semibold)).foregroundStyle(Theme.label).lineLimit(2)
                Text(subtitle).font(.footnote).foregroundStyle(Theme.secondary).lineLimit(1)
                if let award = item.award {
                    Label(award, systemImage: "sparkles").font(.caption.weight(.semibold)).foregroundStyle(Theme.gold)
                }
                if let why = item.why {
                    Text(why).font(.footnote).italic().foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            .contentShape(Rectangle())
            .onTapGesture { openMaps() }
            Spacer(minLength: 4)
            Button(action: onSave) {
                Group {
                    if saving { ProgressView().controlSize(.small) }
                    else { Image(systemName: item.saved ? "bookmark.fill" : "bookmark").font(.system(size: 17, weight: .medium)) }
                }
                .foregroundStyle(item.saved ? Theme.gold : Theme.label)
                .frame(width: 40, height: 40)
            }
            .buttonStyle(.plain)
            .disabled(item.saved || saving)
            .accessibilityLabel(item.saved ? "Saved: \(item.name)" : "Save \(item.name)")
        }
        .padding(.vertical, 12)
    }

    private var subtitle: String {
        let parts = (item.address ?? "").split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
        let hood = parts.count >= 3 ? parts[parts.count - 3] : nil
        let price = item.priceLevel.flatMap { (1...4).contains($0) ? String(repeating: "$", count: $0) : nil }
        let rating = item.rating.map { String(format: "★ %.1f", $0) }
        return [hood, item.kindLabel, rating, price, item.distanceM.map { Fmt.distance(Double($0)) }].compactMap { $0 }.joined(separator: " · ")
    }

    private func openMaps() {
        if let link = item.mapsUrl, let url = URL(string: link) { Links.open(url) }
    }
}
