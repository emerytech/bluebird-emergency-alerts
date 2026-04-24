package com.ets3d.bluebirdalertsandroid

object AppLabels {
    const val KEY_LOCKDOWN = "lockdown"
    const val KEY_EVACUATION = "evacuation"
    const val KEY_SHELTER = "shelter"
    const val KEY_SECURE = "secure"
    const val KEY_REQUEST_HELP = "request_help"

    const val LOCKDOWN = "Lockdown"
    const val EVACUATION = "Evacuation"
    const val SHELTER = "Shelter"
    const val SECURE = "Secure Perimeter"
    const val REQUEST_HELP = "Request Help"

    const val ACTIVE_HELP_REQUESTS = "Active Help Requests"
    const val NO_ACTIVE_HELP_REQUESTS = "No active help requests."
    const val FORWARD_REQUEST_HELP = "Forward Request Help"

    val DEFAULT_FEATURE_LABELS: Map<String, String> = mapOf(
        KEY_LOCKDOWN to LOCKDOWN,
        KEY_EVACUATION to EVACUATION,
        KEY_SHELTER to SHELTER,
        KEY_SECURE to SECURE,
        KEY_REQUEST_HELP to REQUEST_HELP,
    )

    private fun normalizeFeatureKey(value: String): String {
        return when (value.trim().lowercase()) {
            "team_assist", "team assist", "request help" -> KEY_REQUEST_HELP
            else -> value.trim().lowercase()
        }
    }

    fun labelForFeatureKey(
        key: String,
        remoteLabels: Map<String, String> = DEFAULT_FEATURE_LABELS,
    ): String {
        val normalized = normalizeFeatureKey(key)
        return remoteLabels[normalized] ?: DEFAULT_FEATURE_LABELS[normalized] ?: key
    }

    fun featureDisplayName(
        rawValue: String,
        remoteLabels: Map<String, String> = DEFAULT_FEATURE_LABELS,
    ): String {
        return labelForFeatureKey(rawValue, remoteLabels)
    }
}
