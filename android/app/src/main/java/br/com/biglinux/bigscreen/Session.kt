package br.com.biglinux.bigscreen

import android.os.ParcelFileDescriptor
import android.os.SystemClock
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.Closeable
import java.io.DataInputStream
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket
import java.security.MessageDigest
import java.security.cert.X509Certificate
import java.util.concurrent.LinkedBlockingDeque
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket
import javax.net.ssl.X509TrustManager

/** How to reach the computer. */
sealed class Target {
    /** Network (Wi-Fi, Ethernet, USB tethering, adb reverse on 127.0.0.1). */
    class Network(val addresses: List<String>, val port: Int, val serverId: String?, val fingerprint: String?) : Target()

    /** USB accessory (Android Open Accessory): the cable is the channel, no TLS. */
    class Accessory(val fd: ParcelFileDescriptor) : Target()
}

/** How to prove who we are. */
sealed class Pairing {
    object Token : Pairing()                                       // already paired: challenge-response
    class Ticket(val ticket: String, val secret: ByteArray) : Pairing()   // QR code
    object Confirm : Pairing()                                     // code shown on both screens
}

interface SessionListener {
    fun onState(state: String, detail: String)
    fun onPairCode(code: String, seconds: Int)
    fun onReady(computer: Computer)
    fun onConfig(config: JSONObject)
    fun onFrame()
    fun onBrightness(percent: Int)
    /** ``retry``: worth reconnecting automatically. */
    fun onClosed(reason: String, message: String, retry: Boolean)
}

/** Diagnostics shown on the phone. */
class SessionStats {
    @Volatile var connectedAt = 0L
    @Volatile var frames = 0L
    @Volatile var rects = 0L
    @Volatile var bytesIn = 0L
    @Volatile var lastDecodeMs = 0
    @Volatile var rttMs = -1
    @Volatile var transport = ""
    @Volatile var address = ""
    @Volatile var lastError = ""
    val fps = FpsMeter()
}

class FpsMeter {
    private val times = LongArray(64)
    private var count = 0
    private var head = 0

    @Synchronized fun tick(now: Long = SystemClock.elapsedRealtime()) {
        times[head] = now
        head = (head + 1) % times.size
        if (count < times.size) count++
    }

    @Synchronized fun value(now: Long = SystemClock.elapsedRealtime()): Double {
        var n = 0
        var oldest = now
        for (i in 0 until count) {
            val t = times[i]
            if (now - t <= 5000) {
                n++
                if (t < oldest) oldest = t
            }
        }
        return if (n < 2 || now == oldest) 0.0 else (n - 1) * 1000.0 / (now - oldest)
    }
}

/**
 * One connection to a computer, in its own thread. Writes go through a queue
 * drained by a writer thread (never the UI thread); the reader decodes
 * rectangles into [canvas] and acknowledges each PRESENT.
 */
