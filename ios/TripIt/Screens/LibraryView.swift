import SwiftUI

/// Want to go / Been: filters the whole Library.
enum VisitFilter: String, CaseIterable, Identifiable {
    case all, want, been
    var id: String { rawValue }
    var label: String { self == .all ? "All" : self == .want ? "Want to go" : "Been" }
    func apply(_ places: [Place]) -> [Place] {
        switch self {
        case .all: places
        case .want: places.filter { !$0.visited }
        case .been: places.filter(\.visited)
        }
    }
}

/// The Library tab: your home city, trips as routes, every other city sorted automatically, and your own lists.
struct LibraryView: View {
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @AppStorage("library.visit") private var visit: VisitFilter = .all
    @AppStorage("library.cityLayout") private var cityLayout: CityLayout = .cards
    @AppStorage("library.citySort") private var citySort: CitySort = .places
    @AppStorage("library.section") private var section: LibrarySection = .places
    @State private var cityFilter: String?
    @State private var groupFilter: PlaceGroup?
    @State private var postFilter = "all"
    @State private var query = ""
    @State private var sheet: LibrarySheet?
    @State private var newFolder = false
    @State private var folderName = ""
    @State private var deleting: Place?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                header
                if !store.loaded, let error = store.error {
                    EmptyState(symbol: "wifi.slash", title: "Can't load your library", text: error) {
                        Button("Try again") { Task { await store.refresh() } }.buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 200)
                    }
                } else if !store.loaded {
                    SkeletonRows().padding(.top, 20)
                } else if !query.trimmingCharacters(in: .whitespaces).isEmpty {
                    searchResults
                } else if store.saved.isEmpty && store.realTrips.isEmpty {
                    EmptyState(symbol: "bookmark", title: "Nothing saved yet",
                               text: "Share a TikTok or Instagram post to The Travel Edit, paste a link, or search for a place. Places file themselves by city.") {
                        Button { router.addRequest = Router.AddRequest() } label: { Label("Save a place", systemImage: "plus") }
                            .buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 220)
                    }
                    .padding(.top, 24)
                } else {
                    ForEach(store.jobs.filter(\.isActive)) { job in
                        ImportProgressCard(job: job).padding(.top, 14)
                    }
                    sectionPicker.padding(.top, 16)
                    switch section {
                    case .places: placesSection
                    case .lists: listsSection
                    case .posts: postsSection
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 40)
        }
        .background(Theme.background.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .animation(.snappy, value: store.saved.map(\.id))
        .refreshable { await store.refresh() }
        .sheet(item: $sheet) { sheet in sheet.view.environment(store).environment(router) }
        .alert("New list", isPresented: $newFolder) {
            TextField("e.g. Date night", text: $folderName)
            Button("Cancel", role: .cancel) {}
            Button("Create") {
                let name = folderName.trimmingCharacters(in: .whitespaces)
                guard !name.isEmpty else { return }
                Task { if let folder = await store.createFolder(name) { router.push(.folder(id: folder.id)) } }
            }
        }
        .confirmationDialog("Delete this place everywhere? It leaves your Library, lists and trips.",
                            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button("Delete place", role: .destructive) {
                if let place = deleting { Task { await store.delete(place) } }
            }
        }
    }

    private var shown: [Place] { visit.apply(store.saved) }

    // MARK: Header, search and filter

    private var header: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center) {
                Text("Library").font(Theme.serif(38)).foregroundStyle(Theme.label)
                Spacer()
                Text(Fmt.plural(store.saved.count, "place")).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                ProfileButton()
            }
            .padding(.top, 12)
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass").foregroundStyle(Theme.tertiary)
                TextField("Places, cities, lists", text: $query)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.search)
                if !query.isEmpty {
                    Button { query = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.quiet) }
                        .accessibilityLabel("Clear search")
                }
            }
            .font(Theme.text(.body))
            .padding(.horizontal, 18).frame(height: 48)
            .background(Theme.cell, in: Capsule())
            .padding(.top, 18)
        }
    }

    // MARK: Search

    @ViewBuilder private var searchResults: some View {
        let q = PlaceFilter.normalize(query)
        let places = shown.filter { PlaceFilter.searchText($0).contains(q) }
        let folders = store.folders.filter { PlaceFilter.normalize($0.name).contains(q) }
        let cityHits = store.cityGroups(shown).filter { PlaceFilter.normalize($0.name).contains(q) }
        if places.isEmpty && folders.isEmpty && cityHits.isEmpty {
            EmptyState(symbol: "magnifyingglass", title: "Nothing matches", text: "Nothing in your Library matches “\(query)”.")
        }
        if !cityHits.isEmpty || !folders.isEmpty {
            SectionHeading("Cities and lists", size: 20).padding(.top, 20)
            ForEach(cityHits) { city in
                NavigationLink(value: Route.city(name: city.name)) {
                    ListRow(title: city.name, subtitle: Fmt.plural(city.places.count, "place"), photo: city.places.first?.photos.first, symbol: "building.2")
                }.buttonStyle(PressStyle())
            }
            ForEach(folders) { folder in
                NavigationLink(value: Route.folder(id: folder.id)) {
                    ListRow(title: folder.name, subtitle: Fmt.plural(folder.placeCount, "place"), photo: folder.covers.first, symbol: "list.bullet")
                }.buttonStyle(PressStyle())
            }
        }
        if !places.isEmpty {
            SectionHeading(Fmt.plural(places.count, "place"), size: 20).padding(.top, 20)
            ForEach(places) { place in
                NavigationLink(value: Route.place(id: place.id, tripId: nil)) {
                    PlaceRow(place: place).padding(.vertical, 6)
                }
                .buttonStyle(PressStyle())
                .placeActions(place, onDelete: { Task { await store.deleteWithUndo(place) } }, sheet: $sheet)
                Divider().overlay(Theme.divider)
            }
        }
    }

    // MARK: Places, Lists, Posts

    private var sectionPicker: some View {
        HStack(spacing: 0) {
            ForEach(LibrarySection.allCases) { option in
                Button { withAnimation(.easeInOut(duration: 0.2)) { section = option } } label: {
                    Text(option.rawValue).font(Theme.text(.subheadline, weight: section == option ? .medium : .regular))
                        .foregroundStyle(section == option ? Theme.label : Theme.secondary)
                        .frame(maxWidth: .infinity).frame(height: 36)
                        .background(section == option ? Theme.background : .clear, in: Capsule())
                        .shadow(color: .black.opacity(section == option ? 0.06 : 0), radius: 2, y: 1)
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(Theme.fill, in: Capsule())
        .sensoryFeedback(.selection, trigger: section)
    }

    /// Every saved place, newest first, narrowed by city with a row of chips.
    @ViewBuilder private var placesSection: some View {
        let groups = store.cityGroups(shown)
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                FilterChip(label: "All cities", count: shown.count, isOn: cityFilter == nil) { cityFilter = nil }
                ForEach(groups) { group in
                    FilterChip(label: group.name, count: group.places.count, isOn: cityFilter == group.id) {
                        cityFilter = cityFilter == group.id ? nil : group.id
                    }
                }
            }
        }
        .padding(.top, 12)
        .sensoryFeedback(.selection, trigger: cityFilter)
        // Kind of place, Want to go / Been, and the map: one quiet line.
        HStack(spacing: 14) {
            Menu {
                Button("All kinds") { groupFilter = nil }
                ForEach(PlaceGroup.allCases) { g in Button(g.label) { groupFilter = g } }
            } label: {
                Label(groupFilter?.label ?? "All kinds", systemImage: "chevron.down").labelStyle(TrailingIcon())
            }
            Spacer()
            Menu {
                ForEach(VisitFilter.allCases) { v in Button(v.label) { visit = v } }
            } label: {
                Label(visit.label, systemImage: "chevron.down").labelStyle(TrailingIcon())
            }
            Button { router.push(.map) } label: { Image(systemName: "map") }.accessibilityLabel("Map")
        }
        .font(Theme.text(.footnote, weight: .medium)).foregroundStyle(Theme.label)
        .padding(.top, 12)
        .sensoryFeedback(.selection, trigger: groupFilter)
        let places = shown.filter {
            (cityFilter == nil || Store.cityKey($0.city) == cityFilter) && (groupFilter == nil || PlaceGroup.of($0.category) == groupFilter)
        }.sorted { $0.createdAt > $1.createdAt }
        LazyVStack(spacing: 0) {
            ForEach(places) { place in
                NavigationLink(value: Route.place(id: place.id, tripId: nil)) {
                    PlaceRow(place: place, compact: true).padding(.vertical, 4)
                }
                .buttonStyle(PressStyle())
                .placeActions(place, onDelete: { Task { await store.deleteWithUndo(place) } }, sheet: $sheet)
                Divider().overlay(Theme.divider)
            }
        }
        .padding(.top, 4)
    }

    /// Lists as cards, in the same type-only style as the edits.
    @ViewBuilder private var listsSection: some View {
        HStack {
            Text("Your lists · \(store.folders.count)".uppercased()).font(Theme.text(.caption2, weight: .medium)).kerning(1.6)
                .foregroundStyle(Theme.secondary)
            Spacer()
            AccentTextButton(title: "New list") { folderName = ""; newFolder = true }
        }
        .padding(.top, 18)
        if store.folders.isEmpty {
            Text("Make lists for anything: date night, early risers, best croissants. A place can be on several.")
                .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary).padding(.top, 8)
        }
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
            ForEach(store.folders) { folder in
                NavigationLink(value: Route.folder(id: folder.id)) {
                    EditTile(caption: Fmt.plural(folder.placeCount, "place"), title: folder.name, preview: listCities(folder),
                             seed: folder.id, titleSize: 19)
                        .frame(height: 150)
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
                .buttonStyle(PressStyle())
            }
        }
        .padding(.top, 10)
    }

    private func listCities(_ folder: Folder) -> String {
        let cities = Array(Set(store.saved.filter { $0.folderIds.contains(folder.id) && !$0.city.isEmpty }.map(\.city))).sorted()
        return cities.count <= 3 ? cities.joined(separator: ", ") : "\(cities.count) cities"
    }

    /// The posts you've saved from, newest first: each opens the places it gave you.
    @ViewBuilder private var postsSection: some View {
        let platforms = [("all", "All"), ("tiktok", "TikTok"), ("instagram", "Instagram"), ("youtu", "YouTube")]
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(platforms.indices, id: \.self) { i in
                    FilterChip(label: platforms[i].1, isOn: postFilter == platforms[i].0) { postFilter = platforms[i].0 }
                }
            }
        }
        .padding(.top, 12)
        let posts = store.jobs.filter { !$0.isActive && (postFilter == "all" || $0.url.contains(postFilter)) }
            .sorted { $0.createdAt > $1.createdAt }
        if posts.isEmpty {
            Text("Posts you share to The Travel Edit appear here, with the places each one gave you.")
                .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary).padding(.top, 14)
        }
        LazyVStack(spacing: 0) {
            ForEach(posts) { job in
                if let reelId = job.reelId, job.status != "failed" {
                    NavigationLink(value: Route.reel(id: reelId)) { PostRow(job: job) }.buttonStyle(PressStyle())
                } else {
                    JobRow(job: job).padding(.vertical, 10)
                }
                Divider().overlay(Theme.divider)
            }
        }
        .padding(.top, 8)
    }

    // MARK: Around home

    @ViewBuilder private var aroundHome: some View {
        if let home = store.home {
            let places = shown.filter { store.isHome($0) }
            let open = places.filter { Hours.status($0.openingHours)?.isOpen == true }.count
            NavigationLink(value: Route.city(name: home.city)) {
                Card(padding: 16) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 4) {
                            Label { Text("Your city") } icon: { Image(systemName: "house").font(.system(size: 13, weight: .light)) }
                                .font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                            Text("Around \(home.city)").font(Theme.serif(22)).foregroundStyle(Theme.label)
                            HStack(spacing: 0) {
                                Text(Fmt.plural(places.count, "place")).foregroundStyle(Theme.secondary)
                                if open > 0 { Text(" · ").foregroundStyle(Theme.secondary); Text("\(open) open now").foregroundStyle(Theme.open) }
                            }
                            .font(Theme.text(.footnote))
                        }
                        Spacer()
                        Image(systemName: "chevron.right").font(.system(size: 13, weight: .light)).foregroundStyle(Theme.label)
                            .frame(width: 32, height: 32).background(Theme.background, in: Circle())
                    }
                    if !places.isEmpty { PhotoStrip(places: places).padding(.top, 12) }
                }
            }
            .buttonStyle(PressStyle())
        }
    }

    // MARK: Trips

    @ViewBuilder private var trips: some View {
        let all = store.realTrips
        SectionHeading(title: "Trips") {
            AccentTextButton(title: "New trip") { sheet = .newTrip([], nil) }
        }
        .padding(.top, 36)
        if all.isEmpty {
            Text("Plan a trip from a city you've saved places in, or start one from scratch.")
                .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
        }
        ForEach(Array(all.enumerated()), id: \.element.id) { i, trip in
            NavigationLink(value: Route.trip(id: trip.id)) {
                if i == 0 { TripRouteCard(trip: trip) } else { TripRow(trip: trip) }
            }
            .buttonStyle(PressStyle())
            .padding(.top, i == 0 ? 4 : 10)
        }
    }

    // MARK: Cities

    @ViewBuilder private var cities: some View {
        let groups = citySort.apply(store.cityGroups(shown))
        if !groups.isEmpty {
            SectionHeading(title: "Cities") {
                HStack(spacing: 12) {
                    LayoutToggle(layout: $cityLayout)
                    if groups.count > (cityLayout == .list ? 5 : 1) {
                        Button { router.push(.cities) } label: {
                            Text("See all").font(Theme.text(.footnote)).foregroundStyle(Theme.link)
                                .frame(minHeight: 44).contentShape(Rectangle())
                        }
                        .buttonStyle(PressStyle())
                        .accessibilityLabel("See all \(groups.count) cities")
                    }
                }
            }
            .padding(.top, 36)
            switch cityLayout {
            case .cards:
                // Every city, side by side: swipe across them.
                ScrollView(.horizontal, showsIndicators: false) {
                    LazyHStack(alignment: .top, spacing: 12) {
                        ForEach(groups) { city in
                            NavigationLink(value: Route.city(name: city.name)) {
                                CityTile(city: city, trip: store.trip(forCity: city.name), pictureHeight: 150).frame(width: 158)
                            }
                            .buttonStyle(PressStyle())
                        }
                    }
                    .scrollTargetLayout()
                    .padding(.horizontal, 20)
                }
                .scrollTargetBehavior(.viewAligned)
                .padding(.horizontal, -20)
                .padding(.top, 4)
            case .list:
                VStack(spacing: 0) {
                    ForEach(groups.prefix(5)) { city in
                        NavigationLink(value: Route.city(name: city.name)) { CityRow(city: city, trip: store.trip(forCity: city.name)) }
                            .buttonStyle(PressStyle())
                        Divider().overlay(Theme.divider)
                    }
                }
            }
        }
    }

    // MARK: Lists

    @ViewBuilder private var lists: some View {
        SectionHeading(title: "Your lists") {
            AccentTextButton(title: "New list") { folderName = ""; newFolder = true }
        }
        .padding(.top, 32)
        if store.folders.isEmpty {
            Text("Make lists for anything: date night, early risers, best croissants. A place can be on several.")
                .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
        }
        ForEach(store.folders) { folder in
            Divider().overlay(Theme.divider)
            NavigationLink(value: Route.folder(id: folder.id)) {
                ListRow(title: folder.name, subtitle: listSubtitle(folder), photo: folder.covers.first, symbol: "list.bullet")
            }
            .buttonStyle(PressStyle())
        }
        if !store.folders.isEmpty { Divider().overlay(Theme.divider) }
    }

    private func listSubtitle(_ folder: Folder) -> String {
        let cities = Array(Set(store.saved.filter { $0.folderIds.contains(folder.id) && !$0.city.isEmpty }.map(\.city))).sorted()
        let where_ = cities.isEmpty ? nil : cities.count <= 2 ? cities.joined(separator: ", ") : "\(cities.count) cities"
        return [Fmt.plural(folder.placeCount, "place"), where_].compactMap { $0 }.joined(separator: " · ")
    }
}

