import SwiftUI

/// Draws a scene from its script (SceneScripts): one step per line, a letter then numbers, colours as hex, and a
/// path last where there is one. Lights, stars, water glints and birds are tagged, so the Home header can bring
/// them to life on top of the still picture (SceneMotionView).
///
///   S o c o c …  sky gradient          G x y r c o  glow           R x y w h c o  rectangle
///   U x y w h r c o  rounded rectangle  P c o d  filled path        F c o d  filled path, even-odd
///   L c w o d  stroked path            C x y r c o  disc            E x y rx ry c o  ellipse
///   O x y r c w o  ring                 V y c c  water gradient      M axis o … m  reflection
///   T x y w h c o  a light that twinkles     Y x y r c o  a point of light that twinkles
///   X x y r c o  a star                      Q x y w h c o  a glint on the water
///   B x y k c  a bird                        N  grain
enum SceneScript {
    enum Step {
        case sky([(Double, UInt32)])
        case glow(CGFloat, CGFloat, CGFloat, UInt32, Double)
        case rect(CGRect, UInt32, Double, radius: CGFloat)
        case path(Path, UInt32, Double, evenOdd: Bool)
        case line(Path, UInt32, CGFloat, Double)
        case disc(CGFloat, CGFloat, CGFloat, UInt32, Double)
        case ellipse(CGRect, UInt32, Double)
        case ring(CGFloat, CGFloat, CGFloat, UInt32, CGFloat, Double)
        case water(CGFloat, UInt32, UInt32)
        case mirror(CGFloat, Double, [Step])
        case light(CGRect, UInt32, Double)
        case point(CGFloat, CGFloat, CGFloat, UInt32, Double)
        case star(CGFloat, CGFloat, CGFloat, Double)
        case glint(CGRect, UInt32, Double)
        case bird(CGFloat, CGFloat, CGFloat, UInt32)
        case grain
    }

    /// The steps of a script, read once when the scene is first used.
    static func steps(_ script: String) -> [Step] {
        var lines = script.split(separator: "\n")[...]
        return parse(&lines)
    }

    private static func parse(_ lines: inout ArraySlice<Substring>) -> [Step] {
        var out: [Step] = []
        while let line = lines.popFirst() {
            let parts = line.split(separator: " ", omittingEmptySubsequences: true)
            guard let code = parts.first else { continue }
            func n(_ i: Int) -> CGFloat { i < parts.count ? CGFloat(Double(parts[i]) ?? 0) : 0 }
            func d(_ i: Int) -> Double { i < parts.count ? Double(parts[i]) ?? 0 : 0 }
            func c(_ i: Int) -> UInt32 { i < parts.count ? UInt32(parts[i], radix: 16) ?? 0 : 0 }
            func rest(_ i: Int) -> String { parts.count > i ? parts[i...].joined(separator: " ") : "" }
            switch code {
            case "S":
                var stops: [(Double, UInt32)] = []
                var i = 1
                while i + 1 < parts.count { stops.append((d(i), c(i + 1))); i += 2 }
                out.append(.sky(stops))
            case "G": out.append(.glow(n(1), n(2), n(3), c(4), d(5)))
            case "R": out.append(.rect(CGRect(x: n(1), y: n(2), width: n(3), height: n(4)), c(5), d(6), radius: 0))
            case "U": out.append(.rect(CGRect(x: n(1), y: n(2), width: n(3), height: n(4)), c(6), d(7), radius: n(5)))
            case "P": out.append(.path(SVGPath.parse(rest(3)), c(1), d(2), evenOdd: false))
            case "F": out.append(.path(SVGPath.parse(rest(3)), c(1), d(2), evenOdd: true))
            case "L": out.append(.line(SVGPath.parse(rest(4)), c(1), n(2), d(3)))
            case "C": out.append(.disc(n(1), n(2), n(3), c(4), d(5)))
            case "E": out.append(.ellipse(CGRect(x: n(1) - n(3), y: n(2) - n(4), width: n(3) * 2, height: n(4) * 2), c(5), d(6)))
            case "O": out.append(.ring(n(1), n(2), n(3), c(4), n(5), d(6)))
            case "V": out.append(.water(n(1), c(2), c(3)))
            case "M":
                let axis = n(1), opacity = d(2)
                out.append(.mirror(axis, opacity, parse(&lines)))
            case "m": return out
            case "T": out.append(.light(CGRect(x: n(1), y: n(2), width: n(3), height: n(4)), c(5), d(6)))
            case "Y": out.append(.point(n(1), n(2), n(3), c(4), d(5)))
            case "X": out.append(.star(n(1), n(2), n(3), d(5)))
            case "Q": out.append(.glint(CGRect(x: n(1), y: n(2), width: n(3), height: n(4)), c(5), d(6)))
            case "B": out.append(.bird(n(1), n(2), n(3), c(4)))
            case "N": out.append(.grain)
            default: break
            }
        }
        return out
    }

