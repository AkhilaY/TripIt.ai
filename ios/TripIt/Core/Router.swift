import Foundation
import Observation

enum AppTab: Hashable {
    case home, library, discover, bookings, concierge
}

/// Screens pushed onto a tab's navigation stack.
enum Route: Hashable {
    case place(id: String, tripId: String?)
    case trip(id: String)
    case folder(id: String)
    /// Everything saved in one city (your home city is "Around <city>").
    case city(name: String)
    /// Your saved places on a map.
    case map
    case imports
    /// The places saved from one post.
    case reel(id: String)
    /// A restaurant's menu.
    case menu(placeId: String)
    /// A place from an edit that isn't saved yet: a preview with Save.
    case editPlace(tripId: String, editId: String, entryId: String)
    /// A screen of the web app that isn't native yet, by its address inside the app (e.g. "#/packing/<trip id>").
    case web(hash: String)
}

/// Which tab is showing and what's pushed on each, so links (from web screens and notifications) can open screens.
@MainActor
@Observable
final class Router {
    var tab: AppTab = .home
    var home: [Route] = []
    var library: [Route] = []
    var discover: [Route] = []
    var bookings: [Route] = []
    var concierge: [Route] = []
    var showProfile = false
    var profilePath: [Route] = []
    /// Set to open the Add sheet, optionally with a link already filled in.
    var addRequest: AddRequest?

    struct AddRequest: Identifiable {
        let id = UUID()
        var text: String = ""
        var tripId: String?
        var folderId: String?
    }

    func push(_ route: Route) {
        if showProfile { profilePath.append(route); return }
        switch tab {
        case .home: home.append(route)
        case .library: library.append(route)
        case .discover: discover.append(route)
        case .bookings: bookings.append(route)
        case .concierge: concierge.append(route)
        }
    }

    /// Opens one of the web app's addresses ("#/trip/abc", "/#/saved?reel=x") as the matching screen.
    func open(_ address: String) {
        var hash = address
        if let range = hash.range(of: "#") { hash = String(hash[range.upperBound...]) }
        let pieces = hash.split(separator: "?", maxSplits: 1).map(String.init)
        let parts = (pieces.first ?? "").split(separator: "/").map(String.init)
        let query = URLComponents(string: "?" + (pieces.count > 1 ? pieces[1] : ""))?.queryItems ?? []
        func param(_ name: String) -> String? { query.first { $0.name == name }?.value }

        switch parts.first ?? "" {
        case "", "home":
            showProfile = false
            tab = .home
        case "library", "saved":
            showProfile = false
            tab = .library
            library = param("reel").map { [.reel(id: $0)] } ?? []
        case "city" where parts.count > 1:
            push(.city(name: parts[1].removingPercentEncoding ?? parts[1]))
        case "place" where parts.count > 1:
            if parts.count > 2, parts[2] == "menu" { push(.menu(placeId: parts[1])) }
            else { push(.place(id: parts[1], tripId: param("trip"))) }
        case "trip" where parts.count > 1:
            if parts.count > 2, parts[2] == "bookings" { push(.web(hash: "#/trip/\(parts[1])/bookings")) }
            else { push(.trip(id: parts[1])) }
        case "editplace" where parts.count > 3:
            push(.editPlace(tripId: parts[1], editId: parts[2], entryId: parts[3]))
        case "folder" where parts.count > 1:
            push(.folder(id: parts[1]))
        case "map":
            showProfile = false
            push(.map)
        case "discover":
            showProfile = false
            tab = .discover
        case "bookings":
            showProfile = false
            tab = .bookings
        case "concierge":
            showProfile = false
            tab = .concierge
        case "profile", "settings":
            showProfile = true
        case "imports":
            push(.imports)
        case "signin":
            NotificationCenter.default.post(name: API.signedOut, object: nil)
        case "add":
            addRequest = AddRequest(text: param("url") ?? "")
        default:
            push(.web(hash: "#" + hash))
        }
    }
}
