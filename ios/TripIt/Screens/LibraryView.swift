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
    @State private var query = ""
    @State private var allCities = false
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
                        Button("Try again") { Task { await store.refresh() } }.buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 200)
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
                    aroundHome.padding(.top, 20)
                    trips
                    cities
                    lists
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 40)
        }
        .background(Theme.background.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
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
            HStack(spacing: 10) {
                Spacer()
                RoundIconButton(symbol: "plus", label: "Save a place") { router.addRequest = Router.AddRequest() }
                ProfileButton()
            }
            .padding(.top, 8)
            HStack {
                Text("Library").font(Theme.serif(32)).foregroundStyle(Theme.label)
                Spacer()
                Button { router.push(.map) } label: {
                    Label("Map", systemImage: "map").font(.footnote.weight(.medium)).foregroundStyle(Theme.label)
                        .padding(.horizontal, 12).frame(height: 32)
                        .background(Theme.cell, in: Capsule())
                        .overlay(Capsule().strokeBorder(Theme.raisedBorder))
                }
                .buttonStyle(.plain)
            }
            .padding(.top, 8)
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
            .font(.subheadline)
            .padding(.horizontal, 12).frame(height: 38)
            .background(Theme.cell, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.border))
            .padding(.top, 12)
            VisitPicker(visit: $visit, places: store.saved).padding(.top, 10)
        }
    }

    // MARK: Search

    @ViewBuilder private var searchResults: some View {
        let q = PlaceFilter.normalize(query)
        let places = shown.filter { PlaceFilter.normalize("\($0.name) \($0.neighborhood ?? "") \($0.city) \($0.venue ?? "")").contains(q) }
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
                }.buttonStyle(.plain)
            }
            ForEach(folders) { folder in
                NavigationLink(value: Route.folder(id: folder.id)) {
                    ListRow(title: folder.name, subtitle: Fmt.plural(folder.placeCount, "place"), photo: folder.covers.first, symbol: "list.bullet")
                }.buttonStyle(.plain)
            }
        }
        if !places.isEmpty {
            SectionHeading(Fmt.plural(places.count, "place"), size: 20).padding(.top, 20)
            ForEach(places) { place in
                NavigationLink(value: Route.place(id: place.id, tripId: nil)) {
                    PlaceRow(place: place).padding(.vertical, 6)
                }
                .buttonStyle(.plain)
                .placeActions(place, onDelete: { Task { await store.deleteWithUndo(place) } }, sheet: $sheet)
                Divider().overlay(Theme.divider)
            }
        }
    }

    // MARK: Around home

    @ViewBuilder private var aroundHome: some View {
        if let home = store.home {
            let places = shown.filter { store.isHome($0) }
            let open = places.filter { Hours.status($0.openingHours)?.isOpen == true }.count
            NavigationLink(value: Route.city(name: home.city)) {
                Card(radius: 16, padding: 14) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 4) {
                            Label { Text("YOUR CITY").kerning(1.6) } icon: { Image(systemName: "house") }
                                .font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.link)
                            Text("Around \(home.city)").font(Theme.serif(20)).foregroundStyle(Theme.label)
                            HStack(spacing: 0) {
                                Text(Fmt.plural(places.count, "place")).foregroundStyle(Theme.secondary)
                                if open > 0 { Text(" · ").foregroundStyle(Theme.secondary); Text("\(open) open now").foregroundStyle(Theme.open) }
                            }
                            .font(.footnote)
                        }
                        Spacer()
                        Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.label)
                            .frame(width: 28, height: 28).background(Theme.raised, in: Circle())
                    }
                    if !places.isEmpty { PhotoStrip(places: places).padding(.top, 12) }
                }
            }
            .buttonStyle(.plain)
        }
    }

    // MARK: Trips

    @ViewBuilder private var trips: some View {
        let all = store.realTrips
        SectionHeading(title: "Trips") {
            AccentTextButton(title: "New trip") { sheet = .newTrip([], nil) }
        }
        .padding(.top, 28)
        if all.isEmpty {
            Text("Plan a trip from a city you've saved places in, or start one from scratch.")
                .font(.subheadline).foregroundStyle(Theme.secondary)
        }
        ForEach(Array(all.enumerated()), id: \.element.id) { i, trip in
            NavigationLink(value: Route.trip(id: trip.id)) {
                if i == 0 { TripRouteCard(trip: trip) } else { TripRow(trip: trip) }
            }
            .buttonStyle(.plain)
            .padding(.top, i == 0 ? 4 : 10)
        }
    }

    // MARK: Cities

    @ViewBuilder private var cities: some View {
        let groups = store.cityGroups(shown)
        if !groups.isEmpty {
            SectionHeading(title: "Cities") {
                if groups.count > 4 {
                    Button { withAnimation { allCities.toggle() } } label: {
                        HStack(spacing: 4) {
                            Text(allCities ? "Show fewer" : "See all \(groups.count)")
                            Image(systemName: allCities ? "chevron.up" : "chevron.down").font(.caption2.weight(.bold))
                        }
                        .font(.footnote.weight(.semibold)).foregroundStyle(Theme.link).frame(minHeight: 36)
                    }
                    .buttonStyle(.plain)
                } else {
                    Text("Sorted for you automatically").font(.caption).foregroundStyle(Theme.tertiary)
                }
            }
            .padding(.top, 28)
            let visible = allCities ? groups : Array(groups.prefix(4))
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], alignment: .leading, spacing: 16) {
                ForEach(visible) { city in
                    NavigationLink(value: Route.city(name: city.name)) { CityTile(city: city, trip: store.trip(forCity: city.name)) }
                        .buttonStyle(.plain)
                }
            }
            .padding(.top, 4)
        }
    }

    // MARK: Lists

    @ViewBuilder private var lists: some View {
        SectionHeading(title: "Your lists") {
            AccentTextButton(title: "New list") { folderName = ""; newFolder = true }
        }
        .padding(.top, 20)
        if store.folders.isEmpty {
            Text("Make lists for anything: date night, early risers, best croissants. A place can be on several.")
                .font(.subheadline).foregroundStyle(Theme.secondary)
        }
        ForEach(Array(store.folders.enumerated()), id: \.element.id) { i, folder in
            NavigationLink(value: Route.folder(id: folder.id)) {
                ListRow(title: folder.name, subtitle: listSubtitle(folder), photo: folder.covers.first, symbol: "list.bullet")
            }
            .buttonStyle(.plain)
            if i < store.folders.count - 1 { Divider().overlay(Theme.divider) }
        }
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
                        Text(option.label).fontWeight(on ? .semibold : .medium)
                        Text("\(option.apply(places).count)").foregroundStyle(on ? Theme.background.opacity(0.8) : Theme.secondary)
                    }
                    .font(.footnote)
                    .foregroundStyle(on ? Theme.background : Theme.label)
                    .frame(maxWidth: .infinity, minHeight: 30)
                    .background(on ? Theme.label : .clear, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(3)
        .background(Theme.cell, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 11, style: .continuous).strokeBorder(Theme.border))
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
                Text("+\(places.count - 3)").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                    .frame(maxWidth: .infinity, minHeight: 58)
                    .background(Theme.raised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
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
            Color.clear.frame(height: 96).frame(maxWidth: .infinity)
                .overlay {
                    RemoteImage(url: trip.coverPhoto?.url(width: 900)) {
                        ZStack { Theme.raised; Image(systemName: "airplane").font(.title).foregroundStyle(Theme.secondary) }
                    }
                }
                .clipped()
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline) {
                    Text(trip.name).font(Theme.serif(20)).foregroundStyle(Theme.label).lineLimit(1)
                    Spacer()
                    if let countdown = trip.countdown { Text(countdown).font(.footnote.weight(.semibold)).foregroundStyle(Theme.link) }
                }
                Text([trip.dateRange ?? "No dates yet", Fmt.plural(trip.placeCount, "place")].joined(separator: " · "))
                    .font(.footnote).foregroundStyle(Theme.secondary)
                RouteStrip(stops: trip.cities).padding(.top, 8)
            }
            .padding(EdgeInsets(top: 12, leading: 14, bottom: 14, trailing: 14))
        }
        .background(Theme.cell)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Theme.border))
    }
}

