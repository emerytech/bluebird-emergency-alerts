package com.ets3d.bluebirdalertsandroid

import android.content.Context
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject

enum class DSThemeMode {
    SYSTEM,
    LIGHT,
    DARK,
}

data class DesignTokens(
    val primary: Color,
    val danger: Color,
    val background: Color,
    val backgroundDeep: Color,
    val card: Color,
    val inputBackground: Color,
    val textPrimary: Color,
    val textSecondary: Color,
    val textTertiary: Color = Color(0xFF6B7FA8),
    val border: Color,
    val success: Color,
    val warning: Color,
    val info: Color,
    val quietAccent: Color,
    val spacingXS: Int,
    val spacingSM: Int,
    val spacingMD: Int,
    val spacingLG: Int,
    val spacingXL: Int,
    val radiusButton: Int,
    val radiusCard: Int,
    val radiusInput: Int,
    val typeTitle: Int,
    val typeTitleLarge: Int,
    val typeTitleMedium: Int,
    val typeBody: Int,
    val typeButton: Int,
    val typeCaption: Int,
    // Extended tokens — defaults match iOS spec
    val cardBorder: Color = Color(0x1A000000),
    val inputBorder: Color = Color(0x1A123478),
    val spacingXXL: Int = 24,
    val typeSectionTitle: Int = 13,
) {
    companion object {
        val Defaults = DesignTokens(
            primary         = Color(0xFF1B5FE4),
            danger          = Color(0xFFDC2626),
            background      = Color(0xFFEEF5FF),
            backgroundDeep  = Color(0xFFDCE9FF),
            card            = Color(0xFFFFFFFF),
            inputBackground = Color(0xFF39404F),
            textPrimary     = Color(0xFF10203F),
            textSecondary   = Color(0xFF45577A),
            border          = Color(0x1A123478),
            success         = Color(0xFF166534),
            warning         = Color(0xFFB45309),
            info            = Color(0xFF1D4ED8),
            quietAccent     = Color(0xFF8E3BEB),
            spacingXS       = 4,
            spacingSM       = 8,
            spacingMD       = 12,
            spacingLG       = 16,
            spacingXL       = 20,
            spacingXXL      = 24,
            radiusButton    = 16,
            radiusCard      = 20,
            radiusInput     = 14,
            typeTitle       = 24,
            typeTitleLarge  = 28,
            typeTitleMedium = 20,
            typeBody        = 16,
            typeButton      = 16,
            typeCaption     = 12,
            typeSectionTitle = 13,
            cardBorder      = Color(0x1A000000),
            inputBorder     = Color(0x1A123478),
        )

        val DarkDefaults = Defaults.copy(
            primary         = Color(0xFF4D8BFF),
            background      = Color(0xFF0D1424),
            backgroundDeep  = Color(0xFF111B2E),
            card            = Color(0xFF192132),
            textPrimary     = Color(0xFFE8EEFF),
            textSecondary   = Color(0xFF8FA3C8),
            textTertiary    = Color(0xFF7A92BB),
            border          = Color(0x33FFFFFF),
            cardBorder      = Color(0x1AFFFFFF),
            inputBorder     = Color(0x4DFFFFFF),
        )
    }
}

object DSTokenStore {
    @Volatile private var didLoad = false
    @Volatile private var current: DesignTokens = DesignTokens.Defaults

    /** Set this to true before calling loadIfNeeded() for correct dark-mode token resolution. */
    @Volatile var isDarkMode: Boolean = false

    fun loadIfNeeded(context: Context) {
        if (didLoad) return
        synchronized(this) {
            if (didLoad) return
            didLoad = true
            current = runCatching {
                context.assets.open("tokens.json").bufferedReader().use { reader ->
                    parseTokens(JSONObject(reader.readText()))
                }
            }.getOrElse { if (isDarkMode) DesignTokens.DarkDefaults else DesignTokens.Defaults }
        }
    }

    fun tokens(): DesignTokens = current

    fun parseHexColor(raw: String): Color? = parseHexColorInternal(raw)

