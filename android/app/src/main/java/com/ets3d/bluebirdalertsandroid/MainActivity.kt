package com.ets3d.bluebirdalertsandroid

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.*
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.clickable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.zIndex
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.fragment.app.FragmentActivity
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Calendar
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

// ── Brand colours ─────────────────────────────────────────────────────────────
// get() ensures each composable access re-reads DSTokenStore.tokens(), which
// reads the mutableStateOf _isDarkMode and creates a Compose snapshot observation.
private val AppBg       get() = DSColor.Background
private val AppBgDeep   get() = DSColor.BackgroundDeep
private val SurfaceMain get() = DSColor.Card
private val SurfaceSoft get() = DSColor.Background
private val BorderSoft  get() = DSColor.Border
private val BluePrimary get() = DSColor.Primary
private val BlueLight   get() = DSColor.Info
private val BlueDark    get() = DSColor.Primary
private val QuietPurple get() = DSColor.QuietAccent
private val AlarmRed    get() = DSColor.Danger
private val AlarmGreen  get() = DSColor.Success
private val TextPri     get() = DSColor.TextPrimary
private val TextMuted   get() = DSColor.TextSecondary
private val TextOnDark  get() = DSColor.Background

// ── Prefs ──────────────────────────────────────────────────────────────────────
private const val PREFS      = "bluebird_prefs"
private const val KEY_UID    = "user_id"
private const val KEY_SETUP  = "setup_done"
private const val KEY_NAME   = "user_name"
private const val KEY_ROLE   = "user_role"
private const val KEY_LOGIN  = "login_name"
private const val KEY_CAN_DEACTIVATE = "can_deactivate"
private const val KEY_SCHOOL_NAME = "school_name"
private const val KEY_SERVER_URL = "server_url"
private const val KEY_BIOMETRICS_ALLOWED = "biometrics_allowed"
private const val KEY_HAPTIC_ALERTS_ENABLED = "haptic_alerts_enabled"
private const val KEY_FLASHLIGHT_ALERTS_ENABLED = "flashlight_alerts_enabled"
private const val KEY_SCREEN_FLASH_ALERTS_ENABLED = "screen_flash_alerts_enabled"
private const val KEY_DARK_MODE = "dark_mode_enabled"
private const val TAG_ACTIVATION = "BluebirdActivation"
internal const val EXTRA_OPEN_ALARM = "bluebird_open_alarm"
internal const val EXTRA_ALARM_TITLE = "bluebird_alarm_title"
internal const val EXTRA_ALARM_MESSAGE = "bluebird_alarm_message"
internal const val EXTRA_ALERT_TYPE = "bluebird_alert_type"
private const val KEY_SELECTED_TENANT_SLUG = "selected_tenant_slug"
private const val KEY_SELECTED_TENANT_NAME = "selected_tenant_name"
private const val KEY_USER_TITLE = "user_title"
private const val KEY_DEVICE_ID = "bluebird_device_id"

private enum class HoldActivationUiState {
    Idle,
    Pressing,
    Holding,
    NearComplete,
    Triggered,
    Canceled,
}

data class AlarmLaunchEvent(
    val title: String,
    val body: String,
    val tenantSlug: String? = null,
    val isSilentForMe: Boolean = false,
    val type: String = "",
    val receivedAtMillis: Long = System.currentTimeMillis(),
)

object AlarmLaunchCoordinator {
    private val _event = MutableStateFlow<AlarmLaunchEvent?>(null)
    val event: StateFlow<AlarmLaunchEvent?> get() = _event

    fun publish(title: String, body: String, tenantSlug: String? = null, isSilentForMe: Boolean = false, type: String = "") {
        _event.value = AlarmLaunchEvent(
            title = title,
            body = body,
            tenantSlug = tenantSlug?.takeIf { it.isNotBlank() },
            isSilentForMe = isSilentForMe,
            type = type,
        )
    }
}

private class AndroidHoldHaptics(context: Context) {
    private val vibrator: Vibrator? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val manager = context.getSystemService(VibratorManager::class.java)
            manager?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        }

    private val canVibrate: Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.VIBRATE) == PackageManager.PERMISSION_GRANTED

    private fun oneShot(durationMs: Long, amplitude: Int) {
        if (!canVibrate) return
        val v = vibrator ?: return
        if (!v.hasVibrator()) return
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                v.vibrate(VibrationEffect.createOneShot(durationMs, amplitude))
            } else {
                @Suppress("DEPRECATION")
                v.vibrate(durationMs)
            }
        } catch (_: SecurityException) {
            // Ignore haptics when permission/capability isn't available.
        } catch (_: Throwable) {
            // Defensive: never crash activation flow because of haptics.
        }
    }

    fun touchDown() = oneShot(18L, 55)

    fun progressTick(strong: Boolean) = oneShot(
        if (strong) 24L else 14L,
        if (strong) 95 else 55,
    )

    fun cancel() = oneShot(22L, 48)

    fun success() {
        if (!canVibrate) return
        val v = vibrator ?: return
        if (!v.hasVibrator()) return
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                v.vibrate(
                    VibrationEffect.createWaveform(
                        longArrayOf(0L, 26L, 30L, 42L),
                        intArrayOf(0, 110, 0, 190),
                        -1,
                    ),
                )
            } else {
                @Suppress("DEPRECATION")
                v.vibrate(45L)
            }
        } catch (_: SecurityException) {
            // Ignore haptic issues and keep alert flow alive.
        } catch (_: Throwable) {
            // Defensive no-op.
        }
    }
}
internal const val NOTIF_CH   = "bluebird_alerts"
internal const val ALERT_PUSH_NOTIFICATION_ID = 1001
internal const val HELP_REQUEST_PUSH_NOTIFICATION_ID = 1003

private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
private fun isSetupDone(ctx: Context) = prefs(ctx).getBoolean(KEY_SETUP, false)
private fun getUserId(ctx: Context)   = prefs(ctx).getString(KEY_UID, "") ?: ""
private fun getUserName(ctx: Context) = prefs(ctx).getString(KEY_NAME, "") ?: ""
private fun getUserRole(ctx: Context) = prefs(ctx).getString(KEY_ROLE, "") ?: ""
private fun getLoginName(ctx: Context) = prefs(ctx).getString(KEY_LOGIN, "") ?: ""
private fun getSchoolName(ctx: Context) = prefs(ctx).getString(KEY_SCHOOL_NAME, "") ?: ""
private fun canDeactivateAlarm(ctx: Context) = prefs(ctx).getBoolean(KEY_CAN_DEACTIVATE, false)

/** Returns true if the current user's role allows access to district-level settings and features. */
private fun canAccessDistrictSettings(role: String): Boolean =
    role.equals("district_admin", ignoreCase = true) ||
    role.equals("super_admin", ignoreCase = true) ||
    role.equals("platform_super_admin", ignoreCase = true)

/** Returns true if the role can approve/deny quiet period requests. */
private fun isAdminRole(role: String): Boolean =
    role.equals("admin", ignoreCase = true) ||
    role.equals("building_admin", ignoreCase = true) ||
    role.equals("district_admin", ignoreCase = true)
private fun getServerUrl(ctx: Context): String {
    val stored = prefs(ctx).getString(KEY_SERVER_URL, "") ?: ""
    if (stored.isBlank()) return stored
    val normalized = normalizeServerUrl(stored)
    if (normalized != stored) {
        prefs(ctx).edit().putString(KEY_SERVER_URL, normalized).apply()
    }
    return normalized
}
private fun biometricsAllowed(ctx: Context) = prefs(ctx).getBoolean(KEY_BIOMETRICS_ALLOWED, false)
private fun setBiometricsAllowed(ctx: Context, allowed: Boolean) {
    prefs(ctx).edit().putBoolean(KEY_BIOMETRICS_ALLOWED, allowed).apply()
}
private fun hapticAlertsEnabled(ctx: Context) = prefs(ctx).getBoolean(KEY_HAPTIC_ALERTS_ENABLED, true)
private fun setHapticAlertsEnabled(ctx: Context, enabled: Boolean) {
    prefs(ctx).edit().putBoolean(KEY_HAPTIC_ALERTS_ENABLED, enabled).apply()
}
private fun flashlightAlertsEnabled(ctx: Context) = prefs(ctx).getBoolean(KEY_FLASHLIGHT_ALERTS_ENABLED, true)
private fun setFlashlightAlertsEnabled(ctx: Context, enabled: Boolean) {
    prefs(ctx).edit().putBoolean(KEY_FLASHLIGHT_ALERTS_ENABLED, enabled).apply()
}
private fun screenFlashAlertsEnabled(ctx: Context) = prefs(ctx).getBoolean(KEY_SCREEN_FLASH_ALERTS_ENABLED, true)
private fun setScreenFlashAlertsEnabled(ctx: Context, enabled: Boolean) {
    prefs(ctx).edit().putBoolean(KEY_SCREEN_FLASH_ALERTS_ENABLED, enabled).apply()
}
private fun loadDarkModeSetting(ctx: Context) = prefs(ctx).getBoolean(KEY_DARK_MODE, false)
private fun saveDarkModeSetting(ctx: Context, enabled: Boolean) {
    prefs(ctx).edit().putBoolean(KEY_DARK_MODE, enabled).apply()
}
private fun getSelectedTenantSlug(ctx: Context) = prefs(ctx).getString(KEY_SELECTED_TENANT_SLUG, "") ?: ""
private fun getSelectedTenantName(ctx: Context) = prefs(ctx).getString(KEY_SELECTED_TENANT_NAME, "") ?: ""
private fun getUserTitle(ctx: Context) = prefs(ctx).getString(KEY_USER_TITLE, "") ?: ""
private fun getOrCreateDeviceId(ctx: Context): String {
    val stored = prefs(ctx).getString(KEY_DEVICE_ID, null)
    if (!stored.isNullOrBlank()) return stored
    val generated = java.util.UUID.randomUUID().toString()
    prefs(ctx).edit().putString(KEY_DEVICE_ID, generated).apply()
    return generated
}

private fun snakeToTitle(s: String): String =
    s.split('_', '-').joinToString(" ") { it.replaceFirstChar { c -> c.uppercase() } }

private fun Context.findActivity(): FragmentActivity? = when (this) {
    is FragmentActivity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

private fun FragmentActivity.applyAlarmWindowFlags(active: Boolean) {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
        setShowWhenLocked(active)
        setTurnScreenOn(active)
    } else {
        @Suppress("DEPRECATION")
        if (active) {
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON,
            )
        } else {
            window.clearFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON,
            )
        }
    }
    if (active) {
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    } else {
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
}

private fun extractSchoolSlug(value: String): String {
    val trimmed = value.trim().removeSuffix("/")
    if (trimmed.isBlank()) return ""
    if (!trimmed.contains("://")) {
        val parts = trimmed.split("/").filter { it.isNotBlank() }
        return if (parts.size == 1 && !trimmed.contains(".")) parts.first().lowercase() else parts.lastOrNull()?.lowercase().orEmpty()
    }
    return runCatching {
        val uri = java.net.URI(trimmed)
        uri.path.trim('/').split("/").firstOrNull().orEmpty().lowercase()
    }.getOrDefault("")
}
private fun schoolBaseUrl(slug: String): String {
    val normalized = slug.trim().trim('/').lowercase()
    if (normalized.isBlank()) return BuildConfig.BACKEND_BASE_URL
    return "${BuildConfig.BACKEND_BASE_URL}/$normalized"
}
private fun normalizeServerUrl(value: String): String {
    val trimmed = value.trim().removeSuffix("/")
    if (trimmed.isBlank()) return BuildConfig.BACKEND_BASE_URL
    if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
        return runCatching {
            val uri = java.net.URI(trimmed)
            val path = uri.path?.trim('/').orEmpty()
            if (path.isBlank()) {
                "$trimmed/default"
            } else {
                trimmed
            }
        }.getOrDefault(trimmed)
    }
    if (!trimmed.contains(".") && !trimmed.contains("/")) return schoolBaseUrl(trimmed)
    if (trimmed.startsWith("/")) return normalizeServerUrl(BuildConfig.BACKEND_BASE_URL + trimmed)
    return normalizeServerUrl("https://$trimmed")
}
private fun currentDeviceName(): String {
    val manufacturer = Build.MANUFACTURER?.trim().orEmpty()
    val model = Build.MODEL?.trim().orEmpty()
    return when {
        manufacturer.isBlank() && model.isBlank() -> "Android device"
        model.startsWith(manufacturer, ignoreCase = true) -> model
        manufacturer.isBlank() -> model
        model.isBlank() -> manufacturer
        else -> "$manufacturer $model"
    }
}

private val bannerTimeFormatter: DateTimeFormatter = DateTimeFormatter.ofPattern("MMM d, h:mm a")
private fun formatIsoForBanner(value: String?): String? {
    val cleaned = value?.trim()?.takeIf { it.isNotEmpty() && !it.equals("null", ignoreCase = true) } ?: return null
    return runCatching {
        bannerTimeFormatter.format(Instant.parse(cleaned).atZone(ZoneId.systemDefault()))
    }.getOrNull()
}

internal fun ensureNotificationChannel(context: Context) {
    val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    val existing = manager.getNotificationChannel(NOTIF_CH)
    val soundUri = Uri.parse("android.resource://${context.packageName}/${R.raw.bluebird_alarm}")
    val needsRecreate = existing == null ||
        existing.importance < NotificationManager.IMPORTANCE_HIGH ||
        existing.sound?.toString() != soundUri.toString()
    if (needsRecreate && existing != null) {
        manager.deleteNotificationChannel(NOTIF_CH)
    }
    if (needsRecreate) {
        val channel = NotificationChannel(
            NOTIF_CH,
            "BlueBird Alerts",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Emergency school alerts"
            enableVibration(true)
            vibrationPattern = longArrayOf(0L, 900L, 350L, 900L, 350L, 1200L)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            setSound(
                soundUri,
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build(),
            )
        }
        manager.createNotificationChannel(channel)
    }
}

internal data class AuthUser(
    val userId: Int,
    val name: String,
    val role: String,
    val loginName: String,
    val mustChangePassword: Boolean,
    val canDeactivateAlarm: Boolean,
)

internal data class SchoolOption(
    val name: String,
    val slug: String,
    val path: String,
)

private enum class SchoolLoadState {
    Loading,
    Loaded,
    Empty,
    Failed,
}

data class BroadcastUpdate(
    val updateId: Int,
    val createdAt: String,
    val adminUserId: Int? = null,
    val adminLabel: String? = null,
    val message: String,
)

data class AdminInboxMessage(
    val messageId: Int,
    val createdAt: String,
    val senderUserId: Int? = null,
    val senderLabel: String? = null,
    val message: String,
    val status: String,
    val responseMessage: String? = null,
    val responseCreatedAt: String? = null,
    val responseByLabel: String? = null,
)

data class InboxRecipient(
    val userId: Int,
    val label: String,
)

data class TeamAssistActionRecipient(
    val userId: Int,
    val label: String,
)

data class QuietPeriodMobileStatus(
    val requestId: Int? = null,
    val status: String? = null,
    val reason: String? = null,
    val requestedAt: String? = null,
    val approvedAt: String? = null,
    val approvedByLabel: String? = null,
    val expiresAt: String? = null,
    val scheduledStartAt: String? = null,
    val scheduledEndAt: String? = null,
)

data class AdminQuietPeriodRequest(
    val requestId: Int,
    val userId: Int,
    val userName: String?,
    val userRole: String?,
    val reason: String?,
    val status: String,
    val requestedAt: String,
    val approvedAt: String? = null,
    val approvedByLabel: String? = null,
    val expiresAt: String? = null,
    val scheduledStartAt: String? = null,
    val scheduledEndAt: String? = null,
)

data class AdminQuietModalEvent(
    val id: String,
    val requestId: Int,
    val userName: String,
    val userRole: String,
    val reason: String?,
    val requestedAt: String?,
    val tenantSlug: String?,
)

data class DistrictQuietPeriodItem(
    val requestId: Int,
    val userId: Int,
    val userName: String?,
    val userRole: String?,
    val reason: String?,
    val status: String,
    val requestedAt: String,
    val approvedAt: String? = null,
    val approvedByLabel: String? = null,
    val deniedAt: String? = null,
    val cancelledAt: String? = null,
    val expiresAt: String? = null,
    val scheduledStartAt: String? = null,
    val scheduledEndAt: String? = null,
    val countdownTargetAt: String? = null,
    val countdownMode: String? = null,
    val tenantSlug: String,
    val tenantName: String,
)

enum class AdminEventType { QUIET_PENDING, QUIET_APPROVED, ADMIN_MESSAGE }

data class AdminEvent(
    val id: String,
    val type: AdminEventType,
    val title: String,
    val body: String,
)

private data class SafetyAction(
    val key: String,
    val title: String,
    val symbol: String,
    val color: Color,
    val message: String,
)

private fun buildSafetyActions(featureLabels: Map<String, String>): List<SafetyAction> = listOf(
    SafetyAction(
        key = AppLabels.KEY_SECURE,
        title = AppLabels.labelForFeatureKey(AppLabels.KEY_SECURE, featureLabels).uppercase(),
        symbol = "\uD83D\uDD10",
        color = DSColor.Info,
        message = "SECURE emergency initiated. Follow school secure procedures.",
    ),
    SafetyAction(
        key = AppLabels.KEY_LOCKDOWN,
        title = AppLabels.labelForFeatureKey(AppLabels.KEY_LOCKDOWN, featureLabels).uppercase(),
        symbol = "\uD83D\uDD12",
        color = DSColor.Danger,
        message = "LOCKDOWN emergency initiated. Follow lockdown procedures immediately.",
    ),
    SafetyAction(
        key = AppLabels.KEY_EVACUATION,
        title = AppLabels.labelForFeatureKey(AppLabels.KEY_EVACUATION, featureLabels).uppercase(),
        symbol = "\uD83D\uDEB6",
        color = DSColor.Success,
        message = "EVACUATE emergency initiated. Move to evacuation locations now.",
    ),
    SafetyAction(
        key = AppLabels.KEY_SHELTER,
        title = AppLabels.labelForFeatureKey(AppLabels.KEY_SHELTER, featureLabels).uppercase(),
        symbol = "\uD83C\uDFE0",
        color = DSColor.Warning,
        message = "SHELTER emergency initiated. Move into shelter protocol.",
    ),
    SafetyAction(
        key = "hold",
        title = "HOLD",
        symbol = "\u23F8",
        color = DSColor.QuietAccent,
        message = "HOLD emergency initiated. Keep current position until cleared.",
    ),
)

private val TeamAssistTypes = listOf(
    "Fight in Progress",
    "Irate Parent",
    "Medical Assistance",
    "Principal to Front Office",
    "Suspicious Activity",
)

// ── Multi-tenant models ────────────────────────────────────────────────────────
data class TenantSummaryItem(
    val tenantSlug: String,
    val tenantName: String,
    val role: String?,
)

data class TenantOverviewItem(
    val tenantSlug: String,
    val tenantName: String,
    val alarmIsActive: Boolean,
    val alarmMessage: String?,
    val alarmIsTraining: Boolean,
    val lastAlertAt: String?,
    val acknowledgementCount: Int,
    val expectedUserCount: Int,
    val acknowledgementRate: Double,
)

internal data class MeData(
    val userId: Int,
    val name: String,
    val role: String,
    val loginName: String,
    val title: String?,
    val canDeactivateAlarm: Boolean,
    val tenants: List<TenantSummaryItem>,
    val selectedTenant: String,
)

// ── Data ───────────────────────────────────────────────────────────────────────
data class AlarmStatus(
    val isActive: Boolean = false,
    val message: String?  = null,
    val isTraining: Boolean = false,
    val trainingLabel: String? = null,
    val activatedAt: String? = null,
    val activatedByUserId: Int? = null,
    val activatedByLabel: String? = null,
    val broadcasts: List<BroadcastUpdate> = emptyList(),
    val acknowledgementCount: Int = 0,
    val expectedUserCount: Int = 0,
    val acknowledgementPercentage: Float = 0f,
    val currentUserAcknowledged: Boolean = false,
    val triggeredByUserId: Int? = null,
    val silentForSender: Boolean = true,
    val isSilentForCurrentUser: Boolean = false,
    val alertId: Int? = null,
)

data class IncidentFeedItem(
    val id: Int,
    val type: String,
    val status: String,
    val createdBy: Int,
    val createdAt: String,
    val targetScope: String,
)

data class TeamAssistFeedItem(
    val id: Int,
    val type: String,
    val status: String,
    val createdBy: Int,
    val createdAt: String,
    val actedByLabel: String? = null,
    val forwardToLabel: String? = null,
    val cancelledByUserId: Int? = null,
    val cancelReasonText: String? = null,
    val cancelReasonCategory: String? = null,
)

data class ProviderDeliveryStats(
    val total: Int = 0,
    val ok: Int = 0,
    val failed: Int = 0,
    val lastError: String? = null,
)

data class PushDeliveryStats(
    val total: Int = 0,
    val ok: Int = 0,
    val failed: Int = 0,
    val lastError: String? = null,
    val byProvider: Map<String, ProviderDeliveryStats> = emptyMap(),
)

data class AuditLogEntry(
    val id: Int,
    val timestamp: String,
    val eventType: String,
    val actorLabel: String? = null,
    val targetType: String? = null,
)

data class UiState(
    val alarm: AlarmStatus      = AlarmStatus(),
    val connected: Boolean?     = null,   // null = unknown, true/false = result
    val isBusy: Boolean         = false,
    val successMsg: String?     = null,
    val errorMsg: String?       = null,
    val adminInbox: List<AdminInboxMessage> = emptyList(),
    val unreadAdminMessages: Int = 0,
    val adminMessageRecipients: List<InboxRecipient> = emptyList(),
    val quietPeriodStatus: QuietPeriodMobileStatus? = null,
    val activeIncidents: List<IncidentFeedItem> = emptyList(),
    val activeTeamAssists: List<TeamAssistFeedItem> = emptyList(),
    val isRefreshingFeed: Boolean = false,
    val teamAssistActionRecipients: List<TeamAssistActionRecipient> = emptyList(),
    val adminQuietPeriodRequests: List<AdminQuietPeriodRequest> = emptyList(),
    val pendingAdminEvents: List<AdminEvent> = emptyList(),
    val pendingAdminQuietModals: List<AdminQuietModalEvent> = emptyList(),
    val isWsConnected: Boolean = false,
    val pushDeliveryStats: PushDeliveryStats? = null,
    val auditLog: List<AuditLogEntry> = emptyList(),
    val featureLabels: Map<String, String> = AppLabels.DEFAULT_FEATURE_LABELS,
    val tenants: List<TenantSummaryItem> = emptyList(),
    val selectedTenantSlug: String = "",
    val selectedTenantName: String = "",
    val userTitle: String = "",
    val districtTenants: List<TenantOverviewItem> = emptyList(),
    val districtQuietRequests: List<DistrictQuietPeriodItem> = emptyList(),
    val districtAuditLog: List<AuditLogEntry> = emptyList(),
    val tenantSettings: TenantSettings = TenantSettings(),
)

// ── ViewModel ──────────────────────────────────────────────────────────────────
class MainViewModel : ViewModel() {
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state

    private var client: BackendClient? = null
    private var currentBaseUrl: String = ""
    private val wsHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .build()
    private var alarmWs: okhttp3.WebSocket? = null
    private var districtWs: okhttp3.WebSocket? = null
    private var districtWsJob: Job? = null
    private val districtWsGeneration = AtomicInteger(0)
    private var wsJob: Job? = null
    private var wsPingJob: Job? = null
    private val wsGeneration = AtomicInteger(0)
    private var cachedUserId: Int? = null
    private var cachedUserRole: String = ""
    private var cachedHomeSlug: String = ""
    private val processedEventIds = LinkedHashSet<String>(200)
    @Volatile private var pendingAck = false
    @Volatile private var cachedFcmToken: String? = null

    private fun isDuplicateEvent(eventId: String): Boolean {
        if (eventId.isBlank()) return false
        synchronized(processedEventIds) {
            if (processedEventIds.contains(eventId)) return true
            processedEventIds.add(eventId)
            if (processedEventIds.size > 200) processedEventIds.remove(processedEventIds.iterator().next())
            return false
        }
    }

    fun init(ctx: Context) {
        if (client != null) return
        cachedUserId = getUserId(ctx).toIntOrNull()
        cachedUserRole = getUserRole(ctx)
        val serverUrl = getServerUrl(ctx)
        val savedSlug = getSelectedTenantSlug(ctx)
        val savedName = getSelectedTenantName(ctx)
        cachedHomeSlug = extractSchoolSlug(serverUrl)
        currentBaseUrl = if (savedSlug.isNotBlank()) buildSelectedTenantUrl(serverUrl, savedSlug) else serverUrl
        client = BackendClient(currentBaseUrl, BuildConfig.BACKEND_API_KEY)
        if (savedSlug.isNotBlank()) {
            _state.update { it.copy(selectedTenantSlug = savedSlug, selectedTenantName = savedName) }
        }
        refreshFeatureLabels()
        registerPushToken(ctx)
        startPolling(ctx)
        loadMeData(ctx)
        startAlarmWebSocket(ctx)
        val role = getUserRole(ctx)
        if (canAccessDistrictSettings(role)) startDistrictWebSocket(ctx)
    }

