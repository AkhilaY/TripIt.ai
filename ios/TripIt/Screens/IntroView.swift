import SwiftUI

/// The first thing a new person sees: four short slides on what The Travel Edit does, then sign-in.
/// The pictures are built from the app's own pieces, so they look like the real screens.
struct IntroView: View {
    let onDone: () -> Void
    @State private var page = 0

    private let slides: [(title: String, text: String)] = [
        ("Save it from a Reel", "Share a TikTok or Instagram post to The Travel Edit. It finds every place mentioned and puts them on your map."),
        ("Everything finds its city", "Places file themselves by city, so London, Lisbon and the spots near home are always one tap away."),
        ("Days that actually work", "Turn your saves into a plan with realistic times: breakfast, a market, lunch, dinner. Never five lunches at once."),
        ("Plan it together", "Invite a partner or friends to a trip. Add places, move days and keep your bookings in one place."),
    ]

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer()
                if page < slides.count - 1 {
                    Button("Skip", action: onDone).font(.subheadline.weight(.medium)).foregroundStyle(Theme.secondary)
                }
            }
            .frame(height: 44)
            .padding(.horizontal, 24)

            TabView(selection: $page) {
                ForEach(slides.indices, id: \.self) { i in
                    VStack(spacing: 28) {
                        picture(i)
                            .frame(maxWidth: .infinity, minHeight: 300, maxHeight: 340)
                            .background(Theme.cell, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                            .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).strokeBorder(Theme.border))
                        VStack(spacing: 10) {
                            Text(slides[i].title).font(Theme.serif(32)).foregroundStyle(Theme.label).multilineTextAlignment(.center)
                            Text(slides[i].text).font(.body).foregroundStyle(Theme.secondary).multilineTextAlignment(.center)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(.horizontal, 8)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 24)
                    .tag(i)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))

            HStack(spacing: 7) {
                ForEach(slides.indices, id: \.self) { i in
                    Capsule().fill(i == page ? Theme.accent : Theme.tertiary.opacity(0.5))
                        .frame(width: i == page ? 18 : 7, height: 7)
                }
            }
            .animation(.spring(duration: 0.3), value: page)
            .padding(.bottom, 20)

            Button(page == slides.count - 1 ? "Get started" : "Next") {
                if page == slides.count - 1 { onDone() } else { withAnimation { page += 1 } }
            }
            .buttonStyle(PrimaryButtonStyle())
            .padding(.horizontal, 24)
            .padding(.bottom, 24)
        }
        .background(Theme.background.ignoresSafeArea())
    }

    @ViewBuilder private func picture(_ i: Int) -> some View {
        switch i {
        case 0: ReelPicture()
        case 1: CitiesPicture()
        case 2: DayPicture()
        default: TogetherPicture()
        }
    }
}

private struct MiniRow: View {
    let category: Category
    let name: String
    let detail: String
    var trailing: String? = nil

    var body: some View {
        HStack(spacing: 12) {
            CategoryTile(category: category, size: 34)
            VStack(alignment: .leading, spacing: 1) {
                Text(name).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.label)
                Text(detail).font(.caption).foregroundStyle(Theme.secondary)
            }
            Spacer(minLength: 4)
            if let trailing { Text(trailing).font(.caption.weight(.semibold)).foregroundStyle(Theme.ok) }
        }
    }
}

private struct ReelPicture: View {
    var body: some View {
        HStack(spacing: 16) {
            ZStack {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(LinearGradient(colors: [Category.food.color, Category.dessert.color, Category.drinks.color], startPoint: .topLeading, endPoint: .bottomTrailing))
                    .opacity(0.85)
                Image(systemName: "play.fill").font(.title2).foregroundStyle(.white.opacity(0.9))
                VStack { Spacer(); Text("@londonfoodie").font(.caption2.weight(.semibold)).foregroundStyle(.white).padding(.bottom, 10) }
            }
            .frame(width: 96, height: 170)
            Image(systemName: "arrow.right").font(.headline).foregroundStyle(Theme.gold)
            VStack(alignment: .leading, spacing: 14) {
                MiniRow(category: .food, name: "Dishoom", detail: "Restaurant · Carnaby", trailing: "Saved")
                MiniRow(category: .cafe, name: "Monmouth", detail: "Café · Borough", trailing: "Saved")
                MiniRow(category: .shopping, name: "Liberty", detail: "Shopping · Soho", trailing: "Saved")
            }
        }
        .padding(20)
    }
}