    /// The still picture. With `leavingOutBirds`, birds are left for the motion layer to fly.
    static func draw(_ steps: [Step], _ p: Painter, leavingOutBirds: Bool = false) {
        let ctx = p.ctx
        for step in steps {
            switch step {
            case .sky(let stops): p.sky(stops)
            case let .glow(x, y, r, hex, o): p.glow(x, y, r, hex, o)
            case let .rect(rect, hex, o, radius):
                ctx.fill(radius > 0 ? Path(roundedRect: rect, cornerRadius: radius) : Path(rect), with: .color(Painter.color(hex, o)))
            case let .path(path, hex, o, evenOdd):
                ctx.fill(path, with: .color(Painter.color(hex, o)), style: FillStyle(eoFill: evenOdd))
            case let .line(path, hex, w, o):
                ctx.stroke(path, with: .color(Painter.color(hex, o)), style: StrokeStyle(lineWidth: w, lineCap: .round))
            case let .disc(x, y, r, hex, o), let .point(x, y, r, hex, o): p.disc(x, y, r, hex, o)
            case let .ellipse(rect, hex, o): ctx.fill(Path(ellipseIn: rect), with: .color(Painter.color(hex, o)))
            case let .ring(x, y, r, hex, w, o):
                ctx.stroke(Path(ellipseIn: CGRect(x: x - r, y: y - r, width: r * 2, height: r * 2)),
                           with: .color(Painter.color(hex, o)), lineWidth: w)
            case let .water(y, top, bottom):
                ctx.fill(Path(CGRect(x: 0, y: y, width: Painter.W, height: Painter.H - y)),
                         with: .linearGradient(Gradient(colors: [Painter.color(top), Painter.color(bottom)]),
                                               startPoint: CGPoint(x: 0, y: y), endPoint: CGPoint(x: 0, y: Painter.H)))
            case let .mirror(axis, o, inner): p.reflect(axis, opacity: o) { draw(inner, $0) }
            case let .light(rect, hex, o), let .glint(rect, hex, o): ctx.fill(Path(rect), with: .color(Painter.color(hex, o)))
            case let .star(x, y, r, o): p.disc(x, y, r, 0xFFFFFF, o)
            case let .bird(x, y, k, hex): if !leavingOutBirds { bird(ctx, x, y, k, hex, flap: 1) }
            case .grain: p.grain()
            }
        }
    }

    static func bird(_ ctx: GraphicsContext, _ x: CGFloat, _ y: CGFloat, _ k: CGFloat, _ hex: UInt32, flap: CGFloat) {
        var path = Path()
        path.move(to: CGPoint(x: x - k, y: y))
        path.addQuadCurve(to: CGPoint(x: x, y: y), control: CGPoint(x: x - k / 2, y: y - k / 2 * flap))
        path.addQuadCurve(to: CGPoint(x: x + k, y: y), control: CGPoint(x: x + k / 2, y: y - k / 2 * flap))
        ctx.stroke(path, with: .color(Painter.color(hex, 0.75)), style: StrokeStyle(lineWidth: 0.9, lineCap: .round))
    }

    /// The moving parts, drawn over the still picture at time `t` (seconds).
    static func drawMotion(_ steps: [Step], _ ctx: GraphicsContext, t: Double) {
        for (i, step) in steps.enumerated() {
            let phase = Double((i &* 2654435761) % 1000) / 1000 * 2 * .pi
            switch step {
            case let .light(rect, hex, o):
                // Most windows stay steady; some brighten and dim slowly, a few blink off and on.
                let wave = sin(t * (0.35 + phase / 12) + phase)
                let extra = pow(max(0, wave), 6) * 0.55
                if extra > 0.02 { ctx.fill(Path(rect), with: .color(Painter.color(0xFFF1C8, min(1, o * extra * 1.6)))) }
                if wave < -0.985 { ctx.fill(Path(rect), with: .color(Painter.color(0x1A1A2A, 0.7))) }
                _ = hex
            case let .point(x, y, r, hex, _):
                let sparkle = pow(max(0, sin(t * 2.4 + phase * 3)), 12)
                if sparkle > 0.05 {
                    let rr = r * (1 + 1.6 * sparkle)
                    ctx.fill(Path(ellipseIn: CGRect(x: x - rr, y: y - rr, width: rr * 2, height: rr * 2)),
                             with: .color(Painter.color(hex, sparkle)))
                }
            case let .star(x, y, r, o):
                let blink = 0.5 + 0.5 * sin(t * (0.6 + phase / 6) + phase)
                let rr = r * (0.8 + 0.5 * blink)
                ctx.fill(Path(ellipseIn: CGRect(x: x - rr, y: y - rr, width: rr * 2, height: rr * 2)),
                         with: .color(Painter.color(0xFFFFFF, o * blink * 0.8)))
            case let .glint(rect, hex, o):
                // Each glint drifts a little and comes and goes, so the water moves.
                let drift = CGFloat(sin(t * 0.5 + phase)) * 7
                let shine = 0.5 + 0.5 * sin(t * 1.1 + phase * 2)
                ctx.fill(Path(rect.offsetBy(dx: drift, dy: 0)), with: .color(Painter.color(hex, o * shine)))
            case let .bird(x, y, k, hex):
                // Birds glide slowly across and wrap around, flapping now and then.
                let span = Painter.W + 80
                var bx = (x + CGFloat(t * 7 + phase * 10)).truncatingRemainder(dividingBy: span)
                if bx > Painter.W + 40 { bx -= span }
                let by = y + CGFloat(sin(t * 0.7 + phase)) * 3
                let flap = CGFloat(0.4 + 0.6 * abs(sin(t * 3 + phase)))
                bird(ctx, bx, by, k, hex, flap: flap)
            default: break
            }
        }
    }
}

/// The moving parts of a scene (twinkling lights, stars, water, birds) over its still picture, filling the frame
/// the same way. Pauses when asked, and stays still for Reduce Motion.
struct SceneMotionView: View {
    let steps: [SceneScript.Step]
    var paused = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 24, paused: paused || reduceMotion)) { context in
            Canvas { ctx, size in
                let s = max(size.width / Painter.W, size.height / Painter.H)
                var c = ctx
                c.translateBy(x: (size.width - Painter.W * s) / 2, y: (size.height - Painter.H * s) / 2)
                c.scaleBy(x: s, y: s)
                SceneScript.drawMotion(steps, c, t: context.date.timeIntervalSinceReferenceDate)
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
