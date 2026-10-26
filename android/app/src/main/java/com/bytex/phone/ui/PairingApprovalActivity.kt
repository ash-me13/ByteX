package com.bytex.phone.ui

import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.bytex.phone.model.PairingPayload
import com.bytex.phone.network.SecureConnectionManager

class PairingApprovalActivity : AppCompatActivity() {

    private lateinit var connectionManager: SecureConnectionManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        connectionManager = SecureConnectionManager(this)

        val pcName = intent.getStringExtra("pc_name") ?: "ByteX PC"
        val qrJson = intent.getStringExtra("qr_json") ?: ""
        val payload = PairingPayload.fromJson(qrJson)

        val layout = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(48, 80, 48, 80)
            gravity = android.view.Gravity.CENTER
        }

        val title = TextView(this).apply {
            text = "ByteX PC Detected"
            textSize = 20f
            setTypeface(null, android.graphics.Typeface.BOLD)
            gravity = android.view.Gravity.CENTER
        }

        val desc = TextView(this).apply {
            text = "Do you want to connect this phone to ByteX on '$pcName'?"
            textSize = 16f
            setPadding(0, 32, 0, 48)
            gravity = android.view.Gravity.CENTER
        }

        val connectBtn = Button(this).apply {
            text = "Connect"
            setOnClickListener {
                if (payload != null) {
                    connectionManager.startPairingHandshake(payload)
                }
                finish()
            }
        }

        val cancelBtn = Button(this).apply {
            text = "Cancel"
            setOnClickListener {
                finish()
            }
        }

        layout.addView(title)
        layout.addView(desc)
        layout.addView(connectBtn)
        layout.addView(cancelBtn)
        setContentView(layout)
    }
}