    fun refreshFeatureLabels() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.configLabels() }
                .onSuccess { labels ->
                    if (labels.isNotEmpty()) {
                        _state.update { it.copy(featureLabels = AppLabels.DEFAULT_FEATURE_LABELS + labels) }
                    }
                }
        }
    }

    private fun registerPushToken(ctx: Context) {
        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            if (!task.isSuccessful) return@addOnCompleteListener
            val token = task.result ?: return@addOnCompleteListener
            cachedFcmToken = token
            val userId = getUserId(ctx).toIntOrNull()
            val deviceId = getOrCreateDeviceId(ctx)
            viewModelScope.launch(Dispatchers.IO) {
                runCatching { client?.registerAndroidDevice(token, userId, deviceId) }
            }
        }
    }

    private fun startPolling(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull()
        viewModelScope.launch(Dispatchers.IO) {
            var tick = 0
            while (isActive) {
                var cycleHadSuccess = false
                runCatching { client!!.alarmStatus() }
                    .onSuccess { alarm ->
                        cycleHadSuccess = true
                        _state.update { s ->
                            val safeAlarm = if (pendingAck && !alarm.currentUserAcknowledged)
                                alarm.copy(currentUserAcknowledged = true) else alarm
                            s.copy(alarm = safeAlarm, connected = true)
                        }
                    }
                if (userId != null) {
                    runCatching { client!!.quietPeriodStatus(userId = userId) }
                        .onSuccess { quiet ->
                            cycleHadSuccess = true
                            _state.update { it.copy(quietPeriodStatus = quiet) }
                        }
                }
                if (refreshIncidentFeedsOnce()) {
                    cycleHadSuccess = true
                }
                _state.update { it.copy(connected = cycleHadSuccess) }
                tick += 1
                if (tick % 6 == 0) {
                    cachedFcmToken?.let { token -> runCatching { client!!.heartbeat(token) } }
                }
                if (tick % 18 == 0) {
                    runCatching { client!!.configLabels() }
                        .onSuccess { labels ->
                            if (labels.isNotEmpty()) {
                                _state.update { it.copy(featureLabels = AppLabels.DEFAULT_FEATURE_LABELS + labels) }
                            }
                        }
                }
                delay(10_000)
            }
        }
    }

    private suspend fun refreshIncidentFeedsOnce(): Boolean {
        var success = false
        runCatching { client!!.activeIncidents() }
            .onSuccess { incidents ->
                success = true
                _state.update { it.copy(activeIncidents = incidents) }
            }
        runCatching { client!!.activeRequestHelp() }
            .onSuccess { teamAssists ->
                success = true
                _state.update { it.copy(activeTeamAssists = teamAssists) }
            }
        return success
    }

    fun refreshIncidentFeeds() {
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isRefreshingFeed = true) }
            refreshIncidentFeedsOnce()
            _state.update { it.copy(isRefreshingFeed = false) }
        }
    }

    fun handleAlarmLaunch(message: String, isSilentForMe: Boolean = false) {
        val normalized = message.trim()
        _state.update {
            it.copy(
                alarm = it.alarm.copy(
                    isActive = true,
                    message = normalized.ifBlank { it.alarm.message ?: "Emergency alert received." },
                    isSilentForCurrentUser = isSilentForMe,
                ),
                successMsg = null,
                errorMsg = null,
            )
        }
        refreshIncidentFeeds()
    }

    fun activateAlarm(ctx: Context, message: String, isTraining: Boolean = false, trainingLabel: String? = null) {
        val userId = getUserId(ctx).toIntOrNull()
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.activateAlarm(message, userId, isTraining = isTraining, trainingLabel = trainingLabel) }
                .onSuccess { alarm ->
                    _state.update {
                        it.copy(
                            alarm = alarm,
                            isBusy = false,
                            successMsg = if (isTraining) "Training alert activated." else "Alarm activated.",
                        )
                    }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to activate alarm.") }
                }
        }
    }

    fun deregisterCurrentDevice(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull()
        val deviceId = getOrCreateDeviceId(ctx)
        viewModelScope.launch(Dispatchers.IO) {
            FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
                val token = task.result ?: return@addOnCompleteListener
                runCatching { client?.deregisterAndroidDevice(token, userId, deviceId) }
            }
        }
    }

    fun deactivateAlarm(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull()
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.deactivateAlarm(userId) }
                .onSuccess { alarm ->
                    AlarmAudioController.stop()
                    _state.update { it.copy(alarm = alarm, isBusy = false, successMsg = "Alarm cleared.") }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to deactivate alarm.") }
                }
        }
    }

    fun acknowledgeAlarm(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull() ?: return
        val alertId = _state.value.alarm.alertId ?: return
        viewModelScope.launch(Dispatchers.IO) {
            pendingAck = true
            _state.update { it.copy(isBusy = true, errorMsg = null, alarm = it.alarm.copy(currentUserAcknowledged = true)) }
            runCatching { client!!.acknowledgeAlert(alertId = alertId, userId = userId) }
                .onSuccess {
                    _state.update { it.copy(isBusy = false) }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Acknowledgement failed.", alarm = it.alarm.copy(currentUserAcknowledged = false)) }
                }
            pendingAck = false
        }
    }

    fun sendAlertMessageFromOverlay(ctx: Context, message: String) {
        val userId = getUserId(ctx).toIntOrNull() ?: return
        val alertId = _state.value.alarm.alertId ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.sendAlertMessage(alertId = alertId, userId = userId, message = message) }
                .onFailure { e ->
                    android.util.Log.d("BlueBird", "sendAlertMessage failed: ${e.message}")
                }
        }
    }

    fun sendReport(ctx: Context, category: String, note: String?) {
        val userId = getUserId(ctx).toIntOrNull()
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.sendReport(userId = userId, category = category, note = note) }
                .onSuccess {
                    _state.update { it.copy(isBusy = false, successMsg = "Report sent to admins.") }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to send report.") }
                }
        }
    }

    fun sendAdminMessage(ctx: Context, message: String) {
        val userId = getUserId(ctx).toIntOrNull()
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.messageAdmin(userId = userId, message = message) }
                .onSuccess {
                    _state.update { it.copy(isBusy = false, successMsg = "Message sent to admins.") }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to message admins.") }
                }
        }
    }

    fun sendAdminMessageToUsers(ctx: Context, message: String, recipientUserIds: List<Int>, sendToAll: Boolean) {
        val adminUserId = getUserId(ctx).toIntOrNull()
        if (adminUserId == null) {
            _state.update { it.copy(errorMsg = "Admin sign-in is required.") }
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching {
                client!!.sendMessageFromAdmin(
                    adminUserId = adminUserId,
                    message = message,
                    recipientUserIds = recipientUserIds,
                    sendToAll = sendToAll,
                )
            }
                .onSuccess { sentCount ->
                    val label = if (sendToAll) "all users" else "selected user"
                    _state.update { it.copy(isBusy = false, successMsg = "Message sent to $label ($sentCount).") }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to send admin message.") }
                }
        }
    }

    fun refreshAdminInbox(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull() ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.messageInbox(userId = userId) }
                .onSuccess { inbox ->
                    _state.update { it.copy(adminInbox = inbox.messages, unreadAdminMessages = inbox.unreadCount) }
                }
        }
    }

    fun refreshAdminRecipients() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.listMessageRecipients() }
                .onSuccess { recipients ->
                    _state.update { it.copy(adminMessageRecipients = recipients) }
                }
        }
    }

    fun refreshTeamAssistActionRecipients() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.listTeamAssistActionRecipients() }
                .onSuccess { recipients ->
                    _state.update { it.copy(teamAssistActionRecipients = recipients) }
                }
        }
    }

    fun refreshAdminQuietPeriodRequests(ctx: Context) {
        val adminUserId = getUserId(ctx).toIntOrNull() ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.listAdminQuietPeriodRequests(adminUserId = adminUserId) }
                .onSuccess { requests ->
                    _state.update { it.copy(adminQuietPeriodRequests = requests.filter { req -> req.userId != adminUserId }) }
                }
        }
    }

    fun enqueueAdminEvent(event: AdminEvent) {
        _state.update { it.copy(pendingAdminEvents = it.pendingAdminEvents + event) }
    }

    fun dismissAdminEvent(id: String) {
        _state.update { it.copy(pendingAdminEvents = it.pendingAdminEvents.filterNot { e -> e.id == id }) }
    }

    fun enqueueAdminQuietModal(event: AdminQuietModalEvent) {
        if (_state.value.pendingAdminQuietModals.none { it.id == event.id }) {
            _state.update { it.copy(pendingAdminQuietModals = it.pendingAdminQuietModals + event) }
        }
    }

    fun dequeueAdminQuietModal(id: String) {
        _state.update { it.copy(pendingAdminQuietModals = it.pendingAdminQuietModals.filterNot { e -> e.id == id }) }
    }

    fun clearAdminQuietModalsForRequest(requestId: Int) {
        _state.update { it.copy(pendingAdminQuietModals = it.pendingAdminQuietModals.filterNot { e -> e.requestId == requestId }) }
    }

    fun refreshPushDeliveryStats(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull() ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.alarmPushStats(userId = userId) }
                .onSuccess { stats -> _state.update { it.copy(pushDeliveryStats = stats) } }
        }
    }

    internal fun getClient(): BackendClient? = client

    fun refreshAuditLog(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull() ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.auditLog(userId = userId, limit = 50) }
                .onSuccess { entries -> _state.update { it.copy(auditLog = entries) } }
        }
    }

    fun replyToAdminMessage(ctx: Context, messageId: Int, message: String) {
        val userId = getUserId(ctx).toIntOrNull() ?: return
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.replyAdminMessage(adminUserId = userId, messageId = messageId, message = message) }
                .onSuccess {
                    val inbox = runCatching { client!!.messageInbox(userId = userId) }.getOrNull()
                    _state.update {
                        it.copy(
                            isBusy = false,
                            successMsg = "Reply sent.",
                            adminInbox = inbox?.messages ?: it.adminInbox,
                            unreadAdminMessages = inbox?.unreadCount ?: it.unreadAdminMessages,
                        )
                    }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to reply to message.") }
                }
        }
    }

    fun requestQuietPeriod(ctx: Context, reason: String?, scheduledStartAt: String? = null, scheduledEndAt: String? = null) {
        val userId = getUserId(ctx).toIntOrNull()
        if (userId == null) {
            _state.update { it.copy(errorMsg = "You must be signed in to request a quiet period.") }
            return
        }
        Log.d("QuietPeriod", "Submit tapped — userId=$userId reason=$reason")
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            Log.d("QuietPeriod", "POST /quiet-periods/request")
            runCatching { client!!.requestQuietPeriod(userId = userId, reason = reason, scheduledStartAt = scheduledStartAt, scheduledEndAt = scheduledEndAt) }
                .onSuccess {
                    Log.d("QuietPeriod", "Request submitted successfully")
                    val quiet = runCatching { client!!.quietPeriodStatus(userId = userId) }.getOrNull()
                    _state.update {
                        it.copy(
                            isBusy = false,
                            successMsg = "Quiet period request sent to admins.",
                            quietPeriodStatus = quiet ?: it.quietPeriodStatus,
                        )
                    }
                }
                .onFailure { e ->
                    Log.e("QuietPeriod", "Request failed: ${e.message}", e)
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to request quiet period.") }
                }
        }
    }

    fun requestHelp(ctx: Context, type: String) {
        val userId = getUserId(ctx).toIntOrNull()
        if (userId == null) {
            _state.update { it.copy(errorMsg = "You must be signed in to request help.") }
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.createRequestHelp(userId = userId, type = type) }
                .onSuccess {
                    val activeTeamAssists = runCatching { client!!.activeRequestHelp() }.getOrDefault(_state.value.activeTeamAssists)
                    _state.update {
                        it.copy(
                            isBusy = false,
                            successMsg = "Request help sent.",
                            activeTeamAssists = activeTeamAssists,
                        )
                    }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to send request help.") }
                }
        }
    }

    fun createTeamAssist(ctx: Context, type: String) {
        requestHelp(ctx = ctx, type = type)
    }

    fun updateRequestHelpAction(ctx: Context, teamAssistId: Int, action: String, forwardToUserId: Int? = null) {
        val actorUserId = getUserId(ctx).toIntOrNull()
        if (actorUserId == null) {
            _state.update { it.copy(errorMsg = "Admin sign-in is required.") }
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching {
                client!!.updateRequestHelpAction(
                    teamAssistId = teamAssistId,
                    actorUserId = actorUserId,
                    action = action,
                    forwardToUserId = forwardToUserId,
                )
            }
                .onSuccess { _ ->
                    if (action == "acknowledge") {
                        (ctx.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager)
                            ?.cancel(HELP_REQUEST_PUSH_NOTIFICATION_ID)
                    }
                    val activeTeamAssists = runCatching { client!!.activeRequestHelp() }.getOrDefault(_state.value.activeTeamAssists)
                    _state.update {
                        it.copy(
                            isBusy = false,
                            successMsg = "Request help updated by ${getUserName(ctx)}.",
                            activeTeamAssists = activeTeamAssists,
                        )
                    }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to update request help.") }
                }
        }
    }

    fun updateTeamAssistAction(ctx: Context, teamAssistId: Int, action: String, forwardToUserId: Int? = null) {
        updateRequestHelpAction(
            ctx = ctx,
            teamAssistId = teamAssistId,
            action = action,
            forwardToUserId = forwardToUserId,
        )
    }

    fun cancelTeamAssist(ctx: Context, teamAssistId: Int, reasonText: String, reasonCategory: String) {
        val userId = getUserId(ctx).toIntOrNull()
        if (userId == null) {
            _state.update { it.copy(errorMsg = "Sign-in is required.") }
            return
        }
        // Optimistic: remove immediately so the UI updates without waiting for the round-trip.
        _state.update { it.copy(
            isBusy = true,
            errorMsg = null,
            activeTeamAssists = it.activeTeamAssists.filter { ta -> ta.id != teamAssistId },
        ) }
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.cancelTeamAssist(teamAssistId = teamAssistId, userId = userId, reasonText = reasonText, reasonCategory = reasonCategory) }
                .onSuccess {
                    val confirmed = runCatching { client!!.activeRequestHelp() }.getOrDefault(_state.value.activeTeamAssists)
                    _state.update { it.copy(isBusy = false, successMsg = "Help request cancelled.", activeTeamAssists = confirmed) }
                }
                .onFailure { e ->
                    val restored = runCatching { client!!.activeRequestHelp() }.getOrDefault(_state.value.activeTeamAssists)
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to cancel help request.", activeTeamAssists = restored) }
                }
        }
    }

    fun approveQuietPeriodRequest(ctx: Context, requestId: Int) {
        val adminUserId = getUserId(ctx).toIntOrNull()
        if (adminUserId == null) {
            _state.update { it.copy(errorMsg = "Admin sign-in is required.") }
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.approveQuietPeriodRequest(requestId = requestId, adminUserId = adminUserId) }
                .onSuccess {
                    val quiet = runCatching { client!!.quietPeriodStatus(userId = adminUserId) }.getOrNull()
                    val requests = runCatching { client!!.listAdminQuietPeriodRequests(adminUserId = adminUserId) }.getOrDefault(_state.value.adminQuietPeriodRequests)
                    _state.update {
                        it.copy(
                            isBusy = false,
                            successMsg = "Quiet period request approved.",
                            quietPeriodStatus = quiet ?: it.quietPeriodStatus,
                            adminQuietPeriodRequests = requests,
                        )
                    }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to approve quiet period request.") }
                }
        }
    }

    fun denyQuietPeriodRequest(ctx: Context, requestId: Int) {
        val adminUserId = getUserId(ctx).toIntOrNull()
        if (adminUserId == null) {
            _state.update { it.copy(errorMsg = "Admin sign-in is required.") }
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.denyQuietPeriodRequest(requestId = requestId, adminUserId = adminUserId) }
                .onSuccess {
                    val requests = runCatching { client!!.listAdminQuietPeriodRequests(adminUserId = adminUserId) }.getOrDefault(_state.value.adminQuietPeriodRequests)
                    _state.update {
                        it.copy(
                            isBusy = false,
                            successMsg = "Quiet period request denied.",
                            adminQuietPeriodRequests = requests,
                        )
                    }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to deny quiet period request.") }
                }
        }
    }

    fun deleteQuietPeriodRequest(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull()
        val requestId = _state.value.quietPeriodStatus?.requestId
        if (userId == null || requestId == null) {
            _state.update { it.copy(errorMsg = "No active quiet period request to delete.") }
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.deleteQuietPeriodRequest(requestId = requestId, userId = userId) }
                .onSuccess {
                    val quiet = runCatching { client!!.quietPeriodStatus(userId = userId) }.getOrNull()
                    _state.update {
                        it.copy(
                            isBusy = false,
                            successMsg = "Quiet period request deleted.",
                            quietPeriodStatus = quiet ?: QuietPeriodMobileStatus(),
                        )
                    }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to delete quiet period request.") }
                }
        }
    }

    fun loadMeData(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull() ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                BackendClient(getServerUrl(ctx), BuildConfig.BACKEND_API_KEY).getMe(userId)
            }.onSuccess { me ->
                val currentSlug = _state.value.selectedTenantSlug
                val slugIsValid = me.tenants.any { it.tenantSlug == currentSlug }
                val selectedSlug = if (slugIsValid && currentSlug.isNotBlank()) {
                    currentSlug
                } else {
                    me.tenants.firstOrNull()?.tenantSlug ?: me.selectedTenant
                }
                val selectedName = me.tenants.firstOrNull { it.tenantSlug == selectedSlug }?.tenantName ?: ""
                prefs(ctx).edit()
                    .putString(KEY_SELECTED_TENANT_SLUG, selectedSlug)
                    .putString(KEY_SELECTED_TENANT_NAME, selectedName)
                    .putString(KEY_USER_TITLE, me.title ?: "")
                    .apply()
                _state.update { s ->
                    s.copy(
                        tenants = me.tenants,
                        selectedTenantSlug = selectedSlug,
                        selectedTenantName = selectedName,
                        userTitle = me.title ?: "",
                    )
                }
                val newUrl = buildSelectedTenantUrl(getServerUrl(ctx), selectedSlug)
                if (newUrl != currentBaseUrl) {
                    currentBaseUrl = newUrl
                    client = BackendClient(newUrl, BuildConfig.BACKEND_API_KEY)
                    startAlarmWebSocket(ctx)
                }
                loadTenantSettings()
            }
        }
    }

    fun switchTenant(ctx: Context, slug: String, name: String) {
        prefs(ctx).edit()
            .putString(KEY_SELECTED_TENANT_SLUG, slug)
            .putString(KEY_SELECTED_TENANT_NAME, name)
            .apply()
        _state.update {
            it.copy(
                selectedTenantSlug = slug,
                selectedTenantName = name,
                alarm = AlarmStatus(),
                districtTenants = emptyList(),
            )
        }
        val newUrl = buildSelectedTenantUrl(getServerUrl(ctx), slug)
        currentBaseUrl = newUrl
        client = BackendClient(newUrl, BuildConfig.BACKEND_API_KEY)
        startAlarmWebSocket(ctx)
    }

    fun loadTenantSettings() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client?.getTenantSettings() ?: TenantSettings() }
                .onSuccess { settings -> _state.update { it.copy(tenantSettings = settings) } }
            // silently ignore failures — safe defaults remain in UiState
        }
    }

    fun loadDistrictOverview(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull() ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.getDistrictOverview(userId) }
                .onSuccess { tenants -> _state.update { it.copy(districtTenants = tenants) } }
                .onFailure { e -> _state.update { it.copy(errorMsg = e.message ?: "Failed to load district overview.") } }
        }
    }

    fun loadDistrictQuietPeriods(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull() ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.listDistrictQuietPeriods(userId) }
                .onSuccess { requests ->
                    _state.update { it.copy(districtQuietRequests = requests.filter { req -> req.userId != userId }) }
                }
        }
    }

    fun approveDistrictQuietRequest(ctx: Context, requestId: Int, tenantSlug: String) {
        val adminId = getUserId(ctx).toIntOrNull() ?: return
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true) }
            runCatching { client!!.approveDistrictQuietPeriod(requestId, adminId, tenantSlug) }
                .onSuccess {
                    val updated = _state.value.districtQuietRequests.filterNot { it.requestId == requestId }
                    _state.update { it.copy(districtQuietRequests = updated, isBusy = false, successMsg = "Quiet period approved.") }
                }
                .onFailure { e -> _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Approve failed.") } }
        }
    }

    fun denyDistrictQuietRequest(ctx: Context, requestId: Int, tenantSlug: String) {
        val adminId = getUserId(ctx).toIntOrNull() ?: return
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true) }
            runCatching { client!!.denyDistrictQuietPeriod(requestId, adminId, tenantSlug) }
                .onSuccess {
                    val updated = _state.value.districtQuietRequests.filterNot { it.requestId == requestId }
                    _state.update { it.copy(districtQuietRequests = updated, isBusy = false, successMsg = "Quiet period request denied.") }
                }
                .onFailure { e -> _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Deny failed.") } }
        }
    }

    fun loadDistrictAuditLog(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull() ?: return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { client!!.listDistrictAuditLog(userId) }
                .onSuccess { entries -> _state.update { it.copy(districtAuditLog = entries) } }
        }
    }

    private fun startDistrictWebSocket(ctx: Context) {
        districtWsJob?.cancel()
        districtWs?.close(1000, "restart")
        districtWs = null
        val userId = getUserId(ctx).toIntOrNull() ?: return
        val homeSlug = cachedHomeSlug.ifBlank { extractSchoolSlug(getServerUrl(ctx)) }
        if (homeSlug.isBlank() || userId <= 0) return
        val myGen = districtWsGeneration.incrementAndGet()
        val serverUrl = getServerUrl(ctx)
        districtWsJob = viewModelScope.launch(Dispatchers.IO) {
            var backoffMs = 3_000L
            while (isActive && districtWsGeneration.get() == myGen) {
                val wsUrl = buildDistrictWsUrl(serverUrl, userId, homeSlug)
                if (wsUrl.isBlank()) break
                Log.d("DistrictWS", "WS connecting: $wsUrl gen=$myGen")
                val closed = CompletableDeferred<Unit>()
                val closeCode = AtomicInteger(-1)
                districtWs = wsHttpClient.newWebSocket(
                    okhttp3.Request.Builder()
                        .url(wsUrl)
                        .header("X-API-Key", BuildConfig.BACKEND_API_KEY)
                        .build(),
                    object : okhttp3.WebSocketListener() {
                        override fun onOpen(ws: okhttp3.WebSocket, response: okhttp3.Response) {
                            Log.d("DistrictWS", "WS open gen=$myGen")
                            backoffMs = 3_000L
                        }
                        override fun onMessage(ws: okhttp3.WebSocket, text: String) {
                            handleWsMessage(text)
                        }
                        override fun onFailure(ws: okhttp3.WebSocket, t: Throwable, response: okhttp3.Response?) {
                            Log.w("DistrictWS", "WS failure: ${t.message} gen=$myGen")
                            districtWs = null
                            closed.complete(Unit)
                        }
                        override fun onClosed(ws: okhttp3.WebSocket, code: Int, reason: String) {
                            Log.d("DistrictWS", "WS closed: code=$code reason=$reason gen=$myGen")
                            closeCode.set(code)
                            districtWs = null
                            closed.complete(Unit)
                        }
                    },
                )
                closed.await()
                if (!isActive || districtWsGeneration.get() != myGen) break
                val code = closeCode.get()
                if (code in 4000..4999) {
                    Log.w("DistrictWS", "WS rejected by server code=$code, not reconnecting gen=$myGen")
                    break
                }
                if (code == 1001 || code == 1012) backoffMs = 500L
                delay(backoffMs)
                backoffMs = minOf(backoffMs * 2, 30_000L)
            }
        }
    }

    private fun buildDistrictWsUrl(serverUrl: String, userId: Int, homeSlug: String): String {
        return runCatching {
            val uri = java.net.URI(serverUrl)
            val scheme = if (uri.scheme == "https") "wss" else "ws"
            val port = if (uri.port > 0) ":${uri.port}" else ""
            "$scheme://${uri.host}$port/ws/district/alerts?user_id=$userId&home_tenant=$homeSlug"
        }.getOrDefault("")
    }

    private fun startAlarmWebSocket(ctx: Context) {
        wsJob?.cancel()
        wsPingJob?.cancel()
        alarmWs?.close(1000, "restart")
        alarmWs = null
        _state.update { it.copy(isWsConnected = false) }
        val myGen = wsGeneration.incrementAndGet()
        val serverUrl = getServerUrl(ctx)
        val slug = _state.value.selectedTenantSlug.ifBlank { extractSchoolSlug(serverUrl) }
        if (slug.isBlank()) return
        Log.d("BluebirdWS", "WS starting gen=$myGen slug=$slug")
        wsJob = viewModelScope.launch(Dispatchers.IO) {
            var backoffMs = 2_000L
            while (isActive && wsGeneration.get() == myGen) {
                val wsUrl = buildWsUrl(serverUrl, slug)
                if (wsUrl.isBlank()) break
                Log.d("BluebirdWS", "WS connecting: $wsUrl backoff=${backoffMs}ms gen=$myGen")
                val closed = CompletableDeferred<Unit>()
                val closeCode = AtomicInteger(-1)
                alarmWs = wsHttpClient.newWebSocket(
                    okhttp3.Request.Builder()
                        .url(wsUrl)
                        .header("X-API-Key", BuildConfig.BACKEND_API_KEY)
                        .build(),
                    object : okhttp3.WebSocketListener() {
                        override fun onOpen(ws: okhttp3.WebSocket, response: okhttp3.Response) {
                            backoffMs = 2_000L
                            _state.update { it.copy(isWsConnected = true) }
                            Log.d("BluebirdWS", "WS connected: $wsUrl gen=$myGen")
                            // Reconcile state on (re)connect, then maintain presence with pings.
                            wsPingJob?.cancel()
                            wsPingJob = viewModelScope.launch(Dispatchers.IO) {
                                // Sync on reconnect — best-effort.
                                val uid = cachedUserId
                                runCatching { client!!.syncState(uid) }
                                    .onSuccess { sync ->
                                        _state.update { s ->
                                            s.copy(
                                                alarm = sync.alarm,
                                                quietPeriodStatus = sync.quietPeriod ?: s.quietPeriodStatus,
                                            )
                                        }
                                    }
                                // Ping every 25 s — keeps presence updated + detects dead connections.
                                while (isActive && wsGeneration.get() == myGen) {
                                    delay(25_000L)
                                    if (!ws.send("""{"type":"ping"}""")) break
                                }
                            }
                        }
                        override fun onMessage(ws: okhttp3.WebSocket, text: String) {
                            backoffMs = 2_000L
                            val eventType = runCatching { JSONObject(text).optString("event", "?") }.getOrDefault("?")
                            Log.d("BluebirdWS", "WS message event=$eventType slug=$slug gen=$myGen")
                            handleWsMessage(text)
                        }
                        override fun onFailure(ws: okhttp3.WebSocket, t: Throwable, response: okhttp3.Response?) {
                            Log.w("BluebirdWS", "WS failure: ${t.message} gen=$myGen")
                            wsPingJob?.cancel()
                            _state.update { it.copy(isWsConnected = false) }
                            alarmWs = null
                            closed.complete(Unit)
                        }
                        override fun onClosed(ws: okhttp3.WebSocket, code: Int, reason: String) {
                            Log.d("BluebirdWS", "WS closed: code=$code reason=$reason gen=$myGen")
                            closeCode.set(code)
                            wsPingJob?.cancel()
                            _state.update { it.copy(isWsConnected = false) }
                            alarmWs = null
                            closed.complete(Unit)
                        }
                    },
                )
                closed.await()
                if (!isActive || wsGeneration.get() != myGen) break
                val code = closeCode.get()
                if (code in 4000..4999) {
                    Log.w("BluebirdWS", "WS rejected by server code=$code, not reconnecting gen=$myGen")
                    break
                }
                if (code == 1001 || code == 1012) {
                    backoffMs = 500L
                    Log.d("BluebirdWS", "WS server-restart close code=$code, reconnecting quickly gen=$myGen")
                }
                Log.d("BluebirdWS", "WS reconnecting in ${backoffMs}ms gen=$myGen")
                delay(backoffMs)
                backoffMs = minOf(backoffMs * 2, 15_000L)
            }
            Log.d("BluebirdWS", "WS loop exited gen=$myGen")
        }
    }

    private fun buildWsUrl(serverUrl: String, slug: String): String {
        return runCatching {
            val uri = java.net.URI(serverUrl)
            val scheme = if (uri.scheme == "https") "wss" else "ws"
            val port = if (uri.port > 0) ":${uri.port}" else ""
            "$scheme://${uri.host}$port/ws/$slug/alerts"
        }.getOrDefault("")
    }

    private fun buildSelectedTenantUrl(serverUrl: String, slug: String): String {
        val trimmedSlug = slug.trim()
        if (trimmedSlug.isBlank()) return serverUrl
        return runCatching {
            val uri = java.net.URI(serverUrl)
            val segs = uri.path.trim('/').split("/").filter { it.isNotBlank() }
            val newSegs = if (segs.isEmpty()) listOf(trimmedSlug) else segs.toMutableList().also { it[0] = trimmedSlug }
            val port = if (uri.port > 0) ":${uri.port}" else ""
            "${uri.scheme}://${uri.host}$port/${newSegs.joinToString("/")}"
        }.getOrDefault(serverUrl)
    }

    private fun handleWsMessage(text: String) {
        val j = runCatching { JSONObject(text) }.getOrNull() ?: return
        // Silently discard server pongs.
        if (j.optString("type") == "pong") return
        val event = j.optString("event")
        val eventId = j.optString("event_id").trim()
        if (isDuplicateEvent(eventId)) {
            Log.d("BluebirdWS", "WS dedup skip eventId=$eventId event=$event")
            return
        }
        val eventSlug = j.optString("tenant_slug").trim()
        val alarm = j.optJSONObject("alarm")
        val currentSlug = _state.value.selectedTenantSlug
        val isCurrentTenant = eventSlug.isBlank() || eventSlug == currentSlug
        if (eventSlug.isNotBlank()) updateDistrictTenant(eventSlug, event, alarm)
        if (!isCurrentTenant) return
        when (event) {
            "alarm_activated", "alert_triggered" -> {
                val a = alarm ?: return
                val triggeredByUid = a.optInt("triggered_by_user_id", -1).takeIf { it > 0 }
                val silentForSender = a.optBoolean("silent_for_sender", true)
                val isSilentForMe = silentForSender && triggeredByUid != null && triggeredByUid == cachedUserId
                _state.update { s ->
                    s.copy(alarm = s.alarm.copy(
                        isActive = a.optBoolean("is_active", true),
                        message = a.optString("message").ifBlank { null },
                        isTraining = a.optBoolean("is_training", false),
                        trainingLabel = a.optString("training_label").ifBlank { null },
                        activatedByLabel = a.optString("activated_by_label").ifBlank { null },
                        triggeredByUserId = triggeredByUid,
                        silentForSender = silentForSender,
                        isSilentForCurrentUser = isSilentForMe,
                        alertId = if (a.has("current_alert_id") && !a.isNull("current_alert_id"))
                            a.optInt("current_alert_id") else s.alarm.alertId,
                        acknowledgementCount = a.optInt("acknowledgement_count", s.alarm.acknowledgementCount),
                        expectedUserCount = a.optInt("expected_user_count", s.alarm.expectedUserCount),
                        acknowledgementPercentage = a.optDouble("acknowledgement_percentage", s.alarm.acknowledgementPercentage.toDouble()).toFloat(),
                    ))
                }
            }
            "alarm_deactivated", "tenant_alert_cleared" -> {
                AlarmAudioController.stop()
                _state.update { s ->
                    s.copy(alarm = s.alarm.copy(
                        isActive = false, message = null, isTraining = false,
                        trainingLabel = null, broadcasts = emptyList(),
                    ))
                }
            }
            "quiet_request_created", "quiet_request_updated" -> {
                val uid = cachedUserId ?: return
                viewModelScope.launch(Dispatchers.IO) {
                    runCatching { client!!.listAdminQuietPeriodRequests(adminUserId = uid) }
                        .onSuccess { requests -> _state.update { it.copy(adminQuietPeriodRequests = requests) } }
                }
                if (event == "quiet_request_created") {
                    val requesterName = j.optString("user_name").ifBlank { "A team member" }
                    val requesterRole = j.optString("user_role").ifBlank { "user" }
                    val reason = j.optString("reason").ifBlank { null }
                    val requestId = j.optInt("request_id", -1).takeIf { it > 0 }
                    val tenantSlug = eventSlug.ifBlank { null }
                    // Toast notification for all users.
                    enqueueAdminEvent(AdminEvent(
                        id = "quiet_created_${System.currentTimeMillis()}",
                        type = AdminEventType.QUIET_PENDING,
                        title = "$requesterName requested quiet time",
                        body = if (reason != null) "“$reason”" else "Awaiting admin approval.",
                    ))
                    // Rich actionable modal for admins only.
                    if (requestId != null && isAdminRole(cachedUserRole)) {
                        enqueueAdminQuietModal(AdminQuietModalEvent(
                            id = "qm_${requestId}",
                            requestId = requestId,
                            userName = requesterName,
                            userRole = snakeToTitle(requesterRole),
                            reason = reason,
                            requestedAt = null,
                            tenantSlug = tenantSlug,
                        ))
                    }
                } else {
                    // quiet_request_updated — clear any open modal for this request.
                    val requestId = j.optInt("request_id", -1).takeIf { it > 0 }
                    if (requestId != null) clearAdminQuietModalsForRequest(requestId)
                }
            }
            "message_received" -> {
                val uid = cachedUserId ?: return
                viewModelScope.launch(Dispatchers.IO) {
                    runCatching { client!!.messageInbox(userId = uid) }
                        .onSuccess { inbox -> _state.update { it.copy(adminInbox = inbox.messages, unreadAdminMessages = inbox.unreadCount) } }
                }
                val msgText = j.optString("message").ifBlank { null }
                val senderLabel = j.optString("sender_label").ifBlank { null } ?: "Admin"
                if (msgText != null) {
                    enqueueAdminEvent(AdminEvent(
                        id = "msg_${System.currentTimeMillis()}",
                        type = AdminEventType.ADMIN_MESSAGE,
                        title = "Message from $senderLabel",
                        body = msgText,
                    ))
                }
            }
            "tenant_acknowledgement_updated" -> {
                val a = alarm ?: return
                _state.update { s ->
                    s.copy(alarm = s.alarm.copy(
                        acknowledgementCount = a.optInt("acknowledgement_count", s.alarm.acknowledgementCount),
                        expectedUserCount = a.optInt("expected_user_count", s.alarm.expectedUserCount),
                        acknowledgementPercentage = a.optDouble("acknowledgement_percentage", s.alarm.acknowledgementPercentage.toDouble()).toFloat(),
                    ))
                }
            }
            "admin_broadcast" -> {
                val msgId = j.optInt("message_id", -1).takeIf { it > 0 } ?: return
                val msgText = j.optString("message").ifBlank { null } ?: return
                val senderLabel = j.optString("sender_label").ifBlank { null }
                val timestamp = j.optString("timestamp").ifBlank { null }
                _state.update { s ->
                    if (s.alarm.broadcasts.any { it.updateId == msgId }) return@update s
                    val newBroadcast = BroadcastUpdate(
                        updateId = msgId,
                        createdAt = timestamp ?: "",
                        adminLabel = senderLabel,
                        message = msgText,
                    )
                    s.copy(alarm = s.alarm.copy(broadcasts = s.alarm.broadcasts + newBroadcast))
                }
            }
            "new_user_message", "admin_reply" -> { /* handled server-side, no client action needed */ }
            "help_request_acknowledged", "help_request_resolved" -> {
                viewModelScope.launch(Dispatchers.IO) {
                    runCatching { client!!.activeRequestHelp() }
                        .onSuccess { result -> _state.update { it.copy(activeTeamAssists = result) } }
                }
            }
        }
    }

    private fun updateDistrictTenant(slug: String, event: String, alarm: JSONObject?) {
        val idx = _state.value.districtTenants.indexOfFirst { it.tenantSlug == slug }
        if (idx < 0) return
        _state.update { s ->
            val old = s.districtTenants[idx]
            val updated = when (event) {
                "alarm_activated", "alert_triggered" -> old.copy(
                    alarmIsActive = alarm?.optBoolean("is_active", true) ?: true,
                    alarmMessage = alarm?.optString("message")?.ifBlank { null },
                    alarmIsTraining = alarm?.optBoolean("is_training", false) ?: false,
                )
                "alarm_deactivated", "tenant_alert_cleared" -> old.copy(
                    alarmIsActive = false, alarmMessage = null, alarmIsTraining = false,
                )
                "tenant_acknowledgement_updated" -> old.copy(
                    acknowledgementCount = alarm?.optInt("acknowledgement_count", old.acknowledgementCount) ?: old.acknowledgementCount,
                    acknowledgementRate = alarm?.optDouble("acknowledgement_rate", old.acknowledgementRate) ?: old.acknowledgementRate,
                )
                else -> old
            }
            val newList = s.districtTenants.toMutableList().also { it[idx] = updated }
            s.copy(districtTenants = newList)
        }
    }

    fun clearMessages() = _state.update { it.copy(successMsg = null, errorMsg = null) }

    fun setErrorMessage(message: String) {
        _state.update { it.copy(errorMsg = message) }
    }
}

private object BiometricGate {
    private const val AUTH_FLAGS = BiometricManager.Authenticators.BIOMETRIC_STRONG or
        BiometricManager.Authenticators.DEVICE_CREDENTIAL

    fun isAvailable(context: Context): Boolean {
        val result = BiometricManager.from(context).canAuthenticate(AUTH_FLAGS)
        return result == BiometricManager.BIOMETRIC_SUCCESS
    }

    fun authenticate(
        activity: FragmentActivity,
        title: String,
        subtitle: String,
        onResult: (Boolean) -> Unit,
    ) {
        val executor = ContextCompat.getMainExecutor(activity)
        val prompt = BiometricPrompt(
            activity,
            executor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    onResult(true)
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    onResult(false)
                }

                override fun onAuthenticationFailed() {
                    // Wait for explicit success/error callback.
                }
            },
        )
        val promptInfo = BiometricPrompt.PromptInfo.Builder()
            .setTitle(title)
            .setSubtitle(subtitle)
            .setAllowedAuthenticators(AUTH_FLAGS)
            .build()
        prompt.authenticate(promptInfo)
    }
}

// ── Activity ───────────────────────────────────────────────────────────────────
class MainActivity : FragmentActivity() {
    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { _ -> }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        applyAlarmLaunchFlags(intent)
        // User pref takes priority over system dark mode; set before loadIfNeeded so token
        // parsing uses the correct mode from the very first composition.
        DSTokenStore.isDarkMode = if (prefs(this).contains(KEY_DARK_MODE)) {
            loadDarkModeSetting(this)
        } else {
            (resources.configuration.uiMode and
                android.content.res.Configuration.UI_MODE_NIGHT_MASK) ==
                android.content.res.Configuration.UI_MODE_NIGHT_YES
        }
        DSTokenStore.loadIfNeeded(this)
        ensureNotificationChannel(this)
        askNotificationPermission()
        setContent {
            val ctx = LocalContext.current
            var darkModeEnabled by remember { mutableStateOf(loadDarkModeSetting(ctx)) }
            BlueBirdTheme(darkTheme = darkModeEnabled) {
                App(
                    darkModeEnabled = darkModeEnabled,
                    onDarkModeChanged = { enabled ->
                        DSTokenStore.isDarkMode = enabled  // batched with darkModeEnabled; single recomposition
                        darkModeEnabled = enabled
                        saveDarkModeSetting(ctx, enabled)
                    },
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        applyAlarmLaunchFlags(intent)
    }

    private fun applyAlarmLaunchFlags(intent: Intent?) {
        if (intent?.getBooleanExtra(EXTRA_OPEN_ALARM, false) != true) return

        val alertType = intent.getStringExtra(EXTRA_ALERT_TYPE) ?: ""
        if (alertType != "help_request") {
            applyAlarmWindowFlags(active = true)
        }
        AlarmLaunchCoordinator.publish(
            title = intent.getStringExtra(EXTRA_ALARM_TITLE).orEmpty().ifBlank { "BlueBird Alert" },
            body = intent.getStringExtra(EXTRA_ALARM_MESSAGE).orEmpty().ifBlank { "Emergency alert received." },
            type = alertType,
        )
    }

    private fun askNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        requestPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }
}

// ── Theme ──────────────────────────────────────────────────────────────────────
// BlueBirdTheme is defined in BlueBirdTheme.kt

@Composable
private fun BlueBirdLogo(modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(20.dp),
        color = SurfaceMain,
        shadowElevation = 10.dp,
    ) {
        Image(
            painter = painterResource(id = R.drawable.bluebird_alert_logo),
            contentDescription = "BlueBird Alerts logo",
            modifier = Modifier
                .fillMaxSize()
                .padding(6.dp)
        )
    }
}

// ── Root ───────────────────────────────────────────────────────────────────────
@Composable
private fun App(darkModeEnabled: Boolean, onDarkModeChanged: (Boolean) -> Unit) {
    val ctx = LocalContext.current
    var setupDone by remember { mutableStateOf(isSetupDone(ctx)) }

    if (!setupDone) {
        LoginScreen(onDone = { setupDone = true })
    } else {
        MainScreen(
            onLogout = {
                val savedServerUrl = getServerUrl(ctx)
                prefs(ctx).edit().clear().putString(KEY_SERVER_URL, savedServerUrl).apply()
                setupDone = false
            },
            darkModeEnabled = darkModeEnabled,
            onDarkModeChanged = onDarkModeChanged,
        )
    }
}

