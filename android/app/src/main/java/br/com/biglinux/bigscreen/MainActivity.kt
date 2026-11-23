package br.com.biglinux.bigscreen

import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Bundle
import android.provider.MediaStore
import android.text.InputType
import android.text.format.DateUtils
import android.view.Gravity
import android.view.View
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView

/** Home: how to connect, the computers this phone knows and the ones on the network. */
class MainActivity : Activity() {
    private lateinit var store: Store
    private lateinit var knownBox: LinearLayout
    private lateinit var foundBox: LinearLayout
    private lateinit var foundStatus: TextView
    private lateinit var foundProgress: ProgressBar
    private var scanning = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = Store(this)
        val stay = intent.getBooleanExtra(EXTRA_STAY, false)
        val last = store.lastServer
        if (savedInstanceState == null && !stay && last.isNotEmpty() && store.bool(PREF_AUTO, true) &&
            store.computer(last) != null) {
            startActivity(DisplayActivity.forComputer(this, last))
        }
        setContentView(build())
    }

    override fun onResume() {
        super.onResume()
        fillKnown()
        scan()
    }

    private fun build(): View {
        val c = this
        val root = Ui.column(c, 20)
        val header = LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(ImageView(c).apply {
                setImageResource(R.drawable.logo)
                importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            }, LinearLayout.LayoutParams(Ui.dp(c, 64), Ui.dp(c, 64)))
            addView(Ui.column(c).apply {
                setPadding(Ui.dp(c, 16), 0, 0, 0)
                addView(Ui.text(c, getString(R.string.app_name), 22f, R.color.text, true))
                addView(Ui.body(c, getString(R.string.tagline)))
            }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        }
        root.addView(header)
        root.addView(Ui.heading(c, getString(R.string.how_connect)))
        val cards = listOf(
            Ui.actionCard(c, R.drawable.ic_wifi, getString(R.string.connect_network),
                getString(R.string.connect_network_sub)) { scan() },
            Ui.actionCard(c, R.drawable.ic_usb, getString(R.string.connect_usb),
                getString(R.string.connect_usb_sub)) { info(R.string.usb_title, R.string.usb_text) },
            Ui.actionCard(c, R.drawable.ic_qr, getString(R.string.scan_qr), getString(R.string.scan_qr_sub)) { qr() },
            Ui.actionCard(c, R.drawable.ic_add, getString(R.string.add_manual),
                getString(R.string.add_manual_sub)) { manual() })
        for (card in cards) root.addView(Ui.margins(card, c, bottom = 10))

        knownBox = Ui.column(c)
        root.addView(knownBox)

        root.addView(Ui.heading(c, getString(R.string.found_computers)))
        val status = LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(Ui.dp(c, 4), 0, 0, Ui.dp(c, 8))
        }
        foundProgress = ProgressBar(c, null, android.R.attr.progressBarStyleSmall)
        foundStatus = Ui.body(c, "")
        status.addView(foundProgress)
        status.addView(foundStatus, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
            leftMargin = Ui.dp(c, 12)
        })
        root.addView(status)
        foundBox = Ui.card(c).apply { setPadding(0, Ui.dp(c, 4), 0, Ui.dp(c, 4)) }
        root.addView(foundBox)
        root.addView(Ui.margins(Ui.button(c, getString(R.string.search_again), primary = false) { scan() }, c, top = 12))

        val footer = LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, Ui.dp(c, 24), 0, Ui.dp(c, 8))
        }
        footer.addView(Ui.button(c, getString(R.string.settings), primary = false) {
            startActivity(Intent(c, SettingsActivity::class.java))
        })
        footer.addView(Ui.spacer(c, 1).apply { layoutParams = LinearLayout.LayoutParams(Ui.dp(c, 12), 1) })
        footer.addView(Ui.button(c, getString(R.string.help), primary = false) { info(R.string.help, R.string.help_text) })
        root.addView(footer)
        return Ui.scroll(c, root)
    }

    private fun fillKnown() {
        knownBox.removeAllViews()
        val computers = store.computers()
        if (computers.isEmpty()) return
        knownBox.addView(Ui.heading(this, getString(R.string.known_computers)))
        val card = Ui.card(this).apply { setPadding(0, Ui.dp(context, 4), 0, Ui.dp(context, 4)) }
        for (computer in computers) {
            val seen = if (computer.lastSeen > 0) getString(R.string.last_seen,
                DateUtils.getRelativeTimeSpanString(computer.lastSeen)) else ""
            val row = Ui.row(this, computer.name, listOf(seen, transportLabel(computer.lastTransport))
                .filter { it.isNotEmpty() }.joinToString(" · ")) {
                startActivity(DisplayActivity.forComputer(this, computer.serverId))
            }
            row.setOnLongClickListener {
                AlertDialog.Builder(this)
                    .setMessage(getString(R.string.forget_confirm, computer.name))
                    .setPositiveButton(R.string.forget) { _, _ ->
                        store.forget(computer.serverId)
                        fillKnown()
                    }
                    .setNegativeButton(android.R.string.cancel, null).show()
                true
            }
            card.addView(row)
        }
        knownBox.addView(card)
    }

    private fun scan() {
        if (scanning) return
        scanning = true
        foundProgress.visibility = View.VISIBLE
        foundStatus.text = getString(R.string.searching)
        val known = store.computers()
        Thread({
            val found = try {
                Discovery.scan(known)
            } catch (error: Exception) {
                emptyList()
            }
            runOnUiThread { showFound(found) }
        }, "bsmd-discovery").start()
    }

    private fun showFound(found: List<Found>) {
        scanning = false
        if (isFinishing) return
        foundProgress.visibility = View.GONE
        foundBox.removeAllViews()
        foundStatus.text = if (found.isEmpty()) getString(R.string.none_found) else ""
        foundBox.visibility = if (found.isEmpty()) View.GONE else View.VISIBLE
        for (item in found) {
            val known = store.computer(item.serverId)
            val subtitle = listOf(item.address,
                getString(if (item.pairingOpen) R.string.pairing_open else R.string.available)).joinToString(" · ")
            foundBox.addView(Ui.row(this, item.name, subtitle) {
                startActivity(if (known != null && store.token(item.serverId) != null)
                    DisplayActivity.forComputer(this, item.serverId, item.address)
                else DisplayActivity.forAddress(this, listOf(item.address), item.port, item.serverId, null))
            })
        }
    }

    private fun info(title: Int, text: Int) {
        AlertDialog.Builder(this).setTitle(title).setMessage(text).setPositiveButton(R.string.close, null).show()
    }

    private fun qr() {
        AlertDialog.Builder(this).setTitle(R.string.qr_title).setMessage(R.string.qr_text)
            .setPositiveButton(R.string.open_camera) { _, _ ->
                try {
                    startActivity(Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA))
                } catch (error: ActivityNotFoundException) {
                    // no camera app
                }
            }
            .setNegativeButton(R.string.close, null).show()
    }

    private fun manual() {
        val input = EditText(this).apply {
            hint = getString(R.string.manual_hint)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine()
        }
        val box = Ui.column(this, 20).apply { addView(input) }
        AlertDialog.Builder(this).setTitle(R.string.manual_title).setView(box)
            .setPositiveButton(R.string.connect) { _, _ ->
                val text = input.text.toString().trim()
                val host = text.substringBefore(':')
                val port = text.substringAfter(':', "").toIntOrNull() ?: DEFAULT_PORT
                if (host.isEmpty() || host.any { it.isWhitespace() } || port !in 1..65535) {
                    info(R.string.manual_title, R.string.manual_invalid)
                } else {
                    startActivity(DisplayActivity.forAddress(this, listOf(host), port, null, null))
                }
            }
            .setNegativeButton(android.R.string.cancel, null).show()
    }

    private fun transportLabel(transport: String): String = when {
        transport.startsWith("usb") -> getString(R.string.connect_usb)
        transport == "vpn" -> getString(R.string.transport_vpn)
        transport.isEmpty() -> ""
        else -> getString(R.string.connect_network)
    }

    companion object {
        const val EXTRA_STAY = "stay"
        const val PREF_AUTO = "auto_connect"
    }
}
