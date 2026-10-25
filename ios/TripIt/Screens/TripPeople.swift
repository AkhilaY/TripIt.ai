import SwiftUI
import UIKit

/// Planning a trip together: who's on it, an invite link to share, and leaving or removing people.
enum TripInvite {
    /// Gets the trip's invite link and opens the share sheet with it.
    @MainActor static func share(_ trip: TripDetail, store: Store) async {
        do {
            let link: InviteLink = try await API.shared.post("/v1/trips/\(trip.id)/invite")
            guard let url = API.shared.url(link.path) else { return }
            let activity = UIActivityViewController(activityItems: ["Plan \(trip.name) with me on The Travel Edit", url], applicationActivities: nil)
            Links.topViewController()?.present(activity, animated: true)
        } catch { store.fail(error) }
    }

    /// Joins the trip an invite link is for (from traveledit://join?token=…), then opens it.
    @MainActor static func join(_ token: String, store: Store, router: Router) async {
        do {
            let trip: Trip = try await API.shared.post("/v1/join/\(token)")
            await store.reloadTrips()
            router.tab = .library
            router.open("#/trip/\(trip.id)")
            store.show("You're planning \(trip.name) together")
        } catch { store.fail(error) }
    }
}

/// The faces of everyone on a trip, with Invite. Shown at the top of the trip's places.
struct PeopleRow: View {
    let trip: TripDetail
    @State private var showPeople = false
    @Environment(Store.self) private var store

    var body: some View {
        let people = trip.members ?? []
        HStack(spacing: 12) {
            if people.count > 1 {
                Button { showPeople = true } label: {
                    HStack(spacing: 10) {
                        HStack(spacing: -6) {
                            ForEach(people.prefix(4)) { Face(member: $0) }
                        }
                        Text(names(people)).font(.subheadline).foregroundStyle(Theme.secondary).lineLimit(1)
                    }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("People on this trip: \(names(people))")
            } else {
                Label("Plan it together", systemImage: "person.2").font(.subheadline).foregroundStyle(Theme.secondary)
            }
            Spacer(minLength: 8)
            Button { Task { await TripInvite.share(trip, store: store) } } label: {
                Label("Invite", systemImage: "plus").font(.footnote.weight(.semibold)).foregroundStyle(Theme.link)
            }
            .buttonStyle(.borderless)
        }
        .sheet(isPresented: $showPeople) { PeopleSheet(trip: trip).environment(store) }
    }

    private func names(_ people: [TripMember]) -> String {
        let names = people.map { $0.you ? "You" : String($0.name.split(separator: " ").first ?? "") }
        return names.count > 3 ? "\(names.prefix(2).joined(separator: ", ")) and \(names.count - 2) more" : names.joined(separator: names.count == 2 ? " and " : ", ")
    }
}

struct Face: View {
    let member: TripMember
    var body: some View {
        Text(member.initials)
            .font(Theme.serif(13)).foregroundStyle(member.you ? Theme.accentInk : Theme.gold)
            .frame(width: 28, height: 28)
            .background(member.you ? Theme.accent : Theme.cell, in: Circle())
            .overlay(Circle().strokeBorder(Theme.background, lineWidth: 2))
    }
}

/// Everyone planning the trip. The owner can remove people or turn the invite link off; others can leave.
struct PeopleSheet: View {
    let trip: TripDetail
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var confirmLeave = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(trip.members ?? []) { m in
                        HStack(spacing: 12) {
                            Face(member: m)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(m.you ? "\(m.name) (you)" : m.name).foregroundStyle(Theme.label)
                                Text(m.role == "owner" ? "Made the trip" : "Planning with you").font(.caption).foregroundStyle(Theme.secondary)
                            }
                        }
                        .swipeActions {
                            if trip.isOwner, !m.you {
                                Button(role: .destructive) { Task { await remove(m) } } label: { Label("Remove", systemImage: "person.badge.minus") }
                            }
                        }
                    }
                } footer: {
                    Text("Everyone here can add places, change the plan and add bookings. Your other saves stay private.")
                }
                Section {
                    Button { Task { await TripInvite.share(trip, store: store) } } label: { Label("Invite someone", systemImage: "person.badge.plus") }
                    if trip.isOwner {
                        Button(role: .destructive) { Task { await turnOffLink() } } label: { Label("Turn off the invite link", systemImage: "link.badge.plus") }
                    } else {
                        Button(role: .destructive) { confirmLeave = true } label: { Label("Leave trip", systemImage: "rectangle.portrait.and.arrow.right") }
                    }
                }
            }
            .tripBackground()
            .navigationTitle("People")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .confirmationDialog("Leave \(trip.name)? It leaves your Trips; the places you added stay on it.", isPresented: $confirmLeave, titleVisibility: .visible) {
                Button("Leave trip", role: .destructive) { Task { await leave() } }
            }
        }
    }

    private func remove(_ m: TripMember) async {
        do {
            try await API.shared.call("DELETE", "/v1/trips/\(trip.id)/members/\(m.userId)")
            _ = try? await store.loadTrip(trip.id)
            store.show("\(m.name) was removed")
        } catch { store.fail(error) }
    }

    private func turnOffLink() async {
        do {
            try await API.shared.call("DELETE", "/v1/trips/\(trip.id)/invite")
            store.show("The old link no longer works")
        } catch { store.fail(error) }
    }

    private func leave() async {
        guard let me = trip.members?.first(where: \.you) else { return }
        do {
            try await API.shared.call("DELETE", "/v1/trips/\(trip.id)/members/\(me.userId)")
            store.tripDetails[trip.id] = nil
            await store.reloadTrips()
            dismiss()
            store.show("You left \(trip.name)")
        } catch { store.fail(error) }
    }
}
