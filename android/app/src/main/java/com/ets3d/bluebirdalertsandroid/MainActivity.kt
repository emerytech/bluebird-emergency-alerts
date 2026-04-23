package com.ets3d.bluebirdalertsandroid

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
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
import org.json.JSONArray
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            BlueBirdAlertsTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    val viewModel: MainViewModel = viewModel()
                    BlueBirdAlertsScreen(viewModel)
                }
            }
        }
    }
}

data class AlarmUiState(
    val isActive: Boolean = false,
    val message: String? = null,
    val activatedAt: String? = null,
    val activatedByUserId: Int? = null,
)

data class UiState(
    val backendBaseUrl: String = BuildConfig.BACKEND_BASE_URL,
    val backendReachable: Boolean? = null,
    val deviceRegistered: Boolean = false,
    val registeredDeviceCount: Int = 0,
    val providerCountsText: String = "",
    val lastStatus: String? = null,
    val lastError: String? = null,
    val recentAlerts: List<String> = emptyList(),
    val isTestingBackend: Boolean = false,
    val isRegistering: Boolean = false,
    val isSending: Boolean = false,
    val isRefreshing: Boolean = false,
    val isDeactivating: Boolean = false,
    val localTestTokenSuffix: String = LOCAL_TEST_DEVICE_TOKEN.takeLast(8),
    val alarm: AlarmUiState = AlarmUiState(),
)

class MainViewModel : ViewModel() {
    private val client = BackendClient(BuildConfig.BACKEND_BASE_URL)
    private val _uiState = MutableStateFlow(UiState())
    val uiState: StateFlow<UiState> = _uiState

    init {
        startAlarmPolling()
    }

    private fun startAlarmPolling() {
        viewModelScope.launch(Dispatchers.IO) {
            while (isActive) {
                runCatching { client.alarmStatus() }
                    .onSuccess { alarm ->
                        _uiState.update { state ->
                            state.copy(
                                alarm = AlarmUiState(
                                    isActive = alarm.isActive,
                                    message = alarm.message,
                                    activatedAt = alarm.activatedAt,
                                    activatedByUserId = alarm.activatedByUserId,
                                ),
                            )
                        }
                    }
                    .onFailure { error ->
                        _uiState.update { state ->
                            state.copy(lastError = "Alarm status check failed: ${error.message}")
                        }
                    }
                delay(3000)
            }
        }
    }

    fun testBackend() {
        viewModelScope.launch(Dispatchers.IO) {
            _uiState.update { it.copy(isTestingBackend = true, lastError = null) }
            runCatching { client.health() }
                .onSuccess { ok ->
                    _uiState.update {
                        it.copy(
                            backendReachable = ok,
                            lastStatus = if (ok) "Backend reachable." else "Backend returned an unhealthy response.",
                            isTestingBackend = false,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            backendReachable = false,
                            lastError = "Backend test failed: ${error.message}",
                            isTestingBackend = false,
                        )
                    }
                }
        }
    }

    fun registerLocalTestDevice() {
        viewModelScope.launch(Dispatchers.IO) {
            _uiState.update { it.copy(isRegistering = true, lastError = null) }
            runCatching { client.registerLocalAndroidDevice(LOCAL_TEST_DEVICE_TOKEN) }
                .onSuccess { response ->
                    _uiState.update {
                        it.copy(
                            deviceRegistered = response.deviceCount > 0,
                            registeredDeviceCount = response.deviceCount,
                            providerCountsText = response.providerCounts.entries.joinToString { entry -> "${entry.key}: ${entry.value}" },
                            lastStatus = "Registered local test device. Devices: ${response.deviceCount}",
                            isRegistering = false,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            deviceRegistered = false,
                            lastError = "Register device failed: ${error.message}",
                            isRegistering = false,
                        )
                    }
                }
        }
    }

    fun loadDebugData() {
        viewModelScope.launch(Dispatchers.IO) {
            _uiState.update { it.copy(isRefreshing = true, lastError = null) }
            runCatching {
                val devices = client.devices()
                val alerts = client.alerts(limit = 5)
                val alarm = client.alarmStatus()
                Triple(devices, alerts, alarm)
            }.onSuccess { (devices, alerts, alarm) ->
                _uiState.update {
                    it.copy(
                        registeredDeviceCount = devices.deviceCount,
                        providerCountsText = devices.providerCounts.entries.joinToString { entry -> "${entry.key}: ${entry.value}" },
                        recentAlerts = alerts.alerts.map { alert -> "#${alert.alertId} ${alert.message}" },
                        lastStatus = "Loaded backend debug data.",
                        isRefreshing = false,
                        alarm = AlarmUiState(
                            isActive = alarm.isActive,
                            message = alarm.message,
                            activatedAt = alarm.activatedAt,
                            activatedByUserId = alarm.activatedByUserId,
                        ),
                    )
                }
            }.onFailure { error ->
                _uiState.update {
                    it.copy(
                        lastError = "Load debug data failed: ${error.message}",
                        isRefreshing = false,
                    )
                }
            }
        }
    }

