import SwiftUI
import UIKit

/// The kinds of booking, with their names, colours and symbols (as on the web).
enum BookingKind: String, CaseIterable, Identifiable {
    case flight, hotel, reservation, tour, car, other
    var id: String { rawValue }

    init(_ raw: String) { self = BookingKind(rawValue: raw) ?? .other }

    var label: String {
        switch self {
        case .flight: "Flight"
        case .hotel: "Stay"
        case .reservation: "Table"
        case .tour: "Tour"
        case .car: "Car"
        case .other: "Booking"
        }
    }

    /// The filter chip's name.
    var plural: String {
        switch self {
        case .flight: "Flights"
        case .hotel: "Stays"
        case .reservation: "Tables"
        case .tour: "Tours"
        case .car: "Cars"
        case .other: "Other"
        }
    }

    /// The name in the form's Type picker.
    var formLabel: String {
        switch self {
        case .flight: "Flight"
        case .hotel: "Hotel or stay"
        case .reservation: "Table reservation"
        case .tour: "Tour or experience"
        case .car: "Car rental"
        case .other: "Other"
        }
    }

    var symbol: String {
        switch self {
        case .flight: "airplane"
        case .hotel: "bed.double.fill"
        case .reservation: "fork.knife"
        case .tour: "ticket.fill"
        case .car: "car.fill"
        case .other: "tag.fill"
        }
    }

    var color: Color {
        switch self {
        case .flight: Theme.blue
        case .hotel: Theme.indigo
        case .reservation: Theme.gold
        case .tour: Theme.teal
        case .car: Theme.green
        case .other: Theme.gray
        }
    }
}

/// Dates on bookings are local wall-clock times as printed ("2026-11-07T19:25"), with no time zone.
enum BookingTime {
    private static func formatter(_ format: String) -> DateFormatter {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = format
        return f
    }

    private static let withTime = formatter("yyyy-MM-dd'T'HH:mm")
    private static let dayOnly = formatter("yyyy-MM-dd")

    static func date(_ value: String) -> Date? {
        value.count > 10 ? withTime.date(from: value) : dayOnly.date(from: value)
    }

    static func string(_ date: Date, time: Bool) -> String {
        (time ? withTime : dayOnly).string(from: date)
    }

    static func addDays(_ iso: String, _ n: Int) -> String {
        guard let day = Fmt.day(iso), let moved = Calendar.current.date(byAdding: .day, value: n, to: day) else { return iso }
        return Fmt.iso(moved)
    }

    static func days(from a: String, to b: String) -> Int {
        guard let x = Fmt.day(a), let y = Fmt.day(b) else { return 0 }
        return Calendar.current.dateComponents([.day], from: x, to: y).day ?? 0
    }
}

extension Booking {
    var bookingKind: BookingKind { BookingKind(kind) }

    /// The line under the title and the line under that, as on the web's booking cards.
    var details: (sub: String, meta: String) {
        let clock = { (t: String?) in t.map(Fmt.clock) }
        switch bookingKind {
        case .flight:
            let sub = [startTime.map { "Departs \(Fmt.clock($0))" }, notes].compactMap { $0 }.joined(separator: " · ")
            var meta = ""
            if endAt != nil {
                let otherDay = endDay != startDay ? endDay.map(Fmt.shortDay) : nil
                meta = "Lands " + [otherDay, clock(endTime)].compactMap { $0 }.joined(separator: ", ")
            }
            return (sub, meta.trimmingCharacters(in: .whitespaces))
        case .hotel:
            let nights = startDay.flatMap { s in endDay.map { BookingTime.days(from: s, to: $0) } } ?? 0
            let sub = [startTime.map { "Check-in from \(Fmt.clock($0))" } ?? "Check-in", nights > 0 ? Fmt.plural(nights, "night") : nil]
                .compactMap { $0 }.joined(separator: " · ")
            return (sub, address ?? "")
        case .reservation:
            let sub = [partySize.map { "Table for \($0)" } ?? "Reservation", clock(startTime)].compactMap { $0 }.joined(separator: " · ")
            return (sub, address ?? "")
        case .car:
            let sub = [startTime.map { "Pick-up \(Fmt.clock($0))" }, endDay.map { "Drop-off \(Fmt.shortDay($0))" }]
                .compactMap { $0 }.joined(separator: " · ")
            return (sub, [origin, destination].compactMap { $0 }.joined(separator: " → "))
        case .tour, .other:
            return ([clock(startTime), notes].compactMap { $0 }.joined(separator: " · "), address ?? "")
        }
    }
}

