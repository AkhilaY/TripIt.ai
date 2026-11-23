import SwiftUI

/// "Search your places" from the bottom bar: your saved places, cities, lists and trips as you type.
struct SearchSheet: View {
    let onOpen: (Route) -> Void
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @FocusState private var focused: Bool

    private var q: String { PlaceFilter.normalize(query) }

    private var places: [Place] {
        guard !q.isEmpty else { return Array(store.saved.sorted { $0.createdAt > $1.createdAt }.prefix(8)) }
        return Array(store.saved.filter { PlaceFilter.searchText($0).contains(q) }.prefix(40))
    }

    private var cities: [String] {
        guard !q.isEmpty else { return [] }
        let all = Set(store.saved.map(\.city).filter { !$0.isEmpty })
        return all.filter { PlaceFilter.normalize($0).contains(q) }.sorted()
    }

    private var folders: [Folder] {
        q.isEmpty ? [] : store.folders.filter { PlaceFilter.normalize($0.name).contains(q) }
    }

    private var trips: [Trip] {
        q.isEmpty ? [] : store.trips.filter { !$0.isLocal && PlaceFilter.normalize("\($0.name) \($0.city)").contains(q) }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                HStack(spacing: 12) {
                    Image(systemName: "magnifyingglass").font(.system(size: 18, weight: .light)).foregroundStyle(Theme.secondary)
                    TextField("Places, cities, lists, cuisines", text: $query)
                        .font(Theme.text(.body))
                        .focused($focused)
                        .submitLabel(.search)
                        .autocorrectionDisabled()
                    if !query.isEmpty {
                        Button { query = "" } label: {
                            Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.tertiary)
                        }
                        .accessibilityLabel("Clear")
                    }
                }
                .padding(.horizontal, 18)
                .frame(height: 52)
                .background(Theme.cell, in: Capsule())
                .padding(.horizontal, 20)
                .padding(.top, 8)

                List {
                    if !cities.isEmpty {
                        Section {
                            ForEach(cities, id: \.self) { city in row(.city(name: city), symbol: "building.2", title: city, detail: count(city)) }
                        } header: { header("Cities") }
                    }
                    if !trips.isEmpty {
                        Section {
                            ForEach(trips) { trip in row(.trip(id: trip.id), symbol: "airplane", title: trip.name, detail: Fmt.plural(trip.placeCount, "place")) }
                        } header: { header("Trips") }
                    }
                    if !folders.isEmpty {
                        Section {
                            ForEach(folders) { folder in row(.folder(id: folder.id), symbol: "folder", title: folder.name, detail: Fmt.plural(folder.placeCount, "place")) }
                        } header: { header("Lists") }
                    }
                    Section {
                        if places.isEmpty {
                            Text(q.isEmpty ? "Nothing saved yet." : "Nothing matches “\(query)”.")
                                .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
                                .listRowSeparator(.hidden)
                        }
                        ForEach(places) { place in
                            Button { open(.place(id: place.id, tripId: nil)) } label: { PlaceRow(place: place) }
                                .buttonStyle(.plain)
                                .listRowInsets(EdgeInsets(top: 10, leading: 20, bottom: 10, trailing: 20))
                                .listRowSeparatorTint(Theme.border)
                        }
                    } header: {
                        header(q.isEmpty ? "Recently saved" : "Places")
                    }
                }
                .listStyle(.plain)
                .scrollDismissesKeyboard(.immediately)
            }
            .tripBackground()
            .navigationTitle("Search")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
            }
            .onAppear { focused = true }
        }
    }

    private func count(_ city: String) -> String {
        Fmt.plural(store.saved.filter { $0.city == city }.count, "place")
    }

    private func header(_ text: String) -> some View {
        Text(text).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).textCase(nil)
    }

    private func row(_ route: Route, symbol: String, title: String, detail: String) -> some View {
        Button { open(route) } label: {
            HStack(spacing: 14) {
                SymbolTile(symbol: symbol, size: 44)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(Theme.text(.body)).foregroundStyle(Theme.label)
                    Text(detail).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                }
                Spacer(minLength: 0)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowInsets(EdgeInsets(top: 8, leading: 20, bottom: 8, trailing: 20))
        .listRowSeparatorTint(Theme.border)
    }

    private func open(_ route: Route) {
        onOpen(route)
        dismiss()
    }
}
