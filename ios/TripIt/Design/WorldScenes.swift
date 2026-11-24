import SwiftUI

/// The drawn places: Home's header shows your next trip's and home city's first, then the rest in a new order each
/// day; a card for one of these cities without a photo shows its scene.
enum WorldScenes {
    static let all: [WorldScene] = [
        kyoto, santorini, venice, agra, cappadocia, hongKong, iceland, rio, paris, marrakech, newYork, alps,
        tokyo, london, dubai, jaipur, bali, capeTown, amalfi, sydney, rome, barcelona, istanbul, cairo,
        lisbon, amsterdam, prague, bangkok, singapore, sanFrancisco, machuPicchu, maldives,
    ]

    /// The scene for a city, if it's one of the drawn places.
    static func find(_ city: String) -> WorldScene? {
        let key = PlaceFilter.normalize(city)
        guard !key.isEmpty else { return nil }
        return all.first { scene in scene.names.contains { key.contains($0) } }
    }

    /// Scenes for Home: these cities' first (in order, no repeats), then the others in an order that turns over daily.
    static func forHome(cities: [String], count: Int = 8, now: Date = Date()) -> [WorldScene] {
        var picked: [WorldScene] = []
        for city in cities {
            if let s = find(city), !picked.contains(s) { picked.append(s) }
        }
        let day = Calendar.current.ordinality(of: .day, in: .era, for: now) ?? 0
        let rest = all.filter { !picked.contains($0) }
        let k = rest.isEmpty ? 0 : (day * 3) % rest.count
        picked += Array(rest[k...] + rest[..<k])
        return Array(picked.prefix(count))
    }

    // MARK: - Japan

    static let kyoto = WorldScene(id: "kyoto", place: "Yasaka Pagoda, Kyoto", names: ["kyoto"], base: 0x8C5A7A) { p in
        p.sky([(0, 0x2D2342), (0.45, 0x8C5A7A), (0.8, 0xE7A68A), (1, 0xF4CDA0)])
        p.glow(270, 250, 120, 0xFFD9A8, 0.8)
        p.disc(270, 250, 26, 0xFFE7C4)
        p.ridge(300, 70, steps: 6, 0x7D5A7A, seed: "k1", rough: 0.7)
        p.haze(250, 90, 0xE7A68A, 0.5)
        p.ridge(330, 50, steps: 8, 0x5A3F5E, seed: "k2")
        WorldScenes.pagoda(p, x: 220, base: 370, scale: 1, 0x2B1E2A)
        var r = Seeded("kyoto")
        for i in 0..<14 {
            let x = CGFloat(i) * 30 - 10, h = 22 + r.next() * 16
            p.fill("M\(x) \(380 - h) L\(x + 17) \(360 - h) L\(x + 34) \(380 - h) Z", 0x2B1E2A)
            p.rect(x + 3, 380 - h, 28, h + 90, 0x3A2733)
            p.rect(x + 12, 392 - h, 8, 10, 0xF4C27A, 0.5 + Double(r.next()) * 0.5)
        }
        WorldScenes.blossoms(p, x: -20, y: 300, w: 120, h: 120, count: 160, seed: "kb1")
        WorldScenes.blossoms(p, x: 300, y: 330, w: 120, h: 120, count: 120, seed: "kb2")
        for i in 0..<9 {
            let x = 40 + CGFloat(i) * 38
            p.glow(x, 402, 16, 0xF7B267, 0.6)
            p.fill(Path(ellipseIn: CGRect(x: x - 4, y: 396, width: 8, height: 12)), 0xF7B267)
        }
        p.birds(7, 60, 120, spread: 120, 0x2B1E2A, seed: "kyb")
        p.grain()
    }

    static let tokyo = WorldScene(id: "tokyo", place: "Mount Fuji from Tokyo", names: ["tokyo", "osaka", "yokohama", "japan"], base: 0x3E4670) { p in
        p.sky([(0, 0x1E2A52), (0.5, 0x6C6A9A), (0.85, 0xE8A58C), (1, 0xF6C79C)])
        p.glow(110, 230, 120, 0xFFD3A8, 0.7)
        p.fill("M60 300 Q150 200 195 150 Q205 146 215 150 Q260 200 350 300 Z", 0x5E6494)
        p.fill("M180 166 Q195 150 210 150 Q222 160 232 178 Q220 172 212 182 Q204 170 196 182 Q188 172 180 178 Z", 0xF3F0F4)
        p.haze(250, 70, 0xE8A58C, 0.55)
        p.skyline(base: 360, minH: 30, maxH: 110, minW: 12, maxW: 24, 0x1B1F3B, lights: 0xFFD27A, seed: "tok", density: 0.4)
        // Tokyo Tower
        p.fill("M300 360 L306 240 L310 200 L312 160 L314 200 L318 240 L324 360 L316 360 L312 300 L308 360 Z", 0xE0533A)
        p.rect(298, 300, 28, 4, 0xF3F0F4)
        p.rect(303, 240, 18, 4, 0xF3F0F4)
        p.glow(312, 160, 12, 0xFFD27A, 0.8)
        p.water(360, top: 0x3A3A6A, bottom: 0x10122A, seed: "tokw", shimmer: 0xFFD27A, glints: 70)
        p.birds(5, 220, 110, spread: 80, 0x1B1F3B, seed: "tkb")
        p.grain()
    }

    // MARK: - Mediterranean

    static let santorini = WorldScene(id: "santorini", place: "Oia, Santorini", names: ["santorini", "oia", "mykonos", "greece", "athens"], base: 0xC78BA0) { p in
        p.sky([(0, 0x3B4F86), (0.5, 0xC78BA0), (0.8, 0xF2B391), (1, 0xF8D7A8)])
        p.glow(300, 290, 140, 0xFFD49A, 0.9)
        p.disc(300, 300, 22, 0xFFE9C6)
        p.water(300, top: 0xC7889B, bottom: 0x2D3F6B, seed: "sea", shimmer: 0xFFE3B8, glints: 70)
        p.fill("M0 460 L0 200 Q60 190 120 230 Q200 280 240 330 L260 460 Z", 0x7A4B4A)
        var r = Seeded("oia")
        let walls: [UInt32] = [0xFBF5EC, 0xF3E7D8, 0xEADCCB]
        for i in 0..<60 {
            let x = r.next() * 300
            let y = 230 + (x / 300) * 120 + r.next() * 70
            let w = 14 + r.next() * 16, h = 10 + r.next() * 10
            p.fill(Path(roundedRect: CGRect(x: x, y: y, width: w, height: h), cornerRadius: 1.5), walls[i % 3])
            if r.next() < 0.4 { p.rect(x + w / 2 - 1.5, y + h - 5, 3, 4, 0xF4B860) }
        }
        WorldScenes.dome(p, x: 70, y: 238, s: 1.4)
        WorldScenes.dome(p, x: 150, y: 280, s: 1.1)
        WorldScenes.dome(p, x: 36, y: 300, s: 1)
        p.fill("M318 360 L336 360 L333 365 L321 365 Z M327 345 L335 356 L327 356 Z", 0x1E2540)
        p.birds(5, 200, 110, spread: 90, 0x3B2F45, seed: "sb")
        p.grain()
    }