/// All / Want to go / Been, with counts.
struct VisitPicker: View {
    @Binding var visit: VisitFilter
    let places: [Place]

    var body: some View {
        HStack(spacing: 4) {
            ForEach(VisitFilter.allCases) { option in
                let on = option == visit
                Button { withAnimation(.snappy) { visit = option } } label: {
                    HStack(spacing: 4) {
                        Text(option.label).font(Theme.text(.subheadline, weight: on ? .medium : .regular))
                        Text("\(option.apply(places).count)").font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                    }
                    .foregroundStyle(on ? Theme.label : Theme.secondary)
                    .frame(maxWidth: .infinity, minHeight: 40)
                    .background(on ? Theme.cell : .clear, in: Capsule())
                }
                .buttonStyle(PressStyle())
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(4)
        .background(Theme.background, in: Capsule())
        .overlay(Capsule().strokeBorder(Theme.chipBorder))
    }
}

/// Three photos and "+9".
struct PhotoStrip: View {
    let places: [Place]

    var body: some View {
        let withPhotos = places.filter { !$0.photos.isEmpty }
        let shown = Array((withPhotos.isEmpty ? places : withPhotos).prefix(places.count > 4 ? 3 : 4))
        HStack(spacing: 8) {
            ForEach(shown) { p in PhotoBox(place: p, width: nil, height: 58, radius: 10) }
            if places.count > 4 {
                Text("+\(places.count - 3)").font(Theme.text(.subheadline)).foregroundStyle(Theme.label)
                    .frame(maxWidth: .infinity, minHeight: 58)
                    .background(Theme.background, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            ForEach(0..<max(0, 4 - shown.count - (places.count > 4 ? 1 : 0)), id: \.self) { _ in Color.clear.frame(maxWidth: .infinity, maxHeight: 58) }
        }
    }
}

/// The next trip, big: cover photo, countdown, dates and its route.
struct TripRouteCard: View {
    let trip: Trip

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            TripCover(trip: trip, width: nil, height: 180, radius: 14)
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline) {
                    Text(trip.name).font(Theme.serif(20)).foregroundStyle(Theme.label).lineLimit(1)
                    Spacer()
                    if let countdown = trip.countdown { Text(countdown).font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary) }
                }
                Text([trip.dateRange ?? "No dates yet", Fmt.plural(trip.placeCount, "place")].joined(separator: " · "))
                    .font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                RouteStrip(stops: trip.cities).padding(.top, 8)
            }
            .padding(.top, 14)
        }
        .contentShape(Rectangle())
    }
}

