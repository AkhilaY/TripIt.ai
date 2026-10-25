import CoreLocation
import SwiftUI

/// Home during a trip: today at this stop as a timeline, what's near you right now, and the next stop on the route.
struct TravelHome: View {
    let trip: Trip
    let day: Int
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @State private var location = Location.shared
    @State private var weather: WeatherToday?

    private var detail: TripDetail? { store.tripDetails[trip.id] }
    private var stops: [TripStop] { trip.stops ?? detail?.stops ?? [] }
    private var stopIndex: Int { stops.firstIndex { day >= $0.startDay && day <= $0.endDay } ?? 0 }
    private var currentCity: String { stops.indices.contains(stopIndex) ? stops[stopIndex].city : trip.city }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            today.padding(.top, 16)
            nearYou
            nextStop
        }
        .task(id: trip.id) {
            if store.tripDetails[trip.id] == nil { _ = try? await store.loadTrip(trip.id) }
            await loadWeather()
        }
    }

    // MARK: Today

    private struct Slot: Identifiable {
        let place: Place
        let minute: Int
        var id: String { place.id }
    }

    private var slots: [Slot] {
        (detail?.dayPlaces(day) ?? []).map { Slot(place: $0, minute: detail?.minute(of: $0.id) ?? Self.minute(of: $0)) }
    }

    /// "Breakfast", "Lunch" or "Dinner" for meals; otherwise the kind of place ("Market" isn't breakfast).
    static func stopLabel(_ p: Place) -> String {
        let category = Category(p.category)
        if category == .food || category == .cafe {
            if p.timeOfDay == "morning" { return "Breakfast" }
            if category == .food, let tod = p.timeOfDay, tod == "lunch" || tod == "dinner" { return tod.capitalized }
        }
        return category.label
    }

    /// The planned time, or a usual time for its part of the day (until the server's schedule arrives).
    static func minute(of p: Place) -> Int {
        if let t = p.startTime { let parts = t.split(separator: ":").compactMap { Int($0) }; if parts.count == 2 { return parts[0] * 60 + parts[1] } }
        switch p.timeOfDay {
        case "morning": return 9 * 60 + 30
        case "lunch": return 12 * 60 + 30
        case "afternoon": return 15 * 60
        case "dinner": return 19 * 60 + 30
        case "evening": return 21 * 60
        default: return 12 * 60
        }
    }

    private var nowMinute: Int {
        let c = Calendar.current.dateComponents([.hour, .minute], from: Date())
        return (c.hour ?? 0) * 60 + (c.minute ?? 0)
    }

    private var nextSlot: Slot? {
        slots.first { !$0.place.visited && $0.minute >= nowMinute - 30 } ?? slots.first { !$0.place.visited }
    }

    @ViewBuilder private var today: some View {
        let list = slots
        Card(radius: 16, padding: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Eyebrow(text: stops.count > 1 ? "Today · Day \(day) of \(trip.dayCount) · \(currentCity)" : "Today · Day \(day) of \(trip.dayCount)", color: Theme.gold)
                    Text(dayTitle).font(Theme.serif(20)).foregroundStyle(Theme.label).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                if let weather {
                    VStack(alignment: .trailing, spacing: 1) {
                        Text("\(Self.temperature(weather.tempMax))°").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                        Text(weather.summary).font(.caption2).foregroundStyle(Theme.secondary).lineLimit(1)
                    }
                }
            }
            if list.isEmpty {
                Text("Nothing planned for today yet.").font(.subheadline).foregroundStyle(Theme.secondary).padding(.top, 10)
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(list.enumerated()), id: \.element.id) { i, slot in
                        timelineRow(slot, isNext: slot.id == nextSlot?.id, previous: i > 0 ? list[i - 1].place : nil, last: i == list.count - 1 && gapCandidates.isEmpty)
                    }
                    if !gapCandidates.isEmpty { gapRow }
                }
                .padding(.top, 12)
            }
            HStack(spacing: 8) {
                Button("Open today") { router.push(.today(tripId: trip.id, day: nil)) }
                    .buttonStyle(PrimaryButtonStyle(compact: true))
                if let next = nextSlot?.place {
                    Menu {
                        Button { Links.open(next.directionsURL) } label: { Label("Apple Maps", systemImage: "map") }
                        Button { Links.open(next.googleDirectionsURL) } label: { Label("Google Maps", systemImage: "globe") }
                    } label: {
                        Label("Directions", systemImage: "arrow.up.right")
                            .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.accent)
                            .padding(.horizontal, 16).padding(.vertical, 9)
                            .frame(maxWidth: .infinity)
                            .background(Theme.fill, in: Capsule())
                    }
                } else {
                    Button("Plan today") { router.push(.trip(id: trip.id)) }.buttonStyle(PrimaryButtonStyle(tinted: true, compact: true))
                }
            }
            .padding(.top, 14)
        }
    }

    private var dayTitle: String {
        if let title = detail?.title(of: day) { return title }
        var hoods: [String] = []
        for hood in slots.compactMap(\.place.neighborhood) where !hoods.contains(hood) { hoods.append(hood) }
        if hoods.count >= 2 { return "\(hoods[0]), then \(hoods[1])" }
        if let only = hoods.first { return only }
        return "Day \(day) in \(currentCity)"
    }

    private func timelineRow(_ slot: Slot, isNext: Bool, previous: Place?, last: Bool) -> some View {
        let p = slot.place
        let walk = walkMinutes(to: p, from: previous)
        let booked = detail?.bookings.contains { $0.placeId == p.id } ?? false
        return HStack(alignment: .top, spacing: 10) {
            Text(Self.clock(slot.minute))
                .font(.caption2.weight(.medium).monospacedDigit()).foregroundStyle(Theme.secondary)
                .frame(width: 50, alignment: .trailing)
                .padding(.top, 2)
            VStack(spacing: 0) {
                Circle()
                    .fill(isNext ? Theme.gold : .clear)
                    .overlay(Circle().strokeBorder(isNext ? Theme.gold : Theme.quiet, lineWidth: 1.5))
                    .frame(width: 9, height: 9)
                    .padding(.top, 4)
                if !last { Rectangle().fill(Theme.border).frame(width: 1).frame(maxHeight: .infinity) }
            }
            NavigationLink(value: Route.place(id: p.id, tripId: trip.id)) {
                VStack(alignment: .leading, spacing: 2) {
                    if isNext { Eyebrow(text: leaveText(slot, walk: walk), color: Theme.gold) }
                    Text(p.name).font(Theme.serif(isNext ? 17 : 15)).foregroundStyle(p.visited ? Theme.secondary : Theme.label)
                        .strikethrough(p.visited).lineLimit(2)
                    Text([Self.stopLabel(p),
                          walk.map { "\($0) min walk" }].compactMap { $0 }.joined(separator: " · "))
                        .font(.caption).foregroundStyle(Theme.secondary)
                    if p.bookingNeed != nil, !booked, Category(p.category).hasMenu {
                        Text(p.bookingNeed == "required" ? "No table booked yet" : "No table booked · expect a queue")
                            .font(.caption.weight(.medium)).foregroundStyle(Theme.attention)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.bottom, 14)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
    }

    private func leaveText(_ slot: Slot, walk: Int?) -> String {
        guard let walk else { return "Next" }
        let leave = slot.minute - walk - nowMinute
        return leave > 0 && leave <= 90 ? "Next · leave in \(leave) min" : "Next"
    }

    /// Walking minutes from where you are (or the stop before), about 80 m a minute.
    private func walkMinutes(to p: Place, from previous: Place?) -> Int? {
        if let d = p.distance(from: location.current), d < 5000 { return max(1, Int(d / 80)) }
        if let prev = previous, let a = prev.coordinate, let b = p.coordinate {
            let d = CLLocation(latitude: a.latitude, longitude: a.longitude).distance(from: CLLocation(latitude: b.latitude, longitude: b.longitude))
            return d < 5000 ? max(1, Int(d / 80)) : nil
        }
        return nil
    }

    /// When nothing's planned for dinner: saved food places in this city near where the day ends.
    private var gapCandidates: [Place] {
        guard let detail else { return [] }
        let todays = slots
        guard !todays.isEmpty, !todays.contains(where: { $0.minute >= 18 * 60 }) else { return [] }
        let planned = Set(detail.places.filter { $0.dayNumber != nil }.map(\.id))
        let anchor = todays.last { $0.place.isLocated }?.place.coordinate
        let key = Store.cityKey(currentCity)
        return store.saved.filter { p in
            guard [.food, .drinks].contains(Category(p.category)), !planned.contains(p.id), Store.cityKey(p.city) == key else { return false }
            guard let anchor, let c = p.coordinate else { return anchor == nil }
            return CLLocation(latitude: anchor.latitude, longitude: anchor.longitude).distance(from: CLLocation(latitude: c.latitude, longitude: c.longitude)) < 2500
        }
    }

    private var gapRow: some View {
        let options = gapCandidates
        return HStack(alignment: .top, spacing: 10) {
            Text(Self.clock(19 * 60 + 30)).font(.caption2.weight(.medium).monospacedDigit()).foregroundStyle(Theme.secondary)
                .frame(width: 50, alignment: .trailing).padding(.top, 2)
            Circle().strokeBorder(Theme.quiet, style: StrokeStyle(lineWidth: 1.5, dash: [2, 2])).frame(width: 9, height: 9).padding(.top, 4)
            VStack(alignment: .leading, spacing: 2) {
                Text("Dinner isn't planned").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                Text("\(Fmt.plural(options.count, "saved place")) \(options.count == 1 ? "is" : "are") close to where you'll be")
                    .font(.caption).foregroundStyle(Theme.secondary)
                Menu {
                    ForEach(options.prefix(8)) { p in
                        Button(p.name) { Task { await addForDinner(p) } }
                    }
                } label: {
                    Text("Choose one").font(.caption.weight(.semibold)).foregroundStyle(Theme.link).frame(minHeight: 28)
                }
            }
        }
    }

    private func addForDinner(_ p: Place) async {
        if !(detail?.places.contains { $0.id == p.id } ?? false) { await store.addToTrip(trip.id, [p.id]) }
        await store.tripCall("POST", "/v1/trips/\(trip.id)/add-to-day", ["place_ids": [p.id], "day": day])
        if let fresh = store.tripDetails[trip.id]?.places.first(where: { $0.id == p.id }) {
            await store.patch(fresh, ["time_of_day": "dinner"], tripId: trip.id)
        }
        store.show("\(p.name) added for dinner")
    }

    // MARK: Near you now

    @ViewBuilder private var nearYou: some View {
        let here = location.current
        let key = Store.cityKey(currentCity)
        let near = store.saved
            .filter { p in
                if let d = p.distance(from: here) { return d < 3000 }
                return here == nil && Store.cityKey(p.city) == key
            }
            .sorted { ($0.distance(from: here) ?? .infinity) < ($1.distance(from: here) ?? .infinity) }
            .prefix(8)
        if !near.isEmpty {
            SectionHeading(title: "Near you now") {
                Text("From your \(currentCity) saves").font(.caption).foregroundStyle(Theme.tertiary)
            }
            .padding(.top, 24)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: 10) {
                    ForEach(Array(near)) { p in
                        NavigationLink(value: Route.place(id: p.id, tripId: nil)) {
                            VStack(alignment: .leading, spacing: 2) {
                                PhotoBox(place: p, width: 124, height: 88, radius: 12)
                                Text(p.name).font(.footnote.weight(.semibold)).foregroundStyle(Theme.label).lineLimit(1).padding(.top, 5)
                                HStack(spacing: 0) {
                                    if let st = Hours.status(p.openingHours) {
                                        Text(st.isOpen ? "Open" : "Closed").foregroundStyle(st.isOpen ? Theme.open : Theme.secondary)
                                    }
                                    if let d = p.distance(from: here) {
                                        Text((Hours.status(p.openingHours) == nil ? "" : " · ") + "\(max(1, Int(d / 80))) min walk").foregroundStyle(Theme.secondary)
                                    }
                                }
                                .font(.caption2).lineLimit(1)
                            }
                            .frame(width: 124, alignment: .leading)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.trailing, 20)
            }
            .padding(.trailing, -20)
        }
    }

    // MARK: Next stop

    @ViewBuilder private var nextStop: some View {
        if stops.indices.contains(stopIndex + 1) {
            let stop = stops[stopIndex + 1]
            let key = Store.cityKey(stop.city)
            let saved = store.saved.filter { Store.cityKey($0.city) == key }
            let inPlan = (detail?.places ?? []).filter { ($0.dayNumber ?? 0) >= stop.startDay && ($0.dayNumber ?? 0) <= stop.endDay }
            let hotel = (detail?.bookings ?? []).contains { b in
                b.kind == "hotel" && covers(b, day: stop.startDay)
            }
            SectionHeading("Next stop").padding(.top, 24)
            Card(radius: 16, padding: 12) {
                HStack(spacing: 12) {
                    PlaceThumbOrIcon(place: saved.first { !$0.photos.isEmpty }, symbol: "building.2", size: 46)
                    VStack(alignment: .leading, spacing: 2) {
                        if let date = Fmt.tripDay(start: trip.startDate, day: stop.startDay) { Eyebrow(text: date, color: Theme.gold) }
                        Text(stop.city).font(Theme.serif(18)).foregroundStyle(Theme.label)
                        let travel = [stop.travelNote ?? stop.travelMode.map { $0 == "flight" ? "Flight" : $0.capitalized },
                                      stop.travelMinutes.map { "about \(Self.duration($0))" }].compactMap { $0 }
                        if !travel.isEmpty { Text(travel.joined(separator: " · ")).font(.caption).foregroundStyle(Theme.secondary) }
                    }
                    Spacer(minLength: 0)
                }
                Divider().overlay(Theme.border).padding(.vertical, 10)
                Label("\(Fmt.plural(saved.count, "saved place")) · \(inPlan.count) in the plan", systemImage: "bookmark")
                    .font(.caption).foregroundStyle(Theme.label)
                if !hotel {
                    HStack {
                        Label("No hotel booked yet", systemImage: "bed.double").font(.caption.weight(.medium)).foregroundStyle(Theme.attention)
                        Spacer()
                        Button("Add a stay") { router.open("#/trip/\(trip.id)/bookings") }
                            .font(.caption.weight(.semibold)).foregroundStyle(Theme.link)
                    }
                    .padding(.top, 8)
                }
            }
        }
    }

    private func covers(_ b: Booking, day: Int) -> Bool {
        guard let dateString = Fmt.isoDay(start: trip.startDate, day: day) else { return false }
        let start = String((b.startAt ?? "").prefix(10)), end = String((b.endAt ?? b.startAt ?? "").prefix(10))
        return !start.isEmpty && start <= dateString && dateString <= max(end, start)
    }

    // MARK: Weather and formatting

    private func loadWeather() async {
        let coordinate = location.current?.coordinate ?? detail?.dayPlaces(day).first(where: \.isLocated)?.coordinate
            ?? detail?.places.first(where: \.isLocated)?.coordinate
        guard let c = coordinate else { return }
        weather = try? await API.shared.get("/v1/weather/today?lat=\(c.latitude)&lon=\(c.longitude)&on=\(Fmt.iso(Date()))", as: WeatherToday?.self)
    }

    static func temperature(_ celsius: Double) -> Int {
        Locale.current.measurementSystem == .us ? Int((celsius * 9 / 5 + 32).rounded()) : Int(celsius.rounded())
    }

    static func clock(_ minute: Int) -> String {
        Fmt.clock(String(format: "%02d:%02d", (minute / 60) % 24, minute % 60))
    }

    static func duration(_ minutes: Int) -> String {
        if minutes < 60 { return "\(minutes) min" }
        let quarters = Int((Double(minutes) / 15).rounded())
        let h = quarters / 4, q = quarters % 4
        return "\(h)\(["", "¼", "½", "¾"][q]) hr"
    }
}

struct WeatherToday: Codable, Hashable {
    var summary: String
    var tempMin: Double
    var tempMax: Double
    var rainChance: Int?
}

/// A place's photo, or a symbol when there's none.
struct PlaceThumbOrIcon: View {
    let place: Place?
    let symbol: String
    var size: CGFloat = 46

    var body: some View {
        if let place { PlaceThumb(place: place, size: size) }
        else {
            RoundedRectangle(cornerRadius: size * 0.25, style: .continuous).fill(Theme.raised)
                .frame(width: size, height: size)
                .overlay(Image(systemName: symbol).foregroundStyle(Theme.secondary))
        }
    }
}
