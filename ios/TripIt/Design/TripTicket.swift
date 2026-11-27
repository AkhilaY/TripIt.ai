import SwiftUI

/// Flights joined into journeys: legs that leave within 24 hours of the last one landing (or taking off) are one
/// journey, so a layover isn't mistaken for where you're going.
enum Journeys {
    static func all(_ bookings: [Booking]) -> [[Booking]] {
        let flights = bookings.filter { $0.kind == "flight" && $0.startAt != nil }.sorted { ($0.startAt ?? "") < ($1.startAt ?? "") }
        var out: [[Booking]] = []
        for leg in flights {
            if let last = out.last?.last, let gap = hours(from: last.endAt ?? last.startAt, to: leg.startAt), gap >= 0, gap <= 24,
               connects(last, leg) {
                out[out.count - 1].append(leg)
            } else {
                out.append([leg])
            }
        }
        return out
    }

    /// The first journey: how you get there.
    static func outbound(_ bookings: [Booking]) -> [Booking] { all(bookings).first ?? [] }

    /// The cities a flight booking lands in, for suggesting them as trip stops (layovers left out).
    static func destinations(_ bookings: [Booking]) -> [String] {
        all(bookings).compactMap { $0.last?.destination }.map(cityName)
    }

    private static func connects(_ a: Booking, _ b: Booking) -> Bool {
        guard let to = code(a.destination), let from = code(b.origin) else { return true }  // unknown airports: trust the times
        return to == from
    }

    private static func hours(from a: String?, to b: String?) -> Double? {
        guard let a, let b, let x = stamp(a), let y = stamp(b) else { return nil }
        return y.timeIntervalSince(x) / 3600
    }

