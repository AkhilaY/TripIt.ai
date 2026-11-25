import SwiftUI

/// A drawn map of where an edit's places sit, numbered in order with a dotted line between them. Drawn on the phone
/// from the places' coordinates, so there's nothing to load and nothing to fail.
struct RouteSketch: View {
    struct Stop {
        let number: Int
        let latitude: Double
        let longitude: Double
    }

    let stops: [Stop]

    var body: some View {
        Canvas { ctx, size in
            // Soft contour lines, so it reads as a map.
            for (i, f) in [0.26, 0.56, 0.82].enumerated() {
                var line = Path()
                line.move(to: CGPoint(x: 0, y: size.height * f))
                line.addCurve(to: CGPoint(x: size.width, y: size.height * (f - 0.06 + 0.05 * Double(i))),
                              control1: CGPoint(x: size.width * 0.35, y: size.height * (f - 0.16)),
                              control2: CGPoint(x: size.width * 0.65, y: size.height * (f + 0.14)))
                ctx.stroke(line, with: .color(Theme.border), lineWidth: i == 1 ? 7 : 2)
            }
            guard !stops.isEmpty else { return }
            // Longitude shrinks towards the poles; scale it so distances look right, then fit everything in.
            let lats = stops.map(\.latitude), lons = stops.map(\.longitude)
            let k = cos(((lats.min()! + lats.max()!) / 2) * .pi / 180)
            let xs = lons.map { $0 * k }, ys = lats.map { -$0 }
            let spanX = max(xs.max()! - xs.min()!, 0.002), spanY = max(ys.max()! - ys.min()!, 0.002)
            let inset: CGFloat = 30
            let scale = min((size.width - inset * 2) / spanX, (size.height - inset * 2) / spanY)
            let cx = (xs.max()! + xs.min()!) / 2, cy = (ys.max()! + ys.min()!) / 2
            let points = zip(xs, ys).map { CGPoint(x: size.width / 2 + ($0 - cx) * scale, y: size.height / 2 + ($1 - cy) * scale) }

            var route = Path()
            route.addLines(points)
            ctx.stroke(route, with: .color(Theme.label.opacity(0.45)), style: StrokeStyle(lineWidth: 1.2, dash: [4, 4]))
            for (stop, point) in zip(stops, points) {
                ctx.fill(Path(ellipseIn: CGRect(x: point.x - 13, y: point.y - 13, width: 26, height: 26)), with: .color(Theme.label))
                ctx.draw(Text("\(stop.number)").font(Theme.text(.caption, weight: .medium)).foregroundStyle(Theme.background), at: point)
            }
        }
        .frame(height: 190)
        .background(Theme.fill, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .accessibilityHidden(true)  // the list below says the same
    }
}

/// An edit as a card without a photo: its caption, title and first few places, set on ink, sage or sand.
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
            Spacer(minLength: 8)
            Text(title).font(Theme.serif(titleSize)).foregroundStyle(ink).lineLimit(3).minimumScaleFactor(0.8)
            if !preview.isEmpty {
                Text(preview).font(Theme.text(.footnote)).foregroundStyle(ink.opacity(0.75)).lineLimit(2).padding(.top, 8)
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
