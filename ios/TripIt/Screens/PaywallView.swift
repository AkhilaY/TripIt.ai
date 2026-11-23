import StoreKit
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

/// Free vs Plus: this month's video saves, what Plus adds, the plans with their prices, and the post waiting to
/// be saved. Buying goes through the App Store; the server confirms it before Plus turns on.
struct PaywallView: View {
    let request: PaywallRequest
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var purchases = Purchases.shared
    @State private var chosen: String = "plus.yearly"
    @State private var notice: Notice?
    @State private var managing = false

    private struct Notice: Identifiable {
        let id = UUID()
        let title: String
        let text: String
    }

    private var plan: PlanInfo? { store.plan }
    private var selected: Product? { purchases.products.first { $0.id == chosen } ?? purchases.products.first }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(plan?.isPlus == true ? "You're on Plus" : "Save every post you love")
                            .font(Theme.serif(32)).foregroundStyle(Theme.label)
                        if plan?.isPlus == true {
                            Text(plan?.renewsDay.map { "Your subscription renews on \($0) unless you cancel it." } ?? "Unlimited video saves are on.")
                                .font(Theme.text(.body)).foregroundStyle(Theme.secondary)
                        } else if let message = request.message {
                            Text(message).font(Theme.text(.body)).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
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
                    if plan?.isPlus != true { options }
                    legal
                }
                .padding(20)
            }
            .safeAreaInset(edge: .bottom) { actions }
            .background(Theme.background.ignoresSafeArea())
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
            }
            .alert(item: $notice) { n in
                Alert(title: Text(n.title), message: Text(n.text), dismissButton: .default(Text("OK")))
            }
            .manageSubscriptionsSheet(isPresented: $managing)
            .task {
                await store.loadPlan()
                if purchases.products.isEmpty { await purchases.loadProducts() }
            }
        }
    }

    /// Monthly and yearly, with their App Store prices.
    @ViewBuilder private var options: some View {
        if purchases.products.isEmpty {
            HStack(spacing: 10) {
                if purchases.loadFailed {
                    Text("Plans couldn't load from the App Store.").font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
                    Button("Try again") { Task { await purchases.loadProducts() } }.font(Theme.text(.subheadline))
                } else {
                    ProgressView()
                }
            }
            .frame(maxWidth: .infinity, minHeight: 80)
        } else {
            VStack(spacing: 10) {
                ForEach(purchases.products, id: \.id) { product in
                    Button { chosen = product.id } label: { option(product) }
                        .buttonStyle(PressStyle())
                }
            }
        }
    }

    private func option(_ product: Product) -> some View {
        let on = selected?.id == product.id
        return HStack(alignment: .center, spacing: 12) {
            Image(systemName: on ? "checkmark.circle.fill" : "circle")
                .font(.system(size: 20)).foregroundStyle(on ? Theme.label : Theme.tertiary)
            VStack(alignment: .leading, spacing: 3) {
                Text(product.isYearly ? "Yearly" : "Monthly").font(Theme.text(.headline, weight: .medium)).foregroundStyle(Theme.label)
                Text([product.priceLine, product.trialLine].compactMap { $0 }.joined(separator: " · "))
                    .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
            }
            Spacer(minLength: 8)
            if let monthly = product.monthlyEquivalent {
                Text(monthly).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
            }
        }
        .padding(16)
        .background(Theme.cell, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(on ? Theme.label : Theme.border, lineWidth: on ? 1.5 : 1))
        .contentShape(Rectangle())
        .animation(.easeOut(duration: 0.15), value: on)
    }

    /// What Apple asks every subscription screen to say, with the terms and privacy policy.
    private var legal: some View {
        VStack(alignment: .leading, spacing: 8) {
            if plan?.isPlus != true {
                Text("Payment is charged to your Apple ID. The subscription renews automatically at the same price unless you cancel it at least 24 hours before the end of the period. Manage or cancel it any time in Settings > Apple ID > Subscriptions.")
                    .font(Theme.text(.caption)).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 16) {
                Link("Terms of Use", destination: AppConfig.baseURL.appendingPathComponent("terms"))
                Link("Privacy Policy", destination: AppConfig.baseURL.appendingPathComponent("privacy"))
                Button("Restore Purchases") { restore() }
            }
            .font(Theme.text(.caption, weight: .medium)).foregroundStyle(Theme.label)
        }
    }

    @ViewBuilder private var actions: some View {
        VStack(spacing: 10) {
            if plan?.isPlus == true {
                if plan?.plusUntil != nil {
                    Button { managing = true } label: { Text("Manage subscription").frame(maxWidth: .infinity) }
                        .buttonStyle(PrimaryButtonStyle())
                }
            } else {
                Button { buy() } label: {
                    ZStack {
                        Text(selected.map { "Continue · \($0.priceLine)" } ?? "Upgrade to Plus").opacity(purchases.busy ? 0 : 1)
                        if purchases.busy { ProgressView().tint(Theme.accentInk) }
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(selected == nil || purchases.busy)
                Button("Not now") { dismiss() }
                    .font(Theme.text(.subheadline)).foregroundStyle(Theme.link)
            }
        }
        .padding(.horizontal, 20).padding(.vertical, 12)
        .background(.bar)
    }

    private func buy() {
        guard let product = selected else { return }
        Task {
            do {
                switch try await purchases.buy(product, store: store) {
                case .purchased:
                    store.show("Welcome to Plus")
                    dismiss()
                case .pending:
                    notice = Notice(title: "Waiting for approval", text: "Plus turns on as soon as the purchase is approved.")
                case .cancelled:
                    break
                }
            } catch {
                notice = Notice(title: "Couldn't upgrade", text: (error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
            }
        }
    }

    private func restore() {
        Task {
            do {
                if try await purchases.restore(store: store) {
                    store.show("Plus restored")
                } else {
                    notice = Notice(title: "Nothing to restore", text: "There's no active Travel Edit Plus subscription on this Apple ID.")
                }
            } catch {
                notice = Notice(title: "Couldn't restore", text: (error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
            }
        }
    }

    private func meter(_ plan: PlanInfo, limit: Int) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Free video saves").font(Theme.text(.subheadline)).foregroundStyle(Theme.label)
                Spacer()
                Text("\(min(plan.videoSavesUsed, limit)) of \(limit) used").font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
            }
            HStack(spacing: 5) {
                ForEach(0..<limit, id: \.self) { i in
                    Capsule().fill(i < plan.videoSavesUsed ? Theme.gold : Theme.fill).frame(height: 6)
                }
            }
            Text("Resets \(plan.resetDay).").font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
        }
    }

    private func waiting(_ link: String) -> some View {
        Card(padding: 14) {
            HStack(spacing: 12) {
                SymbolTile(symbol: JobRow.symbol(for: link), color: Theme.indigo)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Waiting to be saved").font(Theme.text(.subheadline)).foregroundStyle(Theme.label)
                    Text(URL(string: link)?.host?.replacingOccurrences(of: "www.", with: "") ?? link)
                        .font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).lineLimit(1)
                }
                Spacer(minLength: 0)
            }
        }
    }

    private func perk(_ symbol: String, _ title: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol).font(Theme.text(.body)).foregroundStyle(Theme.gold).frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(Theme.text(.subheadline)).foregroundStyle(Theme.label)
                Text(text).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
