import SwiftUI

/// An edit as a card without a photo: its caption with the title right under it, and its first places at the foot,
/// set on ink, sage or sand.
struct EditTile: View {
    let caption: String
    let title: String
    var preview = ""
    let seed: String  // the same edit always gets the same colour
    var titleSize: CGFloat = 26

    var body: some View {
        let (background, ink) = Self.colors(seed)
        VStack(alignment: .leading, spacing: 0) {
            Text(caption.uppercased())
                .font(Theme.text(.caption2, weight: .medium)).kerning(1.6)
                .foregroundStyle(ink.opacity(0.7)).lineLimit(2)
            Text(title).font(Theme.serif(titleSize)).foregroundStyle(ink).lineLimit(3).minimumScaleFactor(0.8)
                .padding(.top, 8)
            Spacer(minLength: 10)
            if !preview.isEmpty {
                Text(preview).font(Theme.text(.footnote)).foregroundStyle(ink.opacity(0.75)).lineLimit(2)
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(background)
    }

    static func colors(_ seed: String) -> (Color, Color) {
        switch seed.unicodeScalars.reduce(0, { ($0 &* 31 &+ Int($1.value)) & 0xFFFF }) % 3 {
        case 0: (Theme.label, Theme.background)  // ink (light on dark; flips in dark mode)
        case 1: (Theme.dynamic(0xE6EEE7, 0x1F2A22), Theme.label)  // sage
        default: (Theme.dynamic(0xEFE7DD, 0x2B241D), Theme.label)  // sand
        }
    }
}
