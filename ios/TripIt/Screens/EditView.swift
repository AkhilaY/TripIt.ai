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
                if let cover = edit.coverPhoto {
                    RemoteImage(url: cover.url(width: 1200)) { Theme.raised }
                        .frame(height: 230)
                        .frame(maxWidth: .infinity)
                        .clipped()
                }
                VStack(alignment: .leading, spacing: 8) {
                    Eyebrow(text: "The edit · \(trip?.name ?? store.trips.first { $0.id == tripId }?.name ?? "")")
                    Text(edit.title).font(Theme.serif(30)).foregroundStyle(Theme.label)
                    if !edit.dek.isEmpty {
                        Text(edit.dek).font(.body).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                    Text(byline(edit)).font(.footnote).foregroundStyle(Theme.tertiary)
                    keepButton(edit).padding(.top, 6)
                }
                .padding(.horizontal, 20)
                .padding(.top, 18)
                VStack(spacing: 14) {
                    ForEach(edit.entries.indices, id: \.self) { index in
                        entry(edit.entries[index], number: index + 1, edit: edit)
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
            Text("Kept as a list, even after the edits refresh.").font(.footnote).foregroundStyle(Theme.secondary)
        } else {
            Button { Task { await keep(edit) } } label: {
                if keeping { ProgressView() } else { Label("Save this edit", systemImage: "bookmark") }
            }
            .buttonStyle(PrimaryButtonStyle(compact: true)).fixedSize()
            .disabled(keeping)
            Text("Edits refresh daily. Save this one to keep it as a list.").font(.footnote).foregroundStyle(Theme.secondary)
        }
    }

    private func entry(_ item: EditItem, number: Int, edit: TripEdit) -> some View {
        let saved = item.saved ? item.placeId.flatMap { store.place($0) } : nil
        return Card {
            Button { open(item, edit: edit) } label: {
                VStack(alignment: .leading, spacing: 0) {
                    if let photo = item.photo {
                        RemoteImage(url: photo.url(width: 900)) { Theme.raised }
                            .frame(height: 170)
                            .frame(maxWidth: .infinity)
                            .clipped()
                    }
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text(String(format: "%02d", number)).font(Theme.serif(22)).foregroundStyle(Theme.gold)
                            Eyebrow(text: [Category(item.category).label, item.neighborhood].compactMap { $0 }.joined(separator: " · "),
                                    color: Theme.secondary)
                        }
                        HStack(spacing: 5) {
                            Text(item.name).font(Theme.serif(21)).foregroundStyle(Theme.label)
                            if saved?.mustDo == true { Image(systemName: "star.fill").font(.caption).foregroundStyle(Theme.gold) }
                        }
                        if !item.note.isEmpty {
                            Text(item.note).font(.subheadline).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                        if !item.saved, let rating = item.rating {
                            Text(String(format: "★ %.1f", rating) + (item.ratingCount.map { " · \(Fmt.count($0)) reviews" } ?? ""))
                                .font(.footnote).foregroundStyle(Theme.secondary)
                        }
                        if let saved { OpenStatusText(hours: saved.openingHours).font(.footnote) }
                    }
                    .padding(14)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            Divider().overlay(Theme.divider)
            HStack(spacing: 12) {
                if let source = item.source {
                    if let link = source.url, let url = URL(string: link) {
                        Button { Links.open(url) } label: { Text("via \(source.name)").lineLimit(1) }
                            .font(.footnote.weight(.semibold)).foregroundStyle(Theme.link)
                    } else {
                        Text(item.saved ? source.name : "via \(source.name)").font(.footnote).foregroundStyle(Theme.secondary).lineLimit(1)
                    }
                }
                Spacer(minLength: 8)
                if item.saved {
                    Label("In your library", systemImage: "checkmark").font(.footnote.weight(.semibold)).foregroundStyle(Theme.ok)
                } else {
                    Button { Task { await save(item, edit: edit) } } label: {
                        if saving.contains(item.id) { ProgressView().controlSize(.small) } else { Label("Save", systemImage: "bookmark") }
                    }
                    .buttonStyle(PrimaryButtonStyle(tinted: true, compact: true)).fixedSize()
                    .disabled(saving.contains(item.id))
                }
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 14).padding(.vertical, 10)
        }
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