private struct CitiesPicture: View {
    private let cities: [(String, Int, Category)] = [("London", 12, .attraction), ("Paris", 8, .cafe), ("Lisbon", 5, .nature), ("Tokyo", 9, .food)]
    var body: some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 16) {
            ForEach(cities.indices, id: \.self) { i in
                let city = cities[i]
                VStack(alignment: .leading, spacing: 4) {
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(city.2.color.opacity(0.14))
                        .frame(height: 74)
                        .overlay(Image(systemName: city.2.symbol).font(.title3).foregroundStyle(city.2.color))
                    Text(city.0).font(Theme.serif(18)).foregroundStyle(Theme.label)
                    Text("\(city.1) places").font(.caption).foregroundStyle(Theme.secondary)
                }
            }
        }
        .padding(20)
    }
}

private struct DayPicture: View {
    private let stops: [(String, String, String)] = [("9:30", "Layla Bakery", "Breakfast"), ("11:00", "Portobello Market", "Market · 9 min walk"),
                                                     ("1:00", "The Ledbury", "Lunch"), ("3:30", "Daunt Books", "Shopping"), ("7:30", "Dishoom", "Dinner")]
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Eyebrow(text: "Today · Day 2 of 5 · London")
            Text("Notting Hill").font(Theme.serif(22)).foregroundStyle(Theme.label)
            VStack(alignment: .leading, spacing: 9) {
                ForEach(stops.indices, id: \.self) { i in
                    let s = stops[i]
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text(s.0).font(.caption.weight(.medium).monospacedDigit()).foregroundStyle(Theme.secondary).frame(width: 36, alignment: .trailing)
                        Circle().fill(s.0 == "9:30" ? Theme.gold : Theme.cell).overlay(Circle().strokeBorder(Theme.tertiary, lineWidth: 1.5)).frame(width: 9, height: 9)
                        VStack(alignment: .leading, spacing: 0) {
                            Text(s.1).font(Theme.serif(16)).foregroundStyle(Theme.label)
                            Text(s.2).font(.caption2).foregroundStyle(Theme.secondary)
                        }
                    }
                }
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct TogetherPicture: View {
    var body: some View {
        VStack(spacing: 18) {
            HStack(spacing: 10) {
                HStack(spacing: -8) {
                    ForEach(["A", "S", "J"], id: \.self) { letter in
                        Text(letter).font(Theme.serif(15)).foregroundStyle(letter == "A" ? Theme.accentInk : Theme.gold)
                            .frame(width: 34, height: 34)
                            .background(letter == "A" ? Theme.accent : Theme.background, in: Circle())
                            .overlay(Circle().strokeBorder(Theme.cell, lineWidth: 2))
                    }
                }
                Text("You, Sam and Jo").font(.subheadline).foregroundStyle(Theme.secondary)
                Spacer()
                Label("Invite", systemImage: "plus").font(.footnote.weight(.semibold)).foregroundStyle(Theme.link)
            }
            VStack(spacing: 10) {
                HStack {
                    VStack(alignment: .leading, spacing: 2) { Text("LHR").font(Theme.serif(30)); Text("8:05 AM").font(.caption).foregroundStyle(Theme.secondary) }
                    Spacer()
                    Image(systemName: "airplane").foregroundStyle(Theme.gold)
                    Spacer()
                    VStack(alignment: .trailing, spacing: 2) { Text("CDG").font(Theme.serif(30)); Text("10:20 AM").font(.caption).foregroundStyle(Theme.secondary) }
                }
                .foregroundStyle(Theme.label)
                Rectangle().fill(Theme.border).frame(height: 1)
                HStack {
                    VStack(alignment: .leading, spacing: 1) { Text("FLIGHT").font(.caption2.weight(.semibold)).foregroundStyle(Theme.secondary); Text("BA 304").font(.subheadline.weight(.semibold)) }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 1) { Text("DATE").font(.caption2.weight(.semibold)).foregroundStyle(Theme.secondary); Text("Fri, Nov 13").font(.subheadline.weight(.semibold)) }
                }
                .foregroundStyle(Theme.label)
            }
            .padding(16)
            .background(Theme.background, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .padding(20)
    }
}