    private fun parseTokens(root: JSONObject): DesignTokens {
        val base = if (isDarkMode) DesignTokens.DarkDefaults else DesignTokens.Defaults
        return base.copy(
            primary          = pickColor(root, base.primary,          "color.mode.primary",          "theme.colors.primary", "color.button.primary", "colors.button.primary", "colors.primary", "color.primary"),
            danger           = pickColor(root, base.danger,           "color.button.danger",          "colors.button.danger", "colors.danger", "color.danger", "theme.colors.danger"),
            background       = pickColor(root, base.background,       "color.mode.background",        "colors.background.light", "color.background.light", "colors.background", "color.background"),
            backgroundDeep   = pickColor(root, base.backgroundDeep,   "color.mode.background_deep",   "colors.background.dark", "color.background.dark", "colors.background_deep"),
            card             = pickColor(root, base.card,             "color.mode.card",              "color.background.surface", "colors.background.surface", "colors.card", "color.card"),
            inputBackground  = pickColor(root, base.inputBackground,  "colors.input_background",      "color.input_background", "colors.inputBackground", "color.inputBackground"),
            textPrimary      = pickColor(root, base.textPrimary,      "color.mode.text_primary",      "colors.text_primary", "color.text_primary", "colors.textPrimary", "color.textPrimary"),
            textSecondary    = pickColor(root, base.textSecondary,    "color.mode.text_secondary",    "colors.text_secondary", "color.text_secondary", "colors.textSecondary", "color.textSecondary"),
            textTertiary     = pickColor(root, base.textTertiary,     "color.mode.text_tertiary",     "colors.text_tertiary",  "color.text_tertiary"),
            border           = pickColor(root, base.border,           "color.mode.border",            "color.border.default", "colors.border.default", "colors.border", "color.border"),
            success          = pickColor(root, base.success,          "color.status.success",         "colors.status.success"),
            warning          = pickColor(root, base.warning,          "color.status.warning",         "colors.status.warning"),
            info             = pickColor(root, base.info,             "color.status.info",            "colors.status.info"),
            quietAccent      = pickColor(root, base.quietAccent,      "color.status.quiet",           "colors.status.quiet"),
            cardBorder       = pickColor(root, base.cardBorder,       "color.mode.card_border",       "colors.card_border"),
            inputBorder      = pickColor(root, base.inputBorder,      "color.mode.input_border",      "colors.input_border"),
            spacingXS        = pickInt(root, base.spacingXS,          "spacing.xs"),
            spacingSM        = pickInt(root, base.spacingSM,          "spacing.sm"),
            spacingMD        = pickInt(root, base.spacingMD,          "spacing.md"),
            spacingLG        = pickInt(root, base.spacingLG,          "spacing.lg"),
            spacingXL        = pickInt(root, base.spacingXL,          "spacing.xl"),
            spacingXXL       = pickInt(root, base.spacingXXL,         "spacing.xxl"),
            radiusButton     = pickInt(root, base.radiusButton,       "radius.button"),
            radiusCard       = pickInt(root, base.radiusCard,         "radius.card"),
            radiusInput      = pickInt(root, base.radiusInput,        "radius.input"),
            typeTitle        = pickInt(root, base.typeTitle,          "typography.title.size"),
            typeTitleLarge   = pickInt(root, base.typeTitleLarge,     "typography.title_large.size"),
            typeTitleMedium  = pickInt(root, base.typeTitleMedium,    "typography.title_medium.size"),
            typeBody         = pickInt(root, base.typeBody,           "typography.body.size"),
            typeButton       = pickInt(root, base.typeButton,         "typography.button.size"),
            typeCaption      = pickInt(root, base.typeCaption,        "typography.caption.size"),
            typeSectionTitle = pickInt(root, base.typeSectionTitle,   "typography.section_title.size"),
        )
    }

    private fun pickColor(root: JSONObject, fallback: Color, vararg paths: String): Color {
        val variant = if (isDarkMode) "dark" else "light"
        for (path in paths) {
            val raw = lookup(root, path) ?: continue
            val hex = when (raw) {
                is String -> raw
                is JSONObject -> raw.optString(variant)
                    .ifBlank { raw.optString("light") }
                    .ifBlank { raw.optString("default") }
                    .ifBlank { raw.optString("value") }
                else -> ""
            }
            val parsed = parseHexColorInternal(hex)
            if (parsed != null) return parsed
        }
        return fallback
    }