// ── Login screen ───────────────────────────────────────────────────────────────
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LoginScreen(onDone: () -> Unit) {
    val ctx = LocalContext.current
    val focusManager = LocalFocusManager.current
    val keyboardController = LocalSoftwareKeyboardController.current
    var serverUrl by remember { mutableStateOf(getServerUrl(ctx)) }
    var schoolOptions by remember { mutableStateOf<List<SchoolOption>>(emptyList()) }
    var selectedSchoolSlug by remember { mutableStateOf(extractSchoolSlug(getServerUrl(ctx))) }
    var schoolLoadState by remember { mutableStateOf(SchoolLoadState.Loading) }
    var schoolMenuExpanded by remember { mutableStateOf(false) }
    var username by remember { mutableStateOf(getLoginName(ctx)) }
    var password by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }
    var isSubmitting by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var showOnboarding by remember { mutableStateOf(false) }
    val scrollState = rememberScrollState()
    var animateIntro by remember { mutableStateOf(false) }
    val introAlpha by animateFloatAsState(
        targetValue = if (animateIntro) 1f else 0f,
        animationSpec = tween(durationMillis = 280, easing = FastOutSlowInEasing),
        label = "login_intro_alpha",
    )
    val hapticFeedback = LocalHapticFeedback.current
    val errorShake = remember { Animatable(0f) }
    LaunchedEffect(error) {
        if (error != null) {
            repeat(3) {
                errorShake.animateTo(8f, tween(50))
                errorShake.animateTo(-8f, tween(50))
            }
            errorShake.animateTo(0f, tween(50))
        }
    }

    val submitLogin: () -> Unit = {
        val normalizedUsername = username.trim()
        if (normalizedUsername.isBlank() || password.isBlank()) {
            hapticFeedback.performHapticFeedback(HapticFeedbackType.LongPress)
            error = "Enter your username and password."
        } else if (schoolOptions.isNotEmpty() && selectedSchoolSlug.isBlank()) {
            hapticFeedback.performHapticFeedback(HapticFeedbackType.LongPress)
            error = "Select your school."
        } else {
            val normalizedServerUrl = normalizeServerUrl(serverUrl)
            isSubmitting = true
            error = null
            focusManager.clearFocus()
            val client = BackendClient(normalizedServerUrl, BuildConfig.BACKEND_API_KEY)
            kotlinx.coroutines.CoroutineScope(Dispatchers.IO).launch {
                runCatching { client.login(normalizedUsername, password) }
                    .onSuccess { user ->
                        val schoolName = schoolOptions.firstOrNull { it.slug == selectedSchoolSlug }?.name
                            ?: snakeToTitle(selectedSchoolSlug)
                        prefs(ctx).edit()
                            .putString(KEY_UID, user.userId.toString())
                            .putString(KEY_NAME, user.name)
                            .putString(KEY_ROLE, user.role)
                            .putString(KEY_LOGIN, user.loginName)
                            .putString(KEY_SCHOOL_NAME, schoolName)
                            .putString(KEY_SERVER_URL, normalizedServerUrl)
                            .putBoolean(KEY_CAN_DEACTIVATE, user.canDeactivateAlarm)
                            .putBoolean(KEY_SETUP, true)
                            .apply()
                        kotlinx.coroutines.withContext(Dispatchers.Main) {
                            isSubmitting = false
                            onDone()
                        }
                    }
                    .onFailure { e ->
                        kotlinx.coroutines.withContext(Dispatchers.Main) {
                            isSubmitting = false
                            error = e.message ?: "Sign-in failed."
                        }
                    }
            }
        }
    }

    LaunchedEffect(Unit) { animateIntro = true }

    LaunchedEffect(Unit) {
        val client = BackendClient(BuildConfig.BACKEND_BASE_URL, BuildConfig.BACKEND_API_KEY)
        runCatching { client.listSchools() }
            .onSuccess { schools ->
                schoolOptions = schools
                schoolLoadState = if (schools.isNotEmpty()) SchoolLoadState.Loaded else SchoolLoadState.Empty
                if (schools.isNotEmpty()) {
                    val savedSlug = selectedSchoolSlug
                    val chosen = schools.firstOrNull { it.slug == savedSlug } ?: schools.first()
                    selectedSchoolSlug = chosen.slug
                    serverUrl = schoolBaseUrl(chosen.slug)
                }
            }
            .onFailure {
                schoolLoadState = SchoolLoadState.Failed
                if (selectedSchoolSlug.isNotBlank()) {
                    serverUrl = schoolBaseUrl(selectedSchoolSlug)
                }
            }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .dismissKeyboardOnTap(focusManager, keyboardController)
            .background(
                Brush.verticalGradient(listOf(AppBg, AppBgDeep))
            ),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(scrollState)
                .imePadding()
                .navigationBarsPadding()
                .padding(horizontal = 24.dp, vertical = 32.dp)
                .graphicsLayer {
                    alpha = introAlpha
                    translationY = 5f * density * (1f - introAlpha)
                },
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            Surface(
                shape = RoundedCornerShape(24.dp),
                color = SurfaceMain,
                shadowElevation = 12.dp,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(20.dp),
                ) {
                    BlueBirdLogo(modifier = Modifier.size(84.dp))
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        Text(
                            "BlueBird Alerts",
                            fontSize = 32.sp,
                            fontWeight = FontWeight.Bold,
                            color = TextPri,
                        )
                        Text(
                            "Clear, fast emergency communication for school response.",
                            fontSize = 14.sp,
                            lineHeight = 20.sp,
                            color = TextMuted,
                            textAlign = TextAlign.Center,
                        )
                    }
                    Surface(
                        shape = RoundedCornerShape(14.dp),
                        color = SurfaceSoft,
                        border = BorderStroke(1.dp, BorderSoft.copy(alpha = 0.35f)),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
                            Text("School server", fontSize = 12.sp, color = TextMuted)
                            Text(
                                normalizeServerUrl(serverUrl),
                                fontSize = 14.sp,
                                color = BluePrimary,
                                fontWeight = FontWeight.Medium,
                            )
                        }
                    }
                }
            }

            if (schoolOptions.isNotEmpty()) {
                ExposedDropdownMenuBox(
                    expanded = schoolMenuExpanded,
                    onExpandedChange = { schoolMenuExpanded = !schoolMenuExpanded },
                ) {
                    val selectedSchoolName = schoolOptions.firstOrNull { it.slug == selectedSchoolSlug }?.name ?: ""
                    OutlinedTextField(
                        value = selectedSchoolName,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("School") },
                        placeholder = { Text("Select your school", color = Color.White.copy(alpha = 0.4f)) },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = schoolMenuExpanded) },
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = BluePrimary,
                            unfocusedBorderColor = DSColor.InputBorder,
                            focusedLabelColor = BluePrimary,
                            unfocusedLabelColor = Color.White.copy(alpha = 0.6f),
                            focusedTextColor = Color.White,
                            unfocusedTextColor = Color.White,
                            cursorColor = BluePrimary,
                            focusedContainerColor = DSColor.InputBackground,
                            unfocusedContainerColor = DSColor.InputBackground,
                        ),
                        modifier = Modifier
                            .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                            .fillMaxWidth()
                            .defaultMinSize(minHeight = 56.dp),
                    )
                    ExposedDropdownMenu(
                        expanded = schoolMenuExpanded,
                        onDismissRequest = { schoolMenuExpanded = false },
                    ) {
                        schoolOptions.forEach { school ->
                            DropdownMenuItem(
                                text = {
                                    Column {
                                        Text(school.name)
                                        Text(school.slug, color = TextMuted, fontSize = 12.sp)
                                    }
                                },
                                onClick = {
                                    selectedSchoolSlug = school.slug
                                    serverUrl = schoolBaseUrl(school.slug)
                                    schoolMenuExpanded = false
                                    error = null
                                },
                            )
                        }
                    }
                }
            } else {
                OutlinedTextField(
                    value = serverUrl,
                    onValueChange = {
                        serverUrl = it
                        selectedSchoolSlug = extractSchoolSlug(it)
                        error = null
                    },
                    label = { Text("School code or URL") },
                    placeholder = { Text("nn", color = Color.White.copy(alpha = 0.4f)) },
                    singleLine = true,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = BluePrimary,
                        unfocusedBorderColor = DSColor.InputBorder,
                        focusedLabelColor = BluePrimary,
                        unfocusedLabelColor = Color.White.copy(alpha = 0.6f),
                        focusedTextColor = Color.White,
                        unfocusedTextColor = Color.White,
                        cursorColor = BluePrimary,
                        focusedContainerColor = DSColor.InputBackground,
                        unfocusedContainerColor = DSColor.InputBackground,
                    ),
                    modifier = Modifier
                        .fillMaxWidth()
                        .defaultMinSize(minHeight = 56.dp),
                )
            }

            OutlinedTextField(
                value = username,
                onValueChange = {
                    username = it
                    error = null
                },
                label = { Text("Username") },
                placeholder = { Text("Enter your BlueBird username", color = Color.White.copy(alpha = 0.4f)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = BluePrimary,
                    unfocusedBorderColor = DSColor.InputBorder,
                    focusedLabelColor = BluePrimary,
                    unfocusedLabelColor = Color.White.copy(alpha = 0.6f),
                    focusedTextColor = Color.White,
                    unfocusedTextColor = Color.White,
                    cursorColor = BluePrimary,
                    focusedContainerColor = DSColor.InputBackground,
                    unfocusedContainerColor = DSColor.InputBackground,
                ),
                modifier = Modifier
                    .fillMaxWidth()
                    .defaultMinSize(minHeight = 56.dp),
            )

            OutlinedTextField(
                value = password,
                onValueChange = {
                    password = it
                    error = null
                },
                label = { Text("Password") },
                placeholder = { Text("Enter your password", color = Color.White.copy(alpha = 0.4f)) },
                singleLine = true,
                visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { if (!isSubmitting) submitLogin() }),
                trailingIcon = {
                    TextButton(onClick = { showPassword = !showPassword }) {
                        Text(if (showPassword) "Hide" else "Show", color = BlueLight, fontSize = 12.sp)
                    }
                },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = BluePrimary,
                    unfocusedBorderColor = DSColor.InputBorder,
                    focusedLabelColor = BluePrimary,
                    unfocusedLabelColor = Color.White.copy(alpha = 0.6f),
                    focusedTextColor = Color.White,
                    unfocusedTextColor = Color.White,
                    cursorColor = BluePrimary,
                    focusedContainerColor = DSColor.InputBackground,
                    unfocusedContainerColor = DSColor.InputBackground,
                ),
                modifier = Modifier
                    .fillMaxWidth()
                    .defaultMinSize(minHeight = 56.dp),
            )

            error?.let {
                Text(
                    text = it,
                    color = DSColor.Danger,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Medium,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .fillMaxWidth()
                        .graphicsLayer { translationX = errorShake.value },
                )
            }

            Text(
                when (schoolLoadState) {
                    SchoolLoadState.Loaded ->
                        "Select your school, then sign in with the username and password created in the BlueBird admin dashboard."
                    SchoolLoadState.Loading ->
                        "Loading schools from BlueBird server..."
                    SchoolLoadState.Empty ->
                        "No schools found on the backend yet. You can still enter a school code like nn, or a full school URL."
                    SchoolLoadState.Failed ->
                        "Could not reach the school list from the backend. You can still enter a school code like nn, or a full school URL."
                },
                fontSize = 13.sp,
                lineHeight = 20.sp,
                color = TextMuted,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )

            BBPrimaryButton(
                text = if (isSubmitting) "Signing In…" else "Sign In",
                onClick = submitLogin,
                enabled = !isSubmitting && username.isNotBlank() && password.isNotBlank(),
                isLoading = isSubmitting,
                modifier = Modifier.fillMaxWidth(),
            )

            TextButton(
                onClick = { showOnboarding = true },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    "New user? Get started with a code",
                    color = BluePrimary.copy(alpha = 0.85f),
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }
    }

    if (showOnboarding) {
        OnboardingSheet(
            onDone = { createdUsername ->
                if (createdUsername.isNotBlank()) username = createdUsername
                showOnboarding = false
            },
            onCancel = { showOnboarding = false },
        )
    }
}

// ── Main screen ────────────────────────────────────────────────────────────────
private enum class DashboardPanel {
    Home,
    Messaging,
    QuietPeriod,
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
private fun MainScreen(
    onLogout: () -> Unit,
    darkModeEnabled: Boolean,
    onDarkModeChanged: (Boolean) -> Unit,
    vm: MainViewModel = viewModel(),
) {
    val ctx = LocalContext.current
    val focusManager = LocalFocusManager.current
    val keyboardController = LocalSoftwareKeyboardController.current
    val state by vm.state.collectAsState()
    var showDeactivateDialog by remember { mutableStateOf(false) }
    var showAuditLogModal by remember { mutableStateOf(false) }
    var showReportDialog by remember { mutableStateOf(false) }
    var showSettingsScreen by remember { mutableStateOf(false) }
    var showQuietRequestOverlay by remember { mutableStateOf(false) }
    var showQuietDeleteConfirmOverlay by remember { mutableStateOf(false) }
    var showCancelRequestConfirmDialog by remember { mutableStateOf(false) }
    var showTeamAssistDialog by remember { mutableStateOf(false) }
    var promptRequestHelpId by remember { mutableStateOf<Int?>(null) }
    var dismissedPromptRequestHelpId by remember { mutableStateOf<Int?>(null) }
    var activePanel by remember { mutableStateOf(DashboardPanel.Home) }
    var replyTarget by remember { mutableStateOf<AdminInboxMessage?>(null) }
    var feedTab by remember { mutableStateOf(0) }
    var activationInFlight by remember { mutableStateOf(false) }
    var holdFlashActive by remember { mutableStateOf(false) }
    var holdFlashProgress by remember { mutableStateOf(0f) }
    var holdFlashColor by remember { mutableStateOf(AlarmRed) }
    var trainingModeEnabled by remember { mutableStateOf(false) }
    var trainingLabel by remember { mutableStateOf("This is a drill") }
    var pendingAlertAction by remember { mutableStateOf<SafetyAction?>(null) }
    var showEmergencyModal by remember { mutableStateOf(false) }
    var showDistrictView by remember { mutableStateOf(false) }
    var quietActionPendingId by remember { mutableStateOf<Int?>(null) }
    var quietActionPendingIsApprove by remember { mutableStateOf(true) }
    var showTenantMenu by remember { mutableStateOf(false) }
    val userName = remember { getUserName(ctx) }
    val userRole = remember { getUserRole(ctx) }
    val schoolName = remember { getSchoolName(ctx) }
    val currentUserId = remember { getUserId(ctx).toIntOrNull() }
    val canDeactivate = remember { canDeactivateAlarm(ctx) }
    val isAdmin = remember(userRole) {
        userRole.equals("admin", ignoreCase = true) ||
        userRole.equals("building_admin", ignoreCase = true) ||
        userRole.equals("district_admin", ignoreCase = true)
    }
    val isDistrictSession = remember(userRole) {
        userRole.equals("district_admin", ignoreCase = true) ||
        userRole.equals("super_admin", ignoreCase = true) ||
        userRole.equals("platform_super_admin", ignoreCase = true)
    }
    val effectiveSchoolName = state.selectedTenantName.ifBlank { schoolName }
    val isMultiTenant = state.tenants.size > 1
    var biometricsEnabled by remember { mutableStateOf(biometricsAllowed(ctx)) }
    var hapticAlertsOn by remember { mutableStateOf(hapticAlertsEnabled(ctx)) }
    var flashlightAlertsOn by remember { mutableStateOf(flashlightAlertsEnabled(ctx)) }
    var screenFlashAlertsOn by remember { mutableStateOf(screenFlashAlertsEnabled(ctx)) }
    // darkModeEnabled and onDarkModeChanged are hoisted from setContent / App()
    val safetyActions = remember(state.featureLabels) { buildSafetyActions(state.featureLabels) }
    val holdDurationMs = (state.tenantSettings.alerts.holdSeconds.toLong() * 1000L).coerceAtLeast(1000L)
    val requestHelpLabel = AppLabels.labelForFeatureKey(AppLabels.KEY_REQUEST_HELP, state.featureLabels)
    val launchEvent by AlarmLaunchCoordinator.event.collectAsState()

    val runProtectedAction: (Boolean, () -> Unit) -> Unit = { adminFeature, action ->
        if (!biometricsEnabled) {
            action()
        } else {
            val activity = ctx.findActivity()
            if (activity == null || !BiometricGate.isAvailable(ctx)) {
                // Graceful fallback: continue action when biometric is unavailable.
                action()
            } else {
                val subtitle = if (adminFeature) "Confirm admin action" else "Confirm emergency action"
                BiometricGate.authenticate(
                    activity = activity,
                    title = "BlueBird Alerts",
                    subtitle = subtitle,
                ) { ok ->
                    if (ok) {
                        action()
                    } else {
                        vm.setErrorMessage("Biometric verification was canceled.")
                    }
                }
            }
        }
    }

    LaunchedEffect(Unit) { vm.init(ctx) }
    LaunchedEffect(isAdmin) {
        if (!isAdmin) return@LaunchedEffect
        vm.refreshAdminRecipients()
        vm.refreshTeamAssistActionRecipients()
        vm.refreshAdminQuietPeriodRequests(ctx)
        vm.refreshPushDeliveryStats(ctx)
        while (true) {
            vm.refreshAdminInbox(ctx)
            vm.refreshAdminQuietPeriodRequests(ctx)
            vm.refreshPushDeliveryStats(ctx)
            delay(8_000)
        }
    }

    LaunchedEffect(isAdmin, state.activeTeamAssists) {
        if (!isAdmin) {
            promptRequestHelpId = null
            dismissedPromptRequestHelpId = null
            return@LaunchedEffect
        }
        val firstPendingId = state.activeTeamAssists
            .firstOrNull { it.status.equals("active", ignoreCase = true) && it.createdBy != currentUserId }
            ?.id
        if (firstPendingId == null) {
            promptRequestHelpId = null
            dismissedPromptRequestHelpId = null
            return@LaunchedEffect
        }
        if (promptRequestHelpId == null && dismissedPromptRequestHelpId != firstPendingId) {
            promptRequestHelpId = firstPendingId
        }
        if (promptRequestHelpId != null && state.activeTeamAssists.none { it.id == promptRequestHelpId }) {
            promptRequestHelpId = null
        }
    }

    LaunchedEffect(launchEvent?.receivedAtMillis) {
        val event = launchEvent ?: return@LaunchedEffect
        val eventSlug = event.tenantSlug
        if (eventSlug != null && eventSlug != state.selectedTenantSlug) {
            vm.setErrorMessage("Alert received for another school. Switch schools to view it.")
            return@LaunchedEffect
        }
        activePanel = DashboardPanel.Home
        showSettingsScreen = false
        showDeactivateDialog = false
        showReportDialog = false
        showQuietRequestOverlay = false
        showQuietDeleteConfirmOverlay = false
        showTeamAssistDialog = false
        replyTarget = null
        if (event.type == "help_request") {
            // Help requests: refresh the feed and switch to the help requests tab.
            // Do NOT activate emergency alarm state or show the takeover screen.
            vm.refreshIncidentFeeds()
            feedTab = 1
            return@LaunchedEffect
        }
        if (event.isSilentForMe) {
            // Sender gets discreet confirmation — no alarm takeover, no siren.
            vm.handleAlarmLaunch(event.body, isSilentForMe = true)
        } else {
            vm.handleAlarmLaunch(event.body)
        }
    }

    // Dismiss flash messages after 3s
    LaunchedEffect(state.successMsg, state.errorMsg) {
        if (state.successMsg != null || state.errorMsg != null) {
            delay(3_000)
            vm.clearMessages()
        }
    }
    LaunchedEffect(state.isBusy) {
        if (!state.isBusy) activationInFlight = false
    }

    AlarmSoundEffect(
        isAlarmActive = state.alarm.isActive,
        isTrainingAlarm = state.alarm.isTraining,
        silentForMe = state.alarm.isSilentForCurrentUser,
    )
    val alertFeedbackState = AlertFeedbackEffect(
        isAlarmActive = state.alarm.isActive,
        isTrainingAlarm = state.alarm.isTraining,
        hapticsEnabled = hapticAlertsOn,
        flashlightEnabled = flashlightAlertsOn,
        screenFlashEnabled = screenFlashAlertsOn,
        silentForMe = state.alarm.isSilentForCurrentUser,
    )
    DisposableEffect(state.alarm.isActive) {
        val activity = ctx.findActivity()
        activity?.applyAlarmWindowFlags(active = state.alarm.isActive)
        onDispose {
            if (!state.alarm.isActive) {
                activity?.applyAlarmWindowFlags(active = false)
            }
        }
    }

    // Block back navigation while an alarm is active.
    val alarmTakeoverActive = state.alarm.isActive && !state.alarm.isSilentForCurrentUser
    BackHandler(enabled = alarmTakeoverActive) {}

    Scaffold(
        containerColor = Color.Transparent,
        topBar = {
            TopAppBar(
                title = {
                    if (showSettingsScreen || effectiveSchoolName.isBlank()) {
                        Text(
                            if (showSettingsScreen) "Settings" else "BlueBird Alerts",
                            fontWeight = FontWeight.Bold,
                            color = TextPri,
                        )
                    } else if (isMultiTenant) {
                        Box {
                            TextButton(
                                onClick = { showTenantMenu = true },
                                contentPadding = PaddingValues(0.dp),
                            ) {
                                Column(verticalArrangement = Arrangement.Center) {
                                    Text(
                                        "BlueBird Alerts",
                                        fontWeight = FontWeight.Bold,
                                        color = TextPri,
                                        fontSize = 18.sp,
                                        lineHeight = 20.sp,
                                    )
                                    Row(
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(2.dp),
                                    ) {
                                        Text(
                                            effectiveSchoolName,
                                            fontWeight = FontWeight.Medium,
                                            color = DSColor.TextTertiary,
                                            fontSize = 12.sp,
                                            lineHeight = 14.sp,
                                        )
                                        Text("▾", color = DSColor.TextTertiary, fontSize = 10.sp)
                                    }
                                }
                            }
                            DropdownMenu(
                                expanded = showTenantMenu,
                                onDismissRequest = { showTenantMenu = false },
                                containerColor = SurfaceMain,
                            ) {
                                state.tenants.forEach { tenant ->
                                    DropdownMenuItem(
                                        text = {
                                            Row(
                                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                                                verticalAlignment = Alignment.CenterVertically,
                                            ) {
                                                Text(
                                                    tenant.tenantName,
                                                    color = TextPri,
                                                    fontWeight = if (tenant.tenantSlug == state.selectedTenantSlug) FontWeight.Bold else FontWeight.Normal,
                                                )
                                                if (tenant.tenantSlug == state.selectedTenantSlug) {
                                                    Text("✓", color = BluePrimary, fontWeight = FontWeight.Bold)
                                                }
                                            }
                                        },
                                        onClick = {
                                            showTenantMenu = false
                                            showDistrictView = false
                                            vm.switchTenant(ctx, tenant.tenantSlug, tenant.tenantName)
                                        },
                                    )
                                }
                            }
                        }
                    } else {
                        Column(verticalArrangement = Arrangement.Center) {
                            Text(
                                "BlueBird Alerts",
                                fontWeight = FontWeight.Bold,
                                color = TextPri,
                                fontSize = 18.sp,
                                lineHeight = 20.sp,
                            )
                            Text(
                                effectiveSchoolName,
                                fontWeight = FontWeight.Medium,
                                color = DSColor.TextTertiary,
                                fontSize = 12.sp,
                                lineHeight = 14.sp,
                            )
                        }
                    }
                },
                navigationIcon = {
                    if (showSettingsScreen) {
                        IconButton(onClick = { showSettingsScreen = false }) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Back",
                                tint = BluePrimary,
                            )
                        }
                    }
                },
                actions = {
                    if (isDistrictSession && !showSettingsScreen) {
                        TextButton(onClick = {
                            showDistrictView = !showDistrictView
                            if (showDistrictView) {
                                vm.loadDistrictOverview(ctx)
                                vm.loadDistrictQuietPeriods(ctx)
                                vm.loadDistrictAuditLog(ctx)
                            }
                        }) {
                            Text(
                                if (showDistrictView) "School" else "District",
                                color = BluePrimary,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                    }
                    if (!showSettingsScreen) {
                        TextButton(
                            onClick = {
                                showSettingsScreen = true
                                showDistrictView = false
                            },
                        ) {
                            Text(
                                "Settings",
                                color = BluePrimary,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = SurfaceMain,
                    titleContentColor = TextPri,
                ),
            )
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .dismissKeyboardOnTap(focusManager, keyboardController)
                .background(Brush.verticalGradient(listOf(AppBg, AppBgDeep))),
        ) {
            if (showSettingsScreen) {
                SettingsScreen(
                    onLogout = {
                        vm.deregisterCurrentDevice(ctx)
                        onLogout()
                    },
                    biometricsEnabled = biometricsEnabled,
                    hapticAlertsEnabled = hapticAlertsOn,
                    flashlightAlertsEnabled = flashlightAlertsOn,
                    screenFlashAlertsEnabled = screenFlashAlertsOn,
                    darkModeEnabled = darkModeEnabled,
                    isAlarmActive = state.alarm.isActive,
                    onBiometricsChanged = { enabled ->
                        biometricsEnabled = enabled
                        setBiometricsAllowed(ctx, enabled)
                        if (enabled && !BiometricGate.isAvailable(ctx)) {
                            Toast.makeText(
                                ctx,
                                "Biometrics unavailable on this device. Actions will fall back to standard confirmation.",
                                Toast.LENGTH_LONG,
                            ).show()
                        }
                    },
                    onHapticAlertsChanged = { enabled ->
                        hapticAlertsOn = enabled
                        setHapticAlertsEnabled(ctx, enabled)
                    },
                    onFlashlightAlertsChanged = { enabled ->
                        flashlightAlertsOn = enabled
                        setFlashlightAlertsEnabled(ctx, enabled)
                    },
                    onScreenFlashAlertsChanged = { enabled ->
                        screenFlashAlertsOn = enabled
                        setScreenFlashAlertsEnabled(ctx, enabled)
                    },
                    onDarkModeChanged = onDarkModeChanged,
                )
            } else if (showDistrictView) {
                DistrictOverviewScreen(
                    tenants = state.districtTenants,
                    quietRequests = state.districtQuietRequests,
                    auditLog = state.districtAuditLog,
                    isBusy = state.isBusy,
                    onRefresh = {
                        vm.loadDistrictOverview(ctx)
                        vm.loadDistrictQuietPeriods(ctx)
                        vm.loadDistrictAuditLog(ctx)
                    },
                    onApproveQuiet = { requestId, tenantSlug -> vm.approveDistrictQuietRequest(ctx, requestId, tenantSlug) },
                    onDenyQuiet = { requestId, tenantSlug -> vm.denyDistrictQuietRequest(ctx, requestId, tenantSlug) },
                    modifier = Modifier.fillMaxSize(),
                )
            } else {
                Column(
                    modifier = Modifier.fillMaxSize(),
                ) {
                    Surface(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 20.dp, vertical = 16.dp),
                        color = SurfaceMain,
                        shape = RoundedCornerShape(24.dp),
                        shadowElevation = 6.dp,
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(14.dp),
                            ) {
                                BlueBirdLogo(modifier = Modifier.size(52.dp))
                                Column {
                                    Text("BlueBird Alerts", fontWeight = FontWeight.Bold, fontSize = 20.sp, color = TextPri)
                                    Text(
                                        if (userName.isNotBlank()) "$userName • ${snakeToTitle(userRole)}" else "School Safety",
                                        fontSize = 12.sp,
                                        color = TextMuted,
                                    )
                                    if (effectiveSchoolName.isNotBlank()) {
                                        Text(
                                            effectiveSchoolName,
                                            fontSize = 11.sp,
                                            color = DSColor.TextTertiary,
                                        )
                                    }
                                }
                            }
                            ConnectionDot(state.connected)
                        }
                    }

                    // ── Flash messages ───────────────────────────────────────
                    state.successMsg?.let {
                        FlashBanner(it, isError = false)
                    }
                    state.errorMsg?.let {
                        FlashBanner(it, isError = true)
                    }
                    state.quietPeriodStatus?.let { quiet ->
                        QuietPeriodStatusBanner(
                            status = quiet,
                            isBusy = state.isBusy,
                            onDeletePending = { vm.deleteQuietPeriodRequest(ctx) },
                            onDeleteApproved = { showQuietDeleteConfirmOverlay = true },
                        )
                    }

                    // ── Scrollable content ────────────────────────────────────
                    Column(
                        modifier = Modifier
                            .weight(1f)
                            .verticalScroll(rememberScrollState()),
                    ) {
                    AlarmBanner(
                        alarm = state.alarm,
                        schoolName = effectiveSchoolName,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 20.dp, vertical = 8.dp),
                    )
                    if (!state.alarm.isActive) {
                        CircularEmergencyButton(
                            enabled = !state.isBusy && !activationInFlight,
                            holdDurationMs = holdDurationMs,
                            onHoldComplete = { showEmergencyModal = true },
                            onHoldVisual = { active, progress, color ->
                                holdFlashActive = active
                                holdFlashProgress = progress.coerceIn(0f, 1f)
                                holdFlashColor = color
                            },
                            modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                        )
                    }

                    ActiveSafetyFeedCard(
                        selectedTab = feedTab,
                        onSelectTab = { feedTab = it },
                        alarm = state.alarm,
                        canDeactivate = canDeactivate,
                        incidents = state.activeIncidents,
                        teamAssists = state.activeTeamAssists,
                        featureLabels = state.featureLabels,
                        isAdmin = isAdmin,
                        currentUserId = currentUserId,
                        actionRecipients = state.teamAssistActionRecipients,
                        isBusy = state.isBusy,
                        isRefreshing = state.isRefreshingFeed,
                        onRefresh = { vm.refreshIncidentFeeds() },
                        onDeactivateAlarm = {
                            showDeactivateDialog = true
                        },
                        onTeamAssistAction = { teamAssistId, action, forwardToUserId ->
                            runProtectedAction(true) {
                                vm.updateRequestHelpAction(
                                    ctx = ctx,
                                    teamAssistId = teamAssistId,
                                    action = action,
                                    forwardToUserId = forwardToUserId,
                                )
                            }
                        },
                        onTeamAssistCancel = { teamAssistId, reasonText, reasonCategory ->
                            runProtectedAction(true) {
                                vm.cancelTeamAssist(ctx = ctx, teamAssistId = teamAssistId, reasonText = reasonText, reasonCategory = reasonCategory)
                            }
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 20.dp, vertical = 8.dp),
                    )

                    if (state.alarm.broadcasts.isNotEmpty()) {
                        BroadcastsCard(
                            broadcasts = state.alarm.broadcasts,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 20.dp, vertical = 8.dp),
                        )
                    }
                    DashboardPanelTabsCard(
                        activePanel = activePanel,
                        onSelectPanel = { activePanel = it },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 20.dp, vertical = 8.dp),
                    )

                    if (activePanel == DashboardPanel.Messaging) {
                        if (isAdmin) {
                            AdminInboxCard(
                                messages = state.adminInbox,
                                unreadCount = state.unreadAdminMessages,
                                recipients = state.adminMessageRecipients,
                                isBusy = state.isBusy,
                                onSendMessage = { message, recipientUserIds, sendToAll ->
                                    runProtectedAction(true) {
                                        vm.sendAdminMessageToUsers(
                                            ctx = ctx,
                                            message = message,
                                            recipientUserIds = recipientUserIds,
                                            sendToAll = sendToAll,
                                        )
                                    }
                                },
                                onReply = { replyTarget = it },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 20.dp, vertical = 8.dp),
                            )
                        } else {
                            UserMessageAdminCard(
                                isBusy = state.isBusy,
                                onSend = { message -> vm.sendAdminMessage(ctx, message) },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 20.dp, vertical = 8.dp),
                            )
                        }
                    }

                    if (activePanel == DashboardPanel.QuietPeriod) {
                        val qStatus = state.quietPeriodStatus?.status?.lowercase()
                        if (qStatus == "pending" || qStatus == "scheduled") {
                            PendingQuietRequestCard(
                                status = state.quietPeriodStatus!!,
                                isBusy = state.isBusy,
                                onCancelRequest = { showCancelRequestConfirmDialog = true },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 20.dp, vertical = 8.dp),
                            )
                        } else {
                            OutlinedButton(
                                onClick = { showQuietRequestOverlay = true },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 20.dp, vertical = 8.dp)
                                    .height(52.dp),
                                shape = RoundedCornerShape(14.dp),
                                enabled = !state.isBusy,
                                colors = ButtonDefaults.outlinedButtonColors(contentColor = Color(0xFF7C3AED)),
                            ) {
                                Text("Request Quiet Period", fontWeight = FontWeight.SemiBold)
                            }
                        }
                        if (isAdmin) {
                            AdminQuietPeriodRequestsCard(
                                requests = state.adminQuietPeriodRequests,
                                isBusy = state.isBusy,
                                onApprove = { requestId ->
                                    quietActionPendingId = requestId
                                    quietActionPendingIsApprove = true
                                },
                                onDeny = { requestId ->
                                    quietActionPendingId = requestId
                                    quietActionPendingIsApprove = false
                                },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 20.dp, vertical = 8.dp),
                            )
                            PushDeliveryStatsCard(
                                stats = state.pushDeliveryStats,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 20.dp, vertical = 4.dp),
                            )
                            AuditLogButtonCard(
                                onClick = { showAuditLogModal = true },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 20.dp, vertical = 4.dp),
                            )
                        }
                    }

                    // ── Action buttons ───────────────────────────────────────
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 20.dp, vertical = 24.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        if (state.alarm.isActive) {
                            OutlinedButton(
                                onClick = { showReportDialog = true },
                                modifier = Modifier.fillMaxWidth().height(52.dp),
                                shape = RoundedCornerShape(14.dp),
                                enabled = !state.isBusy,
                                colors = ButtonDefaults.outlinedButtonColors(contentColor = BlueLight),
                            ) {
                            Text("Send Update To Admins", fontWeight = FontWeight.SemiBold)
                            }
                        }

                        OutlinedButton(
                            onClick = { showTeamAssistDialog = true },
                            modifier = Modifier.fillMaxWidth().height(52.dp),
                            shape = RoundedCornerShape(14.dp),
                            enabled = !state.isBusy,
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = Color(0xFF0F766E)),
                        ) {
                            Text(requestHelpLabel, fontWeight = FontWeight.SemiBold)
                        }

                        if (isAdmin) {
                            Surface(
                                color = SurfaceMain,
                                shape = RoundedCornerShape(18.dp),
                                shadowElevation = 2.dp,
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Column(
                                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                                    verticalArrangement = Arrangement.spacedBy(10.dp),
                                ) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Column {
                                            Text("Training Mode", color = TextPri, fontWeight = FontWeight.Bold)
                                            Text(
                                                "Drill alerts stay local and skip live push/SMS.",
                                                color = TextMuted,
                                                fontSize = 12.sp,
                                            )
                                        }
                                        Switch(
                                            checked = trainingModeEnabled,
                                            onCheckedChange = { trainingModeEnabled = it },
                                        )
                                    }
                                    if (trainingModeEnabled) {
                                        OutlinedTextField(
                                            value = trainingLabel,
                                            onValueChange = { trainingLabel = it },
                                            modifier = Modifier.fillMaxWidth(),
                                            label = { Text("Training Label") },
                                            placeholder = { Text("This is a drill") },
                                            singleLine = true,
                                        )
                                    }
                                }
                            }
                        }

                        Text(
                            "Version ${BuildConfig.VERSION_NAME}  ·  ${BuildConfig.BACKEND_BASE_URL}",
                            fontSize = 11.sp,
                            color = TextMuted,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    }
                }
            }

            if (holdFlashActive) {
                val transition = rememberInfiniteTransition(label = "holdFlash")
                val pulse by transition.animateFloat(
                    initialValue = 0f,
                    targetValue = 1f,
                    animationSpec = infiniteRepeatable(
                        animation = tween(durationMillis = 560, easing = FastOutSlowInEasing),
                        repeatMode = RepeatMode.Reverse,
                    ),
                    label = "flashPulse",
                )
                val flashAlpha = (0.035f + holdFlashProgress * 0.09f) + ((0.03f + holdFlashProgress * 0.07f) * pulse)
                val countdown = maxOf(1, kotlin.math.ceil((1f - holdFlashProgress).coerceIn(0f, 1f) * (holdDurationMs / 1000f)).toInt())
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(holdFlashColor.copy(alpha = flashAlpha.coerceAtMost(0.22f))),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = countdown.toString(),
                        fontSize = 118.sp,
                        fontWeight = FontWeight.Black,
                        color = Color.White.copy(alpha = (0.45f + pulse * 0.40f).coerceAtMost(0.9f)),
                        modifier = Modifier.graphicsLayer {
                            val scale = 0.9f + pulse * 0.2f
                            scaleX = scale
                            scaleY = scale
                            shadowElevation = 16f
                        },
                        textAlign = TextAlign.Center,
                    )
                }
            }

            AdminEventModal(
                events = state.pendingAdminEvents,
                onDismiss = { id -> vm.dismissAdminEvent(id) },
            )

            val currentQuietModal = state.pendingAdminQuietModals.firstOrNull()
            if (currentQuietModal != null && !state.alarm.isActive) {
                AdminQuietRequestModal(
                    event = currentQuietModal,
                    onApprove = {
                        quietActionPendingId = currentQuietModal.requestId
                        quietActionPendingIsApprove = true
                        vm.dequeueAdminQuietModal(currentQuietModal.id)
                    },
                    onDeny = {
                        quietActionPendingId = currentQuietModal.requestId
                        quietActionPendingIsApprove = false
                        vm.dequeueAdminQuietModal(currentQuietModal.id)
                    },
                    onView = {
                        activePanel = DashboardPanel.QuietPeriod
                        showSettingsScreen = false
                        showDistrictView = false
                        vm.dequeueAdminQuietModal(currentQuietModal.id)
                    },
                    onDismiss = {
                        vm.dequeueAdminQuietModal(currentQuietModal.id)
                    },
                )
            }

            if (alertFeedbackState.screenFlashAlpha > 0f) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(alertFeedbackState.screenFlashColor.copy(alpha = alertFeedbackState.screenFlashAlpha))
                        .zIndex(18f),
                )
            }

            if (alarmTakeoverActive) {
                EmergencyAlarmTakeover(
                    alarm = state.alarm,
                    schoolName = effectiveSchoolName,
                    canDeactivate = canDeactivate,
                    isBusy = state.isBusy,
                    onDeactivate = {
                        showDeactivateDialog = true
                    },
                    onAcknowledge = {
                        vm.acknowledgeAlarm(ctx)
                    },
                    onSendMessage = { message ->
                        vm.sendAlertMessageFromOverlay(ctx, message)
                    },
                    modifier = Modifier
                        .fillMaxSize()
                        .zIndex(20f),
                )
            }
        }
    }

    if (showQuietRequestOverlay) {
        QuietPeriodRequestOverlay(
            isBusy = state.isBusy,
            errorMsg = state.errorMsg,
            onCancel = { showQuietRequestOverlay = false },
            onConfirm = { reason, scheduledStartAt, scheduledEndAt ->
                vm.requestQuietPeriod(ctx, reason, scheduledStartAt, scheduledEndAt)
            },
            onSuccess = { showQuietRequestOverlay = false },
        )
    }
    if (showQuietDeleteConfirmOverlay) {
        QuietPeriodDeleteConfirmOverlay(
            isBusy = state.isBusy,
            onCancel = { showQuietDeleteConfirmOverlay = false },
            onConfirm = {
                showQuietDeleteConfirmOverlay = false
                runProtectedAction(false) { vm.deleteQuietPeriodRequest(ctx) }
            },
        )
    }
    if (showCancelRequestConfirmDialog) {
        val cancelQStatus = state.quietPeriodStatus?.status?.lowercase()
        val isScheduledCancel = cancelQStatus == "scheduled"
        AlertDialog(
            onDismissRequest = { if (!state.isBusy) showCancelRequestConfirmDialog = false },
            containerColor = DSColor.Card,
            title = {
                Text(
                    if (isScheduledCancel) "Cancel Scheduled Period?" else "Cancel Request?",
                    color = DSColor.TextPrimary,
                    fontWeight = FontWeight.Bold,
                )
            },
            text = {
                Text(
                    if (isScheduledCancel) "This will cancel your scheduled quiet period." else "This will cancel your pending quiet period request.",
                    color = DSColor.TextSecondary,
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        showCancelRequestConfirmDialog = false
                        runProtectedAction(false) { vm.deleteQuietPeriodRequest(ctx) }
                    },
                    enabled = !state.isBusy,
                    colors = ButtonDefaults.buttonColors(containerColor = DSColor.Danger),
                ) {
                    Text(if (isScheduledCancel) "Cancel Scheduled Period" else "Cancel Request", fontWeight = FontWeight.SemiBold)
                }
            },
            dismissButton = {
                TextButton(onClick = { if (!state.isBusy) showCancelRequestConfirmDialog = false }) {
                    Text(if (isScheduledCancel) "Keep Scheduled Period" else "Keep Request", color = DSColor.TextSecondary, fontWeight = FontWeight.SemiBold)
                }
            },
        )
    }
    if (showTeamAssistDialog) {
        TeamAssistDialog(
            titleLabel = requestHelpLabel,
            isBusy = state.isBusy,
            onDismiss = { showTeamAssistDialog = false },
            onConfirm = { type ->
                showTeamAssistDialog = false
                vm.requestHelp(ctx, type)
            },
        )
    }

    if (showAuditLogModal) {
        AuditLogsModal(
            client = vm.getClient(),
            userId = getUserId(ctx).toIntOrNull() ?: 0,
            onDismiss = { showAuditLogModal = false },
        )
    }

    val promptRequest = promptRequestHelpId?.let { id ->
        state.activeTeamAssists.firstOrNull { it.id == id }
    }
    if (isAdmin && promptRequest != null) {
        AlertDialog(
            onDismissRequest = {
                dismissedPromptRequestHelpId = promptRequest.id
                promptRequestHelpId = null
            },
            containerColor = SurfaceMain,
            title = { Text("Incoming $requestHelpLabel", color = TextPri, fontWeight = FontWeight.Bold) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        "From #${promptRequest.createdBy} • ${formatIsoForBanner(promptRequest.createdAt) ?: promptRequest.createdAt}",
                        color = TextMuted,
                        fontSize = 13.sp,
                    )
                    Text("Acknowledge to log receipt, or Resolve to close the request.", color = TextPri, fontSize = 14.sp)
                }
            },
            confirmButton = {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(
                        enabled = !state.isBusy,
                        onClick = {
                            dismissedPromptRequestHelpId = promptRequest.id
                            promptRequestHelpId = null
                            runProtectedAction(true) {
                                vm.updateRequestHelpAction(
                                    ctx = ctx,
                                    teamAssistId = promptRequest.id,
                                    action = "acknowledge",
                                )
                            }
                        },
                    ) {
                        Text("Acknowledge", color = BluePrimary, fontWeight = FontWeight.SemiBold)
                    }
                    Button(
                        enabled = !state.isBusy,
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF0F766E)),
                        onClick = {
                            dismissedPromptRequestHelpId = promptRequest.id
                            promptRequestHelpId = null
                            runProtectedAction(true) {
                                vm.updateRequestHelpAction(
                                    ctx = ctx,
                                    teamAssistId = promptRequest.id,
                                    action = "resolve",
                                )
                            }
                        },
                    ) {
                        Text("Resolve", fontWeight = FontWeight.SemiBold)
                    }
                }
            },
            dismissButton = {
                TextButton(
                    onClick = {
                        dismissedPromptRequestHelpId = promptRequest.id
                        promptRequestHelpId = null
                    },
                ) {
                    Text("Later", color = TextMuted)
                }
            },
        )
    }

    // ── Dialogs ───────────────────────────────────────────────────────────────
    val pendingQid = quietActionPendingId
    val pendingQApprove = quietActionPendingIsApprove
    if (pendingQid != null) {
        ConfirmDialog(
            title = if (pendingQApprove) "Approve Quiet Period?" else "Deny Quiet Period?",
            body = if (pendingQApprove) "Approve this quiet period request?" else "Deny this quiet period request?",
            confirmLabel = if (pendingQApprove) "Approve" else "Deny",
            onConfirm = {
                quietActionPendingId = null
                runProtectedAction(true) {
                    if (pendingQApprove) vm.approveQuietPeriodRequest(ctx, pendingQid)
                    else vm.denyQuietPeriodRequest(ctx, pendingQid)
                }
            },
            onDismiss = { quietActionPendingId = null },
        )
    }

    if (showDeactivateDialog) {
        ConfirmDialog(
            title = "Deactivate alarm?",
            body = "This will clear the active alarm for the whole school. Only admins can do this.",
            confirmLabel = "Deactivate",
            onConfirm = {
                showDeactivateDialog = false
                runProtectedAction(true) { vm.deactivateAlarm(ctx) }
            },
            onDismiss = { showDeactivateDialog = false },
        )
    }

    if (showReportDialog) {
        ReportDialog(
            isBusy = state.isBusy,
            onConfirm = { category, note ->
                showReportDialog = false
                vm.sendReport(ctx, category, note)
            },
            onDismiss = { showReportDialog = false },
        )
    }

    replyTarget?.let { target ->
        AdminReplyDialog(
            target = target,
            isBusy = state.isBusy,
            onDismiss = { replyTarget = null },
            onConfirm = { reply ->
                replyTarget = null
                runProtectedAction(true) { vm.replyToAdminMessage(ctx, target.messageId, reply) }
            },
        )
    }

    if (showEmergencyModal) {
        EmergencyTypeModal(
            actions = safetyActions,
            onSelect = { action ->
                showEmergencyModal = false
                activationInFlight = true
                pendingAlertAction = action
            },
            onDismiss = { showEmergencyModal = false },
        )
    }

    pendingAlertAction?.let { action ->
        AlertDialog(
            onDismissRequest = {
                pendingAlertAction = null
                activationInFlight = false
            },
            containerColor = SurfaceMain,
            title = { Text("Activate ${action.title}?", color = TextPri, fontWeight = FontWeight.Bold) },
            text = {
                val school = effectiveSchoolName
                Text(
                    if (school.isNotBlank()) "This will send an emergency alert to all devices at $school."
                    else "This will send an emergency alert to all registered devices.",
                    color = TextMuted,
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        val a = pendingAlertAction
                        if (a != null) {
                            pendingAlertAction = null
                            runProtectedAction(false) {
                                runCatching {
                                    vm.activateAlarm(ctx, a.message, isTraining = trainingModeEnabled, trainingLabel = trainingLabel)
                                }.onFailure { err ->
                                    activationInFlight = false
                                    Log.e(TAG_ACTIVATION, "activateAlarm failed", err)
                                    vm.setErrorMessage("Failed to activate alarm.")
                                }
                            }
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = AlarmRed),
                ) {
                    Text("Activate", fontWeight = FontWeight.Bold)
                }
            },
            dismissButton = {
                TextButton(onClick = {
                    pendingAlertAction = null
                    activationInFlight = false
                }) {
                    Text("Cancel", color = TextMuted)
                }
            },
        )
    }
}

