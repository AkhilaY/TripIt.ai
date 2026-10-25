import Foundation
import Observation

enum AppTab: Hashable {
    case home, library, calendar, bookings, concierge
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
    /// One trip's bookings.
    case bookings(tripId: String)
    /// One of a trip's edits.
    case edit(tripId: String, editId: String)
    /// A trip day as you live it (today's, or the given day).
    case today(tripId: String, day: Int?)
    case packing(tripId: String)
    /// Events during a trip.
    case events(tripId: String)
    /// Everything dated: events, bookings, planned days and trips.
    case calendar
    /// Your travel taste: five questions that tailor edits, briefings and suggestions.
    case taste
    /// Owner only: everyone with an account, and AI spend.
    case people
    case usage
}

/// Which tab is showing and what's pushed on each, so links (from notifications and shared links) can open screens.
@MainActor
@Observable
final class Router {
    var tab: AppTab = .home
    var home: [Route] = []
    var library: [Route] = []
    var calendar: [Route] = []
    var bookings: [Route] = []
    var concierge: [Route] = []
    var showProfile = false
    var profilePath: [Route] = []
    /// Set to open the Add sheet, optionally with a link already filled in.
    var addRequest: AddRequest?
    /// Set to add or edit a booking.
    var bookingRequest: BookingRequest?

    struct BookingRequest: Identifiable {
        let id = UUID()
        var tripId: String?  // nil: the trip it most likely belongs to, which the person can change
        var booking: Booking?  // edit this one
        var fields: BookingFields?  // start the form filled in (a stay for nights with none, a table at a place)
        var title: String?
    }

    struct AddRequest: Identifiable {
        let id = UUID()
        var text: String = ""
        var tripId: String?
        var folderId: String?
        var city: String?  // search around this city (a city page)
    }

    func push(_ route: Route) {
        if showProfile { profilePath.append(route); return }
        switch tab {
        case .home: home.append(route)
        case .library: library.append(route)
        case .calendar: calendar.append(route)
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
            if parts.count > 2, parts[2] == "bookings" { push(.bookings(tripId: parts[1])) }
            else { push(.trip(id: parts[1])) }
        case "calendar", "discover":
            showProfile = false
            tab = .calendar
        case "taste":
            push(.taste)
        case "usage":
            push(.usage)
        case "today" where parts.count > 1:
            push(.today(tripId: parts[1], day: param("day").flatMap { Int($0) }))
        case "packing" where parts.count > 1:
            push(.packing(tripId: parts[1]))
        case "events" where parts.count > 1:
            push(.events(tripId: parts[1]))
        case "edit" where parts.count > 2:
            push(.edit(tripId: parts[1], editId: parts[2]))
        case "editplace" where parts.count > 3:
            push(.editPlace(tripId: parts[1], editId: parts[2], entryId: parts[3]))
        case "folder" where parts.count > 1:
            push(.folder(id: parts[1]))
        case "map":
            showProfile = false
            push(.map)
        case "bookings":
            if let trip = param("trip") { push(.bookings(tripId: trip)); break }
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
            addRequest = AddRequest(text: param("url") ?? "", tripId: param("trip"), folderId: param("folder"), city: param("city"))
        default:
            break  // an address the app doesn't have a screen for
        }
    }
}