    static let amalfi = WorldScene.scripted(id: "amalfi", place: "Positano, Amalfi Coast", names: ["amalfi", "positano", "sorrento", "capri", "naples"], base: 0x9CC3DC, script: SceneScripts.amalfi)

    static let venice = WorldScene(id: "venice", place: "Grand Canal, Venice", names: ["venice", "venezia"], base: 0xD9A070) { p in
        p.sky([(0, 0x5E78A8), (0.6, 0xE3B9A4), (1, 0xF2D5B8)])
        p.glow(120, 140, 150, 0xFFE1BE, 0.7)
        p.fill("M250 170 Q290 120 330 170 Z", 0x9E9AA0)
        p.rect(250, 170, 80, 40, 0xC8BFB6)
        p.rect(288, 140, 4, 12, 0x9E9AA0)
        p.haze(150, 80, 0xEAC9B5, 0.6)
        let palazzi: (Painter) -> Void = { q in
            var r = Seeded("ven")
            let walls: [UInt32] = [0xC9805E, 0xD9A070, 0xB86F55, 0xE0B38A]
            var x: CGFloat = -10
            while x < Painter.W {
                let w = 34 + r.next() * 30, h = 90 + r.next() * 70
                q.rect(x, 300 - h, w, h, walls[Int(r.next() * 4) % 4])
                var yy = 300 - h + 12
                while yy < 290 {
                    var xx = x + 6
                    while xx < x + w - 8 {
                        q.fill("M\(xx) \(yy + 10) L\(xx) \(yy + 3) Q\(xx + 3) \(yy - 1) \(xx + 6) \(yy + 3) L\(xx + 6) \(yy + 10) Z", r.next() < 0.3 ? 0xF9D48C : 0x5B3A33, 0.9)
                        xx += 11
                    }
                    yy += 18
                }
                x += w + 1
            }
        }
        palazzi(p)
        p.water(300, top: 0x4D6B7A, bottom: 0x1F3240, seed: "canal", shimmer: 0xF9D48C, glints: 80)
        p.reflect(300, opacity: 0.28, palazzi)
        p.fill("M70 392 Q140 404 220 386 Q214 396 200 398 Q140 410 80 398 Z", 0x141018)
        p.stroke("M188 388 L200 356", 0x141018, width: 2)
        p.grain()
    }

    static let rome = WorldScene(id: "rome", place: "The Colosseum, Rome", names: ["rome", "roma", "vatican", "italy"], base: 0xE8B48F) { p in
        p.sky([(0, 0x6A7FB0), (0.55, 0xE3B39A), (1, 0xF6D2A8)])
        p.glow(300, 200, 140, 0xFFE2B8, 0.8)
        p.ridge(330, 40, steps: 6, 0xB98E7A, seed: "r1")
        // Colosseum: four tiers of arches, the top one broken away on the right
        p.fill("M40 340 L40 200 Q195 180 350 200 L350 260 L300 250 L290 225 L260 230 L250 205 L230 210 L200 196 L40 196 Z", 0xD9A47A)
        for tier in 0..<3 {
            let y = 330 - CGFloat(tier) * 42
            var x: CGFloat = 50
            while x < 330 - CGFloat(tier) * 20 {
                p.fill("M\(x) \(y) L\(x) \(y - 22) Q\(x + 8) \(y - 34) \(x + 16) \(y - 22) L\(x + 16) \(y) Z", 0x7A4A36, 0.85)
                x += 24
            }
        }
        p.rect(40, 340, 310, 6, 0xB98058)
        var r = Seeded("pines")
        for i in 0..<5 {
            let x = CGFloat(i) * 90 - 20 + r.next() * 20
            p.rect(x + 18, 350, 3, 60, 0x3A2A22)
            p.fill("M\(x) 356 Q\(x + 20) 326 \(x + 42) 356 Q\(x + 20) 364 \(x) 356 Z", 0x3E5A3A)
        }
        p.rect(0, 400, Painter.W, 60, 0x5E4A3A)
        p.birds(6, 220, 100, spread: 100, 0x5A3A3A, seed: "rb")
        p.grain()
    }

    static let barcelona = WorldScene(id: "barcelona", place: "Sagrada Família, Barcelona", names: ["barcelona", "spain", "madrid"], base: 0xE8A57E) { p in
        p.sky([(0, 0x3E5A92), (0.5, 0xC897A0), (0.85, 0xF2B48A), (1, 0xF7CF9A)])
        p.glow(90, 260, 130, 0xFFDAA8, 0.8)
        p.haze(260, 80, 0xF2B48A, 0.5)
        let spires: [(CGFloat, CGFloat)] = [(160, 120), (185, 90), (210, 70), (235, 95), (260, 130), (290, 150)]
        for (x, top) in spires {
            p.fill("M\(x - 9) 330 L\(x - 7) \(top + 40) Q\(x) \(top - 10) \(x + 7) \(top + 40) L\(x + 9) 330 Z", 0x6E4E48)
            p.disc(x, top + 2, 3, 0xF2C46A)
            var yy = top + 50
            while yy < 320 { p.rect(x - 3, yy, 6, 2, 0x4A3430); yy += 9 }
        }
        p.rect(140, 300, 170, 40, 0x6E4E48)
        p.skyline(base: 380, minH: 20, maxH: 50, minW: 18, maxW: 28, 0x4A3A4A, lights: 0xFFD99A, seed: "bcn", density: 0.3)
        var r = Seeded("palms")
        for i in 0..<4 {
            let x = 20 + CGFloat(i) * 110 + r.next() * 30
            p.stroke("M\(x) 460 Q\(x + 4) 420 \(x + 2) 380", 0x2A2026, width: 3)
            p.fill("M\(x + 2) 380 Q\(x - 20) 372 \(x - 30) 390 Q\(x - 12) 378 \(x + 2) 382 Q\(x + 20) 370 \(x + 34) 388 Q\(x + 16) 376 \(x + 2) 380 Z", 0x2A2026)
        }
        p.grain()
    }

