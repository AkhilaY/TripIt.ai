import SwiftUI

/// One of a trip's edits: a cover, the title and a line about it, then each place numbered, with why it's in the
/// edit and where the pick came from. Places not in your library yet can be saved one by one, or the whole edit kept
/// as a list (edits refresh daily).
struct EditView: View {
    let tripId: String
    let editId: String
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @State private var edits: TripEdits?
    @State private var error: String?
    @State private var saving: Set<String> = []
    @State private var keeping = false

    private var edit: TripEdit? { edits?.edits.first { $0.id == editId } }
    private var trip: TripDetail? { store.tripDetails[tripId] }

    var body: some View {
        Group {
            if let edit {
                content(edit)
            } else if let error {
                EmptyState(symbol: "sparkles", title: "Couldn't open this edit", text: error).frame(maxHeight: .infinity)
            } else if edits != nil {
                EmptyState(symbol: "sparkles", title: "This edit was refreshed", text: "Open the trip to see the latest ones.")
                    .frame(maxHeight: .infinity)
            } else {
                SkeletonRows().padding(20).frame(maxHeight: .infinity, alignment: .top)
            }
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle(edit?.title ?? "The edit")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func load() async {
        do {
            async let e: TripEdits = API.shared.get("/v1/trips/\(tripId)/edits")
            if trip == nil { _ = try? await store.loadTrip(tripId) }
            edits = try await e
        } catch { self.error = error.localizedDescription }
    }

    private func content(_ edit: TripEdit) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: 8) {
                    if let name = edits?.tripName, !name.isEmpty {
                        Text("Today's edit · \(name)".uppercased()).font(Theme.text(.caption2, weight: .medium)).kerning(1.8)
                            .foregroundStyle(Theme.secondary)
                    }
                    Text(edit.title).font(Theme.serif(30)).foregroundStyle(Theme.label)
                    if !edit.dek.isEmpty {
                        Text(edit.dek).font(Theme.text(.body)).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                    Text(byline(edit)).font(Theme.text(.footnote)).foregroundStyle(Theme.tertiary)
                    keepButton(edit).padding(.top, 6)
                }
                .padding(.horizontal, 20)
                .padding(.top, 18)
                // Where the places are, numbered as in the list (when at least two are on the map).
                let stops = edit.entries.enumerated().compactMap { i, item in
                    item.latitude.flatMap { lat in item.longitude.map { RouteSketch.Stop(number: i + 1, latitude: lat, longitude: $0) } }
                }
                if stops.count >= 2 {
                    RouteSketch(stops: stops).padding(.horizontal, 20).padding(.top, 22)
                }
                VStack(spacing: 0) {
                    Divider().overlay(Theme.divider)
                    ForEach(edit.entries.indices, id: \.self) { index in
                        entry(edit.entries[index], number: index + 1, edit: edit)
                        Divider().overlay(Theme.divider)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 22)
            }
            .padding(.bottom, 40)
        }
    }

    private func byline(_ edit: TripEdit) -> String {
        let by: String
        switch edits?.curatedBy {
        case "claude+web": by = "Your saves and the best of the press"
        case "claude": by = "Curated for you"
        default: by = "From your saves"
        }
        return [by, Fmt.plural(edit.entries.count, "place"), edit.newCount > 0 ? "\(edit.newCount) new to you" : nil]
            .compactMap { $0 }.joined(separator: " · ")
    }

    @ViewBuilder private func keepButton(_ edit: TripEdit) -> some View {
        if let folderId = edit.folderId {
            Button { router.push(.folder(id: folderId)) } label: { Label("Saved to your Library", systemImage: "checkmark") }
                .buttonStyle(PrimaryButtonStyle(tinted: true, compact: true)).fixedSize()
            Text("Kept as a list, even after the edits refresh.").font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
        } else {
            Button { Task { await keep(edit) } } label: {
                if keeping { ProgressView() } else { Label("Save this edit", systemImage: "bookmark") }
            }
            .buttonStyle(PrimaryButtonStyle(compact: true)).fixedSize()
            .disabled(keeping)
            Text("Edits refresh daily. Save this one to keep it as a list.").font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
        }
    }

