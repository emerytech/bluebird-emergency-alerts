package com.ets3d.bluebirdalertsandroid

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

private const val SILENT_NOTIF_CH = "bluebird_info"
private const val SILENT_NOTIF_ID = 1002
private const val HELP_REQUEST_NOTIF_CH = "bluebird_help_request"
private const val NON_CRITICAL_NOTIF_CH = "non_critical_notifications"
private const val NON_CRITICAL_NOTIF_ID = 1004
private val NON_CRITICAL_TYPES = setOf(
    "quiet_period_update", "quiet_request", "admin_message", "onboarding", "info"
)
// Types that are real emergency alerts — the ONLY types that may trigger
// EmergencyAlarmTakeover, alarm sound, and full-screen notification behavior.
// An empty/missing type is treated as emergency for backward compatibility.
internal val EMERGENCY_ALERT_TYPES = setOf(
    "lockdown", "evacuation", "shelter", "secure", "hold",
    "emergency", "fire", "medical", "drill",
)

class BlueBirdFirebaseMessagingService : FirebaseMessagingService() {
    override fun onCreate() {
        super.onCreate()
        ensureNotificationChannel(applicationContext)
    }

    override fun onNewToken(token: String) {
        AndroidPushRegistrar.register(token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)
        ensureNotificationChannel(applicationContext)

        val title = message.notification?.title
            ?: message.data["title"]
            ?: "BlueBird Alert"
        val body = message.notification?.body
            ?: message.data["body"]
            ?: message.data["message"]
            ?: "Emergency alert received."

        val alertType = message.data["type"] ?: ""
        val isHelpRequest = alertType == "help_request"
        val isNonCritical = alertType in NON_CRITICAL_TYPES
        // HARD FAIL-SAFE: only real emergencies (or blank type for legacy) may trigger
        // alarm state. Any non-emergency type must NEVER reach AlarmLaunchCoordinator.
        val isEmergency = alertType.isBlank() || alertType in EMERGENCY_ALERT_TYPES

        // Detect whether this device belongs to the user who triggered the alert.
        val triggeredByUid = message.data["triggered_by_user_id"]?.toIntOrNull()
        val silentForSender = message.data["silent_for_sender"] == "true"
        val storedUid = applicationContext
            .getSharedPreferences("bluebird_prefs", Context.MODE_PRIVATE)
            .getString("user_id", "")?.toIntOrNull()
        val isSilentForMe = silentForSender
            && triggeredByUid != null
            && storedUid != null
            && triggeredByUid == storedUid

        // Only publish to AlarmLaunchCoordinator for actual emergency types.
        // Non-emergency types (quiet requests, admin messages, help requests) must
        // never activate emergency alarm state or trigger EmergencyAlarmTakeover.
        if (isEmergency) {
            AlarmLaunchCoordinator.publish(
                title = title,
                body = body,
                tenantSlug = message.data["tenant_slug"],
                isSilentForMe = isSilentForMe,
                type = alertType,
            )
        } else {
            android.util.Log.d("BlueBird", "Push type='$alertType' is non-emergency — skipping AlarmLaunchCoordinator")
        }

        if (isSilentForMe) {
            // Sender gets a discreet confirmation — no siren, no vibration, no screen wake.
            ensureSilentNotificationChannel(applicationContext)
            val (silentTitle, silentBody) = if (isHelpRequest) {
                "Help request sent" to "Your help request has been sent to your team."
            } else {
                "Alert sent" to "Your emergency alert has been sent to your school."
            }
            val silentNotification = NotificationCompat.Builder(this, SILENT_NOTIF_CH)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(silentTitle)
                .setContentText(silentBody)
                .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                .setAutoCancel(true)
                .build()
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
                .notify(SILENT_NOTIF_ID, silentNotification)
            return
        }

        // Non-sender: show notification with type-appropriate sound.
        val launchIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_OPEN_ALARM, true)
            putExtra(EXTRA_ALARM_TITLE, title)
            putExtra(EXTRA_ALARM_MESSAGE, body)
            putExtra(EXTRA_ALERT_TYPE, alertType)
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            ALERT_PUSH_NOTIFICATION_ID,
            launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        if (isNonCritical) {
            ensureNonCriticalNotificationChannel(applicationContext)
            val notification = NotificationCompat.Builder(this, NON_CRITICAL_NOTIF_CH)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                .setCategory(NotificationCompat.CATEGORY_MESSAGE)
                .setShowWhen(true)
                .setWhen(System.currentTimeMillis())
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
                .build()
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
                .notify(NON_CRITICAL_NOTIF_ID, notification)
        } else if (isHelpRequest) {
            ensureHelpRequestNotificationChannel(applicationContext)
            val helpSoundUri = Uri.parse("android.resource://$packageName/${R.raw.help_request_alert}")
            val notification = NotificationCompat.Builder(this, HELP_REQUEST_NOTIF_CH)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setCategory(NotificationCompat.CATEGORY_MESSAGE)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setShowWhen(true)
                .setWhen(System.currentTimeMillis())
                .setSound(helpSoundUri)
                .setVibrate(longArrayOf(0L, 400L, 200L, 400L))
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
                .build()
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
                .notify(HELP_REQUEST_PUSH_NOTIFICATION_ID, notification)
        } else {
            // Emergency: full alarm behavior.
            val soundUri = Uri.parse("android.resource://$packageName/${R.raw.bluebird_alarm}")
            wakeScreenForAlert()
            val notification = NotificationCompat.Builder(this, NOTIF_CH)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setCategory(NotificationCompat.CATEGORY_ALARM)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setShowWhen(true)
                .setWhen(System.currentTimeMillis())
                .setSound(soundUri)
                .setVibrate(longArrayOf(0L, 900L, 350L, 900L, 350L, 1200L))
                .setAutoCancel(false)
                .setOngoing(true)
                .setContentIntent(pendingIntent)
                .setFullScreenIntent(pendingIntent, true)
                .build()
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
                .notify(ALERT_PUSH_NOTIFICATION_ID, notification)
        }
    }

    private fun ensureHelpRequestNotificationChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (manager.getNotificationChannel(HELP_REQUEST_NOTIF_CH) != null) return
        val soundUri = Uri.parse("android.resource://${context.packageName}/${R.raw.help_request_alert}")
        val attrs = android.media.AudioAttributes.Builder()
            .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .setUsage(android.media.AudioAttributes.USAGE_NOTIFICATION)
            .build()
        val channel = NotificationChannel(
            HELP_REQUEST_NOTIF_CH,
            "BlueBird Help Requests",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Help request alerts from staff"
            enableVibration(true)
            vibrationPattern = longArrayOf(0L, 400L, 200L, 400L)
            setSound(soundUri, attrs)
        }
        manager.createNotificationChannel(channel)
    }

    private fun ensureNonCriticalNotificationChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (manager.getNotificationChannel(NON_CRITICAL_NOTIF_CH) != null) return
        val channel = NotificationChannel(
            NON_CRITICAL_NOTIF_CH,
            "BlueBird Notifications",
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = "Routine updates: quiet requests, approvals, admin messages"
            enableVibration(false)
        }
        manager.createNotificationChannel(channel)
    }

    private fun ensureSilentNotificationChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (manager.getNotificationChannel(SILENT_NOTIF_CH) != null) return
        val channel = NotificationChannel(
            SILENT_NOTIF_CH,
            "BlueBird Info",
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = "Confirmation and status notifications"
            enableVibration(false)
            setSound(null, null)
        }
        manager.createNotificationChannel(channel)
    }

    private fun wakeScreenForAlert() {
        val powerManager = getSystemService(Context.POWER_SERVICE) as? PowerManager ?: return
        @Suppress("DEPRECATION")
        val wakeLock = powerManager.newWakeLock(
            PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP,
            "bluebird:push-alert",
        )
        runCatching { wakeLock.acquire(5_000L) }
    }
}

object AndroidPushRegistrar {
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()
    private val json = "application/json; charset=utf-8".toMediaType()

    fun register(token: String) {
        if (token.isBlank()) return

        val body = JSONObject()
            .put("device_token", token.trim())
            .put("platform", "android")
            .put("push_provider", "fcm")

        val requestBuilder = Request.Builder()
            .url("${BuildConfig.BACKEND_BASE_URL.trimEnd('/')}/register-device")
            .post(body.toString().toRequestBody(json))

        if (BuildConfig.BACKEND_API_KEY.isNotBlank()) {
            requestBuilder.header("X-API-Key", BuildConfig.BACKEND_API_KEY)
        }

        runCatching {
            http.newCall(requestBuilder.build()).execute().use { response ->
                response.body?.close()
            }
        }
    }
}
