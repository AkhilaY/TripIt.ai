import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// "Share → Travel Edit" from TikTok, Instagram, YouTube, Maps or Safari: sends the link to your account and shows
/// the import as a checklist while it runs. You can close it any time; the import carries on in the background.
/// On the free plan, once the month's video saves are used, it offers Plus instead.
final class ShareViewController: UIViewController {
    private let model = ShareModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        model.onFinish = { [weak self] in
            self?.extensionContext?.completeRequest(returningItems: nil)
        }
        model.openApp = { [weak self] url in
            self?.open(url)
            self?.extensionContext?.completeRequest(returningItems: nil)
        }
        let host = UIHostingController(rootView: ShareView(model: model))
        addChild(host)
        host.view.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(host.view)
        NSLayoutConstraint.activate([
            host.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            host.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            host.view.topAnchor.constraint(equalTo: view.topAnchor),
            host.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        host.didMove(toParent: self)
        Task { await model.handle(items: extensionContext?.inputItems as? [NSExtensionItem] ?? []) }
    }

    /// Extensions can't call UIApplication.shared, so this finds the app through the responder chain.
    private func open(_ url: URL) {
        var responder: UIResponder? = self
        let selector = NSSelectorFromString("openURL:options:completionHandler:")
        while let current = responder {
            if let app = current as? UIApplication, app.responds(to: selector) {
                app.perform(selector, with: url, with: [UIApplication.OpenExternalURLOptionsKey: Any]())
                return
            }
            responder = current.next
        }
    }
}

/// The parts of an import job the share sheet shows.
struct ShareJob: Decodable {
    struct Reel: Decodable {
        var platform: String?
        var title: String?
        var uploader: String?
    }

    var id: String
    var status: String
    var message: String?
    var reel: Reel?
    var addedPlaces: Int?

    var finished: Bool { status == "done" || status == "failed" }
}

struct SharePlan: Decodable {
    var plan: String
    var videoSavesUsed: Int
    var videoSavesLimit: Int?
}

@MainActor
final class ShareModel: ObservableObject {
    enum Phase: Equatable {
        case working
        case done(places: Int, again: Bool)
        case background  // still going after a while; it finishes on its own
        case upgrade(String)
        case error(String)
    }

    static let steps = ["Link received", "Opening the post", "Listening", "Finding places"]

    @Published var phase: Phase = .working
    @Published var step = 0  // the step in progress; steps before it are ticked
    @Published var job: ShareJob?
    @Published var savesLeft: Int?
    var link: URL?
    var onFinish: () -> Void = {}
    var openApp: (URL) -> Void = { _ in }

    func handle(items: [NSExtensionItem]) async {
        let (url, text) = await Self.loadLink(from: items)
        guard let url else {
            phase = .error("There's no link to save here. Share a TikTok, Instagram or YouTube post, or a map link.")
            return
        }
        link = url
        guard let token = SessionStore.token else {
            phase = .error("Open Travel Edit and sign in first, then share again.")
            return
        }
        do {
            let job = try await Self.send(url: url, text: text, token: token)
            self.job = job
            withAnimation(.spring(duration: 0.45)) { step = 1 }
            if job.status == "done" {
                finish(job, again: true)
                return
            }
            Task { savesLeft = await Self.savesLeft(token: token) }
            await follow(job.id, token: token)
        } catch ShareError.signedOut {
            SessionStore.clear()
            phase = .error("You've been signed out. Open Travel Edit, sign in, then share again.")
        } catch ShareError.upgrade(let message) {
            Self.keepForLater(url)
            withAnimation(.spring(duration: 0.45)) { phase = .upgrade(message) }
        } catch {
            phase = .error("Couldn't reach The Travel Edit. Check your connection and try again.")
        }
    }

    /// Checks on the import until it's done, for up to three minutes.
    private func follow(_ id: String, token: String) async {
        let started = Date()
        while Date().timeIntervalSince(started) < 180 {
            try? await Task.sleep(for: .seconds(1.5))
            guard let fresh: ShareJob = try? await Self.get("v1/jobs/\(id)", token: token) else { continue }
            job = fresh
            let next: Int
            switch fresh.status {
            case "transcribing": next = 2
            case "analyzing": next = 3
            case "done", "failed": next = Self.steps.count
            default: next = 1
            }
            if next != step { withAnimation(.spring(duration: 0.45)) { step = next } }
            if fresh.finished {
                if fresh.status == "failed" {
                    phase = .error(fresh.message ?? "Couldn't read that post. Open Travel Edit to try again.")
                } else {
                    finish(fresh, again: false)
                }
                return
            }
        }
        withAnimation { phase = .background }
    }

