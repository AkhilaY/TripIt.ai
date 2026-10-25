import SwiftUI

/// One message in a conversation with the concierge, kept on this phone (per trip).
struct ChatMessage: Codable, Hashable, Identifiable {
    var id = UUID()
    var role: String  // user or assistant
    var content: String
    var placeIds: [String] = []
    var actions: [ProposedAction] = []
    var applied = false
    var dismissed = false
    var error = false
}

/// The Concierge tab: ask about your saved places, plan an evening, or rework a day. It proposes changes and
/// nothing moves until you apply them.
struct ConciergeView: View {
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @State private var location = Location.shared
    @State private var tripId: String?
    @State private var chosen = false
    @State private var messages: [ChatMessage] = []
    @State private var draft = ""
    @State private var busy = false
    @State private var applying: UUID?
    @FocusState private var typing: Bool

    static let prompts = ["Plan my evening", "Where should I eat near my next stop?", "What's worth booking ahead?",
                          "Make tomorrow more relaxed", "Rainy day ideas from my saves"]

    private var trip: TripDetail? { tripId.flatMap { store.tripDetails[$0] } }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    header
                    if messages.isEmpty {
                        welcome
                    } else {
                        ForEach(messages.indices, id: \.self) { i in
                            bubble(messages[i], index: i).padding(.top, 12)
                        }
                        if busy {
                            HStack(spacing: 8) { ProgressView(); Text("Thinking…").font(.subheadline).foregroundStyle(Theme.secondary) }
                                .padding(.top, 12)
                        }
                    }
                    Color.clear.frame(height: 1).id("end")
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 20)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Theme.background.ignoresSafeArea())
            .safeAreaInset(edge: .bottom) { composer }
            .onChange(of: messages.count) { _, _ in withAnimation { proxy.scrollTo("end", anchor: .bottom) } }
            .onChange(of: busy) { _, _ in withAnimation { proxy.scrollTo("end", anchor: .bottom) } }
        }
        .toolbar(.hidden, for: .navigationBar)
        .task(id: store.loaded) {
            if !chosen {
                tripId = store.activeTrip?.trip.id ?? store.realTrips.first?.id
            }
            messages = Self.read(tripId)
            if let tripId, store.tripDetails[tripId] == nil { _ = try? await store.loadTrip(tripId) }
            location.request()
        }
    }

    // MARK: Header and trip

    private var header: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Spacer()
                if !messages.isEmpty {
                    RoundIconButton(symbol: "square.and.pencil", label: "New conversation") {
                        messages = []
                        Self.write(tripId, [])
                    }
                }
                ProfileButton()
            }
            .padding(.top, 8)
            Text("Concierge").font(Theme.serif(32)).foregroundStyle(Theme.label).padding(.top, 8)
            Text("Your personal travel assistant").font(.subheadline).foregroundStyle(Theme.secondary)
            if !store.realTrips.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(store.realTrips) { t in
                            FilterChip(label: t.name, isOn: tripId == t.id) { choose(t.id) }
                        }
                        FilterChip(label: "All trips", isOn: tripId == nil) { choose(nil) }
                    }
                }
                .padding(.top, 12)
            }
        }
    }

    private func choose(_ id: String?) {
        chosen = true
        tripId = id
        messages = Self.read(id)
        if let id, store.tripDetails[id] == nil { Task { _ = try? await store.loadTrip(id) } }
    }

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 12) {
            Eyebrow(text: "At your service")
            Text("Ask about your saved places, plan an evening, or rework a day. I suggest changes; nothing moves until you confirm.")
                .font(Theme.serif(20)).foregroundStyle(Theme.label).fixedSize(horizontal: false, vertical: true)
            FlowLayout(spacing: 8) {
                ForEach(Self.prompts, id: \.self) { q in
                    Button { Task { await send(q) } } label: {
                        Text(q).font(.subheadline).foregroundStyle(Theme.label)
                            .padding(.horizontal, 12).padding(.vertical, 8)
                            .background(Theme.cell, in: Capsule())
                            .overlay(Capsule().strokeBorder(Theme.border))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(.top, 28)
    }

    // MARK: Messages

    @ViewBuilder private func bubble(_ m: ChatMessage, index: Int) -> some View {
        if m.role == "user" {
            HStack {
                Spacer(minLength: 48)
                Text(m.content).font(.body).foregroundStyle(Theme.accentInk)
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(Theme.accent, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            }
        } else {
            VStack(alignment: .leading, spacing: 10) {
                Text(m.error ? "Couldn't answer" : "Concierge").font(.caption.weight(.semibold)).foregroundStyle(m.error ? Theme.warn : Theme.gold)
                Text(m.content).font(.body).foregroundStyle(Theme.label).fixedSize(horizontal: false, vertical: true)
                let places = m.placeIds.compactMap { id in trip?.places.first { $0.id == id } ?? store.place(id) }
                ForEach(places) { p in
                    NavigationLink(value: Route.place(id: p.id, tripId: tripId)) {
                        HStack(spacing: 10) {
                            PlaceThumb(place: p, size: 40)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(p.name).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                                Text([Category(p.category).label, p.neighborhood].compactMap { $0 }.joined(separator: " · "))
                                    .font(.caption).foregroundStyle(Theme.secondary)
                            }
                            Spacer(minLength: 0)
                            Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(Theme.quiet)
                        }
                        .padding(8)
                        .background(Theme.fill, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
                if !m.actions.isEmpty { proposal(m, index: index) }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.cell, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Theme.border))
        }
    }

    private func proposal(_ m: ChatMessage, index: Int) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Eyebrow(text: "Proposed changes", color: Theme.secondary)
            ForEach(m.actions, id: \.self) { a in
                Label(a.label, systemImage: "arrow.right.circle").font(.subheadline).foregroundStyle(Theme.label)
            }
            if m.applied {
                Text("Applied to your trip").font(.footnote).foregroundStyle(Theme.ok)
            } else if m.dismissed {
                Text("Left as it was").font(.footnote).foregroundStyle(Theme.secondary)
            } else {
                HStack(spacing: 14) {
                    Button { Task { await apply(index) } } label: {
                        if applying == m.id { ProgressView() } else { Text("Apply") }
                    }
                    .buttonStyle(PrimaryButtonStyle(compact: true)).fixedSize()
                    .disabled(applying != nil || tripId == nil)
                    Button("Not now") {
                        messages[index].dismissed = true
                        Self.write(tripId, messages)
                    }
                    .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.link)
                }
                .padding(.top, 4)
            }
        }
        .padding(12)
        .background(Theme.fill, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    // MARK: Composer

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("Ask your concierge…", text: $draft, axis: .vertical)
                .lineLimit(1...5)
                .focused($typing)
                .submitLabel(.send)
                .onSubmit { Task { await send(draft) } }
                .padding(.horizontal, 14).padding(.vertical, 10)
                .background(Theme.cell, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Theme.border))
            Button { Task { await send(draft) } } label: {
                Image(systemName: "arrow.up").font(.body.weight(.semibold)).foregroundStyle(Theme.accentInk)
                    .frame(width: 40, height: 40)
                    .background(Theme.accent, in: Circle())
            }
            .buttonStyle(.plain)
            .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || busy)
            .accessibilityLabel("Send")
        }
        .padding(.horizontal, 16).padding(.vertical, 8)
        .background(.bar)
    }

    // MARK: Talking to the concierge

    private func send(_ text: String) async {
        let question = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty, !busy else { return }
        draft = ""
        messages.append(ChatMessage(role: "user", content: question))
        Self.write(tripId, messages)
        busy = true
        defer { busy = false }
        let history: [[String: String]] = messages.filter { !$0.error }.suffix(20).map { ["role": $0.role, "content": $0.content] }
        let here = location.current?.coordinate
        let now = Date()
        let clock = Calendar.current.dateComponents([.hour, .minute], from: now)
        do {
            let reply: ConciergeReply = try await API.shared.post("/v1/concierge", [
                "trip_id": tripId,
                "local_time": Fmt.iso(now) + String(format: "T%02d:%02d", clock.hour ?? 0, clock.minute ?? 0),
                "latitude": here?.latitude,
                "longitude": here?.longitude,
                "messages": history,
            ])
            messages.append(ChatMessage(role: "assistant", content: reply.reply, placeIds: reply.placeIds, actions: reply.actions))
        } catch {
            messages.append(ChatMessage(role: "assistant", content: error.localizedDescription, error: true))
        }
        Self.write(tripId, messages)
    }

    private func apply(_ index: Int) async {
        guard let tripId, messages.indices.contains(index) else { return }
        let m = messages[index]
        applying = m.id
        defer { applying = nil }
        do {
            for a in m.actions {
                switch a.type {
                case "move":
                    let _: TripDetail = try await API.shared.post("/v1/trips/\(tripId)/move", ["place_id": a.placeId, "day": a.day, "index": a.index ?? 999])
                case "must_do":
                    let _: Place = try await API.shared.patch("/v1/places/\(a.placeId)", ["must_do": a.value])
                case "visited":
                    let _: Place = try await API.shared.patch("/v1/places/\(a.placeId)", ["visited": a.value])
                case "set_time":
                    let body: [String: Any?] = (a.time ?? "").isEmpty ? ["clear_start_time": true] : ["start_time": a.time]
                    let _: Place = try await API.shared.patch("/v1/places/\(a.placeId)", body)
                default:
                    continue
                }
            }
            messages[index].applied = true
            Self.write(tripId, messages)
            _ = try? await store.loadTrip(tripId)
            await store.reloadPlaces()
            store.show("Your trip is updated")
        } catch { store.fail(error) }
    }

    // MARK: Kept on this phone

    private static func key(_ tripId: String?) -> String { "tripit.chat.\(tripId ?? "all")" }

    static func read(_ tripId: String?) -> [ChatMessage] {
        guard let data = UserDefaults.standard.data(forKey: key(tripId)) else { return [] }
        return (try? JSONDecoder().decode([ChatMessage].self, from: data)) ?? []
    }

    static func write(_ tripId: String?, _ messages: [ChatMessage]) {
        if let data = try? JSONEncoder().encode(Array(messages.suffix(40))) { UserDefaults.standard.set(data, forKey: key(tripId)) }
    }
}
