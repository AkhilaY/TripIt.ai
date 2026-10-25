import CoreLocation
import SwiftUI

/// After a Reel is read: its places, grouped by city and already filed there (your home city is "Around <city>",
/// anywhere else is that city's wishlist). Untick any you don't want, add them to a trip that passes through
/// (matched to the right stop, with places off the route offered as day trips) or to a list.
struct SaveReviewSheet: View {
    let job: Job
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var location = Location.shared
    @State private var unticked = Set<String>()
    @State private var addToTrip = true
    @State private var dayTrips = Set<String>()
    @State private var lists = Set<String>()
    @State private var busy = false
    @State private var newList = false
    @State private var newListName = ""

    private var places: [Place] {
        guard let reel = job.reelId else { return [] }
        return store.places.filter { $0.reelIds.contains(reel) }
    }

    /// Saved by this Reel (the rest were in your Library already).
    private func isNew(_ p: Place) -> Bool { p.createdAt >= job.createdAt }

    private var groups: [Store.CityGroup] {
        Dictionary(grouping: places) { Store.cityKey($0.city) }
            .map { _, items in Store.CityGroup(name: items[0].city, country: items[0].country, places: items) }
            .sorted { $0.places.count > $1.places.count }
    }

    private var allHome: Bool { !places.isEmpty && places.allSatisfy { store.isHome($0) } }

    /// The upcoming trip whose route passes through any of these cities.
    private var trip: Trip? {
        guard !allHome else { return nil }
        let keys = Set(places.map { Store.cityKey($0.city) })
        return store.upcomingTrips.first { t in t.cities.contains { keys.contains(Store.cityKey($0)) } }
    }

