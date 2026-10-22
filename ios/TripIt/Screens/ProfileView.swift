import SwiftUI
import UserNotifications

/// Your account and settings (opened from the person button at the top right).
struct ProfileView: View {
    @Environment(Session.self) private var session
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var home: HomeSetting?
    @State private var editingHome = false
    @State private var homeText = ""
    @State private var notifications: UNAuthorizationStatus = .notDetermined
    @State private var changingPassword = false
    @State private var deleting = false
    @State private var confirmSignOut = false

    var body: some View {
        List {
            if let me = session.me {
                Section {
                    HStack(spacing: 14) {
                        Text(String((me.name.isEmpty ? me.email : me.name).prefix(1)).uppercased())
                            .font(Theme.serif(26)).foregroundStyle(Theme.accentInk)
                            .frame(width: 56, height: 56)
                            .background(Theme.accent, in: Circle())
                        VStack(alignment: .leading, spacing: 2) {
                            Text(me.name.isEmpty ? "Your account" : me.name).font(Theme.serif(22))
                            Text(me.email).font(.subheadline).foregroundStyle(Theme.secondary)
                        }
                    }
                    .listRowBackground(Color.clear)
                }
            }
            Section("You") {
                Button { homeText = home?.city ?? ""; editingHome = true } label: {
                    row("house.fill", Theme.green, "Home city", home.map { [$0.city, $0.country].filter { !$0.isEmpty }.joined(separator: ", ") } ?? "Discover looks here first")
                }
                NavigationLink(value: Route.imports) {
                    row("tray.full.fill", Theme.blue, "Imports",
                        store.jobs.contains(where: \.isActive) ? "Working on a post…" : "Posts you've shared and their status", chevron: false)
                }
                NavigationLink(value: Route.web(hash: "#/taste")) {
                    row("sparkles", Theme.gold, "Your travel taste", "Tailors your edits, briefings and concierge", chevron: false)
                }
            }
            Section {
                Toggle(isOn: Binding(get: { notifications == .authorized }, set: { on in
                    Task {
                        if on {
                            if notifications == .denied {
                                Links.open(URL(string: UIApplication.openSettingsURLString))
                            } else {
                                _ = await Push.shared.enable()
                            }
                        } else {
                            Links.open(URL(string: UIApplication.openSettingsURLString))
                        }
                        notifications = await Push.shared.status()
                    }
                })) {
                    row("bell.fill", Theme.red, "Import notifications", "When a shared post's places are saved")
                }
            } header: {
                Text("Notifications")
            } footer: {
                if notifications == .denied { Text("Notifications are off for Travel Edit. Turn them on in Settings → Notifications → Travel Edit.") }
            }
            Section("Account") {
                Button { changingPassword = true } label: { row("lock.fill", Theme.gray, "Change password", nil) }
                if session.me?.isAdmin == true {
                    NavigationLink(value: Route.web(hash: "#/profile")) {
                        row("person.2.fill", Theme.indigo, "Invites and people", "Invite testers; reset a forgotten password", chevron: false)
                    }
                }
                Button { confirmSignOut = true } label: {
                    row("rectangle.portrait.and.arrow.right", Theme.danger, "Sign out", nil)
                }
            }
            Section {
                Button("Delete account", role: .destructive) { deleting = true }
            } footer: {
                Text("The Travel Edit \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "") · \(AppConfig.baseURL.host ?? "")")
            }
        }
        .tripBackground()
        .navigationTitle("Profile")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        .task {
            notifications = await Push.shared.status()
            home = try? await API.shared.get("/v1/home", as: HomeSetting?.self)
        }
        .alert("Home city", isPresented: $editingHome) {
            TextField("e.g. Brooklyn, New York", text: $homeText)
            Button("Cancel", role: .cancel) {}
            Button("Save") { Task { await saveHome() } }
        } message: {
            Text("Discover shows places around here, and places you save here go in a collection near home.")
        }
        .confirmationDialog("Sign out of The Travel Edit on this phone?", isPresented: $confirmSignOut, titleVisibility: .visible) {
            Button("Sign out", role: .destructive) { Task { dismiss(); await session.signOut() } }
        }
        .sheet(isPresented: $changingPassword) { PasswordSheet().environment(store) }
        .sheet(isPresented: $deleting) { DeleteAccountSheet().environment(session) }
    }

