import Foundation
import Observation
import StoreKit

/// Plus, bought in the App Store (StoreKit 2). Each purchase carries the account's token, and its signed transaction
/// goes to the server, which checks Apple's signature before turning Plus on. Renewals and refunds reach the server
/// from Apple directly; the app also passes on any transaction it hears about, in case one was missed.
@MainActor
@Observable
final class Purchases {
    static let shared = Purchases()

    var products: [Product] = []
    var busy = false
    var loadFailed = false

    private var listener: Task<Void, Never>?

    /// Loads the products and starts listening for transactions (renewals, purchases approved later, refunds).
    func start(store: Store) {
        guard listener == nil else { return }
        listener = Task {
            for await update in Transaction.updates {
                await self.deliver(update, store: store)
            }
        }
        Task { await loadProducts() }
    }

    func loadProducts() async {
        let ids = Purchases.productIDs
        do {
            let found = try await Product.products(for: ids)
            products = found.sorted { ($0.subscription?.subscriptionPeriod.unit == .year ? 1 : 0) < ($1.subscription?.subscriptionPeriod.unit == .year ? 1 : 0) }
            loadFailed = found.isEmpty
        } catch {
            loadFailed = true
        }
    }

    static let productIDs = ["plus.monthly", "plus.yearly"]

    enum Outcome { case purchased, pending, cancelled }

    /// Buys Plus. The server confirms it before this returns `.purchased`.
    func buy(_ product: Product, store: Store) async throws -> Outcome {
        busy = true
        defer { busy = false }
        var options: Set<Product.PurchaseOption> = []
        if let token = store.plan?.accountToken, let uuid = UUID(uuidString: token) {
            options.insert(.appAccountToken(uuid))
        }
        switch try await product.purchase(options: options) {
        case .success(let result):
            try await send(result, store: store)
            return .purchased
        case .pending:
            return .pending  // e.g. Ask to Buy: arrives later through Transaction.updates
        case .userCancelled:
            return .cancelled
        @unknown default:
            return .cancelled
        }
    }

    /// Restore Purchases: asks the App Store for this Apple ID's subscriptions and passes the current one on.
    /// Returns whether Plus is on afterwards.
    func restore(store: Store) async throws -> Bool {
        busy = true
        defer { busy = false }
        try await AppStore.sync()
        for await entitlement in Transaction.currentEntitlements {
            try await send(entitlement, store: store)
        }
        await store.loadPlan()
        return store.plan?.isPlus == true
    }

    /// On launch: passes on the current subscription quietly, so the server stays in step if a notification
    /// from Apple went astray.
    func refresh(store: Store) async {
        for await entitlement in Transaction.currentEntitlements {
            try? await send(entitlement, store: store)
        }
    }

    private func deliver(_ result: VerificationResult<Transaction>, store: Store) async {
        try? await send(result, store: store)
    }

    private func send(_ result: VerificationResult<Transaction>, store: Store) async throws {
        guard case .verified(let transaction) = result, Purchases.productIDs.contains(transaction.productID) else {
            throw PurchaseError.unverified
        }
        let plan: PlanInfo = try await API.shared.post("/v1/me/plan/appstore", ["signed_transaction": result.jwsRepresentation])
        store.plan = plan
        await transaction.finish()
        if plan.isPlus { await store.loadPlan() }  // saves a post kept while out of free saves
    }
}

enum PurchaseError: LocalizedError {
    case unverified
    var errorDescription: String? { "The App Store couldn't confirm this purchase. Try again in a moment." }
}

extension Product {
    /// "$4.99 a month", "$34.99 a year".
    var priceLine: String {
        guard let period = subscription?.subscriptionPeriod else { return displayPrice }
        let unit: String
        switch period.unit {
        case .day: unit = "day"
        case .week: unit = "week"
        case .month: unit = "month"
        case .year: unit = "year"
        @unknown default: unit = "period"
        }
        return period.value == 1 ? "\(displayPrice) a \(unit)" : "\(displayPrice) every \(period.value) \(unit)s"
    }

    var isYearly: Bool { subscription?.subscriptionPeriod.unit == .year }

    /// For the yearly plan: what it works out to each month ("$2.92 a month").
    var monthlyEquivalent: String? {
        guard isYearly else { return nil }
        return (price / 12).formatted(priceFormatStyle) + " a month"
    }

    var trialLine: String? {
        guard let offer = subscription?.introductoryOffer, offer.paymentMode == .freeTrial else { return nil }
        let p = offer.period
        let unit = p.unit == .day ? "day" : p.unit == .week ? "week" : p.unit == .month ? "month" : "year"
        return "\(p.value)-\(unit) free trial"
    }
}
