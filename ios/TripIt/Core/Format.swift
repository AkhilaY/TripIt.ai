import CoreLocation
import Foundation

enum Fmt {
    private static let isoDay: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    static func day(_ iso: String) -> Date? { isoDay.date(from: String(iso.prefix(10))) }
    static func iso(_ date: Date) -> String { isoDay.string(from: date) }

    /// "2026-10-24" → "Sat, Oct 24"
    static func shortDay(_ iso: String) -> String {
        guard let date = day(iso) else { return iso }
        return date.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day())
    }

    /// The date of a trip's day, e.g. "Sat, Oct 24", when the trip has a start date.
    static func tripDay(start: String?, day number: Int) -> String? {
        guard let start, let first = day(start),
              let date = Calendar.current.date(byAdding: .day, value: number - 1, to: first) else { return nil }
        return date.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day())
    }

    /// "19:30" → "7:30 PM" in the phone's style
    static func clock(_ hhmm: String) -> String {
        let parts = hhmm.split(separator: ":").compactMap { Int($0) }
        guard parts.count == 2, let date = Calendar.current.date(from: DateComponents(hour: parts[0], minute: parts[1])) else { return hhmm }
        return date.formatted(date: .omitted, time: .shortened)
    }

    static func count(_ n: Int) -> String {
        n >= 1000 ? String(format: n >= 10000 ? "%.0fk" : "%.1fk", Double(n) / 1000).replacingOccurrences(of: ".0k", with: "k") : "\(n)"
    }

    static func distance(_ meters: Double) -> String {
        Measurement(value: meters, unit: UnitLength.meters)
            .formatted(.measurement(width: .abbreviated, usage: .road, numberFormatStyle: .number.precision(.fractionLength(0...1))))
    }

    static func duration(_ seconds: Int) -> String {
        let minutes = max(1, Int((Double(seconds) / 60).rounded()))
        return minutes < 60 ? "\(minutes) min" : "\(minutes / 60) h \(minutes % 60 > 0 ? "\(minutes % 60) min" : "")".trimmingCharacters(in: .whitespaces)
    }

    static func ago(_ iso: String) -> String {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = parser.date(from: iso) ?? ISO8601DateFormatter().date(from: iso)
            ?? ISO8601DateFormatter().date(from: iso + "Z")
        guard let date else { return "" }
        return date.formatted(.relative(presentation: .named))
    }

    static func plural(_ n: Int, _ word: String) -> String { "\(n) \(word)\(n == 1 ? "" : "s")" }

    static let timesOfDay = ["morning", "lunch", "afternoon", "dinner", "evening"]
}

extension Place {
    var coordinate: CLLocationCoordinate2D? {
        guard let latitude, let longitude else { return nil }
        return CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }

    func distance(from location: CLLocation?) -> Double? {
        guard let location, let latitude, let longitude else { return nil }
        return location.distance(from: CLLocation(latitude: latitude, longitude: longitude))
    }

    /// Links that open the place in Apple Maps or Google Maps.
    var appleMapsURL: URL? {
        var c = URLComponents(string: "https://maps.apple.com/")!
        if let latitude, let longitude {
            c.queryItems = [.init(name: "q", value: resolvedName ?? name), .init(name: "ll", value: "\(latitude),\(longitude)")]
        } else {
            c.queryItems = [.init(name: "q", value: [resolvedName ?? name, address ?? city].filter { !$0.isEmpty }.joined(separator: ", "))]
        }
        return c.url
    }

    var googleMapsURL: URL? {
        if let mapsUrl, mapsUrl.hasPrefix("http"), let url = URL(string: mapsUrl) { return url }
        var c = URLComponents(string: "https://www.google.com/maps/search/")!
        c.queryItems = [.init(name: "api", value: "1"),
                        .init(name: "query", value: [resolvedName ?? name, address ?? city].filter { !$0.isEmpty }.joined(separator: ", "))]
        return c.url
    }

    /// Turn-by-turn directions in Google Maps (the app if installed, otherwise the website).
    var googleDirectionsURL: URL? {
        Maps.googleDirections(latitude: latitude, longitude: longitude, query: [name, address ?? city].filter { !$0.isEmpty }.joined(separator: ", "))
    }

    var directionsURL: URL? {
        var c = URLComponents(string: "https://maps.apple.com/")!
        if let latitude, let longitude {
            c.queryItems = [.init(name: "daddr", value: "\(latitude),\(longitude)")]
        } else {
            c.queryItems = [.init(name: "daddr", value: [name, address ?? city].filter { !$0.isEmpty }.joined(separator: ", "))]
        }
        return c.url
    }
}

enum Maps {
    static func appleDirections(latitude: Double?, longitude: Double?, query: String) -> URL? {
        var c = URLComponents(string: "https://maps.apple.com/")!
        if let latitude, let longitude {
            c.queryItems = [.init(name: "daddr", value: "\(latitude),\(longitude)")]
        } else {
            c.queryItems = [.init(name: "daddr", value: query)]
        }
        return c.url
    }

    static func googleDirections(latitude: Double?, longitude: Double?, query: String) -> URL? {
        var c = URLComponents(string: "https://www.google.com/maps/dir/")!
        let destination = latitude.flatMap { lat in longitude.map { "\(lat),\($0)" } } ?? query
        c.queryItems = [.init(name: "api", value: "1"), .init(name: "destination", value: destination)]
        return c.url
    }
}
