import SwiftUI
import UIKit

// MARK: - Your travel taste

struct TasteProfile: Codable {
    var pace: String?
    var budget: String?
    var food: [String] = []
    var interests: [String] = []
    var mornings: String?
    var notes: String?
}

/// Five quick questions about how you travel; edits, briefings, Discover and the concierge use the answers.
struct TasteView: View {
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var profile = TasteProfile()
    @State private var step = 0
    @State private var loaded = false
    @State private var saving = false

    struct Option: Identifiable {
        let value: String
        let label: String
        var hint: String?
        var id: String { value }
    }

    struct Question {
        let key: String
        let text: String
        let single: Bool
        let options: [Option]
        var notes = false
    }

    static let questions: [Question] = [
        Question(key: "pace", text: "How do you like to travel?", single: true, options: [
            Option(value: "slow", label: "Slow & savoured", hint: "Fewer places, longer lunches"),
            Option(value: "balanced", label: "Balanced", hint: "A rhythm of plans and wandering"),
            Option(value: "packed", label: "See it all", hint: "Every hour well spent"),
        ]),
        Question(key: "budget", text: "When it comes to spending…", single: true, options: [
            Option(value: "value", label: "Hidden gems", hint: "Good value and local favourites"),
            Option(value: "mix", label: "A considered mix", hint: "Save here, splurge there"),
            Option(value: "splurge", label: "Worth the splurge", hint: "The best table in town"),
        ]),
        Question(key: "food", text: "What do you look for at the table?", single: false,
                 options: ["Fine dining", "Neighbourhood favourites", "Street food", "Cafés & bakeries", "Natural wine",
                           "Cocktail bars", "Seafood", "Vegetarian-friendly"].map { Option(value: $0, label: $0) }),
        Question(key: "interests", text: "What makes a trip for you?", single: false,
                 options: ["Design & architecture", "Art & museums", "Fashion & boutiques", "Views & nature", "Wellness & spas",
                           "Nightlife", "History", "Markets", "Live music", "Theatre & comedy", "Sports"].map { Option(value: $0, label: $0) }),
        Question(key: "mornings", text: "And your mornings?", single: true, options: [
            Option(value: "early", label: "Early riser", hint: "First in line, golden light"),
            Option(value: "late", label: "Late starts", hint: "Nothing before ten"),
        ], notes: true),
    ]

