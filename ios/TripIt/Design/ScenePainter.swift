import SwiftUI
import UIKit

/// Draws the illustrated world scenes: deep skies, hazy layers of distance, glowing light, water with reflections,
/// lit windows, birds and a fine grain. Every scene is drawn in a 390 × 460 frame and scaled to fill its view.
struct Painter {
    var ctx: GraphicsContext
    static let W: CGFloat = 390
    static let H: CGFloat = 460

    private var W: CGFloat { Self.W }
    private var H: CGFloat { Self.H }

    static func color(_ hex: UInt32, _ opacity: Double = 1) -> Color { Color(hex: hex).opacity(opacity) }

    // MARK: Shapes

    func fill(_ d: String, _ hex: UInt32, _ opacity: Double = 1) {
        ctx.fill(SVGPath.parse(d), with: .color(Self.color(hex, opacity)))
    }

    func fill(_ path: Path, _ hex: UInt32, _ opacity: Double = 1) {
        ctx.fill(path, with: .color(Self.color(hex, opacity)))
    }

    func rect(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat, _ hex: UInt32, _ opacity: Double = 1) {
        fill(Path(CGRect(x: x, y: y, width: w, height: h)), hex, opacity)
    }

    func stroke(_ d: String, _ hex: UInt32, width: CGFloat, _ opacity: Double = 1) {
        ctx.stroke(SVGPath.parse(d), with: .color(Self.color(hex, opacity)), style: StrokeStyle(lineWidth: width, lineCap: .round))
    }

    func disc(_ x: CGFloat, _ y: CGFloat, _ r: CGFloat, _ hex: UInt32, _ opacity: Double = 1) {
        fill(Path(ellipseIn: CGRect(x: x - r, y: y - r, width: r * 2, height: r * 2)), hex, opacity)
    }

    // MARK: Light and air

    func sky(_ stops: [(Double, UInt32)]) {
        let gradient = Gradient(stops: stops.map { Gradient.Stop(color: Self.color($0.1), location: $0.0) })
        ctx.fill(Path(CGRect(x: 0, y: 0, width: W, height: H)),
                 with: .linearGradient(gradient, startPoint: .zero, endPoint: CGPoint(x: 0, y: H)))
    }

    /// A soft round glow: the sun, a lamp, a lantern.
    func glow(_ x: CGFloat, _ y: CGFloat, _ r: CGFloat, _ hex: UInt32, _ opacity: Double = 1) {
        let gradient = Gradient(stops: [
            .init(color: Self.color(hex, opacity), location: 0),
            .init(color: Self.color(hex, opacity * 0.55), location: 0.25),
            .init(color: Self.color(hex, 0), location: 1),
        ])
        ctx.fill(Path(ellipseIn: CGRect(x: x - r, y: y - r, width: r * 2, height: r * 2)),
                 with: .radialGradient(gradient, center: CGPoint(x: x, y: y), startRadius: 0, endRadius: r))
    }

    /// A band of mist, strongest in its middle.
    func haze(_ y: CGFloat, _ h: CGFloat, _ hex: UInt32, _ opacity: Double) {
        let gradient = Gradient(stops: [
            .init(color: Self.color(hex, 0), location: 0),
            .init(color: Self.color(hex, opacity), location: 0.5),
            .init(color: Self.color(hex, 0), location: 1),
        ])
        ctx.fill(Path(CGRect(x: 0, y: y, width: W, height: h)),
                 with: .linearGradient(gradient, startPoint: CGPoint(x: 0, y: y), endPoint: CGPoint(x: 0, y: y + h)))
    }

    func stars(_ count: Int, maxY: CGFloat, seed: String) {
        var r = Seeded(seed)
        for _ in 0..<count {
            let x = r.next() * W, y = r.next() * maxY, size = 0.3 + r.next() * 0.9
            disc(x, y, size, 0xFFFFFF, 0.3 + Double(r.next()) * 0.7)
        }
    }

    // MARK: Land and water

    /// A range of hills or mountains along `base`, rising up to `amp`.
    func ridge(_ base: CGFloat, _ amp: CGFloat, steps: Int, _ hex: UInt32, seed: String, rough: CGFloat = 0.5) {
        var r = Seeded(seed)
        var p = Path()
        p.move(to: CGPoint(x: 0, y: H))
        p.addLine(to: CGPoint(x: 0, y: base))
        var prev = base
        let step = W / CGFloat(steps)
        for i in 1...steps {
            let x = step * CGFloat(i)
            let wave = abs(sin(Double(i) * 1.7 + Double(r.next()) * 3))
            let y = base - amp * (r.next() * (1 - rough) + rough * CGFloat(wave))
            let cy = min(prev, y) - amp * 0.15 * r.next()
            p.addQuadCurve(to: CGPoint(x: x, y: y), control: CGPoint(x: x - step / 2, y: cy))
            prev = y
        }
        p.addLine(to: CGPoint(x: W, y: H))
        p.closeSubpath()
        fill(p, hex)
    }