// ── Composable components ──────────────────────────────────────────────────────

@Composable
private fun CircularEmergencyButton(
    enabled: Boolean,
    holdDurationMs: Long,
    onHoldComplete: () -> Unit,
    onHoldVisual: (Boolean, Float, Color) -> Unit,
    modifier: Modifier = Modifier,
) {
    val scope = rememberCoroutineScope()
    val haptic = LocalHapticFeedback.current
    val configuration = LocalConfiguration.current
    val screenWidth = configuration.screenWidthDp.dp
    val buttonSize = (screenWidth * 0.4f).coerceIn(180.dp, 320.dp)
    val innerSize = buttonSize * (130f / 148f)
    val strokeWidth = (buttonSize * 0.054f).coerceIn(6.dp, 14.dp)
    val iconFontSize = with(LocalDensity.current) { (buttonSize * 0.31f).toSp() }
    val holdProgress = remember { Animatable(0f) }
    var holdState by remember { mutableStateOf(HoldActivationUiState.Idle) }
    var holdJob by remember { mutableStateOf<Job?>(null) }
    var triggered by remember { mutableStateOf(false) }
    var lastHapticSecond by remember { mutableStateOf(-1) }

    val ringColor by animateColorAsState(
        targetValue = when {
            holdProgress.value >= 0.8f -> AlarmRed
            holdProgress.value >= 0.55f -> DSColor.Warning
            else -> Color.White.copy(alpha = 0.85f)
        },
        animationSpec = tween(durationMillis = 150),
        label = "circRingColor",
    )
    val buttonScale by animateFloatAsState(
        targetValue = when (holdState) {
            HoldActivationUiState.Idle, HoldActivationUiState.Canceled -> 1f
            HoldActivationUiState.Triggered -> 1.10f
            else -> 0.97f + (holdProgress.value * 0.10f)
        },
        animationSpec = spring(dampingRatio = 0.82f, stiffness = Spring.StiffnessMediumLow),
        label = "circScale",
    )

    fun cancelHold(userCancelled: Boolean) {
        holdJob?.cancel()
        holdJob = null
        if (userCancelled && !triggered && holdProgress.value > 0.01f) {
            haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
            holdState = HoldActivationUiState.Canceled
        }
        lastHapticSecond = -1
        scope.launch {
            holdProgress.animateTo(0f, tween(durationMillis = 200, easing = FastOutSlowInEasing))
            if (holdState != HoldActivationUiState.Triggered) holdState = HoldActivationUiState.Idle
            triggered = false
            onHoldVisual(false, 0f, AlarmRed)
        }
    }

    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier
                .size(buttonSize)
                .pointerInput(enabled, holdDurationMs) {
                    detectTapGestures(
                        onPress = {
                            if (!enabled || holdJob?.isActive == true) return@detectTapGestures
                            holdState = HoldActivationUiState.Pressing
                            haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                            holdJob = scope.launch {
                                val start = withFrameNanos { it }
                                holdProgress.snapTo(0f)
                                onHoldVisual(true, 0f, AlarmRed)
                                while (isActive) {
                                    val now = withFrameNanos { it }
                                    val elapsedMs = ((now - start) / 1_000_000L).coerceAtLeast(0L)
                                    val progress = (elapsedMs.toFloat() / holdDurationMs.toFloat()).coerceIn(0f, 1f)
                                    holdProgress.snapTo(progress)
                                    onHoldVisual(true, progress, AlarmRed)
                                    holdState = when {
                                        progress >= 1f -> HoldActivationUiState.Triggered
                                        progress >= 0.8f -> HoldActivationUiState.NearComplete
                                        progress > 0.02f -> HoldActivationUiState.Holding
                                        else -> HoldActivationUiState.Pressing
                                    }
                                    val remainingSeconds = kotlin.math.ceil((holdDurationMs - elapsedMs) / 1000f).toInt().coerceAtLeast(0)
                                    if (remainingSeconds != lastHapticSecond) {
                                        haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                                        lastHapticSecond = remainingSeconds
                                    }
                                    if (progress >= 1f && !triggered) {
                                        triggered = true
                                        lastHapticSecond = -1
                                        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                        onHoldVisual(false, 0f, AlarmRed)
                                        onHoldComplete()
                                        return@launch
                                    }
                                }
                            }
                            val released = tryAwaitRelease()
                            if (!triggered) cancelHold(userCancelled = released)
                        },
                    )
                }
                .alpha(if (enabled) 1f else 0.5f),
        ) {
            CircularProgressIndicator(
                progress = { 1f },
                color = AlarmRed.copy(alpha = 0.20f),
                strokeWidth = strokeWidth,
                modifier = Modifier.fillMaxSize(),
            )
            CircularProgressIndicator(
                progress = { holdProgress.value },
                color = ringColor,
                strokeWidth = strokeWidth,
                modifier = Modifier.fillMaxSize(),
            )
            Surface(
                shape = CircleShape,
                color = AlarmRed,
                modifier = Modifier
                    .size(innerSize)
                    .graphicsLayer {
                        scaleX = buttonScale
                        scaleY = buttonScale
                    },
                shadowElevation = (8f + holdProgress.value * 18f).dp,
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text("🚨", fontSize = iconFontSize)
                }
            }
        }
        Text(
            when (holdState) {
                HoldActivationUiState.Idle, HoldActivationUiState.Pressing -> "Hold to Activate"
                HoldActivationUiState.Holding -> "Keep Holding…"
                HoldActivationUiState.NearComplete -> "Almost There…"
                HoldActivationUiState.Triggered -> "Activating…"
                HoldActivationUiState.Canceled -> "Hold to Activate"
            },
            color = TextMuted,
            fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold,
        )
    }
    DisposableEffect(Unit) {
        onDispose {
            holdJob?.cancel()
            onHoldVisual(false, 0f, AlarmRed)
        }
    }
}

@Composable
private fun EmergencyTypeModal(
    actions: List<SafetyAction>,
    onSelect: (SafetyAction) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = SurfaceMain,
        title = { Text("Select Emergency Type", color = TextPri, fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                actions.forEach { action ->
                    Surface(
                        onClick = { onSelect(action) },
                        color = action.color.copy(alpha = 0.12f),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(14.dp),
                        ) {
                            Text(action.symbol, fontSize = 24.sp)
                            Text(
                                action.title,
                                color = TextPri,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 15.sp,
                            )
                        }
                    }
                }
            }
        },
        confirmButton = {},
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel", color = TextMuted)
            }
        },
    )
}

@Composable
private fun ConnectionDot(connected: Boolean?) {
    val color = when (connected) {
        true  -> AlarmGreen
        false -> AlarmRed
        null  -> TextMuted
    }
    val label = when (connected) {
        true  -> "Connected"
        false -> "Offline"
        null  -> "Checking…"
    }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Box(
            modifier = Modifier
                .size(10.dp)
                .clip(CircleShape)
                .background(color)
        )
        Text(label, fontSize = 12.sp, color = TextMuted)
    }
}

@Composable
private fun FlashBanner(message: String, isError: Boolean) {
    val bg = if (isError) AlarmRed.copy(alpha = 0.12f) else AlarmGreen.copy(alpha = 0.12f)
    val fg = if (isError) AlarmRed else AlarmGreen
    val border = if (isError) AlarmRed.copy(alpha = 0.28f) else AlarmGreen.copy(alpha = 0.28f)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 4.dp)
            .background(bg, RoundedCornerShape(12.dp))
            .border(1.dp, border, RoundedCornerShape(12.dp))
            .padding(14.dp),
    ) {
        Text(message, color = fg, fontSize = 14.sp)
    }
}

