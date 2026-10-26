import SwiftUI

/// Home: at home it's this weekend and what's open now from your saves; then your next trip, with anything it
/// still needs, and what you saved lately and where each one was filed.
struct HomeView: View {
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(Session.self) private var session
    @State private var location = Location.shared
    @State private var shuffle = 0
    @State private var settingHome = false
    @State private var homeCity = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                header
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
                    } else {
                        NextUpCard().padding(.top, 20)
                        weekend.padding(.top, 20)
                        openNow
                        comingUp
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
            if let trip = store.upcomingTrips.first, store.tripDetails[trip.id] == nil { _ = try? await store.loadTrip(trip.id) }
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

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Eyebrow(text: [Self.today.string(from: Date()), headerCity].compactMap { $0 }.joined(separator: " · "), color: Theme.secondary)
                Spacer()
                RoundIconButton(symbol: "plus", label: "Save a place") { router.addRequest = Router.AddRequest() }
                ProfileButton()
            }
            Text(greeting).font(Theme.serif(28)).foregroundStyle(Theme.label)
        }
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

    // MARK: This weekend

    @ViewBuilder private var weekend: some View {
        if let home = store.home {
            let picks = WeekendPicks.make(from: store.saved.filter { store.isHome($0) && !$0.visited }, seed: shuffle)
            Card(radius: 18, padding: 16) {
                Eyebrow(text: "This weekend · \(WeekendPicks.label())")
                Text("Your \(home.city) weekend").font(Theme.serif(22)).foregroundStyle(Theme.label).padding(.top, 6)
                if picks.isEmpty {
                    Text("Save places around \(home.city) and we'll pick a couple for the weekend from the ones you haven't been to.")
                        .font(.subheadline).foregroundStyle(Theme.secondary).padding(.top, 4)
                } else {
                    Text("Picked from places you've saved but haven't been to yet")
                        .font(.footnote).foregroundStyle(Theme.secondary).padding(.top, 4)
                    VStack(spacing: 10) {
                        ForEach(picks, id: \.place.id) { pick in
                            NavigationLink(value: Route.place(id: pick.place.id, tripId: nil)) {
                                HStack(spacing: 12) {
                                    PlaceThumb(place: pick.place, size: 46)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Eyebrow(text: pick.slot, color: Theme.tertiary)
                                        Text(pick.place.name).font(.body.weight(.semibold)).foregroundStyle(Theme.label).lineLimit(1)
                                        meta(pick.place)
                                    }
                                    Spacer(minLength: 0)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.top, 12)
                    HStack(spacing: 8) {
                        Button("Plan the weekend") { Task { await planWeekend(picks.map(\.place)) } }
                            .buttonStyle(PrimaryButtonStyle(compact: true))
                        Button { withAnimation { shuffle += 1 } } label: { Label("Shuffle", systemImage: "shuffle") }
                            .buttonStyle(PrimaryButtonStyle(tinted: true, compact: true))
                            .fixedSize()
                    }
                    .padding(.top, 14)
                }
            }
        } else {
            Card(radius: 18, padding: 16) {
                Eyebrow(text: "Your city")
                Text("Where's home?").font(Theme.serif(22)).foregroundStyle(Theme.label).padding(.top, 6)
                Text("Set your home city and places you save there are kept as Around your city, with weekend picks and what's open now.")
                    .font(.subheadline).foregroundStyle(Theme.secondary).padding(.top, 4)
                Button("Set home city") { homeCity = ""; settingHome = true }
                    .buttonStyle(PrimaryButtonStyle(tinted: true)).padding(.top, 16)
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
                Text(p.bookingKind == "tickets" ? "Tickets needed" : "Book ahead").fontWeight(.semibold).foregroundStyle(Theme.attention)
            }
        }
        .font(.footnote).lineLimit(1)
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

    // MARK: Open now

    @ViewBuilder private var openNow: some View {
        let open = openPlaces
        if !open.isEmpty {
            SectionHeading("Open now from your saves").padding(.top, 32)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: 12) {
                    ForEach(open) { p in
                        NavigationLink(value: Route.place(id: p.id, tripId: nil)) {
                            VStack(alignment: .leading, spacing: 3) {
                                PhotoBox(place: p, width: 136, height: 96, radius: 12)
                                Text(p.name).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label).lineLimit(1).padding(.top, 6)
                                HStack(spacing: 0) {
                                    OpenStatusText(hours: p.openingHours)
                                    if let d = p.distance(from: location.current) { Text(" · " + Fmt.distance(d)).foregroundStyle(Theme.secondary) }
                                }
                                .font(.footnote).lineLimit(1)
                            }
                            .frame(width: 136, alignment: .leading)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.trailing, 20)
            }
            .padding(.trailing, -20)
            .padding(.top, 4)
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
        if let trip = store.upcomingTrips.first {
            SectionHeading("Coming up").padding(.top, 28)
            NavigationLink(value: Route.trip(id: trip.id)) {
                Card(padding: 14) {
                    HStack(spacing: 14) {
                        TripCover(trip: trip, size: 50)
                        VStack(alignment: .leading, spacing: 3) {
                            if let countdown = trip.countdown { Eyebrow(text: countdown) }
                            Text(trip.name).font(Theme.serif(18)).foregroundStyle(Theme.label).lineLimit(1)
                            Text([trip.cities.joined(separator: " → "), trip.dateRange].compactMap { $0 }.joined(separator: " · "))
                                .font(.footnote).foregroundStyle(Theme.secondary).lineLimit(1)
                        }
                        Spacer(minLength: 0)
                    }
                    if let need = needsBooking(trip) {
                        Divider().overlay(Theme.border).padding(.vertical, 12)
                        HStack(spacing: 10) {
                            Image(systemName: "bell").foregroundStyle(Theme.attention)
                            Text("\(need.name) still needs \(need.bookingKind == "tickets" ? "tickets" : "a table")")
                                .font(.subheadline).foregroundStyle(Theme.label).lineLimit(1)
                            Spacer()
                            Text("Book").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.link)
                        }
                    }
                }
            }
            .buttonStyle(.plain)
        }
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
            SectionHeading(thisWeek.isEmpty ? "Recently saved" : "Saved this week").padding(.top, 28)
            VStack(spacing: 0) {
                ForEach(Array(shown.enumerated()), id: \.element.id) { i, p in
                    NavigationLink(value: Route.place(id: p.id, tripId: nil)) {
                        HStack(spacing: 14) {
                            PlaceThumb(place: p, size: 40)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(p.name).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label).lineLimit(1)
                                Text(store.filing(p)).font(.footnote).foregroundStyle(Theme.secondary).lineLimit(1)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 10)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    if i < shown.count - 1 { Divider().overlay(Theme.divider) }
                }
            }
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

/// The profile button: your initial in a circle.
struct ProfileButton: View {
    @Environment(Router.self) private var router
    @Environment(Session.self) private var session

    var body: some View {
        Button { router.showProfile = true } label: {
            Text(initial).font(Theme.serif(16)).foregroundStyle(Theme.link)
                .frame(width: 34, height: 34)
                .background(Theme.raised, in: Circle())
                .overlay(Circle().strokeBorder(Theme.raisedBorder))
                .frame(width: 40, height: 40)
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
                        Image(systemName: Category(place.category).symbol).font(.title2).foregroundStyle(Theme.secondary)
                    }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
    }
}

/// A trip's cover photo, or a plane.
struct TripCover: View {
    let trip: Trip
    var size: CGFloat = 56

    var body: some View {
        RemoteImage(url: trip.coverPhoto?.url(width: Int(size * 3))) {
            ZStack { Theme.raised; Image(systemName: "airplane").foregroundStyle(Theme.secondary) }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: size * 0.22, style: .continuous))
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
