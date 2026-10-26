import PhotosUI
import SwiftUI
import UIKit

/// A booking being added or edited.
struct BookingFields: Equatable {
    var kind: BookingKind = .flight
    var title = ""
    var startAt: String?
    var endAt: String?
    var origin = ""
    var destination = ""
    var address = ""
    var confirmation = ""
    var partySize: Int?
    var notes = ""
    var placeId: String?
    var source = "manual"

    init() {}

    init(_ b: Booking) {
        kind = b.bookingKind
        title = b.title
        startAt = b.startAt
        endAt = b.endAt
        origin = b.origin ?? ""
        destination = b.destination ?? ""
        address = b.address ?? ""
        confirmation = b.confirmation ?? ""
        partySize = b.partySize
        notes = b.notes ?? ""
        placeId = b.placeId
    }

    init(_ d: BookingDraft, source: String) {
        kind = BookingKind(d.kind)
        title = d.title
        startAt = d.startAt
        endAt = d.endAt
        origin = d.origin ?? ""
        destination = d.destination ?? ""
        address = d.address ?? ""
        confirmation = d.confirmation ?? ""
        partySize = d.partySize
        notes = d.notes ?? ""
        self.source = source
    }

    /// A table at a saved place.
    static func reservation(at place: Place) -> BookingFields {
        var f = BookingFields()
        f.kind = .reservation
        f.title = place.name
        f.placeId = place.id
        f.address = place.address ?? ""
        return f
    }

    var isValid: Bool { !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    /// Every field for an edit (empty ones are cleared), or only what's filled in for a new booking.
    func body(creating: Bool) -> [String: Any?] {
        func clean(_ text: String) -> String? {
            let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : t
        }
        let spec = kind
        var body: [String: Any?] = [
            "kind": kind.rawValue,
            "title": clean(title),
            "start_at": startAt,
            "end_at": spec.endLabel == nil ? nil : endAt,
            "origin": spec.originLabel == nil ? nil : clean(origin),
            "destination": spec.destinationLabel == nil ? nil : clean(destination),
            "address": spec.addressLabel == nil ? nil : clean(address),
            "confirmation": clean(confirmation),
            "party_size": spec.hasGuests ? partySize : nil,
            "notes": clean(notes),
        ]
        if creating {
            body = body.filter { $0.value != nil }
            body["source"] = source
            if kind == .reservation, let placeId { body["place_id"] = placeId }
        }
        return body
    }
}

/// Which fields each kind of booking has, and what they're called (as on the web).
extension BookingKind {
    var titleLabel: String {
        switch self {
        case .flight: "Flight number"
        case .hotel: "Hotel"
        case .reservation: "Restaurant or venue"
        case .tour: "Tour or experience"
        case .car: "Rental company"
        case .other: "What is it?"
        }
    }

    var titlePlaceholder: String {
        switch self {
        case .flight: "BA 178"
        case .hotel: "The Hoxton"
        case .reservation: "Name"
        case .tour: "Food tour, museum slot…"
        case .car: "Hertz"
        case .other: "Train, ferry, event…"
        }
    }

    var originLabel: String? {
        switch self {
        case .flight: "From"
        case .car: "Pick-up location"
        default: nil
        }
    }

    var destinationLabel: String? {
        switch self {
        case .flight: "To"
        case .car: "Drop-off location"
        default: nil
        }
    }

    var addressLabel: String? {
        switch self {
        case .hotel, .reservation: "Address"
        case .tour: "Meeting point"
        case .other: "Where"
        default: nil
        }
    }

    var startLabel: String {
        switch self {
        case .flight: "Departs"
        case .hotel: "Check-in"
        case .car: "Pick-up"
        case .other: "When"
        case .reservation, .tour: "Date and time"
        }
    }

    var endLabel: String? {
        switch self {
        case .flight: "Arrives"
        case .hotel: "Check-out"
        case .car: "Drop-off"
        case .other: "Until"
        default: nil
        }
    }