    private func stop(for city: String, in trip: Trip) -> (Int, TripStop)? {
        let key = Store.cityKey(city)
        guard let i = (trip.stops ?? []).firstIndex(where: { Store.cityKey($0.city) == key }) else { return nil }
        return (i, trip.stops![i])
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    header
                    if places.isEmpty {
                        Text("No places were found in this post.").font(.subheadline).foregroundStyle(Theme.secondary).padding(.top, 16)
                    }
                    if let trip, !allHome { tripToggle(trip).padding(.top, 16) }
                    ForEach(groups) { group in groupSection(group) }
                    filing.padding(.top, 20)
                    listChips.padding(.top, 18)
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 24)
            }
            .background(Theme.background.ignoresSafeArea())
            .safeAreaInset(edge: .bottom) {
                VStack(spacing: 8) {
                    Button(saveLabel) { Task { await save() } }
                        .buttonStyle(PrimaryButtonStyle())
                        .disabled(busy)
                    if trip == nil, !allHome, let city = groups.first?.name {
                        Button("Plan a trip to \(city)") { Task { await save(); planTrip(city) } }
                            .font(.footnote.weight(.semibold)).foregroundStyle(Theme.link)
                    }
                }
                .padding(.horizontal, 20).padding(.vertical, 10)
                .background(Theme.background)
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
                ToolbarItem(placement: .principal) {
                    Text("THE TRAVEL EDIT").font(Theme.serif(14, weight: .semibold)).kerning(2)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .alert("New list", isPresented: $newList) {
                TextField("e.g. Date night", text: $newListName)
                Button("Cancel", role: .cancel) {}
                Button("Create") {
                    Task {
                        let name = newListName.trimmingCharacters(in: .whitespaces)
                        if !name.isEmpty, let folder = await store.createFolder(name) { lists.insert(folder.id) }
                    }
                }
            }
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(Theme.serif(24)).foregroundStyle(Theme.label)
            HStack(spacing: 6) {
                if allHome {
                    Label("Your city", systemImage: "house").font(.caption2.weight(.semibold)).foregroundStyle(Theme.gold)
                        .padding(.horizontal, 7).padding(.vertical, 3).background(Theme.gold.opacity(0.14), in: Capsule())
                } else if groups.count > 1 {
                    Text("Sorted by city").font(.caption).foregroundStyle(Theme.secondary)
                }
                if let who = job.reel?.uploader { Text((groups.count > 1 && !allHome ? "· " : "") + "from @\(who)").font(.caption).foregroundStyle(Theme.secondary) }
            }
        }
        .padding(.top, 8)
    }

    private var title: String {
        let n = Fmt.plural(places.count, "place")
        if groups.count == 1, let city = groups.first?.name, !city.isEmpty { return "\(n) in \(city)" }
        if groups.count > 1 {
            let countries = Set(places.map(\.country).filter { !$0.isEmpty })
            return countries.count == 1 ? "\(n) across \(countries.first!)" : "\(n) in \(groups.count) cities"
        }
        return n
    }

    // MARK: Trip

    private func tripToggle(_ trip: Trip) -> some View {
        Card(radius: 14, padding: 12) {
            HStack(spacing: 12) {
                TripCover(trip: trip, size: 40)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Add to \(trip.name)").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                    Text([trip.dateRange, trip.cities.joined(separator: " → ")].compactMap { $0 }.joined(separator: " · "))
                        .font(.caption).foregroundStyle(Theme.secondary).lineLimit(1)
                }
                Spacer(minLength: 8)
                Toggle("Add to \(trip.name)", isOn: $addToTrip).labelsHidden().tint(Theme.gold)
            }
        }
    }

    // MARK: Groups

    @ViewBuilder private func groupSection(_ group: Store.CityGroup) -> some View {
        let onRoute = trip.flatMap { stop(for: group.name, in: $0) }
        HStack(alignment: .firstTextBaseline) {
            Text(onRoute == nil && trip != nil && addToTrip ? "Not on your route" : (group.name.isEmpty ? "Somewhere" : group.name))
                .font(Theme.serif(18)).foregroundStyle(Theme.label)
            Spacer()
            if let route = onRoute, addToTrip, let trip {
                Text("Stop \(route.0 + 1)" + (dayRange(route.1, trip).map { " · \($0)" } ?? "")).font(.caption).foregroundStyle(Theme.secondary)
            } else if onRoute == nil, trip != nil, addToTrip {
                Text(group.name).font(.caption).foregroundStyle(Theme.secondary)
            }
        }
        .padding(.top, 20)
        VStack(spacing: 0) {
            ForEach(group.places) { p in
                if onRoute == nil, let trip, addToTrip { dayTripRow(p, trip: trip) } else { placeRow(p) }
                if p.id != group.places.last?.id { Divider().overlay(Theme.divider) }
            }
        }
    }

    private func placeRow(_ p: Place) -> some View {
        let fresh = isNew(p)
        let ticked = !unticked.contains(p.id)
        return Button {
            guard fresh else { return }
            if ticked { unticked.insert(p.id) } else { unticked.remove(p.id) }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: fresh ? (ticked ? "checkmark.circle.fill" : "circle") : "checkmark.seal")
                    .font(.system(size: 18)).foregroundStyle(fresh ? (ticked ? Theme.gold : Theme.quiet) : Theme.secondary)
                PlaceThumb(place: p, size: 40)
                VStack(alignment: .leading, spacing: 2) {
                    Text(p.name).font(.subheadline.weight(.semibold)).foregroundStyle(ticked || !fresh ? Theme.label : Theme.secondary).lineLimit(1)
                    Text(fresh ? subtitle(p) : (p.visited ? "Already saved · You've been here" : "Already saved"))
                        .font(.caption).foregroundStyle(Theme.secondary).lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(ticked && fresh ? .isSelected : [])
    }

    private func dayTripRow(_ p: Place, trip: Trip) -> some View {
        let on = dayTrips.contains(p.id)
        return HStack(spacing: 12) {
            PlaceThumb(place: p, size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(p.name).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label).lineLimit(1)
                Text(nearestStopText(p, trip: trip) ?? Category(p.category).label).font(.caption).foregroundStyle(Theme.secondary).lineLimit(1)
            }
            Spacer(minLength: 8)
            Button(on ? "Day trip added" : "Add as day trip") {
                if on { dayTrips.remove(p.id) } else { dayTrips.insert(p.id) }
            }
            .font(.caption.weight(.semibold))
            .foregroundStyle(on ? Theme.background : Theme.label)
            .padding(.horizontal, 10).frame(height: 28)
            .background(on ? Theme.label : Theme.raised, in: Capsule())
            .buttonStyle(.plain)
        }
        .padding(.vertical, 8)
    }

    private func subtitle(_ p: Place) -> String {
        var parts = [p.neighborhood, Category(p.category).label].compactMap { $0 }
        if let d = p.distance(from: location.current), d < 50_000 { parts.append(Fmt.distance(d)) }
        if let trip, addToTrip, let route = stop(for: p.city, in: trip), let range = dayRange(route.1, trip) { parts.append(range) }
        return parts.joined(separator: " · ")
    }

    private func dayRange(_ stop: TripStop, _ trip: Trip) -> String? {
        if let start = Fmt.isoDay(start: trip.startDate, day: stop.startDay).flatMap(Fmt.day),
           let end = Fmt.isoDay(start: trip.startDate, day: stop.endDay).flatMap(Fmt.day) { return Fmt.range(start, end) }
        return stop.startDay == stop.endDay ? "Day \(stop.startDay)" : "Days \(stop.startDay)–\(stop.endDay)"
    }

    /// "About 2 hr from Interlaken": by straight-line distance to the closest stop's saved places.
    private func nearestStopText(_ p: Place, trip: Trip) -> String? {
        guard let c = p.coordinate else { return nil }
        let here = CLLocation(latitude: c.latitude, longitude: c.longitude)
        var best: (String, Double)?
        for city in Set(trip.cities) {
            let key = Store.cityKey(city)
            for q in store.saved where Store.cityKey(q.city) == key {
                guard let qc = q.coordinate else { continue }
                let d = here.distance(from: CLLocation(latitude: qc.latitude, longitude: qc.longitude))
                if best == nil || d < best!.1 { best = (city, d) }
            }
        }
        guard let best else { return nil }
        let city = best.0
        let minutes = Int(best.1 / 1000 / 70 * 60)  // about 70 km/h by road or rail
        return minutes < 20 ? "Close to \(city)" : "About \(TravelHome.duration(minutes)) from \(city)"
    }

    // MARK: Filing and lists

    private var filing: some View {
        VStack(alignment: .leading, spacing: 8) {
            Eyebrow(text: "Files to", color: Theme.secondary)
            Card(radius: 14, padding: 12) {
                HStack(spacing: 12) {
                    Image(systemName: allHome ? "house" : "building.2").foregroundStyle(Theme.label)
                        .frame(width: 34, height: 34).background(Theme.raised, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(fileTitle).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                        Text(fileSubtitle).font(.caption).foregroundStyle(Theme.secondary)
                    }
                    Spacer(minLength: 0)
                }
            }
        }
    }

    private var fileTitle: String {
        if allHome, let home = store.home { return "Around \(home.city)" }
        let cities = groups.map(\.name).filter { !$0.isEmpty }
        return cities.count <= 2 ? cities.joined(separator: " and ") : "\(cities.count) cities"
    }

    private var fileSubtitle: String {
        if allHome { return "Your city, sorted by neighbourhood" }
        if trip != nil && addToTrip { return "Each city, and its stop on your trip" }
        return groups.count == 1 ? "Your \(groups[0].name) wishlist, no trip yet" : "Each city's wishlist"
    }

    private var listChips: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 4) {
                Eyebrow(text: "Also add to", color: Theme.secondary)
                Text("(optional)").font(.caption2).foregroundStyle(Theme.tertiary)
            }
            FlowChips {
                ForEach(store.folders) { folder in
                    let on = lists.contains(folder.id)
                    Button { if on { lists.remove(folder.id) } else { lists.insert(folder.id) } } label: {
                        Label(folder.name, systemImage: on ? "checkmark" : "list.bullet")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(on ? Theme.background : Theme.label)
                            .padding(.horizontal, 10).frame(height: 30)
                            .background(on ? Theme.label : Theme.cell, in: Capsule())
                            .overlay(Capsule().strokeBorder(Theme.border, lineWidth: on ? 0 : 1))
                    }
                    .buttonStyle(.plain)
                }
                Button { newListName = ""; newList = true } label: {
                    Label("New list", systemImage: "plus").font(.caption.weight(.medium)).foregroundStyle(Theme.link)
                        .padding(.horizontal, 10).frame(height: 30)
                        .overlay(Capsule().strokeBorder(Theme.border))
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: Saving

    private var kept: [Place] { places.filter { !unticked.contains($0.id) } }

    private var saveLabel: String {
        if busy { return "Saving…" }
        let n = kept.filter(isNew).count
        if let trip, addToTrip { return n > 0 ? "Save \(Fmt.plural(n, "place")) to \(trip.name)" : "Add to \(trip.name)" }
        return n > 0 ? "Save \(Fmt.plural(n, "place"))" : "Done"
    }

    private func save() async {
        busy = true
        defer { busy = false }
        // Unticked new places leave the Library (they were saved while the Reel was read).
        for p in places where unticked.contains(p.id) && isNew(p) {
            _ = await store.delete(p)
        }
        let keep = kept
        if let trip, addToTrip {
            let ids = keep.filter { stop(for: $0.city, in: trip) != nil || dayTrips.contains($0.id) }
                .filter { !$0.tripIds.contains(trip.id) }.map(\.id)
            if !ids.isEmpty { await store.addToTrip(trip.id, ids) }
        }
        for folder in lists {
            let ids = keep.filter { !$0.folderIds.contains(folder) }.map(\.id)
            if !ids.isEmpty { await store.addToFolder(folder, ids) }
        }
        // Dated events go straight into Apple Calendar, with reminders.
        let events = keep.filter { Category($0.category) == .event && $0.eventDate != nil }
        if !events.isEmpty {
            let added = await EventSync.shared.add(events)
            if added > 0 { store.show(added == 1 ? "Added to your calendar, with reminders" : "\(added) events added to your calendar, with reminders") }
        }
        store.reviewJob = nil
        dismiss()
    }

    private func planTrip(_ city: String) {
        router.tab = .library
        router.push(.city(name: city))
    }
}

/// Chips that wrap onto new lines.
struct FlowChips<Content: View>: View {
    @ViewBuilder var content: () -> Content

    var body: some View {
        FlowLayout(spacing: 8) { content() }
    }
}

struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, row: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width { x = 0; y += row + spacing; row = 0 }
            x += size.width + spacing
            row = max(row, size.height)
        }
        return CGSize(width: width.isFinite ? width : x, height: y + row)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, row: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX { x = bounds.minX; y += row + spacing; row = 0 }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            row = max(row, size.height)
        }
    }
}
