import MapKit
import UIKit

enum MapsLauncher {
    static var hasGoogleMapsApp: Bool {
        guard let url = URL(string: "comgooglemaps://") else { return false }
        return UIApplication.shared.canOpenURL(url)
    }

    private static func query(for place: Place) -> String {
        [place.resolvedName ?? place.name, place.address ?? place.city].compactMap { $0 }.joined(separator: ", ")
    }

    static func openInAppleMaps(_ place: Place, directions: Bool = false) {
        if let coordinate = place.coordinate {
            let item = MKMapItem(placemark: MKPlacemark(coordinate: coordinate))
            item.name = place.resolvedName ?? place.name
            let options: [String: Any]? = directions
                ? [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDefault]
                : nil
            item.openInMaps(launchOptions: options)
        } else {
            var components = URLComponents(string: "https://maps.apple.com/")!
            components.queryItems = [URLQueryItem(name: directions ? "daddr" : "q", value: query(for: place))]
            if let url = components.url { UIApplication.shared.open(url) }
        }
    }

    static func openInGoogleMaps(_ place: Place, directions: Bool = false) {
        if let url = googleMapsURL(for: place, directions: directions) {
            UIApplication.shared.open(url)
        }
    }

    static func googleMapsURL(for place: Place, directions: Bool = false, preferApp: Bool = true) -> URL? {
        let q = query(for: place)
        if preferApp && hasGoogleMapsApp {
            var components = URLComponents(string: "comgooglemaps://")!
            components.queryItems = directions
                ? [URLQueryItem(name: "daddr", value: q)]
                : [URLQueryItem(name: "q", value: q)]
            if let c = place.coordinate {
                components.queryItems?.append(URLQueryItem(name: "center", value: "\(c.latitude),\(c.longitude)"))
            }
            return components.url
        }
        var components = URLComponents(string: directions
            ? "https://www.google.com/maps/dir/"
            : "https://www.google.com/maps/search/")!
        components.queryItems = [URLQueryItem(name: "api", value: "1"),
                                 URLQueryItem(name: directions ? "destination" : "query", value: q)]
        return components.url
    }

    /// Plain-text list with Google Maps links, for sharing a trip with friends or pasting into notes.
    static func shareText(for trip: Trip) -> String {
        var lines = ["\(trip.name) — saved with TripIt", ""]
        func line(_ place: Place) -> String {
            let link = googleMapsURL(for: place, preferApp: false)?.absoluteString ?? ""
            return "• \(place.name) (\(place.category.label)) \(link)"
        }
        if trip.hasItinerary {
            for day in 1...trip.dayCount {
                let places = trip.stops(onDay: day)
                guard !places.isEmpty else { continue }
                lines.append("Day \(day): \(trip.title(forDay: day))")
                lines += places.map(line)
                lines.append("")
            }
            let rest = trip.unscheduledPlaces
            if !rest.isEmpty {
                lines.append("Also saved")
                lines += rest.map(line)
            }
        } else {
            lines += trip.allPlaces.map(line)
        }
        return lines.joined(separator: "\n")
    }
}
