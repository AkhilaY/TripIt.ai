import Foundation

// Mirrors backend/app/models.py. Decoded with .convertFromSnakeCase.

enum JobStatus: String, Codable {
    case queued, downloading, transcribing, analyzing, done, failed

    var isFinished: Bool { self == .done || self == .failed }
}

struct ReelMetadataDTO: Codable, Hashable {
    var platform: String
    var url: String
    var title: String?
    var caption: String?
    var uploader: String?
    var thumbnailUrl: String?
    var durationSeconds: Double?
}

struct ExtractedPlaceDTO: Codable, Hashable {
    var name: String
    var category: String
    var city: String
    var country: String
    var neighborhood: String?
    var address: String?
    var description: String
    var recommendedItems: [String]
    var priceHint: String?
    var tips: String?
    var source: String
    var confidence: String
}

struct ExtractionResultDTO: Codable, Hashable {
    var title: String
    var destinationCity: String?
    var destinationCountry: String?
    var summary: String
    var places: [ExtractedPlaceDTO]
}

struct JobDTO: Codable {
    var id: String
    var url: String
    var status: JobStatus
    var message: String?
    var reel: ReelMetadataDTO?
    var result: ExtractionResultDTO?
    var warnings: [String]
}

struct CreateJobRequest: Codable {
    var url: String
    var sharedText: String?
}

struct PlanPlaceDTO: Codable {
    var id: String
    var name: String
    var category: String
    var latitude: Double?
    var longitude: Double?
    var neighborhood: String?
    var notes: String?
}

struct PlanRequestDTO: Codable {
    var city: String
    var days: Int
    var startDate: String?
    var preferences: String?
    var places: [PlanPlaceDTO]
}

struct PlannedStopDTO: Codable {
    var placeId: String
    var timeOfDay: String
    var note: String?
}

struct PlannedDayDTO: Codable {
    var dayNumber: Int
    var title: String
    var stops: [PlannedStopDTO]
}

struct PlanResultDTO: Codable {
    var days: [PlannedDayDTO]
    var unscheduledPlaceIds: [String]
    var notes: String?
}
