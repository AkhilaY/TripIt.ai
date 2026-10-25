import Foundation

// Mirrors the server's JSON (backend/app/models.py). Keys arrive in snake_case and are converted by the decoder.
// Dates and times stay as the server's strings ("2026-10-22", "19:30") and are formatted where shown.

struct PlacePhoto: Codable, Hashable {
    var source: String
    var url: String
    var attribution: String?
}

struct TimeRange: Codable, Hashable {
    var open: String
    var close: String
}

struct OpeningHours: Codable, Hashable {
    var weekly: [[TimeRange]]?
    var text: [String]
    var source: String
}

struct Place: Codable, Identifiable, Hashable {
    var id: String
    var tripId: String?
    var reelId: String?
    var name: String
    var category: String
    var summary: String
    var recommendedItems: [String]
    var priceHint: String?
    var tips: String?
    var userNotes: String
    var confidence: String
    var visited: Bool
    var neighborhood: String?
    var address: String?
    var city: String
    var country: String
    var latitude: Double?
    var longitude: Double?
    var mapsUrl: String?
    var resolvedName: String?
    var dayNumber: Int?
    var dayOrder: Int
    var timeOfDay: String?
    var dayNote: String?
    var openingHours: OpeningHours?
    var photos: [PlacePhoto]
    var tripIds: [String]
    var folderIds: [String]
    var saved: Bool
    var suggested: Bool
    var suggestionNote: String?
    var mustDo: Bool
    var startTime: String?
    var eventDate: String?
    var eventEndDate: String?
    var venue: String?
    var rating: Double?
    var ratingCount: Int?
    var bookingKind: String?
    var bookingNeed: String?
    var bookingNote: String?
    var reserveUrl: String?
    var reserveProvider: String?
    var reserveCheckedAt: String?
    var website: String?
    var phone: String?
    var reelIds: [String]
    var mentionCount: Int
    var createdAt: String

    var isLocated: Bool { latitude != nil && longitude != nil }
}

struct Reel: Codable, Identifiable, Hashable {
    var id: String
    var url: String
    var platform: String
    var title: String
    var creator: String?
    var thumbnailUrl: String?
    var placeCount: Int
}

struct Booking: Codable, Identifiable, Hashable {
    var id: String
    var tripId: String
    var kind: String
    var title: String
    var startAt: String?
    var endAt: String?
    var origin: String?
    var destination: String?
    var address: String?
    var confirmation: String?
    var partySize: Int?
    var notes: String?
    var placeId: String?
}

/// One city on a trip's route; stops cover the trip's days back to back.
struct TripStop: Codable, Hashable {
    var city: String
    var country: String
    var days: Int
    var startDay: Int
    var endDay: Int
    var travelMode: String?
    var travelMinutes: Int?
    var travelNote: String?

    /// How you get here, for the route strip and travel days.
    var travelSymbol: String {
        ["train": "tram.fill", "flight": "airplane", "drive": "car.fill", "bus": "bus.fill", "ferry": "ferry.fill", "walk": "figure.walk"][travelMode ?? ""] ?? "arrow.right"
    }

    var travelLabel: String {
        ["train": "Train", "flight": "Flight", "drive": "Drive", "bus": "Bus", "ferry": "Ferry", "walk": "Walk"][travelMode ?? ""] ?? "Travel"
    }
}

/// When a stop happens on its day (exact, or estimated from the stops before it).
struct ScheduledStop: Codable, Hashable {
    var placeId: String
    var day: Int
    var time: String
    var estimated: Bool
}

/// A place planned on a day it's closed, with the nearest day in the same city it's open.
struct TripClosure: Codable, Hashable {
    var placeId: String
    var day: Int
    var message: String
    var moveToDay: Int?
    var moveToLabel: String?
}

struct Trip: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var city: String
    var country: String
    var kind: String
    var createdAt: String
    var startDate: String?
    var dayCount: Int
    var dayTitles: [String]
    var planNotes: String?
    var plannedBy: String?
    var placeCount: Int
    var mappedCount: Int
    var categories: [String]
    var coverPhoto: PlacePhoto?
    var shareToken: String?
    var stops: [TripStop]?
    var role: String?
    var memberCount: Int?

    var isLocal: Bool { kind == "local" }
    /// Someone else's trip you were invited to plan, or yours with people on it.
    var isShared: Bool { role == "editor" || (memberCount ?? 0) > 0 }
}

/// Someone planning a trip: its owner, or a person they invited.
struct TripMember: Codable, Hashable, Identifiable {
    var userId: String
    var name: String
    var role: String
    var you: Bool
    var id: String { userId }

    var initials: String { name.split(separator: " ").compactMap(\.first).prefix(2).map(String.init).joined().uppercased() }
}

struct InviteLink: Codable {
    var token: String
    var path: String
}

