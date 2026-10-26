import SwiftUI

/// A searchable list of saved places with checkmarks.
struct PlaceChecklist: View {
    let places: [Place]
    @Binding var picked: Set<String>
    /// Owned by the screen, which puts its search text in the navigation bar.
    @Binding var filter: PlaceFilter
    @Environment(Store.self) private var store
    @State private var sort: PlaceSort = .popular
    @State private var scope: Scope = .everything

    /// Which saved places to choose from: all of them, one city's, or one folder's.
    private enum Scope: Hashable {
        case everything
        case city(String)
        case folder(String)
    }

    private struct CityCount: Identifiable {
        let city: String
        let count: Int
        var id: String { city }
    }

    /// Cities among these places, most places first.
    private var cities: [CityCount] {
        Dictionary(grouping: places.filter { !$0.city.isEmpty }, by: \.city).map { CityCount(city: $0.key, count: $0.value.count) }
            .sorted { $0.count != $1.count ? $0.count > $1.count : $0.city < $1.city }
    }

    private var scopeLabel: String {
        switch scope {
        case .everything: "Everything saved"
        case .city(let city): city
        case .folder(let id): store.folders.first { $0.id == id }?.name ?? "Everything saved"
        }
    }

    private var scopeSymbol: String {
        switch scope {
        case .everything: "tray.full"
        case .city: "building.2"
        case .folder: "folder"
        }
    }

    var body: some View {
        let inFolder: [Place] = switch scope {
        case .everything: places
        case .city(let city): places.filter { $0.city == city }
        case .folder(let id): places.filter { $0.folderIds.contains(id) }
        }
        let shown = sort.sorted(filter.apply(inFolder), from: nil)
        Section {
            PlaceFilterBar(places: inFolder, filter: $filter, sort: $sort, showSort: false)
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
        } header: {
            HStack {
                Menu {
                    Picker("Show", selection: $scope) {
                        Label("Everything saved", systemImage: "tray.full").tag(Scope.everything)
                    }
                    if cities.count > 1 {
                        Picker("Cities", selection: $scope) {
                            ForEach(cities) { Text("\($0.city) (\($0.count))").tag(Scope.city($0.city)) }
                        }
                    }
                    if !store.folders.isEmpty {
                        Picker("Folders", selection: $scope) {
                            ForEach(store.folders) { Text($0.name).tag(Scope.folder($0.id)) }
                        }
                    }
                } label: {
                    HStack(spacing: 5) {
                        Label(scopeLabel, systemImage: scopeSymbol)
                        Image(systemName: "chevron.up.chevron.down").font(.caption2.weight(.bold))
                    }
                    .font(.subheadline.weight(.semibold))
                }
                .textCase(nil)
                .onChange(of: scope) { _, _ in filter.cities = [] }
                Spacer()
                let allPicked = !shown.isEmpty && shown.allSatisfy { picked.contains($0.id) }
                Button(allPicked ? "Untick all" : "Tick all") {
                    if allPicked { shown.forEach { picked.remove($0.id) } } else { shown.forEach { picked.insert($0.id) } }
                }
                .font(.subheadline.weight(.semibold))
                .textCase(nil)
                .disabled(shown.isEmpty)
            }
        }
        Section {
            if shown.isEmpty {
                Text(places.isEmpty ? "Nothing saved yet." : "Nothing matches.").foregroundStyle(Theme.secondary)
            }
            ForEach(shown) { place in
                Button {
                    if picked.contains(place.id) { picked.remove(place.id) } else { picked.insert(place.id) }
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: picked.contains(place.id) ? "checkmark.circle.fill" : "circle")
                            .font(.title3)
                            .foregroundStyle(picked.contains(place.id) ? Theme.accent : Theme.tertiary)
                        PlaceRow(place: place)
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }
}

/// Pick saved places to add somewhere (a folder, a trip, a day).
struct PlacePickerSheet: View {
    let title: String
    let exclude: Set<String>
    let confirm: String
    let onDone: ([String]) async -> Void
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var picked = Set<String>()
    @State private var filter = PlaceFilter()
    @State private var busy = false

    var body: some View {
        NavigationStack {
            List {
                PlaceChecklist(places: store.places.filter { !exclude.contains($0.id) }, picked: $picked, filter: $filter)
            }
            .searchable(text: $filter.query, prompt: "Search your saved places")
            .tripBackground()
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else {
                        Button(picked.isEmpty ? confirm : "\(confirm) (\(picked.count))") {
                            busy = true
                            Task { await onDone(Array(picked)); dismiss() }
                        }
                        .disabled(picked.isEmpty)
                    }
                }
            }
        }
    }
}

