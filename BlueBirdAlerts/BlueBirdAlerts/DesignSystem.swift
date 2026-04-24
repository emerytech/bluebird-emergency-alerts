import SwiftUI

enum DSColor {
    static let primary = Color(red: 0.11, green: 0.37, blue: 0.89)
    static let danger = Color(red: 0.86, green: 0.26, blue: 0.22)
    static let background = Color(red: 0.93, green: 0.96, blue: 1.0)
    static let backgroundDeep = Color(red: 0.86, green: 0.91, blue: 1.0)
    static let card = Color.white
    static let inputBackground = Color(red: 0.22, green: 0.25, blue: 0.31)
    static let textPrimary = Color(red: 0.06, green: 0.13, blue: 0.25)
    static let textSecondary = Color(red: 0.27, green: 0.34, blue: 0.48)
    static let border = Color.white.opacity(0.12)
}

enum DSSpacing {
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 12
    static let lg: CGFloat = 16
    static let xl: CGFloat = 20
}

enum DSRadius {
    static let button: CGFloat = 12
    static let card: CGFloat = 22
    static let input: CGFloat = 12
}

enum DSTypography {
    static let title = Font.system(size: 24, weight: .bold)
    static let body = Font.system(size: 16, weight: .regular)
    static let button = Font.system(size: 16, weight: .semibold)
}
