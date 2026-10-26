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
    var startAt: String?  // local wall-clock time as printed: "2026-11-07" or "2026-11-07T19:25"
    var endAt: String?
    var origin: String?
    var destination: String?
    var address: String?
    var confirmation: String?
    var partySize: Int?
    var notes: String?
    var placeId: String?
    var tripName: String?  // only in the list of every booking (GET /v1/bookings)

    var startDay: String? { startAt.map { String($0.prefix(10)) } }
    var startTime: String? { startAt.flatMap { $0.count > 10 ? String($0.suffix(5)) : nil } }
    var endDay: String? { endAt.map { String($0.prefix(10)) } }
    var endTime: String? { endAt.flatMap { $0.count > 10 ? String($0.suffix(5)) : nil } }
    /// The last day it covers (check-out, arrival, drop-off), or its first.
    var lastDay: String? { endDay ?? startDay }
}

/// What Claude read from a confirmation, for the person to check before it's saved.
struct BookingDraft: Codable, Hashable {
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
}

struct Lounge: Codable, Hashable {
    var name: String
    var terminal: String?
    var location: String?
    var access: [String]
    var hours: String?
}

struct LoungeResult: Codable {
    var status: String
    var airport: String?
    var airportName: String?
    var lounges: [Lounge]
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

/// Your plan: Free has a few video saves a month, Plus has no limit.
struct PlanInfo: Codable, Hashable {
    var plan: String
    var videoSavesUsed: Int
    var videoSavesLimit: Int?
    var resetsAt: String

    var isPlus: Bool { plan == "plus" }
    var savesLeft: Int? { videoSavesLimit.map { max(0, $0 - videoSavesUsed) } }
    var resetDay: String {
        guard let date = ISO8601DateFormatter().date(from: resetsAt) else { return "next month" }
        var style = Date.FormatStyle.dateTime.month(.wide).day()
        style.timeZone = .gmt  // the month turns over in UTC
        return date.formatted(style)
    }
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

/// A well-rated place near you or your trip that isn't saved yet (from Google, picked for your taste).
struct DiscoverItem: Codable, Identifiable, Hashable {
    var id: String  // "google:<place id>", the same id the add-a-place search uses
    var name: String
    var kindLabel: String?
    var address: String?
    var latitude: Double?
    var longitude: Double?
    var rating: Double?
    var ratingCount: Int?
    var priceLevel: Int?
    var mapsUrl: String?
    var photo: String?
    var distanceM: Int?
    var award: String?
    var why: String?
    var saved: Bool
}

struct DiscoverArea: Codable, Hashable {
    var name: String
    var latitude: Double
    var longitude: Double
}

struct DiscoverResult: Codable {
    var status: String  // ok, disabled, no_area, error
    var area: DiscoverArea?
    var items: [DiscoverItem]
}

struct PackingItem: Codable, Identifiable, Hashable {
    var id: String
    var text: String
    var group: String
    var reason: String?
    var days: [Int]
    var dayBag: Bool
    var packed: Bool
    var unused: Bool
    var custom: Bool
}

/// A trip day's weather: a forecast, or the same dates last year when it's too far ahead.
struct WeatherDay: Codable, Hashable {
    var day: Int
    var date: String
    var summary: String
    var tempMin: Double
    var tempMax: Double
    var rainChance: Int?
    var source: String
}

struct PackingList: Codable, Hashable {
    var tripId: String
    var items: [PackingItem]
    var weather: [WeatherDay]
    var notes: String?
    var carryOnOnly: Bool
    var generatedBy: String  // claude, offline or manual
}

/// An event near where you'll be during a trip (from Ticketmaster).
struct EventItem: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var url: String
    var image: String?
    var startAt: String  // local "YYYY-MM-DDTHH:MM", or "YYYY-MM-DD" when the time isn't set
    var status: String
    var venue: String?
    var category: String
    var genre: String?
    var priceMin: Double?
    var priceMax: Double?
    var currency: String?
    var day: Int?
    var match: Bool
    var why: String?

    var date: String { String(startAt.prefix(10)) }
    var time: String? { startAt.count > 10 ? String(startAt.suffix(5)) : nil }
}

struct TripEvents: Codable {
    var status: String  // ok, disabled, no_dates, no_location, error
    var events: [EventItem]
}

/// A short note on a trip day: a headline and a few lines on how it goes.
struct DayBriefing: Codable, Hashable {
    var headline: String
    var points: [String]
}

/// One dated thing on the calendar: a saved event, a booking, a planned stop, or a trip's span of days.
struct CalendarItem: Codable, Identifiable, Hashable {
    var id: String
    var kind: String  // event, booking, stop or trip
    var title: String
    var date: String?
    var endDate: String?
    var time: String?
    var endTime: String?
    var partOfDay: String?
    var subtitle: String?
    var category: String?
    var placeId: String?
    var tripId: String?
    var bookingId: String?
    var googleUrl: String?
    var icsUrl: String?
}

/// A private link calendar apps can subscribe to.
struct CalendarFeed: Codable, Hashable {
    var url: String
    var webcalUrl: String
    var googleUrl: String
}

struct CalendarResult: Codable {
    var items: [CalendarItem]
    var undated: [CalendarItem]
    var feed: CalendarFeed?
}

/// A change the concierge proposes; nothing changes until you apply it.
struct ProposedAction: Codable, Hashable {
    var type: String  // move, must_do, set_time, visited
    var placeId: String
    var day: Int?
    var index: Int?
    var value: Bool?
    var time: String?
    var label: String
}

struct ConciergeReply: Codable {
    var reply: String
    var placeIds: [String]
    var actions: [ProposedAction]
}
