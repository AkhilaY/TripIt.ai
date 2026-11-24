import SwiftUI
import UIKit

/// A photo from Unsplash. Unsplash's rules: load it from their address, and name the photographer where it's shown large.
struct ScenePhoto: Codable, Hashable {
    let photo: String  // "photo-…", the image's name on images.unsplash.com
    let name: String
    let username: String

    /// The photo cropped on Unsplash's servers to this many pixels.
    func url(width: Int, height: Int) -> URL? {
        URL(string: "https://images.unsplash.com/\(photo)?w=\(width)&h=\(height)&fit=crop&crop=entropy&q=75&fm=jpg")
    }

    /// Two sizes only (full screen, and cards), so each photo is downloaded at most twice and then kept on the phone.
    var large: URL? { url(width: 1080, height: 1920) }
    var card: URL? { url(width: 600, height: 720) }
    var credit: String { "Photo: \(name) / Unsplash" }
}

/// Which photo a city gets: its own hand-picked one, its featured place's (Kyoto, or Lake Lucerne for Lucerne), or one
/// the server found on Unsplash. Found ones are kept on the phone, so each city is only asked about once.
@MainActor @Observable
final class CityPhotoBook {
    static let shared = CityPhotoBook()

    private(set) var found: [String: ScenePhoto] = DiskCache.load("city-photos") ?? [:]
    @ObservationIgnored private var asked: Set<String> = []

    nonisolated static func key(_ city: String) -> String { PlaceFilter.normalize(city) }

    func photo(for city: String) -> ScenePhoto? {
        let key = Self.key(city)
        guard !key.isEmpty else { return nil }
        return ScenePhotos.cities[key] ?? WorldScenes.exact(city)?.photo ?? found[key]
    }

    /// Asks the server for a photo of a city that has none yet (once per run; a city with no good photo is left).
    func load(city: String, country: String = "") async {
        let key = Self.key(city)
        guard key.count >= 2, photo(for: city) == nil, !asked.contains(key), SessionStore.token != nil else { return }
        asked.insert(key)
        let enc = { (s: String) in s.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "" }
        guard let result = try? await API.shared.get("/v1/city-photo?city=\(enc(city))&country=\(enc(country))", as: ScenePhoto?.self),
              let result else { return }
        found[key] = result
        DiskCache.save("city-photos", found)
    }
}

/// An Unsplash photo filling its frame. The welcome photos are in the app; others show at once once seen before.
struct PhotoFill: View {
    let photo: ScenePhoto
    var large = false
    var bundled: String?  // an asset in the app

    var body: some View {
        if let bundled, let image = UIImage(named: bundled) {
            Color.clear
                .overlay { Image(uiImage: image).resizable().scaledToFill() }
                .clipped()
                .contentShape(Rectangle())
        } else {
            let url = large ? photo.large : photo.card
            // Kept on the phone from an earlier run: read it now, so the Home header doesn't open blank.
            let _ = large ? ImageLoader.fromDisk(url) : nil
            RemoteImage(url: url) { Color(hex: 0x8E8984) }
        }
    }
}

/// A city's picture on its card: the city's photo; until there is one, the best photo of a place saved there.
struct CityCover: View {
    let city: String
    var country = ""
    var fallback: [URL] = []

    var body: some View {
        Group {
            if let photo = CityPhotoBook.shared.photo(for: city) {
                PhotoFill(photo: photo)
            } else {
                ChainImage(urls: fallback) { CityScene(city: city, country: country) }
            }
        }
        .task(id: city) { await CityPhotoBook.shared.load(city: city, country: country) }
    }
}
