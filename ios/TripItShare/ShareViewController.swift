import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Receives a TikTok / Instagram link from the share sheet, starts processing on the backend and
/// queues it for the app. The extension stays short-lived; the app saves the places when opened.
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
        case saved(String)
        case error(String)
    }

    @Published var phase: Phase = .working
    var onFinish: () -> Void = {}

    func handle(items: [NSExtensionItem]) async {
        let (url, text) = await Self.loadLink(from: items)
        guard let url else {
            phase = .error("Couldn't find a link to save. Share a TikTok or Instagram post.")
            return
        }

        var pending = PendingImport(url: url.absoluteString, sharedText: text)
        // Kick off the backend job now so the places are often ready by the time the app opens.
        // If this fails (offline, slow server) the app submits it later.
        do {
            let job = try await APIClient(timeout: 10).createJob(url: pending.url, sharedText: text)
            pending.jobID = job.id
            pending.state = .processing
        } catch {
            pending.message = error.localizedDescription
        }
        PendingImportStore.add(pending)

        phase = .saved(pending.state == .processing
                       ? "Finding places… open TripIt to see them on your map."
                       : "Saved. TripIt will process it when you open the app.")
        try? await Task.sleep(for: .seconds(1.6))
        onFinish()
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
        VStack(spacing: 16) {
            switch model.phase {
            case .working:
                ProgressView()
                Text("Saving to TripIt…").font(.headline)
            case .saved(let message):
                Image(systemName: "mappin.circle.fill")
                    .font(.system(size: 48))
                    .foregroundStyle(.tint)
                Text("Saved to TripIt").font(.headline)
                Text(message).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
            case .error(let message):
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 44))
                    .foregroundStyle(.orange)
                Text(message).multilineTextAlignment(.center)
                Button("Close") { model.onFinish() }.buttonStyle(.borderedProminent)
            }
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemBackground))
    }
}