    private static let full: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm"
        return f
    }()

    private static func stamp(_ s: String) -> Date? { s.count > 10 ? full.date(from: String(s.prefix(16))) : Fmt.day(s) }

    /// "Atlanta (ATL)" → "ATL"; a plain three-letter code stays as it is.
    static func code(_ place: String?) -> String? {
        guard let place, !place.isEmpty else { return nil }
        if let match = place.firstMatch(of: #/\(([A-Z]{3})\)/#) { return String(match.1) }
        let t = place.trimmingCharacters(in: .whitespaces)
        return t.count <= 4 ? t.uppercased() : nil
    }

    /// "Zurich (ZRH)" → "Zurich".
    static func cityName(_ place: String) -> String {
        place.replacing(#/\s*\([A-Z]{3}\)/#, with: "").trimmingCharacters(in: .whitespaces)
    }

    /// The short form shown on a ticket: the airport code, else the place's name.
    static func short(_ place: String?) -> String {
        code(place) ?? place.map(cityName) ?? "—"
    }
}

/// One flight leg on a ticket: from, the flight and time, to.
struct LegRow: View {
    let leg: Booking
    var size: CGFloat = 22
    var ink: Color = Theme.label

    var body: some View {
        HStack(alignment: .lastTextBaseline, spacing: 8) {
            Text(Journeys.short(leg.origin)).font(Theme.serif(size)).lineLimit(1).minimumScaleFactor(0.6)
            VStack(spacing: 3) {
                Text([leg.title, leg.startTime.map(Fmt.clock)].compactMap { $0 }.joined(separator: " · "))
                    .font(Theme.text(.caption2)).foregroundStyle(ink.opacity(0.65)).lineLimit(1)
                Rectangle().fill(ink.opacity(0.2)).frame(height: 1)
            }
            .frame(maxWidth: .infinity)
            Text(Journeys.short(leg.destination)).font(Theme.serif(size)).lineLimit(1).minimumScaleFactor(0.6)
        }
        .foregroundStyle(ink)
    }
}

/// What a trip's ticket says, worked out once for the pass and the trip header.
struct TicketInfo {
    let name: String
    let legs: [Booking]
    let dates: String?
    let cities: String?  // "Zurich 2 · Munich 3 nights"
    let daysToGo: Int?

    init(name: String, city: String, startDate: String?, dayCount: Int, stops: [TripStop]?, bookings: [Booking]) {
        self.name = name
        legs = Journeys.outbound(bookings)
        if let s = startDate.flatMap(Fmt.day) {
            let e = Calendar.current.date(byAdding: .day, value: max(0, dayCount - 1), to: s) ?? s
            dates = Fmt.range(s, e)
            daysToGo = BookingTime.days(from: Fmt.iso(Date()), to: Fmt.iso(s))
        } else {
            dates = nil
            daysToGo = nil
        }
        let real = (stops ?? []).filter { !$0.city.isEmpty }
        if real.count > 1 {
            cities = real.map { "\($0.city) \(max(1, $0.days - 1))" }.joined(separator: " · ") + " nights"
        } else if !city.isEmpty {
            cities = city + (dayCount > 1 ? " · " + Fmt.plural(dayCount - 1, "night") : "")
        } else {
            cities = dayCount > 1 ? Fmt.plural(dayCount - 1, "night") : nil
        }
    }

    var stub: String { [dates, cities].compactMap { $0 }.joined(separator: " · ") }
}

/// A trip as a ticket on Home: its name and dates, then each flight leg of the way there, then the cities.
struct BoardingPass: View {
    let info: TicketInfo
    let onOpen: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(info.name).font(Theme.serif(24)).foregroundStyle(Theme.label).lineLimit(2).minimumScaleFactor(0.7)
                    Text(info.dates ?? "No dates yet").font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                }
                Spacer(minLength: 8)
                if let days = info.daysToGo, days > 0 {
                    VStack(alignment: .trailing, spacing: 3) {
                        Text("IN").font(Theme.text(.caption2, weight: .medium)).kerning(1.6).foregroundStyle(Theme.secondary)
                        CountdownBoard(days: days)
                    }
                } else if info.daysToGo != nil {
                    Text("ON NOW").font(Theme.text(.caption2, weight: .medium)).kerning(1.6).foregroundStyle(Theme.background)
                        .padding(.horizontal, 10).padding(.vertical, 6).background(Theme.label, in: Capsule())
                }
            }
            .padding(.horizontal, 18).padding(.top, 16).padding(.bottom, 12)
            VStack(spacing: 10) {
                if info.legs.isEmpty {
                    HStack(spacing: 8) {
                        Image(systemName: "airplane").font(.system(size: 13, weight: .light))
                        Text("No flight added yet").font(Theme.text(.footnote))
                        Spacer()
                    }
                    .foregroundStyle(Theme.tertiary)
                } else {
                    ForEach(info.legs) { LegRow(leg: $0) }
                }
            }
            .padding(.horizontal, 18).padding(.bottom, 12)
            Line().stroke(Theme.border, style: StrokeStyle(lineWidth: 1.5, dash: [5, 4])).frame(height: 1).padding(.horizontal, 14)
            HStack {
                Text(info.cities ?? "Add the cities you're going to").font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).lineLimit(1)
                Spacer(minLength: 8)
                Image(systemName: "chevron.right").font(Theme.text(.caption, weight: .medium)).foregroundStyle(Theme.tertiary)
            }
            .padding(.horizontal, 18).padding(.vertical, 12)
        }
        .background(Theme.background)
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .shadow(color: .black.opacity(0.08), radius: 16, y: 8)
        .contentShape(Rectangle())
        .onTapGesture { Haptics.tap(); onOpen() }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }

    struct Line: Shape {
        func path(in rect: CGRect) -> Path {
            var p = Path()
            p.move(to: CGPoint(x: 0, y: rect.midY))
            p.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
            return p
        }
    }
}

/// The top of a trip's page: the city's photo when it has a city, over a dark ticket band with the name, the way
/// there and the dates. It sits in the list, so it scrolls away with it.
struct TripHeaderCard: View {
    let trip: TripDetail

    var body: some View {
        let info = TicketInfo(name: trip.name, city: trip.city, startDate: trip.startDate, dayCount: trip.dayCount,
                              stops: trip.stops, bookings: trip.bookings)
        let ink = Theme.background
        VStack(alignment: .leading, spacing: 0) {
            if !trip.city.isEmpty {
                Color.clear.frame(height: 120)
                    .overlay { CityCover(city: trip.city, country: trip.country) }
                    .clipped()
            }
            VStack(alignment: .leading, spacing: 10) {
                Text(info.name).font(Theme.serif(30)).foregroundStyle(ink).lineLimit(2).minimumScaleFactor(0.7)
                ForEach(info.legs) { LegRow(leg: $0, size: 20, ink: ink) }
                Text([info.stub.isEmpty ? nil : info.stub, Fmt.plural(trip.places.count, "place"),
                      info.daysToGo.flatMap { $0 > 0 ? "in " + Fmt.plural($0, "day") : nil }].compactMap { $0 }.joined(separator: " · "))
                    .font(Theme.text(.footnote)).foregroundStyle(ink.opacity(0.7))
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.label)
        }
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
    }
}
