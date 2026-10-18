import MapKit
import SwiftUI

struct PlaceDetailView: View {
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @Bindable var place: Place
    @State private var confirmDelete = false

    var body: some View {
        List {
            if let coordinate = place.coordinate {
                Section {
                    Map(initialPosition: .region(MKCoordinateRegion(center: coordinate, latitudinalMeters: 800, longitudinalMeters: 800)),
                        interactionModes: []) {
                        Marker(place.name, systemImage: place.category.symbol, coordinate: coordinate)
                            .tint(place.category.color)
                    }
                    .frame(height: 180)
                    .listRowInsets(EdgeInsets())
                    .onTapGesture { MapsLauncher.openInAppleMaps(place) }
                }
            }

            Section {
                VStack(alignment: .leading, spacing: 6) {
                    Label(place.category.label, systemImage: place.category.symbol)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(place.category.color)
                    Text(place.name).font(.title2.bold())
                    if let resolved = place.resolvedName {
                        Text("On maps as \(resolved)").font(.caption).foregroundStyle(.secondary)
                    }
                    if !place.locationLine.isEmpty {
                        Text(place.locationLine).foregroundStyle(.secondary)
                    }
                    if place.confidence == "low" {
                        Label("Name was hard to make out; double-check it", systemImage: "questionmark.circle")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
                if !place.summary.isEmpty { Text(place.summary) }
            }

            Section("Open in") {
                HStack {
                    mapButton("Apple Maps", systemImage: "map.fill") { MapsLauncher.openInAppleMaps(place) }
                    mapButton("Google Maps", systemImage: "globe.americas.fill") { MapsLauncher.openInGoogleMaps(place) }
                }
                .buttonStyle(.borderless)
                Menu {
                    Button("Apple Maps") { MapsLauncher.openInAppleMaps(place, directions: true) }
                    Button("Google Maps") { MapsLauncher.openInGoogleMaps(place, directions: true) }
                } label: {
                    Label("Directions", systemImage: "arrow.triangle.turn.up.right.diamond.fill")
                }
            }

            if !place.recommendedItems.isEmpty || place.tips != nil || place.priceHint != nil {
                Section("From the reel") {
                    ForEach(place.recommendedItems, id: \.self) { item in
                        Label(item, systemImage: "star.fill").symbolRenderingMode(.multicolor)
                    }
                    if let price = place.priceHint { Label(price, systemImage: "dollarsign.circle") }
                    if let tips = place.tips { Label(tips, systemImage: "lightbulb") }
                }
            }

            Section("Details") {
                if let address = place.address { LabeledContent("Address", value: address) }
                if let phone = place.phone, let url = URL(string: "tel:\(phone.filter { $0.isNumber || $0 == "+" })") {
                    Button { openURL(url) } label: { LabeledContent("Phone", value: phone) }
                }
                if let website = place.website, let url = URL(string: website) {
                    Link(destination: url) { LabeledContent("Website", value: url.host() ?? website) }
                }
                Toggle("Visited", isOn: $place.visited)
                if let trip = place.trip, trip.hasItinerary {
                    Picker("Day", selection: $place.dayNumber) {
                        Text("Not scheduled").tag(Int?.none)
                        ForEach(1...trip.dayCount, id: \.self) { Text("Day \($0)").tag(Int?.some($0)) }
                    }
                    Picker("Time", selection: $place.timeOfDayRaw) {
                        Text("Any time").tag(String?.none)
                        ForEach(TimeOfDay.allCases) { Text($0.label).tag(String?.some($0.rawValue)) }
                    }
                }
                Picker("Category", selection: $place.categoryRaw) {
                    ForEach(PlaceCategory.allCases) { Label($0.label, systemImage: $0.symbol).tag($0.rawValue) }
                }
            }

            Section("My notes") {
                TextField("Add a note", text: $place.userNotes, axis: .vertical)
            }

            if let source = place.source {
                Section("Saved from") {
                    if let url = URL(string: source.url) {
                        Link(destination: url) {
                            VStack(alignment: .leading) {
                                Text(source.title).foregroundStyle(.primary)
                                Text([source.platformName, source.creator.map { "@\($0)" }].compactMap { $0 }.joined(separator: " · "))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }

            Section {
                Button("Delete place", role: .destructive) { confirmDelete = true }
            }
        }
        .navigationTitle(place.name)
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog("Delete \(place.name)?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) {
                dismiss()
                context.delete(place)
            }
        }
    }

    private func mapButton(_ title: String, systemImage: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
        }
        .buttonStyle(.bordered)
    }
}
