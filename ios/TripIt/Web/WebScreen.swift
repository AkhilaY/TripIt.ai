import SafariServices
import SwiftUI
import UIKit
import WebKit

/// The web app's cookies for the embedded screens: they sign in with the same session as the native app.
enum WebSession {
    static func prepare() async {
        guard let token = SessionStore.token, let host = AppConfig.baseURL.host else { return }
        var props: [HTTPCookiePropertyKey: Any] = [
            .name: AppConfig.sessionCookie, .value: token, .domain: host, .path: "/",
            .expires: Date().addingTimeInterval(90 * 86400),
        ]
        if AppConfig.baseURL.scheme == "https" { props[.secure] = "TRUE" }
        guard let cookie = HTTPCookie(properties: props) else { return }
        await WKWebsiteDataStore.default().httpCookieStore.setCookie(cookie)
    }

    @MainActor
    static func clearCookies() {
        WKWebsiteDataStore.default().removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), modifiedSince: .distantPast) {}
    }
}

/// One screen of the web app (Discover, Bookings, Concierge, Calendar, Edits…) inside the native app.
/// The page hides its own tab bar; links to screens the app has natively open them natively instead.
struct WebScreen: View {
    let hash: String
    /// The first screen of a tab has nowhere to go back to.
    var isRoot = false

    @Environment(Router.self) private var router
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var ready = false
    @State private var failed = false
    @State private var reloadToken = 0

    var body: some View {
        ZStack {
            Theme.background.ignoresSafeArea()
            if ready {
                WebView(hash: hash, reloadToken: reloadToken, failed: $failed) { message in
                    handle(message)
                }
            }
            if failed {
                EmptyState(symbol: "wifi.slash", color: Theme.gray, title: "Can't reach TripIt",
                           text: "Check your connection and try again.") {
                    Button("Try again") { failed = false; reloadToken += 1 }
                        .buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 200)
                }
                .background(Theme.background)
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .task {
            await WebSession.prepare()
            ready = true
        }
    }

    private func handle(_ message: [String: Any]) {
        if let address = message["open"] as? String {
            router.open(address)
        } else if message["back"] != nil {
            if !isRoot { dismiss() }
        } else if let path = message["changed"] as? String {
            Task { await refresh(after: path) }
        }
    }

    /// Something changed on a web screen: refresh the native copy of what it touched.
    private func refresh(after path: String) async {
        let parts = path.split(separator: "/").map(String.init)
        if parts.count > 2, parts[1] == "trips", store.tripDetails[parts[2]] != nil {
            _ = try? await store.loadTrip(parts[2])
        }
        await store.reloadPlaces()
        await store.reloadTrips()
    }
}

private struct WebView: UIViewRepresentable {
    let hash: String
    let reloadToken: Int
    @Binding var failed: Bool
    let onMessage: ([String: Any]) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.applicationNameForUserAgent = "TripItiOS/2.0"
        config.allowsInlineMediaPlayback = true
        config.limitsNavigationsToAppBoundDomains = true  // lets the web app's service worker run
        config.userContentController.add(WeakHandler(context.coordinator), name: "tripit")

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.isOpaque = false
        webView.backgroundColor = UIColor(Theme.background)
        webView.scrollView.backgroundColor = UIColor(Theme.background)
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        #if DEBUG
        if #available(iOS 16.4, *) { webView.isInspectable = true }
        #endif
        context.coordinator.load(webView)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.parent = self
        if context.coordinator.loadedToken != reloadToken { context.coordinator.load(webView) }
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "tripit")
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
        var parent: WebView
        var loadedToken = -1
        private let home = AppConfig.baseURL

        init(_ parent: WebView) { self.parent = parent }

        func load(_ webView: WKWebView) {
            loadedToken = parent.reloadToken
            var c = URLComponents(url: home, resolvingAgainstBaseURL: false)!
            c.path = "/"
            c.queryItems = [URLQueryItem(name: "embed", value: "1")]
            let hash = parent.hash.hasPrefix("#") ? String(parent.hash.dropFirst()) : parent.hash
            c.fragment = hash
            if let url = c.url { webView.load(URLRequest(url: url)) }
        }

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            if let body = message.body as? [String: Any] { parent.onMessage(body) }
        }

        private func isOurs(_ url: URL) -> Bool {
            url.host == home.host && (url.scheme == "https" || url.scheme == "http")
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else { return decisionHandler(.cancel) }
            if ["about", "blob", "data"].contains(url.scheme ?? "") { return decisionHandler(.allow) }
            if isOurs(url), action.targetFrame != nil, !url.path.hasSuffix(".ics") { return decisionHandler(.allow) }
            decisionHandler(.cancel)
            Self.openOutside(url)
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = action.request.url { Self.openOutside(url) }
            return nil
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.failed = false
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            if (error as NSError).code != NSURLErrorCancelled { parent.failed = true }
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            webView.reload()
        }

        /// Other websites open in an in-app Safari sheet; calendar files, phone numbers and maps go to their apps.
        static func openOutside(_ url: URL) {
            if url.scheme == "https" || url.scheme == "http", !url.path.hasSuffix(".ics"), !Links.opensApp(url) {
                Links.presentSafari(url)
            } else {
                UIApplication.shared.open(url)
            }
        }
    }
}

/// WKUserContentController keeps its handlers alive; this keeps it from keeping the screen alive too.
@MainActor
private final class WeakHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?
    init(_ target: WKScriptMessageHandler) { self.target = target }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(controller, didReceive: message)
    }
}

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
