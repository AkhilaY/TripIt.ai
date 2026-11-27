import SwiftUI

/// One of Home's daily edits: a short, titled set of places. Most are made on the phone from your own saves
/// ("Coffee in Atlanta", "Open now near you") and change each day; the rest are the AI-curated edits your planned
/// trips already have.
struct HomeEdit: Identifiable, Hashable {
    let id: String
    let caption: String  // "Atlanta · 6 places"
    let title: String
    let note: String
    let placeIds: [String]
    let cover: PlacePhoto?
    var city = ""  // for the drawn stand-in while (or if) there's no photo
    var fallbacks: [PlacePhoto] = []  // tried in turn if the cover doesn't load
    var urls: [URL]?  // a trip edit's photos in the order to try (see TripEdit.coverURLs)
    var preview = ""  // its first few places' names, for the card
    var tripId: String?
    var tripEditId: String?

    var route: Route {
        if let tripId, let tripEditId { return .edit(tripId: tripId, editId: tripEditId) }
        return .savedEdit(SavedEdit(id: id, title: title, note: note, placeIds: placeIds))
    }

    static func == (a: HomeEdit, b: HomeEdit) -> Bool { a.id == b.id && a.placeIds == b.placeIds }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

/// The places of an edit made from your saves, for its own page.
struct SavedEdit: Hashable {
    let id: String
    let title: String
    let note: String
    let placeIds: [String]
}

enum HomeEdits {
    /// Today's edits from your saves: every candidate with at least three places, in an order that turns over each
    /// day, five at most. `open` is what's open near you right now (its own edit when there are two or more).
    static func make(saved: [Place], home: String?, open: [Place], trips: [Trip], now: Date = Date()) -> [HomeEdit] {
        let day = Calendar.current.ordinality(of: .day, in: .era, for: now) ?? 0
        let notBeen = saved.filter { !$0.visited }
        var out: [HomeEdit] = []

        func add(_ id: String, _ caption: String, _ title: String, _ note: String, _ places: [Place], min: Int = 3) {
            guard places.count >= min else { return }
            let picked = order(places, day: day)
            let photos = picked.compactMap(\.photos.first)
            out.append(HomeEdit(id: id, caption: "\(caption) · \(Fmt.plural(places.count, "place"))", title: title, note: note,
                                placeIds: picked.map(\.id), cover: photos.first, city: picked.first?.city ?? caption,
                                fallbacks: Array(photos.dropFirst().prefix(3)), preview: Self.preview(picked.map(\.name))))
        }

        // The city most of your saves are in stands in for home until you set one.
        // Dictionaries come back in a different order each time they're built, so everything below is sorted:
        // the same saves always give the same edits in the same order, and a refresh doesn't reshuffle the cards.
        let city = home ?? Dictionary(grouping: notBeen.filter { !$0.city.isEmpty }, by: \.city)
            .max { ($0.value.count, $1.key) < ($1.value.count, $0.key) }?.key
        if let city {
            let here = notBeen.filter { PlaceFilter.normalize($0.city) == PlaceFilter.normalize(city) }
            add("coffee-\(city)", city, "Coffee in \(city)", "The cafés you've saved and haven't tried yet.",
                here.filter { Category($0.category) == .cafe })
            add("drinks-\(city)", city, "Drinks in \(city)", "Bars and late spots from your saves.",
                here.filter { [.drinks, .nightlife].contains(Category($0.category)) })
            add("sweet-\(city)", city, "Something sweet", "Bakeries and dessert places you saved in \(city).",
                here.filter { Category($0.category) == .dessert })
            let food = here.filter { Category($0.category) == .food }
            for (cuisine, places) in Dictionary(grouping: food.filter { $0.cuisine != nil }, by: { $0.cuisine! }).sorted(by: { $0.key < $1.key }) {
                guard let c = Cuisine(rawValue: cuisine) else { continue }
                add("cuisine-\(cuisine)-\(city)", city, "\(c.label) in \(city)", "Every \(c.label.lowercased()) place you've saved here.", places)
            }
            add("book-\(city)", city, "Worth booking ahead", "Places in \(city) that fill up. Get a table before you go.",
                here.filter { $0.shownNeed == "required" })
            add("starred-\(city)", city, "Your starred \(city)", "The places you marked as must-dos.", here.filter(\.mustDo))
            add("outside-\(city)", city, "Out and about", "Parks, sights and things to do around \(city).",
                here.filter { [.attraction, .nature, .activity].contains(Category($0.category)) })
        }

        // Cities you've saved a lot in but haven't planned a trip to yet.
        let planned = Set(trips.flatMap { [$0.city] + ($0.stops ?? []).map(\.city) }.map(PlaceFilter.normalize))
        let elsewhere = Dictionary(grouping: notBeen.filter { !$0.city.isEmpty && $0.city != city }, by: \.city)
        for (other, places) in elsewhere.sorted(by: { $0.key < $1.key }) where places.count >= 5 && !planned.contains(PlaceFilter.normalize(other)) {
            add("wish-\(other)", other, "One day in \(other)", "Your saves there, ready for when you go.", places, min: 5)
        }

        let monthAgo = Fmt.iso(Calendar.current.date(byAdding: .day, value: -30, to: now) ?? now)
        add("recent", "Saved this month", "Fresh finds", "Everything you saved in the last 30 days.",
            saved.filter { $0.createdAt >= monthAgo })

        // A new order each day, so Home doesn't show the same edits every morning.
        let rotated = out.isEmpty ? [] : Array(out[(day % out.count)...] + out[..<(day % out.count)])
        var picks = Array(rotated.prefix(5))
        if open.count >= 2 {
            let ids = open.map(\.id)
            picks.insert(HomeEdit(id: "open-now", caption: "Right now · \(Fmt.plural(open.count, "place"))", title: "Open now near you",
                                  note: "Saved places that are open as you read this, the closest first.", placeIds: ids,
                                  cover: open.filter { !$0.photos.isEmpty }.min { $0.id < $1.id }?.photos.first,  // not the nearest: it changes as you move
                                  city: open.first?.city ?? "", preview: Self.preview(open.map(\.name))), at: 0)
        }
        return picks
    }

