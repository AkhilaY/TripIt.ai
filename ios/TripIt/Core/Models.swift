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

    var isLocal: Bool { kind == "local" }
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

    var isLocal: Bool { kind == "local" }

    /// The stops on a day, in order.
    func stops(on day: Int) -> [Place] {
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

struct EditItem: Codable, Identifiable, Hashable {
    var id: String
    var placeId: String?
    var saved: Bool
    var name: String
    var category: String
    var photo: PlacePhoto?
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

struct TripEdits: Codable {
    var tripId: String
    var edits: [TripEdit]
    var curatedBy: String?
    var stale: Bool
    var refreshing: Bool
}
