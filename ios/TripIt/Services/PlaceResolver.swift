import CoreLocation
import MapKit

/// Turns "Joe's Pizza, Greenwich Village, New York" into coordinates and an address using Apple Maps
/// search (free, no API key).
actor PlaceResolver {
    struct Match {
        var name: String
        var coordinate: CLLocationCoordinate2D
        var address: String?
        var phone: String?
        var website: URL?
    }

    private var cityRegions: [String: MKCoordinateRegion] = [:]

    func resolve(name: String, neighborhood: String?, city: String, country: String) async -> Match? {
        let region = await region(forCity: city, country: country)
        let queries = [
            [name, neighborhood, city].compactMap { $0 }.joined(separator: ", "),
            "\(name), \(city)",
        ]
        for query in queries {
            if let match = await search(query, near: region) { return match }
        }
        return nil
    }

    private func search(_ query: String, near region: MKCoordinateRegion?) async -> Match? {
        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = query
        request.resultTypes = [.pointOfInterest, .address]
        if let region { request.region = region }

        guard let response = try? await MKLocalSearch(request: request).start() else { return nil }
        let items = response.mapItems.filter { item in
            guard let region else { return true }
            // Ignore matches in a different city with the same name (> ~60 km away).
            let center = CLLocation(latitude: region.center.latitude, longitude: region.center.longitude)
            return item.placemark.location.map { $0.distance(from: center) < 60_000 } ?? false
        }
        guard let item = items.first else { return nil }
        return Match(
            name: item.name ?? query,
            coordinate: item.placemark.coordinate,
            address: Self.formatAddress(item.placemark),
            phone: item.phoneNumber,
            website: item.url
        )
    }

    private func region(forCity city: String, country: String) async -> MKCoordinateRegion? {
        let key = "\(city)|\(country)".lowercased()
        if let cached = cityRegions[key] { return cached }
        guard !city.isEmpty,
              let placemark = try? await CLGeocoder().geocodeAddressString("\(city), \(country)").first,
              let location = placemark.location else { return nil }
        let region = MKCoordinateRegion(center: location.coordinate, latitudinalMeters: 40_000, longitudinalMeters: 40_000)
        cityRegions[key] = region
        return region
    }

    private static func formatAddress(_ placemark: MKPlacemark) -> String? {
        let street = [placemark.subThoroughfare, placemark.thoroughfare].compactMap { $0 }.joined(separator: " ")
        let parts = [street.isEmpty ? nil : street, placemark.locality, placemark.administrativeArea]
            .compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: ", ")
    }
}