/// "Zürich —— St. Moritz —— Interlaken"
struct RouteStrip: View {
    let stops: [String]
    var body: some View {
        HStack(spacing: 6) {
            ForEach(Array(stops.enumerated()), id: \.offset) { i, stop in
                if i > 0 { Rectangle().fill(Theme.raisedBorder).frame(height: 1) }
                Text(stop).font(Theme.text(.footnote)).foregroundStyle(Theme.label).lineLimit(1).fixedSize()
            }
            if stops.count == 1 { Spacer() }
        }
    }
}

extension Trip {
    /// The cities on the trip's route, in order ("London", "Paris", "London").
    var cities: [String] {
        let route = (stops ?? []).map(\.city).filter { !$0.isEmpty }
        return route.isEmpty ? [city].filter { !$0.isEmpty } : route
    }
}

/// A smaller trip row: photo, name, dates and route.
struct TripRow: View {
    let trip: Trip
    var body: some View {
        HStack(spacing: 14) {
            TripCover(trip: trip, size: 64)
            VStack(alignment: .leading, spacing: 3) {
                Text(trip.name).font(Theme.text(.headline)).foregroundStyle(Theme.label).lineLimit(1)
                Text([trip.dateRange, trip.cities.joined(separator: " → "), trip.isShared ? "Shared" : nil].compactMap { $0?.isEmpty == false ? $0 : nil }.joined(separator: " · "))
                    .font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.system(size: 13, weight: .light)).foregroundStyle(Theme.tertiary)
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
    }
}

/// A city in the grid: one picture (the best photo from its places, else its drawn scene), its name and whether a
/// trip's planned.
struct CityTile: View {
    let city: Store.CityGroup
    let trip: Trip?
    var pictureHeight: CGFloat = 110

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Color.clear
                .frame(height: pictureHeight)
                .overlay {
                    CityCover(city: city.name, country: city.country, fallback: city.coverURLs(width: 400))
                }
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            Text(city.name).font(Theme.serif(19)).foregroundStyle(Theme.label).lineLimit(1).padding(.top, 10)
            CityLine(city: city, trip: trip)
        }
        .contentShape(Rectangle())
    }
}