    fun activateAlarm(message: String, userIdText: String) {
        viewModelScope.launch(Dispatchers.IO) {
            _uiState.update { it.copy(isSending = true, lastError = null) }
            runCatching {
                client.activateAlarm(
                    message = message,
                    userId = userIdText.trim().toIntOrNull(),
                )
            }.onSuccess { response ->
                _uiState.update {
                    it.copy(
                        lastStatus = "Alarm activated.",
                        isSending = false,
                        alarm = AlarmUiState(
                            isActive = response.isActive,
                            message = response.message,
                            activatedAt = response.activatedAt,
                            activatedByUserId = response.activatedByUserId,
                        ),
                    )
                }
                loadDebugData()
            }.onFailure { error ->
                _uiState.update {
                    it.copy(
                        lastError = "Alarm activation failed: ${error.message}",
                        isSending = false,
                    )
                }
            }
        }
    }

    fun deactivateAlarm(adminUserIdText: String) {
        viewModelScope.launch(Dispatchers.IO) {
            _uiState.update { it.copy(isDeactivating = true, lastError = null) }
            runCatching {
                client.deactivateAlarm(adminUserIdText.trim().toIntOrNull())
            }.onSuccess { response ->
                _uiState.update {
                    it.copy(
                        lastStatus = "Alarm deactivated.",
                        isDeactivating = false,
                        alarm = AlarmUiState(
                            isActive = response.isActive,
                            message = response.message,
                            activatedAt = response.activatedAt,
                            activatedByUserId = response.activatedByUserId,
                        ),
                    )
                }
                loadDebugData()
            }.onFailure { error ->
                _uiState.update {
                    it.copy(
                        lastError = "Alarm deactivation failed: ${error.message}",
                        isDeactivating = false,
                    )
                }
            }
        }
    }
}

private class BackendClient(baseUrl: String) {
    private val http = OkHttpClient()
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()
    private val normalizedBaseUrl = baseUrl.trimEnd('/')

    fun health(): Boolean {
        val request = Request.Builder()
            .url("$normalizedBaseUrl/health")
            .get()
            .build()

        http.newCall(request).execute().use { response ->
            val body = requireSuccess(response)
            return JSONObject(body).optBoolean("ok", false)
        }
    }

    fun registerLocalAndroidDevice(token: String): RegisterDeviceResponse {
        val body = JSONObject()
            .put("device_token", token)
            .put("platform", "android")
            .put("push_provider", "fcm")

        val request = Request.Builder()
            .url("$normalizedBaseUrl/register-device")
            .post(body.toString().toRequestBody(jsonMediaType))
            .build()

        http.newCall(request).execute().use { response ->
            val responseBody = requireSuccess(response)
            return RegisterDeviceResponse(JSONObject(responseBody))
        }
    }

    fun activateAlarm(message: String, userId: Int?): AlarmStatusResponse {
        val body = JSONObject().put("message", message)
        if (userId != null) {
            body.put("user_id", userId)
        }
        val request = Request.Builder()
            .url("$normalizedBaseUrl/alarm/activate")
            .post(body.toString().toRequestBody(jsonMediaType))
            .build()

        http.newCall(request).execute().use { response ->
            val responseBody = requireSuccess(response)
            return AlarmStatusResponse(JSONObject(responseBody))
        }
    }

    fun deactivateAlarm(userId: Int?): AlarmStatusResponse {
        val body = JSONObject()
        if (userId != null) {
            body.put("user_id", userId)
        }
        val request = Request.Builder()
            .url("$normalizedBaseUrl/alarm/deactivate")
            .post(body.toString().toRequestBody(jsonMediaType))
            .build()

        http.newCall(request).execute().use { response ->
            val responseBody = requireSuccess(response)
            return AlarmStatusResponse(JSONObject(responseBody))
        }
    }

    fun alarmStatus(): AlarmStatusResponse {
        val request = Request.Builder()
            .url("$normalizedBaseUrl/alarm/status")
            .get()
            .build()

        http.newCall(request).execute().use { response ->
            val body = requireSuccess(response)
            return AlarmStatusResponse(JSONObject(body))
        }
    }

    fun devices(): DevicesResponse {
        val request = Request.Builder()
            .url("$normalizedBaseUrl/devices")
            .get()
            .build()

        http.newCall(request).execute().use { response ->
            val body = requireSuccess(response)
            return DevicesResponse(JSONObject(body))
        }
    }

