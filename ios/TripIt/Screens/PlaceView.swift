import MapKit
import SwiftUI

/// One place: photos, what the reel said, hours, how to get there, its folders and trips, and your notes.
/// Opened from a trip it also shows that trip's day and time for it.
struct PlaceView: View {
    let placeId: String
    let tripId: String?
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var detail: PlaceDetail?
    @State private var loadError: String?
    @State private var notes = ""
    @State private var notesLoaded = false
    @State private var sheet: LibrarySheet?
    @State private var confirmDelete = false
    @State private var locating = false
    @State private var locateQuery = ""
    @State private var allHours = false
    @State private var editingNote = false
    @FocusState private var noteFocused: Bool

    private var trip: TripDetail? { tripId.flatMap { store.tripDetails[$0] } }

    private var place: Place? {
        if let trip, let p = trip.places.first(where: { $0.id == placeId }) { return p }
        return store.places.first { $0.id == placeId } ?? detail?.place
    }

    var body: some View {
        Group {
            if let place {
                content(place)
            } else if let loadError {
                EmptyState(symbol: "mappin.slash", title: "Couldn't open this place", text: loadError)
                    .frame(maxHeight: .infinity)
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Theme.background.ignoresSafeArea())
        .task { await load() }
    }

    private func load() async {
        do {
            if let tripId, store.tripDetails[tripId] == nil { _ = try await store.loadTrip(tripId) }
            let fresh: PlaceDetail = try await API.shared.get("/v1/places/\(placeId)")
            detail = fresh
            if !notesLoaded { notes = fresh.place.userNotes; notesLoaded = true }
            await findReserveLink(fresh.place)
        } catch {
            loadError = error.localizedDescription
        }
    }

    /// Looks once, in the background, for the restaurant's Resy, OpenTable, Tock or SevenRooms page.
    private func findReserveLink(_ p: Place) async {
        guard Category(p.category).hasMenu, p.website != nil, p.reserveCheckedAt == nil else { return }
        if let fresh: Place = try? await API.shared.post("/v1/places/\(p.id)/reserve-link") {
            store.update(fresh)
            detail?.place = fresh
        }
    }

    @ViewBuilder private func content(_ p: Place) -> some View {
        let category = Category(p.category)
        let slotTrip = trip ?? memberTrip(p)
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Hero(place: p)
                VStack(alignment: .leading, spacing: 0) {
                    header(p, category)
                    if p.suggested, let trip { suggestedBanner(p, trip).padding(.top, 16) }
                    visitToggle(p).padding(.top, 18)
                    whySaved(p).padding(.top, 24)
                    mainAction(p, category).padding(.top, 20)
                    quietActions(p, category).padding(.top, 12)
                    if category == .event { eventSection(p).padding(.top, 28) }
                    if let slotTrip, !slotTrip.isLocal { tripSlot(p, slotTrip).padding(.top, 28) }
                    if !p.isLocated { locatePrompt(p).padding(.top, 20) }
                    goodToKnow(p).padding(.top, 28)
                    details(p).padding(.top, 28)
                    organize(p, category).padding(.top, 28)
                }
                .padding(.horizontal, 20)
                .padding(.top, 20)
                .padding(.bottom, 48)
            }
        }
        .ignoresSafeArea(edges: .top)
        .background(Theme.background.ignoresSafeArea())
        .toolbarBackground(.hidden, for: .navigationBar)
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ShareLink(item: p.googleMapsURL ?? AppConfig.baseURL, subject: Text(p.name), message: Text(p.name))
            moreMenu(p, slotTrip)
        }
        .sheet(item: $sheet) { $0.view.environment(store).environment(router) }
        .confirmationDialog("Delete this place everywhere? It leaves your Library, lists and trips.",
                            isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete place", role: .destructive) {
                Task { if await store.delete(p) { dismiss() } }
            }
        }
        .alert("Find on the map", isPresented: $locating) {
            TextField("Search, e.g. \(p.name), \(p.city)", text: $locateQuery)
            Button("Cancel", role: .cancel) {}
            Button("Find") { Task { await locate(p) } }
        } message: {
            Text("Add a street or neighbourhood if the first search didn't find it.")
        }
        .task(id: slotTrip?.id) {
            if let id = slotTrip?.id, store.tripDetails[id] == nil { _ = try? await store.loadTrip(id) }
        }
        .onDisappear { saveNotes(p) }
    }

    /// The trip this place is on (when it wasn't opened from one), so its day and time show here.
    private func memberTrip(_ p: Place) -> TripDetail? {
        guard let id = store.realTrips.first(where: { p.tripIds.contains($0.id) })?.id else { return nil }
        return store.tripDetails[id]
    }

    // MARK: Header

    private func header(_ p: Place, _ category: Category) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Eyebrow(text: [category.label, p.mustDo ? "Starred" : nil].compactMap { $0 }.joined(separator: " · "), color: Theme.tertiary)
            Text(p.name).font(Theme.serif(28)).foregroundStyle(Theme.label).fixedSize(horizontal: false, vertical: true)
            let loc = [p.neighborhood, p.city.isEmpty ? nil : p.city].compactMap { $0 }.joined(separator: ", ")
            if !loc.isEmpty { Text(loc).font(.subheadline).foregroundStyle(Theme.secondary) }
            statusLine(p)
            if let resolved = p.resolvedName, resolved != p.name {
                Text("On maps as \(resolved)").font(.footnote).foregroundStyle(Theme.secondary)
            }
            if p.confidence == "low" {
                Text("The name was hard to make out in the Reel; double-check it.").font(.footnote).foregroundStyle(Theme.attention)
            }
        }
    }

    /// "● Open now · until midnight · $$"
    @ViewBuilder private func statusLine(_ p: Place) -> some View {
        let status = Hours.status(p.openingHours)
        let price = p.priceHint.flatMap { $0.count <= 5 ? $0 : nil }
        if status != nil || price != nil {
            HStack(spacing: 6) {
                if let status {
                    Circle().fill(status.isOpen ? Theme.open : Theme.quiet).frame(width: 7, height: 7)
                    Text(status.isOpen ? "Open now" : "Closed").fontWeight(.semibold).foregroundStyle(status.isOpen ? Theme.open : Theme.secondary)
                    let rest = status.label.replacingOccurrences(of: "Open until ", with: "until ").replacingOccurrences(of: "Closed · ", with: "")
                    if rest != "Closed" && rest != "Open 24 hours" { Text("· " + rest).foregroundStyle(Theme.secondary) }
                }
                if let price { Text((status == nil ? "" : "· ") + price).foregroundStyle(Theme.secondary) }
            }
            .font(.subheadline)
            .padding(.top, 2)
        }
    }

    private func suggestedBanner(_ p: Place, _ trip: TripDetail) -> some View {
        Card(padding: 14) {
            HStack(spacing: 12) {
                Image(systemName: "sparkles").foregroundStyle(Theme.link)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Suggested for this trip").font(.subheadline.weight(.semibold))
                    Text(p.suggestionNote ?? "Added by AI to fill a quiet day").font(.caption).foregroundStyle(Theme.secondary)
                }
                Spacer()
                Button("Keep") {
                    Task {
                        await store.tripCall("POST", "/v1/trips/\(trip.id)/places/\(p.id)/keep")
                        await store.reloadPlaces()
                        store.show("Kept, and added to your Library")
                    }
                }
                .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.link)
            }
        }
    }

    /// Want to go | Been here
    /// One check button: tap to mark it visited (the circle fills in), tap again to undo.
    private func visitToggle(_ p: Place) -> some View {
        let on = p.visited
        return Button {
            Task { await store.patch(p, ["visited": !on]) }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: on ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 18, weight: .regular))
                    .foregroundStyle(on ? Theme.ok : Theme.tertiary)
                    .contentTransition(.symbolEffect(.replace))
                Text("Been here").font(.footnote.weight(on ? .semibold : .medium))
                    .foregroundStyle(on ? Theme.ok : Theme.label)
            }
            .padding(.leading, 8).padding(.trailing, 14).frame(minHeight: 34)
            .background(on ? Theme.ok.opacity(0.1) : .clear, in: Capsule())
            .overlay(Capsule().strokeBorder(on ? Theme.ok.opacity(0.4) : Theme.border, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .sensoryFeedback(.success, trigger: on) { _, new in new }
        .accessibilityAddTraits(on ? .isSelected : [])
        .accessibilityHint(on ? "Marks it as somewhere you still want to go" : "Marks it as visited")
    }

    // MARK: Why you saved it

    private func whySaved(_ p: Place) -> some View {
        let reel = detail?.reels.first
        let quote = p.tips ?? p.recommendedItems.first.map { "Order the \($0)." } ?? (p.summary.isEmpty ? nil : p.summary)
        return VStack(alignment: .leading, spacing: 12) {
            Text("Why you saved it").font(Theme.serif(19)).foregroundStyle(Theme.label)
            Card(padding: 14) {
                HStack(alignment: .top, spacing: 14) {
                    if let reel {
                        Button { Links.open(URL(string: reel.url)) } label: { ReelThumb(reel: reel, place: p) }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Watch the Reel")
                    }
                    VStack(alignment: .leading, spacing: 3) {
                        if let reel {
                            Text(reel.creator.map { "@\($0)" } ?? reel.platform.capitalized).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                            Text("From a Reel · saved \(Self.savedDate(p.createdAt))").font(.caption).foregroundStyle(Theme.secondary)
                        } else {
                            Text("Saved by you").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                            Text("Saved \(Self.savedDate(p.createdAt))").font(.caption).foregroundStyle(Theme.secondary)
                        }
                        if let quote {
                            Text("“\(quote)”").font(Theme.serif(15, weight: .regular)).italic().foregroundStyle(Theme.label)
                                .fixedSize(horizontal: false, vertical: true).padding(.top, 6)
                        }
                        if let reel {
                            Button("Watch the Reel") { Links.open(URL(string: reel.url)) }
                                .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.link).frame(minHeight: 36)
                        }
                        if p.mentionCount >= 2 {
                            Text("In \(p.mentionCount) of your saved Reels").font(.caption).foregroundStyle(Theme.secondary)
                        }
                    }
                    Spacer(minLength: 0)
                }
                if editingNote || !notes.isEmpty {
                    Divider().overlay(Theme.border).padding(.vertical, 12)
                    TextField("Your note", text: $notes, axis: .vertical)
                        .lineLimit(1...10)
                        .font(.subheadline)
                        .focused($noteFocused)
                        .onChange(of: notes) { _, _ in scheduleNotesSave(p) }
                }
            }
            if !editingNote && notes.isEmpty {
                Button { editingNote = true; noteFocused = true } label: {
                    Label("Add your own note", systemImage: "square.and.pencil").font(.subheadline.weight(.medium)).foregroundStyle(Theme.label)
                }
                .frame(minHeight: 36)
            }
        }
    }

    private static func savedDate(_ iso: String) -> String {
        guard let date = Fmt.day(iso) else { return "recently" }
        return date.formatted(.dateTime.day().month(.abbreviated))
    }

    // MARK: Actions

    private enum MainAction { case reserve(URL), tickets(URL), directions }

    private func main(_ p: Place, _ category: Category) -> MainAction {
        let booked = (trip ?? memberTrip(p))?.bookings.contains { $0.placeId == p.id && $0.kind == "reservation" } ?? false
        if !booked, let url = p.reserveUrl.flatMap({ URL(string: $0) }) { return .reserve(url) }
        if p.bookingKind == "tickets", p.shownNeed != nil, let url = p.website.flatMap({ URL(string: $0) }) { return .tickets(url) }
        return .directions
    }

    @ViewBuilder private func mainAction(_ p: Place, _ category: Category) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            switch main(p, category) {
            case .reserve(let url):
                Button { Links.open(url) } label: { Label("Book a table", systemImage: "calendar") }.buttonStyle(PrimaryButtonStyle())
            case .tickets(let url):
                Button { Links.open(url) } label: { Label("Get tickets", systemImage: "ticket") }.buttonStyle(PrimaryButtonStyle())
            case .directions:
                Menu {
                    Button { Links.open(p.directionsURL) } label: { Label("Apple Maps", systemImage: "map") }
                    Button { Links.open(p.googleDirectionsURL) } label: { Label("Google Maps", systemImage: "globe") }
                } label: {
                    Label("Directions", systemImage: "arrow.triangle.turn.up.right.diamond")
                        .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.accentInk)
                        .frame(maxWidth: .infinity, minHeight: 42)
                        .background(Theme.accent, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            }
            if let need = needText(p) {
                Label(need, systemImage: "info.circle").font(.footnote).foregroundStyle(p.shownNeed == "required" ? Theme.attention : Theme.secondary)
            }
        }
    }

    private func needText(_ p: Place) -> String? {
        guard let need = p.shownNeed, need != "none" else { return nil }
        let required = need == "required"
        let text: String
        if p.bookingKind == "tickets" { text = required ? "Tickets needed" : "Tickets recommended" }
        else { text = required ? "Book ahead" : "Booking recommended" }
        if let note = p.bookingNote { return text + ". " + note }
        return text + "."
    }

    /// Quiet buttons under the main one: Directions (unless it's the main one), Menu, Call, Website.
    private func quietActions(_ p: Place, _ category: Category) -> some View {
        let primary = main(p, category)
        let phone = p.phone.flatMap { URL(string: "tel:" + $0.filter { $0.isNumber || $0 == "+" }) }
        let site = p.website.flatMap { URL(string: $0) }
        var isDirections = false
        var isTickets = false
        switch primary { case .directions: isDirections = true; case .tickets: isTickets = true; default: break }
        return HStack(spacing: 10) {
            if !isDirections { DirectionsButton(apple: p.directionsURL, google: p.googleDirectionsURL) }
            if category.hasMenu, Features.isOn("menus") {
                Button { router.push(.menu(placeId: p.id)) } label: { QuietTileLabel(symbol: "menucard", title: "Menu") }.buttonStyle(.plain)
            }
            if let phone {
                Button { Links.open(phone) } label: { QuietTileLabel(symbol: "phone", title: "Call") }.buttonStyle(.plain)
            }
            if let site, !isTickets {
                Button { Links.open(site) } label: { QuietTileLabel(symbol: "globe", title: "Website") }.buttonStyle(.plain)
            }
        }
    }

    private func moreMenu(_ p: Place, _ slotTrip: TripDetail?) -> some View {
        Menu {
            Button { Task { await store.toggleStar(p) } } label: {
                Label(p.mustDo ? "Remove star" : "Star", systemImage: p.mustDo ? "star.slash" : "star")
            }
            Button { sheet = .trips([p.id]) } label: { Label("Add to a trip…", systemImage: "airplane") }
            Button { sheet = .folders([p.id]) } label: { Label("Add to a list…", systemImage: "list.bullet") }
            Button {
                locateQuery = [p.name, p.neighborhood, p.city].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ")
                locating = true
            } label: { Label(p.isLocated ? "Wrong pin? Search again" : "Find on the map", systemImage: "location.magnifyingglass") }
            if let slotTrip, !p.suggested {
                Button(role: .destructive) {
                    Task {
                        await store.removeFromTrip(slotTrip.id, p.id)
                        store.show("Removed from \(slotTrip.name). It's still in your Library.")
                        if trip != nil { dismiss() }
                    }
                } label: { Label("Remove from \(slotTrip.name)", systemImage: "minus.circle") }
            }
            Button(role: .destructive) { confirmDelete = true } label: { Label("Delete place", systemImage: "trash") }
        } label: {
            Image(systemName: "ellipsis")
        }
        .accessibilityLabel("More: star, lists, wrong pin, remove from trip, delete")
    }

    // MARK: Sections

    private func sectionTitle(_ text: String) -> some View {
        Text(text).font(Theme.serif(19)).foregroundStyle(Theme.label).padding(.bottom, 8)
    }

    private func eventSection(_ p: Place) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            sectionTitle("When")
            Card(padding: 14) {
                if let date = p.eventDate.flatMap(Fmt.day) {
                    DatePicker("Date", selection: Binding(get: { date }, set: { new in
                        Task { await store.patch(p, ["event_date": Fmt.iso(new)]) }
                    }), displayedComponents: .date)
                    if let end = p.eventEndDate { Text("Runs until \(Fmt.shortDay(end)).").font(.footnote).foregroundStyle(Theme.secondary) }
                    Button("Clear date", role: .destructive) { Task { await store.patch(p, ["clear_event_date": true]) } }
                        .font(.subheadline).padding(.top, 8)
                } else {
                    Button { Task { await store.patch(p, ["event_date": Fmt.iso(Date())]) } } label: {
                        infoRow("calendar.badge.plus", "Add the date", "So it shows on your calendar")
                    }
                    .buttonStyle(.plain)
                }
                if let venue = p.venue { infoRow("mappin", venue, nil).padding(.top, 10) }
            }
        }
    }

    /// The day, time and reservation on the trip this place is part of.
    private func tripSlot(_ p: Place, _ trip: TripDetail) -> some View {
        let member = trip.places.first { $0.id == p.id } ?? p
        let booking = trip.bookings.first { $0.placeId == p.id }
        return VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                sectionTitle("On your trip")
                Spacer()
                Button(trip.name) { router.push(.trip(id: trip.id)) }
                    .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.link).lineLimit(1)
            }
            Card {
                if trip.dayCount > 0 {
                    Menu {
                        Button("Not scheduled") { Task { await store.patch(p, ["day_number": 0], tripId: trip.id) } }
                        ForEach(1...trip.dayCount, id: \.self) { d in
                            Button(dayLabel(trip, d)) { Task { await store.patch(p, ["day_number": d], tripId: trip.id) } }
                        }
                    } label: {
                        slotRow("calendar", "Day", member.dayNumber.map { dayLabel(trip, $0) } ?? "Not scheduled", chevron: true)
                    }
                    Divider().overlay(Theme.border).padding(.leading, 48)
                    Menu {
                        Button("Any time") { Task { await store.patch(p, ["clear_time_of_day": true], tripId: trip.id) } }
                        ForEach(Fmt.timesOfDay, id: \.self) { t in
                            Button(t.capitalized) { Task { await store.patch(p, ["time_of_day": t], tripId: trip.id) } }
                        }
                        Divider()
                        Button("Set an exact time…") { Task { await store.patch(p, ["start_time": member.startTime ?? "19:00"], tripId: trip.id) } }
                        if member.startTime != nil {
                            Button("Clear exact time") { Task { await store.patch(p, ["clear_start_time": true], tripId: trip.id) } }
                        }
                    } label: {
                        slotRow("clock", "Time", timeLabel(member), chevron: true)
                    }
                    if let start = member.startTime, let date = clockDate(start) {
                        DatePicker("Exact time", selection: Binding(get: { date }, set: { new in
                            Task { await store.patch(p, ["start_time": hhmm(new)], tripId: trip.id) }
                        }), displayedComponents: .hourAndMinute)
                        .font(.subheadline)
                        .padding(.horizontal, 14).padding(.bottom, 8)
                    }
                    Divider().overlay(Theme.border).padding(.leading, 48)
                }
                if Category(p.category).hasMenu || p.shownNeed != nil || booking != nil {
                    Button { router.open("#/trip/\(trip.id)/bookings") } label: {
                        slotRow("ticket", "Reservation", booking.map { $0.title } ?? "Not booked yet", chevron: booking == nil,
                                attention: booking == nil && p.shownNeed == "required")
                    }
                }
            }
            .buttonStyle(.plain)
        }
    }

    private func dayLabel(_ trip: TripDetail, _ d: Int) -> String {
        [Fmt.tripDay(start: trip.startDate, day: d) ?? "Day \(d)", trip.city.isEmpty ? nil : trip.city].compactMap { $0 }.joined(separator: " · ")
    }

    private func timeLabel(_ p: Place) -> String {
        if let start = p.startTime { return Fmt.clock(start) }
        return p.timeOfDay?.capitalized ?? "Any time"
    }

    private func slotRow(_ symbol: String, _ title: String, _ value: String, chevron: Bool, attention: Bool = false) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol).frame(width: 22).foregroundStyle(Theme.secondary)
            Text(title).foregroundStyle(Theme.secondary)
            Spacer(minLength: 8)
            Text(value).fontWeight(.medium).foregroundStyle(attention ? Theme.attention : Theme.label).lineLimit(1)
            if chevron { Image(systemName: "chevron.up.chevron.down").font(.caption).foregroundStyle(Theme.quiet) }
        }
        .font(.subheadline)
        .padding(.horizontal, 14).frame(minHeight: 44)
        .contentShape(Rectangle())
    }

    private func locatePrompt(_ p: Place) -> some View {
        Button {
            locateQuery = [p.name, p.neighborhood, p.city].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ")
            locating = true
        } label: {
            Card(padding: 14) {
                HStack(spacing: 12) {
                    Image(systemName: "mappin.and.ellipse").foregroundStyle(Theme.attention)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Not on the map yet").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                        Text("Search for it to add the pin").font(.caption).foregroundStyle(Theme.secondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right").font(.footnote).foregroundStyle(Theme.quiet)
                }
            }
        }
        .buttonStyle(.plain)
    }

    private func locate(_ p: Place) async {
        do {
            let fresh: Place = try await API.shared.post("/v1/places/\(p.id)/locate", ["query": locateQuery])
            store.update(fresh)
            detail?.place = fresh
            if let tripId { _ = try? await store.loadTrip(tripId) }
            store.show("Found it")
        } catch { store.fail(error) }
    }

    /// Today's hours (tap for the week), tips, and the price and what it's like.
    private func goodToKnow(_ p: Place) -> some View {
        let quoteUsed = p.tips
        return VStack(alignment: .leading, spacing: 0) {
            sectionTitle("Good to know")
            Card {
                if let hours = p.openingHours, !hours.text.isEmpty {
                    Button { withAnimation(.snappy) { allHours.toggle() } } label: {
                        HStack(alignment: .top, spacing: 12) {
                            Image(systemName: "clock").frame(width: 22).foregroundStyle(Theme.secondary)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(todayHours(hours)).font(.subheadline.weight(.medium)).foregroundStyle(Theme.label)
                                Text("From \(hours.source == "google" ? "Google" : "OpenStreetMap") · hours change, check before you go")
                                    .font(.caption).foregroundStyle(Theme.secondary)
                            }
                            Spacer(minLength: 8)
                            Text(allHours ? "Less" : "All hours").font(.footnote.weight(.semibold)).foregroundStyle(Theme.link)
                        }
                        .padding(14)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    if allHours {
                        let today = Hours.mondayIndex()
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(Array(hours.text.enumerated()), id: \.offset) { i, line in
                                Text(line)
                                    .font(.footnote.weight(hours.weekly != nil && i == today ? .semibold : .regular))
                                    .foregroundStyle(hours.weekly != nil && i == today ? Theme.label : Theme.secondary)
                            }
                        }
                        .padding(.leading, 48).padding(.trailing, 14).padding(.bottom, 14)
                    }
                } else {
                    infoRow("clock", "No opening hours found", "Check Google Maps before you go").padding(14)
                }
                ForEach(p.recommendedItems.dropFirst(quoteUsed == nil ? 1 : 0), id: \.self) { item in
                    Divider().overlay(Theme.border).padding(.leading, 48)
                    infoRow("star", "Try the \(item)", nil).padding(14)
                }
                if let price = p.priceHint, !p.summary.isEmpty || price.count > 5 {
                    Divider().overlay(Theme.border).padding(.leading, 48)
                    infoRow("tag", [price, p.summary.isEmpty ? nil : p.summary].compactMap { $0 }.joined(separator: " · "), nil).padding(14)
                } else if !p.summary.isEmpty, p.tips != nil || !p.recommendedItems.isEmpty {
                    Divider().overlay(Theme.border).padding(.leading, 48)
                    infoRow("text.quote", p.summary, nil).padding(14)
                }
            }
        }
    }

    /// "Open today 8 AM – midnight", "Closed today".
    private func todayHours(_ hours: OpeningHours) -> String {
        guard let weekly = hours.weekly, weekly.count == 7 else { return hours.text.first ?? "Hours" }
        let ranges = weekly[Hours.mondayIndex()]
        if ranges.isEmpty { return "Closed today" }
        return "Open today " + ranges.map { "\(Fmt.clock($0.open)) – \(Fmt.clock($0.close))" }.joined(separator: ", ")
    }

    /// Address, phone, website, then the rating.
    private func details(_ p: Place) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            sectionTitle("Details")
            Card {
                let rows = detailRows(p)
                if rows.isEmpty { infoRow("info.circle", "No details yet", nil).padding(14) }
                ForEach(Array(rows.enumerated()), id: \.offset) { i, row in
                    if i > 0 { Divider().overlay(Theme.border).padding(.leading, 48) }
                    row
                }
            }
        }
    }

    private func detailRows(_ p: Place) -> [AnyView] {
        var rows: [AnyView] = []
        if let address = p.address {
            rows.append(AnyView(HStack(spacing: 12) {
                infoRow("mappin", address, nil)
                Button { UIPasteboard.general.string = address; store.show("Address copied") } label: {
                    Image(systemName: "doc.on.doc").foregroundStyle(Theme.secondary).frame(width: 44, height: 44)
                }
                .accessibilityLabel("Copy address")
            }.padding(.leading, 14).padding(.trailing, 4).padding(.vertical, 4)))
        }
        if let phone = p.phone {
            rows.append(AnyView(Button { Links.open(URL(string: "tel:" + phone.filter { $0.isNumber || $0 == "+" })) } label: {
                infoRow("phone", phone, nil).padding(14)
            }.buttonStyle(.plain)))
        }
        if let site = p.website, let url = URL(string: site) {
            rows.append(AnyView(Button { Links.open(url) } label: {
                infoRow("globe", (url.host ?? site).replacingOccurrences(of: "www.", with: ""), nil).padding(14)
            }.buttonStyle(.plain)))
        }
        if let rating = p.rating {
            let reviews = p.ratingCount.map { " · \($0.formatted()) reviews" } ?? ""
            rows.append(AnyView(Button { Links.open(p.googleMapsURL) } label: {
                infoRow("star", String(format: "%.1f on Google", rating) + reviews, nil, quiet: true).padding(14)
            }.buttonStyle(.plain)))
        }
        return rows
    }

    /// City (automatic), category and lists.
    private func organize(_ p: Place, _ category: Category) -> some View {
        let lists = store.folders.filter { p.folderIds.contains($0.id) }
        let trips = store.realTrips.filter { p.tripIds.contains($0.id) }
        return VStack(alignment: .leading, spacing: 0) {
            sectionTitle("Organize")
            Card {
                organizeRow("City") {
                    Text(store.isHome(p) ? "Around \(p.city) · automatic" : p.city.isEmpty ? "Unknown" : "\(p.city) · automatic")
                        .foregroundStyle(Theme.secondary)
                }
                Divider().overlay(Theme.border).padding(.leading, 14)
                organizeRow("Category") {
                    Menu {
                        ForEach(Category.allCases) { c in
                            Button { Task { await store.patch(p, ["category": c.rawValue]) } } label: { Label(c.label, systemImage: c.symbol) }
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Text(category.label).fontWeight(.medium)
                            Image(systemName: "chevron.up.chevron.down").font(.caption)
                        }
                        .foregroundStyle(Theme.label)
                    }
                }
                Divider().overlay(Theme.border).padding(.leading, 14)
                organizeRow("Lists") {
                    Button { sheet = .folders([p.id]) } label: {
                        Text(lists.isEmpty ? "Add to a list" : lists.map(\.name).joined(separator: ", "))
                            .fontWeight(.medium).foregroundStyle(lists.isEmpty ? Theme.link : Theme.label).lineLimit(1)
                    }
                }
                Divider().overlay(Theme.border).padding(.leading, 14)
                organizeRow("Trips") {
                    Button { sheet = .trips([p.id]) } label: {
                        Text(trips.isEmpty ? "Add to a trip" : trips.map(\.name).joined(separator: ", "))
                            .fontWeight(.medium).foregroundStyle(trips.isEmpty ? Theme.link : Theme.label).lineLimit(1)
                    }
                }
            }
            .buttonStyle(.plain)
        }
    }

    private func organizeRow<V: View>(_ title: String, @ViewBuilder value: () -> V) -> some View {
        HStack {
            Text(title).foregroundStyle(Theme.label)
            Spacer(minLength: 12)
            value()
        }
        .font(.subheadline)
        .padding(.horizontal, 14).frame(minHeight: 42)
    }

    private func infoRow(_ symbol: String, _ text: String, _ sub: String?, quiet: Bool = false) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol).frame(width: 22).foregroundStyle(Theme.secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(text).font(.subheadline).foregroundStyle(quiet ? Theme.secondary : Theme.label).fixedSize(horizontal: false, vertical: true)
                if let sub { Text(sub).font(.caption).foregroundStyle(Theme.secondary) }
            }
            Spacer(minLength: 0)
        }
        .contentShape(Rectangle())
    }

    // MARK: Notes and times

    @State private var notesTask: Task<Void, Never>?

    private func scheduleNotesSave(_ p: Place) {
        guard notesLoaded else { return }
        notesTask?.cancel()
        notesTask = Task {
            try? await Task.sleep(for: .seconds(1.2))
            if !Task.isCancelled { saveNotes(p) }
        }
    }

    private func saveNotes(_ p: Place) {
        guard notesLoaded, notes != (place?.userNotes ?? p.userNotes) else { return }
        let text = notes
        Task { await store.patch(p, ["user_notes": text]) }
    }

    private func clockDate(_ hhmm: String) -> Date? {
        let parts = hhmm.split(separator: ":").compactMap { Int($0) }
        guard parts.count == 2 else { return nil }
        return Calendar.current.date(bySettingHour: parts[0], minute: parts[1], second: 0, of: Date())
    }

    private func hhmm(_ date: Date) -> String {
        let c = Calendar.current.dateComponents([.hour, .minute], from: date)
        return String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0)
    }
}

