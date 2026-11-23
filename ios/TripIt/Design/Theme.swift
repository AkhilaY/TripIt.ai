import SwiftUI
import UIKit

/// The Travel Edit's look: an editorial, fashion-house feel. White pages and near-black ink by day, black and
/// white by night, Futura for all type (built into iOS), and colour kept for status only (open, needs booking).
/// Light, Dark or the phone's setting is chosen in Profile → Appearance; new installs start in Light.
enum Theme {
    static let accent = dynamic(0x19110B, 0xFFFFFF)  // ink: buttons and active states
    static let accentInk = dynamic(0xFFFFFF, 0x19110B)  // text on the accent
    static let gold = dynamic(0x6F6A66, 0xA8A29C)  // was gold; now the quiet grey for eyebrows and small notes
    static let link = dynamic(0x19110B, 0xFFFFFF)  // text buttons
    static let background = dynamic(0xFFFFFF, 0x000000)
    static let cell = dynamic(0xF6F5F3, 0x161514)  // panels
    static let label = dynamic(0x19110B, 0xF5F2EE)
    static let secondary = dynamic(0x6F6A66, 0xA8A29C)
    static let tertiary = dynamic(0x9A9590, 0x6B6763)
    static let fill = translucent(0x19110B, 0.05, 0xFFFFFF, 0.08)  // quiet buttons and tiles
    static let border = translucent(0x19110B, 0.10, 0xFFFFFF, 0.12)  // hairlines
    static let divider = border
    static let raised = fill
    static let raisedBorder = border
    static let quiet = tertiary

    // Status
    static let danger = dynamic(0x9A3B1E, 0xE08A6E)
    static let ok = dynamic(0x2F6B47, 0x7FB48F)
    static let warn = dynamic(0x9A6A1E, 0xD4A15A)
    static let open = ok
    static let attention = danger

    static let blue = dynamic(0x557189, 0x86A2BA)
    static let green = dynamic(0x2F6B47, 0x7FB48F)
    static let orange = dynamic(0x9A6A1E, 0xD4A15A)
    static let indigo = dynamic(0x5E5A7E, 0x9C97C0)
    static let teal = dynamic(0x5B827C, 0x86AFA8)
    static let gray = dynamic(0x6F6A66, 0xA8A29C)
    static let red = dynamic(0x9A3B1E, 0xE08A6E)
    static let pink = dynamic(0xB2707A, 0xC98C95)

    /// The app's typeface. Futura ships with iOS (Medium and Bold faces), so nothing is bundled.
    static let fontName = "Futura-Medium"
    static let boldFontName = "Futura-Bold"

    /// Display type (titles and headings), now in Futura. The name is kept so existing screens don't change.
    /// Headings stay at the regular weight, the way fashion houses set them; only `.heavy`/`.black` go bold.
    static func serif(_ size: CGFloat, weight: Font.Weight = .semibold) -> Font {
        let name = (weight == .heavy || weight == .black) ? boldFontName : fontName
        return Font.custom(name, size: size * 0.96, relativeTo: size >= 28 ? .largeTitle : size >= 20 ? .title2 : .headline)
    }

    static func uiSerif(_ size: CGFloat, weight: UIFont.Weight = .semibold) -> UIFont {
        UIFont(name: fontName, size: size * 0.96) ?? .systemFont(ofSize: size, weight: weight)
    }

    /// Body type in Futura at the size of a system text style, growing with the phone's text size.
    static func text(_ style: Font.TextStyle) -> Font {
        let size: CGFloat = switch style {
        case .largeTitle: 34
        case .title: 28
        case .title2: 22
        case .title3: 20
        case .headline: 17
        case .body: 17
        case .callout: 16
        case .subheadline: 15
        case .footnote: 13
        case .caption: 12
        case .caption2: 11
        @unknown default: 17
        }
        return Font.custom(fontName, size: size, relativeTo: style)
    }

    static func translucent(_ light: UInt32, _ lightAlpha: CGFloat, _ dark: UInt32, _ darkAlpha: CGFloat) -> Color {
        Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark, alpha: darkAlpha) : UIColor(hex: light, alpha: lightAlpha) })
    }

    static func dynamic(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light) })
    }

    /// Navigation and tab bars in the app's fonts and colours.
    static func applyAppearance() {
        let nav = UINavigationBarAppearance()
        nav.configureWithDefaultBackground()
        nav.backgroundEffect = UIBlurEffect(style: .systemChromeMaterial)
        nav.largeTitleTextAttributes = [.font: uiSerif(34, weight: .regular), .foregroundColor: UIColor(Theme.label)]
        nav.titleTextAttributes = [.font: uiSerif(18, weight: .regular), .foregroundColor: UIColor(Theme.label), .kern: 0.4]
        let scrollEdge = UINavigationBarAppearance()
        scrollEdge.configureWithTransparentBackground()
        scrollEdge.largeTitleTextAttributes = nav.largeTitleTextAttributes
        scrollEdge.titleTextAttributes = nav.titleTextAttributes
        UINavigationBar.appearance().standardAppearance = nav
        UINavigationBar.appearance().compactAppearance = nav
        UINavigationBar.appearance().scrollEdgeAppearance = scrollEdge
        UISegmentedControl.appearance().selectedSegmentTintColor = UIColor(Theme.background)
        if let small = UIFont(name: fontName, size: 13) {
            UISegmentedControl.appearance().setTitleTextAttributes([.font: small], for: .normal)
        }

        // The tab bar: black, with white for the open tab and grey for the rest (like a fashion house's app).
        let tab = UITabBarAppearance()
        tab.configureWithOpaqueBackground()
        tab.backgroundColor = .black
        tab.shadowColor = .clear
        let item = UITabBarItemAppearance()
        let grey = UIColor(white: 0.58, alpha: 1)
        let tabFont = UIFont(name: fontName, size: 11) ?? .systemFont(ofSize: 11, weight: .medium)
        item.normal.iconColor = grey
        item.normal.titleTextAttributes = [.foregroundColor: grey, .font: tabFont, .kern: 0.4]
        item.selected.iconColor = .white
        item.selected.titleTextAttributes = [.foregroundColor: UIColor.white, .font: tabFont, .kern: 0.4]
        tab.stackedLayoutAppearance = item
        tab.inlineLayoutAppearance = item
        tab.compactInlineLayoutAppearance = item
        UITabBar.appearance().standardAppearance = tab
        UITabBar.appearance().scrollEdgeAppearance = tab
    }
}

