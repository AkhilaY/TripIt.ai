import SwiftUI

/// A trip day's bookings, worked out for the plan: the stay you're in that night, and the timed ones (flights,
/// tables, tours) with where each falls among the day's stops.
struct DayBookings {
    enum Mode: Equatable { case checkIn, night(Int, Int), checkOut, departs, lands, at }

    struct Item {
        let booking: Booking
        let mode: Mode
        let minutes: Int?  // when in the day, for placing it among the stops
    }

    var stays: [Item] = []
    var timed: [Item] = []
    private var isFirstDay = false

    init(trip: TripDetail, day: Int) {
        isFirstDay = day == 1
        guard let iso = Fmt.isoDay(start: trip.startDate, day: day) else { return }
        for b in trip.bookings {
            guard let first = b.startDay else { continue }
            let last = b.lastDay ?? first
            if b.kind == "hotel" {
                guard first <= iso, iso <= last else { continue }
                if iso == first {
                    stays.append(Item(booking: b, mode: .checkIn, minutes: nil))
                } else if iso == last {
                    stays.append(Item(booking: b, mode: .checkOut, minutes: nil))
                } else {
                    let nights = max(1, BookingTime.days(from: first, to: last))
                    stays.append(Item(booking: b, mode: .night(BookingTime.days(from: first, to: iso) + 1, nights), minutes: nil))
                }
            } else if first == iso {
                let travel = b.kind == "flight" || (b.origin != nil && b.destination != nil)
                timed.append(Item(booking: b, mode: travel ? .departs : .at, minutes: Self.minutes(b.startTime)))
            } else if b.kind == "flight" || b.origin != nil, let end = b.endDay, end == iso, first < iso {
                timed.append(Item(booking: b, mode: .lands, minutes: Self.minutes(b.endTime)))  // an overnight flight lands today
            }
        }
        // Check-out before check-in on a day you change hotels.
        stays.sort { ($0.mode == .checkOut ? 0 : 1) < ($1.mode == .checkOut ? 0 : 1) }
        timed.sort { ($0.minutes ?? -1) < ($1.minutes ?? -1) }
    }

    var hasTravel: Bool { timed.contains { $0.mode == .departs || $0.mode == .lands } }

    /// When the day is free around its travel: after you land on the way there (an overnight flight, or the first
    /// day's), else before you leave.
    var window: String? {
        if let landed = timed.last(where: { $0.mode == .lands }), let t = landed.booking.endTime { return "after \(Fmt.clock(t))" }
        let leaving = timed.filter { $0.mode == .departs }
        if isFirstDay, let arrive = leaving.last, arrive.booking.endDay == arrive.booking.startDay, let t = arrive.booking.endTime {
            return "after \(Fmt.clock(t))"
        }
        if !isFirstDay, let leave = leaving.first, let t = leave.booking.startTime { return "before \(Fmt.clock(t))" }
        return nil
    }

    /// Stop index → the bookings that go just above it (index == count: after the last stop).
    func slots(for stops: [Place]) -> [Int: [Item]] {
        var out: [Int: [Item]] = [:]
        for item in timed {
            var index = stops.count
            if let m = item.minutes {
                if let i = stops.firstIndex(where: { (Self.minutes(for: $0) ?? -1) > m }) { index = i }
            } else {
                index = 0
            }
            out[index, default: []].append(item)
        }
        return out
    }

    static func minutes(_ hhmm: String?) -> Int? {
        guard let hhmm, hhmm.count == 5, let h = Int(hhmm.prefix(2)), let m = Int(hhmm.suffix(2)) else { return nil }
        return h * 60 + m
    }

    /// A stop's time: its exact time, else its part of the day.
    static func minutes(for place: Place) -> Int? {
        if let t = minutes(place.startTime) { return t }
        return ["morning": 9 * 60, "afternoon": 13 * 60, "evening": 19 * 60, "night": 21 * 60][place.timeOfDay ?? ""]
    }
}

/// A booking on the plan: a flight or train as a block with its times, a stay as a ribbon for its nights.
struct BookingLine: View {
    let item: DayBookings.Item
    let onTap: () -> Void