    static let lisbon = WorldScene(id: "lisbon", place: "Alfama, Lisbon", names: ["lisbon", "lisboa", "porto", "portugal"], base: 0xF2C39A) { p in
        p.sky([(0, 0x6A92C2), (0.6, 0xC9DCE6), (1, 0xF6DDB8)])
        p.glow(320, 140, 110, 0xFFF2D8, 0.7)
        p.water(250, top: 0x8AB4C9, bottom: 0x5C8AA6, seed: "tejo", glints: 30)
        p.fill("M220 250 L232 232 L246 250 Z M300 250 L312 236 L324 250 Z", 0xEDEDED, 0.7)
        var r = Seeded("alfama")
        let colours: [UInt32] = [0xF2C38A, 0xE9967A, 0xF6E6C8, 0x9CC0D8, 0xF3D9A0]
        for row in 0..<6 {
            var x: CGFloat = -10 + CGFloat(row % 2) * 12
            let y = 270 + CGFloat(row) * 28
            while x < Painter.W {
                let w = 26 + r.next() * 14
                p.rect(x, y, w, 30, colours[Int(r.next() * 5) % 5])
                p.fill("M\(x - 2) \(y) L\(x + w / 2) \(y - 8) L\(x + w + 2) \(y) Z", 0xB5563A)
                p.rect(x + 6, y + 10, 4, 6, 0x5A4030)
                p.rect(x + w - 12, y + 10, 4, 6, 0x5A4030)
                x += w + 2
            }
        }
        // Tram 28
        p.stroke("M0 368 L390 356", 0x3A2A22, width: 0.8)
        p.stroke("M165 398 L178 362", 0x3A2A22, width: 1.2)
        p.fill(Path(roundedRect: CGRect(x: 118, y: 396, width: 94, height: 6), cornerRadius: 3), 0xE8E2D0)
        p.fill(Path(roundedRect: CGRect(x: 120, y: 400, width: 90, height: 34), cornerRadius: 6), 0xF2C230)
        var pane: CGFloat = 126
        while pane < 204 { p.rect(pane, 406, 11, 12, 0xFFF2C0); pane += 13 }
        p.rect(120, 420, 90, 2, 0xC9302C)
        p.rect(188, 422, 10, 12, 0x8A6A2A)
        p.rect(110, 434, 110, 3, 0x3A2A22)
        p.disc(140, 436, 4, 0x2A2220)
        p.disc(190, 436, 4, 0x2A2220)
        p.grain()
    }

    // MARK: - India and Middle East

    static let agra = WorldScene(id: "agra", place: "Taj Mahal, Agra", names: ["agra", "taj"], base: 0xF3D2B6) { p in
        p.sky([(0, 0xE8B7A0), (0.5, 0xF3D2B6), (1, 0xF7E4CC)])
        p.glow(195, 180, 170, 0xFFF1DE, 0.9)
        p.haze(270, 40, 0xF7E4CC, 0.9)
        let taj: (Painter) -> Void = { q in
            q.rect(135, 230, 120, 70, 0xF6ECE0)
            q.fill("M155 230 Q195 150 235 230 Z", 0xF6ECE0)
            q.rect(193, 160, 4, 12, 0xF6ECE0)
            for x: CGFloat in [100, 290] {
                q.rect(x - 3, 170, 6, 130, 0xF6ECE0)
                q.disc(x, 168, 6, 0xF6ECE0)
            }
            for x: CGFloat in [150, 240] { q.fill("M\(x - 12) 232 Q\(x) 205 \(x + 12) 232 Z", 0xF6ECE0) }
            q.fill("M180 300 L180 260 Q195 240 210 260 L210 300 Z", 0xE6C9A6)
        }
        taj(p)
        var r = Seeded("agra")
        for i in 0..<18 {
            let x = CGFloat(i) * 23 - 5
            p.fill("M\(x) 330 Q\(x + 4) \(300 - r.next() * 20) \(x + 8) 330 Z", 0x3E5A44)
        }
        p.water(330, top: 0xC9B7A6, bottom: 0x8E8A86, seed: "pool", glints: 20)
        p.reflect(330, opacity: 0.3, taj)
        p.rect(0, 328, Painter.W, 3, 0xB8A08A)
        p.birds(6, 230, 90, spread: 100, 0x6E5546, seed: "ab")
        p.grain()
    }

    static let jaipur = WorldScene(id: "jaipur", place: "Hawa Mahal, Jaipur", names: ["jaipur", "udaipur", "jodhpur", "rajasthan", "delhi"], base: 0xE39A84) { p in
        p.sky([(0, 0x5A86B6), (0.55, 0xE9C3A6), (1, 0xF6D9B0)])
        p.glow(330, 120, 110, 0xFFF2D6, 0.7)
        // The palace of winds: a pink honeycomb of little windows rising to a peak
        p.fill("M60 400 L60 220 L100 200 L140 170 L195 130 L250 170 L290 200 L330 220 L330 400 Z", 0xE3907A)
        var tier: CGFloat = 0
        while tier < 6 {
            let y = 380 - tier * 34
            let inset = max(0, tier - 2) * 30
            var x = 70 + inset
            while x < 316 - inset {
                p.fill("M\(x) \(y) L\(x) \(y - 16) Q\(x + 7) \(y - 26) \(x + 14) \(y - 16) L\(x + 14) \(y) Z", 0xF6D3C0)
                p.rect(x + 4, y - 14, 6, 10, 0x9C4A3E, 0.8)
                x += 20
            }
            tier += 1
        }
        for x: CGFloat in [100, 140, 195, 250, 290] {
            p.fill("M\(x - 8) \(x == 195 ? 130 : 180) Q\(x) \(x == 195 ? 112 : 166) \(x + 8) \(x == 195 ? 130 : 180) Z", 0xF6D3C0)
        }
        p.rect(0, 400, Painter.W, 60, 0x8A5A4A)
        p.rect(0, 400, Painter.W, 2, 0x6E4438)
        for x: CGFloat in [10, 334, 362] {
            p.fill("M\(x) 400 L\(x) 372 Q\(x + 9) 360 \(x + 18) 372 L\(x + 18) 400 Z", 0xD98470)
            p.fill("M\(x + 4) 400 L\(x + 4) 376 Q\(x + 9) 368 \(x + 14) 376 L\(x + 14) 400 Z", 0x7A3A30)
        }
        p.birds(9, 120, 70, spread: 160, 0x5A3A3A, seed: "pigeons")
        p.grain()
    }

    static let dubai = WorldScene.scripted(id: "dubai", place: "Burj Khalifa, Dubai", names: ["dubai", "abu dhabi", "doha", "uae", "qatar"], base: 0x7A5A86, script: SceneScripts.dubai)

    static let istanbul = WorldScene(id: "istanbul", place: "Blue Mosque, Istanbul", names: ["istanbul", "turkey", "ankara"], base: 0xB98A9A) { p in
        p.sky([(0, 0x34406E), (0.55, 0xB98A9A), (0.85, 0xEFB28E), (1, 0xF6CFA0)])
        p.glow(80, 250, 120, 0xFFD6A6, 0.7)
        let mosque: (Painter) -> Void = { q in
            q.fill("M120 280 Q195 200 270 280 Z", 0x3A3654)
            let domes: [(CGFloat, CGFloat)] = [(130, 26), (260, 26), (165, 18), (225, 18)]
            for (x, r) in domes {
                q.fill("M\(x - r) 290 Q\(x) \(290 - r * 1.6) \(x + r) 290 Z", 0x3A3654)
            }
            q.rect(110, 280, 170, 30, 0x3A3654)
            for x: CGFloat in [80, 110, 280, 310] {
                q.rect(x - 2.5, 170, 5, 140, 0x3A3654)
                q.fill("M\(x - 3) 172 L\(x) 150 L\(x + 3) 172 Z", 0x3A3654)
                q.rect(x - 4, 220, 8, 3, 0x3A3654)
            }
            q.rect(190, 196, 1.5, 12, 0x3A3654)
        }
        mosque(p)
        p.water(310, top: 0x5A5A86, bottom: 0x1E2240, seed: "bos", shimmer: 0xFFD6A6, glints: 70)
        p.reflect(310, opacity: 0.28, mosque)
        p.fill("M220 380 Q280 392 340 378 L334 388 L226 388 Z", 0x1A1A2A)
        p.rect(260, 368, 40, 12, 0x1A1A2A)
        p.birds(10, 120, 120, spread: 180, 0x2A2640, seed: "gulls")
        p.grain()
    }