@Composable
private fun DashboardPanelTabsCard(
    activePanel: DashboardPanel,
    onSelectPanel: (DashboardPanel) -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        color = SurfaceMain,
        shape = RoundedCornerShape(20.dp),
        shadowElevation = 4.dp,
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Dashboard", color = TextPri, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(
                    onClick = { onSelectPanel(DashboardPanel.Home) },
                    modifier = Modifier.weight(1f).height(44.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (activePanel == DashboardPanel.Home) BlueDark else SurfaceSoft,
                        contentColor = if (activePanel == DashboardPanel.Home) Color.White else TextPri,
                    ),
                    shape = RoundedCornerShape(16.dp),
                ) {
                    Text("Home", fontWeight = FontWeight.SemiBold, fontSize = 13.sp, maxLines = 1)
                }

                Button(
                    onClick = { onSelectPanel(DashboardPanel.Messaging) },
                    modifier = Modifier.weight(1f).height(44.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (activePanel == DashboardPanel.Messaging) BluePrimary else SurfaceSoft,
                        contentColor = if (activePanel == DashboardPanel.Messaging) Color.White else TextPri,
                    ),
                    shape = RoundedCornerShape(16.dp),
                ) {
                    Text("Messaging", fontWeight = FontWeight.SemiBold, fontSize = 13.sp, maxLines = 1)
                }

                Button(
                    onClick = { onSelectPanel(DashboardPanel.QuietPeriod) },
                    modifier = Modifier.weight(1f).height(44.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (activePanel == DashboardPanel.QuietPeriod) QuietPurple else QuietPurple.copy(alpha = 0.75f),
                        contentColor = Color.White,
                    ),
                    shape = RoundedCornerShape(16.dp),
                ) {
                    Text(
                        "Quiet Period",
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 12.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

@Composable
private fun UserMessageAdminCard(
    isBusy: Boolean,
    onSend: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var message by remember { mutableStateOf("") }
    Surface(
        modifier = modifier,
        color = SurfaceMain,
        shape = RoundedCornerShape(20.dp),
        shadowElevation = 4.dp,
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Message Admin", color = TextPri, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            OutlinedTextField(
                value = message,
                onValueChange = { message = it },
                label = { Text("Message", color = TextMuted) },
                placeholder = { Text("Need help in room 204", color = TextMuted) },
                minLines = 2,
                maxLines = 4,
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = BluePrimary,
                    unfocusedBorderColor = BorderSoft,
                    focusedTextColor = TextPri,
                    unfocusedTextColor = TextPri,
                    cursorColor = BluePrimary,
                    focusedContainerColor = SurfaceSoft,
                    unfocusedContainerColor = SurfaceSoft,
                ),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = {
                    onSend(message.trim())
                    message = ""
                },
                enabled = !isBusy && message.isNotBlank(),
                modifier = Modifier.fillMaxWidth().height(46.dp),
                colors = ButtonDefaults.buttonColors(containerColor = BluePrimary),
                shape = RoundedCornerShape(12.dp),
            ) {
                Text("Send Message", fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@Composable
private fun ActiveSafetyFeedCard(
    selectedTab: Int,
    onSelectTab: (Int) -> Unit,
    alarm: AlarmStatus,
    canDeactivate: Boolean,
    incidents: List<IncidentFeedItem>,
    teamAssists: List<TeamAssistFeedItem>,
    featureLabels: Map<String, String>,
    isAdmin: Boolean,
    currentUserId: Int?,
    actionRecipients: List<TeamAssistActionRecipient>,
    isBusy: Boolean,
    isRefreshing: Boolean,
    onRefresh: () -> Unit,
    onDeactivateAlarm: () -> Unit,
    onTeamAssistAction: (Int, String, Int?) -> Unit,
    onTeamAssistCancel: (Int, String, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        color = SurfaceMain,
        shape = RoundedCornerShape(20.dp),
        shadowElevation = 8.dp,
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Active Feed", color = TextPri, fontWeight = FontWeight.Bold, fontSize = DSTypography.Body)
                TextButton(onClick = onRefresh, enabled = !isRefreshing) {
                    Text(if (isRefreshing) "Refreshing…" else "Refresh", color = BluePrimary, fontSize = DSTypography.Caption)
                }
            }
            if (alarm.isActive && canDeactivate) {
                DangerButton(
                    text = if (isBusy) "Working…" else if (alarm.isTraining) "End Training Alert" else "Deactivate Alarm",
                    onClick = onDeactivateAlarm,
                    enabled = !isBusy,
                    isLoading = isBusy,
                    modifier = Modifier.fillMaxWidth().height(52.dp),
                )
            }
            TabRow(
                selectedTabIndex = selectedTab,
                containerColor = Color.Transparent,
                contentColor = BluePrimary,
            ) {
                Tab(selected = selectedTab == 0, onClick = { onSelectTab(0) }, text = { Text("Emergencies") })
                Tab(selected = selectedTab == 1, onClick = { onSelectTab(1) }, text = { Text(AppLabels.ACTIVE_HELP_REQUESTS) })
            }
            if (selectedTab == 0) {
                if (incidents.isEmpty()) {
                    Text("No active incidents.", color = TextMuted, fontSize = 13.sp)
                } else {
                    incidents.take(8).forEach { incident ->
                        FeedRow(
                            title = snakeToTitle(incident.type),
                            subtitle = "${formatIsoForBanner(incident.createdAt) ?: incident.createdAt} • by #${incident.createdBy}",
                            tone = Color(0xFF1D4ED8),
                        )
                    }
                }
            } else {
                if (teamAssists.isEmpty()) {
                    Text(AppLabels.NO_ACTIVE_HELP_REQUESTS, color = TextMuted, fontSize = 13.sp)
                } else {
                    teamAssists.take(8).forEach { teamAssist ->
                        TeamAssistRow(
                            teamAssist = teamAssist,
                            featureLabels = featureLabels,
                            isAdmin = isAdmin,
                            currentUserId = currentUserId,
                            actionRecipients = actionRecipients,
                            isBusy = isBusy,
                            onTeamAssistAction = onTeamAssistAction,
                            onTeamAssistCancel = onTeamAssistCancel,
                        )
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TeamAssistRow(
    teamAssist: TeamAssistFeedItem,
    featureLabels: Map<String, String>,
    isAdmin: Boolean,
    currentUserId: Int?,
    actionRecipients: List<TeamAssistActionRecipient>,
    isBusy: Boolean,
    onTeamAssistAction: (Int, String, Int?) -> Unit,
    onTeamAssistCancel: (Int, String, String) -> Unit,
) {
    var showForwardDialog by remember(teamAssist.id) { mutableStateOf(false) }
    var showCancelDialog by remember(teamAssist.id) { mutableStateOf(false) }
    var forwardQuery by remember(teamAssist.id) { mutableStateOf("") }
    var cancelReasonText by remember(teamAssist.id) { mutableStateOf("") }
    var cancelReasonCategory by remember(teamAssist.id) { mutableStateOf("") }
    var cancelCategoryExpanded by remember(teamAssist.id) { mutableStateOf(false) }
    val cancelCategories = listOf(
        "accidental" to "Accidental",
        "resolved" to "Already Resolved",
        "test" to "Was a Test",
        "duplicate" to "Duplicate Request",
        "other" to "Other",
    )
    val filteredRecipients = remember(actionRecipients, forwardQuery) {
        actionRecipients.filter {
            it.label.contains(forwardQuery, ignoreCase = true)
        }
    }
    val subtitleParts = buildList {
        add("${formatIsoForBanner(teamAssist.createdAt) ?: teamAssist.createdAt} • by #${teamAssist.createdBy}")
        val actorLabel = teamAssist.actedByLabel?.takeIf { it.isNotBlank() }
        if (actorLabel != null) {
            add("${snakeToTitle(teamAssist.status)} by $actorLabel")
        } else {
            add(snakeToTitle(teamAssist.status))
        }
        teamAssist.forwardToLabel?.takeIf { it.isNotBlank() }?.let { add("to $it") }
    }
    val isTerminal = teamAssist.status.equals("resolved", ignoreCase = true) || teamAssist.status.equals("cancelled", ignoreCase = true)
    val isRequester = currentUserId != null && currentUserId == teamAssist.createdBy
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        FeedRow(
            title = AppLabels.featureDisplayName(teamAssist.type, featureLabels),
            subtitle = subtitleParts.joinToString(" • "),
            tone = Color(0xFF0F766E),
        )
        if (isAdmin || (isRequester && !isTerminal)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (isAdmin) {
                    val isOpenOrActive = teamAssist.status.equals("open", ignoreCase = true) || teamAssist.status.equals("active", ignoreCase = true)
                    if (isOpenOrActive) {
                        AssistActionChip(label = "Acknowledge", enabled = !isBusy) {
                            onTeamAssistAction(teamAssist.id, "acknowledge", null)
                        }
                    }
                    if (!isTerminal) {
                        AssistActionChip(label = "Resolve", enabled = !isBusy) {
                            onTeamAssistAction(teamAssist.id, "resolve", null)
                        }
                        AssistActionChip(label = "Forward", enabled = !isBusy && actionRecipients.isNotEmpty()) {
                            showForwardDialog = true
                        }
                    }
                }
                if (isRequester && !isTerminal) {
                    AssistActionChip(label = "Cancel Request", enabled = !isBusy) {
                        cancelReasonText = ""
                        cancelReasonCategory = ""
                        showCancelDialog = true
                    }
                }
            }
        }
    }

    if (showCancelDialog) {
        AlertDialog(
            onDismissRequest = { showCancelDialog = false },
            title = { Text("Cancel Help Request", color = TextPri, fontWeight = FontWeight.Bold) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    ExposedDropdownMenuBox(
                        expanded = cancelCategoryExpanded,
                        onExpandedChange = { cancelCategoryExpanded = it },
                    ) {
                        OutlinedTextField(
                            value = cancelCategories.firstOrNull { it.first == cancelReasonCategory }?.second ?: "",
                            onValueChange = {},
                            readOnly = true,
                            label = { Text("Reason category") },
                            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = cancelCategoryExpanded) },
                            modifier = Modifier.fillMaxWidth().menuAnchor(),
                        )
                        ExposedDropdownMenu(
                            expanded = cancelCategoryExpanded,
                            onDismissRequest = { cancelCategoryExpanded = false },
                        ) {
                            cancelCategories.forEach { (value, label) ->
                                DropdownMenuItem(
                                    text = { Text(label) },
                                    onClick = {
                                        cancelReasonCategory = value
                                        cancelCategoryExpanded = false
                                    },
                                )
                            }
                        }
                    }
                    OutlinedTextField(
                        value = cancelReasonText,
                        onValueChange = { cancelReasonText = it },
                        label = { Text("Details (required)") },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 2,
                        maxLines = 4,
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        if (cancelReasonText.isNotBlank() && cancelReasonCategory.isNotBlank()) {
                            showCancelDialog = false
                            onTeamAssistCancel(teamAssist.id, cancelReasonText.trim(), cancelReasonCategory)
                        }
                    },
                    enabled = cancelReasonText.isNotBlank() && cancelReasonCategory.isNotBlank(),
                ) {
                    Text("Confirm Cancel", color = Color(0xFFDC2626))
                }
            },
            dismissButton = {
                TextButton(onClick = { showCancelDialog = false }) {
                    Text("Back", color = TextMuted)
                }
            },
        )
    }

    if (showForwardDialog) {
        AlertDialog(
            onDismissRequest = { showForwardDialog = false },
            title = { Text(AppLabels.FORWARD_REQUEST_HELP, color = TextPri, fontWeight = FontWeight.Bold) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(
                        value = forwardQuery,
                        onValueChange = { forwardQuery = it },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        label = { Text("Search users") },
                    )
                    Column(
                        modifier = Modifier.heightIn(max = 220.dp).verticalScroll(rememberScrollState()),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        filteredRecipients.take(20).forEach { recipient ->
                            TextButton(
                                onClick = {
                                    onTeamAssistAction(teamAssist.id, "forward", recipient.userId)
                                    showForwardDialog = false
                                    forwardQuery = ""
                                },
                                modifier = Modifier.fillMaxWidth(),
                                enabled = !isBusy,
                            ) {
                                Text(recipient.label, color = BluePrimary, modifier = Modifier.fillMaxWidth())
                            }
                        }
                        if (filteredRecipients.isEmpty()) {
                            Text("No users found.", color = TextMuted, fontSize = 12.sp)
                        }
                    }
                }
            },
            confirmButton = {},
            dismissButton = {
                TextButton(onClick = { showForwardDialog = false }) {
                    Text("Close", color = TextMuted)
                }
            },
        )
    }
}

@Composable
private fun AssistActionChip(label: String, enabled: Boolean, onClick: () -> Unit) {
    Surface(
        color = if (enabled) BluePrimary.copy(alpha = 0.12f) else Color(0xFFE2E8F0),
        shape = RoundedCornerShape(999.dp),
    ) {
        TextButton(
            onClick = onClick,
            enabled = enabled,
            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 2.dp),
        ) {
            Text(label, color = if (enabled) BluePrimary else TextMuted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
private fun FeedRow(title: String, subtitle: String, tone: Color) {
    Surface(
        color = tone.copy(alpha = 0.07f),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp)) {
            Text(title, color = tone, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
            Text(subtitle, color = TextMuted, fontSize = 12.sp)
        }
    }
}

@Composable
private fun QuietPeriodStatusBanner(
    status: QuietPeriodMobileStatus,
    isBusy: Boolean,
    onDeletePending: () -> Unit,
    onDeleteApproved: () -> Unit,
) {
    val normalized = status.status?.lowercase().orEmpty()
    if (normalized.isBlank()) return

    // Countdown timer — approved: counts to expiresAt; scheduled: counts to scheduledStartAt.
    val countdownTarget = if (normalized == "scheduled") status.scheduledStartAt else status.expiresAt
    var secondsLeft by remember(countdownTarget) { mutableStateOf(0L) }
    LaunchedEffect(countdownTarget, normalized) {
        if (normalized !in setOf("approved", "scheduled") || countdownTarget == null) return@LaunchedEffect
        while (true) {
            val target = try { Instant.parse(countdownTarget).toEpochMilli() } catch (_: Exception) { 0L }
            secondsLeft = maxOf(0L, (target - System.currentTimeMillis()) / 1000)
            if (secondsLeft <= 0L) break
            delay(1000L)
        }
    }

    val bg: Color
    val border: Color
    val fg: Color
    val text: String
    when (normalized) {
        "approved" -> {
            val countdown = when {
                secondsLeft > 3600 -> "${secondsLeft / 3600}h ${(secondsLeft % 3600) / 60}m"
                secondsLeft > 60 -> "${secondsLeft / 60}m ${secondsLeft % 60}s"
                secondsLeft > 0 -> "${secondsLeft}s"
                else -> formatIsoForBanner(status.expiresAt) ?: "soon"
            }
            bg = AlarmRed.copy(alpha = 0.14f)
            border = AlarmRed.copy(alpha = 0.32f)
            fg = AlarmRed
            text = "Quiet period ACTIVE — Ends in $countdown"
        }
        "pending" -> {
            bg = DSColor.Info.copy(alpha = 0.12f)
            border = DSColor.Info.copy(alpha = 0.28f)
            fg = DSColor.Info
            val schedInfo = status.scheduledStartAt?.let { " — Starts ${formatIsoForBanner(it) ?: it}" } ?: ""
            text = "Quiet period request pending approval$schedInfo"
        }
        "scheduled" -> {
            val countdown = when {
                secondsLeft > 3600 -> "${secondsLeft / 3600}h ${(secondsLeft % 3600) / 60}m"
                secondsLeft > 60 -> "${secondsLeft / 60}m ${secondsLeft % 60}s"
                secondsLeft > 0 -> "${secondsLeft}s"
                else -> formatIsoForBanner(status.scheduledStartAt) ?: "soon"
            }
            bg = DSColor.Success.copy(alpha = 0.12f)
            border = DSColor.Success.copy(alpha = 0.28f)
            fg = DSColor.Success
            text = "Quiet period SCHEDULED — Starts in $countdown"
        }
        "denied" -> {
            bg = DSColor.Warning.copy(alpha = 0.14f)
            border = DSColor.Warning.copy(alpha = 0.32f)
            fg = DSColor.Warning
            text = "Quiet period request denied"
        }
        else -> return
    }
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 4.dp)
            .background(bg, RoundedCornerShape(12.dp))
            .border(1.dp, border, RoundedCornerShape(12.dp))
            .padding(14.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(text, color = fg, fontSize = 14.sp, fontWeight = FontWeight.Bold)
            status.reason?.takeIf { it.isNotBlank() }?.let {
                Text("Reason: $it", color = fg, fontSize = 12.sp)
            }
            if (normalized in setOf("pending", "approved", "scheduled")) {
                Button(
                    onClick = {
                        if (normalized == "approved") onDeleteApproved() else onDeletePending()
                    },
                    enabled = !isBusy,
                    shape = RoundedCornerShape(10.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = AlarmRed,
                        contentColor = Color.White,
                        disabledContainerColor = TextMuted.copy(alpha = 0.7f),
                        disabledContentColor = Color.White,
                    ),
                ) {
                    Text(
                        when {
                            isBusy -> "Deleting..."
                            normalized == "approved" -> "End Quiet Period"
                            normalized == "scheduled" -> "Cancel Scheduled Period"
                            else -> "Delete Request"
                        },
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }
        }
    }
}

@Composable
private fun AdminEventModal(
    events: List<AdminEvent>,
    onDismiss: (String) -> Unit,
) {
    if (events.isEmpty()) return
    val event = events.first()

    val scale by animateFloatAsState(
        targetValue = 1f,
        animationSpec = tween(durationMillis = 200, easing = FastOutSlowInEasing),
        label = "admin_modal_scale",
    )
    val alpha by animateFloatAsState(
        targetValue = 1f,
        animationSpec = tween(durationMillis = 180),
        label = "admin_modal_alpha",
    )

    val icon = when (event.type) {
        AdminEventType.QUIET_PENDING  -> "⏸"
        AdminEventType.QUIET_APPROVED -> "✓"
        AdminEventType.ADMIN_MESSAGE  -> "✉"
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp, vertical = 72.dp)
            .zIndex(10f),
        contentAlignment = Alignment.TopCenter,
    ) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = SurfaceMain,
            shadowElevation = 16.dp,
            modifier = Modifier
                .fillMaxWidth()
                .graphicsLayer { scaleX = scale; scaleY = scale; this.alpha = alpha }
                .clickable { onDismiss(event.id) },
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier
                        .size(40.dp)
                        .background(QuietPurple.copy(alpha = 0.15f), CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(icon, fontSize = 18.sp)
                }
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    Text(
                        event.title,
                        color = TextPri,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 14.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        event.body,
                        color = TextMuted,
                        fontSize = 13.sp,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Icon(
                    Icons.Default.Close,
                    contentDescription = "Dismiss",
                    tint = TextMuted,
                    modifier = Modifier
                        .size(18.dp)
                        .clickable { onDismiss(event.id) },
                )
            }
        }
    }
}

@Composable
private fun AdminQuietRequestModal(
    event: AdminQuietModalEvent,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
    onView: () -> Unit,
    onDismiss: () -> Unit,
) {
    var visible by remember { mutableStateOf(false) }
    LaunchedEffect(event.id) { visible = true }

    AnimatedVisibility(
        visible = visible,
        enter = fadeIn(animationSpec = tween(180)) + scaleIn(initialScale = 0.94f, animationSpec = tween(180)),
        exit = fadeOut(animationSpec = tween(120)) + scaleOut(targetScale = 0.96f, animationSpec = tween(120)),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .zIndex(10f),
            contentAlignment = Alignment.Center,
        ) {
            // Scrim — tap outside to dismiss.
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black.copy(alpha = 0.35f))
                    .clickable(onClick = onDismiss),
            )
            Surface(
                shape = RoundedCornerShape(22.dp),
                color = SurfaceMain,
                shadowElevation = 10.dp,
                border = BorderStroke(1.dp, QuietPurple.copy(alpha = 0.25f)),
                modifier = Modifier
                    .padding(horizontal = 24.dp)
                    .clickable(enabled = false) {},
            ) {
                Column(
                    modifier = Modifier.padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Box(
                            modifier = Modifier
                                .size(36.dp)
                                .background(QuietPurple.copy(alpha = 0.15f), CircleShape),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text("🌙", fontSize = 18.sp)
                        }
                        Text(
                            "Quiet Request Pending",
                            fontWeight = FontWeight.Bold,
                            fontSize = 16.sp,
                            color = TextPri,
                        )
                    }
                    Text(
                        "${event.userName} • ${event.userRole}",
                        fontSize = 13.sp,
                        color = TextMuted,
                    )
                    event.reason?.let { reason ->
                        Text(
                            "“$reason”",
                            fontSize = 13.sp,
                            color = TextMuted,
                            fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
                        )
                    }
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Button(
                            onClick = onApprove,
                            modifier = Modifier.weight(1f),
                            colors = ButtonDefaults.buttonColors(containerColor = QuietPurple),
                            shape = RoundedCornerShape(10.dp),
                        ) {
                            Text("Approve", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                        }
                        Button(
                            onClick = onDeny,
                            modifier = Modifier.weight(1f),
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFDC2626)),
                            shape = RoundedCornerShape(10.dp),
                        ) {
                            Text("Deny", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                        }
                        OutlinedButton(
                            onClick = onView,
                            modifier = Modifier.weight(1f),
                            shape = RoundedCornerShape(10.dp),
                            border = BorderStroke(1.dp, QuietPurple.copy(alpha = 0.5f)),
                        ) {
                            Text("View", fontSize = 12.sp, color = QuietPurple)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AdminQuietPeriodRequestsCard(
    requests: List<AdminQuietPeriodRequest>,
    isBusy: Boolean,
    onApprove: (Int) -> Unit,
    onDeny: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        color = SurfaceMain,
        shape = RoundedCornerShape(20.dp),
        shadowElevation = 4.dp,
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Quiet Period Requests", color = TextPri, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            if (requests.isEmpty()) {
                Text("No pending quiet period requests.", color = TextMuted, fontSize = 13.sp)
            } else {
                requests.take(10).forEach { item ->
                    Surface(
                        color = SurfaceSoft,
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = (item.userName ?: "User #${item.userId}") + " • ${snakeToTitle(item.userRole ?: "user")}",
                                    color = TextPri,
                                    fontWeight = FontWeight.SemiBold,
                                    fontSize = 14.sp,
                                    modifier = Modifier.weight(1f),
                                )
                                if (item.scheduledStartAt != null) {
                                    BBStatusBadge("Scheduled", color = DSColor.Info)
                                }
                            }
                            item.scheduledStartAt?.let { startAt ->
                                Text(
                                    text = "Starts: ${formatIsoForBanner(startAt) ?: startAt}",
                                    color = DSColor.Info,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.SemiBold,
                                )
                            }
                            Text(
                                text = "Requested: ${formatIsoForBanner(item.requestedAt) ?: item.requestedAt}",
                                color = TextMuted,
                                fontSize = 12.sp,
                            )
                            item.reason?.takeIf { it.isNotBlank() }?.let { reason ->
                                Text(
                                    text = "Reason: $reason",
                                    color = TextMuted,
                                    fontSize = 12.sp,
                                )
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(
                                    onClick = { onApprove(item.requestId) },
                                    enabled = !isBusy && item.status.equals("pending", ignoreCase = true),
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = AlarmGreen,
                                        contentColor = Color.White,
                                    ),
                                    shape = RoundedCornerShape(10.dp),
                                ) {
                                    Text("Approve", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                                }
                                Button(
                                    onClick = { onDeny(item.requestId) },
                                    enabled = !isBusy && item.status.equals("pending", ignoreCase = true),
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = AlarmRed,
                                        contentColor = Color.White,
                                    ),
                                    shape = RoundedCornerShape(10.dp),
                                ) {
                                    Text("Deny", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PushDeliveryStatsCard(stats: PushDeliveryStats?, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        color = SurfaceMain,
        shape = RoundedCornerShape(20.dp),
        shadowElevation = 4.dp,
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Push Delivery", color = TextPri, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            if (stats == null || stats.total == 0) {
                Text("No deliveries recorded for current alert.", color = TextMuted, fontSize = 13.sp)
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Text("✓ ${stats.ok} sent", color = Color(0xFF166534), fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                    if (stats.failed > 0) {
                        Text("✗ ${stats.failed} failed", color = Color(0xFFDC2626), fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                    }
                }
                if (stats.byProvider.isNotEmpty()) {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        stats.byProvider.entries.sortedBy { it.key }.forEach { (provider, ps) ->
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text(
                                    provider.uppercase(),
                                    color = TextMuted,
                                    fontSize = 11.sp,
                                    fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                                )
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Text("${ps.ok}/${ps.total}", color = TextMuted, fontSize = 11.sp)
                                    if (ps.failed > 0) {
                                        Text("✗ ${ps.failed}", color = Color(0xFFDC2626), fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
                                    }
                                }
                            }
                            ps.lastError?.takeIf { it.isNotBlank() }?.let {
                                Text(it, color = Color(0xFFDC2626), fontSize = 10.sp, maxLines = 1)
                            }
                        }
                    }
                }
                stats.lastError?.takeIf { it.isNotBlank() }?.let {
                    Text("Last error: $it", color = Color(0xFFDC2626), fontSize = 12.sp, maxLines = 2)
                }
            }
        }
    }
}

@Composable
private fun AuditLogButtonCard(onClick: () -> Unit, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        color = SurfaceMain,
        shape = RoundedCornerShape(20.dp),
        shadowElevation = 4.dp,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp).fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text("Audit Log", color = TextPri, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                Text("Activity, logins, user changes", color = TextMuted, fontSize = 12.sp)
            }
            TextButton(
                onClick = onClick,
                colors = ButtonDefaults.textButtonColors(contentColor = BluePrimary),
            ) {
                Text("View Logs", fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                Spacer(Modifier.width(4.dp))
                Text("›", fontSize = 16.sp)
            }
        }
    }
}

