import SwiftUI

/// New trip, however it starts (from nothing, from saved places, a list or a city): a name, its cities (any number,
/// or none yet) and dates; then the saved places to take, when there are any; then anything already booked.
/// Every step but the name can be left for later.
struct NewTripSheet: View {
    let placeIds: [String]
    let folderId: String?
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss

    struct Stop: Identifiable, Equatable {
        let id = UUID()
        var city: String
        var days: Int
    }

    @State private var step = 1
    @State private var stops: [Stop] = []
    @State private var typed = ""
    @State private var name = ""
    @State private var days = 3
    @State private var startDate: Date?
    @State private var endDate: Date?
    @State private var pickingDates = false
    private var hasStart: Bool { startDate != nil }
    private var start: Date { startDate ?? Date() }
    @State private var picked = Set<String>()
    @State private var touched = false
    @State private var filter = PlaceFilter()
    @State private var busy = false
    @State private var error: String?

    /// The trip's length: its dates, else its cities' days added up, else what you set.
    private var totalDays: Int {
        if let s = startDate, let e = endDate { return min(21, max(1, (Calendar.current.dateComponents([.day], from: s, to: e).day ?? 0) + 1)) }
        return stops.isEmpty ? days : min(21, stops.reduce(0) { $0 + $1.days })
    }

    var body: some View {
        NavigationStack {
            Group {
                switch step {
                case 1: whereStep
                case 2: placesStep
                default: bookedStep
                }
            }
            .tripBackground()
            .navigationTitle("New trip")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    if step > 1 { Button { back() } label: { Label("Back", systemImage: "chevron.left") } }
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
            .sheet(isPresented: $pickingDates) {
                DateRangeSheet(start: $startDate, end: $endDate)
                    .presentationDragIndicator(.visible)
            }
        }
        .onAppear(perform: setUp)
    }

    private func setUp() {
        let fromFolder = folderId.map { id in store.places.filter { $0.folderIds.contains(id) }.map(\.id) } ?? []
        picked = Set(placeIds + fromFolder)
        touched = !picked.isEmpty
        let cities = picked.compactMap { store.place($0)?.city }.filter { !$0.isEmpty }
        for city in cities where !stops.contains(where: { PlaceFilter.normalize($0.city) == PlaceFilter.normalize(city) }) {
            stops.append(Stop(city: city, days: 2))
        }
    }

    // MARK: Step 1

    private func toggle(_ city: String) {
        let key = PlaceFilter.normalize(city)
        if let i = stops.firstIndex(where: { PlaceFilter.normalize($0.city) == key }) {
            stops.remove(at: i)
        } else {
            stops.append(Stop(city: city, days: 2))
        }
    }

    private func addTyped() {
        let city = typed.trimmingCharacters(in: .whitespaces)
        guard !city.isEmpty else { return }
        if !stops.contains(where: { PlaceFilter.normalize($0.city) == PlaceFilter.normalize(city) }) {
            stops.append(Stop(city: city, days: 2))
        }
        typed = ""
    }