    static let cairo = WorldScene(id: "cairo", place: "The Pyramids, Giza", names: ["cairo", "giza", "egypt", "luxor"], base: 0xE6B07E) { p in
        p.sky([(0, 0x5C7EB0), (0.55, 0xEBC39A), (1, 0xF6D8A8)])
        p.glow(300, 230, 150, 0xFFE8C0, 0.85)
        p.disc(300, 230, 20, 0xFFF0D0)
        p.haze(280, 60, 0xF6D8A8, 0.7)
        p.fill("M60 330 L160 190 L260 330 Z", 0xC98E5A)
        p.fill("M160 190 L260 330 L200 330 Z", 0xA8724A)
        p.fill("M230 330 L300 240 L370 330 Z", 0xC98E5A)
        p.fill("M300 240 L370 330 L330 330 Z", 0xA8724A)
        p.fill("M10 330 L50 285 L90 330 Z", 0xB88252)
        p.fill("M0 460 L0 330 Q200 316 390 334 L390 460 Z", 0xE0B07A)
        p.fill("M0 460 L0 380 Q110 352 230 374 Q320 390 390 366 L390 460 Z", 0xD49E68)
        p.stroke("M0 380 Q110 352 230 374 Q320 390 390 366", 0xF2CC96, width: 1)
        // Date palms at the edge of the plateau
        for (x, h) in [(CGFloat(28), CGFloat(70)), (52, 54), (356, 62)] {
            let top = 340 - h
            p.stroke("M\(x) 340 Q\(x + 4) \(top + h / 2) \(x + 1) \(top)", 0x5A4030, width: 2.4)
            for (dx, dy) in [(-16.0, 8.0), (-12.0, -6.0), (0.0, -10.0), (12.0, -6.0), (16.0, 8.0)] {
                p.stroke("M\(x + 1) \(top) Q\(x + 1 + CGFloat(dx) / 2) \(top + CGFloat(dy) - 6) \(x + 1 + CGFloat(dx)) \(top + CGFloat(dy))", 0x4A5A3A, width: 2)
            }
        }
        p.grain()
    }

    static let marrakech = WorldScene(id: "marrakech", place: "Jemaa el-Fnaa, Marrakech", names: ["marrakech", "morocco", "fez", "fes"], base: 0xB3577A) { p in
        p.sky([(0, 0x3B2A55), (0.5, 0xB3577A), (0.85, 0xF08A5D), (1, 0xF7B26A)])
        p.glow(110, 300, 160, 0xFFC782, 0.8)
        p.ridge(340, 50, steps: 5, 0x7A4560, seed: "atlas", rough: 0.8)
        p.fill("M60 324 L72 284 L84 324 Z", 0xE8D6E0, 0.25)
        p.rect(250, 130, 40, 220, 0xB5643F)
        p.rect(258, 100, 24, 30, 0xB5643F)
        p.rect(266, 80, 8, 20, 0xB5643F)
        for y: CGFloat in [150, 190, 230, 270, 310] { p.fill("M262 \(y) L262 \(y - 12) Q270 \(y - 20) 278 \(y - 12) L278 \(y) Z", 0x6B3420) }
        p.disc(270, 76, 3, 0xE8C05A)
        p.rect(0, 350, Painter.W, 110, 0x4A2A1E)
        var r = Seeded("stalls")
        let awnings: [UInt32] = [0xC0392B, 0xE67E22, 0xF1C40F, 0xECF0F1]
        for i in 0..<16 {
            let x = CGFloat(i) * 25, y = 360 + r.next() * 20
            p.glow(x + 12, y + 6, 20, 0xFFC46B, 0.55)
            p.fill("M\(x) \(y) L\(x + 12) \(y - 14) L\(x + 24) \(y) Z", awnings[i % 4], 0.9)
            p.rect(x + 4, y, 16, 40, 0x3B2316)
        }
        p.birds(8, 40, 110, spread: 140, 0x2A1A30, seed: "mb")
        p.grain()
    }

    static let cappadocia = WorldScene(id: "cappadocia", place: "Göreme, Cappadocia", names: ["cappadocia", "goreme"], base: 0xF4C7A4) { p in
        p.sky([(0, 0x7FA3C9), (0.55, 0xF4C7A4), (1, 0xF7DDBE)])
        p.glow(90, 300, 140, 0xFFE0B6, 0.8)
        p.ridge(320, 60, steps: 7, 0xD8A887, seed: "c1")
        p.haze(280, 80, 0xF7DDBE, 0.6)
        var r = Seeded("balloons")
        let colours: [UInt32] = [0xD9534F, 0xF0AD4E, 0x5B8DB8, 0xE8D44D, 0x8E5BA8, 0x5FA67A]
        for i in 0..<14 {
            let x = r.next() * Painter.W, y = 60 + r.next() * 200, s = 0.4 + r.next() * 0.9
            let o = 0.55 + Double(s) * 0.4
            p.fill(Path(ellipseIn: CGRect(x: x - 12 * s, y: y - 15 * s, width: 24 * s, height: 30 * s)), colours[i % 6], o)
            p.fill("M\(x - 10 * s) \(y + 6 * s) L\(x - 3 * s) \(y + 20 * s) L\(x + 3 * s) \(y + 20 * s) L\(x + 10 * s) \(y + 6 * s) Z", colours[i % 6], o * 0.85)
            p.rect(x - 3 * s, y + 20 * s, 6 * s, 4 * s, 0x5A3B2A, o)
        }
        for i in 0..<11 {
            let x = CGFloat(i) * 38 + r.next() * 10, h = 60 + r.next() * 60
            p.fill("M\(x) 400 L\(x + 8) \(400 - h) Q\(x + 16) \(386 - h) \(x + 24) \(400 - h) L\(x + 32) 400 Z", 0xB97F5C)
            p.fill(Path(roundedRect: CGRect(x: x + 13, y: 400 - h * 0.55, width: 5, height: 7), cornerRadius: 2), 0x5A3B2A)
        }
        p.ridge(430, 30, steps: 6, 0x8A5A42, seed: "c2")
        p.grain()
    }

    // MARK: - Europe

    static let paris = WorldScene.scripted(id: "paris", place: "The Eiffel Tower, Paris", names: ["paris", "france"], base: 0x4A4270, script: SceneScripts.paris)

    static let london = WorldScene.scripted(id: "london", place: "Westminster, London", names: ["london", "england", "uk"], base: 0x7E8498, script: SceneScripts.london)

