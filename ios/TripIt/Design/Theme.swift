import SwiftUI
import UIKit

/// TripIt's look: sand and espresso, a serif for display type, colour mostly from photos.
/// Same palette as the web app (backend/app/static/styles.css), on standard iOS components.
enum Theme {
    static let accent = dynamic(0x2B2019, 0xEADFCF)  // espresso: buttons and active states
    static let accentInk = dynamic(0xFBF7F1, 0x17110D)  // text on the accent
    static let gold = dynamic(0xA07A50, 0xC9A47A)
    static let link = dynamic(0x84603C, 0xD3B08A)
    static let background = dynamic(0xF1EBE2, 0x15100C)
    static let cell = dynamic(0xFBF8F3, 0x211A14)
    static let label = dynamic(0x2B2019, 0xF0E7DA)
    static let secondary = dynamic(0x7A6A5B, 0xA69684)
    static let tertiary = dynamic(0xB3A493, 0x6A5C4F)
    static let fill = Color(uiColor: UIColor { $0.userInterfaceStyle == .dark
        ? UIColor(red: 240 / 255, green: 231 / 255, blue: 218 / 255, alpha: 0.08)
        : UIColor(red: 43 / 255, green: 32 / 255, blue: 25 / 255, alpha: 0.06) })
    static let danger = dynamic(0xA4473C, 0xD27A6E)
    static let ok = dynamic(0x5D7B53, 0x93B087)
    static let warn = dynamic(0xA9762E, 0xD4A15A)

    static let blue = dynamic(0x557189, 0x86A2BA)
    static let green = dynamic(0x5D7B53, 0x93B087)
    static let orange = dynamic(0xA9762E, 0xD4A15A)
    static let indigo = dynamic(0x5E5A7E, 0x9C97C0)
    static let teal = dynamic(0x5B827C, 0x86AFA8)
    static let gray = dynamic(0x8A7F73, 0xA99D90)
    static let red = dynamic(0xA4473C, 0xD27A6E)
    static let pink = dynamic(0xB2707A, 0xC98C95)

    /// Display type: the system serif (New York), like the web app's Cormorant headings.
    static func serif(_ size: CGFloat, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .serif)
    }

    static func dynamic(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light) })
    }

    /// Navigation and tab bars in the TripIt fonts and colours.
    static func applyAppearance() {
        let serif = UIFontDescriptor.preferredFontDescriptor(withTextStyle: .largeTitle).withDesign(.serif)!
        let large = UIFont(descriptor: serif.withSymbolicTraits(.traitBold) ?? serif, size: 34)
        let small = UIFont(descriptor: serif.withSymbolicTraits(.traitBold) ?? serif, size: 19)
        let nav = UINavigationBarAppearance()
        nav.configureWithDefaultBackground()
        nav.backgroundEffect = UIBlurEffect(style: .systemChromeMaterial)
        nav.largeTitleTextAttributes = [.font: large, .foregroundColor: UIColor(Theme.label)]
        nav.titleTextAttributes = [.font: small, .foregroundColor: UIColor(Theme.label)]
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
        case .food: "Food"
        case .cafe: "Cafés"
        case .dessert: "Sweets"
        case .drinks: "Drinks"
        case .nightlife: "Nightlife"
        case .attraction: "Sights"
        case .activity: "Things to do"
        case .event: "Events"
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

    var color: Color {
        switch self {
        case .food: Theme.dynamic(0xB0644A, 0xC98063)
        case .cafe: Theme.dynamic(0x8A6A4E, 0xAD8C6E)
        case .dessert: Theme.dynamic(0xB2707A, 0xC98C95)
        case .drinks: Theme.dynamic(0x7E5B78, 0xA383A0)
        case .nightlife: Theme.dynamic(0x4F5878, 0x8590B4)
        case .attraction: Theme.dynamic(0x557189, 0x86A2BA)
        case .activity: Theme.dynamic(0x5B827C, 0x86AFA8)
        case .event: Theme.dynamic(0xA4537C, 0xD08AB0)
        case .nature: Theme.dynamic(0x6C875B, 0x97B084)
        case .shopping: Theme.dynamic(0x8E8455, 0xB5AB7C)
        case .stay: Theme.dynamic(0x6A869C, 0x96B0C4)
        case .other: Theme.dynamic(0x8A7F73, 0xA99D90)
        }
    }

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
