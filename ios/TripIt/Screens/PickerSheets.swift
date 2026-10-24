import SwiftUI

/// A searchable list of saved places with checkmarks.
struct PlaceChecklist: View {
    let places: [Place]
    @Binding var picked: Set<String>
    /// Owned by the screen, which puts its search text in the navigation bar.
    @Binding var filter: PlaceFilter
    @Environment(Store.self) private var store
    @State private var sort: PlaceSort = .popular
    @State private var folderId: String?

    var body: some View {
        let inFolder = folderId.map { id in places.filter { $0.folderIds.contains(id) } } ?? places
        let shown = sort.sorted(filter.apply(inFolder), from: nil)
        Section {
            PlaceFilterBar(places: inFolder, filter: $filter, sort: $sort, showSort: false)
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
        } header: {
            HStack {
                if !store.folders.isEmpty {
                    Menu {
                        Picker("Folder", selection: $folderId) {
                            Text("Everything saved").tag(String?.none)
                            ForEach(store.folders) { Text($0.name).tag(String?.some($0.id)) }
                        }
                    } label: {
                        Label(store.folders.first { $0.id == folderId }?.name ?? "Everything saved", systemImage: "folder")
                            .font(.subheadline.weight(.semibold))
                    }
                    .textCase(nil)
                }
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