    static let amsterdam = WorldScene(id: "amsterdam", place: "Canal houses, Amsterdam", names: ["amsterdam", "netherlands", "rotterdam"], base: 0x8A9AB8) { p in
        p.sky([(0, 0x3E4E7A), (0.6, 0xA9B4CC), (1, 0xEFD8C0)])
        p.glow(320, 150, 100, 0xFFEBCC, 0.6)
        let houses: (Painter) -> Void = { q in
            var r = Seeded("ams")
            let colours: [UInt32] = [0x5A3A30, 0x3E4A5A, 0x7A5A40, 0x2E3A30, 0x8A4A3A]
            var x: CGFloat = -4
            while x < Painter.W {
                let w = 30 + r.next() * 10, h = 120 + r.next() * 60, top = 300 - h
                q.rect(x, top, w, h, colours[Int(r.next() * 5) % 5])
                q.fill("M\(x + 4) \(top) L\(x + 4) \(top - 10) L\(x + 10) \(top - 10) L\(x + 10) \(top - 18) Q\(x + w / 2) \(top - 32) \(x + w - 10) \(top - 18) L\(x + w - 10) \(top - 10) L\(x + w - 4) \(top - 10) L\(x + w - 4) \(top) Z", colours[Int(r.next() * 5) % 5])
                var yy = top + 10
                while yy < 290 {
                    q.rect(x + 6, yy, 7, 10, r.next() < 0.4 ? 0xFFD98A : 0xE8E2D6, 0.9)
                    q.rect(x + w - 13, yy, 7, 10, r.next() < 0.4 ? 0xFFD98A : 0xE8E2D6, 0.9)
                    yy += 20
                }
                x += w + 1
            }
        }
        houses(p)
        p.water(300, top: 0x4A5A6E, bottom: 0x1E2A36, seed: "gracht", shimmer: 0xFFD98A, glints: 70)
        p.reflect(300, opacity: 0.3, houses)
        p.fill("M40 300 Q195 250 350 300 L350 310 Q195 266 40 310 Z", 0x3A2E2A)
        // Bicycles on the bridge
        for x: CGFloat in [150, 210] {
            for wx in [x, x + 16] {
                p.ctx.stroke(Path(ellipseIn: CGRect(x: wx - 6, y: 284, width: 12, height: 12)), with: .color(Painter.color(0x1A1A1A)), lineWidth: 1)
            }
            p.stroke("M\(x) 290 L\(x + 7) 282 L\(x + 16) 290 M\(x + 7) 282 L\(x + 5) 278", 0x1A1A1A, width: 1)
        }
        p.grain()
    }

    static let prague = WorldScene(id: "prague", place: "Charles Bridge, Prague", names: ["prague", "praha", "czech", "vienna", "budapest"], base: 0x7E7AA0) { p in
        p.sky([(0, 0x272E52), (0.55, 0x7E7AA0), (0.85, 0xDCA79A), (1, 0xF0C49C)])
        p.stars(30, maxY: 110, seed: "prs")
        p.glow(200, 220, 140, 0xFFD6A6, 0.5)
        let castle: (Painter) -> Void = { q in
            q.ridge(250, 30, steps: 5, 0x3A3A5A, seed: "hill")
            q.rect(110, 200, 170, 40, 0x2E2E4A)
            q.windows(110, 200, 170, 40, 0xFFD58A, seed: "hrad", density: 0.4)
            let spires: [(CGFloat, CGFloat)] = [(170, 90), (200, 110), (230, 80)]
            for (x, h) in spires {
                q.rect(x - 6, 200 - h + 30, 12, h - 30, 0x2E2E4A)
                q.fill("M\(x - 7) \(230 - h) L\(x) \(190 - h) L\(x + 7) \(230 - h) Z", 0x2E2E4A)
            }
            q.skyline(base: 300, minH: 20, maxH: 60, minW: 16, maxW: 26, 0x34344E, lights: 0xFFD58A, seed: "mala", density: 0.3)
        }
        castle(p)
        p.water(300, top: 0x3E4470, bottom: 0x161A30, seed: "vltava", shimmer: 0xFFD58A, glints: 70)
        p.reflect(300, opacity: 0.28, castle)
        // The bridge: arches and statues with lamps
        p.rect(0, 330, Painter.W, 14, 0x2A2638)
        var x: CGFloat = 0
        while x < Painter.W { p.fill("M\(x) 344 Q\(x + 30) 314 \(x + 60) 344 L\(x + 60) 360 L\(x) 360 Z", 0x2A2638); x += 60 }
        for sx: CGFloat in [40, 120, 200, 280, 360] {
            p.rect(sx - 2, 312, 4, 18, 0x2A2638)
            p.glow(sx + 8, 312, 10, 0xFFD58A, 0.8)
        }
        p.grain()
    }

    static let alps = WorldScene(id: "alps", place: "Lake Lucerne, Switzerland", names: ["switzerland", "zurich", "lucerne", "luzern", "geneva", "interlaken", "zermatt", "bern", "alps", "chamonix", "lake como", "como", "innsbruck"], base: 0x8E9EBB) { p in
        p.sky([(0, 0x5D7AAE), (0.6, 0xB9C8DE), (1, 0xE7E2DA)])
        p.glow(300, 120, 110, 0xFFF4E0, 0.7)
        let peaks: (Painter) -> Void = { q in
            q.fill("M0 290 L60 210 L90 240 L150 150 L190 200 L230 160 L290 240 L330 200 L390 270 L390 330 L0 330 Z", 0x5C6E8E)
            q.fill("M150 150 L165 175 L158 172 L150 182 L142 170 L134 176 Z M230 160 L245 182 L236 178 L226 186 L220 176 Z M60 210 L72 228 L64 226 L56 232 L50 224 Z", 0xF2F4F7)
        }
        peaks(p)
        p.haze(250, 80, 0xE7E2DA, 0.5)
        p.ridge(345, 40, steps: 7, 0x2C3F4C, seed: "a2")
        p.water(345, top: 0x6F86A6, bottom: 0x2D3E57, seed: "luc", glints: 40)
        p.reflect(345, opacity: 0.25, peaks)
        var r = Seeded("alps")
        for _ in 0..<30 {
            let x = r.next() * Painter.W, y = 370 + r.next() * 60, s = 0.6 + r.next() * 0.9
            p.fill("M\(x) \(y - 26 * s) L\(x + 8 * s) \(y) L\(x - 8 * s) \(y) Z", 0x14231F)
        }
        p.fill("M300 352 L318 338 L336 352 Z", 0x3B2418)
        p.rect(304, 352, 28, 16, 0x6B4228)
        p.rect(314, 356, 6, 6, 0xFFD98A)
        p.birds(4, 70, 90, spread: 80, 0x2C3F4C, seed: "alb")
        p.grain()
    }