struct QuickButton: View {
    let symbol: String
    let color: Color
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) { QuickLabel(symbol: symbol, color: color, title: title) }
            .buttonStyle(.plain)
    }
}

struct QuickLabel: View {
    let symbol: String
    let color: Color
    let title: String

    var body: some View {
        QuietTileLabel(symbol: symbol.replacingOccurrences(of: ".fill", with: ""), title: title)
    }
}

/// One Directions button; its menu opens right where you tap, with Apple Maps and Google Maps.
struct DirectionsButton: View {
    let apple: URL?
    let google: URL?

    var body: some View {
        Menu {
            Button { Links.open(apple) } label: { Label("Apple Maps", systemImage: "map") }
            Button { Links.open(google) } label: { Label("Google Maps", systemImage: "globe") }
        } label: {
            QuickLabel(symbol: "arrow.triangle.turn.up.right.diamond.fill", color: Theme.orange, title: "Directions")
        }
        .buttonStyle(.plain)
    }
}

/// Swipe through the place's photos, with its spot on the map as the last page. Runs edge to edge under the
/// navigation buttons.
private struct Hero: View {
    let place: Place
    @State private var page = 0

    var body: some View {
        let photos = place.photos
        let pages = photos.count + (place.isLocated ? 1 : 0)
        Group {
            if pages > 0 {
                TabView(selection: $page) {
                    ForEach(Array(photos.enumerated()), id: \.offset) { i, photo in
                        Color.clear
                            .overlay { RemoteImage(url: photo.url(width: 1200)) { Theme.raised } }
                            .clipped()
                            .overlay(alignment: .bottomLeading) {
                                if let credit = photo.attribution ?? (photo.source == "reel" ? "From the Reel" : nil) {
                                    Text(credit).font(.caption2).foregroundStyle(.white.opacity(0.9))
                                        .lineLimit(1).truncationMode(.middle)
                                        .frame(maxWidth: 150, alignment: .leading)
                                        .padding(.horizontal, 8).padding(.vertical, 4)
                                        .background(.black.opacity(0.35), in: Capsule())
                                        .padding(.leading, 12).padding(.bottom, 28)
                                }
                            }
                            .tag(i)
                    }
                    if let coordinate = place.coordinate {
                        Map(initialPosition: .region(MKCoordinateRegion(center: coordinate, latitudinalMeters: 700, longitudinalMeters: 700))) {
                            Marker(place.name, systemImage: Category(place.category).symbol, coordinate: coordinate)
                                .tint(Theme.gold)
                        }
                        .allowsHitTesting(false)
                        .tag(photos.count)
                    }
                }
                .tabViewStyle(.page(indexDisplayMode: pages > 1 ? .always : .never))
            } else {
                ZStack {
                    Theme.raised
                    Image(systemName: Category(place.category).symbol).font(.system(size: 40)).foregroundStyle(Theme.secondary)
                }
            }
        }
        .frame(height: 280)
        .frame(maxWidth: .infinity)
        .overlay(alignment: .top) {
            // keeps the status bar and buttons readable over a bright photo
            LinearGradient(colors: [.black.opacity(0.35), .clear], startPoint: .top, endPoint: .bottom).frame(height: 110).allowsHitTesting(false)
        }
    }
}

/// The Reel a place was saved from: a frame from it (or its thumbnail) with a play mark.
struct ReelThumb: View {
    let reel: Reel
    let place: Place

    var body: some View {
        let frame = place.photos.first { $0.source == "reel" }
        let url = frame?.url(width: 240) ?? reel.thumbnailUrl.flatMap { API.shared.url($0) }
        Color.clear
            .frame(width: 52, height: 70)
            .overlay { RemoteImage(url: url) { Theme.raised } }
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay {
                Image(systemName: "play.fill").font(.system(size: 11)).foregroundStyle(.white)
                    .frame(width: 24, height: 24).background(.black.opacity(0.4), in: Circle())
            }
    }
}