    /// Water from `y` down, with short glints of light on it.
    func water(_ y: CGFloat, top: UInt32, bottom: UInt32, seed: String, shimmer: UInt32 = 0xFFFFFF, glints: Int = 40) {
        let gradient = Gradient(colors: [Self.color(top), Self.color(bottom)])
        ctx.fill(Path(CGRect(x: 0, y: y, width: W, height: H - y)),
                 with: .linearGradient(gradient, startPoint: CGPoint(x: 0, y: y), endPoint: CGPoint(x: 0, y: H)))
        var r = Seeded(seed)
        for _ in 0..<glints {
            let gy = y + 4 + r.next() * (H - y - 8)
            let w = 6 + r.next() * 40
            rect(r.next() * W, gy, w, 0.9, shimmer, 0.12 + Double(r.next()) * 0.35)
        }
    }

    /// Draws `content` again, upside down below `axis`, faintly: its reflection in the water.
    func reflect(_ axis: CGFloat, opacity: Double = 0.3, _ content: (Painter) -> Void) {
        ctx.drawLayer { layer in
            var c = layer
            c.opacity = opacity
            c.clip(to: Path(CGRect(x: 0, y: axis, width: Self.W, height: Self.H - axis)))
            c.translateBy(x: 0, y: axis * 2)
            c.scaleBy(x: 1, y: -1)
            content(Painter(ctx: c))
        }
    }

    // MARK: Details

    /// Lit windows across a building's face.
    func windows(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat, _ hex: UInt32, seed: String, density: CGFloat = 0.35) {
        var r = Seeded(seed)
        var yy = y + 4
        while yy < y + h - 3 {
            var xx = x + 3
            while xx < x + w - 3 {
                if r.next() < density { rect(xx, yy, 2, 2.6, hex, 0.5 + Double(r.next()) * 0.5) }
                xx += 5
            }
            yy += 6
        }
    }

    func birds(_ count: Int, _ x0: CGFloat, _ y0: CGFloat, spread: CGFloat, _ hex: UInt32, seed: String) {
        var r = Seeded(seed)
        for _ in 0..<count {
            let x = x0 + r.next() * spread, y = y0 + r.next() * spread * 0.35, k = 2 + r.next() * 3
            stroke("M\(x - k) \(y) q\(k / 2) \(-k / 2) \(k) 0 q\(k / 2) \(-k / 2) \(k) 0", hex, width: 0.9, 0.75)
        }
    }

    /// A row of simple buildings from `x` to the right edge, with lit windows; returns nothing, draws in place.
    func skyline(base: CGFloat, minH: CGFloat, maxH: CGFloat, minW: CGFloat, maxW: CGFloat, _ hex: UInt32,
                 lights: UInt32, seed: String, density: CGFloat = 0.35, gap: CGFloat = 1) {
        var r = Seeded(seed)
        var x: CGFloat = -6
        while x < W {
            let w = minW + r.next() * (maxW - minW), h = minH + r.next() * (maxH - minH)
            rect(x, base - h, w, h, hex)
            windows(x, base - h, w, h, lights, seed: seed + "\(Int(x))", density: density)
            x += w + gap
        }
    }

    /// A fine film grain over everything, so the scene reads as a print rather than flat colour.
    func grain() {
        ctx.drawLayer { layer in
            var c = layer
            c.opacity = 0.5
            c.fill(Path(CGRect(x: 0, y: 0, width: Self.W, height: Self.H)),
                   with: .tiledImage(Image(uiImage: Grain.image), origin: .zero, sourceRect: CGRect(x: 0, y: 0, width: 1, height: 1), scale: 0.5))
        }
    }
}

/// A small square of random speckle, made once and tiled.
private enum Grain {
    static let image: UIImage = {
        let size = 96
        var r = Seeded("grain")
        return UIGraphicsImageRenderer(size: CGSize(width: size, height: size)).image { ctx in
            for y in 0..<size {
                for x in 0..<size {
                    let v = r.next()
                    UIColor(white: v > 0.5 ? 1 : 0, alpha: 0.05 + 0.12 * abs(v - 0.5)).setFill()
                    ctx.fill(CGRect(x: x, y: y, width: 1, height: 1))
                }
            }
        }
    }()
}