    /// "First Cliff Walk, Lake St. Moritz, Rigi Kulm…"
    static func preview(_ names: [String]) -> String {
        names.prefix(3).joined(separator: ", ") + (names.count > 3 ? "…" : "")
    }

    /// Starred first, then a daily shuffle of the rest, eight at most.
    private static func order(_ places: [Place], day: Int) -> [Place] {
        let starred = places.filter(\.mustDo)
        let rest = places.filter { !$0.mustDo }.sorted { $0.id < $1.id }
        let k = rest.isEmpty ? 0 : day % rest.count
        let shuffled = Array(rest[k...] + rest[..<k])
        return Array((starred + shuffled).prefix(8))
    }

    /// A planned trip's AI-curated edits, as Home cards.
    static func fromTrip(_ trip: Trip, _ edits: TripEdits) -> [HomeEdit] {
        edits.edits.prefix(2).map { edit in
            HomeEdit(id: "trip-\(trip.id)-\(edit.id)", caption: "\(trip.name) · \(Fmt.plural(edit.entries.count, "place"))",
                     title: edit.title, note: edit.dek, placeIds: [], cover: edit.coverCandidates.first, city: trip.city,
                     fallbacks: Array(edit.coverCandidates.dropFirst()), urls: edit.coverURLs(width: 800),
                     preview: preview(edit.entries.map(\.name)), tripId: trip.id, tripEditId: edit.id)
        }
    }
}

/// A tall photo card for an edit, as in the design's "Coming up" row: the photo, a grey caption, the title.
struct HomeEditCard: View {
    let edit: HomeEdit
    let fallback: Place?
    var width: CGFloat = 270
    var height: CGFloat = 200

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // No photo: Google's links for suggested places stop working, so edits are set in type instead.
            EditTile(caption: edit.caption, title: edit.title, preview: edit.preview, seed: edit.id)
                .frame(width: width, height: height)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .frame(width: width, alignment: .leading)
        .contentShape(Rectangle())
    }
}

/// An edit made from your saves: its title and note, then the places.
struct SavedEditView: View {
    let edit: SavedEdit
    @Environment(Store.self) private var store

    private var places: [Place] { edit.placeIds.compactMap { store.place($0) } }

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 8) {
                    Text(edit.title).font(Theme.serif(32)).foregroundStyle(Theme.label)
                    Text(edit.note).font(Theme.text(.body)).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 8)
                .listRowInsets(EdgeInsets(top: 0, leading: 20, bottom: 12, trailing: 20))
                .listRowSeparator(.hidden)
            }
            Section {
                ForEach(places) { place in
                    NavigationLink(value: Route.place(id: place.id, tripId: nil)) { PlaceRow(place: place) }
                        .listRowInsets(EdgeInsets(top: 12, leading: 20, bottom: 12, trailing: 20))
                        .listRowSeparatorTint(Theme.border)
                }
            }
        }
        .listStyle(.plain)
        .tripBackground()
        .navigationBarTitleDisplayMode(.inline)
    }
}
