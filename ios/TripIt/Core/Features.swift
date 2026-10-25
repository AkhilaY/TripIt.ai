import Foundation

/// Features switched off on the server (FEATURES_OFF), hidden in the app. Until the server answers, the first App
/// Store version's list is assumed so nothing appears and then vanishes.
enum Features {
    nonisolated(unsafe) static var off: Set<String> = ["events", "concierge", "menus", "lounges", "calendar", "chatgpt", "booking_needs"]

    static func isOn(_ name: String) -> Bool { !off.contains(name) }

    private struct Answer: Decodable { var off: [String] }

    static func refresh() async {
        if let answer: Answer = try? await API.shared.get("/v1/features") { off = Set(answer.off) }
    }
}

extension Place {
    /// Whether to book ahead, when that check is switched on.
    var shownNeed: String? { Features.isOn("booking_needs") ? bookingNeed : nil }
}
