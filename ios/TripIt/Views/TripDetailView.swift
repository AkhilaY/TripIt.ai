import SwiftUI

struct TripDetailView: View {
    @Bindable var trip: Trip

    enum Mode: String, CaseIterable, Identifiable {
        case places = "Places", itinerary = "Itinerary", map = "Map"
        var id: String { rawValue }
    }

    @State private var mode: Mode = .places
    @State private var showingPlanner = false
    @State private var renaming = false
    @State private var newName = ""

    var body: some View {
        VStack(spacing: 0) {
            Picker("View", selection: $mode) {
                ForEach(Mode.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal)
            .padding(.bottom, 8)

            switch mode {
            case .places: PlacesListView(trip: trip)
            case .itinerary: ItineraryView(trip: trip, showingPlanner: $showingPlanner)
            case .map: TripMapView(trip: trip)
            }
        }
        .navigationTitle(trip.name)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                ShareLink(item: MapsLauncher.shareText(for: trip)) { Image(systemName: "square.and.arrow.up") }
                Menu {
                    Button { showingPlanner = true } label: {
                        Label(trip.hasItinerary ? "Re-plan trip" : "Plan my trip", systemImage: "calendar.badge.plus")
                    }
                    if trip.hasItinerary {
                        Button(role: .destructive) { trip.clearItinerary() } label: {
                            Label("Clear itinerary", systemImage: "calendar.badge.minus")
                        }
                    }
                    Button {
                        newName = trip.name
                        renaming = true
                    } label: { Label("Rename", systemImage: "pencil") }
                } label: { Image(systemName: "ellipsis.circle") }
            }
        }
        .sheet(isPresented: $showingPlanner) {
            PlanTripSheet(trip: trip) { mode = .itinerary }
        }
        .alert("Rename trip", isPresented: $renaming) {
            TextField("Name", text: $newName)
            Button("Save") { if !newName.isEmpty { trip.name = newName } }
            Button("Cancel", role: .cancel) {}
        }
    }
}

struct PlacesListView: View {
    @Environment(\.modelContext) private var context
    let trip: Trip

    var body: some View {
        let grouped = Dictionary(grouping: trip.allPlaces, by: \.category)
        List {
            ForEach(PlaceCategory.allCases.filter { grouped[$0] != nil }) { category in
                Section {
                    ForEach(grouped[category] ?? []) { place in
                        NavigationLink { PlaceDetailView(place: place) } label: { PlaceRow(place: place) }
                            .swipeActions(edge: .leading) {
                                Button { place.visited.toggle() } label: {
                                    Label(place.visited ? "Not visited" : "Visited", systemImage: "checkmark.circle")
                                }
                                .tint(.green)
                            }
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) { context.delete(place) } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                            }
                    }
                } header: {
                    Label(category.label, systemImage: category.symbol).foregroundStyle(category.color)
                }
            }
        }
        .overlay {
            if trip.allPlaces.isEmpty {
                ContentUnavailableView("No places", systemImage: "mappin.slash")
            }
        }
    }
}

struct PlaceRow: View {
    let place: Place

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: place.category.symbol)
                .foregroundStyle(.white)
                .frame(width: 32, height: 32)
                .background(place.category.color.gradient, in: Circle())
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text(place.name).font(.body.weight(.medium)).strikethrough(place.visited)
                    if place.coordinate == nil {
                        Image(systemName: "mappin.slash").font(.caption).foregroundStyle(.orange)
                    }
                }
                if !place.locationLine.isEmpty {
                    Text(place.locationLine).font(.caption).foregroundStyle(.secondary)
                }
                if !place.recommendedItems.isEmpty {
                    Text("Try: " + place.recommendedItems.joined(separator: ", "))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        }
    }
}
