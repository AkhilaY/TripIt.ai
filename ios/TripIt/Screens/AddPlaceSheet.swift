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
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Text(request.city.map { "Save a place in \($0)" } ?? "Save a place")
                        .font(Theme.serif(28)).foregroundStyle(Theme.label)
                        .padding(.top, 4)
                    field.padding(.top, 18)
                    if kind == .empty {
                        HStack(spacing: 10) {
                            PasteButton(payloadType: String.self) { strings in
                                if let first = strings.first { text = first }
                            }
                            .labelStyle(.titleAndIcon)
                            .buttonBorderShape(.capsule)
                            .tint(Theme.accent)
                            PhotosPicker(selection: $shots, maxSelectionCount: 10, matching: .images) {
                                HStack(spacing: 6) {
                                    Image(systemName: "photo.on.rectangle").font(.system(size: 13, weight: .light))
                                    Text("Screenshots").font(Theme.text(.subheadline))
                                }
                                .foregroundStyle(Theme.label)
                                .padding(.horizontal, 14).frame(height: 36)
                                .overlay(Capsule().strokeBorder(Theme.chipBorder))
                            }
                        }
                        .padding(.top, 14)
                    } else if !store.trips.isEmpty {
                        alsoAdd.padding(.top, 12)
                    }
                    if let error {
                        Text(error).font(Theme.text(.subheadline)).foregroundStyle(Theme.danger).padding(.top, 14)
                    }
                    switch kind {
                    case .reel:
                        Button("Save the places in this post") { Task { await importReel() } }
                            .buttonStyle(PrimaryButtonStyle()).padding(.top, 24)
                    case .map:
                        Button("Add this place") { Task { await addMapLink() } }
                            .buttonStyle(PrimaryButtonStyle()).padding(.top, 24)
                    case .search:
                        resultList(text.trimmingCharacters(in: .whitespacesAndNewlines)).padding(.top, 18)
                    case .empty:
                        EmptyView()
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 32)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Theme.background.ignoresSafeArea())
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button { dismiss() } label: { Image(systemName: "xmark").font(.system(size: 14, weight: .light)) }
                        .accessibilityLabel("Close")
                }
            }
            .overlay { if busy { ProgressView().controlSize(.large).padding(24).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16)) } }
            .disabled(busy)
            .task(id: text) { await search() }
            .onChange(of: shots) { _, items in if !items.isEmpty { Task { await sendShots(items) } } }
            .onAppear {
                text = request.text
                tripId = request.tripId
                city = request.city ?? ""
                if request.text.isEmpty { focused = true }
            }
        }
    }

    private var field: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass").font(.system(size: 15, weight: .light)).foregroundStyle(Theme.secondary)
            TextField("Paste a link or search", text: $text, axis: .vertical)
                .font(Theme.text(.body))
                .focused($focused)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .submitLabel(.search)
                .lineLimit(1...3)
            if !text.isEmpty {
                Button { text = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.tertiary) }
                    .buttonStyle(.borderless)
                    .accessibilityLabel("Clear")
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .background(Theme.cell, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    /// "Also add to" as one small chip, shown once there's something to save.
    private var alsoAdd: some View {
        Menu {
            Picker("Also add to", selection: $tripId) {
                Text("Just save it").tag(String?.none)
                ForEach(store.trips) { Text($0.name).tag(String?.some($0.id)) }
            }
        } label: {
            HStack(spacing: 6) {
                Text(tripId.flatMap { id in store.trips.first { $0.id == id }?.name }.map { "Also add to \($0)" } ?? "Also add to a trip")
                    .font(Theme.text(.subheadline))
                Image(systemName: "chevron.down").font(.system(size: 11, weight: .light))
            }
            .foregroundStyle(Theme.label)
            .padding(.horizontal, 14).frame(height: 34)
            .overlay(Capsule().strokeBorder(Theme.chipBorder))
        }
    }

    @ViewBuilder private func resultList(_ name: String) -> some View {
        if searching && results.isEmpty {
            ProgressView().frame(maxWidth: .infinity).padding(.vertical, 12)
        }
        VStack(spacing: 0) {
            ForEach(results) { result in
                Button { Task { await add(result) } } label: {
                    HStack(spacing: 14) {
                        CategoryTile(category: Category(result.category), size: 44)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(result.name).font(Theme.text(.body)).foregroundStyle(Theme.label).lineLimit(1)
                            if let address = result.address {
                                Text(address).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).lineLimit(1)
                            }
                        }
                        Spacer(minLength: 8)
                        Image(systemName: "plus").font(.system(size: 15, weight: .light)).foregroundStyle(Theme.label)
                    }
                    .padding(.vertical, 12)
                    .contentShape(Rectangle())
                }
                .buttonStyle(PressStyle())
                Divider().overlay(Theme.border)
            }
        }
        if name.count >= 2 && !searching {
            if tripId == nil && request.city == nil {
                TextField("City", text: $city)
                    .font(Theme.text(.body))
                    .padding(.horizontal, 16).frame(height: 44)
                    .background(Theme.cell, in: Capsule())
                    .padding(.top, 16)
            }
            AccentTextButton(title: "Add “\(name)” by name", symbol: "plus") { Task { await addByName(name) } }
                .disabled(tripId == nil && city.trimmingCharacters(in: .whitespaces).isEmpty)
                .padding(.top, 6)
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
            results = try await API.shared.post("/v1/places/search", ["query": query, "trip_id": tripId, "city": tripId == nil ? request.city : nil])
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
        } catch let upgrade as UpgradeNeeded {
            dismiss()
            try? await Task.sleep(for: .milliseconds(600))  // one sheet at a time
            store.paywall = PaywallRequest(link: upgrade.link, message: upgrade.message)
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
