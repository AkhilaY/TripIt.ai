import SwiftUI
import UIKit

/// Everything dated in one place: saved events, bookings, planned trip days and trips. A month at the top, then
/// what's on from the day you pick to the end of the month, and saved events that still need a date.
struct CalendarView: View {
    /// The Calendar tab (with your profile button), rather than a screen pushed from elsewhere.
    var isTab = false
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @State private var result: CalendarResult?
    @State private var error: String?
    @State private var filter = "all"
    @State private var month = String(Fmt.iso(Date()).prefix(7))  // "2026-10"
    @State private var selected: String?
    @State private var syncing = false
    @State private var dating: CalendarItem?

    struct Filter: Identifiable {
        let id: String
        let label: String
    }

    static let filters = [Filter(id: "all", label: "All"), Filter(id: "event", label: "Events"),
                          Filter(id: "booking", label: "Bookings"), Filter(id: "stop", label: "Plans")]

    /// A day of the agenda and what's listed on it.
    struct AgendaDay: Identifiable {
        let id: String
        let items: [CalendarItem]
    }

    static func color(_ kind: String) -> Color {
        switch kind {
        case "event": Theme.dynamic(0xA4537C, 0xD08AB0)
        case "booking": Theme.dynamic(0x4E78A6, 0x8AAFD8)
        case "stop": Theme.dynamic(0x5B827C, 0x86AFA8)
        default: Theme.dynamic(0xB08A4E, 0xD2B07A)
        }
    }