/// "12 places · Trip 12 Dec" under a city's name.
struct CityLine: View {
    let city: Store.CityGroup
    let trip: Trip?

    var body: some View {
        HStack(spacing: 0) {
            Text(Fmt.plural(city.places.count, "place") + " · ").foregroundStyle(Theme.secondary)
            if let trip, let start = trip.startDate.flatMap(Fmt.day) {
                Text("Trip " + start.formatted(.dateTime.day().month(.abbreviated))).foregroundStyle(Theme.label)
            } else if trip != nil {
                Text("On a trip").foregroundStyle(Theme.label)
            } else {
                Text("No trip yet").foregroundStyle(Theme.secondary)
            }
        }
        .font(Theme.text(.footnote)).lineLimit(1)
    }
}

/// A city in the list view: a small picture, its name, and how many places and when the trip is.
struct CityRow: View {
    let city: Store.CityGroup
    let trip: Trip?
    var showCountry = false

    var body: some View {
        HStack(spacing: 14) {
            Color.clear.frame(width: 56, height: 56)
                .overlay { CityCover(city: city.name, country: city.country, fallback: city.coverURLs(width: 160)) }
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(city.name + (showCountry && !city.country.isEmpty ? ", \(city.country)" : ""))
                    .font(Theme.serif(18)).foregroundStyle(Theme.label).lineLimit(1)
                CityLine(city: city, trip: trip)
            }
            Spacer(minLength: 8)
            Image(systemName: "chevron.right").font(Theme.text(.caption)).foregroundStyle(Theme.tertiary)
        }
        .padding(.vertical, 10)
        .contentShape(Rectangle())
    }
}

