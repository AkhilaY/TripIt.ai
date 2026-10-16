import CoreLocation
import Foundation
import SwiftData

// CloudKit-backed SwiftData rules: every property needs a default or must be optional,
// relationships must be optional, and @Attribute(.unique) isn't allowed.

@Model
final class Trip {
    var id: UUID = UUID()
    var name: String = ""
    var city: String = ""
    var country: String = ""
    var createdAt: Date = Date()

    // Itinerary
    var startDate: Date?
    var dayCount: Int = 0
    var dayTitles: [String] = []
    var planNotes: String?

    @Relationship(deleteRule: .cascade, inverse: \Place.trip)
    var places: [Place]? = []

    @Relationship(deleteRule: .cascade, inverse: \ReelSource.trip)
    var sources: [ReelSource]? = []

    init(name: String, city: String, country: String) {
        self.name = name
        self.city = city
        self.country = country
    }

    var allPlaces: [Place] { (places ?? []).sorted { $0.createdAt < $1.createdAt } }
    var hasItinerary: Bool { dayCount > 0 }

    func places(onDay day: Int) -> [Place] {
        allPlaces.filter { $0.dayNumber == day }.sorted { $0.dayOrder < $1.dayOrder }
    }

    var unscheduledPlaces: [Place] { allPlaces.filter { $0.dayNumber == nil } }

    func title(forDay day: Int) -> String {
        day - 1 < dayTitles.count ? dayTitles[day - 1] : "Day \(day)"
    }

    func date(forDay day: Int) -> Date? {
        startDate.flatMap { Calendar.current.date(byAdding: .day, value: day - 1, to: $0) }
    }

    func clearItinerary() {
        for place in allPlaces {
            place.dayNumber = nil
            place.dayOrder = 0
            place.timeOfDayRaw = nil
            place.dayNote = nil
        }
        dayCount = 0
        dayTitles = []
        planNotes = nil
    }
}

@Model
final class Place {
    var id: UUID = UUID()
    var name: String = ""
    var categoryRaw: String = PlaceCategory.other.rawValue
    var summary: String = ""
    var recommendedItems: [String] = []
    var priceHint: String?
    var tips: String?
    var userNotes: String = ""
    var confidence: String = "high"
    var visited: Bool = false
    var createdAt: Date = Date()

    // Location
    var neighborhood: String?
    var address: String?
    var city: String = ""
    var country: String = ""
    var latitude: Double?
    var longitude: Double?
    var phone: String?
    var website: String?
    var resolvedName: String?  // the name Apple Maps matched, if different

    // Itinerary
    var dayNumber: Int?
    var dayOrder: Int = 0
    var timeOfDayRaw: String?
    var dayNote: String?

    var trip: Trip?
    var source: ReelSource?

    init(name: String, category: PlaceCategory, city: String, country: String) {
        self.name = name
        self.categoryRaw = category.rawValue
        self.city = city
        self.country = country
    }

    var category: PlaceCategory {
        get { PlaceCategory(rawValue: categoryRaw) ?? .other }
        set { categoryRaw = newValue.rawValue }
    }

    var timeOfDay: TimeOfDay? {
        get { timeOfDayRaw.flatMap(TimeOfDay.init(rawValue:)) }
        set { timeOfDayRaw = newValue?.rawValue }
    }

    var coordinate: CLLocationCoordinate2D? {
        guard let latitude, let longitude else { return nil }
        return CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }

    var locationLine: String {
        [neighborhood, city].compactMap { $0?.isEmpty == false ? $0 : nil }.joined(separator: " · ")
    }
}

@Model
final class ReelSource {
    var id: UUID = UUID()
    var url: String = ""
    var platform: String = ""
    var title: String = ""
    var summary: String = ""
    var caption: String?
    var creator: String?
    var thumbnailURL: String?
    var importedAt: Date = Date()

    var trip: Trip?

    @Relationship(deleteRule: .nullify, inverse: \Place.source)
    var places: [Place]? = []

    init(url: String, platform: String, title: String) {
        self.url = url
        self.platform = platform
        self.title = title
    }

    var platformName: String {
        switch platform {
        case "tiktok": return "TikTok"
        case "instagram": return "Instagram"
        case "youtube": return "YouTube"
        default: return "Link"
        }
    }
}