    var body: some View {
        let b = item.booking
        Button(action: onTap) {
            HStack(spacing: 10) {
                Image(systemName: symbol).font(.system(size: 14, weight: .medium)).foregroundStyle(Theme.label)
                    .frame(width: 22)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(Theme.text(.subheadline, weight: .medium)).foregroundStyle(Theme.label).lineLimit(1)
                    Text(detail).font(Theme.text(.caption)).foregroundStyle(Theme.secondary).lineLimit(1)
                }
                Spacer(minLength: 0)
                if let c = b.confirmation, !c.isEmpty {
                    Text(c).font(Theme.text(.caption2, weight: .medium)).foregroundStyle(Theme.secondary)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 9)
            .background(isStay ? Theme.dynamic(0xE9EEF6, 0x1E2633) : Theme.dynamic(0xEFE7DD, 0x2B241D),
                        in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(alignment: .leading) {
                if isStay { UnevenRoundedRectangle(topLeadingRadius: 12, bottomLeadingRadius: 12).fill(Theme.teal).frame(width: 4) }
            }
        }
        .buttonStyle(.borderless)
    }

    private var isStay: Bool { item.booking.kind == "hotel" }

    private var symbol: String {
        switch item.booking.kind {
        case "flight": item.mode == .lands ? "airplane.arrival" : "airplane.departure"
        case "hotel": "bed.double.fill"
        case "reservation": "fork.knife"
        case "car": "car.fill"
        case "tour": "ticket.fill"
        default: item.booking.origin != nil ? "tram.fill" : "ticket.fill"
        }
    }

    private var title: String {
        let b = item.booking
        switch item.mode {
        case .departs, .lands:
            let route = [b.origin.map(Journeys.short), b.destination.map(Journeys.short)].compactMap { $0 }.joined(separator: " → ")
            return route.isEmpty ? b.title : route
        default: return b.title
        }
    }

    private var detail: String {
        let b = item.booking
        switch item.mode {
        case .checkIn: return "Check in" + (b.startTime.map { " · \(Fmt.clock($0))" } ?? "")
        case .checkOut: return "Check out" + (b.endTime.map { " · \(Fmt.clock($0))" } ?? "")
        case .night(let k, let n): return "Night \(k) of \(n)"
        case .departs:
            var parts = [b.title]
            if let t = b.startTime { parts.append(Fmt.clock(t)) }
            if let e = b.endTime {
                parts.append("lands " + (b.endDay != b.startDay ? "next day " : "") + Fmt.clock(e))
            }
            return parts.joined(separator: " · ")
        case .lands: return "\(b.title) · landed " + (b.endTime.map(Fmt.clock) ?? "today")
        case .at: return [b.startTime.map(Fmt.clock), b.address].compactMap { $0 }.joined(separator: " · ")
        }
    }
}

/// What a trip's bookings say that the trip doesn't yet: its start date, and cities you fly into that aren't on it.
/// One tap each; "Not now" hides it for good.
struct TripSuggestions: View {
    let trip: TripDetail
    @Environment(Store.self) private var store
    @AppStorage("trip.suggestions.dismissed") private var dismissed = ""

    private var key: String { trip.id + ":" + trip.bookings.map(\.id).joined() }

    private var startDay: String? {
        guard trip.startDate == nil else { return nil }
        return Journeys.outbound(trip.bookings).first?.startDay ?? trip.bookings.compactMap(\.startDay).min()
    }

    private var newCities: [String] {
        let have = Set(((trip.stops ?? []).map(\.city) + [trip.city]).map(PlaceFilter.normalize))
        let home = PlaceFilter.normalize(store.home?.city ?? "")
        let origin = Journeys.outbound(trip.bookings).first?.origin.map { PlaceFilter.normalize(Journeys.cityName($0)) }
        var seen = Set<String>()
        return Journeys.destinations(trip.bookings).filter { city in
            let k = PlaceFilter.normalize(city)
            guard !k.isEmpty, k.count > 3, !have.contains(k), k != home, k != origin, !seen.contains(k) else { return false }
            seen.insert(k)
            return true
        }
    }

    var body: some View {
        let cities = newCities
        if !dismissed.split(separator: ",").contains(Substring(key)), startDay != nil || !cities.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Text("FROM YOUR BOOKINGS").font(Theme.text(.caption2, weight: .medium)).kerning(1.6).foregroundStyle(Theme.secondary)
                if let day = startDay, let date = Fmt.day(day) {
                    row("Start the trip on \(date.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated)))", "Set") {
                        _ = await store.tripCall("PATCH", "/v1/trips/\(trip.id)", ["start_date": day])
                    }
                }
                ForEach(cities, id: \.self) { city in
                    row("Add \(city) to this trip", "Add") { await add(city) }
                }
                Button("Not now") { dismissed += (dismissed.isEmpty ? "" : ",") + key }
                    .font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.dynamic(0xEFE7DD, 0x2B241D), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
    }

    private func row(_ text: String, _ action: String, _ run: @escaping () async -> Void) -> some View {
        HStack {
            Text(text).font(Theme.text(.subheadline)).foregroundStyle(Theme.label)
            Spacer(minLength: 8)
            Button(action) { Task { await run(); Haptics.success() } }
                .font(Theme.text(.subheadline, weight: .medium)).buttonStyle(.borderless)
        }
    }

    /// Adds the city to the route; a trip with no city yet takes it as its only one.
    private func add(_ city: String) async {
        var stops: [[String: Any]] = (trip.stops ?? []).filter { !$0.city.isEmpty }.map { ["city": $0.city, "days": $0.days] }
        if stops.isEmpty && !trip.city.isEmpty { stops = [["city": trip.city, "days": max(1, trip.dayCount)]] }
        stops.append(["city": city, "days": stops.isEmpty ? max(1, trip.dayCount) : 2])
        if let fresh: TripDetail = try? await API.shared.put("/v1/trips/\(trip.id)/stops", ["stops": stops]) {
            store.apply(fresh)
            await store.reloadTrips()
        }
    }
}
