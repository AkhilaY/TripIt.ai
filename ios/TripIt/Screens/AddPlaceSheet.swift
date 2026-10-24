import PhotosUI
import SwiftUI

/// Add to your library: paste a TikTok, Instagram or YouTube link, a Google or Apple Maps link,
/// search for a place by name, or pick screenshots.
struct AddPlaceSheet: View {
    let request: Router.AddRequest
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var tripId: String?
    @State private var city = ""
    @State private var results: [PlaceCandidate] = []
    @State private var searching = false
    @State private var busy = false
    @State private var error: String?
    @State private var shots: [PhotosPickerItem] = []
    @FocusState private var focused: Bool

    private enum Kind { case reel, map, search, empty }

    private var kind: Kind {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return .empty }
        guard let url = LinkExtractor.firstURL(in: t), let host = url.host?.lowercased() else { return .search }
        if ["tiktok.com", "instagram.com", "instagr.am", "youtube.com", "youtu.be"].contains(where: { host == $0 || host.hasSuffix("." + $0) }) {
            return .reel
        }
        if host.hasPrefix("maps.") || host == "goo.gl" || host.hasSuffix("maps.apple") || (host.contains("google.") && url.path.hasPrefix("/maps")) {
            return .map
        }
        return .search
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        Image(systemName: "magnifyingglass").foregroundStyle(Theme.secondary)
                        TextField("Paste a link, or search for a place", text: $text, axis: .vertical)
                            .focused($focused)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .submitLabel(.search)
                        if !text.isEmpty {
                            Button { text = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.tertiary) }
                                .buttonStyle(.borderless)
                        }
                    }
                    if !store.trips.isEmpty {
                        Picker("Also add to", selection: $tripId) {
                            Text("Just save it").tag(String?.none)
                            ForEach(store.trips) { Text($0.name).tag(String?.some($0.id)) }
                        }
                    }
                } footer: {
                    if kind == .empty {
                        Text("Share posts straight from TikTok or Instagram with Share → Travel Edit.")
                    }
                }

                if let error {
                    Text(error).foregroundStyle(Theme.danger)
                }

                switch kind {
                case .reel:
                    Section {
                        Button { Task { await importReel() } } label: {
                            action("sparkles", Theme.gold, "Save the places in this post",
                                   "The Travel Edit watches it and finds every place mentioned. About a minute.")
                        }
                    }
                case .map:
                    Section {
                        Button { Task { await addMapLink() } } label: {
                            action("map.fill", Theme.green, "Add this place", "From the Google Maps or Apple Maps link")
                        }
                    }
                case .search:
                    Section {
                        if searching && results.isEmpty { HStack { ProgressView(); Text("Searching…").foregroundStyle(Theme.secondary) } }
                        ForEach(results) { result in
                            Button { Task { await add(result) } } label: {
                                HStack(spacing: 12) {
                                    CategoryTile(category: Category(result.category))
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(result.name).foregroundStyle(Theme.label)
                                        if let address = result.address {
                                            Text(address).font(.caption).foregroundStyle(Theme.secondary).lineLimit(2)
                                        }
                                    }
                                    Spacer()
                                    Image(systemName: "plus.circle.fill").foregroundStyle(Theme.link)
                                }
                            }
                        }
                        let name = text.trimmingCharacters(in: .whitespacesAndNewlines)
                        if name.count >= 2 && !searching {
                            if tripId == nil {
                                TextField("City (to add “\(name)” by name)", text: $city)
                            }
                            Button { Task { await addByName(name) } } label: {
                                Label("Add “\(name)” by name", systemImage: "text.badge.plus")
                            }
                            .disabled(tripId == nil && city.trimmingCharacters(in: .whitespaces).isEmpty)
                        }
                    } header: {
                        if !results.isEmpty { Text("Places") }
                    }
                case .empty:
                    Section {
                        PhotosPicker(selection: $shots, maxSelectionCount: 10, matching: .images) {
                            action("photo.on.rectangle.angled", Theme.indigo, "Screenshots",
                                   "Of a post, a map or an article. The Travel Edit finds the places in them.")
                        }
                        PasteButton(payloadType: String.self) { strings in
                            if let first = strings.first { text = first }
                        }
                        .labelStyle(.titleAndIcon)
                    }
                }
            }
            .tripBackground()
            .navigationTitle("Add")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .overlay { if busy { ProgressView().controlSize(.large).padding(24).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16)) } }
            .disabled(busy)
            .task(id: text) { await search() }
            .onChange(of: shots) { _, items in if !items.isEmpty { Task { await sendShots(items) } } }
            .onAppear {
                text = request.text
                tripId = request.tripId
                if request.text.isEmpty { focused = true }
            }
        }
    }

    private func action(_ symbol: String, _ color: Color, _ title: String, _ subtitle: String) -> some View {
        HStack(spacing: 12) {
            SymbolTile(symbol: symbol, color: color, size: 38)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.body.weight(.semibold)).foregroundStyle(Theme.label)
                Text(subtitle).font(.caption).foregroundStyle(Theme.secondary)
            }
        }
    }

    private func search() async {
        error = nil
        let query = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard kind == .search, query.count >= 2 else { results = []; return }
        searching = true
        try? await Task.sleep(for: .milliseconds(400))
        guard !Task.isCancelled else { return }
        do {
            results = try await API.shared.post("/v1/places/search", ["query": query, "trip_id": tripId])
        } catch is CancellationError {
            return
        } catch {
            results = []
        }
        searching = false
    }

    private func finish(_ message: String) {
        store.show(message)
        dismiss()
    }

    private func importReel() async {
        busy = true
        do {
            try await store.importLink(text)
            finish("Finding the places in that post…")
        } catch { self.error = error.localizedDescription }
        busy = false
    }

    private func addMapLink() async {
        busy = true
        do {
            let result: AddPlaceResult = try await API.shared.post("/v1/places/from-link", ["url": text, "trip_id": tripId, "folder_id": request.folderId])
            await store.add(result)
            if let tripId { _ = try? await store.loadTrip(tripId) }
            dismiss()
        } catch { self.error = error.localizedDescription }
        busy = false
    }

    private func add(_ candidate: PlaceCandidate) async {
        busy = true
        do {
            let result: AddPlaceResult = try await API.shared.post("/v1/places",
                                                                   ["candidate_id": candidate.candidateId, "trip_id": tripId, "folder_id": request.folderId])
            await store.add(result)
            if let tripId { _ = try? await store.loadTrip(tripId) }
            dismiss()
        } catch { self.error = error.localizedDescription }
        busy = false
    }

    private func addByName(_ name: String) async {
        busy = true
        do {
            let result: AddPlaceResult = try await API.shared.post("/v1/places", [
                "name": name, "trip_id": tripId, "folder_id": request.folderId,
                "city": tripId == nil ? city.trimmingCharacters(in: .whitespaces) : nil,
            ])
            await store.add(result)
            if let tripId { _ = try? await store.loadTrip(tripId) }
            dismiss()
        } catch { self.error = error.localizedDescription }
        busy = false
    }

    private func sendShots(_ items: [PhotosPickerItem]) async {
        busy = true
        var jpegs: [Data] = []
        for item in items {
            guard let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) else { continue }
            if let jpeg = image.scaled(maxSide: 2000).jpegData(compressionQuality: 0.8) { jpegs.append(jpeg) }
        }
        shots = []
        guard !jpegs.isEmpty else { busy = false; error = "Couldn't read those images."; return }
        do {
            try await store.importScreenshots(jpegs, note: nil)
            finish("Finding the places in your screenshots…")
        } catch { self.error = error.localizedDescription }
        busy = false
    }
}

extension UIImage {
    /// A smaller copy whose longest side is at most `maxSide` points (screenshots are sent as JPEGs under 6 MB).
    func scaled(maxSide: CGFloat) -> UIImage {
        let longest = max(size.width, size.height)
        guard longest > maxSide else { return self }
        let scale = maxSide / longest
        let target = CGSize(width: size.width * scale, height: size.height * scale)
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        return UIGraphicsImageRenderer(size: target, format: format).image { _ in draw(in: CGRect(origin: .zero, size: target)) }
    }
}
