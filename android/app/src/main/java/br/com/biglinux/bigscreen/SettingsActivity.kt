package br.com.biglinux.bigscreen

import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import org.json.JSONObject

/**
 * Settings. "Appearance", "Screen", "Performance" and "Interaction" belong to
 * this display and are kept on the computer (sent as "set" commands it checks);
 * they can only change while connected. The rest stays on the phone.
 */
class SettingsActivity : Activity() {
    private lateinit var store: Store

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = Store(this)
        title = getString(R.string.settings)
        setContentView(build())
    }

    private fun build(): View {
        val c = this
        val root = Ui.column(c, 20)
        root.addView(Ui.title(c, getString(R.string.settings)))
        val session = DisplayActivity.session()
        val config = DisplayActivity.lastConfig ?: JSONObject()

        section(root, R.string.section_connection) { card ->
            card.addView(Ui.row(c, getString(R.string.device_name), store.deviceName) { rename() })
            card.addView(Ui.switchRow(c, getString(R.string.auto_connect), getString(R.string.auto_connect_sub),
                store.bool(MainActivity.PREF_AUTO, true)) { store.setBool(MainActivity.PREF_AUTO, it) })
        }

        val remote = Ui.column(c)
        remote.addView(Ui.body(c, getString(if (session != null) R.string.sent_to_computer
        else R.string.not_connected_settings)).apply { setPadding(Ui.dp(c, 4), Ui.dp(c, 12), 0, 0) })

        fun send(key: String, value: Any) {
            DisplayActivity.session()?.setting(key, value)
        }

        section(remote, R.string.section_appearance) { card ->
            val orientation = if (config.optString("orientation") == "auto") "auto" else
                when (config.optString("orientation")) {
                    "portrait" -> "vertical"
                    "reverse_landscape" -> "horizontal_flipped"
                    "reverse_portrait" -> "vertical_flipped"
                    else -> "horizontal"
                }
            card.addView(Ui.choiceRow(c, getString(R.string.orientation),
                listOf("auto", "horizontal", "vertical", "horizontal_flipped", "vertical_flipped"),
                listOf(getString(R.string.orientation_auto), getString(R.string.orientation_horizontal),
                    getString(R.string.orientation_vertical), getString(R.string.orientation_horizontal_flipped),
                    getString(R.string.orientation_vertical_flipped)), orientation) { value ->
                if (value == "auto") send("android_auto_rotate", true) else send("orientation", value)
            })
            card.addView(Ui.switchRow(c, getString(R.string.immersive), getString(R.string.immersive_sub),
                store.bool(DisplayActivity.PREF_IMMERSIVE, true)) { store.setBool(DisplayActivity.PREF_IMMERSIVE, it) })
            card.addView(Ui.switchRow(c, getString(R.string.presentation), getString(R.string.presentation_sub),
                store.bool(DisplayActivity.PREF_PRESENTATION, false)) {
                store.setBool(DisplayActivity.PREF_PRESENTATION, it)
            })
        }
        section(remote, R.string.section_screen) { card ->
            card.addView(Ui.switchRow(c, getString(R.string.keep_screen_on), getString(R.string.keep_screen_on_sub),
                config.optBoolean("keep_screen_on", true)) { send("android_keep_screen_on", it) })
            card.addView(Ui.switchRow(c, getString(R.string.burn_in), getString(R.string.burn_in_sub),
                config.optBoolean("burn_in", true)) { send("android_burn_in", it) })
            card.addView(Ui.switchRow(c, getString(R.string.computer_brightness),
                getString(R.string.computer_brightness_sub), store.bool(DisplayActivity.PREF_BRIGHTNESS, true)) {
                store.setBool(DisplayActivity.PREF_BRIGHTNESS, it)
            })
        }
        section(remote, R.string.section_performance) { card ->
            card.addView(Ui.choiceRow(c, getString(R.string.profile), listOf("auto", "economy", "balanced", "fluid"),
                listOf(getString(R.string.profile_auto), getString(R.string.profile_economy),
                    getString(R.string.profile_balanced), getString(R.string.profile_fluid)),
                config.optString("profile", "auto")) { send("performance_profile", it) })
            card.addView(Ui.choiceRow(c, getString(R.string.quality), listOf("auto", "lossless", "balanced", "economy"),
                listOf(getString(R.string.quality_auto), getString(R.string.quality_lossless),
                    getString(R.string.quality_balanced), getString(R.string.quality_economy)),
                config.optString("quality", "auto")) { send("android_quality", it) })
            val sizes = listOf("auto", "native", "1920", "1280", "960", "640")
            card.addView(Ui.choiceRow(c, getString(R.string.resolution), sizes,
                listOf(getString(R.string.resolution_auto), getString(R.string.resolution_native)) +
                    sizes.drop(2).map { getString(R.string.resolution_px, it) },
                config.optString("resolution", "auto")) { send("android_resolution", it) })
        }
        section(remote, R.string.section_interaction) { card ->
            card.addView(Ui.switchRow(c, getString(R.string.touchscreen), getString(R.string.touchscreen_sub),
                config.optBoolean("touch", true)) { send("touch_enabled", it) })
            card.addView(Ui.switchRow(c, getString(R.string.media_controls), getString(R.string.media_controls_sub),
                config.optBoolean("touch_media", true)) { send("touch_media", it) })
        }
        setEnabled(remote, session != null)
        root.addView(remote)

        section(root, R.string.section_system) { card ->
            val version = try {
                packageManager.getPackageInfo(packageName, 0).versionName ?: "?"
            } catch (error: PackageManager.NameNotFoundException) {
                "?"
            }
            card.addView(Ui.row(c, getString(R.string.version, version, Bsdp.VERSION), getString(R.string.license), null))
            card.addView(Ui.row(c, getString(R.string.project), PROJECT_URL) {
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(PROJECT_URL)))
                } catch (error: ActivityNotFoundException) {
                    // no browser
                }
            })
        }
        return Ui.scroll(c, root)
    }

    private fun section(parent: LinearLayout, title: Int, fill: (LinearLayout) -> Unit) {
        parent.addView(Ui.heading(this, getString(title)))
        val card = Ui.card(this).apply { setPadding(0, Ui.dp(context, 4), 0, Ui.dp(context, 4)) }
        fill(card)
        parent.addView(card)
    }

    private fun setEnabled(view: View, enabled: Boolean) {
        view.isEnabled = enabled
        view.alpha = if (enabled) 1f else 0.55f
        if (view is LinearLayout) for (i in 0 until view.childCount) setEnabledChild(view.getChildAt(i), enabled)
    }

    private fun setEnabledChild(view: View, enabled: Boolean) {
        view.isEnabled = enabled
        if (view is LinearLayout) for (i in 0 until view.childCount) setEnabledChild(view.getChildAt(i), enabled)
    }

    private fun rename() {
        val input = EditText(this).apply {
            setText(store.deviceName)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_WORDS
            setSingleLine()
        }
        AlertDialog.Builder(this).setTitle(R.string.device_name)
            .setView(Ui.column(this, 20).apply { addView(input) })
            .setPositiveButton(android.R.string.ok) { _, _ ->
                val name = input.text.toString().trim()
                if (name.isNotEmpty()) {
                    store.deviceName = name
                    recreate()
                }
            }
            .setNegativeButton(android.R.string.cancel, null).show()
    }

    companion object {
        const val PROJECT_URL = "https://github.com/ruscher/big-screen-monitor-display"
    }
}
