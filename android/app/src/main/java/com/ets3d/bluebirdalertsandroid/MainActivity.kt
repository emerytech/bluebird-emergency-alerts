package com.ets3d.bluebirdalertsandroid

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.fragment.app.FragmentActivity
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

// ── Brand colours ─────────────────────────────────────────────────────────────
private val AppBg       = Color(0xFFEEF5FF)
private val AppBgDeep   = Color(0xFFDCE9FF)
private val SurfaceMain = Color(0xFFFFFFFF)
private val SurfaceSoft = Color(0xFFF6FAFF)
private val BorderSoft  = Color(0x1A123478)
private val BluePrimary = Color(0xFF1B5FE4)
private val BlueLight   = Color(0xFF2F84FF)
private val BlueDark    = Color(0xFF092054)
private val QuietPurple = Color(0xFF8E3BEB)
private val AlarmRed    = Color(0xFFDC2626)
private val AlarmGreen  = Color(0xFF16A34A)
private val TextPri     = Color(0xFF10203F)
private val TextMuted   = Color(0xFF5D7398)
private val TextOnDark  = Color(0xFFF8FAFC)

// ── Prefs ──────────────────────────────────────────────────────────────────────
private const val PREFS      = "bluebird_prefs"
private const val KEY_UID    = "user_id"
private const val KEY_SETUP  = "setup_done"
private const val KEY_NAME   = "user_name"
private const val KEY_ROLE   = "user_role"
private const val KEY_LOGIN  = "login_name"
private const val KEY_CAN_DEACTIVATE = "can_deactivate"
private const val KEY_SERVER_URL = "server_url"
private const val KEY_BIOMETRICS_ALLOWED = "biometrics_allowed"
internal const val NOTIF_CH   = "bluebird_alerts"

private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
private fun isSetupDone(ctx: Context) = prefs(ctx).getBoolean(KEY_SETUP, false)
private fun getUserId(ctx: Context)   = prefs(ctx).getString(KEY_UID, "") ?: ""
private fun getUserName(ctx: Context) = prefs(ctx).getString(KEY_NAME, "") ?: ""
private fun getUserRole(ctx: Context) = prefs(ctx).getString(KEY_ROLE, "") ?: ""
private fun getLoginName(ctx: Context) = prefs(ctx).getString(KEY_LOGIN, "") ?: ""
private fun canDeactivateAlarm(ctx: Context) = prefs(ctx).getBoolean(KEY_CAN_DEACTIVATE, false)
private fun getServerUrl(ctx: Context) = prefs(ctx).getString(KEY_SERVER_URL, "") ?: ""
private fun biometricsAllowed(ctx: Context) = prefs(ctx).getBoolean(KEY_BIOMETRICS_ALLOWED, false)
private fun setBiometricsAllowed(ctx: Context, allowed: Boolean) {
    prefs(ctx).edit().putBoolean(KEY_BIOMETRICS_ALLOWED, allowed).apply()
}

private fun Context.findActivity(): FragmentActivity? = when (this) {
    is FragmentActivity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
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
    if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) return trimmed
    if (!trimmed.contains(".") && !trimmed.contains("/")) return schoolBaseUrl(trimmed)
    if (trimmed.startsWith("/")) return BuildConfig.BACKEND_BASE_URL + trimmed
    return "https://$trimmed"
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
    val channel = NotificationChannel(
        NOTIF_CH,
        "BlueBird Alerts",
        NotificationManager.IMPORTANCE_HIGH,
    ).apply {
        description = "Emergency school alerts"
        enableVibration(true)
        setSound(
            RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM),
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build(),
        )
    }
    (context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
        .createNotificationChannel(channel)
}

private data class AuthUser(
    val userId: Int,
    val name: String,
    val role: String,
    val loginName: String,
    val mustChangePassword: Boolean,
    val canDeactivateAlarm: Boolean,
)

private data class SchoolOption(
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
)

private data class SafetyAction(
    val key: String,
    val title: String,
    val iconRes: Int,
    val color: Color,
    val message: String,
)

