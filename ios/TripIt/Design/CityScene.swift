import SwiftUI

/// A city's photo (hand-picked, or found on Unsplash by the server). Until one arrives, or where there's none, a soft
/// plain colour: no drawn stand-in.
struct CityScene: View {
    let city: String
    var country = ""

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(hex: 0xA39E99), Color(hex: 0x6F6A66)], startPoint: .top, endPoint: .bottom)
            if let photo = CityPhotoBook.shared.photo(for: city) {
                PhotoFill(photo: photo)
            }
        }
        .task(id: city) { await CityPhotoBook.shared.load(city: city, country: country) }
    }

    /// Anywhere without a drawn scene: a simple landscape that fits it.
    @ViewBuilder private var landscape: some View {
        let look = CityLook.of(city)
        let sky = look.palette.sky(hour: Calendar.current.component(.hour, from: Date()))
        Canvas { ctx, size in
            var r = Seeded(city.lowercased())
            let w = size.width, h = size.height
            let rect = CGRect(origin: .zero, size: size)
            ctx.fill(Path(rect), with: .linearGradient(Gradient(colors: sky), startPoint: .zero, endPoint: CGPoint(x: 0, y: h)))
            let sun = min(w, h) * 0.07
            ctx.fill(Path(ellipseIn: CGRect(x: w * 0.3 - sun, y: h * 0.36 - sun, width: sun * 2, height: sun * 2)),
                     with: .color(Color(hex: 0xFFF3DC).opacity(0.5)))
            let horizon = h * 0.62
            let p = look.palette
            switch look.kind {
            case .lake, .peaks:
                ctx.fill(Shapes.ridge(w, h, base: horizon - h * 0.1, amp: h * 0.22, steps: 7, &r), with: .color(p.far))
                ctx.fill(Shapes.ridge(w, h, base: horizon, amp: h * 0.18, steps: 5, &r), with: .color(p.mid))
                if look.kind == .lake {
                    ctx.fill(Path(CGRect(x: 0, y: horizon, width: w, height: h - horizon)), with: .color(p.mid.opacity(0.85)))
                    var shore = Path()
                    shore.move(to: CGPoint(x: 0, y: h)); shore.addLine(to: CGPoint(x: 0, y: horizon + h * 0.06))
                    shore.addQuadCurve(to: CGPoint(x: w * 0.45, y: h), control: CGPoint(x: w * 0.3, y: horizon + h * 0.02))
                    ctx.fill(shore, with: .color(p.near.opacity(0.9)))
                    Shapes.lights(&ctx, w, base: horizon + 2, color: p.lights, count: 14, &r)
                } else {
                    ctx.fill(Shapes.ridge(w, h, base: horizon + h * 0.12, amp: h * 0.12, steps: 4, &r), with: .color(p.near))
                    Shapes.lights(&ctx, w, base: horizon + h * 0.1, color: p.lights, count: 8, &r)
                }
            case .coast:
                ctx.fill(Path(CGRect(x: 0, y: horizon, width: w, height: h - horizon)), with: .color(p.mid))
                ctx.fill(Shapes.hills(w, h, base: horizon, amp: h * 0.06, &r), with: .color(p.far.opacity(0.6)))
                var cliff = Path()
                cliff.move(to: CGPoint(x: w, y: h)); cliff.addLine(to: CGPoint(x: w, y: horizon - h * 0.14))
                cliff.addQuadCurve(to: CGPoint(x: w * 0.58, y: h), control: CGPoint(x: w * 0.7, y: horizon - h * 0.1))
                ctx.fill(cliff, with: .color(p.near))
                for i in 0..<5 {
                    ctx.fill(Path(CGRect(x: w * 0.1 + CGFloat(i) * w * 0.14, y: horizon + 8 + CGFloat(i) * 6, width: w * 0.1, height: 1)),
                             with: .color(Color(hex: 0xF3E6CC).opacity(0.5)))
                }
            case .desert:
                ctx.fill(Shapes.hills(w, h, base: horizon, amp: h * 0.1, &r), with: .color(p.far))
                ctx.fill(Shapes.hills(w, h, base: horizon + h * 0.1, amp: h * 0.12, &r), with: .color(p.mid))
                ctx.fill(Shapes.hills(w, h, base: horizon + h * 0.22, amp: h * 0.08, &r), with: .color(p.near))
            default:
                ctx.fill(Shapes.hills(w, h, base: horizon, amp: h * 0.1, &r), with: .color(p.far))
                ctx.fill(Shapes.landmark(look.kind, w, h, base: horizon + h * 0.08, &r), with: .color(p.mid))
                ctx.fill(Shapes.hills(w, h, base: horizon + h * 0.14, amp: h * 0.08, &r), with: .color(p.near))
                Shapes.lights(&ctx, w, base: horizon + h * 0.08, color: p.lights, count: look.kind == .skyline ? 26 : 12, &r)
            }
        }
        .accessibilityHidden(true)
    }
}

