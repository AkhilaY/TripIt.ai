import SwiftUI

/// Trip → Plan: the days, their stops in order with travel times between them, and what's not scheduled yet.
/// Tap Edit to drag stops into a new order; press and hold a stop to move it to another day.
struct TripPlan: View {
    let trip: TripDetail
    @Binding var sheet: TripSheet?
    @Binding var librarySheet: LibrarySheet?
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.editMode) private var editMode
    @AppStorage("travel.mode") private var travelMode = "walk"
    @State private var legs: [Int: [String: Leg]] = [:]  // day → "from>to" → leg

    var body: some View {
        if trip.dayCount == 0 {
            ScrollView {
                EmptyState(symbol: "calendar", color: Theme.indigo, title: "No itinerary yet",
                           text: "Build it yourself from your \(Fmt.plural(trip.places.count, "saved place")), or have them grouped into days by neighbourhood and time. You can fix the order of your own plan later.") {
                    VStack(spacing: 10) {
                        Button { addToDay(nil) } label: { Label("Build it myself", systemImage: "calendar.badge.plus") }
                            .buttonStyle(PrimaryButtonStyle())
                        Button { sheet = .plan } label: { Label("Plan my days", systemImage: "sparkles") }
                            .buttonStyle(PrimaryButtonStyle(tinted: true))
                    }
                    .frame(maxWidth: 260)
                    .disabled(trip.places.isEmpty)
                }
            }
            .tripBackground()
        } else {
            list
        }
    }

    private var list: some View {
        List {
            Section {
                HStack {
                    Label(plannedBy, systemImage: trip.plannedBy == "claude" ? "sparkles" : "calendar")
                        .font(.subheadline).foregroundStyle(Theme.secondary)
                    Spacer()
                    Picker("Travel", selection: $travelMode) {
                        Image(systemName: "figure.walk").tag("walk")
                        Image(systemName: "tram.fill").tag("transit")
                        Image(systemName: "car.fill").tag("drive")
                        Image(systemName: "bicycle").tag("bike")
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 168)
                }
                if let notes = trip.planNotes {
                    Text(notes).font(.subheadline).foregroundStyle(Theme.label)
                }
                if !trip.route.isEmpty { TripRouteStrip(stops: trip.route) { sheet = .route } }
            }
            ForEach(1...trip.dayCount, id: \.self) { day in
                daySection(day)
            }
            if editMode?.wrappedValue.isEditing != true {
                Section {
                    Button { addToDay(nil) } label: { Label("Add a day", systemImage: "plus") }
                        .disabled(trip.dayCount >= 21)
                }
            }
            let unscheduled = trip.places.filter { $0.dayNumber == nil }
                .sorted { $0.mustDo != $1.mustDo ? $0.mustDo : $0.mentionCount > $1.mentionCount }
            if !unscheduled.isEmpty {
                Section {
                    ForEach(unscheduled) { place in
                        NavigationLink(value: Route.place(id: place.id, tripId: trip.id)) {
                            PlaceRow(place: place)
                        }
                        .contextMenu { moveMenu(place) }
                    }
                } header: {
                    HStack {
                        Text("Not on a day yet · \(unscheduled.count)")
                        Spacer()
                        if editMode?.wrappedValue.isEditing != true {
                            Button { Task { await fitThemIn() } } label: { Label("Fit them in", systemImage: "wand.and.rays") }
                                .font(.footnote.weight(.semibold)).foregroundStyle(Theme.link).textCase(nil)
                        }
                    }
                } footer: {
                    if !trip.route.isEmpty { Text("Each goes on the lightest day in its own city, on a day it's open.") }
                }
            }
            Section {
                EmptyView()
            } footer: {
                Text(trip.startDate == nil
                     ? "Open a stop to set an exact time. Set a start date (••• → Name and dates) to check each stop is open on its day."
                     : "Open a stop to set an exact time, like a reservation.")
            }
        }
        .listStyle(.insetGrouped)
        .tripBackground()
        .task(id: legsKey) { await loadLegs() }
    }

    private var plannedBy: String {
        switch trip.plannedBy ?? "" {
        case "claude": "Planned for you"
        case "offline": "Grouped by location"
        default: "Your itinerary"
        }
    }

    @ViewBuilder private func daySection(_ day: Int) -> some View {
        let stops = trip.dayPlaces(day)
        let located = stops.filter(\.isLocated)
        let stop = trip.stop(on: day)
        let arriving = stop.flatMap { $0.startDay == day && $0.startDay > 1 ? $0 : nil }
        Section {
            if let arriving, editMode?.wrappedValue.isEditing != true {
                TravelDayRow(from: trip.stop(on: day - 1)?.city, stop: arriving, ticket: dayBookings(day).first { ["flight", "train"].contains($0.kind) }) {
                    router.push(.bookings(tripId: trip.id))
                }
            }
            ForEach(dayBookings(day)) { booking in
                Button { router.push(.bookings(tripId: trip.id)) } label: {
                    HStack(spacing: 12) {
                        SymbolTile(symbol: bookingSymbol(booking.kind), color: Theme.blue)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(booking.title).foregroundStyle(Theme.label)
                            Text([booking.startAt.flatMap(timePart).map(Fmt.clock), booking.origin, booking.destination]
                                .compactMap { $0 }.joined(separator: " · "))
                                .font(.caption).foregroundStyle(Theme.secondary)
                        }
                    }
                }
            }
            ForEach(Array(stops.enumerated()), id: \.element.id) { index, place in
                VStack(alignment: .leading, spacing: 8) {
                    NavigationLink(value: Route.place(id: place.id, tripId: trip.id)) {
                        StopRow(place: place, number: index + 1)
                    }
                    if let closure = trip.closure(for: place.id), editMode?.wrappedValue.isEditing != true {
                        ClosureLine(closure: closure) { day in Task { await move(place, to: day) } }
                    }
                    if editMode?.wrappedValue.isEditing != true,
                       let next = located.firstIndex(where: { $0.id == place.id }).flatMap({ $0 + 1 < located.count ? located[$0 + 1] : nil }),
                       place.isLocated {
                        legView(day: day, from: place, to: next)
                    }
                }
                .contextMenu { moveMenu(place) }
                .swipeActions(edge: .trailing) {
                    Button { Task { await move(place, to: 0) } } label: { Label("Unschedule", systemImage: "calendar.badge.minus") }
                        .tint(Theme.gray)
                }
            }
            .onMove { from, to in reorder(day: day, stops: stops, from: from, to: to) }
            if stops.isEmpty {
                Text("Nothing planned yet.").foregroundStyle(Theme.secondary)
            }
            if editMode?.wrappedValue.isEditing != true {
                Button { addToDay(day) } label: { Label("Add places", systemImage: "plus") }
            }
        } header: {
            VStack(alignment: .leading, spacing: 2) {
                if let stop, stop.startDay == day {
                    StopHeading(stop: stop, start: trip.startDate).padding(.bottom, 10)
                }
                if let date = Fmt.tripDay(start: trip.startDate, day: day) {
                    Text(date.uppercased()).font(.caption.weight(.bold)).foregroundStyle(Theme.gold)
                }
                Text("Day \(day)").font(Theme.serif(24)).foregroundStyle(Theme.label)
                if let title = trip.title(of: day) {
                    Text(title).font(.subheadline).foregroundStyle(Theme.secondary)
                }
            }
            .textCase(nil)
            .padding(.top, 8)
        }
    }

    @ViewBuilder private func moveMenu(_ place: Place) -> some View {
        Menu {
            ForEach(1...max(trip.dayCount, 1), id: \.self) { d in
                Button("Day \(d)") { Task { await move(place, to: d) } }.disabled(place.dayNumber == d)
            }
            Button("Not scheduled") { Task { await move(place, to: 0) } }.disabled(place.dayNumber == nil)
        } label: {
            Label("Move to…", systemImage: "arrow.left.arrow.right")
        }
        Button { Task { await store.toggleStar(place) } } label: {
            Label(place.mustDo ? "Remove star" : "Star", systemImage: place.mustDo ? "star.slash" : "star")
        }
        Button(role: .destructive) { Task { await store.removeFromTrip(trip.id, place.id) } } label: {
            Label("Remove from trip", systemImage: "minus.circle")
        }
    }

    // MARK: Changes

    private func fitThemIn() async {
        let before = trip.places.filter { $0.dayNumber == nil }.count
        if let fresh = await store.tripCall("POST", "/v1/trips/\(trip.id)/fit") {
            let left = fresh.places.filter { $0.dayNumber == nil }.count
            store.show("Fitted in \(Fmt.plural(before - left, "place"))")
        }
    }

    private func move(_ place: Place, to day: Int) async {
        let index = day == 0 ? 0 : trip.dayPlaces(day).count
        await store.tripCall("POST", "/v1/trips/\(trip.id)/move", ["place_id": place.id, "day": day, "index": index])
    }

    private func reorder(day: Int, stops: [Place], from: IndexSet, to: Int) {
        var ids = stops.map(\.id)
        ids.move(fromOffsets: from, toOffset: to)
        // Show the new order right away; the server confirms it.
        if var local = store.tripDetails[trip.id] {
            for (i, id) in ids.enumerated() {
                if let k = local.places.firstIndex(where: { $0.id == id }) { local.places[k].dayOrder = i }
            }
            store.tripDetails[trip.id] = local
        }
        Task { await store.tripCall("POST", "/v1/trips/\(trip.id)/days/\(day)/order", ["place_ids": ids]) }
    }

    /// Pick places to put on a day (or on a new day). Places not on the trip yet join it first.
    private func addToDay(_ day: Int?) {
        let tripId = trip.id
        let onTrip = Set(trip.places.map(\.id))
        let onDay = Set(day.map { trip.dayPlaces($0).map(\.id) } ?? [])
        librarySheet = .pick(title: day.map { "Add to Day \($0)" } ?? "Places for a new day", exclude: onDay, confirm: "Add", onDone: { ids in
            let missing = ids.filter { !onTrip.contains($0) }
            if !missing.isEmpty { await store.addToTrip(tripId, missing) }
            await store.tripCall("POST", "/v1/trips/\(tripId)/add-to-day", ["place_ids": ids, "day": day])
        })
    }

    // MARK: Travel times

    private var legsKey: String {
        trip.id + travelMode + (1...max(trip.dayCount, 1)).map { trip.dayPlaces($0).map(\.id).joined() }.joined(separator: "|")
    }

    private func loadLegs() async {
        for day in 1...max(trip.dayCount, 1) where trip.dayPlaces(day).filter(\.isLocated).count > 1 {
            guard let result: DayLegs = try? await API.shared.get("/v1/trips/\(trip.id)/days/\(day)/legs") else { continue }
            var byPair: [String: Leg] = [:]
            for leg in result.legs { byPair["\(leg.fromPlaceId ?? "")>\(leg.toPlaceId)"] = leg }
            legs[day] = byPair
        }
    }

    @ViewBuilder private func legView(day: Int, from: Place, to: Place) -> some View {
        if let leg = legs[day]?["\(from.id)>\(to.id)"] {
            let time = travelTime(leg)
            Button {
                var c = URLComponents(string: "https://maps.apple.com/")!
                c.queryItems = [.init(name: "saddr", value: "\(from.latitude ?? 0),\(from.longitude ?? 0)"),
                                .init(name: "daddr", value: "\(to.latitude ?? 0),\(to.longitude ?? 0)"),
                                .init(name: "dirflg", value: ["walk": "w", "transit": "r", "drive": "d"][travelMode] ?? "w")]
                Links.open(c.url)
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: modeSymbol).font(.caption)
                    if let time {
                        Text("\(time.estimated ? "≈ " : "")\(Fmt.duration(time.durationS)) · \(Fmt.distance(Double(time.distanceM)))")
                    } else {
                        Text("No route")
                    }
                    Text("to \(to.name)").lineLimit(1)
                }
                .font(.caption)
                .foregroundStyle(Theme.secondary)
                .padding(.leading, 40)
            }
            .buttonStyle(.borderless)
        }
    }

    /// The time for the chosen mode; short hops with no transit route fall back to walking.
    private func travelTime(_ leg: Leg) -> TravelTime? {
        if let entry = leg.times[travelMode], let time = entry { return time }
        if travelMode == "transit", let entry = leg.times["walk"], let time = entry { return time }
        return nil
    }

    private var modeSymbol: String {
        ["walk": "figure.walk", "transit": "tram.fill", "drive": "car.fill", "bike": "bicycle"][travelMode] ?? "figure.walk"
    }

    // MARK: Bookings on a day

    private func dayBookings(_ day: Int) -> [Booking] {
        guard let start = trip.startDate.flatMap(Fmt.day),
              let date = Calendar.current.date(byAdding: .day, value: day - 1, to: start) else { return [] }
        let iso = Fmt.iso(date)
        return trip.bookings.filter { ($0.startAt ?? "").hasPrefix(iso) }.sorted { ($0.startAt ?? "") < ($1.startAt ?? "") }
    }

    private func timePart(_ value: String) -> String? {
        value.count > 11 ? String(value.suffix(5)) : nil
    }

    private func bookingSymbol(_ kind: String) -> String {
        ["flight": "airplane", "hotel": "bed.double.fill", "reservation": "fork.knife", "car": "car.fill"][kind] ?? "ticket.fill"
    }
}

