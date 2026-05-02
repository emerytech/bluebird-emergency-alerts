import SwiftUI
import Foundation
import UIKit

enum DSThemeMode: String, CaseIterable {
    case system
    case light
    case dark

    var colorScheme: ColorScheme? {
        switch self {
        case .system:
            return nil
        case .light:
            return .light
        case .dark:
            return .dark
        }
    }

    var tokenVariant: String {
        switch self {
        case .dark:
            return "dark"
        case .light:
            return "light"
        case .system:
            return UITraitCollection.current.userInterfaceStyle == .dark ? "dark" : "light"
        }
    }

    var isDark: Bool { tokenVariant == "dark" }
}

enum DSThemePreference {
    static let storageKey = "ds_theme_mode"

    static var mode: DSThemeMode {
        get {
            DSThemeMode(rawValue: UserDefaults.standard.string(forKey: storageKey) ?? "") ?? .system
        }
        set {
            UserDefaults.standard.set(newValue.rawValue, forKey: storageKey)
        }
    }

    static var colorScheme: ColorScheme? {
        mode.colorScheme
    }
}

final class DSTokenStore {
    static let shared = DSTokenStore()

    private var tokens: [String: Any] = [:]
    private var didLoad = false
    private var numberCache: [String: CGFloat] = [:]

    private init() {}

    func loadIfNeeded() {
        guard !didLoad else { return }
        didLoad = true

        if let bundleURL = Bundle.main.url(forResource: "tokens", withExtension: "json"),
           let loaded = loadJSON(url: bundleURL) {
            tokens = loaded
            return
        }

        let candidates = [
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
                .appendingPathComponent("design")
                .appendingPathComponent("tokens.json"),
        ]
        for url in candidates where FileManager.default.fileExists(atPath: url.path) {
            if let loaded = loadJSON(url: url) {
                tokens = loaded
                return
            }
        }
    }

    func color(
        candidates: [String],
        fallback: Color,
    ) -> Color {
        loadIfNeeded()
        for path in candidates {
            if let value = valueForPath(path),
               let hex = asColorHex(value),
               let color = Color(hex: hex) {
                return color
            }
        }
        return fallback
    }

    func number(
        candidates: [String],
        fallback: CGFloat,
    ) -> CGFloat {
        loadIfNeeded()
        let cacheKey = candidates.joined(separator: "|")
        if let cached = numberCache[cacheKey] { return cached }
        for path in candidates {
            if let value = valueForPath(path),
               let n = asCGFloat(value) {
                numberCache[cacheKey] = n
                return n
            }
        }
        numberCache[cacheKey] = fallback
        return fallback
    }

    private func loadJSON(url: URL) -> [String: Any]? {
        guard
            let data = try? Data(contentsOf: url),
            let object = try? JSONSerialization.jsonObject(with: data),
            let dict = object as? [String: Any]
        else {
            return nil
        }
        return dict
    }

    private func valueForPath(_ path: String) -> Any? {
        let parts = path.split(separator: ".").map(String.init)
        guard !parts.isEmpty else { return nil }
        var current: Any = tokens
        for key in parts {
            guard let dict = current as? [String: Any] else { return nil }
            let candidates = [key, key.replacingOccurrences(of: "-", with: "_"), key.replacingOccurrences(of: "_", with: "-")]
            guard let nextKey = candidates.first(where: { dict[$0] != nil }), let next = dict[nextKey] else {
                return nil
            }
            current = next
        }
        return current
    }

    private func asColorHex(_ value: Any) -> String? {
        if let str = value as? String {
            return str
        }
        if let dict = value as? [String: Any] {
            let variant = DSThemePreference.mode.tokenVariant
            if let s = dict[variant] as? String { return s }
            if let s = dict["default"] as? String { return s }
            if let s = dict["value"] as? String { return s }
            if let s = dict["light"] as? String { return s }
        }
        return nil
    }

    private func asCGFloat(_ value: Any) -> CGFloat? {
        if let n = value as? NSNumber {
            return CGFloat(truncating: n)
        }
        if let s = value as? String, let d = Double(s.trimmingCharacters(in: .whitespacesAndNewlines)) {
            return CGFloat(d)
        }
        if let dict = value as? [String: Any] {
            if let n = dict["value"] as? NSNumber {
                return CGFloat(truncating: n)
            }
            if let s = dict["value"] as? String, let d = Double(s.trimmingCharacters(in: .whitespacesAndNewlines)) {
                return CGFloat(d)
            }
        }
        return nil
    }
}

extension Color {
    init?(hex: String) {
        let trimmed = hex.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: "#", with: "")
        let normalized: String
        switch trimmed.count {
        case 3:
            normalized = trimmed.map { "\($0)\($0)" }.joined()
        case 6, 8:
            normalized = trimmed
        default:
            return nil
        }

