import SwiftUI

/// Pick a trip's dates on a calendar: tap the first day, then the last. "No dates yet" leaves them open.
struct DateRangeSheet: View {
    @Binding var start: Date?
    @Binding var end: Date?
    var maxDays = 21
    @Environment(\.dismiss) private var dismiss
    @State private var first: Date?
    @State private var last: Date?

    private let calendar = Calendar.current
    private var today: Date { calendar.startOfDay(for: Date()) }
    private var months: [Date] {
        let thisMonth = calendar.date(from: calendar.dateComponents([.year, .month], from: today)) ?? today
        return (0..<18).compactMap { calendar.date(byAdding: .month, value: $0, to: thisMonth) }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                summary.padding(.horizontal, 20).padding(.bottom, 10)
                weekdayHeader.padding(.horizontal, 16)
                Divider().overlay(Theme.border)
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 26) {
                        ForEach(months, id: \.self) { month in monthView(month) }
                    }
                    .padding(.horizontal, 16).padding(.vertical, 16)
                }
                actions
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Trip dates")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
        }
        .onAppear { first = start; last = end }
    }

    // MARK: Pieces

    private var summary: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(rangeText).font(Theme.serif(24)).foregroundStyle(Theme.label)
            Spacer()
            if let n = dayCount { Text(Fmt.plural(n, "day")).font(Theme.text(.subheadline)).foregroundStyle(Theme.secondary) }
        }
    }

    private var rangeText: String {
        guard let first else { return "Choose the first day" }
        guard let last else { return first.formatted(.dateTime.month(.abbreviated).day()) + " – choose the last day" }
        return Fmt.range(first, last)
    }

    private var dayCount: Int? {
        guard let first else { return nil }
        return (calendar.dateComponents([.day], from: first, to: last ?? first).day ?? 0) + 1
    }

    private var weekdayHeader: some View {
        let symbols = calendar.veryShortStandaloneWeekdaySymbols
        let shift = calendar.firstWeekday - 1
        let ordered = Array(symbols[shift...] + symbols[..<shift])
        return HStack(spacing: 0) {
            ForEach(Array(ordered.enumerated()), id: \.offset) { _, s in
                Text(s).font(Theme.text(.caption)).foregroundStyle(Theme.secondary).frame(maxWidth: .infinity)
            }
        }
        .padding(.vertical, 8)
    }

    private func monthView(_ month: Date) -> some View {
        let days = calendar.range(of: .day, in: .month, for: month)?.count ?? 30
        let lead = (calendar.component(.weekday, from: month) - calendar.firstWeekday + 7) % 7
        let cells: [Date?] = Array(repeating: nil, count: lead)
            + (0..<days).map { calendar.date(byAdding: .day, value: $0, to: month) }
        return VStack(alignment: .leading, spacing: 10) {
            Text(month.formatted(.dateTime.month(.wide).year())).font(Theme.text(.headline, weight: .medium)).foregroundStyle(Theme.label)
                .padding(.leading, 4)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 0), count: 7), spacing: 4) {
                ForEach(Array(cells.enumerated()), id: \.offset) { _, day in
                    if let day { dayCell(day) } else { Color.clear.frame(height: 42) }
                }
            }
        }
    }

    private func dayCell(_ day: Date) -> some View {
        let past = day < today
        let isFirst = first.map { calendar.isDate($0, inSameDayAs: day) } ?? false
        let isLast = last.map { calendar.isDate($0, inSameDayAs: day) } ?? false
        let inside = first.flatMap { f in last.map { l in day > f && day < l } } ?? false
        let selected = isFirst || isLast
        return Button { tap(day) } label: {
            Text("\(calendar.component(.day, from: day))")
                .font(Theme.text(.subheadline, weight: selected ? .medium : .regular))
                .foregroundStyle(selected ? Theme.accentInk : past ? Theme.quiet : Theme.label)
                .frame(maxWidth: .infinity, minHeight: 42)
                .background {
                    ZStack {
                        if inside || (isFirst && last != nil && !isLast) || (isLast && !isFirst) {
                            // The band joining the first and last days.
                            Theme.fill
                                .padding(.leading, isFirst ? 21 : 0)
                                .padding(.trailing, isLast ? 21 : 0)
                        }
                        if selected { Circle().fill(Theme.accent).frame(width: 40, height: 40) }
                    }
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(past)
        .accessibilityLabel(day.formatted(date: .complete, time: .omitted))
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var actions: some View {
        VStack(spacing: 8) {
            Button { start = first; end = last ?? first; dismiss() } label: { Text("Done").frame(maxWidth: .infinity) }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(first == nil)
            Button("No dates yet") { start = nil; end = nil; dismiss() }
                .font(Theme.text(.subheadline)).foregroundStyle(Theme.link).frame(minHeight: 36)
        }
        .padding(.horizontal, 20).padding(.vertical, 12)
        .background(Theme.background)
    }

    // MARK: Choosing

    /// First tap sets the first day; the next sets the last (or starts again if it's earlier, or too long a trip).
    private func tap(_ day: Date) {
        withAnimation(.easeOut(duration: 0.15)) {
            if let f = first, last == nil, day >= f,
               (calendar.dateComponents([.day], from: f, to: day).day ?? 0) < maxDays {
                last = day
            } else {
                first = day
                last = nil
            }
        }
    }
}