    private func saveHome() async {
        let city = homeText.trimmingCharacters(in: .whitespaces)
        do {
            if city.isEmpty {
                try await API.shared.call("DELETE", "/v1/home")
                home = nil
            } else {
                home = try await API.shared.put("/v1/home", ["city": city])
                store.show("Home set to \(home?.city ?? city)")
            }
        } catch { store.fail(error) }
    }

    private func row(_ symbol: String, _ color: Color, _ title: String, _ subtitle: String?, chevron: Bool = false) -> some View {
        HStack(spacing: 12) {
            SymbolTile(symbol: symbol, color: color)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).foregroundStyle(Theme.label)
                if let subtitle { Text(subtitle).font(.caption).foregroundStyle(Theme.secondary) }
            }
        }
    }
}

private struct PasswordSheet: View {
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var current = ""
    @State private var new = ""
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        NavigationStack {
            Form {
                SecureField("Current password", text: $current).textContentType(.password)
                SecureField("New password (at least 8 characters)", text: $new).textContentType(.newPassword)
                if let error { Text(error).foregroundStyle(Theme.danger) }
            }
            .tripBackground()
            .navigationTitle("Change password")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else {
                        Button("Save") {
                            busy = true
                            Task {
                                do {
                                    try await API.shared.call("POST", "/v1/me/password", ["current": current, "new": new])
                                    store.show("Password changed")
                                    dismiss()
                                } catch { self.error = error.localizedDescription }
                                busy = false
                            }
                        }
                        .disabled(current.isEmpty || new.count < 8)
                    }
                }
            }
        }
        .presentationDetents([.medium])
    }
}

private struct DeleteAccountSheet: View {
    @Environment(Session.self) private var session
    @Environment(\.dismiss) private var dismiss
    @State private var password = ""
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    SecureField("Your password", text: $password).textContentType(.password)
                } footer: {
                    Text("This deletes your account and everything in it: saved places, folders, trips, bookings and photos. It can't be undone.")
                }
                if let error { Text(error).foregroundStyle(Theme.danger) }
                Section {
                    Button(role: .destructive) {
                        busy = true
                        Task {
                            do {
                                try await API.shared.call("DELETE", "/v1/me", ["password": password])
                                session.signOutLocally()
                            } catch { self.error = error.localizedDescription }
                            busy = false
                        }
                    } label: {
                        if busy { ProgressView() } else { Text("Delete my account").frame(maxWidth: .infinity) }
                    }
                    .disabled(password.isEmpty || busy)
                }
            }
            .tripBackground()
            .navigationTitle("Delete account")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
        .presentationDetents([.medium])
    }
}

/// Posts and screenshots you've shared, and how each import went.
struct ImportsView: View {
    @Environment(Store.self) private var store

    var body: some View {
        List {
            if store.jobs.isEmpty {
                EmptyState(symbol: "tray", title: "Nothing shared yet",
                           text: "Share a TikTok, Instagram or YouTube post to Travel Edit from the share sheet, and the places in it are saved for you.")
                    .listRowBackground(Color.clear)
            }
            ForEach(store.jobs) { job in
                if job.status == "done", let tripId = job.tripId {
                    NavigationLink(value: Route.trip(id: tripId)) { JobRow(job: job) }
                } else if job.status == "done", let reelId = job.reelId {
                    NavigationLink(value: Route.reel(id: reelId)) { JobRow(job: job) }
                } else {
                    JobRow(job: job)
                }
            }
        }
        .tripBackground()
        .navigationTitle("Imports")
        .refreshable { await store.refresh() }
    }
}

/// The places saved from one post.
struct ReelPlacesView: View {
    let reelId: String
    @Environment(Store.self) private var store

    var body: some View {
        let places = store.places.filter { $0.reelIds.contains(reelId) }
        List {
            if places.isEmpty {
                Text("No places from this post are saved.").foregroundStyle(Theme.secondary)
            }
            ForEach(places) { place in
                NavigationLink(value: Route.place(id: place.id, tripId: nil)) { PlaceRow(place: place) }
            }
        }
        .tripBackground()
        .navigationTitle(Fmt.plural(places.count, "place") + " from one post")
        .navigationBarTitleDisplayMode(.inline)
    }
}
