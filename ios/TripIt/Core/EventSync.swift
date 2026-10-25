import EventKit
import UserNotifications

/// Saved events (pop-ups, shows, classes) go into Apple Calendar and get reminders: an hour before (9 AM on the day
/// when there's no time) and at 6 PM the evening before. Calendar access is write-only, so the app can add events but
/// never read your calendar; what it added is remembered here so nothing is added twice.
@MainActor
final class EventSync {
    static let shared = EventSync()
    private let eventStore = EKEventStore()
    private let addedKey = "events.addedToCalendar"  // place id → "date|time" it was added with

    private var added: [String: String] {
        get { UserDefaults.standard.dictionary(forKey: addedKey) as? [String: String] ?? [:] }
        set { UserDefaults.standard.set(newValue, forKey: addedKey) }
    }

    var canWrite: Bool {
        let status = EKEventStore.authorizationStatus(for: .event)
        return status == .writeOnly || status == .fullAccess
    }

    /// Right after you save events from a post: asks for calendar and notification permission the first time, then
    /// adds them. Returns how many went into the calendar.
    @discardableResult
    func add(_ places: [Place]) async -> Int {
        if await Push.shared.status() == .notDetermined { _ = await Push.shared.enable() }
        if EKEventStore.authorizationStatus(for: .event) == .notDetermined {
            _ = try? await eventStore.requestWriteOnlyAccessToEvents()
        }
        return await sync(places)
    }

    /// Adds any upcoming saved event not in the calendar yet (or whose date changed) and refreshes the reminders.
    /// Never asks for permission; `add` does that.
    @discardableResult
    func sync(_ places: [Place]) async -> Int {
        let today = Fmt.iso(Date())
        let upcoming = places.filter {
            Category($0.category) == .event && $0.saved && $0.eventDate != nil && ($0.eventEndDate ?? $0.eventDate ?? "") >= today
        }
        var count = 0
        if canWrite {
            var done = added
            for p in upcoming {
                guard let date = p.eventDate, let day = Fmt.day(date) else { continue }
                let stamp = "\(date)|\(p.startTime ?? "")"
                guard done[p.id] != stamp else { continue }
                let event = EKEvent(eventStore: eventStore)
                event.title = p.name
                event.location = [p.venue, p.address].compactMap { $0 }.joined(separator: ", ")
                event.notes = [p.summary.isEmpty ? nil : p.summary, "Saved in The Travel Edit"].compactMap { $0 }.joined(separator: "\n\n")
                event.calendar = eventStore.defaultCalendarForNewEvents
                if let start = Self.start(of: p) {
                    event.startDate = start
                    event.endDate = start.addingTimeInterval(2 * 3600)
                } else {
                    event.isAllDay = true
                    event.startDate = day
                    event.endDate = p.eventEndDate.flatMap(Fmt.day) ?? day
                }
                do {
                    try eventStore.save(event, span: .thisEvent)
                    done[p.id] = stamp
                    count += 1
                } catch {
                    Monitoring.report("Couldn't add an event to the calendar: \(error)")
                }
            }
            added = done
        }
        await scheduleReminders(upcoming)
        return count
    }

    /// When it starts, for an event with a date and a time.
    static func start(of p: Place) -> Date? {
        guard let date = p.eventDate, let time = p.startTime, let day = Fmt.day(date) else { return nil }
        let parts = time.split(separator: ":").compactMap { Int($0) }
        guard parts.count == 2 else { return nil }
        return Calendar.current.date(bySettingHour: parts[0], minute: parts[1], second: 0, of: day)
    }

    private func scheduleReminders(_ events: [Place]) async {
        let center = UNUserNotificationCenter.current()
        let status = await center.notificationSettings().authorizationStatus
        guard status == .authorized || status == .provisional else { return }
        let old = await center.pendingNotificationRequests().map(\.identifier).filter { $0.hasPrefix("event-") }
        center.removePendingNotificationRequests(withIdentifiers: old)
        let calendar = Calendar.current
        for p in events {
            guard let date = p.eventDate, let day = Fmt.day(date) else { continue }
            let start = Self.start(of: p)
            let venue = p.venue.map { " at \($0)" } ?? ""
            let soon = start.map { $0.addingTimeInterval(-3600) } ?? calendar.date(bySettingHour: 9, minute: 0, second: 0, of: day)
            await remind(center, "event-\(p.id)-soon", at: soon, title: p.name,
                         body: start.map { "Starts at \($0.formatted(date: .omitted, time: .shortened))\(venue)" } ?? "Today\(venue)", placeId: p.id)
            let evening = calendar.date(byAdding: .day, value: -1, to: day).flatMap { calendar.date(bySettingHour: 18, minute: 0, second: 0, of: $0) }
            await remind(center, "event-\(p.id)-eve", at: evening, title: "Tomorrow: \(p.name)",
                         body: (start.map { "At \($0.formatted(date: .omitted, time: .shortened))" } ?? "All day") + venue, placeId: p.id)
        }
    }

    private func remind(_ center: UNUserNotificationCenter, _ id: String, at date: Date?, title: String, body: String, placeId: String) async {
        guard let date, date > Date() else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.userInfo = ["url": "#/place/\(placeId)"]
        let parts = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: date)
        try? await center.add(UNNotificationRequest(identifier: id, content: content,
                                                    trigger: UNCalendarNotificationTrigger(dateMatching: parts, repeats: false)))
    }
}