    private func finish(_ job: ShareJob, again: Bool) {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        withAnimation(.spring(duration: 0.45)) {
            step = Self.steps.count
            phase = .done(places: job.addedPlaces ?? 0, again: again)
        }
    }

    func review() {
        guard let id = job?.id else { return onFinish() }
        openApp(URL(string: "traveledit://review?job=\(id)")!)
    }

    func upgrade() {
        var parts = URLComponents(string: "traveledit://upgrade")!
        if let link { parts.queryItems = [URLQueryItem(name: "url", value: link.absoluteString)] }
        openApp(parts.url!)
    }

    /// The app saves this link once you're on Plus.
    private static func keepForLater(_ url: URL) {
        UserDefaults(suiteName: AppConfig.appGroupID)?.set(url.absoluteString, forKey: "pendingUpgradeLink")
    }

    enum ShareError: Error { case signedOut, server, upgrade(String) }

    private static func request(_ path: String, token: String) -> URLRequest {
        var request = URLRequest(url: AppConfig.baseURL.appendingPathComponent(path))
        request.timeoutInterval = 20
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return request
    }

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    private static func send(url: URL, text: String?, token: String) async throws -> ShareJob {
        var request = request("v1/jobs", token: token)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var body: [String: String] = ["url": url.absoluteString]
        if let text, !text.isEmpty { body["shared_text"] = String(text.prefix(4000)) }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 401 || status == 403 { throw ShareError.signedOut }
        if status == 402 {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw ShareError.upgrade(detail ?? "You've used this month's free video saves. Upgrade to Plus for unlimited saves.")
        }
        guard (200..<300).contains(status) else { throw ShareError.server }
        return try decoder.decode(ShareJob.self, from: data)
    }

    private static func get<T: Decodable>(_ path: String, token: String) async throws -> T {
        let (data, response) = try await URLSession.shared.data(for: request(path, token: token))
        guard (200..<300).contains((response as? HTTPURLResponse)?.statusCode ?? 0) else { throw ShareError.server }
        return try decoder.decode(T.self, from: data)
    }

    private static func savesLeft(token: String) async -> Int? {
        guard let plan: SharePlan = try? await get("v1/me/plan", token: token), let limit = plan.videoSavesLimit else { return nil }
        return max(0, limit - plan.videoSavesUsed)
    }

    private static func loadLink(from items: [NSExtensionItem]) async -> (URL?, String?) {
        var foundURL: URL?
        var foundText: String?
        for item in items {
            if let text = item.attributedContentText?.string, !text.isEmpty {
                foundText = foundText ?? text
            }
            for provider in item.attachments ?? [] {
                if foundURL == nil, provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
                   let url = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier) as? URL,
                   url.scheme?.hasPrefix("http") == true {
                    foundURL = url
                }
                if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier),
                   let text = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) as? String {
                    foundText = foundText ?? text
                    if foundURL == nil { foundURL = LinkExtractor.firstURL(in: text) }
                }
            }
        }
        if foundURL == nil, let foundText { foundURL = LinkExtractor.firstURL(in: foundText) }
        return (foundURL, foundText)
    }
}

private enum Palette {
    static let espresso = Color(red: 0.17, green: 0.13, blue: 0.10)
    static let gold = Color(red: 0.72, green: 0.56, blue: 0.33)
    static let ok = Color(red: 0.24, green: 0.52, blue: 0.36)
    static let accent = Color(light: espresso, dark: Color(red: 0.93, green: 0.88, blue: 0.80))
}

private extension Color {
    init(light: Color, dark: Color) {
        self.init(UIColor { $0.userInterfaceStyle == .dark ? UIColor(dark) : UIColor(light) })
    }
}

