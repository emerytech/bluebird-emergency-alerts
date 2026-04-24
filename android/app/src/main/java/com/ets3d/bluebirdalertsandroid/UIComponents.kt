package com.ets3d.bluebirdalertsandroid

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.font.FontWeight

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
        label = { Text(label, color = DSColor.TextSecondary) },
        placeholder = { Text(placeholder, color = DSColor.TextSecondary.copy(alpha = 0.8f)) },
        singleLine = singleLine,
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = DSColor.Primary,
            unfocusedBorderColor = DSColor.Border,
            focusedTextColor = DSColor.TextPrimary,
            unfocusedTextColor = DSColor.TextPrimary,
            cursorColor = DSColor.Primary,
            focusedContainerColor = DSColor.Card,
            unfocusedContainerColor = DSColor.Card,
        ),
        modifier = modifier,
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