/// Which picture a city gets.
struct CityLook {
    enum Kind { case eiffel, clock, needle, fort, skyline, pagoda, dome, pyramid, lake, peaks, coast, desert }
    let kind: Kind
    let palette: ScenePalette

    static func of(_ city: String) -> CityLook {
        let key = PlaceFilter.normalize(city)
        let kind = landmarks.first { key.contains($0.key) }?.kind ?? fallback(key)
        return CityLook(kind: kind, palette: ScenePalette.palette(for: kind))
    }

    private static let landmarks: [(key: String, kind: Kind)] = [
        ("paris", .eiffel), ("london", .clock), ("dubai", .needle), ("abu dhabi", .needle), ("doha", .needle),
        ("shanghai", .needle), ("toronto", .needle), ("seattle", .needle),
        ("jaipur", .fort), ("udaipur", .fort), ("jodhpur", .fort), ("delhi", .fort), ("agra", .fort), ("mumbai", .fort),
        ("new york", .skyline), ("nyc", .skyline), ("brooklyn", .skyline), ("manhattan", .skyline), ("chicago", .skyline),
        ("hong kong", .skyline), ("singapore", .skyline), ("atlanta", .skyline), ("los angeles", .skyline), ("houston", .skyline),
        ("tokyo", .pagoda), ("kyoto", .pagoda), ("osaka", .pagoda), ("seoul", .pagoda), ("beijing", .pagoda), ("hanoi", .pagoda),
        ("rome", .dome), ("florence", .dome), ("istanbul", .dome), ("vatican", .dome), ("st petersburg", .dome), ("washington", .dome),
        ("cairo", .pyramid), ("giza", .pyramid), ("mexico city", .pyramid),
        ("zurich", .lake), ("lucerne", .lake), ("geneva", .lake), ("como", .lake), ("annecy", .lake), ("bern", .lake),
        ("interlaken", .peaks), ("zermatt", .peaks), ("aspen", .peaks), ("banff", .peaks), ("chamonix", .peaks), ("denver", .peaks),
        ("switzerland", .lake),
        ("lisbon", .coast), ("barcelona", .coast), ("sydney", .coast), ("tulum", .coast), ("miami", .coast), ("amalfi", .coast),
        ("positano", .coast), ("nice", .coast), ("honolulu", .coast), ("cape town", .coast), ("santorini", .coast), ("bali", .coast),
        ("marrakech", .desert), ("las vegas", .desert), ("phoenix", .desert), ("scottsdale", .desert), ("palm springs", .desert),
        ("jaisalmer", .desert), ("sedona", .desert),
    ]

    /// Anywhere else: a landscape picked from the name, so the same city always gets the same one.
    private static func fallback(_ key: String) -> Kind {
        let kinds: [Kind] = [.skyline, .coast, .lake, .peaks, .desert]
        let sum = key.unicodeScalars.reduce(0) { $0 + Int($1.value) }
        return kinds[sum % kinds.count]
    }
}

/// A scene's colours: sky (by time of day), then far, middle and near layers, and its lights.
struct ScenePalette {
    let day: [Color], dusk: [Color], night: [Color]
    let far: Color, mid: Color, near: Color, lights: Color

    func sky(hour: Int) -> [Color] {
        switch hour {
        case 6..<16: day
        case 16..<20: dusk
        default: night
        }
    }

