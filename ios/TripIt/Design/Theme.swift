import SwiftUI
import UIKit

/// The Travel Edit's look: warm ivory by day, deep espresso at night, one serif (Newsreader) for display type,
/// one-colour icons, and colour only for status: green means open, coral means it needs your attention.
/// Same palette as the web app (backend/app/static/styles.css).
enum Theme {
    static let accent = dynamic(0x84652F, 0xC9A46A)  // gold: the main button and active states
    static let accentInk = dynamic(0xFFFDF9, 0x13100D)  // text on the accent
    static let gold = accent
    static let link = accent
    static let background = dynamic(0xF6F1E9, 0x13100D)
    static let cell = dynamic(0xFFFDF9, 0x1E1A16)  // cards
    static let border = dynamic(0xE6DDCF, 0x2E2822)
    static let raised = dynamic(0xEFE8DC, 0x2A241E)  // quiet buttons and tiles
    static let raisedBorder = dynamic(0xDDD3C3, 0x3A322A)
    static let divider = dynamic(0xE6DDCF, 0x2A241E)
    static let label = dynamic(0x1C1813, 0xF2EBE0)
    static let secondary = dynamic(0x6E6458, 0xA89D8F)
    static let tertiary = dynamic(0x776C60, 0x958A7E)
    static let quiet = dynamic(0xA39889, 0x6B6157)
    static let fill = raised

    // Status
    static let open = dynamic(0x4A6B3E, 0xA3BE8C)
    static let attention = dynamic(0xA14F37, 0xE59C7F)
    static let ok = open
    static let warn = attention
    static let danger = attention

    // Older names: icons are one colour now, so these are the quiet ink, except the status ones.
    static let blue = secondary
    static let indigo = secondary
    static let teal = secondary
    static let gray = secondary
    static let pink = secondary
    static let green = open
    static let orange = attention
    static let red = attention

    /// Display type: Newsreader (bundled), falling back to the system serif.
    static func serif(_ size: CGFloat, weight: Font.Weight = .medium) -> Font {
        hasNewsreader ? Font.custom("Newsreader", size: size).weight(weight) : Font.system(size: size, weight: weight, design: .serif)
    }

    static let hasNewsreader = UIFont(name: "Newsreader", size: 12) != nil
        || UIFont.fontNames(forFamilyName: "Newsreader").isEmpty == false

    static func uiSerif(_ size: CGFloat, weight: UIFont.Weight = .medium) -> UIFont {
        if hasNewsreader {
            let descriptor = UIFontDescriptor(fontAttributes: [.family: "Newsreader", .traits: [UIFontDescriptor.TraitKey.weight: weight]])
            return UIFont(descriptor: descriptor, size: size)
        }
        let serif = UIFontDescriptor.preferredFontDescriptor(withTextStyle: .body).withDesign(.serif)!
        return UIFont(descriptor: serif.addingAttributes([.traits: [UIFontDescriptor.TraitKey.weight: weight]]), size: size)
    }

    static func dynamic(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light) })
    }

    /// Navigation and tab bars in the app's fonts and colours.
    static func applyAppearance() {
        let nav = UINavigationBarAppearance()
        nav.configureWithDefaultBackground()
        nav.backgroundEffect = UIBlurEffect(style: .systemChromeMaterial)
        nav.largeTitleTextAttributes = [.font: uiSerif(36), .foregroundColor: UIColor(Theme.label)]
        nav.titleTextAttributes = [.font: uiSerif(19, weight: .semibold), .foregroundColor: UIColor(Theme.label)]
        let scrollEdge = UINavigationBarAppearance()
        scrollEdge.configureWithTransparentBackground()
        scrollEdge.largeTitleTextAttributes = nav.largeTitleTextAttributes
        scrollEdge.titleTextAttributes = nav.titleTextAttributes
        UINavigationBar.appearance().standardAppearance = nav
        UINavigationBar.appearance().compactAppearance = nav
        UINavigationBar.appearance().scrollEdgeAppearance = scrollEdge
        UISegmentedControl.appearance().selectedSegmentTintColor = UIColor(Theme.cell)
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

    /// Icons are one colour; categories are told apart by their symbol.
    var color: Color { Theme.accent }

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
}
