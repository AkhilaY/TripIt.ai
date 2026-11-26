import SwiftUI

/// The Edits tab, as a magazine: each morning a new issue, with a cover photo, the masthead and today's edits as its
/// cover lines. Each line opens that edit. Earlier issues are kept on the phone as back issues. Free for everyone.
struct EditsTabView: View {
    @Environment(Store.self) private var store
    @Environment(Router.self) private var router
    @Environment(Session.self) private var session
    @State private var location = Location.shared
    @State private var tripEdits: [HomeEdit] = []
    @State private var issues: [EditIssue] = DiskCache.load("edit-issues") ?? []
    @State private var touched: String?

    var body: some View {
        GeometryReader { outer in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    cover(height: max(560, outer.size.height * 0.86), top: outer.safeAreaInsets.top)
                    backIssues.padding(.horizontal, 20)
                }
                .padding(.bottom, 40)
            }
            .ignoresSafeArea(edges: .top)
        }
        .background(Theme.background.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .sensoryFeedback(.selection, trigger: touched)
        .task(id: store.upcomingTrips.first?.id) {
            if let trip = store.upcomingTrips.first { await loadTripEdits(trip) }
        }
        .onChange(of: today.map(\.id)) { _, _ in keepIssue() }
        .onAppear { keepIssue() }
    }

    // MARK: Today's issue

    private var today: [HomeEdit] {
        tripEdits + HomeEdits.make(saved: store.saved, home: store.home?.city, open: [], trips: store.realTrips)
    }

    private static let start = Fmt.day("2026-10-01") ?? Date()

    /// One issue a day since the magazine began.
    private var number: Int { max(1, (Calendar.current.dateComponents([.day], from: Self.start, to: Date()).day ?? 0) + 1) }

    /// Today's cover: a featured place, a different one each day.
    private var coverScene: WorldScene {
        let all = WorldScenes.all
        return all[number % all.count]
    }

    private func cover(height: CGFloat, top: CGFloat) -> some View {
        let scene = coverScene
        let name = session.me?.name.split(separator: " ").first.map { String($0).uppercased() }
        let edits = Array(today.prefix(4))
        return ZStack(alignment: .top) {
            WorldSceneImage(scene: scene)
            LinearGradient(stops: [.init(color: .black.opacity(0.55), location: 0), .init(color: .clear, location: 0.3),
                                   .init(color: .clear, location: 0.45), .init(color: .black.opacity(0.82), location: 1)],
                           startPoint: .top, endPoint: .bottom)
            VStack(spacing: 4) {
                Text("THE").font(Theme.text(.caption2)).kerning(6)
                Text("TRAVEL EDIT").font(Theme.serif(34)).kerning(5)
                Text(["NO. \(number)", Date().formatted(.dateTime.weekday(.wide).day().month(.wide)).uppercased(), name.map { "FOR \($0)" }]
                    .compactMap { $0 }.joined(separator: " · "))
                    .font(Theme.text(.caption2)).kerning(1.6).opacity(0.85).multilineTextAlignment(.center)
            }
            .foregroundStyle(.white)
            .padding(.top, top + 14).padding(.horizontal, 20)
            VStack(alignment: .leading, spacing: 0) {
                Spacer()
                Text("IN THIS ISSUE").font(Theme.text(.caption2, weight: .medium)).kerning(2).foregroundStyle(.white.opacity(0.8))
                if edits.isEmpty {
                    Text("Save a few places and tomorrow's issue is made from them.")
                        .font(Theme.text(.subheadline)).foregroundStyle(.white.opacity(0.85)).padding(.top, 10)
                }
                ForEach(Array(edits.enumerated()), id: \.element.id) { i, edit in
                    Button { touched = edit.id; router.push(edit.route) } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 14) {
                            Text(String(format: "%02d", i + 1)).font(Theme.text(.footnote)).opacity(0.7)
                            Text(edit.title).font(Theme.serif(22)).multilineTextAlignment(.leading).lineLimit(2)
                            Spacer(minLength: 8)
                            Text(edit.caption).font(Theme.text(.caption)).opacity(0.7).lineLimit(1)
                        }
                        .foregroundStyle(.white)
                        .padding(.vertical, 12)
                        .contentShape(Rectangle())
                        .overlay(alignment: .bottom) { Rectangle().fill(.white.opacity(0.2)).frame(height: 1) }
                    }
                    .buttonStyle(PressStyle())
                }
                if let photo = scene.photo {
                    Text("Cover: \(scene.place) · \(photo.credit)").font(Theme.text(.caption2)).foregroundStyle(.white.opacity(0.6))
                        .padding(.top, 12)
                }
            }
            .padding(.horizontal, 24).padding(.bottom, 28)
        }
        .frame(height: height)
        .frame(maxWidth: .infinity)
        .clipShape(UnevenRoundedRectangle(bottomLeadingRadius: 28, bottomTrailingRadius: 28, style: .continuous))
    }

    // MARK: Back issues

    @ViewBuilder private var backIssues: some View {
        let past = issues.filter { $0.number != number }.sorted { $0.number > $1.number }
        Text("BACK ISSUES").font(Theme.text(.caption2, weight: .medium)).kerning(2).foregroundStyle(Theme.secondary)
            .padding(.top, 28)
        if past.isEmpty {
            Text("Each day's issue is kept here, so an edit you liked is still here after it refreshes.")
                .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary).padding(.top, 8)
                .fixedSize(horizontal: false, vertical: true)
        }
        ForEach(past) { issue in
            NavigationLink(value: Route.backIssue(issue)) {
                HStack(alignment: .firstTextBaseline, spacing: 14) {
                    Text("No. \(issue.number)").font(Theme.serif(18)).foregroundStyle(Theme.label)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(issue.lines.map(\.title).prefix(2).joined(separator: " · ")).font(Theme.text(.subheadline))
                            .foregroundStyle(Theme.label).lineLimit(1)
                        Text(Fmt.day(issue.date)?.formatted(.dateTime.weekday(.wide).day().month(.wide)) ?? issue.date)
                            .font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right").font(Theme.text(.caption)).foregroundStyle(Theme.tertiary)
                }
                .padding(.vertical, 12)
                .contentShape(Rectangle())
            }
            .buttonStyle(PressStyle())
            Divider().overlay(Theme.divider)
        }
    }

    /// Keeps today's issue (once there's something in it), so it can be read again as a back issue; 30 at most.
    private func keepIssue() {
        let lines = today.prefix(6).map(EditIssue.Line.init)
        guard !lines.isEmpty else { return }
        var kept = issues.filter { $0.number != number }
        kept.append(EditIssue(number: number, date: Fmt.iso(Date()), lines: Array(lines)))
        issues = Array(kept.sorted { $0.number > $1.number }.prefix(30))
        DiskCache.save("edit-issues", issues)
    }

    private func loadTripEdits(_ trip: Trip) async {
        let key = "home-edits-\(trip.id)"
        if tripEdits.isEmpty, let cached: TripEdits = DiskCache.load(key) { tripEdits = HomeEdits.fromTrip(trip, cached) }
        guard let fresh: TripEdits = try? await API.shared.get("/v1/trips/\(trip.id)/edits") else { return }
        DiskCache.save(key, fresh)
        tripEdits = HomeEdits.fromTrip(trip, fresh)
    }
}

