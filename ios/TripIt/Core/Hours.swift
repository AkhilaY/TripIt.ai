import Foundation

/// Whether a place is open now, by this phone's clock (as the web app does).
enum Hours {
    struct Status {
        let label: String
        let isOpen: Bool
    }

    /// Monday = 0, as the server stores the week.
    static func mondayIndex(_ date: Date = Date()) -> Int {
        (Calendar.current.component(.weekday, from: date) + 5) % 7
    }

    private static func minutes(_ hhmm: String) -> Int? {
        let p = hhmm.split(separator: ":").compactMap { Int($0) }
        return p.count == 2 ? p[0] * 60 + p[1] : nil
    }

    static func status(_ hours: OpeningHours?, now: Date = Date()) -> Status? {
        guard let weekly = hours?.weekly, weekly.count == 7 else { return nil }
        let day = mondayIndex(now)
        let c = Calendar.current.dateComponents([.hour, .minute], from: now)
        let t = (c.hour ?? 0) * 60 + (c.minute ?? 0)
        // Still open from last night?
        for r in weekly[(day + 6) % 7] {
            if let o = minutes(r.open), let cl = minutes(r.close), cl < o, t < cl {
                return Status(label: "Open until \(Fmt.clock(r.close))", isOpen: true)
            }
        }
        for r in weekly[day] {
            guard let o = minutes(r.open), let cl = minutes(r.close) else { continue }
            let close = cl <= o ? cl + 24 * 60 : cl
            if t >= o && t < close {
                return Status(label: r.close == "24:00" || (o == 0 && close >= 24 * 60) ? "Open 24 hours" : "Open until \(Fmt.clock(r.close))", isOpen: true)
            }
            if t < o { return Status(label: "Closed · opens \(Fmt.clock(r.open))", isOpen: false) }
        }
        for offset in 1...7 {
            let next = weekly[(day + offset) % 7]
            if let first = next.first {
                let when = offset == 1 ? "tomorrow" : Calendar.current.weekdaySymbols[(Calendar.current.component(.weekday, from: now) - 1 + offset) % 7]
                return Status(label: "Closed · opens \(when) \(Fmt.clock(first.open))", isOpen: false)
            }
        }
        return Status(label: "Closed", isOpen: false)
    }
}
