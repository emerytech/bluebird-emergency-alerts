package com.ets3d.bluebirdalertsandroid

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.FocusManager
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.SoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

fun Modifier.dismissKeyboardOnTap(
    focusManager: FocusManager,
    keyboardController: SoftwareKeyboardController?,
): Modifier = pointerInput(Unit) {
    awaitEachGesture {
        awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Final)
        val up = waitForUpOrCancellation(pass = PointerEventPass.Final)
        if (up != null) {
            focusManager.clearFocus()
            keyboardController?.hide()
        }
    }
}

@Composable
fun PrimaryButton(
    text: String,
    onClick: () -> Unit,
    enabled: Boolean,
    isLoading: Boolean = false,
    modifier: Modifier = Modifier,
) {
    val scale = animateFloatAsState(
        targetValue = if (enabled) 1f else 0.995f,
        animationSpec = tween(120),
        label = "primary_button_scale",
    )
    Button(
        onClick = onClick,
        enabled = enabled && !isLoading,
        shape = RoundedCornerShape(DSRadius.Button),
        colors = ButtonDefaults.buttonColors(
            containerColor = DSColor.Primary,
            disabledContainerColor = DSColor.Primary.copy(alpha = 0.55f),
            contentColor = Color.White,
            disabledContentColor = Color.White.copy(alpha = 0.9f),
        ),
        modifier = modifier
            .height(52.dp)
            .scale(scale.value),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(DSSpacing.SM)) {
            if (isLoading) {
                CircularProgressIndicator(
                    color = Color.White,
                    strokeWidth = DSSpacing.XS,
                )
            }
            Text(text = text, fontSize = DSTypography.Button, fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
fun DangerButton(
    text: String,
    onClick: () -> Unit,
    enabled: Boolean,
    isLoading: Boolean = false,
    modifier: Modifier = Modifier,
) {
    val scale = animateFloatAsState(
        targetValue = if (enabled) 1f else 0.995f,
        animationSpec = tween(120),
        label = "danger_button_scale",
    )
    Button(
        onClick = onClick,
        enabled = enabled && !isLoading,
        shape = RoundedCornerShape(DSRadius.Button),
        colors = ButtonDefaults.buttonColors(
            containerColor = DSColor.Danger,
            disabledContainerColor = DSColor.Danger.copy(alpha = 0.55f),
            contentColor = Color.White,
            disabledContentColor = Color.White.copy(alpha = 0.9f),
        ),
        modifier = modifier.scale(scale.value),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(DSSpacing.SM)) {
            if (isLoading) {
                CircularProgressIndicator(
                    color = Color.White,
                    strokeWidth = DSSpacing.XS,
                )
            }
            Text(text = text, fontSize = DSTypography.Button, fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
fun TextInput(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    placeholder: String,
    modifier: Modifier = Modifier,
    singleLine: Boolean = false,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        placeholder = { Text(placeholder, color = Color.White.copy(alpha = 0.4f)) },
        singleLine = singleLine,
        shape = RoundedCornerShape(DSRadius.Input),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = DSColor.Primary,
            unfocusedBorderColor = DSColor.InputBorder,
            focusedTextColor = Color.White,
            unfocusedTextColor = Color.White,
            cursorColor = DSColor.Primary,
            focusedContainerColor = DSColor.InputBackground,
            unfocusedContainerColor = DSColor.InputBackground,
            focusedLabelColor = DSColor.Primary,
            unfocusedLabelColor = Color.White.copy(alpha = 0.6f),
        ),
        modifier = modifier.fillMaxWidth(),
    )
}

@Composable
fun CardView(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(DSRadius.Card),
        color = DSColor.Card,
        tonalElevation = DSSpacing.XS,
        shadowElevation = DSSpacing.SM,
    ) {
        Column(modifier = Modifier.padding(DSSpacing.LG)) {
            content()
        }
    }
}

@Composable
fun SectionContainer(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(DSSpacing.MD),
    ) {
        Text(
            text = title,
            color = DSColor.TextPrimary,
            fontSize = DSTypography.Body,
            fontWeight = FontWeight.Bold,
        )
        content()
    }
}

// ── BB Component Library ──────────────────────────────────────────────────────

/**
 * Full-screen gradient background matching the iOS app gradient
 * (DSColor.Background → DSColor.BackgroundDeep, top to bottom).
 */
@Composable
fun BBScreenBackground(
    modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit,
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(
                brush = Brush.verticalGradient(
                    colors = listOf(DSColor.Background, DSColor.BackgroundDeep),
                ),
            ),
        content = content,
    )
}

/**
 * Card surface with shadow and subtle border matching iOS CardView:
 * shadowRadius=8, shadowOpacity=0.06, cornerRadius=DSRadius.Card, padding=DSSpacing.LG.
 */
@Composable
fun BBCard(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(DSRadius.Card)
    Surface(
        shape = shape,
        color = DSColor.Card,
        border = BorderStroke(1.dp, DSColor.CardBorder),
        modifier = modifier.shadow(
            elevation = 8.dp,
            shape = shape,
            clip = false,
            spotColor = Color.Black.copy(alpha = 0.06f),
            ambientColor = Color.Black.copy(alpha = 0.03f),
        ),
    ) {
        Column(
            modifier = Modifier.padding(DSSpacing.LG),
            content = content,
        )
    }
}

/**
 * Primary action button matching iOS PrimaryButton:
 * - 52dp height (≈ iOS minHeight 46pt)
 * - Press-state scale animation to 0.985
 * - Colored drop shadow (primary at 28% opacity)
 * - Disabled state at 45% alpha with no shadow
 */
@Composable
fun BBPrimaryButton(
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    isLoading: Boolean = false,
    modifier: Modifier = Modifier,
) {
    val interactionSource = remember { MutableInteractionSource() }
    val isPressed by interactionSource.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = when {
            isPressed -> 0.985f
            !enabled || isLoading -> 0.97f
            else -> 1f
        },
        animationSpec = tween(durationMillis = 140, easing = FastOutSlowInEasing),
        label = "bb_primary_scale",
    )
    val shape = RoundedCornerShape(DSRadius.Button)
    Button(
        onClick = onClick,
        enabled = enabled && !isLoading,
        interactionSource = interactionSource,
        shape = shape,
        colors = ButtonDefaults.buttonColors(
            containerColor = DSColor.Primary,
            disabledContainerColor = DSColor.Primary.copy(alpha = 0.45f),
            contentColor = Color.White,
            disabledContentColor = Color.White.copy(alpha = 0.7f),
        ),
        elevation = ButtonDefaults.buttonElevation(
            defaultElevation = 0.dp,
            pressedElevation = 0.dp,
            disabledElevation = 0.dp,
        ),
        modifier = modifier
            .height(52.dp)
            .scale(scale)
            .shadow(
                elevation = if (enabled && !isLoading) 8.dp else 0.dp,
                shape = shape,
                clip = false,
                spotColor = DSColor.Primary.copy(alpha = 0.28f),
                ambientColor = DSColor.Primary.copy(alpha = 0.08f),
            ),
    ) {
        if (isLoading) {
            CircularProgressIndicator(
                color = Color.White,
                strokeWidth = 2.dp,
                modifier = Modifier.size(20.dp),
            )
        } else {
            Text(text, fontSize = DSTypography.Button, fontWeight = FontWeight.SemiBold)
        }
    }
}

