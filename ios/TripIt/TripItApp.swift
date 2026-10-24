import SwiftUI

@main
struct TripItApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var session = Session()
    @State private var store = Store()

    init() {
        Monitoring.start()
        Theme.applyAppearance()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(session)
                .environment(store)
                .tint(Theme.gold)
        }
    }
}

/// Light, Dark, or the phone's setting (Profile → Appearance).
enum Appearance: String, CaseIterable, Identifiable {
    case system, light, dark
    static let key = "appearance"
    var id: String { rawValue }
    var label: String { self == .system ? "System" : self == .light ? "Light" : "Dark" }
    var scheme: ColorScheme? { self == .light ? .light : self == .dark ? .dark : nil }
}

struct RootView: View {
    @Environment(Session.self) private var session
    @Environment(Store.self) private var store
    @AppStorage(Appearance.key) private var appearance: Appearance = .system

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
        .preferredColorScheme(appearance.scheme)
        .task { await session.restore() }
        .onReceive(NotificationCenter.default.publisher(for: API.signedOut)) { _ in
            session.signOutLocally()
        }
        .onChange(of: session.phase) { _, phase in
            if phase != .signedIn { store.reset() }
        }
    }
}