/// A stop on a day: its number, photo, name and when.
struct StopRow: View {
    let place: Place
    let number: Int

    var body: some View {
        let category = Category(place.category)
        HStack(spacing: 12) {
            Text("\(number)")
                .font(.caption.weight(.bold)).foregroundStyle(.white)
                .frame(width: 24, height: 24)
                .background(category.color, in: Circle())
            PlaceThumb(place: place, size: 52)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 4) {
                    Text(place.name).font(.body.weight(.semibold)).strikethrough(place.visited).lineLimit(1)
                    if place.mustDo { Image(systemName: "star.fill").font(.caption).foregroundStyle(Theme.gold) }
                }
                Text([place.startTime.map(Fmt.clock) ?? place.timeOfDay?.capitalized, category.label, place.neighborhood]
                    .compactMap { $0 }.joined(separator: " · "))
                    .font(.subheadline).foregroundStyle(Theme.secondary).lineLimit(1)
                if let note = place.dayNote {
                    Text(note).font(.footnote).italic().foregroundStyle(Theme.secondary).lineLimit(2)
                }
            }
        }
    }
}

// MARK: - Multi-city pieces

/// The trip's cities in a row, with how you travel between them. Tap to edit the route.
struct TripRouteStrip: View {
    let stops: [TripStop]
    let onEdit: () -> Void