private fun buildSafetyActions(featureLabels: Map<String, String>): List<SafetyAction> = listOf(
    SafetyAction(
        key = AppLabels.KEY_SECURE,
        title = AppLabels.labelForFeatureKey(AppLabels.KEY_SECURE, featureLabels).uppercase(),
        iconRes = android.R.drawable.ic_menu_compass,
        color = Color(0xFF5EA8F2),
        message = "SECURE emergency initiated. Follow school secure procedures.",
    ),
    SafetyAction(
        key = AppLabels.KEY_LOCKDOWN,
        title = AppLabels.labelForFeatureKey(AppLabels.KEY_LOCKDOWN, featureLabels).uppercase(),
        iconRes = android.R.drawable.ic_lock_lock,
        color = Color(0xFFE0524D),
        message = "LOCKDOWN emergency initiated. Follow lockdown procedures immediately.",
    ),
    SafetyAction(
        key = AppLabels.KEY_EVACUATION,
        title = AppLabels.labelForFeatureKey(AppLabels.KEY_EVACUATION, featureLabels).uppercase(),
        iconRes = android.R.drawable.ic_menu_directions,
        color = Color(0xFF93CB43),
        message = "EVACUATE emergency initiated. Move to evacuation locations now.",
    ),
    SafetyAction(
        key = AppLabels.KEY_SHELTER,
        title = AppLabels.labelForFeatureKey(AppLabels.KEY_SHELTER, featureLabels).uppercase(),
        iconRes = android.R.drawable.ic_menu_myplaces,
        color = Color(0xFFE6A23C),
        message = "SHELTER emergency initiated. Move into shelter protocol.",
    ),
    SafetyAction(
        key = "hold",
        title = "HOLD",
        iconRes = android.R.drawable.ic_media_pause,
        color = Color(0xFF8E3BEB),
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

// ── Data ───────────────────────────────────────────────────────────────────────
data class AlarmStatus(
    val isActive: Boolean = false,
    val message: String?  = null,
    val activatedAt: String? = null,
    val activatedByUserId: Int? = null,
    val broadcasts: List<BroadcastUpdate> = emptyList(),
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
    val cancelRequesterConfirmed: Boolean = false,
    val cancelAdminConfirmed: Boolean = false,
    val cancelAdminLabel: String? = null,
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
    val featureLabels: Map<String, String> = AppLabels.DEFAULT_FEATURE_LABELS,
)

// ── ViewModel ──────────────────────────────────────────────────────────────────
class MainViewModel : ViewModel() {
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state

    private var client: BackendClient? = null

    fun init(ctx: Context) {
        if (client != null) return
        client = BackendClient(
            baseUrl = getServerUrl(ctx),
            apiKey  = BuildConfig.BACKEND_API_KEY,
        )
        refreshFeatureLabels()
        registerPushToken(ctx)
        startPolling(ctx)
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
            val userId = getUserId(ctx).toIntOrNull()
            viewModelScope.launch(Dispatchers.IO) {
                runCatching { client?.registerAndroidDevice(token, userId) }
            }
        }
    }

    private fun startPolling(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull()
        viewModelScope.launch(Dispatchers.IO) {
            var tick = 0
            while (isActive) {
                runCatching { client!!.alarmStatus() }
                    .onSuccess { alarm ->
                        _state.update { it.copy(alarm = alarm, connected = true) }
                    }
                    .onFailure {
                        _state.update { it.copy(connected = false) }
                    }
                if (userId != null) {
                    runCatching { client!!.quietPeriodStatus(userId = userId) }
                        .onSuccess { quiet ->
                            _state.update { it.copy(quietPeriodStatus = quiet) }
                        }
                }
                refreshIncidentFeedsOnce()
                tick += 1
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

    private suspend fun refreshIncidentFeedsOnce() {
        runCatching { client!!.activeIncidents() }
            .onSuccess { incidents ->
                _state.update { it.copy(activeIncidents = incidents) }
            }
        runCatching { client!!.activeRequestHelp() }
            .onSuccess { teamAssists ->
                _state.update { it.copy(activeTeamAssists = teamAssists) }
            }
    }

    fun refreshIncidentFeeds() {
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isRefreshingFeed = true) }
            refreshIncidentFeedsOnce()
            _state.update { it.copy(isRefreshingFeed = false) }
        }
    }

    fun activateAlarm(ctx: Context, message: String) {
        val userId = getUserId(ctx).toIntOrNull()
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.activateAlarm(message, userId) }
                .onSuccess { alarm ->
                    _state.update { it.copy(alarm = alarm, isBusy = false, successMsg = "Alarm activated.") }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to activate alarm.") }
                }
        }
    }

    fun deactivateAlarm(ctx: Context) {
        val userId = getUserId(ctx).toIntOrNull()
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.deactivateAlarm(userId) }
                .onSuccess { alarm ->
                    _state.update { it.copy(alarm = alarm, isBusy = false, successMsg = "Alarm cleared.") }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to deactivate alarm.") }
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
                    _state.update { it.copy(adminQuietPeriodRequests = requests) }
                }
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

    fun requestQuietPeriod(ctx: Context, reason: String?) {
        val userId = getUserId(ctx).toIntOrNull()
        if (userId == null) {
            _state.update { it.copy(errorMsg = "You must be signed in to request a quiet period.") }
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.requestQuietPeriod(userId = userId, reason = reason) }
                .onSuccess {
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

    fun confirmRequestHelpCancel(ctx: Context, teamAssistId: Int) {
        val actorUserId = getUserId(ctx).toIntOrNull()
        if (actorUserId == null) {
            _state.update { it.copy(errorMsg = "Sign-in is required.") }
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            _state.update { it.copy(isBusy = true, errorMsg = null) }
            runCatching { client!!.confirmRequestHelpCancel(teamAssistId = teamAssistId, actorUserId = actorUserId) }
                .onSuccess { updated ->
                    val activeTeamAssists = runCatching { client!!.activeRequestHelp() }.getOrDefault(_state.value.activeTeamAssists)
                    _state.update {
                        it.copy(
                            isBusy = false,
                            successMsg = if (updated.status.equals("cancelled", ignoreCase = true)) {
                                "Request help cancelled after dual confirmation."
                            } else {
                                "Cancellation confirmation saved. Waiting for second confirmation."
                            },
                            activeTeamAssists = activeTeamAssists,
                        )
                    }
                }
                .onFailure { e ->
                    _state.update { it.copy(isBusy = false, errorMsg = e.message ?: "Failed to confirm request-help cancellation.") }
                }
        }
    }

    fun confirmTeamAssistCancel(ctx: Context, teamAssistId: Int) {
        confirmRequestHelpCancel(ctx = ctx, teamAssistId = teamAssistId)
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
        ensureNotificationChannel(this)
        askNotificationPermission()
        setContent {
            BlueBirdTheme {
                App()
            }
        }
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
@Composable
private fun BlueBirdTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary   = BluePrimary,
            background = AppBg,
            surface   = SurfaceMain,
            onPrimary  = TextOnDark,
            onBackground = TextPri,
            onSurface  = TextPri,
            error      = AlarmRed,
        ),
        content = content,
    )
}

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
private fun App() {
    val ctx = LocalContext.current
    var setupDone by remember { mutableStateOf(isSetupDone(ctx)) }

    if (!setupDone) {
        LoginScreen(onDone = { setupDone = true })
    } else {
        MainScreen(onLogout = {
            val savedServerUrl = getServerUrl(ctx)
            prefs(ctx).edit().clear().putString(KEY_SERVER_URL, savedServerUrl).apply()
            setupDone = false
        })
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
    val scrollState = rememberScrollState()

    val submitLogin: () -> Unit = {
        val normalizedUsername = username.trim()
        if (normalizedUsername.isBlank() || password.isBlank()) {
            error = "Enter your username and password."
        } else if (schoolOptions.isNotEmpty() && selectedSchoolSlug.isBlank()) {
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
                        prefs(ctx).edit()
                            .putString(KEY_UID, user.userId.toString())
                            .putString(KEY_NAME, user.name)
                            .putString(KEY_ROLE, user.role)
                            .putString(KEY_LOGIN, user.loginName)
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
                .padding(horizontal = 24.dp, vertical = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            Surface(
                shape = RoundedCornerShape(28.dp),
                color = SurfaceMain,
                shadowElevation = 8.dp,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(22.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    BlueBirdLogo(modifier = Modifier.size(116.dp))
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        Text(
                            "BlueBird Alerts",
                            fontSize = 28.sp,
                            fontWeight = FontWeight.Bold,
                            color = TextPri,
                        )
                        Text(
                            "Clear, fast emergency communication for school response.",
                            fontSize = 14.sp,
                            color = TextMuted,
                            textAlign = TextAlign.Center,
                        )
                    }
                    Surface(
                        shape = RoundedCornerShape(18.dp),
                        color = SurfaceSoft,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(Modifier.padding(16.dp)) {
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
                        label = { Text("School", color = TextMuted) },
                        placeholder = { Text("Select your school", color = TextMuted) },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = schoolMenuExpanded) },
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = BluePrimary,
                            unfocusedBorderColor = BorderSoft,
                            focusedTextColor = TextPri,
                            unfocusedTextColor = TextPri,
                            cursorColor = BluePrimary,
                            focusedContainerColor = SurfaceMain,
                            unfocusedContainerColor = SurfaceMain,
                        ),
                        modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
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
                    label = { Text("School code or URL", color = TextMuted) },
                    placeholder = { Text("nn", color = TextMuted) },
                    singleLine = true,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = BluePrimary,
                        unfocusedBorderColor = BorderSoft,
                        focusedTextColor = TextPri,
                        unfocusedTextColor = TextPri,
                        cursorColor = BluePrimary,
                        focusedContainerColor = SurfaceMain,
                        unfocusedContainerColor = SurfaceMain,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            OutlinedTextField(
                value = username,
                onValueChange = {
                    username = it
                    error = null
                },
                label = { Text("Username", color = TextMuted) },
                placeholder = { Text("Enter your BlueBird username", color = TextMuted) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = BluePrimary,
                    unfocusedBorderColor = BorderSoft,
                    focusedTextColor = TextPri,
                    unfocusedTextColor = TextPri,
                    cursorColor = BluePrimary,
                    focusedContainerColor = SurfaceMain,
                    unfocusedContainerColor = SurfaceMain,
                ),
                modifier = Modifier.fillMaxWidth(),
            )

            OutlinedTextField(
                value = password,
                onValueChange = {
                    password = it
                    error = null
                },
                label = { Text("Password", color = TextMuted) },
                placeholder = { Text("Enter your password", color = TextMuted) },
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
                    unfocusedBorderColor = BorderSoft,
                    focusedTextColor = TextPri,
                    unfocusedTextColor = TextPri,
                    cursorColor = BluePrimary,
                    focusedContainerColor = SurfaceMain,
                    unfocusedContainerColor = SurfaceMain,
                ),
                modifier = Modifier.fillMaxWidth(),
            )

            error?.let {
                Text(
                    text = it,
                    color = Color(0xFFB91C1C),
                    fontSize = 13.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
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
                color = TextMuted,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )

            PrimaryButton(
                text = if (isSubmitting) "Signing In…" else "Sign In",
                onClick = submitLogin,
                enabled = !isSubmitting,
                isLoading = isSubmitting,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
            )
        }
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
private fun MainScreen(onLogout: () -> Unit, vm: MainViewModel = viewModel()) {
    val ctx = LocalContext.current
    val focusManager = LocalFocusManager.current
    val keyboardController = LocalSoftwareKeyboardController.current
    val state by vm.state.collectAsState()
    var showDeactivateDialog by remember { mutableStateOf(false) }
    var showReportDialog by remember { mutableStateOf(false) }
    var showSettingsScreen by remember { mutableStateOf(false) }
    var pendingSafetyAction by remember { mutableStateOf<SafetyAction?>(null) }
    var showQuietRequestOverlay by remember { mutableStateOf(false) }
    var showQuietDeleteConfirmOverlay by remember { mutableStateOf(false) }
    var showTeamAssistDialog by remember { mutableStateOf(false) }
    var promptRequestHelpId by remember { mutableStateOf<Int?>(null) }
    var dismissedPromptRequestHelpId by remember { mutableStateOf<Int?>(null) }
    var activePanel by remember { mutableStateOf(DashboardPanel.Home) }
    var replyTarget by remember { mutableStateOf<AdminInboxMessage?>(null) }
    var feedTab by remember { mutableStateOf(0) }
    val userName = remember { getUserName(ctx) }
    val userRole = remember { getUserRole(ctx) }
    val currentUserId = remember { getUserId(ctx).toIntOrNull() }
    val canDeactivate = remember { canDeactivateAlarm(ctx) }
    val isAdmin = remember(userRole) { userRole.equals("admin", ignoreCase = true) }
    var biometricsEnabled by remember { mutableStateOf(biometricsAllowed(ctx)) }
    val safetyActions = remember(state.featureLabels) { buildSafetyActions(state.featureLabels) }
    val requestHelpLabel = AppLabels.labelForFeatureKey(AppLabels.KEY_REQUEST_HELP, state.featureLabels)

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
        while (true) {
            vm.refreshAdminInbox(ctx)
            vm.refreshAdminQuietPeriodRequests(ctx)
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

    // Dismiss flash messages after 3s
    LaunchedEffect(state.successMsg, state.errorMsg) {
        if (state.successMsg != null || state.errorMsg != null) {
            delay(3_000)
            vm.clearMessages()
        }
    }

    AlarmSoundEffect(isAlarmActive = state.alarm.isActive)

    Scaffold(
        containerColor = Color.Transparent,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        if (showSettingsScreen) "Settings" else "BlueBird Alerts",
                        fontWeight = FontWeight.Bold,
                        color = TextPri,
                    )
                },
                actions = {
                    TextButton(
                        onClick = { showSettingsScreen = !showSettingsScreen },
                    ) {
                        Text(
                            if (showSettingsScreen) "Back" else "Settings",
                            color = BluePrimary,
                            fontWeight = FontWeight.SemiBold,
                        )
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
                    onLogout = onLogout,
                    biometricsEnabled = biometricsEnabled,
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
                )
            } else {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState()),
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
                                        if (userName.isNotBlank()) "$userName • ${userRole.replaceFirstChar { it.uppercase() }}" else "School Safety",
                                        fontSize = 12.sp,
                                        color = TextMuted,
                                    )
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

                    ActiveSafetyFeedCard(
                        selectedTab = feedTab,
                        onSelectTab = { feedTab = it },
                        incidents = state.activeIncidents,
                        teamAssists = state.activeTeamAssists,
                        featureLabels = state.featureLabels,
                        isAdmin = isAdmin,
                        currentUserId = currentUserId,
                        actionRecipients = state.teamAssistActionRecipients,
                        isBusy = state.isBusy,
                        isRefreshing = state.isRefreshingFeed,
                        onRefresh = { vm.refreshIncidentFeeds() },
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
                        onTeamAssistCancelConfirm = { teamAssistId ->
                            runProtectedAction(true) {
                                vm.confirmRequestHelpCancel(ctx = ctx, teamAssistId = teamAssistId)
                            }
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 20.dp, vertical = 8.dp),
                    )

                    // ── Alarm banner ─────────────────────────────────────────
                    AlarmBanner(
                        alarm = state.alarm,
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
                    SafetyActionGrid(
                        actions = safetyActions,
                        enabled = !state.isBusy && !state.alarm.isActive,
                        onSelect = { action -> pendingSafetyAction = action },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 20.dp, vertical = 8.dp),
                    )

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
                        if (isAdmin) {
                            AdminQuietPeriodRequestsCard(
                                requests = state.adminQuietPeriodRequests,
                                isBusy = state.isBusy,
                                onApprove = { requestId ->
                                    runProtectedAction(true) { vm.approveQuietPeriodRequest(ctx, requestId) }
                                },
                                onDeny = { requestId ->
                                    runProtectedAction(true) { vm.denyQuietPeriodRequest(ctx, requestId) }
                                },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 20.dp, vertical = 8.dp),
                            )
                        }
                    }

                    Spacer(Modifier.weight(1f))

                    // ── Action buttons ───────────────────────────────────────
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 20.dp, vertical = 24.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        // Deactivate (only when active)
                        if (state.alarm.isActive && canDeactivate) {
                            OutlinedButton(
                                onClick = { showDeactivateDialog = true },
                                modifier = Modifier.fillMaxWidth().height(52.dp),
                                shape = RoundedCornerShape(14.dp),
                                enabled = !state.isBusy,
                                colors = ButtonDefaults.outlinedButtonColors(contentColor = TextPri),
                            ) {
                                Text(
                                    if (state.isBusy) "Working…" else "Deactivate Alarm",
                                    fontWeight = FontWeight.SemiBold,
                                )
                            }
                        }

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
    }

    pendingSafetyAction?.let { action ->
        ActionInitiateOverlay(
            action = action,
            isBusy = state.isBusy,
            onCancel = { pendingSafetyAction = null },
            onInitiate = {
                pendingSafetyAction = null
                runProtectedAction(false) { vm.activateAlarm(ctx, action.message) }
            },
        )
    }
    if (showQuietRequestOverlay) {
        QuietPeriodRequestOverlay(
            isBusy = state.isBusy,
            onCancel = { showQuietRequestOverlay = false },
            onConfirm = { reason ->
                showQuietRequestOverlay = false
                vm.requestQuietPeriod(ctx, reason)
            },
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
                    Text("Take action now to clear this active request.", color = TextPri, fontSize = 14.sp)
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
                                    action = "responding",
                                )
                            }
                        },
                    ) {
                        Text("Responding", fontWeight = FontWeight.SemiBold)
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
}

