import SwiftUI

/// The Plans tab: Calendar and Bookings in one. A day-by-day timeline of flights, stays, tables, saved events and
/// planned trip days (with a week strip to jump around), or the month calendar. + adds a booking.
struct PlansView: View {
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @AppStorage("plans.month") private var monthView = false
    @State private var result: CalendarResult? = DiskCache.load("calendar")
    @State private var error: String?
    @State private var filter = "all"
    @State private var syncing = false
    @State private var dating: CalendarItem?
    @State private var focused: String?

    private var today: String { Fmt.iso(Date()) }

    var body: some View {
        VStack(spacing: 0) {
            header.padding(.horizontal, 20)
            if monthView {
                CalendarView(isTab: true, embedded: true)
            } else {
                timeline
            }
        }
        .background(Theme.background.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .task { await load() }
        .onChange(of: router.bookingRequest == nil) { _, closed in if closed { Task { await load() } } }
        .sheet(isPresented: $syncing) { CalendarSyncSheet(feed: result?.feed) { result?.feed = $0 } }
        .sheet(item: $dating) { item in
            EventDateSheet(item: item) { Task { await load(); await store.reloadPlaces() } }
        }
        .sensoryFeedback(.selection, trigger: focused)
        .sensoryFeedback(.selection, trigger: filter)
        .sensoryFeedback(.impact(weight: .light), trigger: monthView)
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .center, spacing: 8) {
                Text("Plans").font(Theme.serif(38)).foregroundStyle(Theme.label)
                Spacer()
                RoundIconButton(symbol: monthView ? "list.bullet" : "calendar", label: monthView ? "Timeline" : "Month") {
                    withAnimation(.easeInOut(duration: 0.25)) { monthView.toggle() }
                }
                Menu {
                    Button { router.bookingRequest = Router.BookingRequest() } label: { Label("Add a booking", systemImage: "ticket") }
                    Button { syncing = true } label: { Label("Sync with your calendar", systemImage: "calendar.badge.plus") }
                } label: {
                    Image(systemName: "plus").font(.system(size: 17, weight: .regular)).foregroundStyle(Theme.accentInk)
                        .frame(width: 40, height: 40).background(Theme.accent, in: Circle())
                }
                .accessibilityLabel("Add")
                ProfileButton()
            }
            Text(subtitle).font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
        }
        .padding(.top, 12).padding(.bottom, 8)
    }

    private var subtitle: String {
        guard let trip = store.upcomingTrips.first, let start = trip.startDate else { return "Flights, stays, tables and events" }
        let days = BookingTime.days(from: today, to: start)
        return days <= 0 ? "\(trip.name) · on now" : days == 1 ? "\(trip.name) tomorrow" : "\(trip.name) in \(days) days"
    }

    private func load() async {
        do {
            let fresh: CalendarResult = try await API.shared.get("/v1/calendar")
            result = fresh
            DiskCache.save("calendar", fresh)
            error = nil
        } catch is CancellationError {
        } catch { self.error = error.localizedDescription }
    }

    // MARK: Timeline

    static let filters: [(id: String, label: String)] = [("all", "All"), ("flight", "Flights"), ("hotel", "Stays"),
                                                          ("reservation", "Tables"), ("event", "Events"), ("stop", "Places")]

    private func matches(_ item: CalendarItem) -> Bool {
        switch filter {
        case "all": item.kind != "trip"
        case "event", "stop": item.kind == filter
        default: item.kind == "booking" && item.category == filter
        }
    }

    @ViewBuilder private var timeline: some View {
        if let result {
            let days = Self.days(result.items.filter(matches), from: today)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        weekStrip(result.items) { day in
                            focused = day
                            withAnimation(.easeInOut(duration: 0.3)) { proxy.scrollTo(day, anchor: .top) }
                        }
                        chips.padding(.top, 14)
                        if days.isEmpty {
                            Text(filter == "all" ? "Nothing coming up. Bookings, saved events and trip days appear here on their dates."
                                 : "Nothing coming up here.")
                                .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary).padding(.top, 24)
                        }
                        ForEach(days) { entry in
                            dayView(entry.id, entry.items, all: result.items).id(entry.id)
                        }
                        undated(result)
                    }
                    .padding(.horizontal, 20).padding(.bottom, 40)
                }
                .refreshable { await load() }
            }
        } else if let error {
            EmptyState(symbol: "wifi.slash", title: "Couldn't load your plans", text: error) {
                Button("Try again") { Task { await load() } }.buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 200)
            }
            Spacer()
        } else {
            SkeletonRows(photo: false).padding(.top, 20).padding(.horizontal, 20)
            Spacer()
        }
    }

    /// Upcoming days with something on them, each item on its first day (a stay is shown as a band on each night).
    struct PlanDay: Identifiable {
        let id: String  // "2026-12-12"
        let items: [CalendarItem]
    }

    static func days(_ items: [CalendarItem], from today: String) -> [PlanDay] {
        var map: [String: [CalendarItem]] = [:]
        let last = BookingTime.addDays(today, 180)
        for item in items {
            guard let start = item.date else { continue }
            if item.kind == "booking", item.category == "hotel", let end = item.endDate, end > start {
                var day = start
                while day < end, day <= last {
                    if day >= today { map[day, default: []].append(item) }
                    day = BookingTime.addDays(day, 1)
                }
            } else if start >= today || (item.endDate ?? start) >= today {
                map[max(start, today), default: []].append(item)
            }
        }
        return map.keys.filter { $0 <= last }.sorted().map { day in
            PlanDay(id: day, items: (map[day] ?? []).sorted { ($0.time ?? "99") < ($1.time ?? "99") })
        }
    }

    private func weekStrip(_ items: [CalendarItem], jump: @escaping (String) -> Void) -> some View {
        let week = (0..<7).map { BookingTime.addDays(today, $0) }
        return HStack(spacing: 0) {
            ForEach(week, id: \.self) { day in
                let date = Fmt.day(day) ?? Date()
                let kinds = Set(items.filter { item in
                    guard let start = item.date, item.kind != "trip" else { return false }
                    return start == day || (start < day && (item.endDate ?? start) > day)
                }.map { Self.color(for: $0) })
                Button { jump(day) } label: {
                    VStack(spacing: 3) {
                        Text(date.formatted(.dateTime.weekday(.narrow))).font(Theme.text(.caption)).opacity(0.7)
                        Text(date.formatted(.dateTime.day())).font(Theme.text(.headline))
                        HStack(spacing: 2) {
                            ForEach(Array(kinds.prefix(3)), id: \.self) { Circle().fill($0).frame(width: 5, height: 5) }
                        }
                        .frame(height: 6)
                    }
                    .foregroundStyle(day == (focused ?? today) ? Theme.accentInk : Theme.label)
                    .frame(maxWidth: .infinity).padding(.vertical, 8)
                    .background(day == (focused ?? today) ? Theme.accent : .clear, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.top, 6)
    }

    private var chips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(Self.filters, id: \.id) { f in
                    FilterChip(label: f.label, isOn: filter == f.id) { withAnimation(.easeOut(duration: 0.2)) { filter = f.id } }
                }
            }
        }
    }

    @ViewBuilder private func dayView(_ day: String, _ items: [CalendarItem], all: [CalendarItem]) -> some View {
        let date = Fmt.day(day) ?? Date()
        let trip = all.first { $0.kind == "trip" && ($0.date ?? "") <= day && ($0.endDate ?? $0.date ?? "") >= day }
        let dayNumber = trip?.date.map { BookingTime.days(from: $0, to: day) + 1 }
        HStack(alignment: .firstTextBaseline) {
            Text((day == today ? "Today · " : "") + date.formatted(.dateTime.weekday(.wide).day().month(.wide)))
                .font(Theme.text(.headline, weight: .medium)).foregroundStyle(Theme.label)
            Spacer()
            if let trip, let n = dayNumber {
                Text("Day \(n) · \(trip.title)").font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).lineLimit(1)
            }
        }
        .padding(.top, 24).padding(.bottom, 6)
        Divider().overlay(Theme.divider)
        let stays = items.filter { $0.kind == "booking" && $0.category == "hotel" && ($0.endDate ?? "") > ($0.date ?? "") }
        ForEach(stays) { stay in stayBand(stay, day: day) }
        let stops = items.filter { $0.kind == "stop" }
        let others = items.filter { !stays.contains($0) && $0.kind != "stop" }
        ForEach(others) { item in row(item) }
        ForEach(stops.prefix(4)) { item in row(item) }
        if stops.count > 4, let tripId = stops.first?.tripId {
            Button("\(stops.count - 4) more places this day") { router.push(.today(tripId: tripId, day: dayNumber)) }
                .font(Theme.text(.footnote)).foregroundStyle(Theme.link).padding(.leading, 56).padding(.vertical, 6)
        }
    }

    private func stayBand(_ stay: CalendarItem, day: String) -> some View {
        let nights = BookingTime.days(from: stay.date ?? day, to: stay.endDate ?? day)
        let night = BookingTime.days(from: stay.date ?? day, to: day) + 1
        return Button { open(stay) } label: {
            HStack {
                Text(stay.title).font(Theme.text(.subheadline, weight: .medium)).foregroundStyle(Theme.label).lineLimit(1)
                Spacer()
                Text("Night \(night) of \(nights)").font(Theme.text(.footnote)).foregroundStyle(Theme.indigo)
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            .background(Theme.indigo.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .buttonStyle(PressStyle())
        .padding(.top, 10)
    }

    private func row(_ item: CalendarItem) -> some View {
        let color = Self.color(for: item)
        return Button { open(item) } label: {
            HStack(alignment: .top, spacing: 12) {
                Text(item.time.map(Fmt.clock) ?? item.partOfDay?.capitalized ?? "All day")
                    .font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                    .frame(width: 44, alignment: .leading).padding(.top, 2)
                VStack(alignment: .leading, spacing: 2) {
                    Text(Self.label(for: item).uppercased()).font(Theme.text(.caption2, weight: .medium)).kerning(1.4).foregroundStyle(color)
                    Text(item.title).font(Theme.text(.body)).foregroundStyle(Theme.label).multilineTextAlignment(.leading)
                    if let sub = item.subtitle, !sub.isEmpty {
                        Text(sub).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).lineLimit(2)
                    }
                }
                .padding(.leading, 12)
                .overlay(alignment: .leading) { Rectangle().fill(color).frame(width: 3) }
                Spacer(minLength: 0)
            }
            .padding(.vertical, 10)
            .contentShape(Rectangle())
        }
        .buttonStyle(PressStyle())
    }

    @ViewBuilder private func undated(_ result: CalendarResult) -> some View {
        if (filter == "all" || filter == "event") && !result.undated.isEmpty {
            Text("Saved events without a date").font(Theme.text(.headline, weight: .medium)).foregroundStyle(Theme.label)
                .padding(.top, 28).padding(.bottom, 6)
            Divider().overlay(Theme.divider)
            ForEach(result.undated) { item in
                HStack(spacing: 12) {
                    row(item)
                    Button("Set date") { dating = item }.buttonStyle(PrimaryButtonStyle(tinted: true, compact: true)).fixedSize()
                }
            }
        }
    }

    // MARK: Kinds

    static func label(for item: CalendarItem) -> String {
        switch item.kind {
        case "booking":
            switch item.category {
            case "flight": "Flight"
            case "hotel": "Stay"
            case "reservation": "Table"
            case "tour": "Tour"
            case "car": "Car"
            default: "Booking"
            }
        case "event": "Event"
        case "stop": "Planned"
        default: "Trip"
        }
    }

    static func color(for item: CalendarItem) -> Color {
        switch item.kind {
        case "booking":
            switch item.category {
            case "flight": Theme.blue
            case "hotel": Theme.indigo
            case "reservation": Theme.ok
            default: Theme.dynamic(0x8A6A4A, 0xC4A27E)
            }
        case "event": CalendarView.color("event")
        case "stop": Theme.secondary
        default: CalendarView.color("trip")
        }
    }

    private func open(_ item: CalendarItem) {
        switch item.kind {
        case "booking":
            if let tripId = item.tripId { router.push(.bookings(tripId: tripId)) }
        case "trip":
            if let tripId = item.tripId { router.push(.trip(id: tripId)) }
        default:
            if let placeId = item.placeId { router.push(.place(id: placeId, tripId: item.kind == "stop" ? item.tripId : nil)) }
        }
    }
}
