import Foundation
import Observation

/// Your library as the app knows it: saved places, folders, trips and imports, refreshed from the server.
/// Screens read from here and call its methods to change things, so every list stays in step.
@MainActor
@Observable
final class Store {
    var places: [Place] = []
    var folders: [Folder] = []
    var trips: [Trip] = []
    var jobs: [Job] = []
    var tripDetails: [String: TripDetail] = [:]
    /// Your home city: its places are "Around <city>" and never need a trip.
    var home: HomeSetting?
    var loaded = false
    var error: String?
    /// A short message shown at the bottom of the screen ("Saved to Date night").
    var toast: Toast?
    /// An import that just finished, to review: its places by city, a trip that passes through, lists.
    var reviewJob: Job?
    /// Every booking across your trips, soonest first (undated ones last), for the Bookings tab.
    var bookings: [Booking] = []
    var bookingsLoaded = false
    /// Features switched off on the server (see Features), kept here so screens update when it arrives.
    var featuresOff = Features.off

    private let api = API.shared
    private var pollTask: Task<Void, Never>?

    /// What the app showed last time, so it opens instantly and refreshes in the background.
    private struct Snapshot: Codable {
        var places: [Place]
        var folders: [Folder]
        var trips: [Trip]
        var jobs: [Job]
        var home: HomeSetting?
    }

    private static var snapshotURL: URL? {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?.appendingPathComponent("library.json")
    }

    init() {
        guard let url = Self.snapshotURL, let data = try? Data(contentsOf: url),
              let saved = try? JSONDecoder().decode(Snapshot.self, from: data) else { return }
        (places, folders, trips, jobs, home) = (saved.places, saved.folders, saved.trips, saved.jobs, saved.home)
        loaded = true
    }

    private func saveSnapshot() {
        let snapshot = Snapshot(places: places, folders: folders, trips: trips, jobs: jobs, home: home)
        guard let url = Self.snapshotURL, let data = try? JSONEncoder().encode(snapshot) else { return }
        try? data.write(to: url, options: .atomic)
    }

    struct Toast: Equatable, Identifiable {
        let id = UUID()
        let text: String
        let isError: Bool
    }

    func show(_ text: String, error: Bool = false) {
        toast = Toast(text: text, isError: error)
    }

    func fail(_ error: Error) {
        if error is CancellationError { return }
        show(error.localizedDescription, error: true)
    }

    // MARK: Loading

    func refresh() async {
        do {
            async let p: [Place] = api.get("/v1/places")
            async let f: [Folder] = api.get("/v1/folders")
            async let t: [Trip] = api.get("/v1/trips")
            async let j: [Job] = api.get("/v1/jobs?limit=30")
            async let h = api.get("/v1/home", as: HomeSetting?.self)
            (places, folders, trips, jobs) = try await (p, f, t, j)
            await Features.refresh()
            featuresOff = Features.off
            await EventSync.shared.sync(saved)
            home = (try? await h) ?? home
            loaded = true
            error = nil
            saveSnapshot()
            if jobs.contains(where: \.isActive) { pollJobs() }
        } catch {
            if !loaded { self.error = error.localizedDescription }
        }
    }

    func reloadPlaces() async {
        if let p: [Place] = try? await api.get("/v1/places") { places = p; await EventSync.shared.sync(saved) }
        if let f: [Folder] = try? await api.get("/v1/folders") { folders = f }
    }

    func reloadTrips() async {
        if let t: [Trip] = try? await api.get("/v1/trips") { trips = t }
    }

    @discardableResult
    func loadTrip(_ id: String) async throws -> TripDetail {
        let trip: TripDetail = try await api.get("/v1/trips/\(id)")
        tripDetails[id] = trip
        return trip
    }

    /// Keeps the cached trip and the saved list in step after a call that returns the whole trip.
    func apply(_ trip: TripDetail) {
        tripDetails[trip.id] = trip
        for p in trip.places { update(p, inTrip: true) }
    }