    /// Check-out is a day; the others have a time too.
    var endHasTime: Bool { self != .hotel }

    var hasGuests: Bool { self == .reservation || self == .tour }
}

/// Adding or editing a booking. A new one can come from a screenshot or the confirmation email (Claude reads it and
/// each booking it finds is checked in the form before it's saved) or be typed in.
struct BookingSheet: View {
    let request: Router.BookingRequest
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var tripId = ""
    @State private var path: [Step] = []
    @State private var shots: [PhotosPickerItem] = []
    @State private var reading = false
    @State private var drafts: [BookingDraft] = []
    @State private var draftSource = "text"

    enum Step: Hashable { case paste, manual, drafts }

    /// Stands for your home city's collection until it's made.
    static let home = "home"

    private var homeCollection: Trip? {
        guard let home = store.home else { return nil }
        return store.trips.first { $0.isLocal && $0.role != "editor" && Store.cityKey($0.city) == Store.cityKey(home.city) }
    }

    /// Bookings near home go in your home city's collection, made the first time.
    private func useHomeCollection() async {
        if let existing = homeCollection { tripId = existing.id; return }
        do {
            let trip: TripDetail = try await API.shared.post("/v1/home/collection")
            store.apply(trip)
            await store.reloadTrips()
            tripId = trip.id
        } catch {
            store.fail(error)
            tripId = store.likelyBookingTrip?.id ?? ""
        }
    }

    var body: some View {
        NavigationStack(path: $path) {
            root
                .navigationDestination(for: Step.self) { step in
                    switch step {
                    case .paste:
                        PasteConfirmation { text in Task { await read(text: text, images: []) } }
                    case .manual:
                        BookingFormView(tripId: tripId, fields: BookingFields(), heading: "Add a booking") { dismiss() }
                    case .drafts:
                        DraftsFlow(tripId: tripId, drafts: drafts, source: draftSource) { dismiss() }
                    }
                }
        }
        .onAppear {
            if tripId.isEmpty {
                // Usually the trip you're on; at home, near home (a pop-up's tickets, a dinner reservation).
                tripId = request.tripId ?? request.booking?.tripId ?? store.activeTrip?.trip.id
                    ?? (store.home != nil ? Self.home : store.likelyBookingTrip?.id ?? "")
            }
        }
        .task(id: tripId) {
            if tripId == Self.home { await useHomeCollection(); return }
            if !tripId.isEmpty, store.tripDetails[tripId] == nil { _ = try? await store.loadTrip(tripId) }
        }
    }

    @ViewBuilder private var root: some View {
        if let booking = request.booking {
            BookingFormView(tripId: booking.tripId, bookingId: booking.id, fields: BookingFields(booking),
                            heading: request.title ?? "Edit booking", cancellable: true) { dismiss() }
        } else if let fields = request.fields {
            BookingFormView(tripId: tripId, fields: fields, heading: request.title ?? "Add a booking", cancellable: true) { dismiss() }
        } else {
            chooser
        }
    }

    /// Your trips, soonest first, after near home.
    private var tripsToChoose: [Trip] {
        store.realTrips.filter { $0.id != homeCollection?.id }
    }