    private fun pickInt(root: JSONObject, fallback: Int, vararg paths: String): Int {
        for (path in paths) {
            val raw = lookup(root, path) ?: continue
            when (raw) {
                is Number -> return raw.toInt()
                is String -> raw.toDoubleOrNull()?.toInt()?.let { return it }
                is JSONObject -> {
                    if (raw.has("value")) {
                        val value = raw.get("value")
                        if (value is Number) return value.toInt()
                        if (value is String) value.toDoubleOrNull()?.toInt()?.let { return it }
                    }
                }
            }
        }
        return fallback
    }

    private fun lookup(root: JSONObject, path: String): Any? {
        var current: Any = root
        for (segment in path.split(".")) {
            val obj = current as? JSONObject ?: return null
            val candidates = listOf(segment, segment.replace("-", "_"), segment.replace("_", "-"))
            val key = candidates.firstOrNull { obj.has(it) } ?: return null
            current = obj.get(key)
        }
        return current
    }

    private fun parseHexColorInternal(raw: String): Color? {
        val cleaned = raw.trim().removePrefix("#")
        if (cleaned.isEmpty()) return null
        val expanded = when (cleaned.length) {
            3 -> cleaned.flatMap { listOf(it, it) }.joinToString("")
            6, 8 -> cleaned
            else -> return null
        }
        val numeric = expanded.toLongOrNull(16) ?: return null
        return when (expanded.length) {
            6 -> Color(0xFF000000 or numeric)
            8 -> {
                val a = (numeric shr 24) and 0xFF
                val rgb = numeric and 0x00FFFFFF
                Color((a shl 24) or rgb)
            }
            else -> null
        }
    }
}

object DSColor {
    val Primary:         Color get() = DSTokenStore.tokens().primary
    val Accent:          Color get() = Primary
    val Danger:          Color get() = DSTokenStore.tokens().danger
    val Background:      Color get() = DSTokenStore.tokens().background
    val BackgroundDeep:  Color get() = DSTokenStore.tokens().backgroundDeep
    val Card:            Color get() = DSTokenStore.tokens().card
    val CardBorder:      Color get() = DSTokenStore.tokens().cardBorder
    val InputBackground: Color get() = DSTokenStore.tokens().inputBackground
    val InputBorder:     Color get() = DSTokenStore.tokens().inputBorder
    val TextPrimary:     Color get() = DSTokenStore.tokens().textPrimary
    val TextSecondary:   Color get() = DSTokenStore.tokens().textSecondary
    val TextTertiary:    Color get() = DSTokenStore.tokens().textTertiary
    val Border:          Color get() = DSTokenStore.tokens().border
    val Success:         Color get() = DSTokenStore.tokens().success
    val Warning:         Color get() = DSTokenStore.tokens().warning
    val Info:            Color get() = DSTokenStore.tokens().info
    val QuietAccent:     Color get() = DSTokenStore.tokens().quietAccent
}

object DSSpacing {
    val XS  get() = DSTokenStore.tokens().spacingXS.dp
    val SM  get() = DSTokenStore.tokens().spacingSM.dp
    val MD  get() = DSTokenStore.tokens().spacingMD.dp
    val LG  get() = DSTokenStore.tokens().spacingLG.dp
    val XL  get() = DSTokenStore.tokens().spacingXL.dp
    val XXL get() = DSTokenStore.tokens().spacingXXL.dp
}

object DSRadius {
    val Button get() = DSTokenStore.tokens().radiusButton.dp
    val Card   get() = DSTokenStore.tokens().radiusCard.dp
    val Input  get() = DSTokenStore.tokens().radiusInput.dp
}

object DSTypography {
    val TitleLarge   get() = DSTokenStore.tokens().typeTitleLarge.sp
    val TitleMedium  get() = DSTokenStore.tokens().typeTitleMedium.sp
    val Title        get() = DSTokenStore.tokens().typeTitle.sp
    val Body         get() = DSTokenStore.tokens().typeBody.sp
    val Button       get() = DSTokenStore.tokens().typeButton.sp
    val Caption      get() = DSTokenStore.tokens().typeCaption.sp
    val SectionTitle get() = DSTokenStore.tokens().typeSectionTitle.sp
}