    private var whereStep: some View {
        let cities = Dictionary(grouping: store.places.filter { !$0.city.isEmpty }, by: \.city).mapValues(\.count)
            .sorted { $0.value > $1.value }.prefix(10)
        return Form {
            Section("Name") {
                TextField(stops.first.map { "\($0.city) trip" } ?? "e.g. Swiss Germany trip", text: $name)
                    .textInputAutocapitalization(.words)
            }
            Section {
                ForEach($stops) { $stop in
                    Stepper(value: $stop.days, in: 1...21) {
                        HStack {
                            Text(stop.city).font(Theme.text(.body))
                            Spacer()
                            Text(Fmt.plural(stop.days, "day")).foregroundStyle(Theme.secondary)
                        }
                    }
                }
                .onDelete { stops.remove(atOffsets: $0) }
                .onMove { stops.move(fromOffsets: $0, toOffset: $1) }
                HStack {
                    TextField(stops.isEmpty ? "A city, e.g. Lisbon" : "Add another city", text: $typed)
                        .textInputAutocapitalization(.words)
                        .submitLabel(.done)
                        .onSubmit(addTyped)
                    if !typed.isEmpty {
                        Button("Add", action: addTyped).font(Theme.text(.subheadline, weight: .medium))
                    }
                }
                if !cities.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(Array(cities), id: \.key) { item in
                                FilterChip(label: item.key, count: item.value,
                                           isOn: stops.contains { PlaceFilter.normalize($0.city) == PlaceFilter.normalize(item.key) }) {
                                    toggle(item.key)
                                }
                            }
                        }
                    }
                    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                }
            } header: {
                Text("Cities, in order (optional)")
            } footer: {
                Text(stops.count > 1 ? "Swipe to remove a city; each gets its own days, in this order."
                     : "Pick one or more, or none: you can add places from anywhere later.")
            }
            .sensoryFeedback(.selection, trigger: stops.count)
            Section {
                Button { pickingDates = true } label: {
                    HStack {
                        Text("Dates").foregroundStyle(Theme.label)
                        Spacer()
                        Text(startDate.map { s in Fmt.range(s, endDate ?? s) } ?? "No dates yet")
                            .foregroundStyle(startDate == nil ? Theme.secondary : Theme.label)
                        Image(systemName: "calendar").foregroundStyle(Theme.secondary)
                    }
                }
                if startDate == nil && stops.isEmpty {
                    Stepper(value: $days, in: 1...21) {
                        HStack { Text("Days"); Spacer(); Text("\(days)").fontWeight(.semibold) }
                    }
                } else {
                    HStack { Text("Days"); Spacer(); Text("\(totalDays)").fontWeight(.semibold) }
                }
            }
            Section {
                Button("Next") { next() }
                    .buttonStyle(PrimaryButtonStyle())
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
            }
        }
    }

    private func next() {
        addTyped()
        if !touched {  // start with everything saved in those cities ticked
            let keys = Set(stops.map { PlaceFilter.normalize($0.city) })
            for place in store.places where keys.contains(PlaceFilter.normalize(place.city)) { picked.insert(place.id) }
            touched = true
        }
        withAnimation { step = choosable ? 2 : 3 }
    }

    private func back() {
        withAnimation { step = step == 3 && choosable ? 2 : 1 }
    }

    /// Whether there are saved places worth offering: ones already picked, or saved in the trip's cities.
    private var choosable: Bool {
        if !picked.isEmpty { return true }
        let keys = Set(stops.map { PlaceFilter.normalize($0.city) })
        return !keys.isEmpty && store.places.contains { keys.contains(PlaceFilter.normalize($0.city)) }
    }

    // MARK: Step 2

    private var placesStep: some View {
        List {
            PlaceChecklist(places: store.places, picked: $picked, filter: $filter)
        }
        .searchable(text: $filter.query, prompt: "Search your saved places")
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 6) {
                if let error { Text(error).font(Theme.text(.footnote)).foregroundStyle(Theme.danger) }
                Button { withAnimation { step = 3 } } label: {
                    Text(picked.isEmpty ? "Next" : "Next · \(Fmt.plural(picked.count, "place"))")
                }
                .buttonStyle(PrimaryButtonStyle())
            }
            .padding(.horizontal, 20).padding(.vertical, 10)
            .background(.bar)
        }
    }

    // MARK: Step 3

    private var bookedStep: some View {
        Form {
            Section {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Already booked anything?").font(Theme.serif(26)).foregroundStyle(Theme.label)
                    Text("Add it and it goes on your plan, on its day. Its cities and dates can fill in what you left out.")
                        .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets(top: 4, leading: 4, bottom: 4, trailing: 4))
            }
            Section {
                bookedRow("airplane", "Add a flight", "Flight number and times, every leg") { create(then: .flight) }
                bookedRow("bed.double.fill", "Add a stay", "Hotel, apartment or house") { create(then: .hotel) }
                bookedRow("doc.text.viewfinder", "From a screenshot", "Of a confirmation email or app") { create(then: .other) }
            } footer: {
                Text("Nothing yet? Create the trip; you can add bookings any time from the trip.")
            }
            Section {
                if let error { Text(error).font(Theme.text(.footnote)).foregroundStyle(Theme.danger) }
                Button { create(then: nil) } label: {
                    Text("Create trip" + (picked.isEmpty ? "" : " · \(Fmt.plural(picked.count, "place"))"))
                }
                .buttonStyle(PrimaryButtonStyle())
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
            }
        }
    }

    private func bookedRow(_ symbol: String, _ title: String, _ detail: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                SymbolTile(symbol: symbol, color: Theme.blue)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).foregroundStyle(Theme.label)
                    Text(detail).font(Theme.text(.caption)).foregroundStyle(Theme.secondary)
                }
                Spacer()
                Image(systemName: "chevron.right").font(Theme.text(.caption)).foregroundStyle(Theme.tertiary)
            }
        }
    }

    private var busyOverlay: some View {
        ZStack {
            Color.black.opacity(0.25).ignoresSafeArea()
            VStack(spacing: 12) {
                ProgressView().controlSize(.large)
                Text("Creating your trip…").font(Theme.text(.headline))
            }
            .padding(28)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        }
    }

    /// Makes the trip and opens it; with a kind, the booking form opens on it next.
    private func create(then booking: BookingKind?) {
        error = nil
        busy = true
        Task {
            var body: [String: Any?] = [
                "name": name.trimmingCharacters(in: .whitespaces).isEmpty ? nil : name,
                "days": totalDays, "start_date": hasStart ? Fmt.iso(start) : nil, "place_ids": Array(picked), "plan": "manual",
            ]
            if !stops.isEmpty {
                body["stops"] = stops.map { ["city": $0.city, "days": $0.days] as [String: Any] }
            }
            do {
                let trip: TripDetail = try await API.shared.post("/v1/trips", body)
                store.apply(trip)
                await store.reloadTrips()
                await store.reloadPlaces()
                store.show(booking == nil ? "Your trip is ready" : "Trip made. Now your booking")
                Haptics.success()
                dismiss()
                router.push(.trip(id: trip.id))
                if let booking {
                    try? await Task.sleep(for: .milliseconds(600))  // let this sheet finish closing first
                    var fields = BookingFields()
                    fields.kind = booking
                    router.bookingRequest = .init(tripId: trip.id, fields: booking == .other ? nil : fields)
                }
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
        }
    }
}
