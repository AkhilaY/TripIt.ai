import SwiftUI

/// Home, as in the design: a box of scenery with today's date and the greeting, today's edits (made from your saves,
/// plus your next trip's curated ones), your trips, what's next, this weekend at home and what you saved lately.
struct HomeView: View {
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(Session.self) private var session
    @State private var location = Location.shared
    @State private var shuffle = 0
    @State private var settingHome = false
    @State private var homeCity = ""
    @State private var tripEdits: [HomeEdit] = []

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                headerBox
                if !store.loaded, let error = store.error {
                    EmptyState(symbol: "wifi.slash", title: "Can't reach The Travel Edit", text: error) {
                        Button("Try again") { Task { await store.refresh() } }.buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 200)
                    }
                } else if !store.loaded {
                    SkeletonRows().padding(.top, 24)
                } else {
                    ForEach(store.jobs.filter(\.isActive)) { job in
                        ImportProgressCard(job: job).padding(.top, 16)
                    }
                    if store.saved.isEmpty && store.realTrips.isEmpty {
                        GetStartedCard().padding(.top, 20)
                    }
                    if let active = store.activeTrip {
                        TravelHome(trip: active.trip, day: active.day)
                    }
                    edits
                    if store.activeTrip == nil {
                        comingUp
                        NextUpCard(includeTrips: false).padding(.top, 28)
                        weekend.padding(.top, 40)
                    }
                    recent
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 40)
        }
        .background(Theme.background.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .refreshable { await store.refresh() }
        .task(id: store.upcomingTrips.first?.id) {
            guard let trip = store.upcomingTrips.first else { tripEdits = []; return }
            if store.tripDetails[trip.id] == nil { _ = try? await store.loadTrip(trip.id) }
            await loadTripEdits(trip)
        }
        .onAppear { location.request() }
        .task { if !store.bookingsLoaded { await store.reloadBookings() } }
        .alert("Your home city", isPresented: $settingHome) {
            TextField("e.g. Atlanta", text: $homeCity)
            Button("Cancel", role: .cancel) {}
            Button("Save") { Task { _ = await store.setHome(homeCity.trimmingCharacters(in: .whitespaces)) } }
        } message: {
            Text("Places you save there are kept as Around your city, with no trip needed.")
        }
    }

    // MARK: Header

    /// The greeting in a box of slowly changing scenery (the welcome screen's), still while another page covers it.
    private var headerBox: some View {
        WelcomeScenery(paused: router.tab != .home || !router.home.isEmpty, fullBleed: false, gradient: WelcomeSceneryStyle.header) { current, textOpacity in
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .center) {
                    Text([Self.today.string(from: Date()), headerCity].compactMap { $0 }.joined(separator: " · "))
                        .font(Theme.text(.subheadline)).kerning(0.3)
                        .foregroundStyle(.white.opacity(0.92))
                        .lineLimit(1)
                    Spacer(minLength: 8)
                    ProfileButton(onPhoto: true)
                }
                Spacer(minLength: 0)
                Text(greeting)
                    .font(Theme.serif(34))
                    .foregroundStyle(.white)
                    .lineLimit(2).minimumScaleFactor(0.8)
                    .accessibilityAddTraits(.isHeader)
                Text(WelcomeSceneryStyle.scenes[current].place)
                    .font(Theme.text(.footnote)).kerning(0.6)
                    .foregroundStyle(.white.opacity(0.78))
                    .opacity(textOpacity)
                    .padding(.top, 6)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, 20).padding(.top, 14).padding(.bottom, 20)
        }
        .frame(height: 300)
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
        .padding(.top, 8)
    }

    /// Where you are: today's stop during a trip, otherwise home.
    private var headerCity: String? {
        if let active = store.activeTrip {
            let stops = active.trip.stops ?? []
            return stops.first { active.day >= $0.startDay && active.day <= $0.endDay }?.city ?? active.trip.city
        }
        return store.home?.city
    }

    private static let today: DateFormatter = {
        let f = DateFormatter(); f.setLocalizedDateFormatFromTemplate("EEEE d MMMM"); return f
    }()

    private var greeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        let part = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening"
        let first = session.me?.name.split(separator: " ").first.map(String.init) ?? ""
        return first.isEmpty ? part : "\(part), \(first)"
    }

    // MARK: Today's edits

    private var homeEdits: [HomeEdit] {
        tripEdits + HomeEdits.make(saved: store.saved, home: store.home?.city, open: openPlaces, trips: store.realTrips)
    }

    @ViewBuilder private var edits: some View {
        let all = homeEdits
        if !all.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("Today's edits").font(Theme.serif(25)).foregroundStyle(Theme.label)
                Text("Picked from your saves, new each day").font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
            }
            .padding(.top, 36)
            ScrollView(.horizontal, showsIndicators: false) {
                LazyHStack(alignment: .top, spacing: 12) {
                    ForEach(all) { edit in
                        Button { router.push(edit.route) } label: {
                            HomeEditCard(edit: edit, fallback: edit.placeIds.first.flatMap { store.place($0) })
                        }
                        .buttonStyle(.plain)
                    }
                }
                .scrollTargetLayout()
                .padding(.horizontal, 20)
            }
            .scrollTargetBehavior(.viewAligned)
            .padding(.horizontal, -20)
            .padding(.top, 16)
        }
    }

    /// The next trip's AI-curated edits, as they were last made (nothing is curated from here).
    private func loadTripEdits(_ trip: Trip) async {
        let key = "home-edits-\(trip.id)"
        if tripEdits.isEmpty, let cached: TripEdits = DiskCache.load(key) { tripEdits = HomeEdits.fromTrip(trip, cached) }
        guard let fresh: TripEdits = try? await API.shared.get("/v1/trips/\(trip.id)/edits") else { return }
        DiskCache.save(key, fresh)
        tripEdits = HomeEdits.fromTrip(trip, fresh)
    }

    // MARK: This weekend

    @ViewBuilder private var weekend: some View {
        if let home = store.home {
            let picks = WeekendPicks.make(from: store.saved.filter { store.isHome($0) && !$0.visited }, seed: shuffle)
            VStack(alignment: .leading, spacing: 6) {
                Text("This weekend in \(home.city)").font(Theme.serif(25)).foregroundStyle(Theme.label)
                Text(picks.isEmpty ? "Save places around \(home.city) and we'll pick a couple for the weekend from the ones you haven't been to."
                                   : "Picked from places you've saved but haven't been to yet")
                    .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !picks.isEmpty {
                VStack(spacing: 0) {
                    ForEach(picks, id: \.place.id) { pick in
                        Divider().overlay(Theme.border)
                        NavigationLink(value: Route.place(id: pick.place.id, tripId: nil)) {
                            HStack(spacing: 16) {
                                PlaceThumb(place: pick.place, size: 76)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(pick.slot).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                                    Text(pick.place.name).font(Theme.text(.headline)).foregroundStyle(Theme.label).lineLimit(1)
                                    meta(pick.place)
                                }
                                Spacer(minLength: 0)
                            }
                            .padding(.vertical, 16)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                    Divider().overlay(Theme.border)
                }
                .padding(.top, 18)
                VStack(spacing: 12) {
                    Button("Plan the weekend") { Task { await planWeekend(picks.map(\.place)) } }
                        .buttonStyle(PrimaryButtonStyle())
                    Button("Show other ideas") { withAnimation { shuffle += 1 } }
                        .buttonStyle(PrimaryButtonStyle(tinted: true))
                }
                .padding(.top, 22)
            }
        } else {
            Card(padding: 18) {
                Text("Your city").font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                Text("Where's home?").font(Theme.text(.headline)).foregroundStyle(Theme.label).padding(.top, 6)
                Text("Set your home city and places you save there are kept as Around your city, with weekend picks and what's open now.")
                    .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary).padding(.top, 4)
                    .fixedSize(horizontal: false, vertical: true)
                AccentTextButton(title: "Set home city", symbol: nil) { homeCity = ""; settingHome = true }
            }
        }
    }

    /// "Midtown · 1.6 mi · walk-in" with "Book ahead" in coral.
    private func meta(_ p: Place) -> some View {
        let distance = p.distance(from: location.current).map(Fmt.distance)
        let parts = [p.neighborhood ?? Category(p.category).label, distance].compactMap { $0 }
        return HStack(spacing: 0) {
            Text(parts.joined(separator: " · ")).foregroundStyle(Theme.secondary)
            if p.shownNeed == "required" {
                Text(" · ").foregroundStyle(Theme.secondary)
                Text(p.bookingKind == "tickets" ? "Tickets needed" : "Book ahead").foregroundStyle(Theme.attention)
            }
        }
        .font(Theme.text(.footnote)).lineLimit(1)
    }

    /// Puts the picks in a "This weekend" list and opens it.
    private func planWeekend(_ places: [Place]) async {
        let ids = places.map(\.id)
        if let folder = store.folders.first(where: { $0.name.caseInsensitiveCompare("This weekend") == .orderedSame }) {
            await store.addToFolder(folder.id, ids)
            router.push(.folder(id: folder.id))
        } else if let folder = await store.createFolder("This weekend", placeIds: ids) {
            router.push(.folder(id: folder.id))
        }
    }

    /// Saved places open right now near you (or around home), the closest first.
    private var openPlaces: [Place] {
        let here = location.current
        let candidates = store.saved.filter { p in
            guard Hours.status(p.openingHours)?.isOpen == true else { return false }
            if let d = p.distance(from: here) { return d < 30_000 }
            return store.isHome(p)
        }
        return Array(candidates.sorted { ($0.distance(from: here) ?? .infinity) < ($1.distance(from: here) ?? .infinity) }.prefix(8))
    }

    // MARK: Coming up

    @ViewBuilder private var comingUp: some View {
        let trips = store.upcomingTrips
        if !trips.isEmpty {
            Text("Coming up").font(Theme.serif(25)).foregroundStyle(Theme.label).padding(.top, 40)
            if trips.count == 1, let trip = trips.first {
                tripCard(trip, width: nil).padding(.top, 14)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 12) {
                        ForEach(trips) { trip in tripCard(trip, width: 240) }
                    }
                    .padding(.horizontal, 20)
                }
                .padding(.horizontal, -20)
                .padding(.top, 14)
            }
            if let trip = trips.first, let need = needsBooking(trip) {
                Card(padding: 18) {
                    Text("\(trip.name) · before you go").font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                    Text("\(need.name) still needs \(need.bookingKind == "tickets" ? "tickets" : "a table")")
                        .font(Theme.text(.headline)).foregroundStyle(Theme.label).padding(.top, 6)
                    AccentTextButton(title: need.bookingKind == "tickets" ? "Get tickets" : "Book a table", symbol: nil) {
                        router.push(.place(id: need.id, tripId: trip.id))
                    }
                }
                .padding(.top, 24)
            }
        }
    }

    /// A trip as a photo with its countdown and name under it (`width` nil: the whole row).
    private func tripCard(_ trip: Trip, width: CGFloat?) -> some View {
        NavigationLink(value: Route.trip(id: trip.id)) {
            VStack(alignment: .leading, spacing: 0) {
                TripCover(trip: trip, width: width, height: width == nil ? 220 : 200, radius: 14)
                Text([trip.countdown, trip.dateRange].compactMap { $0 }.joined(separator: " · "))
                    .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary).lineLimit(1)
                    .padding(.top, 14)
                Text(trip.name).font(Theme.serif(20)).foregroundStyle(Theme.label).lineLimit(1).padding(.top, 4)
            }
            .frame(width: width, alignment: .leading)
            .frame(maxWidth: width == nil ? .infinity : nil, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    /// The first place on the trip that must be booked and has no reservation yet.
    private func needsBooking(_ trip: Trip) -> Place? {
        guard let detail = store.tripDetails[trip.id] else { return nil }
        let booked = Set(detail.bookings.compactMap(\.placeId))
        return detail.places.first { $0.shownNeed == "required" && !booked.contains($0.id) && !$0.suggested }
    }

    // MARK: Recent saves

    @ViewBuilder private var recent: some View {
        let weekAgo = Fmt.iso(Calendar.current.date(byAdding: .day, value: -7, to: Date()) ?? Date())
        let sorted = store.saved.sorted { $0.createdAt > $1.createdAt }
        let thisWeek = sorted.filter { $0.createdAt >= weekAgo }
        let shown = Array((thisWeek.isEmpty ? sorted : thisWeek).prefix(5))
        if !shown.isEmpty {
            HStack(alignment: .firstTextBaseline) {
                Text(thisWeek.isEmpty ? "Recently saved" : "Saved this week").font(Theme.serif(25)).foregroundStyle(Theme.label)
                Spacer()
                Button { router.tab = .library } label: {
                    Text("See all").font(Theme.text(.subheadline)).underline().foregroundStyle(Theme.link)
                }
                .buttonStyle(.plain)
            }
            .padding(.top, 44)
            VStack(spacing: 0) {
                ForEach(shown) { p in
                    Divider().overlay(Theme.border)
                    NavigationLink(value: Route.place(id: p.id, tripId: nil)) {
                        HStack(spacing: 16) {
                            PlaceThumb(place: p, size: 64)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(p.name).font(Theme.text(.headline)).foregroundStyle(Theme.label).lineLimit(1)
                                Text(store.filing(p)).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).lineLimit(1)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 14)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
                Divider().overlay(Theme.border)
            }
            .padding(.top, 14)
        } else if store.home != nil {
            EmptyState(symbol: "bookmark", title: "Nothing saved yet",
                       text: "Share a TikTok or Instagram post to The Travel Edit, paste a link, or search for a place.") {
                Button { router.addRequest = Router.AddRequest() } label: { Label("Save a place", systemImage: "plus") }
                    .buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 220)
            }
            .padding(.top, 16)
        }
    }
}

/// The profile button: your initial in a black circle (a white one over a photo), as in the design.
struct ProfileButton: View {
    var onPhoto = false
    @Environment(Router.self) private var router
    @Environment(Session.self) private var session

    var body: some View {
        Button { router.showProfile = true } label: {
            Text(initial).font(Theme.serif(18))
                .foregroundStyle(onPhoto ? Color(red: 0.098, green: 0.067, blue: 0.043) : Theme.accentInk)
                .frame(width: 44, height: 44)
                .background(onPhoto ? Color.white : Theme.accent, in: Circle())
                .frame(width: 48, height: 48)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Profile and settings")
    }

    private var initial: String {
        let source = (session.me?.name).flatMap { $0.isEmpty ? nil : $0 } ?? session.me?.email ?? "?"
        return String(source.prefix(1)).uppercased()
    }
}

/// A place's first photo at a fixed size, or its category symbol.
struct PhotoBox: View {
    let place: Place
    let width: CGFloat?
    let height: CGFloat
    var radius: CGFloat = 16

    var body: some View {
        Color.clear
            .frame(width: width, height: height)
            .frame(maxWidth: width == nil ? .infinity : nil)
            .overlay {
                RemoteImage(url: place.photos.first?.url(width: 600)) {
                    ZStack {
                        Theme.raised
                        Image(systemName: Category(place.category).symbol).font(Theme.text(.title2)).foregroundStyle(Theme.secondary)
                    }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
    }
}

/// A trip's cover photo, or a plane: a square of `size`, or `width` × `height` (a nil width fills the row).
struct TripCover: View {
    let trip: Trip
    var size: CGFloat = 56
    var width: CGFloat?
    var height: CGFloat?
    var radius: CGFloat?

    var body: some View {
        let h = height ?? size
        Color.clear
            .frame(width: height == nil ? size : width, height: h)
            .frame(maxWidth: height != nil && width == nil ? .infinity : nil)
            .overlay {
                RemoteImage(url: trip.coverPhoto?.url(width: height == nil ? Int(size * 3) : 900)) {
                    ZStack { Theme.cell; Image(systemName: "airplane").font(.system(size: min(h * 0.3, 26), weight: .light)).foregroundStyle(Theme.secondary) }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: radius ?? min(size * 0.14, 14), style: .continuous))
    }
}

/// Two places for the weekend from your unvisited saves at home: Saturday brunch or lunch, Sunday dinner.
enum WeekendPicks {
    struct Pick { let slot: String; let place: Place }

    /// "Oct 24–25" for this weekend (or just Sunday's date on a Sunday).
    static func label(now: Date = Date()) -> String {
        let (sat, sun) = days(now)
        return Fmt.range(sat ?? sun, sun)
    }

    /// This weekend's Saturday (nil on a Sunday, when it's passed) and Sunday.
    static func days(_ now: Date) -> (Date?, Date) {
        let cal = Calendar.current
        let today = cal.startOfDay(for: now)
        let weekday = cal.component(.weekday, from: today)  // Sunday = 1
        if weekday == 1 { return (nil, today) }
        let sat = cal.date(byAdding: .day, value: 7 - weekday, to: today) ?? today
        return (sat, cal.date(byAdding: .day, value: 1, to: sat) ?? sat)
    }

    static func make(from places: [Place], seed: Int, now: Date = Date()) -> [Pick] {
        let (sat, sun) = days(now)
        let eat: Set<Category> = [.food, .cafe, .dessert, .drinks]
        var pool = places.filter { eat.contains(Category($0.category)) }
        if pool.isEmpty { pool = places }
        guard !pool.isEmpty else { return [] }
        let rotated = rotate(pool.sorted { ($0.mustDo ? 0 : 1, $0.createdAt) < ($1.mustDo ? 0 : 1, $1.createdAt) }, by: seed)
        var picks: [Pick] = []
        var used = Set<String>()
        // Saturday: a café or restaurant open late morning; Sunday: a restaurant or bar open in the evening.
        if let sat, let p = rotated.first(where: { !used.contains($0.id) && [.cafe, .food, .dessert].contains(Category($0.category)) && isOpen($0, on: sat, minute: 11 * 60) }) ?? rotated.first(where: { !used.contains($0.id) }) {
            picks.append(Pick(slot: Category(p.category) == .cafe ? "Sat · Coffee" : "Sat · Brunch", place: p)); used.insert(p.id)
        }
        if let p = rotated.first(where: { !used.contains($0.id) && [.food, .drinks].contains(Category($0.category)) && isOpen($0, on: sun, minute: 19 * 60) }) ?? rotated.first(where: { !used.contains($0.id) }) {
            picks.append(Pick(slot: Category(p.category) == .drinks ? "Sun · Drinks" : "Sun · Dinner", place: p)); used.insert(p.id)
        }
        return picks
    }

    private static func rotate(_ items: [Place], by n: Int) -> [Place] {
        guard !items.isEmpty else { return items }
        let k = ((n * 2) % items.count + items.count) % items.count
        return Array(items[k...] + items[..<k])
    }

    /// Open at that time of day (true when the hours aren't known).
    static func isOpen(_ place: Place, on day: Date, minute: Int) -> Bool {
        guard let weekly = place.openingHours?.weekly, weekly.count == 7 else { return true }
        let ranges = weekly[Hours.mondayIndex(day)]
        return ranges.contains { r in
            let o = mins(r.open), c = mins(r.close)
            guard let o, let c else { return false }
            let close = c <= o ? c + 24 * 60 : c
            return minute >= o && minute < close
        }
    }

    private static func mins(_ hhmm: String) -> Int? {
        let p = hhmm.split(separator: ":").compactMap { Int($0) }
        return p.count == 2 ? p[0] * 60 + p[1] : nil
    }
}
