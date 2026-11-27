import SwiftUI

/// Days to go, in split-flap tiles like a departure board. The digits roll into place when Home opens, with a tick.
struct CountdownBoard: View {
    let days: Int
    @State private var shown = 0

    var body: some View {
        HStack(spacing: 4) {
            ForEach(Array(String(shown).enumerated()), id: \.offset) { _, digit in
                Text(String(digit))
                    .font(Theme.serif(30))
                    .contentTransition(.numericText(value: Double(shown)))
                    .foregroundStyle(Color(hex: 0xF4EDE2))
                    .frame(width: 30, height: 42)
                    .background(Color(hex: 0x1E1A17), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                    .overlay { Rectangle().fill(.black).frame(height: 1) }  // the flap's hinge
            }
        }
        .sensoryFeedback(.impact(flexibility: .rigid, intensity: 0.6), trigger: shown)
        .task(id: days) {
            try? await Task.sleep(for: .milliseconds(250))
            withAnimation(.spring(duration: 0.7)) { shown = days }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Fmt.plural(days, "day") + " to go")
    }
}

/// Cities as a stack of cards, like a wallet. Fan them out to see each; tap one to open it; press and hold for more.
struct CityWallet: View {
    let groups: [Store.CityGroup]
    let tripLine: (Store.CityGroup) -> String
    let onOpen: (Store.CityGroup) -> Void
    @State private var fanned = false

    var body: some View {
        let gap: CGFloat = fanned ? 232 : 56
        let height: CGFloat = 220 + gap * CGFloat(max(0, groups.count - 1))
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Your cities").font(Theme.serif(25)).foregroundStyle(Theme.label)
                Spacer()
                Button { withAnimation(.spring(duration: 0.5, bounce: 0.2)) { fanned.toggle() } } label: {
                    Image(systemName: "chevron.down").font(.system(size: 15, weight: .medium)).foregroundStyle(Theme.label)
                        .rotationEffect(.degrees(fanned ? 180 : 0))
                        .frame(width: 40, height: 40).background(Theme.fill, in: Circle())
                }
                .accessibilityLabel(fanned ? "Stack the cities" : "Spread out the cities")
            }
            ZStack(alignment: .top) {
                ForEach(Array(groups.enumerated()), id: \.element.id) { i, city in
                    Button { onOpen(city) } label: { card(city) }
                        .buttonStyle(PressStyle())
                        .offset(y: gap * CGFloat(i))
                        .contextMenu {
                            Button { onOpen(city) } label: { Label("Open \(city.name)", systemImage: "arrow.up.right") }
                        }
                }
            }
            .frame(height: height, alignment: .top)
        }
        .sensoryFeedback(.impact(weight: .light), trigger: fanned)
    }

    private func card(_ city: Store.CityGroup) -> some View {
        Color.clear.frame(height: 220)
            .overlay { CityCover(city: city.name, country: city.country, fallback: city.coverURLs(width: 600)) }
            .overlay(alignment: .topLeading) {
                ZStack(alignment: .topLeading) {
                    LinearGradient(colors: [.black.opacity(0.55), .clear], startPoint: .top, endPoint: .center)
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text(city.name).font(Theme.serif(22)).foregroundStyle(.white)
                        Text(tripLine(city)).font(Theme.text(.caption)).foregroundStyle(.white.opacity(0.85))
                    }
                    .padding(16)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .shadow(color: .black.opacity(0.18), radius: 10, y: -4)
    }
}
