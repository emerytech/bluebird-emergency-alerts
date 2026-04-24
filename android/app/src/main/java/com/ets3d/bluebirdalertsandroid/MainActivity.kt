package com.ets3d.bluebirdalertsandroid

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.core.content.ContextCompat
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
private const val KEY_UID    = "user_id"
private const val KEY_SETUP  = "setup_done"
private const val KEY_NAME   = "user_name"
private const val KEY_ROLE   = "user_role"
private const val KEY_LOGIN  = "login_name"
private const val KEY_CAN_DEACTIVATE = "can_deactivate"
private const val KEY_SERVER_URL = "server_url"
internal const val NOTIF_CH   = "bluebird_alerts"

private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
private fun isSetupDone(ctx: Context) = prefs(ctx).getBoolean(KEY_SETUP, false)
private fun getUserId(ctx: Context)   = prefs(ctx).getString(KEY_UID, "") ?: ""
private fun getUserName(ctx: Context) = prefs(ctx).getString(KEY_NAME, "") ?: ""
private fun getUserRole(ctx: Context) = prefs(ctx).getString(KEY_ROLE, "") ?: ""
private fun getLoginName(ctx: Context) = prefs(ctx).getString(KEY_LOGIN, "") ?: ""
private fun canDeactivateAlarm(ctx: Context) = prefs(ctx).getBoolean(KEY_CAN_DEACTIVATE, false)
private fun getServerUrl(ctx: Context) = prefs(ctx).getString(KEY_SERVER_URL, "") ?: ""
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

// ── Data ───────────────────────────────────────────────────────────────────────
data class AlarmStatus(
    val isActive: Boolean = false,
    val message: String?  = null,
    val activatedAt: String? = null,
    val activatedByUserId: Int? = null,
    val broadcasts: List<BroadcastUpdate> = emptyList(),
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
            baseUrl = getServerUrl(ctx),
            apiKey  = BuildConfig.BACKEND_API_KEY,
        )
        registerPushToken(ctx)
        startPolling()
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

    fun clearMessages() = _state.update { it.copy(successMsg = null, errorMsg = null) }
}

// ── Activity ───────────────────────────────────────────────────────────────────
class MainActivity : ComponentActivity() {
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
            .background(
                Brush.verticalGradient(listOf(Navy, Color(0xFF0D2347)))
            ),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(scrollState)
                .imePadding()
                .navigationBarsPadding()
                .padding(horizontal = 32.dp, vertical = 24.dp),
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
                    Text("School server", fontSize = 12.sp, color = TextMuted)
                    Text(
                        normalizeServerUrl(serverUrl),
                        fontSize = 14.sp,
                        color = BlueLight,
                        fontWeight = FontWeight.Medium,
                    )
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
                            unfocusedBorderColor = Color(0xFF2A3F5F),
                            focusedTextColor = TextPri,
                            unfocusedTextColor = TextPri,
                            cursorColor = BluePrimary,
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
                        unfocusedBorderColor = Color(0xFF2A3F5F),
                        focusedTextColor = TextPri,
                        unfocusedTextColor = TextPri,
                        cursorColor = BluePrimary,
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
                    unfocusedBorderColor = Color(0xFF2A3F5F),
                    focusedTextColor = TextPri,
                    unfocusedTextColor = TextPri,
                    cursorColor = BluePrimary,
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
                    unfocusedBorderColor = Color(0xFF2A3F5F),
                    focusedTextColor = TextPri,
                    unfocusedTextColor = TextPri,
                    cursorColor = BluePrimary,
                ),
                modifier = Modifier.fillMaxWidth(),
            )

            error?.let {
                Text(
                    text = it,
                    color = Color(0xFFFCA5A5),
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

            Button(
                onClick = submitLogin,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
                shape = RoundedCornerShape(14.dp),
                enabled = !isSubmitting,
                colors = ButtonDefaults.buttonColors(containerColor = BluePrimary, disabledContainerColor = Color(0xFF1D4ED8)),
            ) {
                Text(if (isSubmitting) "Signing In…" else "Sign In", fontSize = 16.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}

// ── Main screen ────────────────────────────────────────────────────────────────
@Composable
private fun MainScreen(onLogout: () -> Unit, vm: MainViewModel = viewModel()) {
    val ctx = LocalContext.current
    val state by vm.state.collectAsState()
    var showActivateDialog by remember { mutableStateOf(false) }
    var showDeactivateDialog by remember { mutableStateOf(false) }
    var showReportDialog by remember { mutableStateOf(false) }
    var showSettingsDialog by remember { mutableStateOf(false) }
    val userName = remember { getUserName(ctx) }
    val userRole = remember { getUserRole(ctx) }
    val canDeactivate = remember { canDeactivateAlarm(ctx) }

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
                    Text(
                        if (userName.isNotBlank()) "$userName • ${userRole.replaceFirstChar { it.uppercase() }}" else "School Safety",
                        fontSize = 12.sp,
                        color = TextMuted,
                    )
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

            if (state.alarm.broadcasts.isNotEmpty()) {
                BroadcastsCard(
                    broadcasts = state.alarm.broadcasts,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 20.dp, vertical = 8.dp),
                )
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

    if (showSettingsDialog) {
        SettingsDialog(onDismiss = { showSettingsDialog = false }, onLogout = {
            showSettingsDialog = false
            onLogout()
        })
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
                HorizontalDivider(color = Color(0x33FFFFFF), thickness = 1.dp)
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
private fun BroadcastsCard(broadcasts: List<BroadcastUpdate>, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(20.dp),
        color = NavySurface,
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
                    HorizontalDivider(color = Color(0xFF2A3F5F))
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
        containerColor = NavySurface,
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
                        unfocusedBorderColor = Color(0xFF2A3F5F),
                        focusedTextColor = TextPri,
                        unfocusedTextColor = TextPri,
                        cursorColor = BluePrimary,
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
private fun SettingsDialog(onDismiss: () -> Unit, onLogout: () -> Unit) {
    val ctx = LocalContext.current
    val userName = remember { getUserName(ctx) }
    val loginName = remember { getLoginName(ctx) }
    val userRole = remember { getUserRole(ctx) }
    val userId = remember { getUserId(ctx) }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = NavySurface,
        title = { Text("Settings", color = TextPri, fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Signed in as", color = TextMuted, fontSize = 12.sp)
                Text(userName.ifBlank { "BlueBird user" }, color = TextPri, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                Text("@${loginName.ifBlank { "unknown" }}", color = BlueLight, fontSize = 13.sp)
                HorizontalDivider(color = Color(0xFF2A3F5F))
                Text("Role: ${userRole.replaceFirstChar { it.uppercase() }}", color = TextPri, fontSize = 14.sp)
                Text("User ID: $userId", color = TextPri, fontSize = 14.sp)
                Text("Server: ${BuildConfig.BACKEND_BASE_URL}", color = TextMuted, fontSize = 12.sp)
            }
        },
        confirmButton = {
            Button(
                onClick = onLogout,
                colors = ButtonDefaults.buttonColors(containerColor = AlarmRed),
            ) { Text("Log Out") }
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