    static func palette(for kind: CityLook.Kind) -> ScenePalette {
        switch kind {
        case .fort, .desert, .pyramid:
            ScenePalette(day: [hex(0xC9775A), hex(0xE7A97D), hex(0xF3D3A6)], dusk: [hex(0x6E3E4E), hex(0xC9775A), hex(0xF0B47F)],
                         night: [hex(0x2B2238), hex(0x5A3E58), hex(0x9C6B66)],
                         far: hex(0xC98763), mid: hex(0x8A4B3A), near: hex(0x4E2A25), lights: hex(0xFFE2A8))
        case .needle:
            ScenePalette(day: [hex(0x6C8BB0), hex(0xC4B8B0), hex(0xEBCFAE)], dusk: [hex(0x3E3358), hex(0xA2688A), hex(0xE8B48F)],
                         night: [hex(0x17142A), hex(0x2E2748), hex(0x6A4E68)],
                         far: hex(0xB9837F), mid: hex(0x5A3D55), near: hex(0x2A1E32), lights: hex(0xFFE6B0))
        case .eiffel, .dome:
            ScenePalette(day: [hex(0x7D93B8), hex(0xB9C3D6), hex(0xE6D5CC)], dusk: [hex(0x40496E), hex(0x8B86A8), hex(0xD9B8B2)],
                         night: [hex(0x1C2038), hex(0x34385C), hex(0x6C6684)],
                         far: hex(0x8C88A6), mid: hex(0x4A4768), near: hex(0x2B2944), lights: hex(0xFFDFA0))
        case .clock:
            ScenePalette(day: [hex(0x8A929C), hex(0xB9BDC0), hex(0xD9D5CC)], dusk: [hex(0x5F6670), hex(0x9CA1A6), hex(0xC9C6BE)],
                         night: [hex(0x1F242B), hex(0x3A4049), hex(0x6E7078)],
                         far: hex(0x8E9298), mid: hex(0x4C5158), near: hex(0x2E3238), lights: hex(0xF5D8A0))
        case .skyline, .pagoda:
            ScenePalette(day: [hex(0x6F8AB0), hex(0xAFC0D4), hex(0xE5DCCF)], dusk: [hex(0x3E4670), hex(0x8E7898), hex(0xE0A98E)],
                         night: [hex(0x1E2440), hex(0x3E4670), hex(0x7A6F8E)],
                         far: hex(0x4C5378), mid: hex(0x2A3052), near: hex(0x141830), lights: hex(0xFFD98E))
        case .coast:
            ScenePalette(day: [hex(0x5C86A6), hex(0xA9C4D2), hex(0xEBD9BF)], dusk: [hex(0x4B5F86), hex(0xC48E8E), hex(0xF0C79C)],
                         night: [hex(0x172238), hex(0x2D4260), hex(0x5E6E86)],
                         far: hex(0x7FA3B8), mid: hex(0x3E6A7E), near: hex(0x264552), lights: hex(0xFFF0C8))
        case .lake, .peaks:
            ScenePalette(day: [hex(0x5E6F8F), hex(0x9AA9C2), hex(0xC9CFD9)], dusk: [hex(0x4F5F80), hex(0x8E9EBB), hex(0xD2C7C0)],
                         night: [hex(0x1A2238), hex(0x33405E), hex(0x5E6A86)],
                         far: hex(0x7C8AA6), mid: hex(0x3D4A66), near: hex(0x24304A), lights: hex(0xF3D9A4))
        }
    }

    private static func hex(_ v: UInt32) -> Color { Color(hex: v) }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}

/// A small repeatable random source, so a city's picture is the same every time.
struct Seeded {
    private var state: UInt64
    init(_ seed: String) { state = seed.unicodeScalars.reduce(1469598103934665603) { ($0 ^ UInt64($1.value)) &* 1099511628211 } }
    mutating func next() -> CGFloat {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        return CGFloat((state >> 33) % 10_000) / 10_000
    }
}

