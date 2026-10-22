import UIKit
import UserNotifications

/// Native notifications ("3 new places saved in Lisbon") through Apple's push service.
/// The device token goes to the server, which sends a notification when an import finishes.
@MainActor
final class Push: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Push()
    /// Posted with the notification's link (e.g. "/#/trip/abc") when you tap one.
    static let opened = Notification.Name("TripItNotificationOpened")
    private static let tokenKey = "tripit.apnsToken"

    private var token: String? {
        get { UserDefaults.standard.string(forKey: Self.tokenKey) }
        set { UserDefaults.standard.set(newValue, forKey: Self.tokenKey) }
    }

    func status() async -> UNAuthorizationStatus {
        await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    /// Asks for permission (the first time) and registers this phone.
    func enable() async -> Bool {
        let granted = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        if granted { UIApplication.shared.registerForRemoteNotifications() }
        return granted
    }

    /// On launch: re-register if notifications are already allowed (tokens can change).
    func registerIfAllowed() async {
        UNUserNotificationCenter.current().delegate = self
        if await status() == .authorized { UIApplication.shared.registerForRemoteNotifications() }
    }

    func didRegister(_ deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        token = hex
        #if DEBUG
        let environment = "sandbox"  // builds run from Xcode use Apple's development push service
        #else
        let environment = "production"
        #endif
        Task { try? await API.shared.call("POST", "/v1/push/apns", ["token": hex, "environment": environment]) }
    }

    /// Signing out: stop this phone getting the account's notifications.
    func unregister() async {
        guard let token else { return }
        try? await API.shared.call("DELETE", "/v1/push/apns/\(token)")
        self.token = nil
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async
        -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        let url = response.notification.request.content.userInfo["url"] as? String
        await MainActor.run {
            if let url { NotificationCenter.default.post(name: Push.opened, object: url) }
        }
    }
}

@MainActor
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = Push.shared
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Push.shared.didRegister(deviceToken)
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        #if DEBUG
        print("Push registration failed: \(error)")
        #endif
    }
}