    var body: some View {
        Button(action: onEdit) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(Array(stops.enumerated()), id: \.offset) { i, stop in
                        if i > 0 {
                            HStack(spacing: 4) {
                                Rectangle().fill(Theme.tertiary.opacity(0.6)).frame(width: 14, height: 1)
                                Image(systemName: stop.travelSymbol).font(.system(size: 10, weight: .semibold))
                                if let minutes = stop.travelMinutes, minutes > 0 { Text(TravelHome.duration(minutes)).font(.caption2) }
                                Rectangle().fill(Theme.tertiary.opacity(0.6)).frame(width: 14, height: 1)
                            }
                            .foregroundStyle(Theme.secondary)
                        }
                        VStack(alignment: .leading, spacing: 1) {
                            Text(stop.city).font(Theme.serif(17)).foregroundStyle(Theme.label)
                            Text(Fmt.plural(stop.days, "day"))
                                .font(.caption2).foregroundStyle(Theme.secondary)
                        }
                    }
                }
                .padding(.vertical, 2)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Route: " + stops.map(\.city).joined(separator: ", then ") + ". Edit route")
    }
}

/// Above a stop's first day: the city and its dates.
struct StopHeading: View {
    let stop: TripStop
    let start: String?

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(stop.city).font(Theme.serif(28)).foregroundStyle(Theme.label)
            Spacer()
            Text(dates).font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
        }
        .padding(.top, 10)
        .overlay(alignment: .top) { Rectangle().fill(Theme.border).frame(height: 1) }
    }

    private var dates: String {
        let days = stop.startDay == stop.endDay ? "Day \(stop.startDay)" : "Days \(stop.startDay)–\(stop.endDay)"
        guard let first = Fmt.isoDay(start: start, day: stop.startDay).flatMap(Fmt.day),
              let last = Fmt.isoDay(start: start, day: stop.endDay).flatMap(Fmt.day) else { return days }
        return "\(days) · \(Fmt.range(first, last))"
    }
}

