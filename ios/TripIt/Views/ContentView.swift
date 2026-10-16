import SwiftUI

struct ContentView: View {
    var body: some View {
        TabView {
            TripsView()
                .tabItem { Label("Trips", systemImage: "suitcase.fill") }
            AllPlacesMapView()
                .tabItem { Label("Map", systemImage: "map.fill") }
            ImportsView()
                .tabItem { Label("Imports", systemImage: "square.and.arrow.down.fill") }
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape.fill") }
        }
    }
}