    var body: some View {
        let q = Self.questions[step]
        let last = step == Self.questions.count - 1
        VStack(alignment: .leading, spacing: 0) {
            ProgressView(value: Double(step + 1), total: Double(Self.questions.count)).tint(Theme.gold)
                .padding(.horizontal, 20)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Eyebrow(text: "\(step + 1) of \(Self.questions.count)")
                    Text(q.text).font(Theme.serif(30)).foregroundStyle(Theme.label)
                    Text(q.single ? "Choose one" : "Choose as many as you like").font(.subheadline).foregroundStyle(Theme.secondary)
                    VStack(spacing: 10) {
                        ForEach(q.options) { option in
                            let on = isChosen(q, option.value)
                            Button { toggle(q, option.value) } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(option.label).font(.body.weight(.semibold))
                                        if let hint = option.hint { Text(hint).font(.footnote).opacity(0.75) }
                                    }
                                    Spacer()
                                    if on { Image(systemName: "checkmark").font(.footnote.weight(.bold)) }
                                }
                                .foregroundStyle(on ? Theme.accentInk : Theme.label)
                                .padding(14)
                                .background(on ? Theme.accent : Theme.cell, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                                .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Theme.border, lineWidth: on ? 0 : 1))
                            }
                            .buttonStyle(.plain)
                            .accessibilityAddTraits(on ? .isSelected : [])
                        }
                    }
                    if q.notes {
                        VStack(alignment: .leading, spacing: 6) {
                            Eyebrow(text: "Anything else?", color: Theme.secondary)
                            TextField("Dietary needs, who you travel with, things you love or avoid",
                                      text: Binding(get: { profile.notes ?? "" }, set: { profile.notes = $0 }), axis: .vertical)
                                .lineLimit(2...5)
                                .padding(12)
                                .background(Theme.cell, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.border))
                        }
                        .padding(.top, 6)
                    }
                }
                .padding(20)
                .id(step)
                .transition(.asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity), removal: .opacity))
            }
            Button {
                if last { Task { await save() } } else { withAnimation { step += 1 } }
            } label: {
                if saving { ProgressView() } else { Text(last ? "Save my taste" : "Continue") }
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(saving || !loaded)
            .padding(20)
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle("Your travel taste")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if step > 0 {
                ToolbarItem(placement: .topBarLeading) { Button("Back") { withAnimation { step -= 1 } } }
            }
            ToolbarItem(placement: .topBarTrailing) {
                if !last { Button("Skip") { withAnimation { step += 1 } } }
            }
        }
        .navigationBarBackButtonHidden(step > 0)
        .task {
            if let p: TasteProfile = try? await API.shared.get("/v1/profile") { profile = p }
            loaded = true
        }
    }

    private func isChosen(_ q: Question, _ value: String) -> Bool {
        switch q.key {
        case "pace": profile.pace == value
        case "budget": profile.budget == value
        case "mornings": profile.mornings == value
        case "food": profile.food.contains(value)
        default: profile.interests.contains(value)
        }
    }

    private func toggle(_ q: Question, _ value: String) {
        switch q.key {
        case "pace": profile.pace = profile.pace == value ? nil : value
        case "budget": profile.budget = profile.budget == value ? nil : value
        case "mornings": profile.mornings = profile.mornings == value ? nil : value
        case "food": if let i = profile.food.firstIndex(of: value) { profile.food.remove(at: i) } else { profile.food.append(value) }
        default: if let i = profile.interests.firstIndex(of: value) { profile.interests.remove(at: i) } else { profile.interests.append(value) }
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        let notes = (profile.notes ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            let _: TasteProfile = try await API.shared.put("/v1/profile", [
                "pace": profile.pace, "budget": profile.budget, "food": profile.food, "interests": profile.interests,
                "mornings": profile.mornings, "notes": notes.isEmpty ? nil : notes,
            ])
            store.show("Your taste is saved")
            dismiss()
        } catch { store.fail(error) }
    }
}

// MARK: - People (owner only)

private struct AdminUser: Codable, Identifiable {
    var id: String
    var email: String
    var name: String
    var isAdmin: Bool
    var createdAt: String
}

private struct TempPassword: Codable {
    var password: String
}

/// Everyone with an account, and a temporary password for someone who forgot theirs.
struct PeopleAdminView: View {
    @Environment(Store.self) private var store
    @State private var users: [AdminUser] = []
    @State private var temp: (email: String, password: String)?
    @State private var resetting: AdminUser?

    var body: some View {
        List {
            if let temp {
                Section {
                    HStack {
                        Text(temp.password).font(.title3.monospaced().weight(.semibold)).textSelection(.enabled)
                        Spacer()
                        Button("Copy") { UIPasteboard.general.string = temp.password; store.show("Copied") }
                    }
                } footer: {
                    Text("A temporary password for \(temp.email). They can change it in their Profile after signing in.")
                }
            }
            Section {
                ForEach(users) { u in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(u.email.isEmpty ? (u.name.isEmpty ? "Signed in with Apple" : u.name) : u.email)
                            Text(u.isAdmin ? "Owner" : "Joined \(Fmt.shortDay(u.createdAt))").font(.footnote).foregroundStyle(Theme.secondary)
                        }
                        Spacer()
                        if !u.isAdmin, !u.email.isEmpty, !u.email.hasSuffix("@users.traveledit.invalid") {
                            Button("Reset password") { resetting = u }.font(.footnote.weight(.semibold))
                        }
                    }
                }
            } footer: {
                Text("\(Fmt.plural(users.count, "account")). Anyone can sign up; people who use Sign in with Apple don't have a password to reset.")
            }
        }
        .tripBackground()
        .navigationTitle("People")
        .task { await load() }
        .refreshable { await load() }
        .confirmationDialog("Reset \(resetting?.email ?? "")'s password? It signs them out everywhere.",
                            isPresented: Binding(get: { resetting != nil }, set: { if !$0 { resetting = nil } }), titleVisibility: .visible) {
            Button("Reset password", role: .destructive) {
                if let u = resetting { Task { await reset(u) } }
            }
        }
    }

    private func load() async {
        do { users = try await API.shared.get("/v1/admin/users") } catch { store.fail(error) }
    }

    private func reset(_ u: AdminUser) async {
        do {
            let result: TempPassword = try await API.shared.post("/v1/admin/users/\(u.id)/reset-password")
            temp = (u.email, result.password)
        } catch { store.fail(error) }
    }
}

