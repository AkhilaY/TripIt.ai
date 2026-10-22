import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// "Share → TripIt" from TikTok, Instagram, YouTube, Maps or Safari: sends the link to your TripIt account,
/// which finds the places in the background (you get them in Saved a minute later).
final class ShareViewController: UIViewController {
    private let model = ShareModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        model.onFinish = { [weak self] in
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
}

@MainActor
final class ShareModel: ObservableObject {
    enum Phase: Equatable {
        case working
        case saved
        case error(String)
    }

    @Published var phase: Phase = .working
    var onFinish: () -> Void = {}

    func handle(items: [NSExtensionItem]) async {
        let (url, text) = await Self.loadLink(from: items)
        guard let url else {
            phase = .error("There's no link to save here. Share a TikTok, Instagram or YouTube post, or a map link.")
            return
        }
        guard let token = SessionStore.token else {
            phase = .error("Open TripIt and sign in first, then share again.")
            return
        }
        do {
            try await Self.send(url: url, text: text, token: token)
            phase = .saved
            try? await Task.sleep(for: .seconds(1.4))
            onFinish()
        } catch ShareError.signedOut {
            SessionStore.clear()
            phase = .error("You've been signed out. Open TripIt, sign in, then share again.")
        } catch {
            phase = .error("Couldn't reach TripIt. Check your connection and try again.")
        }
    }

    enum ShareError: Error { case signedOut, server }

    private static func send(url: URL, text: String?, token: String) async throws {
        var request = URLRequest(url: AppConfig.baseURL.appendingPathComponent("v1/jobs"))
        request.httpMethod = "POST"
        request.timeoutInterval = 20
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        var body: [String: String] = ["url": url.absoluteString]
        if let text, !text.isEmpty { body["shared_text"] = String(text.prefix(4000)) }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (_, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 401 || status == 403 { throw ShareError.signedOut }
        if !(200..<300).contains(status) { throw ShareError.server }
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

struct ShareView: View {
    @ObservedObject var model: ShareModel

    var body: some View {
        VStack(spacing: 14) {
            switch model.phase {
            case .working:
                ProgressView()
                Text("Saving to TripIt…").font(.headline)
            case .saved:
                Image(systemName: "bookmark.circle.fill")
                    .font(.system(size: 52))
                    .foregroundStyle(Color(red: 0.17, green: 0.13, blue: 0.10))
                Text("Saved to TripIt").font(.title3.weight(.semibold))
                Text("Finding the places now. They'll be in Saved in about a minute.")
                    .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
            case .error(let message):
                Image(systemName: "exclamationmark.circle.fill")
                    .font(.system(size: 46))
                    .foregroundStyle(.orange)
                Text(message).multilineTextAlignment(.center)
                Button("Close") { model.onFinish() }.buttonStyle(.borderedProminent).tint(Color(red: 0.17, green: 0.13, blue: 0.10))
            }
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemBackground))
    }
}