    static let iceland = WorldScene(id: "iceland", place: "Kirkjufell, Iceland", names: ["iceland", "reykjavik", "norway", "tromso", "lapland", "finland"], base: 0x0E2A3A) { p in
        p.sky([(0, 0x05101C), (0.6, 0x0E2A3A), (1, 0x1C4A54)])
        p.stars(160, maxY: 260, seed: "ices")
        let aurora: (Painter) -> Void = { q in
            var r = Seeded("aurora")
            let greens: [UInt32] = [0x6BF2B5, 0x57D9C9, 0x9BF78A]
            for i in 0..<6 {
                let fi = CGFloat(i)
                let d = "M\(-40 + fi * 10) \(120 + fi * 14) Q\(100 + r.next() * 60) \(40 + r.next() * 40) \(220 + r.next() * 40) \(110 + fi * 8) Q\(300 + r.next() * 40) \(80 + r.next() * 40) \(430) \(70 + fi * 12)"
                q.ctx.stroke(SVGPath.parse(d), with: .color(Painter.color(greens[i % 3], 0.12 + Double(r.next()) * 0.12)),
                             style: StrokeStyle(lineWidth: 14 + r.next() * 18, lineCap: .round))
            }
        }
        let mountain: (Painter) -> Void = { q in
            q.fill("M120 320 Q170 220 210 150 Q230 160 260 220 Q300 290 330 320 Z", 0x1A2633)
            q.fill("M200 165 Q210 152 218 158 Q226 170 236 190 Q222 184 214 192 Q206 180 196 188 Z", 0xDDE8F0, 0.8)
        }
        aurora(p)
        p.ridge(330, 30, steps: 5, 0x13202B, seed: "i1")
        mountain(p)
        p.water(330, top: 0x0F2A36, bottom: 0x050C14, seed: "icew", shimmer: 0x6BF2B5, glints: 50)
        p.reflect(330, opacity: 0.22) { q in aurora(q); mountain(q) }
        p.fill("M20 400 L30 378 L40 400 Z M44 404 L52 388 L60 404 Z", 0x0A1520)
        p.grain()
    }

    // MARK: - Asia

    static let hongKong = WorldScene(id: "hongkong", place: "Victoria Harbour, Hong Kong", names: ["hong kong", "macau", "shanghai", "shenzhen"], base: 0x2B3466) { p in
        p.sky([(0, 0x0B0F26), (0.6, 0x2B3466), (1, 0x6A5A8E)])
        p.stars(80, maxY: 160, seed: "hks")
        p.fill("M0 460 L0 150 Q90 100 180 140 Q260 110 390 160 L390 460 Z", 0x1E2647)
        p.haze(200, 120, 0x6A5A8E, 0.35)
        let towers: (Painter) -> Void = { q in
            q.skyline(base: 300, minH: 70, maxH: 240, minW: 14, maxW: 36, 0x141A33, lights: 0xFFD58A, seed: "hk", density: 0.4, gap: 2)
        }
        towers(p)
        p.water(300, top: 0x1A2148, bottom: 0x070A18, seed: "hkw", shimmer: 0xFFD58A, glints: 120)
        p.reflect(300, opacity: 0.3, towers)
        p.fill("M230 360 Q260 370 300 360 L295 368 L236 368 Z", 0x0B0F1F)
        p.fill("M262 360 L262 318 Q285 326 290 346 Z", 0xC45B3A, 0.9)
        p.grain()
    }

    static let singapore = WorldScene(id: "singapore", place: "Marina Bay, Singapore", names: ["singapore", "kuala lumpur", "malaysia"], base: 0x3A4A7A) { p in
        p.sky([(0, 0x141C3E), (0.6, 0x4A4A86), (1, 0xC9809A)])
        p.stars(50, maxY: 140, seed: "sgs")
        let bay: (Painter) -> Void = { q in
            q.skyline(base: 300, minH: 60, maxH: 170, minW: 14, maxW: 26, 0x1A2040, lights: 0xFFE3A8, seed: "sg", density: 0.4)
            for x: CGFloat in [230, 270, 310] {
                q.fill("M\(x) 300 L\(x + 2) 170 L\(x + 24) 170 L\(x + 22) 300 Z", 0x232A4E)
                q.windows(x + 2, 170, 20, 130, 0xFFE3A8, seed: "mbs\(Int(x))", density: 0.5)
            }
            q.fill("M222 170 Q280 156 342 168 L342 160 Q280 148 222 162 Z", 0x2E3660)
        }
        bay(p)
        p.water(300, top: 0x2A3060, bottom: 0x0A0E24, seed: "sgw", shimmer: 0xFFE3A8, glints: 100)
        p.reflect(300, opacity: 0.3, bay)
        // Supertrees glowing on the shore
        for x: CGFloat in [40, 80, 130] {
            p.stroke("M\(x) 400 L\(x) 340", 0x3A2A5A, width: 4)
            p.fill("M\(x - 18) 340 Q\(x) 326 \(x + 18) 340 Q\(x) 346 \(x - 18) 340 Z", 0xB05AC8, 0.85)
            p.glow(x, 338, 24, 0xD08AF0, 0.4)
        }
        p.grain()
    }

    static let bangkok = WorldScene(id: "bangkok", place: "Wat Arun, Bangkok", names: ["bangkok", "thailand", "chiang mai", "phuket"], base: 0xE39A6A) { p in
        p.sky([(0, 0x4A4A86), (0.55, 0xE39A8A), (0.85, 0xF7B46A), (1, 0xF9D08A)])
        p.glow(310, 240, 130, 0xFFD890, 0.85)
        let wat: (Painter) -> Void = { q in
            q.fill("M150 300 L170 220 L180 160 L190 110 L195 60 L200 110 L210 160 L220 220 L240 300 Z", 0x6A3A46)
            for y: CGFloat in [160, 200, 240, 280] { q.rect(176 - (y - 160) * 0.18, y, 38 + (y - 160) * 0.36, 3, 0xF2C46A, 0.8) }
            for x: CGFloat in [110, 280] { q.fill("M\(x - 14) 300 L\(x - 4) 240 L\(x) 210 L\(x + 4) 240 L\(x + 14) 300 Z", 0x6A3A46) }
        }
        wat(p)
        p.water(300, top: 0xC98A7A, bottom: 0x4A3046, seed: "chao", shimmer: 0xFFD890, glints: 70)
        p.reflect(300, opacity: 0.3, wat)
        p.fill("M40 380 Q120 392 200 378 L194 388 L46 388 Z", 0x2A1A22)
        p.fill("M60 378 Q110 360 170 378 Z", 0xC0392B, 0.85)
        p.birds(6, 220, 100, spread: 100, 0x3A2A3A, seed: "bkb")
        p.grain()
    }