struct ShareView: View {
    @ObservedObject var model: ShareModel

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("The Travel Edit").font(.system(.subheadline, design: .serif).weight(.semibold))
                Spacer()
                Button(closeLabel) { model.onFinish() }.font(.body.weight(.semibold)).tint(Palette.accent)
            }
            .padding(.horizontal, 20).padding(.vertical, 14)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    switch model.phase {
                    case .upgrade(let message): upgrade(message)
                    case .error(let message): failure(message)
                    default: progress
                    }
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .background(Color(.systemBackground))
    }

    private var closeLabel: String {
        switch model.phase {
        case .working: "Hide"
        default: "Done"
        }
    }

    // MARK: Checklist

    private var progress: some View {
        VStack(alignment: .leading, spacing: 22) {
            VStack(alignment: .leading, spacing: 6) {
                Text(heading).font(.system(.title2, design: .serif).weight(.semibold))
                    .contentTransition(.opacity)
                if let source { Text(source).font(.subheadline).foregroundStyle(.secondary).lineLimit(2) }
            }
            VStack(alignment: .leading, spacing: 0) {
                ForEach(ShareModel.steps.indices, id: \.self) { i in
                    ChecklistRow(title: ShareModel.steps[i], state: state(of: i), last: i == ShareModel.steps.count - 1)
                }
            }
            footer
        }
    }

    private func state(of i: Int) -> ChecklistRow.State {
        if case .done = model.phase { return .done }
        if i < model.step { return .done }
        return i == model.step ? .active : .waiting
    }

    private var heading: String {
        switch model.phase {
        case .done(let places, let again):
            if again { return "Already in your library" }
            return places == 0 ? "Saved" : places == 1 ? "Saved 1 new place" : "Saved \(places) new places"
        case .background: return "Still working on it"
        default: return "Saving to Travel Edit"
        }
    }

    private var source: String? {
        let reel = model.job?.reel
        if let uploader = reel?.uploader, !uploader.isEmpty {
            let title = reel?.title.map { "“\($0)” · " } ?? ""
            return title + "@" + uploader
        }
        return model.link?.host?.replacingOccurrences(of: "www.", with: "")
    }

    @ViewBuilder private var footer: some View {
        switch model.phase {
        case .done(_, let again):
            Button { model.review() } label: {
                Text(again ? "Open in Travel Edit" : "Review places").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent).controlSize(.large).tint(Palette.espresso)
            .transition(.move(edge: .bottom).combined(with: .opacity))
            if let left = model.savesLeft, !again {
                Text(left == 1 ? "1 free video save left this month." : "\(left) free video saves left this month.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        case .background:
            Text("This one's taking longer. It keeps going after you close this, and you'll get a notification when the places are saved.")
                .font(.subheadline).foregroundStyle(.secondary)
        default:
            Text("You can close this. Saving carries on, and the places show up in your library.")
                .font(.footnote).foregroundStyle(.secondary)
        }
    }

    // MARK: Out of saves

    private func upgrade(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            Image(systemName: "sparkles")
                .font(.system(size: 34)).foregroundStyle(Palette.gold)
                .symbolEffect(.bounce, value: message)
            Text("You're out of free saves").font(.system(.title2, design: .serif).weight(.semibold))
            Text(message).font(.body).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: 10) {
                perk("infinity", "Unlimited video saves from TikTok, Instagram and YouTube")
                perk("bookmark", "We'll keep this post and save it as soon as you upgrade")
                perk("photo.on.rectangle", "Screenshots and map links stay free")
            }
            Button { model.upgrade() } label: { Text("Upgrade to Plus").frame(maxWidth: .infinity) }
                .buttonStyle(.borderedProminent).controlSize(.large).tint(Palette.espresso)
            Button { model.onFinish() } label: { Text("Not now").frame(maxWidth: .infinity) }
                .buttonStyle(.bordered).controlSize(.large).tint(Palette.accent)
        }
        .transition(.opacity)
    }

    private func perk(_ symbol: String, _ text: String) -> some View {
        Label { Text(text).font(.subheadline) } icon: { Image(systemName: symbol).foregroundStyle(Palette.gold) }
    }

    private func failure(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Image(systemName: "exclamationmark.circle.fill").font(.system(size: 34)).foregroundStyle(.orange)
            Text("Couldn't save this").font(.system(.title2, design: .serif).weight(.semibold))
            Text(message).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// One line of the checklist: an empty circle, then a pulsing dot while it runs, then a tick.
struct ChecklistRow: View {
    enum State { case waiting, active, done }

    let title: String
    let state: State
    let last: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            VStack(spacing: 0) {
                ZStack {
                    switch state {
                    case .done:
                        Image(systemName: "checkmark.circle.fill")
                            .font(.system(size: 24)).foregroundStyle(Palette.ok)
                            .transition(.scale(scale: 0.4).combined(with: .opacity))
                    case .active:
                        Circle().stroke(Palette.gold, lineWidth: 2).frame(width: 22, height: 22)
                            .overlay { Circle().fill(Palette.gold).frame(width: 10, height: 10).phaseAnimator([0.35, 1]) { v, p in v.opacity(p).scaleEffect(p) } }
                    case .waiting:
                        Circle().stroke(Color(.tertiaryLabel), lineWidth: 1.5).frame(width: 22, height: 22)
                    }
                }
                .frame(width: 26, height: 26)
                if !last {
                    Rectangle().fill(state == .done ? Palette.ok.opacity(0.5) : Color(.separator))
                        .frame(width: 2, height: 22)
                }
            }
            Text(title)
                .font(.body.weight(state == .active ? .semibold : .regular))
                .foregroundStyle(state == .waiting ? Color(.tertiaryLabel) : Color(.label))
                .padding(.top, 3)
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title), \(state == .done ? "done" : state == .active ? "in progress" : "waiting")")
    }
}