// MARK: - Usage & costs (owner only)

private struct UsageReport: Codable {
    struct Day: Codable, Hashable { var day: String; var cost: Double; var calls: Int }
    struct Feature: Codable, Hashable { var feature: String; var calls: Int; var cost: Double; var inputTokens: Int; var outputTokens: Int; var searches: Int }
    struct Person: Codable, Hashable { var userId: String?; var email: String; var calls: Int; var costMonth: Double; var costToday: Double }
    struct Google: Codable, Hashable { var kind: String; var calls: Int; var cost: Double }

    var month: String
    var monthCost: Double
    var todayCost: Double
    var monthlyBudget: Double?
    var paused: Bool
    var config: [String: Double?]
    var limitLabels: [String: String]
    var days: [Day]
    var features: [Feature]
    var people: [Person]
    var google: [Google]
    var googleCost: Double

    /// A budget or limit. The decoder turns snake_case keys into camelCase, dictionary keys included, so both are tried.
    func value(_ key: String) -> Double? {
        let parts = key.split(separator: "_").map(String.init)
        let camel = (parts.first ?? "") + parts.dropFirst().map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined()
        return (config[key] ?? config[camel]) ?? nil
    }
}

/// AI spend this month by day, feature and person, Google Maps calls, and the budgets and daily limits.
struct UsageView: View {
    @Environment(Store.self) private var store
    @State private var report: UsageReport?
    @State private var editing = false

    static let featureLabels = [
        "import": "Imports", "plan": "AI plans", "tidy": "Tidy with AI", "suggest": "Suggestions", "concierge": "Concierge",
        "menu": "Menus", "menu_retry": "Menus (extra tries)", "menu_links": "Menus (finding links)", "bookings": "Reading bookings",
        "packing": "Packing lists", "edits": "Edits", "edits_research": "Edits (web research)", "discover": "Discover notes",
        "lounges": "Lounges", "booking_needs": "Booking checks", "events": "What's on", "briefing": "Daily briefings", "other": "Other",
    ]
    static let googleLabels = [
        "locate": "Place lookups", "search": "Place search", "nearby": "Discover nearby", "details": "Place details",
        "menu_photos": "Menu photo search", "photo": "Photos", "routes": "Travel times (per route)",
    ]

    static func money(_ n: Double?) -> String {
        guard let n else { return "no budget" }
        return n > 0 && n < 0.01 ? "<$0.01" : String(format: "$%.2f", n)
    }