extension Store.CityGroup {
    /// Starred places first, then the best-known (most ratings), so the cover is a place worth showing.
    func coverURLs(width: Int) -> [URL] {
        places.filter { !$0.photos.isEmpty }
            .sorted { ($0.mustDo ? 1 : 0, $0.ratingCount ?? 0) > ($1.mustDo ? 1 : 0, $1.ratingCount ?? 0) }
            .prefix(4)
            .compactMap { $0.photos.first?.url(width: width) }
    }

    /// When a place here was last saved.
    var lastSaved: String { places.map(\.createdAt).max() ?? "" }
}

/// Cities as cards (swipe across) or as a list; remembered.
enum CityLayout: String {
    case cards, list
}

enum CitySort: String, CaseIterable, Identifiable {
    case places, recent, name, country
    var id: String { rawValue }

    var label: String {
        switch self {
        case .places: "Most places"
        case .recent: "Recent"
        case .name: "A–Z"
        case .country: "By country"
        }
    }

    func apply(_ groups: [Store.CityGroup]) -> [Store.CityGroup] {
        switch self {
        case .places: groups
        case .recent: groups.sorted { $0.lastSaved > $1.lastSaved }
        case .name: groups.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        case .country: groups.sorted { ($0.country, $0.name) < ($1.country, $1.name) }
        }
    }
}

