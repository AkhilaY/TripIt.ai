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
                HStack(spacing: 10) {
                    Image(systemName: "magnifyingglass").font(.system(size: 15, weight: .light)).foregroundStyle(Theme.secondary)
                    TextField("Search your places", text: $query)
                        .font(Theme.text(.body))
                        .focused($focused)
                        .submitLabel(.search)
                        .autocorrectionDisabled()
                    if !query.isEmpty {
                        Button { query = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.tertiary) }
                            .accessibilityLabel("Clear")
                    }
                }
                .padding(.horizontal, 16)
                .frame(height: 46)
                .background(Theme.cell, in: Capsule())
                .padding(.horizontal, 20)
                .padding(.top, 4)

                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        if q.isEmpty && !places.isEmpty {
                            Text("Recent").font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).padding(.bottom, 4)
                        }
                        ForEach(cities, id: \.self) { city in
                            row(.city(name: city), title: city, detail: count(city)) { CityScene(city: city) }
                        }
                        ForEach(trips) { trip in
                            row(.trip(id: trip.id), title: trip.name, detail: trip.dateRange ?? Fmt.plural(trip.placeCount, "place")) {
                                TripCover(trip: trip, size: 48)
                            }
                        }
                        ForEach(folders) { folder in
                            row(.folder(id: folder.id), title: folder.name, detail: Fmt.plural(folder.placeCount, "place")) {
                                RemoteImage(url: folder.covers.first?.url(width: 150)) { Theme.cell }
                            }
                        }
                        ForEach(places) { place in
                            Button { open(.place(id: place.id, tripId: nil)) } label: {
                                PlaceRow(place: place).padding(.vertical, 10)
                            }
                            .buttonStyle(PressStyle())
                            Divider().overlay(Theme.border)
                        }
                        if !q.isEmpty && places.isEmpty && cities.isEmpty && trips.isEmpty && folders.isEmpty {
                            Text("Nothing matches “\(query)”").font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary).padding(.top, 24)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 16)
                    .animation(.snappy, value: query)
                }
                .scrollDismissesKeyboard(.immediately)
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button { dismiss() } label: { Image(systemName: "xmark").font(.system(size: 14, weight: .light)) }
                        .accessibilityLabel("Close")
                }
            }
            .onAppear { focused = true }
        }
    }

    private func count(_ city: String) -> String {
        Fmt.plural(store.saved.filter { $0.city == city }.count, "place")
    }

    private func row<Thumb: View>(_ route: Route, title: String, detail: String, @ViewBuilder thumb: () -> Thumb) -> some View {
        VStack(spacing: 0) {
            Button { open(route) } label: {
                HStack(spacing: 14) {
                    thumb().frame(width: 48, height: 48).clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(title).font(Theme.text(.body)).foregroundStyle(Theme.label).lineLimit(1)
                        Text(detail).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).lineLimit(1)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.vertical, 10)
                .contentShape(Rectangle())
            }
            .buttonStyle(PressStyle())
            Divider().overlay(Theme.border)
        }
    }

    private func open(_ route: Route) {
        onOpen(route)
        dismiss()
    }
}