struct TripDetail: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var city: String
    var country: String
    var kind: String
    var startDate: String?
    var dayCount: Int
    var dayTitles: [String]
    var planNotes: String?
    var plannedBy: String?
    var coverPhoto: PlacePhoto?
    var shareToken: String?
    var places: [Place]
    var reels: [Reel]
    var bookings: [Booking]
    var stops: [TripStop]?
    var closures: [TripClosure]?
    var schedule: [ScheduledStop]?
    var role: String?
    var members: [TripMember]?

    var isOwner: Bool { role != "editor" }

    var isLocal: Bool { kind == "local" }

    /// When a planned stop happens, in minutes after midnight: its exact time, or the server's estimate.
    func minute(of placeId: String) -> Int? {
        guard let time = schedule?.first(where: { $0.placeId == placeId })?.time else { return nil }
        let parts = time.split(separator: ":").compactMap { Int($0) }
        return parts.count == 2 ? parts[0] * 60 + parts[1] : nil
    }

    /// The route's cities when there's more than one.
    var route: [TripStop] { (stops ?? []).count > 1 ? stops ?? [] : [] }

    func stop(on day: Int) -> TripStop? { route.first { day >= $0.startDay && day <= $0.endDay } }

    func closure(for placeId: String) -> TripClosure? { closures?.first { $0.placeId == placeId } }

    /// The places planned for a day, in order.
    func dayPlaces(_ day: Int) -> [Place] {
        places.filter { $0.dayNumber == day }.sorted { $0.dayOrder < $1.dayOrder }
    }

    func title(of day: Int) -> String? {
        guard day >= 1, day <= dayTitles.count else { return nil }
        let title = dayTitles[day - 1]
        return title.isEmpty || title == "Day \(day)" ? nil : title
    }
}

struct PlaceDetail: Codable, Hashable {
    var place: Place
    var reels: [Reel]
}

struct Folder: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var placeCount: Int
    var covers: [PlacePhoto]
}

struct ReelMetadata: Codable, Hashable {
    var platform: String
    var url: String
    var title: String?
    var uploader: String?
}

struct Job: Codable, Identifiable, Hashable {
    var id: String
    var url: String
    var status: String
    var message: String?
    var createdAt: String
    var reel: ReelMetadata?
    var warnings: [String]
    var tripId: String?
    var reelId: String?
    var addedPlaces: Int

    var isActive: Bool { ["queued", "downloading", "transcribing", "analyzing"].contains(status) }
}

struct Me: Codable, Hashable {
    var id: String
    var email: String
    var name: String
    var isAdmin: Bool
    var hasImportKey: Bool
    var hasPassword: Bool?  // false for accounts made with Sign in with Apple
}

struct SessionOut: Codable {
    var user: Me
    var token: String
}

struct AuthStatus: Codable {
    var accounts: Bool
}

struct PlaceCandidate: Codable, Identifiable, Hashable {
    var candidateId: String
    var name: String
    var address: String?
    var category: String
    var latitude: Double
    var longitude: Double
    var id: String { candidateId }
}

struct AddPlaceResult: Codable {
    var place: Place
    var created: Bool
}

struct HomeSetting: Codable, Hashable {
    var city: String
    var country: String
    var latitude: Double?
    var longitude: Double?
}

struct TripShareLink: Codable {
    var token: String
    var path: String
}

struct TravelTime: Codable, Hashable {
    var durationS: Int
    var distanceM: Int
    var estimated: Bool
}

struct Leg: Codable, Hashable {
    var fromPlaceId: String?
    var toPlaceId: String
    var times: [String: TravelTime?]
}

struct DayLegs: Codable {
    var day: Int
    var provider: String
    var legs: [Leg]
}

struct EditSource: Codable, Hashable {
    var name: String
    var title: String?
    var url: String?
}

struct EditItem: Codable, Identifiable, Hashable {
    var id: String
    var placeId: String?
    var saved: Bool
    var name: String
    var category: String
    var neighborhood: String?
    var city: String?
    var note: String
    var source: EditSource?
    var photo: PlacePhoto?
    var rating: Double?
    var ratingCount: Int?
    var latitude: Double?
    var longitude: Double?
    var mapsUrl: String?
}

struct TripEdit: Codable, Identifiable, Hashable {
    var id: String
    var title: String
    var dek: String
    var entries: [EditItem]
    var coverPhoto: PlacePhoto?
    var folderId: String?
    var newCount: Int
}

struct MenuItem: Codable, Hashable {
    var name: String
    var description: String?
    var price: String?
    var tags: [String]
}

struct MenuSection: Codable, Hashable {
    var title: String
    var note: String?
    var items: [MenuItem]
}

/// A place's menu: status "unknown" until someone looks, "found" or "none".
struct PlaceMenu: Codable {
    var status: String
    var sections: [MenuSection]
    var notes: String?
    var sourceKind: String?
    var sourceUrl: String?
    var fetchedAt: String?
    var trace: [String]
}

struct TripEdits: Codable {
    var tripId: String
    var edits: [TripEdit]
    var curatedBy: String?
    var stale: Bool
    var refreshing: Bool
}