/// Two small icons, cards or list.
struct LayoutToggle: View {
    @Binding var layout: CityLayout

    var body: some View {
        HStack(spacing: 2) {
            option(.cards, "square.grid.2x2", "Cards")
            option(.list, "list.bullet", "List")
        }
        .padding(3)
        .background(Theme.fill, in: Capsule())
    }

    private func option(_ value: CityLayout, _ symbol: String, _ name: String) -> some View {
        Button {
            withAnimation(.easeOut(duration: 0.2)) { layout = value }
        } label: {
            Image(systemName: symbol)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(layout == value ? Theme.accentInk : Theme.secondary)
                .frame(width: 34, height: 28)
                .background(layout == value ? Theme.accent : .clear, in: Capsule())
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(name)
        .accessibilityAddTraits(layout == value ? .isSelected : [])
    }
}

/// A row with a photo (or symbol), a title and a line under it, and a chevron.
struct ListRow: View {
    let title: String
    let subtitle: String
    let photo: PlacePhoto?
    let symbol: String

    var body: some View {
        HStack(spacing: 14) {
            RemoteImage(url: photo?.url(width: 150)) {
                ZStack { Theme.raised; Image(systemName: symbol).foregroundStyle(Theme.secondary) }
            }
            .frame(width: 56, height: 56)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(Theme.text(.body)).foregroundStyle(Theme.label).lineLimit(1)
                Text(subtitle).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.system(size: 13, weight: .light)).foregroundStyle(Theme.tertiary)
        }
        .padding(.vertical, 12)
        .contentShape(Rectangle())
    }
}

/// Sheets the Library screens open.
enum LibrarySheet: Identifiable {
    case folders([String])
    case trips([String])
    case newTrip([String], String?)
    case pick(title: String, exclude: Set<String>, confirm: String, onDone: ([String]) async -> Void)

    var id: String {
        switch self {
        case .folders(let ids): "folders" + ids.joined()
        case .trips(let ids): "trips" + ids.joined()
        case .newTrip(let ids, let folder): "new" + ids.joined() + (folder ?? "")
        case .pick(let title, _, _, _): "pick" + title
        }
    }

    @MainActor @ViewBuilder var view: some View {
        switch self {
        case .folders(let ids): FolderPickerSheet(placeIds: ids)
        case .trips(let ids): TripPickerSheet(placeIds: ids)
        case .newTrip(let ids, let folder): NewTripSheet(placeIds: ids, folderId: folder)
        case .pick(let title, let exclude, let confirm, let onDone):
            PlacePickerSheet(title: title, exclude: exclude, confirm: confirm, onDone: onDone)
        }
    }
}

extension View {
    /// Swipe to star or delete; press and hold to file a place in a folder or trip.
    func placeActions(_ place: Place, onDelete: @escaping () -> Void, sheet: Binding<LibrarySheet?>) -> some View {
        modifier(PlaceActions(place: place, onDelete: onDelete, sheet: sheet))
    }
}

private struct PlaceActions: ViewModifier {
    let place: Place
    let onDelete: () -> Void
    @Binding var sheet: LibrarySheet?
    @Environment(Store.self) private var store

