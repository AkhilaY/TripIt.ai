import PhotosUI
import SwiftUI

/// A restaurant's menu, read from its website (or photos of the menu) and laid out by section.
struct MenuView: View {
    let placeId: String
    @Environment(Store.self) private var store
    @State private var menu: PlaceMenu?
    @State private var busy = false
    @State private var error: String?
    @State private var diet: String?
    @State private var shots: [PhotosPickerItem] = []
    @State private var editingSite = false
    @State private var siteText = ""

    private static let diets: [(String, String)] = [("vegetarian", "Vegetarian"), ("vegan", "Vegan"), ("gluten_free", "Gluten-free"), ("spicy", "Spicy")]

    private var place: Place? { store.place(placeId) }

    var body: some View {
        List {
            if let error {
                Text(error).foregroundStyle(Theme.danger)
            }
            if busy {
                VStack(spacing: 12) {
                    ProgressView().controlSize(.large)
                    Text("Looking for the menu").font(Theme.serif(22))
                    Text("Checking \(place?.website != nil ? "the website" : "what's online") and reading it for you. This can take up to a minute.")
                        .font(.subheadline).foregroundStyle(Theme.secondary).multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 40)
                .listRowBackground(Color.clear)
            } else if let menu {
                switch menu.status {
                case "found": found(menu)
                case "none": notFound(menu)
                default: unknown
                }
            } else {
                ProgressView().frame(maxWidth: .infinity).listRowBackground(Color.clear)
            }
        }
        .tripBackground()
        .navigationTitle(place.map { "Menu · \($0.name)" } ?? "Menu")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .onChange(of: shots) { _, items in if !items.isEmpty { Task { await upload(items) } } }
        .alert("The restaurant's website", isPresented: $editingSite) {
            TextField("e.g. restaurant.com", text: $siteText)
                .textInputAutocapitalization(.never).keyboardType(.URL).autocorrectionDisabled()
            Button("Cancel", role: .cancel) {}
            Button("Find the menu") { Task { await setWebsite() } }
        } message: {
            Text("The Travel Edit looks there for the menu.")
        }
    }

    // MARK: States

    private var unknown: some View {
        EmptyState(symbol: "menucard.fill", color: Theme.accent, title: "See the menu",
                   text: "We'll look for it \(place?.website != nil ? "on the website" : "online") and lay it out neatly here. If it's only on Google, a screenshot works too.") {
            VStack(spacing: 10) {
                Button { Task { await find(refresh: false) } } label: { Label("Find the menu", systemImage: "magnifyingglass") }
                    .buttonStyle(PrimaryButtonStyle())
                extraButtons
            }
            .frame(maxWidth: 280)
        }
        .listRowBackground(Color.clear)
    }

    @ViewBuilder private func notFound(_ menu: PlaceMenu) -> some View {
        EmptyState(symbol: "menucard", title: "No menu found",
                   text: "We couldn't find a menu we could read. Some places only post theirs on Instagram or a delivery app. Seen it on Google? Screenshot the menu there and add it here.") {
            VStack(spacing: 10) {
                Button("Try again") { Task { await find(refresh: true) } }.buttonStyle(PrimaryButtonStyle(tinted: true))
                extraButtons
            }
            .frame(maxWidth: 280)
        }
        .listRowBackground(Color.clear)
        if !menu.trace.isEmpty {
            Section("What we tried") {
                ForEach(Array(menu.trace.enumerated()), id: \.offset) { _, line in
                    Text(line).font(.footnote).foregroundStyle(Theme.secondary)
                }
            }
        }
    }

    private var extraButtons: some View {
        VStack(spacing: 8) {
            PhotosPicker(selection: $shots, maxSelectionCount: 6, matching: .images) {
                Label("Add a photo of the menu", systemImage: "camera")
            }
            Button(place?.website != nil ? "Use a different website" : "Add the restaurant's website") {
                siteText = place?.website ?? ""
                editingSite = true
            }
        }
        .font(.subheadline.weight(.semibold))
        .tint(Theme.link)
    }

    @ViewBuilder private func found(_ menu: PlaceMenu) -> some View {
        let present = Self.diets.filter { tag in menu.sections.contains { $0.items.contains { $0.tags.contains(tag.0) } } }
        let active = present.contains { $0.0 == diet } ? diet : nil
        let sections = menu.sections
            .map { MenuSection(title: $0.title, note: $0.note, items: $0.items.filter { keep($0, diet: active) }) }
            .filter { !$0.items.isEmpty }
        Section {
            HStack {
                Text(sourceLine(menu)).font(.footnote).foregroundStyle(Theme.secondary)
                Spacer()
                Button("Refresh") { Task { await find(refresh: true) } }.font(.subheadline.weight(.semibold)).buttonStyle(.borderless)
            }
            if let notes = menu.notes { Text(notes).font(.subheadline) }
            if !present.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(present.indices, id: \.self) { i in
                            let tag = present[i]
                            FilterChip(label: tag.1, isOn: active == tag.0) { diet = active == tag.0 ? nil : tag.0 }
                        }
                    }
                }
            }
        }
        if sections.isEmpty {
            Text("Nothing on the menu matches that filter.").foregroundStyle(Theme.secondary)
        }
        ForEach(Array(sections.enumerated()), id: \.offset) { _, section in
            Section {
                if let note = section.note { Text(note).font(.footnote).italic().foregroundStyle(Theme.secondary) }
                ForEach(Array(section.items.enumerated()), id: \.offset) { _, item in
                    MenuItemRow(item: item, labels: Dictionary(uniqueKeysWithValues: Self.diets))
                }
            } header: {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(section.title).font(Theme.serif(22)).foregroundStyle(Theme.label).textCase(nil)
                    Text("\(section.items.count)").foregroundStyle(Theme.secondary)
                }
            }
        }
        Section {
            PhotosPicker(selection: $shots, maxSelectionCount: 6, matching: .images) {
                Label("Wrong or missing dishes? Add a photo of the menu", systemImage: "camera")
            }
            .tint(Theme.link)
        } footer: {
            Text("Menus change. Check with the restaurant for today's dishes and prices."
                 + (menu.sourceKind == "photos" || menu.sourceKind == "upload" ? " Read from photos, so some items may be missing or misread." : ""))
        }
    }

    private func keep(_ item: MenuItem, diet: String?) -> Bool {
        guard let diet else { return true }
        return item.tags.contains(diet) || (diet == "vegetarian" && item.tags.contains("vegan"))
    }

    private func sourceLine(_ menu: PlaceMenu) -> String {
        let when = menu.fetchedAt.map { " · " + Fmt.ago($0) } ?? ""
        switch menu.sourceKind {
        case "upload": return "From the photo you added" + when
        case "photos": return "Read from photos on Google Maps" + when
        default:
            let host = menu.sourceUrl.flatMap { URL(string: $0)?.host }?.replacingOccurrences(of: "www.", with: "")
            return "From " + (host ?? "the website") + when
        }
    }

    // MARK: Loading

    private func load() async {
        do { menu = try await API.shared.get("/v1/places/\(placeId)/menu") }
        catch { self.error = error.localizedDescription }
    }

    private func find(refresh: Bool) async {
        busy = true
        error = nil
        do { menu = try await API.shared.post("/v1/places/\(placeId)/menu", ["refresh": refresh]) }
        catch { self.error = error.localizedDescription }
        busy = false
    }

    private func upload(_ items: [PhotosPickerItem]) async {
        busy = true
        error = nil
        var images: [String] = []
        for item in items {
            guard let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data),
                  let jpeg = image.scaled(maxSide: 2000).jpegData(compressionQuality: 0.8) else { continue }
            images.append("data:image/jpeg;base64," + jpeg.base64EncodedString())
        }
        shots = []
        if images.isEmpty { error = "Couldn't read those photos." }
        else {
            do { menu = try await API.shared.post("/v1/places/\(placeId)/menu/upload", ["images": images]) }
            catch { self.error = error.localizedDescription }
        }
        busy = false
    }

    private func setWebsite() async {
        let text = siteText.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty, let place else { return }
        await store.patch(place, ["website": text])
        await find(refresh: true)
    }
}

private struct MenuItemRow: View {
    let item: MenuItem
    let labels: [String: String]

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(item.name).font(.body.weight(.medium))
                if !item.tags.isEmpty {
                    HStack(spacing: 4) {
                        ForEach(item.tags, id: \.self) { tag in
                            Chip(text: labels[tag] ?? tag, color: tag == "spicy" ? Theme.red : Theme.green)
                        }
                    }
                }
                if let description = item.description {
                    Text(description).font(.subheadline).foregroundStyle(Theme.secondary)
                }
            }
            Spacer(minLength: 8)
            if let price = item.price {
                Text(price).font(.body.weight(.semibold)).monospacedDigit()
            }
        }
        .padding(.vertical, 2)
    }
}
