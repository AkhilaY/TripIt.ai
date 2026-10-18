import SwiftUI

enum PlaceCategory: String, CaseIterable, Codable, Identifiable {
    case food, cafe, dessert, drinks, nightlife, attraction, activity, nature, shopping, stay, other

    var id: String { rawValue }

    var label: String {
        switch self {
        case .food: return "Food"
        case .cafe: return "Cafés"
        case .dessert: return "Sweets"
        case .drinks: return "Drinks"
        case .nightlife: return "Nightlife"
        case .attraction: return "Sights"
        case .activity: return "Things to do"
        case .nature: return "Outdoors"
        case .shopping: return "Shopping"
        case .stay: return "Stay"
        case .other: return "Other"
        }
    }

    var symbol: String {
        switch self {
        case .food: return "fork.knife"
        case .cafe: return "cup.and.saucer.fill"
        case .dessert: return "birthday.cake.fill"
        case .drinks: return "wineglass.fill"
        case .nightlife: return "music.note"
        case .attraction: return "building.columns.fill"
        case .activity: return "figure.walk"
        case .nature: return "leaf.fill"
        case .shopping: return "bag.fill"
        case .stay: return "bed.double.fill"
        case .other: return "mappin"
        }
    }

    var color: Color {
        switch self {
        case .food: return .orange
        case .cafe: return .brown
        case .dessert: return .pink
        case .drinks: return .purple
        case .nightlife: return .indigo
        case .attraction: return .blue
        case .activity: return .teal
        case .nature: return .green
        case .shopping: return .mint
        case .stay: return .cyan
        case .other: return .gray
        }
    }

    /// Default slot when planning a day.
    var preferredTimeOfDay: TimeOfDay {
        switch self {
        case .cafe: return .morning
        case .food: return .lunch
        case .dessert, .shopping, .attraction, .activity, .nature, .other: return .afternoon
        case .drinks, .nightlife: return .evening
        case .stay: return .evening
        }
    }
}

enum TimeOfDay: String, CaseIterable, Codable, Identifiable {
    case morning, lunch, afternoon, dinner, evening

    var id: String { rawValue }
    var label: String { rawValue.capitalized }
    var sortIndex: Int { Self.allCases.firstIndex(of: self) ?? 0 }

    var symbol: String {
        switch self {
        case .morning: return "sunrise.fill"
        case .lunch: return "sun.max.fill"
        case .afternoon: return "sun.haze.fill"
        case .dinner: return "sunset.fill"
        case .evening: return "moon.stars.fill"
        }
    }
}