/**
 * Outlined secondary button for non-destructive secondary actions.
 */
@Composable
fun BBSecondaryButton(
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    modifier: Modifier = Modifier,
) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(DSRadius.Button),
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = DSColor.Primary,
            disabledContentColor = DSColor.Primary.copy(alpha = 0.4f),
        ),
        border = BorderStroke(
            width = 1.5.dp,
            color = if (enabled) DSColor.Primary.copy(alpha = 0.6f) else DSColor.Primary.copy(alpha = 0.2f),
        ),
        modifier = modifier.height(52.dp),
    ) {
        Text(text, fontSize = DSTypography.Button, fontWeight = FontWeight.SemiBold)
    }
}

/**
 * Text field matching iOS TextInput:
 * - Dark slate inputBackground (same in light and dark mode)
 * - Visible border stroke (inputBorder token, primary when focused)
 * - White text on dark background
 * - Correct input corner radius
 */
@Composable
fun BBTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    placeholder: String = "",
    modifier: Modifier = Modifier,
    singleLine: Boolean = false,
    minLines: Int = 1,
    maxLines: Int = if (singleLine) 1 else Int.MAX_VALUE,
    accentColor: Color = DSColor.Primary,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        placeholder = { Text(placeholder, color = Color.White.copy(alpha = 0.4f)) },
        singleLine = singleLine,
        minLines = minLines,
        maxLines = maxLines,
        shape = RoundedCornerShape(DSRadius.Input),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = accentColor,
            unfocusedBorderColor = DSColor.InputBorder,
            focusedTextColor = Color.White,
            unfocusedTextColor = Color.White,
            cursorColor = accentColor,
            focusedContainerColor = DSColor.InputBackground,
            unfocusedContainerColor = DSColor.InputBackground,
            focusedLabelColor = accentColor,
            unfocusedLabelColor = Color.White.copy(alpha = 0.6f),
        ),
        modifier = modifier.fillMaxWidth(),
    )
}

/**
 * Pill-shaped status badge with a tinted background and border.
 * Mirrors the iOS badge pattern used in alarm/quiet status indicators.
 */
@Composable
fun BBStatusBadge(
    label: String,
    color: Color = DSColor.Success,
    modifier: Modifier = Modifier,
) {
    Surface(
        shape = RoundedCornerShape(50),
        color = color.copy(alpha = 0.15f),
        border = BorderStroke(1.dp, color.copy(alpha = 0.45f)),
        modifier = modifier,
    ) {
        Text(
            text = label,
            color = color,
            fontSize = DSTypography.Caption,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
        )
    }
}

/**
 * Modal surface card for dialogs (quiet period request, confirmations, etc.).
 * Full-width with horizontal margin, elevated shadow, correct card radius.
 */
@Composable
fun BBModalCard(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(DSRadius.Card),
        color = DSColor.Card,
        shadowElevation = 24.dp,
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = DSSpacing.XXL),
    ) {
        Column(
            modifier = Modifier.padding(DSSpacing.XXL),
            verticalArrangement = Arrangement.spacedBy(DSSpacing.LG),
            content = content,
        )
    }
}
