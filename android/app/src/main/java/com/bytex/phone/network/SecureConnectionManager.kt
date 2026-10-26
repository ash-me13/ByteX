package com.bytex.phone.network

import android.content.Context
import android.os.Handler
import android.os.Looper
import com.bytex.phone.model.PairingPayload
import com.bytex.phone.security.SecureStorageManager
import okhttp3.*
import org.json.JSONObject
import java.util.concurrent.TimeUnit

enum class ConnectionState {
    DISCONNECTED,
    PAIRING,
    WAITING_FOR_APPROVAL,
    CONNECTING,
    CONNECTED,
    RECONNECTING,
    EXPIRED,
    REJECTED,
    ERROR
}

class SecureConnectionManager(private val context: Context) {
    private val storage = SecureStorageManager(context)
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(10, TimeUnit.SECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private var state: ConnectionState = ConnectionState.DISCONNECTED
    private val handler = Handler(Looper.getMainLooper())
    private var stateListeners = mutableListOf<(ConnectionState, String?) -> Unit>()
    private var reconnectAttempts = 0
    private val maxReconnectAttempts = 5

    fun addListener(listener: (ConnectionState, String?) -> Unit) {
        stateListeners.add(listener)
        listener(state, null)
    }

    private fun updateState(newState: ConnectionState, message: String? = null) {
        state = newState
        handler.post {
            stateListeners.forEach { it(newState, message) }
        }
    }

    fun startPairingHandshake(payload: PairingPayload) {
        if (payload.isExpired()) {
            updateState(ConnectionState.EXPIRED, "Pairing code has expired.")
            return
        }

        updateState(ConnectionState.PAIRING, "Connecting to ByteX PC...")
        val url = "ws://${payload.host}:${payload.port}/ws/phone"
        val request = Request.Builder().url(url).build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                // Send pairing request
                val pairMsg = JSONObject().apply {
                    put("type", "PAIRING_REQUEST")
                    put("protocol_version", 1)
                    put("session_id", payload.sessionId)
                    put("secret", payload.secret)
                    put("device_id", storage.getDeviceId())
                    put("device_name", storage.getDeviceName())
                    put("platform", "Android")
                }
                ws.send(pairMsg.toString())
            }

            override fun onMessage(ws: WebSocket, text: String) {
                val json = JSONObject(text)
                when (json.optString("type")) {
                    "PAIRING_WAITING_APPROVAL" -> {
                        updateState(ConnectionState.WAITING_FOR_APPROVAL, "Approval requested on PC. Please approve on ByteX.")
                    }
                    "PAIRING_APPROVED" -> {
                        val token = json.optString("device_token", "token_" + payload.sessionId)
                        storage.saveDeviceCredentials(
                            deviceId = storage.getDeviceId(),
                            deviceToken = token,
                            pcName = payload.pcName,
                            host = payload.host,
                            port = payload.port
                        )
                        updateState(ConnectionState.CONNECTED, "Connected to ByteX on ${payload.pcName}")
                    }
                    "PAIRING_REJECTED" -> {
                        updateState(ConnectionState.REJECTED, json.optString("message", "Pairing rejected"))
                    }
                    "PAIRING_ERROR" -> {
                        updateState(ConnectionState.ERROR, json.optString("message", "Pairing error"))
                    }
                }
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                updateState(ConnectionState.ERROR, "Connection failed: ${t.localizedMessage}")
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                updateState(ConnectionState.DISCONNECTED, "Disconnected from ByteX")
            }
        })
    }

    fun connectTrusted() {
        if (!storage.isPaired()) {
            updateState(ConnectionState.DISCONNECTED, "No paired PC found. Please scan QR.")
            return
        }

        val host = storage.getHost() ?: "127.0.0.1"
        val port = storage.getPort()
        val token = storage.getDeviceToken() ?: ""
        val url = "ws://$host:$port/ws/phone"

        updateState(ConnectionState.CONNECTING, "Connecting to ${storage.getPcName()}...")
        val request = Request.Builder().url(url).build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                val authMsg = JSONObject().apply {
                    put("type", "AUTHENTICATE")
                    put("protocol_version", 1)
                    put("device_id", storage.getDeviceId())
                    put("device_token", token)
                }
                ws.send(authMsg.toString())
            }

            override fun onMessage(ws: WebSocket, text: String) {
                val json = JSONObject(text)
                when (json.optString("type")) {
                    "AUTH_SUCCESS" -> {
                        reconnectAttempts = 0
                        updateState(ConnectionState.CONNECTED, "Connected to ${storage.getPcName()}")
                    }
                    "AUTH_FAILED" -> {
                        storage.clearCredentials()
                        updateState(ConnectionState.ERROR, "Authentication failed. Device revoked.")
                    }
                    "PONG" -> {
                        // Heartbeat acknowledged
                    }
                }
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                scheduleReconnect()
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                updateState(ConnectionState.DISCONNECTED, "Disconnected")
            }
        })
    }

    private fun scheduleReconnect() {
        if (reconnectAttempts < maxReconnectAttempts) {
            reconnectAttempts++
            val delayMs = (1000L * (1 shl reconnectAttempts)).coerceAtMost(16000L)
            updateState(ConnectionState.RECONNECTING, "Reconnecting (attempt $reconnectAttempts)...")
            handler.postDelayed({ connectTrusted() }, delayMs)
        } else {
            updateState(ConnectionState.DISCONNECTED, "Could not reconnect to PC.")
        }
    }

    fun disconnect() {
        try {
            webSocket?.close(1000, "User disconnected")
        } catch (e: Exception) {}
        updateState(ConnectionState.DISCONNECTED, "Disconnected")
    }
}
