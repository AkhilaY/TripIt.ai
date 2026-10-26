import SwiftUI

/// Why the upgrade screen is open: a post that couldn't be saved (from the share sheet or the app), or just a look.
struct PaywallRequest: Identifiable, Hashable {
    var id = UUID()
    var link: String?
    var message: String?
}

/// Thrown by Store.importLink when the free plan's video saves for the month are used up.
struct UpgradeNeeded: Error {
    let link: String
    let message: String
}

/// A post shared while out of free saves, kept (in the App Group, so the share sheet can leave it too)
/// and saved once you're on Plus.
enum PendingLink {
    private static let key = "pendingUpgradeLink"
    private static var defaults: UserDefaults { UserDefaults(suiteName: AppConfig.appGroupID) ?? .standard }

    static var current: String? { defaults.string(forKey: key) }
    static func keep(_ link: String) { defaults.set(link, forKey: key) }
    static func take() -> String? {
        let link = current
        defaults.removeObject(forKey: key)
        return link
    }
}

/// Free vs Plus: this month's video saves, what Plus adds, and the post waiting to be saved.
struct PaywallView: View {
    let request: PaywallRequest
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var comingSoon = false

    private var plan: PlanInfo? { store.plan }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    VStack(alignment: .leading, spacing: 8) {
                        Eyebrow(text: "Travel Edit Plus")
                        Text(plan?.isPlus == true ? "You're on Plus" : "Save every post you love")
                            .font(Theme.serif(32)).foregroundStyle(Theme.label)
                        if let message = request.message, plan?.isPlus != true {
                            Text(message).font(.body).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    if let plan, !plan.isPlus, let limit = plan.videoSavesLimit { meter(plan, limit: limit) }
                    if let link = request.link ?? PendingLink.current, plan?.isPlus != true { waiting(link) }
                    Card(padding: 16) {
                        VStack(alignment: .leading, spacing: 14) {
                            perk("infinity", "Unlimited video saves", "Every TikTok, Instagram and YouTube post you share, with no monthly count.")
                            perk("sparkles", "Every place and event found for you", "Restaurants, bars, sights and dated events from each post, ready to plan with.")
                            perk("photo.on.rectangle", "Screenshots and map links stay free", "On every plan, as many as you like.")
                        }
                    }
                }
                .padding(20)
            }
            .safeAreaInset(edge: .bottom) {
                if plan?.isPlus != true {
                    VStack(spacing: 10) {
                        Button { comingSoon = true } label: { Text("Upgrade to Plus").frame(maxWidth: .infinity) }
                            .buttonStyle(PrimaryButtonStyle())
                        Button("Not now") { dismiss() }
                            .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.link)
                    }
                    .padding(.horizontal, 20).padding(.vertical, 12)
                    .background(.bar)
                }
            }
            .background(Theme.background.ignoresSafeArea())
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
            }
            .alert("Plus is almost here", isPresented: $comingSoon) {
                Button("OK", role: .cancel) {}
            } message: {
                Text("Subscriptions open in the next update. We've kept the post you shared and will save it as soon as you upgrade.")
            }
            .task { await store.loadPlan() }
        }
    }

    private func meter(_ plan: PlanInfo, limit: Int) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Free video saves").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                Spacer()
                Text("\(min(plan.videoSavesUsed, limit)) of \(limit) used").font(.subheadline).foregroundStyle(Theme.secondary)
            }
            HStack(spacing: 5) {
                ForEach(0..<limit, id: \.self) { i in
                    Capsule().fill(i < plan.videoSavesUsed ? Theme.gold : Theme.fill).frame(height: 6)
                }
            }
            Text("Resets \(plan.resetDay).").font(.footnote).foregroundStyle(Theme.secondary)
        }
    }

    private func waiting(_ link: String) -> some View {
        Card(padding: 14) {
            HStack(spacing: 12) {
                SymbolTile(symbol: JobRow.symbol(for: link), color: Theme.indigo)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Waiting to be saved").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                    Text(URL(string: link)?.host?.replacingOccurrences(of: "www.", with: "") ?? link)
                        .font(.footnote).foregroundStyle(Theme.secondary).lineLimit(1)
                }
                Spacer(minLength: 0)
            }
        }
    }

    private func perk(_ symbol: String, _ title: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol).font(.body.weight(.semibold)).foregroundStyle(Theme.gold).frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                Text(text).font(.footnote).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