@Composable
private fun AuditLogsModal(client: BackendClient?, userId: Int, onDismiss: () -> Unit) {
    val pageSize = 25
    var entries by remember { mutableStateOf<List<AuditLogEntry>>(emptyList()) }
    var isLoading by remember { mutableStateOf(false) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var search by remember { mutableStateOf("") }
    var selectedEventType by remember { mutableStateOf<String?>(null) }
    var availableTypes by remember { mutableStateOf<List<String>>(emptyList()) }
    var offset by remember { mutableStateOf(0) }
    var hasMore by remember { mutableStateOf(true) }
    var expandedId by remember { mutableStateOf<Int?>(null) }
    val scope = rememberCoroutineScope()

    fun load(reset: Boolean) {
        if (client == null || isLoading) return
        isLoading = true
        loadError = null
        val currentOffset = if (reset) 0 else offset
        scope.launch(Dispatchers.IO) {
            runCatching {
                client.auditLog(
                    userId = userId,
                    limit = pageSize,
                    offset = currentOffset,
                    search = search.trim().takeIf { it.isNotEmpty() },
                    eventType = selectedEventType,
                )
            }.onSuccess { newEntries ->
                withContext(Dispatchers.Main) {
                    if (reset) {
                        entries = newEntries
                        offset = newEntries.size
                        if (availableTypes.isEmpty()) {
                            availableTypes = newEntries.map { it.eventType }.distinct().sorted()
                        }
                    } else {
                        entries = entries + newEntries
                        offset += newEntries.size
                    }
                    hasMore = newEntries.size == pageSize
                    isLoading = false
                }
            }.onFailure { err ->
                withContext(Dispatchers.Main) {
                    loadError = err.message ?: "Failed to load logs"
                    isLoading = false
                }
            }
        }
    }

    LaunchedEffect(Unit) { load(reset = true) }

    var debounceJob by remember { mutableStateOf<Job?>(null) }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = DSColor.Background,
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                // Header
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "Audit Logs",
                        color = DSColor.TextPrimary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 18.sp,
                    )
                    IconButton(onClick = onDismiss) {
                        Icon(
                            imageVector = Icons.Default.Close,
                            contentDescription = "Close",
                            tint = DSColor.TextSecondary,
                        )
                    }
                }
                HorizontalDivider(color = DSColor.Border)

                // Search
                OutlinedTextField(
                    value = search,
                    onValueChange = { v ->
                        search = v
                        debounceJob?.cancel()
                        debounceJob = scope.launch {
                            delay(350)
                            load(reset = true)
                        }
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 10.dp),
                    placeholder = { Text("Search action or user…", color = DSColor.TextSecondary) },
                    leadingIcon = {
                        Icon(Icons.Default.Search, contentDescription = null, tint = DSColor.TextSecondary)
                    },
                    trailingIcon = if (search.isNotEmpty()) {
                        { IconButton(onClick = { search = ""; load(reset = true) }) {
                            Icon(Icons.Default.Close, contentDescription = "Clear", tint = DSColor.TextSecondary)
                        }}
                    } else null,
                    singleLine = true,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = DSColor.Primary,
                        unfocusedBorderColor = DSColor.Border,
                        focusedTextColor = DSColor.TextPrimary,
                        unfocusedTextColor = DSColor.TextPrimary,
                    ),
                    shape = RoundedCornerShape(12.dp),
                )

                // Filter chips
                if (availableTypes.isNotEmpty()) {
                    LazyRow(
                        modifier = Modifier.padding(bottom = 8.dp),
                        contentPadding = PaddingValues(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        item {
                            FilterChip(
                                selected = selectedEventType == null,
                                onClick = { selectedEventType = null; load(reset = true) },
                                label = { Text("All", fontSize = 12.sp) },
                                colors = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = DSColor.Primary,
                                    selectedLabelColor = Color.White,
                                ),
                            )
                        }
                        items(availableTypes) { type ->
                            FilterChip(
                                selected = selectedEventType == type,
                                onClick = {
                                    selectedEventType = if (selectedEventType == type) null else type
                                    load(reset = true)
                                },
                                label = { Text(snakeToTitle(type), fontSize = 12.sp) },
                                colors = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = DSColor.Primary,
                                    selectedLabelColor = Color.White,
                                ),
                            )
                        }
                    }
                }

                HorizontalDivider(color = DSColor.Border)

                // Content
                when {
                    isLoading && entries.isEmpty() -> {
                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                            CircularProgressIndicator(color = DSColor.Primary)
                        }
                    }
                    loadError != null && entries.isEmpty() -> {
                        Column(
                            modifier = Modifier.fillMaxSize(),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.Center,
                        ) {
                            Text(
                                loadError ?: "Error loading logs",
                                color = DSColor.Danger,
                                fontSize = 14.sp,
                                textAlign = TextAlign.Center,
                                modifier = Modifier.padding(horizontal = 32.dp),
                            )
                            Spacer(Modifier.height(12.dp))
                            Button(onClick = { load(reset = true) }) { Text("Retry") }
                        }
                    }
                    entries.isEmpty() -> {
                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                            Text("No audit logs found", color = DSColor.TextSecondary, fontSize = 14.sp)
                        }
                    }
                    else -> {
                        LazyColumn(modifier = Modifier.fillMaxSize()) {
                            items(entries) { entry ->
                                AuditLogRow(
                                    entry = entry,
                                    isExpanded = expandedId == entry.id,
                                    onClick = { expandedId = if (expandedId == entry.id) null else entry.id },
                                )
                                HorizontalDivider(
                                    color = DSColor.Border,
                                    thickness = 0.5.dp,
                                    modifier = Modifier.padding(horizontal = 16.dp),
                                )
                            }
                            if (hasMore) {
                                item {
                                    Box(
                                        modifier = Modifier.fillMaxWidth().padding(16.dp),
                                        contentAlignment = Alignment.Center,
                                    ) {
                                        if (isLoading) {
                                            CircularProgressIndicator(
                                                color = DSColor.Primary,
                                                modifier = Modifier.size(24.dp),
                                                strokeWidth = 2.dp,
                                            )
                                        } else {
                                            OutlinedButton(onClick = { load(reset = false) }) {
                                                Text("Load More", color = DSColor.Primary)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AuditLogRow(entry: AuditLogEntry, isExpanded: Boolean, onClick: () -> Unit) {
    val dotColor = when {
        entry.eventType.contains("alarm") || entry.eventType.contains("alert") -> DSColor.Danger
        entry.eventType.contains("login") -> DSColor.Primary
        entry.eventType.contains("user") -> Color(0xFF7C3AED)
        entry.eventType.contains("quiet") -> Color(0xFF0D9488)
        else -> DSColor.TextSecondary
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onClick() }
            .padding(horizontal = 16.dp, vertical = 10.dp),
    ) {
        Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .offset(y = 5.dp)
                    .clip(CircleShape)
                    .background(dotColor),
            )
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(
                    snakeToTitle(entry.eventType),
                    color = DSColor.TextPrimary,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 14.sp,
                )
                Text(
                    buildString {
                        entry.actorLabel?.let { append(it); append(" · ") }
                        append(entry.timestamp.take(16).replace("T", " "))
                    },
                    color = DSColor.TextSecondary,
                    fontSize = 12.sp,
                )
            }
            Icon(
                imageVector = if (isExpanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                contentDescription = null,
                tint = DSColor.TextSecondary,
                modifier = Modifier.size(16.dp),
            )
        }
        if (isExpanded) {
            Spacer(Modifier.height(8.dp))
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(DSColor.Border.copy(alpha = 0.3f), RoundedCornerShape(8.dp))
                    .padding(10.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                AuditDetailRow("Event ID", entry.id.toString())
                AuditDetailRow("Timestamp", entry.timestamp)
                entry.targetType?.let { AuditDetailRow("Target", it) }
            }
        }
    }
}

@Composable
private fun AuditDetailRow(label: String, value: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            "$label:",
            color = DSColor.TextSecondary,
            fontWeight = FontWeight.SemiBold,
            fontSize = 12.sp,
            modifier = Modifier.width(80.dp),
        )
        Text(value, color = DSColor.TextPrimary, fontSize = 12.sp)
    }
}

@Composable
private fun PendingQuietRequestCard(
    status: QuietPeriodMobileStatus,
    isBusy: Boolean,
    onCancelRequest: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val isScheduled = status.status?.lowercase() == "scheduled"
    val cardColor = if (isScheduled) DSColor.Success.copy(alpha = 0.10f) else DSColor.Info.copy(alpha = 0.10f)
    val borderColor = if (isScheduled) DSColor.Success.copy(alpha = 0.25f) else DSColor.Info.copy(alpha = 0.25f)
    val badgeLabel = if (isScheduled) "Approved — Scheduled" else "Pending Approval"
    val badgeColor = if (isScheduled) DSColor.Success else DSColor.Info
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(16.dp),
        color = cardColor,
        border = BorderStroke(1.dp, borderColor),
    ) {
        Column(
            modifier = Modifier.padding(DSSpacing.LG),
            verticalArrangement = Arrangement.spacedBy(DSSpacing.SM),
        ) {
            Row(
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    if (isScheduled) "Quiet Period Scheduled" else "Quiet Period Requested",
                    color = DSColor.TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = DSTypography.Body,
                )
                BBStatusBadge(badgeLabel, color = badgeColor)
            }
            status.scheduledStartAt?.let { startAt ->
                Text(
                    "Starts: ${formatIsoForBanner(startAt) ?: startAt}",
                    color = if (isScheduled) DSColor.Success else DSColor.Info,
                    fontSize = DSTypography.Caption,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            status.requestedAt?.let { at ->
                Text(
                    "Requested: ${formatIsoForBanner(at) ?: at}",
                    color = DSColor.TextSecondary,
                    fontSize = DSTypography.Caption,
                )
            }
            status.reason?.takeIf { it.isNotBlank() }?.let { reason ->
                Text(
                    "Reason: $reason",
                    color = DSColor.TextSecondary,
                    fontSize = DSTypography.Caption,
                )
            }
            BBSecondaryButton(
                text = when {
                    isBusy -> "Cancelling…"
                    isScheduled -> "Cancel Scheduled Period"
                    else -> "Cancel Request"
                },
                onClick = onCancelRequest,
                enabled = !isBusy,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun QuietPeriodDeleteConfirmOverlay(
    isBusy: Boolean,
    onCancel: () -> Unit,
    onConfirm: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = { if (!isBusy) onCancel() },
        containerColor = DSColor.Card,
        title = {
            Text(
                "End Quiet Period Early?",
                color = DSColor.TextPrimary,
                fontWeight = FontWeight.Bold,
            )
        },
        text = {
            Text(
                "This will cancel your approved quiet period. Admins will be notified.",
                color = DSColor.TextSecondary,
                fontSize = DSTypography.Body,
            )
        },
        confirmButton = {
            Button(
                onClick = onConfirm,
                enabled = !isBusy,
                colors = ButtonDefaults.buttonColors(containerColor = DSColor.Danger),
            ) {
                if (isBusy) {
                    CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp, modifier = Modifier.size(18.dp))
                } else {
                    Text("End Early", fontWeight = FontWeight.SemiBold)
                }
            }
        },
        dismissButton = {
            TextButton(onClick = { if (!isBusy) onCancel() }) {
                Text("Cancel", color = DSColor.TextSecondary, fontWeight = FontWeight.SemiBold)
            }
        },
    )
}

@Composable
private fun AlarmBanner(alarm: AlarmStatus, schoolName: String = "", modifier: Modifier = Modifier) {
    val pulse = rememberInfiniteTransition(label = "pulse")
    val pulseAlpha by pulse.animateFloat(
        initialValue = 1f,
        targetValue  = if (alarm.isActive) 0.65f else 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(900, easing = EaseInOut),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulseAlpha",
    )

    val bg = when {
        alarm.isActive && alarm.isTraining -> Color(0xFFD97706)
        alarm.isActive -> AlarmRed
        else -> SurfaceMain
    }

    Surface(
        modifier = modifier.alpha(if (alarm.isActive) pulseAlpha else 1f),
        shape = RoundedCornerShape(24.dp),
        color = bg,
        tonalElevation = 4.dp,
        shadowElevation = if (alarm.isActive) 12.dp else 6.dp,
    ) {
        Column(
            modifier = Modifier.padding(28.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    if (alarm.isActive) "⚠" else "✓",
                    fontSize = 32.sp,
                )
                Column {
                    Text(
                        if (alarm.isActive && alarm.isTraining) "TRAINING DRILL" else if (alarm.isActive) "ALARM ACTIVE" else "All Clear",
                        fontWeight = FontWeight.ExtraBold,
                        fontSize = 26.sp,
                        color = if (alarm.isActive) TextOnDark else TextPri,
                    )
                    Text(
                        if (alarm.isActive && alarm.isTraining) (alarm.trainingLabel ?: "This is a drill") else if (alarm.isActive) "Emergency alert in progress" else "No active school alarm",
                        fontSize = 14.sp,
                        color = if (alarm.isActive && alarm.isTraining) Color(0xFFFFF3E0) else if (alarm.isActive) Color(0xFFFFCDD2) else TextMuted,
                    )
                }
            }

            if (alarm.isActive) {
                HorizontalDivider(color = Color(0x33FFFFFF), thickness = 1.dp)
                if (schoolName.isNotBlank()) {
                    Text(schoolName, fontSize = 12.sp, color = Color(0xFFFFCDD2), fontWeight = FontWeight.SemiBold)
                }
                alarm.message?.let {
                    Text(it, fontSize = 16.sp, color = TextOnDark, fontWeight = FontWeight.Medium)
                }
                val triggeredByText = alarm.activatedByLabel
                    ?: alarm.activatedByUserId?.let { "User #$it" }
                    ?: "Unknown"
                Text(
                    "Triggered by: $triggeredByText",
                    fontSize = 13.sp,
                    color = Color(0xFFFFCDD2),
                    fontWeight = FontWeight.Medium,
                )
                alarm.activatedAt?.let {
                    Text("Activated: $it", fontSize = 12.sp, color = Color(0xFFFFCDD2))
                }
                if (alarm.acknowledgementCount > 0) {
                    Text(
                        "✓ ${alarm.acknowledgementCount} acknowledged",
                        fontSize = 12.sp,
                        color = Color(0xFFA7F3D0),
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }
        }
    }
}

@Composable
private fun EmergencyAlarmTakeover(
    alarm: AlarmStatus,
    schoolName: String = "",
    canDeactivate: Boolean,
    isBusy: Boolean,
    onDeactivate: () -> Unit,
    onAcknowledge: () -> Unit,
    onSendMessage: ((message: String) -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val accent = if (alarm.isTraining) DSColor.Warning else AlarmRed
    val title = if (alarm.isTraining) "TRAINING DRILL" else "EMERGENCY ALERT"
    val subtitle = if (alarm.isTraining) {
        alarm.trainingLabel?.takeIf { it.isNotBlank() } ?: "This is a drill"
    } else {
        alarm.message?.takeIf { it.isNotBlank() } ?: "School alarm is active"
    }
    val instructions = if (alarm.isTraining)
        "Follow drill procedures as directed."
    else
        "Follow school emergency procedures immediately."

    val pulse = rememberInfiniteTransition(label = "alarmTakeoverPulse")
    val pulseScale by pulse.animateFloat(
        initialValue = 0.96f,
        targetValue = 1.04f,
        animationSpec = infiniteRepeatable(
            animation = tween(820, easing = EaseInOut),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "takeoverIconScale",
    )

    Box(
        modifier = modifier
            .background(Brush.verticalGradient(listOf(accent, Color(0xFF0D1117))))
            .padding(horizontal = 24.dp, vertical = 28.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            // ── Header ─────────────────────────────────────────────────────
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(20.dp),
                modifier = Modifier.padding(top = 8.dp),
            ) {
                Box(
                    modifier = Modifier
                        .size(148.dp)
                        .graphicsLayer { scaleX = pulseScale; scaleY = pulseScale }
                        .border(8.dp, Color.White.copy(alpha = 0.28f), CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        if (alarm.isTraining) "!" else "🚨",
                        fontSize = 64.sp,
                        fontWeight = FontWeight.Black,
                        textAlign = TextAlign.Center,
                    )
                }

                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        title,
                        color = Color.White,
                        fontSize = 32.sp,
                        fontWeight = FontWeight.Black,
                        textAlign = TextAlign.Center,
                        lineHeight = 36.sp,
                    )
                    Text(
                        subtitle,
                        color = Color.White.copy(alpha = 0.92f),
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold,
                        textAlign = TextAlign.Center,
                    )
                    if (schoolName.isNotBlank()) {
                        Text(
                            schoolName,
                            color = Color.White.copy(alpha = 0.72f),
                            fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold,
                            textAlign = TextAlign.Center,
                        )
                    }
                    alarm.activatedByLabel?.takeIf { it.isNotBlank() }?.let {
                        Text(
                            "Activated by: $it",
                            color = Color.White.copy(alpha = 0.68f),
                            fontSize = 12.sp,
                            textAlign = TextAlign.Center,
                        )
                    }
                }

                // ── Instructions ─────────────────────────────────────────
                Surface(
                    color = Color.White.copy(alpha = 0.12f),
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        instructions,
                        color = Color.White.copy(alpha = 0.94f),
                        fontSize = 15.sp,
                        fontWeight = FontWeight.SemiBold,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                    )
                }

                // ── Acknowledgement progress ──────────────────────────────
                run {
                    val ackPct = alarm.acknowledgementPercentage
                    val ackColor = when {
                        ackPct >= 70f -> Color(0xFF34D399)  // success green
                        ackPct >= 30f -> Color(0xFFFBBF24)  // warning amber
                        else          -> Color(0xFFF87171)  // danger red
                    }
                    val animatedPct by animateFloatAsState(
                        targetValue = (ackPct / 100f).coerceIn(0f, 1f),
                        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy),
                        label = "ackProgress",
                    )
                    Column(
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                if (alarm.expectedUserCount > 0)
                                    "${alarm.acknowledgementCount} / ${alarm.expectedUserCount} acknowledged"
                                else
                                    "${alarm.acknowledgementCount} acknowledged",
                                color = Color.White,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                            if (alarm.expectedUserCount > 0) {
                                Text(
                                    "${ackPct.toInt()}%",
                                    color = ackColor,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.Black,
                                )
                            }
                        }
                        LinearProgressIndicator(
                            progress = { animatedPct },
                            color = ackColor,
                            trackColor = Color.White.copy(alpha = 0.18f),
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(8.dp)
                                .clip(RoundedCornerShape(4.dp)),
                        )
                    }
                }

                // ── Admin broadcasts ──────────────────────────────────────
                if (alarm.broadcasts.isNotEmpty()) {
                    Column(
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            "Admin Updates",
                            color = Color.White.copy(alpha = 0.65f),
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 0.5.sp,
                        )
                        alarm.broadcasts.take(5).forEach { update ->
                            Surface(
                                color = Color.White.copy(alpha = 0.10f),
                                shape = RoundedCornerShape(12.dp),
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Column(
                                    verticalArrangement = Arrangement.spacedBy(3.dp),
                                    modifier = Modifier.padding(12.dp),
                                ) {
                                    Text(
                                        update.message,
                                        color = Color.White.copy(alpha = 0.94f),
                                        fontSize = 13.sp,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        update.adminLabel?.let {
                                            Text(it, color = Color.White.copy(alpha = 0.55f), fontSize = 10.sp, fontWeight = FontWeight.SemiBold)
                                        }
                                        update.createdAt?.let {
                                            Text(it.take(16).replace("T", " "), color = Color.White.copy(alpha = 0.45f), fontSize = 10.sp)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // ── Message admin (post-ack) ───────────────────────────────
                if (alarm.currentUserAcknowledged && onSendMessage != null) {
                    var overlayMsg by remember { mutableStateOf("") }
                    var isSending by remember { mutableStateOf(false) }
                    var sentFeedback by remember { mutableStateOf(false) }

                    Column(
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            "Message Admin",
                            color = Color.White.copy(alpha = 0.65f),
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 0.5.sp,
                        )
                        if (sentFeedback) {
                            Text(
                                "✓ Message sent",
                                color = Color(0xFF34D399),
                                fontSize = 13.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            androidx.compose.material3.OutlinedTextField(
                                value = overlayMsg,
                                onValueChange = { overlayMsg = it },
                                placeholder = {
                                    Text(
                                        "Send message to admin…",
                                        color = Color.White.copy(alpha = 0.45f),
                                        fontSize = 13.sp,
                                    )
                                },
                                maxLines = 3,
                                textStyle = androidx.compose.ui.text.TextStyle(
                                    color = Color.White,
                                    fontSize = 13.sp,
                                ),
                                colors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = Color.White.copy(alpha = 0.55f),
                                    unfocusedBorderColor = Color.White.copy(alpha = 0.25f),
                                    cursorColor = Color.White,
                                ),
                                shape = RoundedCornerShape(12.dp),
                                modifier = Modifier.weight(1f),
                            )
                            IconButton(
                                onClick = {
                                    val msg = overlayMsg.trim()
                                    if (msg.isNotEmpty() && !isSending) {
                                        isSending = true
                                        onSendMessage(msg)
                                        overlayMsg = ""
                                        sentFeedback = true
                                        isSending = false
                                    }
                                },
                                enabled = overlayMsg.trim().isNotEmpty() && !isSending,
                                modifier = Modifier
                                    .size(44.dp)
                                    .background(
                                        if (overlayMsg.trim().isEmpty()) Color.White.copy(alpha = 0.18f)
                                        else DSColor.Primary,
                                        CircleShape,
                                    ),
                            ) {
                                if (isSending) {
                                    CircularProgressIndicator(
                                        color = Color.White,
                                        strokeWidth = 2.dp,
                                        modifier = Modifier.size(20.dp),
                                    )
                                } else {
                                    Text(
                                        "→",
                                        color = Color.White,
                                        fontSize = 18.sp,
                                        fontWeight = FontWeight.Bold,
                                    )
                                }
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(24.dp))

            // ── Actions ────────────────────────────────────────────────────
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                // Acknowledge button — visible to ALL users
                Button(
                    onClick = onAcknowledge,
                    enabled = !isBusy && !alarm.currentUserAcknowledged && alarm.alertId != null,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color(0xFF34D399),
                        contentColor = Color(0xFF064E3B),
                        disabledContainerColor = Color.White.copy(alpha = 0.20f),
                        disabledContentColor = Color.White.copy(alpha = 0.60f),
                    ),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(58.dp),
                    shape = RoundedCornerShape(16.dp),
                ) {
                    Text(
                        when {
                            alarm.currentUserAcknowledged -> "✓ Acknowledged"
                            isBusy -> "Acknowledging…"
                            else -> "Acknowledge"
                        },
                        fontWeight = FontWeight.Black,
                        fontSize = 17.sp,
                    )
                }

                if (canDeactivate) {
                    Button(
                        onClick = onDeactivate,
                        enabled = !isBusy,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = Color.White,
                            contentColor = accent,
                            disabledContainerColor = Color.White.copy(alpha = 0.7f),
                            disabledContentColor = accent.copy(alpha = 0.65f),
                        ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(52.dp),
                        shape = RoundedCornerShape(16.dp),
                    ) {
                        Text(
                            if (isBusy) "Disabling Alarm…" else "Disable Alarm",
                            fontWeight = FontWeight.Bold,
                            fontSize = 15.sp,
                        )
                    }
                }

            }
        }
    }
}

@Composable
private fun DistrictOverviewScreen(
    tenants: List<TenantOverviewItem>,
    quietRequests: List<DistrictQuietPeriodItem>,
    auditLog: List<AuditLogEntry>,
    isBusy: Boolean,
    onRefresh: () -> Unit,
    onApproveQuiet: (requestId: Int, tenantSlug: String) -> Unit,
    onDenyQuiet: (requestId: Int, tenantSlug: String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var pendingApprovalId by remember { mutableStateOf<Int?>(null) }
    var pendingApprovalSlug by remember { mutableStateOf("") }
    var pendingApprovalIsApprove by remember { mutableStateOf(true) }

    if (pendingApprovalId != null) {
        AlertDialog(
            onDismissRequest = { pendingApprovalId = null },
            containerColor = DSColor.Card,
            title = {
                Text(
                    if (pendingApprovalIsApprove) "Approve Quiet Period?" else "Deny Quiet Period?",
                    color = DSColor.TextPrimary,
                    fontWeight = FontWeight.Bold,
                )
            },
            text = {
                Text(
                    if (pendingApprovalIsApprove)
                        "This will grant the user a quiet period and notify them."
                    else
                        "The user will be notified their request was denied.",
                    color = DSColor.TextSecondary,
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        val id = pendingApprovalId ?: return@Button
                        val slug = pendingApprovalSlug
                        if (pendingApprovalIsApprove) onApproveQuiet(id, slug)
                        else onDenyQuiet(id, slug)
                        pendingApprovalId = null
                    },
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (pendingApprovalIsApprove) DSColor.Success else DSColor.Danger,
                    ),
                    enabled = !isBusy,
                ) {
                    Text(if (pendingApprovalIsApprove) "Approve" else "Deny", fontWeight = FontWeight.SemiBold)
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingApprovalId = null }) {
                    Text("Cancel", color = DSColor.TextSecondary)
                }
            },
        )
    }

    Column(
        modifier = modifier
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("District Overview", color = TextPri, fontWeight = FontWeight.Bold, fontSize = 20.sp)
            TextButton(onClick = onRefresh, enabled = !isBusy) {
                Text(if (isBusy) "Loading…" else "Refresh", color = BluePrimary)
            }
        }

        if (quietRequests.isNotEmpty()) {
            Surface(
                color = SurfaceMain,
                shape = RoundedCornerShape(20.dp),
                shadowElevation = 4.dp,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            "Pending Quiet Requests",
                            color = DSColor.TextPrimary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 16.sp,
                        )
                        Surface(
                            shape = RoundedCornerShape(10.dp),
                            color = DSColor.QuietAccent.copy(alpha = 0.15f),
                        ) {
                            Text(
                                "${quietRequests.size}",
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                                color = DSColor.QuietAccent,
                                fontWeight = FontWeight.Bold,
                                fontSize = 13.sp,
                            )
                        }
                    }
                    quietRequests.forEach { req ->
                        HorizontalDivider(color = DSColor.Border)
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        req.userName ?: "Unknown User",
                                        color = DSColor.TextPrimary,
                                        fontWeight = FontWeight.SemiBold,
                                        fontSize = 14.sp,
                                    )
                                    Text(
                                        req.tenantName,
                                        color = DSColor.TextSecondary,
                                        fontSize = 12.sp,
                                    )
                                    if (!req.reason.isNullOrBlank()) {
                                        Text(
                                            "\"${req.reason}\"",
                                            color = DSColor.TextTertiary,
                                            fontSize = 12.sp,
                                        )
                                    }
                                }
                                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    OutlinedButton(
                                        onClick = {
                                            pendingApprovalId = req.requestId
                                            pendingApprovalSlug = req.tenantSlug
                                            pendingApprovalIsApprove = false
                                        },
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                                        border = BorderStroke(1.dp, DSColor.Danger.copy(alpha = 0.6f)),
                                        colors = ButtonDefaults.outlinedButtonColors(contentColor = DSColor.Danger),
                                        enabled = !isBusy,
                                    ) {
                                        Text("Deny", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                                    }
                                    Button(
                                        onClick = {
                                            pendingApprovalId = req.requestId
                                            pendingApprovalSlug = req.tenantSlug
                                            pendingApprovalIsApprove = true
                                        },
                                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                                        colors = ButtonDefaults.buttonColors(containerColor = DSColor.QuietAccent),
                                        enabled = !isBusy,
                                    ) {
                                        Text("Approve", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        if (tenants.isEmpty()) {
            Surface(
                color = SurfaceMain,
                shape = RoundedCornerShape(20.dp),
                shadowElevation = 4.dp,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Box(modifier = Modifier.padding(32.dp), contentAlignment = Alignment.Center) {
                    Text(
                        if (isBusy) "Loading schools…" else "No schools found. Tap Refresh to load.",
                        color = TextMuted,
                        fontSize = 14.sp,
                        textAlign = TextAlign.Center,
                    )
                }
            }
        } else {
            tenants.forEach { tenant ->
                DistrictTenantRow(tenant)
            }
        }

        Surface(
            color = SurfaceMain,
            shape = RoundedCornerShape(20.dp),
            shadowElevation = 4.dp,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    "District Audit Log",
                    color = DSColor.TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 16.sp,
                )
                if (auditLog.isEmpty()) {
                    Text("No audit events.", color = TextMuted, fontSize = 13.sp)
                } else {
                    auditLog.take(20).forEach { entry ->
                        HorizontalDivider(color = DSColor.Border)
                        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text(
                                snakeToTitle(entry.eventType),
                                color = DSColor.TextPrimary,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 13.sp,
                            )
                            Text(
                                buildString {
                                    entry.actorLabel?.let { append(it); append(" • ") }
                                    append(entry.timestamp.take(16))
                                },
                                color = DSColor.TextSecondary,
                                fontSize = 11.sp,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DistrictTenantRow(tenant: TenantOverviewItem) {
    val accentColor = when {
        tenant.alarmIsActive && tenant.alarmIsTraining -> DSColor.Warning
        tenant.alarmIsActive -> DSColor.Danger
        else -> DSColor.Success
    }
    Surface(
        color = SurfaceMain,
        shape = RoundedCornerShape(16.dp),
        shadowElevation = 3.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(tenant.tenantName, color = TextPri, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                Text(
                    when {
                        tenant.alarmIsActive && tenant.alarmIsTraining -> "TRAINING DRILL"
                        tenant.alarmIsActive -> tenant.alarmMessage ?: "ALARM ACTIVE"
                        else -> "All Clear"
                    },
                    color = accentColor,
                    fontSize = 13.sp,
                    fontWeight = if (tenant.alarmIsActive) FontWeight.Bold else FontWeight.Normal,
                )
                if (tenant.alarmIsActive && tenant.expectedUserCount > 0) {
                    Text(
                        "Acknowledged: ${tenant.acknowledgementCount}/${tenant.expectedUserCount} (${(tenant.acknowledgementRate * 100).toInt()}%)",
                        color = TextMuted,
                        fontSize = 11.sp,
                    )
                }
            }
            Box(
                modifier = Modifier
                    .size(12.dp)
                    .clip(CircleShape)
                    .background(accentColor),
            )
        }
    }
}

@Composable
private fun BroadcastsCard(broadcasts: List<BroadcastUpdate>, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(20.dp),
        color = SurfaceMain,
        tonalElevation = 2.dp,
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("Admin Updates", color = TextPri, fontWeight = FontWeight.Bold, fontSize = 18.sp)
            broadcasts.take(3).forEach { item ->
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(item.message, color = TextPri, fontSize = 14.sp, fontWeight = FontWeight.Medium)
                    Text(item.createdAt, color = TextMuted, fontSize = 11.sp)
                }
                if (item != broadcasts.take(3).last()) {
                    HorizontalDivider(color = BorderSoft)
                }
            }
        }
    }
}

@Composable
private fun SafetyActionGrid(
    actions: List<SafetyAction>,
    enabled: Boolean,
    onActivate: (SafetyAction) -> Unit,
    onHoldVisual: (Boolean, Float, Color) -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(20.dp),
        color = SurfaceMain,
        tonalElevation = 2.dp,
        shadowElevation = 8.dp,
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            for (row in actions.chunked(2)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    row.forEach { action ->
                        SafetyActionButton(
                            action = action,
                            enabled = enabled,
                            onActivate = { onActivate(action) },
                            onHoldVisual = onHoldVisual,
                            modifier = Modifier.weight(1f),
                        )
                    }
                    if (row.size == 1) {
                        Spacer(modifier = Modifier.weight(1f))
                    }
                }
            }
        }
    }
}

@Composable
private fun SafetyActionButton(
    action: SafetyAction,
    enabled: Boolean,
    onActivate: () -> Unit,
    onHoldVisual: (Boolean, Float, Color) -> Unit,
    modifier: Modifier = Modifier,
) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val haptics = remember { AndroidHoldHaptics(context) }
    val holdProgress = remember(action.key) { Animatable(0f) }
    var holdState by remember(action.key) { mutableStateOf(HoldActivationUiState.Idle) }
    var holdJob by remember(action.key) { mutableStateOf<Job?>(null) }
    var triggered by remember(action.key) { mutableStateOf(false) }

    val ringColor by animateColorAsState(
        targetValue = when {
            holdProgress.value >= 0.8f -> AlarmRed
            holdProgress.value >= 0.55f -> DSColor.Warning
            else -> Color.White.copy(alpha = 0.88f)
        },
        animationSpec = tween(durationMillis = 150),
        label = "actionRingColor",
    )
    val actionScale by animateFloatAsState(
        targetValue = when (holdState) {
            HoldActivationUiState.Idle, HoldActivationUiState.Canceled -> 1f
            HoldActivationUiState.Triggered -> 1.12f
            HoldActivationUiState.Pressing, HoldActivationUiState.Holding, HoldActivationUiState.NearComplete ->
                0.97f + (holdProgress.value * 0.11f)
        },
        animationSpec = spring(dampingRatio = 0.82f, stiffness = Spring.StiffnessMediumLow),
        label = "actionScale",
    )

    fun cancelHold(userCancelled: Boolean) {
        holdJob?.cancel()
        holdJob = null
        if (userCancelled && !triggered && holdProgress.value > 0.01f) {
            haptics.cancel()
            holdState = HoldActivationUiState.Canceled
        }
        scope.launch {
            holdProgress.animateTo(0f, tween(durationMillis = 200, easing = FastOutSlowInEasing))
            if (holdState != HoldActivationUiState.Triggered) {
                holdState = HoldActivationUiState.Idle
            }
            triggered = false
            onHoldVisual(false, 0f, action.color)
        }
    }

    Column(
        modifier = modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .size(122.dp)
                    .pointerInput(action.key, enabled) {
                        detectTapGestures(
                            onPress = {
                                if (!enabled || holdJob?.isActive == true) return@detectTapGestures
                                holdState = HoldActivationUiState.Pressing
                                haptics.touchDown()
                                holdJob = scope.launch {
                                    val holdDurationMs = 3_000L
                                    val start = withFrameNanos { it }
                                    var nextTickMs = 750L
                                    holdProgress.snapTo(0f)
                                    onHoldVisual(true, 0f, action.color)
                                    while (isActive) {
                                        val now = withFrameNanos { it }
                                        val elapsedMs = ((now - start) / 1_000_000L).coerceAtLeast(0L)
                                        val progress = (elapsedMs.toFloat() / holdDurationMs.toFloat()).coerceIn(0f, 1f)
                                        holdProgress.snapTo(progress)
                                        onHoldVisual(true, progress, action.color)
                                        holdState = when {
                                            progress >= 1f -> HoldActivationUiState.Triggered
                                            progress >= 0.8f -> HoldActivationUiState.NearComplete
                                            progress > 0.02f -> HoldActivationUiState.Holding
                                            else -> HoldActivationUiState.Pressing
                                        }
                                        if (elapsedMs >= nextTickMs) {
                                            haptics.progressTick(strong = progress >= 0.8f)
                                            nextTickMs += 750L
                                        }
                                        if (progress >= 1f && !triggered) {
                                            triggered = true
                                            haptics.success()
                                            onHoldVisual(false, 0f, action.color)
                                            onActivate()
                                            return@launch
                                        }
                                    }
                                }
                                val released = tryAwaitRelease()
                                if (!triggered) {
                                    cancelHold(userCancelled = released)
                                }
                            },
                        )
                    }
                    .alpha(if (enabled) 1f else 0.55f),
            ) {
                CircularProgressIndicator(
                    progress = { 1f },
                    color = Color.White.copy(alpha = 0.14f),
                    strokeWidth = 6.dp,
                    modifier = Modifier.fillMaxSize(),
                )
                CircularProgressIndicator(
                    progress = { holdProgress.value },
                    color = ringColor,
                    strokeWidth = 6.dp,
                    modifier = Modifier.fillMaxSize(),
                )
                Surface(
                    shape = CircleShape,
                    color = action.color,
                    modifier = Modifier
                        .size(106.dp)
                        .graphicsLayer {
                            scaleX = actionScale
                            scaleY = actionScale
                        },
                    shadowElevation = (6f + holdProgress.value * 14f).dp,
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Text(action.symbol, fontSize = 34.sp, color = Color.White)
                    }
                }
            }
            Text(
                action.title,
                fontWeight = FontWeight.ExtraBold,
                color = TextPri,
                fontSize = 15.sp,
                textAlign = TextAlign.Center,
                lineHeight = 17.sp,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 34.dp),
            )
            Text(
                when (holdState) {
                    HoldActivationUiState.Idle, HoldActivationUiState.Pressing -> "Hold to Activate"
                    HoldActivationUiState.Holding -> "Keep Holding…"
                    HoldActivationUiState.NearComplete -> "Release to Cancel"
                    HoldActivationUiState.Triggered -> "Activating…"
                    HoldActivationUiState.Canceled -> "Hold to Activate"
                },
                color = Color.White.copy(alpha = 0.86f),
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
            )
    }
    DisposableEffect(action.key) {
        onDispose {
            holdJob?.cancel()
            onHoldVisual(false, 0f, action.color)
        }
    }
}

@Composable
private fun QuietPeriodRequestOverlay(
    isBusy: Boolean,
    errorMsg: String?,
    onCancel: () -> Unit,
    onConfirm: (reason: String?, scheduledStartAt: String?, scheduledEndAt: String?) -> Unit,
    onSuccess: () -> Unit,
) {
    var reason by remember { mutableStateOf("") }
    var submitted by remember { mutableStateOf(false) }
    var scheduleForLater by remember { mutableStateOf(false) }
    var scheduledStart by remember { mutableStateOf<java.time.ZonedDateTime?>(null) }
    var scheduledEnd by remember { mutableStateOf<java.time.ZonedDateTime?>(null) }
    val context = LocalContext.current
    val displayFmt = java.time.format.DateTimeFormatter.ofPattern("MMM d, h:mm a")
    val isoFmt = java.time.format.DateTimeFormatter.ISO_OFFSET_DATE_TIME

    fun pickDateTime(initial: java.time.ZonedDateTime, onPicked: (java.time.ZonedDateTime) -> Unit) {
        val cal = java.util.Calendar.getInstance()
        cal.set(initial.year, initial.monthValue - 1, initial.dayOfMonth, initial.hour, initial.minute)
        android.app.DatePickerDialog(
            context,
            { _, year, month, day ->
                android.app.TimePickerDialog(
                    context,
                    { _, hour, minute ->
                        onPicked(java.time.ZonedDateTime.of(year, month + 1, day, hour, minute, 0, 0, java.time.ZoneId.systemDefault()))
                    },
                    cal.get(java.util.Calendar.HOUR_OF_DAY),
                    cal.get(java.util.Calendar.MINUTE),
                    false,
                ).show()
            },
            cal.get(java.util.Calendar.YEAR),
            cal.get(java.util.Calendar.MONTH),
            cal.get(java.util.Calendar.DAY_OF_MONTH),
        ).show()
    }

    LaunchedEffect(isBusy) {
        if (submitted && !isBusy && errorMsg == null) {
            onSuccess()
        }
    }

    Dialog(
        onDismissRequest = { if (!isBusy) onCancel() },
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        BBModalCard {
            Text(
                "Request Quiet Period",
                color = TextPri,
                fontWeight = FontWeight.Bold,
                fontSize = DSTypography.TitleMedium,
            )
            Text(
                "Admins will be notified and can approve or deny your request.",
                color = TextMuted,
                fontSize = DSTypography.Caption,
            )
            BBTextField(
                value = reason,
                onValueChange = { reason = it },
                label = "Reason (optional)",
                minLines = 2,
                maxLines = 4,
                accentColor = QuietPurple,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Schedule for later", color = TextPri, fontSize = DSTypography.Body)
                Switch(
                    checked = scheduleForLater,
                    onCheckedChange = { on ->
                        scheduleForLater = on
                        if (on) {
                            val now = java.time.ZonedDateTime.now()
                            if (scheduledStart == null) scheduledStart = now.plusHours(1)
                            if (scheduledEnd == null) scheduledEnd = now.plusHours(5)
                        }
                    },
                    colors = SwitchDefaults.colors(checkedThumbColor = QuietPurple, checkedTrackColor = QuietPurple.copy(alpha = 0.4f)),
                )
            }
            if (scheduleForLater) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Start time", color = TextMuted, fontSize = DSTypography.Caption)
                    OutlinedButton(
                        onClick = { pickDateTime(scheduledStart ?: java.time.ZonedDateTime.now().plusHours(1)) { scheduledStart = it; if (scheduledEnd != null && scheduledEnd!! <= it) scheduledEnd = it.plusHours(4) } },
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(10.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = QuietPurple),
                    ) {
                        Text(scheduledStart?.format(displayFmt) ?: "Pick start time", fontWeight = FontWeight.SemiBold)
                    }
                    Text("End time", color = TextMuted, fontSize = DSTypography.Caption)
                    OutlinedButton(
                        onClick = { pickDateTime(scheduledEnd ?: (scheduledStart?.plusHours(4) ?: java.time.ZonedDateTime.now().plusHours(5))) { scheduledEnd = it } },
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(10.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = QuietPurple),
                    ) {
                        Text(scheduledEnd?.format(displayFmt) ?: "Pick end time", fontWeight = FontWeight.SemiBold)
                    }
                }
            }
            if (!errorMsg.isNullOrBlank()) {
                Text(errorMsg, color = AlarmRed, fontSize = DSTypography.Caption)
            }
            BBPrimaryButton(
                text = if (scheduleForLater) "Schedule Request" else "Submit Request",
                onClick = {
                    submitted = true
                    onConfirm(
                        reason.trim().ifBlank { null },
                        if (scheduleForLater) scheduledStart?.format(isoFmt) else null,
                        if (scheduleForLater) scheduledEnd?.format(isoFmt) else null,
                    )
                },
                enabled = !isBusy && (!scheduleForLater || (scheduledStart != null && scheduledEnd != null)),
                isLoading = isBusy,
                modifier = Modifier.fillMaxWidth(),
            )
            TextButton(
                onClick = { if (!isBusy) onCancel() },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Cancel", color = TextMuted, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@Composable
private fun ActivateDialog(isBusy: Boolean, onConfirm: (String) -> Unit, onDismiss: () -> Unit) {
    var message by remember { mutableStateOf("Emergency alert. Please follow school procedures.") }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = SurfaceMain,
        title = { Text("Activate school alarm?", color = TextPri, fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("This will send an emergency alert to all registered devices.", color = TextMuted, fontSize = 14.sp)
                OutlinedTextField(
                    value = message,
                    onValueChange = { message = it },
                    label = { Text("Alert message", color = TextMuted) },
                    minLines = 3,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = AlarmRed,
                        unfocusedBorderColor = BorderSoft,
                        focusedTextColor = TextPri,
                        unfocusedTextColor = TextPri,
                        cursorColor = AlarmRed,
                        focusedContainerColor = SurfaceSoft,
                        unfocusedContainerColor = SurfaceSoft,
                    ),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { if (message.isNotBlank()) onConfirm(message) },
                enabled = !isBusy && message.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = AlarmRed),
            ) {
                Text("Activate", fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel", color = TextMuted)
            }
        },
    )
}

@Composable
private fun ReportDialog(
    isBusy: Boolean,
    onConfirm: (String, String?) -> Unit,
    onDismiss: () -> Unit,
) {
    var selectedCategory by remember { mutableStateOf("need_help") }
    var note by remember { mutableStateOf("") }
    val categories = listOf(
        "safe" to "I Am Safe",
        "need_help" to "Need Help",
        "suspicious_person" to "Suspicious Person",
        "medical_emergency" to "Medical Emergency",
    )

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = SurfaceMain,
        title = { Text("Send structured report", color = TextPri, fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Send a short structured update to admins without opening a chat feed.", color = TextMuted, fontSize = 14.sp)
                categories.forEach { (value, label) ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        RadioButton(
                            selected = selectedCategory == value,
                            onClick = { selectedCategory = value },
                            colors = RadioButtonDefaults.colors(selectedColor = BluePrimary),
                        )
                        Text(label, color = TextPri)
                    }
                }
                OutlinedTextField(
                    value = note,
                    onValueChange = { note = it },
                    label = { Text("Optional note", color = TextMuted) },
                    minLines = 2,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = BluePrimary,
                        unfocusedBorderColor = BorderSoft,
                        focusedTextColor = TextPri,
                        unfocusedTextColor = TextPri,
                        cursorColor = BluePrimary,
                        focusedContainerColor = SurfaceSoft,
                        unfocusedContainerColor = SurfaceSoft,
                    ),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { onConfirm(selectedCategory, note.trim().ifBlank { null }) },
                enabled = !isBusy,
                colors = ButtonDefaults.buttonColors(containerColor = BluePrimary),
            ) { Text("Send") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = TextMuted) }
        },
    )
}

@Composable
private fun TeamAssistDialog(
    titleLabel: String,
    isBusy: Boolean,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var selectedType by remember { mutableStateOf(TeamAssistTypes.first()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(titleLabel, color = TextPri, fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    "Choose a type and send to your school's response team.",
                    color = TextMuted,
                    fontSize = 13.sp,
                )
                TeamAssistTypes.forEach { type ->
                    FilterChip(
                        selected = selectedType == type,
                        onClick = { selectedType = type },
                        label = { Text(type) },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        },
        confirmButton = {
            Button(
                onClick = { onConfirm(selectedType) },
                enabled = !isBusy,
                colors = ButtonDefaults.buttonColors(containerColor = BluePrimary),
            ) {
                Text(if (isBusy) "Sending…" else "Send", fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel", color = TextMuted)
            }
        },
    )
}

@Composable
private fun MessageAdminDialog(
    isBusy: Boolean,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var message by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = SurfaceMain,
        title = { Text("Message Admin", color = TextPri, fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Send a short message to school admins.", color = TextMuted, fontSize = 14.sp)
                OutlinedTextField(
                    value = message,
                    onValueChange = { message = it },
                    label = { Text("Message", color = TextMuted) },
                    placeholder = { Text("Need help in room 204", color = TextMuted) },
                    minLines = 2,
                    maxLines = 4,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = BluePrimary,
                        unfocusedBorderColor = BorderSoft,
                        focusedTextColor = TextPri,
                        unfocusedTextColor = TextPri,
                        cursorColor = BluePrimary,
                        focusedContainerColor = SurfaceSoft,
                        unfocusedContainerColor = SurfaceSoft,
                    ),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { onConfirm(message.trim()) },
                enabled = !isBusy && message.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = BluePrimary),
            ) { Text("Send") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = TextMuted) }
        },
    )
}

