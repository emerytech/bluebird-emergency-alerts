package com.ets3d.bluebirdalertsandroid

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.SideEffect
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.shape.RoundedCornerShape

// ── Alert-type semantic colors ────────────────────────────────────────────────
object BBAlertColors {
    val Lockdown  = Color(0xFFDC2626)
    val Secure    = Color(0xFF1D4ED8)
    val Evacuate  = Color(0xFF166534)
    val Shelter   = Color(0xFFB45309)
    val Hold      = Color(0xFF8E3BEB)
    val Active    = Color(0xFFDC2626)
    val Clear     = Color(0xFF166534)

    fun forType(type: String): Color = when (type.lowercase().trim()) {
        "lockdown"           -> Lockdown
        "secure"             -> Secure
        "evacuate","evacuation" -> Evacuate
        "shelter"            -> Shelter
        "hold"               -> Hold
        else                 -> Active
    }
}

// ── Status semantic colors ────────────────────────────────────────────────────
object BBStatusColors {
    val Success       = Color(0xFF166534)
    val Warning       = Color(0xFFB45309)
    val Info          = Color(0xFF1D4ED8)
    val Quiet         = Color(0xFF8E3BEB)
    val Offline       = Color(0xFF6B7280)
    val Archived      = Color(0xFF374151)
    val Expired       = Color(0xFF9CA3AF)
    val Trial         = Color(0xFFD97706)
    val ActiveLicense = Color(0xFF166534)
}

// ── Material3 color schemes ───────────────────────────────────────────────────
private val BlueBirdLightColorScheme = lightColorScheme(
    primary          = Color(0xFF1B5FE4),
    onPrimary        = Color.White,
    primaryContainer = Color(0xFFEEF5FF),
    onPrimaryContainer = Color(0xFF10203F),
    secondary        = Color(0xFF1D4ED8),
    onSecondary      = Color.White,
    tertiary         = Color(0xFF8E3BEB),
    onTertiary       = Color.White,
    background       = Color(0xFFEEF5FF),
    onBackground     = Color(0xFF10203F),
    surface          = Color(0xFFFFFFFF),
    onSurface        = Color(0xFF10203F),
    surfaceVariant   = Color(0xFFDCE9FF),
    onSurfaceVariant = Color(0xFF5D7398),
    outline          = Color(0x1A123478),
    error            = Color(0xFFDC2626),
    onError          = Color.White,
)

private val BlueBirdDarkColorScheme = darkColorScheme(
    primary          = Color(0xFF4D8BFF),
    onPrimary        = Color(0xFF10203F),
    primaryContainer = Color(0xFF192132),
    onPrimaryContainer = Color(0xFFE8EEFF),
    secondary        = Color(0xFF4D8BFF),
    onSecondary      = Color(0xFF10203F),
    tertiary         = Color(0xFF8E3BEB),
    onTertiary       = Color.White,
    background       = Color(0xFF0D1424),
    onBackground     = Color(0xFFE8EEFF),
    surface          = Color(0xFF192132),
    onSurface        = Color(0xFFE8EEFF),
    surfaceVariant   = Color(0xFF111B2E),
    onSurfaceVariant = Color(0xFF8FA3C8),
    outline          = Color(0x33FFFFFF),
    error            = Color(0xFFDC2626),
    onError          = Color.White,
)

// ── Typography using design tokens ────────────────────────────────────────────
private val BlueBirdTypography = Typography(
    displayLarge  = TextStyle(fontSize = androidx.compose.ui.unit.TextUnit(28f, androidx.compose.ui.unit.TextUnitType.Sp), fontWeight = FontWeight.Bold),
    headlineMedium = TextStyle(fontSize = androidx.compose.ui.unit.TextUnit(24f, androidx.compose.ui.unit.TextUnitType.Sp), fontWeight = FontWeight.Bold),
    titleLarge    = TextStyle(fontSize = androidx.compose.ui.unit.TextUnit(20f, androidx.compose.ui.unit.TextUnitType.Sp), fontWeight = FontWeight.SemiBold),
    titleMedium   = TextStyle(fontSize = androidx.compose.ui.unit.TextUnit(16f, androidx.compose.ui.unit.TextUnitType.Sp), fontWeight = FontWeight.SemiBold),
    titleSmall    = TextStyle(fontSize = androidx.compose.ui.unit.TextUnit(13f, androidx.compose.ui.unit.TextUnitType.Sp), fontWeight = FontWeight.SemiBold),
    bodyLarge     = TextStyle(fontSize = androidx.compose.ui.unit.TextUnit(16f, androidx.compose.ui.unit.TextUnitType.Sp), fontWeight = FontWeight.Normal),
    bodyMedium    = TextStyle(fontSize = androidx.compose.ui.unit.TextUnit(14f, androidx.compose.ui.unit.TextUnitType.Sp), fontWeight = FontWeight.Normal),
    bodySmall     = TextStyle(fontSize = androidx.compose.ui.unit.TextUnit(12f, androidx.compose.ui.unit.TextUnitType.Sp), fontWeight = FontWeight.Normal),
    labelLarge    = TextStyle(fontSize = androidx.compose.ui.unit.TextUnit(16f, androidx.compose.ui.unit.TextUnitType.Sp), fontWeight = FontWeight.SemiBold),
    labelMedium   = TextStyle(fontSize = androidx.compose.ui.unit.TextUnit(12f, androidx.compose.ui.unit.TextUnitType.Sp), fontWeight = FontWeight.Medium),
    labelSmall    = TextStyle(fontSize = androidx.compose.ui.unit.TextUnit(11f, androidx.compose.ui.unit.TextUnitType.Sp), fontWeight = FontWeight.Medium),
)

// ── Shapes using design tokens ────────────────────────────────────────────────
private val BlueBirdShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small      = RoundedCornerShape(12.dp),
    medium     = RoundedCornerShape(16.dp),
    large      = RoundedCornerShape(20.dp),
    extraLarge = RoundedCornerShape(24.dp),
)

// ── Theme composable ──────────────────────────────────────────────────────────
@Composable
fun BlueBirdTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = if (darkTheme) BlueBirdDarkColorScheme else BlueBirdLightColorScheme
    SideEffect { DSTokenStore.isDarkMode = darkTheme }
    MaterialTheme(
        colorScheme = colorScheme,
        typography  = BlueBirdTypography,
        shapes      = BlueBirdShapes,
        content     = content,
    )
}

// ── Animation durations (ms) ──────────────────────────────────────────────────
object BBAnimation {
    const val Fast   = 150
    const val Normal = 250
    const val Slow   = 350
    const val Hold   = 80
}
