package br.com.biglinux.bigscreen

import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.DataInputStream
import java.io.IOException
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.zip.DataFormatException
import java.util.zip.Inflater
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * BSDP (Big Screen Display Protocol) v1 - the app side.
 *
 * Counterpart of usr/share/big-screen-monitor-display/bsmd/displays/android/protocol.py;
 * tests/data/bsdp-vectors.json holds byte-exact vectors both test suites check.
 * Framing: "BS", u8 version, u8 type, u32 payload length (big endian), payload.
 * No Android API here: the JVM unit tests run this file as it is.
 */
object Bsdp {
    const val VERSION = 1
    const val HEADER_SIZE = 8
    const val MAX_PAYLOAD = 8 * 1024 * 1024

    // app -> computer
    const val HELLO = 0x01
    const val AUTH = 0x02
    const val PAIR = 0x03
    const val VIEW = 0x04
    const val PRESENTED = 0x05
    const val TOUCH = 0x06
    const val COMMAND = 0x07
    const val STATS = 0x08

    // both ways
    const val PING = 0x09
    const val PONG = 0x0A
    const val BYE = 0x0B

    // computer -> app
    const val CHALLENGE = 0x41
    const val PAIR_WAIT = 0x42
    const val WELCOME = 0x43
    const val REJECT = 0x44
    const val CONFIG = 0x45
    const val RECT = 0x50
    const val PRESENT = 0x51
    const val BRIGHTNESS = 0x52

    const val FMT_FILL = 0
    const val FMT_RGB_ZLIB = 1
    const val FMT_JPEG = 2
    const val FMT_PNG = 3
    const val FMT_WEBP = 4

    const val TOUCH_DOWN = 1
    const val TOUCH_MOVE = 2
    const val TOUCH_UP = 3
    const val TOUCH_CANCEL = 4

    const val RECT_HEADER = 14
    val FORMATS = listOf("fill", "rgb-zlib", "jpeg", "png", "webp")

    class ProtocolException(message: String) : IOException(message)

    class Message(val kind: Int, val payload: ByteArray) {
        fun json(): JSONObject {
            if (payload.size > 64 * 1024) throw ProtocolException("control message too large")
            return try {
                JSONObject(String(payload, Charsets.UTF_8))
            } catch (error: Exception) {
                throw ProtocolException("invalid JSON")
            }
        }
    }

    // ------------------------------------------------------------ framing
    fun frame(kind: Int, payload: ByteArray = ByteArray(0)): ByteArray {
        val out = ByteBuffer.allocate(HEADER_SIZE + payload.size)
        out.put('B'.code.toByte())
        out.put('S'.code.toByte())
        out.put(VERSION.toByte())
        out.put(kind.toByte())
        out.putInt(payload.size)
        out.put(payload)
        return out.array()
    }

    fun json(kind: Int, obj: JSONObject): ByteArray = frame(kind, obj.toString().toByteArray(Charsets.UTF_8))

    /** Read one message; throws on a broken header (the connection is then closed). */
    fun read(input: DataInputStream, limit: Int = MAX_PAYLOAD): Message {
        val header = ByteArray(HEADER_SIZE)
        input.readFully(header)
        if (header[0] != 'B'.code.toByte() || header[1] != 'S'.code.toByte()) throw ProtocolException("bad magic")
        if (header[2].toInt() != VERSION) throw ProtocolException("unsupported version ${header[2]}")
        val kind = header[3].toInt() and 0xFF
        val length = ByteBuffer.wrap(header, 4, 4).int
        if (length < 0 || length > limit) throw ProtocolException("message too large ($length)")
        val payload = ByteArray(length)
        input.readFully(payload)
        return Message(kind, payload)
    }

    fun parseAll(bytes: ByteArray): List<Message> {
        val input = DataInputStream(ByteArrayInputStream(bytes))
        val out = ArrayList<Message>()
        while (input.available() > 0) out.add(read(input))
        return out
    }