    private var chooser: some View {
        Form {
            if tripsToChoose.isEmpty && store.home == nil {
                Section {
                    Text("Set your home city in Profile for bookings near home, or save a trip for its flights and stays.")
                        .foregroundStyle(Theme.secondary)
                }
            } else {
                Section {
                    Picker("For", selection: $tripId) {
                        if let home = store.home {
                            Text("Around \(home.city)").tag(homeCollection?.id ?? Self.home)
                        }
                        ForEach(tripsToChoose) { Text($0.name).tag($0.id) }
                    }
                } footer: {
                    Text("Near home: tickets for a pop-up, a table at a restaurant. On a trip: flights, stays and tours.")
                }
                Section {
                    PhotosPicker(selection: $shots, maxSelectionCount: 6, matching: .images) {
                        option("photo.on.rectangle", Theme.green, "Screenshot or photo", "Of a confirmation, e-ticket or itinerary")
                    }
                    Button { path.append(.paste) } label: {
                        option("doc.plaintext", Theme.orange, "Paste the email text", "We read the flight, hotel or reservation details")
                    }
                    Button { path.append(.manual) } label: {
                        option("square.and.pencil", Theme.gray, "Enter it yourself", "Flight, stay, table, tour or car")
                    }
                } footer: {
                    Text("You check what we read before anything is saved. A confirmation number alone can't be looked up, so we read the confirmation itself.")
                }
                .disabled(reading || tripId.isEmpty || tripId == Self.home)
                if reading {
                    Section {
                        HStack(spacing: 10) { ProgressView(); Text("Reading your confirmation…").foregroundStyle(Theme.secondary) }
                    }
                }
            }
        }
        .tripBackground()
        .navigationTitle("Add a booking")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        .onChange(of: shots) { _, items in
            guard !items.isEmpty else { return }
            shots = []
            Task { await readShots(items) }
        }
    }

    private func option(_ symbol: String, _ color: Color, _ title: String, _ subtitle: String) -> some View {
        HStack(spacing: 12) {
            SymbolTile(symbol: symbol, color: color)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).foregroundStyle(Theme.label)
                Text(subtitle).font(.footnote).foregroundStyle(Theme.secondary)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.quiet)
        }
    }

    private func readShots(_ items: [PhotosPickerItem]) async {
        var images: [String] = []
        for item in items.prefix(6) {
            guard let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data),
                  let jpeg = image.scaled(maxSide: 2000).jpegData(compressionQuality: 0.8) else { continue }
            images.append("data:image/jpeg;base64,\(jpeg.base64EncodedString())")
        }
        guard !images.isEmpty else { store.show("Couldn't open those photos", error: true); return }
        await read(text: nil, images: images)
    }

    private func read(text: String?, images: [String]) async {
        reading = true
        defer { reading = false }
        do {
            let found: [BookingDraft] = try await API.shared.post("/v1/trips/\(tripId)/bookings/read", ["text": text, "images": images])
            guard !found.isEmpty else {
                store.show("No bookings found there. You can enter it yourself.", error: true)
                return
            }
            drafts = found
            draftSource = images.isEmpty ? "text" : "screenshot"
            path = [.drafts]
        } catch { store.fail(error) }
    }
}

/// Paste a confirmation email or itinerary for Claude to read.
private struct PasteConfirmation: View {
    let onRead: (String) -> Void
    @State private var text = ""

    var body: some View {
        Form {
            Section {
                TextEditor(text: $text)
                    .frame(minHeight: 200)
                    .overlay(alignment: .topLeading) {
                        if text.isEmpty {
                            Text("Paste the confirmation email or itinerary here").foregroundStyle(Theme.tertiary)
                                .padding(.top, 8).padding(.leading, 5).allowsHitTesting(false)
                        }
                    }
            } footer: {
                Text("You can paste more than one booking at once. Names and card details aren't needed; leave them out if you like.")
            }
        }
        .tripBackground()
        .navigationTitle("Paste a confirmation")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("Read") { onRead(text.trimmingCharacters(in: .whitespacesAndNewlines)) }
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }
}

/// Each booking Claude read, one at a time, to check and save (or skip).
private struct DraftsFlow: View {
    let tripId: String
    let drafts: [BookingDraft]
    let source: String
    let onFinished: () -> Void
    @State private var index = 0

    var body: some View {
        if index < drafts.count {
            BookingFormView(tripId: tripId, fields: BookingFields(drafts[index], source: source),
                            heading: drafts.count > 1 ? "Check booking (\(index + 1) of \(drafts.count))" : "Check booking",
                            reviewing: true, onSkip: advance) { advance() }
                .id(index)
        }
    }

