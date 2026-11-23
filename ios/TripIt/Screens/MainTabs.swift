import SwiftUI

struct MainTabs: View {
    @State private var router = Router()
    @Environment(Store.self) private var store
    @Environment(Session.self) private var session
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage(RootView.pendingJoinKey) private var pendingJoin = ""

    @State private var opened: Set<AppTab> = [.home]  // tabs are built the first time they're opened, then kept
    @State private var keyboardUp = false
    @State private var searching = false

    private var tabs: [BottomBar.Item] {
        var items: [BottomBar.Item] = [
            .init(tab: .home, title: "Home", symbol: "house"),
            .init(tab: .library, title: "Library", symbol: "bookmark"),
            .init(tab: .calendar, title: "Calendar", symbol: "calendar"),
            .init(tab: .bookings, title: "Bookings", symbol: "ticket"),
        ]
        if !store.featuresOff.contains("concierge") { items.append(.init(tab: .concierge, title: "Concierge", symbol: "sparkles")) }
        return items
    }

    var body: some View {
        VStack(spacing: 0) {
            ZStack {
                tabStack(.home) { NavigationStack(path: $router.home) { HomeView().withRoutes() } }
                tabStack(.library) { NavigationStack(path: $router.library) { LibraryView().withRoutes() } }
                tabStack(.calendar) { NavigationStack(path: $router.calendar) { CalendarView(isTab: true).withRoutes() } }
                tabStack(.bookings) { NavigationStack(path: $router.bookings) { BookingsView().withRoutes() } }
                if !store.featuresOff.contains("concierge") {
                    tabStack(.concierge) { NavigationStack(path: $router.concierge) { ConciergeView().withRoutes() } }
                }
            }
            .tint(Theme.accent)
            .background(Theme.background.ignoresSafeArea(edges: .top))
            // The page sits on the black bar like a card: square at the top, rounded where it meets the bar.
            .clipShape(RoundedBottom(radius: keyboardUp ? 0 : 28))
            .modifier(ToastOverlay())
            if !keyboardUp {
                BottomBar(items: tabs, selected: router.tab, onSelect: select, onSearch: { searching = true },
                          onAdd: { router.addRequest = Router.AddRequest() })
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .background(Color.black.ignoresSafeArea())
        .animation(.easeOut(duration: 0.2), value: keyboardUp)
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { _ in keyboardUp = true }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in keyboardUp = false }
        .onChange(of: router.tab) { _, tab in opened.insert(tab) }
        .sheet(isPresented: $searching) {
            SearchSheet { route in router.push(route) }
                .environment(store)
                .tint(Theme.accent)
        }
        .environment(router)
        .sheet(isPresented: $router.showProfile) {
            NavigationStack(path: $router.profilePath) { ProfileView().withRoutes() }
                .environment(router).environment(store).environment(session)
                .modifier(ToastOverlay())
                .tint(Theme.accent)
        }
        .sheet(item: $router.addRequest) { request in
            AddPlaceSheet(request: request)
                .environment(router).environment(store)
                .tint(Theme.accent)
        }
        .sheet(item: $router.bookingRequest) { request in
            BookingSheet(request: request)
                .environment(router).environment(store)
                .modifier(ToastOverlay())
                .tint(Theme.accent)
        }
        .sheet(item: Binding(get: { store.reviewJob }, set: { store.reviewJob = $0 })) { job in
            SaveReviewSheet(job: job)
                .environment(router).environment(store)
                .modifier(ToastOverlay())
                .tint(Theme.accent)
        }
        .sheet(item: Binding(get: { store.paywall }, set: { store.paywall = $0 })) { request in
            PaywallView(request: request)
                .environment(router).environment(store)
                .tint(Theme.accent)
        }
        .task(id: pendingJoin) {
            guard !pendingJoin.isEmpty else { return }
            let token = pendingJoin
            pendingJoin = ""
            await TripInvite.join(token, store: store, router: router)
        }
        .task {
            await store.refresh()  // the saved copy shows meanwhile
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
            let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            if url.host == "upgrade" {
                // From the share sheet when the month's free video saves are used up
                let link = query.first(where: { $0.name == "url" })?.value
                if let link { PendingLink.keep(link) }
                store.paywall = PaywallRequest(link: link, message: nil)
            } else if url.host == "review", let id = query.first(where: { $0.name == "job" })?.value {
                // "Review places" in the share sheet once an import is done
                Task {
                    await store.refresh()
                    if let job = store.jobs.first(where: { $0.id == id }) { store.reviewJob = job }
                }
            } else if let link = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "url" })?.value {
                router.addRequest = Router.AddRequest(text: link)
            } else if let fragment = url.fragment {
                router.open("#" + fragment)
            }
        }
    }

    /// One tab's screens, kept alive (with their scroll position and pushed pages) while another tab is open.
    @ViewBuilder private func tabStack<Content: View>(_ tab: AppTab, @ViewBuilder content: () -> Content) -> some View {
        if opened.contains(tab) || router.tab == tab {
            content()
                .opacity(router.tab == tab ? 1 : 0)
                .allowsHitTesting(router.tab == tab)
                .accessibilityHidden(router.tab != tab)
        }
    }

    /// Tapping the open tab again goes back to its first page.
    private func select(_ tab: AppTab) {
        Haptics.tap()
        if router.tab == tab {
            withAnimation {
                switch tab {
                case .home: router.home = []
                case .library: router.library = []
                case .calendar: router.calendar = []
                case .bookings: router.bookings = []
                case .concierge: router.concierge = []
                }
            }
        } else {
            router.tab = tab
        }
    }
}

