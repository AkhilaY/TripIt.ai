import SwiftUI
import UIKit

// MARK: - Images

/// Downloads and caches photos (place photos are signed links on the server, so no headers are needed).
actor ImageLoader {
    static let shared = ImageLoader()
    private let cache = NSCache<NSURL, UIImage>()
    private var running: [URL: Task<UIImage?, Never>] = [:]

    func image(_ url: URL) async -> UIImage? {
        if let hit = cache.object(forKey: url as NSURL) { return hit }
        if let task = running[url] { return await task.value }
        let task = Task<UIImage?, Never> {
            guard let (data, response) = try? await URLSession.shared.data(from: url),
                  (response as? HTTPURLResponse)?.statusCode ?? 200 < 400,
                  let image = UIImage(data: data) else { return nil }
            return await image.byPreparingForDisplay() ?? image
        }
        running[url] = task
        let image = await task.value
        running[url] = nil
        if let image { cache.setObject(image, forKey: url as NSURL) }
        return image
    }
}

/// A photo from TripIt (fills its frame; shows the placeholder until it loads or if it can't).
struct RemoteImage<Placeholder: View>: View {
    let url: URL?
    @ViewBuilder var placeholder: () -> Placeholder
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                placeholder()
            }
        }
        .task(id: url) {
            image = nil
            if let url { image = await ImageLoader.shared.image(url) }
        }
    }
}

extension PlacePhoto {
    /// The photo's address at a given width (the server resizes Google photos).
    func url(width: Int) -> URL? {
        API.shared.url(url + (url.contains("?") ? "&" : "?") + "w=\(width)")
    }
}

// MARK: - Category tiles and place thumbnails

struct CategoryTile: View {
    let category: Category
    var size: CGFloat = 30

    var body: some View {
        SymbolTile(symbol: category.symbol, size: size)
    }
}

/// A quiet square with a one-colour symbol, for list rows. (The colour argument is kept for older callers.)
struct SymbolTile: View {
    let symbol: String
    var color: Color = Theme.gray
    var size: CGFloat = 30

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
            .fill(Theme.raised)
            .frame(width: size, height: size)
            .overlay(Image(systemName: symbol).font(.system(size: size * 0.44, weight: .medium)).foregroundStyle(Theme.label))
    }
}

struct PlaceThumb: View {
    let place: Place
    var size: CGFloat = 56

    var body: some View {
        let category = Category(place.category)
        RemoteImage(url: place.photos.first?.url(width: Int(size * 3))) {
            ZStack {
                Theme.raised
                Image(systemName: category.symbol).font(.system(size: size * 0.36, weight: .medium)).foregroundStyle(Theme.secondary)
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: min(size * 0.25, 16), style: .continuous))
    }
}

// MARK: - Place rows

struct PlaceRow: View {
    let place: Place
    var showCategory = true
    var showDay = false
    var distance: Double?

    var body: some View {
        HStack(spacing: 12) {
            PlaceThumb(place: place)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 5) {
                    Text(place.name)
                        .font(.body.weight(.semibold))
                        .strikethrough(place.visited)
                        .lineLimit(1)
                    if place.mustDo {
                        Image(systemName: "star.fill").font(.caption).foregroundStyle(Theme.gold)
                    }
                    if !place.isLocated {
                        Circle().fill(Theme.warn).frame(width: 6, height: 6).accessibilityLabel("Not on the map yet")
                    }
                }
                Text(subtitle).font(.subheadline).foregroundStyle(Theme.secondary).lineLimit(1)
                chips
                if !place.recommendedItems.isEmpty {
                    Text("Try: " + place.recommendedItems.joined(separator: ", "))
                        .font(.footnote).foregroundStyle(Theme.secondary).lineLimit(1)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 2)
        .contentShape(Rectangle())
    }

    private var subtitle: String {
        [showCategory ? Category(place.category).label : nil, place.neighborhood, place.city.isEmpty ? nil : place.city]
            .compactMap { $0 }.joined(separator: " · ")
    }

    @ViewBuilder private var chips: some View {
        let items = chipItems
        if !items.isEmpty {
            HStack(spacing: 6) {
                ForEach(items) { item in
                    Chip(text: item.text, symbol: item.symbol, color: item.color)
                }
            }
        }
    }