extension UIColor {
    convenience init(hex: UInt32, alpha: CGFloat = 1) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
    }
}

/// The kinds of place, with the web app's names, colours and icons.
enum Category: String, CaseIterable, Identifiable {
    case food, cafe, dessert, drinks, nightlife, attraction, activity, event, nature, shopping, stay, other
    var id: String { rawValue }

    init(_ raw: String) { self = Category(rawValue: raw) ?? .other }

    var label: String {
        switch self {
        case .food: "Restaurant"
        case .cafe: "Café"
        case .dessert: "Sweets"
        case .drinks: "Bar"
        case .nightlife: "Nightlife"
        case .attraction: "Sight"
        case .activity: "Things to do"
        case .event: "Event"
        case .nature: "Outdoors"
        case .shopping: "Shopping"
        case .stay: "Stay"
        case .other: "Other"
        }
    }

    var symbol: String {
        switch self {
        case .food: "fork.knife"
        case .cafe: "cup.and.saucer.fill"
        case .dessert: "birthday.cake.fill"
        case .drinks: "wineglass.fill"
        case .nightlife: "music.note"
        case .attraction: "building.columns.fill"
        case .activity: "figure.walk"
        case .event: "ticket.fill"
        case .nature: "leaf.fill"
        case .shopping: "bag.fill"
        case .stay: "bed.double.fill"
        case .other: "mappin"
        }
    }

    /// One ink colour for every category icon: the kind of place is told apart by its symbol, not by colour.
    var color: Color { Theme.dynamic(0x19110B, 0xF5F2EE) }

    /// Places that get a menu (and a Reserve button when the restaurant takes bookings online).
    var hasMenu: Bool { [.food, .cafe, .dessert, .drinks, .nightlife].contains(self) }
}

/// Friendlier groups of categories for the filter chips, as on the web.
enum PlaceGroup: String, CaseIterable, Identifiable {
    case food, coffee, drinks, stay, shopping, sights, activities, events, other
    var id: String { rawValue }

    var label: String {
        switch self {
        case .food: "Food"
        case .coffee: "Coffee"
        case .drinks: "Drinks"
        case .stay: "Hotels"
        case .shopping: "Shopping"
        case .sights: "Sights"
        case .activities: "Activities"
        case .events: "Events"
        case .other: "Other"
        }
    }

    var categories: [Category] {
        switch self {
        case .food: [.food, .dessert]
        case .coffee: [.cafe]
        case .drinks: [.drinks, .nightlife]
        case .stay: [.stay]
        case .shopping: [.shopping]
        case .sights: [.attraction, .nature]
        case .activities: [.activity]
        case .events: [.event]
        case .other: [.other]
        }
    }

    static func of(_ category: String) -> PlaceGroup {
        let c = Category(category)
        return allCases.first { $0.categories.contains(c) } ?? .other
    }

    var symbol: String {
        switch self {
        case .events: "ticket.fill"
        case .activities: "figure.walk"
        default: categories[0].symbol
        }
    }

    var color: Color { categories[0].color }
}

/// A restaurant's cuisine, as the server works it out (see backend/app/cuisine.py), with an emoji for its chip.
enum Cuisine: String, CaseIterable, Identifiable {
    case pizza, italian, indian, mexican, japanese, chinese, korean, thai, vietnamese, mediterranean, french, latin,
         spanish, american, seafood, vegan
    var id: String { rawValue }

    var label: String {
        switch self {
        case .pizza: "Pizza"
        case .italian: "Italian"
        case .indian: "Indian"
        case .mexican: "Mexican"
        case .japanese: "Japanese"
        case .chinese: "Chinese"
        case .korean: "Korean"
        case .thai: "Thai"
        case .vietnamese: "Vietnamese"
        case .mediterranean: "Mediterranean"
        case .french: "French"
        case .latin: "Latin"
        case .spanish: "Spanish"
        case .american: "Burgers & BBQ"
        case .seafood: "Seafood"
        case .vegan: "Vegetarian"
        }
    }

    var emoji: String {
        switch self {
        case .pizza: "🍕"
        case .italian: "🍝"
        case .indian: "🍛"
        case .mexican: "🌮"
        case .japanese: "🍣"
        case .chinese: "🥟"
        case .korean: "🥢"
        case .thai: "🍜"
        case .vietnamese: "🥖"
        case .mediterranean: "🥙"
        case .french: "🥐"
        case .latin: "🫓"
        case .spanish: "🥘"
        case .american: "🍔"
        case .seafood: "🦞"
        case .vegan: "🥗"
        }
    }
}
