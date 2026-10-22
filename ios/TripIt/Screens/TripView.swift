import SwiftUI

/// A trip: its places, the day-by-day plan, and a map. Bookings, packing, events and edits open from here.
struct TripView: View {
    let tripId: String
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var mode = "places"
    @State private var loadError: String?
    @State private var sheet: TripSheet?
    @State private var librarySheet: LibrarySheet?
    @State private var confirmDelete = false
    @State private var editMode: EditMode = .inactive
    @State private var working: String?

    var body: some View {
        Group {
            if let trip = store.tripDetails[tripId] {
                content(trip)
            } else if let loadError {
                EmptyState(symbol: "airplane", title: "Couldn't open this trip", text: loadError) {
                    Button("Try again") { Task { await load() } }.buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 200)
                }
                .frame(maxHeight: .infinity)
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Theme.background.ignoresSafeArea())
        .task { await load() }
    }

    private func load() async {
        do {
            loadError = nil
            _ = try await store.loadTrip(tripId)
        } catch {
            if store.tripDetails[tripId] == nil { loadError = error.localizedDescription }
        }
    }

    private func modes(_ trip: TripDetail) -> [String] {
        trip.isLocal ? ["places", "map"] : ["places", "plan", "map"]
    }

    @ViewBuilder private func content(_ trip: TripDetail) -> some View {
        VStack(spacing: 0) {
            Picker("View", selection: $mode) {
                ForEach(modes(trip), id: \.self) { Text($0.capitalized).tag($0) }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 16).padding(.vertical, 8)
            switch mode {
            case "plan": TripPlan(trip: trip, sheet: $sheet, librarySheet: $librarySheet).environment(\.editMode, $editMode)
            case "map": TripMapView(trip: trip)
            default: TripPlaces(trip: trip, librarySheet: $librarySheet)
            }
        }
        .navigationTitle(trip.name)
        .navigationBarTitleDisplayMode(mode == "map" ? .inline : .large)
        .toolbar {
            if mode == "plan" && trip.dayCount > 0 {
                Button(editMode.isEditing ? "Done" : "Edit") {
                    withAnimation { editMode = editMode.isEditing ? .inactive : .active }
                }
            }
            menu(trip)
        }
        .refreshable { await load() }
        .sheet(item: $sheet) { sheet in
            sheet.view(trip: trip).environment(store).environment(router)
        }
        .sheet(item: $librarySheet) { $0.view.environment(store).environment(router) }
        .confirmationDialog("Delete \(trip.name)? Its places stay in your saved places.", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete trip", role: .destructive) {
                Task { if await store.deleteTrip(trip.id) { dismiss() } }
            }
        }
        .overlay {
            if let working {
                VStack(spacing: 10) {
                    ProgressView()
                    Text(working).font(.subheadline.weight(.medium))
                }
                .padding(24)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            }
        }
        .onChange(of: mode) { _, _ in editMode = .inactive }
    }

    private func menu(_ trip: TripDetail) -> some View {
        Menu {
            Section {
                Button { Task { await share(trip) } } label: { Label(trip.shareToken == nil ? "Share a link" : "Share link", systemImage: "square.and.arrow.up") }
                if trip.shareToken != nil {
                    Button(role: .destructive) { Task { await stopSharing(trip) } } label: { Label("Stop sharing", systemImage: "link.badge.plus") }
                }
            }
            if !trip.isLocal {
                Section {
                    Button { sheet = .plan } label: { Label(trip.dayCount > 0 ? "Re-plan with AI" : "Plan with AI", systemImage: "sparkles") }
                    if trip.dayCount > 0 {
                        Button { sheet = .tidy } label: { Label("Tidy with AI", systemImage: "wand.and.stars") }
                        Button { Task { await suggest(trip) } } label: { Label("Suggest places for quiet days", systemImage: "lightbulb") }
                    }
                }
                Section {
                    Button { router.push(.web(hash: "#/trip/\(trip.id)/bookings")) } label: { Label("Bookings", systemImage: "ticket") }
                    Button { router.push(.web(hash: "#/packing/\(trip.id)")) } label: { Label("Packing list", systemImage: "suitcase") }
                    Button { router.push(.web(hash: "#/events/\(trip.id)")) } label: { Label("What's on", systemImage: "music.mic") }
                }
            }
            Section {
                Button { sheet = .details } label: { Label(trip.isLocal ? "Rename" : "Name and dates", systemImage: "pencil") }
                Button(role: .destructive) { confirmDelete = true } label: { Label("Delete trip", systemImage: "trash") }
            }
        } label: {
            Image(systemName: "ellipsis.circle")
        }
    }

    private func share(_ trip: TripDetail) async {
        do {
            let link: TripShareLink = try await API.shared.post("/v1/trips/\(trip.id)/share")
            await store.reloadTrips()
            _ = try? await store.loadTrip(trip.id)
            guard let url = API.shared.url(link.path) else { return }
            let activity = UIActivityViewController(activityItems: [url], applicationActivities: nil)
            Links.topViewController()?.present(activity, animated: true)
        } catch { store.fail(error) }
    }

    private func stopSharing(_ trip: TripDetail) async {
        do {
            try await API.shared.call("DELETE", "/v1/trips/\(trip.id)/share")
            _ = try? await store.loadTrip(trip.id)
            store.show("The link no longer works")
        } catch { store.fail(error) }
    }

    private func suggest(_ trip: TripDetail) async {
        working = "Looking for places for quiet days…"
        let before = trip.places.filter(\.suggested).count
        if let fresh = await store.tripCall("POST", "/v1/trips/\(trip.id)/suggest") {
            let added = fresh.places.filter(\.suggested).count - before
            store.show(added > 0 ? "Added \(Fmt.plural(added, "suggestion"))" : "No quiet days to fill")
        }
        working = nil
    }
}