    private struct ChipItem: Identifiable {
        let text: String
        let symbol: String?
        let color: Color
        var id: String { text }
    }

    private var chipItems: [ChipItem] {
        var out: [ChipItem] = []
        if Category(place.category) == .event {
            out.append(ChipItem(text: place.eventDate.map(Fmt.shortDay) ?? "Date TBC", symbol: "calendar", color: Theme.secondary))
        }
        if place.suggested { out.append(ChipItem(text: "Suggested", symbol: "sparkles", color: Theme.gold)) }
        if place.bookingNeed == "required" {
            out.append(ChipItem(text: place.bookingKind == "tickets" ? "Tickets needed" : "Book ahead", symbol: nil, color: Theme.warn))
        }
        if let rating = place.rating {
            let count = place.ratingCount.map { " (\(Fmt.count($0)))" } ?? ""
            out.append(ChipItem(text: String(format: "%.1f", rating) + count, symbol: "star.fill", color: Theme.secondary))
        }
        if place.mentionCount >= 2 { out.append(ChipItem(text: "\(place.mentionCount) Reels", symbol: nil, color: Theme.secondary)) }
        if showDay, let day = place.dayNumber { out.append(ChipItem(text: "Day \(day)", symbol: nil, color: Theme.secondary)) }
        if let distance { out.append(ChipItem(text: Fmt.distance(distance), symbol: nil, color: Theme.secondary)) }
        return out
    }
}

struct Chip: View {
    let text: String
    var symbol: String?
    var color: Color = Theme.secondary

    var body: some View {
        HStack(spacing: 3) {
            if let symbol { Image(systemName: symbol).font(.system(size: 9, weight: .bold)) }
            Text(text).font(.caption.weight(.semibold)).lineLimit(1)
        }
        .foregroundStyle(color)
        .padding(.horizontal, 7).padding(.vertical, 2)
        .background(Theme.raised, in: Capsule())
    }
}

/// A filter chip that can be toggled on and off.
struct FilterChip: View {
    let label: String
    var count: Int?
    var symbol: String?
    let isOn: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                if let symbol { Image(systemName: symbol).font(.caption.weight(.bold)) }
                Text(label).font(.subheadline.weight(.medium))
                if let count { Text("\(count)").font(.caption.weight(.semibold)).opacity(0.6) }
            }
            .padding(.horizontal, 12).padding(.vertical, 7)
            .foregroundStyle(isOn ? Theme.background : Theme.label)
            .background(isOn ? Theme.label : Theme.cell, in: Capsule())
            .overlay(Capsule().strokeBorder(Theme.border, lineWidth: isOn ? 0 : 1))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isOn ? .isSelected : [])
    }
}

// MARK: - Buttons, empty states, toasts

/// The one main action on a screen (gold), or with `tinted` a quiet one.
struct PrimaryButtonStyle: ButtonStyle {
    var tinted = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .padding(.horizontal, 16)
            .frame(maxWidth: .infinity, minHeight: 42)
            .foregroundStyle(tinted ? Theme.label : Theme.accentInk)
            .background(tinted ? Theme.raised : Theme.accent, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay {
                if tinted { RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.raisedBorder) }
            }
            .opacity(configuration.isPressed ? 0.75 : 1)
    }
}

/// A quiet square button with an icon over its label (Directions, Menu, Call, Website).
struct QuietTileLabel: View {
    let symbol: String
    let title: String

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: symbol).font(.system(size: 15, weight: .regular))
            Text(title).font(.caption2.weight(.medium)).lineLimit(1).minimumScaleFactor(0.8)
        }
        .foregroundStyle(Theme.label)
        .frame(maxWidth: .infinity, minHeight: 50)
        .background(Theme.cell, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.border))
    }
}

/// Small caps above a heading ("THIS WEEKEND · 24–25 OCT").
struct Eyebrow: View {
    let text: String
    var color: Color = Theme.gold
    var body: some View {
        Text(text.uppercased()).font(.system(size: 10, weight: .semibold)).kerning(1.4).foregroundStyle(color)
    }
}