// ── Composable components ──────────────────────────────────────────────────────

@Composable
private fun ConnectionDot(connected: Boolean?) {
    val color = when (connected) {
        true  -> AlarmGreen
        false -> AlarmRed
        null  -> Color(0xFF64748B)
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
    val bg = if (isError) Color(0xFFFFE8E8) else Color(0xFFEAF8EF)
    val fg = if (isError) Color(0xFFB91C1C) else Color(0xFF166534)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 4.dp)
            .background(bg, RoundedCornerShape(12.dp))
            .border(1.dp, if (isError) Color(0xFFF5B5B5) else Color(0xFFB7E4C7), RoundedCornerShape(12.dp))
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
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                Button(
                    onClick = { onSelectPanel(DashboardPanel.Home) },
                    modifier = Modifier.weight(1f).height(46.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (activePanel == DashboardPanel.Home) BlueDark else SurfaceSoft,
                        contentColor = if (activePanel == DashboardPanel.Home) Color.White else TextPri,
                    ),
                    shape = RoundedCornerShape(16.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Icon(
                            painter = painterResource(android.R.drawable.ic_menu_view),
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                        )
                        Text("Home", fontWeight = FontWeight.SemiBold)
                    }
                }

                Button(
                    onClick = { onSelectPanel(DashboardPanel.Messaging) },
                    modifier = Modifier.weight(1f).height(46.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (activePanel == DashboardPanel.Messaging) BluePrimary else SurfaceSoft,
                        contentColor = if (activePanel == DashboardPanel.Messaging) Color.White else TextPri,
                    ),
                    shape = RoundedCornerShape(16.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Icon(
                            painter = painterResource(android.R.drawable.ic_dialog_email),
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                        )
                        Text("Messaging", fontWeight = FontWeight.SemiBold)
                    }
                }

                Button(
                    onClick = { onSelectPanel(DashboardPanel.QuietPeriod) },
                    modifier = Modifier.weight(1f).height(46.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (activePanel == DashboardPanel.QuietPeriod) QuietPurple else QuietPurple.copy(alpha = 0.75f),
                        contentColor = Color.White,
                    ),
                    shape = RoundedCornerShape(16.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Icon(
                            painter = painterResource(android.R.drawable.ic_lock_idle_alarm),
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                        )
                        Text("Quiet Period", fontWeight = FontWeight.SemiBold)
                    }
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
    incidents: List<IncidentFeedItem>,
    teamAssists: List<TeamAssistFeedItem>,
    featureLabels: Map<String, String>,
    isAdmin: Boolean,
    currentUserId: Int?,
    actionRecipients: List<TeamAssistActionRecipient>,
    isBusy: Boolean,
    isRefreshing: Boolean,
    onRefresh: () -> Unit,
    onTeamAssistAction: (Int, String, Int?) -> Unit,
    onTeamAssistCancelConfirm: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        color = SurfaceMain,
        shape = RoundedCornerShape(20.dp),
        shadowElevation = 4.dp,
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Active Feed", color = TextPri, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                TextButton(onClick = onRefresh, enabled = !isRefreshing) {
                    Text(if (isRefreshing) "Refreshing…" else "Refresh", color = BluePrimary)
                }
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
                            title = incident.type.uppercase(),
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
                            onTeamAssistCancelConfirm = onTeamAssistCancelConfirm,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TeamAssistRow(
    teamAssist: TeamAssistFeedItem,
    featureLabels: Map<String, String>,
    isAdmin: Boolean,
    currentUserId: Int?,
    actionRecipients: List<TeamAssistActionRecipient>,
    isBusy: Boolean,
    onTeamAssistAction: (Int, String, Int?) -> Unit,
    onTeamAssistCancelConfirm: (Int) -> Unit,
) {
    var showForwardDialog by remember(teamAssist.id) { mutableStateOf(false) }
    var forwardQuery by remember(teamAssist.id) { mutableStateOf("") }
    val filteredRecipients = remember(actionRecipients, forwardQuery) {
        actionRecipients.filter {
            it.label.contains(forwardQuery, ignoreCase = true)
        }
    }
    val subtitleParts = buildList {
        add("${formatIsoForBanner(teamAssist.createdAt) ?: teamAssist.createdAt} • by #${teamAssist.createdBy}")
        val actorLabel = teamAssist.actedByLabel?.takeIf { it.isNotBlank() }
        if (actorLabel != null) {
            add("${teamAssist.status.replaceFirstChar { it.uppercase() }} by $actorLabel")
        } else {
            add(teamAssist.status.replaceFirstChar { it.uppercase() })
        }
        teamAssist.forwardToLabel?.takeIf { it.isNotBlank() }?.let { add("to $it") }
        if (teamAssist.status.equals("cancel_pending", ignoreCase = true)) {
            val requesterState = if (teamAssist.cancelRequesterConfirmed) "Requester ✓" else "Requester …"
            val adminState = if (teamAssist.cancelAdminConfirmed) "Admin ✓" else "Admin …"
            add("$requesterState, $adminState")
        }
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        FeedRow(
            title = AppLabels.featureDisplayName(teamAssist.type, featureLabels),
            subtitle = subtitleParts.joinToString(" • "),
            tone = Color(0xFF0F766E),
        )
        val canRequesterConfirm = currentUserId != null && currentUserId == teamAssist.createdBy && !teamAssist.cancelRequesterConfirmed
        if (isAdmin || canRequesterConfirm) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (isAdmin) {
                    AssistActionChip(label = "Acknowledge", enabled = !isBusy) {
                        onTeamAssistAction(teamAssist.id, "acknowledge", null)
                    }
                    AssistActionChip(label = "Responding", enabled = !isBusy) {
                        onTeamAssistAction(teamAssist.id, "responding", null)
                    }
                    AssistActionChip(label = "Forward", enabled = !isBusy && actionRecipients.isNotEmpty()) {
                        showForwardDialog = true
                    }
                    AssistActionChip(label = if (teamAssist.cancelAdminConfirmed) "Admin Confirmed" else "Confirm Cancel", enabled = !isBusy && !teamAssist.cancelAdminConfirmed) {
                        onTeamAssistCancelConfirm(teamAssist.id)
                    }
                } else if (canRequesterConfirm) {
                    AssistActionChip(label = "Confirm Cancel", enabled = !isBusy) {
                        onTeamAssistCancelConfirm(teamAssist.id)
                    }
                }
            }
        }
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
    val bg: Color
    val border: Color
    val fg: Color
    val text: String
    when (normalized) {
        "approved" -> {
            val until = formatIsoForBanner(status.expiresAt)?.let { " until $it" } ?: ""
            bg = Color(0xFFFEE2E2)
            border = Color(0xFFFCA5A5)
            fg = Color(0xFF991B1B)
            text = "Quiet period ACTIVE$until"
        }
        "pending" -> {
            bg = Color(0xFFEFF6FF)
            border = Color(0xFF93C5FD)
            fg = Color(0xFF1D4ED8)
            text = "Quiet period request pending admin approval"
        }
        "denied" -> {
            bg = Color(0xFFFFF7ED)
            border = Color(0xFFFDBA74)
            fg = Color(0xFF9A3412)
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
            if (normalized == "pending" || normalized == "approved") {
                Button(
                    onClick = {
                        if (normalized == "approved") onDeleteApproved() else onDeletePending()
                    },
                    enabled = !isBusy,
                    shape = RoundedCornerShape(10.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color(0xFFB91C1C),
                        contentColor = Color.White,
                        disabledContainerColor = Color(0xFF94A3B8),
                        disabledContentColor = Color.White,
                    ),
                ) {
                    Text(
                        if (isBusy) "Deleting..." else if (normalized == "approved") "End Quiet Period" else "Delete Request",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
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
                        color = Color(0xFFF8FAFF),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(
                                text = (item.userName ?: "User #${item.userId}") + " • ${(item.userRole ?: "user").replaceFirstChar { it.uppercase() }}",
                                color = TextPri,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 14.sp,
                            )
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
                                        containerColor = Color(0xFF166534),
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
                                        containerColor = Color(0xFFB91C1C),
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
private fun QuietPeriodDeleteConfirmOverlay(
    isBusy: Boolean,
    onCancel: () -> Unit,
    onConfirm: () -> Unit,
) {
    var slideValue by remember { mutableStateOf(0f) }
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xCC0B1220))
            .navigationBarsPadding()
            .statusBarsPadding(),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 24.dp, vertical = 20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("BlueBird Alerts", color = Color(0xFFD4DCEE), fontSize = 16.sp, fontWeight = FontWeight.Bold)
            Spacer(modifier = Modifier.height(24.dp))
            Surface(
                shape = CircleShape,
                color = Color(0xFFDC2626),
                modifier = Modifier.size(86.dp),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text("!", fontSize = 34.sp, color = Color.White, fontWeight = FontWeight.ExtraBold)
                }
            }
            Spacer(modifier = Modifier.height(14.dp))
            Text(
                "END QUIET PERIOD EARLY",
                color = Color.White,
                fontWeight = FontWeight.ExtraBold,
                fontSize = 24.sp,
                textAlign = TextAlign.Center,
            )
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                "Do you really want to end this approved quiet period early?",
                color = Color(0xFFE2E8F0),
                fontWeight = FontWeight.Medium,
                fontSize = 15.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(modifier = Modifier.height(24.dp))
            Surface(
                shape = RoundedCornerShape(28.dp),
                color = Color(0xFF5B616B),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                    Text(
                        if (isBusy) "Ending…" else "Slide to Confirm →",
                        color = Color.White,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 16.sp,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Slider(
                        value = slideValue,
                        onValueChange = { slideValue = it },
                        onValueChangeFinished = {
                            if (!isBusy && slideValue >= 0.95f) {
                                onConfirm()
                            }
                            slideValue = 0f
                        },
                        enabled = !isBusy,
                        colors = SliderDefaults.colors(
                            thumbColor = Color.White,
                            activeTrackColor = Color(0xFFFCA5A5),
                            inactiveTrackColor = Color(0xFF6D747F),
                        ),
                        valueRange = 0f..1f,
                    )
                }
            }
            Spacer(modifier = Modifier.weight(1f))
            Surface(
                shape = CircleShape,
                color = Color(0xCC9CA3AF),
                modifier = Modifier.size(68.dp),
            ) {
                Button(
                    onClick = onCancel,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color.Transparent,
                        contentColor = Color.White,
                    ),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    Text("✕", fontSize = 26.sp, fontWeight = FontWeight.Bold)
                }
            }
            Text(
                "Cancel",
                color = Color.White,
                fontSize = 14.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
    }
}

@Composable
private fun AlarmBanner(alarm: AlarmStatus, modifier: Modifier = Modifier) {
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

    val bg = if (alarm.isActive) AlarmRed else SurfaceMain

    Surface(
        modifier = modifier.alpha(if (alarm.isActive) pulseAlpha else 1f),
        shape = RoundedCornerShape(24.dp),
        color = bg,
        tonalElevation = 4.dp,
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
                        if (alarm.isActive) "ALARM ACTIVE" else "All Clear",
                        fontWeight = FontWeight.ExtraBold,
                        fontSize = 26.sp,
                        color = if (alarm.isActive) TextOnDark else TextPri,
                    )
                    Text(
                        if (alarm.isActive) "Emergency alert in progress" else "No active school alarm",
                        fontSize = 14.sp,
                        color = if (alarm.isActive) Color(0xFFFFCDD2) else TextMuted,
                    )
                }
            }

            if (alarm.isActive) {
                HorizontalDivider(color = Color(0x33FFFFFF), thickness = 1.dp)
                alarm.message?.let {
                    Text(it, fontSize = 16.sp, color = TextOnDark, fontWeight = FontWeight.Medium)
                }
                alarm.activatedAt?.let {
                    Text("Activated: $it", fontSize = 12.sp, color = Color(0xFFFFCDD2))
                }
                alarm.activatedByUserId?.let {
                    Text("Triggered by user #$it", fontSize = 12.sp, color = Color(0xFFFFCDD2))
                }
            }
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
    onSelect: (SafetyAction) -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(20.dp),
        color = SurfaceMain,
        tonalElevation = 2.dp,
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 18.dp, vertical = 20.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            for (row in actions.chunked(2)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    row.forEach { action ->
                        SafetyActionButton(
                            action = action,
                            enabled = enabled,
                            onClick = { onSelect(action) },
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
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        colors = ButtonDefaults.buttonColors(
            containerColor = Color.Transparent,
            disabledContainerColor = Color.Transparent,
            contentColor = TextPri,
            disabledContentColor = TextMuted,
        ),
        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Surface(
                shape = CircleShape,
                color = action.color,
                modifier = Modifier.size(126.dp),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        painter = painterResource(action.iconRes),
                        contentDescription = action.title,
                        tint = Color.White,
                        modifier = Modifier.size(44.dp),
                    )
                }
            }
            Text(
                action.title,
                fontWeight = FontWeight.ExtraBold,
                color = TextPri,
                fontSize = 18.sp,
                textAlign = TextAlign.Center,
                lineHeight = 20.sp,
            )
        }
    }
}

