import MapKit
import SwiftUI

/// Places on an Apple map, coloured by kind. Tap a pin for a card that opens the place.
struct PlacesMap: View {
    let places: [Place]
    var tripId: String?
    /// Join the pins in order (a day's route).
    var route = false
    @Binding var selected: String?
    @State private var position: MapCameraPosition = .automatic

    var body: some View {
        let located = places.filter(\.isLocated)
        Map(position: $position, selection: $selected) {
            UserAnnotation()
            if route, located.count > 1 {
                MapPolyline(coordinates: located.compactMap(\.coordinate))
                    .stroke(Theme.accent.opacity(0.55), style: StrokeStyle(lineWidth: 3, lineCap: .round, dash: [6, 6]))
            }
            ForEach(Array(located.enumerated()), id: \.element.id) { index, place in
                let category = Category(place.category)
                if let coordinate = place.coordinate {
                    Marker(route ? "\(index + 1). \(place.name)" : place.name, systemImage: category.symbol, coordinate: coordinate)
                        .tint(category.color)
                        .tag(place.id)
                }
            }
        }
        .mapControls {
            MapUserLocationButton()
            MapCompass()
        }
        .onChange(of: places.map(\.id)) { _, _ in withAnimation { position = .automatic } }
        .safeAreaInset(edge: .bottom) {
            if let id = selected, let place = places.first(where: { $0.id == id }) {
                NavigationLink(value: Route.place(id: place.id, tripId: tripId)) {
                    HStack(spacing: 12) {
                        PlaceRow(place: place)
                        Image(systemName: "chevron.right").foregroundStyle(Theme.tertiary)
                    }
                    .padding(12)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                    .padding(.horizontal, 12).padding(.bottom, 8)
                }
                .buttonStyle(.plain)
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.spring(duration: 0.3), value: selected)
    }
}

/// Trip → Map, with a chip for each day.
struct TripMapView: View {
    let trip: TripDetail
    @State private var day = 0
    @State private var selected: String?

    var body: some View {
        let shown = day == 0 ? trip.places : trip.stops(on: day)
        let missing = shown.filter { !$0.isLocated }.count
        PlacesMap(places: shown, tripId: trip.id, route: day > 0, selected: $selected)
            .safeAreaInset(edge: .top) {
                VStack(spacing: 6) {
                    if trip.dayCount > 0 {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 8) {
                                ForEach(0...trip.dayCount, id: \.self) { d in
                                    FilterChip(label: d == 0 ? "All" : "Day \(d)", isOn: d == day) { day = d; selected = nil }
                                }
                            }
                            .padding(.horizontal, 12)
                        }
                    }
                    if missing > 0 {
                        Text("\(Fmt.plural(missing, "place")) not on the map yet")
                            .font(.caption.weight(.medium))
                            .padding(.horizontal, 10).padding(.vertical, 5)
                            .background(.regularMaterial, in: Capsule())
                    }
                }
                .padding(.vertical, 6)
            }
    }
}

/// Your saved places on a map, filtered by kind (the Map button in the Library).
struct MapTab: View {
    @Environment(Store.self) private var store
    @State private var groups = Set<PlaceGroup>()
    @State private var starred = false
    @State private var selected: String?

    var body: some View {
        let shown = store.places.filter { (groups.isEmpty || groups.contains(PlaceGroup.of($0.category))) && (!starred || $0.mustDo) }
        let counts = Dictionary(grouping: store.places, by: { PlaceGroup.of($0.category) }).mapValues(\.count)
        PlacesMap(places: shown, selected: $selected)
            .safeAreaInset(edge: .top) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        FilterChip(label: "Starred", symbol: "star.fill", isOn: starred) { starred.toggle() }
                        ForEach(PlaceGroup.allCases.filter { counts[$0] != nil }) { group in
                            FilterChip(label: group.label, count: counts[group], isOn: groups.contains(group)) {
                                if groups.contains(group) { groups.remove(group) } else { groups.insert(group) }
                                selected = nil
                            }
                        }
                    }
                    .padding(.horizontal, 12).padding(.vertical, 6)
                }
            }
            .navigationTitle("Map")
            .navigationBarTitleDisplayMode(.inline)
            .onAppear { Location.shared.request() }
    }
}
