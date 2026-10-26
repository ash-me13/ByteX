package com.bytex.phone.security

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import java.util.UUID

class SecureStorageManager(context: Context) {
    private val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
    private val prefs: SharedPreferences = try {
        EncryptedSharedPreferences.create(
            "bytex_secure_prefs",
            masterKeyAlias,
            context,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    } catch (e: Exception) {
        context.getSharedPreferences("bytex_fallback_prefs", Context.MODE_PRIVATE)
    }

    fun getDeviceId(): String {
        var devId = prefs.getString("device_id", null)
        if (devId == null) {
            devId = "android_" + UUID.randomUUID().toString()
            prefs.edit().putString("device_id", devId).apply()
        }
        return devId
    }

    fun getDeviceName(): String {
        return android.os.Build.MODEL ?: "Android Device"
    }

    fun saveDeviceCredentials(deviceId: String, deviceToken: String, pcName: String, host: String, port: Int) {
        prefs.edit()
            .putString("device_id", deviceId)
            .putString("device_token", deviceToken)
            .putString("pc_name", pcName)
            .putString("host", host)
            .putInt("port", port)
            .putBoolean("is_paired", true)
            .apply()
    }

    fun getDeviceToken(): String? = prefs.getString("device_token", null)
    fun getPcName(): String? = prefs.getString("pc_name", null)
    fun getHost(): String? = prefs.getString("host", null)
    fun getPort(): Int = prefs.getInt("port", 8000)
    fun isPaired(): Boolean = prefs.getBoolean("is_paired", false) && getDeviceToken() != null

    fun clearCredentials() {
        prefs.edit()
            .remove("device_token")
            .remove("pc_name")
            .remove("host")
            .remove("port")
            .putBoolean("is_paired", false)
            .apply()
    }
}
