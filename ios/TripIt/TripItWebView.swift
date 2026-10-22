import SafariServices
import SwiftUI
import UIKit
import WebKit

/// Shows the web app. It keeps its own cookies (so you stay signed in), opens links to other sites in Safari,
/// and copies your session to the shared Keychain for the Share Extension.
struct TripItWebView: UIViewRepresentable {
    let url: URL

    func makeCoordinator() -> Coordinator { Coordinator(home: url) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.applicationNameForUserAgent = "TripItiOS/1.0"
        config.allowsInlineMediaPlayback = true
        // Lets the web app's service worker run (offline trips), for the domains listed in Info.plist.
        config.limitsNavigationsToAppBoundDomains = true

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.isOpaque = false
        webView.backgroundColor = UIColor(named: "Background")
        webView.scrollView.contentInsetAdjustmentBehavior = .never  // the page handles the notch itself
        webView.scrollView.bounces = true

        let refresh = UIRefreshControl()
        refresh.addTarget(context.coordinator, action: #selector(Coordinator.reload(_:)), for: .valueChanged)
        webView.scrollView.refreshControl = refresh

        context.coordinator.webView = webView
        config.websiteDataStore.httpCookieStore.add(context.coordinator)
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKHTTPCookieStoreObserver {
        let home: URL
        weak var webView: WKWebView?
        private var foregroundObserver: NSObjectProtocol?

        init(home: URL) {
            self.home = home
            super.init()
            foregroundObserver = NotificationCenter.default.addObserver(
                forName: UIApplication.willEnterForegroundNotification, object: nil, queue: .main
            ) { [weak self] _ in
                self?.syncSession()
            }
        }

        /// Signing in or out changes the cookie: keep the Share Extension's copy in step right away.
        func cookiesDidChange(in cookieStore: WKHTTPCookieStore) {
            syncSession()
        }

        deinit {
            if let foregroundObserver { NotificationCenter.default.removeObserver(foregroundObserver) }
        }

        @objc func reload(_ sender: UIRefreshControl) {
            webView?.reload()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { sender.endRefreshing() }
        }

        private func isOurs(_ url: URL) -> Bool {
            url.host == home.host && (url.scheme == "https" || url.scheme == "http")
        }

        /// Copies the sign-in cookie to the shared Keychain, or clears it after you sign out.
        func syncSession() {
            guard let store = webView?.configuration.websiteDataStore.httpCookieStore else { return }
            let host = home.host ?? ""
            store.getAllCookies { cookies in
                let session = cookies.first { $0.name == AppConfig.sessionCookie && host.hasSuffix($0.domain.trimmingCharacters(in: CharacterSet(charactersIn: "."))) }
                if let value = session?.value, !value.isEmpty {
                    SessionStore.save(value)
                } else {
                    SessionStore.clear()
                }
            }
        }

        // MARK: Navigation

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else { return decisionHandler(.cancel) }
            if url.scheme == "about" || url.scheme == "blob" || url.scheme == "data" {
                return decisionHandler(.allow)
            }
            if isOurs(url), action.targetFrame != nil, !url.path.hasSuffix(".ics") {
                return decisionHandler(.allow)
            }
            // Other sites, calendar files and tel:/maps links open outside the app.
            decisionHandler(.cancel)
            open(url)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            syncSession()
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            showOffline(in: webView, error: error)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            if (error as NSError).code != NSURLErrorCancelled { syncSession() }
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            webView.reload()
        }

        // MARK: Links that open a new window (target="_blank", window.open)

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = action.request.url {
                if isOurs(url), !url.path.hasSuffix(".ics") { webView.load(action.request) } else { open(url) }
            }
            return nil
        }

        private func open(_ url: URL) {
            if url.scheme == "https" || url.scheme == "http", !url.path.hasSuffix(".ics"),
               let top = Self.topViewController() {
                let safari = SFSafariViewController(url: url)
                safari.dismissButtonStyle = .close
                top.present(safari, animated: true)
            } else {
                UIApplication.shared.open(url)
            }
        }

        private static func topViewController() -> UIViewController? {
            let scene = UIApplication.shared.connectedScenes.first { $0.activationState == .foregroundActive } as? UIWindowScene
            var top = scene?.windows.first { $0.isKeyWindow }?.rootViewController
            while let presented = top?.presentedViewController { top = presented }
            return top
        }

        private func showOffline(in webView: WKWebView, error: Error) {
            let code = (error as NSError).code
            guard code != NSURLErrorCancelled else { return }
            let html = """
            <html><head><meta name="viewport" content="width=device-width, initial-scale=1">
            <style>body{font:17px -apple-system,system-ui;background:#F1EBE2;color:#2B2019;display:flex;align-items:center;
            justify-content:center;height:100vh;margin:0;text-align:center}@media(prefers-color-scheme:dark){body{background:#15100C;color:#F0E7DA}}
            a{display:inline-block;margin-top:18px;padding:12px 22px;border-radius:24px;background:#2B2019;color:#F1EBE2;text-decoration:none}
            @media(prefers-color-scheme:dark){a{background:#F0E7DA;color:#15100C}}</style></head>
            <body><div><h2>Can't reach TripIt</h2><p>Check your connection and try again.</p>
            <a href="\(home.absoluteString)">Try again</a></div></body></html>
            """
            webView.loadHTMLString(html, baseURL: home)
        }
    }
}