    func body(content: Content) -> some View {
        content
            .swipeActions(edge: .leading) {
                Button { Task { await store.toggleStar(place) } } label: {
                    Label(place.mustDo ? "Unstar" : "Star", systemImage: place.mustDo ? "star.slash" : "star.fill")
                }
                .tint(Theme.gold)
            }
            .swipeActions(edge: .trailing) {
                Button(role: .destructive, action: onDelete) { Label("Delete", systemImage: "trash") }
            }
            .contextMenu {
                Button { Task { await store.toggleStar(place) } } label: {
                    Label(place.mustDo ? "Remove star" : "Star", systemImage: place.mustDo ? "star.slash" : "star")
                }
                Button { sheet = .folders([place.id]) } label: { Label("Folders…", systemImage: "folder") }
                Button { sheet = .trips([place.id]) } label: { Label("Add to a trip…", systemImage: "airplane") }
                if let url = place.directionsURL {
                    Button { Links.open(url) } label: { Label("Directions", systemImage: "arrow.triangle.turn.up.right.diamond") }
                }
                if let url = place.googleMapsURL {
                    ShareLink(item: url, subject: Text(place.name)) { Label("Share", systemImage: "square.and.arrow.up") }
                }
                Button(role: .destructive, action: onDelete) { Label("Delete", systemImage: "trash") }
            }
    }
}

// MARK: - Folders strip

struct FolderStrip: View {
    let folders: [Folder]
    let onNew: () -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .top, spacing: 12) {
                ForEach(folders) { folder in
                    NavigationLink(value: Route.folder(id: folder.id)) { FolderCard(folder: folder) }
                        .buttonStyle(PressStyle())
                }
                Button(action: onNew) {
                    VStack(alignment: .leading, spacing: 6) {
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .fill(Theme.fill)
                            .frame(width: 128, height: 128)
                            .overlay(Image(systemName: "plus").font(Theme.text(.title2)).foregroundStyle(Theme.secondary))
                        Text("New folder").font(Theme.text(.subheadline))
                        Text(folders.isEmpty ? "e.g. Date night, Brunch" : "Name it anything")
                            .font(Theme.text(.caption)).foregroundStyle(Theme.secondary)
                    }
                    .frame(width: 128, alignment: .leading)
                }
                .buttonStyle(PressStyle())
            }
            .padding(.horizontal, 16).padding(.vertical, 4)
        }
    }
}

struct FolderCard: View {
    let folder: Folder

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            cover
                .frame(width: 128, height: 128)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            Text(folder.name).font(Theme.text(.subheadline)).lineLimit(1)
            Text(Fmt.plural(folder.placeCount, "place")).font(Theme.text(.caption)).foregroundStyle(Theme.secondary)
        }
        .frame(width: 128, alignment: .leading)
    }

    @ViewBuilder private var cover: some View {
        let photos = Array(folder.covers.prefix(4))
        if photos.count >= 3 {
            let grid = [GridItem(.fixed(63), spacing: 2), GridItem(.fixed(63), spacing: 2)]
            LazyVGrid(columns: grid, spacing: 2) {
                ForEach(0..<4, id: \.self) { i in
                    RemoteImage(url: i < photos.count ? photos[i].url(width: 240) : nil) { Theme.fill }
                        .frame(width: 63, height: 63).clipped()
                }
            }
        } else if let first = photos.first {
            RemoteImage(url: first.url(width: 400)) { Theme.fill }
        } else {
            ZStack { Theme.fill; Image(systemName: "folder.fill").font(Theme.text(.title)).foregroundStyle(Theme.gold) }
        }
    }
}

// MARK: - Imports in progress

struct JobRow: View {
    let job: Job
    @Environment(Store.self) private var store

    var body: some View {
        HStack(spacing: 12) {
            SymbolTile(symbol: Self.symbol(for: job.url), color: job.status == "failed" ? Theme.warn : Theme.indigo)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(Theme.text(.subheadline)).lineLimit(2)
                    .foregroundStyle(job.status == "failed" ? Theme.warn : Theme.label)
                Text(job.url.hasPrefix("upload:") ? "Screenshots" : job.url.replacingOccurrences(of: "https://", with: "").replacingOccurrences(of: "www.", with: ""))
                    .font(Theme.text(.caption)).foregroundStyle(Theme.secondary).lineLimit(1)
            }
            Spacer()
            if job.isActive {
                ProgressView()
            } else if job.status == "failed" {
                Button("Retry") { Task { await store.retry(job) } }.buttonStyle(PrimaryButtonStyle(tinted: true, compact: true)).fixedSize()
            }
        }
    }

    private var title: String {
        if job.isActive { return job.message ?? "Waiting to process…" }
        if job.status == "failed" { return job.message ?? "Import failed" }
        return job.message ?? "Done"
    }

    static func symbol(for url: String) -> String {
        if url.hasPrefix("upload:") { return "photo.on.rectangle" }
        if url.contains("tiktok") { return "music.note" }
        if url.contains("instagram") { return "camera" }
        if url.contains("youtu") { return "play.rectangle" }
        return "link"
    }
}

