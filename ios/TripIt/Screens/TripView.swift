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
                    Button { router.push(.bookings(tripId: trip.id)) } label: { Label("Bookings", systemImage: "ticket") }
                    Button { router.push(.web(hash: "#/packing/\(trip.id)")) } label: { Label("Packing list", systemImage: "suitcase") }
                    Button { router.push(.web(hash: "#/events/\(trip.id)")) } label: { Label("What's on", systemImage: "music.mic") }
                }
            }
            if !trip.isLocal {
                Section {
                    if (trip.members ?? []).count > 1 {
                        Button { sheet = .people } label: { Label("People on this trip", systemImage: "person.2") }
                    }
                    Button { Task { await TripInvite.share(trip, store: store) } } label: { Label("Invite someone to plan with you", systemImage: "person.badge.plus") }
                }
            }
            Section {
                Button { sheet = .details } label: { Label(trip.isLocal ? "Rename" : "Name and dates", systemImage: "pencil") }
                if !trip.isLocal {
                    Button { sheet = .route } label: { Label("Edit route", systemImage: "point.topleft.down.to.point.bottomright.curvepath") }
                }
                if trip.isOwner {
                    Button(role: .destructive) { confirmDelete = true } label: { Label("Delete trip", systemImage: "trash") }
                } else {
                    Button(role: .destructive) { sheet = .people } label: { Label("Leave trip", systemImage: "rectangle.portrait.and.arrow.right") }
                }
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
    case plan, tidy, details, route, people
    var id: String { rawValue }

    @MainActor @ViewBuilder func view(trip: TripDetail) -> some View {
        switch self {
        case .plan: PlanSheet(trip: trip)
        case .tidy: TidySheet(trip: trip)
        case .details: TripDetailsSheet(trip: trip)
        case .route: RouteSheet(trip: trip)
        case .people: PeopleSheet(trip: trip)
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


/// The trip's route: cities in order, days in each, and how you get from one to the next.
struct RouteSheet: View {
    let trip: TripDetail
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var stops: [Draft] = []
    @State private var busy = false

    struct Draft: Identifiable {
        let id = UUID()
        var city: String
        var days: Int
        var mode: String
        var hours: Double
        var note: String
    }

    static let modes = ["train", "flight", "drive", "bus", "ferry", "other"]

    var body: some View {
        NavigationStack {
            Form {
                ForEach($stops) { $stop in
                    let index = stops.firstIndex { $0.id == stop.id } ?? 0
                    Section {
                        if index > 0 {
                            Picker("Getting there", selection: $stop.mode) {
                                ForEach(Self.modes, id: \.self) { Text($0 == "drive" ? "Drive" : $0.capitalized).tag($0) }
                            }
                            Stepper(value: $stop.hours, in: 0...24, step: 0.25) {
                                Text(stop.hours == 0 ? "Travel time not set" : "About \(TravelHome.duration(Int(stop.hours * 60)))")
                            }
                            TextField("Note, e.g. Eurostar from St Pancras", text: $stop.note)
                        }
                        TextField("City", text: $stop.city).textInputAutocapitalization(.words)
                        Stepper(value: $stop.days, in: 1...21) { Text(Fmt.plural(stop.days, "day")) }
                    } header: {
                        HStack {
                            Text("Stop \(index + 1)")
                            Spacer()
                            if stops.count > 1 {
                                Button("Remove", role: .destructive) { stops.removeAll { $0.id == stop.id } }
                                    .font(.footnote).textCase(nil)
                            }
                        }
                    }
                }
                Section {
                    Button { stops.append(Draft(city: "", days: 2, mode: "train", hours: 0, note: "")) } label: {
                        Label("Add a stop", systemImage: "plus")
                    }
                } footer: {
                    Text("\(Fmt.plural(stops.reduce(0) { $0 + $1.days }, "day")) in all. If the trip is longer, the last stop keeps the extra days.")
                }
            }
            .tripBackground()
            .navigationTitle("Route")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }
                        .disabled(busy || stops.contains { $0.city.trimmingCharacters(in: .whitespaces).isEmpty })
                }
            }
        }
        .onAppear {
            guard stops.isEmpty else { return }
            let route = trip.stops ?? []
            stops = route.isEmpty
                ? [Draft(city: trip.city, days: max(trip.dayCount, 1), mode: "train", hours: 0, note: "")]
                : route.map { Draft(city: $0.city, days: $0.days, mode: $0.travelMode ?? "train",
                                    hours: Double($0.travelMinutes ?? 0) / 60, note: $0.travelNote ?? "") }
        }
    }

    private func save() async {
        busy = true
        defer { busy = false }
        let body: [[String: Any]] = stops.enumerated().map { i, s in
            var stop: [String: Any] = ["city": s.city.trimmingCharacters(in: .whitespaces), "days": s.days]
            if i > 0 {
                stop["travel_mode"] = s.mode
                if s.hours > 0 { stop["travel_minutes"] = Int(s.hours * 60) }
                if !s.note.isEmpty { stop["travel_note"] = s.note }
            }
            return stop
        }
        do {
            let fresh: TripDetail = try await API.shared.put("/v1/trips/\(trip.id)/stops", ["stops": body])
            store.apply(fresh)
            await store.reloadTrips()
            dismiss()
        } catch { store.fail(error) }
    }
}