    fun touch(kind: Int, x: Int, y: Int, timeMs: Long, pointer: Int = 0): ByteArray {
        val body = ByteBuffer.allocate(12)
        body.put(kind.toByte())
        body.put(pointer.toByte())
        body.putShort(x.coerceIn(0, 65535).toShort())
        body.putShort(y.coerceIn(0, 65535).toShort())
        body.putShort(0)
        body.putInt((timeMs and 0xFFFFFFFFL).toInt())
        return frame(TOUCH, body.array())
    }

    fun presented(frameId: Long, decodeMs: Int, queued: Int): ByteArray {
        val body = ByteBuffer.allocate(8)
        body.putInt((frameId and 0xFFFFFFFFL).toInt())
        body.putShort(decodeMs.coerceIn(0, 65535).toShort())
        body.putShort(queued.coerceIn(0, 65535).toShort())
        return frame(PRESENTED, body.array())
    }

    fun token(kind: Int, value: Int): ByteArray = frame(kind, ByteBuffer.allocate(4).putInt(value).array())

    fun tokenOf(payload: ByteArray): Int {
        if (payload.size != 4) throw ProtocolException("bad PING/PONG")
        return ByteBuffer.wrap(payload).int
    }

    class RectHeader(val x: Int, val y: Int, val w: Int, val h: Int, val canvasW: Int, val canvasH: Int,
                     val format: Int)

    fun rectHeader(payload: ByteArray): RectHeader {
        if (payload.size < RECT_HEADER) throw ProtocolException("short RECT")
        val b = ByteBuffer.wrap(payload)
        val x = b.short.toInt() and 0xFFFF
        val y = b.short.toInt() and 0xFFFF
        val w = b.short.toInt() and 0xFFFF
        val h = b.short.toInt() and 0xFFFF
        val cw = b.short.toInt() and 0xFFFF
        val ch = b.short.toInt() and 0xFFFF
        val format = b.get().toInt() and 0xFF
        if (w == 0 || h == 0 || x + w > cw || y + h > ch || cw > 8192 || ch > 8192) {
            throw ProtocolException("bad rectangle")
        }
        return RectHeader(x, y, w, h, cw, ch, format)
    }

    class Present(val frameId: Long, val canvasW: Int, val canvasH: Int)

    fun present(payload: ByteArray): Present {
        if (payload.size != 8) throw ProtocolException("bad PRESENT")
        val b = ByteBuffer.wrap(payload)
        return Present(b.int.toLong() and 0xFFFFFFFFL, b.short.toInt() and 0xFFFF, b.short.toInt() and 0xFFFF)
    }

    /** RGB+zlib rectangle -> ARGB pixels. */
    fun inflateRgb(data: ByteArray, offset: Int, w: Int, h: Int, out: IntArray? = null): IntArray {
        val count = w * h
        val raw = ByteArray(count * 3)
        val inflater = Inflater()
        try {
            inflater.setInput(data, offset, data.size - offset)
            var done = 0
            while (done < raw.size) {
                val n = inflater.inflate(raw, done, raw.size - done)
                if (n == 0 && (inflater.finished() || inflater.needsInput())) break
                done += n
            }
            if (done != raw.size) throw ProtocolException("short pixel data")
        } catch (error: DataFormatException) {
            throw ProtocolException("bad pixel data")
        } finally {
            inflater.end()
        }
        val pixels = if (out != null && out.size >= count) out else IntArray(count)
        var j = 0
        for (i in 0 until count) {
            pixels[i] = (0xFF shl 24) or ((raw[j].toInt() and 0xFF) shl 16) or
                ((raw[j + 1].toInt() and 0xFF) shl 8) or (raw[j + 2].toInt() and 0xFF)
            j += 3
        }
        return pixels
    }

    fun fillColor(data: ByteArray, offset: Int): Int {
        if (data.size < offset + 3) throw ProtocolException("short FILL")
        return (0xFF shl 24) or ((data[offset].toInt() and 0xFF) shl 16) or
            ((data[offset + 1].toInt() and 0xFF) shl 8) or (data[offset + 2].toInt() and 0xFF)
    }