/// "Want to go ⌄": the words first, the icon after.
struct TrailingIcon: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 4) { configuration.title; configuration.icon.font(.system(size: 10, weight: .semibold)) }
    }
}

enum LibrarySection: String, CaseIterable, Identifiable {
    case places = "Places", lists = "Lists", posts = "Posts"
    var id: String { rawValue }
}

/// A saved post: who posted it, how many places it gave you, and when.
struct PostRow: View {
    let job: Job

    var body: some View {
        HStack(spacing: 12) {
            SymbolTile(symbol: JobRow.symbol(for: job.url), color: Theme.indigo)
            VStack(alignment: .leading, spacing: 2) {
                Text(job.reel?.uploader.map { $0.hasPrefix("@") ? $0 : "@\($0)" } ?? job.reel?.title ?? "A saved post")
                    .font(Theme.text(.body)).foregroundStyle(Theme.label).lineLimit(1)
                Text([Fmt.plural(job.addedPlaces, "place"), Fmt.parseISO(job.createdAt)?.formatted(.relative(presentation: .named))]
                    .compactMap { $0 }.joined(separator: " · "))
                    .font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
            }
            Spacer(minLength: 8)
            Image(systemName: "chevron.right").font(Theme.text(.caption)).foregroundStyle(Theme.tertiary)
        }
        .padding(.vertical, 10)
        .contentShape(Rectangle())
    }
}

/// Library → Cities → See all: every city you've saved places in, as cards or a list, sorted how you like.
struct AllCitiesView: View {
    @Environment(Store.self) private var store
    @AppStorage("library.visit") private var visit: VisitFilter = .all
    @AppStorage("library.cityLayout") private var layout: CityLayout = .cards
    @AppStorage("library.citySort") private var sort: CitySort = .places

    var body: some View {
        let groups = sort.apply(store.cityGroups(visit.apply(store.saved)))
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Cities").font(Theme.serif(34)).foregroundStyle(Theme.label)
                    Spacer()
                    LayoutToggle(layout: $layout)
                }
                Text((groups.count == 1 ? "1 city" : "\(groups.count) cities") + " · " + Fmt.plural(groups.reduce(0) { $0 + $1.places.count }, "place"))
                    .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary).padding(.top, 2)
                VisitPicker(visit: $visit, places: store.saved).padding(.top, 16)
                sortChips.padding(.top, 10)
                if sort == .country {
                    let countries = Dictionary(grouping: groups) { $0.country.isEmpty ? "Elsewhere" : $0.country }
                    ForEach(countries.keys.sorted(), id: \.self) { country in
                        Text(country).font(Theme.serif(22)).foregroundStyle(Theme.label).padding(.top, 26)
                        cities(countries[country] ?? [])
                    }
                } else {
                    cities(groups).padding(.top, 8)
                }
            }
            .padding(.horizontal, 20).padding(.bottom, 40)
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var sortChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(CitySort.allCases) { option in
                    Button { withAnimation(.easeOut(duration: 0.2)) { sort = option } } label: {
                        Text(option.label).font(Theme.text(.footnote, weight: sort == option ? .medium : .regular))
                            .foregroundStyle(sort == option ? Theme.accentInk : Theme.label)
                            .padding(.horizontal, 14).frame(height: 32)
                            .background(sort == option ? Theme.accent : Theme.fill, in: Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    @ViewBuilder private func cities(_ groups: [Store.CityGroup]) -> some View {
        switch layout {
        case .cards:
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)],
                      alignment: .leading, spacing: 18) {
                ForEach(groups) { city in
                    NavigationLink(value: Route.city(name: city.name)) { CityTile(city: city, trip: store.trip(forCity: city.name)) }
                        .buttonStyle(PressStyle())
                }
            }
            .padding(.top, 10)
        case .list:
            LazyVStack(spacing: 0) {
                ForEach(groups) { city in
                    NavigationLink(value: Route.city(name: city.name)) {
                        CityRow(city: city, trip: store.trip(forCity: city.name), showCountry: sort != .country)
                    }
                    .buttonStyle(PressStyle())
                    Divider().overlay(Theme.divider)
                }
            }
        }
    }
}
