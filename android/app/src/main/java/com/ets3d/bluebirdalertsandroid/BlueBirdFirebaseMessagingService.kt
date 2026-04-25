package com.ets3d.bluebirdalertsandroid

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
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

        val launchIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            ALERT_PUSH_NOTIFICATION_ID,
            launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(this, NOTIF_CH)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setAutoCancel(true)
            .setOngoing(false)
            .setContentIntent(pendingIntent)
            .build()

        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .notify(ALERT_PUSH_NOTIFICATION_ID, notification)
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