    static let bali = WorldScene(id: "bali", place: "Rice terraces, Bali", names: ["bali", "ubud", "indonesia", "lombok"], base: 0x8AB87A) { p in
        p.sky([(0, 0x6C9AC8), (0.55, 0xBFD8D0), (1, 0xF4E0B0)])
        p.glow(90, 150, 120, 0xFFF2D0, 0.7)
        p.fill("M200 220 Q260 120 320 220 Z", 0x7A90A8, 0.7)
        p.haze(190, 60, 0xE8F0E0, 0.6)
        let greens: [UInt32] = [0x5E8A4A, 0x6E9E56, 0x7EB062, 0x8EC06E, 0x6A9A50, 0x7AAA5C]
        for i in 0..<8 {
            let y = 230 + CGFloat(i) * 30
            p.fill("M0 460 L0 \(y) Q100 \(y - 14) 200 \(y + 4) Q300 \(y + 18) 390 \(y - 6) L390 460 Z", greens[i % 6])
            p.stroke("M0 \(y + 2) Q100 \(y - 12) 200 \(y + 6) Q300 \(y + 20) 390 \(y - 4)", 0xD9EAB0, width: 1, 0.6)
        }
        // A split temple gate
        p.fill("M150 300 L160 230 L172 230 L172 300 Z M200 300 L200 230 L212 230 L222 300 Z", 0x5A3A2E)
        p.fill("M156 234 L166 214 L172 234 Z M200 234 L206 214 L216 234 Z", 0x5A3A2E)
        var r = Seeded("palm")
        for i in 0..<3 {
            let x = 40 + CGFloat(i) * 140 + r.next() * 20
            p.stroke("M\(x) 300 Q\(x + 6) 250 \(x + 2) 210", 0x3A4A2A, width: 3)
            p.fill("M\(x + 2) 210 Q\(x - 24) 202 \(x - 34) 222 Q\(x - 14) 208 \(x + 2) 212 Q\(x + 24) 200 \(x + 38) 218 Q\(x + 18) 206 \(x + 2) 210 Z", 0x3A5A2A)
        }
        p.grain()
    }

    static let maldives = WorldScene(id: "maldives", place: "Overwater villas, Maldives", names: ["maldives", "male", "bora bora", "fiji", "seychelles", "mauritius"], base: 0x6FC4D0) { p in
        p.sky([(0, 0x4A8AC8), (0.55, 0x9CCFE0), (1, 0xF6E2B8)])
        p.glow(300, 230, 120, 0xFFF4D8, 0.8)
        p.water(260, top: 0x7FD4D8, bottom: 0x1E7A9A, seed: "lagoon", glints: 70)
        p.rect(0, 260, Painter.W, 2, 0xF6F2E0, 0.7)
        for i in 0..<5 {
            let x = 40 + CGFloat(i) * 70, y = 300 + CGFloat(i % 2) * 20
            p.fill("M\(x - 4) \(y) L\(x + 22) \(y - 22) L\(x + 48) \(y) Z", 0xB08A5A)
            p.rect(x, y, 44, 16, 0xE8D6B0)
            p.rect(x + 18, y + 4, 8, 10, 0x5A3A2A)
            for px in stride(from: x + 2, through: x + 42, by: 10) { p.rect(px, y + 16, 2, 22, 0x6A4A3A) }
        }
        p.rect(0, 340, Painter.W, 3, 0x8A6A4A)
        p.fill("M300 220 Q340 214 370 222 L390 226 L390 236 L290 236 Z", 0xF2E6C0)
        p.stroke("M340 222 Q344 196 338 176", 0x4A3A2A, width: 2)
        p.fill("M338 176 Q320 168 312 182 Q326 174 338 178 Q352 168 364 180 Q350 172 338 176 Z", 0x3A6A3A)
        p.grain()
    }

    // MARK: - Americas

    static let newYork = WorldScene.scripted(id: "newyork", place: "Brooklyn Bridge, New York", names: ["new york", "nyc", "brooklyn", "manhattan", "queens", "chicago", "boston", "atlanta", "philadelphia"], base: 0x23284E, script: SceneScripts.newyork)

    static let sanFrancisco = WorldScene(id: "sanfrancisco", place: "Golden Gate, San Francisco", names: ["san francisco", "sf", "california", "los angeles", "seattle", "portland"], base: 0xE39A7A) { p in
        p.sky([(0, 0x4E6A9E), (0.55, 0xD6A6A0), (0.85, 0xF2B88E), (1, 0xF6D0A0)])
        p.glow(80, 260, 120, 0xFFDCB0, 0.7)
        p.ridge(290, 50, steps: 5, 0x6A6A86, seed: "marin", rough: 0.6)
        p.haze(230, 90, 0xF2E2D6, 0.75)
        p.water(300, top: 0x5A7A9A, bottom: 0x1E3A56, seed: "bay", glints: 60)
        let towerX: [CGFloat] = [110, 290]
        for x in towerX {
            p.rect(x - 6, 140, 4, 200, 0xC2452E)
            p.rect(x + 2, 140, 4, 200, 0xC2452E)
            for y: CGFloat in [160, 210, 260] { p.rect(x - 6, y, 12, 4, 0xC2452E) }
        }
        p.stroke("M-10 300 L110 142 Q200 260 290 142 L400 300", 0xC2452E, width: 2)
        p.rect(0, 296, Painter.W, 6, 0xA8382A)
        for i in 0..<30 {
            let x = 113 + CGFloat(i) * 6
            let t = (x - 200) / 90
            let top = 142 + 59 * (1 - t * t)  // where the main cable hangs at this point
            p.stroke("M\(x) 296 L\(x) \(top)", 0xC2452E, width: 0.5, 0.7)
        }
        p.birds(5, 200, 90, spread: 90, 0x3A3A4A, seed: "sfb")
        p.grain()
    }

    static let rio = WorldScene(id: "rio", place: "Sugarloaf, Rio de Janeiro", names: ["rio", "brazil", "sao paulo", "buenos aires"], base: 0x86C3DA) { p in
        p.sky([(0, 0x3A8EC2), (0.5, 0x86C3DA), (0.85, 0xF4D3A2), (1, 0xF6B98A)])
        p.glow(330, 160, 130, 0xFFF1CE, 0.7)
        p.fill("M20 250 Q50 120 90 140 Q120 170 140 250 Z", 0x31584B, 0.9)
        p.rect(58, 120, 2, 16, 0xE9E2D6)
        p.rect(52, 124, 14, 2, 0xE9E2D6)
        p.haze(220, 90, 0xBFE0E6, 0.5)
        let loaf: (Painter) -> Void = { q in
            q.fill("M210 352 Q215 250 250 210 Q290 190 305 250 Q318 300 330 352 Z", 0x2A4D45)
            q.fill("M60 352 Q80 300 110 290 Q140 300 150 352 Z", 0x2F574C)
        }
        loaf(p)
        p.stroke("M120 292 Q190 230 255 212", 0x1D2B33, width: 0.8)
        p.rect(180, 248, 6, 5, 0xE0533A)
        p.water(352, top: 0x3C8AA6, bottom: 0x1C4A63, seed: "riow", glints: 60)
        p.reflect(352, opacity: 0.25, loaf)
        p.skyline(base: 352, minH: 10, maxH: 40, minW: 8, maxW: 22, 0x1D3A4A, lights: 0xFFE6A8, seed: "rio", density: 0.3)
        p.birds(5, 260, 120, spread: 70, 0x1D2B33, seed: "rb")
        p.grain()
    }

