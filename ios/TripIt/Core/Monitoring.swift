import Foundation
import Sentry

/// Crash and error reporting with Sentry, when the build has a DSN (SENTRY_DSN_IOS). Only the account id is
/// attached, never emails or what people have saved.
enum Monitoring {
    private(set) static var enabled = false

    static func start() {
        guard let dsn = Bundle.main.object(forInfoDictionaryKey: "SentryDSN") as? String,
              dsn.hasPrefix("https://") else { return }
        SentrySDK.start { options in
            options.dsn = dsn
            #if DEBUG
            options.environment = "debug"
            #else
            options.environment = "production"
            #endif
            options.sendDefaultPii = false
        }
        enabled = true
    }

    static func setUser(_ id: String?) {
        guard enabled else { return }
        SentrySDK.setUser(id.map { User(userId: $0) })
    }

    /// Something went wrong that the app handled (a response it couldn't read, for example).
    static func report(_ message: String) {
        guard enabled else { return }
        SentrySDK.capture(message: message)
    }
}
