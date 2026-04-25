package com.ets3d.bluebirdalertsandroid

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
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
        val soundUri = Uri.parse("android.resource://$packageName/${R.raw.bluebird_alarm}")

        val launchIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_OPEN_ALARM, true)
            putExtra(EXTRA_ALARM_TITLE, title)
            putExtra(EXTRA_ALARM_MESSAGE, body)
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            ALERT_PUSH_NOTIFICATION_ID,
            launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        AlarmLaunchCoordinator.publish(title = title, body = body)
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