    /// One place, like a line in a magazine's contents: a big number, the name, where, the note, then its source and
    /// whether it's saved. No photo, so nothing waits to load.
    private func entry(_ item: EditItem, number: Int, edit: TripEdit) -> some View {
        let saved = item.saved ? item.placeId.flatMap { store.place($0) } : nil
        return HStack(alignment: .top, spacing: 16) {
            Text(String(format: "%02d", number)).font(Theme.serif(30)).foregroundStyle(Theme.tertiary)
                .frame(width: 40, alignment: .leading)
            VStack(alignment: .leading, spacing: 0) {
                Button { open(item, edit: edit) } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 5) {
                            Text(item.name).font(Theme.serif(20)).foregroundStyle(Theme.label).multilineTextAlignment(.leading)
                            if saved?.mustDo == true { Image(systemName: "star.fill").font(Theme.text(.caption)).foregroundStyle(Theme.gold) }
                        }
                        let meta = [Category(item.category).label, item.neighborhood].compactMap { $0 }.joined(separator: " · ")
                        if !meta.isEmpty { Text(meta).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary) }
                        if !item.note.isEmpty {
                            Text(item.note).font(Theme.text(.subheadline)).foregroundStyle(Theme.label.opacity(0.8))
                                .fixedSize(horizontal: false, vertical: true).padding(.top, 2)
                        }
                        if !item.saved, let rating = item.rating {
                            Text(String(format: "★ %.1f", rating) + (item.ratingCount.map { " · \(Fmt.count($0)) reviews" } ?? ""))
                                .font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                        }
                        if let saved { OpenStatusText(hours: saved.openingHours).font(Theme.text(.footnote)) }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                }
                .buttonStyle(PressStyle())
                HStack(spacing: 12) {
                    if let source = item.source {
                        if let link = source.url, let url = URL(string: link) {
                            Button { Links.open(url) } label: { Text("via \(source.name)").lineLimit(1) }
                                .font(Theme.text(.footnote)).foregroundStyle(Theme.link)
                        } else {
                            Text(item.saved ? source.name : "via \(source.name)").font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).lineLimit(1)
                        }
                    }
                    Spacer(minLength: 8)
                    if item.saved {
                        Label("In your library", systemImage: "checkmark").font(Theme.text(.footnote)).foregroundStyle(Theme.ok)
                    } else {
                        Button { Task { await save(item, edit: edit) } } label: {
                            if saving.contains(item.id) { ProgressView().controlSize(.small) } else { Label("Save", systemImage: "bookmark") }
                        }
                        .buttonStyle(PrimaryButtonStyle(tinted: true, compact: true)).fixedSize()
                        .disabled(saving.contains(item.id))
                    }
                }
                .buttonStyle(PressStyle())
                .padding(.top, 10)
            }
        }
        .padding(.vertical, 18)
    }

    private func open(_ item: EditItem, edit: TripEdit) {
        if item.saved, let placeId = item.placeId {
            let onTrip = trip?.places.contains { $0.id == placeId } ?? false
            router.push(.place(id: placeId, tripId: onTrip ? tripId : nil))
        } else {
            router.push(.editPlace(tripId: tripId, editId: edit.id, entryId: item.id))
        }
    }

    private func save(_ item: EditItem, edit: TripEdit) async {
        saving.insert(item.id)
        defer { saving.remove(item.id) }
        do {
            let place: Place = try await API.shared.post("/v1/trips/\(tripId)/edits/\(edit.id)/entries/\(item.id)/save")
            edits = try? await API.shared.get("/v1/trips/\(tripId)/edits")
            await store.reloadPlaces()
            store.show("Saved \(place.name) to your library")
        } catch { store.fail(error) }
    }

    private func keep(_ edit: TripEdit) async {
        keeping = true
        defer { keeping = false }
        do {
            let folder: Folder = try await API.shared.post("/v1/trips/\(tripId)/edits/\(edit.id)/bookmark")
            edits = try? await API.shared.get("/v1/trips/\(tripId)/edits")
            await store.reloadPlaces()
            store.show("Saved as “\(folder.name)” in your Library")
        } catch { store.fail(error) }
    }
}
