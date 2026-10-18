import Foundation

/// Settings shared between the app and the Share Extension through the App Group.
enum AppConfig {
    static let appGroupID: String = Bundle.main.object(forInfoDictionaryKey: "AppGroupID") as? String ?? ""

    static var sharedDefaults: UserDefaults {
        UserDefaults(suiteName: appGroupID) ?? .standard
    }

    private enum Keys {
        static let baseURL = "apiBaseURL"
        static let apiKey = "apiKey"
    }

    /// Backend URL: the value set in Settings, falling back to the one baked in at build time.
    static var apiBaseURL: URL? {
        get {
            let stored = sharedDefaults.string(forKey: Keys.baseURL)
            let raw = (stored?.isEmpty == false ? stored : bundled("TripItAPIBaseURL")) ?? ""
            return URL(string: raw.trimmingCharacters(in: .whitespaces))
        }
        set { sharedDefaults.set(newValue?.absoluteString, forKey: Keys.baseURL) }
    }

    static var apiKey: String {
        get {
            let stored = sharedDefaults.string(forKey: Keys.apiKey)
            return (stored?.isEmpty == false ? stored : bundled("TripItAPIKey")) ?? ""
        }
        set { sharedDefaults.set(newValue, forKey: Keys.apiKey) }
    }

    private static func bundled(_ key: String) -> String? {
        guard let value = Bundle.main.object(forInfoDictionaryKey: key) as? String,
              !value.isEmpty, !value.hasPrefix("$(") else { return nil }
        return value
    }
}
