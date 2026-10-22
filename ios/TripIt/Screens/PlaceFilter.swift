import CoreLocation
import SwiftUI

/// Search, type chips (any number), cities, starred and "not in a trip": the Saved list's filters.
struct PlaceFilter: Equatable {
    var query = ""
    var groups = Set<PlaceGroup>()
    var cities = Set<String>()
    var starred = false
    var unplanned = false

    var isActive: Bool { !query.isEmpty || !groups.isEmpty || !cities.isEmpty || starred || unplanned }
    var moreCount: Int { cities.count + (unplanned ? 1 : 0) }

    func apply(_ places: [Place]) -> [Place] {
        let q = Self.normalize(query)
        return places.filter { p in
            (groups.isEmpty || groups.contains(PlaceGroup.of(p.category)))
                && (cities.isEmpty || cities.contains(p.city.isEmpty ? "Somewhere" : p.city))
                && (!starred || p.mustDo)
                && (!unplanned || p.tripIds.isEmpty)
                && (q.isEmpty || Self.normalize("\(p.name) \(p.neighborhood ?? "") \(p.city) \(p.venue ?? "")").contains(q))
        }
    }

    static func normalize(_ s: String) -> String {
        s.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil).trimmingCharacters(in: .whitespaces)
    }
}

enum PlaceSort: String, CaseIterable, Identifiable {
    case popular, name, closest, rating, recent
    var id: String { rawValue }

    var label: String {
        switch self {
        case .popular: "Most popular"
        case .name: "A to Z"
        case .closest: "Closest to me"
        case .rating: "Highest rated"
        case .recent: "Recently saved"
        }
    }

    /// Starred places always come first; the chosen order sorts each half.
    func sorted(_ places: [Place], from location: CLLocation?) -> [Place] {
        places.sorted { a, b in
            if a.mustDo != b.mustDo { return a.mustDo }
            switch self {
            case .popular:
                if a.mentionCount != b.mentionCount { return a.mentionCount > b.mentionCount }
                if (a.rating ?? 0) != (b.rating ?? 0) { return (a.rating ?? 0) > (b.rating ?? 0) }
            case .name: break
            case .closest:
                let da = a.distance(from: location) ?? .infinity, db = b.distance(from: location) ?? .infinity
                if da != db { return da < db }
            case .rating:
                if (a.rating ?? 0) != (b.rating ?? 0) { return (a.rating ?? 0) > (b.rating ?? 0) }
                if (a.ratingCount ?? 0) != (b.ratingCount ?? 0) { return (a.ratingCount ?? 0) > (b.ratingCount ?? 0) }
            case .recent:
                if a.createdAt != b.createdAt { return a.createdAt > b.createdAt }
            }
            return a.name.localizedCaseInsensitiveCompare(b.name) == .orderedAscending
        }
    }
}

/// The chips and menus above a list of saved places.
struct PlaceFilterBar: View {
    let places: [Place]
    @Binding var filter: PlaceFilter
    @Binding var sort: PlaceSort
    var showSort = true

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                if showSort { sortMenu }
                FilterChip(label: "Starred", symbol: "star.fill", isOn: filter.starred) { filter.starred.toggle() }
                groupChips
                moreMenu
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 2)
        }
    }

    private var groupCounts: [PlaceGroup: Int] {
        Dictionary(grouping: places, by: { PlaceGroup.of($0.category) }).mapValues(\.count)
    }

    private var cityCounts: [CityCount] {
        let counts = Dictionary(grouping: places, by: { $0.city.isEmpty ? "Somewhere" : $0.city }).mapValues(\.count)
        return counts.map { CityCount(city: $0.key, count: $0.value) }
            .sorted { $0.count != $1.count ? $0.count > $1.count : $0.city < $1.city }
    }

    private var sortMenu: some View {
        Menu {
            Picker("Sort", selection: $sort) {
                ForEach(PlaceSort.allCases) { option in
                    Text(option.label).tag(option)
                }
            }
        } label: {
            Label(sort.label, systemImage: "arrow.up.arrow.down")
                .font(.subheadline.weight(.medium))
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(Theme.cell, in: Capsule())
                .overlay(Capsule().strokeBorder(Theme.fill, lineWidth: 1))
        }
        .onChange(of: sort) { _, value in
            if value == .closest { Location.shared.request() }
        }
    }

    private var groupChips: some View {
        let counts = groupCounts
        let shown: [PlaceGroup] = PlaceGroup.allCases.filter { counts[$0] != nil }
        return ForEach(shown) { group in
            FilterChip(label: group.label, count: counts[group], isOn: filter.groups.contains(group)) {
                toggle(group)
            }
        }
    }

    private func toggle(_ group: PlaceGroup) {
        if filter.groups.contains(group) { filter.groups.remove(group) } else { filter.groups.insert(group) }
    }

    private func cityBinding(_ city: String) -> Binding<Bool> {
        Binding(
            get: { filter.cities.contains(city) },
            set: { on in
                if on { filter.cities.insert(city) } else { filter.cities.remove(city) }
            })
    }

    private var moreMenu: some View {
        let cities = cityCounts
        let label = filter.moreCount > 0 ? "Filters · \(filter.moreCount)" : "More filters"
        return Menu {
            Toggle("Not in a trip yet", isOn: $filter.unplanned)
            if cities.count > 1 {
                Section("Cities") {
                    ForEach(cities) { item in
                        Toggle("\(item.city) (\(item.count))", isOn: cityBinding(item.city))
                    }
                }
            }
            if filter.isActive {
                Button("Clear filters", role: .destructive) { filter = PlaceFilter(query: filter.query) }
            }
        } label: {
            FilterChipLabel(text: label, isOn: filter.moreCount > 0)
        }
    }
}

private struct CityCount: Identifiable {
    let city: String
    let count: Int
    var id: String { city }
}

private struct FilterChipLabel: View {
    let text: String
    let isOn: Bool
    var body: some View {
        HStack(spacing: 4) {
            Text(text).font(.subheadline.weight(.medium))
            Image(systemName: "chevron.down").font(.caption2.weight(.bold))
        }
        .padding(.horizontal, 12).padding(.vertical, 7)
        .foregroundStyle(isOn ? Theme.accentInk : Theme.label)
        .background(isOn ? Theme.accent : Theme.cell, in: Capsule())
        .overlay(Capsule().strokeBorder(Theme.fill, lineWidth: isOn ? 0 : 1))
    }
}
