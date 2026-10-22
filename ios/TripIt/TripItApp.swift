import SwiftUI

/// TripIt for iPhone: the TripIt web app, full screen, plus what only a native app can do (the Share Extension).
@main
struct TripItApp: App {
    var body: some Scene {
        WindowGroup {
            TripItWebView(url: AppConfig.baseURL)
                .ignoresSafeArea()
                .background(Color("Background").ignoresSafeArea())
        }
    }
}