/// A section heading in the serif, with an optional action on the right.
struct SectionHeading<Trailing: View>: View {
    let title: String
    var size: CGFloat = 20
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).font(Theme.serif(size)).foregroundStyle(Theme.label)
            Spacer(minLength: 8)
            trailing()
        }
        .frame(minHeight: 36)
    }
}

extension SectionHeading where Trailing == EmptyView {
    init(_ title: String, size: CGFloat = 20) { self.init(title: title, size: size) { EmptyView() } }
}

/// A text button in the accent colour with a symbol ("+ New trip").
struct AccentTextButton: View {
    let title: String
    var symbol: String? = "plus"
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                if let symbol { Image(systemName: symbol).font(.footnote.weight(.semibold)) }
                Text(title).font(.footnote.weight(.semibold))
            }
            .foregroundStyle(Theme.link)
            .frame(minHeight: 36)
        }
        .buttonStyle(.plain)
    }
}

struct EmptyState<Actions: View>: View {
    let symbol: String
    var color: Color = Theme.gray
    let title: String
    let text: String
    @ViewBuilder var actions: () -> Actions

    var body: some View {
        VStack(spacing: 12) {
            SymbolTile(symbol: symbol, color: color, size: 56)
            Text(title).font(Theme.serif(24))
            Text(text).font(.subheadline).foregroundStyle(Theme.secondary).multilineTextAlignment(.center)
            actions()
        }
        .padding(.horizontal, 28).padding(.vertical, 36)
        .frame(maxWidth: .infinity)
    }
}

extension EmptyState where Actions == EmptyView {
    init(symbol: String, color: Color = Theme.gray, title: String, text: String) {
        self.init(symbol: symbol, color: color, title: title, text: text) { EmptyView() }
    }
}

struct ToastView: View {
    let toast: Store.Toast

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: toast.isError ? "exclamationmark.circle.fill" : "checkmark.circle.fill")
                .foregroundStyle(toast.isError ? Theme.warn : Theme.ok)
            Text(toast.text).font(.subheadline.weight(.medium)).multilineTextAlignment(.leading)
        }
        .padding(.horizontal, 16).padding(.vertical, 11)
        .background(.regularMaterial, in: Capsule())
        .shadow(color: .black.opacity(0.12), radius: 14, y: 6)
        .padding(.horizontal, 20)
    }
}

struct ToastOverlay: ViewModifier {
    @Environment(Store.self) private var store

    func body(content: Content) -> some View {
        content.overlay(alignment: .bottom) {
            if let toast = store.toast {
                ToastView(toast: toast)
                    .padding(.bottom, 64)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                    .id(toast.id)
                    .task(id: toast.id) {
                        try? await Task.sleep(for: .seconds(toast.isError ? 4 : 2.6))
                        withAnimation { if store.toast?.id == toast.id { store.toast = nil } }
                    }
                    .onTapGesture { withAnimation { store.toast = nil } }
            }
        }
        .animation(.spring(duration: 0.35), value: store.toast)
    }
}

/// A rounded card with a hairline border.
struct Card<Content: View>: View {
    var radius: CGFloat = 16
    var padding: CGFloat = 0
    @ViewBuilder var content: () -> Content
    var body: some View {
        VStack(alignment: .leading, spacing: 0, content: content)
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.cell, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous).strokeBorder(Theme.border))
    }
}

/// A round button for the top of a screen (+, profile initial).
struct RoundIconButton: View {
    let symbol: String
    let label: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 14, weight: .regular))
                .foregroundStyle(Theme.label)
                .frame(width: 34, height: 34)
                .background(Theme.cell, in: Circle())
                .overlay(Circle().strokeBorder(Theme.border))
                .frame(width: 40, height: 40)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

/// Green "Open now · until 10 PM", or the time it opens, from saved hours.
struct OpenStatusText: View {
    let hours: OpeningHours?
    var body: some View {
        if let status = Hours.status(hours) {
            Text(status.label).foregroundStyle(status.isOpen ? Theme.open : Theme.secondary)
        }
    }
}

extension View {
    /// TripIt's warm background behind lists and scroll views.
    func tripBackground() -> some View {
        scrollContentBackground(.hidden).background(Theme.background.ignoresSafeArea())
    }
}