    fun alerts(limit: Int): AlertsResponse {
        val request = Request.Builder()
            .url("$normalizedBaseUrl/alerts?limit=$limit")
            .get()
            .build()

        http.newCall(request).execute().use { response ->
            val body = requireSuccess(response)
            return AlertsResponse(JSONObject(body))
        }
    }

    private fun requireSuccess(response: okhttp3.Response): String {
        val body = response.body?.string().orEmpty()
        if (!response.isSuccessful) {
            val errorMessage = runCatching {
                val detail = JSONObject(body).opt("detail")
                when (detail) {
                    is String -> detail
                    is JSONArray -> detail.optJSONObject(0)?.optString("msg") ?: body
                    else -> body
                }
            }.getOrDefault(body.ifBlank { "Request failed." })
            error(errorMessage)
        }
        return body
    }
}

private data class RegisterDeviceResponse(
    val registered: Boolean,
    val deviceCount: Int,
    val providerCounts: Map<String, Int>,
) {
    constructor(json: JSONObject) : this(
        registered = json.optBoolean("registered"),
        deviceCount = json.optInt("device_count"),
        providerCounts = jsonObjectToMap(json.optJSONObject("provider_counts")),
    )
}

private data class AlarmStatusResponse(
    val isActive: Boolean,
    val message: String?,
    val activatedAt: String?,
    val activatedByUserId: Int?,
) {
    constructor(json: JSONObject) : this(
        isActive = json.optBoolean("is_active"),
        message = json.optString("message").ifBlank { null },
        activatedAt = json.optString("activated_at").ifBlank { null },
        activatedByUserId = if (json.has("activated_by_user_id") && !json.isNull("activated_by_user_id")) json.optInt("activated_by_user_id") else null,
    )
}

private data class DevicesResponse(
    val deviceCount: Int,
    val providerCounts: Map<String, Int>,
) {
    constructor(json: JSONObject) : this(
        deviceCount = json.optInt("device_count"),
        providerCounts = jsonObjectToMap(json.optJSONObject("provider_counts")),
    )
}

private data class AlertItem(
    val alertId: Int,
    val message: String,
)

private data class AlertsResponse(
    val alerts: List<AlertItem>,
) {
    constructor(json: JSONObject) : this(
        alerts = buildList {
            val array = json.optJSONArray("alerts") ?: JSONArray()
            for (index in 0 until array.length()) {
                val item = array.optJSONObject(index) ?: continue
                add(
                    AlertItem(
                        alertId = item.optInt("alert_id"),
                        message = item.optString("message"),
                    ),
                )
            }
        },
    )
}

