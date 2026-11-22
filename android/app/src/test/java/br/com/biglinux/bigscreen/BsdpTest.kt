package br.com.biglinux.bigscreen

import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

/** The app's protocol against tests/data/bsdp-vectors.json, written by the computer's tests. */
class BsdpTest {
    private val vectors: JSONObject by lazy {
        val candidates = listOf("../../tests/data/bsdp-vectors.json", "../tests/data/bsdp-vectors.json",
            "tests/data/bsdp-vectors.json")
        val file = candidates.map { File(it) }.firstOrNull { it.exists() }
            ?: throw AssertionError("bsdp-vectors.json not found from ${File(".").absolutePath}")
        JSONObject(file.readText())
    }

    private fun bytes(key: String): ByteArray = B64.decode(vectors.getString(key))
    private fun hexBytes(key: String): ByteArray {
        val text = vectors.getString(key)
        return ByteArray(text.length / 2) { i -> text.substring(i * 2, i * 2 + 2).toInt(16).toByte() }
    }

    @Test
    fun proofsAndCodesMatchTheComputer() {
        val dev = vectors.getString("device_id")
        assertEquals(vectors.getString("auth_proof"),
            B64.encode(Bsdp.authProof(bytes("token"), bytes("server_nonce"), bytes("client_nonce"), dev)))
        assertEquals(vectors.getString("pair_proof"),
            B64.encode(Bsdp.pairProof(bytes("token"), bytes("server_nonce"), bytes("client_nonce"), dev)))
        assertEquals(vectors.getString("sas"),
            Bsdp.sas(bytes("fingerprint"), bytes("server_nonce"), bytes("client_nonce"), dev))
        assertEquals(vectors.getString("display_id"), Bsdp.displayId(dev))
    }

    @Test
    fun messagesAreByteExact() {
        assertArrayEquals(hexBytes("ping"), Bsdp.token(Bsdp.PING, 0x01020304))
        assertArrayEquals(hexBytes("touch"), Bsdp.touch(Bsdp.TOUCH_MOVE, 513, 260, 123456789L))
        assertArrayEquals(hexBytes("presented"), Bsdp.presented(77, 12, 1))
    }

    @Test
    fun computerMessagesParse() {
        val present = Bsdp.parseAll(hexBytes("present")).single()
        assertEquals(Bsdp.PRESENT, present.kind)
        val body = Bsdp.present(present.payload)
        assertEquals(77L, body.frameId)
        assertEquals(1280, body.canvasW)
        assertEquals(720, body.canvasH)
        val brightness = Bsdp.parseAll(hexBytes("brightness")).single()
        assertEquals(Bsdp.BRIGHTNESS, brightness.kind)
        assertEquals(55, brightness.payload[0].toInt())
        val view = Bsdp.parseAll(hexBytes("json_view")).single().json()
        assertEquals(1080, view.getInt("w"))
        assertEquals(2340, view.getInt("h"))
    }

    @Test
    fun rectanglesDecode() {
        val rect = Bsdp.parseAll(hexBytes("rect_zlib")).single()
        val header = Bsdp.rectHeader(rect.payload)
        assertEquals(Bsdp.FMT_RGB_ZLIB, header.format)
        val pixels = Bsdp.inflateRgb(rect.payload, Bsdp.RECT_HEADER, header.w, header.h)
        val expected = vectors.getJSONArray("rect_zlib_pixels")
        for (i in 0 until expected.length()) {
            val rgb = expected.getJSONArray(i)
            val argb = (0xFF shl 24) or (rgb.getInt(0) shl 16) or (rgb.getInt(1) shl 8) or rgb.getInt(2)
            assertEquals("pixel $i", argb, pixels[i])
        }
        val fill = Bsdp.parseAll(hexBytes("rect_fill")).single()
        val fillHeader = Bsdp.rectHeader(fill.payload)
        assertEquals(Bsdp.FMT_FILL, fillHeader.format)
        assertEquals(8, fillHeader.x)
        assertEquals(48, fillHeader.canvasH)
        assertEquals(0xFF102030.toInt(), Bsdp.fillColor(fill.payload, Bsdp.RECT_HEADER))
    }

    @Test
    fun brokenInputIsRefused() {
        for (bad in listOf("XX0101000000", "425302010000000000")) {
            try {
                Bsdp.parseAll(ByteArray(bad.length / 2) { i -> bad.substring(i * 2, i * 2 + 2).toInt(16).toByte() })
                fail("accepted $bad")
            } catch (expected: java.io.IOException) {
                // bad magic or version
            }
        }
        try {   // a rectangle outside its canvas
            Bsdp.rectHeader(byteArrayOf(0, 100, 0, 0, 0, 10, 0, 10, 0, 64, 0, 64, 0, 0))
            fail("accepted a rectangle outside the canvas")
        } catch (expected: Bsdp.ProtocolException) {
        }
    }

    @Test
    fun base64RoundTrip() {
        for (size in 0..40) {
            val data = ByteArray(size) { (it * 37 + 11).toByte() }
            assertArrayEquals(data, B64.decode(B64.encode(data)))
        }
        assertTrue(B64.encode(byteArrayOf(-1, -2, -3)).none { it == '+' || it == '/' || it == '=' })
    }
}