/// A rectangle with rounded bottom corners whose top runs on up past the frame, so a background that fills the
/// status bar isn't cut off there.
struct RoundedBottom: Shape {
    var radius: CGFloat
    var animatableData: CGFloat {
        get { radius }
        set { radius = newValue }
    }

    func path(in rect: CGRect) -> Path {
        var tall = rect
        tall.origin.y -= 2000
        tall.size.height += 2000
        return UnevenRoundedRectangle(bottomLeadingRadius: radius, bottomTrailingRadius: radius, style: .continuous).path(in: tall)
    }
}

/// The black bar under every tab, as in the design: a search field for your saved places, a round white + to save
/// a link or a place, then the tabs in white (open) and grey.
struct BottomBar: View {
    struct Item: Identifiable {
        let tab: AppTab
        let title: String
        let symbol: String
        var id: AppTab { tab }
    }

    let items: [Item]
    let selected: AppTab
    let onSelect: (AppTab) -> Void
    let onSearch: () -> Void
    let onAdd: () -> Void

    private static let grey = Color(red: 0.557, green: 0.541, blue: 0.525)  // #8E8A86

    var body: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                Button(action: onSearch) {
                    HStack(spacing: 12) {
                        Image(systemName: "magnifyingglass").font(.system(size: 18, weight: .light))
                        Text("Search your places").font(Theme.text(.body))
                        Spacer(minLength: 0)
                    }
                    .foregroundStyle(Color(red: 0.604, green: 0.584, blue: 0.565))  // #9A9590
                    .padding(.horizontal, 20)
                    .frame(height: 52)
                    .background(Color(red: 0.118, green: 0.118, blue: 0.118), in: Capsule())  // #1E1E1E
                    .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                Button(action: onAdd) {
                    Image(systemName: "plus").font(.system(size: 22, weight: .light))
                        .foregroundStyle(Color(red: 0.098, green: 0.067, blue: 0.043))
                        .frame(width: 52, height: 52)
                        .background(Color.white, in: Circle())
                        .shadow(color: .white.opacity(0.25), radius: 9)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Save a link or a place")
            }
            HStack(spacing: 0) {
                ForEach(items) { item in
                    let on = item.tab == selected
                    Button { onSelect(item.tab) } label: {
                        VStack(spacing: 5) {
                            Image(systemName: item.symbol).font(.system(size: 19, weight: .light))
                            Text(item.title).font(Theme.text(.footnote, weight: on ? .medium : .regular)).kerning(0.6)
                        }
                        .foregroundStyle(on ? Color.white : Self.grey)
                        .frame(maxWidth: .infinity, minHeight: 50)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(on ? .isSelected : [])
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 14)
        .padding(.bottom, 2)
        .background(Color.black)
        .environment(\.colorScheme, .dark)
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
        case .bookings(let tripId): BookingsView(tripId: tripId)
        case .edit(let tripId, let editId): EditView(tripId: tripId, editId: editId)
        case .savedEdit(let edit): SavedEditView(edit: edit)
        case .today(let tripId, let day): TodayView(tripId: tripId, day: day)
        case .packing(let tripId): PackingView(tripId: tripId)
        case .events(let tripId): EventsView(tripId: tripId)
        case .calendar: CalendarView()
        case .taste: TasteView()
        case .people: PeopleAdminView()
        case .usage: UsageView()
        }
    }
}

private struct RootToolbar: ViewModifier {
    let add: Bool
    @Environment(Router.self) private var router

    func body(content: Content) -> some View {
        content.toolbar {
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
