import Foundation

/// A shared link waiting to be turned into places. The Share Extension writes these to the App Group;
/// the app picks them up, polls the backend and saves the places.
struct PendingImport: Codable, Identifiable, Hashable {
    enum State: String, Codable {
        case waiting      // not yet sent to the backend
        case processing   // backend job running
        case failed
    }

    var id = UUID()
    var url: String
    var sharedText: String?
    var jobID: String?
    var state: State = .waiting
    var message: String?
    var createdAt = Date()
}

enum PendingImportStore {
    private static let key = "pendingImports"

    static func all() -> [PendingImport] {
        guard let data = AppConfig.sharedDefaults.data(forKey: key),
              let items = try? JSONDecoder().decode([PendingImport].self, from: data) else { return [] }
        return items
    }

    static func add(_ item: PendingImport) {
        var items = all()
        items.removeAll { $0.url == item.url && $0.state != .failed }
        items.append(item)
        save(items)
    }

    static func update(_ item: PendingImport) {
        var items = all()
        if let index = items.firstIndex(where: { $0.id == item.id }) {
            items[index] = item
            save(items)
        }
    }

    static func remove(id: UUID) {
        save(all().filter { $0.id != id })
    }

    private static func save(_ items: [PendingImport]) {
        if let data = try? JSONEncoder().encode(items) {
            AppConfig.sharedDefaults.set(data, forKey: key)
        }
    }
}

enum LinkExtractor {
    /// Finds the first http(s) link in text such as "Check out this video! https://vm.tiktok.com/ZM123/".
    static func firstURL(in text: String) -> URL? {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        return detector.matches(in: text, range: range)
            .compactMap(\.url)
            .first { $0.scheme == "http" || $0.scheme == "https" }
    }
}