    func update(_ place: Place, inTrip: Bool = false) {
        if let i = places.firstIndex(where: { $0.id == place.id }) {
            var merged = place
            if inTrip { // a trip's copy carries that trip's day and time; keep the saved copy's own fields
                merged.tripId = places[i].tripId
                merged.dayNumber = places[i].dayNumber
                merged.dayOrder = places[i].dayOrder
                merged.timeOfDay = places[i].timeOfDay
                merged.startTime = places[i].startTime
            }
            places[i] = merged
        }
        guard !inTrip else { return }
        for (id, var trip) in tripDetails {
            if let i = trip.places.firstIndex(where: { $0.id == place.id }) {
                let old = trip.places[i]
                var merged = place
                merged.tripId = old.tripId
                merged.dayNumber = old.dayNumber
                merged.dayOrder = old.dayOrder
                merged.timeOfDay = old.timeOfDay
                merged.dayNote = old.dayNote
                merged.suggested = old.suggested
                merged.suggestionNote = old.suggestionNote
                if place.tripId != id { merged.startTime = old.startTime }
                trip.places[i] = merged
                tripDetails[id] = trip
            }
        }
    }

    func place(_ id: String) -> Place? {
        places.first { $0.id == id } ?? tripDetails.values.lazy.compactMap { $0.places.first { $0.id == id } }.first
    }

    // MARK: Imports

