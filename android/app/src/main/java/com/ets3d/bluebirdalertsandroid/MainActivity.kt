package com.ets3d.bluebirdalertsandroid

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
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
import org.json.JSONObject
import java.util.concurrent.TimeUnit

// ── Brand colours ─────────────────────────────────────────────────────────────
private val Navy        = Color(0xFF0B1A33)
private val NavySurface = Color(0xFF122040)
private val BluePrimary = Color(0xFF2563EB)
private val BlueLight   = Color(0xFF3B82F6)
private val AlarmRed    = Color(0xFFDC2626)
private val AlarmGreen  = Color(0xFF16A34A)
private val TextPri     = Color(0xFFFFFFFF)
private val TextMuted   = Color(0xFF94A3B8)

// ── Prefs ──────────────────────────────────────────────────────────────────────
private const val PREFS      = "bluebird_prefs"
private const val KEY_API    = "api_key"
private const val KEY_UID    = "user_id"
private const val KEY_SETUP  = "setup_done"
private const val NOTIF_CH   = "bluebird_alerts"

private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
private fun isSetupDone(ctx: Context) = prefs(ctx).getBoolean(KEY_SETUP, false)
private fun getApiKey(ctx: Context)   = prefs(ctx).getString(KEY_API, "") ?: ""
private fun getUserId(ctx: Context)   = prefs(ctx).getString(KEY_UID, "") ?: ""

// ── Data ───────────────────────────────────────────────────────────────────────
data class AlarmStatus(
    val isActive: Boolean = false,
    val message: String?  = null,
    val activatedAt: String? = null,
    val activatedByUserId: Int? = null,
)

data class UiState(
    val alarm: AlarmStatus      = AlarmStatus(),
    val connected: Boolean?     = null,   // null = unknown, true/false = result
    val isBusy: Boolean         = false,
    val successMsg: String?     = null,
    val errorMsg: String?       = null,
)

// ── ViewModel ──────────────────────────────────────────────────────────────────
class MainViewModel : ViewModel() {
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state

    private var client: BackendClient? = null

    fun init(ctx: Context) {
        if (client != null) return
        client = BackendClient(
            baseUrl = BuildConfig.BACKEND_BASE_URL,
            apiKey  = getApiKey(ctx),
        )
        startPolling()
    }

    private fun startPolling() {
        viewModelScope.launch(Dispatchers.IO) {
            while (isActive) {
                runCatching { client!!.alarmStatus() }
                    .onSuccess { alarm ->
                        _state.update { it.copy(alarm = alarm, connected = true) }
                    }
                    .onFailure {
                        _state.update { it.copy(connected = false) }
                    }
                delay(4_000)
            }
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

    fun clearMessages() = _state.update { it.copy(successMsg = null, errorMsg = null) }
}

// ── Activity ───────────────────────────────────────────────────────────────────
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        createNotificationChannel()
        setContent {
            BlueBirdTheme {
                App()
            }
        }
    }

    private fun createNotificationChannel() {
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
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .createNotificationChannel(channel)
    }
}

// ── Theme ──────────────────────────────────────────────────────────────────────
@Composable
private fun BlueBirdTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary   = BluePrimary,
            background = Navy,
            surface   = NavySurface,
            onPrimary  = TextPri,
            onBackground = TextPri,
            onSurface  = TextPri,
            error      = AlarmRed,
        ),
        content = content,
    )
}

// ── Root ───────────────────────────────────────────────────────────────────────
@Composable
private fun App() {
    val ctx = LocalContext.current
    var setupDone by remember { mutableStateOf(isSetupDone(ctx)) }

    if (!setupDone) {
        SetupScreen(onDone = { setupDone = true })
    } else {
        MainScreen()
    }
}

