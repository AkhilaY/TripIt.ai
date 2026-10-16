import SwiftUI

struct SettingsView: View {
    @State private var baseURL = AppConfig.apiBaseURL?.absoluteString ?? ""
    @State private var apiKey = AppConfig.apiKey
    @State private var testResult: String?
    @State private var testing = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://your-server.fly.dev", text: $baseURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("API key", text: $apiKey)
                } header: {
                    Text("Backend")
                } footer: {
                    Text("The TripIt server that downloads reels and asks Claude to find the places. Shared with the share extension.")
                }

                Section {
                    Button {
                        Task { await test() }
                    } label: {
                        HStack {
                            Text("Save & test connection")
                            Spacer()
                            if testing { ProgressView() }
                        }
                    }
                    if let testResult { Text(testResult).font(.callout) }
                }

                Section("Maps") {
                    LabeledContent("Google Maps app", value: MapsLauncher.hasGoogleMapsApp ? "Installed" : "Not installed — opens in browser")
                }
            }
            .navigationTitle("Settings")
        }
    }

    private func test() async {
        AppConfig.apiBaseURL = URL(string: baseURL.trimmingCharacters(in: .whitespaces))
        AppConfig.apiKey = apiKey
        testing = true
        defer { testing = false }
        do {
            try await APIClient(timeout: 10).health()
            testResult = "✅ Connected"
        } catch {
            testResult = "❌ \(error.localizedDescription)"
        }
    }
}
