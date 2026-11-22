package br.com.biglinux.bigscreen

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.hardware.usb.UsbAccessory
import android.hardware.usb.UsbManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.DisplayMetrics
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import org.json.JSONObject
import java.lang.ref.WeakReference
import kotlin.random.Random

/**
 * The display: the computer's theme over the whole screen. Connects on start,
 * disconnects on stop (no background service, no wake lock: the screen stays
 * on through the window flag only while a session runs), reconnects with
 * backoff and when a network comes back, never shows an old frame as current.
 */
class DisplayActivity : Activity(), SessionListener, DisplayView.Listener {
    private lateinit var store: Store
    private lateinit var display: DisplayView
    private lateinit var overlay: LinearLayout
    private lateinit var overlayTitle: TextView
    private lateinit var overlayText: TextView
    private lateinit var overlayCode: TextView
    private lateinit var overlayProgress: ProgressBar
    private lateinit var overlayButtons: LinearLayout
    private lateinit var menuButton: ImageButton
    private val canvas = FrameCanvas()
    private val handler = Handler(Looper.getMainLooper())
    private var session: Session? = null
    private var target: Target? = null
    private var pairing: Pairing = Pairing.Token
    private var serverId: String? = null
    private var computerName = ""
    private var attempts = 0
    private var started = false
    private var reconnectPending = false
    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private var config = JSONObject()
    private var viewW = 0
    private var viewH = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = Store(this)
        setContentView(build())
        readIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        readIntent(intent)
        if (started) restart()
    }

    override fun onStart() {
        super.onStart()
        started = true
        activeRef = WeakReference(this)
        applyImmersive()
        watchNetwork(true)
        display.post { connect() }
    }

    override fun onStop() {
        super.onStop()
        started = false
        if (activeRef?.get() === this) activeRef = null
        handler.removeCallbacksAndMessages(null)
        watchNetwork(false)
        session?.close("paused")
        session = null
        canvas.clear()
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    override fun onDestroy() {
        super.onDestroy()
        canvas.release()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) applyImmersive()
    }

    // ------------------------------------------------------------ layout
    private fun build(): View {
        val c = this
        val root = FrameLayout(c)
        display = DisplayView(c)
        display.canvas = canvas
        display.listener = this
        root.addView(display, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT))
        overlay = Ui.column(c, 24).apply {
            gravity = Gravity.CENTER_HORIZONTAL
            background = Ui.rounded(c, R.color.overlay, 28)
            // Screen readers read state changes (connecting, code, disconnected) as they happen.
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        overlay.addView(ImageView(c).apply {
            setImageResource(R.drawable.logo)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LinearLayout.LayoutParams(Ui.dp(c, 72), Ui.dp(c, 72)))
        overlayTitle = Ui.text(c, "", 20f, R.color.text, true).apply {
            gravity = Gravity.CENTER
            setTextColor(0xFFF5F5F7.toInt())
            setPadding(0, Ui.dp(c, 12), 0, Ui.dp(c, 4))
        }
        overlayText = Ui.body(c, "").apply {
            gravity = Gravity.CENTER
            setTextColor(0xFFB4B4BC.toInt())
        }
        overlayCode = Ui.text(c, "", 40f, R.color.text, true).apply {
            gravity = Gravity.CENTER
            setTextColor(0xFFF6D32D.toInt())
            letterSpacing = 0.15f
            visibility = View.GONE
        }
        overlayProgress = ProgressBar(c).apply { isIndeterminate = true }
        overlayButtons = LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, Ui.dp(c, 16), 0, 0)
        }
        overlay.addView(overlayTitle)
        overlay.addView(overlayText)
        overlay.addView(overlayCode)
        overlay.addView(overlayProgress, LinearLayout.LayoutParams(Ui.dp(c, 36), Ui.dp(c, 36)).apply {
            topMargin = Ui.dp(c, 16)
        })
        overlay.addView(overlayButtons)
        root.addView(overlay, FrameLayout.LayoutParams(minOf(Ui.dp(c, 460),
            resources.displayMetrics.widthPixels - Ui.dp(c, 32)), FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.CENTER))
        menuButton = ImageButton(c).apply {
            setImageResource(R.drawable.ic_more)
            setColorFilter(0xFFFFFFFF.toInt())
            background = Ui.rounded(c, R.color.overlay, 24)
            contentDescription = getString(R.string.menu_settings_button)
            alpha = 0f
            setOnClickListener { showMenu() }
        }
        root.addView(menuButton, FrameLayout.LayoutParams(Ui.dp(c, 48), Ui.dp(c, 48), Gravity.TOP or Gravity.END)
            .apply { setMargins(0, Ui.dp(c, 16), Ui.dp(c, 16), 0) })
        return root
    }

    private fun showOverlay(title: String, text: String, busy: Boolean, code: String? = null,
                            buttons: List<Pair<String, () -> Unit>> = emptyList()) {
        overlay.visibility = View.VISIBLE
        overlayTitle.text = title
        overlayText.text = text
        overlayText.visibility = if (text.isEmpty()) View.GONE else View.VISIBLE
        overlayProgress.visibility = if (busy) View.VISIBLE else View.GONE
        overlayCode.visibility = if (code == null) View.GONE else View.VISIBLE
        overlayCode.text = code?.let { "${it.take(3)} ${it.drop(3)}" } ?: ""
        overlayCode.contentDescription = code?.toCharArray()?.joinToString(" ") ?: ""
        overlayButtons.removeAllViews()
        for ((label, action) in buttons) {
            overlayButtons.addView(Ui.button(this, label, primary = overlayButtons.childCount == 0) { action() },
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT).apply { setMargins(Ui.dp(this@DisplayActivity, 6), 0,
                    Ui.dp(this@DisplayActivity, 6), 0) })
        }
    }

    private fun hideOverlay() {
        overlay.visibility = View.GONE
    }

    // ------------------------------------------------------------ intents
    private fun readIntent(intent: Intent) {
        val accessory = accessoryOf(intent)
        if (accessory != null) {
            val manager = getSystemService(Context.USB_SERVICE) as UsbManager
            val fd = try { manager.openAccessory(accessory) } catch (error: Exception) { null }
            if (fd != null) {
                target = Target.Accessory(fd)
                pairing = Pairing.Confirm           // auth when paired, otherwise codes on both screens
                computerName = getString(R.string.connect_usb)
                return
            }
        }
        val data: Uri? = intent.data
        if (data != null && data.scheme == "bsmd" && data.host == "pair") {
            val addresses = (data.getQueryParameter("a") ?: "").split(",").map { it.trim() }.filter { it.isNotEmpty() }
            val secret = data.getQueryParameter("s") ?: ""
            val ticket = data.getQueryParameter("t") ?: ""
            serverId = data.getQueryParameter("id")
            computerName = data.getQueryParameter("n") ?: "Linux"
            val port = data.getQueryParameter("p")?.toIntOrNull() ?: DEFAULT_PORT
            val secretBytes = try { B64.decode(secret) } catch (error: IllegalArgumentException) { null }
            if (addresses.isNotEmpty() && ticket.length == 16 && secretBytes != null && secretBytes.size >= 16) {
                target = Target.Network(addresses, port, serverId, data.getQueryParameter("fp"))
                pairing = Pairing.Ticket(ticket, secretBytes)
                return
            }
        }
        val id = intent.getStringExtra(EXTRA_SERVER)
        val known = id?.let { store.computer(it) }
        if (known != null) {
            serverId = known.serverId
            computerName = known.name
            val preferred = intent.getStringExtra(EXTRA_ADDRESS)
            val addresses = (listOfNotNull(preferred) + known.addresses).distinct()
            target = Target.Network(addresses, known.port, known.serverId, known.fingerprint)
            pairing = if (store.token(known.serverId) != null) Pairing.Token else Pairing.Confirm
            return
        }
        val addresses = intent.getStringArrayExtra(EXTRA_ADDRESSES)?.toList()
        if (!addresses.isNullOrEmpty()) {
            serverId = intent.getStringExtra(EXTRA_SERVER_HINT)
            computerName = addresses.first()
            target = Target.Network(addresses, intent.getIntExtra(EXTRA_PORT, DEFAULT_PORT), serverId,
                intent.getStringExtra(EXTRA_FP))
            pairing = Pairing.Confirm
            return
        }
        target = null
    }

    @Suppress("DEPRECATION")
    private fun accessoryOf(intent: Intent): UsbAccessory? =
        if (intent.action == UsbManager.ACTION_USB_ACCESSORY_ATTACHED) intent.getParcelableExtra(UsbManager.EXTRA_ACCESSORY)
        else null

    // ------------------------------------------------------------ session
    private fun connect() {
        if (!started || session != null) return
        val t = target
        if (t == null) {
            showOverlay(getString(R.string.state_disconnected), getString(R.string.choose_computer), false,
                buttons = listOf(getString(R.string.choose_computer) to { goHome() }))
            return
        }
        reconnectPending = false
        viewW = display.width.takeIf { it > 0 } ?: resources.displayMetrics.widthPixels
        viewH = display.height.takeIf { it > 0 } ?: resources.displayMetrics.heightPixels
        showOverlay(getString(R.string.state_connecting, computerName), "", true)
        val s = Session(store, t, pairing, hello(t), canvas, this)
        session = s
        s.start()
    }

    private fun restart() {
        session?.close("closed")
        session = null
        canvas.clear()
        display.invalidate()
        attempts = 0
        connect()
    }

    @Suppress("DEPRECATION")
    private fun hello(t: Target): JSONObject {
        val metrics = DisplayMetrics()
        windowManager.defaultDisplay.getRealMetrics(metrics)
        val version = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: "1"
        } catch (error: PackageManager.NameNotFoundException) {
            "1"
        }
        return JSONObject()
            .put("proto", Bsdp.VERSION).put("device_id", store.deviceId).put("name", store.deviceName)
            .put("model", Build.MODEL ?: "").put("manufacturer", Build.MANUFACTURER ?: "")
            .put("android", Build.VERSION.RELEASE ?: "").put("sdk", Build.VERSION.SDK_INT)
            .put("app_version", version)
            .put("screen", JSONObject().put("w", metrics.widthPixels).put("h", metrics.heightPixels))
            .put("view", JSONObject().put("w", viewW).put("h", viewH))
            .put("density", metrics.densityDpi)
            .put("formats", org.json.JSONArray(Bsdp.FORMATS))
            .put("touch", packageManager.hasSystemFeature(PackageManager.FEATURE_TOUCHSCREEN))
            .put("brightness", true).put("battery", true)
            .put("transport", if (t is Target.Accessory) "usb-accessory" else networkTransport())
    }

    @Suppress("DEPRECATION")
    private fun networkTransport(): String {
        val manager = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val caps = manager.getNetworkCapabilities(manager.activeNetwork) ?: return "other"
            return when {
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
                else -> "other"
            }
        }
        return when (manager.activeNetworkInfo?.type) {
            ConnectivityManager.TYPE_ETHERNET -> "ethernet"
            ConnectivityManager.TYPE_WIFI -> "wifi"
            else -> "other"
        }
    }

    private fun scheduleReconnect() {
        if (!started || reconnectPending) return
        reconnectPending = true
        attempts++
        val delay = longArrayOf(1000, 2000, 4000, 8000, 15000, 30000)[minOf(attempts - 1, 5)]
        showOverlay(getString(R.string.state_reconnecting, attempts), getString(R.string.reason_io), true,
            buttons = listOf(getString(R.string.choose_computer) to { goHome() }))
        handler.postDelayed({ if (reconnectPending) connect() }, delay)
    }

    private fun watchNetwork(on: Boolean) {
        val manager = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        if (on && networkCallback == null) {
            val callback = object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    // A network came back: try now instead of waiting for the backoff.
                    handler.post {
                        if (reconnectPending) {
                            handler.removeCallbacksAndMessages(null)
                            reconnectPending = false
                            connect()
                        }
                    }
                }
            }
            try {
                manager.registerNetworkCallback(NetworkRequest.Builder().build(), callback)
                networkCallback = callback
            } catch (error: Exception) {
                // without ACCESS_NETWORK_STATE on some ROMs: backoff only
            }
        } else if (!on) {
            networkCallback?.let { try { manager.unregisterNetworkCallback(it) } catch (e: Exception) { } }
            networkCallback = null
        }
    }

    // ------------------------------------------------------------ SessionListener (session threads)
    override fun onState(state: String, detail: String) {}

    override fun onPairCode(code: String, seconds: Int) = runOnUiThread {
        showOverlay(getString(R.string.state_pairing), getString(R.string.pair_code_text), true, code)
    }

    override fun onReady(computer: Computer) = runOnUiThread {
        attempts = 0
        serverId = computer.serverId
        computerName = computer.name
        pairing = Pairing.Token
        showOverlay(computer.name, getString(R.string.state_waiting_frame), true)
        if (display.width > 0 && (display.width != viewW || display.height != viewH)) {
            session?.view(display.width, display.height)
        }
    }

    override fun onConfig(config: JSONObject) = runOnUiThread {
        this.config = config
        lastConfig = config
        requestedOrientation = when (config.optString("orientation")) {
            "portrait" -> ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            "reverse_landscape" -> ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE
            "reverse_portrait" -> ActivityInfo.SCREEN_ORIENTATION_REVERSE_PORTRAIT
            "auto" -> ActivityInfo.SCREEN_ORIENTATION_FULL_SENSOR
            else -> ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        }
        if (config.optBoolean("keep_screen_on", true)) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        display.touchEnabled = config.optBoolean("touch", true)
        scheduleBurnIn()
    }

    override fun onFrame() {
        if (overlay.visibility == View.VISIBLE) runOnUiThread { hideOverlay() }
        display.postInvalidate()
    }

    override fun onBrightness(percent: Int) = runOnUiThread {
        if (!store.bool(PREF_BRIGHTNESS, true)) return@runOnUiThread
        val attrs = window.attributes
        attrs.screenBrightness = (percent / 100f).coerceIn(0.02f, 1f)
        window.attributes = attrs
    }

    override fun onClosed(reason: String, message: String, retry: Boolean) = runOnUiThread {
        session = null
        canvas.clear()                     // never keep showing an old frame as if it were current
        display.invalidate()
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (!started) return@runOnUiThread
        val accessory = target is Target.Accessory
        if (accessory && serverId != null) {
            // The cable was pulled: carry on over the network with the same identity.
            store.computer(serverId!!)?.let { known ->
                target = Target.Network(known.addresses, known.port, known.serverId, known.fingerprint)
                pairing = Pairing.Token
            }
        }
        val again = retry && store.bool(MainActivity.PREF_AUTO, true) && target != null && target !is Target.Accessory
        if (again) {
            scheduleReconnect()
            return@runOnUiThread
        }
        val text = reasonText(reason)
        val buttons = ArrayList<Pair<String, () -> Unit>>()
        if (reason in setOf("unknown_device", "revoked", "auth_failed") && target is Target.Network) {
            buttons.add(getString(R.string.pair_again) to { pairing = Pairing.Confirm; attempts = 0; connect() })
        } else if (target != null && reason !in setOf("certificate", "mitm", "other_computer", "disabled")) {
            buttons.add(getString(R.string.retry) to { attempts = 0; connect() })
        }
        buttons.add(getString(R.string.choose_computer) to { goHome() })
        showOverlay(getString(R.string.state_disconnected), text, false, buttons = buttons)
    }

    private fun reasonText(reason: String): String = getString(when (reason) {
        "denied" -> R.string.reason_denied
        "expired" -> R.string.reason_expired
        "auth_failed" -> R.string.reason_auth_failed
        "unknown_device" -> R.string.reason_unknown_device
        "revoked" -> R.string.reason_revoked
        "disabled" -> R.string.reason_disabled
        "replaced" -> R.string.reason_replaced
        "certificate" -> R.string.reason_certificate
        "mitm" -> R.string.reason_mitm
        "other_computer" -> R.string.reason_other_computer
        "protocol" -> R.string.reason_protocol
        "busy" -> R.string.reason_busy
        "rate_limited" -> R.string.reason_rate_limited
        "shutdown" -> R.string.reason_shutdown
        "version" -> R.string.reason_version
        else -> R.string.reason_io
    })

    // ------------------------------------------------------------ DisplayView.Listener (UI thread)
    override fun onTouch(kind: Int, x: Int, y: Int) {
        session?.touch(kind, x, y)
    }

    override fun onViewSize(w: Int, h: Int) {
        if (session != null && (w != viewW || h != viewH)) {
            viewW = w
            viewH = h
            session?.view(w, h)
        }
    }

    override fun onAppMenu() = showMenu()

    override fun onAnyTouch() {
        if (store.bool(PREF_PRESENTATION, false)) return
        menuButton.animate().cancel()
        menuButton.alpha = 0.85f
        menuButton.animate().alpha(0f).setStartDelay(3500).setDuration(600).start()
    }

    // ------------------------------------------------------------ menu, burn-in, immersive
    private fun showMenu() {
        val s = session
        val items = arrayOf(getString(R.string.menu_theme_menu), getString(R.string.menu_prev_theme),
            getString(R.string.menu_next_theme), getString(R.string.settings), getString(R.string.menu_diagnostics),
            getString(R.string.menu_disconnect))
        AlertDialog.Builder(this).setTitle(computerName).setItems(items) { _, which ->
            when (which) {
                0 -> s?.command(JSONObject().put("cmd", "menu"))
                1 -> s?.command(JSONObject().put("cmd", "theme_prev"))
                2 -> s?.command(JSONObject().put("cmd", "theme_next"))
                3 -> startActivity(Intent(this, SettingsActivity::class.java))
                4 -> diagnostics()
                5 -> goHome()
            }
        }.show()
    }

    private fun diagnostics() {
        val s = session
        val stats = s?.stats
        val uptime = if (stats != null && stats.connectedAt > 0) (SystemClock.elapsedRealtime() - stats.connectedAt) / 1000 else 0
        val lines = listOf(
            getString(R.string.diag_computer) to computerName,
            getString(R.string.diag_transport) to (stats?.let { "${it.transport} ${it.address}".trim() } ?: "—"),
            getString(R.string.diag_uptime) to String.format(java.util.Locale.ROOT, "%d:%02d:%02d", uptime / 3600,
                uptime / 60 % 60, uptime % 60),
            getString(R.string.diag_fps) to String.format(java.util.Locale.ROOT, "%.1f", stats?.fps?.value() ?: 0.0),
            getString(R.string.diag_frames) to "${stats?.frames ?: 0} (${stats?.rects ?: 0})",
            getString(R.string.diag_decode) to "${stats?.lastDecodeMs ?: 0} ms",
            getString(R.string.diag_latency) to (stats?.rttMs?.takeIf { it >= 0 }?.let { "$it ms" } ?: "—"),
            getString(R.string.diag_traffic) to String.format(java.util.Locale.ROOT, "%.1f MB",
                (stats?.bytesIn ?: 0L) / 1048576.0),
            getString(R.string.diag_resolution) to "${canvas.width}×${canvas.height} → ${display.width}×${display.height}",
            getString(R.string.diag_last_error) to (stats?.lastError?.takeIf { it.isNotEmpty() } ?: "—"),
            getString(R.string.version, appVersion(), Bsdp.VERSION) to "")
        AlertDialog.Builder(this).setTitle(R.string.menu_diagnostics)
            .setMessage(lines.joinToString("\n") { (k, v) -> if (v.isEmpty()) k else "$k: $v" })
            .setPositiveButton(R.string.close, null).show()
    }

    private fun appVersion(): String = try {
        packageManager.getPackageInfo(packageName, 0).versionName ?: "?"
    } catch (error: PackageManager.NameNotFoundException) {
        "?"
    }

    private val burnIn = object : Runnable {
        override fun run() {
            val max = Ui.dp(this@DisplayActivity, 4)
            display.shiftX = Random.nextInt(-max, max + 1)
            display.shiftY = Random.nextInt(-max, max + 1)
            display.invalidate()
            handler.postDelayed(this, 120_000)
        }
    }

    private fun scheduleBurnIn() {
        handler.removeCallbacks(burnIn)
        if (config.optBoolean("burn_in", true)) {
            handler.postDelayed(burnIn, 120_000)
        } else {
            display.shiftX = 0
            display.shiftY = 0
        }
    }

    @Suppress("DEPRECATION")
    private fun applyImmersive() {
        if (!store.bool(PREF_IMMERSIVE, true)) {
            window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_VISIBLE
            return
        }
        window.decorView.systemUiVisibility = (View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or View.SYSTEM_UI_FLAG_FULLSCREEN
            or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN)
    }

    private fun goHome() {
        session?.close("closed")
        session = null
        startActivity(Intent(this, MainActivity::class.java).putExtra(MainActivity.EXTRA_STAY, true)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP))
        finish()
    }

    companion object {
        const val EXTRA_SERVER = "server_id"
        const val EXTRA_SERVER_HINT = "server_hint"
        const val EXTRA_ADDRESS = "address"
        const val EXTRA_ADDRESSES = "addresses"
        const val EXTRA_PORT = "port"
        const val EXTRA_FP = "fingerprint"
        const val PREF_BRIGHTNESS = "computer_brightness"
        const val PREF_IMMERSIVE = "immersive"
        const val PREF_PRESENTATION = "presentation"

        /** The running display (the settings screen talks to its session); weak: never keeps it alive. */
        @Volatile private var activeRef: WeakReference<DisplayActivity>? = null
        @Volatile var lastConfig: JSONObject? = null

        fun session(): Session? = activeRef?.get()?.session

        fun forComputer(context: Context, serverId: String, address: String? = null): Intent =
            Intent(context, DisplayActivity::class.java).putExtra(EXTRA_SERVER, serverId).also {
                if (address != null) it.putExtra(EXTRA_ADDRESS, address)
            }

        fun forAddress(context: Context, addresses: List<String>, port: Int, serverId: String?,
                       fingerprint: String?): Intent =
            Intent(context, DisplayActivity::class.java).putExtra(EXTRA_ADDRESSES, addresses.toTypedArray())
                .putExtra(EXTRA_PORT, port).putExtra(EXTRA_SERVER_HINT, serverId).putExtra(EXTRA_FP, fingerprint)
    }
}
