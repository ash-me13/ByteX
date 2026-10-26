package com.bytex.phone.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.bytex.phone.R
import com.bytex.phone.model.PairingPayload
import com.bytex.phone.network.ConnectionState
import com.bytex.phone.network.SecureConnectionManager
import com.bytex.phone.security.SecureStorageManager

class MainActivity : AppCompatActivity() {

    private lateinit var storage: SecureStorageManager
    private lateinit var connectionManager: SecureConnectionManager
    private lateinit var statusText: TextView
    private lateinit var scanButton: Button
    private lateinit var disconnectButton: Button

    private val requestCameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted: Boolean ->
        if (isGranted) {
            launchQrScanner()
        } else {
            Toast.makeText(this, "Camera permission is required to scan the PC pairing QR code.", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Initialize managers
        storage = SecureStorageManager(this)
        connectionManager = SecureConnectionManager(this)

        // Setup simple layout programmatically or via layout
        setupUI()

        connectionManager.addListener { state, msg ->
            runOnUiThread {
                updateStateUI(state, msg)
            }
        }

        // Auto-reconnect if already paired
        if (storage.isPaired()) {
            connectionManager.connectTrusted()
        }
    }

    private fun setupUI() {
        val layout = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(48, 80, 48, 80)
            gravity = android.view.Gravity.CENTER
        }

        val titleText = TextView(this).apply {
            text = "ByteX Phone Companion"
            textSize = 22f
            setTypeface(null, android.graphics.Typeface.BOLD)
            gravity = android.view.Gravity.CENTER
        }

        statusText = TextView(this).apply {
            text = if (storage.isPaired()) "🔴 Disconnected" else "No PC paired"
            textSize = 16f
            setPadding(0, 32, 0, 32)
            gravity = android.view.Gravity.CENTER
        }

        scanButton = Button(this).apply {
            text = "📱 Scan QR Code"
            setOnClickListener { checkCameraAndScan() }
        }

        disconnectButton = Button(this).apply {
            text = "Disconnect"
            visibility = android.view.View.GONE
            setOnClickListener {
                connectionManager.disconnect()
            }
        }

        layout.addView(titleText)
        layout.addView(statusText)
        layout.addView(scanButton)
        layout.addView(disconnectButton)
        setContentView(layout)
    }

    private fun checkCameraAndScan() {
        when {
            ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED -> {
                launchQrScanner()
            }
            else -> {
                requestCameraPermissionLauncher.launch(Manifest.permission.CAMERA)
            }
        }
    }

    private fun launchQrScanner() {
        // Launches pairing approval with scanned QR payload
        Toast.makeText(this, "Align camera with ByteX PC QR code...", Toast.LENGTH_SHORT).show()
    }

    fun handleQrScanned(qrJsonString: String) {
        val payload = PairingPayload.fromJson(qrJsonString)
        if (payload == null) {
            Toast.makeText(this, "Invalid ByteX QR code payload.", Toast.LENGTH_SHORT).show()
            return
        }

        if (payload.isExpired()) {
            Toast.makeText(this, "This pairing QR code has expired.", Toast.LENGTH_SHORT).show()
            return
        }

        val intent = Intent(this, PairingApprovalActivity::class.java).apply {
            putExtra("pc_name", payload.pcName)
            putExtra("qr_json", qrJsonString)
        }
        startActivity(intent)
    }

    private fun updateStateUI(state: ConnectionState, message: String?) {
        when (state) {
            ConnectionState.CONNECTED -> {
                statusText.text = "🟢 Connected to ByteX (${storage.getPcName()})"
                scanButton.visibility = android.view.View.GONE
                disconnectButton.visibility = android.view.View.VISIBLE
            }
            ConnectionState.CONNECTING -> {
                statusText.text = "🟡 Connecting..."
                disconnectButton.visibility = android.view.View.GONE
            }
            ConnectionState.RECONNECTING -> {
                statusText.text = "🟡 Reconnecting..."
            }
            ConnectionState.WAITING_FOR_APPROVAL -> {
                statusText.text = "🟠 Waiting for PC Approval..."
            }
            ConnectionState.PAIRING -> {
                statusText.text = "Pairing in progress..."
            }
            ConnectionState.DISCONNECTED -> {
                statusText.text = "🔴 Phone Disconnected"
                scanButton.visibility = android.view.View.VISIBLE
                disconnectButton.visibility = android.view.View.GONE
            }
            ConnectionState.EXPIRED -> {
                statusText.text = "⚠️ Pairing Code Expired"
                scanButton.visibility = android.view.View.VISIBLE
            }
            ConnectionState.REJECTED -> {
                statusText.text = "❌ Pairing Rejected"
                scanButton.visibility = android.view.View.VISIBLE
            }
            ConnectionState.ERROR -> {
                statusText.text = "⚠️ ${message ?: "Connection Error"}"
            }
        }
    }
}
