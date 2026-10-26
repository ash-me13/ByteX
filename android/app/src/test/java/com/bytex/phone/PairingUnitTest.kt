package com.bytex.phone

import com.bytex.phone.model.PairingPayload
import org.junit.Assert.*
import org.junit.Test

class PairingUnitTest {

    @Test
    fun testValidQRPayloadParsing() {
        val json = """
            {
                "v": 1,
                "sid": "1234-5678-uuid",
                "sec": "abcdef0123456789",
                "pc": "My-PC",
                "host": "192.168.1.100",
                "port": 8000,
                "exp": ${System.currentTimeMillis() / 1000 + 60}
            }
        """.trimIndent()

        val payload = PairingPayload.fromJson(json)
        assertNotNull(payload)
        assertEquals(1, payload?.protocolVersion)
        assertEquals("1234-5678-uuid", payload?.sessionId)
        assertEquals("abcdef0123456789", payload?.secret)
        assertEquals("My-PC", payload?.pcName)
        assertEquals("192.168.1.100", payload?.host)
        assertEquals(8000, payload?.port)
        assertFalse(payload?.isExpired() ?: true)
    }

    @Test
    fun testExpiredQRPayload() {
        val json = """
            {
                "v": 1,
                "sid": "1234-5678-uuid",
                "sec": "abcdef0123456789",
                "pc": "My-PC",
                "host": "192.168.1.100",
                "port": 8000,
                "exp": ${System.currentTimeMillis() / 1000 - 10}
            }
        """.trimIndent()

        val payload = PairingPayload.fromJson(json)
        assertNotNull(payload)
        assertTrue(payload?.isExpired() ?: false)
    }

    @Test
    fun testInvalidQRPayloadFormat() {
        val invalidJson = "{ invalid_json: true }"
        val payload = PairingPayload.fromJson(invalidJson)
        assertNull(payload)
    }

    @Test
    fun testTamperedQRPayload() {
        val missingFields = """
            {
                "v": 1,
                "sid": "1234"
            }
        """.trimIndent()
        val payload = PairingPayload.fromJson(missingFields)
        assertNull(payload)
    }
}