        var value: UInt64 = 0
        guard Scanner(string: normalized).scanHexInt64(&value) else { return nil }
        if normalized.count == 8 {
            let a = Double((value & 0xFF00_0000) >> 24) / 255.0
            let r = Double((value & 0x00FF_0000) >> 16) / 255.0
            let g = Double((value & 0x0000_FF00) >> 8) / 255.0
            let b = Double(value & 0x0000_00FF) / 255.0
            self = Color(.sRGB, red: r, green: g, blue: b, opacity: a)
        } else {
            let r = Double((value & 0xFF00_00) >> 16) / 255.0
            let g = Double((value & 0x00FF_00) >> 8) / 255.0
            let b = Double(value & 0x0000_FF) / 255.0
            self = Color(.sRGB, red: r, green: g, blue: b, opacity: 1.0)
        }
    }
}

// MARK: - District branding override

enum DSBranding {
    static var overridePrimary: Color? = nil
    static var overrideAccent: Color? = nil

    /// Apply district-level color overrides. Pass hex strings (e.g. "#1B5FE4").
    /// Call this after receiving district config from the backend.
    static func apply(primary: String? = nil, accent: String? = nil) {
        overridePrimary = primary.flatMap { Color(hex: $0) }
        overrideAccent  = accent.flatMap  { Color(hex: $0) }
    }

    static func reset() {
        overridePrimary = nil
        overrideAccent  = nil
    }
}

// MARK: - Adaptive fallback helpers

private extension DSColor {
    static func adaptive(light: UIColor, dark: UIColor) -> Color {
        Color(UIColor { traits in traits.userInterfaceStyle == .dark ? dark : light })
    }
}

// MARK: - Color tokens

enum DSColor {
    static var primary: Color {
        if let override = DSBranding.overridePrimary { return override }
        return DSTokenStore.shared.color(
            candidates: ["theme.colors.primary", "color.mode.primary", "color.button.primary", "colors.button.primary", "colors.primary", "color.primary"],
            fallback: adaptive(
                light: UIColor(red: 0.11, green: 0.37, blue: 0.89, alpha: 1),
                dark:  UIColor(red: 0.30, green: 0.55, blue: 1.00, alpha: 1)
            )
        )
    }

    static var accent: Color {
        DSBranding.overrideAccent ?? primary
    }

    static var danger: Color {
        DSTokenStore.shared.color(
            candidates: ["color.button.danger", "colors.button.danger", "colors.danger", "color.danger", "theme.colors.danger"],
            fallback: adaptive(
                light: UIColor(red: 0.86, green: 0.26, blue: 0.22, alpha: 1),
                dark:  UIColor(red: 1.00, green: 0.40, blue: 0.38, alpha: 1)
            )
        )
    }

    static var background: Color {
        DSTokenStore.shared.color(
            candidates: ["color.mode.background", "colors.background.light", "color.background.light", "colors.background", "color.background"],
            fallback: adaptive(
                light: UIColor(red: 0.93, green: 0.96, blue: 1.00, alpha: 1),
                dark:  UIColor(red: 0.05, green: 0.08, blue: 0.14, alpha: 1)
            )
        )
    }

    static var backgroundDeep: Color {
        DSTokenStore.shared.color(
            candidates: ["color.mode.background_deep", "colors.background.dark", "color.background.dark", "colors.background_deep", "color.background_deep"],
            fallback: adaptive(
                light: UIColor(red: 0.86, green: 0.91, blue: 1.00, alpha: 1),
                dark:  UIColor(red: 0.07, green: 0.11, blue: 0.18, alpha: 1)
            )
        )
    }

    static var card: Color {
        DSTokenStore.shared.color(
            candidates: ["color.mode.card", "color.background.surface", "colors.background.surface", "colors.card", "color.card"],
            fallback: adaptive(
                light: UIColor.white,
                dark:  UIColor(red: 0.10, green: 0.13, blue: 0.20, alpha: 1)
            )
        )
    }

    static var inputBackground: Color {
        DSTokenStore.shared.color(
            candidates: ["colors.input_background", "color.input_background"],
            fallback: Color(red: 0.22, green: 0.25, blue: 0.31)
        )
    }

    static var textPrimary: Color {
        DSTokenStore.shared.color(
            candidates: ["color.mode.text_primary", "colors.text_primary", "color.text_primary", "colors.textPrimary", "color.textPrimary"],
            fallback: adaptive(
                light: UIColor(red: 0.06, green: 0.13, blue: 0.25, alpha: 1),
                dark:  UIColor(red: 0.91, green: 0.93, blue: 1.00, alpha: 1)
            )
        )
    }

    static var textSecondary: Color {
        DSTokenStore.shared.color(
            candidates: ["color.mode.text_secondary", "colors.text_secondary", "color.text_secondary", "colors.textSecondary", "color.textSecondary"],
            fallback: adaptive(
                light: UIColor(red: 0.27, green: 0.34, blue: 0.48, alpha: 1),
                dark:  UIColor(red: 0.56, green: 0.64, blue: 0.78, alpha: 1)
            )
        )
    }

