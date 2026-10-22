import SwiftUI

/// The Library tab: everything you've saved (with folders on top) and your trips.
struct LibraryView: View {
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @AppStorage("library.segment") private var segment = "saved"
    @AppStorage("library.sort") private var sort: PlaceSort = .popular
    @State private var filter = PlaceFilter()
    @State private var selecting = false
    @State private var selection = Set<String>()
    @State private var sheet: LibrarySheet?
    @State private var newFolder = false
    @State private var folderName = ""
    @State private var deleting: Place?
    @State private var location = Location.shared

    var body: some View {
        List(selection: $selection) {
            Section {
                Picker("Show", selection: $segment) {
                    Text("Saved").tag("saved")
                    Text("Trips").tag("trips")
                }
                .pickerStyle(.segmented)
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 16))
                ForEach(store.jobs.filter(\.isActive)) { job in
                    JobRow(job: job)
                }
            }
            if !store.loaded, let error = store.error {
                EmptyState(symbol: "wifi.slash", title: "Can't load your library", text: error) {
                    Button("Try again") { Task { await store.refresh() } }.buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 200)
                }
                .listRowBackground(Color.clear)
            } else if !store.loaded {
                ProgressView().frame(maxWidth: .infinity).listRowBackground(Color.clear)
            } else if segment == "trips" {
                TripsSection(sheet: $sheet)
            } else {
                savedSections
            }
        }
        .listStyle(.insetGrouped)
        .tripBackground()
        .environment(\.editMode, .constant(selecting ? .active : .inactive))
        .navigationTitle("Library")
        .rootToolbar(add: true)
        .searchable(text: $filter.query, placement: .navigationBarDrawer(displayMode: .automatic), prompt: "Search your saved places")
        .refreshable { await store.refresh() }
        .safeAreaInset(edge: .bottom) {
            if selecting { selectionBar }
        }
        .sheet(item: $sheet) { sheet in
            sheet.view.environment(store).environment(router)
        }
        .alert("New folder", isPresented: $newFolder) {
            TextField("e.g. Date night", text: $folderName)
            Button("Cancel", role: .cancel) {}
            Button("Create") {
                let name = folderName.trimmingCharacters(in: .whitespaces)
                guard !name.isEmpty else { return }
                Task { if let folder = await store.createFolder(name) { router.push(.folder(id: folder.id)) } }
            }
        }
        .confirmationDialog("Delete this place everywhere? It leaves your saved places, folders and trips.",
                            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button("Delete place", role: .destructive) {
                if let place = deleting { Task { await store.delete(place) } }
            }
        }
        .onChange(of: segment) { _, _ in selecting = false; selection = [] }
    }

    // MARK: Saved

    @ViewBuilder private var savedSections: some View {
        Section {
            FolderStrip(folders: store.folders) { folderName = ""; newFolder = true }
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
        } header: {
            Text("Your folders")
        }
        if store.places.isEmpty {
            EmptyState(symbol: "bookmark.fill", color: Theme.accent, title: "Nothing saved yet",
                       text: "Share a TikTok or Instagram post to TripIt, paste a link, or search for a place. Everything you save lands here, ready to sort into folders and trips.") {
                Button { router.addRequest = Router.AddRequest() } label: { Label("Add a place", systemImage: "plus") }
                    .buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 220)
            }
            .listRowBackground(Color.clear)
        } else {
            let shown = sort.sorted(filter.apply(store.places), from: location.current)
            Section {
                PlaceFilterBar(places: store.places, filter: $filter, sort: $sort)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
            }
            Section {
                if shown.isEmpty {
                    EmptyState(symbol: "mappin.slash", title: "Nothing matches",
                               text: filter.query.isEmpty ? "Try fewer filters." : "No saved place matches “\(filter.query)”.") {
                        Button("Clear filters") { filter = PlaceFilter() }.buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 200)
                    }
                    .listRowBackground(Color.clear)
                }
                ForEach(shown) { place in
                    NavigationLink(value: Route.place(id: place.id, tripId: nil)) {
                        PlaceRow(place: place, distance: sort == .closest ? place.distance(from: location.current) : nil)
                    }
                    .tag(place.id)
                    .placeActions(place, onDelete: { deleting = place }, sheet: $sheet)
                }
            } header: {
                HStack {
                    Text(filter.isActive ? "\(Fmt.plural(shown.count, "place")) match" : Fmt.plural(shown.count, "place"))
                    Spacer()
                    Button(selecting ? "Done" : "Select") {
                        withAnimation { selecting.toggle(); selection = [] }
                    }
                    .font(.subheadline.weight(.semibold))
                    .textCase(nil)
                }
            }
        }
    }

    private var selectionBar: some View {
        let ids = Array(selection)
        return HStack(spacing: 10) {
            Text(selection.isEmpty ? "Tick places" : Fmt.plural(selection.count, "place"))
                .font(.subheadline.weight(.semibold))
            Spacer()
            Button { sheet = .folders(ids) } label: { Label("Folder", systemImage: "folder.badge.plus") }
            Button { sheet = .trips(ids) } label: { Label("Trip", systemImage: "airplane") }
            Button { sheet = .newTrip(ids, nil) } label: { Label("New trip", systemImage: "plus") }
        }
        .labelStyle(.iconOnly)
        .font(.title3)
        .disabled(selection.isEmpty)
        .padding(.horizontal, 20).padding(.vertical, 14)
        .background(.regularMaterial, in: Capsule())
        .padding(.horizontal, 16).padding(.bottom, 8)
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
