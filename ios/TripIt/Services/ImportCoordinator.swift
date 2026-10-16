import Foundation
import Observation
import SwiftData

/// Moves shared links through: pending (App Group) -> backend job -> places saved in SwiftData.
@MainActor
@Observable
final class ImportCoordinator {
    private(set) var pending: [PendingImport] = []
    private(set) var statusByID: [UUID: String] = [:]
    private(set) var lastImportedTrip: Trip?

    private let resolver = PlaceResolver()
    private var pollTask: Task<Void, Never>?
    private var pollGeneration = 0
    private var context: ModelContext?

    func attach(_ context: ModelContext) {
        self.context = context
    }

    /// Call when the app becomes active. Polls until everything pending is finished.
    func start() {
        reload()
        guard context != nil, pollTask == nil else { return }
        pollGeneration += 1
        let generation = pollGeneration
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                let active = await self.tick()
                if !active { break }
                try? await Task.sleep(for: .seconds(3))
            }
            // Only clear our own handle; stop()+start() may already have replaced it.
            if let self, self.pollGeneration == generation { self.pollTask = nil }
        }
    }

    func stop() {
        pollTask?.cancel()
        pollTask = nil
    }

    func addLink(_ text: String) {
        guard let url = LinkExtractor.firstURL(in: text) else { return }
        PendingImportStore.add(PendingImport(url: url.absoluteString, sharedText: text == url.absoluteString ? nil : text))
        stop()
        start()
    }

    func retry(_ item: PendingImport) {
        var item = item
        item.state = .waiting
        item.jobID = nil
        item.message = nil
        PendingImportStore.update(item)
        stop()
        start()
    }

    func remove(_ item: PendingImport) {
        PendingImportStore.remove(id: item.id)
        reload()
    }

    private func reload() {
        pending = PendingImportStore.all().sorted { $0.createdAt > $1.createdAt }
    }

    /// One polling pass. Returns true while there is still work in flight.
    private func tick() async -> Bool {
        reload()
        let client = APIClient()
        var stillActive = false

        for var item in pending where item.state != .failed {
            do {
                if item.jobID == nil {
                    let job = try await client.createJob(url: item.url, sharedText: item.sharedText)
                    item.jobID = job.id
                    item.state = .processing
                    PendingImportStore.update(item)
                }
                let job = try await client.job(id: item.jobID!)
                statusByID[item.id] = job.message ?? job.status.rawValue.capitalized
                if item.message != nil {
                    item.message = nil
                    PendingImportStore.update(item)
                }

                switch job.status {
                case .done:
                    if let result = job.result {
                        try await save(result: result, reel: job.reel, url: item.url)
                    }
                    PendingImportStore.remove(id: item.id)
                case .failed:
                    item.state = .failed
                    item.message = job.message ?? "Processing failed"
                    PendingImportStore.update(item)
                default:
                    stillActive = true
                }
            } catch APIError.http(404, _) {
                // Server restarted and forgot the job; submit it again.
                item.jobID = nil
                item.state = .waiting
                PendingImportStore.update(item)
                stillActive = true
            } catch APIError.http(let code, let detail) where (400..<500).contains(code) && code != 429 {
                // Bad link, wrong API key, etc. Retrying won't help until something changes.
                item.state = .failed
                item.message = detail ?? "Request rejected (\(code))"
                PendingImportStore.update(item)
            } catch {
                item.message = error.localizedDescription
                PendingImportStore.update(item)
                // Network problems: keep the item and try again next time the app opens.
            }
        }
        reload()
        return stillActive
    }

    // MARK: - Saving

    private func save(result: ExtractionResultDTO, reel: ReelMetadataDTO?, url: String) async throws {
        guard let context else { throw CancellationError() }

        let source = ReelSource(
            url: reel?.url ?? url,
            platform: reel?.platform ?? "",
            title: result.title
        )
        source.summary = result.summary
        source.caption = reel?.caption
        source.creator = reel?.uploader
        source.thumbnailURL = reel?.thumbnailUrl
        context.insert(source)

        var firstTrip: Trip?
        for extracted in result.places {
            let city = extracted.city.isEmpty ? (result.destinationCity ?? "Saved places") : extracted.city
            let country = extracted.country.isEmpty ? (result.destinationCountry ?? "") : extracted.country
            let trip = findOrCreateTrip(city: city, country: country, in: context)
            firstTrip = firstTrip ?? trip

            if let existing = trip.allPlaces.first(where: { Self.normalized($0.name) == Self.normalized(extracted.name) }) {
                merge(extracted, into: existing)
                continue
            }

            let place = Place(name: extracted.name, category: PlaceCategory(rawValue: extracted.category) ?? .other,
                              city: city, country: country)
            place.summary = extracted.description
            place.recommendedItems = extracted.recommendedItems
            place.priceHint = extracted.priceHint
            place.tips = extracted.tips
            place.neighborhood = extracted.neighborhood
            place.address = extracted.address
            place.confidence = extracted.confidence
            place.source = source
            context.insert(place)
            place.trip = trip

            if let match = await resolver.resolve(name: extracted.name, neighborhood: extracted.neighborhood,
                                                  city: city, country: country) {
                place.latitude = match.coordinate.latitude
                place.longitude = match.coordinate.longitude
                place.address = place.address ?? match.address
                place.phone = match.phone
                place.website = match.website?.absoluteString
                if Self.normalized(match.name) != Self.normalized(extracted.name) {
                    place.resolvedName = match.name
                }
            }
        }

        source.trip = firstTrip
        try context.save()
        lastImportedTrip = firstTrip
    }

    private func merge(_ extracted: ExtractedPlaceDTO, into place: Place) {
        let newItems = extracted.recommendedItems.filter { !place.recommendedItems.contains($0) }
        place.recommendedItems += newItems
        if place.tips == nil { place.tips = extracted.tips }
        if place.priceHint == nil { place.priceHint = extracted.priceHint }
        if !extracted.description.isEmpty && !place.summary.contains(extracted.description) {
            place.summary += place.summary.isEmpty ? extracted.description : "\n\n" + extracted.description
        }
    }

    private func findOrCreateTrip(city: String, country: String, in context: ModelContext) -> Trip {
        let trips = (try? context.fetch(FetchDescriptor<Trip>())) ?? []
        if let trip = trips.first(where: { Self.normalized($0.city) == Self.normalized(city) }) {
            return trip
        }
        let trip = Trip(name: city, city: city, country: country)
        context.insert(trip)
        return trip
    }

    static func normalized(_ text: String) -> String {
        text.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty && $0 != "the" }
            .joined(separator: " ")
    }
}
