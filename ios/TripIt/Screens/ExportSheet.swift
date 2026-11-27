import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Trip → Export (Plus): the whole trip (the plan, flights, stays and tables) as a PDF, as text for Apple Notes or
/// Notion, or into a calendar. The server writes each one; this sheet fetches it and hands it on.
struct ExportSheet: View {
    let trip: TripDetail
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var style = "designed"
    @State private var busy: String?
    @State private var copied: String?
    @State private var error: String?

    /// US-style paper where it's used; A4 everywhere else.
    private var paper: String {
        ["US", "CA", "MX", "PH", "CL", "CO"].contains(Locale.current.region?.identifier ?? "") ? "Letter" : "A4"
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(trip.name).font(Theme.serif(30)).foregroundStyle(Theme.label)
                        Text("The plan for each day, with your flights, stays and tables.")
                            .font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary)
                    }
                    .padding(.bottom, 6)

                    card(symbol: "doc.richtext", title: "PDF", detail: "Share it, print it, or save it to Files or Notes.") {
                        Picker("Style", selection: $style) {
                            Text("Designed").tag("designed")
                            Text("Printable").tag("printable")
                        }
                        .pickerStyle(.segmented)
                        Text(style == "designed"
                             ? "A cover photo, your bookings at a glance, then a page for each day with photos and notes."
                             : "The whole trip on two or three pages, with boxes to tick. No photos, easy on ink.")
                            .font(Theme.text(.footnote)).foregroundStyle(Theme.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        Button { Task { await makePDF() } } label: { working("pdf", "Make the PDF") }
                            .buttonStyle(PrimaryButtonStyle())
                    }

                    card(symbol: "doc.on.clipboard", title: "Notes and Notion",
                         detail: "Copy the trip, then paste it into a note or a Notion page: headings, bookings and a list for each day.") {
                        HStack(spacing: 10) {
                            copyButton("notes", "Copy for Notes")
                            copyButton("notion", "Copy for Notion")
                        }
                        if let copied {
                            Label(copied == "notes" ? "Copied. Paste it into a new note." : "Copied. Paste it into a Notion page.",
                                  systemImage: "checkmark")
                                .font(Theme.text(.footnote)).foregroundStyle(Theme.ok)
                        }
                    }

                    card(symbol: "calendar.badge.plus", title: "Calendar",
                         detail: "Flights, stays, tables and each day's places, at local time.") {
                        Button { Task { await addToCalendar() } } label: { working("calendar", "Add to Calendar") }
                            .buttonStyle(OutlinedButton())
                    }

                    if let error {
                        Text(error).font(Theme.text(.footnote)).foregroundStyle(Theme.danger)
                    }
                }
                .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 30)
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Export")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }

    // MARK: Pieces

    private func card<Content: View>(symbol: String, title: String, detail: String,
                                     @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: symbol).font(.system(size: 17, weight: .light)).foregroundStyle(Theme.label)
                    .frame(width: 36, height: 36).background(Theme.fill, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(Theme.text(.headline, weight: .medium)).foregroundStyle(Theme.label)
                    Text(detail).font(Theme.text(.footnote)).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            content()
        }
        .padding(16)
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Theme.border))
    }

    private func working(_ job: String, _ title: String) -> some View {
        HStack(spacing: 8) {
            if busy == job { ProgressView().controlSize(.small) }
            Text(busy == job ? "Making it…" : title)
        }
        .frame(maxWidth: .infinity)
    }

    private func copyButton(_ kind: String, _ title: String) -> some View {
        Button { Task { await copy(kind) } } label: { working(kind, title) }
            .buttonStyle(OutlinedButton())
    }

    // MARK: Exports

    private func run(_ job: String, _ work: () async throws -> Void) async {
        busy = job
        error = nil
        defer { busy = nil }
        do { try await work() } catch is CancellationError {
        } catch { self.error = (error as? APIError)?.message ?? error.localizedDescription }
    }

    private func makePDF() async {
        await run("pdf") {
            let data = try await API.shared.data("/v1/trips/\(trip.id)/document?style=\(style)&size=\(paper)")
            let name = trip.name.replacingOccurrences(of: "/", with: "-") + (style == "printable" ? " (printable)" : "")
            let file = FileManager.default.temporaryDirectory.appendingPathComponent(name + ".pdf")
            try data.write(to: file, options: .atomic)
            let share = UIActivityViewController(activityItems: [file], applicationActivities: nil)
            Links.topViewController()?.present(share, animated: true)
        }
    }

    private struct TripText: Decodable {
        let markdown: String
        let html: String
    }

    /// Notes keeps headings, bold and lists from rich text; Notion turns Markdown into headings and to-dos.
    private func copy(_ kind: String) async {
        await run(kind) {
            let text: TripText = try await API.shared.get("/v1/trips/\(trip.id)/text")
            if kind == "notes" {
                UIPasteboard.general.setItems([[UTType.html.identifier: text.html, UTType.utf8PlainText.identifier: text.markdown]])
            } else {
                UIPasteboard.general.string = text.markdown
            }
            withAnimation { copied = kind }
        }
    }

    private struct Link: Decodable {
        let url: String
    }

    /// Opens the trip's calendar file, which offers to add every event to Apple Calendar.
    private func addToCalendar() async {
        await run("calendar") {
            let link: Link = try await API.shared.post("/v1/trips/\(trip.id)/export-link?format=ics")
            if let url = API.shared.url(link.url) { openURL(url) }
        }
    }
}

/// A full-width outlined button, the quieter partner of PrimaryButtonStyle.
struct OutlinedButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.text(.subheadline, weight: .medium))
            .foregroundStyle(Theme.label)
            .padding(.horizontal, 14).frame(minHeight: 46)
            .overlay(Capsule().strokeBorder(Theme.chipBorder))
            .contentShape(Capsule())
            .opacity(configuration.isPressed ? 0.6 : 1)
    }
}