enum TripSheet: String, Identifiable {
    case plan, tidy, details
    var id: String { rawValue }

    @MainActor @ViewBuilder func view(trip: TripDetail) -> some View {
        switch self {
        case .plan: PlanSheet(trip: trip)
        case .tidy: TidySheet(trip: trip)
        case .details: TripDetailsSheet(trip: trip)
        }
    }
}

/// Plan (or re-plan) the trip with AI: how many days, from when, and anything to keep in mind.
struct PlanSheet: View {
    let trip: TripDetail
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var days = 3
    @State private var hasStart = false
    @State private var start = Date()
    @State private var preferences = ""
    @State private var busy = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Stepper(value: $days, in: 1...21) { HStack { Text("Days"); Spacer(); Text("\(days)").fontWeight(.semibold) } }
                    Toggle("Start date", isOn: $hasStart.animation())
                    if hasStart { DatePicker("Starts", selection: $start, displayedComponents: .date) }
                } footer: {
                    Text("AI groups your \(Fmt.plural(trip.places.count, "place")) by neighbourhood and time of day. Starred places always fit in. This replaces the current plan.")
                }
                Section("Anything to keep in mind?") {
                    TextField("e.g. slow mornings, no museums", text: $preferences, axis: .vertical)
                }
            }
            .tripBackground()
            .navigationTitle(trip.dayCount > 0 ? "Re-plan" : "Plan with AI")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else { Button("Plan") { plan() }.disabled(trip.places.isEmpty) }
                }
            }
            .interactiveDismissDisabled(busy)
        }
        .presentationDetents([.medium, .large])
        .onAppear {
            days = trip.dayCount > 0 ? trip.dayCount : max(1, min(21, Int((Double(trip.places.count) / 4).rounded(.up))))
            if let s = trip.startDate.flatMap(Fmt.day) { hasStart = true; start = s }
        }
    }

    private func plan() {
        busy = true
        Task {
            let body: [String: Any?] = ["days": days, "start_date": hasStart ? Fmt.iso(start) : nil,
                                        "preferences": preferences.isEmpty ? nil : preferences]
            if let fresh = await store.tripCall("POST", "/v1/trips/\(trip.id)/plan", body) {
                store.show(fresh.plannedBy == "claude" ? "Your trip is planned" : "Planned by location (AI unavailable)")
                dismiss()
            }
            busy = false
        }
    }
}

/// Ask AI to tidy a plan you built: order stops, suggest times, or follow an instruction.
struct TidySheet: View {
    let trip: TripDetail
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var instruction = ""
    @State private var busy = false
    private let ideas = ["Group stops by neighborhood", "Make it more relaxed", "Put meals at mealtimes", "Start later in the morning"]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Optional: e.g. make day 2 more relaxed", text: $instruction, axis: .vertical)
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack {
                            ForEach(ideas, id: \.self) { idea in
                                FilterChip(label: idea, isOn: instruction == idea) { instruction = idea }
                            }
                        }
                    }
                } footer: {
                    Text("Keeps your places on their days unless you ask otherwise, orders the stops and suggests times.")
                }
            }
            .tripBackground()
            .navigationTitle("Tidy with AI")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy { ProgressView() } else {
                        Button("Tidy") {
                            busy = true
                            Task {
                                if await store.tripCall("POST", "/v1/trips/\(trip.id)/tidy",
                                                        ["instruction": instruction.isEmpty ? nil : instruction]) != nil {
                                    store.show("Tidied")
                                    dismiss()
                                }
                                busy = false
                            }
                        }
                    }
                }
            }
            .interactiveDismissDisabled(busy)
        }
        .presentationDetents([.medium])
    }
}

/// Rename the trip and set its start date.
struct TripDetailsSheet: View {
    let trip: TripDetail
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var hasStart = false
    @State private var start = Date()

    var body: some View {
        NavigationStack {
            Form {
                TextField("Name", text: $name)
                if !trip.isLocal {
                    Toggle("Start date", isOn: $hasStart.animation())
                    if hasStart { DatePicker("Starts", selection: $start, displayedComponents: .date) }
                }
            }
            .tripBackground()
            .navigationTitle(trip.isLocal ? "Rename" : "Name and dates")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        Task {
                            var body: [String: Any?] = ["name": name.trimmingCharacters(in: .whitespaces)]
                            if !trip.isLocal { body["start_date"] = hasStart ? Fmt.iso(start) : nil }
                            if await store.tripCall("PATCH", "/v1/trips/\(trip.id)", body) != nil { dismiss() }
                        }
                    }
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .presentationDetents([.medium])
        .onAppear {
            name = trip.name
            if let s = trip.startDate.flatMap(Fmt.day) { hasStart = true; start = s }
        }
    }
}