    private var today: String { Fmt.iso(Date()) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if let error {
                    EmptyState(symbol: "wifi.slash", title: "Couldn't load your calendar", text: error) {
                        Button("Try again") { Task { await load() } }.buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 200)
                    }
                } else if let result {
                    if result.items.isEmpty && result.undated.isEmpty {
                        EmptyState(symbol: "calendar", color: Self.color("event"), title: "Nothing on your calendar yet",
                                   text: "Save a reel about a pop-up, a class or a show and it lands here on its date. Bookings and planned trip days appear too.")
                    } else {
                        content(result)
                    }
                } else {
                    ProgressView().frame(maxWidth: .infinity).padding(.top, 80)
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 40)
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle("Calendar")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { syncing = true } label: { Label("Sync", systemImage: "calendar.badge.plus") }
            }
            if isTab {
                ToolbarItem(placement: .topBarTrailing) { ProfileButton() }
            }
        }
        .task { await load() }
        .refreshable { await load() }
        .sheet(isPresented: $syncing) { CalendarSyncSheet(feed: result?.feed) { result?.feed = $0 } }
        .sheet(item: $dating) { item in
            EventDateSheet(item: item) { Task { await load(); await store.reloadPlaces() } }
        }
    }

    private func load() async {
        do {
            result = try await API.shared.get("/v1/calendar")
            error = nil
        } catch is CancellationError {
        } catch { self.error = error.localizedDescription }
    }

    // MARK: Content

    private func filtered(_ items: [CalendarItem]) -> [CalendarItem] {
        filter == "all" ? items : items.filter { $0.kind == filter || (filter == "stop" && $0.kind == "trip") }
    }

    /// Each item on every day it covers (a hotel stay or a week-long pop-up shows on all its days).
    private func byDay(_ items: [CalendarItem]) -> [String: [CalendarItem]] {
        var map: [String: [CalendarItem]] = [:]
        for item in items {
            guard let start = item.date else { continue }
            let end = item.endDate ?? start
            var day = start
            var guardCount = 0
            while day <= end, guardCount < 400 {
                map[day, default: []].append(item)
                day = BookingTime.addDays(day, 1)
                guardCount += 1
            }
        }
        return map
    }

    @ViewBuilder private func content(_ result: CalendarResult) -> some View {
        let items = filtered(result.items)
        let days = byDay(items)
        let tripDays = byDay(result.items.filter { $0.kind == "trip" })
        Text(weekLine(result.items)).font(.subheadline).foregroundStyle(Theme.secondary)
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(Self.filters) { f in
                    let count = f.id == "all" ? result.items.filter { $0.kind != "trip" }.count
                        : result.items.filter { $0.kind == f.id }.count + (f.id == "event" ? result.undated.count : 0)
                    FilterChip(label: f.label, count: count, isOn: filter == f.id) { filter = f.id }
                }
            }
        }
        .padding(.top, 12)
        MonthGrid(month: $month, selected: $selected, days: days, tripDays: tripDays, today: today)
            .padding(.top, 14)
        agenda(result, days: days)
        let undated = filter == "all" || filter == "event" ? result.undated : []
        if !undated.isEmpty {
            Eyebrow(text: "Saved events without a date", color: Theme.secondary).padding(.top, 24)
            Card {
                ForEach(undated) { item in
                    HStack(spacing: 12) {
                        Button { if let id = item.placeId { router.push(.place(id: id, tripId: nil)) } } label: {
                            HStack(spacing: 12) {
                                SymbolTile(symbol: Category.event.symbol, color: Category.event.color)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(item.title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                                    if let sub = item.subtitle { Text(sub).font(.footnote).foregroundStyle(Theme.secondary) }
                                }
                                Spacer(minLength: 0)
                            }
                        }
                        .buttonStyle(.plain)
                        Button("Set date") { dating = item }
                            .buttonStyle(PrimaryButtonStyle(tinted: true, compact: true)).fixedSize()
                    }
                    .padding(12)
                    if item.id != undated.last?.id { Divider().overlay(Theme.divider) }
                }
            }
            .padding(.top, 8)
            Text("Add a date and they appear on the calendar.").font(.footnote).foregroundStyle(Theme.secondary).padding(.top, 6)
        }
    }

    private func weekLine(_ items: [CalendarItem]) -> String {
        let end = BookingTime.addDays(today, 6)
        let soon = items.filter { ($0.date ?? "") >= today && ($0.date ?? "") <= end }
        let events = soon.filter { $0.kind == "event" }.count
        let bookings = soon.filter { $0.kind == "booking" }.count
        let parts = [events > 0 ? Fmt.plural(events, "event") : nil, bookings > 0 ? Fmt.plural(bookings, "booking") : nil].compactMap { $0 }
        return parts.isEmpty ? "No events or bookings in the next 7 days" : parts.joined(separator: " and ") + " in the next 7 days"
    }

    // MARK: Agenda

    @ViewBuilder private func agenda(_ result: CalendarResult, days: [String: [CalendarItem]]) -> some View {
        let isThisMonth = month == String(today.prefix(7))
        let start = selected.flatMap { $0.hasPrefix(month) ? $0 : nil } ?? (isThisMonth ? today : "\(month)-01")
        let end = "\(month)-31"
        let agendaDays = days.keys.filter { $0 >= start && $0 <= end }.sorted()
        let shown = agendaDays.compactMap { day -> AgendaDay? in
            // Something lasting several days is listed once: on its first day, as ongoing at the top, or on a tapped day.
            let list = (days[day] ?? []).filter { item in
                item.kind == "trip" ? item.date == day
                    : item.endDate == nil || item.date == day || day == selected || (day == agendaDays.first && (item.date ?? "") < day)
            }
            return list.isEmpty ? nil : AgendaDay(id: day, items: list)
        }
        if shown.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text(selected.map { days[$0] == nil ? "Nothing on \(Fmt.shortDay($0))." : "Nothing else this month." } ?? "Nothing else this month.")
                    .font(.subheadline).foregroundStyle(Theme.secondary)
                if let next = filtered(result.items).first(where: { ($0.date ?? "") > end }), let date = next.date {
                    Button("Show what's next") { month = String(date.prefix(7)); selected = date }
                        .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.link)
                }
            }
            .padding(.top, 20)
        }
        ForEach(shown) { entry in
            Eyebrow(text: (entry.id == today ? "Today · " : "") + Fmt.shortDay(entry.id), color: entry.id == selected ? Theme.gold : Theme.secondary)
                .padding(.top, 20)
            Card {
                let rows = agendaRows(entry.items, day: entry.id, all: result.items)
                ForEach(rows) { row in
                    AgendaRow(row: row) { open(row) }
                    if row.id != rows.last?.id { Divider().overlay(Theme.divider) }
                }
            }
            .padding(.top, 8)
        }
    }

    struct Row: Identifiable {
        let id: String
        let kind: String
        let when: String
        let title: String
        let subtitle: String?
        let item: CalendarItem?
        var planTrip: String?
        var planDay: Int?
    }

    /// A day of a planned trip shows as one row (Plans shows every stop).
    private func agendaRows(_ list: [CalendarItem], day: String, all: [CalendarItem]) -> [Row] {
        var rows: [Row] = []
        var plans: Set<String> = []
        for item in list {
            if item.kind != "stop" || filter != "all" {
                rows.append(Row(id: item.id, kind: item.kind, when: when(item, day: day), title: item.title, subtitle: item.subtitle, item: item))
                continue
            }
            guard let tripId = item.tripId, !plans.contains(tripId) else { continue }
            plans.insert(tripId)
            let same = list.filter { $0.kind == "stop" && $0.tripId == tripId }
            let trip = all.first { $0.kind == "trip" && $0.tripId == tripId }
            let n = trip?.date.map { BookingTime.days(from: $0, to: day) + 1 }
            let names = same.prefix(3).map(\.title).joined(separator: ", ") + (same.count > 3 ? " + \(same.count - 3) more" : "")
            rows.append(Row(id: "plan:\(tripId):\(day)", kind: "stop", when: n.map { "Day \($0)" } ?? "Plan",
                            title: "\(trip.map { "\($0.title) plan" } ?? "Your plan") · \(Fmt.plural(same.count, "stop"))",
                            subtitle: names, item: nil, planTrip: tripId, planDay: n))
        }
        return rows
    }

    private func when(_ item: CalendarItem, day: String) -> String {
        if item.kind == "trip" { return "Trip" }
        if item.endDate != nil, day != item.date { return day == item.endDate ? "Last day" : "Ongoing" }
        if let time = item.time { return Fmt.clock(time) }
        return item.partOfDay.map { $0.capitalized } ?? "All day"
    }

    private func open(_ row: Row) {
        if let tripId = row.planTrip { router.push(.today(tripId: tripId, day: row.planDay)); return }
        guard let item = row.item else { return }
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

/// One line of the agenda: when, a coloured bar, what, and for events and bookings a way into your calendar app.
private struct AgendaRow: View {
    let row: CalendarView.Row
    let onOpen: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Button(action: onOpen) {
                HStack(spacing: 10) {
                    Text(row.when).font(.footnote.weight(.semibold)).foregroundStyle(Theme.secondary).frame(width: 64, alignment: .leading)
                    RoundedRectangle(cornerRadius: 2).fill(CalendarView.color(row.kind).opacity(row.kind == "trip" ? 0.5 : 1)).frame(width: 3, height: 34)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(row.title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label).lineLimit(2)
                        if let sub = row.subtitle { Text(sub).font(.footnote).foregroundStyle(Theme.secondary).lineLimit(2) }
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if let item = row.item, item.kind == "event" || item.kind == "booking", item.googleUrl != nil || item.icsUrl != nil {
                Menu {
                    if let ics = item.icsUrl, let url = API.shared.url(ics) {
                        Button { UIApplication.shared.open(url) } label: { Label("Apple Calendar", systemImage: "calendar") }
                    }
                    if let google = item.googleUrl, let url = URL(string: google) {
                        Button { Links.open(url) } label: { Label("Google Calendar", systemImage: "globe") }
                    }
                } label: {
                    Image(systemName: "calendar.badge.plus").foregroundStyle(Theme.link).frame(width: 36, height: 36)
                }
                .accessibilityLabel("Add \(item.title) to your calendar app")
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
    }
}

/// The month: a dot for each kind of thing on a day, trip days tinted, today ringed. Tap a day to start the
/// agenda there.
private struct MonthGrid: View {
    @Binding var month: String
    @Binding var selected: String?
    let days: [String: [CalendarItem]]
    let tripDays: [String: [CalendarItem]]
    let today: String

    private var calendar: Calendar { Calendar.current }

    private var firstOfMonth: Date { Fmt.day("\(month)-01") ?? Date() }

    var body: some View {
        let count = calendar.range(of: .day, in: .month, for: firstOfMonth)?.count ?? 30
        let weekday = calendar.component(.weekday, from: firstOfMonth)
        let lead = (weekday - calendar.firstWeekday + 7) % 7
        let symbols = calendar.veryShortStandaloneWeekdaySymbols
        let ordered = Array(symbols[(calendar.firstWeekday - 1)...] + symbols[..<(calendar.firstWeekday - 1)])
        let columns = Array(repeating: GridItem(.flexible(), spacing: 0), count: 7)
        Card(padding: 12) {
            HStack {
                Button { step(-1) } label: { Image(systemName: "chevron.left").frame(width: 36, height: 36) }
                    .accessibilityLabel("Previous month")
                Spacer()
                Text(firstOfMonth.formatted(.dateTime.month(.wide).year())).font(Theme.serif(20)).foregroundStyle(Theme.label)
                Spacer()
                if month != String(today.prefix(7)) {
                    Button("Today") { month = String(today.prefix(7)); selected = nil }.font(.footnote.weight(.semibold))
                }
                Button { step(1) } label: { Image(systemName: "chevron.right").frame(width: 36, height: 36) }
                    .accessibilityLabel("Next month")
            }
            .foregroundStyle(Theme.link)
            .buttonStyle(.plain)
            HStack(spacing: 0) {
                ForEach(ordered.indices, id: \.self) { i in
                    Text(ordered[i]).font(.caption2.weight(.semibold)).foregroundStyle(Theme.tertiary).frame(maxWidth: .infinity, minHeight: 20)
                }
            }
            .padding(.top, 6)
            LazyVGrid(columns: columns, spacing: 2) {
                // Blank cells before the 1st, then the month's days, in one list so each has its own identity.
                ForEach(0..<(lead + count), id: \.self) { i in
                    if i < lead {
                        Color.clear.frame(height: 44)
                    } else {
                        cell(String(format: "\(month)-%02d", i - lead + 1), number: i - lead + 1)
                    }
                }
            }
            HStack(spacing: 14) {
                legend("event", "Events")
                legend("booking", "Bookings")
                legend("stop", "Plans")
                legend("trip", "Trips")
            }
            .padding(.top, 10)
        }
    }

    private func cell(_ iso: String, number: Int) -> some View {
        let items = (days[iso] ?? []).filter { $0.kind != "trip" }
        let kinds = Array(NSOrderedSet(array: items.map(\.kind)).array as? [String] ?? []).prefix(3)
        let inTrip = tripDays[iso] != nil
        let isSelected = iso == selected
        return Button { selected = isSelected ? nil : iso } label: {
            VStack(spacing: 3) {
                Text("\(number)")
                    .font(.subheadline.weight(iso == today ? .bold : .regular))
                    .foregroundStyle(isSelected ? Theme.accentInk : (iso < today ? Theme.tertiary : Theme.label))
                    .frame(width: 32, height: 32)
                    .background(isSelected ? Theme.accent : Color.clear, in: Circle())
                    .overlay(Circle().strokeBorder(iso == today && !isSelected ? Theme.gold : Color.clear, lineWidth: 1.5))
                HStack(spacing: 2) {
                    ForEach(Array(kinds), id: \.self) { k in Circle().fill(CalendarView.color(k)).frame(width: 5, height: 5) }
                }
                .frame(height: 5)
            }
            .frame(maxWidth: .infinity, minHeight: 44)
            .background(inTrip ? CalendarView.color("trip").opacity(0.14) : Color.clear)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Fmt.shortDay(iso) + (items.isEmpty ? "" : ", \(Fmt.plural(items.count, "item"))") + (inTrip ? ", trip day" : ""))
    }

    private func legend(_ kind: String, _ label: String) -> some View {
        HStack(spacing: 4) {
            Circle().fill(CalendarView.color(kind)).frame(width: 7, height: 7)
            Text(label).font(.caption2).foregroundStyle(Theme.secondary)
        }
    }

    private func step(_ n: Int) {
        if let next = calendar.date(byAdding: .month, value: n, to: firstOfMonth) {
            month = String(Fmt.iso(next).prefix(7))
            selected = nil
        }
    }
}

/// Calendar sync: a private link Apple or Google Calendar subscribes to, so events, bookings and plans keep
/// flowing in.
private struct CalendarSyncSheet: View {
    @State var feed: CalendarFeed?
    let onChange: (CalendarFeed?) -> Void
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var working = false

    var body: some View {
        NavigationStack {
            Form {
                if let feed {
                    Section {
                        Button { if let url = URL(string: feed.webcalUrl) { UIApplication.shared.open(url) } } label: {
                            Label("Apple Calendar: subscribe on this iPhone", systemImage: "calendar")
                        }
                        Button { Links.open(URL(string: feed.googleUrl)) } label: { Label("Google Calendar", systemImage: "globe") }
                        Button {
                            UIPasteboard.general.string = feed.url
                            store.show("Link copied")
                        } label: { Label("Copy link for Outlook or another app", systemImage: "link") }
                    } footer: {
                        Text("New events, bookings and plans keep flowing in. Apple Calendar refreshes on its own schedule; Google can take a few hours. This link is private: anyone who has it can see your calendar.")
                    }
                    Section {
                        Button("Turn off this link", role: .destructive) { Task { await turnOff() } }
                    }
                } else {
                    Section {
                        Text("Events, bookings and planned days show up in Google or Apple Calendar and stay up to date.")
                        Button { Task { await turnOn() } } label: {
                            if working { ProgressView() } else { Text("Turn on calendar sync") }
                        }
                        .disabled(working)
                    } footer: {
                        Text("To add just one event, tap the calendar button next to it instead.")
                    }
                }
            }
            .tripBackground()
            .navigationTitle("Sync your calendar")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }

    private func turnOn() async {
        working = true
        defer { working = false }
        do {
            let fresh: CalendarFeed = try await API.shared.post("/v1/calendar/feed")
            feed = fresh
            onChange(fresh)
        } catch { store.fail(error) }
    }

    private func turnOff() async {
        do {
            try await API.shared.call("DELETE", "/v1/calendar/feed")
            feed = nil
            onChange(nil)
            store.show("Calendar link turned off")
        } catch { store.fail(error) }
    }
}

/// When a saved event happens: its date, an optional start time, and an end date for something that runs a few days.
private struct EventDateSheet: View {
    let item: CalendarItem
    let onSaved: () -> Void
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var date = Date()
    @State private var hasTime = false
    @State private var time = Calendar.current.date(from: DateComponents(hour: 19)) ?? Date()
    @State private var hasEnd = false
    @State private var end = Date()

    var body: some View {
        NavigationStack {
            Form {
                DatePicker("Date", selection: $date, displayedComponents: .date)
                Toggle("Starts at a set time", isOn: $hasTime.animation())
                if hasTime { DatePicker("Starts at", selection: $time, displayedComponents: .hourAndMinute) }
                Toggle("Runs several days", isOn: $hasEnd.animation())
                if hasEnd { DatePicker("Ends on", selection: $end, in: date..., displayedComponents: .date) }
            }
            .tripBackground()
            .navigationTitle("When is it?")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { Task { await save() } } }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func save() async {
        guard let placeId = item.placeId else { return }
        var body: [String: Any?] = ["event_date": Fmt.iso(date), "event_end_date": hasEnd && end > date ? Fmt.iso(end) : nil]
        if hasTime { body["start_time"] = BookingTime.string(time, time: true).suffix(5).description } else { body["clear_start_time"] = true }
        do {
            let _: Place = try await API.shared.patch("/v1/places/\(placeId)", body)
            store.show("On your calendar for \(Fmt.shortDay(Fmt.iso(date)))")
            onSaved()
            dismiss()
        } catch { store.fail(error) }
    }
}