    private func advance() {
        if index + 1 < drafts.count { index += 1 } else { onFinished() }
    }
}

/// The booking form: its type, the fields that type has, dates, the confirmation number and notes.
struct BookingFormView: View {
    let tripId: String
    var bookingId: String?
    var heading: String
    var cancellable = false
    var reviewing = false
    var onSkip: (() -> Void)?
    let onSaved: () -> Void
    @State private var fields: BookingFields
    @State private var saving = false
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss

    init(tripId: String, bookingId: String? = nil, fields: BookingFields, heading: String, cancellable: Bool = false,
         reviewing: Bool = false, onSkip: (() -> Void)? = nil, onSaved: @escaping () -> Void) {
        self.tripId = tripId
        self.bookingId = bookingId
        self.heading = heading
        self.cancellable = cancellable
        self.reviewing = reviewing
        self.onSkip = onSkip
        self.onSaved = onSaved
        _fields = State(initialValue: fields)
    }

    var body: some View {
        let kind = fields.kind
        Form {
            Section {
                Picker("Type", selection: $fields.kind) {
                    ForEach(BookingKind.allCases) { Text($0.formLabel).tag($0) }
                }
                textRow(kind.titleLabel, kind.titlePlaceholder, $fields.title)
                if let label = kind.originLabel { textRow(label, kind == .flight ? "JFK" : "", $fields.origin) }
                if let label = kind.destinationLabel { textRow(label, kind == .flight ? "LHR" : "", $fields.destination) }
                if let label = kind.addressLabel { textRow(label, "", $fields.address) }
                if kind.hasGuests {
                    Stepper(value: Binding(get: { fields.partySize ?? 2 }, set: { fields.partySize = $0 }), in: 1...100) {
                        LabeledContent("Guests", value: fields.partySize.map(String.init) ?? "—")
                    }
                }
            }
            Section {
                WhenRow(label: kind.startLabel, value: $fields.startAt, suggestedDay: tripStart)
            }
            if let label = kind.endLabel {
                Section {
                    WhenRow(label: label, value: $fields.endAt, allowsTime: kind.endHasTime,
                            suggestedDay: fields.startAt.map { String($0.prefix(10)) } ?? tripStart)
                }
            }
            Section {
                textRow("Confirmation number", "", $fields.confirmation)
                TextField("Notes: terminal, seat, room type…", text: $fields.notes, axis: .vertical).lineLimit(1...4)
            } footer: {
                if reviewing {
                    Text("Check what was read against your confirmation. Anything it couldn't find is left blank.")
                } else {
                    Text("Keep confirmation numbers handy for the airport or front desk. Bookings stay private: shared trip links never include them.")
                }
            }
            if reviewing, let onSkip {
                Section { Button("Skip this one", action: onSkip) }
            }
        }
        .tripBackground()
        .navigationTitle(heading)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if cancellable {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
            ToolbarItem(placement: .confirmationAction) {
                if saving { ProgressView() } else {
                    Button("Save") { Task { await save() } }.disabled(!fields.isValid)
                }
            }
        }
    }

    private var tripStart: String? {
        store.tripDetails[tripId]?.startDate ?? store.trips.first { $0.id == tripId }?.startDate
    }

    private func textRow(_ label: String, _ placeholder: String, _ text: Binding<String>) -> some View {
        LabeledContent(label) {
            TextField(label, text: text, prompt: Text(placeholder))
                .multilineTextAlignment(.trailing)
                .textInputAutocapitalization(label == "From" || label == "To" ? .characters : .words)
                .autocorrectionDisabled()
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            let trip: TripDetail
            if let bookingId {
                trip = try await API.shared.patch("/v1/trips/\(tripId)/bookings/\(bookingId)", fields.body(creating: false))
            } else {
                trip = try await API.shared.post("/v1/trips/\(tripId)/bookings", fields.body(creating: true))
            }
            store.apply(trip)
            await store.reloadBookings()
            store.show(bookingId == nil ? "Booking saved" : "Booking updated")
            onSaved()
        } catch { store.fail(error) }
    }
}