@Composable
private fun BlueBirdAlertsScreen(viewModel: MainViewModel) {
    val state by viewModel.uiState.collectAsState()
    var message by remember { mutableStateOf("Emergency alert. Please follow school procedures.") }
    var triggerUserId by remember { mutableStateOf("") }
    var adminUserId by remember { mutableStateOf("") }
    var showConfirm by remember { mutableStateOf(false) }
    val alarmMessage = state.alarm.message
    val activatedAt = state.alarm.activatedAt
    val activatedByUserId = state.alarm.activatedByUserId

    AlarmSoundEffect(isAlarmActive = state.alarm.isActive)

    LaunchedEffect(alarmMessage) {
        if (state.alarm.isActive && !alarmMessage.isNullOrBlank()) {
            message = alarmMessage
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text("! ", fontSize = 36.sp, color = Color(0xFFD32F2F), fontWeight = FontWeight.Bold)
            Text("BlueBird Alerts", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        }

        AlarmBanner(state.alarm)

        StatusRow("Backend", state.backendBaseUrl)
        StatusRow(
            "Backend status",
            when (state.backendReachable) {
                true -> "reachable"
                false -> "unreachable"
                null -> "not tested"
            },
        )
        StatusRow("Device", if (state.deviceRegistered) "registered" else "not registered")
        StatusRow("Token source", "local test")
        StatusRow("Alarm sound", if (state.alarm.isActive) "playing until cleared" else "idle")
        if (activatedAt != null) {
            StatusRow("Activated at", activatedAt)
        }
        if (activatedByUserId != null) {
            StatusRow("Activated by", activatedByUserId.toString())
        }
        if (state.registeredDeviceCount > 0) {
            StatusRow("Registered devices", state.registeredDeviceCount.toString())
        }
        if (state.providerCountsText.isNotBlank()) {
            StatusRow("Providers", state.providerCountsText)
        }

        state.lastStatus?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.secondary) }
        state.lastError?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }

        OutlinedButton(
            onClick = { viewModel.testBackend() },
            modifier = Modifier.fillMaxWidth(),
            enabled = !state.isTestingBackend,
        ) {
            Text(if (state.isTestingBackend) "Testing..." else "Test Backend")
        }

        OutlinedButton(
            onClick = { viewModel.registerLocalTestDevice() },
            modifier = Modifier.fillMaxWidth(),
            enabled = !state.isRegistering,
        ) {
            Text(if (state.isRegistering) "Registering..." else "Use Local Test Device")
        }

        OutlinedButton(
            onClick = { viewModel.loadDebugData() },
            modifier = Modifier.fillMaxWidth(),
            enabled = !state.isRefreshing,
        ) {
            Text(if (state.isRefreshing) "Refreshing..." else "Load Debug Data")
        }

        OutlinedTextField(
            value = message,
            onValueChange = { message = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Alarm message") },
            minLines = 3,
        )

        OutlinedTextField(
            value = triggerUserId,
            onValueChange = { triggerUserId = it.filter(Char::isDigit) },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Trigger user id (optional)") },
            singleLine = true,
        )

        Button(
            onClick = { showConfirm = true },
            modifier = Modifier
                .fillMaxWidth()
                .height(120.dp),
            shape = RoundedCornerShape(28.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFD32F2F)),
            enabled = !state.isSending && message.isNotBlank(),
        ) {
            Text(
                text = if (state.isSending) "Activating..." else "ACTIVATE ALARM",
                fontSize = 28.sp,
                fontWeight = FontWeight.ExtraBold,
            )
        }

        OutlinedTextField(
            value = adminUserId,
            onValueChange = { adminUserId = it.filter(Char::isDigit) },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Admin user id to deactivate") },
            singleLine = true,
        )

        OutlinedButton(
            onClick = { viewModel.deactivateAlarm(adminUserId) },
            modifier = Modifier.fillMaxWidth(),
            enabled = !state.isDeactivating && adminUserId.isNotBlank(),
        ) {
            Text(if (state.isDeactivating) "Deactivating..." else "Deactivate Alarm")
        }

        if (state.recentAlerts.isNotEmpty()) {
            Text("Recent Alerts", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            state.recentAlerts.forEach { alert ->
                Text(alert, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.secondary)
            }
        }

        Spacer(modifier = Modifier.height(12.dp))
    }

    if (showConfirm) {
        AlertDialog(
            onDismissRequest = { showConfirm = false },
            title = { Text("Activate alarm?") },
            text = { Text(message) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showConfirm = false
                        viewModel.activateAlarm(message, triggerUserId)
                    },
                ) {
                    Text("Activate")
                }
            },
            dismissButton = {
                TextButton(onClick = { showConfirm = false }) {
                    Text("Cancel")
                }
            },
        )
    }
}

@Composable
private fun AlarmBanner(alarm: AlarmUiState) {
    val color = if (alarm.isActive) Color(0xFFD32F2F) else Color(0xFF1F7A4D)
    val text = if (alarm.isActive) "ALARM ACTIVE" else "Alarm clear"
    val detail = if (alarm.isActive) alarm.message ?: "Emergency alert in progress." else "No active school alarm."
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(color, RoundedCornerShape(18.dp))
            .padding(18.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(text, color = Color.White, fontWeight = FontWeight.ExtraBold, fontSize = 22.sp)
            Text(detail, color = Color.White)
        }
    }
}

@Composable
private fun AlarmSoundEffect(isAlarmActive: Boolean) {
    val context = LocalContext.current
    val player = remember { AlarmPlayer(context.applicationContext) }

    DisposableEffect(isAlarmActive) {
        if (isAlarmActive) {
            player.start()
        } else {
            player.stop()
        }
        onDispose { }
    }

    DisposableEffect(Unit) {
        onDispose { player.release() }
    }
}

private class AlarmPlayer(private val context: Context) {
    private var mediaPlayer: MediaPlayer? = null

    fun start() {
        if (mediaPlayer?.isPlaying == true) return
        val uri = defaultAlarmUri()
        val player = MediaPlayer()
        player.setAudioAttributes(
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build(),
        )
        player.setDataSource(context, uri)
        player.isLooping = true
        player.prepare()
        player.start()
        mediaPlayer = player
    }

    fun stop() {
        mediaPlayer?.run {
            if (isPlaying) {
                stop()
            }
            reset()
            release()
        }
        mediaPlayer = null
    }

    fun release() {
        stop()
    }

    private fun defaultAlarmUri(): Uri {
        return RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
    }
}

@Composable
private fun StatusRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.secondary)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun BlueBirdAlertsTheme(content: @Composable () -> Unit) {
    MaterialTheme(content = content)
}

private fun jsonObjectToMap(jsonObject: JSONObject?): Map<String, Int> {
    if (jsonObject == null) return emptyMap()
    return buildMap {
        val keys = jsonObject.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            put(key, jsonObject.optInt(key))
        }
    }
}

private const val LOCAL_TEST_DEVICE_TOKEN = "local-android-device-token-001"
