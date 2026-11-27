import SwiftUI
import UserNotifications

/// Your account and settings (opened from the person button at the top right).
struct ProfileView: View {
    @Environment(Session.self) private var session
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var paywall: PaywallRequest?
    @State private var home: HomeSetting?
    @State private var editingHome = false
    @State private var editingName = false
    @State private var nameText = ""
    @State private var homeText = ""
    @State private var notifications: UNAuthorizationStatus = .notDetermined
    @State private var changingPassword = false
    @State private var deleting = false
    @State private var confirmSignOut = false
    @State private var sendingFeedback = false
    @AppStorage(Appearance.key) private var appearance: Appearance = .light

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 30) {
                if let me = session.me { identity(me) }
                group("You") {
                    Button { homeText = home?.city ?? ""; editingHome = true } label: {
                        row("house", "Home city", home.map { [$0.city, $0.country].filter { !$0.isEmpty }.joined(separator: ", ") } ?? "Discover looks here first")
                    }
                    divider
                    NavigationLink(value: Route.imports) {
                        row("tray.full", "Imports", store.jobs.contains(where: \.isActive) ? "Working on a post…" : "Posts you've shared and their status", chevron: true)
                    }
                    divider
                    NavigationLink(value: Route.taste) {
                        row("sparkles", "Your travel taste", "Tailors your edits, briefings and concierge", chevron: true)
                    }
                }
                if let plan = store.plan, session.me?.isAdmin != true {
                    group("Plan") {
                        Button { paywall = PaywallRequest() } label: {
                            row("infinity", plan.isPlus ? "Travel Edit Plus" : "Free plan", planLine(plan), chevron: true)
                        }
                    }
                }
                VStack(alignment: .leading, spacing: 12) {
                    Text("Appearance").font(Theme.serif(19)).foregroundStyle(Theme.label)
                    HStack(spacing: 8) {
                        ForEach(Appearance.allCases) { option in
                            let on = appearance == option
                            Button { withAnimation(.easeOut(duration: 0.2)) { appearance = option } } label: {
                                Text(option.label)
                                    .font(Theme.text(.subheadline, weight: on ? .medium : .regular))
                                    .foregroundStyle(on ? Theme.accentInk : Theme.label)
                                    .frame(maxWidth: .infinity, minHeight: 40)
                                    .background(on ? Theme.accent : Color.clear, in: Capsule())
                                    .overlay(Capsule().strokeBorder(on ? Color.clear : Theme.chipBorder))
                                    .contentShape(Capsule())
                            }
                            .buttonStyle(PressStyle())
                            .accessibilityAddTraits(on ? .isSelected : [])
                        }
                    }
                }
                group("Notifications", footer: notifications == .denied
                      ? "Notifications are off for Travel Edit. Turn them on in Settings → Notifications → Travel Edit." : nil) {
                    HStack(spacing: 14) {
                        icon("bell")
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Import notifications").font(Theme.text(.body)).foregroundStyle(Theme.label)
                            Text("When a shared post's places are saved").font(Theme.text(.caption)).foregroundStyle(Theme.secondary)
                        }
                        Spacer(minLength: 8)
                        Toggle("Import notifications", isOn: Binding(get: { notifications == .authorized }, set: { on in
                            Task {
                                if on, notifications != .denied {
                                    _ = await Push.shared.enable()
                                } else {
                                    Links.open(URL(string: UIApplication.openSettingsURLString))
                                }
                                notifications = await Push.shared.status()
                            }
                        }))
                        .labelsHidden()
                        .tint(Theme.ok)
                    }
                    .padding(.horizontal, 16).padding(.vertical, 12)
                }
                group("Account") {
                    if session.me?.hasPassword != false {
                        Button { changingPassword = true } label: { row("lock", "Change password", nil) }
                        divider
                    }
                    if session.me?.isAdmin == true {
                        NavigationLink(value: Route.people) {
                            row("person.2", "People", "Everyone with an account; reset a forgotten password", chevron: true)
                        }
                        divider
                        NavigationLink(value: Route.usage) {
                            row("chart.bar", "Usage & costs", "AI spend, cost per save, budgets and limits", chevron: true)
                        }
                        divider
                    }
                    Button { sendingFeedback = true } label: {
                        row("bubble.left", "Send feedback", "Something broken, confusing or missing? Tell us")
                    }
                    divider
                    Button { confirmSignOut = true } label: { row("rectangle.portrait.and.arrow.right", "Sign out", nil) }
                }
                group("About") {
                    Link(destination: AppConfig.baseURL.appendingPathComponent("support")) { row("questionmark.circle", "Help & support", nil, chevron: true) }
                    divider
                    Link(destination: AppConfig.baseURL.appendingPathComponent("privacy")) { row("hand.raised", "Privacy Policy", nil, chevron: true) }
                    divider
                    Link(destination: AppConfig.baseURL.appendingPathComponent("terms")) { row("doc.text", "Terms of Use", nil, chevron: true) }
                }
                VStack(alignment: .leading, spacing: 10) {
                    Button("Delete account") { deleting = true }
                        .font(Theme.text(.subheadline)).foregroundStyle(Theme.danger)
                        .frame(minHeight: 36)
                    Text("The Travel Edit \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "")")
                        .font(Theme.text(.caption)).foregroundStyle(Theme.tertiary)
                }
            }
            .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 40)
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle("Profile")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        .task {
            notifications = await Push.shared.status()
            home = try? await API.shared.get("/v1/home", as: HomeSetting?.self)
        }
        .sheet(item: $paywall) { PaywallView(request: $0).environment(store) }
        .alert("Your name", isPresented: $editingName) {
            TextField("First name", text: $nameText).textContentType(.givenName)
            Button("Cancel", role: .cancel) {}
            Button("Save") { Task { do { try await session.setName(nameText) } catch { store.fail(error) } } }
        } message: {
            Text("For your greeting, and how friends see you on a trip you plan together.")
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
        .sheet(isPresented: $sendingFeedback) { FeedbackSheet().environment(store) }
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

    private func planLine(_ plan: PlanInfo) -> String {
        guard let left = plan.savesLeft else { return plan.renewsDay.map { "Unlimited video saves · Renews \($0)" } ?? "Unlimited video saves" }
        return (left == 1 ? "1 video save left" : "\(left) video saves left") + " this month · Upgrade to Plus"
    }

    // MARK: Pieces

    /// Your initial, name and email; tap to change your name.
    private func identity(_ me: Me) -> some View {
        Button { nameText = me.name; editingName = true } label: {
            HStack(spacing: 16) {
                Text(String((me.name.isEmpty ? me.email : me.name).prefix(1)).uppercased())
                    .font(Theme.serif(28)).foregroundStyle(Theme.accentInk)
                    .frame(width: 64, height: 64)
                    .background(Theme.accent, in: Circle())
                VStack(alignment: .leading, spacing: 3) {
                    Text(me.name.isEmpty ? "Add your name" : me.name).font(Theme.serif(26)).foregroundStyle(Theme.label)
                    Text(me.email.isEmpty ? "Signed in with Apple" : me.email).font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
                }
                Spacer(minLength: 8)
                Text("Edit").font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(PressStyle())
        .accessibilityHint("Change your name")
        .padding(.top, 8)
    }

    /// A titled card of rows, as elsewhere in the app.
    private func group<Content: View>(_ title: String, footer: String? = nil, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(Theme.serif(19)).foregroundStyle(Theme.label)
            VStack(spacing: 0) { content() }
                .buttonStyle(PressStyle())
                .background(Theme.cell, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            if let footer {
                Text(footer).font(Theme.text(.caption)).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var divider: some View { Divider().overlay(Theme.border).padding(.leading, 54) }

    private func icon(_ symbol: String) -> some View {
        Image(systemName: symbol).font(.system(size: 17, weight: .light)).foregroundStyle(Theme.label).frame(width: 24)
    }

    private func row(_ symbol: String, _ title: String, _ subtitle: String?, chevron: Bool = false) -> some View {
        HStack(spacing: 14) {
            icon(symbol)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(Theme.text(.body)).foregroundStyle(Theme.label)
                if let subtitle { Text(subtitle).font(Theme.text(.caption)).foregroundStyle(Theme.secondary).multilineTextAlignment(.leading) }
            }
            Spacer(minLength: 8)
            if chevron { Image(systemName: "chevron.right").font(.system(size: 12, weight: .regular)).foregroundStyle(Theme.tertiary) }
        }
        .padding(.horizontal, 16).padding(.vertical, 13)
        .contentShape(Rectangle())
    }
}

/// Profile → Send feedback: goes to the team with your email, so they can reply.
private struct FeedbackSheet: View {
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var message = ""
    @State private var busy = false
    @State private var error: String?
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("What's working, what's broken, what you wish it did…", text: $message, axis: .vertical)
                        .lineLimit(6...14)
                        .focused($focused)
                } footer: {
                    Text("Goes straight to the team with your email, so we can reply.")
                }
                if let error { Text(error).foregroundStyle(Theme.danger) }
            }
            .tripBackground()
            .navigationTitle("Send feedback")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else {
                        Button("Send") { Task { await send() } }
                            .disabled(message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
            }
            .onAppear { focused = true }
        }
        .presentationDetents([.medium, .large])
    }

    private func send() async {
        busy = true
        let info = Bundle.main.infoDictionary ?? [:]
        let version = "\(info["CFBundleShortVersionString"] as? String ?? "") (\(info["CFBundleVersion"] as? String ?? ""))"
        do {
            try await API.shared.call("POST", "/v1/feedback", ["message": message, "screen": "Profile", "version": version, "platform": "ios"])
            store.show("Thanks! Your feedback was sent")
            dismiss()
        } catch { self.error = error.localizedDescription }
        busy = false
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
    private var usesPassword: Bool { session.me?.hasPassword != false }  // Sign in with Apple accounts confirm by typing DELETE

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if usesPassword {
                        SecureField("Your password", text: $password).textContentType(.password)
                    } else {
                        TextField("Type DELETE to confirm", text: $password).textInputAutocapitalization(.characters).autocorrectionDisabled()
                    }
                } footer: {
                    Text("This deletes your account and everything in it: saved places, folders, trips, bookings and photos. It can't be undone.")
                }
                if let error { Text(error).foregroundStyle(Theme.danger) }
                Section {
                    Button(role: .destructive) {
                        busy = true
                        Task {
                            do {
                                try await API.shared.call("DELETE", "/v1/me", usesPassword ? ["password": password] : ["confirm": password])
                                session.signOutLocally()
                            } catch { self.error = error.localizedDescription }
                            busy = false
                        }
                    } label: {
                        if busy { ProgressView() } else { Text("Delete my account").frame(maxWidth: .infinity) }
                    }
                    .disabled(busy || (usesPassword ? password.isEmpty : password.trimmingCharacters(in: .whitespaces).lowercased() != "delete"))
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
