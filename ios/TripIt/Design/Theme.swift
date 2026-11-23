import SwiftUI
import UIKit

/// The Travel Edit's look, from the "Light redesign" design: white pages and near-black ink by day (black and white by
/// night), Jost for all type (bundled, Futura-like, used at its regular and light weights the way fashion houses
/// set type), photos instead of icons where there is one, and colour kept for status only (open, needs booking).
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
    static let border = dynamic(0xE6E3DF, 0x2A2826)  // hairlines between rows and around outlined pieces
    static let chipBorder = dynamic(0xD9D5D0, 0x3A3734)
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

    /// The app's typeface: Jost (SIL Open Font License, in Shared/Fonts), the face the design is set in.
    static let fontName = "Jost-Regular"
    static let lightFontName = "Jost-Light"
    static let mediumFontName = "Jost-Medium"

    private static func faceName(_ weight: Font.Weight) -> String {
        switch weight {
        case .ultraLight, .thin, .light: lightFontName
        case .medium, .bold, .heavy, .black: mediumFontName
        default: fontName
        }
    }

    /// Display type (titles and headings). Headings are set at the regular weight, as in the design; `.light` gives
    /// the thin wordmark weight and `.medium` or heavier the button weight. (The name is from the earlier serif look.)
    static func serif(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        Font.custom(faceName(weight), size: size, relativeTo: size >= 28 ? .largeTitle : size >= 20 ? .title2 : .headline)
    }

    static func uiSerif(_ size: CGFloat, weight: UIFont.Weight = .regular) -> UIFont {
        let name = weight.rawValue <= UIFont.Weight.light.rawValue ? lightFontName
            : weight.rawValue >= UIFont.Weight.medium.rawValue ? mediumFontName : fontName
        return UIFont(name: name, size: size) ?? .systemFont(ofSize: size, weight: weight)
    }

    /// Body type at the size of a system text style, growing with the phone's text size. Regular unless asked;
    /// `.medium` is for buttons and the open tab.
    static func text(_ style: Font.TextStyle, weight: Font.Weight = .regular) -> Font {
        let size: CGFloat = switch style {
        case .largeTitle: 34
        case .title: 28
        case .title2: 22
        case .title3: 20
        case .headline: 18
        case .body: 17
        case .callout: 16
        case .subheadline: 15
        case .footnote: 14
        case .caption: 13
        case .caption2: 11
        @unknown default: 17
        }
        return Font.custom(faceName(weight), size: size, relativeTo: style)
    }

    static func translucent(_ light: UInt32, _ lightAlpha: CGFloat, _ dark: UInt32, _ darkAlpha: CGFloat) -> Color {
        Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark, alpha: darkAlpha) : UIColor(hex: light, alpha: lightAlpha) })
    }

    static func dynamic(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light) })
    }

    /// Navigation bars, bar buttons and segmented controls in the app's type and colours. (The tab bar is the app's
    /// own; see MainTabs.)
    static func applyAppearance() {
        let nav = UINavigationBarAppearance()
        nav.configureWithDefaultBackground()
        nav.backgroundEffect = UIBlurEffect(style: .systemChromeMaterial)
        nav.largeTitleTextAttributes = [.font: uiSerif(34), .foregroundColor: UIColor(Theme.label)]
        nav.titleTextAttributes = [.font: uiSerif(18), .foregroundColor: UIColor(Theme.label), .kern: 0.3]
        let button = UIBarButtonItemAppearance()
        button.normal.titleTextAttributes = [.font: uiSerif(17)]
        nav.buttonAppearance = button
        nav.doneButtonAppearance = button
        let scrollEdge = UINavigationBarAppearance()
        scrollEdge.configureWithTransparentBackground()
        scrollEdge.largeTitleTextAttributes = nav.largeTitleTextAttributes
        scrollEdge.titleTextAttributes = nav.titleTextAttributes
        scrollEdge.buttonAppearance = button
        scrollEdge.doneButtonAppearance = button
        UINavigationBar.appearance().standardAppearance = nav
        UINavigationBar.appearance().compactAppearance = nav
        UINavigationBar.appearance().scrollEdgeAppearance = scrollEdge
        UISegmentedControl.appearance().selectedSegmentTintColor = UIColor(Theme.background)
        if let small = UIFont(name: fontName, size: 14) {
            UISegmentedControl.appearance().setTitleTextAttributes([.font: small], for: .normal)
        }
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

    /// A muted swatch for the kind of place, shown as a small dot on its filter chip and in place rows.
    var swatch: Color {
        switch self {
        case .food: Theme.dynamic(0x9A4A2E, 0xD58E70)  // rust
        case .coffee: Theme.dynamic(0x6B4E37, 0xC2A184)  // umber
        case .drinks: Theme.dynamic(0x6E2E3F, 0xCC8C9C)  // burgundy
        case .stay: Theme.dynamic(0x3F5566, 0x93AABC)  // slate
        case .shopping: Theme.dynamic(0x86641A, 0xD4B062)  // ochre
        case .sights: Theme.dynamic(0x4F6B4A, 0x98B391)  // sage
        case .activities: Theme.dynamic(0x2F5F5B, 0x7FB0AA)  // teal
        case .events: Theme.dynamic(0x5B3B66, 0xB597C3)  // plum
        case .other: Theme.tertiary
        }
    }
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
