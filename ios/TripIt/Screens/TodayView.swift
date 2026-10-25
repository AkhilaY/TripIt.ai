import SwiftUI

/// One day of a trip, as you live it: what's booked, today's bag, what's on tonight, a short briefing, the next stop
/// with directions, then the rest of the day and what you've done.
struct TodayView: View {
    let tripId: String
    @State var day: Int? = nil
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @State private var briefings: [String: DayBriefing] = [:]
    @State private var packing: PackingList?
    @State private var events: TripEvents?

    private var trip: TripDetail? { store.tripDetails[tripId] }

    /// Which day of the trip it is today, if the trip is happening.
    private var todayNumber: Int? {
        store.activeTrip.flatMap { $0.trip.id == tripId ? $0.day : nil }
    }

    var body: some View {
        Group {
            if let trip {
                if trip.dayCount == 0 {
                    EmptyState(symbol: "calendar", color: Theme.indigo, title: "No itinerary yet",
                               text: "Plan the trip first, then this page walks you through each day.") {
                        Button("Open the trip") { router.push(.trip(id: tripId)) }.buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 220)
                    }
                    .frame(maxHeight: .infinity)
                } else {
                    content(trip, day: min(max(1, day ?? todayNumber ?? 1), trip.dayCount))
                }
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle(title)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { router.push(.trip(id: tripId)) } label: { Image(systemName: "calendar") }
                    .accessibilityLabel("Full itinerary")
            }
        }
        .task {
            if trip == nil { _ = try? await store.loadTrip(tripId) }
            packing = try? await API.shared.get("/v1/trips/\(tripId)/packing", as: PackingList?.self)
            if Features.isOn("events") { events = try? await API.shared.get("/v1/trips/\(tripId)/events") }
        }
    }

    private var title: String {
        guard let trip, trip.dayCount > 0 else { return trip?.name ?? "" }
        let shown = min(max(1, day ?? todayNumber ?? 1), trip.dayCount)
        return shown == todayNumber ? "Today" : "Day \(shown)"
    }

    private func content(_ trip: TripDetail, day: Int) -> some View {
        let list = trip.dayPlaces(day)
        let next = list.first { !$0.visited }
        let done = list.filter(\.visited)
        let later = list.filter { !$0.visited && $0.id != next?.id }
        let isToday = day == todayNumber
        return ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text([Fmt.tripDay(start: trip.startDate, day: day), trip.name, trip.title(of: day)].compactMap { $0 }.joined(separator: " · "))
                    .font(.subheadline).foregroundStyle(Theme.secondary)
                if trip.dayCount > 1 { dayPicker(trip, day: day).padding(.top, 12) }
                booked(trip, day: day)
                bag(day: day)
                tonight(day: day)
                if !list.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        ProgressView(value: Double(done.count) / Double(list.count)).tint(Theme.ok)
                        Text("\(done.count) of \(Fmt.plural(list.count, "stop")) done").font(.footnote).foregroundStyle(Theme.secondary)
                    }
                    .padding(.top, 20)
                    briefing(trip, day: day, isToday: isToday)
                }
                if list.isEmpty {
                    EmptyState(symbol: "calendar", title: "Nothing planned", text: "Open a place and move it to this day.")
                } else if let next {
                    nextCard(trip, next, number: (list.firstIndex(of: next) ?? 0) + 1, of: list.count).padding(.top, 18)
                } else {
                    Card(padding: 16) {
                        HStack(spacing: 14) {
                            SymbolTile(symbol: "checkmark", color: Theme.ok, size: 44)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Day complete").font(Theme.serif(22))
                                Text("You visited all \(Fmt.plural(list.count, "stop")).\(day < trip.dayCount ? " Day \(day + 1) is next." : "")")
                                    .font(.subheadline).foregroundStyle(Theme.secondary)
                            }
                        }
                    }
                    .padding(.top, 18)
                }
                if !later.isEmpty {
                    SectionHeading(title: isToday ? "Later today" : "Later") { Text("\(later.count)").foregroundStyle(Theme.secondary) }
                        .padding(.top, 22)
                    ForEach(later) { p in stopRow(trip, p, number: (list.firstIndex(of: p) ?? 0) + 1) }
                }
                if !done.isEmpty {
                    SectionHeading(title: "Done") { Text("\(done.count)").foregroundStyle(Theme.secondary) }.padding(.top, 22)
                    ForEach(done) { p in stopRow(trip, p, number: (list.firstIndex(of: p) ?? 0) + 1) }
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 40)
        }
        .refreshable { _ = try? await store.loadTrip(tripId) }
    }

    private func dayPicker(_ trip: TripDetail, day: Int) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(1...trip.dayCount, id: \.self) { d in
                    FilterChip(label: d == todayNumber ? "Today" : "Day \(d)", isOn: d == day) { self.day = d }
                }
            }
        }
    }

    // MARK: Booked, bag, tonight

    @ViewBuilder private func booked(_ trip: TripDetail, day: Int) -> some View {
        let date = Fmt.isoDay(start: trip.startDate, day: day)
        let list = trip.bookings.filter { $0.startDay == date && !($0.kind == "reservation" && $0.placeId != nil) }
        if date != nil, !list.isEmpty {
            Eyebrow(text: "Booked today", color: Theme.secondary).padding(.top, 22)
            Card {
                ForEach(list) { b in
                    Button { router.push(.bookings(tripId: tripId)) } label: {
                        HStack(spacing: 12) {
                            SymbolTile(symbol: b.bookingKind.symbol, color: b.bookingKind.color)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(b.title + (b.bookingKind == .flight && b.origin != nil && b.destination != nil ? " \(b.origin!) → \(b.destination!)" : ""))
                                    .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                                Text([b.bookingKind.label, b.startTime.map(Fmt.clock), b.confirmation.map { "Ref \($0)" }].compactMap { $0 }.joined(separator: " · "))
                                    .font(.footnote).foregroundStyle(Theme.secondary)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(12)
                    }
                    .buttonStyle(.plain)
                    if b.id != list.last?.id { Divider().overlay(Theme.divider) }
                }
            }
            .padding(.top, 8)
        }
    }

    @ViewBuilder private func bag(day: Int) -> some View {
        let items = (packing?.items ?? []).filter { $0.dayBag && ($0.days.isEmpty || $0.days.contains(day)) }
        if !items.isEmpty {
            Label("Today's bag", systemImage: "bag").font(.system(size: 10, weight: .semibold)).textCase(.uppercase).kerning(1.4)
                .foregroundStyle(Theme.secondary).padding(.top, 22)
            Card(padding: 12) {
                ForEach(items) { item in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.text).font(.subheadline.weight(.semibold))
                        if let reason = item.reason { Text(reason).font(.footnote).foregroundStyle(Theme.secondary) }
                    }
                    .padding(.vertical, 4)
                }
            }
            .padding(.top, 8)
            .onTapGesture { router.push(.packing(tripId: tripId)) }
        }
    }

    @ViewBuilder private func tonight(day: Int) -> some View {
        let list = (events?.status == "ok" ? events?.events ?? [] : [])
            .filter { $0.day == day && ($0.time == nil || ($0.time ?? "") >= "16:00") }
            .sorted { $0.match && !$1.match }
            .prefix(3)
        if !list.isEmpty {
            Label("On nearby", systemImage: "ticket").font(.system(size: 10, weight: .semibold)).textCase(.uppercase).kerning(1.4)
                .foregroundStyle(Theme.secondary).padding(.top, 22)
            Card {
                ForEach(Array(list)) { e in
                    Button { router.push(.events(tripId: tripId)) } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(e.name).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                                Text([e.time.map(Fmt.clock), e.venue].compactMap { $0 }.joined(separator: " · ")).font(.footnote).foregroundStyle(Theme.secondary)
                            }
                            Spacer(minLength: 0)
                            Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.quiet)
                        }
                        .padding(12)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.top, 8)
        }
    }

    // MARK: Briefing

    @ViewBuilder private func briefing(_ trip: TripDetail, day: Int, isToday: Bool) -> some View {
        let key = "\(day):\(isToday)"
        Card(padding: 14) {
            if let brief = briefings[key] {
                VStack(alignment: .leading, spacing: 8) {
                    Text(brief.headline).font(Theme.serif(20)).foregroundStyle(Theme.label)
                    ForEach(brief.points, id: \.self) { point in
                        HStack(alignment: .top, spacing: 8) {
                            Circle().fill(Theme.gold).frame(width: 5, height: 5).padding(.top, 7)
                            Text(point).font(.subheadline).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            } else {
                HStack(spacing: 10) { ProgressView(); Text("Reading the day…").font(.subheadline).foregroundStyle(Theme.secondary) }
            }
        }
        .padding(.top, 14)
        .task(id: key) {
            guard briefings[key] == nil else { return }
            var body: [String: Any?] = [:]
            if isToday { body["local_date"] = Fmt.iso(Date()) }
            if let brief: DayBriefing = try? await API.shared.post("/v1/trips/\(tripId)/days/\(day)/briefing", body) { briefings[key] = brief }
        }
    }

    // MARK: Stops

    private func time(_ trip: TripDetail, _ p: Place) -> String {
        TravelHome.clock(trip.minute(of: p.id) ?? TravelHome.minute(of: p))
    }

    private func nextCard(_ trip: TripDetail, _ p: Place, number: Int, of count: Int) -> some View {
        Card(padding: 14) {
            Eyebrow(text: "Next · stop \(number) of \(count)")
            NavigationLink(value: Route.place(id: p.id, tripId: tripId)) {
                HStack(spacing: 12) {
                    PlaceThumb(place: p, size: 64)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(p.name).font(Theme.serif(22)).foregroundStyle(Theme.label).lineLimit(2)
                        Text([time(trip, p), TravelHome.stopLabel(p)].joined(separator: " · ")).font(.footnote).foregroundStyle(Theme.secondary)
                        OpenStatusText(hours: p.openingHours).font(.footnote)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.quiet)
                }
                .padding(.top, 8)
            }
            .buttonStyle(.plain)
            HStack(spacing: 8) {
                Menu {
                    Button { Links.open(p.directionsURL) } label: { Label("Apple Maps", systemImage: "map") }
                    Button { Links.open(p.googleDirectionsURL) } label: { Label("Google Maps", systemImage: "globe") }
                } label: {
                    Label("Directions", systemImage: "arrow.up.right")
                        .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.accentInk)
                        .padding(.horizontal, 16).padding(.vertical, 9)
                        .frame(maxWidth: .infinity)
                        .background(Theme.accent, in: Capsule())
                }
                Button("I've been") { Task { await store.patch(p, ["visited": true], tripId: tripId) } }
                    .buttonStyle(PrimaryButtonStyle(tinted: true, compact: true))
            }
            .padding(.top, 12)
        }
    }

    private func stopRow(_ trip: TripDetail, _ p: Place, number: Int) -> some View {
        HStack(spacing: 12) {
            Text("\(number)").font(.caption.weight(.bold)).foregroundStyle(Category(p.category).color)
                .frame(width: 22, height: 22)
                .background(Category(p.category).color.opacity(0.14), in: Circle())
            NavigationLink(value: Route.place(id: p.id, tripId: tripId)) {
                HStack(spacing: 12) {
                    PlaceThumb(place: p, size: 44)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(p.name).font(.subheadline.weight(.semibold)).strikethrough(p.visited).foregroundStyle(Theme.label).lineLimit(1)
                        Text([time(trip, p), Category(p.category).label].joined(separator: " · ")).font(.footnote).foregroundStyle(Theme.secondary)
                    }
                    Spacer(minLength: 0)
                }
            }
            .buttonStyle(.plain)
            if p.visited {
                Button("Undo") { Task { await store.patch(p, ["visited": false], tripId: tripId) } }
                    .font(.footnote.weight(.semibold)).foregroundStyle(Theme.link).buttonStyle(.plain)
                    .accessibilityLabel("Mark \(p.name) not visited")
            }
        }
        .padding(.vertical, 8)
    }
}
