import CoreLocation
import Foundation

@MainActor
enum ItineraryPlanner {
    enum Source { case claude, offline }

    /// Plans with Claude on the backend; falls back to a simple on-device plan if the server can't be reached.
    @discardableResult
    static func plan(trip: Trip, days: Int, startDate: Date?, preferences: String) async -> (Source, Error?) {
        let places = trip.allPlaces
        let request = PlanRequestDTO(
            city: trip.city,
            days: days,
            startDate: startDate.map { Self.dateFormatter.string(from: $0) },
            preferences: preferences.isEmpty ? nil : preferences,
            places: places.map {
                PlanPlaceDTO(id: $0.id.uuidString, name: $0.name, category: $0.categoryRaw,
                             latitude: $0.latitude, longitude: $0.longitude,
                             neighborhood: $0.neighborhood, notes: $0.summary)
            }
        )

        do {
            let result = try await APIClient(timeout: 120).planItinerary(request)
            apply(result, to: trip, startDate: startDate)
            return (.claude, nil)
        } catch {
            planOffline(trip: trip, days: days, startDate: startDate)
            return (.offline, error)
        }
    }

    static func apply(_ result: PlanResultDTO, to trip: Trip, startDate: Date?) {
        let byID = Dictionary(uniqueKeysWithValues: trip.allPlaces.map { ($0.id.uuidString, $0) })
        trip.clearItinerary()
        for (index, day) in result.days.enumerated() {
            let dayNumber = index + 1
            for (order, stop) in day.stops.enumerated() {
                guard let place = byID[stop.placeId] else { continue }
                place.dayNumber = dayNumber
                place.dayOrder = order
                place.timeOfDay = TimeOfDay(rawValue: stop.timeOfDay)
                place.dayNote = stop.note
            }
        }
        trip.dayCount = result.days.count
        trip.dayTitles = result.days.map(\.title)
        trip.startDate = startDate
        trip.planNotes = result.notes
    }

    /// Groups nearby places into days with k-means on coordinates, then orders each day by time of day.
    static func planOffline(trip: Trip, days: Int, startDate: Date?) {
        trip.clearItinerary()
        let located = trip.allPlaces.filter { $0.coordinate != nil }
        let unlocated = trip.allPlaces.filter { $0.coordinate == nil }
        let k = max(1, min(days, located.count))

        var groups = kMeans(located, k: k)
        if groups.isEmpty {
            groups = Array(repeating: [], count: max(1, min(days, unlocated.count)))
        }
        // Spread places without coordinates over the lightest days.
        for place in unlocated {
            let index = groups.indices.min { groups[$0].count < groups[$1].count } ?? 0
            groups[index].append(place)
        }

        for (dayIndex, group) in groups.enumerated() {
            let ordered = group.sorted { $0.category.preferredTimeOfDay.sortIndex < $1.category.preferredTimeOfDay.sortIndex }
            for (order, place) in ordered.enumerated() {
                place.dayNumber = dayIndex + 1
                place.dayOrder = order
                place.timeOfDay = place.category.preferredTimeOfDay
            }
        }
        trip.dayCount = groups.count
        trip.dayTitles = groups.map { group in
            let hoods = group.compactMap(\.neighborhood)
            let common = Dictionary(grouping: hoods, by: { $0 }).max { $0.value.count < $1.value.count }?.key
            return common ?? trip.city
        }
        trip.startDate = startDate
    }

    private static func kMeans(_ places: [Place], k: Int) -> [[Place]] {
        guard !places.isEmpty else { return [] }
        let points = places.map { $0.coordinate! }
        // Seed with places spread out along latitude for determinism.
        let sorted = points.indices.sorted { points[$0].latitude < points[$1].latitude }
        var centers = (0..<k).map { points[sorted[$0 * sorted.count / k]] }
        var assignment = [Int](repeating: 0, count: points.count)

        for _ in 0..<15 {
            for (i, p) in points.enumerated() {
                assignment[i] = centers.indices.min { distance(p, centers[$0]) < distance(p, centers[$1]) } ?? 0
            }
            for c in centers.indices {
                let members = points.indices.filter { assignment[$0] == c }.map { points[$0] }
                guard !members.isEmpty else { continue }
                centers[c] = CLLocationCoordinate2D(
                    latitude: members.map(\.latitude).reduce(0, +) / Double(members.count),
                    longitude: members.map(\.longitude).reduce(0, +) / Double(members.count)
                )
            }
        }
        return centers.indices
            .map { c in places.indices.filter { assignment[$0] == c }.map { places[$0] } }
            .filter { !$0.isEmpty }
    }

    private static func distance(_ a: CLLocationCoordinate2D, _ b: CLLocationCoordinate2D) -> Double {
        let dLat = a.latitude - b.latitude
        let dLon = (a.longitude - b.longitude) * cos(a.latitude * .pi / 180)
        return dLat * dLat + dLon * dLon
    }

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()
}