/// Reads SVG path data (M L H V Q C Z, absolute and relative) into a Path, so scenes can be written compactly.
enum SVGPath {
    static func parse(_ d: String) -> Path {
        var path = Path()
        var tokens: [String] = []
        var number = ""
        func flush() { if !number.isEmpty { tokens.append(number); number = "" } }
        for ch in d {
            if ch.isLetter && ch != "e" {
                flush(); tokens.append(String(ch))
            } else if ch == "-" {
                if let last = number.last, last == "e" { number.append(ch) } else { flush(); number.append(ch) }
            } else if ch == " " || ch == "," || ch == "\n" {
                flush()
            } else if ch == "." && number.contains(".") {
                flush(); number.append(ch)
            } else {
                number.append(ch)
            }
        }
        flush()

        var i = 0
        var cmd: Character = "M"
        var cur = CGPoint.zero
        var start = CGPoint.zero
        func num() -> CGFloat {
            guard i < tokens.count, let v = Double(tokens[i]) else { i += 1; return 0 }
            i += 1
            return CGFloat(v)
        }
        while i < tokens.count {
            if let c = tokens[i].first, c.isLetter {
                cmd = c; i += 1
                if cmd == "Z" || cmd == "z" { path.closeSubpath(); cur = start; continue }
            }
            let rel = cmd.isLowercase
            func pt() -> CGPoint {
                let x = num(), y = num()
                return rel ? CGPoint(x: cur.x + x, y: cur.y + y) : CGPoint(x: x, y: y)
            }
            switch cmd {
            case "M", "m":
                cur = pt(); start = cur; path.move(to: cur)
                cmd = rel ? "l" : "L"  // further pairs are lines
            case "L", "l":
                cur = pt(); path.addLine(to: cur)
            case "H", "h":
                let x = num(); cur = CGPoint(x: rel ? cur.x + x : x, y: cur.y); path.addLine(to: cur)
            case "V", "v":
                let y = num(); cur = CGPoint(x: cur.x, y: rel ? cur.y + y : y); path.addLine(to: cur)
            case "Q", "q":
                let c1 = pt(), end = pt(); path.addQuadCurve(to: end, control: c1); cur = end
            case "C", "c":
                let c1 = pt(), c2 = pt(), end = pt(); path.addCurve(to: end, control1: c1, control2: c2); cur = end
            default:
                i += 1
            }
        }
        return path
    }
}

/// One drawn place for the Home header and for cards without a photo.
struct WorldScene: Identifiable, Hashable {
    let id: String
    let place: String  // shown under the greeting
    let names: [String]  // city or region names that pick this scene
    let base: UInt32  // colour shown for the split second before it's drawn
    let draw: (Painter) -> Void

    static func == (a: WorldScene, b: WorldScene) -> Bool { a.id == b.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

/// A scene drawn to fill its frame.
struct WorldSceneCanvas: View {
    let scene: WorldScene
    var body: some View {
        Canvas { ctx, size in
            let s = max(size.width / Painter.W, size.height / Painter.H)
            var c = ctx
            c.translateBy(x: (size.width - Painter.W * s) / 2, y: (size.height - Painter.H * s) / 2)
            c.scaleBy(x: s, y: s)
            scene.draw(Painter(ctx: c))
        }
    }
}

/// A scene as a picture: drawn once per size, then kept, so scrolling and crossfades cost nothing.
struct WorldSceneImage: View {
    let scene: WorldScene
    var body: some View {
        GeometryReader { geo in
            SceneImageContent(scene: scene, size: geo.size)
        }
        .accessibilityHidden(true)
    }
}

private struct SceneImageContent: View {
    let scene: WorldScene
    let size: CGSize
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            Color(hex: scene.base)
            if let image { Image(uiImage: image).resizable().transition(.opacity) }
        }
        .task(id: "\(scene.id)-\(Int(size.width))x\(Int(size.height))") {
            guard size.width > 1, size.height > 1 else { return }
            let drawn = SceneCache.image(scene, size: size)
            withAnimation(.easeOut(duration: 0.2)) { image = drawn }
        }
    }
}

@MainActor
enum SceneCache {
    private static let cache = NSCache<NSString, UIImage>()

    static func image(_ scene: WorldScene, size: CGSize) -> UIImage? {
        let key = "\(scene.id)-\(Int(size.width))x\(Int(size.height))" as NSString
        if let hit = cache.object(forKey: key) { return hit }
        let renderer = ImageRenderer(content: WorldSceneCanvas(scene: scene).frame(width: size.width, height: size.height))
        renderer.scale = UIScreen.main.scale
        guard let image = renderer.uiImage else { return nil }
        cache.setObject(image, forKey: key)
        return image
    }
}