/// File places in folders. For one place, tick its folders; for several, choose where they all go.
struct FolderPickerSheet: View {
    let placeIds: [String]
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var naming = false
    @State private var name = ""

    var body: some View {
        let single = placeIds.count == 1 ? store.place(placeIds[0]) : nil
        NavigationStack {
            List {
                Section {
                    Button { name = ""; naming = true } label: { Label("New folder", systemImage: "folder.badge.plus") }
                }
                Section {
                    ForEach(store.folders) { folder in
                        let inside = single?.folderIds.contains(folder.id) ?? false
                        Button {
                            Task {
                                if inside { await store.removeFromFolder(folder.id, placeIds[0]) }
                                else {
                                    await store.addToFolder(folder.id, placeIds)
                                    store.show("Saved to \(folder.name)")
                                    if single == nil { dismiss() }
                                }
                            }
                        } label: {
                            HStack {
                                SymbolTile(symbol: "folder.fill", color: Theme.gold)
                                VStack(alignment: .leading) {
                                    Text(folder.name).foregroundStyle(Theme.label)
                                    Text(Fmt.plural(folder.placeCount, "place")).font(.caption).foregroundStyle(Theme.secondary)
                                }
                                Spacer()
                                if inside { Image(systemName: "checkmark").foregroundStyle(Theme.link).fontWeight(.semibold) }
                            }
                        }
                    }
                } footer: {
                    Text(single != nil ? "A place can be in as many folders as you like." : "Adds \(Fmt.plural(placeIds.count, "place")) to the folder you choose.")
                }
            }
            .tripBackground()
            .navigationTitle(single.map { "Folders for \($0.name)" } ?? "Add to a folder")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .alert("New folder", isPresented: $naming) {
                TextField("e.g. Date night", text: $name)
                Button("Cancel", role: .cancel) {}
                Button("Create") {
                    let clean = name.trimmingCharacters(in: .whitespaces)
                    guard !clean.isEmpty else { return }
                    Task {
                        if await store.createFolder(clean, placeIds: placeIds) != nil {
                            store.show("Saved to \(clean)")
                            dismiss()
                        }
                    }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

/// Add places to a trip (or, for one place, see and change which trips it's on).
struct TripPickerSheet: View {
    let placeIds: [String]
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var newTrip = false

    var body: some View {
        let single = placeIds.count == 1 ? store.place(placeIds[0]) : nil
        NavigationStack {
            List {
                Section {
                    Button { newTrip = true } label: { Label("New trip", systemImage: "airplane") }
                }
                Section {
                    if store.trips.isEmpty { Text("No trips yet.").foregroundStyle(Theme.secondary) }
                    ForEach(store.trips) { trip in
                        let inside = single?.tripIds.contains(trip.id) ?? false
                        Button {
                            Task {
                                if inside { await store.removeFromTrip(trip.id, placeIds[0]) }
                                else {
                                    await store.addToTrip(trip.id, placeIds)
                                    store.show("Added to \(trip.name)")
                                    if single == nil { dismiss() }
                                }
                            }
                        } label: {
                            HStack {
                                SymbolTile(symbol: trip.isLocal ? "house.fill" : "airplane", color: Theme.blue)
                                VStack(alignment: .leading) {
                                    Text(trip.name).foregroundStyle(Theme.label)
                                    Text([trip.city, Fmt.plural(trip.placeCount, "place")].joined(separator: " · "))
                                        .font(.caption).foregroundStyle(Theme.secondary)
                                }
                                Spacer()
                                if inside { Image(systemName: "checkmark").foregroundStyle(Theme.link).fontWeight(.semibold) }
                            }
                        }
                    }
                } footer: {
                    Text("Places join a trip unscheduled. Put them on a day from the trip's Plan.")
                }
            }
            .tripBackground()
            .navigationTitle(single.map { "Trips for \($0.name)" } ?? "Add to a trip")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .sheet(isPresented: $newTrip) { NewTripSheet(placeIds: placeIds, folderId: nil) }
        }
        .presentationDetents([.medium, .large])
    }
}