/// The Bookings tab (every trip's bookings), or one trip's bookings when `tripId` is set.
struct BookingsView: View {
    var tripId: String?
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @State private var kind = "all"
    @State private var tripFilter = "all"
    @State private var showPast = false
    @State private var acting: Booking?
    @State private var lounges: Booking?
    /// Flight-and-trip date clashes the person chose to keep ("<flight id>:<trip start>").
    @AppStorage("bookings.kept") private var keptRaw = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if tripId == nil { header }
                content
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 40)
        }
        .background(Theme.background.ignoresSafeArea())
        .toolbar(tripId == nil ? .hidden : .automatic, for: .navigationBar)
        .navigationTitle(tripId == nil ? "" : "Bookings")
        .toolbar {
            if let tripId {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { router.bookingRequest = Router.BookingRequest(tripId: tripId) } label: { Image(systemName: "plus") }
                        .accessibilityLabel("Add a booking")
                }
            }
        }
        .refreshable { await store.reloadBookings() }
        .task { if !store.bookingsLoaded { await store.reloadBookings() } }
        .confirmationDialog(acting?.title ?? "", isPresented: Binding(get: { acting != nil }, set: { if !$0 { acting = nil } }),
                            titleVisibility: .visible, presenting: acting) { booking in
            actions(for: booking)
        }
        .sheet(item: $lounges) { booking in LoungesSheet(booking: booking) }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 10) {
                Spacer()
                RoundIconButton(symbol: "plus", label: "Add a booking") { addBooking() }
                ProfileButton()
            }
            .padding(.top, 8)
            Text("Bookings").font(Theme.serif(32)).foregroundStyle(Theme.label).padding(.top, 8)
        }
    }

    private func addBooking() {
        let trip = tripFilter == "all" ? nil : tripFilter
        router.bookingRequest = Router.BookingRequest(tripId: tripId ?? trip)
    }

    // MARK: Lists

    private var mine: [Booking] {
        guard let tripId else { return store.bookings }
        return store.bookings.filter { $0.tripId == tripId }
    }

    @ViewBuilder private var content: some View {
        let all = mine
        let inTrip = tripId == nil && tripFilter != "all" ? all.filter { $0.tripId == tripFilter } : all
        let present = Set(inTrip.map(\.kind))
        let kindNow = present.contains(kind) ? kind : "all"
        let list = inTrip.filter { kindNow == "all" || $0.kind == kindNow }
        let today = Fmt.iso(Date())
        let upcoming = list.filter { ($0.lastDay ?? "") >= today && $0.startAt != nil }.sorted { ($0.startAt ?? "") < ($1.startAt ?? "") }
        let undated = list.filter { $0.startAt == nil }
        let past = list.filter { $0.startAt != nil && ($0.lastDay ?? "") < today }.sorted { ($0.startAt ?? "") > ($1.startAt ?? "") }

        if !store.bookingsLoaded {
            SkeletonRows().padding(.top, 20)
        } else if all.isEmpty {
            EmptyState(symbol: "airplane", color: Theme.blue, title: "No bookings yet",
                       text: "Flights and stays for trips, and tickets and tables near home, in one place. Add one from a screenshot, the confirmation email, or type it in.") {
                Button { addBooking() } label: { Label("Add a booking", systemImage: "plus") }
                    .buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 220)
            }
            .padding(.top, 24)
        } else {
            Text(nextLine(upcoming.first, today: today)).font(.subheadline).foregroundStyle(Theme.secondary).padding(.top, 2)
            filters(present: present, kindNow: kindNow)
            attention(kind: kindNow, all: all, today: today)
            if upcoming.isEmpty {
                Text("Nothing coming up\(kindNow != "all" || tripFilter != "all" ? " here" : "").")
                    .font(.subheadline).foregroundStyle(Theme.secondary).padding(.top, 24)
            } else {
                byDate(upcoming, today: today)
            }
            if !undated.isEmpty {
                DateHeading(text: "Needs a date")
                ForEach(undated) { booking in
                    card(booking)
                    Button { router.bookingRequest = Router.BookingRequest(tripId: booking.tripId, booking: booking, title: "Add date and time") } label: {
                        Label("Add date and time", systemImage: "calendar.badge.plus").font(.footnote.weight(.semibold)).foregroundStyle(Theme.link)
                    }
                    .buttonStyle(.plain).padding(.top, 6)
                }
            }
            if !past.isEmpty {
                Button { withAnimation { showPast.toggle() } } label: {
                    Text("\(showPast ? "Hide" : "Show") past bookings (\(past.count))")
                }
                .buttonStyle(PrimaryButtonStyle(tinted: true))
                .padding(.top, 24)
                if showPast { byDate(past, today: today) }
            }
            Text("Bookings stay private: shared trip links never include them.")
                .font(.footnote).foregroundStyle(Theme.secondary).padding(.top, 20)
        }
    }

    private func nextLine(_ next: Booking?, today: String) -> String {
        guard let next, let day = next.startDay else { return "Nothing coming up" }
        return "Next: \(next.title) · \(day == today ? "today" : Fmt.shortDay(day))"
    }

    @ViewBuilder private func filters(present: Set<String>, kindNow: String) -> some View {
        // Near home first, then trips: wherever there are bookings.
        let tripsWith = (store.trips.filter(\.isLocal) + store.realTrips).filter { t in mine.contains { $0.tripId == t.id } }
        if present.count > 1 || (tripId == nil && (tripsWith.count > 1 || tripFilter != "all")) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    if tripId == nil, tripsWith.count > 1 || tripFilter != "all" {
                        Menu {
                            Picker("Trip", selection: $tripFilter) {
                                Text("Everything").tag("all")
                                ForEach(tripsWith) { Text($0.name).tag($0.id) }
                            }
                        } label: {
                            HStack(spacing: 5) {
                                Text(tripsWith.first { $0.id == tripFilter }?.name ?? "Everything").font(.subheadline.weight(.medium))
                                Image(systemName: "chevron.down").font(.caption2.weight(.bold))
                            }
                            .foregroundStyle(Theme.label)
                            .padding(.horizontal, 12).padding(.vertical, 7)
                            .background(Theme.cell, in: Capsule())
                            .overlay(Capsule().strokeBorder(Theme.border))
                        }
                    }
                    if present.count > 1 {
                        FilterChip(label: "All", isOn: kindNow == "all") { kind = "all" }
                        ForEach(BookingKind.allCases.filter { present.contains($0.rawValue) }) { k in
                            FilterChip(label: k.plural, isOn: kindNow == k.rawValue) { kind = k.rawValue }
                        }
                    }
                }
            }
            .padding(.top, 14)
        }
    }

    @ViewBuilder private func byDate(_ list: [Booking], today: String) -> some View {
        let groups = Dictionary(grouping: list) { $0.startDay ?? "" }
        let days = list.compactMap(\.startDay).reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }
        ForEach(days, id: \.self) { day in
            DateHeading(text: (day == today ? "Today · " : "") + Fmt.shortDay(day))
            ForEach(groups[day] ?? []) { booking in card(booking) }
        }
    }

    private func card(_ booking: Booking) -> some View {
        BookingCard(booking: booking, tripName: tripId == nil && tripFilter == "all" ? booking.tripName : nil,
                    onTap: { acting = booking }, onLounges: { lounges = booking })
            .padding(.top, 8)
    }

    // MARK: Actions

    @ViewBuilder private func actions(for booking: Booking) -> some View {
        if booking.bookingKind == .flight, let origin = booking.origin, Features.isOn("lounges") {
            Button("Airport lounges at \(origin)") { lounges = booking }
        }
        Button("Edit") { router.bookingRequest = Router.BookingRequest(tripId: booking.tripId, booking: booking) }
        if let placeId = booking.placeId {
            Button("Open place") { router.push(.place(id: placeId, tripId: booking.tripId)) }
        }
        if let code = booking.confirmation {
            Button("Copy confirmation number") {
                UIPasteboard.general.string = code
                store.show("Copied")
            }
        }
        Button("Delete booking", role: .destructive) {
            Task {
                if await store.tripCall("DELETE", "/v1/trips/\(booking.tripId)/bookings/\(booking.id)") != nil {
                    await store.reloadBookings()
                    store.show("Booking deleted")
                }
            }
        }
    }

    // MARK: Needs your attention

    private var kept: Set<String> { Set(keptRaw.split(separator: "|").map(String.init)) }

    /// What needs doing before upcoming trips: a first flight that lands on another day than the trip starts, and
    /// nights with no stay booked (per city on a multi-city trip).
    @ViewBuilder private func attention(kind: String, all: [Booking], today: String) -> some View {
        let items = attentionItems(kind: kind, all: all, today: today)
        if !items.isEmpty {
            DateHeading(text: "Needs your attention")
            ForEach(items) { item in
                AttentionCard(item: item, onKeep: { key in
                    keptRaw = (Array(kept) + [key]).suffix(50).joined(separator: "|")
                })
                .padding(.top, 8)
            }
        }
    }

    private func attentionItems(kind: String, all: [Booking], today: String) -> [AttentionItem] {
        var out: [AttentionItem] = []
        let trips = store.realTrips.filter { tripId == nil ? (tripFilter == "all" || $0.id == tripFilter) : $0.id == tripId }
        for t in trips {
            guard let start = t.startDate, t.dayCount > 0 else { continue }
            let end = BookingTime.addDays(start, t.dayCount - 1)
            if end < today || start > BookingTime.addDays(today, 180) { continue }
            let ofTrip = all.filter { $0.tripId == t.id }
            if kind == "all" || kind == "flight",
               let flight = ofTrip.filter({ $0.bookingKind == .flight && $0.startAt != nil }).min(by: { ($0.startAt ?? "") < ($1.startAt ?? "") }),
               let lands = flight.endDay ?? flight.startDay {
                let gap = BookingTime.days(from: start, to: lands)
                let key = "\(flight.id):\(start)"
                if gap != 0, abs(gap) <= 3, start > today, !kept.contains(key) {
                    out.append(AttentionItem(id: key, symbol: "exclamationmark.triangle.fill", color: Theme.warn,
                                             title: "\(flight.title) lands \(Fmt.shortDay(lands)), but your \(t.name) trip starts \(Fmt.shortDay(start))",
                                             subtitle: nil, action: .moveTrip(tripId: t.id, date: lands)))
                }
            }
            guard kind == "all" || kind == "hotel" else { continue }
            let stays = ofTrip.filter { $0.bookingKind == .hotel && $0.startDay != nil }
            func covered(_ night: String) -> Bool {
                stays.contains { h in
                    guard let checkIn = h.startDay else { return false }
                    return checkIn <= night && night < (h.endDay ?? BookingTime.addDays(checkIn, 1))
                }
            }
            let stops = (t.stops ?? []).isEmpty
                ? [TripStop(city: t.city, country: t.country, days: t.dayCount, startDay: 1, endDay: t.dayCount)]
                : t.stops ?? []
            for stop in stops {
                // The nights in this city: its days except the trip's last (you leave that day).
                let lastNight = min(stop.endDay, t.dayCount - 1)
                guard stop.startDay <= lastNight else { continue }
                let open = (stop.startDay...lastNight).map { BookingTime.addDays(start, $0 - 1) }.filter { $0 >= today && !covered($0) }
                guard let first = open.first, let last = open.last else { continue }
                let checkOut = BookingTime.addDays(last, 1)
                let range = Fmt.day(first).flatMap { a in Fmt.day(checkOut).map { Fmt.range(a, $0) } } ?? first
                let city = stops.count > 1 || stop.city != t.name ? " in \(stop.city)" : ""
                out.append(AttentionItem(id: "\(t.id):\(stop.city):\(first)", symbol: "bed.double.fill", color: Theme.indigo,
                                         title: "No hotel booked yet\(city)",
                                         subtitle: "\(t.name) · \(range) · \(Fmt.plural(open.count, "night"))",
                                         action: .addStay(tripId: t.id, city: stop.city, checkIn: first, checkOut: checkOut)))
            }
        }
        return out
    }
}