// ── Setup screen ───────────────────────────────────────────────────────────────
@Composable
private fun SetupScreen(onDone: () -> Unit) {
    val ctx = LocalContext.current
    var apiKey by remember { mutableStateOf("") }
    var userId by remember { mutableStateOf("") }
    var showKey by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(listOf(Navy, Color(0xFF0D2347)))
            ),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            Text(
                "🐦",
                fontSize = 64.sp,
            )
            Text(
                "BlueBird Alerts",
                fontSize = 28.sp,
                fontWeight = FontWeight.Bold,
                color = TextPri,
            )
            Text(
                "School emergency alert system",
                fontSize = 14.sp,
                color = TextMuted,
                textAlign = TextAlign.Center,
            )

            Spacer(Modifier.height(8.dp))

            // Server URL (read-only)
            Surface(
                shape = RoundedCornerShape(14.dp),
                color = NavySurface,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text("Server", fontSize = 12.sp, color = TextMuted)
                    Text(
                        BuildConfig.BACKEND_BASE_URL,
                        fontSize = 14.sp,
                        color = BlueLight,
                        fontWeight = FontWeight.Medium,
                    )
                }
            }

            // API key
            OutlinedTextField(
                value = apiKey,
                onValueChange = { apiKey = it },
                label = { Text("API Key", color = TextMuted) },
                placeholder = { Text("Leave blank if not required", color = TextMuted) },
                singleLine = true,
                visualTransformation = if (showKey) VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                trailingIcon = {
                    TextButton(onClick = { showKey = !showKey }) {
                        Text(if (showKey) "Hide" else "Show", color = BlueLight, fontSize = 12.sp)
                    }
                },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = BluePrimary,
                    unfocusedBorderColor = Color(0xFF2A3F5F),
                    focusedTextColor = TextPri,
                    unfocusedTextColor = TextPri,
                    cursorColor = BluePrimary,
                ),
                modifier = Modifier.fillMaxWidth(),
            )

            // User ID
            OutlinedTextField(
                value = userId,
                onValueChange = { userId = it.filter(Char::isDigit) },
                label = { Text("Your User ID", color = TextMuted) },
                placeholder = { Text("Optional — needed to deactivate alarms", color = TextMuted) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = BluePrimary,
                    unfocusedBorderColor = Color(0xFF2A3F5F),
                    focusedTextColor = TextPri,
                    unfocusedTextColor = TextPri,
                    cursorColor = BluePrimary,
                ),
                modifier = Modifier.fillMaxWidth(),
            )

            Button(
                onClick = {
                    prefs(ctx).edit()
                        .putString(KEY_API, apiKey.trim())
                        .putString(KEY_UID, userId.trim())
                        .putBoolean(KEY_SETUP, true)
                        .apply()
                    onDone()
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = BluePrimary),
            ) {
                Text("Get Started", fontSize = 16.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}

// ── Main screen ────────────────────────────────────────────────────────────────
@Composable
private fun MainScreen(vm: MainViewModel = viewModel()) {
    val ctx = LocalContext.current
    val state by vm.state.collectAsState()
    var showActivateDialog by remember { mutableStateOf(false) }
    var showDeactivateDialog by remember { mutableStateOf(false) }
    var showSettingsDialog by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.init(ctx) }

    // Dismiss flash messages after 3s
    LaunchedEffect(state.successMsg, state.errorMsg) {
        if (state.successMsg != null || state.errorMsg != null) {
            delay(3_000)
            vm.clearMessages()
        }
    }

    AlarmSoundEffect(isAlarmActive = state.alarm.isActive)

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Navy),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState()),
        ) {
            // ── Top bar ──────────────────────────────────────────────
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column {
                    Text("BlueBird Alerts", fontWeight = FontWeight.Bold, fontSize = 20.sp, color = TextPri)
                    Text("School Safety", fontSize = 12.sp, color = TextMuted)
                }
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ConnectionDot(state.connected)
                    TextButton(onClick = { showSettingsDialog = true }) {
                        Text("⚙", fontSize = 20.sp, color = TextMuted)
                    }
                }
            }

            // ── Flash messages ───────────────────────────────────────
            state.successMsg?.let {
                FlashBanner(it, isError = false)
            }
            state.errorMsg?.let {
                FlashBanner(it, isError = true)
            }

            // ── Alarm banner ─────────────────────────────────────────
            AlarmBanner(
                alarm = state.alarm,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 8.dp),
            )

            Spacer(Modifier.weight(1f))

            // ── Action buttons ───────────────────────────────────────
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                // Deactivate (only when active)
                if (state.alarm.isActive) {
                    OutlinedButton(
                        onClick = { showDeactivateDialog = true },
                        modifier = Modifier.fillMaxWidth().height(52.dp),
                        shape = RoundedCornerShape(14.dp),
                        enabled = !state.isBusy,
                        colors = OutlinedButtonDefaults.outlinedButtonColors(contentColor = TextPri),
                        border = ButtonDefaults.outlinedButtonBorder.copy(),
                    ) {
                        Text(
                            if (state.isBusy) "Working…" else "Deactivate Alarm",
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                }

                // Activate
                Button(
                    onClick = { showActivateDialog = true },
                    modifier = Modifier.fillMaxWidth().height(72.dp),
                    shape = RoundedCornerShape(18.dp),
                    enabled = !state.isBusy,
                    colors = ButtonDefaults.buttonColors(containerColor = AlarmRed),
                ) {
                    Text(
                        if (state.isBusy) "Sending…" else "ACTIVATE ALARM",
                        fontSize = 22.sp,
                        fontWeight = FontWeight.ExtraBold,
                        letterSpacing = 1.sp,
                    )
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

    // ── Dialogs ───────────────────────────────────────────────────────────────
    if (showActivateDialog) {
        ActivateDialog(
            isBusy = state.isBusy,
            onConfirm = { msg ->
                showActivateDialog = false
                vm.activateAlarm(ctx, msg)
            },
            onDismiss = { showActivateDialog = false },
        )
    }

    if (showDeactivateDialog) {
        ConfirmDialog(
            title = "Deactivate alarm?",
            body = "This will clear the active alarm for the whole school. Only admins can do this.",
            confirmLabel = "Deactivate",
            onConfirm = {
                showDeactivateDialog = false
                vm.deactivateAlarm(ctx)
            },
            onDismiss = { showDeactivateDialog = false },
        )
    }

    if (showSettingsDialog) {
        SettingsDialog(onDismiss = { showSettingsDialog = false })
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
    val bg = if (isError) Color(0xFF450A0A) else Color(0xFF052E16)
    val fg = if (isError) Color(0xFFFCA5A5) else Color(0xFF86EFAC)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 4.dp)
            .background(bg, RoundedCornerShape(12.dp))
            .padding(14.dp),
    ) {
        Text(message, color = fg, fontSize = 14.sp)
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

    val bg = if (alarm.isActive) AlarmRed else NavySurface
    val borderColor = if (alarm.isActive) Color(0xFFEF4444) else AlarmGreen

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
                        color = TextPri,
                    )
                    Text(
                        if (alarm.isActive) "Emergency alert in progress" else "No active school alarm",
                        fontSize = 14.sp,
                        color = if (alarm.isActive) Color(0xFFFFCDD2) else TextMuted,
                    )
                }
            }

            if (alarm.isActive) {
                Divider(color = Color(0x33FFFFFF), thickness = 1.dp)
                alarm.message?.let {
                    Text(it, fontSize = 16.sp, color = TextPri, fontWeight = FontWeight.Medium)
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
private fun ActivateDialog(isBusy: Boolean, onConfirm: (String) -> Unit, onDismiss: () -> Unit) {
    var message by remember { mutableStateOf("Emergency alert. Please follow school procedures.") }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = NavySurface,
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
                        unfocusedBorderColor = Color(0xFF2A3F5F),
                        focusedTextColor = TextPri,
                        unfocusedTextColor = TextPri,
                        cursorColor = AlarmRed,
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
private fun ConfirmDialog(title: String, body: String, confirmLabel: String, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = NavySurface,
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
private fun SettingsDialog(onDismiss: () -> Unit) {
    val ctx = LocalContext.current
    var apiKey by remember { mutableStateOf(getApiKey(ctx)) }
    var userId by remember { mutableStateOf(getUserId(ctx)) }
    var saved by remember { mutableStateOf(false) }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = NavySurface,
        title = { Text("Settings", color = TextPri, fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(
                    value = apiKey,
                    onValueChange = { apiKey = it },
                    label = { Text("API Key", color = TextMuted) },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = BluePrimary,
                        unfocusedBorderColor = Color(0xFF2A3F5F),
                        focusedTextColor = TextPri,
                        unfocusedTextColor = TextPri,
                        cursorColor = BluePrimary,
                    ),
                )
                OutlinedTextField(
                    value = userId,
                    onValueChange = { userId = it.filter(Char::isDigit) },
                    label = { Text("Your User ID", color = TextMuted) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = BluePrimary,
                        unfocusedBorderColor = Color(0xFF2A3F5F),
                        focusedTextColor = TextPri,
                        unfocusedTextColor = TextPri,
                        cursorColor = BluePrimary,
                    ),
                )
                if (saved) Text("Saved.", color = AlarmGreen, fontSize = 13.sp)
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    prefs(ctx).edit()
                        .putString(KEY_API, apiKey.trim())
                        .putString(KEY_UID, userId.trim())
                        .apply()
                    saved = true
                },
                colors = ButtonDefaults.buttonColors(containerColor = BluePrimary),
            ) { Text("Save") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Close", color = TextMuted) }
        },
    )
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

    fun alarmStatus(): AlarmStatus {
        val req = Request.Builder().url("$base/alarm/status").withAuth().get().build()
        http.newCall(req).execute().use { res ->
            val body = requireSuccess(res)
            val j = JSONObject(body)
            return AlarmStatus(
                isActive          = j.optBoolean("is_active"),
                message           = j.optString("message").ifBlank { null },
                activatedAt       = j.optString("activated_at").ifBlank { null },
                activatedByUserId = if (j.has("activated_by_user_id") && !j.isNull("activated_by_user_id"))
                    j.optInt("activated_by_user_id") else null,
            )
        }
    }

    fun activateAlarm(message: String, userId: Int?): AlarmStatus {
        val body = JSONObject().put("message", message).apply { userId?.let { put("user_id", it) } }
        val req = Request.Builder()
            .url("$base/alarm/activate")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { parseAlarm(it) }
    }

    fun deactivateAlarm(userId: Int?): AlarmStatus {
        val body = JSONObject().apply { userId?.let { put("user_id", it) } }
        val req = Request.Builder()
            .url("$base/alarm/deactivate")
            .withAuth()
            .post(body.toString().toRequestBody(json))
            .build()
        http.newCall(req).execute().use { parseAlarm(it) }
    }

    private fun parseAlarm(res: okhttp3.Response): AlarmStatus {
        val body = requireSuccess(res)
        val j = JSONObject(body)
        return AlarmStatus(
            isActive          = j.optBoolean("is_active"),
            message           = j.optString("message").ifBlank { null },
            activatedAt       = j.optString("activated_at").ifBlank { null },
            activatedByUserId = if (j.has("activated_by_user_id") && !j.isNull("activated_by_user_id"))
                j.optInt("activated_by_user_id") else null,
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