    // ------------------------------------------------------------ crypto
    private fun mac(key: ByteArray, label: String, vararg parts: ByteArray): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key, "HmacSHA256"))
        mac.update(label.toByteArray(Charsets.US_ASCII))
        for (part in parts) {
            mac.update(ByteBuffer.allocate(4).putInt(part.size).array())
            mac.update(part)
        }
        return mac.doFinal()
    }

    fun authProof(token: ByteArray, serverNonce: ByteArray, clientNonce: ByteArray, deviceId: String): ByteArray =
        mac(token, "bsmd-auth-v1", serverNonce, clientNonce, deviceId.toByteArray(Charsets.US_ASCII))

    fun pairProof(secret: ByteArray, serverNonce: ByteArray, clientNonce: ByteArray, deviceId: String): ByteArray =
        mac(secret, "bsmd-pair-v1", serverNonce, clientNonce, deviceId.toByteArray(Charsets.US_ASCII))

    fun sha256(vararg parts: ByteArray): ByteArray {
        val digest = MessageDigest.getInstance("SHA-256")
        for (part in parts) digest.update(part)
        return digest.digest()
    }

    /** Six digits shown on both screens when pairing by confirmation (covers the certificate seen). */
    fun sas(fingerprint: ByteArray, serverNonce: ByteArray, clientNonce: ByteArray, deviceId: String): String {
        val d = sha256("bsmd-sas-v1".toByteArray(Charsets.US_ASCII), fingerprint, serverNonce, clientNonce,
            deviceId.toByteArray(Charsets.US_ASCII))
        val value = ((d[0].toLong() and 0xFF) shl 24) or ((d[1].toLong() and 0xFF) shl 16) or
            ((d[2].toLong() and 0xFF) shl 8) or (d[3].toLong() and 0xFF)
        return String.format(java.util.Locale.ROOT, "%06d", value % 1_000_000L)
    }

    fun displayId(deviceId: String): String =
        "android-" + hex(sha256(deviceId.toByteArray(Charsets.US_ASCII))).substring(0, 12)

    fun hex(bytes: ByteArray): String {
        val chars = "0123456789abcdef"
        val out = StringBuilder(bytes.size * 2)
        for (b in bytes) {
            out.append(chars[(b.toInt() shr 4) and 0xF])
            out.append(chars[b.toInt() and 0xF])
        }
        return out.toString()
    }
}

/** Base64url without padding (as the computer writes it); no android.util / java.util.Base64 (API 26). */
object B64 {
    private const val ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

    fun encode(data: ByteArray): String {
        val out = StringBuilder((data.size * 4 + 2) / 3)
        var i = 0
        while (i < data.size) {
            val b0 = data[i].toInt() and 0xFF
            val b1 = if (i + 1 < data.size) data[i + 1].toInt() and 0xFF else 0
            val b2 = if (i + 2 < data.size) data[i + 2].toInt() and 0xFF else 0
            out.append(ALPHABET[b0 shr 2])
            out.append(ALPHABET[((b0 and 0x3) shl 4) or (b1 shr 4)])
            if (i + 1 < data.size) out.append(ALPHABET[((b1 and 0xF) shl 2) or (b2 shr 6)])
            if (i + 2 < data.size) out.append(ALPHABET[b2 and 0x3F])
            i += 3
        }
        return out.toString()
    }

    fun decode(text: String): ByteArray {
        val clean = text.trimEnd('=').replace('+', '-').replace('/', '_')
        val out = java.io.ByteArrayOutputStream(clean.length * 3 / 4)
        var buffer = 0
        var bits = 0
        for (ch in clean) {
            val value = ALPHABET.indexOf(ch)
            if (value < 0) throw IllegalArgumentException("bad base64")
            buffer = (buffer shl 6) or value
            bits += 6
            if (bits >= 8) {
                bits -= 8
                out.write((buffer shr bits) and 0xFF)
            }
        }
        return out.toByteArray()
    }
}