struct AttentionItem: Identifiable {
    enum Action {
        case moveTrip(tripId: String, date: String)
        case addStay(tripId: String, city: String, checkIn: String, checkOut: String)
    }

    let id: String
    let symbol: String
    let color: Color
    let title: String
    let subtitle: String?
    let action: Action
}

private struct AttentionCard: View {
    let item: AttentionItem
    let onKeep: (String) -> Void
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router

    var body: some View {
        Card(padding: 14) {
            HStack(alignment: .top, spacing: 12) {
                SymbolTile(symbol: item.symbol, color: item.color)
                VStack(alignment: .leading, spacing: 4) {
                    Text(item.title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                        .fixedSize(horizontal: false, vertical: true)
                    if let subtitle = item.subtitle {
                        Text(subtitle).font(.footnote).foregroundStyle(Theme.secondary)
                    }
                    HStack(spacing: 14) {
                        switch item.action {
                        case let .moveTrip(tripId, date):
                            Button("Move trip to \(Fmt.day(date)?.formatted(.dateTime.month(.abbreviated).day()) ?? date)") {
                                Task {
                                    if await store.tripCall("PATCH", "/v1/trips/\(tripId)", ["start_date": date]) != nil {
                                        store.show("Trip now starts \(Fmt.shortDay(date))")
                                    }
                                }
                            }
                            .buttonStyle(PrimaryButtonStyle(compact: true)).fixedSize()
                            Button("Keep both") { onKeep(item.id) }
                                .font(.footnote.weight(.semibold)).foregroundStyle(Theme.link)
                        case let .addStay(tripId, city, checkIn, checkOut):
                            Button {
                                var fields = BookingFields()
                                fields.kind = .hotel
                                fields.startAt = checkIn
                                fields.endAt = checkOut
                                router.bookingRequest = Router.BookingRequest(tripId: tripId, fields: fields, title: "A stay in \(city)")
                            } label: { Label("Add a stay", systemImage: "plus") }
                                .buttonStyle(PrimaryButtonStyle(compact: true)).fixedSize()
                        }
                    }
                    .buttonStyle(.plain)
                    .padding(.top, 4)
                }
                Spacer(minLength: 0)
            }
        }
    }
}

/// "TODAY · SAT, OCT 24" above a day's bookings.
private struct DateHeading: View {
    let text: String
    var body: some View {
        Eyebrow(text: text, color: Theme.secondary).padding(.top, 22)
    }
}

/// One booking: a flight as a boarding pass, everything else as a card. Tapping it opens its options.
struct BookingCard: View {
    let booking: Booking
    var tripName: String?
    let onTap: () -> Void
    let onLounges: () -> Void
    @Environment(Router.self) private var router