/// A booking's date, with or without a time ("2026-11-07" or "2026-11-07T19:25"), or none. Tapping the date opens a
/// calendar; tapping the time opens a time wheel. Both can be cleared from their pickers.
private struct WhenRow: View {
    let label: String
    @Binding var value: String?
    var allowsTime = true
    var suggestedDay: String?
    @State private var picking: Choosing?

    private enum Choosing: String, Identifiable {
        case day, time
        var id: String { rawValue }
    }

    private var day: String? { value.map { String($0.prefix(10)) } }
    private var time: String? { value.flatMap { $0.count > 10 ? String($0.suffix(5)) : nil } }

    var body: some View {
        LabeledContent(label) {
            Button { picking = .day } label: {
                Text(day.flatMap(Fmt.day).map { $0.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day().year()) } ?? "Add date")
            }
            .buttonStyle(ValueButtonStyle(empty: day == nil))
        }
        .sheet(item: $picking) { choosing in
            switch choosing {
            case .day: dayPicker
            case .time: timePicker
            }
        }
        if allowsTime, day != nil {
            LabeledContent("Time") {
                Button { picking = .time } label: {
                    Text(time.flatMap { BookingTime.date("2000-01-01T" + $0) }.map { $0.formatted(date: .omitted, time: .shortened) } ?? "Add time")
                }
                .buttonStyle(ValueButtonStyle(empty: time == nil))
            }
        }
    }

    private var dayPicker: some View {
        NavigationStack {
            DatePicker("Date", selection: Binding(
                get: { (day ?? suggestedDay).flatMap(Fmt.day) ?? Date() },
                set: { value = Fmt.iso($0) + (time.map { "T" + $0 } ?? "") }),
                displayedComponents: .date)
                .datePickerStyle(.graphical)
                .tint(Theme.accent)
                .padding(.horizontal)
                .navigationTitle(label)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    if value != nil {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Remove", role: .destructive) { value = nil; picking = nil }
                        }
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") {
                            if value == nil { value = suggestedDay ?? Fmt.iso(Date()) }
                            picking = nil
                        }
                    }
                }
                .onAppear { if value == nil { value = suggestedDay ?? Fmt.iso(Date()) } }
        }
        .presentationDetents([.medium, .large])
    }

    private var timePicker: some View {
        NavigationStack {
            DatePicker("Time", selection: Binding(
                get: { BookingTime.date("2000-01-01T" + (time ?? "19:00")) ?? Date() },
                set: { value = (day ?? Fmt.iso(Date())) + "T" + String(BookingTime.string($0, time: true).suffix(5)) }),
                displayedComponents: .hourAndMinute)
                .datePickerStyle(.wheel)
                .labelsHidden()
                .frame(maxWidth: .infinity)
                .navigationTitle("Time")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    if time != nil {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("No time") { value = day; picking = nil }
                        }
                    }
                    ToolbarItem(placement: .confirmationAction) { Button("Done") { picking = nil } }
                }
                .onAppear { if time == nil, let day { value = day + "T19:00" } }
        }
        .presentationDetents([.height(320)])
    }
}

/// The value side of a form row: a soft pill with the date or time, or "Add …" in the link colour.
private struct ValueButtonStyle: ButtonStyle {
    let empty: Bool
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(empty ? .semibold : .regular))
            .foregroundStyle(empty ? Theme.link : Theme.label)
            .padding(.horizontal, 12).padding(.vertical, 6)
            .background(empty ? Color.clear : Theme.fill, in: Capsule())
            .opacity(configuration.isPressed ? 0.6 : 1)
    }
}