@Composable
private fun AdminInboxCard(
    messages: List<AdminInboxMessage>,
    unreadCount: Int,
    recipients: List<InboxRecipient>,
    isBusy: Boolean,
    onSendMessage: (String, List<Int>, Boolean) -> Unit,
    onReply: (AdminInboxMessage) -> Unit,
    modifier: Modifier = Modifier,
) {
    var outboundMessage by remember { mutableStateOf("") }
    var showRecipientPicker by remember { mutableStateOf(false) }
    var sendToAll by remember { mutableStateOf(true) }
    var selectedRecipientIds by remember { mutableStateOf(setOf<Int>()) }
    val recipientLabel = if (sendToAll) {
        "All users"
    } else {
        "${selectedRecipientIds.size} selected"
    }
    CardView(modifier = modifier) {
        SectionContainer("Admin Inbox 🔔 ${if (unreadCount > 0) "($unreadCount)" else ""}") {
            TextInput(
                value = outboundMessage,
                onValueChange = { outboundMessage = it },
                label = "Send a message to users",
                placeholder = "Team update or quick note...",
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedButton(
                onClick = { showRecipientPicker = true },
                enabled = !isBusy,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(10.dp),
            ) {
                Text("Recipients: $recipientLabel", fontWeight = FontWeight.SemiBold)
            }
            PrimaryButton(
                text = if (isBusy) "Sending…" else "Send Message",
                onClick = {
                    val trimmed = outboundMessage.trim()
                    if (trimmed.isNotBlank()) {
                        onSendMessage(trimmed, selectedRecipientIds.toList(), sendToAll)
                        outboundMessage = ""
                    }
                },
                enabled = !isBusy && outboundMessage.isNotBlank() && (sendToAll || selectedRecipientIds.isNotEmpty()),
                isLoading = isBusy,
                modifier = Modifier.fillMaxWidth(),
            )
            if (messages.isEmpty()) {
                Text("No user messages yet.", color = TextMuted, fontSize = 13.sp)
            } else {
                messages.take(4).forEach { item ->
                    Surface(
                        shape = RoundedCornerShape(14.dp),
                        color = SurfaceSoft,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(
                            modifier = Modifier.padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Text(
                                "${item.senderLabel ?: "User"} • ${item.createdAt}",
                                color = TextMuted,
                                fontSize = 12.sp,
                            )
                            Text(item.message, color = TextPri, fontSize = 14.sp, fontWeight = FontWeight.Medium)
                            if (!item.responseMessage.isNullOrBlank()) {
                                Text("Reply: ${item.responseMessage}", color = BlueDark, fontSize = 12.sp)
                            }
                            if (item.status == "open") {
                                OutlinedButton(
                                    onClick = { onReply(item) },
                                    shape = RoundedCornerShape(10.dp),
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Text("Reply", fontWeight = FontWeight.SemiBold)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    if (showRecipientPicker) {
        var query by remember { mutableStateOf("") }
        val filtered = recipients.filter { it.label.contains(query, ignoreCase = true) }
        AlertDialog(
            onDismissRequest = { showRecipientPicker = false },
            containerColor = SurfaceMain,
            title = { Text("Choose recipients", color = TextPri, fontWeight = FontWeight.Bold) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it },
                        label = { Text("Search users", color = TextMuted) },
                        placeholder = { Text("Type a name...", color = TextMuted) },
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = BluePrimary,
                            unfocusedBorderColor = BorderSoft,
                            focusedTextColor = TextPri,
                            unfocusedTextColor = TextPri,
                            cursorColor = BluePrimary,
                            focusedContainerColor = SurfaceSoft,
                            unfocusedContainerColor = SurfaceSoft,
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Checkbox(
                            checked = sendToAll,
                            onCheckedChange = { checked ->
                                sendToAll = checked
                                if (checked) selectedRecipientIds = emptySet()
                            },
                        )
                        Text("Send to all users", color = TextPri)
                    }
                    if (!sendToAll) {
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            filtered.take(12).forEach { recipient ->
                                val checked = selectedRecipientIds.contains(recipient.userId)
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    Checkbox(
                                        checked = checked,
                                        onCheckedChange = { picked ->
                                            selectedRecipientIds = if (picked) {
                                                selectedRecipientIds + recipient.userId
                                            } else {
                                                selectedRecipientIds - recipient.userId
                                            }
                                        },
                                    )
                                    Text(recipient.label, color = TextPri, fontSize = 13.sp)
                                }
                            }
                        }
                    }
                }
            },
            confirmButton = {
                Button(
                    onClick = { showRecipientPicker = false },
                    colors = ButtonDefaults.buttonColors(containerColor = BluePrimary),
                ) {
                    Text("Done")
                }
            },
            dismissButton = {
                TextButton(onClick = { showRecipientPicker = false }) {
                    Text("Close", color = TextMuted)
                }
            },
        )
    }
}

@Composable
private fun AdminReplyDialog(
    target: AdminInboxMessage,
    isBusy: Boolean,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    var reply by remember(target.messageId) { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = SurfaceMain,
        title = { Text("Reply to ${target.senderLabel ?: "user"}", color = TextPri, fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(target.message, color = TextMuted, fontSize = 13.sp)
                OutlinedTextField(
                    value = reply,
                    onValueChange = { reply = it },
                    label = { Text("Reply message", color = TextMuted) },
                    minLines = 2,
                    maxLines = 4,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = BluePrimary,
                        unfocusedBorderColor = BorderSoft,
                        focusedTextColor = TextPri,
                        unfocusedTextColor = TextPri,
                        cursorColor = BluePrimary,
                        focusedContainerColor = SurfaceSoft,
                        unfocusedContainerColor = SurfaceSoft,
                    ),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { onConfirm(reply.trim()) },
                enabled = !isBusy && reply.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = BluePrimary),
            ) { Text("Send Reply") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = TextMuted) }
        },
    )
}

@Composable
private fun ConfirmDialog(title: String, body: String, confirmLabel: String, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = SurfaceMain,
        title = { Text(title, color = TextPri, fontWeight = FontWeight.Bold) },
        text = { Text(body, color = TextMuted) },
        confirmButton = {
            Button(
                onClick = onConfirm,
                colors = ButtonDefaults.buttonColors(containerColor = BluePrimary),
            ) {
                Text(confirmLabel, fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = TextMuted) }
        },
    )
}

@Composable
private fun SettingsScreen(
    onLogout: () -> Unit,
    biometricsEnabled: Boolean,
    hapticAlertsEnabled: Boolean,
    flashlightAlertsEnabled: Boolean,
    screenFlashAlertsEnabled: Boolean,
    darkModeEnabled: Boolean,
    isAlarmActive: Boolean = false,
    onBiometricsChanged: (Boolean) -> Unit,
    onHapticAlertsChanged: (Boolean) -> Unit,
    onFlashlightAlertsChanged: (Boolean) -> Unit,
    onScreenFlashAlertsChanged: (Boolean) -> Unit,
    onDarkModeChanged: (Boolean) -> Unit,
) {
    val ctx = LocalContext.current
    val userName = remember { getUserName(ctx) }
    var showLearningCenter by remember { mutableStateOf(false) }

    if (showLearningCenter) {
        LearningCenterScreen(
            onDismiss = { showLearningCenter = false },
            isAlarmActive = isAlarmActive,
        )
        return
    }
    val loginName = remember { getLoginName(ctx) }
    val userRole = remember { getUserRole(ctx) }
    val userId = remember { getUserId(ctx) }
    val schoolName = remember { getSchoolName(ctx) }
    val activeServerUrl = remember { normalizeServerUrl(getServerUrl(ctx)) }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 20.dp, end = 20.dp, top = 16.dp, bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // Account card
        item {
            Surface(
                color = SurfaceMain,
                shape = RoundedCornerShape(20.dp),
                shadowElevation = 4.dp,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        "ACCOUNT",
                        color = TextMuted,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                        letterSpacing = 0.8.sp,
                    )
                    Text(
                        userName.ifBlank { "BlueBird user" },
                        color = TextPri,
                        fontWeight = FontWeight.Bold,
                        fontSize = 18.sp,
                    )
                    Text(
                        "@${loginName.ifBlank { "unknown" }}",
                        color = BlueLight,
                        fontSize = 13.sp,
                    )
                    HorizontalDivider(color = BorderSoft)
                    if (schoolName.isNotBlank()) {
                        SettingsInfoRow("School", schoolName)
                    }
                    SettingsInfoRow("Role", snakeToTitle(userRole))
                    SettingsInfoRow("User ID", userId)
                    SettingsInfoRow("Server", activeServerUrl, muted = true, small = true)
                }
            }
        }

        // Security card
        item {
            Surface(
                color = SurfaceMain,
                shape = RoundedCornerShape(20.dp),
                shadowElevation = 4.dp,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 18.dp, vertical = 14.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Text("Security", color = TextPri, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                    SettingsToggleRow(
                        title = "Require Biometrics",
                        subtitle = "Require Face ID or fingerprint for emergency and admin actions.",
                        checked = biometricsEnabled,
                        onCheckedChange = onBiometricsChanged,
                    )
                }
            }
        }

        // Emergency feedback card
        item {
            Surface(
                color = SurfaceMain,
                shape = RoundedCornerShape(20.dp),
                shadowElevation = 4.dp,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 18.dp, vertical = 14.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Text("Emergency Feedback", color = TextPri, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                    SettingsToggleRow(
                        title = "Haptic Alerts",
                        subtitle = "Pulse vibration with each active emergency cycle.",
                        checked = hapticAlertsEnabled,
                        onCheckedChange = onHapticAlertsChanged,
                    )
                    SettingsToggleRow(
                        title = "Flashlight Alerts",
                        subtitle = "Flash the device torch while the alert screen is active.",
                        checked = flashlightAlertsEnabled,
                        onCheckedChange = onFlashlightAlertsChanged,
                    )
                    SettingsToggleRow(
                        title = "Screen Flash Alerts",
                        subtitle = "Pulse a full-screen warning overlay during emergencies.",
                        checked = screenFlashAlertsEnabled,
                        onCheckedChange = onScreenFlashAlertsChanged,
                    )
                    Text(
                        "Enable LED Flash Alerts in device settings for enhanced visibility.",
                        color = TextMuted,
                        fontSize = 12.sp,
                    )
                }
            }
        }

        // Appearance card
        item {
            Surface(
                color = SurfaceMain,
                shape = RoundedCornerShape(20.dp),
                shadowElevation = 4.dp,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 18.dp, vertical = 14.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Text("Appearance", color = TextPri, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                    SettingsToggleRow(
                        title = "Dark Mode",
                        subtitle = "Override the system theme and force dark mode.",
                        checked = darkModeEnabled,
                        onCheckedChange = onDarkModeChanged,
                    )
                }
            }
        }

        // Training card
        item {
            val store = remember { lcStore(ctx) }
            Surface(
                color = SurfaceMain,
                shape = RoundedCornerShape(20.dp),
                shadowElevation = 4.dp,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 18.dp, vertical = 14.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text("Training", color = TextPri, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text("Learning Center", color = TextPri, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                            Text(
                                "${store.completedCount} of ${LC_ALL_GUIDES.size} guides completed",
                                color = TextMuted,
                                fontSize = 12.sp,
                            )
                        }
                        TextButton(onClick = { showLearningCenter = true }) {
                            Text("Open", color = BlueLight, fontWeight = FontWeight.SemiBold)
                        }
                    }
                }
            }
        }

        // Sign out
        item {
            Button(
                onClick = onLogout,
                colors = ButtonDefaults.buttonColors(containerColor = AlarmRed),
                modifier = Modifier.fillMaxWidth().height(50.dp),
                shape = RoundedCornerShape(14.dp),
            ) {
                Text("Sign Out", fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@Composable
private fun SettingsInfoRow(label: String, value: String, muted: Boolean = false, small: Boolean = false) {
    val fontSize = if (small) 11.sp else 13.sp
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Top,
    ) {
        Text(label, color = TextMuted, fontSize = fontSize, modifier = Modifier.padding(end = 8.dp))
        Text(
            value,
            color = if (muted) TextMuted else TextPri,
            fontSize = fontSize,
            textAlign = TextAlign.End,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun SettingsToggleRow(
    title: String,
    subtitle: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(title, color = TextPri, fontWeight = FontWeight.SemiBold)
            Text(subtitle, color = TextMuted, fontSize = 12.sp)
        }
        Spacer(Modifier.width(12.dp))
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
        )
    }
}

// ── Alarm sound ────────────────────────────────────────────────────────────────
@Composable
private fun AlertFeedbackEffect(
    isAlarmActive: Boolean,
    isTrainingAlarm: Boolean,
    hapticsEnabled: Boolean,
    flashlightEnabled: Boolean,
    screenFlashEnabled: Boolean,
    silentForMe: Boolean = false,
): AlertFeedbackState {
    val ctx = LocalContext.current
    val appCtx = remember { ctx.applicationContext }
    val feedbackState by AlertFeedbackController.state.collectAsState()

    DisposableEffect(isAlarmActive, isTrainingAlarm, hapticsEnabled, flashlightEnabled, screenFlashEnabled, silentForMe) {
        if (isAlarmActive && !silentForMe) {
            AlertFeedbackController.start(
                appCtx,
                isTraining = isTrainingAlarm,
                hapticsEnabled = hapticsEnabled,
                flashlightEnabled = flashlightEnabled,
                screenFlashEnabled = screenFlashEnabled,
            )
        } else {
            AlertFeedbackController.stop()
        }
        onDispose {
            if (!isAlarmActive) {
                AlertFeedbackController.stop()
            }
        }
    }

    DisposableEffect(Unit) {
        onDispose { AlertFeedbackController.stop() }
    }

    return feedbackState
}

@Composable
private fun AlarmSoundEffect(isAlarmActive: Boolean, isTrainingAlarm: Boolean, silentForMe: Boolean = false) {
    val ctx = LocalContext.current
    val appCtx = remember { ctx.applicationContext }

    DisposableEffect(isAlarmActive, isTrainingAlarm, silentForMe) {
        if (isAlarmActive && !silentForMe) {
            AlarmAudioController.start(appCtx, isTraining = isTrainingAlarm)
        } else {
            AlarmAudioController.stop()
        }
        onDispose {}
    }
    DisposableEffect(Unit) {
        onDispose { AlarmAudioController.release() }
    }
}

private data class AlertFeedbackState(
    val screenFlashAlpha: Float = 0f,
    val screenFlashColor: Color = AlarmRed,
)

private object AlertFeedbackController {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val _state = MutableStateFlow(AlertFeedbackState())
    val state: StateFlow<AlertFeedbackState> get() = _state

    private var job: Job? = null
    private var appContext: Context? = null
    private var vibrator: Vibrator? = null
    private var cameraManager: CameraManager? = null
    private var torchCameraId: String? = null

    @Synchronized
    fun start(
        ctx: Context,
        isTraining: Boolean,
        hapticsEnabled: Boolean,
        flashlightEnabled: Boolean,
        screenFlashEnabled: Boolean,
    ) {
        stop()
        appContext = ctx.applicationContext
        vibrator = resolveVibrator(appContext)
        cameraManager = appContext?.getSystemService(CameraManager::class.java)
        torchCameraId = resolveTorchCameraId(cameraManager)
        val flashColor = if (isTraining) Color(0xFFFFB84D) else AlarmRed
        _state.value = AlertFeedbackState(screenFlashAlpha = 0f, screenFlashColor = flashColor)
        job = scope.launch {
            while (isActive) {
                if (screenFlashEnabled) {
                    _state.value = AlertFeedbackState(
                        screenFlashAlpha = if (isTraining) 0.14f else 0.18f,
                        screenFlashColor = flashColor,
                    )
                } else {
                    _state.value = AlertFeedbackState(screenFlashAlpha = 0f, screenFlashColor = flashColor)
                }
                if (flashlightEnabled) {
                    setTorch(true)
                }
                if (hapticsEnabled) {
                    pulseVibration(isTraining = isTraining)
                }
                delay(300)
                _state.value = AlertFeedbackState(screenFlashAlpha = 0f, screenFlashColor = flashColor)
                if (flashlightEnabled) {
                    setTorch(false)
                }
                if (hapticsEnabled) {
                    runCatching { vibrator?.cancel() }
                }
                delay(300)
            }
        }
    }

    @Synchronized
    fun stop() {
        job?.cancel()
        job = null
        _state.value = AlertFeedbackState()
        runCatching { vibrator?.cancel() }
        setTorch(false)
    }

    private fun resolveVibrator(ctx: Context?): Vibrator? {
        ctx ?: return null
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val mgr = ctx.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
            mgr?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            ctx.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        }
    }

    private fun pulseVibration(isTraining: Boolean) {
        val vib = vibrator ?: return
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vib.vibrate(VibrationEffect.createOneShot(300L, if (isTraining) 120 else 255))
            } else {
                @Suppress("DEPRECATION")
                vib.vibrate(300L)
            }
        }
    }

    private fun resolveTorchCameraId(manager: CameraManager?): String? {
        manager ?: return null
        return runCatching {
            manager.cameraIdList.firstOrNull { id ->
                val chars = manager.getCameraCharacteristics(id)
                chars.get(android.hardware.camera2.CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
            }
        }.getOrNull()
    }

    private fun setTorch(enabled: Boolean) {
        val manager = cameraManager ?: return
        val cameraId = torchCameraId ?: return
        runCatching { manager.setTorchMode(cameraId, enabled) }
    }
}

private object AlarmAudioController {
    private const val TAG = "BlueBirdAlarmAudio"

    private var player: MediaPlayer? = null
    private var appContext: Context? = null
    private var audioManager: AudioManager? = null
    private var hasAudioFocus = false
    private var volumeGuardReceiver: BroadcastReceiver? = null

    @Synchronized
    fun start(ctx: Context, isTraining: Boolean) {
        if (player?.isPlaying == true) {
            Log.d(TAG, "start ignored: already playing")
            return
        }
        appContext = ctx.applicationContext
        ensureAudioFocus()
        runCatching {
            MediaPlayer.create(appContext, R.raw.bluebird_alarm)?.apply {
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build(),
                )
                isLooping = true
                val level = if (isTraining) 0.35f else 1.0f
                setVolume(level, level)
                setOnErrorListener { mp, what, extra ->
                    Log.e(TAG, "player error what=$what extra=$extra")
                    runCatching { mp.stop() }
                    runCatching { mp.reset() }
                    runCatching { mp.release() }
                    player = null
                    false
                }
                start()
            }
        }.onSuccess { created ->
            if (created == null) {
                Log.e(TAG, "Unable to create MediaPlayer for bluebird_alarm.mp3")
                return@onSuccess
            }
            player = created
            enforceMaxAlarmVolume()
            registerVolumeGuard()
            Log.i(TAG, "alarm playback started (training=$isTraining)")
        }.onFailure { err ->
            Log.e(TAG, "Failed to start alarm playback", err)
            stop()
        }
    }

    @Synchronized
    fun stop() {
        Log.i(TAG, "alarm stop requested")
        player?.let { p ->
            runCatching { p.setOnErrorListener(null) }
            runCatching {
                if (p.isPlaying) {
                    p.pause()
                }
            }
            runCatching { p.seekTo(0) }
            runCatching { p.stop() }
            runCatching { p.reset() }
            runCatching { p.release() }.onFailure { err ->
                Log.w(TAG, "Error while releasing player", err)
            }
        }
        player = null
        runCatching {
            val nm = appContext?.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager
            nm?.cancel(ALERT_PUSH_NOTIFICATION_ID)
        }
        unregisterVolumeGuard()
        abandonAudioFocus()
        Log.i(TAG, "alarm playback stopped")
    }

    @Synchronized
    fun release() {
        stop()
        appContext = null
    }

    private fun ensureAudioFocus() {
        val ctx = appContext ?: return
        val am = audioManager ?: (ctx.getSystemService(Context.AUDIO_SERVICE) as? AudioManager).also { audioManager = it }
        if (am == null || hasAudioFocus) return
        val result = am.requestAudioFocus(
            null,
            AudioManager.STREAM_ALARM,
            AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE,
        )
        hasAudioFocus = (result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED)
        Log.d(TAG, "audio focus granted=$hasAudioFocus")
    }

    private fun abandonAudioFocus() {
        val am = audioManager ?: return
        if (!hasAudioFocus) return
        runCatching { am.abandonAudioFocus(null) }
        hasAudioFocus = false
    }

    private fun enforceMaxAlarmVolume() {
        val am = audioManager ?: return
        val maxVolume = am.getStreamMaxVolume(AudioManager.STREAM_ALARM)
        if (maxVolume <= 0) return
        val current = am.getStreamVolume(AudioManager.STREAM_ALARM)
        if (current != maxVolume) {
            am.setStreamVolume(AudioManager.STREAM_ALARM, maxVolume, 0)
            Log.w(TAG, "Alarm stream volume forced to max ($maxVolume)")
        }
    }

    private fun registerVolumeGuard() {
        val ctx = appContext ?: return
        if (volumeGuardReceiver != null) return
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) {
                if (intent?.action != "android.media.VOLUME_CHANGED_ACTION") return
                val streamType = intent.getIntExtra("android.media.EXTRA_VOLUME_STREAM_TYPE", -1)
                if (streamType == AudioManager.STREAM_ALARM && player?.isPlaying == true) {
                    enforceMaxAlarmVolume()
                }
            }
        }
        volumeGuardReceiver = receiver
        ctx.registerReceiver(receiver, IntentFilter("android.media.VOLUME_CHANGED_ACTION"))
        Log.d(TAG, "Volume guard receiver registered")
    }

    private fun unregisterVolumeGuard() {
        val ctx = appContext ?: return
        val receiver = volumeGuardReceiver ?: return
        runCatching { ctx.unregisterReceiver(receiver) }
        volumeGuardReceiver = null
    }
}

// ── Tenant settings data classes ───────────────────────────────────────────────

data class TenantNotificationSettings(
    val nonCriticalSoundName: String = "notification_soft",
    val nonCriticalSoundEnabled: Boolean = true,
    val quietPeriodNotificationsEnabled: Boolean = true,
    val adminMessageNotificationsEnabled: Boolean = true,
    val accessCodeNotificationsEnabled: Boolean = true,
    val auditNotificationsEnabled: Boolean = false,
    val criticalAlertSoundLocked: Boolean = true,
)

data class TenantQuietPeriodSettings(
    val enabled: Boolean = true,
    val requiresApproval: Boolean = true,
    val allowScheduling: Boolean = true,
    val maxDurationMinutes: Int = 1440,
    val defaultDurationMinutes: Int = 60,
    val allowSelfApproval: Boolean = false,
    val districtAdminCanApproveAll: Boolean = true,
    val buildingAdminScope: String = "building",
)

data class TenantAlertSettings(
    val teachersCanTriggerSecurePerimeter: Boolean = true,
    val teachersCanTriggerLockdown: Boolean = true,
    val lawEnforcementCanTrigger: Boolean = false,
    val requireHoldToActivate: Boolean = true,
    val holdSeconds: Int = 3,
    val disableRequiresAdmin: Boolean = true,
)

data class TenantDeviceSettings(
    val deviceStatusReportingEnabled: Boolean = true,
    val markDeviceStaleAfterMinutes: Int = 30,
    val excludeInactiveDevicesFromPush: Boolean = true,
)

data class TenantAccessCodeSettings(
    val enabled: Boolean = true,
    val autoExpireEnabled: Boolean = true,
    val defaultExpirationDays: Int = 14,
    val autoArchiveRevokedEnabled: Boolean = false,
    val autoArchiveRevokedAfterDays: Int = 7,
)

data class TenantSettings(
    val notifications: TenantNotificationSettings = TenantNotificationSettings(),
    val quietPeriods: TenantQuietPeriodSettings = TenantQuietPeriodSettings(),
    val alerts: TenantAlertSettings = TenantAlertSettings(),
    val devices: TenantDeviceSettings = TenantDeviceSettings(),
    val accessCodes: TenantAccessCodeSettings = TenantAccessCodeSettings(),
)

// ── Backend client ─────────────────────────────────────────────────────────────
internal class BackendClient(baseUrl: String, private val apiKey: String) {
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()
    private val json = "application/json; charset=utf-8".toMediaType()
    private val base = baseUrl.trimEnd('/')

    private fun Request.Builder.withAuth() = apply {
        if (apiKey.isNotBlank()) header("X-API-Key", apiKey)
    }

    private fun JSONObject.optNullableString(key: String): String? {
        val value = optString(key).trim()
        return value.takeIf { it.isNotEmpty() && !it.equals("null", ignoreCase = true) }
    }

    fun listSchools(): List<SchoolOption> {
        val req = Request.Builder().url("${BuildConfig.BACKEND_BASE_URL}/schools").get().build()
        http.newCall(req).execute().use { res ->
            val bodyText = requireSuccess(res)
            val json = JSONObject(bodyText)
            val schoolsJson = json.optJSONArray("schools")
            return buildList {
                if (schoolsJson != null) {
                    for (i in 0 until schoolsJson.length()) {
                        val item = schoolsJson.optJSONObject(i) ?: continue
                        add(
                            SchoolOption(
                                name = item.optString("name"),
                                slug = item.optString("slug"),
                                path = item.optString("path"),
                            )
                        )
                    }
                }
            }
        }
    }