@Composable
private fun ActionInitiateOverlay(
    action: SafetyAction,
    isBusy: Boolean,
    onCancel: () -> Unit,
    onInitiate: () -> Unit,
) {
    var slideValue by remember(action.key) { mutableStateOf(0f) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xCC0B1220))
            .navigationBarsPadding()
            .statusBarsPadding(),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 24.dp, vertical = 20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("BlueBird Alerts", color = Color(0xFFD4DCEE), fontSize = 16.sp, fontWeight = FontWeight.Bold)
            Spacer(modifier = Modifier.height(22.dp))
            Surface(
                shape = CircleShape,
                color = action.color,
                modifier = Modifier.size(86.dp),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        painter = painterResource(action.iconRes),
                        contentDescription = action.title,
                        tint = Color.White,
                        modifier = Modifier.size(38.dp),
                    )
                }
            }
            Spacer(modifier = Modifier.height(14.dp))
            Text(
                "${action.title} EMERGENCY",
                color = Color.White,
                fontWeight = FontWeight.ExtraBold,
                fontSize = 26.sp,
                textAlign = TextAlign.Center,
            )
            Spacer(modifier = Modifier.height(34.dp))
            Surface(
                shape = RoundedCornerShape(28.dp),
                color = Color(0xFF5B616B),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                    Text(
                        if (isBusy) "Initiating…" else "Slide to Initiate →",
                        color = Color.White,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 16.sp,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Slider(
                        value = slideValue,
                        onValueChange = { slideValue = it },
                        onValueChangeFinished = {
                            if (!isBusy && slideValue >= 0.95f) {
                                onInitiate()
                            }
                            slideValue = 0f
                        },
                        enabled = !isBusy,
                        colors = SliderDefaults.colors(
                            thumbColor = Color.White,
                            activeTrackColor = Color(0xFF9AA0AA),
                            inactiveTrackColor = Color(0xFF6D747F),
                        ),
                        valueRange = 0f..1f,
                    )
                }
            }
            Spacer(modifier = Modifier.weight(1f))
            Surface(
                shape = CircleShape,
                color = Color(0xCC9CA3AF),
                modifier = Modifier.size(68.dp),
            ) {
                Button(
                    onClick = onCancel,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color.Transparent,
                        contentColor = Color.White,
                    ),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    Text("✕", fontSize = 26.sp, fontWeight = FontWeight.Bold)
                }
            }
            Text(
                "Cancel",
                color = Color.White,
                fontSize = 14.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
    }
}