    static let machuPicchu = WorldScene(id: "machupicchu", place: "Machu Picchu, Peru", names: ["machu picchu", "cusco", "cuzco", "peru", "lima"], base: 0x7A9A86) { p in
        p.sky([(0, 0x6A86A8), (0.55, 0xC6D2CC), (1, 0xEFE4CC)])
        p.ridge(250, 120, steps: 5, 0x8A9AA6, seed: "andes", rough: 0.8)
        p.haze(200, 100, 0xEFEFE8, 0.7)
        p.fill("M240 300 Q260 150 300 120 Q330 140 340 300 Z", 0x3E5A48)
        p.fill("M290 130 Q300 118 312 128 Q308 140 296 140 Z", 0x4E6A56)
        p.fill("M0 460 L0 320 Q120 290 240 310 Q320 320 390 300 L390 460 Z", 0x5E7A5A)
        var r = Seeded("ruins")
        for row in 0..<5 {
            let y = 330 + CGFloat(row) * 22
            p.rect(30, y, 300 - CGFloat(row) * 20, 4, 0x8A8A7A)
            var x: CGFloat = 40
            while x < 300 - CGFloat(row) * 20 {
                if r.next() < 0.5 {
                    p.rect(x, y - 14, 16, 14, 0xA8A492)
                    p.fill("M\(x - 1) \(y - 14) L\(x + 8) \(y - 22) L\(x + 17) \(y - 14) Z", 0x7A7666)
                }
                x += 22
            }
        }
        for row in 0..<6 {
            let y = 336 + CGFloat(row) * 18
            p.stroke("M\(318 + CGFloat(row) * 4) \(y) Q360 \(y - 4) 390 \(y - 2)", 0x8A9A6A, width: 1.4)
        }
        p.birds(3, 120, 120, spread: 120, 0x3A4A4A, seed: "condor")
        p.grain()
    }

    // MARK: - Africa and Oceania

    static let capeTown = WorldScene(id: "capetown", place: "Table Mountain, Cape Town", names: ["cape town", "south africa", "johannesburg"], base: 0x8AB0C8) { p in
        p.sky([(0, 0x4A7AB0), (0.55, 0xA6C8DA), (1, 0xF2DCB8)])
        p.glow(320, 140, 110, 0xFFF0D0, 0.7)
        let table: (Painter) -> Void = { q in
            q.fill("M40 300 L80 200 L300 196 L340 300 Z", 0x4E5A6A)
            q.fill("M300 196 L340 230 L380 300 L340 300 Z", 0x5E6A7A)
            q.fill("M20 300 L50 250 L80 300 Z", 0x5A6676)
            q.fill("M80 200 Q190 186 300 196 L296 206 Q190 196 84 210 Z", 0xF4F6F8, 0.85)
        }
        table(p)
        p.haze(260, 50, 0xE8F0F2, 0.6)
        p.skyline(base: 330, minH: 10, maxH: 40, minW: 10, maxW: 22, 0x3A4656, lights: 0xFFE6A8, seed: "ct", density: 0.25)
        p.water(330, top: 0x5A8AAA, bottom: 0x1E4466, seed: "ctw", glints: 60)
        p.reflect(330, opacity: 0.2, table)
        p.fill("M220 380 Q260 388 300 378 L296 386 L224 386 Z", 0xF2F2F2)
        p.rect(258, 352, 1.2, 28, 0x2A2A2A)
        p.fill("M259 352 L276 376 L259 376 Z", 0xF2F2F2)
        p.birds(5, 60, 110, spread: 100, 0x2A3A4A, seed: "ctb")
        p.grain()
    }

    static let sydney = WorldScene(id: "sydney", place: "Opera House, Sydney", names: ["sydney", "australia", "melbourne", "auckland", "new zealand"], base: 0xD89A8A) { p in
        p.sky([(0, 0x3A4A86), (0.55, 0xC88AA0), (0.85, 0xF2B08A), (1, 0xF7CF9A)])
        p.glow(90, 250, 120, 0xFFD8A8, 0.7)
        // Harbour Bridge behind
        p.stroke("M200 290 Q300 200 400 290", 0x2A2A44, width: 4)
        for i in 0..<14 {
            let x = 210 + CGFloat(i) * 13
            let top = 290 - 90 * (1 - pow((x - 300) / 100, 2))
            p.stroke("M\(x) 290 L\(x) \(top)", 0x2A2A44, width: 0.6)
        }
        p.rect(200, 288, 200, 5, 0x2A2A44)
        let opera: (Painter) -> Void = { q in
            q.rect(40, 300, 200, 16, 0xE8D8C8)
            let sails: [(CGFloat, CGFloat, CGFloat)] = [(60, 70, 60), (100, 90, 80), (140, 80, 70), (180, 60, 50)]
            for (x, w, h) in sails {
                q.fill("M\(x) 300 Q\(x + w * 0.2) \(300 - h) \(x + w) \(300 - h * 0.9) Q\(x + w * 0.6) \(300 - h * 0.3) \(x + w * 0.7) 300 Z", 0xF6F0E6)
                q.stroke("M\(x + w * 0.15) 300 Q\(x + w * 0.3) \(300 - h * 0.7) \(x + w * 0.85) \(300 - h * 0.85)", 0xD8C8B6, width: 0.8)
            }
        }
        opera(p)
        p.water(316, top: 0x5A6A9A, bottom: 0x1E2A4A, seed: "harbour", shimmer: 0xFFD8A8, glints: 80)
        p.reflect(316, opacity: 0.3, opera)
        p.fill("M260 380 Q300 390 350 378 L344 388 L266 388 Z", 0x1A2A3A)
        p.rect(290, 368, 40, 12, 0xE8E0D0)
        p.grain()
    }

    // MARK: - Shared pieces

    private static func pagoda(_ p: Painter, x: CGFloat, base: CGFloat, scale s: CGFloat, _ hex: UInt32) {
        for i in 0..<5 {
            let w = (44 - CGFloat(i) * 6) * s, y = base - CGFloat(i) * 26 * s
            p.fill("M\(x - w) \(y - 14 * s) Q\(x) \(y - 20 * s) \(x + w) \(y - 14 * s) L\(x + w * 0.7) \(y - 10 * s) L\(x - w * 0.7) \(y - 10 * s) Z", hex)
            p.rect(x - w * 0.55, y - 10 * s, w * 1.1, 12 * s, hex)
        }
        p.rect(x - 1.2 * s, base - 160 * s, 2.4 * s, 40 * s, hex)
    }

    private static func dome(_ p: Painter, x: CGFloat, y: CGFloat, s: CGFloat) {
        p.rect(x - 10 * s, y, 20 * s, 16 * s, 0xFBF5EC)
        p.fill("M\(x - 10 * s) \(y) Q\(x) \(y - 14 * s) \(x + 10 * s) \(y) Z", 0x2F5DA8)
        p.rect(x - 0.7, y - 16 * s, 1.4, 6 * s, 0xFBF5EC)
    }

    private static func blossoms(_ p: Painter, x: CGFloat, y: CGFloat, w: CGFloat, h: CGFloat, count: Int, seed: String) {
        var r = Seeded(seed)
        let pinks: [UInt32] = [0xF2B8C6, 0xE99AB0, 0xF7D2DC]
        for i in 0..<count {
            p.disc(x + r.next() * w, y + r.next() * h, 2 + r.next() * 5, pinks[i % 3], 0.85)
        }
    }
}
