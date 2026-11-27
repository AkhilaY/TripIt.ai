import SwiftUI

/// Days to go, in split-flap tiles like a departure board. The digits roll into place when Home opens, with a tick.
struct CountdownBoard: View {
    let days: Int
    @State private var shown = 0

    var body: some View {
        HStack(spacing: 4) {
            ForEach(Array(String(shown).enumerated()), id: \.offset) { _, digit in
                Text(String(digit))
                    .font(Theme.serif(30))
                    .contentTransition(.numericText(value: Double(shown)))
                    .foregroundStyle(Color(hex: 0xF4EDE2))
                    .frame(width: 30, height: 42)
                    .background(Color(hex: 0x1E1A17), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                    .overlay { Rectangle().fill(.black).frame(height: 1) }  // the flap's hinge
            }
        }
        .sensoryFeedback(.impact(flexibility: .rigid, intensity: 0.6), trigger: shown)
        .task(id: days) {
            try? await Task.sleep(for: .milliseconds(250))
            withAnimation(.spring(duration: 0.7)) { shown = days }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Fmt.plural(days, "day") + " to go")
    }
}

/// A trip as a boarding pass: the city's photo with the days to go, from and to, then a stub with the date and flight.
struct BoardingPass: View {
    let trip: Trip
    let flight: Booking?
    let from: String
    let onOpen: () -> Void

    /// Days until it starts; 0 or less while it's on; nil without dates.
    private var daysToGo: Int? {
        trip.startDate.map { BookingTime.days(from: Fmt.iso(Date()), to: $0) }
    }

    var body: some View {
        VStack(spacing: 0) {
            Color.clear.frame(height: 118)
                .overlay { CityCover(city: trip.city, country: trip.country) }
                .overlay(alignment: .topTrailing) {
                    if let days = daysToGo, days > 0 {
                        VStack(alignment: .trailing, spacing: 4) {
                            Text("IN").font(Theme.text(.caption2, weight: .medium)).kerning(1.6).foregroundStyle(.white)
                                .shadow(color: .black.opacity(0.4), radius: 3)
                            CountdownBoard(days: days)
                        }
                        .padding(12)
                    } else if daysToGo != nil {
                        Text("ON NOW").font(Theme.text(.caption2, weight: .medium)).kerning(1.6).foregroundStyle(.white)
                            .padding(.horizontal, 10).padding(.vertical, 6).background(.black.opacity(0.45), in: Capsule()).padding(12)
                    }
                }
                .clipped()
            HStack(alignment: .bottom) {
                end("From", code(flight?.origin) ?? from)
                Spacer()
                Image(systemName: "airplane").font(.system(size: 15, weight: .light)).foregroundStyle(Theme.tertiary).padding(.bottom, 10)
                Spacer()
                end("To", code(flight?.destination) ?? trip.city, trailing: true)
            }
            .padding(.horizontal, 18).padding(.top, 12).padding(.bottom, 10)
            Line().stroke(Theme.border, style: StrokeStyle(lineWidth: 1.5, dash: [5, 4])).frame(height: 1).padding(.horizontal, 14)
            HStack {
                Text(stub).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).lineLimit(1)
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

    private func end(_ label: String, _ value: String, trailing: Bool = false) -> some View {
        VStack(alignment: trailing ? .trailing : .leading, spacing: 0) {
            Text(label.uppercased()).font(Theme.text(.caption2, weight: .medium)).kerning(1.6).foregroundStyle(Theme.secondary)
            Text(value).font(Theme.serif(30)).foregroundStyle(Theme.label).lineLimit(1).minimumScaleFactor(0.5)
        }
    }

    /// "Atlanta (ATL)" → "ATL"; a plain three-letter code stays as it is.
    private func code(_ place: String?) -> String? {
        guard let place, !place.isEmpty else { return nil }
        if let match = place.firstMatch(of: #/\(([A-Z]{3})\)/#) { return String(match.1) }
        return place.count <= 4 ? place.uppercased() : place
    }

    private var stub: String {
        var parts: [String] = []
        if let start = trip.startDate.flatMap(Fmt.day) { parts.append(start.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))) }
        if let flight { parts.append(flight.title + (flight.startTime.map { " · \(Fmt.clock($0))" } ?? "")) }
        if trip.dayCount > 1 { parts.append(Fmt.plural(trip.dayCount - 1, "night")) }
        return parts.joined(separator: " · ")
    }

    private struct Line: Shape {
        func path(in rect: CGRect) -> Path {
            var p = Path()
            p.move(to: CGPoint(x: 0, y: rect.midY))
            p.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
            return p
        }
    }
}

/// Cities as a stack of cards, like a wallet. Fan them out to see each; tap one to open it; press and hold for more.
struct CityWallet: View {
    let groups: [Store.CityGroup]
    let tripLine: (Store.CityGroup) -> String
    let onOpen: (Store.CityGroup) -> Void
    @State private var fanned = false

    var body: some View {
        let gap: CGFloat = fanned ? 232 : 56
        let height: CGFloat = 220 + gap * CGFloat(max(0, groups.count - 1))
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Your cities").font(Theme.serif(25)).foregroundStyle(Theme.label)
                Spacer()
                Button { withAnimation(.spring(duration: 0.5, bounce: 0.2)) { fanned.toggle() } } label: {
                    Image(systemName: "chevron.down").font(.system(size: 15, weight: .medium)).foregroundStyle(Theme.label)
                        .rotationEffect(.degrees(fanned ? 180 : 0))
                        .frame(width: 40, height: 40).background(Theme.fill, in: Circle())
                }
                .accessibilityLabel(fanned ? "Stack the cities" : "Spread out the cities")
            }
            ZStack(alignment: .top) {
                ForEach(Array(groups.enumerated()), id: \.element.id) { i, city in
                    Button { onOpen(city) } label: { card(city) }
                        .buttonStyle(PressStyle())
                        .offset(y: gap * CGFloat(i))
                        .contextMenu {
                            Button { onOpen(city) } label: { Label("Open \(city.name)", systemImage: "arrow.up.right") }
                        }
                }
            }
            .frame(height: height, alignment: .top)
        }
        .sensoryFeedback(.impact(weight: .light), trigger: fanned)
    }

    private func card(_ city: Store.CityGroup) -> some View {
        Color.clear.frame(height: 220)
            .overlay { CityCover(city: city.name, country: city.country, fallback: city.coverURLs(width: 600)) }
            .overlay(alignment: .topLeading) {
                ZStack(alignment: .topLeading) {
                    LinearGradient(colors: [.black.opacity(0.55), .clear], startPoint: .top, endPoint: .center)
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text(city.name).font(Theme.serif(22)).foregroundStyle(.white)
                        Text(tripLine(city)).font(Theme.text(.caption)).foregroundStyle(.white.opacity(0.85))
                    }
                    .padding(16)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .shadow(color: .black.opacity(0.18), radius: 10, y: -4)
    }
}
