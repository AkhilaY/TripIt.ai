import SwiftUI

struct FolderView: View {
    let folderId: String
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss
    @AppStorage("library.sort") private var sort: PlaceSort = .popular
    @State private var filter = PlaceFilter()
    @State private var sheet: LibrarySheet?
    @State private var renaming = false
    @State private var name = ""
    @State private var confirmDelete = false
    @State private var location = Location.shared

    var body: some View {
        if let folder = store.folders.first(where: { $0.id == folderId }) {
            let inside = store.places.filter { $0.folderIds.contains(folder.id) }
            let shown = sort.sorted(filter.apply(inside), from: location.current)
            List {
                Section {
                    HStack(spacing: 10) {
                        Menu {
                            Button { pickPlaces(folder, inside: inside) } label: { Label("From your saved places", systemImage: "bookmark") }
                            Button { router.addRequest = Router.AddRequest(folderId: folder.id) } label: { Label("Search for a new place", systemImage: "magnifyingglass") }
                        } label: {
                            Label("Add places", systemImage: "plus")
                                .font(.body.weight(.semibold)).foregroundStyle(Theme.accent)
                                .padding(.horizontal, 20).padding(.vertical, 13).frame(maxWidth: .infinity)
                                .background(Theme.fill, in: Capsule())
                        }
                        if !inside.isEmpty {
                            Button { sheet = .newTrip([], folder.id) } label: { Label("Plan a trip", systemImage: "airplane") }
                                .buttonStyle(PrimaryButtonStyle())
                        }
                    }
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 0, trailing: 16))
                } footer: {
                    Text(Fmt.plural(inside.count, "place"))
                }
                if inside.isEmpty {
                    EmptyState(symbol: "folder", title: "This folder is empty",
                               text: "Add places from everything you've saved. A place can be in as many folders as you like.")
                        .listRowBackground(Color.clear)
                } else {
                    Section {
                        PlaceFilterBar(places: inside, filter: $filter, sort: $sort)
                            .listRowInsets(EdgeInsets())
                            .listRowBackground(Color.clear)
                    }
                    Section {
                        ForEach(shown) { place in
                            NavigationLink(value: Route.place(id: place.id, tripId: nil)) {
                                PlaceRow(place: place, distance: sort == .closest ? place.distance(from: location.current) : nil)
                            }
                            .swipeActions(edge: .leading) {
                                Button { Task { await store.toggleStar(place) } } label: {
                                    Label(place.mustDo ? "Unstar" : "Star", systemImage: place.mustDo ? "star.slash" : "star.fill")
                                }
                                .tint(Theme.gold)
                            }
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    Task { await store.removeFromFolder(folder.id, place.id) }
                                } label: { Label("Remove", systemImage: "folder.badge.minus") }
                            }
                        }
                    } footer: {
                        Text("Swipe left to take a place out of this folder. It stays in your saved places.")
                    }
                }
            }
            .tripBackground()
            .navigationTitle(folder.name)
            .searchable(text: $filter.query, prompt: "Search this folder")
            .refreshable { await store.reloadPlaces() }
            .toolbar {
                Menu {
                    Button { name = folder.name; renaming = true } label: { Label("Rename", systemImage: "pencil") }
                    Button(role: .destructive) { confirmDelete = true } label: { Label("Delete folder", systemImage: "trash") }
                } label: { Image(systemName: "ellipsis.circle") }
            }
            .sheet(item: $sheet) { $0.view.environment(store).environment(router) }
            .alert("Rename folder", isPresented: $renaming) {
                TextField("Name", text: $name)
                Button("Cancel", role: .cancel) {}
                Button("Save") {
                    let clean = name.trimmingCharacters(in: .whitespaces)
                    if !clean.isEmpty { Task { await store.renameFolder(folder, to: clean) } }
                }
            }
            .confirmationDialog("Delete “\(folder.name)”? The places in it stay saved.", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete folder", role: .destructive) {
                    Task { await store.deleteFolder(folder); dismiss() }
                }
            }
        } else {
            EmptyState(symbol: "folder", title: "Folder not found", text: "This folder was deleted.")
                .frame(maxHeight: .infinity)
                .background(Theme.background.ignoresSafeArea())
        }
    }

    private func pickPlaces(_ folder: Folder, inside: [Place]) {
        sheet = .pick(title: "Add to \(folder.name)", exclude: Set(inside.map(\.id)), confirm: "Add", onDone: { ids in
            await store.addToFolder(folder.id, ids)
            store.show("Added \(Fmt.plural(ids.count, "place"))")
        })
    }
}