    static var border: Color {
        DSTokenStore.shared.color(
            candidates: ["color.mode.border", "color.border.default", "colors.border.default", "colors.border", "color.border"],
            fallback: adaptive(
                light: UIColor(white: 0.07, alpha: 0.10),
                dark:  UIColor(white: 1.00, alpha: 0.10)
            )
        )
    }

    static var success: Color {
        DSTokenStore.shared.color(
            candidates: ["color.status.success", "colors.status.success"],
            fallback: Color(red: 0.09, green: 0.42, blue: 0.20)
        )
    }

    static var warning: Color {
        DSTokenStore.shared.color(
            candidates: ["color.status.warning", "colors.status.warning"],
            fallback: Color(red: 0.72, green: 0.45, blue: 0.07)
        )
    }

    static var info: Color {
        DSTokenStore.shared.color(
            candidates: ["color.status.info", "colors.status.info"],
            fallback: Color(red: 0.12, green: 0.32, blue: 0.84)
        )
    }

    static var quietAccent: Color {
        DSTokenStore.shared.color(
            candidates: ["color.status.quiet", "colors.status.quiet"],
            fallback: Color(red: 0.56, green: 0.23, blue: 0.92)
        )
    }

    static var offline: Color {
        DSTokenStore.shared.color(
            candidates: ["color.status.offline", "colors.status.offline"],
            fallback: Color(red: 0.42, green: 0.45, blue: 0.50)
        )
    }

    static var trial: Color {
        DSTokenStore.shared.color(
            candidates: ["color.status.trial", "colors.status.trial"],
            fallback: Color(red: 0.85, green: 0.60, blue: 0.02)
        )
    }
}

// MARK: - Alert type colors

enum DSAlertColor {
    static var lockdown: Color { Color(red: 0.86, green: 0.15, blue: 0.15) }
    static var secure: Color   { Color(red: 0.11, green: 0.31, blue: 0.85) }
    static var evacuate: Color { Color(red: 0.09, green: 0.40, blue: 0.20) }
    static var shelter: Color  { Color(red: 0.70, green: 0.33, blue: 0.03) }
    static var hold: Color     { Color(red: 0.56, green: 0.23, blue: 0.92) }
    static var active: Color   { Color(red: 0.86, green: 0.15, blue: 0.15) }
    static var clear: Color    { Color(red: 0.09, green: 0.40, blue: 0.20) }

    static func forType(_ type: String) -> Color {
        switch type.lowercased().trimmingCharacters(in: .whitespaces) {
        case "lockdown":              return lockdown
        case "secure":                return secure
        case "evacuate", "evacuation": return evacuate
        case "shelter":               return shelter
        case "hold":                  return hold
        default:                      return active
        }
    }
}

// MARK: - Animation durations

enum DSAnimation {
    static let fast:   Double = 0.150
    static let normal: Double = 0.250
    static let slow:   Double = 0.350
    static let hold:   Double = 0.080
}

enum DSSpacing {
    static var xs: CGFloat { DSTokenStore.shared.number(candidates: ["spacing.xs"], fallback: 4) }
    static var sm: CGFloat { DSTokenStore.shared.number(candidates: ["spacing.sm"], fallback: 8) }
    static var md: CGFloat { DSTokenStore.shared.number(candidates: ["spacing.md"], fallback: 12) }
    static var lg: CGFloat { DSTokenStore.shared.number(candidates: ["spacing.lg"], fallback: 16) }
    static var xl: CGFloat { DSTokenStore.shared.number(candidates: ["spacing.xl"], fallback: 20) }
}

enum DSRadius {
    static var button: CGFloat { DSTokenStore.shared.number(candidates: ["radius.button"], fallback: 12) }
    static var card: CGFloat { DSTokenStore.shared.number(candidates: ["radius.card"], fallback: 22) }
    static var input: CGFloat { DSTokenStore.shared.number(candidates: ["radius.input"], fallback: 12) }
}

enum DSTypography {
    static var titleLarge: Font {
        Font.system(size: DSTokenStore.shared.number(candidates: ["typography.title_large.size"], fallback: 28), weight: .bold)
    }
    static var titleMedium: Font {
        Font.system(size: DSTokenStore.shared.number(candidates: ["typography.title_medium.size"], fallback: 20), weight: .semibold)
    }
    static var title: Font {
        Font.system(size: DSTokenStore.shared.number(candidates: ["typography.title.size"], fallback: 24), weight: .bold)
    }
    static var body: Font {
        Font.system(size: DSTokenStore.shared.number(candidates: ["typography.body.size"], fallback: 16), weight: .regular)
    }
    static var button: Font {
        Font.system(size: DSTokenStore.shared.number(candidates: ["typography.button.size"], fallback: 16), weight: .semibold)
    }
    static var caption: Font {
        Font.system(size: DSTokenStore.shared.number(candidates: ["typography.caption.size"], fallback: 12), weight: .regular)
    }
}