/// A day's issue, kept on the phone.
struct EditIssue: Codable, Hashable, Identifiable {
    let number: Int
    let date: String
    let lines: [Line]
    var id: Int { number }

    struct Line: Codable, Hashable {
        let id: String
        let caption: String
        let title: String
        let note: String
        let placeIds: [String]
        let tripId: String?
        let tripEditId: String?

        init(_ edit: HomeEdit) {
            id = edit.id; caption = edit.caption; title = edit.title; note = edit.note; placeIds = edit.placeIds
            tripId = edit.tripId; tripEditId = edit.tripEditId
        }

        var edit: HomeEdit {
            HomeEdit(id: id, caption: caption, title: title, note: note, placeIds: placeIds, cover: nil, tripId: tripId, tripEditId: tripEditId)
        }
    }
}

/// An earlier issue: its date and its edits, each opening as it did that day.
struct BackIssueView: View {
    let issue: EditIssue
    @Environment(Router.self) private var router

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text("NO. \(issue.number)").font(Theme.text(.caption2, weight: .medium)).kerning(2).foregroundStyle(Theme.secondary)
                Text(Fmt.day(issue.date)?.formatted(.dateTime.weekday(.wide).day().month(.wide)) ?? issue.date)
                    .font(Theme.serif(30)).foregroundStyle(Theme.label).padding(.top, 6)
                Divider().overlay(Theme.divider).padding(.top, 16)
                ForEach(Array(issue.lines.enumerated()), id: \.offset) { i, line in
                    Button { router.push(line.edit.route) } label: {
                        HStack(alignment: .top, spacing: 14) {
                            Text(String(format: "%02d", i + 1)).font(Theme.serif(22)).foregroundStyle(Theme.tertiary).frame(width: 32, alignment: .leading)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(line.title).font(Theme.serif(20)).foregroundStyle(Theme.label).multilineTextAlignment(.leading)
                                Text(line.caption).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                                if !line.note.isEmpty {
                                    Text(line.note).font(Theme.text(.subheadline)).foregroundStyle(Theme.label.opacity(0.8)).lineLimit(2)
                                }
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 14)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(PressStyle())
                    Divider().overlay(Theme.divider)
                }
            }
            .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 40)
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
    }
}