    var body: some View {
        List {
            if let r = report {
                let budget = r.monthlyBudget ?? 0
                let share = budget > 0 ? min(1, r.monthCost / budget) : 0
                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("\(Self.money(r.monthCost)) of \(budget > 0 ? Self.money(budget) : "no budget")").font(.headline)
                        Text(r.paused ? "Budget used up: AI is paused until next month"
                             : budget > 0 ? "\(Int(share * 100))% of this month's budget" : "No monthly budget set")
                            .font(.footnote).foregroundStyle(r.paused ? Theme.danger : Theme.secondary)
                        if budget > 0 { ProgressView(value: share).tint(r.paused || share >= 0.8 ? Theme.danger : Theme.ok) }
                    }
                    LabeledContent("Today", value: Self.money(r.todayCost))
                    Button { editing = true } label: {
                        LabeledContent("Budgets and limits", value: "\(Self.money(r.value("user_daily_budget_usd"))) a day each")
                    }
                } header: {
                    Text("AI spend in \(Self.monthName(r.month))")
                } footer: {
                    Text("Estimated from Claude's token counts. Your own use counts toward the budget, but per-person limits don't apply to you.")
                }
                Section("By day") {
                    ForEach(r.days, id: \.self) { d in LabeledContent(Fmt.shortDay(d.day), value: "\(Self.money(d.cost)) · \(d.calls) calls") }
                }
                Section("By feature this month") {
                    ForEach(r.features, id: \.self) { f in
                        LabeledContent {
                            Text(Self.money(f.cost))
                        } label: {
                            Text(Self.featureLabels[f.feature] ?? f.feature)
                            Text("\(f.calls) calls · \(Fmt.count(f.inputTokens + f.outputTokens)) tokens\(f.searches > 0 ? " · \(f.searches) web searches" : "")")
                        }
                    }
                }
                Section("By person this month") {
                    ForEach(r.people, id: \.self) { p in
                        LabeledContent {
                            Text(Self.money(p.costMonth))
                        } label: {
                            Text(p.email)
                            Text("\(p.calls) AI calls · \(Self.money(p.costToday)) today")
                        }
                    }
                }
                Section {
                    ForEach(r.google, id: \.self) { g in
                        LabeledContent(Self.googleLabels[g.kind] ?? g.kind, value: "\(Self.money(g.cost)) · \(g.calls) calls")
                    }
                } header: {
                    Text("Google Maps this month")
                } footer: {
                    if !r.google.isEmpty {
                        Text("About \(Self.money(r.googleCost)) at Google's list prices, before its free monthly allowance. Billed by Google; not part of the AI budget.")
                    }
                }
            } else {
                ProgressView().frame(maxWidth: .infinity).listRowBackground(Color.clear)
            }
        }
        .tripBackground()
        .navigationTitle("Usage & costs")
        .task { await load() }
        .refreshable { await load() }
        .sheet(isPresented: $editing) {
            if let r = report { LimitsSheet(report: r) { await load() } }
        }
    }

    static func monthName(_ month: String) -> String {
        Fmt.day(month + "-01")?.formatted(.dateTime.month(.wide).year()) ?? month
    }

    private func load() async {
        do { report = try await API.shared.get("/v1/admin/usage") } catch { store.fail(error) }
    }
}

/// Change the monthly budget, each person's daily budget and the daily limits.
private struct LimitsSheet: View {
    let report: UsageReport
    let onSaved: () async -> Void
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var values: [String: String] = [:]

    private var keys: [String] {
        ["monthly_budget_usd", "user_daily_budget_usd"] + report.limitLabels.keys.sorted().map { "limit_\($0)" }
    }

    private func label(_ key: String) -> String {
        switch key {
        case "monthly_budget_usd": return "Monthly budget ($)"
        case "user_daily_budget_usd": return "Per person per day ($)"
        default:
            let name = String(key.dropFirst("limit_".count))
            return "Daily \(report.limitLabels[name] ?? name)"
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    ForEach(keys, id: \.self) { key in
                        LabeledContent(label(key)) {
                            TextField("No limit", text: Binding(get: { values[key] ?? "" }, set: { values[key] = $0 }))
                                .keyboardType(.decimalPad)
                                .multilineTextAlignment(.trailing)
                        }
                    }
                } footer: {
                    Text("Empty means no limit. Daily limits are per person and don't apply to you.")
                }
            }
            .tripBackground()
            .navigationTitle("Budgets and limits")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { Task { await save() } } }
            }
        }
        .onAppear {
            for key in keys {
                if let value = report.value(key), value > 0 {
                    values[key] = value == value.rounded() ? String(Int(value)) : String(value)
                }
            }
        }
    }

    private func save() async {
        var body: [String: Any?] = [:]
        for key in keys {
            let text = (values[key] ?? "").trimmingCharacters(in: .whitespaces)
            body[key] = text.isEmpty ? 0 : Double(text.replacingOccurrences(of: ",", with: "."))
        }
        do {
            try await API.shared.call("PUT", "/v1/admin/usage/limits", body)
            await onSaved()
            store.show("Limits saved")
            dismiss()
        } catch { store.fail(error) }
    }
}