    fun configLabels(): Map<String, String> {
        val req = Request.Builder()
            .url("$base/config/labels")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val payload = JSONObject(requireSuccess(res))
            val labels = mutableMapOf<String, String>()
            val keys = payload.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                val value = payload.optString(key).trim()
                if (value.isNotBlank()) {
                    labels[key] = value
                }
            }
            return labels
        }
    }

    fun login(username: String, password: String): AuthUser {
        val body = JSONObject()
            .put("login_name", username.trim().lowercase())
            .put("password", password)
        val req = Request.Builder()
            .url("$base/auth/login")
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { res ->
            val bodyText = requireSuccess(res)
            val j = JSONObject(bodyText)
            return AuthUser(
                userId = j.getInt("user_id"),
                name = j.getString("name"),
                role = j.getString("role"),
                loginName = j.getString("login_name"),
                mustChangePassword = j.optBoolean("must_change_password"),
                canDeactivateAlarm = j.optBoolean("can_deactivate_alarm"),
            )
        }
    }

    fun registerAndroidDevice(token: String, userId: Int?, deviceId: String? = null) {
        val body = JSONObject()
            .put("device_token", token.trim())
            .put("platform", "android")
            .put("push_provider", "fcm")
            .put("device_name", currentDeviceName())
            .apply { userId?.let { put("user_id", it) } }
            .apply { deviceId?.let { put("device_id", it) } }
        val req = Request.Builder()
            .url("$base/register-device")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
    }

    fun heartbeat(token: String) {
        val body = JSONObject()
            .put("device_token", token.trim())
            .put("push_provider", "fcm")
        val req = Request.Builder()
            .url("$base/devices/heartbeat")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        runCatching { http.newCall(req).execute().use { it.close() } }
    }

    fun deregisterAndroidDevice(token: String, userId: Int?, deviceId: String?) {
        val body = JSONObject()
            .put("device_token", token.trim())
            .put("push_provider", "fcm")
            .apply { userId?.let { put("user_id", it) } }
            .apply { deviceId?.let { put("device_id", it) } }
        val req = Request.Builder()
            .url("$base/deregister-device")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        runCatching { http.newCall(req).execute().use { it.close() } }
    }

    fun alarmStatus(): AlarmStatus {
        val req = Request.Builder().url("$base/alarm/status").withAuth().get().build()
        http.newCall(req).execute().use { res ->
            val body = requireSuccess(res)
            val j = JSONObject(body)
            val broadcastsJson = j.optJSONArray("broadcasts")
            val broadcasts = buildList {
                if (broadcastsJson != null) {
                    for (i in 0 until broadcastsJson.length()) {
                        val item = broadcastsJson.optJSONObject(i) ?: continue
                        add(
                            BroadcastUpdate(
                                updateId = item.optInt("update_id"),
                                createdAt = item.optString("created_at"),
                                adminUserId = if (item.has("admin_user_id") && !item.isNull("admin_user_id")) item.optInt("admin_user_id") else null,
                                adminLabel = item.optString("admin_label").ifBlank { null },
                                message = item.optString("message"),
                            )
                        )
                    }
                }
            }
            return AlarmStatus(
                isActive                = j.optBoolean("is_active"),
                message                 = j.optString("message").ifBlank { null },
                activatedAt             = j.optString("activated_at").ifBlank { null },
                activatedByUserId       = if (j.has("activated_by_user_id") && !j.isNull("activated_by_user_id"))
                    j.optInt("activated_by_user_id") else null,
                activatedByLabel        = j.optString("activated_by_label").ifBlank { null },
                broadcasts              = broadcasts,
                acknowledgementCount    = j.optInt("acknowledgement_count", 0),
                expectedUserCount       = j.optInt("expected_user_count", 0),
                acknowledgementPercentage = j.optDouble("acknowledgement_percentage", 0.0).toFloat(),
                currentUserAcknowledged = j.optBoolean("current_user_acknowledged", false),
                alertId                 = if (j.has("current_alert_id") && !j.isNull("current_alert_id"))
                    j.optInt("current_alert_id") else null,
            )
        }
    }

    data class SyncStateResult(val alarm: AlarmStatus, val quietPeriod: QuietPeriodMobileStatus?)

    fun syncState(userId: Int?): SyncStateResult {
        val url = if (userId != null) "$base/sync/state?user_id=$userId" else "$base/sync/state"
        val req = Request.Builder().url(url).withAuth().get().build()
        http.newCall(req).execute().use { res ->
            val body = requireSuccess(res)
            val root = JSONObject(body)
            val aj = root.optJSONObject("alarm") ?: JSONObject()
            val broadcastsJson = aj.optJSONArray("broadcasts")
            val broadcasts = buildList {
                if (broadcastsJson != null) {
                    for (i in 0 until broadcastsJson.length()) {
                        val item = broadcastsJson.optJSONObject(i) ?: continue
                        add(BroadcastUpdate(
                            updateId = item.optInt("update_id"),
                            createdAt = item.optString("created_at"),
                            adminUserId = null,
                            adminLabel = item.optString("admin_label").ifBlank { null },
                            message = item.optString("message"),
                        ))
                    }
                }
            }
            val alarm = AlarmStatus(
                isActive                = aj.optBoolean("is_active"),
                message                 = aj.optString("message").ifBlank { null },
                isTraining              = aj.optBoolean("is_training"),
                trainingLabel           = aj.optString("training_label").ifBlank { null },
                activatedAt             = aj.optString("activated_at").ifBlank { null },
                activatedByLabel        = aj.optString("activated_by_label").ifBlank { null },
                broadcasts              = broadcasts,
                acknowledgementCount    = aj.optInt("acknowledgement_count", 0),
                expectedUserCount       = aj.optInt("expected_user_count", 0),
                acknowledgementPercentage = aj.optDouble("acknowledgement_percentage", 0.0).toFloat(),
                currentUserAcknowledged = aj.optBoolean("current_user_acknowledged", false),
                alertId                 = if (aj.has("current_alert_id") && !aj.isNull("current_alert_id"))
                    aj.optInt("current_alert_id") else null,
            )
            val qj = root.optJSONObject("quiet_period")
            val quiet = if (qj != null) QuietPeriodMobileStatus(
                requestId    = if (qj.has("request_id") && !qj.isNull("request_id")) qj.optInt("request_id") else null,
                status       = qj.optNullableString("status"),
                reason       = qj.optNullableString("reason"),
                requestedAt  = qj.optNullableString("requested_at"),
                approvedAt   = qj.optNullableString("approved_at"),
                approvedByLabel = qj.optNullableString("approved_by_label"),
                expiresAt    = qj.optNullableString("expires_at"),
                scheduledStartAt = qj.optNullableString("scheduled_start_at"),
                scheduledEndAt   = qj.optNullableString("scheduled_end_at"),
            ) else null
            return SyncStateResult(alarm = alarm, quietPeriod = quiet)
        }
    }

    fun sendReport(userId: Int?, category: String, note: String?) {
        val body = JSONObject().put("category", category).apply {
            userId?.let { put("user_id", it) }
            note?.let { put("note", it) }
        }
        val req = Request.Builder()
            .url("$base/reports")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
    }

    fun messageAdmin(userId: Int?, message: String) {
        val body = JSONObject().put("message", message).apply { userId?.let { put("user_id", it) } }
        val req = Request.Builder()
            .url("$base/message-admin")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
    }

    fun sendMessageFromAdmin(adminUserId: Int, message: String, recipientUserIds: List<Int>, sendToAll: Boolean): Int {
        val body = JSONObject()
            .put("admin_user_id", adminUserId)
            .put("message", message)
            .put("send_to_all", sendToAll)
            .apply {
                if (recipientUserIds.isNotEmpty()) {
                    put("recipient_user_ids", JSONArray(recipientUserIds))
                }
            }
        val req = Request.Builder()
            .url("$base/messages/send")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { res ->
            val payload = JSONObject(requireSuccess(res))
            return payload.optInt("sent_count", 0)
        }
    }

    fun listMessageRecipients(): List<InboxRecipient> {
        val req = Request.Builder()
            .url("$base/users")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val body = requireSuccess(res)
            val usersJson = JSONObject(body).optJSONArray("users")
            return buildList {
                if (usersJson != null) {
                    for (i in 0 until usersJson.length()) {
                        val item = usersJson.optJSONObject(i) ?: continue
                        val isActive = item.optBoolean("is_active", true)
                        val role = item.optString("role").lowercase()
                        val userId = item.optInt("user_id", 0)
                        if (!isActive || role == "admin" || role == "building_admin" || userId <= 0) continue
                        add(
                            InboxRecipient(
                                userId = userId,
                                label = "${item.optString("name")} (${item.optString("role")})",
                            )
                        )
                    }
                }
            }.sortedBy { it.label.lowercase() }
        }
    }

    fun listTeamAssistActionRecipients(): List<TeamAssistActionRecipient> {
        val req = Request.Builder()
            .url("$base/users")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val body = requireSuccess(res)
            val usersJson = JSONObject(body).optJSONArray("users")
            return buildList {
                if (usersJson != null) {
                    for (i in 0 until usersJson.length()) {
                        val item = usersJson.optJSONObject(i) ?: continue
                        val isActive = item.optBoolean("is_active", true)
                        val userId = item.optInt("user_id", 0)
                        if (!isActive || userId <= 0) continue
                        add(
                            TeamAssistActionRecipient(
                                userId = userId,
                                label = "${item.optString("name")} (${item.optString("role")})",
                            )
                        )
                    }
                }
            }.sortedBy { it.label.lowercase() }
        }
    }

    fun messageInbox(userId: Int): MessageInboxResponse {
        val req = Request.Builder()
            .url("$base/messages/inbox?user_id=$userId&limit=40")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val body = requireSuccess(res)
            val j = JSONObject(body)
            val messagesJson = j.optJSONArray("messages")
            val messages = buildList {
                if (messagesJson != null) {
                    for (i in 0 until messagesJson.length()) {
                        val item = messagesJson.optJSONObject(i) ?: continue
                        add(
                            AdminInboxMessage(
                                messageId = item.optInt("message_id"),
                                createdAt = item.optString("created_at"),
                                senderUserId = if (item.has("sender_user_id") && !item.isNull("sender_user_id")) item.optInt("sender_user_id") else null,
                                senderLabel = item.optString("sender_label").ifBlank { null },
                                message = item.optString("message"),
                                status = item.optString("status"),
                                responseMessage = item.optString("response_message").ifBlank { null },
                                responseCreatedAt = item.optString("response_created_at").ifBlank { null },
                                responseByLabel = item.optString("response_by_label").ifBlank { null },
                            )
                        )
                    }
                }
            }
            return MessageInboxResponse(
                unreadCount = j.optInt("unread_count"),
                messages = messages,
            )
        }
    }

    fun replyAdminMessage(adminUserId: Int, messageId: Int, message: String) {
        val body = JSONObject()
            .put("admin_user_id", adminUserId)
            .put("message_id", messageId)
            .put("message", message)
        val req = Request.Builder()
            .url("$base/messages/reply")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
    }

    fun requestQuietPeriod(userId: Int, reason: String?, scheduledStartAt: String? = null, scheduledEndAt: String? = null) {
        val body = JSONObject()
            .put("user_id", userId)
            .apply { reason?.let { put("reason", it) } }
            .apply { scheduledStartAt?.let { put("scheduled_start_at", it) } }
            .apply { scheduledEndAt?.let { put("scheduled_end_at", it) } }
        val req = Request.Builder()
            .url("$base/quiet-periods/request")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        Log.d("QuietPeriod", "BackendClient → POST $base/quiet-periods/request body=$body")
        http.newCall(req).execute().use { res ->
            Log.d("QuietPeriod", "BackendClient ← ${res.code}")
            requireSuccess(res)
        }
    }

    fun listAdminQuietPeriodRequests(adminUserId: Int): List<AdminQuietPeriodRequest> {
        val req = Request.Builder()
            .url("$base/quiet-periods/admin/requests?admin_user_id=$adminUserId&limit=120")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val body = JSONObject(requireSuccess(res))
            val items = body.optJSONArray("requests")
            return buildList {
                if (items != null) {
                    for (i in 0 until items.length()) {
                        val item = items.optJSONObject(i) ?: continue
                        add(
                            AdminQuietPeriodRequest(
                                requestId = item.optInt("request_id"),
                                userId = item.optInt("user_id"),
                                userName = item.optNullableString("user_name"),
                                userRole = item.optNullableString("user_role"),
                                reason = item.optNullableString("reason"),
                                status = item.optString("status"),
                                requestedAt = item.optString("requested_at"),
                                approvedAt = item.optNullableString("approved_at"),
                                approvedByLabel = item.optNullableString("approved_by_label"),
                                expiresAt = item.optNullableString("expires_at"),
                                scheduledStartAt = item.optNullableString("scheduled_start_at"),
                                scheduledEndAt = item.optNullableString("scheduled_end_at"),
                            ),
                        )
                    }
                }
            }
        }
    }

    fun approveQuietPeriodRequest(requestId: Int, adminUserId: Int) {
        val body = JSONObject().put("admin_user_id", adminUserId)
        val req = Request.Builder()
            .url("$base/quiet-periods/$requestId/approve")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
    }

    fun denyQuietPeriodRequest(requestId: Int, adminUserId: Int) {
        val body = JSONObject().put("admin_user_id", adminUserId)
        val req = Request.Builder()
            .url("$base/quiet-periods/$requestId/deny")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
    }

    fun alarmPushStats(userId: Int): PushDeliveryStats {
        val req = Request.Builder()
            .url("$base/alarm/push-stats?user_id=$userId")
            .withAuth().get().build()
        http.newCall(req).execute().use { res ->
            val j = JSONObject(requireSuccess(res))
            val byProvider = buildMap<String, ProviderDeliveryStats> {
                val bp = j.optJSONObject("by_provider")
                if (bp != null) {
                    bp.keys().forEach { key ->
                        val pj = bp.optJSONObject(key) ?: return@forEach
                        put(key, ProviderDeliveryStats(
                            total = pj.optInt("total", 0),
                            ok = pj.optInt("ok", 0),
                            failed = pj.optInt("failed", 0),
                            lastError = pj.optNullableString("last_error"),
                        ))
                    }
                }
            }
            return PushDeliveryStats(
                total = j.optInt("total", 0),
                ok = j.optInt("ok", 0),
                failed = j.optInt("failed", 0),
                lastError = j.optNullableString("last_error"),
                byProvider = byProvider,
            )
        }
    }

    fun auditLog(
        userId: Int,
        limit: Int = 25,
        offset: Int = 0,
        search: String? = null,
        eventType: String? = null,
    ): List<AuditLogEntry> {
        val sb = StringBuilder("$base/audit-log?user_id=$userId&limit=$limit&offset=$offset")
        if (!search.isNullOrBlank()) sb.append("&search=").append(java.net.URLEncoder.encode(search, "UTF-8"))
        if (!eventType.isNullOrBlank()) sb.append("&event_type=").append(java.net.URLEncoder.encode(eventType, "UTF-8"))
        val req = Request.Builder()
            .url(sb.toString())
            .withAuth().get().build()
        http.newCall(req).execute().use { res ->
            val j = JSONObject(requireSuccess(res))
            val items = j.optJSONArray("events")
            return buildList {
                if (items != null) {
                    for (i in 0 until items.length()) {
                        val item = items.optJSONObject(i) ?: continue
                        add(
                            AuditLogEntry(
                                id = item.optInt("id"),
                                timestamp = item.optString("timestamp"),
                                eventType = item.optString("event_type"),
                                actorLabel = item.optNullableString("actor_label"),
                                targetType = item.optNullableString("target_type"),
                            )
                        )
                    }
                }
            }
        }
    }

    fun deleteQuietPeriodRequest(requestId: Int, userId: Int) {
        val body = JSONObject().put("user_id", userId)
        val req = Request.Builder()
            .url("$base/quiet-periods/$requestId/delete")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
    }

    fun quietPeriodStatus(userId: Int): QuietPeriodMobileStatus {
        val req = Request.Builder()
            .url("$base/quiet-periods/status?user_id=$userId")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val body = requireSuccess(res)
            val j = JSONObject(body)
            return QuietPeriodMobileStatus(
                requestId = if (j.has("request_id") && !j.isNull("request_id")) j.optInt("request_id") else null,
                status = j.optNullableString("status"),
                reason = j.optNullableString("reason"),
                requestedAt = j.optNullableString("requested_at"),
                approvedAt = j.optNullableString("approved_at"),
                approvedByLabel = j.optNullableString("approved_by_label"),
                expiresAt = j.optNullableString("expires_at"),
                scheduledStartAt = j.optNullableString("scheduled_start_at"),
                scheduledEndAt = j.optNullableString("scheduled_end_at"),
            )
        }
    }

    fun createRequestHelp(userId: Int, type: String): TeamAssistFeedItem {
        val body = JSONObject()
            .put("user_id", userId)
            .put("type", type)
            .put("assigned_team_ids", JSONArray())
        val req = Request.Builder()
            .url("$base/team-assist/create")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { res ->
            val item = JSONObject(requireSuccess(res))
            return TeamAssistFeedItem(
                id = item.optInt("id"),
                type = item.optString("type"),
                status = item.optString("status"),
                createdBy = item.optInt("created_by"),
                createdAt = item.optString("created_at"),
                actedByLabel = item.optNullableString("acted_by_label"),
                forwardToLabel = item.optNullableString("forward_to_label"),
                cancelledByUserId = if (!item.isNull("cancelled_by_user_id")) item.optInt("cancelled_by_user_id") else null,
                cancelReasonText = item.optNullableString("cancel_reason_text"),
                cancelReasonCategory = item.optNullableString("cancel_reason_category"),
            )
        }
    }

    fun createTeamAssist(userId: Int, type: String): TeamAssistFeedItem {
        return createRequestHelp(userId = userId, type = type)
    }

    fun updateRequestHelpAction(teamAssistId: Int, actorUserId: Int, action: String, forwardToUserId: Int? = null): TeamAssistFeedItem {
        val body = JSONObject()
            .put("user_id", actorUserId)
            .put("action", action)
            .apply {
                if (forwardToUserId != null) put("forward_to_user_id", forwardToUserId)
            }
        val req = Request.Builder()
            .url("$base/team-assist/$teamAssistId/action")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { res ->
            val item = JSONObject(requireSuccess(res))
            return TeamAssistFeedItem(
                id = item.optInt("id"),
                type = item.optString("type"),
                status = item.optString("status"),
                createdBy = item.optInt("created_by"),
                createdAt = item.optString("created_at"),
                actedByLabel = item.optNullableString("acted_by_label"),
                forwardToLabel = item.optNullableString("forward_to_label"),
                cancelledByUserId = if (!item.isNull("cancelled_by_user_id")) item.optInt("cancelled_by_user_id") else null,
                cancelReasonText = item.optNullableString("cancel_reason_text"),
                cancelReasonCategory = item.optNullableString("cancel_reason_category"),
            )
        }
    }

    fun updateTeamAssistAction(teamAssistId: Int, actorUserId: Int, action: String, forwardToUserId: Int? = null): TeamAssistFeedItem {
        return updateRequestHelpAction(
            teamAssistId = teamAssistId,
            actorUserId = actorUserId,
            action = action,
            forwardToUserId = forwardToUserId,
        )
    }

    fun cancelTeamAssist(teamAssistId: Int, userId: Int, reasonText: String, reasonCategory: String): TeamAssistFeedItem {
        val body = JSONObject()
            .put("user_id", userId)
            .put("cancel_reason_text", reasonText)
            .put("cancel_reason_category", reasonCategory)
        val req = Request.Builder()
            .url("$base/team-assist/$teamAssistId/cancel")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { res ->
            val item = JSONObject(requireSuccess(res))
            return TeamAssistFeedItem(
                id = item.optInt("id"),
                type = item.optString("type"),
                status = item.optString("status"),
                createdBy = item.optInt("created_by"),
                createdAt = item.optString("created_at"),
                actedByLabel = item.optNullableString("acted_by_label"),
                forwardToLabel = item.optNullableString("forward_to_label"),
                cancelledByUserId = if (!item.isNull("cancelled_by_user_id")) item.optInt("cancelled_by_user_id") else null,
                cancelReasonText = item.optNullableString("cancel_reason_text"),
                cancelReasonCategory = item.optNullableString("cancel_reason_category"),
            )
        }
    }

    fun activeRequestHelp(): List<TeamAssistFeedItem> {
        val req = Request.Builder()
            .url("$base/team-assist/active")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val body = JSONObject(requireSuccess(res))
            val items = body.optJSONArray("team_assists")
            return buildList {
                if (items != null) {
                    for (i in 0 until items.length()) {
                        val item = items.optJSONObject(i) ?: continue
                        add(
                            TeamAssistFeedItem(
                                id = item.optInt("id"),
                                type = item.optString("type"),
                                status = item.optString("status"),
                                createdBy = item.optInt("created_by"),
                                createdAt = item.optString("created_at"),
                                actedByLabel = item.optNullableString("acted_by_label"),
                                forwardToLabel = item.optNullableString("forward_to_label"),
                                cancelledByUserId = if (!item.isNull("cancelled_by_user_id")) item.optInt("cancelled_by_user_id") else null,
                                cancelReasonText = item.optNullableString("cancel_reason_text"),
                                cancelReasonCategory = item.optNullableString("cancel_reason_category"),
                            ),
                        )
                    }
                }
            }
        }
    }

    fun activeTeamAssists(): List<TeamAssistFeedItem> {
        return activeRequestHelp()
    }

    fun activeIncidents(): List<IncidentFeedItem> {
        val req = Request.Builder()
            .url("$base/incidents/active")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val body = JSONObject(requireSuccess(res))
            val items = body.optJSONArray("incidents")
            return buildList {
                if (items != null) {
                    for (i in 0 until items.length()) {
                        val item = items.optJSONObject(i) ?: continue
                        add(
                            IncidentFeedItem(
                                id = item.optInt("id"),
                                type = item.optString("type"),
                                status = item.optString("status"),
                                createdBy = item.optInt("created_by"),
                                createdAt = item.optString("created_at"),
                                targetScope = item.optString("target_scope"),
                            ),
                        )
                    }
                }
            }
        }
    }

    fun activateAlarm(
        message: String,
        userId: Int?,
        isTraining: Boolean = false,
        trainingLabel: String? = null,
    ): AlarmStatus {
        val body = JSONObject()
            .put("message", message)
            .put("is_training", isTraining)
            .apply {
                userId?.let { put("user_id", it) }
                val cleanedLabel = trainingLabel?.trim().orEmpty()
                if (cleanedLabel.isNotEmpty()) {
                    put("training_label", cleanedLabel)
                }
            }
        val req = Request.Builder()
            .url("$base/alarm/activate")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        return http.newCall(req).execute().use { parseAlarm(it) }
    }

    fun deactivateAlarm(userId: Int?): AlarmStatus {
        val body = JSONObject().apply { userId?.let { put("user_id", it) } }
        val req = Request.Builder()
            .url("$base/alarm/deactivate")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        return http.newCall(req).execute().use { parseAlarm(it) }
    }

    fun acknowledgeAlert(alertId: Int, userId: Int) {
        val body = JSONObject().put("user_id", userId)
        val req = Request.Builder()
            .url("$base/alerts/$alertId/ack")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
    }

    fun sendAlertMessage(alertId: Int, userId: Int, message: String, recipientId: Int? = null): Int {
        val body = JSONObject()
            .put("user_id", userId)
            .put("message", message)
        if (recipientId != null) body.put("recipient_id", recipientId)
        val req = Request.Builder()
            .url("$base/alerts/$alertId/messages/send")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { res ->
            val text = requireSuccess(res)
            return JSONObject(text).optInt("id", -1)
        }
    }

    fun broadcastAlertMessage(alertId: Int, userId: Int, message: String): Int {
        val body = JSONObject().put("user_id", userId).put("message", message)
        val req = Request.Builder()
            .url("$base/alerts/$alertId/messages/broadcast")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { res ->
            val text = requireSuccess(res)
            return JSONObject(text).optInt("id", -1)
        }
    }

    fun remindUnacknowledged(alertId: Int, adminUserId: Int): Pair<Int, Int> {
        val body = JSONObject().put("user_id", adminUserId)
        val req = Request.Builder()
            .url("$base/alerts/$alertId/remind")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { res ->
            val text = requireSuccess(res)
            val j = JSONObject(text)
            return Pair(j.optInt("reminded_count", 0), j.optInt("skipped_no_device", 0))
        }
    }

    private fun parseAlarm(res: okhttp3.Response): AlarmStatus {
        val body = requireSuccess(res)
        val j = JSONObject(body)
        val broadcastsJson = j.optJSONArray("broadcasts")
        val broadcasts = buildList {
            if (broadcastsJson != null) {
                for (i in 0 until broadcastsJson.length()) {
                    val item = broadcastsJson.optJSONObject(i) ?: continue
                    add(
                        BroadcastUpdate(
                            updateId = item.optInt("update_id"),
                            createdAt = item.optString("created_at"),
                            adminUserId = if (item.has("admin_user_id") && !item.isNull("admin_user_id")) item.optInt("admin_user_id") else null,
                            message = item.optString("message"),
                        )
                    )
                }
            }
        }
        return AlarmStatus(
            isActive                 = j.optBoolean("is_active"),
            message                  = j.optString("message").ifBlank { null },
            isTraining               = j.optBoolean("is_training", false),
            trainingLabel            = j.optNullableString("training_label"),
            activatedAt              = j.optString("activated_at").ifBlank { null },
            activatedByUserId        = if (j.has("activated_by_user_id") && !j.isNull("activated_by_user_id"))
                j.optInt("activated_by_user_id") else null,
            activatedByLabel         = j.optString("activated_by_label").ifBlank { null },
            broadcasts               = broadcasts,
            acknowledgementCount     = j.optInt("acknowledgement_count", 0),
            expectedUserCount        = j.optInt("expected_user_count", 0),
            acknowledgementPercentage = j.optDouble("acknowledgement_percentage", 0.0).toFloat(),
            currentUserAcknowledged  = j.optBoolean("current_user_acknowledged", false),
            alertId                  = if (j.has("current_alert_id") && !j.isNull("current_alert_id"))
                j.optInt("current_alert_id") else null,
        )
    }

    fun getMe(userId: Int): MeData {
        val req = Request.Builder()
            .url("$base/me?user_id=$userId")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val body = requireSuccess(res)
            val j = JSONObject(body)
            val tenantsJson = j.optJSONArray("tenants")
            val tenants = buildList {
                if (tenantsJson != null) {
                    for (i in 0 until tenantsJson.length()) {
                        val item = tenantsJson.optJSONObject(i) ?: continue
                        add(TenantSummaryItem(
                            tenantSlug = item.optString("tenant_slug"),
                            tenantName = item.optString("tenant_name"),
                            role = item.optNullableString("role"),
                        ))
                    }
                }
            }
            return MeData(
                userId = j.optInt("user_id"),
                name = j.optString("name"),
                role = j.optString("role"),
                loginName = j.optString("login_name"),
                title = j.optNullableString("title"),
                canDeactivateAlarm = j.optBoolean("can_deactivate_alarm"),
                tenants = tenants,
                selectedTenant = j.optString("selected_tenant").ifBlank { tenants.firstOrNull()?.tenantSlug ?: "" },
            )
        }
    }

    fun getDistrictOverview(userId: Int): List<TenantOverviewItem> {
        val req = Request.Builder()
            .url("$base/district/overview?user_id=$userId")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val body = requireSuccess(res)
            val j = JSONObject(body)
            val tenantsJson = j.optJSONArray("tenants")
            return buildList {
                if (tenantsJson != null) {
                    for (i in 0 until tenantsJson.length()) {
                        val item = tenantsJson.optJSONObject(i) ?: continue
                        add(TenantOverviewItem(
                            tenantSlug = item.optString("tenant_slug"),
                            tenantName = item.optString("tenant_name"),
                            alarmIsActive = item.optBoolean("alarm_is_active"),
                            alarmMessage = item.optNullableString("alarm_message"),
                            alarmIsTraining = item.optBoolean("alarm_is_training"),
                            lastAlertAt = item.optNullableString("last_alert_at"),
                            acknowledgementCount = item.optInt("acknowledgement_count"),
                            expectedUserCount = item.optInt("expected_user_count"),
                            acknowledgementRate = item.optDouble("acknowledgement_rate", 0.0),
                        ))
                    }
                }
            }
        }
    }

    fun listDistrictQuietPeriods(userId: Int): List<DistrictQuietPeriodItem> {
        val req = Request.Builder()
            .url("$base/district/quiet-periods?user_id=$userId")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val body = JSONObject(requireSuccess(res))
            val items = body.optJSONArray("requests")
            return buildList {
                if (items != null) {
                    for (i in 0 until items.length()) {
                        val item = items.optJSONObject(i) ?: continue
                        add(DistrictQuietPeriodItem(
                            requestId = item.optInt("request_id"),
                            userId = item.optInt("user_id"),
                            userName = item.optNullableString("user_name"),
                            userRole = item.optNullableString("user_role"),
                            reason = item.optNullableString("reason"),
                            status = item.optString("status"),
                            requestedAt = item.optString("requested_at"),
                            approvedAt = item.optNullableString("approved_at"),
                            approvedByLabel = item.optNullableString("approved_by_label"),
                            deniedAt = item.optNullableString("denied_at"),
                            cancelledAt = item.optNullableString("cancelled_at"),
                            expiresAt = item.optNullableString("expires_at"),
                            scheduledStartAt = item.optNullableString("scheduled_start_at"),
                            scheduledEndAt = item.optNullableString("scheduled_end_at"),
                            countdownTargetAt = item.optNullableString("countdown_target_at"),
                            countdownMode = item.optNullableString("countdown_mode"),
                            tenantSlug = item.optString("tenant_slug"),
                            tenantName = item.optString("tenant_name"),
                        ))
                    }
                }
            }
        }
    }

    fun approveDistrictQuietPeriod(requestId: Int, adminUserId: Int, tenantSlug: String) {
        val body = JSONObject().put("admin_user_id", adminUserId).put("tenant_slug", tenantSlug)
        val req = Request.Builder()
            .url("$base/district/quiet-periods/$requestId/approve")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
    }

    fun denyDistrictQuietPeriod(requestId: Int, adminUserId: Int, tenantSlug: String) {
        val body = JSONObject().put("admin_user_id", adminUserId).put("tenant_slug", tenantSlug)
        val req = Request.Builder()
            .url("$base/district/quiet-periods/$requestId/deny")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
    }

    fun listDistrictAuditLog(userId: Int, limit: Int = 50): List<AuditLogEntry> {
        val req = Request.Builder()
            .url("$base/district/audit-log?user_id=$userId&limit=$limit")
            .withAuth().get().build()
        http.newCall(req).execute().use { res ->
            val j = JSONObject(requireSuccess(res))
            val items = j.optJSONArray("events")
            return buildList {
                if (items != null) {
                    for (i in 0 until items.length()) {
                        val item = items.optJSONObject(i) ?: continue
                        add(AuditLogEntry(
                            id = item.optInt("id"),
                            timestamp = item.optString("timestamp"),
                            eventType = item.optString("event_type"),
                            actorLabel = item.optNullableString("actor_label"),
                            targetType = item.optNullableString("target_type"),
                        ))
                    }
                }
            }
        }
    }

    fun getTenantSettings(): TenantSettings {
        val req = Request.Builder()
            .url("$base/tenant-settings")
            .withAuth()
            .get()
            .build()
        http.newCall(req).execute().use { res ->
            val body = requireSuccess(res)
            val j = JSONObject(body)
            val n  = j.optJSONObject("notifications")  ?: JSONObject()
            val q  = j.optJSONObject("quiet_periods")  ?: JSONObject()
            val a  = j.optJSONObject("alerts")         ?: JSONObject()
            val d  = j.optJSONObject("devices")        ?: JSONObject()
            val ac = j.optJSONObject("access_codes")   ?: JSONObject()
            return TenantSettings(
                notifications = TenantNotificationSettings(
                    nonCriticalSoundName              = n.optString("non_critical_sound_name", "notification_soft"),
                    nonCriticalSoundEnabled           = n.optBoolean("non_critical_sound_enabled", true),
                    quietPeriodNotificationsEnabled   = n.optBoolean("quiet_period_notifications_enabled", true),
                    adminMessageNotificationsEnabled  = n.optBoolean("admin_message_notifications_enabled", true),
                    accessCodeNotificationsEnabled    = n.optBoolean("access_code_notifications_enabled", true),
                    auditNotificationsEnabled         = n.optBoolean("audit_notifications_enabled", false),
                    criticalAlertSoundLocked          = n.optBoolean("critical_alert_sound_locked", true),
                ),
                quietPeriods = TenantQuietPeriodSettings(
                    enabled                     = q.optBoolean("enabled", true),
                    requiresApproval            = q.optBoolean("requires_approval", true),
                    allowScheduling             = q.optBoolean("allow_scheduling", true),
                    maxDurationMinutes          = q.optInt("max_duration_minutes", 1440),
                    defaultDurationMinutes      = q.optInt("default_duration_minutes", 60),
                    allowSelfApproval           = q.optBoolean("allow_self_approval", false),
                    districtAdminCanApproveAll  = q.optBoolean("district_admin_can_approve_all", true),
                    buildingAdminScope          = q.optString("building_admin_scope", "building"),
                ),
                alerts = TenantAlertSettings(
                    teachersCanTriggerSecurePerimeter = a.optBoolean("teachers_can_trigger_secure_perimeter", true),
                    teachersCanTriggerLockdown        = a.optBoolean("teachers_can_trigger_lockdown", true),
                    lawEnforcementCanTrigger          = a.optBoolean("law_enforcement_can_trigger", false),
                    requireHoldToActivate             = a.optBoolean("require_hold_to_activate", true),
                    holdSeconds                       = a.optInt("hold_seconds", 3),
                    disableRequiresAdmin              = a.optBoolean("disable_requires_admin", true),
                ),
                devices = TenantDeviceSettings(
                    deviceStatusReportingEnabled   = d.optBoolean("device_status_reporting_enabled", true),
                    markDeviceStaleAfterMinutes    = d.optInt("mark_device_stale_after_minutes", 30),
                    excludeInactiveDevicesFromPush = d.optBoolean("exclude_inactive_devices_from_push", true),
                ),
                accessCodes = TenantAccessCodeSettings(
                    enabled                      = ac.optBoolean("enabled", true),
                    autoExpireEnabled            = ac.optBoolean("auto_expire_enabled", true),
                    defaultExpirationDays        = ac.optInt("default_expiration_days", 14),
                    autoArchiveRevokedEnabled    = ac.optBoolean("auto_archive_revoked_enabled", false),
                    autoArchiveRevokedAfterDays  = ac.optInt("auto_archive_revoked_after_days", 7),
                ),
            )
        }
    }

    private fun requireSuccess(res: okhttp3.Response): String {
        val body = res.body?.string().orEmpty()
        if (!res.isSuccessful) {
            val detail = runCatching { JSONObject(body).optString("detail") }.getOrDefault(body)
            error(detail.ifBlank { "Request failed (${res.code})" })
        }
        return body
    }

    fun validateInviteCode(code: String, tenantSlug: String): JSONObject {
        val body = JSONObject().apply {
            put("code", code.trim().uppercase())
            put("tenant_slug", tenantSlug.trim())
        }.toString().toRequestBody(json)
        val req = Request.Builder()
            .url("${BuildConfig.BACKEND_BASE_URL}/onboarding/validate-code")
            .post(body).build()
        return http.newCall(req).execute().use { res -> JSONObject(requireSuccess(res)) }
    }

    fun createAccountFromCode(code: String, tenantSlug: String, name: String, loginName: String, password: String): JSONObject {
        val body = JSONObject().apply {
            put("code", code.trim().uppercase())
            put("tenant_slug", tenantSlug.trim())
            put("name", name.trim())
            put("login_name", loginName.trim().lowercase())
            put("password", password)
        }.toString().toRequestBody(json)
        val req = Request.Builder()
            .url("${BuildConfig.BACKEND_BASE_URL}/onboarding/create-account")
            .post(body).build()
        return http.newCall(req).execute().use { res -> JSONObject(requireSuccess(res)) }
    }

    fun validateSetupCode(code: String): JSONObject {
        val body = JSONObject().apply {
            put("code", code.trim().uppercase())
        }.toString().toRequestBody(json)
        val req = Request.Builder()
            .url("${BuildConfig.BACKEND_BASE_URL}/onboarding/validate-setup-code")
            .post(body).build()
        return http.newCall(req).execute().use { res -> JSONObject(requireSuccess(res)) }
    }

    fun createDistrictAdmin(code: String, name: String, loginName: String, password: String): JSONObject {
        val body = JSONObject().apply {
            put("code", code.trim().uppercase())
            put("name", name.trim())
            put("login_name", loginName.trim().lowercase())
            put("password", password)
        }.toString().toRequestBody(json)
        val req = Request.Builder()
            .url("${BuildConfig.BACKEND_BASE_URL}/onboarding/create-district-admin")
            .post(body).build()
        return http.newCall(req).execute().use { res -> JSONObject(requireSuccess(res)) }
    }
}

internal data class MessageInboxResponse(
    val unreadCount: Int,
    val messages: List<AdminInboxMessage>,
)

// ── Onboarding sheet ──────────────────────────────────────────────────────────

private sealed class OnboardingStep {
    object EnterCode : OnboardingStep()
    data class Validated(
        val role: String,
        val roleLabel: String,
        val title: String?,
        val tenantSlug: String,
        val tenantName: String,
        val isSetup: Boolean = false,
    ) : OnboardingStep()
    data class CreateAccount(val tenantSlug: String, val isSetup: Boolean) : OnboardingStep()
    object Success : OnboardingStep()
}

private fun onboardingRoleCaps(role: String): List<String> = when (role.lowercase()) {
    "building_admin" -> listOf(
        "Manage school users and access codes",
        "Trigger and deactivate emergency alerts",
        "Approve or deny quiet period requests",
        "View incident feed and audit log",
    )
    "district_admin" -> listOf(
        "Oversee multiple schools from one account",
        "View cross-school incident and alert feed",
        "Approve quiet period requests across buildings",
    )
    "law_enforcement" -> listOf(
        "Receive emergency alerts instantly",
        "View incident feed and respond to help requests",
        "Submit status updates during incidents",
    )
    "staff" -> listOf(
        "Receive school emergency alerts",
        "Request a quiet period from admins",
        "Submit and track help requests",
        "Send status updates during incidents",
    )
    else -> listOf(
        "Receive school emergency alerts",
        "Submit and track help requests",
        "Send status updates during incidents",
    )
}

@Composable
private fun OnboardingSheet(onDone: (username: String) -> Unit, onCancel: () -> Unit) {
    var step by remember { mutableStateOf<OnboardingStep>(OnboardingStep.EnterCode) }
    var codeText by remember { mutableStateOf("") }
    var tenantSlugText by remember { mutableStateOf("") }
    var nameText by remember { mutableStateOf("") }
    var usernameText by remember { mutableStateOf("") }
    var passwordText by remember { mutableStateOf("") }
    var confirmPasswordText by remember { mutableStateOf("") }
    var isBusy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val client = remember { BackendClient(BuildConfig.BACKEND_BASE_URL, BuildConfig.BACKEND_API_KEY) }
    val shakeOffset = remember { Animatable(0f) }
    val haptic = LocalHapticFeedback.current

    fun doValidate(code: String, slug: String) {
        if (code.length < 4) { error = "Enter a valid invite code."; return }
        scope.launch(Dispatchers.IO) {
            isBusy = true; error = null
            runCatching {
                if (slug.isNotBlank()) {
                    val res = client.validateInviteCode(code, slug)
                    if (res.optBoolean("valid", false)) {
                        step = OnboardingStep.Validated(
                            role = res.optString("role"),
                            roleLabel = res.optString("role_label").ifBlank { res.optString("role") },
                            title = res.optString("title").takeIf { it.isNotBlank() },
                            tenantSlug = res.optString("tenant_slug"),
                            tenantName = res.optString("tenant_name"),
                            isSetup = false,
                        )
                    } else {
                        error = res.optString("error").ifBlank { "Invalid or expired code." }
                    }
                } else {
                    val res = client.validateSetupCode(code)
                    if (res.optBoolean("valid", false)) {
                        step = OnboardingStep.Validated(
                            role = "district_admin",
                            roleLabel = "District Admin",
                            title = null,
                            tenantSlug = res.optString("tenant_slug"),
                            tenantName = res.optString("tenant_name"),
                            isSetup = true,
                        )
                    } else {
                        error = res.optString("error").ifBlank { "Invalid or expired code. Enter your district code above if you have an invite code." }
                    }
                }
            }.onFailure { error = it.message }
            isBusy = false
        }
    }

    val qrScanLauncher = rememberLauncherForActivityResult(ScanContract()) { result ->
        val content = result.contents ?: return@rememberLauncherForActivityResult
        try {
            val json = JSONObject(content)
            when (json.optString("type")) {
                "bluebird_invite" -> {
                    val code = json.getString("code").trim().uppercase()
                    val slug = json.getString("tenant_slug").trim().lowercase()
                    codeText = code
                    tenantSlugText = slug
                    doValidate(code, slug)
                }
                "bluebird_setup" -> {
                    val code = json.getString("code").trim().uppercase()
                    codeText = code
                    tenantSlugText = ""
                    doValidate(code, "")
                }
                else -> {
                    error = "This QR code is not a BlueBird invite code."
                }
            }
        } catch (e: Exception) {
            error = "Could not read QR code. Try entering the code manually."
        }
    }

    fun triggerShake() {
        scope.launch {
            repeat(3) {
                shakeOffset.animateTo(-10f, tween(50))
                shakeOffset.animateTo(10f, tween(50))
            }
            shakeOffset.animateTo(0f)
        }
    }

    Surface(
        modifier = Modifier.fillMaxSize(),
        color = DSColor.Background,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "Get Started",
                    fontSize = 22.sp,
                    fontWeight = FontWeight.Bold,
                    color = DSColor.TextPrimary,
                )
                TextButton(onClick = onCancel) {
                    Text("Cancel", color = BluePrimary)
                }
            }

            when (val s = step) {
                is OnboardingStep.EnterCode -> {
                    Text(
                        "Scan your invite QR code or enter the code manually.",
                        fontSize = 14.sp,
                        color = DSColor.TextSecondary,
                    )
                    OutlinedButton(
                        onClick = {
                            qrScanLauncher.launch(
                                ScanOptions()
                                    .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                                    .setPrompt("Scan your BlueBird invite QR code")
                                    .setBeepEnabled(true)
                                    .setBarcodeImageEnabled(false)
                            )
                        },
                        modifier = Modifier.fillMaxWidth().height(52.dp),
                        border = BorderStroke(1.5.dp, BluePrimary),
                        enabled = !isBusy,
                    ) {
                        Text("Scan QR Code", color = BluePrimary, fontSize = 15.sp, fontWeight = FontWeight.Medium)
                    }
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        HorizontalDivider(modifier = Modifier.weight(1f), color = DSColor.Border)
                        Text("  or enter manually  ", fontSize = 12.sp, color = DSColor.TextSecondary)
                        HorizontalDivider(modifier = Modifier.weight(1f), color = DSColor.Border)
                    }
                    OutlinedTextField(
                        value = tenantSlugText,
                        onValueChange = { tenantSlugText = it.trim().lowercase() },
                        label = { Text("District Code") },
                        placeholder = { Text("e.g. nen") },
                        supportingText = { Text("Enter the district code provided by your administrator. Leave blank for district admin setup codes.") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                    OutlinedTextField(
                        value = codeText,
                        onValueChange = { codeText = it.uppercase() },
                        label = { Text("Invite Code") },
                        placeholder = { Text("e.g. ABCD1234") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                    if (error != null) {
                        Text(error!!, color = DSColor.Danger, fontSize = 13.sp)
                    }
                    PrimaryButton(
                        text = if (isBusy) "Checking…" else "Validate Code",
                        onClick = { doValidate(codeText.trim().uppercase(), tenantSlugText.trim().lowercase()) },
                        enabled = !isBusy && codeText.trim().length >= 4,
                        isLoading = isBusy,
                        modifier = Modifier.fillMaxWidth().height(52.dp),
                    )
                }
                is OnboardingStep.Validated -> {
                    Surface(
                        shape = RoundedCornerShape(14.dp),
                        color = DSColor.Card,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(
                            modifier = Modifier.padding(16.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Text("Code Verified ✓", fontWeight = FontWeight.SemiBold, color = DSColor.Success)
                            Text("School: ${s.tenantName}", fontSize = 14.sp, color = DSColor.TextPrimary)
                            Text("Role: ${s.roleLabel}", fontSize = 14.sp, color = DSColor.TextPrimary)
                            if (!s.title.isNullOrBlank()) {
                                Text("Title: ${s.title}", fontSize = 14.sp, color = DSColor.TextPrimary)
                            }
                        }
                    }
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = DSColor.Background,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(
                            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Text(
                                "What you can do:",
                                fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = DSColor.TextSecondary,
                            )
                            onboardingRoleCaps(s.role).forEach { cap ->
                                Row(
                                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                                    verticalAlignment = Alignment.Top,
                                ) {
                                    Text("•", fontSize = 13.sp, color = DSColor.Primary)
                                    Text(cap, fontSize = 13.sp, color = DSColor.TextPrimary)
                                }
                            }
                        }
                    }
                    PrimaryButton(
                        text = "Create My Account",
                        onClick = { step = OnboardingStep.CreateAccount(s.tenantSlug, s.isSetup) },
                        enabled = true,
                        modifier = Modifier.fillMaxWidth().height(52.dp),
                    )
                    TextButton(onClick = { step = OnboardingStep.EnterCode; codeText = ""; tenantSlugText = ""; error = null }) {
                        Text("Try a Different Code", color = DSColor.TextSecondary, fontSize = 13.sp)
                    }
                }
                is OnboardingStep.CreateAccount -> {
                    val isFormValid = nameText.isNotBlank() &&
                        usernameText.isNotBlank() &&
                        passwordText.length >= 8 &&
                        confirmPasswordText == passwordText &&
                        confirmPasswordText.isNotEmpty()
                    val buttonAlpha by animateFloatAsState(
                        targetValue = if (isFormValid) 1f else 0.5f,
                        label = "buttonAlpha",
                    )
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .offset(x = shakeOffset.value.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp),
                    ) {
                        OutlinedTextField(
                            value = nameText,
                            onValueChange = { nameText = it },
                            label = { Text("Full Name") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                        )
                        OutlinedTextField(
                            value = usernameText,
                            onValueChange = { usernameText = it.lowercase() },
                            label = { Text("Username") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                        )
                        OutlinedTextField(
                            value = passwordText,
                            onValueChange = { passwordText = it },
                            label = { Text("Password (min 8 characters)") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            visualTransformation = PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        )
                        OutlinedTextField(
                            value = confirmPasswordText,
                            onValueChange = { confirmPasswordText = it },
                            label = { Text("Confirm Password") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            visualTransformation = PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        )
                        if (error != null) {
                            Text(error!!, color = DSColor.Danger, fontSize = 13.sp)
                        }
                        PrimaryButton(
                            text = if (isBusy) "Creating Account…" else "Create Account",
                            onClick = {
                                if (!isFormValid) {
                                    haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                    triggerShake()
                                    return@PrimaryButton
                                }
                                val name = nameText.trim()
                                val username = usernameText.trim().lowercase()
                                scope.launch(Dispatchers.IO) {
                                    isBusy = true; error = null
                                    runCatching {
                                        val code = codeText.trim().uppercase()
                                        val res = if (s.isSetup) {
                                            client.createDistrictAdmin(code, name, username, passwordText)
                                        } else {
                                            client.createAccountFromCode(code, s.tenantSlug, name, username, passwordText)
                                        }
                                        if (res.optBoolean("valid", false)) {
                                            step = OnboardingStep.Success
                                        } else {
                                            error = res.optString("error").ifBlank { "Could not create account." }
                                        }
                                    }.onFailure { error = it.message }
                                    isBusy = false
                                }
                            },
                            enabled = !isBusy,
                            isLoading = isBusy,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(52.dp)
                                .alpha(buttonAlpha),
                        )
                    }
                }
                is OnboardingStep.Success -> {
                    Column(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(16.dp),
                    ) {
                        Text("✓", fontSize = 64.sp, color = DSColor.Success)
                        Text(
                            "Account Created!",
                            fontSize = 22.sp,
                            fontWeight = FontWeight.Bold,
                            color = DSColor.TextPrimary,
                        )
                        Text(
                            "Your username has been filled in. Enter your password to sign in.",
                            fontSize = 14.sp,
                            color = DSColor.TextSecondary,
                            textAlign = TextAlign.Center,
                        )
                        PrimaryButton(
                            text = "Go to Sign In",
                            onClick = { onDone(usernameText) },
                            enabled = true,
                            modifier = Modifier.fillMaxWidth().height(52.dp),
                        )
                    }
                }
            }
        }
    }
}
