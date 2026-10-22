import SwiftUI

/// Library → Trips: plan a new trip, today's trip, and a card for each trip.
struct TripsSection: View {
    @Binding var sheet: LibrarySheet?
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @State private var deleting: Trip?

    var body: some View {
        if let active = activeTrip {
            let trip = active.trip, day = active.day
            Section {
                Button { router.push(.web(hash: "#/today/\(trip.id)")) } label: {
                    HStack(spacing: 12) {
                        SymbolTile(symbol: "sun.max.fill", color: Theme.orange, size: 40)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Today in \(trip.city)").font(Theme.serif(20))
                            Text("Day \(day) of \(trip.name). Open the day view").font(.subheadline).foregroundStyle(Theme.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.tertiary)
                    }
                }
                .buttonStyle(.plain)
            }
        }
        Section {
            Button { sheet = .newTrip([], nil) } label: {
                HStack(spacing: 12) {
                    SymbolTile(symbol: "airplane", color: Theme.gold, size: 40)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Plan a new trip").font(.body.weight(.semibold))
                        Text("Pick a city and your saved places. AI can plan it, or build it yourself.")
                            .font(.subheadline).foregroundStyle(Theme.secondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.tertiary)
                }
            }
            .buttonStyle(.plain)
        }
        Section {
            if store.trips.isEmpty {
                Text("Your trips appear here.").foregroundStyle(Theme.secondary).frame(maxWidth: .infinity)
                    .listRowBackground(Color.clear)
            }
            ForEach(store.trips) { trip in
                ZStack {
                    NavigationLink(value: Route.trip(id: trip.id)) { EmptyView() }.opacity(0)
                    TripCard(trip: trip)
                }
                .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 6, trailing: 16))
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
                .swipeActions {
                    Button(role: .destructive) { deleting = trip } label: { Label("Delete", systemImage: "trash") }
                }
            }
        }
        .confirmationDialog("Delete this trip? Its places stay in your saved places.",
                            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button("Delete trip", role: .destructive) {
                if let trip = deleting { Task { await store.deleteTrip(trip.id) } }
            }
        }
    }

    /// The trip happening today (by this phone's date), and which day of it.
    private var activeTrip: (trip: Trip, day: Int)? {
        let today = Calendar.current.startOfDay(for: Date())
        for trip in store.trips {
            guard let startText = trip.startDate, let start = Fmt.day(startText), trip.dayCount > 0 else { continue }
            let day = (Calendar.current.dateComponents([.day], from: Calendar.current.startOfDay(for: start), to: today).day ?? -1) + 1
            if day >= 1 && day <= trip.dayCount { return (trip: trip, day: day) }
        }
        return nil
    }
}

struct TripCard: View {
    let trip: Trip

    var body: some View {
        let categories = trip.categories.map(Category.init)
        let main = categories.first ?? .other
        ZStack(alignment: .bottomLeading) {
            LinearGradient(colors: [main.color, (categories.dropFirst().first ?? .stay).color],
                           startPoint: .topLeading, endPoint: .bottomTrailing)
            Image(systemName: main.symbol)
                .font(.system(size: 90, weight: .semibold))
                .foregroundStyle(.white.opacity(0.14))
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                .padding(18)
            if let cover = trip.coverPhoto {
                RemoteImage(url: cover.url(width: 900)) { Color.clear }
            }
            LinearGradient(colors: [.clear, .black.opacity(0.62)], startPoint: .center, endPoint: .bottom)
            VStack(alignment: .leading, spacing: 4) {
                Spacer()
                Text(trip.name).font(Theme.serif(28)).foregroundStyle(.white).lineLimit(2)
                Text(meta).font(.subheadline.weight(.medium)).foregroundStyle(.white.opacity(0.85))
            }
            .padding(18)
            VStack {
                HStack {
                    if trip.dayCount > 0 {
                        Label(Fmt.plural(trip.dayCount, "day"), systemImage: "calendar")
                            .font(.caption.weight(.semibold)).foregroundStyle(.white)
                            .padding(.horizontal, 10).padding(.vertical, 5)
                            .background(.ultraThinMaterial.opacity(0.9), in: Capsule())
                            .environment(\.colorScheme, .dark)
                    }
                    Spacer()
                }
                Spacer()
            }
            .padding(14)
        }
        .frame(height: 200)
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .shadow(color: .black.opacity(0.12), radius: 16, y: 10)
    }

    private var meta: String {
        [trip.isLocal ? "Near home" : trip.country, Fmt.plural(trip.placeCount, "place")]
            .filter { !$0.isEmpty }.joined(separator: " · ")
    }
}
