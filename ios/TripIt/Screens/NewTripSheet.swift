import SwiftUI

/// New trip: where and how long, then AI or by hand, then the saved places to take.
struct NewTripSheet: View {
    let placeIds: [String]
    let folderId: String?
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss

    @State private var step = 1
    @State private var city = ""
    @State private var name = ""
    @State private var days = 3
    @State private var hasStart = false
    @State private var start = Date()
    @State private var aiPlans = true
    @State private var fillGaps = true
    @State private var preferences = ""
    @State private var picked = Set<String>()
    @State private var touched = false
    @State private var filter = PlaceFilter()
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Group {
                switch step {
                case 1: whereStep
                case 2: howStep
                default: placesStep
                }
            }
            .tripBackground()
            .navigationTitle("New trip")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    if step > 1 { Button { withAnimation { step -= 1 } } label: { Label("Back", systemImage: "chevron.left") } }
                    else { Button("Cancel") { dismiss() } }
                }
                ToolbarItem(placement: .principal) {
                    HStack(spacing: 5) {
                        ForEach(1...3, id: \.self) { i in
                            Capsule().fill(i <= step ? Theme.accent : Theme.fill).frame(width: 22, height: 4)
                        }
                    }
                    .accessibilityLabel("Step \(step) of 3")
                }
            }
            .overlay { if busy { busyOverlay } }
            .interactiveDismissDisabled(busy)
        }
        .onAppear(perform: setUp)
    }

    private func setUp() {
        let fromFolder = folderId.map { id in store.places.filter { $0.folderIds.contains(id) }.map(\.id) } ?? []
        picked = Set(placeIds + fromFolder)
        touched = !picked.isEmpty
        city = picked.compactMap { store.place($0)?.city }.first { !$0.isEmpty } ?? ""
    }

    // MARK: Step 1

    private var whereStep: some View {
        let cities = Dictionary(grouping: store.places.filter { !$0.city.isEmpty }, by: \.city).mapValues(\.count)
            .sorted { $0.value > $1.value }.prefix(6)
        return Form {
            Section {
                TextField("City, e.g. Lisbon", text: $city)
                    .textInputAutocapitalization(.words)
                    .font(.title3)
                if !cities.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(Array(cities), id: \.key) { item in
                                FilterChip(label: item.key, count: item.value, isOn: PlaceFilter.normalize(item.key) == PlaceFilter.normalize(city)) {
                                    city = item.key
                                }
                            }
                        }
                    }
                    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                }
            } header: {
                Text("Where to?")
            } footer: {
                if !cities.isEmpty { Text("Cities you've saved places in.") }
            }
            Section {
                TextField(city.isEmpty ? "Trip name (optional)" : "\(city) trip", text: $name)
                Stepper(value: $days, in: 1...21) {
                    HStack { Text("Days"); Spacer(); Text("\(days)").fontWeight(.semibold) }
                }
                Toggle("Start date", isOn: $hasStart.animation())
                if hasStart {
                    DatePicker("Starts", selection: $start, displayedComponents: .date)
                }
            } footer: {
                Text("With a start date, TripIt checks each stop is open on its day.")
            }
            Section {
                Button("Next") { next() }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(city.trimmingCharacters(in: .whitespaces).isEmpty)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
            }
        }
    }

    private func next() {
        city = city.trimmingCharacters(in: .whitespaces)
        guard !city.isEmpty else { error = "Where are you going?"; return }
        if !touched {  // start with everything saved in that city ticked
            let key = PlaceFilter.normalize(city)
            for place in store.places where PlaceFilter.normalize(place.city) == key { picked.insert(place.id) }
            touched = true
        }
        withAnimation { step = 2 }
    }

    // MARK: Step 2

    private var howStep: some View {
        List {
            Section {
                choice(ai: true, symbol: "sparkles", color: Theme.gold, title: "Plan it for me",
                       text: "AI arranges your places into \(Fmt.plural(days, "day")), grouped by area with sensible times. It can suggest a few extras for quiet days.")
                choice(ai: false, symbol: "calendar", color: Theme.indigo, title: "I'll build it myself",
                       text: "\(Fmt.plural(days, "empty day")) for you to fill from your saved places. You can ask AI to tidy it later.")
            } header: {
                Text("How would you like to plan it?")
            }
        }
    }

    private func choice(ai: Bool, symbol: String, color: Color, title: String, text: String) -> some View {
        Button {
            aiPlans = ai
            withAnimation { step = 3 }
        } label: {
            HStack(spacing: 14) {
                SymbolTile(symbol: symbol, color: color, size: 44)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.headline).foregroundStyle(Theme.label)
                    Text(text).font(.subheadline).foregroundStyle(Theme.secondary)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(Theme.tertiary)
            }
            .padding(.vertical, 6)
        }
    }

    // MARK: Step 3

    private var placesStep: some View {
        List {
            if aiPlans {
                Section {
                    Toggle(isOn: $fillGaps) {
                        VStack(alignment: .leading) {
                            Text("Suggest places for quiet days")
                            Text("Marked “Suggested”, easy to keep or remove").font(.caption).foregroundStyle(Theme.secondary)
                        }
                    }
                    TextField("Anything to keep in mind? e.g. slow mornings", text: $preferences, axis: .vertical)
                }
            }
            PlaceChecklist(places: store.places, picked: $picked, filter: $filter)
        }
        .searchable(text: $filter.query, prompt: "Search your saved places")
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 6) {
                if let error { Text(error).font(.footnote).foregroundStyle(Theme.danger) }
                Button(action: create) {
                    HStack(spacing: 6) {
                        Image(systemName: aiPlans ? "sparkles" : "calendar.badge.plus")
                        Text((aiPlans ? "Plan my trip" : "Create trip") + (picked.isEmpty ? "" : " · \(Fmt.plural(picked.count, "place"))"))
                    }
                }
                .buttonStyle(PrimaryButtonStyle())
            }
            .padding(.horizontal, 20).padding(.vertical, 10)
            .background(.bar)
        }
    }

    private var busyOverlay: some View {
        ZStack {
            Color.black.opacity(0.25).ignoresSafeArea()
            VStack(spacing: 12) {
                ProgressView().controlSize(.large)
                Text(aiPlans ? "Planning your trip…" : "Creating your trip…").font(.headline)
                if aiPlans { Text("This can take up to a minute.").font(.subheadline).foregroundStyle(Theme.secondary) }
            }
            .padding(28)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        }
    }

    private func create() {
        if aiPlans && picked.isEmpty && !fillGaps { error = "Pick some places, or turn on suggestions."; return }
        error = nil
        busy = true
        Task {
            let body: [String: Any?] = [
                "city": city, "name": name.trimmingCharacters(in: .whitespaces).isEmpty ? nil : name,
                "days": days, "start_date": hasStart ? Fmt.iso(start) : nil, "place_ids": Array(picked),
                "plan": aiPlans ? "ai" : "manual", "fill_gaps": aiPlans && fillGaps,
                "preferences": preferences.trimmingCharacters(in: .whitespaces).isEmpty ? nil : preferences,
            ]
            do {
                let trip: TripDetail = try await API.shared.post("/v1/trips", body)
                store.apply(trip)
                await store.reloadTrips()
                await store.reloadPlaces()
                store.show(aiPlans ? (trip.plannedBy == "claude" ? "Your trip is planned" : "Planned by location (AI unavailable)")
                                   : "Your days are ready to fill")
                dismiss()
                router.push(.trip(id: trip.id))
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
        }
    }
}
