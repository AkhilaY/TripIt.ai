import SwiftUI

struct ItineraryView: View {
    let trip: Trip
    @Binding var showingPlanner: Bool

    var body: some View {
        if !trip.hasItinerary {
            ContentUnavailableView {
                Label("No itinerary yet", systemImage: "calendar")
            } description: {
                Text("Turn your \(trip.allPlaces.count) saved places into a day-by-day plan grouped by neighborhood.")
            } actions: {
                Button("Plan my trip") { showingPlanner = true }
                    .buttonStyle(.borderedProminent)
                    .disabled(trip.allPlaces.isEmpty)
            }
        } else {
            List {
                if let notes = trip.planNotes, !notes.isEmpty {
                    Section { Text(notes).font(.callout).foregroundStyle(.secondary) }
                }
                ForEach(1...trip.dayCount, id: \.self) { day in
                    Section {
                        let stops = trip.stops(onDay: day)
                        ForEach(stops) { place in
                            NavigationLink { PlaceDetailView(place: place) } label: { StopRow(place: place) }
                                .contextMenu { moveMenu(for: place) }
                        }
                        .onMove { from, to in reorder(day: day, from: from, to: to) }
                    } header: {
                        DayHeader(trip: trip, day: day)
                    }
                }
                let unscheduled = trip.unscheduledPlaces
                if !unscheduled.isEmpty {
                    Section("Not scheduled") {
                        ForEach(unscheduled) { place in
                            NavigationLink { PlaceDetailView(place: place) } label: { PlaceRow(place: place) }
                                .contextMenu { moveMenu(for: place) }
                        }
                    }
                }
            }
            .toolbar { EditButton() }
        }
    }

    @ViewBuilder
    private func moveMenu(for place: Place) -> some View {
        ForEach(1...max(trip.dayCount, 1), id: \.self) { day in
            if place.dayNumber != day {
                Button("Move to Day \(day)") { move(place, to: day) }
            }
        }
        if trip.dayCount < 21 {
            Button("Move to new day") {
                trip.dayCount += 1
                move(place, to: trip.dayCount)
            }
        }
        if place.dayNumber != nil {
            Button("Unschedule", role: .destructive) { move(place, to: nil) }
        }
    }

    private func move(_ place: Place, to day: Int?) {
        place.dayNumber = day
        place.dayOrder = day.map { trip.stops(onDay: $0).count } ?? 0
        if place.timeOfDay == nil { place.timeOfDay = place.category.preferredTimeOfDay }
    }

    private func reorder(day: Int, from: IndexSet, to: Int) {
        var stops = trip.stops(onDay: day)
        stops.move(fromOffsets: from, toOffset: to)
        for (index, place) in stops.enumerated() { place.dayOrder = index }
    }
}

private struct DayHeader: View {
    let trip: Trip
    let day: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text("Day \(day)").font(.headline).foregroundStyle(.primary)
                if let date = trip.date(forDay: day) {
                    Text(date, format: .dateTime.weekday(.abbreviated).month().day())
                }
            }
            Text(trip.title(forDay: day)).font(.subheadline)
        }
        .textCase(nil)
    }
}

private struct StopRow: View {
    let place: Place

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack {
                Image(systemName: place.timeOfDay?.symbol ?? "clock")
                    .foregroundStyle(place.category.color)
                Text(place.timeOfDay?.label ?? "")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            .frame(width: 64)
            VStack(alignment: .leading, spacing: 2) {
                Text(place.name).font(.body.weight(.medium)).strikethrough(place.visited)
                Text(place.category.label + (place.neighborhood.map { " · \($0)" } ?? ""))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let note = place.dayNote, !note.isEmpty {
                    Text(note).font(.caption).foregroundStyle(.secondary).italic()
                }
            }
        }
    }
}

struct PlanTripSheet: View {
    @Environment(\.dismiss) private var dismiss
    let trip: Trip
    var onPlanned: () -> Void = {}

    @State private var days = 3
    @State private var hasStartDate = false
    @State private var startDate = Date()
    @State private var preferences = ""
    @State private var planning = false
    @State private var offlineNotice: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Stepper("\(days) day\(days == 1 ? "" : "s")", value: $days, in: 1...21)
                    Toggle("Set start date", isOn: $hasStartDate)
                    if hasStartDate {
                        DatePicker("Start", selection: $startDate, displayedComponents: .date)
                    }
                } footer: {
                    Text("\(trip.allPlaces.count) saved places in \(trip.city)")
                }
                Section("Anything to keep in mind?") {
                    TextField("e.g. slow mornings, vegetarian, no museums on day 1", text: $preferences, axis: .vertical)
                }
                if let offlineNotice {
                    Section { Label(offlineNotice, systemImage: "wifi.exclamationmark").foregroundStyle(.orange) }
                }
            }
            .navigationTitle(trip.hasItinerary ? "Re-plan trip" : "Plan my trip")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if planning {
                        ProgressView()
                    } else {
                        Button("Plan") { Task { await plan() } }
                    }
                }
            }
            .interactiveDismissDisabled(planning)
            .onAppear {
                days = trip.hasItinerary ? trip.dayCount : max(1, min(7, Int((Double(trip.allPlaces.count) / 4).rounded(.up))))
                if let start = trip.startDate {
                    hasStartDate = true
                    startDate = start
                }
            }
        }
    }

    private func plan() async {
        planning = true
        let (source, error) = await ItineraryPlanner.plan(
            trip: trip, days: days, startDate: hasStartDate ? startDate : nil, preferences: preferences
        )
        planning = false
        if source == .offline {
            // Show the notice briefly so it's clear this is the simpler offline plan.
            offlineNotice = "Couldn't reach the server (\(error?.localizedDescription ?? "offline")). Made a quick plan by grouping nearby places instead."
            try? await Task.sleep(for: .seconds(2.5))
        }
        onPlanned()
        dismiss()
    }
}