/// "Zürich —— St. Moritz —— Interlaken"
struct RouteStrip: View {
    let stops: [String]
    var body: some View {
        HStack(spacing: 6) {
            ForEach(Array(stops.enumerated()), id: \.offset) { i, stop in
                if i > 0 { Rectangle().fill(Theme.raisedBorder).frame(height: 1) }
                Text(stop).font(.footnote.weight(.medium)).foregroundStyle(Theme.label).lineLimit(1).fixedSize()
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
            TripCover(trip: trip, size: 44)
            VStack(alignment: .leading, spacing: 2) {
                Text(trip.name).font(Theme.serif(17)).foregroundStyle(Theme.label).lineLimit(1)
                Text([trip.dateRange, trip.cities.joined(separator: " → "), trip.isShared ? "Shared" : nil].compactMap { $0?.isEmpty == false ? $0 : nil }.joined(separator: " · "))
                    .font(.footnote).foregroundStyle(Theme.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.quiet)
        }
        .padding(EdgeInsets(top: 8, leading: 8, bottom: 8, trailing: 12))
        .background(Theme.cell, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Theme.border))
    }
}

/// A city in the grid: two photos, its name and whether a trip's planned.
struct CityTile: View {
    let city: Store.CityGroup
    let trip: Trip?

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            let photos = Array(city.places.filter { !$0.photos.isEmpty }.prefix(2))
            HStack(spacing: 2) {
                if photos.isEmpty {
                    ZStack { Theme.raised; Image(systemName: "building.2").foregroundStyle(Theme.secondary) }.frame(height: 80)
                } else {
                    ForEach(photos) { p in PhotoBox(place: p, width: nil, height: 80, radius: 0) }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            Text(city.name).font(Theme.serif(17)).foregroundStyle(Theme.label).lineLimit(1).padding(.top, 6)
            HStack(spacing: 0) {
                Text(Fmt.plural(city.places.count, "place") + " · ").foregroundStyle(Theme.secondary)
                if let trip, let start = trip.startDate.flatMap(Fmt.day) {
                    Text("Trip " + start.formatted(.dateTime.day().month(.abbreviated))).foregroundStyle(Theme.link)
                } else if trip != nil {
                    Text("On a trip").foregroundStyle(Theme.link)
                } else {
                    Text("No trip yet").foregroundStyle(Theme.secondary)
                }
            }
            .font(.footnote).lineLimit(1)
        }
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
            .frame(width: 40, height: 40)
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label).lineLimit(1)
                Text(subtitle).font(.footnote).foregroundStyle(Theme.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.quiet)
        }
        .padding(.vertical, 10)
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
                        .buttonStyle(.plain)
                }
                Button(action: onNew) {
                    VStack(alignment: .leading, spacing: 6) {
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .fill(Theme.fill)
                            .frame(width: 128, height: 128)
                            .overlay(Image(systemName: "plus").font(.title2.weight(.semibold)).foregroundStyle(Theme.secondary))
                        Text("New folder").font(.subheadline.weight(.semibold))
                        Text(folders.isEmpty ? "e.g. Date night, Brunch" : "Name it anything")
                            .font(.caption).foregroundStyle(Theme.secondary)
                    }
                    .frame(width: 128, alignment: .leading)
                }
                .buttonStyle(.plain)
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
            Text(folder.name).font(.subheadline.weight(.semibold)).lineLimit(1)
            Text(Fmt.plural(folder.placeCount, "place")).font(.caption).foregroundStyle(Theme.secondary)
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
            ZStack { Theme.fill; Image(systemName: "folder.fill").font(.title).foregroundStyle(Theme.gold) }
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
                Text(title).font(.subheadline.weight(.semibold)).lineLimit(2)
                    .foregroundStyle(job.status == "failed" ? Theme.warn : Theme.label)
                Text(job.url.hasPrefix("upload:") ? "Screenshots" : job.url.replacingOccurrences(of: "https://", with: "").replacingOccurrences(of: "www.", with: ""))
                    .font(.caption).foregroundStyle(Theme.secondary).lineLimit(1)
            }
            Spacer()
            if job.isActive {
                ProgressView()
            } else if job.status == "failed" {
                Button("Retry") { Task { await store.retry(job) } }.buttonStyle(.bordered).controlSize(.small)
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
