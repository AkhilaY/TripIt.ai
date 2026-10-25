import SwiftUI

/// A trip's packing list: made for its days, the weather and your taste, imported from a list you have, or your own.
/// Tick things off as you pack; after the trip, mark what you didn't use and it's left off next time.
struct PackingView: View {
    let tripId: String
    @Environment(Store.self) private var store
    @State private var list: PackingList?
    @State private var loaded = false
    @State private var error: String?
    @State private var making = false
    @State private var sheet: Sheet?
    @State private var acting: PackingItem?

    enum Sheet: String, Identifiable {
        case add, importList
        var id: String { rawValue }
    }

    struct PackGroup: Identifiable {
        let id: String
        let label: String
    }

    static let groups = [
        PackGroup(id: "clothes", label: "Clothes"), PackGroup(id: "shoes", label: "Shoes & accessories"),
        PackGroup(id: "toiletries", label: "Toiletries & health"), PackGroup(id: "tech", label: "Tech & power"),
        PackGroup(id: "documents", label: "Documents & money"), PackGroup(id: "daybag", label: "Day bag"), PackGroup(id: "other", label: "Other"),
    ]

    private var trip: Trip? { store.trips.first { $0.id == tripId } }

    var body: some View {
        List {
            if !loaded {
                ProgressView().frame(maxWidth: .infinity).listRowBackground(Color.clear)
            } else if let error {
                EmptyState(symbol: "wifi.slash", title: "Couldn't load the list", text: error) {
                    Button("Try again") { Task { await load() } }.buttonStyle(PrimaryButtonStyle(tinted: true)).frame(maxWidth: 200)
                }
                .listRowBackground(Color.clear)
            } else if making {
                VStack(spacing: 12) {
                    ProgressView().controlSize(.large)
                    Text("Packing for \(trip?.city ?? "your trip")").font(Theme.serif(22))
                    Text("Looking at your days, the weather and your taste. This can take up to a minute.")
                        .font(.subheadline).foregroundStyle(Theme.secondary).multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity).padding(.vertical, 40)
                .listRowBackground(Color.clear)
            } else if let list {
                content(list)
            } else {
                start
            }
        }
        .listStyle(.insetGrouped)
        .tripBackground()
        .navigationTitle("Packing")
        .task { await load() }
        .refreshable { await load() }
        .sheet(item: $sheet) { which in
            switch which {
            case .add: AddPackingItem(tripId: tripId) { list = $0 }
            case .importList: ImportPackingList(tripId: tripId) { list = $0 }
            }
        }
        .confirmationDialog(acting?.text ?? "", isPresented: Binding(get: { acting != nil }, set: { if !$0 { acting = nil } }),
                            titleVisibility: .visible, presenting: acting) { item in
            Button(item.unused ? "I did use this" : "I didn't use this") {
                Task { await change(item, ["unused": !item.unused], message: item.unused ? "Noted" : "Noted. It's left off next time") }
            }
            Button("Delete", role: .destructive) { Task { await remove(item) } }
        }
    }

    // MARK: No list yet

    @ViewBuilder private var start: some View {
        EmptyState(symbol: "suitcase.fill", color: Theme.teal, title: "A packing list for this trip",
                   text: "Write your own, bring one you already have, or let it be made for your days and the weather.")
            .listRowBackground(Color.clear)
        Section {
            Button { Task { await make([:]) } } label: {
                option("sparkles", Theme.gold, "Make it for me", makeSubtitle)
            }
            Button { sheet = .importList } label: {
                option("doc.on.doc", Theme.blue, "Import a list", "Paste one from Notes or anywhere, or copy another trip's list")
            }
            Button { sheet = .add } label: {
                option("plus", Theme.gray, "Start my own", "Add things one at a time")
            }
        } footer: {
            if trip?.startDate == nil {
                Text("Add a start date to your trip and the list it makes for you uses the weather too.")
            }
        }
    }

