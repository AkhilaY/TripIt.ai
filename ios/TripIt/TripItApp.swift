import SwiftUI

@main
struct TripItApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var session = Session()
    @State private var store = Store()

    init() {
        Theme.applyAppearance()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(session)
                .environment(store)
                .tint(Theme.accent)
        }
    }
}

struct RootView: View {
    @Environment(Session.self) private var session
    @Environment(Store.self) private var store

    var body: some View {
        Group {
            switch session.phase {
            case .checking:
                ZStack { Theme.background.ignoresSafeArea(); ProgressView() }
            case .signedOut:
                SignInView()
            case .signedIn:
                MainTabs()
            }
        }
        .task { await session.restore() }
        .onReceive(NotificationCenter.default.publisher(for: API.signedOut)) { _ in
            session.signOutLocally()
        }
        .onChange(of: session.phase) { _, phase in
            if phase != .signedIn { store.reset() }
        }
    }
}