/// The day you move to the next city: how you get there, and the ticket if it's booked.
struct TravelDayRow: View {
    let from: String?
    let stop: TripStop
    let ticket: Booking?
    let onTicket: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            SymbolTile(symbol: stop.travelSymbol, color: Theme.blue)
            VStack(alignment: .leading, spacing: 2) {
                Text("Travel day · \(stop.travelLabel.lowercased()) to \(stop.city)").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                Text([from.map { "From \($0)" }, stop.travelMinutes.map { "about \(TravelHome.duration($0))" }, stop.travelNote]
                    .compactMap { $0 }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(Theme.secondary).lineLimit(2)
            }
            Spacer(minLength: 4)
            Button(action: onTicket) {
                Text(ticket == nil ? "Add ticket" : "Ticket").font(.footnote.weight(.semibold)).foregroundStyle(ticket == nil ? Theme.link : Theme.ok)
            }
            .buttonStyle(.borderless)
        }
    }
}

/// "Closed on Sundays · Move it to Mon" under a stop planned on a day it's shut.
struct ClosureLine: View {
    let closure: TripClosure
    let onMove: (Int) -> Void

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "exclamationmark.circle").font(.caption)
            Text(closure.message).font(.caption.weight(.medium))
            Spacer(minLength: 4)
            if let day = closure.moveToDay {
                Button { onMove(day) } label: {
                    Text("Move it to \(closure.moveToLabel ?? "Day \(day)")").font(.caption.weight(.semibold)).foregroundStyle(Theme.link)
                }
                .buttonStyle(.borderless)
            }
        }
        .foregroundStyle(Theme.danger)
        .padding(.leading, 36)
    }
}
