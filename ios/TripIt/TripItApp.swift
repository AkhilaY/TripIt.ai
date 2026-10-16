import SwiftData
import SwiftUI

@main
struct TripItApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @State private var importer = ImportCoordinator()

    let container: ModelContainer = {
        let schema = Schema([Trip.self, Place.self, ReelSource.self])
        // Syncs through the iCloud container in the entitlements; falls back to local-only storage
        // (e.g. when signed out of iCloud or running without the iCloud capability).
        do {
            return try ModelContainer(for: schema, configurations: ModelConfiguration(cloudKitDatabase: .automatic))
        } catch {
            print("CloudKit store unavailable, using local store: \(error)")
            return try! ModelContainer(for: schema, configurations: ModelConfiguration(cloudKitDatabase: .none))
        }
    }()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(importer)
                .onAppear {
                    importer.attach(container.mainContext)
                    importer.start()
                }
        }
        .modelContainer(container)
        .onChange(of: scenePhase) { _, phase in
            switch phase {
            case .active: importer.start()
            case .background: importer.stop()
            default: break
            }
        }
    }
}