    var body: some View {
        Card(padding: 14) {
            if booking.bookingKind == .flight, booking.origin != nil || booking.destination != nil {
                pass
            } else {
                standard
            }
            if let notes = booking.notes, booking.bookingKind == .flight, booking.origin != nil || booking.destination != nil {
                Text(notes).font(.footnote).foregroundStyle(Theme.secondary).padding(.top, 8)
            }
            actionRow
        }
        .contentShape(Rectangle())
        .onTapGesture(perform: onTap)
        .accessibilityElement(children: .contain)
        .accessibilityAction(named: "Options", onTap)
    }

    /// A flight: the airports large with departure and arrival times, then flight, date and reference.
    private var pass: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .center) {
                airport(booking.origin, booking.startTime, plus: 0, alignment: .leading)
                Spacer(minLength: 8)
                HStack(spacing: 6) {
                    Rectangle().fill(Theme.border).frame(height: 1)
                    Image(systemName: "airplane").font(.footnote).foregroundStyle(Theme.blue)
                    Rectangle().fill(Theme.border).frame(height: 1)
                }
                .frame(maxWidth: 110)
                Spacer(minLength: 8)
                airport(booking.destination, booking.endTime, plus: overnight, alignment: .trailing)
            }
            Line().stroke(style: StrokeStyle(lineWidth: 1, dash: [4, 4])).foregroundStyle(Theme.border).frame(height: 1)
            HStack(alignment: .top, spacing: 18) {
                field("Flight", booking.title)
                if let day = booking.startDay { field("Date", Fmt.shortDay(day)) }
                if let code = booking.confirmation { field("Confirmation", code, mono: true) }
                Spacer(minLength: 0)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Flight \(booking.title)\(booking.origin.map { " from \($0)" } ?? "")\(booking.destination.map { " to \($0)" } ?? "")")
    }