    private var makeSubtitle: String {
        let from = (trip?.dayCount ?? 0) > 0 ? Fmt.plural(trip?.dayCount ?? 0, "planned day") : "saved places"
        return "From your \(from)\(trip?.startDate != nil ? ", the weather on your dates" : "") and your taste, with a reason for each thing"
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

    // MARK: The list

    @ViewBuilder private func content(_ list: PackingList) -> some View {
        let packed = list.items.filter(\.packed).count
        Section {
            HStack {
                Label(byline(list), systemImage: list.generatedBy == "claude" ? "sparkles" : "checklist")
                    .font(.footnote).foregroundStyle(Theme.secondary)
                Spacer()
                Menu {
                    Button { sheet = .importList } label: { Label("Import a list", systemImage: "doc.on.doc") }
                    Button { Task { await make([:]) } } label: {
                        Label(list.generatedBy == "manual" ? "Add suggestions" : "Make it again", systemImage: "sparkles")
                    }
                    Button { Task { await make(["carry_on_only": !list.carryOnOnly]) } } label: {
                        Label(list.carryOnOnly ? "Checked bag too" : "Carry-on only", systemImage: "suitcase.rolling")
                    }
                } label: { Image(systemName: "ellipsis.circle").font(.body) }
                    .accessibilityLabel("List options")
            }
            if list.carryOnOnly {
                Label("Carry-on only", systemImage: "suitcase.rolling").font(.footnote.weight(.semibold)).foregroundStyle(Theme.teal)
            }
            if let notes = list.notes, !notes.isEmpty {
                Text(notes).font(.subheadline).foregroundStyle(Theme.label)
            }
            VStack(alignment: .leading, spacing: 6) {
                ProgressView(value: list.items.isEmpty ? 0 : Double(packed) / Double(list.items.count)).tint(Theme.ok)
                Text("\(packed) of \(list.items.count) packed").font(.footnote).foregroundStyle(Theme.secondary)
            }
        }
        if !list.weather.isEmpty { weather(list.weather) }
        ForEach(Self.groups) { group in
            let items = list.items.filter { $0.group == group.id }
            if !items.isEmpty {
                Section {
                    ForEach(items) { item in row(item) }
                } header: {
                    HStack {
                        Text(group.label).font(Theme.serif(19)).foregroundStyle(Theme.label).textCase(nil)
                        Text("\(items.count)").foregroundStyle(Theme.secondary)
                    }
                }
            }
        }
        Section {
            Button { sheet = .add } label: { Label("Add an item", systemImage: "plus") }
        } footer: {
            Text("Back from the trip? Swipe or tap ••• on anything you didn't use and it's left off next time. Things you add stay when the list is made again.")
        }
    }

    private func byline(_ list: PackingList) -> String {
        switch list.generatedBy {
        case "claude": "Made for this trip"
        case "manual": "Your list"
        default: "A basic list"
        }
    }

    private func weather(_ days: [WeatherDay]) -> some View {
        Section {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 10) {
                    ForEach(days, id: \.day) { w in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(Fmt.shortDay(w.date)).font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
                            Text("\(TravelHome.temperature(w.tempMax))° / \(TravelHome.temperature(w.tempMin))°").font(.subheadline.weight(.semibold))
                            Text(w.summary + (w.rainChance.map { " · \($0)%" } ?? "")).font(.caption).foregroundStyle(Theme.secondary).lineLimit(1)
                        }
                        .padding(10)
                        .frame(minWidth: 110, alignment: .leading)
                        .background(Theme.fill, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                }
            }
            .listRowInsets(EdgeInsets(top: 8, leading: 12, bottom: 8, trailing: 12))
        } header: {
            Label("Weather", systemImage: "sun.max").textCase(nil)
        } footer: {
            Text(days.allSatisfy { $0.source == "typical" }
                 ? "Too far ahead for a forecast, so these are last year's conditions for the same dates."
                 : "Forecast. It can change, so check again before you pack.")
        }
    }