    func pollJobs() {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(4))
                guard let self else { return }
                let before = Set(self.jobs.filter(\.isActive).map(\.id))
                guard let fresh: [Job] = try? await self.api.get("/v1/jobs?limit=30") else { continue }
                self.jobs = fresh
                let finished = fresh.filter { before.contains($0.id) && !$0.isActive }
                if !finished.isEmpty {
                    await self.reloadPlaces()
                    await self.reloadTrips()
                    for job in finished {
                        if job.status == "done" {
                            if job.reelId != nil, self.places.contains(where: { $0.reelIds.contains(job.reelId!) }) {
                                self.reviewJob = job
                            } else {
                                self.show(job.addedPlaces == 1 ? "1 new place saved" : "\(job.addedPlaces) new places saved")
                            }
                        } else {
                            self.show(job.message ?? "Couldn't read that post", error: true)
                        }
                    }
                }
                if !fresh.contains(where: \.isActive) { break }
            }
            self?.pollTask = nil
        }
    }

    func importLink(_ text: String) async throws {
        let job: Job = try await api.post("/v1/jobs", ["url": text, "shared_text": text])
        jobs.removeAll { $0.id == job.id }
        jobs.insert(job, at: 0)
        pollJobs()
    }

    func importScreenshots(_ jpegs: [Data], note: String?) async throws {
        let images = jpegs.map { "data:image/jpeg;base64,\($0.base64EncodedString())" }
        let job: Job = try await api.post("/v1/jobs/screenshots", ["images": images, "note": note])
        jobs.insert(job, at: 0)
        pollJobs()
    }

    func retry(_ job: Job) async {
        do {
            let fresh: Job = try await api.post("/v1/jobs/\(job.id)/retry")
            if let i = jobs.firstIndex(where: { $0.id == job.id }) { jobs[i] = fresh }
            pollJobs()
        } catch { fail(error) }
    }

    // MARK: Places

    func patch(_ place: Place, _ body: [String: Any?], tripId: String? = nil) async {
        var body = body
        if let tripId { body["trip_id"] = tripId }
        do {
            let fresh: Place = try await api.patch("/v1/places/\(place.id)", body)
            if let tripId, var trip = tripDetails[tripId], let i = trip.places.firstIndex(where: { $0.id == place.id }) {
                trip.places[i] = fresh
                tripDetails[tripId] = trip
            }
            update(fresh, inTrip: tripId != nil)
            if Category(fresh.category) == .event { await EventSync.shared.sync(saved) }
            if tripId != nil, let saved = places.first(where: { $0.id == place.id }) {
                // fields that aren't trip-specific (star, notes, visited) changed on the saved copy too
                var s = saved
                s.mustDo = fresh.mustDo; s.visited = fresh.visited; s.userNotes = fresh.userNotes
                s.name = fresh.name; s.category = fresh.category
                update(s)
            }
        } catch { fail(error) }
    }

    func toggleStar(_ place: Place) async {
        await patch(place, ["must_do": !place.mustDo])
        show(place.mustDo ? "Star removed" : "Starred. It stays at the top of your lists")
    }

    @discardableResult
    func delete(_ place: Place) async -> Bool {
        do {
            try await api.call("DELETE", "/v1/places/\(place.id)")
            places.removeAll { $0.id == place.id }
            for (id, var trip) in tripDetails where trip.places.contains(where: { $0.id == place.id }) {
                trip.places.removeAll { $0.id == place.id }
                tripDetails[id] = trip
            }
            await reloadPlaces()
            await reloadTrips()
            show("Place deleted")
            return true
        } catch { fail(error); return false }
    }

    func add(_ result: AddPlaceResult) async {
        await reloadPlaces()
        await reloadTrips()
        show(result.created ? "Saved \(result.place.name)" : "\(result.place.name) was already saved")
    }

    // MARK: Folders

    @discardableResult
    func createFolder(_ name: String, placeIds: [String] = []) async -> Folder? {
        do {
            let folder: Folder = try await api.post("/v1/folders", ["name": name, "place_ids": placeIds])
            await reloadPlaces()
            return folder
        } catch { fail(error); return nil }
    }

    func addToFolder(_ folderId: String, _ placeIds: [String]) async {
        do {
            let _: Folder = try await api.post("/v1/folders/\(folderId)/places", ["place_ids": placeIds])
            await reloadPlaces()
        } catch { fail(error) }
    }

    func removeFromFolder(_ folderId: String, _ placeId: String) async {
        do {
            let _: Folder = try await api.delete("/v1/folders/\(folderId)/places/\(placeId)")
            await reloadPlaces()
        } catch { fail(error) }
    }

    func renameFolder(_ folder: Folder, to name: String) async {
        do {
            let _: Folder = try await api.patch("/v1/folders/\(folder.id)", ["name": name])
            await reloadPlaces()
        } catch { fail(error) }
    }

    func deleteFolder(_ folder: Folder) async {
        do {
            try await api.call("DELETE", "/v1/folders/\(folder.id)")
            await reloadPlaces()
            show("Folder deleted. Its places are still saved.")
        } catch { fail(error) }
    }

    // MARK: Trips

    func addToTrip(_ tripId: String, _ placeIds: [String]) async {
        do {
            let trip: TripDetail = try await api.post("/v1/trips/\(tripId)/places", ["place_ids": placeIds])
            apply(trip)
            await reloadPlaces()
            await reloadTrips()
        } catch { fail(error) }
    }

    func removeFromTrip(_ tripId: String, _ placeId: String) async {
        do {
            let trip: TripDetail = try await api.delete("/v1/trips/\(tripId)/places/\(placeId)")
            apply(trip)
            await reloadPlaces()
            await reloadTrips()
        } catch { fail(error) }
    }

    /// Runs a call that returns the whole trip, and keeps everything in step.
    @discardableResult
    func tripCall(_ method: String, _ path: String, _ body: [String: Any?] = [:]) async -> TripDetail? {
        do {
            let trip: TripDetail
            switch method {
            case "DELETE": trip = try await api.delete(path)
            case "PATCH": trip = try await api.patch(path, body)
            default: trip = try await api.post(path, body)
            }
            apply(trip)
            await reloadTrips()
            return trip
        } catch { fail(error); return nil }
    }

    @discardableResult
    func deleteTrip(_ tripId: String) async -> Bool {
        do {
            try await api.call("DELETE", "/v1/trips/\(tripId)")
            tripDetails[tripId] = nil
            await reloadTrips()
            await reloadPlaces()
            return true
        } catch { fail(error); return false }
    }

    // MARK: Bookings

    func reloadBookings() async {
        do {
            bookings = try await api.get("/v1/bookings")
        } catch { if bookingsLoaded { fail(error) } }
        bookingsLoaded = true
    }

    /// The trip a new booking most likely belongs to: the one happening now, else the next one, else the newest.
    var likelyBookingTrip: Trip? {
        if let active = activeTrip { return active.trip }
        let today = Fmt.iso(Date())
        let next = realTrips.filter { ($0.startDate ?? "") >= today }.min { ($0.startDate ?? "") < ($1.startDate ?? "") }
        return next ?? realTrips.max { $0.createdAt < $1.createdAt } ?? trips.first
    }

    func setHome(_ city: String) async -> Bool {
        do {
            home = try await api.put("/v1/home", ["city": city])
            return true
        } catch { fail(error); return false }
    }

    func reset() {
        places = []; folders = []; trips = []; jobs = []; tripDetails = [:]; home = nil; loaded = false
        bookings = []; bookingsLoaded = false
        if let url = Self.snapshotURL { try? FileManager.default.removeItem(at: url) }
        pollTask?.cancel(); pollTask = nil
    }
}

// MARK: - Cities, trips and filing

extension Store {
    struct CityGroup: Identifiable, Hashable {
        let name: String
        let country: String
        let places: [Place]
        var id: String { Store.cityKey(name) }
    }