@Composable
private fun QuietPeriodRequestOverlay(
    isBusy: Boolean,
    onCancel: () -> Unit,
    onConfirm: (String?) -> Unit,
) {
    var slideValue by remember { mutableStateOf(0f) }
    var reason by remember { mutableStateOf("") }
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xCC0B1220))
            .navigationBarsPadding()
            .statusBarsPadding(),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 24.dp, vertical = 20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("BlueBird Alerts", color = Color(0xFFD4DCEE), fontSize = 16.sp, fontWeight = FontWeight.Bold)
            Spacer(modifier = Modifier.height(24.dp))
            Surface(
                shape = CircleShape,
                color = Color(0xFF7C3AED),
                modifier = Modifier.size(86.dp),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text("\uD83D\uDD15", fontSize = 34.sp)
                }
            }
            Spacer(modifier = Modifier.height(14.dp))
            Text(
                "REQUEST QUIET PERIOD",
                color = Color.White,
                fontWeight = FontWeight.ExtraBold,
                fontSize = 24.sp,
                textAlign = TextAlign.Center,
            )
            Spacer(modifier = Modifier.height(24.dp))
            Surface(
                shape = RoundedCornerShape(28.dp),
                color = Color(0xFF5B616B),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                    Text(
                        if (isBusy) "Submitting…" else "Slide to Confirm →",
                        color = Color.White,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 16.sp,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Slider(
                        value = slideValue,
                        onValueChange = { slideValue = it },
                        onValueChangeFinished = {
                            if (!isBusy && slideValue >= 0.95f) {
                                onConfirm(reason.trim().ifBlank { null })
                            }
                            slideValue = 0f
                        },
                        enabled = !isBusy,
                        colors = SliderDefaults.colors(
                            thumbColor = Color.White,
                            activeTrackColor = Color(0xFF9AA0AA),
                            inactiveTrackColor = Color(0xFF6D747F),
                        ),
                        valueRange = 0f..1f,
                    )
                }
            }
            Spacer(modifier = Modifier.height(16.dp))
            OutlinedTextField(
                value = reason,
                onValueChange = { reason = it },
                label = { Text("Reason (optional)", color = Color(0xFFCBD5E1)) },
                placeholder = { Text("Wedding, funeral, testing context...", color = Color(0xFF94A3B8)) },
                minLines = 2,
                maxLines = 4,
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Color(0xFF7C3AED),
                    unfocusedBorderColor = Color(0xFF64748B),
                    focusedTextColor = Color.White,
                    unfocusedTextColor = Color.White,
                    cursorColor = Color(0xFF7C3AED),
                    focusedContainerColor = Color(0x33243355),
                    unfocusedContainerColor = Color(0x22243355),
                    focusedLabelColor = Color(0xFFE2E8F0),
                    unfocusedLabelColor = Color(0xFFCBD5E1),
                ),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(modifier = Modifier.weight(1f))
            Surface(
                shape = CircleShape,
                color = Color(0xCC9CA3AF),
                modifier = Modifier.size(68.dp),
            ) {
                Button(
                    onClick = onCancel,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color.Transparent,
                        contentColor = Color.White,
                    ),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    Text("✕", fontSize = 26.sp, fontWeight = FontWeight.Bold)
                }
            }
            Text(
                "Cancel",
                color = Color.White,
                fontSize = 14.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
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
    onBiometricsChanged: (Boolean) -> Unit,
) {
    val ctx = LocalContext.current
    val userName = remember { getUserName(ctx) }
    val loginName = remember { getLoginName(ctx) }
    val userRole = remember { getUserRole(ctx) }
    val userId = remember { getUserId(ctx) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Surface(
            color = SurfaceMain,
            shape = RoundedCornerShape(20.dp),
            shadowElevation = 4.dp,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("Signed in as", color = TextMuted, fontSize = 12.sp)
                Text(userName.ifBlank { "BlueBird user" }, color = TextPri, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                Text("@${loginName.ifBlank { "unknown" }}", color = BlueLight, fontSize = 13.sp)
                HorizontalDivider(color = BorderSoft)
                Text("Role: ${userRole.replaceFirstChar { it.uppercase() }}", color = TextPri, fontSize = 14.sp)
                Text("User ID: $userId", color = TextPri, fontSize = 14.sp)
                Text("Server: ${BuildConfig.BACKEND_BASE_URL}", color = TextMuted, fontSize = 12.sp)
            }
        }
        Surface(
            color = SurfaceMain,
            shape = RoundedCornerShape(20.dp),
            shadowElevation = 4.dp,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 18.dp, vertical = 14.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Biometrics Allowed", color = TextPri, fontWeight = FontWeight.Bold)
                    Text(
                        "Require Face ID / fingerprint for emergency and admin actions.",
                        color = TextMuted,
                        fontSize = 12.sp,
                    )
                }
                Switch(
                    checked = biometricsEnabled,
                    onCheckedChange = onBiometricsChanged,
                )
            }
        }
        Button(
            onClick = onLogout,
            colors = ButtonDefaults.buttonColors(containerColor = AlarmRed),
            modifier = Modifier.fillMaxWidth().height(50.dp),
            shape = RoundedCornerShape(14.dp),
        ) { Text("Log Out") }
    }
}

