package com.bytex.phone.model

import org.json.JSONObject

data class PairingPayload(
    val protocolVersion: Int,
    val sessionId: String,
    val secret: String,
    val pcName: String,
    val host: String,
    val port: Int,
    val expiresAt: Long
) {
    fun isExpired(): Boolean {
        return (System.currentTimeMillis() / 1000) > expiresAt
    }

    companion object {
        fun fromJson(jsonStr: String): PairingPayload? {
            return try {
                val json = JSONObject(jsonStr)
                PairingPayload(
                    protocolVersion = json.optInt("v", 1),
                    sessionId = json.getString("sid"),
                    secret = json.getString("sec"),
                    pcName = json.getString("pc"),
                    host = json.getString("host"),
                    port = json.getInt("port"),
                    expiresAt = json.getLong("exp")
                )
            } catch (e: Exception) {
                null
            }
        }
    }
}