private enum Shapes {
    static func ridge(_ w: CGFloat, _ h: CGFloat, base: CGFloat, amp: CGFloat, steps: Int, _ r: inout Seeded) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: 0, y: h)); p.addLine(to: CGPoint(x: 0, y: base))
        for i in 0...steps { p.addLine(to: CGPoint(x: w / CGFloat(steps) * CGFloat(i), y: base - r.next() * amp)) }
        p.addLine(to: CGPoint(x: w, y: h)); p.closeSubpath()
        return p
    }

    static func hills(_ w: CGFloat, _ h: CGFloat, base: CGFloat, amp: CGFloat, _ r: inout Seeded) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: 0, y: h)); p.addLine(to: CGPoint(x: 0, y: base))
        let n = 4
        for i in 0..<n {
            let x1 = w / CGFloat(n) * (CGFloat(i) + 0.5), x2 = w / CGFloat(n) * CGFloat(i + 1)
            p.addQuadCurve(to: CGPoint(x: x2, y: base - amp * r.next() * 0.3), control: CGPoint(x: x1, y: base - amp * (0.4 + r.next() * 0.8)))
        }
        p.addLine(to: CGPoint(x: w, y: h)); p.closeSubpath()
        return p
    }

    static func lights(_ ctx: inout GraphicsContext, _ w: CGFloat, base: CGFloat, color: Color, count: Int, _ r: inout Seeded) {
        for _ in 0..<count {
            let x = r.next() * w, y = base - r.next() * 26, d = 1.2 + r.next() * 1.6
            ctx.fill(Path(ellipseIn: CGRect(x: x, y: y, width: d, height: d)), with: .color(color.opacity(0.5 + r.next() * 0.5)))
        }
    }

    static func landmark(_ kind: CityLook.Kind, _ w: CGFloat, _ h: CGFloat, base: CGFloat, _ r: inout Seeded) -> Path {
        var p = Path()
        let cx = w * 0.62
        func poly(_ pts: [(CGFloat, CGFloat)]) { p.addLines(pts.map { CGPoint(x: $0.0, y: $0.1) }); p.closeSubpath() }
        switch kind {
        case .eiffel:
            let t = h * 0.46
            p.move(to: CGPoint(x: cx, y: base - t))
            p.addLine(to: CGPoint(x: cx + 4, y: base - t * 0.55)); p.addLine(to: CGPoint(x: cx + 14, y: base - t * 0.2))
            p.addLine(to: CGPoint(x: cx + 24, y: base)); p.addLine(to: CGPoint(x: cx + 12, y: base))
            p.addQuadCurve(to: CGPoint(x: cx - 12, y: base), control: CGPoint(x: cx, y: base - t * 0.14))
            p.addLine(to: CGPoint(x: cx - 24, y: base)); p.addLine(to: CGPoint(x: cx - 14, y: base - t * 0.2))
            p.addLine(to: CGPoint(x: cx - 4, y: base - t * 0.55)); p.closeSubpath()
        case .clock:
            let t = h * 0.42, b: CGFloat = 12
            poly([(cx - b, base), (cx - b, base - t * 0.72), (cx - b - 2, base - t * 0.76), (cx, base - t),
                  (cx + b + 2, base - t * 0.76), (cx + b, base - t * 0.72), (cx + b, base)])
            p.addRect(CGRect(x: w * 0.05, y: base - h * 0.12, width: w * 0.45, height: h * 0.12))
        case .needle:
            let t = h * 0.58
            poly([(cx, base - t), (cx + 3, base - t * 0.6), (cx + 7, base - t * 0.3), (cx + 11, base),
                  (cx - 11, base), (cx - 7, base - t * 0.3), (cx - 3, base - t * 0.6)])
            for i in 0..<6 {
                let bh = h * (0.08 + r.next() * 0.14)
                p.addRect(CGRect(x: w * (0.05 + CGFloat(i) * 0.09), y: base - bh, width: w * 0.06, height: bh))
            }
        case .fort:
            let y = base - h * 0.14
            p.addRect(CGRect(x: 0, y: y, width: w, height: h * 0.14))
            for i in 0..<4 {
                let x = w * (0.14 + CGFloat(i) * 0.24)
                p.addRect(CGRect(x: x - 6, y: y - 10, width: 12, height: 10))
                p.move(to: CGPoint(x: x - 8, y: y - 10)); p.addQuadCurve(to: CGPoint(x: x + 8, y: y - 10), control: CGPoint(x: x, y: y - 24)); p.closeSubpath()
            }
            for i in 0..<12 { p.addRect(CGRect(x: CGFloat(i) * w / 12, y: y - 4, width: w / 24, height: 4)) }
        case .skyline:
            var x: CGFloat = 0
            while x < w {
                let bw = w * (0.06 + r.next() * 0.07), bh = h * (0.18 + r.next() * 0.34)
                p.addRect(CGRect(x: x, y: base - bh, width: bw, height: bh)); x += bw + 1
            }
            poly([(cx - 9, base), (cx - 9, base - h * 0.5), (cx - 4, base - h * 0.55), (cx, base - h * 0.66),
                  (cx + 4, base - h * 0.55), (cx + 9, base - h * 0.5), (cx + 9, base)])
        case .pagoda:
            for tier in 0..<4 {
                let tw = 30 - CGFloat(tier) * 6, y = base - CGFloat(tier) * 16
                poly([(cx - tw, y - 10), (cx + tw, y - 10), (cx + tw - 6, y - 14), (cx - tw + 6, y - 14)])
                p.addRect(CGRect(x: cx - tw * 0.6, y: y - 10, width: tw * 1.2, height: 10))
            }
            p.addRect(CGRect(x: cx - 1, y: base - 82, width: 2, height: 20))
        case .dome:
            p.addRect(CGRect(x: cx - 30, y: base - 24, width: 60, height: 24))
            p.move(to: CGPoint(x: cx - 26, y: base - 24))
            p.addQuadCurve(to: CGPoint(x: cx + 26, y: base - 24), control: CGPoint(x: cx, y: base - 74)); p.closeSubpath()
            p.addRect(CGRect(x: cx - 2, y: base - 62, width: 4, height: 12))
            p.addRect(CGRect(x: w * 0.05, y: base - h * 0.1, width: w * 0.4, height: h * 0.1))
        case .pyramid:
            poly([(cx - 46, base), (cx, base - h * 0.3), (cx + 46, base)])
            poly([(cx - 96, base), (cx - 64, base - h * 0.18), (cx - 32, base)])
        default:
            break
        }
        return p
    }
}
