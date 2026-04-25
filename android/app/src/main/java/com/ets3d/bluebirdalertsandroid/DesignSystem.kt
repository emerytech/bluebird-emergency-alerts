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
    val typeBody: Int,
    val typeButton: Int,
) {
    companion object {
        val Defaults = DesignTokens(
            primary = Color(0xFF1B5FE4),
            danger = Color(0xFFDC2626),
            background = Color(0xFFEEF5FF),
            backgroundDeep = Color(0xFFDCE9FF),
            card = Color(0xFFFFFFFF),
            inputBackground = Color(0xFF39404F),
            textPrimary = Color(0xFF10203F),
            textSecondary = Color(0xFF5D7398),
            border = Color(0x1A123478),
            success = Color(0xFF166534),
            warning = Color(0xFFB45309),
            info = Color(0xFF1D4ED8),
            quietAccent = Color(0xFF8E3BEB),
            spacingXS = 4,
            spacingSM = 8,
            spacingMD = 12,
            spacingLG = 16,
            spacingXL = 20,
            radiusButton = 12,
            radiusCard = 22,
            radiusInput = 12,
            typeTitle = 24,
            typeBody = 16,
            typeButton = 16,
        )
    }
}

object DSTokenStore {
    @Volatile
    private var didLoad = false

    @Volatile
    private var current: DesignTokens = DesignTokens.Defaults

    fun loadIfNeeded(context: Context) {
        if (didLoad) return
        synchronized(this) {
            if (didLoad) return
            didLoad = true
            current = runCatching {
                context.assets.open("tokens.json").bufferedReader().use { reader ->
                    parseTokens(JSONObject(reader.readText()))
                }
            }.getOrElse { DesignTokens.Defaults }
        }
    }

    fun tokens(): DesignTokens = current

    private fun parseTokens(root: JSONObject): DesignTokens {
        val defaults = DesignTokens.Defaults
        return defaults.copy(
            primary = pickColor(root, defaults.primary, "color.button.primary", "colors.button.primary", "colors.primary", "color.primary", "theme.colors.primary"),
            danger = pickColor(root, defaults.danger, "color.button.danger", "colors.button.danger", "colors.danger", "color.danger", "theme.colors.danger"),
            background = pickColor(root, defaults.background, "colors.background.light", "color.background.light", "colors.background", "color.background"),
            backgroundDeep = pickColor(root, defaults.backgroundDeep, "colors.background.dark", "color.background.dark", "colors.background_deep", "color.background_deep"),
            card = pickColor(root, defaults.card, "color.background.surface", "colors.background.surface", "colors.card", "color.card"),
            inputBackground = pickColor(root, defaults.inputBackground, "colors.input_background", "color.input_background", "colors.inputBackground", "color.inputBackground"),
            textPrimary = pickColor(root, defaults.textPrimary, "colors.text_primary", "color.text_primary", "colors.textPrimary", "color.textPrimary"),
            textSecondary = pickColor(root, defaults.textSecondary, "colors.text_secondary", "color.text_secondary", "colors.textSecondary", "color.textSecondary"),
            border = pickColor(root, defaults.border, "color.border.default", "colors.border.default", "colors.border", "color.border"),
            success = pickColor(root, defaults.success, "color.status.success", "colors.status.success"),
            warning = pickColor(root, defaults.warning, "color.status.warning", "colors.status.warning"),
            info = pickColor(root, defaults.info, "color.status.info", "colors.status.info"),
            quietAccent = pickColor(root, defaults.quietAccent, "color.status.quiet", "colors.status.quiet"),
            spacingXS = pickInt(root, defaults.spacingXS, "spacing.xs"),
            spacingSM = pickInt(root, defaults.spacingSM, "spacing.sm"),
            spacingMD = pickInt(root, defaults.spacingMD, "spacing.md"),
            spacingLG = pickInt(root, defaults.spacingLG, "spacing.lg"),
            spacingXL = pickInt(root, defaults.spacingXL, "spacing.xl"),
            radiusButton = pickInt(root, defaults.radiusButton, "radius.button"),
            radiusCard = pickInt(root, defaults.radiusCard, "radius.card"),
            radiusInput = pickInt(root, defaults.radiusInput, "radius.input"),
            typeTitle = pickInt(root, defaults.typeTitle, "typography.title.size"),
            typeBody = pickInt(root, defaults.typeBody, "typography.body.size"),
            typeButton = pickInt(root, defaults.typeButton, "typography.button.size"),
        )
    }

    private fun pickColor(root: JSONObject, fallback: Color, vararg paths: String): Color {
        for (path in paths) {
            val raw = lookup(root, path) ?: continue
            val hex = when (raw) {
                is String -> raw
                is JSONObject -> raw.optString("light")
                    .ifBlank { raw.optString("default") }
                    .ifBlank { raw.optString("value") }
                else -> ""
            }
            val parsed = parseHexColor(hex)
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
            val candidates = listOf(
                segment,
                segment.replace("-", "_"),
                segment.replace("_", "-"),
            )
            val key = candidates.firstOrNull { obj.has(it) } ?: return null
            current = obj.get(key)
        }
        return current
    }

    private fun parseHexColor(raw: String): Color? {
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
    val Primary: Color get() = DSTokenStore.tokens().primary
    val Danger: Color get() = DSTokenStore.tokens().danger
    val Background: Color get() = DSTokenStore.tokens().background
    val BackgroundDeep: Color get() = DSTokenStore.tokens().backgroundDeep
    val Card: Color get() = DSTokenStore.tokens().card
    val InputBackground: Color get() = DSTokenStore.tokens().inputBackground
    val TextPrimary: Color get() = DSTokenStore.tokens().textPrimary
    val TextSecondary: Color get() = DSTokenStore.tokens().textSecondary
    val Border: Color get() = DSTokenStore.tokens().border
    val Success: Color get() = DSTokenStore.tokens().success
    val Warning: Color get() = DSTokenStore.tokens().warning
    val Info: Color get() = DSTokenStore.tokens().info
    val QuietAccent: Color get() = DSTokenStore.tokens().quietAccent
}

object DSSpacing {
    val XS get() = DSTokenStore.tokens().spacingXS.dp
    val SM get() = DSTokenStore.tokens().spacingSM.dp
    val MD get() = DSTokenStore.tokens().spacingMD.dp
    val LG get() = DSTokenStore.tokens().spacingLG.dp
    val XL get() = DSTokenStore.tokens().spacingXL.dp
}

object DSRadius {
    val Button get() = DSTokenStore.tokens().radiusButton.dp
    val Card get() = DSTokenStore.tokens().radiusCard.dp
    val Input get() = DSTokenStore.tokens().radiusInput.dp
}

object DSTypography {
    val Title get() = DSTokenStore.tokens().typeTitle.sp
    val Body get() = DSTokenStore.tokens().typeBody.sp
    val Button get() = DSTokenStore.tokens().typeButton.sp
}