    private var overnight: Int {
        guard let s = booking.startDay, let e = booking.endDay, e > s else { return 0 }
        return BookingTime.days(from: s, to: e)
    }

    private func airport(_ code: String?, _ time: String?, plus: Int, alignment: HorizontalAlignment) -> some View {
        VStack(alignment: alignment, spacing: 2) {
            Text(code ?? "—").font(Theme.serif(30, weight: .bold)).foregroundStyle(Theme.label).lineLimit(1).minimumScaleFactor(0.6)
            HStack(spacing: 2) {
                Text(time.map(Fmt.clock) ?? " ").font(.footnote.weight(.medium)).foregroundStyle(Theme.secondary)
                if plus > 0 { Text("+\(plus)").font(.caption2.weight(.bold)).foregroundStyle(Theme.warn).baselineOffset(5) }
            }
        }
    }

    private func field(_ label: String, _ value: String, mono: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased()).font(.system(size: 9, weight: .semibold)).kerning(1).foregroundStyle(Theme.tertiary)
            Text(value).font(mono ? .footnote.monospaced().weight(.semibold) : .footnote.weight(.semibold)).foregroundStyle(Theme.label).lineLimit(1)
        }
    }

    private var standard: some View {
        let kind = booking.bookingKind
        let details = booking.details
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                SymbolTile(symbol: kind.symbol, color: kind.color)
                VStack(alignment: .leading, spacing: 2) {
                    Text(booking.title).font(.body.weight(.semibold)).foregroundStyle(Theme.label).lineLimit(2)
                    if !details.sub.isEmpty { Text(details.sub).font(.footnote).foregroundStyle(Theme.secondary) }
                }
                Spacer(minLength: 4)
                Chip(text: kind.label, color: kind.color)
            }
            if !details.meta.isEmpty || booking.confirmation != nil {
                HStack(alignment: .firstTextBaseline) {
                    Text(details.meta).font(.footnote).foregroundStyle(Theme.secondary).lineLimit(2)
                    Spacer(minLength: 8)
                    if let code = booking.confirmation {
                        Text(code).font(.footnote.monospaced().weight(.semibold)).foregroundStyle(Theme.label)
                    }
                }
            }
        }
    }

    @ViewBuilder private var actionRow: some View {
        let directions = booking.bookingKind == .hotel ? booking.address : nil
        let lounges = booking.bookingKind == .flight && Features.isOn("lounges") ? booking.origin : nil
        if tripName != nil || directions != nil || booking.placeId != nil || lounges != nil {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 14) {
                    if let tripName {
                        Button { router.push(.trip(id: booking.tripId)) } label: {
                            Label(tripName, systemImage: "suitcase").lineLimit(1)
                        }
                    }
                    if let address = directions {
                        Button {
                            var c = URLComponents(string: "https://www.google.com/maps/search/")!
                            c.queryItems = [.init(name: "api", value: "1"), .init(name: "query", value: "\(booking.title) \(address)")]
                            Links.open(c.url)
                        } label: { Label("Directions", systemImage: "arrow.triangle.turn.up.right.diamond") }
                    }
                    if let placeId = booking.placeId {
                        Button { router.push(.place(id: placeId, tripId: booking.tripId)) } label: { Label("Open place", systemImage: "mappin") }
                    }
                    if let origin = lounges {
                        Button(action: onLounges) { Label("Lounges at \(origin)", systemImage: "sparkles") }
                    }
                }
                .font(.footnote.weight(.semibold))
                .foregroundStyle(Theme.link)
                .buttonStyle(.plain)
            }
            .padding(.top, 12)
        }
    }
}