    private func row(_ item: PackingItem) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Button { Task { await change(item, ["packed": !item.packed]) } } label: {
                Image(systemName: item.packed ? "checkmark.circle.fill" : "circle")
                    .font(.title3).foregroundStyle(item.packed ? Theme.ok : Theme.tertiary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(item.packed ? "Packed: \(item.text)" : "Not packed: \(item.text)")
            VStack(alignment: .leading, spacing: 3) {
                Text(item.text).strikethrough(item.packed).foregroundStyle(item.unused ? Theme.secondary : Theme.label)
                if item.reason != nil || !item.days.isEmpty {
                    HStack(spacing: 6) {
                        if let reason = item.reason { Text(reason).font(.footnote).foregroundStyle(Theme.secondary) }
                        if !item.days.isEmpty { Chip(text: Self.dayList(item.days)) }
                    }
                }
                if item.unused { Text("Didn't use it last time").font(.caption).foregroundStyle(Theme.tertiary) }
            }
            Spacer(minLength: 4)
            Button { acting = item } label: { Image(systemName: "ellipsis").foregroundStyle(Theme.secondary).frame(width: 28, height: 28) }
                .buttonStyle(.plain)
                .accessibilityLabel("Options for \(item.text)")
        }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive) { Task { await remove(item) } } label: { Label("Delete", systemImage: "trash") }
            Button { Task { await change(item, ["unused": !item.unused], message: item.unused ? "Noted" : "Noted. It's left off next time") } } label: {
                Label(item.unused ? "Used it" : "Didn't use", systemImage: "arrow.uturn.backward")
            }
            .tint(Theme.gray)
        }
    }

    static func dayList(_ days: [Int]) -> String {
        guard let first = days.first, let last = days.last else { return "" }
        if days.count > 3 { return "Days \(first)–\(last)" }
        return (days.count > 1 ? "Days " : "Day ") + days.map(String.init).joined(separator: ", ")
    }

    // MARK: Calls

    private func load() async {
        do {
            list = try await API.shared.get("/v1/trips/\(tripId)/packing", as: PackingList?.self)
            error = nil
        } catch is CancellationError {
        } catch { self.error = error.localizedDescription }
        loaded = true
    }

    private func make(_ body: [String: Any?]) async {
        making = true
        defer { making = false }
        do { list = try await API.shared.post("/v1/trips/\(tripId)/packing", body) } catch { store.fail(error) }
    }

    private func change(_ item: PackingItem, _ body: [String: Any?], message: String? = nil) async {
        if body["packed"] != nil, var copy = list, let i = copy.items.firstIndex(where: { $0.id == item.id }) {
            copy.items[i].packed.toggle()  // instant; the server catches up
            list = copy
        }
        do {
            list = try await API.shared.patch("/v1/trips/\(tripId)/packing/items/\(item.id)", body)
            if let message { store.show(message) }
        } catch {
            store.fail(error)
            await load()
        }
    }

    private func remove(_ item: PackingItem) async {
        do { list = try await API.shared.delete("/v1/trips/\(tripId)/packing/items/\(item.id)") } catch { store.fail(error) }
    }
}

/// One more thing for the list, and which group it goes in.
private struct AddPackingItem: View {
    let tripId: String
    let onDone: (PackingList) -> Void
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var group = "other"

    var body: some View {
        NavigationStack {
            Form {
                TextField("e.g. Camera charger", text: $text)
                Picker("Group", selection: $group) {
                    ForEach(PackingView.groups) { Text($0.label).tag($0.id) }
                }
            }
            .tripBackground()
            .navigationTitle("Add an item")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") {
                        Task {
                            do {
                                let list: PackingList = try await API.shared.post("/v1/trips/\(tripId)/packing/items",
                                                                                ["text": text.trimmingCharacters(in: .whitespaces), "group": group])
                                onDone(list)
                                dismiss()
                            } catch { store.fail(error) }
                        }
                    }
                    .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .presentationDetents([.medium])
    }
}

/// Bring a list you already have: paste it (one thing per line) or copy another trip's.
private struct ImportPackingList: View {
    let tripId: String
    let onDone: (PackingList) -> Void
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var from = ""
    @State private var working = false

    var body: some View {
        let others = store.realTrips.filter { $0.id != tripId }
        NavigationStack {
            Form {
                Section {
                    TextEditor(text: $text)
                        .frame(minHeight: 180)
                        .overlay(alignment: .topLeading) {
                            if text.isEmpty {
                                Text("Paste your list, one thing per line\nPassport\nPhone charger\nSunscreen")
                                    .foregroundStyle(Theme.tertiary).padding(.top, 8).padding(.leading, 5).allowsHitTesting(false)
                            }
                        }
                } footer: {
                    Text("Bullets, checkboxes and numbers are tidied away, and each thing goes in the right group.")
                }
                if !others.isEmpty {
                    Section {
                        Picker("Or copy from a trip", selection: $from) {
                            Text("Choose…").tag("")
                            ForEach(others) { Text($0.name).tag($0.id) }
                        }
                    }
                }
            }
            .tripBackground()
            .navigationTitle("Import a list")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if working { ProgressView() } else {
                        Button("Import") { Task { await importList() } }
                            .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && from.isEmpty)
                    }
                }
            }
        }
    }

    private func importList() async {
        working = true
        defer { working = false }
        do {
            let list: PackingList = try await API.shared.post("/v1/trips/\(tripId)/packing/start", [
                "text": text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : text,
                "copy_from": from.isEmpty ? nil : from,
            ])
            onDone(list)
            store.show("List imported")
            dismiss()
        } catch { store.fail(error) }
    }
}
