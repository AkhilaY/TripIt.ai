import MapKit
import SwiftData
import SwiftUI

/// Map of a set of places with category-colored pins. Tap a pin for details.
struct PlacesMap: View {
    let places: [Place]
    var route: [Place] = []

    @State private var selectedID: UUID?
    @State private var position: MapCameraPosition = .automatic

    var body: some View {
        Map(position: $position, selection: $selectedID) {
            ForEach(places.filter { $0.coordinate != nil }) { place in
                Marker(place.name, systemImage: place.category.symbol, coordinate: place.coordinate!)
                    .tint(place.category.color)
                    .tag(place.id)
            }
            let routeCoordinates = route.compactMap(\.coordinate)
            if routeCoordinates.count > 1 {
                MapPolyline(coordinates: routeCoordinates)
                    .stroke(.tint, style: StrokeStyle(lineWidth: 3, dash: [6, 4]))
            }
            UserAnnotation()
        }
        .mapControls {
            MapUserLocationButton()
            MapCompass()
            MapPitchToggle()
        }
        .onChange(of: places.map(\.id)) { _, _ in
            withAnimation { position = .automatic }
        }
        .sheet(item: selectedPlaceBinding) { place in
            NavigationStack { PlaceDetailView(place: place) }
                .presentationDetents([.medium, .large])
        }
        .overlay(alignment: .bottom) {
            let missing = places.filter { $0.coordinate == nil }.count
            if missing > 0 {
                Text("\(missing) place\(missing == 1 ? "" : "s") couldn't be found on the map")
                    .font(.caption)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(.regularMaterial, in: Capsule())
                    .padding(.bottom, 8)
            }
        }
    }

    private var selectedPlaceBinding: Binding<Place?> {
        Binding(
            get: { places.first { $0.id == selectedID } },
            set: { selectedID = $0?.id }
        )
    }
}

struct TripMapView: View {
    let trip: Trip
    @State private var day: Int?  // nil = all places

    var body: some View {
        let places = day.map { trip.stops(onDay: $0) } ?? trip.allPlaces
        PlacesMap(places: places, route: day == nil ? [] : places)
            .safeAreaInset(edge: .top) {
                if trip.hasItinerary {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack {
                            chip("All", selected: day == nil) { day = nil }
                            ForEach(1...trip.dayCount, id: \.self) { d in
                                chip("Day \(d)", selected: day == d) { day = d }
                            }
                        }
                        .padding(.horizontal)
                    }
                    .padding(.vertical, 6)
                    .background(.bar)
                }
            }
    }

    private func chip(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(title, action: action)
            .font(.subheadline.weight(.medium))
            .buttonStyle(.bordered)
            .tint(selected ? Color.accentColor : Color.secondary)
    }
}

/// Every saved place across all trips.
struct AllPlacesMapView: View {
    @Query private var places: [Place]
    @State private var category: PlaceCategory?

    var body: some View {
        NavigationStack {
            PlacesMap(places: category.map { c in places.filter { $0.category == c } } ?? places)
                .navigationTitle("All places")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    Menu {
                        Picker("Category", selection: $category) {
                            Text("All categories").tag(PlaceCategory?.none)
                            ForEach(PlaceCategory.allCases) { c in
                                Label(c.label, systemImage: c.symbol).tag(PlaceCategory?.some(c))
                            }
                        }
                    } label: {
                        Image(systemName: category == nil
                              ? "line.3.horizontal.decrease.circle"
                              : "line.3.horizontal.decrease.circle.fill")
                    }
                }
        }
    }
}
