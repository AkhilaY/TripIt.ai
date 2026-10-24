import SwiftUI

/// Everything you've saved in one city. Your home city is "Around <city>"; elsewhere it's that city's
/// wishlist, with its trip if you have one.
struct CityView: View {
    let city: String
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @AppStorage("library.visit") private var visit: VisitFilter = .all
    @AppStorage("library.sort") private var sort: PlaceSort = .popular
    @State private var filter = PlaceFilter()
    @State private var location = Location.shared
    @State private var sheet: LibrarySheet?
    @State private var deleting: Place?

    private var isHome: Bool { store.homeKey == Store.cityKey(city) }

    var body: some View {
        let all = store.places(inCity: city)
        let places = sort.sorted(filter.apply(visit.apply(all)), from: location.current)
        let trip = isHome ? nil : store.trip(forCity: city)
        List {
            Section {
                VStack(alignment: .leading, spacing: 4) {
                    if isHome { Eyebrow(text: "Your city") }
                    Text(isHome ? "Around \(city)" : city).font(Theme.serif(28)).foregroundStyle(Theme.label)
                    Text(subtitle(all, trip: trip)).font(.subheadline).foregroundStyle(Theme.secondary)
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets(top: 4, leading: 20, bottom: 8, trailing: 20))
                if let trip {
                    NavigationLink(value: Route.trip(id: trip.id)) { TripRow(trip: trip) }
                        .buttonStyle(.plain)
                        .listRowBackground(Color.clear)
                        .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 16))
                } else if !isHome, !all.isEmpty {
                    Button { sheet = .newTrip(all.map(\.id), nil) } label: {
                        Label("Plan a trip to \(city)", systemImage: "airplane")
                    }
                    .buttonStyle(PrimaryButtonStyle())
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 16))
                }
                VisitPicker(visit: $visit, places: all)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 0, trailing: 16))
                PlaceFilterBar(places: all, filter: $filter, sort: $sort)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
            }
            .listSectionSeparator(.hidden)
            Section {
                if places.isEmpty {
                    EmptyState(symbol: "mappin.slash", title: all.isEmpty ? "Nothing here yet" : "Nothing matches",
                               text: all.isEmpty ? "Places you save in \(city) land here automatically." : "Try fewer filters.")
                        .listRowBackground(Color.clear)
                }
                ForEach(places) { place in
                    NavigationLink(value: Route.place(id: place.id, tripId: nil)) {
                        PlaceRow(place: place, showCategory: true, distance: sort == .closest ? place.distance(from: location.current) : nil)
                    }
                    .placeActions(place, onDelete: { deleting = place }, sheet: $sheet)
                    .listRowBackground(Theme.cell)
                }
            }
        }
        .listStyle(.insetGrouped)
        .tripBackground()
        .searchable(text: $filter.query, prompt: "Search \(isHome ? "around \(city)" : city)")
        .navigationTitle(isHome ? "Around \(city)" : city)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            Button { router.push(.map) } label: { Image(systemName: "map") }.accessibilityLabel("Map")
        }
        .sheet(item: $sheet) { $0.view.environment(store).environment(router) }
        .confirmationDialog("Delete this place everywhere? It leaves your Library, lists and trips.",
                            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button("Delete place", role: .destructive) { if let place = deleting { Task { await store.delete(place) } } }
        }
    }

    private func subtitle(_ all: [Place], trip: Trip?) -> String {
        let open = all.filter { Hours.status($0.openingHours)?.isOpen == true }.count
        var parts = [Fmt.plural(all.count, "place")]
        if isHome {
            if open > 0 { parts.append("\(open) open now") }
            parts.append("sorted by neighbourhood")
        } else if let trip {
            parts.append(trip.dateRange.map { "trip \($0)" } ?? "on \(trip.name)")
        } else {
            parts.append("your wishlist, no trip yet")
        }
        return parts.joined(separator: " · ")
    }
}