    nonisolated static func cityKey(_ city: String) -> String {
        city.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: nil).trimmingCharacters(in: .whitespaces)
    }

    var homeKey: String? { home.map { Store.cityKey($0.city) } }

    func isHome(_ place: Place) -> Bool {
        guard let homeKey, !place.city.isEmpty else { return false }
        return Store.cityKey(place.city) == homeKey
    }

    /// Saved places (not ones an AI plan suggested that you haven't kept).
    var saved: [Place] { places.filter(\.saved) }

    func places(inCity name: String) -> [Place] {
        let key = Store.cityKey(name)
        return saved.filter { Store.cityKey($0.city) == key }
    }

    /// Every city you've saved places in, except home, the biggest first.
    func cityGroups(_ from: [Place]? = nil) -> [CityGroup] {
        let source = (from ?? saved).filter { !$0.city.isEmpty && !isHome($0) }
        return Dictionary(grouping: source) { Store.cityKey($0.city) }
            .map { _, items in CityGroup(name: items[0].city, country: items[0].country, places: items) }
            .sorted { $0.places.count != $1.places.count ? $0.places.count > $1.places.count : $0.name < $1.name }
    }

    /// Trips (not home collections), soonest first; ones without dates last.
    var realTrips: [Trip] {
        trips.filter { !$0.isLocal }.sorted { a, b in
            switch (a.startDate, b.startDate) {
            case let (x?, y?): return x < y
            case (nil, _?): return false
            case (_?, nil): return true
            default: return a.createdAt > b.createdAt
            }
        }
    }

    /// Trips that haven't ended, soonest first.
    var upcomingTrips: [Trip] {
        let today = Fmt.iso(Date())
        return realTrips.filter { t in
            guard let start = t.startDate else { return false }
            return t.lastDay.map { $0 >= today } ?? (start >= today)
        }
    }

    func trip(forCity name: String) -> Trip? {
        let key = Store.cityKey(name)
        let visits = { (t: Trip) in t.cities.contains { Store.cityKey($0) == key } }
        return upcomingTrips.first(where: visits) ?? realTrips.first(where: visits)
    }

    /// The trip you're on today, and which day of it.
    var activeTrip: (trip: Trip, day: Int)? {
        let today = Calendar.current.startOfDay(for: Date())
        for t in realTrips {
            guard let start = t.startDate.flatMap(Fmt.day), t.dayCount > 0,
                  let n = Calendar.current.dateComponents([.day], from: Calendar.current.startOfDay(for: start), to: today).day else { continue }
            if n + 1 >= 1 && n + 1 <= t.dayCount { return (t, n + 1) }
        }
        return nil
    }

    /// Where a place lives: "Around Atlanta", "Switzerland trip, Day 1", "on your wishlist".
    func filing(_ place: Place) -> String {
        let city = place.city.isEmpty ? nil : place.city
        var where_: String
        if isHome(place), let home { where_ = "Around \(home.city)" }
        else if let trip = realTrips.first(where: { place.tripIds.contains($0.id) }) {
            where_ = trip.name.lowercased().contains("trip") ? trip.name : "\(trip.name) trip"
            if let day = tripDetails[trip.id]?.places.first(where: { $0.id == place.id })?.dayNumber { where_ += ", Day \(day)" }
        } else if let folder = folders.first(where: { place.folderIds.contains($0.id) }) { where_ = folder.name }
        else { where_ = "on your wishlist" }
        return [city, where_].compactMap { $0 }.joined(separator: " · ")
    }
}

extension Trip {
    /// The trip's last day ("2026-11-06"), when it has dates.
    var lastDay: String? {
        guard let start = startDate.flatMap(Fmt.day), dayCount > 0,
              let end = Calendar.current.date(byAdding: .day, value: dayCount - 1, to: start) else { return startDate }
        return Fmt.iso(end)
    }

    /// "Nov 1–6" (or "1–6 Nov", by region), or nil without dates.
    var dateRange: String? {
        guard let start = startDate.flatMap(Fmt.day) else { return nil }
        return Fmt.range(start, lastDay.flatMap(Fmt.day) ?? start)
    }

    /// "In 9 days", "Tomorrow", "Now", or nil.
    var countdown: String? {
        guard let start = startDate.flatMap(Fmt.day) else { return nil }
        let cal = Calendar.current
        let days = cal.dateComponents([.day], from: cal.startOfDay(for: Date()), to: start).day ?? 0
        if days > 1 { return "In \(days) days" }
        if days == 1 { return "Tomorrow" }
        if let end = lastDay, end >= Fmt.iso(Date()) { return "Now" }
        return nil
    }
}
