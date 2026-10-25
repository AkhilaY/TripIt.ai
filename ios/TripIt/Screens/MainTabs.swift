import SwiftUI

struct MainTabs: View {
    @State private var router = Router()
    @Environment(Store.self) private var store
    @Environment(Session.self) private var session
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        TabView(selection: $router.tab) {
            NavigationStack(path: $router.home) { HomeView().withRoutes() }
                .tabItem { Label("Home", systemImage: "house") }
                .tag(AppTab.home)
            NavigationStack(path: $router.library) { LibraryView().withRoutes() }
                .tabItem { Label("Library", systemImage: "bookmark") }
                .tag(AppTab.library)
            NavigationStack(path: $router.discover) { WebScreen(hash: "#/discover", isRoot: true).withRoutes() }
                .tabItem { Label("Discover", systemImage: "safari") }
                .tag(AppTab.discover)
            NavigationStack(path: $router.bookings) { WebScreen(hash: "#/bookings", isRoot: true).withRoutes() }
                .tabItem { Label("Bookings", systemImage: "suitcase") }
                .tag(AppTab.bookings)
            NavigationStack(path: $router.concierge) { WebScreen(hash: "#/concierge", isRoot: true).withRoutes() }
                .tabItem { Label("Concierge", systemImage: "sparkles") }
                .tag(AppTab.concierge)
        }
        .environment(router)
        .modifier(ToastOverlay())
        .sheet(isPresented: $router.showProfile) {
            NavigationStack(path: $router.profilePath) { ProfileView().withRoutes() }
                .environment(router).environment(store).environment(session)
                .modifier(ToastOverlay())
        }
        .sheet(item: $router.addRequest) { request in
            AddPlaceSheet(request: request)
                .environment(router).environment(store)
        }
        .sheet(item: Binding(get: { store.reviewJob }, set: { store.reviewJob = $0 })) { job in
            SaveReviewSheet(job: job)
                .environment(router).environment(store)
                .modifier(ToastOverlay())
        }
        .task {
            if !store.loaded { await store.refresh() }
            await Push.shared.registerIfAllowed()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active, store.loaded { Task { await store.refresh() } }
        }
        .onReceive(NotificationCenter.default.publisher(for: Push.opened)) { note in
            guard let url = note.object as? String else { return }
            // A finished import: review its places rather than just listing them.
            if let reel = URLComponents(string: url.replacingOccurrences(of: "#/saved", with: "saved"))?.queryItems?.first(where: { $0.name == "reel" })?.value {
                Task {
                    await store.refresh()
                    if let job = store.jobs.first(where: { $0.reelId == reel }) { store.reviewJob = job } else { router.open(url) }
                }
            } else {
                router.open(url)
            }
        }
        .onOpenURL { url in
            // tripit://open?url=… from the Share Extension, or a link to the web app
            if let link = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "url" })?.value {
                router.addRequest = Router.AddRequest(text: link)
            } else if let fragment = url.fragment {
                router.open("#" + fragment)
            }
        }
    }
}

extension View {
    /// Lets this stack push any of the app's screens.
    func withRoutes() -> some View {
        navigationDestination(for: Route.self) { route in
            RouteView(route: route)
        }
    }

    /// The calendar on the left and your profile on the right, like the web app's main screens.
    func rootToolbar(add: Bool = false) -> some View {
        modifier(RootToolbar(add: add))
    }
}

struct RouteView: View {
    let route: Route

    var body: some View {
        switch route {
        case .place(let id, let tripId): PlaceView(placeId: id, tripId: tripId)
        case .trip(let id): TripView(tripId: id)
        case .folder(let id): FolderView(folderId: id)
        case .city(let name): CityView(city: name)
        case .map: MapTab()
        case .imports: ImportsView()
        case .reel(let id): ReelPlacesView(reelId: id)
        case .menu(let placeId): MenuView(placeId: placeId)
        case .editPlace(let tripId, let editId, let entryId): EditPlaceView(tripId: tripId, editId: editId, entryId: entryId)
        case .web(let hash): WebScreen(hash: hash)
        }
    }
}

private struct RootToolbar: ViewModifier {
    let add: Bool
    @Environment(Router.self) private var router

    func body(content: Content) -> some View {
        content.toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button { router.push(.web(hash: "#/calendar")) } label: {
                    Image(systemName: "calendar")
                }
                .accessibilityLabel("Calendar")
            }
            ToolbarItemGroup(placement: .topBarTrailing) {
                if add {
                    Button { router.addRequest = Router.AddRequest() } label: { Image(systemName: "plus") }
                        .accessibilityLabel("Add a place")
                }
                Button { router.showProfile = true } label: { Image(systemName: "person.crop.circle") }
                    .accessibilityLabel("Profile and settings")
            }
        }
    }
}