class Session(
    private val store: Store,
    private val target: Target,
    private val pairing: Pairing,
    private val hello: JSONObject,
    private val canvas: FrameCanvas,
    private val listener: SessionListener,
) {
    val stats = SessionStats()
    @Volatile private var closed = false
    @Volatile private var lastRx = 0L
    @Volatile private var socket: Closeable? = null
    @Volatile private var output: OutputStream? = null
    private val queue = LinkedBlockingDeque<ByteArray>(256)
    private var reader: Thread? = null
    private var writer: Thread? = null
    private var pinger: Thread? = null
    private val clientNonce = SecureBox.nonce(24)
    private var certFingerprint = ByteArray(0)
    private var pingSent = 0L
    private var pingToken = 0

    fun start() {
        reader = Thread({ runSession() }, "bsmd-session").also { it.start() }
    }

    /** Ends the session (BYE when possible). Safe on the UI thread: the network part runs elsewhere. */
    fun close(reason: String = "closed") {
        if (closed) return
        closed = true
        val out = output
        val sock = socket
        writer?.interrupt()
        pinger?.interrupt()
        Thread({
            try {
                if (out != null) {
                    synchronized(out) {
                        out.write(Bsdp.json(Bsdp.BYE, JSONObject().put("reason", reason)))
                        out.flush()
                    }
                }
            } catch (error: Exception) {
                // already gone
            }
            try {
                sock?.close()
            } catch (error: Exception) {
                // already closed
            }
        }, "bsmd-close").start()
    }

    // ------------------------------------------------------------ sending (any thread)
    fun send(data: ByteArray, droppable: Boolean = false) {
        if (closed) return
        if (droppable && queue.size > 64) return            // a flood of moves: keep the newest only
        queue.offer(data)
    }

    fun touch(kind: Int, x: Int, y: Int) = send(Bsdp.touch(kind, x, y, SystemClock.uptimeMillis()),
        droppable = kind == Bsdp.TOUCH_MOVE)

    fun view(w: Int, h: Int) = send(Bsdp.json(Bsdp.VIEW, JSONObject().put("w", w).put("h", h)))

    fun command(obj: JSONObject) = send(Bsdp.json(Bsdp.COMMAND, obj))

    fun setting(key: String, value: Any) = command(JSONObject().put("cmd", "set").put("key", key).put("value", value))

    fun sendStats(extra: JSONObject) = send(Bsdp.json(Bsdp.STATS, extra))

    // ------------------------------------------------------------ session thread
    private fun runSession() {
        var reason = "io"
        var message = ""
        var retry = true
        try {
            listener.onState("connecting", "")
            val (input, out) = open()
            output = out
            val data = DataInputStream(BufferedInputStream(input, 65536))
            val computer = handshake(data, out) ?: return
            stats.connectedAt = SystemClock.elapsedRealtime()
            startWriter(out)
            startPinger()
            listener.onReady(computer)
            loop(data)
        } catch (rejected: Rejected) {
            reason = rejected.reason
            message = rejected.detail
            retry = rejected.reason in setOf("busy", "rate_limited", "shutdown", "closed", "paused")
        } catch (error: Bsdp.ProtocolException) {
            reason = "protocol"
            message = error.message ?: ""
            retry = false
        } catch (error: CertificateChanged) {
            reason = "certificate"
            message = error.message ?: ""
            retry = false
        } catch (error: IOException) {
            reason = if (closed) "closed" else "io"
            message = error.message ?: error.javaClass.simpleName
        } catch (error: Exception) {
            reason = "error"
            message = error.toString()
        } finally {
            stats.lastError = if (reason == "closed") "" else "$reason $message".trim()
            val wasClosed = closed
            close(reason)
            if (!wasClosed) listener.onClosed(reason, message, retry)
        }
    }

    private class Rejected(val reason: String, val detail: String) : Exception(reason)
    private class CertificateChanged(message: String) : Exception(message)

    private fun open(): Pair<InputStream, OutputStream> {
        val accessory = target as? Target.Accessory
        if (accessory != null) {
            stats.transport = "usb-accessory"
            stats.address = "USB"
            val fd = accessory.fd.fileDescriptor
            socket = accessory.fd
            return Pair(FileInputStream(fd), BufferedOutputStream(FileOutputStream(fd), 65536))
        }
        val network = target as Target.Network
        var last: IOException? = null
        for (address in network.addresses) {
            if (closed) throw IOException("closed")
            try {
                return connect(address, network)
            } catch (error: IOException) {
                last = error
            }
        }
        throw last ?: IOException("no address")
    }

    private fun connect(address: String, target: Target.Network): Pair<InputStream, OutputStream> {
        val raw = Socket()
        socket = raw
        raw.connect(InetSocketAddress(address, target.port), 4000)
        raw.tcpNoDelay = true
        raw.keepAlive = true
        val trust = PinningTrustManager()
        val context = SSLContext.getInstance("TLS")
        context.init(null, arrayOf(trust), null)
        val ssl = context.socketFactory.createSocket(raw, address, target.port, true) as SSLSocket
        socket = ssl
        val wanted = ssl.supportedProtocols.filter { it == "TLSv1.2" || it == "TLSv1.3" }
        if (wanted.isNotEmpty()) ssl.enabledProtocols = wanted.toTypedArray()
        ssl.soTimeout = 30000
        ssl.startHandshake()
        val fp = trust.fingerprint ?: throw IOException("no certificate")
        val pinned = target.fingerprint?.takeIf { it.isNotEmpty() }
        if (pinned != null && B64.encode(fp) != pinned) {
            ssl.close()
            throw CertificateChanged("the computer's certificate changed")
        }
        certFingerprint = fp
        stats.address = address
        stats.transport = when {
            address == "127.0.0.1" -> "usb-adb"
            isTetherInterface(raw) -> "usb-tether"
            else -> hello.optString("transport", "wifi")
        }
        return Pair(ssl.inputStream, BufferedOutputStream(ssl.outputStream, 65536))
    }

    private fun isTetherInterface(raw: Socket): Boolean = try {
        val name = NetworkInterface.getByInetAddress(raw.localAddress)?.name ?: ""
        name.startsWith("rndis") || name.startsWith("ncm") || name.startsWith("usb")
    } catch (error: Exception) {
        false
    }

    private fun write(out: OutputStream, data: ByteArray) {
        synchronized(out) {
            out.write(data)
            out.flush()
        }
    }

    private fun handshake(input: DataInputStream, out: OutputStream): Computer? {
        hello.put("transport", stats.transport)
        hello.put("nonce", B64.encode(clientNonce))
        write(out, Bsdp.json(Bsdp.HELLO, hello))
        val challenge = expect(input, Bsdp.CHALLENGE).json()
        val serverId = challenge.optString("server_id")
        val net = target as? Target.Network
        val expectedId = net?.serverId
        if (!expectedId.isNullOrEmpty() && expectedId != serverId) {
            throw Rejected("other_computer", "a different computer answered at this address")
        }
        val serverNonce = B64.decode(challenge.optString("nonce"))
        val deviceId = hello.getString("device_id")
        val token = store.token(serverId)
        val need = challenge.optString("need")
        when {
            need == "auth" && token != null && pairing !is Pairing.Ticket -> write(out, Bsdp.json(Bsdp.AUTH,
                JSONObject().put("proof", B64.encode(Bsdp.authProof(token, serverNonce, clientNonce, deviceId)))))
            pairing is Pairing.Ticket -> write(out, Bsdp.json(Bsdp.PAIR, JSONObject().put("method", "ticket")
                .put("ticket", pairing.ticket)
                .put("proof", B64.encode(Bsdp.pairProof(pairing.secret, serverNonce, clientNonce, deviceId)))))
            pairing is Pairing.Confirm || need == "pair" && pairing !is Pairing.Token || token == null -> {
                if (pairing is Pairing.Token && need == "pair") {
                    throw Rejected("unknown_device", "this phone is no longer paired with the computer")
                }
                write(out, Bsdp.json(Bsdp.PAIR, JSONObject().put("method", "confirm")))
                val wait = expect(input, Bsdp.PAIR_WAIT).json()
                val expected = Bsdp.sas(certFingerprint, serverNonce, clientNonce, deviceId)
                if (wait.optString("code") != expected) {
                    // Another certificate was in the way: never pair through it.
                    throw Rejected("mitm", "the codes do not match")
                }
                listener.onPairCode(expected, wait.optInt("timeout", 120))
            }
            else -> throw Rejected("unknown_device", "this phone is no longer paired with the computer")
        }
        val welcome = expect(input, Bsdp.WELCOME, waitMs = 130000).json()
        val newToken = welcome.optString("token")
        if (newToken.isNotEmpty()) store.setToken(serverId, B64.decode(newToken))
        val known = store.computer(serverId)
        val addresses = LinkedHashSet<String>()
        if (stats.address.isNotEmpty() && stats.address != "USB") addresses.add(stats.address)
        known?.addresses?.let { addresses.addAll(it) }
        net?.addresses?.let { addresses.addAll(it) }
        val computer = Computer(serverId, challenge.optString("name", "Linux").take(40),
            if (certFingerprint.isNotEmpty()) B64.encode(certFingerprint) else known?.fingerprint ?: "",
            addresses.filter { it != "127.0.0.1" }.take(6), net?.port ?: known?.port ?: DEFAULT_PORT,
            System.currentTimeMillis(), stats.transport, welcome.optString("display_id"))
        store.save(computer)
        store.lastServer = serverId
        return computer
    }

    private fun expect(input: DataInputStream, kind: Int, waitMs: Int = 15000): Bsdp.Message {
        val deadline = SystemClock.elapsedRealtime() + waitMs
        while (true) {
            val msg = Bsdp.read(input, 64 * 1024)
            when (msg.kind) {
                kind -> return msg
                Bsdp.REJECT -> {
                    val body = msg.json()
                    throw Rejected(body.optString("reason", "denied"), body.optString("message"))
                }
                Bsdp.PING -> output?.let { write(it, Bsdp.token(Bsdp.PONG, Bsdp.tokenOf(msg.payload))) }
                Bsdp.BYE -> throw Rejected(msg.json().optString("reason", "closed"), "")
                else -> throw Bsdp.ProtocolException("unexpected message ${msg.kind} during the handshake")
            }
            if (SystemClock.elapsedRealtime() > deadline) throw IOException("handshake timed out")
        }
    }

    private fun loop(input: DataInputStream) {
        while (!closed) {
            val msg = Bsdp.read(input)
            lastRx = SystemClock.elapsedRealtime()
            stats.bytesIn += msg.payload.size + Bsdp.HEADER_SIZE
            when (msg.kind) {
                Bsdp.RECT -> {
                    canvas.apply(msg.payload)
                    stats.rects++
                }
                Bsdp.PRESENT -> {
                    val present = Bsdp.present(msg.payload)
                    val decodeMs = canvas.present()
                    stats.lastDecodeMs = decodeMs
                    stats.frames++
                    stats.fps.tick()
                    send(Bsdp.presented(present.frameId, decodeMs, 0))
                    listener.onFrame()
                }
                Bsdp.CONFIG -> listener.onConfig(msg.json())
                Bsdp.BRIGHTNESS -> if (msg.payload.isNotEmpty()) listener.onBrightness(msg.payload[0].toInt() and 0xFF)
                Bsdp.PING -> send(Bsdp.token(Bsdp.PONG, Bsdp.tokenOf(msg.payload)))
                Bsdp.PONG -> if (Bsdp.tokenOf(msg.payload) == pingToken) {
                    stats.rttMs = (SystemClock.elapsedRealtime() - pingSent).toInt()
                }
                Bsdp.BYE -> {
                    val why = try { msg.json().optString("reason", "closed") } catch (e: Exception) { "closed" }
                    throw Rejected(why, "")
                }
                else -> { }       // newer messages from a newer computer: ignored
            }
        }
    }

    private fun startWriter(out: OutputStream) {
        writer = Thread({
            try {
                while (!closed) {
                    val data = queue.poll(1, TimeUnit.SECONDS) ?: continue
                    write(out, data)
                }
            } catch (error: InterruptedException) {
                // closing
            } catch (error: IOException) {
                try { socket?.close() } catch (e: Exception) { }
            }
        }, "bsmd-writer").also { it.start() }
    }

    /** PING every 5 s of silence; 20 s without anything from the computer ends the session. */
    private fun startPinger() {
        lastRx = SystemClock.elapsedRealtime()
        pinger = Thread({
            try {
                while (!closed) {
                    Thread.sleep(5000)
                    val now = SystemClock.elapsedRealtime()
                    if (now - lastRx > 20000) {
                        try { socket?.close() } catch (e: Exception) { }
                        break
                    }
                    pingToken = (now and 0x7FFFFFFF).toInt()
                    pingSent = now
                    send(Bsdp.token(Bsdp.PING, pingToken))
                    sendStats(JSONObject().put("fps", stats.fps.value()).put("decode_ms", stats.lastDecodeMs)
                        .put("uptime_s", (now - stats.connectedAt) / 1000))
                }
            } catch (error: InterruptedException) {
                // closing
            }
        }, "bsmd-ping").also { it.start() }
    }
}

/** Accepts the computer's self-signed certificate and keeps its fingerprint; the session pins it. */
class PinningTrustManager : X509TrustManager {
    @Volatile var fingerprint: ByteArray? = null

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        throw java.security.cert.CertificateException("no client certificates")
    }

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        val leaf = chain?.firstOrNull() ?: throw java.security.cert.CertificateException("no certificate")
        fingerprint = MessageDigest.getInstance("SHA-256").digest(leaf.encoded)
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
}