private struct Line: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: 0, y: rect.midY))
        path.addLine(to: CGPoint(x: rect.width, y: rect.midY))
        return path
    }
}

/// Lounges at the airport a flight leaves from: name, terminal, how to get in.
struct LoungesSheet: View {
    let booking: Booking
    @Environment(\.dismiss) private var dismiss
    @State private var result: LoungeResult?
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                if let error {
                    Text(error).foregroundStyle(Theme.secondary)
                } else if let result {
                    switch result.status {
                    case "no_airport":
                        Text("We couldn't tell which airport this is. Edit the flight and put the departure airport's code (like JFK) in From.")
                            .foregroundStyle(Theme.secondary)
                    case "error":
                        Text("Couldn't look up lounges right now. Try again in a moment.").foregroundStyle(Theme.secondary)
                    default:
                        if result.lounges.isEmpty {
                            Text("No lounges we're confident about at \(result.airportName ?? booking.origin ?? "this airport").")
                                .foregroundStyle(Theme.secondary)
                        } else {
                            Section {
                                ForEach(result.lounges, id: \.self) { lounge in
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(lounge.name).font(.body.weight(.semibold))
                                        Text([lounge.terminal, lounge.location, lounge.hours.map { "Open \($0)" }].compactMap { $0 }.joined(separator: " · ")
                                            .nonEmpty ?? "Terminal not confirmed")
                                            .font(.footnote).foregroundStyle(Theme.secondary)
                                        Text(lounge.access.isEmpty ? "Access rules not confirmed" : "Access: " + lounge.access.joined(separator: " · "))
                                            .font(.footnote).foregroundStyle(Theme.secondary)
                                    }
                                    .padding(.vertical, 2)
                                }
                            } header: {
                                Text(result.airportName ?? booking.origin ?? "")
                            } footer: {
                                Text("From Claude's knowledge, not a live feed. Lounges change hours, terminals and access rules, so check with the airport, your card or your airline before you rely on one.")
                            }
                        }
                    }
                } else {
                    HStack(spacing: 10) { ProgressView(); Text("Looking up lounges…").foregroundStyle(Theme.secondary) }
                }
            }
            .listStyle(.insetGrouped)
            .tripBackground()
            .navigationTitle("Lounges at \(booking.origin ?? "the airport")")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .task {
            do {
                result = try await API.shared.get("/v1/trips/\(booking.tripId)/bookings/\(booking.id)/lounges")
            } catch { self.error = error.localizedDescription }
        }
    }
}

extension String {
    /// nil for an empty string, for chaining with ??.
    var nonEmpty: String? { isEmpty ? nil : self }
}
