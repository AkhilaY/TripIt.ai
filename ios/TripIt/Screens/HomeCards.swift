import SwiftUI

/// An import in progress: the post, and three steps filling in as it's read.
struct ImportProgressCard: View {
    let job: Job

    private static let steps = ["Opening the post", "Listening", "Finding places"]

    private var step: Int {
        switch job.status {
        case "transcribing": 1
        case "analyzing": 2
        default: 0
        }
    }

    var body: some View {
        Card(padding: 14) {
            HStack(spacing: 12) {
                SymbolTile(symbol: JobRow.symbol(for: job.url), color: Theme.indigo)
                VStack(alignment: .leading, spacing: 2) {
                    Text(job.reel?.title ?? (job.url.hasPrefix("upload:") ? "Your screenshots" : "A saved post"))
                        .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label).lineLimit(1)
                    Text(Self.steps[step] + "…").font(.footnote).foregroundStyle(Theme.secondary)
                        .contentTransition(.opacity)
                }
                Spacer(minLength: 0)
            }
            HStack(spacing: 6) {
                ForEach(Self.steps.indices, id: \.self) { i in
                    Capsule()
                        .fill(i <= step ? Theme.gold : Theme.fill)
                        .frame(height: 4)
                        .overlay {
                            if i == step { Capsule().fill(Theme.gold.opacity(0.5)).phaseAnimator([0.3, 1]) { v, p in v.opacity(p) } }
                        }
                }
            }
            .padding(.top, 12)
            .animation(.spring(duration: 0.5), value: step)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Importing: \(Self.steps[step])")
    }
}

/// What's next: the soonest saved event, booking or trip in the coming month.
struct NextUpCard: View {
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router

    private struct Item {
        let key: String  // "yyyy-MM-dd" or "yyyy-MM-ddTHH:mm", to sort
        let symbol: String
        let color: Color
        let title: String
        let subtitle: String
        let route: Route
    }

    private var next: Item? {
        let today = Fmt.iso(Date())
        let horizon = BookingTime.addDays(today, 30)
        var items: [Item] = []
        for p in store.saved where Category(p.category) == .event {
            guard let date = p.eventDate, date >= today, date <= horizon else { continue }
            items.append(Item(key: date + (p.startTime.map { "T" + $0 } ?? ""), symbol: Category.event.symbol, color: Category.event.color,
                              title: p.name, subtitle: [p.startTime.map(Fmt.clock), p.venue].compactMap { $0 }.joined(separator: " · "),
                              route: .place(id: p.id, tripId: nil)))
        }
        for b in store.bookings {
            guard let start = b.startAt, let day = b.startDay, day >= today, day <= horizon else { continue }
            items.append(Item(key: start, symbol: b.bookingKind.symbol, color: b.bookingKind.color, title: b.title,
                              subtitle: [b.bookingKind.label, b.startTime.map(Fmt.clock)].compactMap { $0 }.joined(separator: " · "),
                              route: .bookings(tripId: b.tripId)))
        }
        for t in store.upcomingTrips {
            guard let start = t.startDate, start > today, start <= horizon else { continue }
            items.append(Item(key: start, symbol: "airplane", color: Theme.gold, title: t.name,
                              subtitle: "Trip · \(t.dateRange ?? "")", route: .trip(id: t.id)))
        }
        return items.min { $0.key < $1.key }
    }

    var body: some View {
        if let item = next {
            Button { router.push(item.route) } label: {
                Card(radius: 18, padding: 16) {
                    Eyebrow(text: "Next up · \(Self.when(item.key))")
                    HStack(spacing: 12) {
                        SymbolTile(symbol: item.symbol, color: item.color, size: 40)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.title).font(Theme.serif(20)).foregroundStyle(Theme.label).lineLimit(2)
                            if !item.subtitle.isEmpty { Text(item.subtitle).font(.footnote).foregroundStyle(Theme.secondary) }
                        }
                        Spacer(minLength: 0)
                        Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.quiet)
                    }
                    .padding(.top, 8)
                }
            }
            .buttonStyle(.plain)
        }
    }

    static func when(_ key: String) -> String {
        let day = String(key.prefix(10))
        let days = BookingTime.days(from: Fmt.iso(Date()), to: day)
        if days == 0 { return "Today" }
        if days == 1 { return "Tomorrow" }
        if days < 7, let date = Fmt.day(day) { return date.formatted(.dateTime.weekday(.wide)) }
        return Fmt.shortDay(day)
    }
}

/// For a new account: the one thing to do first.
struct GetStartedCard: View {
    @Environment(Router.self) private var router

    var body: some View {
        Card(radius: 18, padding: 18) {
            Eyebrow(text: "Get started")
            Text("Save your first place").font(Theme.serif(24)).foregroundStyle(Theme.label).padding(.top, 6)
            VStack(alignment: .leading, spacing: 12) {
                step("1", "Find a post you love on TikTok or Instagram")
                step("2", "Tap Share, then Travel Edit (it may be under More)")
                step("3", "Every place in it is saved and filed by city")
            }
            .padding(.top, 12)
            HStack(spacing: 8) {
                Button { router.addRequest = Router.AddRequest() } label: { Label("Paste a link", systemImage: "link") }
                    .buttonStyle(PrimaryButtonStyle(compact: true))
                Button { router.addRequest = Router.AddRequest() } label: { Label("Search", systemImage: "magnifyingglass") }
                    .buttonStyle(PrimaryButtonStyle(tinted: true, compact: true))
            }
            .padding(.top, 16)
        }
    }

    private func step(_ n: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(n).font(.caption.weight(.bold)).foregroundStyle(Theme.accentInk)
                .frame(width: 22, height: 22).background(Theme.accent, in: Circle())
            Text(text).font(.subheadline).foregroundStyle(Theme.label).fixedSize(horizontal: false, vertical: true)
        }
    }
}