// ── Alarm sound ────────────────────────────────────────────────────────────────
@Composable
private fun AlarmSoundEffect(isAlarmActive: Boolean) {
    val ctx = LocalContext.current
    val player = remember { AlarmPlayer(ctx.applicationContext) }

    DisposableEffect(isAlarmActive) {
        if (isAlarmActive) player.start() else player.stop()
        onDispose {}
    }
    DisposableEffect(Unit) {
        onDispose { player.release() }
    }
}

private class AlarmPlayer(private val ctx: Context) {
    private var player: MediaPlayer? = null

    fun start() {
        if (player?.isPlaying == true) return
        val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
            ?: return
        player = MediaPlayer().apply {
            setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            )
            setDataSource(ctx, uri)
            isLooping = true
            prepare()
            start()
        }
    }

    fun stop() {
        player?.run { if (isPlaying) stop(); reset(); release() }
        player = null
    }

    fun release() = stop()
}

// ── Backend client ─────────────────────────────────────────────────────────────
private class BackendClient(baseUrl: String, private val apiKey: String) {
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

    fun registerAndroidDevice(token: String, userId: Int?) {
        val body = JSONObject()
            .put("device_token", token.trim())
            .put("platform", "android")
            .put("push_provider", "fcm")
            .put("device_name", currentDeviceName())
            .apply { userId?.let { put("user_id", it) } }
        val req = Request.Builder()
            .url("$base/register-device")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
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
                                message = item.optString("message"),
                            )
                        )
                    }
                }
            }
            return AlarmStatus(
                isActive          = j.optBoolean("is_active"),
                message           = j.optString("message").ifBlank { null },
                activatedAt       = j.optString("activated_at").ifBlank { null },
                activatedByUserId = if (j.has("activated_by_user_id") && !j.isNull("activated_by_user_id"))
                    j.optInt("activated_by_user_id") else null,
                broadcasts       = broadcasts,
            )
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
                        if (!isActive || role == "admin" || userId <= 0) continue
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

    fun requestQuietPeriod(userId: Int, reason: String?) {
        val body = JSONObject()
            .put("user_id", userId)
            .apply { reason?.let { put("reason", it) } }
        val req = Request.Builder()
            .url("$base/quiet-periods/request")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { requireSuccess(it) }
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
                cancelRequesterConfirmed = item.optBoolean("cancel_requester_confirmed", false),
                cancelAdminConfirmed = item.optBoolean("cancel_admin_confirmed", false),
                cancelAdminLabel = item.optNullableString("cancel_admin_label"),
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
                cancelRequesterConfirmed = item.optBoolean("cancel_requester_confirmed", false),
                cancelAdminConfirmed = item.optBoolean("cancel_admin_confirmed", false),
                cancelAdminLabel = item.optNullableString("cancel_admin_label"),
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

    fun confirmRequestHelpCancel(teamAssistId: Int, actorUserId: Int): TeamAssistFeedItem {
        val body = JSONObject().put("user_id", actorUserId)
        val req = Request.Builder()
            .url("$base/team-assist/$teamAssistId/cancel-confirm")
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
                cancelRequesterConfirmed = item.optBoolean("cancel_requester_confirmed", false),
                cancelAdminConfirmed = item.optBoolean("cancel_admin_confirmed", false),
                cancelAdminLabel = item.optNullableString("cancel_admin_label"),
            )
        }
    }

    fun confirmTeamAssistCancel(teamAssistId: Int, actorUserId: Int): TeamAssistFeedItem {
        return confirmRequestHelpCancel(teamAssistId = teamAssistId, actorUserId = actorUserId)
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
                                cancelRequesterConfirmed = item.optBoolean("cancel_requester_confirmed", false),
                                cancelAdminConfirmed = item.optBoolean("cancel_admin_confirmed", false),
                                cancelAdminLabel = item.optNullableString("cancel_admin_label"),
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

    fun activateAlarm(message: String, userId: Int?): AlarmStatus {
        val body = JSONObject().put("message", message).apply { userId?.let { put("user_id", it) } }
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
            isActive          = j.optBoolean("is_active"),
            message           = j.optString("message").ifBlank { null },
            activatedAt       = j.optString("activated_at").ifBlank { null },
            activatedByUserId = if (j.has("activated_by_user_id") && !j.isNull("activated_by_user_id"))
                j.optInt("activated_by_user_id") else null,
            broadcasts        = broadcasts,
        )
    }

    private fun requireSuccess(res: okhttp3.Response): String {
        val body = res.body?.string().orEmpty()
        if (!res.isSuccessful) {
            val detail = runCatching { JSONObject(body).optString("detail") }.getOrDefault(body)
            error(detail.ifBlank { "Request failed (${res.code})" })
        }
        return body
    }
}

private data class MessageInboxResponse(
    val unreadCount: Int,
    val messages: List<AdminInboxMessage>,
)
