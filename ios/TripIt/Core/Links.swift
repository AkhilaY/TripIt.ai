import SafariServices
import SwiftUI
import UIKit

/// Opening links outside the app.
@MainActor
enum Links {
    /// Maps links open the Maps apps rather than a web page.
    static func opensApp(_ url: URL) -> Bool {
        let host = url.host ?? ""
        if host == "maps.apple.com" || host.hasSuffix("maps.apple") { return true }
        if host == "maps.app.goo.gl" || host == "maps.google.com" { return true }
        return host.hasSuffix("google.com") && url.path.hasPrefix("/maps")
    }

    static func presentSafari(_ url: URL) {
        guard let top = topViewController() else { UIApplication.shared.open(url); return }
        let safari = SFSafariViewController(url: url)
        safari.dismissButtonStyle = .close
        safari.preferredControlTintColor = UIColor(Theme.accent)
        top.present(safari, animated: true)
    }

    /// Opens a link: maps and phone numbers in their apps, websites in an in-app Safari sheet.
    static func open(_ url: URL?) {
        guard let url else { return }
        if (url.scheme == "https" || url.scheme == "http") && !opensApp(url) { presentSafari(url) }
        else { UIApplication.shared.open(url) }
    }

    static func topViewController() -> UIViewController? {
        let scene = UIApplication.shared.connectedScenes.first { $0.activationState == .foregroundActive } as? UIWindowScene
        var top = scene?.windows.first { $0.isKeyWindow }?.rootViewController
        while let presented = top?.presentedViewController { top = presented }
        return top
    }
}
