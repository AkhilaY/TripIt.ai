import Foundation

/// Settings shared by the app and the Share Extension, read from Info.plist (filled from Config/Secrets.xcconfig).
enum AppConfig {
    static let appGroupID: String = bundled("AppGroupID") ?? ""

    /// Where TripIt runs, e.g. https://my-tripit.fly.dev
    static var baseURL: URL {
        URL(string: (bundled("TripItAPIBaseURL") ?? "").trimmingCharacters(in: .whitespaces))
            ?? URL(string: "https://my-tripit.fly.dev")!
    }

    /// The web app's sign-in cookie. The app copies it to the shared Keychain so the Share Extension can use it.
    static let sessionCookie = "tripit_session"

    private static func bundled(_ key: String) -> String? {
        guard let value = Bundle.main.object(forInfoDictionaryKey: key) as? String,
              !value.isEmpty, !value.hasPrefix("$(") else { return nil }
        return value
    }
}
