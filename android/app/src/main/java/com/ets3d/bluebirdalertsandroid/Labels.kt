package com.ets3d.bluebirdalertsandroid

object AppLabels {
    const val LOCKDOWN = "Lockdown"
    const val EVACUATION = "Evacuation"
    const val SHELTER = "Shelter"
    const val SECURE = "Secure Perimeter"
    const val REQUEST_HELP = "Request Help"

    const val ACTIVE_HELP_REQUESTS = "Active Help Requests"
    const val NO_ACTIVE_HELP_REQUESTS = "No active help requests."
    const val FORWARD_REQUEST_HELP = "Forward Request Help"

    fun featureDisplayName(rawValue: String): String {
        return when (rawValue.trim().lowercase()) {
            "lockdown" -> LOCKDOWN
            "evacuation" -> EVACUATION
            "shelter" -> SHELTER
            "secure" -> SECURE
            "request_help", "request help", "team_assist", "team assist" -> REQUEST_HELP
            else -> rawValue
        }
    }
}

